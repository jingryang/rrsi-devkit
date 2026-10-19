"""L3 Orchestration — Workflow: declarative Stage chain with IO contract validation."""

from __future__ import annotations

from dataclasses import dataclass, field

from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.orchestration.base import Stage, StageProtocol
from ascendc_devkit.orchestration.registry import register_workflow


class _ContractLeaf:
    """A flat_stages() placeholder carrying a node's declared contract.

    Used for dynamic fork-join nodes that have no static child Stages: the chain
    check only needs name + input/output contract, which this forwards from the
    wrapped node (step-2b §9.2.2/§4.3)."""

    def __init__(self, node):
        self._node = node
        self.name = node.name

    def input_contract(self) -> StageIOContract:
        return self._node.input_contract()

    def output_contract(self) -> StageIOContract:
        return self._node.output_contract()


@dataclass
class Workflow(StageProtocol):
    """Declarative workflow: an ordered sequence of Stages.

    Implements StageProtocol so it can be used where a Stage is expected.
    Provides validate_chain() to statically verify IO contract compatibility
    between adjacent stages.
    """

    name: str = ""
    description: str = ""
    stages: list[Stage] = field(default_factory=list)
    # Whether this workflow requires NPU hardware to complete.
    # Design-only workflows (SE) set False — they can run on CPU-only machines.
    # Execution workflows (full, dev, self_evolve_op) set True — preflight will
    # fail fast without NPU before burning agent time.
    requires_npu: bool = False

    def input_contract(self) -> StageIOContract:
        if not self.stages:
            return StageIOContract()
        return self.stages[0].input_contract()

    def output_contract(self) -> StageIOContract:
        if not self.stages:
            return StageIOContract()
        return self.stages[-1].output_contract()

    def actions(self, state, iteration):
        return []

    def gate(self):
        return None

    def validate_chain(self) -> list[str]:
        """Static validation of IO contract chain compatibility.

        Accumulates provides from ALL previous stages (not just the immediate
        predecessor) to account for fields that persist in State across stages
        (e.g., `mode` from entry persists through the entire pipeline).

        Fields still missing after accumulation are user-provided inputs
        (e.g., `requirement_path`, `task_request`) — reported as warnings,
        not errors. The dispatcher validates these at runtime with a richer
        context (State snapshot).

        Returns a list of warning messages (empty = all good).
        """
        warnings: list[str] = []
        accumulated_provides: set[str] = set()
        # Walk the flattened leaf view so group-internal substages are checked
        # (step-2b §9.2.2). For flat workflows flat_stages() == stages.
        stages = self.flat_stages()
        for i in range(len(stages)):
            curr = stages[i]
            accumulated_provides |= set(curr.output_contract().all_provides())
            if i + 1 < len(stages):
                nxt = stages[i + 1]
                required = set(nxt.input_contract().requires)
                missing = required - accumulated_provides
                if missing:
                    warnings.append(
                        f"Stage '{nxt.name}' requires {sorted(missing)} "
                        f"(user-provided input — validated by preflight)"
                    )
        return warnings

    def validate_agents(self) -> list[str]:
        """Load-time fail-fast: every spawn stage's agent_name must resolve to a
        real (non-placeholder) system prompt (step-8 §P1 task 4).

        Walks flat_stages(); for each leaf carrying a non-empty static
        ``agent_name`` (a spawn-type stage), checks that an agent.md exists.
        Returns error messages (empty = all good). Distinct from
        validate_chain()'s warnings: a missing agent.md is a startup error
        (CLAUDE.md: "load-time validation over runtime surfacing"), because the
        spawn would otherwise silently degrade to the generic placeholder prompt
        — the exact failure that left P1's design agents running context-free.

        Stages with no static agent_name are skipped: either they don't spawn
        (e.g. docgen returns no actions), or they compute agent_name dynamically
        in actions() (e.g. codegen by mode) where a static check can't see it.
        """
        from ascendc_devkit.capabilities.agent.sdk_backend import (
            agent_prompt_is_placeholder,
        )
        errors: list[str] = []
        seen: set[str] = set()
        for stage in self.flat_stages():
            name = getattr(stage, "agent_name", "") or ""
            if not name or name in seen:
                continue
            seen.add(name)
            if agent_prompt_is_placeholder(name):
                errors.append(
                    f"Stage '{stage.name}' references agent '{name}' but no "
                    f".claude/agents/{name}.md exists; it would silently fall "
                    f"back to a placeholder system prompt"
                )
        return errors

    def _index_of(self, stage_name: str) -> int:
        """Return the index of a stage by name, or -1 if not found."""
        for i, s in enumerate(self.stages):
            if s.name == stage_name:
                return i
        return -1

    def flat_stages(self, design_target_chip: str = "") -> list[Stage]:
        """Recursively flatten this workflow's node tree into leaf Stages.

        When ``design_target_chip`` is provided (dispatcher preflight), passes it
        to ``self.root(...)`` so chip-specific groups are built correctly.
        Default "" → A3.

        A read-only view (step-2b §9.2.2): where a workflow mounts CompositeGroup
        / ForkJoinGroup subtrees (via a root override), the flat `stages` field no
        longer reflects every executable stage. validate_chain / preflight walk
        this flattened leaf sequence so group-internal substages' contracts are
        seen. Walks `root` and unwraps AtomicStage leaves in traversal order;
        ForkJoinGroup branches with a dynamic branch_factory have no static
        leaves and contribute none (their outward contract is on the group).
        """
        from ascendc_devkit.orchestration.node import AtomicStage, SequentialGroup
        from ascendc_devkit.orchestration.node_forkjoin import ForkJoinGroup
        leaves: list[Stage] = []

        chip = design_target_chip or "A3"

        def _walk(node):
            if isinstance(node, AtomicStage):
                leaves.append(node.stage)
            elif isinstance(node, ForkJoinGroup):
                kids = node.children()
                if kids:
                    for c in kids:
                        _walk(c)
                else:
                    # Dynamic fork-join (branch_factory) has no static leaves;
                    # surface its declared contract as a synthetic leaf so the
                    # chain check sees requires/provides (§4.3).
                    leaves.append(_ContractLeaf(node))
            elif isinstance(node, SequentialGroup):
                for c in node.children():
                    _walk(c)

        _walk(self.root(chip))
        return leaves

    def resolve_next_stage(self, current_name: str, state) -> str | None:
        """Determine the next stage after *current_name* completes.

        1. Ask the current stage for its condition via resolve_condition(state).
        2. Look up (current_name, condition) in the transition table.
        3. Fall back to the linear successor for "default" or missing entries.
        4. Return None if this is the terminal stage.
        """
        idx = self._index_of(current_name)
        if idx < 0:
            return None

        stage = self.stages[idx]
        condition = stage.resolve_condition(state)

        table = self._get_transition_table()
        routes = table.get(current_name, {})
        target = routes.get(condition)
        if target:
            if isinstance(target, tuple):
                return target[0]  # (target_stage, route_type)
            return target

        # Default: linear successor
        if idx + 1 < len(self.stages):
            return self.stages[idx + 1].name
        return None

    def get_route_type(self, stage_name: str, condition: str) -> str:
        """Return the route type for a given (stage, condition) pair.

        Returns one of: "corrective", "escalation", "validation".
        Defaults to "corrective" for unlisted backward transitions.
        """
        table = self._get_transition_table()
        routes = table.get(stage_name, {})
        target = routes.get(condition)
        if isinstance(target, tuple) and len(target) > 1:
            return target[1]
        return "corrective"

    def _get_transition_table(self) -> dict[str, dict[str, str]]:
        """Return the stage transition table.

        Override in subclasses to add domain-specific loop-back routes.
        Default: empty — all stages use linear successors.
        """
        return {}

    def __iter__(self):
        return iter(self.stages)

    def __len__(self):
        return len(self.stages)

    def root(self, design_target_chip: str = ""):
        """Build a SequentialGroup tree from stages + TRANSITION_TABLE.

        ``design_target_chip`` is forwarded to ``_design_root`` by subclass
        overrides so chip-specific groups (precision_debug A3 vs A5) are
        built correctly. Default "" → A3.

        Existing built-in workflows declare flat `stages` + class
        TRANSITION_TABLE; this exposes them as a StageNode tree for the
        GraphExecutor without changing their declarations."""
        from ascendc_devkit.orchestration.node import AtomicStage, SequentialGroup
        table = self._get_transition_table()
        return SequentialGroup(
            name=self.name,
            description=self.description,
            children=[AtomicStage(s) for s in self.stages],
            transition_table=table,
            max_corrective=100,     # top scope uses State.max_corrective at runtime
            max_escalations=100,
        )


