"""
Quick‑connect pair flow.

Removes the per‑client setup wizard. The human user clicks "Connect" in
the dashboard, the dashboard generates a short‑lived pair code, the
user pastes one prompt + claim URL into any AI, and the AI self‑
registers an agent and receives its API key + the brief.

Endpoints:
- POST `/api/v1/pair/start`         — human auth required, mint a code.
- GET  `/api/v1/pair/{code}/status` — human auth required, poll for claim.
- POST `/api/v1/pair/{code}/claim`  — NO auth (the code IS the auth);
                                       called by the AI to self‑register.
"""

from __future__ import annotations

import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config.settings import settings
from backend.core.auth import AuthContext, require_auth
from backend.core.database import get_db
from backend.core.tenancy import TenantScope, TenantScopeDep
from backend.mcp.tools import TOOL_DEFINITIONS
from backend.services.agent_service import (
    AgentRegistrationRequest,
    ScopeDeclaration,
    register_agent,
)
from backend.services.brief_service import BRIEF_VERSION, render_brief
from backend.services.mcp_setup_service import build_setup
from backend.services.pair_service import (
    PAIR_TTL_SECONDS,
    delete_pair,
    get_pair,
    mark_claimed,
    start_pair,
)

router = APIRouter(prefix="/api/v1/pair", tags=["Pair"])


# ─── Schemas ───────────────────────────────────────────────────────


class PairStartRequest(BaseModel):
    purpose: str = Field(
        "", max_length=200, description="Free‑form note shown in pair status (e.g. 'ChatGPT laptop')"
    )


class PairStartResponse(BaseModel):
    code: str
    claim_url: str
    expires_in: int  # seconds


class PairStatusResponse(BaseModel):
    code: str
    claimed: bool
    expires_in: int
    agent_id: str | None = None
    agent_name: str | None = None
    client_name: str | None = None


class PairClaimRequest(BaseModel):
    client_name: str = Field(
        ...,
        min_length=1,
        max_length=80,
        description="Display name of the AI claiming the code (e.g. 'ChatGPT', 'Cursor', 'Claude Desktop')",
    )


class ToolSummary(BaseModel):
    name: str
    description: str


class ClientSetupPayload(BaseModel):
    client_id: str
    display: str
    supports_mcp: bool
    config_path: str
    format: str
    snippet: str
    restart_hint: str


class PairClaimResponse(BaseModel):
    api_key: str
    agent_id: str
    agent_name: str
    mcp_url: str
    brief: str
    brief_version: str
    tools: list[ToolSummary]
    setup: ClientSetupPayload


# ─── Helpers ───────────────────────────────────────────────────────

_AGENT_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(name: str) -> str:
    s = _AGENT_SLUG_RE.sub("-", name.lower()).strip("-")
    return s or "agent"


# Client names that identify the Kora Chrome Extension claiming a pair code.
# When `client_name` slugifies to one of these, the resulting agent row is
# tagged ``agent_kind='extension'`` so the dashboard's Devices tab surfaces
# the install alongside keys minted via ``/api/v1/extension/keys`` — and the
# extension itself only needs ``api_key`` from the response (MCP setup/brief
# fields stay populated for API compatibility but are ignored client-side).
_KORA_EXTENSION_CLIENT_SLUGS: frozenset[str] = frozenset(
    {
        "kora-chrome-extension",
        "kora-extension",
        "kanvas",
        "kanvas-chrome",
        "kanvas-chrome-extension",
    }
)


def _is_kora_extension_client(client_name: str) -> bool:
    """True when ``client_name`` identifies the Kora Chrome Extension."""
    return _slug(client_name) in _KORA_EXTENSION_CLIENT_SLUGS


# ─── Routes ────────────────────────────────────────────────────────


@router.post(
    "/start",
    response_model=PairStartResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Mint a short‑lived pair code for quick‑connect setup",
)
async def pair_start_endpoint(
    request: PairStartRequest,
    auth: AuthContext = Depends(require_auth),
    scope: TenantScope = TenantScopeDep,
):
    record = await start_pair(
        user_id=auth.user_id,
        org_id=scope.org_id,
        purpose=request.purpose,
    )
    base = settings.api_public_url.rstrip("/")
    return PairStartResponse(
        code=record.code,
        claim_url=f"{base}/api/v1/pair/{record.code}/claim",
        expires_in=PAIR_TTL_SECONDS,
    )


