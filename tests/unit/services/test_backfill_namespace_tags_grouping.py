"""
tests/unit/services/test_backfill_namespace_tags_grouping.py
============================================================
S9N-6612: pure grouping matrix for the retro tagging script — union by
shared anchor entity, then near-identical slug/label; dominant-group /
misfile-candidate identification. Scripts are untested by convention here,
but the ticket's acceptance hangs on this function, so it's factored
importable and covered (same treatment as namespace_allocator).
"""

from __future__ import annotations

from backend.services.namespace_tag_service import SegmentProposal
from scripts.backfill_namespace_tags import Item, dominant_group, group_items


def _item(id_, proposal, kind="chat"):
    return Item(kind=kind, id=id_, title=id_, occurred_at=None, proposal=proposal)


INSIGHT = SegmentProposal(
    label="Builder.ai Insight bridge",
    slug="builder-ai-insight-bridge",
    entities=("builder.ai", "insight partners"),
)
INSIGHT_B = SegmentProposal(label="Insight Q4 deal", slug="insight-q4-deal", entities=("insight partners",))
EY = SegmentProposal(label="EY leadership deck", slug="ey-leadership-deck", entities=("ey",))
SOVEREIGN = SegmentProposal(
    label="Sovereign AI strategy", slug="sovereign-ai-strategy", entities=("sekondbrain",)
)
SOVEREIGN_B = SegmentProposal(label="Sovereign AI strategy", slug="sovereign-ai-strategies", entities=())


class TestGrouping:
    def test_repro_namespace_splits_into_segments(self):
        """The ai-expansion-strategy shape: Insight/EY/SeKondBrain items must
        land in three distinct groups — this IS the ticket's validation bar."""
        items = [
            _item("c1", INSIGHT),
            _item("c2", INSIGHT_B),  # different slug, shared entity → same group
            _item("c3", EY),
            _item("c4", SOVEREIGN),
            _item("c5", SOVEREIGN),
            _item("c6", SOVEREIGN_B),  # no entities, near-identical slug → same group
        ]
        groups = group_items(items)
        assert len(groups) == 3
        by_slug = {g.slug: {m.id for m in g.members} for g in groups}
        assert by_slug["builder-ai-insight-bridge"] == {"c1", "c2"}
        assert by_slug["ey-leadership-deck"] == {"c3"}
        assert by_slug["sovereign-ai-strategy"] == {"c4", "c5", "c6"}

    def test_entities_accumulate_on_the_group(self):
        groups = group_items([_item("c1", INSIGHT), _item("c2", INSIGHT_B)])
        assert groups[0].entities == {"builder.ai", "insight partners"}

    def test_items_without_proposals_are_left_out(self):
        items = [_item("c1", INSIGHT), _item("c2", None)]
        groups = group_items(items)
        assert len(groups) == 1 and len(groups[0].members) == 1
        assert items[1].group is None

    def test_dominant_group_and_misfile_candidates(self):
        items = [
            _item("c1", SOVEREIGN),
            _item("c2", SOVEREIGN),
            _item("c3", SOVEREIGN),
            _item("c4", INSIGHT),
            _item("c5", EY),
        ]
        groups = group_items(items)
        dom = dominant_group(groups)
        assert dom is not None and dom.slug == "sovereign-ai-strategy"
        misfiled = {m.id for g in groups if g is not dom for m in g.members}
        assert misfiled == {"c4", "c5"}

    def test_empty(self):
        assert group_items([]) == []
        assert dominant_group([]) is None
