"""
backend/services/namespace_matcher.py
======================================

Related-namespace detector. Used at memory-create time to avoid
fragmentation between near-duplicate namespaces like ``user_prefs`` /
``preferences`` / ``user:preferences``.

Resolution strategy (in order):

1. **Normalize** the requested namespace (lowercase, strip non-alphanumeric
   except ``:`` and ``_``). If the normalized form exactly matches an
   existing namespace, return ``REUSE`` for that one.
2. **Semantic similarity** via the shared bge-small-en-v1.5 encoder
   (``memory_vault.embeddings.encoder``): embed ``name + description``
   for the incoming namespace and every existing one, cosine-compare.
3. **Fuzzy fallback** (SequenceMatcher ratio) — runs cheaply alongside
   the embedder and gets taken whenever the embedder is unavailable or
   returns a low score but the strings are close.

Thresholds (both contribute; best score wins):

    score >= 0.90  ⇒ AUTO_REDIRECT — silently reuse the existing namespace,
                    merge description, write a related_namespaces entry.
    0.60 <= score < 0.90 ⇒ SUGGEST — caller raises 409 with the candidates.
    score < 0.60   ⇒ CREATE_NEW — create as requested.

If no existing namespaces are found, the result is always ``CREATE_NEW``.
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from enum import Enum
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.memory import Memory
from backend.models.namespace_policy import NamespacePolicy

logger = logging.getLogger(__name__)


AUTO_REDIRECT_THRESHOLD = 0.90
# SUGGEST_THRESHOLD calibration:
#   • 0.60 (original) false-positives on `alice:private` vs `alice:workspace`
#     (0.64) — distinct buckets, not a typo.
#   • 0.75 still false-positives on long shared-prefix names like
#     `lme_bench_mr-002` vs `lme_bench_ie-001` (0.80) — both names share
#     `lme_bench_` so the character-overlap ratio runs hot.
#   • 0.85 lets shared-prefix sibling namespaces through while still
#     catching the genuine typos we care about:
#       - `alice:privte`  vs `alice:private`  → 0.96
#       - `user_prefs`    vs `userprefs`      → 0.95
#       - `lme_bench_001` vs `lme_bench_002`  → 0.93
#     If a real typo dips into 0.75–0.85 it's recoverable: the user
#     creates a sibling namespace; the matcher will REUSE it on the next
#     write, and the namespace dashboard surfaces siblings for manual merge.
SUGGEST_THRESHOLD = 0.85


class ResolutionAction(str, Enum):
    REUSE = "reuse"              # exact match after normalization
    AUTO_REDIRECT = "auto_redirect"  # >= 0.90 similarity
    SUGGEST = "suggest"          # 0.60..0.90 — return 409 to caller
    CREATE_NEW = "create_new"    # < 0.60 or no existing namespaces


@dataclass
class NamespaceCandidate:
    namespace: str
    similarity: float


@dataclass
class NamespaceResolution:
    action: ResolutionAction
    # Chosen namespace: for REUSE/AUTO_REDIRECT this is the existing one;
    # for CREATE_NEW this is the normalized requested name.
    namespace: str
    candidates: list[NamespaceCandidate]
    normalized_requested: str


_NORMALIZE_RE = re.compile(r"[^a-z0-9:_]+")


def normalize(ns: str) -> str:
    return _NORMALIZE_RE.sub("", ns.strip().lower())


def _fuzzy_ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _cosine(vec_a, vec_b) -> float:
    import math

    dot = sum(x * y for x, y in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(x * x for x in vec_a))
    norm_b = math.sqrt(sum(x * x for x in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _embed(text: str):
    """Reuse the same encoder the rest of the pipeline uses."""
    from memory_vault.embeddings.encoder import encode
    return encode(text)


async def _existing_namespaces(
    user_id: uuid.UUID, db: AsyncSession,
) -> list[tuple[str, Optional[str]]]:
    """
    Return [(namespace, description)] for every active namespace the user has.

    Pulls names from both Memory (authoritative set of namespaces in use) and
    NamespacePolicy (so a policy created without any memories is still
    considered).
    """
    mem_rows = (
        await db.execute(
            select(Memory.namespace)
            .where(
                Memory.user_id == user_id,
                Memory.invalid_at.is_(None),
            )
            .group_by(Memory.namespace)
        )
    ).all()

    # Scope policy lookup to this user. NamespacePolicy.created_by is
    # nullable for legacy rows seeded before the policy was per-user — those
    # are treated as global/shared (anyone can see them as suggestion
    # candidates). Without this filter, user A's matcher would surface
    # user B's namespaces in the suggestion list AND raise spurious 409s
    # on names like "alice:private" because a different user's
    # "alice:workspace" scored 0.75 fuzzy.
    pol_rows = (
        await db.execute(
            select(NamespacePolicy.namespace, NamespacePolicy.description)
            .where(or_(
                NamespacePolicy.created_by == user_id,
                NamespacePolicy.created_by.is_(None),
            ))
        )
    ).all()

    desc_by_ns: dict[str, Optional[str]] = {}
    for ns, desc in pol_rows:
        desc_by_ns[ns] = desc
    for (ns,) in mem_rows:
        desc_by_ns.setdefault(ns, None)
    return list(desc_by_ns.items())


def _best_score(
    requested: str,
    requested_desc: Optional[str],
    existing: list[tuple[str, Optional[str]]],
) -> list[NamespaceCandidate]:
    """Score every candidate with the max of (embedding cosine, fuzzy ratio)."""
    req_text = f"{requested} {requested_desc or ''}".strip()
    req_vec = None
    try:
        req_vec = _embed(req_text)
    except Exception as exc:
        logger.debug("namespace_matcher.embed_unavailable", extra={"error": str(exc)})

    scored: list[NamespaceCandidate] = []
    for existing_ns, existing_desc in existing:
        fuzzy = _fuzzy_ratio(normalize(requested), normalize(existing_ns))
        semantic = 0.0
        if req_vec is not None:
            try:
                ex_text = f"{existing_ns} {existing_desc or ''}".strip()
                ex_vec = _embed(ex_text)
                semantic = _cosine(req_vec, ex_vec)
            except Exception:
                semantic = 0.0
        # Decouple fuzzy and semantic signals.
        #
        # Fuzzy ratio is a typo detector — it reliably catches
        # `user_prefs` vs `userprefs` style collisions and bottoms out at
        # ~0.3 for unrelated names. So we trust it across the full 0.75–1.0
        # range (above SUGGEST_THRESHOLD).
        #
        # Semantic cosine on a generic sentence-transformers embedding has a
        # high noise floor for short namespace strings — any two short
        # tokens easily land at 0.7–0.85 even when conceptually unrelated
        # (`lme_bench_mr-002` vs `lme_bench_ie-001` ≈ 0.86, `shared` vs
        # `alice:private` ≈ 0.64). At those middle scores semantic is
        # noise, not signal. We therefore only let semantic *raise* the
        # final score when it's strong enough to AUTO_REDIRECT
        # (≥ AUTO_REDIRECT_THRESHOLD). That way semantic can rescue real
        # conceptual aliases (`user:preferences` vs `user_prefs` ≈ 0.93)
        # but cannot push a fuzzy mismatch into the SUGGEST 409 band.
        if semantic >= AUTO_REDIRECT_THRESHOLD:
            score = max(fuzzy, semantic)
        else:
            score = fuzzy
        scored.append(NamespaceCandidate(existing_ns, score))

    scored.sort(key=lambda c: c.similarity, reverse=True)
    return scored


async def resolve_namespace(
    user_id: uuid.UUID,
    requested: str,
    description: Optional[str],
    db: AsyncSession,
) -> NamespaceResolution:
    normalized = normalize(requested)
    existing = await _existing_namespaces(user_id, db)

    # Exact match after normalization
    for ns, _desc in existing:
        if normalize(ns) == normalized:
            return NamespaceResolution(
                action=ResolutionAction.REUSE,
                namespace=ns,
                candidates=[NamespaceCandidate(ns, 1.0)],
                normalized_requested=normalized,
            )

    if not existing:
        return NamespaceResolution(
            action=ResolutionAction.CREATE_NEW,
            namespace=requested,
            candidates=[],
            normalized_requested=normalized,
        )

    scored = _best_score(requested, description, existing)
    top = scored[0]

    if top.similarity >= AUTO_REDIRECT_THRESHOLD:
        return NamespaceResolution(
            action=ResolutionAction.AUTO_REDIRECT,
            namespace=top.namespace,
            candidates=scored[:5],
            normalized_requested=normalized,
        )

    if top.similarity >= SUGGEST_THRESHOLD:
        return NamespaceResolution(
            action=ResolutionAction.SUGGEST,
            namespace=requested,
            candidates=[c for c in scored if c.similarity >= SUGGEST_THRESHOLD][:5],
            normalized_requested=normalized,
        )

    return NamespaceResolution(
        action=ResolutionAction.CREATE_NEW,
        namespace=requested,
        candidates=[],
        normalized_requested=normalized,
    )


class RelatedNamespaceConflict(Exception):
    """Raised when the matcher wants to surface a 409 to the caller.

    The router catches this, formats the candidates, and returns HTTP 409
    with `{suggested: [...], force_create_param: "allow_duplicate=true"}`.
    """

    def __init__(self, requested: str, candidates: list[NamespaceCandidate]) -> None:
        self.requested = requested
        self.candidates = candidates
        super().__init__(
            f"Namespace '{requested}' is similar to existing namespaces: "
            + ", ".join(f"{c.namespace} ({c.similarity:.2f})" for c in candidates)
        )

    def to_dict(self) -> dict:
        return {
            "error": "related_namespace",
            "message": (
                f"Namespace '{self.requested}' looks similar to existing "
                f"namespace(s). Pick one, or pass allow_duplicate=true to "
                f"force creation."
            ),
            "requested": self.requested,
            "suggested": [
                {"namespace": c.namespace, "similarity": round(c.similarity, 3)}
                for c in self.candidates
            ],
            "force_create_param": "allow_duplicate=true",
        }


async def apply_resolution(
    resolution: NamespaceResolution,
    description: Optional[str],
    db: AsyncSession,
    user_id: uuid.UUID,
) -> None:
    """Persist side effects of a REUSE/AUTO_REDIRECT resolution.

    - AUTO_REDIRECT: merge description into the existing policy's description,
      append a related_namespaces entry recording the redirect.
    - REUSE / CREATE_NEW: no side effect here — NamespacePolicy rows are
      created lazily by the L3.1 compression pipeline when the namespace
      first gets its rollup, so we don't need to eagerly insert one.
    """
    if resolution.action != ResolutionAction.AUTO_REDIRECT:
        return

    ns = resolution.namespace
    existing = (
        await db.execute(
            select(NamespacePolicy).where(NamespacePolicy.namespace == ns)
        )
    ).scalar_one_or_none()

    if existing is not None:
        if description and (not existing.description or description not in (existing.description or "")):
            base = (existing.description or "").strip()
            existing.description = (base + ("\n" if base else "") + description)[:500]
        related = list(existing.related_namespaces or [])
        top = resolution.candidates[0] if resolution.candidates else None
        related.append({
            "namespace": resolution.normalized_requested,
            "similarity": round(top.similarity, 3) if top else None,
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "action": "auto_redirect",
        })
        existing.related_namespaces = related[-20:]
