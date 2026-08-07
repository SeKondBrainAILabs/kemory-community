#!/usr/bin/env python
"""
S9N-6612 — retro second-tier tagging: segment existing namespaces into tags.

Dry-run by default: prints a CSV report of every item's proposed segment plus
per-namespace misfile candidates, and writes NOTHING. ``--apply`` creates tag
profiles and stamps ``namespace_tag`` on chats and memories (NULLs only).

Algorithm (propose-then-match at scale — no clustering thresholds to tune):
  1. Per chat / direct memory: ask the LLM to NAME the item's segment from
     its own content (``namespace_tag_service.propose_segment``; never shown
     a candidate list). No configured Groq key → the namespace is reported as
     ``llm_unavailable`` and skipped rather than guessed.
  2. Group proposals deterministically: union-find on shared anchor
     entities, then near-identical slugs/labels (fuzzy ≥ 0.85).
  3. Bridged memories inherit their chat's group — one LLM call per chat,
     not per memory.
  4. ``--apply``: one profile per group (centroid = mean of member
     embeddings; era window from S9N-6613 ``occurred_at``); members stamped.

Misfile report: after grouping, the namespace's dominant group is the one
with the most members; items in OTHER groups are the likely-misfiled
candidates, with reasons (their entities vs the dominant group's, era gap,
and the free drift signal ``memory.namespace != source_chat.namespace``).

Docker usage:
    docker compose -f docker-compose.community.yml run --rm api \
        python scripts/backfill_namespace_tags.py \
        [--namespace project:ai-expansion-strategy]
    docker compose -f docker-compose.community.yml run --rm api \
        python scripts/backfill_namespace_tags.py --apply

Validation bar (ticket): must split ``project:ai-expansion-strategy`` into
its Builder.ai / EY / Al Ansari / SeKondBrain segments.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.adapters.identity_provider import get_identity_provider
from backend.core.database import _get_session_factory, init_db
from backend.core.tenancy import bypass_tenant_filter
from backend.models.ai_chat import AIChat
from backend.models.memory import Memory
from backend.models.namespace_tag import NamespaceTag
from backend.services.chat_classifier import is_pending_namespace
from backend.services.namespace_tag_service import (
    SegmentProposal,
    _fuzzy_ratio,
    _l2_normalize,
    propose_segment,
)

PROPOSAL_CONCURRENCY = 4
SLUG_MATCH = 0.85
MIN_ITEMS_PER_NAMESPACE = 4


# ─── Pure grouping (unit-tested) ────────────────────────────────────


@dataclass
class Item:
    """One taggable thing: a chat, or a direct (non-bridged) memory."""

    kind: str  # "chat" | "memory"
    id: str
    title: str
    occurred_at: datetime | None
    embedding: list[float] | None = None
    proposal: SegmentProposal | None = None
    source_chat_id: str | None = None  # memories only
    namespace_drift: bool = False  # memory.namespace != source_chat.namespace
    group: int | None = None


@dataclass
class Group:
    slug: str
    label: str
    entities: set[str] = field(default_factory=set)
    members: list[Item] = field(default_factory=list)


def group_items(items: list[Item]) -> list[Group]:
    """Union proposals into segments: shared anchor entity first, then
    near-identical slug/label. Pure and deterministic (input order stable)."""
    groups: list[Group] = []
    for item in items:
        prop = item.proposal
        if prop is None:
            continue
        prop_entities = {e.lower() for e in prop.entities}
        target: Group | None = None
        for g in groups:
            if prop_entities and g.entities and prop_entities & g.entities:
                target = g
                break
            if _fuzzy_ratio(prop.slug, g.slug) >= SLUG_MATCH:
                target = g
                break
            if _fuzzy_ratio(prop.label.lower(), g.label.lower()) >= SLUG_MATCH:
                target = g
                break
        if target is None:
            target = Group(slug=prop.slug, label=prop.label)
            groups.append(target)
        target.entities |= prop_entities
        target.members.append(item)
        item.group = groups.index(target)
    return groups


def dominant_group(groups: list[Group]) -> Group | None:
    return max(groups, key=lambda g: len(g.members)) if groups else None


# ─── Data loading ───────────────────────────────────────────────────


async def _load_namespace_items(
    db: AsyncSession, user_id: uuid.UUID, namespace: str, limit: int
) -> tuple[list[Item], dict[str, list[Item]]]:
    """Items needing an LLM proposal + bridged memories keyed by chat id."""
    chats = (
        (
            await db.execute(
                select(AIChat)
                .where(
                    AIChat.user_id == user_id,
                    AIChat.namespace == namespace,
                    AIChat.invalid_at.is_(None),
                )
                .order_by(AIChat.updated_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    memories = (
        (
            await db.execute(
                select(Memory)
                .where(
                    Memory.user_id == user_id,
                    Memory.namespace == namespace,
                    Memory.invalid_at.is_(None),
                )
                .order_by(Memory.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    chat_ids = {str(c.chat_id) for c in chats}
    items: list[Item] = [
        Item(
            kind="chat",
            id=str(c.chat_id),
            title=c.title or "(untitled)",
            occurred_at=c.captured_at,
        )
        for c in chats
        if not c.namespace_tag  # already-tagged rows are settled
    ]

    bridged: dict[str, list[Item]] = {}
    for m in memories:
        if m.namespace_tag:
            continue
        mi = Item(
            kind="memory",
            id=str(m.memory_id),
            title=(m.content or "")[:80].replace("\n", " "),
            occurred_at=m.occurred_at,
            embedding=list(m.embedding) if m.embedding else None,
            source_chat_id=str(m.source_chat_id) if m.source_chat_id else None,
        )
        if mi.source_chat_id and mi.source_chat_id in chat_ids:
            bridged.setdefault(mi.source_chat_id, []).append(mi)
        else:
            if mi.source_chat_id:
                # Source chat lives in ANOTHER namespace (or was purged):
                # the known merge-drift bug — a strong misfile signal.
                mi.namespace_drift = True
            items.append(mi)
    return items, bridged


async def _sample_for(db: AsyncSession, item: Item, user_id: uuid.UUID) -> str:
    if item.kind == "chat":
        from backend.services.chat_classifier import _load_chat_sample

        chat = (
            await db.execute(select(AIChat).where(AIChat.chat_id == uuid.UUID(item.id)))
        ).scalar_one_or_none()
        if chat is None:
            return ""
        sample = await _load_chat_sample(chat, db)
        return f"{chat.title or ''}\n{sample}"
    mem = (
        await db.execute(select(Memory).where(Memory.memory_id == uuid.UUID(item.id)))
    ).scalar_one_or_none()
    return (mem.content or "") if mem else ""


# ─── Apply ──────────────────────────────────────────────────────────


async def _apply_groups(
    db: AsyncSession,
    user_id: uuid.UUID,
    org_id: str,
    namespace: str,
    groups: list[Group],
    bridged: dict[str, list[Item]],
) -> int:
    from sqlalchemy import update as sa_update

    stamped = 0
    for g in groups:
        if not g.members:
            continue
        embeddings = [i.embedding for i in g.members if i.embedding]
        centroid = None
        if embeddings:
            dim = len(embeddings[0])
            sums = [0.0] * dim
            for e in embeddings:
                for k in range(dim):
                    sums[k] += e[k]
            centroid = _l2_normalize([s / len(embeddings) for s in sums])
        dates = [i.occurred_at for i in g.members if i.occurred_at]

        existing = (
            await db.execute(
                select(NamespaceTag).where(
                    NamespaceTag.user_id == user_id,
                    NamespaceTag.namespace == namespace,
                    NamespaceTag.tag == g.slug,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                NamespaceTag(
                    user_id=user_id,
                    org_id=org_id,
                    namespace=namespace,
                    tag=g.slug,
                    label=g.label,
                    entity_terms=sorted(g.entities) or None,
                    centroid=centroid,
                    member_count=len(g.members),
                    occurred_from=min(dates) if dates else None,
                    occurred_to=max(dates) if dates else None,
                    source="backfill",
                )
            )
            await db.flush()

        chat_ids = [uuid.UUID(i.id) for i in g.members if i.kind == "chat"]
        mem_ids = [uuid.UUID(i.id) for i in g.members if i.kind == "memory"]
        # Bridged memories ride their chat's tag.
        for cid in list(chat_ids):
            mem_ids.extend(uuid.UUID(b.id) for b in bridged.get(str(cid), []))
        if chat_ids:
            await db.execute(
                sa_update(AIChat)
                .where(AIChat.chat_id.in_(chat_ids), AIChat.namespace_tag.is_(None))
                .values(namespace_tag=g.slug)
            )
        if mem_ids:
            await db.execute(
                sa_update(Memory)
                .where(Memory.memory_id.in_(mem_ids), Memory.namespace_tag.is_(None))
                .values(namespace_tag=g.slug)
            )
        stamped += len(chat_ids) + len(mem_ids)
    return stamped


# ─── Main pass ──────────────────────────────────────────────────────


async def run(args: argparse.Namespace) -> int:
    await init_db()
    factory = _get_session_factory()
    out_rows: list[dict] = []
    summary: list[str] = []
    identity = get_identity_provider()
    local_config = identity.config
    user_id = uuid.UUID(args.user_id) if args.user_id else local_config.user_id

    async with factory() as db:
        with bypass_tenant_filter():
            if args.namespace:
                namespaces = args.namespace
            else:
                counts: dict[str, int] = {}
                chat_counts = (
                    await db.execute(
                        select(AIChat.namespace, func.count())
                        .where(AIChat.user_id == user_id, AIChat.invalid_at.is_(None))
                        .group_by(AIChat.namespace)
                    )
                ).all()
                memory_counts = (
                    await db.execute(
                        select(Memory.namespace, func.count())
                        .where(Memory.user_id == user_id, Memory.invalid_at.is_(None))
                        .group_by(Memory.namespace)
                    )
                ).all()
                for namespace, count in [*chat_counts, *memory_counts]:
                    counts[namespace] = counts.get(namespace, 0) + int(count)
                namespaces = [
                    namespace
                    for namespace, count in sorted(counts.items())
                    if count >= args.min_items and not is_pending_namespace(namespace)
                ]

            for namespace in namespaces:
                if is_pending_namespace(namespace):
                    summary.append(f"{namespace}: skipped (pending/inbox)")
                    continue
                items, bridged = await _load_namespace_items(db, user_id, namespace, args.limit_per_namespace)
                if len(items) < args.min_items:
                    summary.append(f"{namespace}: skipped ({len(items)} untagged items)")
                    continue

                # LLM proposals — samples loaded sequentially (one session),
                # HTTP calls fanned out bounded.
                samples: list[tuple[Item, str]] = []
                for item in items:
                    samples.append((item, await _sample_for(db, item, user_id)))

                sem = asyncio.Semaphore(args.concurrency)

                async def _propose(
                    item: Item,
                    sample: str,
                    semaphore: asyncio.Semaphore = sem,
                ) -> None:
                    if not sample.strip():
                        return
                    async with semaphore:
                        item.proposal = await propose_segment(sample, ref=item.id)

                await asyncio.gather(*(_propose(i, s) for i, s in samples))

                proposed = [i for i in items if i.proposal is not None]
                if not proposed:
                    summary.append(f"{namespace}: llm_unavailable (0/{len(items)} proposals)")
                    continue

                groups = group_items(items)
                dom = dominant_group(groups)

                for g in groups:
                    misfile = dom is not None and g is not dom and len(groups) > 1
                    for item in g.members:
                        out_rows.append(
                            {
                                "user_id": str(user_id),
                                "namespace": namespace,
                                "kind": item.kind,
                                "id": item.id,
                                "title": item.title,
                                "occurred_at": item.occurred_at.isoformat() if item.occurred_at else "",
                                "tag": g.slug,
                                "tag_label": g.label,
                                "tag_entities": ";".join(sorted(g.entities)),
                                "misfile_candidate": "yes" if misfile else "",
                                "reasons": (
                                    (
                                        f"entities≠dominant({';'.join(sorted(dom.entities)) or dom.slug}); "
                                        if misfile and dom
                                        else ""
                                    )
                                    + ("source-chat-namespace-drift; " if item.namespace_drift else "")
                                ).strip("; "),
                            }
                        )

                n_stamped = 0
                if args.apply:
                    org_id = str(local_config.org_id)
                    n_stamped = await _apply_groups(db, user_id, org_id, namespace, groups, bridged)
                    await db.commit()

                non_dom = sum(len(g.members) for g in groups if g is not dom)
                summary.append(
                    f"{namespace}: {len(items)} items → {len(groups)} segments "
                    f"({len(proposed)} proposals; {non_dom} outside dominant"
                    f"{'; stamped ' + str(n_stamped) if args.apply else '; DRY-RUN'})"
                )

    # CSV to --out (or stdout), summary to stderr — reassign_generic pattern.
    fieldnames = [
        "user_id",
        "namespace",
        "kind",
        "id",
        "title",
        "occurred_at",
        "tag",
        "tag_label",
        "tag_entities",
        "misfile_candidate",
        "reasons",
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(out_rows)
    if args.out:
        with open(args.out, "w", newline="") as f:
            f.write(buf.getvalue())
    else:
        sys.stdout.write(buf.getvalue())

    print("", file=sys.stderr)
    for line in summary:
        print(f"  {line}", file=sys.stderr)
    print(
        f"\n{'APPLIED' if args.apply else 'DRY-RUN — nothing written (pass --apply to stamp tags)'}",
        file=sys.stderr,
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Retro second-tier namespace tagging (S9N-6612)")
    p.add_argument("--user-id", help="Override the configured local user UUID")
    p.add_argument(
        "--namespace",
        action="append",
        help="Restrict to specific namespace(s); default: every non-inbox namespace with enough items",
    )
    p.add_argument("--apply", action="store_true", help="Write profiles and stamp tags")
    p.add_argument("--out", help="Write the CSV report here instead of stdout")
    p.add_argument("--limit-per-namespace", type=int, default=300)
    p.add_argument("--concurrency", type=int, default=PROPOSAL_CONCURRENCY)
    p.add_argument("--min-items", type=int, default=MIN_ITEMS_PER_NAMESPACE)
    return p


def main() -> int:
    args = _build_parser().parse_args()
    if args.min_items < 2:
        print("ERROR: --min-items must be at least 2.", file=sys.stderr)
        return 2
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
