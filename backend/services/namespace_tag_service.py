"""
Kemory — second-tier namespace tag resolution (S9N-6612).

Multi-stage pipeline, stage 2. Stage 1 (allocator → matcher) decides WHICH
NAMESPACE an item lives in and is untouched. This service then decides which
SEGMENT of that namespace the item belongs to — same entities / era → an
existing tag; divergent → a new one. Tags render as ``namespace:tag`` and
segment the timeline/explorer view only; search and recall keep spanning the
whole parent namespace.

Why entity-first: the canonical misfiled namespace
(``project:ai-expansion-strategy``) mixes Builder.ai's Insight-deal chats, EY
and Al Ansari client work with SeKondBrain strategy. All of it shares
corporate-AI vocabulary, so embedding distance under-separates; the
discriminators are the anchor ENTITIES (builder.ai / insight partners vs
sekondbrain vs ey) and, once S9N-6613 dates flow, ERA. Era is therefore a
score *boost*, never a gate — the legacy backlog has no content dates until
the extension's repopulation sweep lands them.

Shape stolen deliberately from ``namespace_llm_resolver`` (measured there):
the LLM only ever NAMES a segment from the item's own content — it is never
shown a candidate list to pick from (anchored on a list, small models
rationalise the biggest option at false confidence 0.9). Deterministic code
does all matching: entity overlap, cosine to per-tag centroids, era windows,
and fuzzy slug matching of LLM proposals against existing profiles.

In Community Edition, optional segment naming uses the user's configured
Groq key. Without Groq, the resolver degrades to deterministic profile
matching and leaves unmatched items untagged for the retro backfill tool.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import structlog
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config.settings import settings
from backend.models.ai_chat import AIChat
from backend.models.memory import Memory
from backend.models.namespace_tag import NamespaceTag

logger = structlog.get_logger(__name__)

# ─── Thresholds (start from chat_classifier's calibration) ──────────
# Accept a profile on embedding evidence alone.
TAG_ACCEPT_SCORE = 0.60
# Runner-up must trail by at least this much (ambiguity → LLM / untagged).
TAG_ACCEPT_GAP = 0.08
# Entity-first shortcut: one shared anchor entity lowers the bar — entities
# are exactly what embeddings blur here.
TAG_ENTITY_SCORE = 0.50
# Per-entity score bonus, capped.
ENTITY_BONUS_PER_TERM = 0.15
ENTITY_BONUS_CAP = 0.30
# Era boost/penalty (occurred_at vs the profile's observed window ± pad).
ERA_PAD = timedelta(days=45)
ERA_FAR = timedelta(days=180)
ERA_BONUS = 0.05
ERA_PENALTY = -0.05
# Fuzzy slug-match threshold for LLM proposals against existing tags.
PROPOSAL_SLUG_MATCH = 0.85
# Cap on stored anchor terms per profile.
MAX_ENTITY_TERMS = 24

_LLM_TIMEOUT_S = 25.0

_GENERIC_SEGMENTS = frozenset(
    {"general", "misc", "miscellaneous", "notes", "chat", "chats", "other", "stuff", "various", "unsorted"}
)


# ─── Pure scoring helpers (unit-tested; scripts reuse them) ─────────


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        return vec
    return [x / norm for x in vec]


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    """Dot product of L2-normalised vectors (0.0 when either is missing)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True))


def _fuzzy_ratio(a: str, b: str) -> float:
    from difflib import SequenceMatcher

    return SequenceMatcher(None, a, b).ratio()


def extract_known_entities(text: str, known_terms: set[str]) -> set[str]:
    """Which of the profiles' anchor entities appear in this text?

    Deterministic substring matching on lowercased text — NEW entities are
    the LLM's job (at proposal time); this only recognises ones we already
    track, so it stays cheap enough for the ingest path.
    """
    if not text or not known_terms:
        return set()
    lowered = text.lower()
    return {t for t in known_terms if t and t in lowered}


