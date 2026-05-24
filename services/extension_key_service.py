"""
Kemory — Extension key service (chats-v1).

Mint / list / revoke per-install API keys for the Kanvas Chrome Extension.

**Design note:** extensions are agents. Each install gets its own row in
``kemory_agent_registry`` with ``agent_kind='extension'`` and ``status='active'``
(auto-approved — the human user proved consent by being authenticated at
mint time). This means:

  * Auth path is unchanged. ``authenticate_api_key`` already resolves
    ``AgentRegistry`` rows by key prefix and reads ``org_id`` straight off
    the row (WS-5 invariant: org_id from the agent record, never headers).
  * Revocation is the existing flow — flip ``status='revoked'`` and the
    auth cache invalidator wipes any cached AuthContexts O(k).
  * Gatekeeper, audit, tenancy filter all work out of the box.

The only thing this service does that the regular agent path doesn't:

  * Auto-activates without going through the pending-approval round-trip
    (matches the pair-claim flow's ``auto_activate=True``).
  * Defaults scopes to ``memory:read`` + ``memory:write`` so the extension
    can ingest chats and surface memories in the popup without each user
    having to wire up the gatekeeper.
  * Surfaces ``installation_id`` so the dashboard can label keys per device
    ("MacBook Chrome", "Work PC Edge", …).

Migration: see ``backend/migrations/versions/015_ai_chats_module.py`` for
the ``agent_kind`` column add.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.agent import AgentRegistry
from backend.services.auth_service import (
    clear_auth_cache_for_agent,
    generate_api_key,
)


# ─── Schemas ─────────────────────────────────────────────────────────


class ExtensionKeyMintRequest(BaseModel):
    """Request body for ``POST /api/v1/extension/keys``."""

    label: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Human-readable device label, e.g. 'MacBook Chrome'.",
    )
    installation_id: uuid.UUID | None = Field(
        None,
        description=(
            "Stable UUID for this Chrome install. The extension generates "
            "and persists this on first launch — re-minting with the same id "
            "rotates the key rather than creating a parallel row."
        ),
    )
    scopes: list[str] = Field(
        default_factory=lambda: ["memory:read", "memory:write", "chat:write"],
        description=(
            "Granted scopes. Defaults to the minimum the extension needs to "
            "push chats and surface memory in the popup."
        ),
    )


class ExtensionKeyMintResponse(BaseModel):
    """Response on mint. ``api_key`` is shown ONCE and never persisted in plaintext."""

    key_id: str = Field(..., description="kemory_agent_registry.agent_id.")
    installation_id: str | None = None
    label: str
    api_key: str = Field(..., description="Plaintext key — store securely in extension storage.")
    scopes: list[str]
    created_at: str
    message: str = Field(
        default=(
            "Extension key minted. Store it once — it cannot be retrieved later. "
            "Send it on every request via the X-API-Key header."
        )
    )


class ExtensionKeyInfo(BaseModel):
    """Public info for listing — never includes the plaintext key."""

    key_id: str
    label: str
    installation_id: str | None
    scopes: list[str]
    status: str
    last_used_at: str | None
    created_at: str


# ─── Service functions ──────────────────────────────────────────────


# Synthetic / service-account org_ids that should NEVER own user-facing
# extension keys. The Kanvas extension's `/auth?reMint=1` flow once
# minted under `org_id=kora-extension` instead of the human's Keycloak
# org, producing chats invisible to the dashboard owner. Refusing this
# class of org_id at mint time makes the failure loud (400) instead of
# silently fragmenting ownership.
#
# Override via KEMORY_EXTENSION_REFUSE_ORG_IDS env (CSV) when this list
# legitimately needs to grow.
_SYNTHETIC_EXTENSION_ORG_IDS: frozenset[str] = frozenset({
    "kora-extension",
})


def _refused_org_ids() -> frozenset[str]:
    override = os.environ.get("KEMORY_EXTENSION_REFUSE_ORG_IDS", "").strip()
    if not override:
        return _SYNTHETIC_EXTENSION_ORG_IDS
    return frozenset({s.strip() for s in override.split(",") if s.strip()})


async def mint_extension_key(
    user_id: uuid.UUID,
    org_id: str,
    request: ExtensionKeyMintRequest,
    db: AsyncSession,
) -> ExtensionKeyMintResponse:
    """Create (or rotate) a Chrome Extension API key.

    When ``installation_id`` matches an existing extension row for this
    user, the key is rotated in place — the old key stops working as soon
    as this transaction commits. When omitted, a fresh row is minted.

    Refuses to mint when the caller's ``org_id`` is on the synthetic
    denylist (see _SYNTHETIC_EXTENSION_ORG_IDS). This catches the case
    where the extension authenticates with a service-account JWT instead
    of the human's Keycloak token — silent failure mode previously left
    chats owned by an identity the dashboard owner couldn't see.
    """
    if org_id and org_id in _refused_org_ids():
        raise ValueError(
            f"Refusing to mint extension key for org_id={org_id!r}. This "
            f"looks like a synthetic / service-account identity, not a "
            f"human user. The extension must authenticate with the user's "
            f"Keycloak token (or an HS256 token whose org_id matches a "
            f"real user account). If this is intentional, override via "
            f"KEMORY_EXTENSION_REFUSE_ORG_IDS env."
        )

    label = request.label.strip()
    if not label:
        raise ValueError("label must be a non-empty string")

    # If installation_id is supplied, see if we already have a row for it.
    existing: AgentRegistry | None = None
    if request.installation_id is not None:
        existing = await _find_extension_by_installation(
            user_id, request.installation_id, db
        )

    plaintext_key, hashed_key, key_prefix = generate_api_key()

    if existing is not None:
        # Rotate in place — same row, new key, same agent_id.
        existing.api_key_hash = hashed_key
        existing.api_key_prefix = key_prefix
        existing.agent_description = label
        existing.declared_scopes = [{"scope": s, "reason": "kanvas-extension"} for s in request.scopes]
        if existing.status == "revoked":
            existing.status = "active"
        await db.flush()
        # Wipe any cached AuthContexts so the old key stops working
        # immediately on the next request.
        await clear_auth_cache_for_agent(existing.agent_id)
        agent = existing
    else:
        agent_name = _derive_agent_name(label, request.installation_id)
        # Avoid colliding with an existing agent_name for this user.
        agent_name = await _unique_agent_name(user_id, agent_name, db)

        agent = AgentRegistry(
            user_id=user_id,
            org_id=org_id,
            agent_name=agent_name,
            agent_description=label,
            declared_scopes=[{"scope": s, "reason": "kanvas-extension"} for s in request.scopes],
            api_key_hash=hashed_key,
            api_key_prefix=key_prefix,
            status="active",
            agent_kind="extension",
        )
        db.add(agent)
        await db.flush()

    return ExtensionKeyMintResponse(
        key_id=str(agent.agent_id),
        installation_id=str(request.installation_id) if request.installation_id else None,
        label=label,
        api_key=plaintext_key,
        scopes=request.scopes,
        created_at=(agent.registered_at or datetime.now(UTC)).isoformat(),
    )


async def list_extension_keys(
    user_id: uuid.UUID,
    db: AsyncSession,
) -> list[ExtensionKeyInfo]:
    rows = (
        await db.execute(
            select(AgentRegistry)
            .where(
                AgentRegistry.user_id == user_id,
                AgentRegistry.agent_kind == "extension",
            )
            .order_by(AgentRegistry.registered_at.desc())
        )
    ).scalars().all()
    return [_to_info(r) for r in rows]


async def revoke_extension_key(
    key_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    row = await _get_extension_for_user(key_id, user_id, db)
    row.status = "revoked"
    await db.flush()
    await clear_auth_cache_for_agent(row.agent_id)


# ─── Internal helpers ──────────────────────────────────────────────


async def _find_extension_by_installation(
    user_id: uuid.UUID,
    installation_id: uuid.UUID,
    db: AsyncSession,
) -> AgentRegistry | None:
    """Look up a Chrome install by the installation_id encoded in agent_name.

    We don't add a dedicated column for ``installation_id`` to ``AgentRegistry``
    — instead we encode it in ``agent_name`` as ``kanvas-{installation_id}``
    so the existing unique constraint on ``(user_id, agent_name)`` doubles as
    "one extension row per install". This keeps the AgentRegistry schema
    untouched apart from the ``agent_kind`` column.
    """
    needle = f"kanvas-{installation_id}"
    return (
        await db.execute(
            select(AgentRegistry).where(
                AgentRegistry.user_id == user_id,
                AgentRegistry.agent_name == needle,
                AgentRegistry.agent_kind == "extension",
            )
        )
    ).scalar_one_or_none()


def _derive_agent_name(label: str, installation_id: uuid.UUID | None) -> str:
    if installation_id is not None:
        return f"kanvas-{installation_id}"
    # Fall back to a label-derived name with a short random suffix to
    # keep things unique when the extension doesn't supply an install id
    # (shouldn't happen post-v1.0, but defensive).
    slug = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in label.lower())
    return f"kanvas-{slug[:48]}-{uuid.uuid4().hex[:6]}"


async def _unique_agent_name(
    user_id: uuid.UUID,
    candidate: str,
    db: AsyncSession,
) -> str:
    """Ensure ``(user_id, agent_name)`` doesn't collide. Suffixes on conflict."""
    name = candidate
    while True:
        clash = (
            await db.execute(
                select(AgentRegistry.agent_id).where(
                    AgentRegistry.user_id == user_id,
                    AgentRegistry.agent_name == name,
                )
            )
        ).scalar_one_or_none()
        if clash is None:
            return name
        name = f"{candidate}-{uuid.uuid4().hex[:4]}"


