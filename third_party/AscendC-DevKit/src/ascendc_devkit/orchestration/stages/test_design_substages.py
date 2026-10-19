"""L3 Orchestration — test_design substages (step-9 L4-a).

The test_design stage is a CompositeGroup of three serial substages mirroring
the design group's "one spawn, one slash, one skill" closed loop (§P9):

    test-analyze → test-casedesign → test-casegen

Each substage reuses the role-A generator agent (ascendc-design-generator) and
is assigned its testdesign skill via STAGE_SKILL_MAP; the spawn's first message
leads with /<skill> (bare name) so the session injects the methodology.

First-principle (CLAUDE.md): the three substages SHARE one working dir so the
skills hand off via files (analyze writes test_analysis.json → casedesign reads
it → ... → casegen writes the CSV). This is the opposite of the design tiling
segments, which isolate per-template subdirs to avoid parallel clobber — the
test chain is serial and self-relays, so it must share a dir.
"""

from __future__ import annotations

import json
from pathlib import Path

from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.orchestration.registry import register_stage
from ascendc_devkit.orchestration.design_artifacts import (
    load_authoritative_requirement,
)
from ascendc_devkit.orchestration.stages.design_substages import _DesignSubstage
from ascendc_devkit.orchestration.kernel.action import NoOp


class _TestDesignSubstage(_DesignSubstage):
    """Role-A generator + a single SHARED working dir.

    Unlike design substages (each isolated under design/<name>), the three test
    substages share one working dir so the skills hand off via files (analyze
    writes test_analysis.json → casedesign reads it → ...) — the first-principle
    self-closure relay. Everything else (file materialization of upstream inputs,
    suppressed prompt-injection, _INPUT_FILENAMES) is inherited from
    _DesignSubstage (step-10 lifted it to the base; F2).
    """

    agent_name = "ascendc-design-generator"

    def _working_dir(self, state):
        if not state._workspace:
            return None
        return state._workspace.artifacts / "test_design"

    @staticmethod
    def _validate_cases_against_spec(state, cases) -> str | None:
        """step-105 防线3：用例 attrs 对 op_spec 契约的一致性自检（产出当下）。

        单点复用域层校验器 ``validate_case_attrs``（§1.15——runner pre-flight 与
        本自检同一通路，编排层不 import adapter 私有符号）；失败 = test_design
        自身产物验收不过（用例↔契约不一致——20260829 interpolate 事故形态：契约
        压平 list[int] vs 用例忠实嵌套 [[1,1]]，3 小时后才在 smoke 联合点爆）。
        冲突以 golden 为准上报（§1.13），不自修（§2.9 producer 自检）。
        无 op_spec / 无 attrs 声明时退化为无操作（本 stage 无契约可对）。
        """
        from ascendc_devkit.domain.operator import OperatorSpec, validate_case_attrs

        op_spec = getattr(state, "op_identity", None)
        op_spec = getattr(op_spec, "spec", None) if op_spec else None
        if op_spec is None:
            req = getattr(state, "requirement", None)
            op_spec = getattr(req, "op_spec", None) if req else None
        if op_spec is None or not isinstance(op_spec, OperatorSpec):
            return None
        spec_map = getattr(op_spec, "attrs", None) or {}
        if not spec_map:
            return None
        from ascendc_devkit.domain.exceptions import HarnessContractError
        for idx, tc in enumerate(cases):
            attrs = getattr(tc, "attrs", None)
            if not attrs:
                continue
            try:
                validate_case_attrs(attrs, idx, operator=op_spec)
            except HarnessContractError as exc:
                return (
                    f"test_design 产物自检失败（用例↔契约不一致）: {exc}。"
                    f"冲突以 golden 为准——契约声明须忠实 golden 语义"
                    f"（嵌套列表声明 list[list[int]]）；用例值形态亦须忠实 "
                    f"golden。本错误不自修，需人工对齐三方（golden/op_spec/用例）。")
        return None

    @classmethod
    def _has_external_cases(cls, state) -> bool:
        """True when the user supplied an external cases CSV (state.cases_path).

        13 E1: cases source is an explicit CLI path (--cann-bench-cases), not a
        profile-declared template. No ``{N}``/``{op}`` probing — the path is
        absolute. Empty/None → the LLM test-design chain runs (generate_ascendc
        and other cases-less workflows keep their LLM chain)."""
        return bool(getattr(state, "cases_path", None))

    def actions(self, state, iteration: int = 1):
        if self._has_external_cases(state):
            # External cases CSV supplied → skip the LLM chain; TestCaseGenStage
            # loads them in transition(). No spawn, no review.
            #
            # contract_satisfied=True (P33): external cases 替代了 analyze/casedesign
            # 的 LLM 产物,这两 stage 的 output_contract(test_analysis / test_casedesign)
            # 在此场景本就不适用 —— 显式声明"确定性跳过",豁免 output_contract 未满足
            # 判定,避免"NoOp → 契约未满足 → 重试 NoOp"死循环耗尽 budget 误 halt。
            # casegen 的 test_cases 由 transition 真实加载;若加载失败它记 own_error,
            # runner 仍按 failed/halt 处理(contract_satisfied 不掩盖真错误)。
            return [NoOp(
                reason=("external cases_path supplied — cases loaded deterministically; "
                        "LLM test design skipped (13 E1)"),
                contract_satisfied=True)]
        return super().actions(state, iteration)