@dataclass(frozen=True)
class ScoreParts:
    embedding: float
    entity_overlap: int
    era: float

    @property
    def total(self) -> float:
        return self.embedding + min(ENTITY_BONUS_CAP, ENTITY_BONUS_PER_TERM * self.entity_overlap) + self.era


def score_profile(
    *,
    embedding: list[float] | None,
    item_entities: set[str],
    occurred_at: datetime | None,
    profile: NamespaceTag,
) -> ScoreParts:
    """Score one item against one tag profile. Pure."""
    emb = cosine(embedding, profile.centroid)

    overlap = 0
    if profile.entity_terms:
        overlap = len(item_entities & {str(t).lower() for t in profile.entity_terms})

    era = 0.0
    if occurred_at is not None and profile.occurred_from and profile.occurred_to:
        lo = profile.occurred_from - ERA_PAD
        hi = profile.occurred_to + ERA_PAD
        if lo <= occurred_at <= hi:
            era = ERA_BONUS
        elif occurred_at < profile.occurred_from - ERA_FAR or occurred_at > profile.occurred_to + ERA_FAR:
            era = ERA_PENALTY

    return ScoreParts(embedding=emb, entity_overlap=overlap, era=era)


@dataclass
class TagDecision:
    """Outcome of one resolution. ``tag`` is None when the item stays untagged."""

    tag: str | None
    created: bool = False
    reason: str = ""
    score: float | None = None
    profile: NamespaceTag | None = field(default=None, repr=False)


def pick_profile(
    *,
    embedding: list[float] | None,
    item_entities: set[str],
    occurred_at: datetime | None,
    profiles: list[NamespaceTag],
) -> TagDecision:
    """Deterministic matching half: best profile or None. Pure."""
    if not profiles:
        return TagDecision(tag=None, reason="no_profiles")

    scored = sorted(
        (
            (
                score_profile(
                    embedding=embedding,
                    item_entities=item_entities,
                    occurred_at=occurred_at,
                    profile=p,
                ),
                p,
            )
            for p in profiles
        ),
        key=lambda sp: sp[0].total,
        reverse=True,
    )
    best_parts, best = scored[0]
    runner_total = scored[1][0].total if len(scored) > 1 else 0.0
    gap = best_parts.total - runner_total

    # Entity-first: a shared anchor entity is strong, specific evidence.
    if best_parts.entity_overlap >= 1 and best_parts.total >= TAG_ENTITY_SCORE:
        return TagDecision(
            tag=best.tag,
            reason=f"entity_match(overlap={best_parts.entity_overlap})",
            score=best_parts.total,
            profile=best,
        )
    if best_parts.total >= TAG_ACCEPT_SCORE and gap >= TAG_ACCEPT_GAP:
        return TagDecision(tag=best.tag, reason="embedding_match", score=best_parts.total, profile=best)
    return TagDecision(tag=None, reason=f"no_fit(best={best_parts.total:.3f},gap={gap:.3f})")


# ─── LLM proposal (name a segment; never pick from a list) ──────────


@dataclass(frozen=True)
class SegmentProposal:
    label: str
    slug: str
    entities: tuple[str, ...]


def _build_segment_prompt(sample: str) -> str:
    return (
        "You are labelling ONE item that already lives inside a project "
        "namespace. Name the specific real-world context it belongs to — the "
        "company/client/deal/product storyline, not the generic subject.\n"
        'Return ONLY a JSON object: {"label": <3-6 word segment name>, '
        '"slug": <kebab-case>, "entities": [<up to 4 lowercase anchor '
        "entities: companies, orgs, products, people>]}.\n"
        "Anchor on WHO/WHAT the item is about (e.g. 'Builder.ai Insight "
        "bridge financing' with entities ['builder.ai','insight partners']), "
        "never a generic label like 'ai strategy'.\n\nITEM:\n" + sample[:4000]
    )


