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

import hashlib
import time
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from jose import JWTError, jwt
from pydantic import BaseModel
from s9n_auth import ApiKeyHasher
from s9n_auth import AuthContext as _S9nAuthContext
from s9n_auth.events import AuthEvent
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config.settings import settings
from backend.models.agent import AgentRegistry

logger = structlog.get_logger(__name__)


async def _bg_touch_last_active(agent_id: uuid.UUID) -> None:
    """Update kemory_agent_registry.last_active_at on its own short-lived
    session, then commit immediately. Keeping this out of the request
    transaction prevents row-lock contention on the agent row when many
    concurrent authenticated writes share the same agent_id (e.g. the
    LongMemEval ingest harness running 16 worker threads).
    """
    try:
        from backend.core.database import _get_session_factory

        async with _get_session_factory()() as own_db:
            async with own_db.begin():
                await own_db.execute(
                    update(AgentRegistry)
                    .where(AgentRegistry.agent_id == agent_id)
                    .values(last_active_at=datetime.now(UTC))
                )
    except Exception:
        # Last-active is advisory; never block the request on its failure.
        pass


# ─── API Key Hashing (s9n-auth ApiKeyHasher, HMAC-SHA256) ─────────
# API keys are high-entropy random tokens, so a slow password hash buys no
# security — s9n-auth keys them with HMAC-SHA256 under a server-side pepper
# (deterministic, microsecond, constant-time). Stored as
# `hmac-sha256:<kid>:<hex>`. Existing kemory bcrypt keys keep verifying via
# allow_legacy_bcrypt and are transparently re-hashed to HMAC on next use
# (verify-then-upgrade) — no forced re-issue. See ADR: kemory seeded s9n-auth.
_BCRYPT_ROUNDS = 12  # legacy: rounds kemory used; kept for the migration test
_hasher: ApiKeyHasher | None = None


def _emit_auth_event(event: AuthEvent) -> None:
    """Forward s9n-auth auth decisions to structlog for a unified audit trail.

    Best-effort: the library swallows any exception raised here so telemetry
    can never fail an authentication.
    """
    logger.info(
        "auth.decision",
        outcome=event.outcome,
        method=event.auth_method,
        org_id=event.org_id or None,
        agent_id=str(event.agent_id) if event.agent_id else None,
        key_prefix=event.key_prefix or None,
        upgraded=event.upgraded or None,
        reason=event.reason or None,
    )


def _get_hasher() -> ApiKeyHasher:
    """Lazily build the process-wide ApiKeyHasher.

    ``settings.api_key_pepper`` is guaranteed non-empty after settings
    model_post_init (a fixed dev pepper in dev, a real secret in staging/prod;
    empty there is fail-closed at startup). ``allow_legacy_bcrypt`` lets it
    verify+upgrade kemory's pre-existing bcrypt hashes.
    """
    global _hasher
    if _hasher is None:
        _hasher = ApiKeyHasher.single(
            settings.api_key_pepper,
            allow_legacy_bcrypt=True,
            on_event=_emit_auth_event,
        )
    return _hasher


# ─── Auth Cache ──────────────────────────────────────────────────
# Cache verified API keys for 5 minutes to avoid repeated hash verification.
# Key: SHA-256 of the plaintext API key → Value: (AuthContext, expiry_time)
_auth_cache: dict[str, tuple["AuthContext", float]] = {}
# Reverse index: agent_id (str) → set of cache keys for that agent.
# Lets us invalidate one agent's entries on key rotation in O(1) without
# walking the whole cache (the previous implementation wiped everything,
# which caused a thundering herd of bcrypt verifications at scale).
_auth_cache_by_agent: dict[str, set[str]] = {}
_AUTH_CACHE_TTL = 300  # seconds

# P1 #8: protect the cache + reverse-index dicts under concurrent writes.
# Single dict ops are GIL-atomic; the COMBINED operations (insert into
# cache + insert into reverse index, or expiry-eviction across both) are
# not. Without this lock, a rotation racing with a verification can leave
# an orphan reverse-index entry pointing at a dropped cache key, or vice
# versa — symptoms: stale-after-rotation auth, occasional misses on
# clear_auth_cache_for_agent, slow memory growth under churn.
# An asyncio.Lock is the right primitive here because every caller is on
# the asyncio event loop (FastAPI request handlers). The critical sections
# are tiny (a handful of dict ops) so contention is negligible.
import asyncio as _asyncio

_auth_cache_lock = _asyncio.Lock()


