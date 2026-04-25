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
_AUTH_CACHE_TTL = 300  # seconds


class AuthContext(BaseModel):
    """Represents the authenticated identity for a request."""
    user_id: uuid.UUID
    agent_id: uuid.UUID | None = None
    agent_name: str = ""
    scopes: list[str] = []
    auth_method: str  # "jwt", "api_key", or "keycloak"


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
) -> str:
    """
    Create a signed JWT access token for an authenticated agent.

    Args:
        agent_id: The agent's UUID
        user_id: The owning user's UUID
        agent_name: Human-readable agent name
        scopes: List of granted scope strings
        expires_delta: Custom expiry (default: settings.jwt_expiry_minutes)

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
        del _auth_cache[ck]

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
        _auth_cache[ck] = (ctx, time.monotonic() + _AUTH_CACHE_TTL)
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
                _auth_cache[ck] = (ctx, time.monotonic() + _AUTH_CACHE_TTL)
                return ctx

    return None


def _build_auth_context(agent: AgentRegistry) -> AuthContext:
    """Extract AuthContext from an AgentRegistry record."""
    scopes = []
    if agent.declared_scopes:
        for scope_obj in agent.declared_scopes:
            if isinstance(scope_obj, dict) and "scope" in scope_obj:
                scopes.append(scope_obj["scope"])
            elif isinstance(scope_obj, str):
                scopes.append(scope_obj)

    return AuthContext(
        user_id=agent.user_id,
        agent_id=agent.agent_id,
        agent_name=agent.agent_name,
        scopes=scopes,
        auth_method="api_key",
    )
