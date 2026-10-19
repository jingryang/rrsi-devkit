"""L3 Orchestration — ForkJoinGroup: parallel children with merge."""

from __future__ import annotations

from dataclasses import dataclass, field

from ascendc_devkit.orchestration.node import StageNode
from ascendc_devkit.domain.contract import StageIOContract


class StateConflictError(Exception):
    """Two ForkJoin children declared the same output field."""


@dataclass
class ForkJoinGroup(StageNode):
    name: str = ""
    description: str = ""
    children_list: list = field(default_factory=list)
    concurrency: str = "thread"

    def __init__(self, name="", description="", children=None,
                 concurrency="thread", branch_factory=None,
                 input_contract_override=None, output_contract_override=None,
                 rerun_selector=None):
        self.name = name
        self.description = description
        self.children_list = list(children or [])
        self.concurrency = concurrency
        # Optional state-driven branch builder (step-2b B', §4.2). When set,
        # resolved_children(state) returns branch_factory(state) instead of the
        # static children_list — letting the tiling fork-join expand one branch
        # per template once template-division has written state.template_division.
        # When None (e.g. full_test), resolved_children falls back to the static
        # children_list → zero regression for existing fork-join nodes.
        self.branch_factory = branch_factory
        # A dynamic node has no static children to aggregate a contract from
        # (§4.3 "contract footgun"). Callers declare the node's outward contract
        # explicitly so flat_stages / validate_chain can see it.
        self._input_override = input_contract_override
        self._output_override = output_contract_override
        # Optional template-precise rerun hook (step-2b C4, R8 follow-up):
        # rerun_selector(state) -> set[str] | None. On a loop-back that targets
        # this node, the executor clears ONLY the named branch subtrees (others
        # skip via their still-completed node_status); None means clear all
        # branches (full rerun). Domain judgment (which template is infeasible)
        # lives in the selector the builder supplies; the executor stays generic.
        self.rerun_selector = rerun_selector

    def children(self) -> list[StageNode]:
        return self.children_list

    def resolved_children(self, state) -> list[StageNode]:
        """Branches to execute for this run.

        Uses branch_factory(state) when present (dynamic per-state expansion),
        else the static children_list. GraphExecutor calls this (guarded by
        hasattr) so dynamic and static fork-join nodes share one execution path.
        Dynamic nodes must NOT rely on their own contract aggregation (empty
        static children → empty contract); the outward contract is carried by
        the contract overrides set at construction (§4.3).
        """
        if self.branch_factory is not None:
            return list(self.branch_factory(state))
        return self.children_list

    def input_contract(self) -> StageIOContract:
        if self._input_override is not None:
            return self._input_override
        requires: list[str] = []
        for c in self.children_list:
            for r in c.input_contract().requires:
                if r not in requires:
                    requires.append(r)
        return StageIOContract(requires=requires)

    def output_contract(self) -> StageIOContract:
        if self._output_override is not None:
            return self._output_override
        provides: list[str] = []
        optional_provides: list[str] = []
        for c in self.children_list:
            oc = c.output_contract()
            for p in oc.provides:
                if p not in provides:
                    provides.append(p)
            for p in oc.optional_provides:
                if p not in optional_provides and p not in provides:
                    optional_provides.append(p)
        return StageIOContract(provides=provides, optional_provides=optional_provides)


def merge_forkjoin(base, children, child_states):
    """Merge each child's declared output fields back into base.

    Dict fields are shallow key-merged INTO base (step-2b R1 + C2 follow-up): a
    branch contributes its own template key into ``tiling_results={template:...}``
    and any keys already in base (e.g. templates not rerun on an anchor→tiling
    partial rerun) are preserved. The duplicate-key guard checks only
    sibling-vs-sibling keys, so a template carried in base is NOT mistaken for a
    collision — only two branches writing the same template name raise. Non-dict
    same-field writes from two branches still conflict (StateConflictError).
    """
    merged = base
    dict_keys: dict[str, set] = {}    # field -> sibling-contributed keys (dict fields)
    nondict_fields: set[str] = set()  # fields a sibling wrote as a non-dict value
    for child, cstate in zip(children, child_states):
        provides = set(child.output_contract().all_provides())
        for f in provides:
            val = getattr(cstate, f)
            if val is None:
                # A branch that never wrote this field (e.g. it failed before
                # producing it) contributes nothing — skip so its unwritten None
                # is not mistaken for a deliberate non-dict write that would
                # collide with a sibling's real dict (the StateConflictError
                # crash, step-60 P1). Last-resort defense; the executor also
                # filters failed branches out before calling merge (step-60 B).
                continue
            if isinstance(val, dict):
                if f in nondict_fields:
                    raise StateConflictError(
                        f"ForkJoin child '{child.name}' writes dict {f!r} "
                        f"already written as non-dict by a sibling")
                clash = dict_keys.get(f, set()) & set(val)  # sibling-vs-sibling only
                if clash:
                    raise StateConflictError(
                        f"ForkJoin dict-merge on '{f}' has overlapping keys "
                        f"{sorted(clash)} (duplicate template name?)")
                prev = getattr(merged, f)
                base_dict = prev if isinstance(prev, dict) else {}
                if f == "tiling_results":
                    # 内层（template → segment）合并：resume 部分重跑时 branch 的
                    # entry 只含本次重跑的段（split/vf-design 已完成被跳过），顶层
                    # 覆盖会丢弃 base 里未重跑的段（如 A5 的 vf_design）→ 下游
                    # codegen 无法构建 VF contract。逐模板保留 base 段再并入 branch
                    # 本次产出的段（同名段以 branch 为准——更新产物）。
                    merged_tiling = dict(base_dict)
                    for tmpl, entry in val.items():
                        if isinstance(entry, dict) and isinstance(
                                merged_tiling.get(tmpl), dict):
                            merged_tiling[tmpl] = {**merged_tiling[tmpl], **entry}
                        else:
                            merged_tiling[tmpl] = entry
                    merged = merged.with_field(f, merged_tiling)
                else:
                    merged = merged.with_field(f, {**base_dict, **val})  # base preserved
                dict_keys.setdefault(f, set()).update(val)
                continue
            if f in dict_keys or f in nondict_fields:
                raise StateConflictError(
                    f"ForkJoin child '{child.name}' writes {f!r} "
                    f"already written by a sibling")
            nondict_fields.add(f)
            merged = merged.with_field(f, val)
    return merged