# —— Built-in Workflows ——

# Cross-group pipeline routes shared by workflows that mount the design groups
# (step-2b §7.1). A group's __escalate__:<cond> bubbles to the pipeline scope and
# is resolved here. Merged into each workflow's TRANSITION_TABLE.
_DESIGN_GROUP_PIPELINE_ROUTES = {
    "general-design": {
        "design_input_invalid":   ("requirement", "escalation"),
        "requirement_incomplete": ("requirement", "corrective"),
    },
    # detailed-design: P83 (step-58) escape hatch. validate's redo_doc/human/
    # redo_general no longer halt/escalate — they escape-forward at the group
    # level (carrying state.design_known_issues), so the group never bubbles a
    # condition and needs no pipeline routes here (§1.4/§2.5: no dead config).
    # step-79: general-design's design_needs_human→halt is REMOVED too — GD-H*
    # is resolved via in-flow resolve_ambiguity (decision → generator/requirement
    # corrective) or forward-escape as known_issue+needs_human_decision. Design
    # gates don't halt (step-60). A concept that fails to produce goes via
    # output_contract unsatisfied / stage fail_strategy, not a design halt.
}


def _design_groups():
    """(general-design group, detailed-design group) freshly built."""
    from ascendc_devkit.orchestration.design_tree import (
        build_general_design_group, build_detailed_design_group,
    )
    return build_general_design_group(), build_detailed_design_group()


