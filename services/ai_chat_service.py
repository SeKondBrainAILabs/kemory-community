"""
Kemory — AI Chats service (chats-v1).

REST-shaped layer for the AI Chats module. Consumers are the FastAPI
route handlers in ``backend/api/routes/ai_chats.py`` and
``backend/api/routes/chat_mappings.py``. Pydantic request/response models
live in this file (matching the convention in ``memory_service.py``).

Three responsibilities:
  1. **Idempotent upsert** by ``(user_id, platform, platform_conversation_id)``
     for chats, and by ``(chat_id, source_turn_id)`` for turns. Re-pushes
     are no-ops when ``content_hash`` matches.
  2. **Namespace resolution.** Precedence is mapping-table override →
     :func:`backend.services.namespace_matcher.resolve_namespace` →
     derived default (``kora:<platform>:<slug>``). The matcher path
     reuses the EXACT same logic memories use, so chats and memories
     share one namespace world.
  3. **Tenancy & auth boundary.** ``org_id`` is always read from the
     caller's ``AuthContext`` (set by the API key path) — never from
     request headers. The global tenancy filter (registered in
     ``backend/core/tenancy.py``) scopes every SELECT to the caller's
     org automatically.

What this file does NOT do (out of scope for v1):
  * Memory extraction. The forward-compat ``source_chat_id`` /
    ``source_turn_id`` columns on ``kemory_memories`` exist so phase 2
    can wire ``compression_pipeline`` into this path without a migration.
  * Object storage for binary artifacts. Inline ``content`` only.
  * MCP tools (``s9nmem_store_chat`` etc.) — phase 2.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.ai_chat import (
    AIChat,
    AIChatArtifact,
    AIChatTurn,
    ChatNamespaceMapping,
)
from backend.services.namespace_matcher import (
    RelatedNamespaceConflict,
    ResolutionAction,
    apply_resolution,
    resolve_namespace,
)

logger = structlog.get_logger(__name__)

# ── Limits ────────────────────────────────────────────────────────
MAX_ARTIFACT_INLINE_BYTES = 1_048_576  # 1 MB
MAX_TURNS_PER_BATCH = 500

VALID_PLATFORMS = {"chatgpt", "claude", "gemini", "manus", "other"}
VALID_ROLES = {"user", "assistant", "system", "tool"}
# audio + video added in v3.33.0 — extension uploads now route through
# the minio-backed POST /chats/{id}/artifacts/upload endpoint and store
# their object key in artifact_metadata.storage_key. Inline content for
# audio/video isn't practically useful (>1MB cap kicks in immediately)
# so the dashboard treats those types as content_url-only.
VALID_ARTIFACT_TYPES = {
    "code", "image", "file", "react", "html", "svg", "audio", "video",
}


# ─── Request / Response schemas ─────────────────────────────────────


class ArtifactUpsert(BaseModel):
    """A single artifact attached to a turn."""

    artifact_type: str = Field(..., max_length=32)
    language: str | None = Field(None, max_length=50)
    content: str | None = Field(
        None,
        description="Inline content for text-shaped artifacts. Capped at 1 MB.",
    )
    content_url: str | None = Field(
        None,
        max_length=1000,
        description="Reserved for object storage. Leave NULL in v1.",
    )
    artifact_metadata: dict[str, Any] | None = None


class TurnUpsert(BaseModel):
    """A single message turn within a chat.

    ``source_turn_id`` is highly recommended: when set, it makes the
    upsert idempotent so the extension can re-push a chat as it grows
    without bookkeeping its own internal id space.
    """

    source_turn_id: str | None = Field(None, max_length=255)
    parent_turn_id: uuid.UUID | None = None
    role: str = Field(..., max_length=20)
    content: str = Field(..., min_length=0)
    content_html: str | None = None
    thinking_content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    turn_metadata: dict[str, Any] | None = None
    sequence: int = Field(..., ge=0)
    artifacts: list[ArtifactUpsert] = Field(default_factory=list)


class ChatUpsert(BaseModel):
    """Idempotent upsert payload for a captured chat.

    Either send the full conversation as ``turns`` on this call, or push
    the chat first and then append turns via ``POST /api/v1/chats/{chat_id}/turns:batch``.
    """

    platform: str = Field(..., max_length=32, description="chatgpt | claude | gemini | manus | other")
    platform_conversation_id: str = Field(..., max_length=255)
    source_project_id: str | None = Field(None, max_length=255)
    source_project_name: str | None = Field(None, max_length=500)
    namespace: str | None = Field(
        None,
        max_length=100,
        description=(
            "Caller-suggested namespace. If omitted, derived from "
            "source_project_name (or platform-default). Mapping table wins "
            "over both; matcher applies after that."
        ),
    )
    namespace_description: str | None = Field(None, max_length=500)
    title: str | None = Field(None, max_length=500)
    model: str | None = Field(None, max_length=100)
    captured_at: datetime | None = None
    installation_id: uuid.UUID | None = None
    chat_metadata: dict[str, Any] | None = None
    turns: list[TurnUpsert] = Field(default_factory=list)
    allow_duplicate: bool = Field(
        default=False,
        description=(
            "Skip the namespace matcher 409 path — accept the caller's "
            "namespace as-is even when it looks similar to an existing one."
        ),
    )


class ArtifactResponse(BaseModel):
    artifact_id: str
    # Nullable since v3.35.0 — None for namespace/memory artifacts.
    turn_id: str | None
    chat_id: str | None
    namespace: str | None
    artifact_type: str
    language: str | None
    content: str | None
    content_url: str | None
    content_sha256: str
    artifact_metadata: dict[str, Any] | None
    # Convenience fields extracted from artifact_metadata (populated on read).
    filename: str | None = None
    size_bytes: int | None = None
    created_at: str


class TurnResponse(BaseModel):
    turn_id: str
    chat_id: str
    source_turn_id: str | None
    parent_turn_id: str | None
    role: str
    content: str
    content_html: str | None
    thinking_content: str | None
    tool_calls: list[dict[str, Any]] | None
    turn_metadata: dict[str, Any] | None
    sequence: int
    created_at: str
    artifacts: list[ArtifactResponse] = Field(default_factory=list)


class ChatResponse(BaseModel):
    chat_id: str
    user_id: str
    platform: str
    platform_conversation_id: str
    source_project_id: str | None
    source_project_name: str | None
    namespace: str
    requested_namespace: str | None
    title: str | None
    model: str | None
    chat_metadata: dict[str, Any] | None
    content_hash: str
    captured_at: str | None
    source_type: str
    installation_id: str | None
    created_at: str
    updated_at: str
    turn_count: int = 0
    # Audit fields for the upsert response — lets the extension distinguish
    # "we created a new row" from "noop because hash matched" from "we
    # appended N turns to an existing chat".
    was_created: bool = False
    was_updated: bool = False
    turns: list[TurnResponse] | None = None


class ChatListItem(BaseModel):
    chat_id: str
    platform: str
    platform_conversation_id: str
    namespace: str
    title: str | None
    captured_at: str | None
    updated_at: str
    turn_count: int
    artifact_count: int = 0


class ChatListResponse(BaseModel):
    items: list[ChatListItem]
    total: int
    limit: int
    offset: int


# ─── Mapping CRUD schemas ───────────────────────────────────────────


class ChatMappingCreate(BaseModel):
    platform: str = Field(..., max_length=32)
    source_project_id: str | None = Field(None, max_length=255)
    source_project_name_pattern: str | None = Field(None, max_length=500)
    target_namespace: str = Field(..., max_length=100)
    priority: int = Field(default=100, ge=0, le=10_000)
    enabled: bool = True


class ChatMappingUpdate(BaseModel):
    target_namespace: str | None = Field(None, max_length=100)
    priority: int | None = Field(None, ge=0, le=10_000)
    enabled: bool | None = None
    source_project_id: str | None = Field(None, max_length=255)
    source_project_name_pattern: str | None = Field(None, max_length=500)


class ChatMappingResponse(BaseModel):
    mapping_id: str
    platform: str
    source_project_id: str | None
    source_project_name_pattern: str | None
    target_namespace: str
    priority: int
    enabled: bool
    created_at: str
    updated_at: str


# ─── Helpers ─────────────────────────────────────────────────────────


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return slug[:60] or "untitled"


def _canonical_turn_dict(turn: TurnUpsert) -> dict[str, Any]:
    """Deterministic dict for hashing — sorted keys, no None noise."""
    return {
        "source_turn_id": turn.source_turn_id,
        "role": turn.role,
        "content": turn.content,
        "thinking_content": turn.thinking_content,
        "tool_calls": turn.tool_calls,
        "sequence": turn.sequence,
        "artifacts": [
            {
                "type": a.artifact_type,
                "language": a.language,
                "content": a.content,
                "content_url": a.content_url,
            }
            for a in turn.artifacts
        ],
    }


def _content_hash(payload: ChatUpsert) -> str:
    """SHA-256 over a deterministic projection of the chat payload.

    Stable across re-pushes when nothing changed; flips when any turn,
    artifact, role, or sequence position differs. Title / model /
    captured_at deliberately don't contribute — those drift harmlessly
    from chat-tool updates and would force noop writes otherwise.
    """
    import json

    canonical = {
        "platform": payload.platform,
        "platform_conversation_id": payload.platform_conversation_id,
        "turns": [_canonical_turn_dict(t) for t in payload.turns],
    }
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _artifact_sha256(artifact: ArtifactUpsert) -> str:
    payload = (artifact.content or "") + "|" + (artifact.content_url or "")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_payload(payload: ChatUpsert) -> None:
    if payload.platform.lower() not in VALID_PLATFORMS:
        raise ValueError(
            f"Invalid platform '{payload.platform}'. Valid: {sorted(VALID_PLATFORMS)}"
        )
    if len(payload.turns) > MAX_TURNS_PER_BATCH:
        raise ValueError(
            f"Too many turns in one upsert ({len(payload.turns)} > {MAX_TURNS_PER_BATCH}). "
            f"Use POST /api/v1/chats/{{chat_id}}/turns:batch to append in chunks."
        )
    for t in payload.turns:
        _validate_turn(t)


def _validate_turn(turn: TurnUpsert) -> None:
    if turn.role not in VALID_ROLES:
        raise ValueError(f"Invalid role '{turn.role}'. Valid: {sorted(VALID_ROLES)}")
    for art in turn.artifacts:
        _validate_artifact(art)


def _validate_artifact(art: ArtifactUpsert) -> None:
    if art.artifact_type not in VALID_ARTIFACT_TYPES:
        raise ValueError(
            f"Invalid artifact_type '{art.artifact_type}'. Valid: {sorted(VALID_ARTIFACT_TYPES)}"
        )
    if art.content is None and not art.content_url:
        raise ValueError("Artifact must have either inline content or content_url.")
    if art.content and len(art.content.encode("utf-8")) > MAX_ARTIFACT_INLINE_BYTES:
        raise ValueError(
            f"Artifact inline content exceeds {MAX_ARTIFACT_INLINE_BYTES} bytes. "
            "Use content_url with object storage (reserved for v1.1)."
        )


# ─── Namespace resolution ───────────────────────────────────────────


async def _lookup_mapping(
    user_id: uuid.UUID,
    platform: str,
    source_project_id: str | None,
    source_project_name: str | None,
    db: AsyncSession,
) -> ChatNamespaceMapping | None:
    """Return the highest-priority enabled mapping for this (platform, project)
    or None when no mapping fires.

    Precedence (within a user's mappings):
      1. Exact ``(platform, source_project_id)`` match.
      2. ``platform`` + case-insensitive substring on ``source_project_name_pattern``.
      Lower ``priority`` value evaluated first; ties broken by ``created_at``.
    """
    if source_project_id:
        exact = (
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
        if exact is not None:
            return exact

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
                return m
    return None


# chats-v1 inbox: when no explicit namespace and no mapping fires, new
# chats land in a per-platform inbox so they're easy to triage. The
# extension typically can't pick a meaningful namespace at capture time,
# so a flat per-platform bucket (`kora:claude`, `kora:chatgpt`) hides
# everything in one pile. The inbox marker `kora:inbox:<platform>`
# tells the dashboard "show in the Inbox tab" and the classifier
# "skip yourself as a destination". When a project name IS known
# (ChatGPT Project / Claude Project) we still derive a content-aware
# default `kora:<platform>:<slug>` because there's a clear human intent.
INBOX_PREFIX = "kora:inbox:"


def is_inbox_namespace(namespace: str | None) -> bool:
    """True when the namespace is one of the per-platform inboxes."""
    return bool(namespace and namespace.startswith(INBOX_PREFIX))


def _derive_default_namespace(
    platform: str,
    source_project_name: str | None,
) -> str:
    """Fall-back when no caller namespace and no mapping fires.

    Examples:
      ('claude', 'Steady Quill') → 'kora:claude:steady-quill'  (project known)
      ('chatgpt', None)          → 'kora:inbox:chatgpt'        (inbox)
    """
    plat = platform.lower()
    if source_project_name:
        return f"kora:{plat}:{_slugify(source_project_name)}"
    return f"{INBOX_PREFIX}{plat}"


async def _resolve_namespace(
    user_id: uuid.UUID,
    payload: ChatUpsert,
    db: AsyncSession,
) -> tuple[str, str | None]:
    """Return (resolved_namespace, requested_namespace_or_None).

    The second element is set when the matcher AUTO_REDIRECTed away from
    what the caller supplied — the chat row records it so the extension
    UI can show "you said X, we stored under Y."
    """
    # 1) Mapping override always wins.
    mapping = await _lookup_mapping(
        user_id,
        payload.platform.lower(),
        payload.source_project_id,
        payload.source_project_name,
        db,
    )
    if mapping is not None:
        requested = payload.namespace
        if requested and requested != mapping.target_namespace:
            return mapping.target_namespace, requested
        return mapping.target_namespace, None

    # 2) Caller-supplied namespace runs through the shared matcher.
    candidate = payload.namespace or _derive_default_namespace(
        payload.platform,
        payload.source_project_name,
    )

    if payload.allow_duplicate:
        return candidate, None

    try:
        resolution = await resolve_namespace(
            user_id,
            candidate,
            payload.namespace_description,
            db,
        )
    except Exception as exc:
        # Matcher is best-effort — fall back to candidate on encoder outage.
        logger.debug("ai_chat_service.matcher_skipped", reason=str(exc))
        return candidate, None

    if resolution.action == ResolutionAction.SUGGEST:
        raise RelatedNamespaceConflict(candidate, resolution.candidates)

    if resolution.action in (ResolutionAction.REUSE, ResolutionAction.AUTO_REDIRECT):
        await apply_resolution(resolution, payload.namespace_description, db, user_id)
        if (
            resolution.action == ResolutionAction.AUTO_REDIRECT
            and resolution.namespace != candidate
        ):
            return resolution.namespace, candidate
        return resolution.namespace, None

    # CREATE_NEW — caller's name stands.
    await apply_resolution(resolution, payload.namespace_description, db, user_id)
    return resolution.namespace, None


# ─── Persistence ────────────────────────────────────────────────────


async def _persist_turns(
    chat: AIChat,
    turns: list[TurnUpsert],
    db: AsyncSession,
) -> int:
    """Insert/upsert ``turns`` under ``chat``. Returns count inserted.

    Idempotency: when a turn carries a ``source_turn_id`` and a row with
    the same ``(chat_id, source_turn_id)`` already exists, the existing
    row is updated in place. Turns without a ``source_turn_id`` are
    always appended (the extension is expected to supply it).
    """
    if not turns:
        return 0

    inserted = 0
    for turn in turns:
        existing: AIChatTurn | None = None
        if turn.source_turn_id:
            existing = (
                await db.execute(
                    select(AIChatTurn).where(
                        AIChatTurn.chat_id == chat.chat_id,
                        AIChatTurn.source_turn_id == turn.source_turn_id,
                    )
                )
            ).scalar_one_or_none()

        if existing is not None:
            existing.role = turn.role
            existing.content = turn.content
            existing.content_html = turn.content_html
            existing.thinking_content = turn.thinking_content
            existing.tool_calls = turn.tool_calls
            existing.turn_metadata = turn.turn_metadata
            existing.sequence = turn.sequence
            existing.parent_turn_id = turn.parent_turn_id
            # Replace artifacts on the turn — simpler and matches the
            # source-of-truth semantic the extension expects (the latest
            # push of a turn replaces any prior artifact list for it).
            await _replace_artifacts_for_turn(existing, turn.artifacts, db)
            continue

        new_turn = AIChatTurn(
            chat_id=chat.chat_id,
            user_id=chat.user_id,
            org_id=chat.org_id,
            source_turn_id=turn.source_turn_id,
            parent_turn_id=turn.parent_turn_id,
            role=turn.role,
            content=turn.content,
            content_html=turn.content_html,
            thinking_content=turn.thinking_content,
            tool_calls=turn.tool_calls,
            turn_metadata=turn.turn_metadata,
            sequence=turn.sequence,
        )
        db.add(new_turn)
        await db.flush()
        if turn.artifacts:
            for art in turn.artifacts:
                _attach_artifact(new_turn, art, db)
        inserted += 1

    return inserted


def _attach_artifact(turn: AIChatTurn, art: ArtifactUpsert, db: AsyncSession) -> None:
    db.add(
        AIChatArtifact(
            turn_id=turn.turn_id,
            chat_id=turn.chat_id,
            user_id=turn.user_id,
            org_id=turn.org_id,
            artifact_type=art.artifact_type,
            language=art.language,
            content=art.content,
            content_url=art.content_url,
            content_sha256=_artifact_sha256(art),
            artifact_metadata=art.artifact_metadata,
        )
    )


async def _replace_artifacts_for_turn(
    turn: AIChatTurn,
    artifacts: list[ArtifactUpsert],
    db: AsyncSession,
) -> None:
    # Drop existing artifact rows for this turn; insert the new set.
    # Cheap because per-turn artifact counts are small (typically 0–3).
    existing = (
        await db.execute(select(AIChatArtifact).where(AIChatArtifact.turn_id == turn.turn_id))
    ).scalars().all()
    for row in existing:
        await db.delete(row)
    for art in artifacts:
        _attach_artifact(turn, art, db)


# ─── Public service API ────────────────────────────────────────────


async def upsert_chat(
    user_id: uuid.UUID,
    org_id: str,
    payload: ChatUpsert,
    db: AsyncSession,
    installation_id: uuid.UUID | None = None,
) -> ChatResponse:
    """Idempotent chat upsert.

    Cases:
      * No existing row → INSERT chat + turns. ``was_created=True``.
      * Existing row, same content_hash → noop (no row touched).
        ``was_created=False``, ``was_updated=False``.
      * Existing row, different content_hash → UPDATE chat + upsert turns.
        ``was_updated=True``.

    Raises :class:`backend.services.namespace_matcher.RelatedNamespaceConflict`
    when the namespace matcher wants a 409 (caller can retry with
    ``allow_duplicate=true``). The route handler maps this to 409.
    """
    _validate_payload(payload)

    namespace, requested_namespace = await _resolve_namespace(user_id, payload, db)

    # Match on the unique constraint (user, platform, conv id).
    existing = (
        await db.execute(
            select(AIChat).where(
                AIChat.user_id == user_id,
                AIChat.platform == payload.platform.lower(),
                AIChat.platform_conversation_id == payload.platform_conversation_id,
                AIChat.invalid_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    new_hash = _content_hash(payload)
    now = datetime.now(UTC)

    if existing is None:
        chat = AIChat(
            user_id=user_id,
            org_id=org_id,
            platform=payload.platform.lower(),
            platform_conversation_id=payload.platform_conversation_id,
            source_project_id=payload.source_project_id,
            source_project_name=payload.source_project_name,
            namespace=namespace,
            requested_namespace=requested_namespace,
            title=payload.title,
            model=payload.model,
            chat_metadata=payload.chat_metadata,
            content_hash=new_hash,
            captured_at=payload.captured_at,
            source_type="extension" if installation_id else "extension",
            installation_id=installation_id,
        )
        db.add(chat)
        await db.flush()
        await _persist_turns(chat, payload.turns, db)
        await db.flush()
        turn_count = await _count_turns(chat.chat_id, db)
        # chats-v1 auto-classify: fire-and-forget background task that
        # re-evaluates the namespace once the chat has accumulated enough
        # content. Extension keeps pushing by (platform, conv_id), unaware
        # — we silently redirect to the right namespace under the hood.
        _schedule_auto_classify_safe(chat.chat_id, user_id)
        return _to_response(
            chat,
            turn_count=turn_count,
            was_created=True,
            was_updated=False,
            turns=None,
        )

    # Existing row — noop fast path.
    if existing.content_hash == new_hash:
        turn_count = await _count_turns(existing.chat_id, db)
        return _to_response(
            existing,
            turn_count=turn_count,
            was_created=False,
            was_updated=False,
            turns=None,
        )

    # Existing row, content changed — update chat metadata + upsert turns.
    #
    # chats-v1 inbox invariant: once the user (or a future classifier)
    # moves a chat out of `kora:inbox:*`, subsequent extension upserts
    # must NOT silently snap it back to inbox. The extension typically
    # doesn't send an explicit `namespace` on its periodic re-pushes
    # (debounced sync of the live conversation), so without this guard
    # `_resolve_namespace` recomputes the default and overwrites the
    # user's deliberate destination on the next 6-second debounce.
    #
    # Rule: preserve the existing namespace when (a) the caller didn't
    # explicitly supply one in this payload AND no mapping fires (the
    # default-derivation branch took effect), AND (b) the existing chat
    # already lives somewhere other than the per-platform inbox. If the
    # caller is explicit OR a mapping is matching, honour the new
    # destination — that's still a user-driven intent signal.
    caller_was_explicit = bool(payload.namespace) or bool(payload.source_project_id) or bool(
        payload.source_project_name
    )
    if (
        not caller_was_explicit
        and not is_inbox_namespace(existing.namespace)
        and namespace != existing.namespace
    ):
        logger.debug(
            "ai_chat_service.preserve_user_namespace",
            chat_id=str(existing.chat_id),
            kept=existing.namespace,
            would_have_been=namespace,
        )
        namespace = existing.namespace
        # Don't surface a "requested vs resolved" diff on a preserved row —
        # the caller didn't ask for anything different.
        requested_namespace = existing.requested_namespace

    existing.namespace = namespace
    existing.requested_namespace = requested_namespace
    existing.source_project_id = payload.source_project_id
    existing.source_project_name = payload.source_project_name
    existing.title = payload.title
    existing.model = payload.model
    existing.chat_metadata = payload.chat_metadata
    existing.captured_at = payload.captured_at
    existing.content_hash = new_hash
    existing.updated_at = now
    if installation_id is not None:
        existing.installation_id = installation_id

    await _persist_turns(existing, payload.turns, db)
    await db.flush()
    turn_count = await _count_turns(existing.chat_id, db)
    # Fire auto-classify again on every content-changing update — the
    # chat may have just crossed the AUTO_MIN_TURNS / AUTO_MIN_CHARS
    # gates with this push. No-op when the chat is no longer pending.
    _schedule_auto_classify_safe(existing.chat_id, user_id)
    return _to_response(
        existing,
        turn_count=turn_count,
        was_created=False,
        was_updated=True,
        turns=None,
    )


def _schedule_auto_classify_safe(chat_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Lazy-import wrapper. Keeps chat_classifier off the import path
    when ai_chat_service is loaded but auto-classify isn't wanted (tests
    mocking it out, etc.). Swallows any scheduling error — auto-classify
    is advisory and must never break the write path."""
    try:
        from backend.services.chat_classifier import schedule_auto_classify

        schedule_auto_classify(chat_id, user_id)
    except Exception as exc:
        logger.debug("ai_chat_service.auto_classify_schedule_failed", reason=str(exc))


async def move_chat(
    chat_id: uuid.UUID,
    user_id: uuid.UUID,
    new_namespace: str,
    db: AsyncSession,
    allow_duplicate: bool = False,
) -> ChatResponse:
    """Move an existing chat to a different namespace.

    The new namespace runs through :func:`namespace_matcher.resolve_namespace`
    just like memory writes, so a typo auto-redirects to the existing
    namespace and a too-close-but-not-matching name raises a 409. Pass
    ``allow_duplicate=True`` to bypass the matcher and write as-is.

    Updating the namespace also clears ``requested_namespace`` (the
    legacy "matcher redirected" marker) because the move IS the new
    intent. The chat's content / turns / content_hash are untouched.
    """
    if not new_namespace or not new_namespace.strip():
        raise ValueError("namespace must be a non-empty string")
    target = new_namespace.strip()

    chat = await _get_chat_for_user(chat_id, user_id, db)
    resolved = target
    if not allow_duplicate:
        try:
            from backend.services.namespace_matcher import (
                RelatedNamespaceConflict,
                ResolutionAction,
                apply_resolution,
                resolve_namespace,
            )

            resolution = await resolve_namespace(user_id, target, None, db)
            if resolution.action == ResolutionAction.SUGGEST:
                raise RelatedNamespaceConflict(target, resolution.candidates)
            await apply_resolution(resolution, None, db, user_id)
            resolved = resolution.namespace
        except Exception as exc:
            # RelatedNamespaceConflict needs to surface to the route handler
            # so it can return 409 — let it through.
            from backend.services.namespace_matcher import RelatedNamespaceConflict

            if isinstance(exc, RelatedNamespaceConflict):
                raise
            logger.debug("ai_chat_service.move_chat.matcher_skipped", reason=str(exc))

    chat.namespace = resolved
    chat.requested_namespace = None
    chat.updated_at = datetime.now(UTC)
    await db.flush()

    turn_count = await _count_turns(chat.chat_id, db)
    return _to_response(
        chat,
        turn_count=turn_count,
        was_created=False,
        was_updated=True,
        turns=None,
    )


async def append_turns(
    chat_id: uuid.UUID,
    user_id: uuid.UUID,
    turns: list[TurnUpsert],
    db: AsyncSession,
) -> dict[str, Any]:
    """Append (or upsert) ``turns`` to an existing chat.

    Used by the extension's streaming path: push the chat once with
    ``ChatUpsert``, then call this endpoint as new turns arrive. Returns
    ``{appended, total_turns}``.

    The chat-level ``content_hash`` is recomputed lazily on the next
    ``upsert_chat`` — this endpoint deliberately doesn't refresh it,
    because the extension is expected to send the canonical conversation
    via ``upsert_chat`` when the user finishes / leaves the page.
    """
    if len(turns) > MAX_TURNS_PER_BATCH:
        raise ValueError(
            f"Batch too large ({len(turns)} > {MAX_TURNS_PER_BATCH} turns)."
        )
    for t in turns:
        _validate_turn(t)

    chat = await _get_chat_for_user(chat_id, user_id, db)
    inserted = await _persist_turns(chat, turns, db)
    chat.updated_at = datetime.now(UTC)
    await db.flush()
    total = await _count_turns(chat_id, db)
    return {
        "chat_id": str(chat_id),
        "appended": inserted,
        "total_turns": total,
    }


async def get_chat(
    chat_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
    include_turns: bool = False,
    include_artifacts: bool = False,
) -> ChatResponse:
    chat = await _get_chat_for_user(chat_id, user_id, db)
    turn_count = await _count_turns(chat_id, db)
    turns_response: list[TurnResponse] | None = None
    if include_turns:
        turns_response = await _load_turns(chat_id, db, include_artifacts=include_artifacts)
    return _to_response(
        chat,
        turn_count=turn_count,
        was_created=False,
        was_updated=False,
        turns=turns_response,
    )


async def list_chats(
    user_id: uuid.UUID,
    db: AsyncSession,
    namespace: str | None = None,
    platform: str | None = None,
    since: datetime | None = None,
    limit: int = 20,
    offset: int = 0,
) -> ChatListResponse:
    # Cap matches the route's Query(le=500). Higher ceiling lets the
    # dashboard's NamespacesPage aggregator pull a whole user's catalogue
    # in one shot to group chats by namespace client-side.
    limit = max(1, min(limit, 500))
    offset = max(0, offset)

    base_where = [AIChat.user_id == user_id, AIChat.invalid_at.is_(None)]
    if namespace:
        base_where.append(AIChat.namespace == namespace)
    if platform:
        base_where.append(AIChat.platform == platform.lower())
    if since:
        base_where.append(AIChat.updated_at >= since)

    total = (
        await db.execute(
            select(func.count()).select_from(AIChat).where(and_(*base_where))
        )
    ).scalar() or 0

    rows = (
        await db.execute(
            select(AIChat)
            .where(and_(*base_where))
            .order_by(AIChat.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()

    items: list[ChatListItem] = []
    for chat in rows:
        items.append(
            ChatListItem(
                chat_id=str(chat.chat_id),
                platform=chat.platform,
                platform_conversation_id=chat.platform_conversation_id,
                namespace=chat.namespace,
                title=chat.title,
                captured_at=chat.captured_at.isoformat() if chat.captured_at else None,
                updated_at=chat.updated_at.isoformat() if chat.updated_at else "",
                turn_count=await _count_turns(chat.chat_id, db),
                artifact_count=await _count_artifacts(chat.chat_id, db),
            )
        )

    return ChatListResponse(items=items, total=int(total), limit=limit, offset=offset)


async def soft_delete_chat(
    chat_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    chat = await _get_chat_for_user(chat_id, user_id, db)
    chat.invalid_at = datetime.now(UTC)
    await db.flush()


# ─── Mapping CRUD ──────────────────────────────────────────────────


async def create_mapping(
    user_id: uuid.UUID,
    org_id: str,
    request: ChatMappingCreate,
    db: AsyncSession,
) -> ChatMappingResponse:
    if request.platform.lower() not in VALID_PLATFORMS:
        raise ValueError(f"Invalid platform '{request.platform}'.")
    if not request.source_project_id and not request.source_project_name_pattern:
        raise ValueError("Mapping must set either source_project_id or source_project_name_pattern.")
    row = ChatNamespaceMapping(
        user_id=user_id,
        org_id=org_id,
        platform=request.platform.lower(),
        source_project_id=request.source_project_id,
        source_project_name_pattern=request.source_project_name_pattern,
        target_namespace=request.target_namespace,
        priority=request.priority,
        enabled=request.enabled,
    )
    db.add(row)
    await db.flush()
    return _mapping_response(row)


async def list_mappings(
    user_id: uuid.UUID,
    db: AsyncSession,
) -> list[ChatMappingResponse]:
    rows = (
        await db.execute(
            select(ChatNamespaceMapping)
            .where(ChatNamespaceMapping.user_id == user_id)
            .order_by(ChatNamespaceMapping.priority.asc(), ChatNamespaceMapping.created_at.asc())
        )
    ).scalars().all()
    return [_mapping_response(r) for r in rows]


async def update_mapping(
    mapping_id: uuid.UUID,
    user_id: uuid.UUID,
    request: ChatMappingUpdate,
    db: AsyncSession,
) -> ChatMappingResponse:
    row = await _get_mapping_for_user(mapping_id, user_id, db)
    if request.target_namespace is not None:
        row.target_namespace = request.target_namespace
    if request.priority is not None:
        row.priority = request.priority
    if request.enabled is not None:
        row.enabled = request.enabled
    if request.source_project_id is not None:
        row.source_project_id = request.source_project_id
    if request.source_project_name_pattern is not None:
        row.source_project_name_pattern = request.source_project_name_pattern
    await db.flush()
    return _mapping_response(row)


async def delete_mapping(
    mapping_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    row = await _get_mapping_for_user(mapping_id, user_id, db)
    await db.delete(row)
    await db.flush()


# ─── Internal helpers ──────────────────────────────────────────────


async def _get_chat_for_user(
    chat_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> AIChat:
    chat = (
        await db.execute(
            select(AIChat).where(
                AIChat.chat_id == chat_id,
                AIChat.user_id == user_id,
                AIChat.invalid_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if chat is None:
        raise ValueError("Chat not found")
    return chat


async def _get_mapping_for_user(
    mapping_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> ChatNamespaceMapping:
    row = (
        await db.execute(
            select(ChatNamespaceMapping).where(
                ChatNamespaceMapping.mapping_id == mapping_id,
                ChatNamespaceMapping.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ValueError("Mapping not found")
    return row


async def _count_turns(chat_id: uuid.UUID, db: AsyncSession) -> int:
    total = (
        await db.execute(
            select(func.count()).select_from(AIChatTurn).where(AIChatTurn.chat_id == chat_id)
        )
    ).scalar()
    return int(total or 0)


async def _count_artifacts(chat_id: uuid.UUID, db: AsyncSession) -> int:
    total = (
        await db.execute(
            select(func.count())
            .select_from(AIChatArtifact)
            .where(AIChatArtifact.chat_id == chat_id)
        )
    ).scalar()
    return int(total or 0)


async def _load_turns(
    chat_id: uuid.UUID,
    db: AsyncSession,
    include_artifacts: bool = False,
) -> list[TurnResponse]:
    rows = (
        await db.execute(
            select(AIChatTurn)
            .where(AIChatTurn.chat_id == chat_id)
            .order_by(AIChatTurn.sequence.asc())
        )
    ).scalars().all()

    artifacts_by_turn: dict[uuid.UUID, list[AIChatArtifact]] = {}
    if include_artifacts and rows:
        turn_ids = [r.turn_id for r in rows]
        arts = (
            await db.execute(
                select(AIChatArtifact).where(AIChatArtifact.turn_id.in_(turn_ids))
            )
        ).scalars().all()
        for art in arts:
            artifacts_by_turn.setdefault(art.turn_id, []).append(art)

    out: list[TurnResponse] = []
    for r in rows:
        out.append(
            TurnResponse(
                turn_id=str(r.turn_id),
                chat_id=str(r.chat_id),
                source_turn_id=r.source_turn_id,
                parent_turn_id=str(r.parent_turn_id) if r.parent_turn_id else None,
                role=r.role,
                content=r.content,
                content_html=r.content_html,
                thinking_content=r.thinking_content,
                tool_calls=r.tool_calls,
                turn_metadata=r.turn_metadata,
                sequence=r.sequence,
                created_at=r.created_at.isoformat() if r.created_at else "",
                artifacts=[
                    _artifact_to_response(a)
                    for a in artifacts_by_turn.get(r.turn_id, [])
                ],
            )
        )
    return out


def _artifact_to_response(a: AIChatArtifact) -> ArtifactResponse:
    """Build an ArtifactResponse from a row, refreshing content_url on
    the fly for minio-backed artifacts so the browser always gets a
    fresh signed URL it can use directly in <audio>/<video>/<img>.

    Persisted content_url (legacy / extension-supplied external URLs)
    are passed through unchanged. The signed-URL path only kicks in
    when artifact_metadata.storage_key is set — that's our marker that
    the body lives in object storage and needs an HMAC-signed URL.

    Since v3.35.0 ``chat_id`` and ``turn_id`` may be None (namespace/memory
    artifacts).  For those cases the new ``/api/v1/artifacts/{id}/blob``
    endpoint is used instead of the chat-scoped blob endpoint.
    """
    meta = a.artifact_metadata or {}
    storage_key = meta.get("storage_key") if isinstance(meta, dict) else None
    content_url = a.content_url
    if storage_key and not content_url:
        try:
            if a.chat_id:
                from backend.services.artifact_storage import build_signed_blob_url
                content_url = build_signed_blob_url(a.chat_id, a.artifact_id)
            else:
                from backend.services.artifact_storage import build_artifact_blob_url
                content_url = build_artifact_blob_url(a.artifact_id)
        except Exception as exc:
            logger.debug("ai_chat_service.signed_url_failed", reason=str(exc))

    meta_dict: dict | None = meta if isinstance(meta, dict) and meta else None
    return ArtifactResponse(
        artifact_id=str(a.artifact_id),
        turn_id=str(a.turn_id) if a.turn_id else None,
        chat_id=str(a.chat_id) if a.chat_id else None,
        namespace=a.namespace if hasattr(a, "namespace") else None,
        artifact_type=a.artifact_type,
        language=a.language,
        content=a.content,
        content_url=content_url,
        content_sha256=a.content_sha256,
        artifact_metadata=meta_dict,
        filename=(meta.get("filename") if isinstance(meta, dict) else None),
        size_bytes=(
            int(meta["size_bytes"]) if isinstance(meta, dict) and meta.get("size_bytes") else None
        ),
        created_at=a.created_at.isoformat() if a.created_at else "",
    )


def _to_response(
    chat: AIChat,
    *,
    turn_count: int,
    was_created: bool,
    was_updated: bool,
    turns: list[TurnResponse] | None,
) -> ChatResponse:
    return ChatResponse(
        chat_id=str(chat.chat_id),
        user_id=str(chat.user_id),
        platform=chat.platform,
        platform_conversation_id=chat.platform_conversation_id,
        source_project_id=chat.source_project_id,
        source_project_name=chat.source_project_name,
        namespace=chat.namespace,
        requested_namespace=chat.requested_namespace,
        title=chat.title,
        model=chat.model,
        chat_metadata=chat.chat_metadata,
        content_hash=chat.content_hash,
        captured_at=chat.captured_at.isoformat() if chat.captured_at else None,
        source_type=chat.source_type,
        installation_id=str(chat.installation_id) if chat.installation_id else None,
        created_at=chat.created_at.isoformat() if chat.created_at else "",
        updated_at=chat.updated_at.isoformat() if chat.updated_at else "",
        turn_count=turn_count,
        was_created=was_created,
        was_updated=was_updated,
        turns=turns,
    )


def _mapping_response(row: ChatNamespaceMapping) -> ChatMappingResponse:
    return ChatMappingResponse(
        mapping_id=str(row.mapping_id),
        platform=row.platform,
        source_project_id=row.source_project_id,
        source_project_name_pattern=row.source_project_name_pattern,
        target_namespace=row.target_namespace,
        priority=row.priority,
        enabled=row.enabled,
        created_at=row.created_at.isoformat() if row.created_at else "",
        updated_at=row.updated_at.isoformat() if row.updated_at else "",
    )


# `or_` import kept in case future filters need it (e.g. mapping name OR id).
_ = or_  # silence linter while the symbol is staged for the v1.1 pattern matcher.
