"""L3 Orchestration — Design substage implementations (step-2b P4/P3).

Stage classes for the general-design / detailed-design groups. Each substage
follows the mature DesignStage pattern: declare IO + artifact contracts, spawn
its skill agent in actions(), parse the agent's JSON product into a State field
(+ decision_log) in transition(). The quality-gate subsystem (general-design-
review / anchor-consistency / validate) was removed per §1.14 最小结构——producer
stages self-check (§2.9); no cross-stage gates remain.

Not @register_stage'd: instantiated directly by design_tree.py builders. The
former integrate + docgen substages are split into SynthesizeStage (integrate:
design_spec + tiling_strategy) and DocgenStage (详细设计说明书), per
docs/plan/synthesize-docgen-dilution/ (§1.14 最小结构).
"""

from __future__ import annotations

import json
import re
from ascendc_devkit.capabilities.agent._shared import is_infra_error_type
from typing import TYPE_CHECKING

from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.domain.artifact import ArtifactContract
from ascendc_devkit.domain.operator import is_scalar_entry, classify_golden_params
from ascendc_devkit.domain.chip import (
    CHIP_GENERATIONS, chip_display_name, chip_programming_model,
    is_known_generation, runtime_supports_design, to_soc_version)
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.orchestration.design_artifacts import (
    load_authoritative_requirement as _load_authoritative_requirement,
    materialize_authoritative_requirement,
)
from ascendc_devkit.orchestration.kernel.action import (
    AskUserQuestion, Option, SpawnAgent, Action,
)
from ascendc_devkit.orchestration.registry import workflow_requires_npu
from ascendc_devkit.orchestration.skill_config import (
    STAGE_SKILL_MAP, skill_allowlist,
)

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State


def _normalize_stem(name: str) -> str:
    """Fold a filename stem for tolerant matching: lowercase + drop separators
    (underscore / hyphen / dot). ``tiling_buffer_kernel`` ≈ ``TilingBufferKernel``
    ≈ ``tiling-buffer-kernel`` ≈ ``tiling.buffer.kernel`` (P62 name relaxation)."""
    return re.sub(r"[_\-.]+", "", (name or "").lower())


def _locate_artifact(wd, filename: str):
    """Find a stage's product FILE on disk, enforcing the LOCATION invariant
    (P62): the product MUST live under this stage's working_dir. Nothing
    outside working_dir is ever accepted — that is the defect that let
    cross_entropy_loss's T1 buffer-kernel land in the repo root yet sail through
    ``result:ok`` on the agent's returned dict. Name matching is tolerant (the
    filename is not a contract, §2.1 / P6) but location is strict:

      1. exact ``filename`` in wd → take it;
      2. else glob ``*<ext>`` in wd, normalize stems (case/_/-/.): an
         exact-normalized hit ranks 0; a prefix/suffix-tolerant hit ranks 1
         (e.g. ``tiling_buffer_kernel_v2`` suffix, ``my_tiling_buffer_kernel``
         prefix);
      3. ambiguous same-rank hits → None (conservative: re-spawn with feedback
         rather than guess wrong).

    Returns the resolved Path, or None when nothing unambiguous is found in wd.
    """
    from pathlib import Path
    wd = Path(wd)
    exact = wd / filename
    if exact.is_file():
        return exact
    ext = Path(filename).suffix
    target = _normalize_stem(Path(filename).stem)
    if not target:
        return None
    ranked = []  # (rank, path)
    for p in wd.glob(f"*{ext}"):
        if not p.is_file():
            continue
        s = _normalize_stem(p.stem)
        if s == target:
            ranked.append((0, p))
        elif s.startswith(target) or s.endswith(target):
            ranked.append((1, p))
    if not ranked:
        return None
    ranked.sort(key=lambda r: (r[0], len(r[1].stem)))
    best_rank = ranked[0][0]
    best = [r for r in ranked if r[0] == best_rank]
    return best[0][1] if len(best) == 1 else None


# —— 孤儿产物检测/处置（20260821 全局收口）———————————————————————————
# 检测层唯一权威源在 capabilities/agent/_shared.py（_harvest_relocation_evidence*
# / _extract_write_target_shared / _batch_dir_anchor_shared / _normalize_stem）；
# 处置层唯一通路在 orchestration/artifact_recovery.py（recover_orphan_artifact：
# 防御性搬回 + WARN + artifact_relocated 事件）。本模块只消费（下方 import），不再
# 持有本地拷贝——F1/F2 时期与 _shared 并存的双份 "Mirrors" 拷贝已收编（§2.5）。
from ascendc_devkit.capabilities.agent._shared import (  # noqa: E402
    _harvest_relocation_evidence,
    _harvest_relocation_evidence_detailed,
)
from ascendc_devkit.orchestration.artifact_recovery import (  # noqa: E402
    recover_orphan_artifact,
)


