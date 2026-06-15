"""Cognition compression-stage plugin registry."""

from __future__ import annotations

import importlib
import pkgutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from types import ModuleType


@dataclass(frozen=True)
class PipelineContext:
    user_id: str
    memory_id: str
    namespace: str


class PipelineStage(ABC):
    @abstractmethod
    async def run(self, context: PipelineContext) -> None:
        """Run one compression pipeline stage."""


_pipeline_stages: list[PipelineStage] = []
_loaded = False
_STAGE_MODULE_ORDER = {
    "backend.plugins.cognition.community": [
        "aaak_encoder",
        "narrative",
        "concept_synthesis",
        "supersedes_graph",
        "quality_scorer",
    ],
}


def register_pipeline_stage(stage_cls: type[PipelineStage]) -> type[PipelineStage]:
    stage_id = f"{stage_cls.__module__}.{stage_cls.__qualname__}"
    if not any(f"{s.__class__.__module__}.{s.__class__.__qualname__}" == stage_id for s in _pipeline_stages):
        _pipeline_stages.append(stage_cls())
    return stage_cls


def _iter_stage_modules(package: ModuleType) -> list[str]:
    return [module.name for module in pkgutil.iter_modules(package.__path__) if not module.ispkg]


def _ordered_stage_modules(package_name: str, package: ModuleType) -> list[str]:
    discovered = _iter_stage_modules(package)
    preferred = _STAGE_MODULE_ORDER.get(package_name, [])
    return [name for name in preferred if name in discovered] + [
        name for name in discovered if name not in preferred
    ]


def load_pipeline_stages() -> list[PipelineStage]:
    global _loaded
    if _loaded:
        return list(_pipeline_stages)

    package_names = ["backend.plugins.cognition.community"]

    for package_name in package_names:
        package = importlib.import_module(package_name)
        for module_name in _ordered_stage_modules(package_name, package):
            importlib.import_module(f"{package_name}.{module_name}")

    _loaded = True
    return list(_pipeline_stages)


def get_pipeline_stages() -> list[PipelineStage]:
    return load_pipeline_stages()


def reset_pipeline_stages_for_tests() -> None:
    global _loaded
    _pipeline_stages.clear()
    _loaded = False


__all__ = [
    "PipelineContext",
    "PipelineStage",
    "get_pipeline_stages",
    "load_pipeline_stages",
    "register_pipeline_stage",
    "reset_pipeline_stages_for_tests",
]
