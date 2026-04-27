"""
S9N Memory Vault — Authentication Service

Handles JWT token creation/validation and API key management.
Implements F01-US-001 (JWT auth), F01-US-002 (API key management).

Security model:
- JWT tokens: Short-lived (15 min), used for session-based access
- API keys: Long-lived, bcrypt-hashed, used for agent-to-agent calls
- Both methods produce the same internal auth context

Performance:
- API key auth uses a SHA-256 prefix for O(1) DB lookup (no bcrypt scan)
- In-memory TTL cache avoids repeated bcrypt verification (~170ms/call)
"""
import uuid
import secrets
import hashlib
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

from jose import jwt, JWTError
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config.settings import settings
from backend.models.agent import AgentRegistry


# ─── Password / API Key Hashing ──────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ─── Auth Cache ──────────────────────────────────────────────────
# Cache verified API keys for 5 minutes to avoid repeated bcrypt calls.
# Key: SHA-256 of the plaintext API key → Value: (AuthContext, expiry_time)
_auth_cache: dict[str, tuple["AuthContext", float]] = {}
# Reverse index: agent_id (str) → set of cache keys for that agent.
# Lets us invalidate one agent's entries on key rotation in O(1) without
# walking the whole cache (the previous implementation wiped everything,
# which caused a thundering herd of bcrypt verifications at scale).
_auth_cache_by_agent: dict[str, set[str]] = {}
_AUTH_CACHE_TTL = 300  # seconds


class AuthContext(BaseModel):
    """Represents the authenticated identity for a request.

    Multi-tenant fields (org_id, team_ids, roles) are populated by the
    auth middleware (see backend/core/auth.py and backend/core/tenancy.py).
    They default to empty values so existing single-tenant code paths keep
    working while TENANT_ENFORCEMENT='off'.
    """
    user_id: uuid.UUID
    agent_id: uuid.UUID | None = None
    agent_name: str = ""
    scopes: list[str] = []
    auth_method: str  # "jwt", "api_key", or "keycloak"

    # ── Multi-tenancy (WS-2) ──────────────────────────────────────
    # Source priority:
    #   keycloak path → token claim (settings.tenant_org_claim)
    #   api_key path  → AgentRegistry.org_id (WS-5, never from headers)
    #   jwt    path   → token claim "org_id" (HS256 internal agents)
    # When TENANT_ENFORCEMENT='enforce', tokens missing this value cause
    # 401 missing_org_claim. While 'off' or 'shadow', empty string is OK.
    org_id: str = ""
    # Resolved server-side from TeamMember rows by team_resolver (WS-4).
    # Not present on token; recomputed per-request with a 60s cache.
    team_ids: list[str] = []
    # Mirror of `scopes` but specifically the role-shaped subset (e.g.
    # "org_admin", "team_owner"). Kept separate so role checks don't have
    # to know about scope-string conventions.
    roles: list[str] = []
    # When set, the request was made by an MCP bridge process holding an
    # API key for a different user but acting on behalf of this user (WS-6).
    # Audit emits both identities so accountability is preserved.
    acting_user_id: uuid.UUID | None = None


class TokenPayload(BaseModel):
    """JWT token payload structure."""
    sub: str          # agent_id
    user_id: str
    agent_name: str
    scopes: list[str]
    exp: datetime
    iat: datetime
    jti: str          # unique token ID for revocation


# ─── JWT Operations ──────────────────────────────────────────────