def _design_root(workflow, before_names, after_names, include_detailed=True,
                 include_test_design=False, chip_version=""):
    """Build a root tree: AtomicStage(before...) → design group(s)
    → [test_design group] → AtomicStage(after...).

    ``chip_version`` determines which precision_debug variant (A3 4-substage or
    A5 6-substage) is built. Default "" → "A3".

    Mirrors full_test's hand-built root (step-2b §9.2, decision (a)): isolates the
    flat/subtree complexity in design workflows without touching the generic
    Workflow.root. `before_names`/`after_names` are flat stage names looked up in
    the registry; the design groups are inserted between them. When
    `include_test_design` is set, the test-design CompositeGroup (step-9 L4-a:
    analyze→casedesign→casegen) is inserted right after the design groups and
    before the after_names (codegen...), so acceptance cases are fixed pre-codegen.
    """
    from ascendc_devkit.orchestration.node import AtomicStage, SequentialGroup
    from ascendc_devkit.orchestration.registry import get_stage
    gd, dd = _design_groups()
    children = [AtomicStage(get_stage(n)()) for n in before_names]
    children.append(gd)
    if include_detailed:
        children.append(dd)
    if include_test_design:
        from ascendc_devkit.orchestration.design_tree import build_ascendc_st_design_node
        children.append(build_ascendc_st_design_node())
    _chip = chip_version or "A3"
    for n in after_names:
        if n == "precision_debug":
            # P0 (51-*.md): precision_debug is now a CompositeGroup, not a flat
            # stage — mount the group here (its position is the token in
            # after_names). Substitution keeps _design_root declarative.
            from ascendc_devkit.orchestration.precision_debug_tree import (
                build_precision_debug_group,
            )
            children.append(build_precision_debug_group(chip_version=_chip))
        else:
            children.append(AtomicStage(get_stage(n)()))
    return SequentialGroup(
        name=workflow.name,
        description=workflow.description,
        children=children,
        transition_table=workflow._get_transition_table(),
        max_corrective=100, max_escalations=100)


