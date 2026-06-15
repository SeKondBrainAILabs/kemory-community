"""Concept-memory quality marker stage.

ConceptSynthesisStage currently writes concept memories with
``quality_score=None`` and ``enrichment_status='pending'`` to preserve the
existing enrichment pipeline contract. This registered stage documents that
community behavior without adding extra I/O.
"""

from __future__ import annotations

from backend.plugins.cognition import PipelineContext, PipelineStage, register_pipeline_stage


@register_pipeline_stage
class QualityScorerStage(PipelineStage):
    async def run(self, context: PipelineContext) -> None:
        return None