def create_access_token(
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    agent_name: str,
    scopes: list[str],
    expires_delta: Optional[timedelta] = None,
    org_id: Optional[str] = None,
) -> str:
    """
    Create a signed JWT access token for an authenticated agent.

    Args:
        agent_id: The agent's UUID
        user_id: The owning user's UUID
        agent_name: Human-readable agent name
        scopes: List of granted scope strings
        expires_delta: Custom expiry (default: settings.jwt_expiry_minutes)
        org_id: Tenant identifier (WS-2). When None, falls back to the
            migration sentinel — callers that have an org_id in scope
            (e.g. /v1/auth/token issuing for an agent) should always pass
            it explicitly so the resulting AuthContext is enforceable.

    Returns:
        Encoded JWT string
    """
    now = datetime.now(timezone.utc)
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.jwt_expiry_minutes)

    payload = {
        "sub": str(agent_id),
        "user_id": str(user_id),
        "agent_name": agent_name,
        "scopes": scopes,
        "org_id": org_id or settings.tenant_legacy_sentinel,
        "exp": now + expires_delta,
        "iat": now,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> Optional[AuthContext]:
    """
    Decode and validate a JWT access token.

    Returns:
        AuthContext if valid, None if invalid/expired
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        # Extract scopes — handle both list and string formats
        scopes = payload.get("scopes", [])
        if isinstance(scopes, str):
            scopes = scopes.split(",")

        return AuthContext(
            user_id=uuid.UUID(payload["user_id"]),
            agent_id=uuid.UUID(payload["sub"]),
            agent_name=payload.get("agent_name", ""),
            scopes=scopes,
            auth_method="jwt",
            # HS256 internal tokens carry org_id when minted post-WS-2;
            # legacy tokens fall back to the sentinel so they keep working
            # until natural rotation (15-minute expiry).
            org_id=payload.get("org_id") or settings.tenant_legacy_sentinel,
        )
    except (JWTError, KeyError, ValueError):
        return None


# ─── API Key Operations ──────────────────────────────────────────

def _prehash_key(key: str) -> str:
    """
    Pre-hash a key with SHA-256 before bcrypt to handle the 72-byte limit.
    bcrypt silently truncates at 72 bytes, so we hash first for security.
    """
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _compute_key_prefix(plaintext_key: str) -> str:
    """Compute a 16-char hex prefix from SHA-256 of the plaintext key for fast DB lookup."""
    return hashlib.sha256(plaintext_key.encode("utf-8")).hexdigest()[:16]


def generate_api_key() -> tuple[str, str, str]:
    """
    Generate a new API key, its bcrypt hash, and a lookup prefix.

    Returns:
        Tuple of (plaintext_key, hashed_key, key_prefix)
        The plaintext key is shown to the user ONCE and never stored.
    Uses SHA-256 pre-hash before bcrypt to handle the 72-byte limit.
    """
    # Generate a 24-byte random key with 's9nmv_' prefix for identification
    raw_key = secrets.token_urlsafe(24)
    plaintext_key = f"s9nmv_{raw_key}"
    hashed_key = pwd_context.hash(_prehash_key(plaintext_key))
    key_prefix = _compute_key_prefix(plaintext_key)
    return plaintext_key, hashed_key, key_prefix


def verify_api_key(plaintext_key: str, hashed_key: str) -> bool:
    """Verify a plaintext API key against its bcrypt hash."""
    if not plaintext_key:
        return False
    return pwd_context.verify(_prehash_key(plaintext_key), hashed_key)


def _cache_key(api_key: str) -> str:
    """Compute cache key from the plaintext API key."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def clear_auth_cache_for_agent(agent_id: uuid.UUID | str) -> None:
    """Drop any AuthContext entries belonging to a specific agent.

    Called on key rotation (WS-5). The reverse-index map ``_auth_cache_by_agent``
    tracks every cache key associated with each agent_id, so this is O(k)
    in the rotation cost rather than O(N) in the cache size — preventing
    the thundering-herd of bcrypt verifications a full cache wipe would
    cause at scale.
    """
    if not agent_id:
        return
    aid = str(agent_id)
    keys = _auth_cache_by_agent.pop(aid, set())
    for ck in keys:
        _auth_cache.pop(ck, None)


def _cache_auth_context(cache_key: str, ctx: "AuthContext", expiry: float) -> None:
    """Store an AuthContext and update the reverse index."""
    _auth_cache[cache_key] = (ctx, expiry)
    if ctx.agent_id is not None:
        _auth_cache_by_agent.setdefault(str(ctx.agent_id), set()).add(cache_key)


async def authenticate_api_key(
    api_key: str,
    db: AsyncSession,
) -> Optional[AuthContext]:
    """
    Authenticate a request using an API key.

    Performance optimizations:
    1. In-memory TTL cache — avoids DB + bcrypt on repeated calls
    2. SHA-256 prefix lookup — finds the right agent in O(1) via indexed column
    3. Falls back to scanning all active agents if prefix is missing (legacy keys)

    Args:
        api_key: The plaintext API key from the request header
        db: Database session

    Returns:
        AuthContext if valid, None if no matching active agent found
    """
    # 1. Check in-memory cache first
    ck = _cache_key(api_key)
    cached = _auth_cache.get(ck)
    if cached:
        ctx, expiry = cached
        if time.monotonic() < expiry:
            return ctx
        # Expired — drop and clean up the reverse-index entry so it
        # doesn't pile up unbounded under churn (heavy rotation, leaked
        # key spam, etc.).
        _auth_cache.pop(ck, None)
        if ctx.agent_id is not None:
            agent_keys = _auth_cache_by_agent.get(str(ctx.agent_id))
            if agent_keys is not None:
                agent_keys.discard(ck)
                if not agent_keys:
                    _auth_cache_by_agent.pop(str(ctx.agent_id), None)

    # 2. Try prefix-based O(1) lookup
    prefix = _compute_key_prefix(api_key)
    result = await db.execute(
        select(AgentRegistry).where(
            AgentRegistry.api_key_prefix == prefix,
            AgentRegistry.status == "active",
        )
    )
    agent = result.scalar_one_or_none()

    if agent and verify_api_key(api_key, agent.api_key_hash):
        ctx = _build_auth_context(agent)
        _cache_auth_context(ck, ctx, time.monotonic() + _AUTH_CACHE_TTL)
        agent.last_active_at = datetime.now(timezone.utc)
        await db.flush()
        return ctx

    # 3. Fallback: scan all active agents (for legacy keys without prefix)
    if agent is None:
        result = await db.execute(
            select(AgentRegistry).where(
                AgentRegistry.status == "active",
                AgentRegistry.api_key_prefix.is_(None),
            )
        )
        agents = result.scalars().all()
        for agent in agents:
            if verify_api_key(api_key, agent.api_key_hash):
                # Backfill the prefix for next time
                agent.api_key_prefix = prefix
                agent.last_active_at = datetime.now(timezone.utc)
                await db.flush()

                ctx = _build_auth_context(agent)
                _cache_auth_context(ck, ctx, time.monotonic() + _AUTH_CACHE_TTL)
                return ctx

    return None


def _build_auth_context(agent: AgentRegistry) -> AuthContext:
    """Extract AuthContext from an AgentRegistry record.

    WS-5 invariant: org_id is read from the agent row, never from request
    headers. A leaked key cannot escalate by spoofing X-Org-Id because we
    don't read that header anywhere on the api_key path.
    """
    scopes = []
    if agent.declared_scopes:
        for scope_obj in agent.declared_scopes:
            if isinstance(scope_obj, dict) and "scope" in scope_obj:
                scopes.append(scope_obj["scope"])
            elif isinstance(scope_obj, str):
                scopes.append(scope_obj)

    # Pre-WS-5 keys have NULL org_id — fall back to the migration sentinel
    # so they keep working until ops reassigns them in P4 rollout phase.
    org_id = (agent.org_id or settings.tenant_legacy_sentinel)

    return AuthContext(
        user_id=agent.user_id,
        agent_id=agent.agent_id,
        agent_name=agent.agent_name,
        scopes=scopes,
        auth_method="api_key",
        org_id=org_id,
    )