_PIPELINE_STAGE_NAMES = [
    "entry", "context", "requirement", "codegen_init", "codegen",
    "perf", "integrate", "finalize",
]


def _instantiate_pipeline_stages() -> list[Stage]:
    """Lazily instantiate the linear pipeline stages from the stage registry.

    test_design AND precision_debug are NOT here: both are CompositeGroups
    (test_design: step-9 L4-a analyze→casedesign→casegen; precision_debug: P0
    51-*.md run_tests→diagnose→…→scope_guard, 7-substage) mounted via the root
    override (_design_root), not flat linear Stages. flat_stages() walks the
    root and surfaces their substages for contract validation.
    """
    from ascendc_devkit.orchestration.registry import get_stage
    return [get_stage(name)() for name in _PIPELINE_STAGE_NAMES]


@register_workflow("generate_ascendc")
class GenerateAscendCWorkflow(Workflow):
    """Full pipeline for new AscendC operator generation (能力下沉 topology).

    Pipeline: entry → context → requirement → design → codegen → precision_debug
      → perf → integrate → finalize

    Capability sink (P57): build/deploy/smoke are owned in-session by codegen
    (agent runs ``redeploy`` → build+install+smoke self-fix loop); precision
    (functional+max_diff) is owned in-session by precision_debug (agent runs
    ``run-cases`` → 改码→commit→redeploy→run-cases loop). deploy/verify stages
    are deleted (no cross-stage error passing).

    Loop-back rules (centralized transition table):
      - codegen 迭代用尽仍 smoke 未过 → **不 halt**(step-84 D4): 告警 + 带
        deploy_result(smoke_passed=False) 前进,交 precision_debug scope_guard 分类
        (runtime→handle / compile→upstream halt). manifest 非契约（缺 callable_target/
        inputs/outputs 等）走**构造性派生 + 机械校验 + 定向 retry**（不 halt；callable_target.symbol
        从 plugin 注册派生，inputs/outputs 缺则反馈重试）；fail_strategy=halt 仅保留给真结构性
        失败(no_last_deploy) + infra(P116 独立于 fail_strategy) + artifact-retry 耗尽.
      - precision_debug exhausted (precision didn't converge) → __halt__
        (human triage; the agent looped through max_rounds without passing)
      - perf redesign needed → detailed-design (strategic change after tactical
        tuning exhausted — the one failure class genuinely tied to design)
      - perf tuned (code changed) → precision_debug (re-validate precision after
        perf's code change; perf改码后重验精度)
    """

    name = "generate_ascendc"
    description = "Full pipeline: requirement → design → codegen → precision_debug → perf → integrate"
    requires_npu = True   # codegen redeploy + precision_debug run-cases + perf need NPU

    # Centralized state machine transition table.
    # Keys not listed here use the linear successor (default).
    #
    # Format: {stage: {condition: (target_stage, route_type)}}
    #   route_type: "corrective" — same-strategy fix (quota-limited in non-interactive)
    #   route_type: "escalation" — architecture-level rework (strict quota, always confirmed)
    #   route_type: "validation" — forward re-validation, never counts as loopback
    #
    # Stagnation escalation (handled by dispatcher):
    #   corrective + same error 3 times → escalated to "escalation" target
    TRANSITION_TABLE = {
        # codegen needs no table entry: manifest 非契约走构造性派生 callable_target +
        # 机械校验 required_keys + 定向 retry（不 halt）；fail_strategy=halt still halts
        # STRUCTURAL failure (no_last_deploy) + infra (P116, 独立于 fail_strategy) +
        # artifact-retry 耗尽（manifest 反复补不全，无可调用算子交下游）
        # via _stage_failed BEFORE resolve_condition. step-84 D4: 迭代用尽仍 smoke
        # 未过**不再**设 last_error → 非 own_error → 不 halt,deploy_result 前进给
        # precision_debug scope_guard 分类(runtime/compile)。故 codegen 仍无需 table
        # 条目(smoke-fail 走线性前进,结构/infra-fail 走 _stage_failed halt)。
        "precision_debug": {
            # CompositeGroup (run_tests→diagnose→…, 7-substage). passed → escalate
            # (linear successor perf); 未通过 → exhausted → __halt__ 交人.
            # §12.1: upstream defect (codegen/test_design/golden/deploy fault
            # flagged by scope guard) → __halt__ — no point retrying.
            # passed is intentionally absent from this table: its escalate
            # lookup returns route=None → graph_executor falls through to the
            # linear successor (perf).  Making it explicit via a named-target
            # entry would couple this handler to the workflow topology.
            "exhausted": ("__halt__", "escalation"),
            "upstream": ("__halt__", "escalation"),
            # §judgment-ownership (P5): diagnose 尽力后假设空间穷尽（stalled）→ __halt__
            # 交人。与 upstream 同路径——模型尽力但修不动，需人工/上游接续。
            "stalled": ("__halt__", "escalation"),
        },
        "perf": {
            # perf is the one failure class genuinely tied to design — it
            # escalates to the detailed-design group (tiling/kernel decisions)
            # after tactical tuning is exhausted.
            "redesign": ("detailed-design", "escalation"),
            # perf改码后重验精度：perf-tuner 改了代码，precision_debug 重新 redeploy +
            # run-cases 验精度（旧 verify 占位换成 precision_debug）。
            "tuned":    ("precision_debug", "validation"),
        },
        **_DESIGN_GROUP_PIPELINE_ROUTES,
    }

    def __init__(self):
        super().__init__(
            name=self.name,
            description=self.description,
            stages=_instantiate_pipeline_stages(),
            requires_npu=True,
        )

    def _get_transition_table(self) -> dict[str, dict[str, str]]:
        return self.TRANSITION_TABLE

    def root(self, design_target_chip: str = ""):
        # entry → context → requirement → [general-design][detailed-design]
        #   → test_design → codegen_init → codegen → precision_debug → perf
        #   → integrate → finalize
        # codegen_init (step 9): deterministic section declaration before codegen.
        # test_design (step-4) fixes acceptance cases before codegen (TDD).
        _chip = design_target_chip or "A3"
        return _design_root(
            self,
            before_names=["entry", "context", "requirement"],
            after_names=["codegen_init", "codegen", "precision_debug", "perf",
                         "integrate", "finalize"],
            include_test_design=True,
            chip_version=_chip)