class AuthContext(_S9nAuthContext):
    """Represents the authenticated identity for a request.

    Subclasses the shared ``s9n_auth.AuthContext`` (kemory is the codebase that
    library's identity shape was seeded from) and adds the one kemory-only
    field, ``team_ids``. Inherited from s9n-auth: ``user_id``, ``agent_id``,
    ``agent_name``, ``scopes``, ``roles``, ``org_id``, ``auth_method``,
    ``acting_user_id``.

    ``user_id`` and ``auth_method`` are re-declared as required to preserve
    kemory's stricter construction contract (the base makes user_id optional
    and auth_method default to "unknown"); every kemory auth path sets both.

    Multi-tenant fields (org_id, team_ids, roles) are populated by the auth
    middleware (see backend/core/auth.py and backend/core/tenancy.py); they
    default to empty so single-tenant code paths keep working while
    TENANT_ENFORCEMENT='off'.

    Source priority for org_id:
      keycloak path → token claim (settings.tenant_org_claim)
      api_key path  → AgentRegistry.org_id (WS-5, never from headers)
      jwt    path   → token claim "org_id" (HS256 internal agents)
    """

    user_id: uuid.UUID
    auth_method: str  # "jwt", "api_key", or "keycloak"

    # Resolved server-side from TeamMember rows by team_resolver (WS-4).
    # Not present on any token; recomputed per-request with a 60s cache.
    team_ids: list[str] = []


class TokenPayload(BaseModel):
    """JWT token payload structure."""

    sub: str  # agent_id
    user_id: str
    agent_name: str
    scopes: list[str]
    exp: datetime
    iat: datetime
    jti: str  # unique token ID for revocation


# ─── JWT Operations ──────────────────────────────────────────────


