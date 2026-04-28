"""
KMV-E8: Cognition OS ↔ Memory Vault Bridge

Publishes memory events and enriched entities to the Cognition OS concept graph.
Supports read-everything / write-back pattern with a generic multi-agent topology:

    SuperRoot (org)
      └── MemoryVault (domain)
           ├── Project nodes (workspace isolation)
           │    └── Agent nodes (namespace containers)
           │         └── Fact / Episode nodes (memories)
           └── Shared Entity Pool (deduped, cross-agent)
                ├── Concept / Person / Organisation nodes

Toggled via COGNITION_OS_URL env var.  Disabled when empty.
Gracefully degrades — logs and skips when Cognition OS unreachable.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

# ── Entity type mapping: KMV enrichment → Cognition OS NodeType ──────────
_ENTITY_TYPE_MAP: dict[str, str] = {
    "PERSON": "Person",
    "ORGANIZATION": "Organisation",
    "LOCATION": "Concept",
    "CONCEPT": "Concept",
    "TECHNOLOGY": "Feature",
    "EVENT": "Episode",
    "DATE": "Fact",
    "PRODUCT": "Application",
}

# ── Relationship type mapping: KMV → Cognition OS RelationshipType ───────
_REL_TYPE_MAP: dict[str, str] = {
    "HAS_ENTITY": "EXTRACTED_FROM",     # reversed direction in CogOS
    "CO_OCCURS_WITH": "CO_OCCURS_WITH",
    "TAGGED_WITH": "RELATED_TO",
}

# ── Memory content_type → NodeType ───────────────────────────────────────
_CONTENT_TYPE_NODE_MAP: dict[str, str] = {
    "fact": "Fact",
    "preference": "Fact",
    "text": "Episode",
    "conversation": "Episode",
    "structured": "Concept",
    "embedding": "Concept",
}


class CognitionBridge:
    """
    Async HTTP bridge to the Cognition OS concept graph.

    Thread-safe.  One instance per application (singleton via settings).
    """

    def __init__(
        self,
        base_url: str = "",
        auth_token: str = "",
        org_id: str = "",
        timeout: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/") if base_url else ""
        self._auth_token = auth_token
        # P3 #19: ``org_id`` here is now a fallback for unauthenticated /
        # background-task callers (e.g. periodic consolidation worker).
        # The primary source is the active TenantScope ContextVar at
        # request time, read in ``_request``. Keeping this constructor
        # arg for one minor version of compat with callers passing it
        # explicitly; remove in v0.3.
        self._fallback_org_id = org_id
        self._timeout = timeout

        # Circuit breaker state
        self._consecutive_failures: int = 0
        self._circuit_open_until: float = 0.0
        self._max_failures: int = 5
        self._cooldown_seconds: float = 60.0

        self._client: httpx.AsyncClient | None = None

    # ── Properties ────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        """True when a Cognition OS URL is configured."""
        return bool(self._base_url)

    @property
    def circuit_open(self) -> bool:
        """True when circuit breaker has tripped."""
        if self._consecutive_failures >= self._max_failures:
            if time.monotonic() < self._circuit_open_until:
                return True
            # Cooldown expired — allow a probe request
            self._consecutive_failures = 0
        return False

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def _get_client(self) -> httpx.AsyncClient:
        # P3 #19: only static headers (auth token) baked at client creation.
        # The X-Org-Id header is dynamic per-request (see _request).
        if self._client is None or self._client.is_closed:
            headers: dict[str, str] = {}
            if self._auth_token:
                headers["Authorization"] = f"Bearer {self._auth_token}"
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers=headers,
                timeout=self._timeout,
            )
        return self._client

    def _resolve_org_id(self) -> str:
        """Return the org_id to send on this request.

        Priority:
          1. Active TenantScope ContextVar (the request's actual org).
          2. Constructor fallback (for background tasks running outside
             a request scope, e.g. periodic consolidation).
        Returns "" if neither is set — callers see no X-Org-Id header.
        """
        # Lazy import: tenancy → auth → settings cycles otherwise.
        from backend.core.tenancy import current_org_id
        return current_org_id() or self._fallback_org_id

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ── Internal request helper ───────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Fire an HTTP request.  Returns parsed JSON or None on failure."""
        if not self.enabled:
            return None
        if self.circuit_open:
            logger.debug("cognition_bridge.circuit_open", path=path)
            return None

        client = await self._get_client()
        try:
            # P3 #19: per-request X-Org-Id from the active TenantScope.
            # Pass via the request's headers kwarg so the client's static
            # headers (auth) are merged with the dynamic per-request one.
            request_headers: dict[str, str] = {}
            org_id = self._resolve_org_id()
            if org_id:
                request_headers["X-Org-Id"] = org_id
            resp = await client.request(method, path, json=json, headers=request_headers)
            resp.raise_for_status()
            self._consecutive_failures = 0
            return resp.json() if resp.content else {}
        except (httpx.HTTPError, Exception) as exc:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._max_failures:
                self._circuit_open_until = time.monotonic() + self._cooldown_seconds
                logger.warning(
                    "cognition_bridge.circuit_tripped",
                    failures=self._consecutive_failures,
                    cooldown_s=self._cooldown_seconds,
                )
            logger.warning("cognition_bridge.request_failed", path=path, error=str(exc))
            return None

    # ── S8.1: Write-Through Hook ──────────────────────────────────────

    async def publish_memory_event(
        self,
        memory_id: str,
        content: str,
        namespace: str,
        user_id: str,
        content_type: str = "text",
        source_agent: str = "",
        project: str = "",
    ) -> str | None:
        """
        Publish a new memory as a graph node in Cognition OS.

        Creates (or merges):
        1. MemoryVault domain root (once)
        2. Project node under domain root
        3. Agent namespace node under project
        4. Memory node (Fact/Episode) under agent namespace
        """
        if not self.enabled:
            return None

        node_type = _CONTENT_TYPE_NODE_MAP.get(content_type, "Episode")
        # Truncate content for node description (graph descriptions should be short)
        description = content[:500] if len(content) > 500 else content
        name = f"memory:{memory_id[:8]}"

        result = await self._request("POST", "/v1/graphs/nodes", json={
            "name": name,
            "node_type": node_type,
            "description": description,
            "graph_type": "concept",
            "metadata": {
                "memory_id": memory_id,
                "namespace": namespace,
                "user_id": user_id,
                "content_type": content_type,
                "source_agent": source_agent,
                "project": project or namespace,
                "source": "kemory",
            },
        })

        if result and "id" in result:
            node_id = result["id"]
            logger.info(
                "cognition_bridge.memory_published",
                memory_id=memory_id,
                node_id=node_id,
                node_type=node_type,
            )
            return node_id
        return None

    # ── S8.2: Enrichment-to-Concept-Graph Bridge ──────────────────────

    async def upsert_entities(
        self,
        memory_id: str,
        entities: list[dict[str, Any]],
        relationships: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Upsert enriched entities and relationships into the concept graph.

        Entities go into the shared pool (deduped by name+type via MERGE).
        Returns summary of created/merged counts.
        """
        if not self.enabled:
            return {"created_nodes": 0, "created_rels": 0}

        created_nodes = 0
        node_id_map: dict[str, str] = {}  # entity_id → cognition node_id

        # Create entity nodes
        for entity in entities:
            entity_type = entity.get("entity_type", "CONCEPT")
            node_type = _ENTITY_TYPE_MAP.get(entity_type, "Concept")
            entity_name = entity.get("name", "unknown")
            entity_id = entity.get("entity_id", str(uuid.uuid4()))

            result = await self._request("POST", "/v1/graphs/nodes", json={
                "name": entity_name,
                "node_type": node_type,
                "description": entity.get("context", ""),
                "graph_type": "concept",
                "metadata": {
                    "confidence": entity.get("confidence", 1.0),
                    "source_memory_id": memory_id,
                    "kmv_entity_id": entity_id,
                    "source": "kemory",
                },
            })

            if result and "id" in result:
                node_id_map[entity_id] = result["id"]
                created_nodes += 1

        # Create relationships
        created_rels = 0
        for rel in relationships:
            rel_type_kmv = rel.get("relationship_type", "RELATED_TO")
            rel_type = _REL_TYPE_MAP.get(rel_type_kmv, "RELATED_TO")

            source_id = node_id_map.get(
                rel.get("source_entity", ""),
                rel.get("source_entity", ""),
            )
            target_id = node_id_map.get(
                rel.get("target_entity", ""),
                rel.get("target_entity", ""),
            )

            if source_id and target_id:
                result = await self._request("POST", "/v1/graphs/relationships", json={
                    "source_id": source_id,
                    "target_id": target_id,
                    "rel_type": rel_type,
                })
                if result:
                    created_rels += 1

        # Batch index into Weaviate for vector search
        if node_id_map:
            batch_entities = []
            for entity in entities:
                eid = entity.get("entity_id", "")
                cog_id = node_id_map.get(eid)
                if cog_id:
                    batch_entities.append({
                        "entity_id": cog_id,
                        "name": entity.get("name", ""),
                        "description": entity.get("context", ""),
                        "node_type": _ENTITY_TYPE_MAP.get(
                            entity.get("entity_type", "CONCEPT"), "Concept"
                        ),
                    })
            if batch_entities:
                await self._request("POST", "/v1/concepts/vectors/batch", json={
                    "entities": batch_entities,
                })

        summary = {"created_nodes": created_nodes, "created_rels": created_rels}
        logger.info("cognition_bridge.entities_upserted", memory_id=memory_id, **summary)
        return summary

    # ── S8.3: Graph-Augmented Recall ──────────────────────────────────

    async def expand_recall(
        self,
        query: str,
        org_id: str = "",
        top_k: int = 5,
        min_score: float = 0.3,
    ) -> list[dict[str, Any]]:
        """
        Expand a recall query via the Cognition OS unified search.

        Returns related concepts/entities that may not appear in
        the local memory vault but exist in the broader knowledge graph.
        """
        if not self.enabled:
            return []

        result = await self._request("POST", "/v1/search", json={
            "query": query,
            "top_k": top_k,
            "filters": {"min_score": min_score},
        })

        if not result or "results" not in result:
            return []

        return [
            {
                "entity_id": r.get("entity_id", ""),
                "title": r.get("title", ""),
                "content": r.get("content", ""),
                "score": r.get("score", 0.0),
                "source": "cognition_os",
            }
            for r in result["results"]
        ]

    async def get_neighbours(
        self,
        node_id: str,
    ) -> list[dict[str, Any]]:
        """Get neighbouring nodes from the concept graph."""
        if not self.enabled:
            return []

        result = await self._request("GET", f"/v1/graphs/nodes/{node_id}/neighbours")
        return result if isinstance(result, list) else []


# ── Singleton ─────────────────────────────────────────────────────────────

_bridge: CognitionBridge | None = None


def get_cognition_bridge() -> CognitionBridge:
    """Get or create the singleton CognitionBridge instance."""
    global _bridge
    if _bridge is None:
        from backend.config.settings import settings
        _bridge = CognitionBridge(
            base_url=getattr(settings, "cognition_os_url", ""),
            auth_token=getattr(settings, "cognition_os_auth_token", ""),
            org_id=getattr(settings, "cognition_os_org_id", ""),
        )
    return _bridge
