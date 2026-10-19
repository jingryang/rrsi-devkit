"""L3 Orchestration — Stage and Workflow registry."""

from __future__ import annotations

import threading
from typing import Type

from ascendc_devkit.orchestration.base import Stage, StageProtocol


STAGE_REGISTRY: dict[str, Type[Stage]] = {}
WORKFLOW_REGISTRY: dict[str, Type] = {}

# 加载互斥锁：批内多 dispatch 线程并发首调 get_workflow/get_stage 时，无锁的
# check-then-act 会让多线程同时进入导入块——导入链跨线程交错时 from-import
# 可见半初始化模块（ImportError: cannot import name）。双检锁保证加载单线程
# 完成、其余线程等待后直接命中缓存。用 RLock：若未来 stage 模块导入链嵌套调
# 回任一 loader（如模块顶层 get_stage），非重入锁会自死锁——重入语义消除该类。
_LOAD_LOCK = threading.RLock()

_stages_loaded = False
_workflows_loaded = False


def _ensure_stages_loaded():
    global _stages_loaded
    if _stages_loaded:
        return
    with _LOAD_LOCK:
        if _stages_loaded:
            return
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage  # noqa: F401
        from ascendc_devkit.orchestration.stages.codegen_init import CodegenInitStage  # noqa: F401
        from ascendc_devkit.orchestration.stages.smoke import SmokeStage  # noqa: F401
        from ascendc_devkit.orchestration.stages.entry import EntryStage  # noqa: F401
        from ascendc_devkit.orchestration.stages.context import ContextStage  # noqa: F401
        from ascendc_devkit.orchestration.stages.requirement import RequirementStage  # noqa: F401
        from ascendc_devkit.orchestration.stages.ascendc_st_design import AscendCSTDesignStage  # noqa: F401
        # precision_debug is a CompositeGroup (P0 51-*.md), not a flat @register_stage
        # Stage — built by precision_debug_tree.build_precision_debug_group() and mounted
        # via the workflow root. Its four sub-stages are instantiated directly by the
        # group builder (like the design sub-stages), so none are registered here.
        from ascendc_devkit.orchestration.stages.perf import PerfStage  # noqa: F401
        from ascendc_devkit.orchestration.stages.integrate import IntegrateStage  # noqa: F401
        from ascendc_devkit.orchestration.stages.finalize import FinalizeStage  # noqa: F401
        from ascendc_devkit.orchestration.stages.cannbench_eval import CannbenchEvalStage  # noqa: F401
        from ascendc_devkit.orchestration.stages.cannbench_adapt import CannbenchAdaptStage  # noqa: F401
        _stages_loaded = True
        _stages_loaded = True


def _ensure_workflows_loaded():
    global _workflows_loaded
    if _workflows_loaded:
        return
    with _LOAD_LOCK:
        if _workflows_loaded:
            return
        from ascendc_devkit.orchestration.workflow import GenerateAscendCWorkflow  # noqa: F401
        _workflows_loaded = True


def register_stage(cls: Type[Stage]) -> Type[Stage]:
    STAGE_REGISTRY[cls.name] = cls
    return cls


def register_workflow(name: str):
    """Decorator to register a Workflow class by name."""
    def decorator(cls):
        WORKFLOW_REGISTRY[name] = cls
        return cls
    return decorator


def get_stage(name: str) -> Type[Stage]:
    _ensure_stages_loaded()
    if name not in STAGE_REGISTRY:
        raise KeyError(f"Unknown stage: {name}. Available: {list(STAGE_REGISTRY)}")
    return STAGE_REGISTRY[name]


def get_workflow(name: str):
    """Get a Workflow instance by name."""
    _ensure_stages_loaded()
    _ensure_workflows_loaded()
    if name not in WORKFLOW_REGISTRY:
        raise KeyError(f"Unknown workflow: {name}. Available: {list(WORKFLOW_REGISTRY)}")
    return WORKFLOW_REGISTRY[name]()


def workflow_requires_npu(name: str) -> bool | None:
    """Whether the named workflow builds/runs on local NPU (``requires_npu``).

    Reads the class attribute without instantiating the workflow tree (the
    pre-design chip gate calls this on every design iteration; building the
    full stage tree each time would be wasteful). Returns None for an unknown
    / empty name so callers can default to the safe branch rather than raise.
    """
    if not name:
        return None
    _ensure_workflows_loaded()
    cls = WORKFLOW_REGISTRY.get(name)
    return getattr(cls, "requires_npu", None) if cls is not None else None


def list_stages() -> list[str]:
    _ensure_stages_loaded()
    return sorted(STAGE_REGISTRY.keys())


def list_workflows() -> list[str]:
    _ensure_stages_loaded()
    _ensure_workflows_loaded()
    return sorted(WORKFLOW_REGISTRY.keys())
