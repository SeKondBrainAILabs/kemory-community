#!/usr/bin/env python
"""
S9N-6612 — promote (graduate) a namespace tag out to a full namespace.

The REVIEWED half of the second-tier design: automatic tagging segments a
namespace in place; when a human confirms a segment genuinely doesn't belong
(e.g. ``project:ai-expansion-strategy:q4-24-performance-and-stability-deal``
is Builder.ai history, not SeKondBrain strategy), this script moves that
segment's chats and memories to their own namespace in one local transaction.

Dry-run by default; ``--apply`` executes. The command preflights memory hash
collisions, moves matching chats/memories, clears source-only tags, updates
chat artifact namespaces, and deactivates the source profile atomically.

Docker usage:
    docker compose -f docker-compose.community.yml run --rm api \
        python scripts/promote_namespace_tag.py \
        --namespace project:ai-expansion-strategy \
        --tag q4-24-performance-and-stability-deal \
        --to-namespace project:builder-ai-insight-deal [--apply]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from sqlalchemy import func, select, update

from backend.adapters.identity_provider import get_identity_provider
from backend.core.database import _get_session_factory, init_db
from backend.core.tenancy import bypass_tenant_filter
from backend.models.ai_chat import AIChat, AIChatArtifact
from backend.models.memory import Memory
from backend.models.namespace_tag import NamespaceTag


async def run(args: argparse.Namespace) -> int:
    await init_db()
    factory = _get_session_factory()
    identity = get_identity_provider()
    user_id = uuid.UUID(args.user_id) if args.user_id else identity.config.user_id
    operation_id = f"promote-{uuid.uuid4().hex[:12]}"

    if args.namespace == args.to_namespace:
        print("ERROR: source and destination namespaces must differ", file=sys.stderr)
        return 2

    async with factory() as db:
        with bypass_tenant_filter():
            profile = (
                await db.execute(
                    select(NamespaceTag).where(
                        NamespaceTag.user_id == user_id,
                        NamespaceTag.namespace == args.namespace,
                        NamespaceTag.tag == args.tag,
                        NamespaceTag.active.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if profile is None:
                print(
                    f"ERROR: no tag profile {args.namespace}:{args.tag} for user {user_id}",
                    file=sys.stderr,
                )
                return 2

            chats = (
                (
                    await db.execute(
                        select(AIChat).where(
                            AIChat.user_id == user_id,
                            AIChat.namespace == args.namespace,
                            AIChat.namespace_tag == args.tag,
                            AIChat.invalid_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            memories = (
                (
                    await db.execute(
                        select(Memory).where(
                            Memory.user_id == user_id,
                            Memory.namespace == args.namespace,
                            Memory.namespace_tag == args.tag,
                            Memory.invalid_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )

            target_hashes = set(
                (
                    await db.execute(
                        select(Memory.content_hash).where(
                            Memory.user_id == user_id,
                            Memory.namespace == args.to_namespace,
                            Memory.invalid_at.is_(None),
                        )
                    )
                ).scalars()
            )
            collisions = [memory for memory in memories if memory.content_hash in target_hashes]
            if collisions:
                print(
                    f"ERROR: {len(collisions)} destination memory hash collision(s); " "nothing moved.",
                    file=sys.stderr,
                )
                for memory in collisions:
                    print(f"  memory {memory.memory_id}", file=sys.stderr)
                return 2

            print(
                f"{args.namespace}:{args.tag} → {args.to_namespace}\n"
                f"  {len(chats)} chats, {len(memories)} memories"
                f" (label: {profile.label!r}, entities: {profile.entity_terms})",
                file=sys.stderr,
            )
            for c in chats:
                print(f"  chat   {c.chat_id}  {c.title or '(untitled)'}", file=sys.stderr)
            for m in memories:
                print(f"  memory {m.memory_id}  {(m.content or '')[:60]!r}", file=sys.stderr)

            if not args.apply:
                print("\nDRY-RUN — nothing moved (pass --apply to promote)", file=sys.stderr)
                return 0

            chat_ids = [chat.chat_id for chat in chats]
            if chat_ids:
                await db.execute(
                    update(AIChat)
                    .where(AIChat.chat_id.in_(chat_ids), AIChat.user_id == user_id)
                    .values(
                        namespace=args.to_namespace,
                        namespace_tag=None,
                        requested_namespace=None,
                        updated_at=func.now(),
                    )
                )
                await db.execute(
                    update(AIChatArtifact)
                    .where(AIChatArtifact.chat_id.in_(chat_ids))
                    .values(namespace=args.to_namespace)
                )

            memory_ids = [memory.memory_id for memory in memories]
            if memory_ids:
                await db.execute(
                    update(Memory)
                    .where(Memory.memory_id.in_(memory_ids), Memory.user_id == user_id)
                    .values(
                        namespace=args.to_namespace,
                        namespace_tag=None,
                        version=Memory.version + 1,
                        updated_at=func.now(),
                    )
                )

            profile.active = False
            await db.commit()

            print(
                f"\nAPPLIED operation={operation_id}: {len(chats)} chats + "
                f"{len(memories)} memories → {args.to_namespace}; profile deactivated.",
                file=sys.stderr,
            )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Promote a namespace tag to a full namespace (S9N-6612)")
    p.add_argument("--user-id", help="Override the configured local user UUID")
    p.add_argument("--namespace", required=True, help="Source namespace")
    p.add_argument("--tag", required=True, help="Tag slug to promote")
    p.add_argument("--to-namespace", required=True, help="Destination namespace")
    p.add_argument("--apply", action="store_true", help="Execute (default: dry-run)")
    return p


def main() -> int:
    return asyncio.run(run(_build_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
