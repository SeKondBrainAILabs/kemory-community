"""
Kemory — lightweight namespace resolver for direct artifact uploads (v3.35.0).

The full :func:`backend.services.ai_chat_service._resolve_namespace` runs the
namespace matcher (vector search, SUGGEST/REUSE/AUTO_REDIRECT) and is designed
for the chat-upsert flow.  For direct artifact uploads we need a simpler path:

  1. Explicit ``namespace`` string provided → use it as-is.
  2. ``platform`` + ``source_project_id`` / ``source_project_name`` →
     consult :class:`~backend.models.ai_chat.ChatNamespaceMapping`; if a row
     fires, return its ``target_namespace``.
  3. ``platform`` + ``source_project_name`` → derive a slug namespace
     ``kora:{platform}:{slug}``.
  4. ``platform`` only → return the per-platform inbox ``kora:inbox:{platform}``.
  5. Neither → ``"shared"``.

No matcher calls, no SUGGEST errors — just a deterministic lookup/derivation.
The caller decides whether to store the resolved namespace or to fall back to
the memory's own namespace (for memory-attached artifacts).
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _slugify(name: str) -> str:
    """Convert a project name to a URL-friendly slug."""
    name = name.lower().strip()
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[\s_]+", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name or "unnamed"


async def lookup_namespace_mapping(
    user_id: uuid.UUID,
    platform: str,
    source_project_id: str | None,
    source_project_name: str | None,
    db: AsyncSession,
) -> str | None:
    """Return the ``target_namespace`` from a matching ChatNamespaceMapping row, or None.

    Uses the same precedence as the chat-upsert path:
      1. Exact (platform, source_project_id) match.
      2. Platform + case-insensitive substring match on source_project_name_pattern.
    """
    from backend.models.ai_chat import ChatNamespaceMapping

    if source_project_id:
        row = (
            await db.execute(
                select(ChatNamespaceMapping)
                .where(
                    ChatNamespaceMapping.user_id == user_id,
                    ChatNamespaceMapping.enabled.is_(True),
                    ChatNamespaceMapping.platform == platform,
                    ChatNamespaceMapping.source_project_id == source_project_id,
                )
                .order_by(
                    ChatNamespaceMapping.priority.asc(),
                    ChatNamespaceMapping.created_at.asc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is not None:
            return row.target_namespace

    if source_project_name:
        patterns = (
            await db.execute(
                select(ChatNamespaceMapping)
                .where(
                    ChatNamespaceMapping.user_id == user_id,
                    ChatNamespaceMapping.enabled.is_(True),
                    ChatNamespaceMapping.platform == platform,
                    ChatNamespaceMapping.source_project_id.is_(None),
                    ChatNamespaceMapping.source_project_name_pattern.is_not(None),
                )
                .order_by(
                    ChatNamespaceMapping.priority.asc(),
                    ChatNamespaceMapping.created_at.asc(),
                )
            )
        ).scalars().all()
        needle = source_project_name.lower()
        for m in patterns:
            pat = (m.source_project_name_pattern or "").lower()
            if pat and pat in needle:
                return m.target_namespace

    return None


async def resolve_artifact_namespace(
    *,
    user_id: uuid.UUID,
    namespace: str | None,
    platform: str | None,
    source_project_id: str | None,
    source_project_name: str | None,
    db: AsyncSession,
) -> str:
    """Return the effective namespace for a direct artifact upload.

    Resolution order:
      1. Explicit ``namespace`` string → return as-is.
      2. ``platform`` provided → try ChatNamespaceMapping lookup.
         If a mapping fires → return ``target_namespace``.
      3. Derive from platform + project name: ``kora:{plat}:{slug}``.
      4. Platform-only inbox: ``kora:inbox:{plat}``.
      5. Fallback: ``"shared"``.
    """
    # 1. Explicit namespace wins.
    if namespace:
        return namespace.strip()

    # 2–4. Require at least a platform.
    if not platform:
        return "shared"

    plat = platform.lower()

    # 2. ChatNamespaceMapping lookup.
    mapping_ns = await lookup_namespace_mapping(
        user_id=user_id,
        platform=plat,
        source_project_id=source_project_id,
        source_project_name=source_project_name,
        db=db,
    )
    if mapping_ns:
        return mapping_ns

    # 3. Derive from project name slug.
    if source_project_name:
        return f"kora:{plat}:{_slugify(source_project_name)}"

    # 4. Platform inbox.
    return f"kora:inbox:{plat}"