class _DesignSubstage(Stage):
    """Shared base: spawn one skill agent, parse one (or more) JSON product(s).

    Subclasses set `agent_name`, `prompt_intro`, and `_schema_files`; the
    base handles the SpawnAgent action, decision-log capture, and the
    missing-artifact error path. Stages writing several products override
    transition().

    Skill identity is read from STAGE_SKILL_MAP (single source of truth in
    orchestration-config.json); artifact schemas are loaded from that skill's
    ``schema/`` directory. Subclasses only declare ``_schema_files`` — no
    skill name duplication in code.
    """

    agent_name: str = ""
    prompt_intro: str = ""
    fail_strategy = "halt"  # 设计阶段默认 halt；gate 子类覆写为 continue

    @property
    def rerun_reset_fields(self) -> list[str]:
        """重跑清空：本 stage 产物字段 + 会话锚点（step-112——重跑 = 新会话，
        镜像 codegen「宁 fresh 勿续旧会话」裁定；旧锚点若残留，反馈重派轮
        会 resume 到上一次运行的会话）。"""
        return list(self.output_contract().provides) + [
            "last_agent_session_id", "last_agent_stage"]
    # ↑ _TestDesignSubstage 继承此类，test-analyze/casedesign/casegen 自动 halt
    # Review fires under this node name (default: the stage's own name). The two
    # group-boundary gates set it to the group name so the default group-boundary
    # review points (general-design / detailed-design) trigger after the gate.
    review_node_name: str = ""

    # M1 (proto-isolation): inject op_dir into the agent prompt? Gate review
    # stages set False — op_dir is the only handle a reviewer could use to glob
    # the cann-bench task tree to proto.yaml/golden.py and redo the proto-vs-
    # golden check that requirement already closed (math_equiv_golden self-check).
    # proto is an external read-only file (never fixed); hiding the path is the
    # constructive guarantee. Generators keep True (legit reference to op source).
    inject_op_dir: bool = True

    # Schema files this stage's skill produces (e.g. ["general_design.json"]).
    # Each file is loaded from the skill's own ``schema/`` directory via
    # SchemaLoader.load_contract_from_skill.  Empty = no spec artifacts.
    _schema_files: list[str] = []

    # First principle (step-10, F2): inputs travel as FILES in the working dir,
    # not as JSON injected into the prompt. This maps each upstream State field a
    # substage consumes (see _upstream_inputs) to the on-disk filename the skill
    # reads it as. Shared across design + test_design; subclasses may extend it.
    _INPUT_FILENAMES: dict = {
        "requirement": "requirement.json",
        "general_design": "general_design.json",
        "template_decision": "template_decision.json",
        "template_division": "template_division.json",
        "tiling_results": "tiling_results.json",
        "tiling_results_current_template": "tiling_current_template.json",
        "design_spec": "design_spec.json",
        "tiling_strategy": "tiling_strategy.json",
        "kernel_architecture": "kernel_architecture.json",
        # P36: design_doc removed from field_map — it is no longer a JSON
        # product (docgen now emits <op>_详细设计说明书.md via its skill, and
        # state.design_doc stores that path). No stage materializes it.
    }

    def _assigned_skill(self) -> str | None:
        """The stage-design skill assigned to this substage (D7 central config).

        None when the substage isn't listed in STAGE_SKILL_MAP — the spawn then
        passes skills=None (inherit default), never [] (suppress all).
        """
        return STAGE_SKILL_MAP.get(self.name)

    def artifact_contract(self) -> ArtifactContract:
        """Load artifact schemas from the assigned skill's ``schema/`` directory.

        Skill identity comes from STAGE_SKILL_MAP (single source of truth in
        orchestration-config.json) — subclasses only declare ``_schema_files``.
        The assigned value is the bare skill name (e.g. ``ascendc-op-general-
        design``); it locates ``.claude/skills/<skill>/schema/<file>``.
        """
        from ascendc_devkit.adapters.schema.loader import SchemaLoader
        assigned = self._assigned_skill()
        if not assigned or not self._schema_files:
            return ArtifactContract(artifacts=[])
        return SchemaLoader.load_contract_from_skill(
            assigned, list(self._schema_files))

    def actions(self, state: "State", iteration: int = 1) -> list[Action]:
        # P93 (step-69) infra 短路（step-27 DEFER 收窄）：上轮 agent 因 infra
        # 错误（网关/配置/鉴权/spawn 超时）未产出 → return [] 终止迭代，不烧
        # budget（这些故障不会自愈，重试无意义）。设计子阶段无 sticky 熔断器，
        # resume 天然重跑（保 step-27 DEFER 内核）；本守卫仅在 run 内"首次 infra
        # 即停"，与 codegen step-27 A-2 同构。
        if (state.last_error is not None
                and state.last_error.stage_name == self.name
                and is_infra_error_type(state.last_error.error_type)):
            return []
        # 孤儿产物不再有提问门（20260821 F3 收口）：locate 失败的 transition 里
        # 已按 transcript 证据就地搬回（recover_orphan_artifact），同轮自愈；拒搬
        # 场景落回 missing-artifact 重试。此处直接进入正常 spawn。
        wd = self._working_dir(state)
        if wd is not None:
            self._materialize_inputs(state, wd)
        prompt = self._build_prompt(state, iteration)
        skill = self._assigned_skill()
        # step-112 (§1.15，补全 codegen step-100 的统一收口)：产物反馈重派轮
        # resume 原会话——被指认的修复（补字段/改形态/落对位置）触及本会话刚
        # 做的工作本体，会话里的推导上下文正是修复所需，全新 spawn 会重付
        # 重载 skill/重读上游/重建意图的冷启动。三条件缺一 → fresh 兜底：
        #   own-stage last_error（门/loopback 错误的 stage_name 非本阶段，
        #   条件自然不命中——语义边界由既有字段承载）+ user_feedback（定向
        #   反馈在位）+ 会话锚点（runner 捕获，见 Runner.run_stage）。
        resume_sid = None
        resume_prompt = None
        if (state.last_error is not None
                and state.last_error.stage_name == self.name
                and state.user_feedback
                # M13（review 整改）：锚点归属——resume 只续「本 stage 自己的
                # 会话」（锚点由 runner 对所有 stage 统一捕获，他 stage spawn
                # 会覆盖；无归属校验会 resume 到外来会话）。
                and getattr(state, "last_agent_stage", "") == self.name
                and getattr(state, "last_agent_session_id", "")):
            resume_sid = state.last_agent_session_id
            resume_prompt = self._render_retry_resume_prompt(state)
        actions: list[Action] = [SpawnAgent(
            agent_name=self.agent_name,
            prompt=prompt,
            context=self._context(state),
            skills=skill_allowlist(skill),
            primary_skill=skill,  # D2: backend delivers /<skill> (was _with_trigger)
            working_dir=wd,
            stage_name=self.name,
            branch_label=self._branch_label(),
            resume_session_id=resume_sid,
            resume_prompt=resume_prompt,
        )]
        return self._maybe_append_review(
            state, self.review_node_name or self.name, actions)

    def _render_retry_resume_prompt(self, state) -> str:
        """反馈重派轮的 resume 消息：resume 首句（同会话继续修复）+ 定向反馈
        全文——与 fresh prompt 的「## 用户反馈」段同一信息源（§1.15 两条投递
        路径同一渲染语义；§1.14 不重发全量任务书，原会话已有）。

        M12（review 整改）：并入**当前** ``last_error.message``——置新错误时
        不清 user_feedback，陈旧反馈可能与新错误并存（轮1 F2 打回 → 轮2 引入
        schema 违规 → 轮3 resume），此前唯一新指令是过期反馈、真实错误文本
        全程不可达 agent。现在每轮 resume 都携带当轮错误，模型两个信号都见。
        """
        parts = [
            "上一轮产物未通过框架校验，请在同一会话继续修复"
            "（勿重做已交付的正确部分，只修正被指认的问题后重新交付）：",
            "",
            state.user_feedback or "",
        ]
        err = getattr(state, "last_error", None)
        err_msg = (getattr(err, "message", "") or "").strip()
        if err_msg and err_msg != (state.user_feedback or ""):
            parts += ["", "## 当前阶段错误（最新一轮校验结果）", err_msg]
        return "\n".join(parts)

    def _materialize_inputs(self, state: "State", working_dir) -> None:
        """Write each declared upstream product from State to a CWD file (F2).

        First principle: the skill reads its inputs from files in the working dir
        exactly as a TUI user would, not from prompt-injected JSON. Idempotent and
        robust for single-step debug (re-materializing from State a file a prior
        substage wrote yields identical content). Only non-empty products are
        written; missing ones are left to validate_inputs. Subclasses with
        user-supplied document inputs override _materialize_extra.
        """
        import dataclasses
        from pathlib import Path
        wd = Path(working_dir)
        wd.mkdir(parents=True, exist_ok=True)
        for field, payload in self._upstream_inputs(state).items():
            if payload is None or payload == {} or payload == []:
                continue
            filename = self._INPUT_FILENAMES.get(field, f"{field}.json")
            # P1/§3.12: agent-facing requirement 一律从磁盘权威文件物化（无损），
            # 不从 State 序列化（reduced dataclass 丢 domain/公式/dtype 域）。
            # 权威不可达 → 告警 + 不落 reduced（§3.12 不拿有损数据冒充权威输入），
            # 由各 stage validate_inputs 加载期拦截（§1.3）。
            if field == "requirement":
                if materialize_authoritative_requirement(state, wd / filename):
                    continue
                from ascendc_devkit.infra.logger import Logger
                Logger.warn(
                    f"[{self.name}] requirement 权威文件不可达（无 workspace / "
                    f"artifacts/requirement/requirement.json 缺失），不物化 reduced "
                    f"需求——agent 输入缺失，应交由 validate_inputs 拦截（§3.12）")
                continue
            if dataclasses.is_dataclass(payload) and not isinstance(payload, type):
                payload = dataclasses.asdict(payload)
            try:
                text = json.dumps(payload, ensure_ascii=False, indent=2,
                                  default=str)
            except (TypeError, ValueError):
                text = json.dumps(str(payload), ensure_ascii=False)
            (wd / filename).write_text(text, encoding="utf-8")
        # P27: auto-materialize the run_context hw_params slice for EVERY design
        # substage — independent of _upstream_inputs, so a stage that forgets to
        # declare it still gets hardware ground truth. This is the mechanical
        # cure for 传递丢失 (the vector that let hardware constants drift into
        # per-skill copies). Skills read hw_params.json via relative path.
        self._materialize_run_context(state, wd)
        self._materialize_extra(state, wd)

    def _materialize_run_context(self, state: "State", working_dir) -> None:
        """Write the hardware ground-truth slice (hw_params.json) from RunContext.

        Single source: the chip spec, loaded once into run_context.hardware_target.
        Empty/absent run_context → write nothing (skills treat hw as unverifiable
        rather than self-supplying a constant).
        """
        rc = getattr(state, "run_context", None)
        if rc is None or not rc.hardware_target or not rc.hardware_target.hw_params:
            return
        from pathlib import Path
        wd = Path(working_dir)
        # Augment with canonical chip identity so design skills (esp. docgen §2.3
        # OpDef AddConfig) have a deterministic file-based chip source. The design
        # JSON contract is chip-agnostic by design, so the chip rides this sanctioned
        # hw_params channel (state.design_target_chip → chip_code + to_soc_version)
        # instead of leaking into design_spec — cures the <SOC_VERSION> placeholder
        # hallucination. Copy first: hw_params is a cached shared object.
        params = dict(rc.hardware_target.hw_params)
        chip = getattr(state, "design_target_chip", "") or ""
        if is_known_generation(chip):
            params["chip_code"] = chip
            params["soc_version"] = to_soc_version(chip)
        text = json.dumps(params, ensure_ascii=False, indent=2)
        (wd / "hw_params.json").write_text(text, encoding="utf-8")

    def _materialize_extra(self, state: "State", working_dir: "Path") -> None:
        """Hook for non-State file inputs (e.g. user-supplied design documents).

        Default: nothing. general-design-generator / dd-intake override to copy the user's
        concept/detailed-design document into the working dir as a file the skill
        reads, instead of injecting its text into the prompt.
        """
        return

    def _branch_label(self) -> str:
        """Fork-join branch label for log/transcript attribution (D8/§P2).

        Empty for non-branch substages; overridden by tiling segments to the
        bound template name so N parallel branches log distinct prefixes.
        """
        return ""

    def _working_dir(self, state: "State"):
        """Materialization path for this substage's products (data-flow (c)).

        Default: artifacts/design/<name>. The tiling fork-join segments override
        this to isolate per-template subdirs so 5 parallel branches don't clobber
        each other's files (P2 product overwrite). Returns None when no workspace.
        """
        if not state._workspace:
            return None
        return state._workspace.artifacts / "design" / self.name

    def _entry_kind_filename(self) -> str | None:
        """The on-disk filename of this stage's OWN product — the existence
        signal for entry_kind (generate vs modify). Derived from the first
        provided field's registered filename. ``TilingStage`` overrides to use
        its first required segment file (its product is a multi-file tiling
        slice, not the group-level ``tiling_results`` the contract advertises)."""
        provides = self.output_contract().provides
        if not provides:
            return None
        return self._INPUT_FILENAMES.get(provides[0], f"{provides[0]}.json")

    def entry_kind(self, state: "State") -> str:
        """P1-a (D2): judge generate-vs-modify by whether this stage's own
        product file already exists in its working dir. A corrective loopback
        re-enters the node at iteration=1 yet the prior product persists on
        disk, so existence — not iteration — is the right signal. Judging by
        ``iteration > 1`` drops the incremental section on a loopback re-entry
        and the agent re-scans from scratch (the P61 stall root cause)."""
        fname = self._entry_kind_filename()
        if not fname:
            return "generate"
        wd = self._working_dir(state)
        if wd is None:
            return "generate"
        return "modify" if (wd / fname).exists() else "generate"

    def _context(self, state: "State") -> dict:
        return {
            "mode": state.mode,
            "op_name": state.op_name,
            "op_dir": str(state.op_dir) if (state.op_dir and self.inject_op_dir) else "",
        }

    def _operator_section(self, state: "State") -> str:
        """A '## 算子' block injecting operator identity + requirement summary.

        Cures P1's "the specific operator wasn't provided": every design agent
        must know which operator it is designing for. Empty string when no
        identity is available (keeps prompts clean in synthetic tests).
        """
        lines: list[str] = []
        if state.op_name:
            lines.append(f"算子名：{state.op_name}")
        if state.op_dir and self.inject_op_dir:
            # design-halt-diagnostics P4: op_dir is presented right where the
            # agent first sees it — disambiguate up front (读参考, not 产出目标)
            # rather than only after the fact via _missing_artifact_error's
            # corrective hint, since a preventable misread costs an iteration.
            lines.append(
                f"算子目录：{state.op_dir}（只读参考，外部已有算子源码所在目录；"
                f"当前工作目录才是本步骤产出文件的唯一位置，见下方产出边界）")
        summary = self._requirement_summary(state)
        if summary:
            lines.append("需求摘要：")
            lines.append(summary)
        if not lines:
            return ""
        return "## 算子\n" + "\n".join(lines)

    @staticmethod
    def _requirement_summary(state: "State", cap: int = 2000) -> str:
        """Render the structured requirement to a size-capped JSON summary."""
        import dataclasses
        req = getattr(state, "requirement", None)
        if req is None:
            return ""
        try:
            if hasattr(req, "to_dict"):
                payload = req.to_dict()
            elif dataclasses.is_dataclass(req):
                payload = dataclasses.asdict(req)
            else:
                payload = req
            text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        except (TypeError, ValueError):
            text = str(req)
        return text[:cap]

    def _skill_section(self) -> str:
        """A short note pointing the agent at the design method loaded for this step.

        The backend delivers the assigned skill (leading ``/<skill>`` on claude /
        first-call on opencode; see the backend's ``render_skill_injection``, D2)
        which loads the SKILL.md design method/spec into the session; this section
        just names it so the body reads coherently. The method content stays in
        SKILL.md (single source) — not duplicated here.
        """
        skill = self._assigned_skill()
        if not skill:
            return ""
        return (f"## 设计方法\n本步骤的设计方法和规范已在本会话加载（skill `{skill}`）；"
                f"请据此执行。")

    def _upstream_inputs(self, state: "State") -> dict:
        """Structured upstream products this substage consumes for THIS step.

        Data-flow (c): the orchestration delivers each step's input products to
        the agent (injected into the prompt below) so the skill reads them from
        the conversation — never by cross-reading another step's files. Default:
        none (general-design-generator works from the requirement summary alone). Consuming
        substages override to name the products their input_contract requires.
        """
        return {}

    _INPUT_CAP = 8000

    def _inputs_section(self, state: "State") -> str:
        """First principle (step-10, F2): inputs travel as files in the working
        dir (see _materialize_inputs), NOT as JSON injected into the prompt. This
        section is therefore suppressed; the SKILL.md contract + prompt_intro tell
        the agent to read the declared input files from the working dir. Kept as a
        method (returning "") so substages whose custom _build_prompt calls it stay
        valid, and so the prompt never re-couples to in-band product injection."""
        return ""

    def _output_boundary(self, state: "State") -> str:
        """P6-d: prevent agent from copying upstream products into the working dir.

        design-halt-diagnostics P4: also restates that cwd (not 算子目录/op_dir)
        is the sole output location — the same corrective hint
        ``_missing_artifact_error`` gives after a miss, moved up front here so
        the first iteration doesn't burn a retry on it.

        Batch 20260820 兜底（方案 B）：注入 working_dir 的**绝对路径** + 要求用
        ``pwd`` 验证。路径来自 ``self._working_dir(state)`` —— 与 SpawnAgent 的
        ``working_dir`` 是同一函数、同一 state、同一时刻计算，且 ``_materialize_inputs``
        已先 mkdir，故注入的路径**必然等于 spawn cwd 且必然存在**。给绝对路径是降低
        模型路径幻觉概率（模型不再需要自己拼 run_dir/batch 前缀）；显式要求 pwd 验证 +
        禁止绝对路径写盘，双保险。这是预防性加固（概率性），主兜底是自动搬回（方案 A）。
        """
        wd = self._working_dir(state)
        if wd is None:
            boundary = (
                "只产出上列文件，且必须写入当前工作目录（相对路径）；"
                "算子目录（op_dir，若上文提及）是只读参考，不是产出位置。"
                "不要将上游产物（如 design_spec / tiling_strategy 等）"
                "复制到当前工作目录。")
        else:
            boundary = (
                f"当前工作目录（cwd）的完整路径为：{wd}\n"
                f"请先用 `pwd` 验证你所在目录，然后用相对路径写入产物；"
                f"禁止拼写绝对路径（绝对路径极易拼错 batch 前缀）。\n"
                "只产出上列文件，且必须写入当前工作目录（相对路径）；"
                "算子目录（op_dir，若上文提及）是只读参考，不是产出位置。"
                "不要将上游产物（如 design_spec / tiling_strategy 等）"
                "复制到当前工作目录。")
        return boundary

    def _build_prompt(self, state: "State", iteration: int) -> str:
        sections = [f"## 任务\n{self.prompt_intro}"]
        # P1-a (D2): entry-kind section — driven by whether this stage's own
        # product already exists (entry_kind=modify), not iteration count, so a
        # corrective loopback re-entry at iteration=1 still carries it (P61 fix).
        if self.entry_kind(state) == "modify":
            sections.append(
                "## 增量修改上下文\n"
                "工作目录中已存在上一轮的本产物，请基于已有产物增量修改："
                "优先检查现有文件，只补充或修正缺失/错误的部分，"
                "勿从零重复扫描。")
        op = self._operator_section(state)
        if op:
            sections.append(op)
        inputs = self._inputs_section(state)
        if inputs:
            sections.append(inputs)
        skill = self._skill_section()
        if skill:
            sections.append(skill)
        sections.append(self.artifact_contract().render_output_requirements())
        sections.append(self._output_boundary(state))
        sections.extend(self._extra_prompt_sections(state))
        # P6-c / P45 第一刀: loopback feedback — gate stages (anchor-consistency /
        # validate) write structured failure details here so the retrying agent
        # sees exactly what failed, not a generic retry context. Rendered via the
        # shared _feedback_section helper (P44-C: verdict = judgment face,
        # remediation = non-binding advice). Consumed once (cleared after use).
        fb_section = self._feedback_section(state)
        if fb_section:
            sections.append(fb_section)
        if state.user_feedback:
            sections.append(f"## 用户反馈\n{state.user_feedback}")
        prev = self._previous_decision_section(state)
        if prev:
            sections.append(prev)
        sections.append(self._decision_log_output_section())
        return "\n\n".join(s for s in sections if s)

    def _extra_prompt_sections(self, state) -> list[str]:
        """Hook for subclasses to inject extra prompt sections (capability
        constraints, role boundaries). Default empty — most stages need nothing
        extra. Inserted after the output boundary, before loopback feedback."""
        return []

    def _feedback_section(self, state) -> str | None:
        """P45 第一刀: render the loopback feedback section so the retrying agent
        sees exactly what failed. Shared by the base ``_build_prompt`` and the
        ``TilingStage`` override (which previously dropped it → run
        20260706-192227's 3-round zero-consumption). P44-C: renders the judgment
        face (verdict/detail) as fact and remediation as non-binding advice, so
        a suggestion is never mistaken for a verdict.
        """
        # Rendering extracted to issue_render.render_loopback_feedback_section
        # (shared with RequirementStage — non-_DesignSubstage that also consumes
        # a gate's _loopback_feedback on escalate-bubble; renderer does the
        # empty-check internally).
        from ascendc_devkit.orchestration.issue_render import render_loopback_feedback_section
        return render_loopback_feedback_section(state)

    def _capture_decision_log(self, state, artifacts) -> dict:
        logs = dict(state.decision_logs)
        content = artifacts.get("decision_log.json")
        if content:
            try:
                logs[self.name] = json.loads(content)
            except json.JSONDecodeError:
                pass
        return logs

    def _error(self, state, message, error_type="missing_artifact"):
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        return state.with_updates(last_error=ErrorFeedback(
            stage_name=self.name, error_type=error_type, message=message))

    def _missing_artifact_error(self, state, filename, wd, transcript=None):
        """P62: product not found in the correct working_dir. Unlike ``_error``
        (which only stamps ``last_error`` for halt routing), this ALSO sets
        ``user_feedback`` so the NEXT iteration's prompt tells the agent WHERE
        the file must land. That is the point of re-spawning: the iteration
        budget exists precisely so a misplaced product gets corrected with a
        targeted hint, not halted on first miss.

        Reached only AFTER in-place recovery was attempted (and refused) by the
        caller — see ``_read_disk_artifacts``. When ``transcript`` evidence
        names the misplaced path, the correction message cites the REAL path
        instead of a generic "not found" (the recovery's own WARN already
        explains why the move was refused: target conflict / cross-batch /
        evidence gone)."""
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        from ascendc_devkit.infra.logger import Logger
        evidence_path, refuse_reason = (
            _harvest_relocation_evidence_detailed(transcript, filename, wd)
            if wd is not None else (None, None))
        if evidence_path is not None:
            Logger.warn(
                f"[{self.name}] {filename} 的孤儿证据指向 {evidence_path}（wd 之外），"
                f"但就地搬回未成功（拒搬原因见上一条 artifact_relocated/拒绝日志），"
                f"走重新生成路径")
            msg = (f"{self.name}: 产物 {filename} 被写入了 {evidence_path}，"
                   f"而不是当前工作目录 {wd}。必须以相对路径写入当前工作目录"
                   f"（spawn 时 cwd 已设为 {wd}），请勿使用绝对路径或写出到"
                   f"仓根/其他目录。")
            return state.with_updates(
                last_error=ErrorFeedback(stage_name=self.name,
                                         error_type="missing_artifact", message=msg),
                user_feedback=msg)
        if refuse_reason == "cross_batch":
            Logger.warn(
                f"[{self.name}] 检测到 {filename} 写入了另一 batch 目录（transcript "
                f"证据），拒搬（避免跨 run 误搬），走重新生成路径")
        msg = (f"{self.name}: 产物 {filename} 未在正确目录找到。"
               f"必须以相对路径写入当前工作目录（spawn 时 cwd 已设为 {wd}），"
               f"请勿使用绝对路径或写出到仓根/其他目录。")
        return state.with_updates(
            last_error=ErrorFeedback(stage_name=self.name,
                                     error_type="missing_artifact", message=msg),
            user_feedback=msg)

    def _infra_no_product_error(self, state, filename, agent_result):
        """P93 (step-69): agent 因 infra 错误（网关/配置/鉴权/spawn 超时）未产出
        ``filename``，不是写错目录。与 ``_missing_artifact_error`` 的关键差别：不
        写 ``user_feedback``（infra 下重试无意义，不教 agent 修路径——上一轮就是
        被这种误导性"写错目录"文案带偏去修路径的）；``last_error.error_type='infra'``
        让 ``actions()`` 短路终止迭代（step-27 DEFER 收窄：设计子阶段补 infra 感知，
        不引熔断器，resume 天然重跑）。"""
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        crash = ""
        metrics = getattr(agent_result, "metrics", None) or {}
        if isinstance(metrics, dict):
            crash = str(metrics.get("failure_reason", ""))
        msg = (f"{self.name}: agent 因基础设施错误未产出 {filename}"
               f"（非写错目录，重试无意义，终止迭代）。原因：{crash}")
        return state.with_updates(last_error=ErrorFeedback(
            stage_name=self.name, error_type="infra", message=msg))

    def _read_disk_artifacts(self, state, result, required, optional=()):
        """P62 single pathway for design-stage product reads. Locates each
        required product FILE on disk under this stage's working_dir (location
        strict, name tolerant via ``_locate_artifact``) and reads it; optional
        files are read only if present.

        Returns ``(raw, None)`` on success — ``raw`` is ``{filename: text}``,
        the shape ``artifact_contract().parse`` and ``_capture_decision_log``
        expect. Returns ``(None, error_state)`` when a required product is
        missing/misplaced (``error_state`` carries last_error + user_feedback so
        the iteration loop re-spawns the agent with a location hint) or unreadable.

        Orphan recovery (20260821 F3 全局收口): when a required product fails
        to locate, the SAME transition first attempts an in-place recovery —
        transcript evidence → ``recover_orphan_artifact`` (defensive move back
        into wd) → re-locate. Success costs ZERO extra iterations (same-round
        self-heal); refusal (target conflict / cross-batch / evidence gone)
        falls through to ``_missing_artifact_error`` exactly as before. The
        prior pending_relocation/AskUserQuestion state machine is deleted
        (§2.5) — the decision point added a cross-iteration sticky state whose
        only value was re-asking what the evidence had already determined.

        The agent-dict fallback is gone (§2.5 唯一通路): a product that leaked to
        the repo root must not sail through on the agent's returned dict. Every
        design-stage transition (``_parse_single``, tiling segments, integrate,
        validate, anchor-per-template, detailed-design-intake) goes through here
        — one location invariant, one re-spawn channel.

        ``decision_log.json`` is read as an IMPLICIT optional (merged into the
        caller's ``optional``) because it is a universal companion — every design
        substage may emit one alongside its required artifact, and the base-class
        ``_capture_decision_log`` looks for it in ``raw``. Centralizing this here
        keeps the single pathway the source of truth for what lands in ``raw``
        and matches the pre-P62 behavior (where ``raw`` was the whole artifacts
        dict)."""
        wd = result.get("_working_dir")
        transcript = None
        agent_result = result.get("agent_result")
        if agent_result is not None:
            transcript = getattr(agent_result, "transcript", None)
        if wd is None:
            prim = required[0] if required else (optional[0] if optional else "?")
            return None, self._missing_artifact_error(state, prim, wd, transcript)
        optional_all = list(optional)
        if "decision_log.json" not in optional_all:
            optional_all.append("decision_log.json")
        raw = {}
        for fn in required:
            located = _locate_artifact(wd, fn)
            if located is None:
                # P93 (step-69): agent 因 infra 错误未产出——非写错目录。改报 infra
                # （不写误导性 user_feedback），让 actions() 短路终止迭代，不烧 3 轮
                # 预算（run 20260720-095303-413565 buffer-kernel 三重误报的教训）。
                if (agent_result is not None
                        and is_infra_error_type(getattr(agent_result, "error_type", None))):
                    return None, self._infra_no_product_error(
                        state, fn, agent_result)
                # 孤儿就地恢复（同轮自愈）：locate 失败 → transcript 证据 → 搬回 →
                # 重新 locate。成功则本轮直接消费产物；拒搬（target 冲突/跨 batch/
                # 证据没了）落回 _missing_artifact_error 正常重试，行为=收口前。
                if (transcript is not None
                        and recover_orphan_artifact(
                            transcript, fn, wd, state, self.name)):
                    located = _locate_artifact(wd, fn)
                if located is None:
                    return None, self._missing_artifact_error(
                        state, fn, wd, transcript)
            try:
                raw[fn] = located.read_text(encoding="utf-8")
            except OSError as e:
                return None, self._error(state, str(e), error_type="schema_violation")
        for fn in optional_all:
            located = _locate_artifact(wd, fn)
            if located is not None:
                try:
                    raw[fn] = located.read_text(encoding="utf-8")
                except OSError as e:
                    return None, self._error(state, str(e), error_type="schema_violation")
        # artifact-location-provenance (success-path stray sweep): the product
        # WAS found in wd, but the agent may ALSO have scattered a same-named
        # copy outside wd (observed: an opencode reviewer wrote blocking_status
        # to BOTH the correct wd AND a doubled-run-id path — batch 20260729-*
        # d67f55). The relocation gate above only fires on a MISSING product, so
        # a stray + correct copy left the stray orphaned forever. Clean any
        # transcript-evidenced stray here so it never accrues as garbage nor
        # (worse) gets mistaken for the product on a later resume. Best-effort:
        # only removes files (a) named like the product, (b) proven written by
        # THIS agent's transcript, (c) outside wd — never a blind fs sweep.
        if transcript is not None and wd is not None:
            self._sweep_located_strays(list(required) + optional_all, wd, transcript)
        return raw, None

    def _sweep_located_strays(self, filenames, wd, transcript):
        """Remove same-named product copies the agent wrote OUTSIDE wd (proven by
        its own transcript), after the real product was located in wd. Bounded &
        safe: only paths the transcript shows THIS agent wrote, matching the
        product name, resolving outside wd. Loud warn per removal (§1.3 — never
        silently), best-effort (never raises into the read path)."""
        from pathlib import Path
        for fn in filenames:
            stray = _harvest_relocation_evidence(transcript, fn, wd)
            if stray is None:
                continue
            try:
                if stray.is_file():
                    stray.unlink()
                    from ascendc_devkit.infra.logger import Logger
                    Logger.warn(
                        f"[{self.name}] removed a stray {fn} the agent wrote "
                        f"outside its working_dir at {stray} (product was "
                        f"correctly located in {wd}; §2.4 artifacts must stay in "
                        f"wd — this orphan is cleaned, not consumed)")
            except OSError:
                pass  # best-effort cleanup — a failed unlink must not break reads

    def _parse_single(self, state, result, field, filename, strict=False):
        """Parse one required JSON artifact into `field`; capture decision log.

        Returns (new_state, ok). On missing/invalid artifact records last_error
        and ok=False so subclasses can short-circuit.

        strict (P47 Step 2): when True, schema errors (e.g. a gate issue missing
        its executable ``acceptance``) are surfaced as last_error with ok=False
        — the producer must state the judgment (§1.3 加载期校验; L3 §3.2: an
        issue whose acceptance cannot be stated is ill-formed, not a special
        class). When False (default) a parseable payload is accepted even with
        schema errors, preserving the lenient behavior non-gate stages rely on.

        P62: delegates the disk locate+read to ``_read_disk_artifacts`` (the
        single pathway, §2.5) — location strict, name tolerant, missing →
        re-spawn with a hint. Clears sticky last_error on success (P5).
        """
        raw, err_state = self._read_disk_artifacts(state, result, [filename])
        if raw is None:
            return err_state, False
        try:
            parsed, errors = self.artifact_contract().parse(raw)
        except (OSError, json.JSONDecodeError) as e:
            return self._error(state, str(e), error_type="schema_violation"), False
        if field not in parsed:
            return self._error(
                state, "; ".join(errors) or f"{self.name}: invalid {filename}",
                error_type="schema_violation"), False
        if strict and errors:
            return self._error(
                state, "; ".join(errors), error_type="schema_violation"), False
        logs = self._capture_decision_log(state, raw)
        return state.with_updates(
            **{field: parsed[field],
               "decision_logs": logs,
               "user_feedback": "",
               "last_error": None}), True  # P5: 清除 sticky error

    def _success_updates(self, state, **fields):
        """Success-path ``state.with_updates`` that always clears this stage's
        own stale ``last_error`` (mirrors ``_parse_single``'s P5 sticky-error
        clear, design-halt-diagnostics P1). Custom
        ``transition`` overrides that bypass ``_parse_single`` must route their
        success branch through this — not through a bare ``state.with_updates(...)``
        — so a prior iteration's failure can't survive into a later successful
        one and falsely halt the pipeline. Callers with a genuine error to
        record on this same branch (e.g. a schema-violation ``last_error``)
        must NOT use this helper for that branch — build the error via
        ``self._error(...)`` instead."""
        return state.with_updates(last_error=None, **fields)


