"""L3.1 concept provenance graph stage.

The community API derives synthesized-from edges from the concept memory's
``_source_memory_ids`` metadata, which is written by ConceptSynthesisStage.
This registered stage keeps that graph concern explicit in the plugin order.
"""

from __future__ import annotations

from backend.plugins.cognition import PipelineContext, PipelineStage, register_pipeline_stage


@register_pipeline_stage
class SupersedesGraphStage(PipelineStage):
    async def run(self, context: PipelineContext) -> None:
        return None