@register_stage
class TestAnalyzeStage(_TestDesignSubstage):
    name = "test-analyze"
    description = "Extract test-relevant info from design products + requirement"
    prompt_intro = (
        "基于设计产物（design_spec / tiling_strategy）与算子需求规格，"
        "做测试分析：特性分析、精度链、边界维度、泛化维度、异常场景、tiling 测试点。"
        "从当前工作目录读取已物化的设计产物文件，产出结构化测试分析报告。")

    def input_contract(self) -> StageIOContract:
        return StageIOContract(
            requires=["requirement", "design_spec", "tiling_strategy"],
            optional=["tiling_results", "design_doc", "user_feedback",
                      "last_error"])

    def output_contract(self) -> StageIOContract:
        return StageIOContract(provides=["test_analysis"])
    _schema_files = ["test_analysis.json"]

    def validate_inputs(self, state: "State") -> list[str]:
        # T1 fail-fast: test design must be driven by the design products, not
        # a bare context. Missing design 产物 → hard error (never improvise).
        # 注:kernel_architecture 自 step-9 起改由 codegen_init(test_design 之后)
        # 产出,且语义变成 section 目录清单(与算子设计无关),故不再纳入硬校验——
        # test-analyze 跑时它必为 None,校验它会让 test_design 永远 fail-fast。
        errors = []
        for field in ("design_spec", "tiling_strategy"):
            if not getattr(state, field, None):
                errors.append(f"test-analyze requires '{field}' (design product missing)")
        if state.requirement is None:
            errors.append("test-analyze requires 'requirement'")
        elif load_authoritative_requirement(state) is None:
            # P1/§3.12（与 GeneralDesignStage 同口径）: requirement 在 State 但权威
            # 磁盘文件不可达 → 物化拿不到全量需求（domain/公式/dtype 域），加载期拦截
            # 而非让 agent 拿 reduced 或缺 requirement.json 静默降质。
            errors.append(
                "requirement 存在于 State 但权威磁盘文件 "
                "artifacts/requirement/requirement.json 不可达——无法物化全量需求")
        return errors

    def _upstream_inputs(self, state: "State") -> dict:
        return {
            "requirement": getattr(state, "requirement", None),
            "design_spec": getattr(state, "design_spec", None),
            "tiling_strategy": getattr(state, "tiling_strategy", None),
            "tiling_results": getattr(state, "tiling_results", None),
        }

    def transition(self, state: "State", result: dict) -> "State":
        # 13 E1: external cases short-circuit — analyze's LLM product isn't
        # needed when cases come from state.cases_path; pass through unchanged.
        if self._has_external_cases(state):
            return state
        new_state, _ok = self._parse_single(
            state, result, "test_analysis", "test_analysis.json")
        return new_state


