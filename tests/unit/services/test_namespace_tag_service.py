"""
tests/unit/services/test_namespace_tag_service.py
=================================================
S9N-6612: pure scoring/matching matrix for the second-tier tag resolver.

Mirrors test_namespace_allocator's style: no DB, no encoder, no LLM — just
the deterministic half that decides existing-tag vs no-fit. The repro
scenario threaded through: a namespace mixing Builder.ai (Insight deal),
EY client work and SeKondBrain strategy, where vocabulary embeds close and
ENTITIES are the real discriminator.
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.models.namespace_tag import NamespaceTag
from backend.services.namespace_tag_service import (
    ERA_BONUS,
    ERA_PENALTY,
    SegmentProposal,
    _l2_normalize,
    _update_profile_stats,
    cosine,
    extract_known_entities,
    match_proposal,
    pick_profile,
    score_profile,
)


def _profile(tag, *, entities=None, centroid=None, frm=None, to=None, members=5):
    return NamespaceTag(
        user_id=None,
        org_id="org-test",
        namespace="project:ai-expansion-strategy",
        tag=tag,
        label=tag.replace("-", " ").title(),
        entity_terms=entities,
        centroid=centroid,
        occurred_from=frm,
        occurred_to=to,
        member_count=members,
    )


BUILDER = _profile(
    "builder-ai-insight-deal",
    entities=["builder.ai", "insight partners", "bdo"],
    centroid=_l2_normalize([1.0, 0.2, 0.0]),
    frm=datetime(2024, 10, 1, tzinfo=UTC),
    to=datetime(2025, 1, 31, tzinfo=UTC),
)
SEKOND = _profile(
    "sovereign-ai-sekondbrain",
    entities=["sekondbrain"],
    centroid=_l2_normalize([0.9, 0.4, 0.0]),  # deliberately CLOSE to BUILDER
    frm=datetime(2026, 5, 1, tzinfo=UTC),
    to=datetime(2026, 7, 30, tzinfo=UTC),
)


class TestVectorHelpers:
    def test_l2_and_cosine(self):
        v = _l2_normalize([3.0, 4.0])
        assert abs(cosine(v, v) - 1.0) < 1e-9
        assert cosine(None, v) == 0.0
        assert cosine([1.0], [1.0, 0.0]) == 0.0  # dim mismatch → no signal

    def test_extract_known_entities_substring_lowercase(self):
        text = "Email from Gabe at Insight Partners re the Builder.ai bridge"
        known = {"insight partners", "builder.ai", "sekondbrain"}
        assert extract_known_entities(text, known) == {"insight partners", "builder.ai"}
        assert extract_known_entities("", known) == set()


class TestScoring:
    def test_entity_overlap_counts_and_caps(self):
        parts = score_profile(
            embedding=None,
            item_entities={"builder.ai", "insight partners", "bdo"},
            occurred_at=None,
            profile=BUILDER,
        )
        assert parts.entity_overlap == 3
        # 3 * 0.15 capped at 0.30
        assert abs(parts.total - 0.30) < 1e-9

    def test_era_inside_window_boosts_far_outside_penalises(self):
        inside = score_profile(
            embedding=None,
            item_entities=set(),
            occurred_at=datetime(2024, 11, 15, tzinfo=UTC),
            profile=BUILDER,
        )
        far = score_profile(
            embedding=None,
            item_entities=set(),
            occurred_at=datetime(2026, 7, 1, tzinfo=UTC),
            profile=BUILDER,
        )
        assert inside.era == ERA_BONUS
        assert far.era == ERA_PENALTY

    def test_no_dates_no_era_signal(self):
        parts = score_profile(embedding=None, item_entities=set(), occurred_at=None, profile=BUILDER)
        assert parts.era == 0.0


class TestPickProfile:
    def test_repro_shape_entity_beats_close_embeddings(self):
        """Both centroids embed near-identically (shared corporate-AI vocab);
        the Insight email must land on the Builder.ai tag via entities."""
        emb = _l2_normalize([0.95, 0.3, 0.0])  # between the two centroids
        decision = pick_profile(
            embedding=emb,
            item_entities={"insight partners"},
            occurred_at=datetime(2024, 11, 3, tzinfo=UTC),
            profiles=[SEKOND, BUILDER],
        )
        assert decision.tag == "builder-ai-insight-deal"
        assert decision.reason.startswith("entity_match")

    def test_ambiguous_embedding_only_is_no_fit(self):
        """No entities, embedding equally close to both → refuse to guess."""
        emb = _l2_normalize([0.95, 0.3, 0.0])
        decision = pick_profile(
            embedding=emb, item_entities=set(), occurred_at=None, profiles=[SEKOND, BUILDER]
        )
        assert decision.tag is None
        assert decision.reason.startswith("no_fit")

    def test_clear_embedding_winner_accepted(self):
        lone = _profile("only-tag", centroid=_l2_normalize([0.0, 0.0, 1.0]))
        decision = pick_profile(
            embedding=_l2_normalize([0.0, 0.1, 1.0]),
            item_entities=set(),
            occurred_at=None,
            profiles=[lone],
        )
        assert decision.tag == "only-tag"
        assert decision.reason == "embedding_match"

    def test_no_profiles(self):
        assert pick_profile(embedding=None, item_entities=set(), occurred_at=None, profiles=[]).tag is None

    def test_era_breaks_near_ties_when_dates_exist(self):
        """Same-entity-free case but one profile's window matches: era should
        push the total over the runner-up gap only when embeddings already
        lean that way (boost, not gate)."""
        emb = BUILDER.centroid  # exactly Builder's centroid
        decision = pick_profile(
            embedding=emb,
            item_entities=set(),
            occurred_at=datetime(2024, 11, 3, tzinfo=UTC),
            profiles=[SEKOND, BUILDER],
        )
        assert decision.tag == "builder-ai-insight-deal"


class TestMatchProposal:
    def test_matches_by_shared_entity(self):
        prop = SegmentProposal(
            label="Insight bridge financing",
            slug="insight-bridge-financing",
            entities=("insight partners",),
        )
        assert match_proposal(prop, [SEKOND, BUILDER]) is BUILDER

    def test_matches_by_near_identical_slug(self):
        prop = SegmentProposal(label="Builder AI Insight Deal", slug="builder-ai-insight-deals", entities=())
        assert match_proposal(prop, [SEKOND, BUILDER]) is BUILDER

    def test_distinct_proposal_matches_nothing(self):
        prop = SegmentProposal(
            label="EY leadership presentation",
            slug="ey-leadership-presentation",
            entities=("ey",),
        )
        assert match_proposal(prop, [SEKOND, BUILDER]) is None


class TestProfileStats:
    def test_folding_updates_centroid_era_entities_count(self):
        p = _profile(
            "t",
            entities=["builder.ai"],
            centroid=_l2_normalize([1.0, 0.0]),
            frm=datetime(2024, 11, 1, tzinfo=UTC),
            to=datetime(2024, 12, 1, tzinfo=UTC),
            members=1,
        )
        _update_profile_stats(
            p,
            embedding=_l2_normalize([0.0, 1.0]),
            entities={"insight partners"},
            occurred_at=datetime(2024, 10, 1, tzinfo=UTC),
        )
        assert p.member_count == 2
        assert p.occurred_from == datetime(2024, 10, 1, tzinfo=UTC)  # window widened
        assert "insight partners" in p.entity_terms
        # running mean of orthonormal vectors, renormalised → 45°
        assert abs(cosine(p.centroid, _l2_normalize([1.0, 1.0])) - 1.0) < 1e-9

    def test_never_null_regression_on_missing_signals(self):
        p = _profile("t", entities=["x"], centroid=_l2_normalize([1.0, 0.0]), members=3)
        _update_profile_stats(p, embedding=None, entities=set(), occurred_at=None)
        assert p.member_count == 4
        assert p.centroid is not None and p.entity_terms == ["x"]