# —— concept-design (general-design) group ——

class GeneralDesignStage(_DesignSubstage):
    name = "general-design-generator"
    description = "Generate the general (concept) design from requirement"
    agent_name = "ascendc-design-generator"
    prompt_intro = "基于需求规格生成概要设计（切分轴优先级 / TilingData / 循环框架 / Buffer 评估 / 归一化梯度公式）。"
    _schema_files = ["general_design.json"]

    def artifact_contract(self) -> ArtifactContract:
        """概设产物的机器契约：general_design.json（必需）+ template_decision.json
        （SIMD/SIMT 编程模型判定，仅 A5 路径产出 → required=False）。

        两个 schema 分别从产出方 skill 的 ``schema/`` 目录加载（template_decision.json
        属于 ascendc-op-design-template-select，仿 TilingStage 遍历子 skill 的机制）——
        schema 随 skill 走（§2.2），概设 agent 在会话内 tail-call 该 skill 产出第二产物。
        """
        from dataclasses import replace as _replace
        from ascendc_devkit.adapters.schema.loader import SchemaLoader
        gd = SchemaLoader.load_spec_from_skill(
            "ascendc-op-general-design", "general_design.json")
        td = _replace(SchemaLoader.load_spec_from_skill(
            "ascendc-op-design-template-select", "template_decision.json"),
            required=False)
        return ArtifactContract(artifacts=[gd, td])

    def input_contract(self) -> StageIOContract:
        # 13 E4 / D-1: golden is a full-chain reference (design 依据 + verify
        # 基准), so concept design requires it too — declaring golden_path here
        # makes every workflow mounting general-design (incl. generate_ascendc_se)
        # require the golden three params (enforced declaratively by preflight).
        return StageIOContract(requires=["requirement", "golden_path"],
                               optional=["design_doc_path"])

    def output_contract(self) -> StageIOContract:
        # template_decision（SIMD/SIMT 判定）为 optional_provides：仅 A5 路径产出，
        # A2/A3 平台锁定 SIMD 不产出；不参与 has_all() 早停检查。
        return StageIOContract(provides=["general_design"],
                               optional_provides=["template_decision"])

    def validate_inputs(self, state: "State") -> list[str]:
        errors = []
        req = state.requirement
        if req is None and not state.design_doc_path:
            errors.append("neither requirement nor design_doc_path is available")
        elif req is not None and _load_authoritative_requirement(state) is None:
            # P1/§1.3: requirement 在 State 但权威磁盘文件不可达 → 物化拿不到
            # 全量需求（domain/公式/dtype 域），加载期拦截而非让 agent 拿 reduced。
            errors.append(
                "requirement 存在于 State 但权威磁盘文件 "
                "artifacts/requirement/requirement.json 不可达——无法物化全量需求")
        return errors

    def _upstream_inputs(self, state: "State") -> dict:
        # general-design-generator's primary input is the requirement; materialize it as
        # requirement.json so the skill reads it from the working dir (F2).
        return {"requirement": getattr(state, "requirement", None)}

    def _materialize_extra(self, state: "State", working_dir: "Path") -> None:
        # When the user supplied a concept-design document (--general-design),
        # copy it into the working dir as a file the skill reads (pass-through /
        # incremental fill), instead of injecting its text into the prompt.
        doc_text = self._read_design_doc(state)
        if doc_text is not None:
            (working_dir / "existing_general_design.md").write_text(
                doc_text, encoding="utf-8")

    def _build_prompt(self, state, iteration: int) -> str:
        # When the user supplied a concept-design document (--general-design),
        # it has been materialized to existing_general_design.md in the working
        # dir (see _materialize_extra); the skill reads it and runs pass-through /
        # incremental fill rather than generating from scratch (step-2b decision 8).
        sections = [f"## 任务\n{self.prompt_intro}"]
        # P1-a (D2): entry-kind section — product-existence driven, not
        # iteration (P61 fix: loopback re-entry at iteration=1 still carries it).
        if self.entry_kind(state) == "modify":
            sections.append(
                "## 增量修改上下文\n"
                "工作目录中已存在上一轮的本产物，请基于已有产物增量修改："
                "优先检查现有文件，只补充或修正缺失/错误的部分，"
                "勿从零重复扫描。")
        op = self._operator_section(state)
        if op:
            sections.append(op)
        skill = self._skill_section()
        if skill:
            sections.append(skill)
        if self._read_design_doc(state) is not None:
            sections.append(
                "## 已有概要设计\n当前工作目录已放置 `existing_general_design.md`；"
                "请走 pass-through / 基于此增量补全缺口，勿从零生成。")
        sections.append(self.artifact_contract().render_output_requirements())
        sections.append(self._output_boundary(state))
        if state.user_feedback:
            sections.append(f"## 用户反馈\n{state.user_feedback}")
        prev = self._previous_decision_section(state)
        if prev:
            sections.append(prev)
        sections.append(self._decision_log_output_section())
        return "\n\n".join(s for s in sections if s)

    @staticmethod
    def _read_design_doc(state) -> str | None:
        path = getattr(state, "design_doc_path", None)
        if not path:
            return None
        try:
            from pathlib import Path
            return Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def transition(self, state, result):
        # step-34 D3: a gate iteration returns [AskUserQuestion] (no agent ran,
        # no general_design.json yet) — consume the user's choice WITHOUT trying
        # to parse a missing artifact. Both choices set cross_gen_confirmed so
        # the gate won't re-fire on the next iteration; retarget additionally
        # rewrites design_target_chip to the on-box chip.
        decision = result.get("decision", "") if isinstance(result, dict) else ""
        if decision == self._CROSSGEN_RETARGET:
            return state.with_updates(
                design_target_chip=state.runtime_target_chip,
                cross_gen_confirmed=True)
        if decision == self._CROSSGEN_CONFIRM:
            return state.with_updates(cross_gen_confirmed=True)
        # 多产物解析：general_design.json 必需；template_decision.json（A5
        # SIMD/SIMT 判定）可选——A2/A3 平台锁定 SIMD 不产出，缺它不报错。
        raw, err_state = self._read_disk_artifacts(
            state, result, ["general_design.json"],
            optional=["template_decision.json"])
        if raw is None:
            return err_state
        try:
            parsed, errors = self.artifact_contract().parse(raw)
        except (OSError, json.JSONDecodeError) as e:
            return self._error(state, str(e), error_type="schema_violation")
        if "general_design" not in parsed:
            return self._error(
                state, "; ".join(errors)
                or f"{self.name}: invalid general_design.json",
                error_type="schema_violation")
        logs = self._capture_decision_log(state, raw)
        updates = {"general_design": parsed["general_design"]}
        if "template_decision" in parsed:
            updates["template_decision"] = parsed["template_decision"]
        return state.with_updates(
            **updates,
            decision_logs=logs,
            user_feedback="",
            last_error=None)  # P5: 清除 sticky error

    # —— step-34 D3: pre-design cross-generation confirmation gate ——————
    # Origin: a user on A2 hardware declared an A5 target; the inconsistency
    # was caught only at codegen's build gate — after requirement / general /
    # detailed / test-design work was already spent. The gate moves the
    # decision to BEFORE design work, riding the existing AskUserQuestion →
    # DecisionPendingError → ``respond`` resume path (path A; Step 0 wired the
    # decision_response.json replay so a non-interactive abort run resumes
    # instead of looping). Fires iff a cross-generation design would be
    # build/run-validated locally — pure-design workflows skip it (their
    # product is never validated on this box, so cross-generation is harmless).
    _CROSSGEN_RETARGET = "改打本机"   # retarget design to the on-box chip
    _CROSSGEN_CONFIRM = "跨代设计"    # proceed cross-generation as declared

    @classmethod
    def _cross_generation_gate_fires(cls, state) -> bool:
        design = getattr(state, "design_target_chip", "") or ""
        runtime = getattr(state, "runtime_target_chip", "") or ""
        if not design or not is_known_generation(runtime):
            return False
        if runtime_supports_design(design, runtime):
            return False
        if getattr(state, "cross_gen_confirmed", False):
            return False
        # Only guard when the workflow will build/run locally. A pure-design
        # workflow (requires_npu=False) can target any generation regardless of
        # the box. Unknown/empty workflow_name → None → don't gate (codegen's
        # build gate remains the backstop for that degenerate case).
        return workflow_requires_npu(state.workflow_name) is True

    def actions(self, state: "State", iteration: int = 1) -> list[Action]:
        if self._cross_generation_gate_fires(state):
            design = chip_display_name(state.design_target_chip)
            runtime = chip_display_name(state.runtime_target_chip)
            return [AskUserQuestion(
                question=(
                    f"目标代际 {design} 与本机硬件 {runtime} 不一致：跨代设计产物"
                    f"无法在本机 build/run。请选择如何继续："),
                options=[
                    Option(
                        label=self._CROSSGEN_RETARGET,
                        description=f"将设计目标改打本机 {runtime}，可在本机完整 build/run"),
                    Option(
                        label=self._CROSSGEN_CONFIRM,
                        description=f"保持 {design} 跨代设计（产物不在本机验证）"),
                ],
            )]
        return super().actions(state, iteration)