async def _get_extension_for_user(
    key_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> AgentRegistry:
    row = (
        await db.execute(
            select(AgentRegistry).where(
                AgentRegistry.agent_id == key_id,
                AgentRegistry.user_id == user_id,
                AgentRegistry.agent_kind == "extension",
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ValueError("Extension key not found")
    return row


def _to_info(row: AgentRegistry) -> ExtensionKeyInfo:
    scopes: list[str] = []
    if row.declared_scopes:
        for s in row.declared_scopes:
            if isinstance(s, dict) and "scope" in s:
                scopes.append(s["scope"])
            elif isinstance(s, str):
                scopes.append(s)
    # The installation_id was encoded into agent_name; recover it for the UI.
    installation_id: str | None = None
    if row.agent_name and row.agent_name.startswith("kanvas-"):
        candidate = row.agent_name.removeprefix("kanvas-")
        # Only surface as installation_id when it looks like a real UUID.
        try:
            installation_id = str(uuid.UUID(candidate))
        except ValueError:
            installation_id = None

    return ExtensionKeyInfo(
        key_id=str(row.agent_id),
        label=row.agent_description or "",
        installation_id=installation_id,
        scopes=scopes,
        status=row.status,
        last_used_at=row.last_active_at.isoformat() if row.last_active_at else None,
        created_at=row.registered_at.isoformat() if row.registered_at else "",
    )


# Silence unused-warning if external code imports Any for type stubs.
_ = Any
