"""L3 Orchestration — ascendc-st-design stage (replaces old 3-step test-design chain).

The old ``test-analyze → test-casedesign → test-casegen`` CompositeGroup is
replaced by a single AtomicStage wrapping the ``ascendc-st-design`` skill,
which provides L0/L1/L2 test-case levels + a deterministic constraint solver
(6 of 8 pipeline steps are Python scripts, not LLM).

Input adapter: ``adapters/testdesign/convert_to_param_def.py`` deterministically
converts ``requirement.json`` + ``design_spec.json`` → ``03_参数定义.yaml``,
skipping the LLM-driven steps 1-2 of the skill so the agent starts from step 3.
The adapter lives in the framework adapter layer (not the skill): it reads
DevKit workflow products (requirement.json / design_spec.json) that don't exist
when the skill is taken standalone, so it must not ship inside the skill dir.

Incremental fusion (P34): external cann-bench cases (``state.cases_path``) and
the LLM-designed cases are NOT mutually exclusive. When a workspace is present
the LLM pipeline always runs; its product is the **supplement** appended to the
external cases (external = benchmark-authoritative primary → ``cases_source``
stays ``"cannbench"`` so the cann-bench standard still governs the merged set).
Without a workspace the LLM cannot run (no CWD to write into) and external cases
are loaded deterministically — the degenerate standalone path.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.orchestration.registry import register_stage
from ascendc_devkit.orchestration.stages.design_substages import _DesignSubstage
from ascendc_devkit.orchestration.kernel.action import NoOp

_log = logging.getLogger(__name__)


@register_stage
class AscendCSTDesignStage(_DesignSubstage):
    """Single-stage wrapper for the ``ascendc-st-design`` skill.

    Replaces the old 3-substage CompositeGroup (test-analyze →
    test-casedesign → test-casegen) with one AtomicStage that wraps the
    full L0/L1/L2 test-design pipeline.  The skill is assigned via
    ``STAGE_SKILL_MAP`` (central config), same as all design substages.

    Paths:
      - **workspace present**: the deterministic input adapter
        (``adapters/testdesign/convert_to_param_def.py``) runs first (<1s), then
        the agent is spawned with the ``ascendc-st-design`` skill mounted and
        instructed to start from step 3. This happens whether or not external
        cann-bench cases were supplied — with external cases the LLM product is
        merged in as a supplement (incremental fusion).
      - **no workspace**: no CWD to run the LLM; external cases (if any) are
        loaded deterministically in ``transition()`` — degenerate path.
    """

    name = "ascendc-st-design"
    description = (
        "Generate L0/L1/L2 acceptance-test cases from design products "
        "via the ascendc-st-design skill (deterministic constraint solver "
        "+ LLM constraint analysis)"
    )
    agent_name = "ascendc-design-generator"
    # Keep the review boundary name "test_design" so the existing review
    # config (orchestration-config.json review.points) continues to fire
    # after this stage without config changes.
    review_node_name = "test_design"
    default_max_iterations = 2
    # 耗竭语义：test_design 是「生成验收用例」而非设计阶段——耗竭时前逃 codegen_init
    # 让 codegen 用 safe defaults（deploy smoke 对无 cases 有 synthetic probe 兜底），
    # 与方案文档「统一前逃」一致。不继承 _DesignSubstage 的 halt（设计产物错误不可
    # 自愈、空 cases 前逃无害；二者语义不同，§1.10 业务语义显式声明）。
    fail_strategy = "continue"

    prompt_intro = (
        "从 step 3 开始执行 ascendc-st-design 工作流。\n"
        "step 1-2 的产出 `design/03_参数定义.yaml` 已通过确定性输入适配器 "
        "在 CWD 生成好（从 requirement.json + design_spec.json 转换）。\n"
        "所有脚本调用使用 CWD 相对路径（<skill_dir>/scripts/，skill 文档有约定），"
        "设计中间产物输出到 `./design/`，最终 CSV 输出到 `./testcases/`。\n"
        "step 9 完成后用 skill 文档的 `merge_test_cases.py` 命令合并 L0/L1/L2 CSV"
        "到 CWD 根，产出 `./合并_测试用例.csv`（`--op-name {op_name}` 取自 "
        "requirement.json 的 op.name，`--aclnn-name {aclnn_name}` 取自 "
        "design/03_参数定义.yaml 的 aclnn_name 字段）。\n"
        "禁止手写合并脚本——必须用 skill 的确定性脚本，确保 stc_input_dtypes 等列为 "
        "合法的 Python tuple repr（如 `('float32',)` 而非裸 `float32`）。\n"
        "\n"
        "【必交产物 · 测试设计方案报告】合并完成后执行 skill step 10「测试设计结果总结」，"
        "在 CWD（当前工作目录）下产出 markdown 报告，文件名固定 `测试设计方案.md`。"
        "这是本 stage 输出契约产物 test_design_report，下游必依赖——缺它 stage 判 fail、"
        "整条 workflow halt，务必产出不可跳过。内容总结测试设计全过程，至少覆盖："
        "(1) 算子参数定义 (2) 提取的测试因子 (3) 参数依赖关系 (4) 隐式约束 "
        "(5) 测试因子依赖图 (6) 约束求解与因子值生成 (7) L0/L1/L2 用例生成结果（含各级用例数）。"
        "报告写到 CWD（./测试设计方案.md），不要写绝对路径或仓库路径——stage 只在 CWD 扫描 .md。\n"
        "\n"
        "【03_参数定义.yaml 的修改边界】03 由输入适配器从 requirement.json + "
        "design_spec.json 确定性生成，执行中不要重建或改写它（参数结构与 "
        "value_range 等字段一律不改——值域问题应修上游声明，而非就地改 03）。仅当"
        "框架反馈明确指出 03 与上游 JSON 不一致（适配器失败 / 对质违规）时，才按 "
        "skill step 1-2 依据两个 JSON 修复对应条目。"
    )

    # ── contracts ──────────────────────────────────────────────────────

    def input_contract(self) -> StageIOContract:
        return StageIOContract(
            requires=["requirement", "design_spec"],
            optional=["tiling_strategy", "cases_path", "last_error",
                      "user_feedback"],
        )

    def output_contract(self) -> StageIOContract:
        return StageIOContract(
            provides=["test_cases", "test_design_report"],
        )

    # ── working dir ────────────────────────────────────────────────────

    def _working_dir(self, state):
        if not state._workspace:
            return None
        return state._workspace.artifacts / "test_design"

    # ── upstream inputs ────────────────────────────────────────────────

    def _upstream_inputs(self, state: "State") -> dict:
        return {
            "requirement": getattr(state, "requirement", None),
            "design_spec": getattr(state, "design_spec", None),
            "tiling_strategy": getattr(state, "tiling_strategy", None),
        }

    # ── validation ─────────────────────────────────────────────────────

    def validate_inputs(self, state: "State") -> list[str]:
        errors = []
        if state.requirement is None:
            errors.append(
                "ascendc-st-design requires 'requirement'")
        if not getattr(state, "design_spec", None):
            errors.append(
                "ascendc-st-design requires 'design_spec' (design product missing)")
        return errors

    # ── actions ────────────────────────────────────────────────────────

    @classmethod
    def _has_external_cases(cls, state) -> bool:
        """True when the user supplied an external cases CSV (state.cases_path).

        13 E1: cases source is an explicit CLI path (--cann-bench-cases), not a
        profile-declared template. No ``{N}``/``{op}`` probing — the path is
        absolute. Empty/None → the LLM test-design chain runs alone."""
        return bool(getattr(state, "cases_path", None))

    def _extra_prompt_sections(self, state) -> list[str]:
        """Incremental-fusion hint: the agent must SUPPLEMENT, not replace.

        Without this the agent has no way to know external cases exist (they are
        loaded by the framework outside its working dir), so it would design
        from scratch and duplicate coverage.
        """
        if not self._has_external_cases(state):
            return []
        return [
            "## 已有外部验收用例（增量补充模式）\n"
            f"用户已提供外部 cann-bench 用例（路径 `{state.cases_path}`），它们是"
            "benchmark 权威主源。本 stage 的产出作为**补充**：请聚焦外部用例未覆盖的"
            "形状/dtype/属性组合与边界，避免重复；最终框架会把外部用例与本轮生成的"
            "合并用例融合为统一验收集（外部为主，生成为补充）。"
        ]

    def actions(self, state, iteration: int = 1):
        # 增量融合（P34）：外部 cases 与 LLM 设计不再互斥。有 workspace 就在
        # CWD 跑输入适配器 + spawn agent，其产物在 transition 里作为外部 cases
        # 的补充被融合；无 workspace 则无法跑 LLM（无 CWD 落产物），外部 cases
        # 仍由 transition 确定性加载。
        wd = self._working_dir(state)
        if wd is None:
            if self._has_external_cases(state):
                return [NoOp(
                    reason=("no workspace — external cases_path loaded "
                            "deterministically; LLM supplement skipped"),
                    contract_satisfied=True)]
            return super().actions(state, iteration)

        wd_path = Path(wd)
        wd_path.mkdir(parents=True, exist_ok=True)
        # 物化上游输入（requirement.json / design_spec.json）到 wd，供转换
        # 读取（super().actions() 里的 _materialize_inputs 在本方法 return 之后才
        # 执行——若在此先跑转换，首轮迭代 wd 里没有输入文件，必 FileNotFoundError）。
        self._materialize_inputs(state, wd_path)
        # 输入适配器：requirement.json + design_spec.json → 03_参数定义.yaml
        # （DevKit 产物 → skill 参数定义的 anti-corruption，归框架 adapter 层，
        # 不在 skill 内——skill 单独取出无这两个文件）。直接 import 调用，不依赖
        # 仓库根路径推算（M1）。
        from ascendc_devkit.adapters.testdesign.convert_to_param_def import (
            convert as _convert_param_def,
        )
        # 反馈逐条累积、末尾一次写入（§1.2 可诊断）：适配器失败与 E-1 对质
        # 违规可同时触发，with_updates(user_feedback=…) 是整体替换——各自
        # 就地写入会让后一条静默覆盖前一条（适配器失败事实丢失）。
        feedback: list[str] = []
        try:
            _convert_param_def(
                "requirement.json", "design_spec.json",
                "design/03_参数定义.yaml", base_dir=wd_path)
        except Exception as exc:  # noqa: BLE001 — 任一失败都给 agent 可观测信号
            # §1.2 可诊断：适配器失败留下可观测信号，且把失败事实写进 prompt
            # （user_feedback），让 agent 知道 03_参数定义.yaml 可能未生成——不要
            # 静默假装 step 1-2 已由适配器完成。
            _log.error("[%s] convert_to_param_def failed: %s", self.name, exc)
            feedback.append(
                "convert_to_param_def.py 执行失败，03_参数定义.yaml 可能未生成："
                f"{str(exc)[:400]}。请按 ascendc-st-design skill 的 step 1-2 从"
                "requirement.json + design_spec.json 手动补齐参数定义后继续。")

        # ── E-1：03 对质（适配器产物 vs 上游 JSON）──
        # agent 改过的路径由 E-3（transition 复验）覆盖；两处共用
        # verify_from_dir（§1.15 单点）。违规走 user_feedback（agent 可消费、
        # 就地修对应条目），不 raise——不静默、也不直接 fail stage。
        # 适配器 raise 时 03 未落盘，此处的校验对象是 agent 上一轮的版本。
        from ascendc_devkit.adapters.testdesign.verify_param_def import (
            verify_from_dir as _verify_pd,
        )
        _pd_path = wd_path / "design" / "03_参数定义.yaml"
        if _pd_path.exists():
            _violations = _verify_pd(wd_path)
            if _violations:
                _log.error("[%s] 03 对质校验失败: %s",
                           self.name, "; ".join(_violations))
                feedback.append(
                    "03_参数定义.yaml 与上游 JSON 不一致："
                    + "; ".join(_violations[:5])
                    + "。请按 ascendc-st-design skill 的 step 1-2 依据 "
                    "requirement.json + design_spec.json 修复对应条目"
                    "（不要整文件重建）。")

        if feedback:
            state = state.with_updates(user_feedback="\n".join(feedback))

        return super().actions(state, iteration)

    # ── transition ─────────────────────────────────────────────────────

    def transition(self, state: "State", result: dict) -> "State":
        # ── E-3：03 对质复验硬门（1903 step-127；agent 执行中可能就地改过 03）──
        # 先查病因（03 与上游 JSON 不一致）再查症状（CSV 缺失），报错带病因。
        # 只在 agent 实际跑过（有 workspace 且 03 已落盘）时校验——无 workspace 的
        # 纯外部 cases 路径不涉及 03。与增量融合正交：03 完整性是前置条件，
        # 无论是否融合外部 cases，损坏即响亮失败（防适配器静默丢参复现，§1.2）。
        wd = self._working_dir(state)
        if wd is not None and Path(wd).is_dir():
            from ascendc_devkit.adapters.testdesign.verify_param_def import (
                verify_from_dir as _verify_pd,
            )
            _pd_path = Path(wd) / "design" / "03_参数定义.yaml"
            if _pd_path.exists():
                _violations = _verify_pd(Path(wd))
                if _violations:
                    return self._error(
                        state,
                        "03_参数定义.yaml 与上游 JSON 不一致（对质复验）: "
                        + "; ".join(_violations[:5])
                        + "。请依据 requirement.json + design_spec.json 修复 03"
                          "对应条目（不要整文件重建）。",
                        error_type="schema_violation")

        # 增量融合（P34）：外部 cases 为主源、LLM 产物为补充；二者都尝试加载，
        # 合并成统一验收集（外部在前）。单一来源为空不报错——只有合并仍空才失败。
        external, ext_err, ext_etype = self._load_external_cases(state)
        generated, report_path, gen_err, gen_etype = (
            self._parse_generated_cases(state, result))
        merged = external + generated
        if not merged:
            return self._error(
                state,
                ext_err or gen_err or "ascendc-st-design produced no test cases",
                error_type=ext_etype or gen_etype or "missing_artifact")

        # cases_source：外部 cann-bench cases 是 benchmark 权威主源 → 保持
        # cann-bench 标准对齐（融合集用同一比较标准）；仅 LLM 产物 → devkit。
        source = "cannbench" if external else "devkit"
        feedback = ""
        if external and not generated:
            # 外部 cases 已满足契约，LLM 补充未产出不阻断；留可观测信号（§1.2）。
            feedback = (
                f"外部 cann-bench cases 已加载 {len(external)} 条；LLM 补充用例未产出"
                f"（{gen_err or 'empty'}），本 stage 以外部 cases 交付。")
        return state.with_updates(
            test_cases=merged, test_design_report=report_path,
            cases_source=source, last_error=None, user_feedback=feedback)

    # ── resolve condition ──────────────────────────────────────────────

    def resolve_condition(self, state: "State") -> str:
        if state.test_cases:
            return "default"
        if state.last_error is None:
            return "default"
        iters = state.stage_iterations.get(self.name, 0)
        if iters >= self.effective_max_iterations():
            return "exhausted"
        return "default"

    # ── case-source loaders ────────────────────────────────────────────

    def _load_external_cases(self, state: "State") -> "tuple[list, str, str]":
        """External cann-bench cases → ``(cases, error_msg, error_type)``.

        No ``cases_path`` → ``([], "", "")`` (not an error — the LLM path may
        still produce cases). Load failure / zero rows → empty list + a message,
        which the caller uses only when the merged set is also empty (external
        cases are a best-effort primary: ones that DID load are kept).
        """
        if not self._has_external_cases(state):
            return [], "", ""
        from ascendc_devkit.domain.cann_bench_cases_loader import (
            load_cann_bench_cases,
        )
        try:
            cases = load_cann_bench_cases(state.cases_path)
        except Exception as exc:
            return [], f"external cases_path load failed: {exc}", "schema_violation"
        if not cases:
            return [], "external cases_path produced 0 cases", "missing_artifact"
        return cases, "", ""

    def _parse_generated_cases(
            self, state: "State", result: dict) -> "tuple[list, object, str, str]":
        """LLM product → ``(cases, report_path, error_msg, error_type)``.

        Locates the merged 13-column CSV + report in the working dir and
        normalizes the CSV via the testdesign adapter. No agent result (e.g. the
        no-workspace NoOp path) → empty list so the caller can fall back to the
        external cases that did load.
        """
        agent_result = result.get("agent_result")
        if agent_result is None:
            return ([], None, "ascendc-st-design: agent produced no result",
                    "missing_artifact")
        wd = self._working_dir(state)
        if wd is None or not Path(wd).is_dir():
            return ([], None, f"ascendc-st-design working dir missing: {wd}",
                    "missing_artifact")

        wd_path = Path(wd)
        # Locate the merged 13-column CSV (from agent prompt)
        csv_path = self._locate_csv(wd_path)
        if csv_path is None:
            return ([], None, f"no merged test-case CSV found under {wd}",
                    "missing_artifact")

        from ascendc_devkit.adapters.testdesign import parse_testcase_csv
        # Pass op_spec so the adapter regroups flat per-tensor shapes into one
        # entry per logical parameter — a DYNAMIC (Tensor[]) input takes nested
        # list[list[int]] (§1.10/§1.12). Without it the flat mapping explodes a
        # TensorList into N top-level inputs and the harness DYNAMIC check fails.
        op_spec = getattr(state.requirement, "op_spec", None)
        try:
            cases = parse_testcase_csv(csv_path, operator=op_spec)
        except ValueError as exc:
            return ([], None, f"CSV→TestCase normalization failed: {exc}",
                    "schema_violation")
        if not cases:
            return ([], None, f"test-case CSV {csv_path.name} produced 0 cases",
                    "missing_artifact")
        return cases, self._locate_report(wd_path), "", ""

    # ── CSV / report locators ──────────────────────────────────────────

    @staticmethod
    def _locate_csv(working_dir: Path) -> "Path | None":
        """定位合并后的 13 列 CSV（stage prompt 约定写到 wd 根，如
        ``合并_测试用例.csv``）。按确定性优先级选择，不依赖 mtime 猜测
        （M5：多轮迭代残留多个合并 CSV 时，旧实现靠 mtime 排序可能选中陈旧
        产物；且 rglob 会扫进 design/、testcases/ 中间产物干扰选择）：
          1. 精确文件名 ``合并_测试用例.csv``；
          2. 名字含「合并」；
          3. 名字含「测试用例」；
          4. 任意 .csv（最后兜底）。
        只扫描 wd 根目录——合并 CSV 是 agent 写到 CWD 的最终产物，不在子目录。
        """
        root = working_dir
        try:
            csvs = sorted(p for p in root.iterdir() if p.suffix.lower() == ".csv")
        except OSError:
            return None
        if not csvs:
            return None
        for p in csvs:
            if p.name == "合并_测试用例.csv":
                return p
        for p in csvs:
            if "合并" in p.name:
                return p
        for p in csvs:
            if "测试用例" in p.name:
                return p
        return csvs[0]

    @staticmethod
    def _locate_report(working_dir: Path) -> "Path | None":
        """定位测试设计方案报告 md（stage prompt 约定写到 wd 根，如
        ``测试设计方案.md``）。与 _locate_csv 同规则：确定性优先级 + 仅 wd 根。
        """
        root = working_dir
        try:
            mds = sorted(p for p in root.iterdir() if p.suffix.lower() == ".md")
        except OSError:
            return None
        for p in mds:
            if p.name == "测试设计方案.md":
                return p
        for p in mds:
            if "设计方案" in p.name or "测试设计" in p.name:
                return p
        return mds[0] if mds else None