# —— detailed-design group ——

class DetailedDesignIntakeStage(_DesignSubstage):
    """Short-circuit entry for the detailed-design group (decision-point 9, A1).

    Pure no-op when ``detailed_design_path`` is unset: emits no actions, returns
    state unchanged, resolves "default" so the group runs its normal generation
    flow (template-division → tiling → ... → validate).

    When the user supplied an existing detailed design (--detailed-design), it
    spawns one agent to parse that document into the three-piece contract
    (design_spec / tiling_strategy / kernel_architecture) + design_doc, then
    resolves "short_circuit" so the group's transition_table routes forward to
    validate — skipping division/tiling/anchor/integrate/docgen. codegen then
    consumes the parsed three-piece contract as usual (plan b).
    """

    name = "dd-intake"
    description = "Parse a user-supplied detailed design; else no-op pass-through"
    agent_name = "ascendc-design-generator"
    default_max_iterations = 1
    prompt_intro = ("解析用户提供的现有详细设计文档，抽取为结构化两件套："
                    "design_spec / tiling_strategy（勿重新设计，忠实转写）。"
                    "kernel_architecture 不再由设计阶段产出，由 codegen_init 确定性生成。")

    def input_contract(self) -> StageIOContract:
        # Declares general_design as required so the detailed-design group's
        # outward input_contract (taken from its first child) keeps requiring it
        # for the normal generation flow (template-division consumes it). The
        # short-circuit parse path reads detailed_design_path + requirement.
        return StageIOContract(requires=["general_design"],
                               optional=["requirement", "detailed_design_path"])

    def output_contract(self) -> StageIOContract:
        # kernel_architecture removed (step 9): now produced by codegen_init.
        return StageIOContract(
            optional_provides=["design_spec", "tiling_strategy",
                               "design_doc"])
    def artifact_contract(self) -> ArtifactContract:
        """Intake 不产出这三件套——它解析用户提供的详设文档转写为三件套。

        Schema 归 integrate skill 所有（synthesize 段即 integrate 职责）；
        intake 在短路径上读取同组 schema。这是唯一不通过 _schema_files / 基类
        自动发现的特例（跨 skill 读 schema）。
        """
        from ascendc_devkit.adapters.schema.loader import SchemaLoader
        # kernel_architecture.json removed (step 9): section declaration is
        # now codegen_init's responsibility, not design's.
        return SchemaLoader.load_contract_from_skill(
            "ascendc-op-design-integrate", [
                "design_spec.json", "tiling_strategy.json",
                "data_flow.json"])

    @staticmethod
    def _has_doc(state) -> bool:
        return bool(getattr(state, "detailed_design_path", None))

    def actions(self, state, iteration: int = 1):
        if not self._has_doc(state):
            return []  # no-op pass-through
        return super().actions(state, iteration)

    def skip_reason(self, state) -> str | None:
        if not self._has_doc(state):
            return "no --detailed-design supplied"
        return None

    def _upstream_inputs(self, state: "State") -> dict:
        # The intake parse path reads the requirement (for op identity / field
        # backfill); materialize it as requirement.json (F2).
        return {"requirement": getattr(state, "requirement", None)}

    def _materialize_extra(self, state: "State", working_dir: "Path") -> None:
        # Copy the user-supplied detailed-design document into the working dir as
        # a file the skill transcribes, instead of injecting its text (F2).
        doc_text = self._read_doc(state)
        if doc_text is not None:
            (working_dir / "existing_detailed_design.md").write_text(
                doc_text, encoding="utf-8")

    def _build_prompt(self, state, iteration: int) -> str:
        sections = [f"## 任务\n{self.prompt_intro}"]
        op = self._operator_section(state)
        if op:
            sections.append(op)
        skill = self._skill_section()
        if skill:
            sections.append(skill)
        if self._read_doc(state) is not None:
            sections.append(
                "## 已有详细设计文档\n当前工作目录已放置 `existing_detailed_design.md`；"
                "请忠实转写为三件套，勿重新设计。")
        sections.append(self.artifact_contract().render_output_requirements())
        sections.append(self._output_boundary(state))
        if state.user_feedback:
            sections.append(f"## 用户反馈\n{state.user_feedback}")
        sections.append(self._decision_log_output_section())
        return "\n\n".join(s for s in sections if s)

    @staticmethod
    def _read_doc(state) -> str | None:
        path = getattr(state, "detailed_design_path", None)
        if not path:
            return None
        try:
            from pathlib import Path
            return Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def transition(self, state, result):
        if not self._has_doc(state):
            return state  # no-op
        # P62: read the parsed design products from disk under working_dir (single
        # pathway via _read_disk_artifacts, §2.5) — same defect class as the other
        # design stages, on this short-circuit path too. design_spec is the de-facto
        # required piece (transition errors without it); the others are optional.
        raw, err_state = self._read_disk_artifacts(
            state, result, ["design_spec.json"],
            optional=["tiling_strategy.json", "data_flow.json"])
        if raw is None:
            return err_state
        parsed, errors = self.artifact_contract().parse(raw)
        if "design_spec" not in parsed:
            return self._error(
                state, "; ".join(errors) or f"{self.name}: missing design_spec.json")
        new_state = self._success_updates(
            state,
            design_spec=parsed.get("design_spec"),
            tiling_strategy=parsed.get("tiling_strategy"),
            data_flow=parsed.get("data_flow"),
            decision_logs=self._capture_decision_log(state, raw),
            user_feedback="")
        # P36: the user-supplied doc already IS the detailed design — design_doc
        # points at its path (state.design_doc stores an md path). No re-render:
        # DocgenStage._render_detailed is gone (docgen now generates the doc via
        # its skill), and on the short-circuit path docgen is skipped anyway.
        return new_state.with_updates(design_doc=str(state.detailed_design_path))

    def resolve_condition(self, state) -> str:
        # Short-circuit only when a doc was supplied AND parsing succeeded
        # (three-piece present). Otherwise fall through to the normal flow.
        if self._has_doc(state) and state.design_spec is not None:
            return "short_circuit"
        return "default"


