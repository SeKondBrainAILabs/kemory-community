"""L5 enterprise namespace-merge detection stage."""

from __future__ import annotations

from backend.plugins.cognition import PipelineContext, PipelineStage, register_pipeline_stage


@register_pipeline_stage
class NamespaceMergeStage(PipelineStage):
    async def run(self, context: PipelineContext) -> None:
        from backend.core.database import _get_session_factory
        from backend.services.compression_pipeline import _check_namespace_content_similarity

        async with _get_session_factory()() as db:
            await _check_namespace_content_similarity(context.user_id, context.namespace, db)
            await db.commit()
