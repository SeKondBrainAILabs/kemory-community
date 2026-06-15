"""L3.1 concept synthesis stage."""

from __future__ import annotations

from backend.plugins.cognition import PipelineContext, PipelineStage, register_pipeline_stage


@register_pipeline_stage
class ConceptSynthesisStage(PipelineStage):
    async def run(self, context: PipelineContext) -> None:
        from backend.core.database import _get_session_factory
        from backend.services.compression_pipeline import _maybe_synthesize_l3_1

        async with _get_session_factory()() as db:
            await _maybe_synthesize_l3_1(db, context.user_id, context.namespace)
            await db.commit()