# —— SE Workflow: requirement analysis + general design ——

_SE_STAGE_NAMES = [
    "entry", "context", "requirement", "finalize",
]


def _instantiate_se_stages() -> list[Stage]:
    """Lazily instantiate the 5 SE pipeline stages."""
    from ascendc_devkit.orchestration.registry import get_stage
    return [get_stage(name)() for name in _SE_STAGE_NAMES]


@register_workflow("generate_ascendc_se")
class GenerateAscendCSEMWorkflow(Workflow):
    """SE workflow: requirement analysis → general design → deliver design doc.

    Pipeline: entry → context → requirement → design → finalize

    Designed for systems engineers who focus on requirement analysis and
    architecture-level design. Stops before detailed design and codegen.
    Each stage supports interactive review (approve/revise/abort).

    Output: design deliverable (design_spec, tiling_strategy, kernel_architecture, data_flow).
    """

    name = "generate_ascendc_se"
    description = "SE pipeline: requirement → general design → finalize deliverable"
    # SE is design-only: no NPU required (can run on CPU-only machines).

    # SE workflow is otherwise linear; design quality is ensured by interactive
    # review (AskUserQuestion approve/revise/abort). The one corrective edge is
    # the defensive design→requirement loop-back for an incomplete requirement,
    # mirroring generate_ascendc (RequirementStage normally self-converges).
    TRANSITION_TABLE: dict = {
        **_DESIGN_GROUP_PIPELINE_ROUTES,
    }

    def __init__(self):
        super().__init__(
            name=self.name,
            description=self.description,
            stages=_instantiate_se_stages(),
        )

    def _get_transition_table(self) -> dict[str, dict[str, str]]:
        return self.TRANSITION_TABLE

    def root(self, design_target_chip: str = ""):
        # entry → context → requirement → [general-design] → finalize
        # SE delivers the concept design only — no detailed-design group, no
        # codegen (job boundary; fixes the prior SE-emits-detailed-design bug).
        return _design_root(
            self,
            before_names=["entry", "context", "requirement"],
            after_names=["finalize"],
            include_detailed=False)


