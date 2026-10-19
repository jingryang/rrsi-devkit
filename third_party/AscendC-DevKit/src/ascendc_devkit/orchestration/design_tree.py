"""L3 Orchestration — Design subtree builders (step-2b P3, §四).

Two parallel top-level groups (revised from 2a's single subtree, §4.0):
  - general-design group: general-design-generator (single stage; the generator
    self-checks its own product — no separate review gate).
  - detailed-design group: template-division → tiling[ForkJoin] → synthesize.
    Producer stages self-check (§2.9); cross-template consistency is
    constructed by synthesize (single author + downstream faithful consumption),
    and golden comparison at codegen is the only catch-all (§1.13). No quality
    gates — the design gate subsystem (general-design-review / anchor /
    validate) was removed per the 最小结构 direction (§1.14).

Job boundary = group boundary: SE workflows mount only the general-design
group; Dev/full workflows mount both. The tiling node is a dynamic ForkJoinGroup
whose branches are built per-template via branch_factory (B', §4.2); its outward
contract is carried by the detailed-design group's output_contract_override
(§4.3) since the dynamic node has no static children to aggregate.
"""

from __future__ import annotations

from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.orchestration.node import AtomicStage, SequentialGroup, CompositeGroup
from ascendc_devkit.orchestration.node_forkjoin import ForkJoinGroup
from ascendc_devkit.orchestration.stages.design_substages import (
    GeneralDesignStage,
    TemplateDivisionStage, SynthesizeStage, DocgenStage,
    DetailedDesignIntakeStage,
    TilingStage,
)

# The detailed-design group runs linearly with no internal corrective loop-back.
# The only transition is dd-intake's short-circuit: a user-supplied detailed
# design (--detailed-design) is parsed by dd-intake into the three-piece
# contract, then jumps forward to synthesize (the assembly owner), skipping
# generation (division/tiling). When no doc is supplied dd-intake
# resolves "default" and the group runs the normal flow linearly.
_DETAILED_DESIGN_TRANSITION_TABLE: dict = {
    "dd-intake": {
        "short_circuit": ("synthesize", "validation"),
    },
}


def _template_name(t) -> str:
    """Branch name for a template entry (dict {name:...} or bare string)."""
    if isinstance(t, dict):
        return str(t.get("name", ""))
    return str(t)


def tiling_branch_factory(state) -> list[SequentialGroup]:
    """One branch per template, each running a single TilingStage (merged
    split → vf-design → buffer-kernel → precision-perf in one agent session,
    step-2b §6.2 合并版 §1.14). vf-design's A5-only skip is decided inside the
    ``ascendc-op-tiling`` facade skill (reads chip programming model), so the
    A2/A3 path degenerates to split → buffer-kernel → precision-perf within the
    same session.

    Branch name is the bare template name so node paths read
    pipeline/detailed-design/tiling/<template>/tiling.
    """
    division = getattr(state, "template_division", None) or {}
    templates = division.get("templates", [])
    branches: list[SequentialGroup] = []
    for t in templates:
        name = _template_name(t)
        branches.append(SequentialGroup(name=name, children=[
            AtomicStage(TilingStage(template=t)),
        ]))
    return branches


def _build_tiling_node() -> ForkJoinGroup:
    # Dynamic node: branches are built per-template at execute time, so it has no
    # static children to aggregate a contract from. Declare the contract
    # explicitly (§4.3) so flat_stages / validate_chain see requires/provides.
    return ForkJoinGroup(
        name="tiling",
        branch_factory=tiling_branch_factory,
        input_contract_override=StageIOContract(requires=["template_division"]),
        output_contract_override=StageIOContract(provides=["tiling_results"]))


def build_general_design_group() -> CompositeGroup:
    """Concept-design group: a single generator stage (no review gate — the
    generator self-checks CR1 four-fields / CR2 gradient formula / 边界红线
    before writing general_design.json)."""
    from ascendc_devkit.orchestration.runtime_config import design_group_quota
    children = [
        AtomicStage(GeneralDesignStage()),        # name="general-design-generator"
    ]
    quota = design_group_quota("general_design_group")
    return CompositeGroup(
        name="general-design",
        children=children,
        transition_table={},
        # template_decision（SIMD/SIMT 判定）为 optional：仅 A5 路径产出，
        # A2/A3 平台锁定 SIMD 不产出。
        output_contract_override=StageIOContract(
            provides=["general_design"],
            optional_provides=["template_decision"]),
        max_corrective=quota["max_corrective"],
        max_escalations=quota["max_escalations"],
    )


def build_detailed_design_group() -> CompositeGroup:
    """Detailed-design group: template-division → tiling[ForkJoin] → synthesize →
    docgen. Producer stages self-check (§2.9); no quality gates. Synthesize 只做
    integrate（design_spec + tiling_strategy）；docgen 独立成段（§1.14 最小结构 +
    §2.9 下游忠实消费上游产物），读 synthesize 产物组装 详细设计说明书，不依赖与
    integrate 同会话（消除长上下文稀释，docs/plan/synthesize-docgen-dilution/）。"""
    from ascendc_devkit.orchestration.runtime_config import design_group_quota
    children = [
        AtomicStage(DetailedDesignIntakeStage()),
        AtomicStage(TemplateDivisionStage()),
        _build_tiling_node(),
        AtomicStage(SynthesizeStage()),
        AtomicStage(DocgenStage()),
    ]
    quota = design_group_quota("detailed_design_group")
    return CompositeGroup(
        name="detailed-design",
        children=children,
        transition_table=_DETAILED_DESIGN_TRANSITION_TABLE,
        # kernel_architecture removed from design output (step 9):
        # section declaration is now codegen_init's responsibility — sections
        # depend on target repo layout, not operator design. design_doc is the
        # 详细设计说明书 path (docgen portion of the merged synthesize owner).
        output_contract_override=StageIOContract(
            provides=["design_spec", "tiling_strategy", "design_doc"],
            optional_provides=["data_flow"]),
        max_corrective=quota["max_corrective"],
        max_escalations=quota["max_escalations"],
    )


def build_ascendc_st_design_node():
    """Single AtomicStage wrapping the ascendc-st-design skill.

    Replaces the old 3-substage CompositeGroup (test-analyze →
    test-casedesign → test-casegen).  The node is an AtomicStage so
    exhausted → route=None → linear successor — unlike the old group's
    halt behavior, the deterministic script chain in ascendc-st-design
    makes exhaustion far less likely, and proceeding to codegen gives
    more actionable feedback.
    """
    from ascendc_devkit.orchestration.registry import get_stage
    from ascendc_devkit.orchestration.node import AtomicStage
    return AtomicStage(get_stage("ascendc-st-design")())