class TemplateDivisionStage(_DesignSubstage):
    name = "template-division"
    description = "Determine template list + global locked decisions"
    agent_name = "ascendc-design-generator"
    prompt_intro = "划分模板列表 + TilingKey 路由 + 全局锁定决策（LD1 精度 / LD2 BUFFER_NUM / LD3 切分轴优先级）。"
    _schema_files = ["template_division.json"]

    def input_contract(self) -> StageIOContract:
        # template_decision（SIMD/SIMT 判定）为 optional：A2/A3 平台不产出，
        # 模板划分默认编程模型=SIMD（平台锁定，C-01）。
        return StageIOContract(requires=["general_design"],
                               optional=["template_decision"])

    def output_contract(self) -> StageIOContract:
        return StageIOContract(provides=["template_division"])

    def _upstream_inputs(self, state: "State") -> dict:
        return {"general_design": getattr(state, "general_design", None),
                "template_decision": getattr(state, "template_decision", None)}

    def transition(self, state, result):
        new_state, ok = self._parse_single(
            state, result, "template_division", "template_division.json")
        if not ok:
            return new_state
        # §2.9 上游自检（删除跨模板一致性门后的兜底）：tiling_key 唯一——否则
        # codegen 的 tiling_key 路由歧义（多模板同 key）。route_condition 互斥是
        # 自然语言语义，无法机械校验，归 template_division SKILL.md 自检项。
        td = getattr(new_state, "template_division", None) or {}
        templates = td.get("templates", []) if isinstance(td, dict) else []
        keys = [t.get("tiling_key") for t in templates if isinstance(t, dict)]
        if len(keys) != len(set(keys)):
            return self._error(
                new_state,
                "template-division: tiling_key 不唯一（存在重复），codegen 路由会歧义；"
                "单一作者自检兜底（§2.9）",
                error_type="schema_violation")
        return new_state


class SynthesizeStage(_DesignSubstage):
    """合成 agent（step-2b 合并版，选 B 编排层合并）：组装 design_spec /
    tiling_strategy（integrate）+ 组装详细设计说明书（docgen）。

    一个 agent 会话串行 tail-call integrate + docgen 两个子 skill，产出
    design_spec.json + tiling_strategy.json（+ 可选 data_flow.json）+ 详细设计
    说明书 md。合并收益（§1.14/§2.9）：文档与契约在同一上下文产出，不可能自相矛盾
    （构造性消解 integrate↔docgen 跨边界漂移）。跨模板不一致由 integrate 子 skill
    就地改自己的产物，绝不回炉上游（owner 语义）。
    """

    name = "synthesize"
    description = "合成最终设计契约（integrate：design_spec + tiling_strategy）"
    agent_name = "ascendc-design-generator"
    prompt_intro = ("汇聚所有模板的 tiling 产物，合成 design_spec / tiling_strategy（共享 "
                    "TilingData、公共函数签名、跨模板精度链一致性）。")
    def input_contract(self) -> StageIOContract:
        return StageIOContract(requires=["tiling_results"])

    def output_contract(self) -> StageIOContract:
        return StageIOContract(
            provides=["design_spec", "tiling_strategy"],
            optional_provides=["data_flow"])

    _schema_files = ["design_spec.json", "tiling_strategy.json", "data_flow.json"]

    def _upstream_inputs(self, state: "State") -> dict:
        return {"tiling_results": getattr(state, "tiling_results", None),
                "requirement": getattr(state, "requirement", None),
                "general_design": getattr(state, "general_design", None)}

    def _extra_prompt_sections(self, state) -> list[str]:
        # P0/D1 (36-*.md §1): consume forwarded advisories — cross-template
        # consistency issues whose owner is the integration layer. Resolve them
        # IN PLACE (e.g. unify two templates' R5 field naming); never loop back,
        # never re-split templates.
        advs = [a for a in (getattr(state, "pending_advisories", None) or [])
                if a.get("target") == "synthesize"]
        if not advs:
            return []
        lines = []
        for a in advs:
            flag = (" ⚠️owner 归属待人工裁定（本轮按整合层默认处理）"
                    if a.get("owner_ambiguous") else "")
            line = f"- [{a.get('code', '?')}]{flag} {a.get('detail', '')}"
            if a.get("remediation"):
                line += f"\n  补救建议: {a.get('remediation')}"
            if a.get("acceptance"):
                line += f"\n  解决判据: {a.get('acceptance')}"
            lines.append(line)
        return ["## 待就地消解的跨模板一致性建议（advisory，非阻断）\n"
                "以下非阻断问题归属整合层，请在本次合成产物中就地统一，"
                "勿回退上游、勿重新切分模板：\n" + "\n".join(lines)]

    def transition(self, state, result):
        # 1. 读 JSON 产物（design_spec + tiling_strategy 必需，data_flow 可选）。
        raw, err_state = self._read_disk_artifacts(
            state, result, ["design_spec.json", "tiling_strategy.json"],
            optional=["data_flow.json"])
        if raw is None:
            return err_state
        parsed, errors = self.artifact_contract().parse(raw)
        if "design_spec" not in parsed:
            return self._error(
                state, "; ".join(errors) or f"{self.name}: missing design_spec.json")
        # 2. integrate 确定性归一化（scalar 路由 / shape rank / param_type /
        #    in-place outputs）——见 IntegrateStage 原注释（C/P121/P123）。
        ds = parsed["design_spec"]
        if isinstance(ds, dict):
            from ascendc_devkit.infra.logger import Logger
            # A4/§1.3: support_domain 结构加载期校验（接线死代码校验器）
            sd = ds.get("support_domain")
            if isinstance(sd, dict):
                from ascendc_devkit.domain.support_domain import (
                    validate_support_domain_structure,
                )
                sd_errs = validate_support_domain_structure(sd)
                if sd_errs:
                    Logger.warn(
                        f"[{self.name}] support_domain 结构校验未通过（§1.3）："
                        + "; ".join(sd_errs))
            auth_req = _load_authoritative_requirement(state)
            moved = _route_scalar_params(
                ds, golden_fn=_load_golden_fn(state), requirement=auth_req)
            if moved:
                Logger.warn(
                    f"[{self.name}] routed {len(moved)} scalar param(s) from "
                    f"inputs/outputs into attrs (LLM mis-classified): {moved}")
            fixed = _reconcile_shape_ranks(ds, getattr(state, "requirement", None))
            if fixed:
                Logger.warn(
                    f"[{self.name}] reconciled {len(fixed)} IO shape rank(s) to "
                    f"requirement: {fixed}")
            if auth_req is not None:
                # P1/A3（§2.9 链内自检）：requirement.domain ⊆ design.support_domain
                # 对质（design 必须覆盖需求域）。未覆盖/超集 → 告警留痕；不机械撑大
                # （反对 D，§1.2 可诊断）。
                sd = ds.get("support_domain")
                if isinstance(sd, dict):
                    from ascendc_devkit.domain.support_domain import (
                        domain_covers, requirement_domain, design_support_domain,
                    )
                    gaps = domain_covers(requirement_domain(auth_req),
                                         design_support_domain(ds))
                    if gaps:
                        Logger.warn(
                            f"[{self.name}] design_spec.support_domain 未覆盖 "
                            f"requirement(golden) 域（链内对质）：\n"
                            + "\n".join(f"  - {g}" for g in gaps)
                            + "\n收窄留痕；由 debug/eval 兜底（§1.2）")
                pt_fixed = _reconcile_param_types(ds, auth_req)
                eo_fixed = _reconcile_emptied_outputs(ds, auth_req)
                if pt_fixed or eo_fixed:
                    from ascendc_devkit.infra.logger import Logger
                    Logger.warn(
                        f"[{self.name}] reconciled design_spec IO to authoritative "
                        f"requirement.json: param_types={pt_fixed} "
                        f"emptied_outputs={eo_fixed}")
        # decision_log.json 随 _read_disk_artifacts 作为 implicit optional 读入 raw
        # （P62 disk-first 单一通路）——与 integrate 原逻辑一致，不读 agent_result.artifacts。
        logs = self._capture_decision_log(state, raw)
        updates = {
            "design_spec": parsed.get("design_spec"),
            "tiling_strategy": parsed.get("tiling_strategy"),
            "data_flow": parsed.get("data_flow"),
            "decision_logs": logs,
            "user_feedback": "",
            "pending_advisories": [],
        }
        # JSON schema 违规 → last_error（重 spawn）。
        if errors:
            from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
            updates["last_error"] = ErrorFeedback(
                stage_name=self.name, error_type="schema_violation",
                message="设计产物 schema 校验未通过: " + "; ".join(errors))
            return state.with_updates(**updates)
        return self._success_updates(state, **updates)