def create_access_token(
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    agent_name: str,
    scopes: list[str],
    expires_delta: timedelta | None = None,
    org_id: str | None = None,
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
    now = datetime.now(UTC)
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


def decode_access_token(token: str) -> AuthContext | None:
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
    """Legacy: kemory's pre-bcrypt SHA-256 hex pre-hash.

    Kept only so the migration test can construct a hash exactly the way the
    pre-s9n-auth code did, proving the new path verifies real DB rows. Production
    no longer calls this — hashing/verification go through the ApiKeyHasher,
    whose ``allow_legacy_bcrypt`` recognises this exact scheme.
    """
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _compute_key_prefix(plaintext_key: str) -> str:
    """16-char hex prefix from SHA-256 of the key, for O(1) DB lookup.

    Identical to ``s9n_auth.lookup_prefix`` (sha256(key)[:16]) — so existing
    rows resolve under the new hasher with no prefix backfill.
    """
    return hashlib.sha256(plaintext_key.encode("utf-8")).hexdigest()[:16]


def generate_api_key() -> tuple[str, str, str]:
    """
    Mint a new API key, its HMAC-SHA256 hash, and a lookup prefix.

    Returns:
        Tuple of (plaintext_key, hashed_key, key_prefix)
        The plaintext key (``kemory_<random>``) is shown ONCE and never stored;
        only ``hashed_key`` (``hmac-sha256:<kid>:<hex>``) and ``key_prefix``
        are persisted.
    """
    # s9n-auth mints `kemory_<token_urlsafe(24)>` and returns the HMAC hash +
    # sha256(raw)[:16] prefix — same prefix scheme kemory already used.
    return _get_hasher().generate("kemory")


def verify_api_key(plaintext_key: str, hashed_key: str) -> bool:
    """Verify a plaintext API key against its stored hash.

    Delegates to the ApiKeyHasher, which transparently handles both the current
    HMAC-SHA256 hashes and legacy bcrypt hashes. Returns False on empty inputs
    or a malformed hash (no timing/error leak to a probe).
    """
    if not plaintext_key or not hashed_key:
        return False
    return _get_hasher().verify(plaintext_key, hashed_key).matched


def _cache_key(api_key: str) -> str:
    """Compute cache key from the plaintext API key."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


async def clear_auth_cache_for_agent(agent_id: uuid.UUID | str) -> None:
    """Drop any AuthContext entries belonging to a specific agent.

    Called on key rotation (WS-5). The reverse-index map ``_auth_cache_by_agent``
    tracks every cache key associated with each agent_id, so this is O(k)
    in the rotation cost rather than O(N) in the cache size — preventing
    the thundering-herd of bcrypt verifications a full cache wipe would
    cause at scale.

    P1 #8: holds ``_auth_cache_lock`` for the cross-dict pop sequence so a
    concurrent ``_cache_auth_context`` can't slot a new entry into the
    reverse index after we've cleared its agent_id but before we drop
    its cache key.
    """
    if not agent_id:
        return
    aid = str(agent_id)
    async with _auth_cache_lock:
        keys = _auth_cache_by_agent.pop(aid, set())
        for ck in keys:
            _auth_cache.pop(ck, None)


async def _cache_auth_context(cache_key: str, ctx: "AuthContext", expiry: float) -> None:
    """Store an AuthContext and update the reverse index.

    P1 #8: locks the cross-dict insert pair so a concurrent expiry-eviction
    can't drop one without the other.
    """
    async with _auth_cache_lock:
        _auth_cache[cache_key] = (ctx, expiry)
        if ctx.agent_id is not None:
            _auth_cache_by_agent.setdefault(str(ctx.agent_id), set()).add(cache_key)


async def authenticate_api_key(
    api_key: str,
    db: AsyncSession,
) -> AuthContext | None:
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
    # 1. Check in-memory cache first.
    # Read is lock-free (single dict.get is GIL-atomic and we're fine
    # with a stale snapshot for the hit path). The cleanup of an expired
    # entry crosses both _auth_cache and _auth_cache_by_agent though, so
    # P1 #8 holds the lock for that section.
    ck = _cache_key(api_key)
    cached = _auth_cache.get(ck)
    if cached:
        ctx, expiry = cached
        if time.monotonic() < expiry:
            return ctx
        # Expired — drop and clean up the reverse-index entry under lock
        # so a concurrent _cache_auth_context can't insert a colliding
        # entry mid-cleanup.
        async with _auth_cache_lock:
            _auth_cache.pop(ck, None)
            if ctx.agent_id is not None:
                agent_keys = _auth_cache_by_agent.get(str(ctx.agent_id))
                if agent_keys is not None:
                    agent_keys.discard(ck)
                    if not agent_keys:
                        _auth_cache_by_agent.pop(str(ctx.agent_id), None)

    # 2. Prefix-based O(1) lookup + verify, via the shared ApiKeyHasher. The
    # PR #17 SQLAlchemy tenant filter would otherwise zero-out these SELECTs —
    # auth runs BEFORE the tenant scope is established (we look up the agent
    # precisely to learn its org_id), so bypass the filter for the auth queries.
    from backend.core.tenancy import bypass_tenant_filter

    hasher = _get_hasher()

    async def _fetch_active_by_prefix(prefix: str) -> AgentRegistry | None:
        with bypass_tenant_filter():
            result = await db.execute(
                select(AgentRegistry).where(
                    AgentRegistry.api_key_prefix == prefix,
                    AgentRegistry.status == "active",
                )
            )
            return result.scalar_one_or_none()

    async def _on_rehash(agent: AgentRegistry, new_hash: str) -> None:
        # Verify-then-upgrade: a key that verified under a legacy bcrypt hash
        # (or a retired pepper) gets its stored hash rewritten to the active
        # HMAC scheme. One-shot per key; never blocks the auth result.
        agent.api_key_hash = new_hash
        with bypass_tenant_filter():
            await db.flush()

    ctx = await hasher.authenticate(
        api_key,
        fetch_active_by_prefix=_fetch_active_by_prefix,
        build_context=_build_auth_context,
        on_rehash=_on_rehash,
    )
    if ctx is not None:
        # P1 #8 lock-protected cache write (avoids the thundering-herd-on-
        # rotation concurrency bug a plain dict assignment had).
        await _cache_auth_context(ck, ctx, time.monotonic() + _AUTH_CACHE_TTL)
        # Defer last_active_at to a short-lived session — under bulk parallel
        # writes (e.g. 16-worker LME ingest) holding this update inside the
        # request transaction pins the agent row until commit and exhausts the
        # connection pool. Same reasoning as gatekeeper._increment_agent_stats.
        await _bg_touch_last_active(ctx.agent_id)
        return ctx

    # 3. Fallback for legacy keys written before the prefix column existed
    # (api_key_prefix IS NULL) — the prefix lookup above can't find them. Scan
    # active null-prefix agents, verify via the hasher (which handles legacy
    # bcrypt), then backfill the prefix and upgrade the hash to HMAC.
    with bypass_tenant_filter():
        result = await db.execute(
            select(AgentRegistry).where(
                AgentRegistry.status == "active",
                AgentRegistry.api_key_prefix.is_(None),
            )
        )
        agents = result.scalars().all()
    for agent in agents:
        res = hasher.verify(api_key, agent.api_key_hash)
        if res.matched:
            # One-shot writes per agent (first request after the prefix column
            # landed), so it's fine to keep them in the request transaction.
            agent.api_key_prefix = _compute_key_prefix(api_key)
            if res.needs_upgrade:
                agent.api_key_hash = hasher.hash(api_key)
            await db.flush()
            await _bg_touch_last_active(agent.agent_id)

            ctx = _build_auth_context(agent)
            await _cache_auth_context(ck, ctx, time.monotonic() + _AUTH_CACHE_TTL)
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
    org_id = agent.org_id or settings.tenant_legacy_sentinel

    return AuthContext(
        user_id=agent.user_id,
        agent_id=agent.agent_id,
        agent_name=agent.agent_name,
        scopes=scopes,
        auth_method="api_key",
        org_id=org_id,
    )