# —— Dev Workflow: detailed design → codegen → precision_debug → perf → integrate ——

_DEV_STAGE_NAMES = [
    "entry", "context", "codegen_init", "codegen",
    "perf", "integrate", "finalize",
]


def _instantiate_dev_stages() -> list[Stage]:
    """Lazily instantiate the Dev pipeline stages (能力下沉 topology)."""
    from ascendc_devkit.orchestration.registry import get_stage
    return [get_stage(name)() for name in _DEV_STAGE_NAMES]


@register_workflow("generate_ascendc_dev")
class GenerateAscendCDevWorkflow(Workflow):
    """Developer workflow (能力下沉 topology): codegen → precision_debug → perf.

    Pipeline: entry → context → design → codegen → precision_debug → perf
      → integrate → finalize

    Designed for developers who receive a general design from SE and need to
    complete the full implementation: detailed design → code → build → test → deliver.
    build/smoke owned in-session by codegen; precision owned by precision_debug
    (mirrors generate_ascendc).
    """

    name = "generate_ascendc_dev"
    description = "Dev pipeline: detailed design → codegen → precision_debug → perf → integrate → deliver"
    requires_npu = True   # codegen redeploy + precision_debug run-cases + perf need NPU

    TRANSITION_TABLE = {
        # codegen needs no entry (fail_strategy=halt 仅 no_last_deploy 结构失败 / infra /
        # artifact-retry 耗尽; manifest 非契约走派生+机械校验+定向 retry 不 halt; step-84 D4:
        # 迭代用尽 smoke-fail 不 halt、线性前进给 precision_debug;见 GenerateAscendCWorkflow).
        "precision_debug": {
            # passed is intentionally absent: route=None → linear successor (perf).
            "exhausted": ("__halt__", "escalation"),
            "upstream": ("__halt__", "escalation"),   # §12.1 scope guard
            "stalled": ("__halt__", "escalation"),   # §P5 diagnose 尽力后假设空间穷尽
        },
        "perf": {
            "redesign": ("detailed-design", "escalation"),
            "tuned":    ("precision_debug", "validation"),
        },
        **_DESIGN_GROUP_PIPELINE_ROUTES,
    }

    def __init__(self):
        super().__init__(
            name=self.name,
            description=self.description,
            stages=_instantiate_dev_stages(),
            requires_npu=True,
        )

    def _get_transition_table(self) -> dict[str, dict[str, str]]:
        return self.TRANSITION_TABLE

    def root(self, design_target_chip: str = ""):
        # entry → context → [general-design][detailed-design]
        #   → test_design → codegen_init → codegen → precision_debug → perf
        #   → integrate → finalize
        # codegen_init (step 9): deterministic section declaration.
        # Concept group runs pass-through when --general-design is supplied.
        # test_design (step-4) fixes acceptance cases before codegen (TDD).
        _chip = design_target_chip or "A3"
        return _design_root(
            self,
            before_names=["entry", "context"],
            after_names=["codegen_init", "codegen", "precision_debug", "perf",
                         "integrate", "finalize"],
            include_test_design=True,
            chip_version=_chip)