class DocgenStage(_DesignSubstage):
    """docgen 独立段（从 synthesize 门面拆出，§1.14 最小结构 + §2.9 下游忠实消费）。

    读 synthesize 段产物（design_spec / tiling_strategy）+ tiling_results +
    general_design，用 ascendc-op-design-docgen skill 组装 <op>_详细设计说明书.md。
    文档与契约的一致性由「docgen 忠实消费上游 JSON 产物」构造性保证（§2.9），
    不依赖与 integrate 同会话——消除「长上下文稀释导致 docgen 被遗忘」的根因
    （docs/plan/synthesize-docgen-dilution/）。
    """

    name = "docgen"
    description = "组装详细设计说明书（docgen：<op>_详细设计说明书.md）"
    agent_name = "ascendc-design-generator"
    prompt_intro = ("读上游合成产物（design_spec / tiling_strategy / tiling_results / "
                    "general_design），按 doc_template_v2.0.md 组装 <op>_详细设计说明书.md。")
    _schema_files = []  # md 非 schema 契约产物（给人读，不机器校验）

    def input_contract(self) -> StageIOContract:
        return StageIOContract(requires=["design_spec", "tiling_strategy"])

    def output_contract(self) -> StageIOContract:
        return StageIOContract(provides=["design_doc"])

    def _upstream_inputs(self, state: "State") -> dict:
        return {
            "design_spec": getattr(state, "design_spec", None),
            "tiling_strategy": getattr(state, "tiling_strategy", None),
            "tiling_results": getattr(state, "tiling_results", None),
            "general_design": getattr(state, "general_design", None),
        }

    def transition(self, state, result):
        # 定位详细设计说明书（文件名非契约，按类型 glob）。
        wd = result.get("_working_dir")
        if wd is None:
            return self._error(
                state, f"{self.name}: no working_dir to locate the design doc")
        from pathlib import Path
        candidates = sorted(Path(wd).glob("*_详细设计说明书.md"))
        if not candidates:
            return self._missing_design_doc(state, wd)
        op_name = state.op_name or ""
        canonical = f"{op_name}_详细设计说明书.md" if op_name else None
        md_path = next(
            (c for c in candidates if canonical and c.name == canonical),
            candidates[0])
        if canonical and md_path.name != canonical:
            from ascendc_devkit.infra.logger import Logger
            Logger.info(
                f"[{self.name}] accepted design doc '{md_path.name}' "
                f"(canonical op_name={op_name}; filename is non-contractual)")
        # OpDef canonical 正向锚点兜底（advisory，fail-forward，非 halt）。
        try:
            md_text = md_path.read_text(encoding="utf-8")
        except OSError as e:
            return self._error(
                state, f"{self.name}: cannot read design doc {md_path}: {e}",
                error_type="infra")
        region = _opdef_code_region(md_text)
        missing = (_opdef_missing_canonical_anchors(region, state.design_spec)
                   if region else [])
        updates = {
            "design_doc": str(md_path),
            "user_feedback": "",
        }
        # OpDef 非 canonical → 非阻断 known_issue（fail-forward，不 halt）。
        if missing:
            own = self.name
            issue = {
                "code": "opdef_non_canonical",
                "severity": "warning",
                "target": "codegen",
                "detail": (f"§2.3 OpDef 非 canonical（缺正向锚点：{', '.join(missing)}）。"
                           "详设 md 的 OpDef 仅供参考；以 codegen def.cpp 编译产物为准。"),
                "source": own,
            }
            carried = [i for i in (state.design_known_issues or [])
                       if i.get("source") != own]
            updates["design_known_issues"] = carried + [issue]
            return self._success_updates(state, **updates)
        return self._success_updates(state, **updates)

    def _missing_design_doc(self, state, wd):
        """方案 C：缺 md → 定向 respawn 反馈（含 skill 提示），不裸 halt。

        runner 的「output_contract 未满足 → 自动重试」会 re-spawn 本 stage；这里设
        user_feedback 让下一轮 prompt（「## 用户反馈」section）告诉 agent 缺什么 +
        本阶段 skill 范围，提示「可能某 skill 未正确调用和执行」，由 agent 自行确认
        （不武断断言「未调用」——也可能是调用了但输出名/路径偏差）。skill 来源
        skill_allowlist(STAGE_SKILL_MAP[self.name])（复用配置，不新增映射）。
        """
        from ascendc_devkit.orchestration.skill_config import (
            STAGE_SKILL_MAP, skill_allowlist)
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        skills = skill_allowlist(STAGE_SKILL_MAP.get(self.name)) or []
        skills_txt = "、".join(s for s in skills if s) or "（未配置）"
        msg = (f"{self.name}: 未产出 <op>_详细设计说明书.md（design_doc 缺失，"
               f"目录 {wd}）。本阶段 skill 为 {skills_txt}；"
               f"可能是因为某 skill 未能正确调用和执行，"
               f"如果确认请继续完成 skill 任务。")
        return state.with_updates(
            last_error=ErrorFeedback(
                stage_name=self.name, error_type="missing_artifact", message=msg),
            user_feedback=msg)


def _load_golden_fn(state):
    """Load the golden callable from ``state.golden_path`` (entry name
    ``state.golden_entry``) — §1.13 golden is the IO-contract authority, parsed
    deterministically (NOT the LLM-derived requirement). Returns None when
    unavailable (no path / unreadable / no entry) so D-reconcile falls back to
    requirement. Mirrors the harness's golden load (``_harness_template.py``)."""
    import importlib.util
    gp = getattr(state, "golden_path", None)
    entry = (getattr(state, "golden_entry", "") or "").strip()
    if gp is None or not entry:
        return None
    try:
        if not gp.exists():
            return None
        spec = importlib.util.spec_from_file_location("_devkit_golden_ref", gp)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return getattr(mod, entry, None)
    except Exception:
        return None


def _lookup_in_requirement(name: str, requirement):
    """Return ``(side, entry_dict_copy)`` for *name* in requirement.inputs/outputs,
    else ``(None, None)``."""
    if not isinstance(requirement, dict):
        return None, None
    for side in ("inputs", "outputs"):
        for e in (requirement.get(side) or []):
            if isinstance(e, dict) and e.get("name") == name:
                return side, dict(e)
    return None, None


def _route_scalar_params(design_spec: dict, golden_fn=None,
                         requirement: dict | None = None) -> list[str]:
    """In-place: move scalar entries the LLM mis-listed under inputs/outputs into
    an ``attrs`` list (created if absent; dict form normalized to list), then
    D-reconcile design_spec IO to the **golden signature** (§1.13 authoritative)
    so inputs/outputs are never emptied by a mis-route.

    Judges via the shared ``is_scalar_entry`` predicate (§2.5 single pathway,
    §1.10 business semantics) — never ``shape == []`` (the 20260805 Maximum RCA,
    where ``_is_scalar_param`` emptied inputs/outputs and halted codegen).

    Step 1 (route): scalar entries under inputs/outputs → attrs (surgical, NOT a
    full OperatorSpec round-trip; preserves design_spec's richer metadata).
    Step 2 (D-reconcile — 能修绝不 halt/不空转): any tensor the golden signature
    (inputs, deterministic) or requirement (aux, incl. outputs) names as a tensor
    must sit in inputs/outputs — mis-routed into attrs → restore; missing entirely
    → fill from requirement. The IO authority is golden, a fixed input, so this is
    a deterministic in-place fix — no halt, no loopback (re-running the LLM
    producer would be idle: the IO contract is not produced by it). The only
    unrecoverable case (golden has no Tensor annotations AND requirement is also
    IO-empty = the op truly has no IO) is left to codegen.validate_inputs.

    Returns moved ``"<side>/<name>"`` for observability (D-restored names are
    removed from ``moved`` — they were not, in the end, routed to attrs)."""
    attrs_raw = design_spec.get("attrs")
    if isinstance(attrs_raw, dict):
        attr_list = [dict(v, name=k) if isinstance(v, dict) else {"name": k}
                     for k, v in attrs_raw.items()]
    elif isinstance(attrs_raw, list):
        attr_list = [dict(a) for a in attrs_raw if isinstance(a, dict)]
    else:
        attr_list = []
    existing = {a.get("name") for a in attr_list if a.get("name")}
    input_names = {i.get("name") for i in design_spec.get("inputs", [])
                   if isinstance(i, dict) and i.get("name")}
    moved: list[str] = []
    for side in ("inputs", "outputs"):
        entries = design_spec.get(side)
        if not isinstance(entries, list):
            continue
        kept = []
        for e in entries:
            name = e.get("name") if isinstance(e, dict) else None
            if (isinstance(e, dict)
                    and is_scalar_entry(e, group=side, input_names=input_names)
                    and name and name not in existing):
                attr = {"name": name,
                        "type": e.get("type") or e.get("dtype", ""),
                        "default": e.get("default")}
                for k in ("semantic", "note", "description"):
                    if k in e:
                        attr[k] = e[k]
                attr_list.append(attr)
                existing.add(name)
                moved.append(f"{side}/{name}")
            else:
                kept.append(e)
        design_spec[side] = kept
    if moved:
        design_spec["attrs"] = attr_list

    # —— D-reconcile: align design_spec IO to golden-signature authority (§1.13) ——
    # auth_tensors: golden-signature INPUTS (deterministic, §1.13) + requirement
    # OUTPUTS (a signature's params are inputs only — return values aren't params,
    # so golden can't give outputs). requirement INPUTS are deliberately NOT used:
    # design_spec may legitimately rename an input (e.g. multi_add x1→x); filling
    # by requirement-input name would duplicate it and break _reconcile_param_types'
    # positional rename-restore. Golden covers inputs authoritatively already.
    auth_tensors: set[str] = set()
    auth_order: list[str] = []                      # stable fill order (golden sig, then req outputs)
    def _auth_add(n):
        if n and n not in auth_tensors:
            auth_tensors.add(n); auth_order.append(n)
    if golden_fn is not None:
        for n in classify_golden_params(golden_fn)[0]:
            _auth_add(n)
    if isinstance(requirement, dict):
        for e in (requirement.get("outputs") or []):
            if isinstance(e, dict):
                _auth_add(e.get("name"))
    if auth_tensors:
        restored, keep_attrs = [], []
        for a in attr_list:                         # tensor mis-routed into attrs → restore
            (restored if a.get("name") in auth_tensors else keep_attrs).append(a)
        ds_names = {i.get("name") for i in design_spec.get("inputs", [])
                    if isinstance(i, dict)}
        ds_names |= {o.get("name") for o in design_spec.get("outputs", [])
                     if isinstance(o, dict)}
        filled = 0
        for name in auth_order:                     # stable order; skip already-present
            if name in ds_names:
                continue
            side, entry = _lookup_in_requirement(name, requirement)
            design_spec.setdefault(side or "inputs", []).append(
                entry or {"name": name, "dtype": [], "shape": [],
                          "format": "ND", "param_type": "REQUIRED"})
            filled += 1
        design_spec["attrs"] = keep_attrs
        moved = [m for m in moved if m.split("/", 1)[-1] not in auth_tensors]
        if restored or filled:
            from ascendc_devkit.infra.logger import Logger
            Logger.warn(
                f"[integrate] reconciled design_spec IO to golden-signature "
                f"authority (restored {len(restored)} misrouted tensor(s) from "
                f"attrs, filled {filled} missing): {sorted(auth_tensors)}")
    return moved


