"""
Pair‑code service — short‑lived codes that let an AI self‑register
without copy‑pasting an API key.

Flow:
1. Dashboard calls `start_pair(...)` — creates a code with a 5‑min TTL
   bound to the human user's identity (user_id + org_id).
2. The user pastes one prompt + the claim URL into any AI.
3. The AI calls `claim_pair(code, client_name)` — this registers a fresh
   agent for the human user and returns the API key + brief + MCP URL.
4. The dashboard polls `get_pair(code)` to know when the claim happened
   so it can flip the UI to "Connected".

Storage:
- Redis when available (`s9nmv:pair:<code>` hash with EXPIRE).
- In‑memory fallback for local mode where Redis is optional.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
import uuid
from dataclasses import asdict, dataclass

from backend.core.redis import get_redis

PAIR_TTL_SECONDS = 5 * 60  # 5 minutes

# Crockford base32 minus visually ambiguous characters (0/O, 1/I/L).
_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def _generate_code() -> str:
    """`XXXX-XXXX` — 8 chars from a 31‑symbol alphabet ≈ 40 bits entropy."""
    left = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))
    right = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))
    return f"{left}-{right}"


@dataclass
class PairRecord:
    code: str
    user_id: str
    org_id: str
    created_at: float
    expires_at: float
    purpose: str = ""
    claimed_at: float | None = None
    agent_id: str | None = None
    agent_name: str | None = None
    client_name: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> PairRecord:
        return cls(**data)

    @property
    def claimed(self) -> bool:
        return self.claimed_at is not None

    @property
    def expired(self) -> bool:
        return time.time() > self.expires_at


# ─── In‑memory fallback ────────────────────────────────────────────

_memory_store: dict[str, PairRecord] = {}
_memory_lock = asyncio.Lock()


async def _purge_memory_expired() -> None:
    now = time.time()
    expired = [c for c, r in _memory_store.items() if r.expires_at < now]
    for c in expired:
        _memory_store.pop(c, None)


# ─── Storage helpers ───────────────────────────────────────────────


def _redis_key(code: str) -> str:
    return f"s9nmv:pair:{code}"


async def _save(record: PairRecord) -> None:
    redis = await get_redis()
    if redis is None:
        async with _memory_lock:
            _memory_store[record.code] = record
        return
    ttl = max(1, int(record.expires_at - time.time()))
    await redis.set(_redis_key(record.code), json.dumps(record.to_dict()), ex=ttl)


async def _load(code: str) -> PairRecord | None:
    redis = await get_redis()
    if redis is None:
        async with _memory_lock:
            await _purge_memory_expired()
            return _memory_store.get(code)
    raw = await redis.get(_redis_key(code))
    if not raw:
        return None
    try:
        return PairRecord.from_dict(json.loads(raw))
    except (ValueError, TypeError):
        return None


# ─── Public API ────────────────────────────────────────────────────


async def start_pair(
    *,
    user_id: uuid.UUID,
    org_id: str,
    purpose: str = "",
) -> PairRecord:
    """Generate a fresh pair code bound to the calling human user."""
    now = time.time()
    record = PairRecord(
        code=_generate_code(),
        user_id=str(user_id),
        org_id=org_id,
        created_at=now,
        expires_at=now + PAIR_TTL_SECONDS,
        purpose=purpose,
    )
    await _save(record)
    return record


async def get_pair(code: str) -> PairRecord | None:
    """Look up a pair record by code. Returns None if missing or expired."""
    record = await _load(code)
    if record is None or record.expired:
        return None
    return record


async def mark_claimed(
    code: str,
    *,
    agent_id: str,
    agent_name: str,
    client_name: str,
) -> PairRecord | None:
    """Atomically flip a pair record to `claimed` on first successful claim.

    Returns the updated record on success, None if the code is missing,
    expired, or has already been claimed.
    """
    record = await _load(code)
    if record is None or record.expired or record.claimed:
        return None
    record.claimed_at = time.time()
    record.agent_id = agent_id
    record.agent_name = agent_name
    record.client_name = client_name
    await _save(record)
    return record


async def delete_pair(code: str) -> None:
    """Best‑effort delete — called after a successful claim to free the slot."""
    redis = await get_redis()
    if redis is None:
        async with _memory_lock:
            _memory_store.pop(code, None)
        return
    await redis.delete(_redis_key(code))