@register_stage
class TestCaseDesignStage(_TestDesignSubstage):
    name = "test-casedesign"
    description = "Turn test analysis into case-design (shape/boundary/redline...)"
    prompt_intro = (
        "基于测试分析报告（test_analysis.json，已在当前工作目录），按各类用例规则"
        "（网络shape / 泛化 / 边界值 / 红线 / 异常 / 专项）生成用例设计方案，"
        "执行知识库自学习（references/ 案例）确保风格与案例一致。")

    def input_contract(self) -> StageIOContract:
        return StageIOContract(
            requires=["test_analysis"],
            optional=["user_feedback", "last_error"])

    def output_contract(self) -> StageIOContract:
        return StageIOContract(provides=["test_casedesign"])
    _schema_files = ["test_casedesign.json"]

    def _upstream_inputs(self, state: "State") -> dict:
        return {"test_analysis": getattr(state, "test_analysis", None)}

    def transition(self, state: "State", result: dict) -> "State":
        # A5: external cases short-circuit — pass through (cases loaded by casegen).
        if self._has_external_cases(state):
            return state
        new_state, _ok = self._parse_single(
            state, result, "test_casedesign", "test_casedesign.json")
        return new_state


@register_stage
class TestCaseGenStage(_TestDesignSubstage):
    name = "test-casegen"
    description = "Generate the acceptance-case CSV from the case design"
    # The acceptance cases harden into codegen's contract, so this is the
    # test-design group's review boundary: in interactive mode the user
    # approves/revises the cases here. review_node_name is the group name so the
    # configured "test_design" review point fires after the last substage.
    review_node_name = "test_design"
    default_max_iterations = 2
    prompt_intro = (
        "基于用例设计方案（test_casedesign.json，已在当前工作目录），用脚本生成 13 列"
        "规格型测试用例 CSV（UTF-8-BOM），去重 + 自检（正/反向算子名）后产出合并版 CSV。")

    def input_contract(self) -> StageIOContract:
        return StageIOContract(
            requires=["test_casedesign"],
            optional=["user_feedback", "last_error"])

    def output_contract(self) -> StageIOContract:
        return StageIOContract(provides=["test_cases", "test_design_report"])
    _schema_files = ["testcase_csv.json"]

    def _upstream_inputs(self, state: "State") -> dict:
        return {"test_casedesign": getattr(state, "test_casedesign", None)}

    def transition(self, state: "State", result: dict) -> "State":
        # 13 E1: state.cases_path set → load the external cann-bench cases
        # deterministically; no agent_result, no CSV parsing. Failures record
        # last_error so the runner retries / halts rather than slipping an empty
        # case set into codegen.
        if self._has_external_cases(state):
            return self._load_external_cases(state)
        # The CSV is parsed by the anti-corruption adapter (not artifact_contract,
        # which only drives the column-contract prompt). Ported from the former
        # monolithic TestDesignStage: locate CSV under the shared dir, normalize,
        # fail (record last_error) on missing/empty/unparseable so the runner
        # retries rather than letting an empty case set slip into codegen.
        agent_result = result.get("agent_result")
        if agent_result is None:
            return self._error(state, "test-casegen: agent produced no result")
        wd = self._working_dir(state)
        if wd is None or not Path(wd).is_dir():
            return self._error(state, f"test-casegen working dir missing: {wd}")
        csv_path = self._locate_csv(Path(wd))
        if csv_path is None:
            # 孤儿就地恢复（20260821 F3 全局收口）：CSV 定位失败 → transcript 证据
            # → recover_orphan_artifact 搬回 → 重新定位。CSV 是多产物（合并/测试
            # 用例/裸 csv），恢复按产物名 ".csv" 扩展 + stem 容错匹配（检测层
            # 语义），拒搬落回既有 _error 重试。
            from ascendc_devkit.orchestration.artifact_recovery import (
                recover_orphan_artifact)
            transcript = getattr(agent_result, "transcript", None)
            if (transcript is not None
                    and recover_orphan_artifact(
                        transcript, "测试用例.csv", wd, state, self.name)):
                csv_path = self._locate_csv(Path(wd))
        if csv_path is None:
            return self._error(state, f"no test-case CSV found under {wd}")
        from ascendc_devkit.adapters.testdesign import parse_testcase_csv
        try:
            cases = parse_testcase_csv(csv_path)
        except ValueError as exc:
            return self._error(
                state, f"CSV→TestCase normalization failed: {exc}",
                error_type="schema_violation")
        if not cases:
            return self._error(
                state, f"test-case CSV {csv_path.name} produced 0 cases")
        err = self._validate_cases_against_spec(state, cases)
        if err:
            return self._error(state, err, error_type="schema_violation")
        report_path = self._locate_report(Path(wd))
        # F6：收尾清错统一归 runner（delivered-success 归一化）。
        return state.with_updates(
            test_cases=cases, test_design_report=report_path,
            cases_source="devkit",   # step-40: LLM-generated CSV cases
            user_feedback="")

    def resolve_condition(self, state: "State") -> str:
        """Route for the group/pipeline transition tables (ported from the
        former monolithic TestDesignStage §九).

        - cases produced → "default" (group proceeds; linear successor codegen).
        - failed and budget exhausted → "exhausted": the group escalates this to
          the pipeline scope where test_design:{exhausted: __halt__} halts for
          human triage rather than letting an empty case set reach codegen.
        - failed but budget remains → "default" (no scoped retry edge; the
          runner already retries within the stage up to its budget).

        A casegen failure is almost always a skill-output problem (CSV missing/
        empty), not a structural flaw, so we halt rather than rewind design.
        """
        if state.test_cases:
            return "default"
        if state.last_error is None:
            return "default"
        iters = state.stage_iterations.get(self.name, 0)
        if iters >= self.effective_max_iterations():
            return "exhausted"
        return "default"

    def _load_external_cases(self, state: "State") -> "State":
        """Load cases from state.cases_path (13 E1). Deterministic — no LLM,
        no ``{op}``/``{N}`` substitution (the path is the user-supplied absolute
        CSV)."""
        from ascendc_devkit.domain.cann_bench_cases_loader import load_cann_bench_cases
        try:
            cases = load_cann_bench_cases(state.cases_path)
        except Exception as exc:
            return self._error(
                state, f"external cases_path load failed: {exc}",
                error_type="schema_violation")
        if not cases:
            return self._error(
                state, "external cases_path produced 0 cases")
        err = self._validate_cases_against_spec(state, cases)
        if err:
            return self._error(state, err, error_type="schema_violation")
        # F6：收尾清错统一归 runner（delivered-success 归一化）。
        return state.with_updates(
            test_cases=cases, cases_source="cannbench",  # step-40: cann-bench task cases
            user_feedback="")

    @staticmethod
    def _locate_csv(working_dir: Path) -> "Path | None":
        csvs = sorted(working_dir.rglob("*.csv"),
                      key=lambda p: (len(p.parts), p.stat().st_mtime),
                      reverse=True)
        if not csvs:
            return None
        for p in csvs:
            if "合并" in p.name:
                return p
        for p in csvs:
            if "测试用例" in p.name:
                return p
        return csvs[0]

    @staticmethod
    def _locate_report(working_dir: Path) -> "Path | None":
        mds = sorted(working_dir.rglob("*.md"),
                     key=lambda p: (len(p.parts), p.stat().st_mtime),
                     reverse=True)
        for p in mds:
            if "设计方案" in p.name or "测试设计" in p.name:
                return p
        return mds[0] if mds else None