def _reconcile_shape_ranks(design_spec: dict, requirement) -> list[str]:
    """P121 S2: integrate producer self-check — design_spec IO ``shape`` rank 须与
    ``requirement``（需求描述权威的 IO 契约）一致。mid-chain LLM 漂移（general-design/
    tiling 重排）致 rank 不符 → 以 requirement 为准**确定性**修正（就地）+ 返回修正项
    供 caller warn。§2.9 producer 自检（非下游门）：发现即修到权威源，不 halt/loopback。

    只修 name 匹配项的 rank（``len(shape)`` 不符）；未匹配（命名漂移）/ requirement 缺失
    不动。内部 tiling reshape 在 tiling_results 不在 design_spec.inputs，故对齐 IO rank
    正确（advance_step_v2 真根因：design_spec input_tokens rank 2 vs requirement 1D）。"""
    if requirement is None:
        return []
    op_spec = getattr(requirement, "op_spec", None)
    if op_spec is None:
        return []
    auth: dict[str, list] = {}
    for ts in list(getattr(op_spec, "inputs", [])) + list(getattr(op_spec, "outputs", [])):
        name = getattr(ts, "name", None)
        shape = getattr(ts, "shape", None)
        if name and isinstance(shape, list):
            auth[name] = shape
    if not auth:
        return []
    fixed: list[str] = []
    for side in ("inputs", "outputs"):
        items = design_spec.get(side)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            ds_shape = item.get("shape")
            if name not in auth or not isinstance(ds_shape, list):
                continue
            req_shape = auth[name]
            if len(ds_shape) != len(req_shape):
                item["shape"] = list(req_shape)  # 以 requirement（需求描述权威）为准
                fixed.append(f"{side}/{name}: rank {len(ds_shape)}→{len(req_shape)}")
    return fixed


# _load_authoritative_requirement is imported from orchestration.design_artifacts
# (§2.5 single pathway — codegen + review gate share the same reach-back).


def _reconcile_param_types(design_spec: dict, req: dict) -> list[str]:
    """P123 S2: design_spec IO ``param_type`` producer self-check (§2.9) — reconcile
    to the authoritative requirement by name.

    ``param_type`` is a semantic contract fact (REQUIRED/OPTIONAL/DYNAMIC) sourced
    from the requirement (proto schema). Mid-chain LLM drift downgrades e.g.
    ``DYNAMIC``→``REQUIRED``. ``DYNAMIC`` is structural — it drives the codegen op
    signature (``Tensor[]`` variadic) and docgen's OpDef ``.ParamType(DYNAMIC)``,
    both of which read design_spec — so keeping design_spec's param_type faithful
    to the requirement prevents a wrong (non-variadic) signature downstream.

    Scope note: this guards **design_spec** only. The precision harness does NOT
    read design_spec — it reads ``requirement.op_spec`` — so the harness's own
    DYNAMIC handling is made correct at the source by the §1.10 ``_route`` fix
    (which keeps DYNAMIC inputs in ``op_spec.inputs``), NOT by this reconcile.
    This function's value is purely design_spec fidelity for codegen/docgen.

    Name-matched items are reconciled directly. When the design agent *renamed*
    an input instead of dropping it (e.g. ``x1``→``x``), the name match misses
    and a structural param_type (DYNAMIC/OPTIONAL — the kinds that change the
    generated signature) would silently stay wrong. #2 fix: detect those
    unmatched structural requirement entries and
      · when the side's design_spec / requirement counts are EQUAL, positionally
        restore the structural param_type onto the renamed item (same-index
        semantics the harness uses), recording it as a ``~pos`` fix;
      · when counts differ (can't safely align), emit a loud warning instead of
        guessing (§1.10 no mechanism-proxy alignment, §1.3 surface the drift).

    Returns fixed ``"<side>/<name>: X→Y"`` (name match) and
    ``"<side>/<old>~pos[i]: X→Y"`` (positional rename restore).
    """
    if not isinstance(req, dict):
        return []
    _STRUCTURAL = {"DYNAMIC", "OPTIONAL"}
    fixed: list[str] = []
    for side in ("inputs", "outputs"):
        req_items = [e for e in (req.get(side) or []) if isinstance(e, dict)]
        auth = {e["name"]: e["param_type"] for e in req_items
                if e.get("name") and e.get("param_type")}
        items = design_spec.get(side)
        if not isinstance(items, list):
            continue
        ds_items = [it for it in items if isinstance(it, dict)]
        ds_names = {it.get("name") for it in ds_items}
        # Pass 1 — name match (authoritative, unambiguous).
        for item in ds_items:
            name = item.get("name")
            want = auth.get(name)
            if want and item.get("param_type") != want:
                old = item.get("param_type")
                item["param_type"] = want
                fixed.append(f"{side}/{name}: {old}→{want}")
        # Pass 2 — rename detection: requirement entries with a structural
        # param_type whose name never appeared in design_spec.
        renamed = [e for e in req_items
                   if e.get("name") not in ds_names
                   and str(e.get("param_type", "")).upper() in _STRUCTURAL]
        if not renamed:
            continue
        from ascendc_devkit.infra.logger import Logger
        if len(ds_items) == len(req_items):
            # Same arity → positional alignment is meaningful. Restore the
            # structural param_type onto the same-index design_spec item when it
            # currently disagrees (only the renamed positions differ).
            for i, (it, e) in enumerate(zip(ds_items, req_items)):
                want = e.get("param_type")
                if (want and str(want).upper() in _STRUCTURAL
                        and it.get("name") != e.get("name")
                        and it.get("param_type") != want):
                    old = it.get("param_type")
                    it["param_type"] = want
                    fixed.append(f"{side}/{it.get('name')}~pos[{i}]: {old}→{want}")
        else:
            Logger.warn(
                f"design_spec {side} appears to have renamed authoritative "
                f"input(s) with structural param_type "
                f"{[e.get('name') for e in renamed]} but arity differs "
                f"(design={len(ds_items)} vs requirement={len(req_items)}); "
                f"cannot safely align by position — docgen/cannbench signature "
                f"may be wrong. Keep requirement input names in design_spec.")
    return fixed


def _reconcile_emptied_outputs(design_spec: dict, req: dict) -> list[str]:
    """design_spec ``outputs`` 清空恢复（§2.9 producer 自检 / §1.2 last-resort 兜底）。

    design agent（integrate）产 design_spec 时会把跟 tiling 无关的 ``outputs`` 漏写
    成空（中链漂移，mid-chain LLM drift）——两种形态：
      · in_place：alias outputs（与 input 同名的 read_write 状态张量）被挪进非契约
        字段 ``in_place_outputs``，契约 ``outputs`` 被清空（advance_step_v2 案例）。
      · out_of_place：outputs 跟 tiling 无关、agent 直接漏写为 ``[]``（foreach_norm
        案例）。out_of_place 输出是独立新张量、无同名 input 可镜像。
    两种都让 codegen.validate_inputs 拒 ``outputs`` 空。requirement.json（§1.13 权威；
    §1.3 已校 mutation_mode 与同名 input-output 自洽）→ 回填 design_spec.outputs：
    alias output（有同名 input）用该 input 的 shape/dtype 补全；out_of_place 输出
    原样取 req 声明（无同名 input → 不镜像，保持 requirement 规格）。
    触发条件：``outputs`` 空/缺 且 ``req.outputs`` 非空；已非空不动（勿覆盖正确产物）。
    不限 mutation_mode —— in_place / out_of_place 同属「agent 清空 outputs」一类
    （§1.2 同类新情况自动正确归位，非各打补丁）。Returns 回填的 output 名（空=未触发）。
    """
    if not isinstance(req, dict):
        return []
    outs = design_spec.get("outputs")
    if isinstance(outs, list) and outs:
        return []  # already populated — don't clobber a correct product
    req_outs = req.get("outputs") or []
    if not isinstance(req_outs, list) or not req_outs:
        return []
    restored = []
    in_by_name: dict[str, dict] = {}
    for i in design_spec.get("inputs") or []:
        if isinstance(i, dict) and i.get("name"):
            in_by_name[i["name"]] = i
    for o in req_outs:
        if not isinstance(o, dict):
            continue
        entry = dict(o)
        name = entry.get("name")
        # alias output is the same tensor as its input → mirror shape/dtype
        src = in_by_name.get(name) if name else None
        if src is not None:
            if not isinstance(entry.get("shape"), list):
                entry["shape"] = list(src.get("shape") or [])
            if not entry.get("dtype"):
                entry["dtype"] = src.get("dtype")
        restored.append(entry)
    design_spec["outputs"] = restored
    return [e.get("name", "?") for e in restored]


_REAL_SOCS: frozenset[str] = frozenset(
    to_soc_version(c) for c in CHIP_GENERATIONS)   # §1.9 single translation source


def _opdef_code_region(text: str) -> str:
    """Concatenate every fenced code block in *text* (the §2.3 OpDef lives in a
    ```cpp fence per doc_template_v2.0.md). Scoping the check to rendered code —
    not the whole doc — avoids false-positives on prose and is the principled
    answer to 'why scan the whole doc': we only opine on code. Empty ⇒ no code
    rendered ⇒ nothing for this hallucination backstop to validate (a wholly
    missing §2.3 is the agent self-check's concern, not this gate's)."""
    import re
    return "\n".join(re.findall(r"```[^\n]*\n(.*?)```", text, re.DOTALL))