@router.get(
    "/{code}/status",
    response_model=PairStatusResponse,
    summary="Poll a pair code's claim status (originator only)",
)
async def pair_status_endpoint(
    code: str,
    auth: AuthContext = Depends(require_auth),
):
    record = await get_pair(code)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="pair_code_not_found_or_expired")
    if record.user_id != str(auth.user_id):
        # Don't leak that the code exists — same 404 as "missing".
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="pair_code_not_found_or_expired")
    import time as _time

    return PairStatusResponse(
        code=record.code,
        claimed=record.claimed,
        expires_in=max(0, int(record.expires_at - _time.time())),
        agent_id=record.agent_id,
        agent_name=record.agent_name,
        client_name=record.client_name,
    )


@router.post(
    "/{code}/claim",
    response_model=PairClaimResponse,
    summary="Self‑register an agent using a pair code (called by the AI)",
)
async def pair_claim_endpoint(
    code: str,
    request: PairClaimRequest,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint — the pair code itself is the bearer credential.

    The AI calls this once with its display name. We register a fresh
    agent owned by the human user who minted the code and return the
    one‑time API key + the brief telling the AI how to behave.
    """
    record = await get_pair(code)
    if record is None or record.claimed:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="pair_code_invalid_or_already_claimed",
        )

    # Build a unique agent_name by sluggifying client_name and appending
    # a 4‑char random suffix so two simultaneous claims from the same
    # client don't collide on the unique (user_id, agent_name) index.
    suffix = secrets.token_hex(2)
    agent_name = f"{_slug(request.client_name)}-{suffix}"

    import uuid as _uuid

    user_uuid = _uuid.UUID(record.user_id)

    is_extension = _is_kora_extension_client(request.client_name)
    try:
        registration = await register_agent(
            user_uuid,
            AgentRegistrationRequest(
                agent_name=agent_name,
                agent_description=f"Auto‑registered via quick‑connect from {request.client_name}",
                declared_scopes=[
                    ScopeDeclaration(
                        scope="memory:read", reason=f"{request.client_name} needs to recall user memories"
                    ),
                    ScopeDeclaration(
                        scope="memory:write", reason=f"{request.client_name} needs to store user memories"
                    ),
                ],
            ),
            db,
            org_id=record.org_id,
            # The pair code itself is the user's consent proof — they minted
            # it from an authenticated dashboard session and the AI just
            # presented it. Skip the AUTO_APPROVE_AGENTS gate so the returned
            # api_key is immediately usable instead of 401ing on every MCP call.
            auto_activate=True,
            # Tag Chrome-extension claims so the install lands under the
            # Devices tab (same kind as /api/v1/extension/keys mints).
            agent_kind="extension" if is_extension else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    # Render brief BEFORE marking the pair claimed. If brief rendering
    # ever fails (e.g. the prompts/ asset is missing from the image), we
    # want the pair to remain usable so the user can retry, rather than
    # burning the code and forcing them to start over.
    brief = render_brief(
        agent_name=registration.agent_name,
        agent_id=registration.agent_id,
        client_name=request.client_name,
    )

    claimed = await mark_claimed(
        code,
        agent_id=registration.agent_id,
        agent_name=registration.agent_name,
        client_name=request.client_name,
    )
    if claimed is None:
        # Someone else claimed between our get_pair check and now.
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="pair_code_invalid_or_already_claimed",
        )

    tools = [ToolSummary(name=t.name, description=t.description) for t in TOOL_DEFINITIONS]

    # Pair codes are single‑use; the dashboard keeps polling /status until
    # the record TTL expires so it can surface "Connected as <agent_name>".
    _ = delete_pair  # imported for completeness; intentional no‑op call site

    base = settings.api_public_url.rstrip("/")
    mcp_url = f"{base}/mcp/v1"
    setup = build_setup(request.client_name, mcp_url, registration.api_key)
    return PairClaimResponse(
        api_key=registration.api_key,
        agent_id=registration.agent_id,
        agent_name=registration.agent_name,
        mcp_url=mcp_url,
        brief=brief,
        brief_version=BRIEF_VERSION,
        tools=tools,
        setup=ClientSetupPayload(
            client_id=setup.client_id,
            display=setup.display,
            supports_mcp=setup.supports_mcp,
            config_path=setup.config_path,
            format=setup.format,
            snippet=setup.snippet,
            restart_hint=setup.restart_hint,
        ),
    )
