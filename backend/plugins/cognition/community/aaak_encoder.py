"""L2 AAAK encoding stage."""

from __future__ import annotations

from backend.plugins.cognition import PipelineContext, PipelineStage, register_pipeline_stage


@register_pipeline_stage
class AaakEncoderStage(PipelineStage):
    async def run(self, context: PipelineContext) -> None:
        from backend.core.database import _get_session_factory
        from backend.services.compression_pipeline import _promote_to_l2

        async with _get_session_factory()() as db:
            await _promote_to_l2(db, context.memory_id)
            await db.commit()