# —— Graph-native Workflow: parallel test suite via ForkJoinGroup ——

@register_workflow("full_test")
class FullTestWorkflow(Workflow):
    """Graph-native workflow: parallel test frameworks via ForkJoinGroup.

    pipeline → entry → [ForkJoin: test_suite] → finalize
    Demonstrates the StageNode tree built directly (not from flat stages)."""

    name = "full_test"
    description = "Parallel test suite via ForkJoinGroup"
    requires_npu = True   # precision_debug / test stages need NPU hardware

    def __init__(self):
        super().__init__(name=self.name, description=self.description, stages=[],
                         requires_npu=True)

    def root(self, design_target_chip: str = ""):
        from ascendc_devkit.orchestration.node import AtomicStage, SequentialGroup
        from ascendc_devkit.orchestration.node_forkjoin import ForkJoinGroup
        from ascendc_devkit.orchestration.precision_debug_tree import (
            build_precision_debug_group,
        )
        from ascendc_devkit.orchestration.registry import get_stage
        entry = AtomicStage(get_stage("entry")())
        finalize = AtomicStage(get_stage("finalize")())
        # Placeholder: reuse the precision_debug group as stand-in until real test
        # stages exist (verify deleted in the 能力下沉 redesign).
        _chip = design_target_chip or "A3"
        suite = ForkJoinGroup(name="test_suite", children=[
            build_precision_debug_group(chip_version=_chip),
        ])
        return SequentialGroup(name=self.name,
                               children=[entry, suite, finalize])


# —— Self-Evolution Workflow: codegen → precision_debug → cannbench_eval ——

_SELF_EVOLVE_STAGE_NAMES = [
    "entry", "context", "requirement", "codegen_init", "codegen",
    "cannbench_adapt", "cannbench_eval", "finalize",
]


def _instantiate_self_evolve_stages() -> list[Stage]:
    from ascendc_devkit.orchestration.registry import get_stage
    return [get_stage(name)() for name in _SELF_EVOLVE_STAGE_NAMES]


