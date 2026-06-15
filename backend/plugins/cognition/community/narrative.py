"""L3 narrative summarization stages."""

from __future__ import annotations

from backend.plugins.cognition import PipelineContext, PipelineStage, register_pipeline_stage


@register_pipeline_stage
class NamespaceNarrativeStage(PipelineStage):
    async def run(self, context: PipelineContext) -> None:
        from backend.core.database import _get_session_factory
        from backend.services.compression_pipeline import _maybe_summarize_l3

        async with _get_session_factory()() as db:
            await _maybe_summarize_l3(
                db,
                context.user_id,
                context.namespace,
                trigger_memory_id=context.memory_id,
            )
            await db.commit()


@register_pipeline_stage
class SessionNarrativeStage(PipelineStage):
    async def run(self, context: PipelineContext) -> None:
        from backend.core.database import _get_session_factory
        from backend.services.compression_pipeline import _maybe_summarize_session_l3

        async with _get_session_factory()() as db:
            await _maybe_summarize_session_l3(
                db,
                context.user_id,
                context.memory_id,
                context.namespace,
            )
            await db.commit()