async def propose_segment(sample: str, *, ref: str, attempts: int = 2) -> SegmentProposal | None:
    """Ask community Groq to name this item's segment, or decline safely."""
    from backend.services.namespace_resolver import _slugify
    from kemory.llm import assistant_text, chat_completion

    if not sample.strip():
        return None

    payload = {
        "model": os.environ.get("KMV_SEGMENT_MODEL", settings.kmv_synthesis_model),
        "messages": [{"role": "user", "content": _build_segment_prompt(sample)}],
        "max_tokens": 120,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    for attempt in range(max(1, attempts)):
        if attempt:
            await asyncio.sleep(0.5 * (2 ** (attempt - 1)))
        try:
            result = await chat_completion(payload, timeout_seconds=_LLM_TIMEOUT_S)
        except Exception as exc:
            logger.debug("namespace_tag.groq_failed", ref=ref, error=str(exc)[:120])
            continue
        try:
            text = assistant_text(result)
            data = json.loads(text) if text else None
        except Exception as exc:
            logger.debug("namespace_tag.llm_parse_failed", ref=ref, error=str(exc)[:120])
            continue
        if not isinstance(data, dict):
            continue
        label = str(data.get("label", "")).strip()
        slug = _slugify(str(data.get("slug", "")) or label)[:120]
        if not slug or slug in _GENERIC_SEGMENTS or label.lower() in _GENERIC_SEGMENTS:
            logger.info("namespace_tag.rejected_generic_segment", ref=ref, label=label)
            return None
        raw_entities = data.get("entities") or []
        entities = tuple(str(e).strip().lower() for e in raw_entities if str(e).strip())[:4]
        return SegmentProposal(label=label[:200], slug=slug, entities=entities)

    logger.debug("namespace_tag.no_proposal", ref=ref)
    return None


def match_proposal(proposal: SegmentProposal, profiles: list[NamespaceTag]) -> NamespaceTag | None:
    """Deterministically match an LLM proposal to an existing profile —
    shared anchor entity, or a near-identical slug/label."""
    prop_entities = set(proposal.entities)
    for p in profiles:
        if prop_entities and p.entity_terms and prop_entities & {str(t).lower() for t in p.entity_terms}:
            return p
        if _fuzzy_ratio(proposal.slug, p.tag) >= PROPOSAL_SLUG_MATCH:
            return p
        if _fuzzy_ratio(proposal.label.lower(), (p.label or "").lower()) >= PROPOSAL_SLUG_MATCH:
            return p
    return None


# ─── Profile CRUD / running updates ─────────────────────────────────


async def load_profiles(user_id: uuid.UUID, namespace: str, db: AsyncSession) -> list[NamespaceTag]:
    rows = (
        await db.execute(
            select(NamespaceTag).where(
                NamespaceTag.user_id == user_id,
                NamespaceTag.namespace == namespace,
                NamespaceTag.active.is_(True),
            )
        )
    ).scalars()
    return list(rows)


def _update_profile_stats(
    profile: NamespaceTag,
    *,
    embedding: list[float] | None,
    entities: set[str],
    occurred_at: datetime | None,
) -> None:
    """Fold one accepted member into the profile (running centroid, era
    window, anchor terms, count). Mutates the ORM row in place."""
    n = profile.member_count or 0
    if embedding:
        if profile.centroid:
            merged = [(c * n + e) / (n + 1) for c, e in zip(profile.centroid, embedding, strict=False)]
            profile.centroid = _l2_normalize(merged)
        else:
            profile.centroid = _l2_normalize(list(embedding))
    if entities:
        existing = [str(t).lower() for t in (profile.entity_terms or [])]
        for term in sorted(entities):
            if term not in existing and len(existing) < MAX_ENTITY_TERMS:
                existing.append(term)
        profile.entity_terms = existing
    if occurred_at is not None:
        if profile.occurred_from is None or occurred_at < profile.occurred_from:
            profile.occurred_from = occurred_at
        if profile.occurred_to is None or occurred_at > profile.occurred_to:
            profile.occurred_to = occurred_at
    profile.member_count = n + 1


async def create_profile(
    *,
    user_id: uuid.UUID,
    org_id: str,
    namespace: str,
    proposal: SegmentProposal,
    embedding: list[float] | None,
    occurred_at: datetime | None,
    db: AsyncSession,
    source: str = "auto",
) -> NamespaceTag:
    """Create a tag profile from an accepted proposal (idempotent on slug —
    a concurrent creator wins and we fold into it)."""
    existing = (
        await db.execute(
            select(NamespaceTag).where(
                NamespaceTag.user_id == user_id,
                NamespaceTag.namespace == namespace,
                NamespaceTag.tag == proposal.slug,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        _update_profile_stats(
            existing, embedding=embedding, entities=set(proposal.entities), occurred_at=occurred_at
        )
        return existing

    profile = NamespaceTag(
        user_id=user_id,
        org_id=org_id,
        namespace=namespace,
        tag=proposal.slug,
        label=proposal.label,
        entity_terms=sorted(set(proposal.entities)) or None,
        centroid=_l2_normalize(list(embedding)) if embedding else None,
        member_count=1,
        occurred_from=occurred_at,
        occurred_to=occurred_at,
        source=source,
    )
    db.add(profile)
    await db.flush()
    return profile


# ─── Chat resolution (the primary ingest path) ──────────────────────


async def _embed_text(text: str) -> list[float] | None:
    try:
        from kemory.embeddings.encoder import encode

        vec = await asyncio.to_thread(encode, text[:2000])
        return list(vec) if vec is not None else None
    except Exception as exc:  # encoder outage → degrade to entity/LLM signals
        logger.debug("namespace_tag.embed_failed", error=str(exc)[:120])
        return None


async def resolve_tag_for_chat(chat: AIChat, db: AsyncSession) -> TagDecision:
    """Stage-2 resolution for one chat. Stamps chat.namespace_tag, updates or
    creates the profile, and cascades the tag to already-bridged memories
    that are still untagged. Caller owns the transaction."""
    from backend.services.chat_classifier import _load_chat_sample, is_pending_namespace

    if not settings.namespace_tags_enabled:
        return TagDecision(tag=None, reason="disabled")
    # Inbox/staging chats aren't segmented — they haven't been routed yet
    # (S9N-6377 taught the bridge the same restraint).
    if is_pending_namespace(chat.namespace):
        return TagDecision(tag=None, reason="pending_namespace")

    profiles = await load_profiles(chat.user_id, chat.namespace, db)
    known_terms = {str(t).lower() for p in profiles for t in (p.entity_terms or [])}

    sample = await _load_chat_sample(chat, db)
    text = f"{chat.title or ''}\n{sample}"
    item_entities = extract_known_entities(text, known_terms)
    embedding = await _embed_text(text)
    occurred = chat.captured_at

    decision = pick_profile(
        embedding=embedding,
        item_entities=item_entities,
        occurred_at=occurred,
        profiles=profiles,
    )

    if decision.tag is None and decision.reason != "disabled":
        proposal = await propose_segment(text, ref=str(chat.chat_id))
        if proposal is not None:
            matched = match_proposal(proposal, profiles)
            if matched is not None:
                decision = TagDecision(tag=matched.tag, reason="llm_matched_existing", profile=matched)
            else:
                profile = await create_profile(
                    user_id=chat.user_id,
                    org_id=chat.org_id,
                    namespace=chat.namespace,
                    proposal=proposal,
                    embedding=embedding,
                    occurred_at=occurred,
                    db=db,
                )
                # create_profile already folded this item into the stats.
                chat.namespace_tag = profile.tag
                await _cascade_tag_to_bridged(chat, profile.tag, db)
                logger.info(
                    "namespace_tag.created",
                    chat_id=str(chat.chat_id),
                    namespace=chat.namespace,
                    tag=profile.tag,
                )
                return TagDecision(tag=profile.tag, created=True, reason="llm_new_segment", profile=profile)

    if decision.tag is not None and decision.profile is not None:
        _update_profile_stats(
            decision.profile,
            embedding=embedding,
            entities=item_entities,
            occurred_at=occurred,
        )
        chat.namespace_tag = decision.tag
        await _cascade_tag_to_bridged(chat, decision.tag, db)
        logger.info(
            "namespace_tag.assigned",
            chat_id=str(chat.chat_id),
            namespace=chat.namespace,
            tag=decision.tag,
            reason=decision.reason,
        )
    return decision


async def _cascade_tag_to_bridged(chat: AIChat, tag: str, db: AsyncSession) -> None:
    """Bridged memories follow their chat's segment; only fills NULLs so a
    later re-resolution never flip-flops rows a human already touched."""
    await db.execute(
        update(Memory)
        .where(
            Memory.source_chat_id == chat.chat_id,
            Memory.namespace == chat.namespace,
            Memory.namespace_tag.is_(None),
        )
        .values(namespace_tag=tag)
    )


# ─── Read API (GET /namespaces/{ns}/tags) ───────────────────────────


class NamespaceTagInfo(BaseModel):
    """One segment of a namespace, centroid omitted (internal math only)."""

    tag: str
    label: str
    description: str | None = None
    entity_terms: list[str] | None = None
    member_count: int = 0
    occurred_from: str | None = None
    occurred_to: str | None = None
    source: str = "auto"


async def list_namespace_tags(
    user_id: uuid.UUID,
    namespace: str,
    db: AsyncSession,
) -> list[NamespaceTagInfo]:
    """Return active local-user tag profiles, largest segment first."""
    profiles = await load_profiles(user_id, namespace, db)
    profiles.sort(key=lambda p: p.member_count or 0, reverse=True)
    return [
        NamespaceTagInfo(
            tag=p.tag,
            label=p.label,
            description=p.description,
            entity_terms=[str(t) for t in (p.entity_terms or [])] or None,
            member_count=p.member_count or 0,
            occurred_from=p.occurred_from.isoformat() if p.occurred_from else None,
            occurred_to=p.occurred_to.isoformat() if p.occurred_to else None,
            source=p.source,
        )
        for p in profiles
    ]


# ─── Fire-and-forget ingest hook (chat_memory_bridge pattern) ───────

_inflight: set[asyncio.Task] = set()


async def _run_tag_resolution(chat_id: uuid.UUID) -> None:
    from backend.core.database import _get_session_factory
    from backend.core.tenancy import bypass_tenant_filter

    factory = _get_session_factory()
    async with factory() as db:
        with bypass_tenant_filter():
            chat = (await db.execute(select(AIChat).where(AIChat.chat_id == chat_id))).scalar_one_or_none()
            if chat is None or chat.invalid_at is not None:
                return
            # Re-resolution keeps the existing tag sticky: once segmented,
            # a chat only moves via promotion/manual action.
            if chat.namespace_tag:
                return
            await resolve_tag_for_chat(chat, db)
            await db.commit()


def schedule_tag_resolution_safe(chat_id: uuid.UUID) -> None:
    """Fire-and-forget stage-2 hook; never raises into the ingest path."""
    if not settings.namespace_tags_enabled:
        return
    try:
        task = asyncio.get_running_loop().create_task(_run_tag_resolution(chat_id))
        _inflight.add(task)
        task.add_done_callback(_inflight.discard)
    except RuntimeError:
        logger.debug("namespace_tag.no_running_loop", chat_id=str(chat_id))
    except Exception as exc:
        logger.warning("namespace_tag.schedule_failed", chat_id=str(chat_id), error=str(exc))