def _opdef_missing_canonical_anchors(code: str,
                                     design_spec: dict | None) -> list[str]:
    """Positive-only: the canonical-OpDef anchors *code* must contain but lacks
    (empty ⇒ canonical). The placeholder-soc bug (<SOC_VERSION_…>) is caught
    POSITIVELY — a real soc_version literal (§1.9 source) must be present.

    Per-name anchors are judged by BUSINESS SEMANTICS (§1.10), not by which list
    a param sits in: a scalar param (``is_scalar_entry`` — in inputs or in the
    ``attrs`` list/dict) must render ``Attr("<name>")``; a tensor input/output
    must render ``Input("<name>")``/``Output("<name>")``. This is what makes a
    correctly-rendered ``Attr("epsilon")`` pass instead of being false-halted as
    'missing Input("epsilon")' (the 51d915 regression)."""
    missing: list[str] = []
    for anchor in ("OP_ADD(", ".ParamType(", ".DataType(", "AddConfig("):
        if anchor not in code:
            missing.append(anchor)
    spec = design_spec or {}
    _ds_input_names = {i.get("name") for i in spec.get("inputs") or []
                       if isinstance(i, dict) and i.get("name")}
    for item in spec.get("inputs") or []:
        name = item.get("name") if isinstance(item, dict) else None
        if not name:
            continue
        kind = "Attr" if is_scalar_entry(item, group="inputs",
                                         input_names=_ds_input_names) else "Input"
        if f'{kind}("{name}")' not in code:
            missing.append(f'{kind}("{name}")')
    for item in spec.get("outputs") or []:
        name = item.get("name") if isinstance(item, dict) else None
        if name and f'Output("{name}")' not in code:
            missing.append(f'Output("{name}")')
    # attrs (list or dict form, per recipe 194) → Attr("<name>")
    attrs_raw = spec.get("attrs")
    if isinstance(attrs_raw, dict):
        attr_names = list(attrs_raw.keys())
    elif isinstance(attrs_raw, list):
        attr_names = [a.get("name") for a in attrs_raw
                      if isinstance(a, dict) and a.get("name")]
    else:
        attr_names = []
    for name in attr_names:
        if f'Attr("{name}")' not in code:
            missing.append(f'Attr("{name}")')
    if not any(soc in code for soc in _REAL_SOCS):
        missing.append("<real soc_version literal>")
    return missing



# —— tiling fork-join branch segments (P5 fleshes out template binding) ——

# 四段 schema 定义：子 skill → (schema 文件名, segment_key, required)。
# vf-design 是 A5 Regbase 专属：A2/A3 门面 skill 不产出 tiling_vf_design.json，
# 故标 required=False（缺它不报错）。
_TILING_SEGMENTS = [
    ("ascendc-op-tiling-split", "tiling_split.json", "split", True),
    ("ascendc-op-tiling-vf-design", "tiling_vf_design.json", "vf_design", False),
    ("ascendc-op-tiling-buffer-kernel", "tiling_buffer_kernel.json", "buffer_kernel", True),
    ("ascendc-op-tiling-precision-perf", "tiling_precision_perf.json", "precision_perf", True),
]


class TilingStage(_DesignSubstage):
    """单模板完整 tiling（step-2b §6.2 合并版，选 B 编排层合并）。

    一个 agent 会话串行 tail-call 四个子 skill（split/vf-design/buffer-kernel/
    precision-perf），产出四份 schema 文件。合并收益（§1.14/§2.9）：跨段不一致
    （buffer-kernel vs precision-perf）构造性消解——同一 agent 一个上下文里写完整
    tiling，不可能自相矛盾到需要跨边界修。vf-design 的 A5-only 跳过由门面 skill
    内判（读芯片编程模型），不再由框架段级 skip_reason 承担。

    template 是 template_division.templates 的 per-template dict；每模板一个
    TilingStage（ForkJoin 分支），读上游全局产物 + 自己的模板名，写
    tiling_results[{template}][{split,vf_design,buffer_kernel,precision_perf}]。
    """

    name = "tiling"
    description = "单模板完整 tiling（split→vf-design→buffer-kernel→precision-perf）"
    agent_name = "ascendc-design-generator"
    prompt_intro = ("对单模板完成完整 tiling 推导：核间/核内切分 → VF 编排（A5）→ "
                    "Buffer/Kernel → 精度/性能。")

    def __init__(self, template=None):
        self.template = template or {}

    @property
    def _template_name(self) -> str:
        t = self.template
        if isinstance(t, dict):
            return str(t.get("name", ""))
        return str(t)

    def input_contract(self) -> StageIOContract:
        return StageIOContract(requires=["template_division"])

    def output_contract(self) -> StageIOContract:
        return StageIOContract(provides=["tiling_results"])

    def artifact_contract(self) -> ArtifactContract:
        """加载四个子 skill 的 schema（vf_design 标 required=False）。"""
        from dataclasses import replace as _replace
        from ascendc_devkit.adapters.schema.loader import SchemaLoader
        specs = []
        for sub_skill, fname, _seg, required in _TILING_SEGMENTS:
            spec = SchemaLoader.load_spec_from_skill(sub_skill, fname)
            if not required:
                spec = _replace(spec, required=False)
            specs.append(spec)
        return ArtifactContract(artifacts=specs)

    def _context(self, state: "State") -> dict:
        ctx = super()._context(state)
        ctx["template"] = self.template
        return ctx

    def _working_dir(self, state: "State"):
        if not state._workspace:
            return None
        return (state._workspace.artifacts / "design" / "tiling"
                / self._template_name)

    def _branch_label(self) -> str:
        return self._template_name

    def _entry_kind_filename(self) -> str | None:
        # 多产物：以首个必需段（split）的产物文件判断增量 vs 生成。
        return "tiling_split.json"

    def _upstream_inputs(self, state: "State") -> dict:
        inputs = {
            "general_design": getattr(state, "general_design", None),
            "template_division": getattr(state, "template_division", None),
        }
        this_template = (getattr(state, "tiling_results", None) or {}).get(
            self._template_name, {})
        if this_template:
            inputs["tiling_results_current_template"] = this_template
        return inputs

    def _build_prompt(self, state, iteration: int) -> str:
        intro = (f"{self.prompt_intro}\n对单模板 `{self._template_name}` 执行，"
                 f"代入上游锁定决策，勿读其他模板。")
        sections = [f"## 任务\n{intro}"]
        if self.entry_kind(state) == "modify":
            sections.append(
                "## 增量修改上下文\n"
                "工作目录中已存在上一轮的本产物，请基于已有产物增量修改："
                "优先检查现有文件，只补充或修正缺失/错误的部分，"
                "勿从零重复扫描。")
        op = self._operator_section(state)
        if op:
            sections.append(op)
        inputs = self._inputs_section(state)
        if inputs:
            sections.append(inputs)
        skill = self._skill_section()
        if skill:
            sections.append(skill)
        sections += [
            f"## 当前模板\n```json\n{json.dumps(self.template, ensure_ascii=False)}\n```",
            self.artifact_contract().render_output_requirements()]
        sections.append(self._output_boundary(state))
        fb_section = self._feedback_section(state)
        if fb_section:
            sections.append(fb_section)
        if state.user_feedback:
            sections.append(f"## 用户反馈\n{state.user_feedback}")
        prev = self._previous_decision_section(state)
        if prev:
            sections.append(prev)
        sections.append(self._decision_log_output_section())
        return "\n\n".join(s for s in sections if s)

    def transition(self, state, result):
        # vf_design 为 optional：A2/A3 门面 skill 不产出，缺它不报错。
        if not result.get("_working_dir"):
            result = {**result, "_working_dir": self._working_dir(state)}
        required = [f for _s, f, _seg, req in _TILING_SEGMENTS if req]
        optional = [f for _s, f, _seg, req in _TILING_SEGMENTS if not req]
        raw, err_state = self._read_disk_artifacts(state, result, required, optional)
        if raw is None:
            return err_state
        parsed, errors = self.artifact_contract().parse(raw)
        if errors:
            return self._error(state, "; ".join(errors),
                               error_type="schema_violation")
        # P10-F2：物理布局契约在位检查（机械兜底，§2.9②——反馈经 user_feedback
        # 被同 agent 确定性消费）。只查在位性，不查内容正确性（内容归设计自检 +
        # skill 物理层展开边界判据）。合法形态集（封闭，§1.12 结构断言非错误枚举）：
        # workspace ∈ {缺省, null, 'none', object}——null/缺省=显式/隐式未使用，
        # 'none'=实践中的等义写法（语义无歧义，容忍）；object 则须含非空字符串数组
        # layout_contract；其余形态（裸数字/list/任意字符串）=载体畸形，同样打回
        # （§1.2 可诊断：不静默推迟到 codegen 期 LLM 自报）。
        # error_type=incomplete_output：R1 语义「产物已交付但契约未满足、喂字段
        # 提示即可确定性纠正」→ artifact-retry 桶（独立预算、不烧 iteration）。
        ws = ((parsed.get("tiling_buffer_kernel") or {})
              .get("buffer_kernel") or {}).get("workspace")
        if ws is None or ws == "none":
            pass  # 无契约无义务（缺省/null/'none'）
        elif not isinstance(ws, dict):
            msg = ("tiling: buffer_kernel.workspace 形态非 object——须为 "
                   "{user_workspace_bytes, rationale, layout_contract} 对象；"
                   "不用 GM workspace 则省略该字段。修正形态后重交本段产物。")
            from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
            return state.with_updates(
                last_error=ErrorFeedback(stage_name=self.name,
                                         error_type="incomplete_output",
                                         message=msg),
                user_feedback=msg)
        else:
            lc = ws.get("layout_contract")
            if not (isinstance(lc, list) and lc
                    and all(isinstance(e, str) and e.strip() for e in lc)):
                msg = ("tiling: buffer_kernel.workspace 契约在位而 layout_contract "
                       "缺失/为空——GM workspace 布局契约须随 workspace 交付"
                       "（平面字节公式与 stride / 跨核 base 偏移 / 发布-汇聚地址恒等式，"
                       "字符串数组形态见 skill 物理层展开边界），补全后重交本段产物。")
                from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
                return state.with_updates(
                    last_error=ErrorFeedback(stage_name=self.name,
                                             error_type="incomplete_output",
                                             message=msg),
                    user_feedback=msg)
        name = self._template_name
        tmpl_entry = dict((state.tiling_results or {}).get(name, {}))
        for _s, fname, seg_key, _req in _TILING_SEGMENTS:
            spec_name = (fname[:-len(".json")]
                         if fname.endswith(".json") else fname)
            payload = parsed.get(spec_name)
            if payload is not None:
                tmpl_entry[seg_key] = payload.get(seg_key)
        logs = self._capture_decision_log(state, raw)
        # F6：收尾清错统一归 runner（delivered-success 归一化）；本 return 不再
        # 手工清 last_error。
        return state.with_updates(
            tiling_results={name: tmpl_entry}, decision_logs=logs,
            user_feedback="")

    def is_satisfied(self, state) -> bool:
        """provides=['tiling_results'] 是聚合字段，需按本模板的必需段切片判定。

        split + buffer_kernel + precision_perf 必需；vf_design 仅 A5 需要（A2/A3
        门面 skill 不产，缺它不判失败）。last_error 指向本 stage 名 → 不满足
        （保留重试，让 location hint 送达下一 spawn）。"""
        err = getattr(state, "last_error", None)
        if err is not None and getattr(err, "stage_name", None) == self.name:
            return False
        return self._own_template_segments_present(state)

    def outputs_delivered(self, state) -> bool:
        """M14（review 整改）：聚合字段的「已交付」降粒度判定。

        provides=['tiling_results'] 是按模板聚合的 dict——批 RESUME/精确
        loopback 重跑剩余模板时，base 已有兄弟模板使 dict 非 None，裸 has_all
        恒真会让 runner 的错误归一化/artifact-retry 预算/终态分类静默失效
        （错误被清 → 独立预算不生效 → 下轮 last_error=None → resume 也不
        触发）。交付语义 = **本模板**的必需段在位。"""
        return self._own_template_segments_present(state)

    def _own_template_segments_present(self, state) -> bool:
        seg = (getattr(state, "tiling_results", None) or {}).get(
            self._template_name, {})
        for _s, _f, seg_key, req in _TILING_SEGMENTS:
            if req and seg.get(seg_key) is None:
                return False
        return True
