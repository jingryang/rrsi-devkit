"""prompt 组装 mixin — CodegenStage 的 prompt 组装职责承载（m1 God module 治理后归属本模块）。

承载 actions / _actions_membase / _materialize_inputs / _programming_model_for /
_build_codegen_prompt（membase 主路径 prompt 组装）。
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from ascendc_devkit.domain.chip import chip_programming_model, to_soc_version
from ascendc_devkit.capabilities.agent._shared import is_infra_error_type
from ascendc_devkit.orchestration.skill_config import STAGE_SKILL_MAP
from ascendc_devkit.orchestration.kernel.action import SpawnAgent, Action

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State


class PromptMixin:
    """prompt 组装 mixin（职责见模块 docstring，经 MRO 合并回 CodegenStage）。"""

    def actions(self, state: State, iteration: int = 1) -> list[Action]:
        # 1. Circuit breaker (existing, unchanged)
        from ascendc_devkit.orchestration.runtime_config import retry_budgets
        if state.codegen_consecutive_failures >= retry_budgets()["consecutive_failures_max"]:
            from ascendc_devkit.infra.logger import Logger
            Logger.error(
                f"codegen circuit breaker tripped: "
                f"{state.codegen_consecutive_failures} consecutive agent "
                f"failures. Stopping. Check the agent transcript under "
                f"<run>/agents/ for the underlying cause."
            )
            return []

        # 2. Infra halt (existing, unchanged)
        if state.last_error and is_infra_error_type(state.last_error.error_type):
            from ascendc_devkit.infra.logger import Logger
            Logger.error(
                f"codegen halting on infrastructure error (not a logic "
                f"failure — breaker untouched): {state.last_error.message}. "
                f"Fix the environment/config and resume."
            )
            return []

        # 3. Determine programming model + agent_name (needed early for session resume)
        model = chip_programming_model(state.design_target_chip or "")
        if state.mode == "new":
            agent_name = "ascendc-coder-regbase" if model == "Regbase" else "ascendc-coder"
        else:
            agent_name = "incremental-developer"
        ws = getattr(state, "_workspace", None)
        working_dir = state.op_dir or (state.op_identity.op_dir
                                       if state.op_identity else None)

        # 4. Materialize design inputs to staging (shared — before routing)
        # （session resume 统一走 backend 层 sdk_backend 的 sidecar 决策，含
        #  resume_fails 累计 + degrade；stage 层不再读 sidecar，§2.5 唯一通路）
        staging_dir = None
        if ws is not None:
            staging_dir = ws.artifacts / "staging"
            staging_dir.mkdir(parents=True, exist_ok=True)
            self._materialize_inputs(state, staging_dir)
            # §1.2/§2.9 domain-gap 安全网（非 halt）：requirement(golden) 域 ⊆ design.support_domain
            # 缺口 → WARN + 结构化信号落盘，按 no-halt 哲学继续（debug/eval 兜底）。
            self._emit_domain_gap_signal(state, staging_dir)

        # 5. Route by programming model
        if model == "Regbase" and state.mode == "new":
            return self._actions_regbase(state, iteration)

        # 6. Membase — existing logic extracted to helper
        return self._actions_membase(state, iteration, staging_dir, agent_name,
                                     working_dir)
    def _actions_membase(self, state: State, iteration: int,
                         staging_dir: Path | None, agent_name: str,
                         working_dir: Path | None) -> list[Action]:
        """Membase 路径：沿用原单 agent 模式（ascendc-coder / incremental-developer）。"""
        # D2 (§4.3): skill 投递经 SpawnAgent.primary_skill 结构化携带、由 backend 边界
        # render_skill_injection 原生渲染（claude 展 /<skill>、opencode first-call），
        # stage 层不再前置 slash。与 design_substages + 全仓 D2 迁移一致（was
        # _with_trigger，codegen 是唯一残留，regbase 特性未跟上）。
        prompt = self._build_codegen_prompt(state, iteration, staging_dir)

        # step-103：context 死键全删（§2.5）——backend 对 SpawnAgent.context 零
        # 消费（签名传递后丢弃），历史注入的 mode/existing_code/last_error/
        # build_feedback/artifact_feedback/previous_sources 全是死通道：前四者
        # prompt builder 已有等价段、feedback 投递在 prompt 反馈段与 resume
        # 消息（§1.15 单点渲染）。信息进 agent 的唯一通路是 prompt。

        # step-100：反馈重派轮 resume 原 coder 会话（§1.15 统一抽象——build/
        # artifact/schema 反馈同属「会话内可修的产物不合格」）。原会话已有完整
        # 任务书与决策上下文，resume_prompt = resume 首句 + 与 fresh prompt
        # 同源的 kind 专属反馈段（§1.14 不重发全量 prompt；§1.15 两条投递路径
        # 同一渲染）。无上轮 session → fresh spawn 兜底。
        feedback = (state.codegen_build_feedback
                    or state.codegen_artifact_feedback)
        resume_sid = None
        resume_prompt = None
        if (feedback and state.last_agent_session_id
                and state.last_agent_stage == "codegen"):
            # M13（review 整改）：锚点归属校验（镜像设计子阶段的 stage_name
            # 守卫）——锚点是 runner 对所有 stage 统一捕获的单点字段，smoke/
            # perf 等 stage 的 spawn 会覆盖它；无归属校验时 stale 反馈 + 他
            # stage spawn 过的组合会 resume 外来会话注入错位修复提示。
            resume_sid = state.last_agent_session_id
            resume_prompt = self._render_retry_resume_prompt(state)

        return [
            SpawnAgent(
                agent_name=agent_name,
                prompt=prompt,
                primary_skill=STAGE_SKILL_MAP.get(self.name),
                working_dir=working_dir,
                repo_baseline=state.target_repo_baseline_ref or None,
                repo_root=state.op_identity.repo_root if state.op_identity else None,
                resume_session_id=resume_sid,
                resume_prompt=resume_prompt,
            )
        ]
    def _materialize_inputs(self, state: State, staging_dir: Path) -> None:
        """Write upstream design products + reference code as staging files (P4).

        Design JSONs and reference code are materialized into the run's staging
        directory (under artifacts/), NOT into the operator repository.  This
        keeps intermediate engineering artifacts out of the op_dir and avoids
        polluting the operator codebase with decision_log.json / design_spec.json
        / etc.

        The agent reads these inputs from staging via absolute paths (injected
        in the prompt) and writes code outputs to cwd (= op_dir).
        """
        from pathlib import Path
        wd = Path(staging_dir) if not isinstance(staging_dir, Path) else staging_dir
        wd.mkdir(parents=True, exist_ok=True)
        # Design contract + upstream source intermediates. The three-piece
        # contract (design_spec/tiling_strategy/kernel_architecture) is the
        # compact blueprint; the source intermediates below carry the
        # implementation detail that used to be missing — Kernel pseudocode /
        # Buffer / split / requirement / acceptance cases — driving the agent
        # to read source instead of grepping CANN
        # (docs/plan/codegen-skill-upstream-reuse). Best-effort: empty fields
        # are skipped (mirrors design_substages._materialize_inputs).
        for field, fn in [
            ("design_spec", "design_spec.json"),
            ("tiling_strategy", "tiling_strategy.json"),
            ("kernel_architecture", "kernel_architecture.json"),
            ("tiling_results", "tiling_results.json"),
            ("general_design", "general_design.json"),
            ("template_division", "template_division.json"),
            ("test_cases", "test_cases.json"),
            # P83 (step-58): escape-hatch known issues
            ("design_known_issues", "known_issues.json"),
        ]:
            payload = getattr(state, field, None)
            if payload is None or payload == {} or payload == []:
                continue
            (wd / fn).write_text(_json_text(payload), encoding="utf-8")
        # step-113 (P11-B1)：tiling_results per-template 切片视图——机械拆分
        # （切分键=顶层 dict 键，零内容理解，§1.12），供 coder 按当前实现模板
        # 读对应切片（71-212KB 单体 → 29-58KB/切片；compaction 冲刷后重读的
        # 回灌量随之缩减）。**单体照写并存**：读通路唯一由 spawn prompt 指针
        # 保证（指切片），单体退为全貌/取证/老批 RESUME 兼容形态。模板名
        # sanitize 后唯一性断言：碰撞/空名 → 跳过切片 + WARN（单体仍是读
        # 单元），确定性回退不 fail。
        _tr = getattr(state, "tiling_results", None)
        if isinstance(_tr, dict) and _tr:
            _names = {}
            for _key in _tr:
                if not isinstance(_key, str):
                    _names = None
                    break
                _safe = re.sub(r"[^A-Za-z0-9._-]+", "_", _key).strip("._-")
                if not _safe or _safe in _names.values():
                    _names = None
                    break
                _names[_key] = _safe
            if _names is None:
                from ascendc_devkit.infra.logger import Logger
                Logger.warn(
                    "codegen: tiling_results 模板名切片冲突/非法（sanitize 后"
                    "碰撞或非字符串键），跳过切片——单体 tiling_results.json "
                    "仍是读单元")
                # M7（review 整改）：碰撞回退的确定性——残留的旧切片目录一并
                # 移除，prompt 指针的 is_dir() 门才能落到单体（此前残留目录
                # 会击穿「切片目录不在 → 指单体」的回退）。
                _stale = wd / "tiling_results"
                if _stale.is_dir():
                    shutil.rmtree(_stale, ignore_errors=True)
            else:
                _slices = wd / "tiling_results"
                # M7（review 整改）：写前整体重建而非增量覆写——重入
                # （loopback/RESUME）后模板集缩减/改名时，陈旧 <T>.json 不得
                # 残留（prompt 会引导 coder 读旧蓝图 + 跨模板核对读陈旧切片）。
                if _slices.is_dir():
                    shutil.rmtree(_slices, ignore_errors=True)
                _slices.mkdir(parents=True, exist_ok=True)
                for _key, _safe in _names.items():
                    (_slices / f"{_safe}.json").write_text(
                        _json_text({_key: _tr[_key]}), encoding="utf-8")
        # requirement.json — the codegen SKILL declares it the "需求权威源"
        # (IO/公式/约束) and reads mutation_mode/math_formula/shape_formula from
        # it (SKILL §维5 in-place plugin contract). Those fields are NOT modeled
        # by the reduced ``Requirement`` dataclass, so ``asdict(state.requirement)``
        # would deliver a spec that contradicts the SKILL's promise (the exact
        # lossy path the review gate's M2 fix rejected). Reach back to the full
        # on-disk requirement.json via the shared helper (§2.5 single pathway).
        # §3.12: 权威不可达（无 workspace / 产物缺失）→ 告警 + 不落 reduced——
        # 不拿有损数据冒充权威输入，skill 因缺 requirement.json 显式暴露。
        from ascendc_devkit.orchestration.design_artifacts import (
            materialize_authoritative_requirement,
        )
        # 仅当 State 确实持有 requirement（reduced）但权威文件不可达时才告警——
        # requirement 非本 stage 必输（intake 直供详设等路径本就没有 requirement），
        # 无 requirement 时「权威不可达」不是缺陷，不制造噪音。
        if (state.requirement is not None
                and not materialize_authoritative_requirement(
                    state, wd / "requirement.json")):
            from ascendc_devkit.infra.logger import Logger
            Logger.warn(
                "codegen: requirement 权威文件不可达（无 workspace / "
                "artifacts/requirement/requirement.json 缺失），不物化 reduced "
                "需求——skill 将因缺少 requirement.json 暴露（§3.12）")
        # Reference code: one file per source, name-preserving
        if state.reference_code:
            for path, content in state.reference_code.items():
                (wd / f"ref_{Path(path).name}").write_text(content, encoding="utf-8")
        # meta.json: codegen skill contract (ascendc-op-dev-coding SKILL.md).
        # Dual source (P65): programming_model drives the coding path (Step4:
        # A5 Regbase → path 3 VF+RegTensor; A2/A3 Membase → path 2 traditional
        # AscendC) and comes from the DESIGN chip (it fixes code STYLE); chip_code
        # + soc_version are the COMPILE target and come from the RUNTIME chip
        # (the on-box hardware) — falling back to design when runtime is unset.
        # This decouples "what code style to emit" from "what to compile for",
        # so an A5 box can validate A2/A3 Membase codegen (forward-compatible):
        # programming_model = "A2 Membase", but chip_code/soc_version = A5/ascend950.
        # Without meta.json the skill status=fail (P4: no stage produced meta.json
        # → the skill's contract never executed → it was never delivered).
        design_chip = state.design_target_chip or ""
        runtime_chip = state.runtime_target_chip or ""
        compile_chip = runtime_chip or design_chip   # runtime first; design fallback
        # 仅首次写入 meta.json（一次性初始化，非每轮刷新）。
        # Regbase 路径：_regbase_ensure_init 会在此基础上补全 retries/et/kernel_steps
        # 等字段；后续迭代 _materialize_inputs 再跑时不能覆盖，否则 retries 计数器重置、
        # E(t) 归零，双层保护失效。
        meta_path = wd / "meta.json"
        if design_chip and not meta_path.exists():
            meta = {
                "programming_model": self._programming_model_for(design_chip),
                "chip_code": compile_chip,
                "soc_version": to_soc_version(compile_chip),
            }
            meta_path.write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    def _programming_model_for(self, chip: str) -> str:
        """programming_model for the codegen skill, derived from the canonical
        chip generation via the domain single-source ``chip_programming_model``
        (§1.9/§2.5). Drives the coding path per ascendc-op-dev-coding SKILL.md
        Step4: A5 Regbase → path 3 (VF + RegTensor); A2/A3 Membase → path 2
        (traditional AscendC). The skill-contract literal is ``"{chip} {model}"``
        (e.g. ``"A5 Regbase"``, ``"A2 Membase"``); the wrapping lives here, the
        pure-model derivation lives in chip.py (layering — domain stays unaware
        of skill-contract formatting). Empty/unknown chip → ``"Membase"`` (the
        conservative, broadly-applicable path — mirrors the domain fallback).
        """
        gen = (chip or "").strip().upper()
        model = chip_programming_model(gen)
        return f"{gen} {model}" if gen else "Membase"
    def _build_codegen_prompt(self, state: State, iteration: int,
                               staging_dir: Path | None = None) -> str:
        """Assemble the full codegen prompt from ordered section renderers.

        Each ``_render_*_section`` method renders exactly one prompt section
        (design inputs, known issues, failure context, repo rules, …). This
        method is the pure assembler: it decides WHICH sections apply and in
        what order; the renderers decide the content. Sections are joined with
        two blank lines.
        """
        # Cross-stage failure context is the one section that must PREPEND the
        # design inputs (original behavior: the "修正任务" heading lands at
        # position 0); the rest are appended in sequence.
        fail_prepend, fail_append = self._cross_stage_failure_sections(
            state, iteration)
        sections = list(fail_prepend)
        sections.extend(self._design_inputs_section(state, staging_dir))
        sections.extend(self._known_issues_section(state))
        sections.extend(self._domain_gap_section(state, staging_dir))
        sections.extend(self._reference_code_section(state))
        sections.extend(self._reference_roots_section(state))
        sections.extend(self._build_commands_section(state))
        sections.extend(fail_append)
        sections.extend(self._repo_rules_section(state))
        sections.extend(self._user_feedback_section(state))
        prev = self._previous_decision_section(state)
        if prev:
            sections.append(prev)
        sections.append(self._decision_log_output_section())
        sections.extend(self._scaffold_protocol_section(state))
        sections.extend(self._manifest_spec_section(state))
        if state.codegen_build_feedback:
            _ws = getattr(state, "_workspace", None)
            _run_dir = str(_ws.dir) if _ws is not None else "<run_dir>"
            sections.append(self._render_build_feedback_section(
                state.codegen_build_feedback, _run_dir))
        if state.codegen_artifact_feedback:
            sections.append(self._render_artifact_feedback_section(
                state.codegen_artifact_feedback))
        scaffold = self._scaffold_contract_summary(state)
        if scaffold:
            sections.append(scaffold)
        return "\n\n".join(sections)

    # —— prompt section renderers（每段一个方法，_build_codegen_prompt 只装配）——

    def _cross_stage_failure_sections(self, state: State,
                                      iteration: int) -> tuple[list[str], list[str]]:
        """Cross-stage failure context sections.

        Returns ``(prepend, append)``: ``prepend`` is the "修正任务" heading that
        must land before the design inputs (original behavior inserted it at
        position 0); ``append`` is the failure reason / previous-source sections
        that come after the build-commands section. A non-codegen ``last_error``
        (design / requirement escalation) is legitimate feedback for codegen —
        build/precision feedback no longer loops back (B5).
        """
        prepend: list[str] = []
        append: list[str] = []
        failure_msgs: list[str] = []
        if state.last_error and state.last_error.stage_name != "codegen":
            failure_msgs.append(
                f"### 上一阶段 '{state.last_error.stage_name}' 反馈\n"
                f"类型: {state.last_error.error_type}\n"
                f"信息: {state.last_error.message}"
            )
        if failure_msgs:
            prepend.append("## 修正任务（上一次生成存在问题，请修复）")
            append.append("## 失败原因\n" + "\n\n".join(failure_msgs))
            append.append("\n请分析以上失败原因，在上一版本代码的基础上进行修复。")
            if state.generated_sources:
                append.append("## 上一版本代码（请修复）")
                for path, content in state.generated_sources.items():
                    append.append(f"### {path}\n```cpp\n{content[:5000]}\n```")
        elif iteration > 1 and state.last_error:
            append.append(
                f"## 上次失败反馈\n{state.last_error.stage_name}: "
                f"{state.last_error.error_type}\n{state.last_error.message}"
            )
        return prepend, append

    def _design_inputs_section(self, state: State,
                               staging_dir: Path | None) -> list[str]:
        """「设计产物（输入文件）」清单段。

        P4: design inputs are materialized to staging (not op_dir).  Point the
        agent at the staging directory via absolute paths so it can read them.
        P3: host_code files → op_host/, kernel_code files → op_kernel/.
        Returns a one-element list (the section) or ``[]`` when no design inputs
        exist.
        """
        design_files: list[str] = []
        if staging_dir and state.design_spec:
            design_files.append(f"`{staging_dir / 'design_spec.json'}` — 算子定义/接口/张量规格")
        elif state.design_spec:
            design_files.append(" `design_spec.json` — 算子定义/接口/张量规格（当前工作目录）")
        if staging_dir and state.tiling_strategy:
            design_files.append(f"`{staging_dir / 'tiling_strategy.json'}` — 切分策略")
        elif state.tiling_strategy:
            design_files.append(" `tiling_strategy.json` — 切分策略（当前工作目录）")
        if staging_dir and state.kernel_architecture:
            design_files.append(f"`{staging_dir / 'kernel_architecture.json'}` — Kernel 架构（含需要产出的文件列表）")
        elif state.kernel_architecture:
            design_files.append(" `kernel_architecture.json` — Kernel 架构（含需要产出的文件列表）")
        # 上游源中间产物（实现蓝图源头，docs/plan/codegen-skill-upstream-reuse 决策3）：agent 读这些
        # 而非 grep CANN。每项标注「翻译为哪层代码」。
        if staging_dir and state.tiling_results:
            # step-113 (P11-B1)：指针指切片目录（读通路唯一）——按当前实现的
            # 模板读对应 `<T>.json`（29-58KB vs 单体 71-212KB，冲刷后重读回灌
            # 量缩减）；跨模板一致性核对读相邻切片；勿整目录通读。单体
            # tiling_results.json 仍在 staging（全貌视图），不注入路径。
            # 碰撞/非法跳过切片的确定性回退：切片目录不在 → 指单体（与物化
            # 侧 WARN「单体仍是读单元」一致，指针不指向不存在的路径）。
            if (staging_dir / "tiling_results").is_dir():
                design_files.append(f"`{staging_dir / 'tiling_results'}/<模板名>.json` — per-template 切片（**实现蓝图主源** buffer_kernel.kernel.pseudocode）：按当前实现的模板读对应切片；跨模板一致性核对读相邻切片，勿整目录通读")
            else:
                design_files.append(f"`{staging_dir / 'tiling_results.json'}` — **实现蓝图主源** buffer_kernel.kernel.pseudocode（切片因模板名冲突未生成，此为单体全量）")
        if staging_dir and state.general_design:
            design_files.append(f"`{staging_dir / 'general_design.json'}` — 概设（算子分类/sections 骨架/precision 策略）")
        if staging_dir and state.template_division:
            design_files.append(f"`{staging_dir / 'template_division.json'}` — 模板结构 + 全局锁定决策（如 BUFFER_NUM）")
        if staging_dir and state.requirement:
            design_files.append(f"`{staging_dir / 'requirement.json'}` — IO/公式/约束（需求权威源）")
        if staging_dir and state.test_cases:
            design_files.append(f"`{staging_dir / 'test_cases.json'}` — 验收用例（TDD：codegen 须满足）")
        if staging_dir:
            design_files.append(f"`{staging_dir / 'meta.json'}` — 编程模型/芯片代号/soc_version（按 programming_model 选编码路径）")
        if not design_files:
            return []
        return ["## 设计产物（输入文件）\n" + "\n".join(f"- {f}" for f in design_files)]

    def _known_issues_section(self, state: State) -> list[str]:
        """P83 (step-58): escape-hatch known issues — 非阻断，实现时避开/兼容。"""
        if not state.design_known_issues:
            return []
        from ascendc_devkit.orchestration.issue_render import render_issues
        ki_lines = render_issues(state.design_known_issues,
                                 detail_limit=None, max_issues=20)
        return [
            "## 设计已知问题（非阻断，实现时避开/兼容）\n"
            "以下问题在设计校验阶段未消解（设计无客观标准，按逃生路径带至此处）。"
            "它们不阻断 codegen，但实现时请尽量避开/兼容，避免引入相同缺陷：\n"
            + "\n".join(f"- {ln}" for ln in ki_lines)
        ]

    def _domain_gap_section(self, state: State,
                            staging_dir: Path | None) -> list[str]:
        """domain-gap 安全网信号（明确消费）：设计 support_domain 未覆盖
        requirement(golden) 域。信号只写不读是静默洞——注入 coder prompt，让生成
        代码的 agent 覆盖 golden 全域而非按设计的窄 support_domain 缩水实现
        （§1.13 golden 是权威），并在 decision_log 记录缺口。"""
        if not staging_dir:
            return []
        _gap_path = staging_dir / "domain_gap_signal.json"
        _gaps: list = []
        if _gap_path.exists():
            try:
                _gap_data = json.loads(_gap_path.read_text(encoding="utf-8"))
                _gaps = _gap_data.get("gaps") or []
            except (OSError, json.JSONDecodeError):
                _gaps = []
        if not _gaps:
            return []
        return [
            "## 设计 support_domain 域缺口（codegen domain-gap 安全网，非阻断）\n"
            "设计声明的支持域未覆盖 requirement(golden) 域（或不可对质）。golden 是权威真值（§1.13）：\n"
            + "\n".join(f"- {g}" for g in _gaps)
            + "\n生成代码请覆盖 requirement(golden) 域（不要静默按设计的窄 support_domain 缩水实现），"
              "并将该缺口记入 decision_log.json 的 `codegen_domain_gap_note` 字段。"
        ]

    def _reference_code_section(self, state: State) -> list[str]:
        """参考算子代码（方案级，当前工作目录）。"""
        if not state.reference_code:
            return []
        refs = [f"`ref_{Path(p).name}`（来源: {p}）" for p in state.reference_code]
        return ["## 参考算子代码（方案级，当前工作目录）\n" + "\n".join(refs)]

    def _reference_roots_section(self, state: State) -> list[str]:
        """脚手架参考（仓约定唯一来源，只读）——E0/机制⓪：显式声明的干净样例算子
        目录，参考其仓约定/脚手架（CMakeLists 注册、目录布局、build/胶水结构），
        不是算法（算法读设计产物）。Q10 修复：通道曾被填充但 codegen 从未消费。"""
        if not state.reference_roots:
            return []
        root_lines = [f"`{r}`" for r in state.reference_roots]
        return [
            "## 脚手架参考（仓约定唯一来源，只读）\n"
            "以下是上游显式声明的**干净样例算子目录**，参考其**仓约定/脚手架**"
            "（CMakeLists 注册、目录布局、build/胶水结构、注册宏写法），"
            "**不是**算法/实现蓝图（算法读设计产物）：\n"
            + "\n".join(f"- {ln}" for ln in root_lines)
            + "\n**只参考这些声明的根**；禁自行浏览目标仓其它兄弟算子目录"
            "（未声明的兄弟可能带毒，照抄产生虚假通过信号）。"
        ]

    def _build_commands_section(self, state: State) -> list[str]:
        """目标仓约定（构建归属，方案 2）：编译/部署/冒烟由框架自动执行，
        coder 不自行构建。"""
        if not state.profile:
            return []
        build_cmds: list[str] = []
        if hasattr(state.profile, "build_commands"):
            build_cmds = state.profile.build_commands(
                state.rel_op_dir, state.full_op_name or "", state.design_target_chip)
        elif isinstance(state.profile, dict):
            # dict profile fallback (legacy snapshots)
            bc = state.profile.get("build", {}).get("command_template", "")
            build_cmds = [bc] if bc else []
        if not build_cmds:
            return []
        return [
            "## 目标仓约定（构建归属，方案 2）\n"
            "整仓编译/部署/冒烟由**框架在 codegen 之后自动执行**——编译未通过时，错误会"
            "注入本会话由你修复。"
            "**不要在会话内自行执行整仓构建**（bash build.sh / cmake --build / install / "
            "smoke / pip）——会污染共享环境且与框架验证重复。\n"
            "参考编译命令（框架用，仅供了解，勿手动执行）:\n"
            + "\n".join(f"  {c}" for c in build_cmds)
            + "\n\n读写/knowledge 搜索/核对改动用标准工具（Read/Grep/Glob/ls/cat/…）；"
            "kernel 阶段错误（runtime/数据/同步）记 decision_log known_issues 交棒。"
            "（本会话尚未编译——若编译后框架注入 API 签名错误，反馈会指引你如何验证签名。）"
        ]

    def _repo_rules_section(self, state: State) -> list[str]:
        """工作目录与改动上报 + 文件放置规则 + 需要产出的 section 清单。"""
        mode_hint = (
            "new 模式：在 op_dir 内新增/补齐算子源文件（用 Bash 或 Edit 工具）。"
            if state.mode == "new" else
            "incremental 模式：用 Edit 工具修改 op_dir 内已存在的源文件，"
            "必要时 Write 新增文件。"
        )
        repo_rules = (
            "\n## 工作目录与改动上报（方案 A，务必遵守）\n"
            "- 当前工作目录就是算子仓内的算子目录（op_dir），你的代码改动直接落在仓里。\n"
            + (f"- **op_dir 的完整绝对路径为：`{state.op_dir}`**——先用 `pwd` 验证你所在目录"
               f"等于此路径，再写文件；禁止拼写绝对路径（绝对路径极易拼错），用相对路径。\n"
               if state.op_dir else "")
            + f"- {mode_hint}\n"
            "- 只动本算子相关的文件，不要触碰 op_dir 之外或与本算子无关的文件。\n"
            "- 构建中间物（*.o / *.so / build/ 等）不算改动，不要写入、不要上报。\n"
            "\n## 文件放置规则（关键）\n"
            "- **host_code** 文件（tiling.h/.cpp, infershape.cpp, def.cpp 等）→ 放到 `op_host/` 子目录\n"
            "- **kernel_code** 文件（kernel.h/.cpp, tiling_data.h, tiling_key.h 等）→ 放到 `op_kernel/` 子目录\n"
            "- **api_code** 文件（ACLNN L0/L2 API 的 .h/.cpp）→ 放到 `op_api/` 子目录（若 kernel_architecture 声明）\n"
            "- **plugin_code** 文件（torch plugin 注册的 .cpp）→ 放到 `op_plugin/` 子目录（若 kernel_architecture 声明）\n"
            "- 这些子目录已存在，参考已有文件的放置方式\n"
            "\n## CMakeLists.txt（非核心，自行参考目标仓）\n"
            "- 参考目标仓内现有算子的 CMakeLists.txt 模式生成\n"
            "- 非核心产物的硬性检查项，但建议生成以确保编译通过\n"
            "\n## 算子导出/发现（best-effort，非阻塞）\n"
            "- CannbenchAdaptStage 在 deploy 和 eval 之间运行，是算子导出的权威适配步骤\n"
            "- codegen 的导出检查降为 best-effort：尽力而为，失败不阻塞 pipeline\n"
            "- 参考目标仓内现有算子的导出/注册模式，确保新算子可被下游工具发现\n"
            "- 不同目标仓机制不同（auto-discover / registry / `__init__.py` wrapper / 无需求）\n"
            "- 从参考实现学习目标仓的导出惯例，禁止写死某仓特定路径（如 `cann_bench/__init__.py`）\n"
            "\n## 中间产物（设计 JSON / 上报记录）\n"
            "- 设计输入文件（design_spec.json 等）在 staging 目录，只读不写。\n"
            "- **不要**把设计 JSON、decision_log.json 等中间产物写入 op_dir（与决策/调试记录分开）。\n"
            "- 改动文件清单由框架从 git diff 机械派生（无需自报）；完成后用 Bash 输出\n"
            "  `git diff --name-only -- op_host/ op_kernel/ op_api/ op_plugin/` 自验改动文件。\n"
        )
        expected_dirs = self._expected_code_files(state)
        if expected_dirs:
            dir_lines = "\n".join(f"- {d}/（具体文件名参考目标仓现有算子确定）" for d in expected_dirs)
            return [
                repo_rules
                + "\n\n根据 kernel_architecture，需要产出以下 section：\n"
                + f"{dir_lines}"
                + "\n\n每个 section 的具体文件名不在契约中约束——参考目标仓内现有算子"
                + "（调用方注入的参考实现路径）的文件命名和目录布局，自行确定。"
                + "\ncodegen 产出判据：每个 section 目录存在且至少包含一个非空源文件。"
            ]
        return [
            repo_rules
            + "\n\n需要产出所有必需的源文件（kernel.h/.cpp, tiling.h/.cpp 等）。"
        ]

    def _user_feedback_section(self, state: State) -> list[str]:
        """Inject user feedback (from interactive loop-back)."""
        if not state.user_feedback:
            return []
        return [
            f"## 用户反馈\n以下是用户针对上一版本代码的反馈意见：\n\n"
            f"{state.user_feedback}"
        ]

    def _scaffold_protocol_section(self, state: State) -> list[str]:
        """仓库调用协议（强制契约）——invocation kind 由 repo profile 选择，
        非 agent 选择（单权威，kind 不漂移）。"""
        scaffold_kind = state.profile.scaffolding_kind() if state.profile is not None else ""
        return [
            "## 仓库调用协议（强制契约）\n"
            f"profile.scaffolding.selected = `{scaffold_kind or '(未解析)'}`。\n"
            "该值优先于 Markdown 详设和 kernel_architecture 的交付裁剪。"
            "若为 `torch_op`，必须生成 `op_plugin/*.cpp`，且同一注册源中包含 "
            "`TORCH_LIBRARY_FRAGMENT(namespace, m)` 与可解析的 `m.def(\"op(...)\")`；"
            "不得因详设写“PTA/op_plugin 不交付”而省略。"
        ]

    def _manifest_spec_section(self, state: State) -> list[str]:
        """算子签名清单（codegen_manifest.json）——codegen 实际采纳的签名。"""
        return [
            "## 算子签名清单（codegen_manifest.json）\n"
            "产出 `codegen_manifest.json` 到当前工作目录，记录 codegen **实际采纳**的算子签名。\n"
            "注意：这是 codegen 确认后的最终签名，不是从 design_spec 拷贝。\n"
            "如果在编码过程中移除了不支持的 dtype、调整了参数默认值，必须在 manifest 中反映。\n"
            "**必须**包含 `callable_target` 字段（`{kind, symbol}`）：声明算子部署后的调用符号。\n"
            "  - `kind`：`torch_op`（经 `TORCH_LIBRARY_FRAGMENT` 注册，调 `torch.ops.<ns>.<op>`）或 `aclnn`。\n"
            "  - `symbol`：确切可调符号；`torch_op` 时为 `torch.ops.<namespace>.<op_name>`，其中 "
            "`<namespace>` 必须与你在 plugin_code 写的 `TORCH_LIBRARY_FRAGMENT(<namespace>, ...)` 一致。\n"
            "  - namespace/op 按目标仓参考算子的注册约定现场确定（与 dtype/CMakeLists 同机制）。\n"
            "schema 见 `schema/codegen_manifest.json`。"
        ]



def _json_text(payload) -> str:
    """Serialize a State field to pretty JSON for staging.

    Handles plain dicts (design_spec/tiling_strategy/kernel_architecture/
    tiling_results/general_design/template_division), dataclass instances
    (Requirement), and lists of dataclasses (test_cases) via a default hook
    that asdict-converts dataclasses and falls back to str for anything else
    (e.g. Path). Mirrors design_substages._materialize_inputs serialization —
    the same idiom, so a dataclass field lands as a real JSON dict, not a
    str() repr that the agent can't read.
    """
    import dataclasses

    def _hook(o):
        if dataclasses.is_dataclass(o) and not isinstance(o, type):
            return dataclasses.asdict(o)
        return str(o)

    return json.dumps(payload, ensure_ascii=False, indent=2, default=_hook)