@register_workflow("self_evolve_op")
class SelfEvolveOpWorkflow(Workflow):
    """Self-evolution per-op pipeline (能力下沉 topology): codegen → precision_debug
      → cannbench_eval.

    Pipeline: entry → context → [design groups] → codegen → precision_debug
      → cannbench_adapt → cannbench_eval → finalize

    Capability sink (P57): build/deploy/smoke owned in-session by codegen;
    precision owned in-session by precision_debug. deploy/verify stages deleted.

    Two-tier evaluation:
      - codegen: in-session build loop (redeploy → build+install+smoke self-fix)
      - precision_debug (① inner-loop self-correction): agent runs run-cases
        against the deployed kernel + golden, 闭环迭代 改码→commit→redeploy→
        run-cases→日志→再改 until all cases pass or max_rounds exhausted.
      - cannbench_eval (② one-shot LOSS): kernel_eval --skip-install →
        overall_score (compile 0.2 + function 0.3 + performance 0.5). The
        training-time loss signal — it does NOT feed back to codegen.

    Loop-back rules:
      - codegen 迭代用尽 smoke-fail → **不 halt**(step-84 D4): 前进给 precision_debug
        scope_guard 分类(runtime→handle / compile→upstream). halt 仅结构/infra 失败。
      - precision_debug exhausted → cannbench_adapt (软门：① 本地预检不阻断 ②；
        D9 止损降级为 ② score，不再 __halt__ 中断链路)
      - cannbench_eval: NO loopback — it is the one-shot loss, not a corrective
        trigger (07 D4). A zero score is the loss.

    Used as the inference-time per-op runner inside TrainingRunner (05).
    """

    name = "self_evolve_op"
    description = "Self-evolution per-op: codegen → precision_debug → cannbench_eval"
    requires_npu = True   # codegen redeploy + precision_debug run-cases + cannbench_eval need NPU

    TRANSITION_TABLE = {
        # codegen needs no entry: manifest 非契约走构造性派生+机械校验+定向 retry（不 halt）；
        # fail_strategy=halt 仅 halt 结构性失败(no_last_deploy) + infra(P116) + artifact-retry
        # 耗尽 via _stage_failed；step-84 D4 迭代用尽 smoke-fail
        # 不设 last_error → 线性前进给 precision_debug(scope_guard 分类)。
        # P0: precision_debug 是 CompositeGroup（四子 stage）。passed → escalate
        #   (线性后继 cannbench_adapt)；未通过 → exhausted → 软门放行 cannbench_adapt
        #   （① 本地预检不阻断 ② 权威评分；D9 止损降级为 ② score）。
        # passed is intentionally absent: route=None → linear successor (cannbench_adapt).
        "precision_debug": {
            "exhausted": ("cannbench_adapt", "validation"),
            "upstream": ("__halt__", "escalation"),   # §12.1 scope guard: upstream defect → halt
            # §P5: stalled（diagnose 尽力后假设空间穷尽）→ __halt__ 交人。与 exhausted
            # 不同——exhausted 是预算耗尽止损走软门评个分；stalled 是模型判断「修不动，
            # 需人工/上游接续」，不该静默走 eval 评分（没通过没意义）。
            "stalled": ("__halt__", "escalation"),
        },
        # cannbench_eval intentionally absent: ② one-shot loss never routes back
        # to codegen (07 D4). Removing the old `eval_failed → codegen` edge keeps
        # the loss signal (②) from polluting the generation loop (①).
        **_DESIGN_GROUP_PIPELINE_ROUTES,
    }

    def __init__(self):
        super().__init__(
            name=self.name,
            description=self.description,
            stages=_instantiate_self_evolve_stages(),
            requires_npu=True,
        )

    def _get_transition_table(self) -> dict[str, dict[str, str]]:
        return self.TRANSITION_TABLE

    def root(self, design_target_chip: str = ""):
        # entry → context → requirement → [general-design][detailed-design]
        #   → test_design → codegen_init → codegen
        #   → precision_debug → cannbench_adapt → cannbench_eval → finalize
        # RequirementStage: LLM agent analyses human-readable requirement doc.
        # test_design (step-4): acceptance cases fixed before codegen (TDD).
        #   13 E1: golden (path/entry/input_type) and external cases come from
        #   the CLI (--golden-entry / --golden-input-type / --cann-bench-cases),
        #   not the repo profile. When --cann-bench-cases is supplied, test_design
        #   consumes those cann-bench cases and precision_debug consumes the
        #   cann-bench golden — ① becomes a local fast precheck of ②'s function
        #   dimension (same cases + same golden formula). No cases_path → LLM
        #   test-design chain (generate_ascendc and cases-less workflows).
        # codegen_init (step 9): deterministic section declaration.
        # precision_debug (能力下沉): runs the real deployed kernel vs golden
        #   (① inner-loop self-correction) via the in-session run-cases loop.
        # cannbench_adapt (step 11): LLM repo glue-file adaptation.
        _chip = design_target_chip or "A3"
        return _design_root(
            self,
            before_names=["entry", "context", "requirement"],
            after_names=["codegen_init", "codegen",
                         "precision_debug", "cannbench_adapt", "cannbench_eval", "finalize"],
            include_test_design=True,
            chip_version=_chip,
        )
