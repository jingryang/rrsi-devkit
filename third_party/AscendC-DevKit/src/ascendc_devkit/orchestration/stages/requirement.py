"""L3 Orchestration — Requirement Stage: analyze design doc, extract unclear items."""

from __future__ import annotations

import json
from ascendc_devkit.capabilities.agent._shared import is_infra_error_type
from ascendc_devkit.capabilities.agent.backend import AgentResult
from dataclasses import replace as dc_replace
from pathlib import Path
from typing import TYPE_CHECKING

from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.domain.artifact import ArtifactContract
from ascendc_devkit.domain.requirement import (
    Requirement, UnclearItem, Constraint, read_proto_precision, read_proto_schema,
    read_proto_tensorlist_inputs,
)
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.orchestration.registry import register_stage
from ascendc_devkit.orchestration.kernel.action import SpawnAgent, Action, AskUserQuestion, Option
from ascendc_devkit.orchestration.skill_config import skill_allowlist

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State


@register_stage
class RequirementStage(Stage):
    name = "requirement"
    description = "Analyze design document, extract requirements and unclear items"
    default_max_iterations = 10

    def input_contract(self) -> StageIOContract:
        return StageIOContract(
            # requirement_path is dual-purpose: IO input AND dispatcher preflight
            # signal for "must be user-provided". It is mandatory but acquired by
            # mode — interactive prompts the user when the CLI omitted it,
            # non-interactive errors out. Keeping it in `requires` is what gives
            # preflight its enforcement hook; do not move it to optional.
            #
            # golden_path (P121): req-analysis 读 golden.py 源码做 shape_equiv
            # 自检（input rank 从张量索引/view 推断），是 shape 权威源。声明在
            # requires = 契约诚实 + early validation（§1.3：golden 缺失 preflight
            # 早炸，而非静默跑→瞎猜 shape）。零影响：三个含 requirement 的 workflow
            # 都挂 general-design（早已 requires golden_path），故 golden_path 本
            # 就在 dispatcher candidates、triple 早触发、batch 早提供完整三件套——
            # 此处加 requires 不改 candidates、不新触发 triple（见 plan scope 论证）。
            requires=["requirement_path", "mode", "golden_path"],
            optional=["op_identity", "reference_code", "design_doc_path"],
        )

    def output_contract(self) -> StageIOContract:
        return StageIOContract(
            provides=["requirement", "unclear_items", "requirement_clarified"],
        )

    def is_satisfied(self, state: State) -> bool:
        """The stage owns requirement completeness: it is only "done" once every
        unclear item is resolved. While items remain pending, the runner keeps
        iterating (re-clarifying) instead of emitting a half-specified spec for
        DesignStage to reject. Non-interactive `blocking` items are handled in
        transition (hard error); `choice` items are auto-resolved there, so by
        the time we get here requirement_clarified reflects the real state.
        """
        return bool(state.requirement_clarified)

    def artifact_contract(self) -> ArtifactContract:
        from ascendc_devkit.adapters.schema.loader import SchemaLoader
        return SchemaLoader.load_contract_from_skill(
            "ascendc-op-req-analysis", ["requirement.json"])

    def actions(self, state: State, iteration: int = 1) -> list[Action]:
        wd = (state._workspace.artifacts / "requirement"
              if state._workspace else None)
        if wd is not None:
            self._materialize_inputs(state, wd)
        prompt = self._build_analysis_prompt(state, iteration)

        context = {
            "mode": state.mode,
        }

        if state.reference_code:
            context["reference_code"] = state.reference_code

        if state.op_identity:
            context["op_identity"] = {
                "op_dir": str(state.op_identity.op_dir),
                "files": {k: str(v) for k, v in state.op_identity.files.items()},
            }

        # If there are unclear items from previous iteration, include them
        if state.unclear_items:
            context["unclear_items"] = [
                {"question": u.question, "resolution": u.resolution}
                for u in state.unclear_items
            ]

        actions: list[Action] = [
            SpawnAgent(
                agent_name="requirement-analyst",
                prompt=prompt,
                context=context,
                skills=skill_allowlist("ascendc-op-req-analysis"),
                primary_skill="ascendc-op-req-analysis",  # D2: backend-rendered
                working_dir=wd,
            )
        ]

        # Interactive review after each round's agent output. The review is an
        # interactive-only feature: it runs AFTER SpawnAgent in the action list,
        # so the user reviews every round's output (no first-round skip). In
        # non-interactive mode correctness is governed by the severity policy in
        # transition (blocking→error, choice→default), so no review is appended
        # and the prior behavior (auto-proceed) is preserved exactly.
        if not state.non_interactive:
            unclear_count = len([u for u in (state.unclear_items or [])
                                 if not getattr(u, "resolution", None)])
            actions.append(
                AskUserQuestion(
                    question=(
                        f"需求分析阶段 (第 {iteration} 轮) 已产出需求规格，请审查：\n"
                        f"  算子: {state.op_name or '（见 requirement.json）'}\n"
                        f"  上一轮待澄清项: {unclear_count} 项\n"
                        f"  选择 approve 进入设计，revise 补充意见后重新分析"
                    ),
                    options=[
                        Option("approve", "✅ 通过，进入下一阶段"),
                        Option("revise", "✏️ 需要修改（将提示输入反馈）"),
                        Option("abort", "❌ 放弃"),
                    ],
                    default_index=0,
                )
            )

        return actions

    def _materialize_inputs(self, state: State, working_dir: Path) -> None:
        """Write the requirement document + reference code as CWD files (F2).

        First principle: the skill reads its inputs from files in the working
        dir, not from prompt-injected content. The requirement document is the
        primary input; reference code is supplementary.
        """
        from ascendc_devkit.infra.logger import Logger  # noqa: PLC0415 (local, mirrors L549/L743)
        wd = Path(working_dir) if not isinstance(working_dir, Path) else working_dir
        wd.mkdir(parents=True, exist_ok=True)
        # Primary input: the user's requirement document
        if state.requirement_path and state.requirement_path.exists():
            (wd / "requirement_doc.md").write_text(
                state.requirement_path.read_text(), encoding="utf-8")
        # Auxiliary requirement material (--requirement-aux, e.g. a cann-bench
        # task's desc.md). Materialized name-preserving like ref_*; disambiguate
        # on basename collision with an existing CWD file by prefixing ``aux_``.
        # Purely supplementary reading for the agent — never a deterministic
        # parse source (schema/precision/tensorlist still read requirement_path).
        if state.requirement_aux_paths:
            seen = set()
            for p in state.requirement_aux_paths:
                p = Path(p)
                if not p.exists():
                    Logger.warn(f"requirement-aux 路径不存在，跳过: {p}")
                    continue
                dest_name = p.name
                if dest_name in seen or (wd / dest_name).exists():
                    dest_name = f"aux_{dest_name}"
                seen.add(dest_name)
                (wd / dest_name).write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
        # Supplementary: reference code (one file per path, name-preserving)
        if state.reference_code:
            for path, content in state.reference_code.items():
                # Use the filename component only, avoiding directory structure
                dest = wd / f"ref_{Path(path).name}"
                dest.write_text(content, encoding="utf-8")
        # P121: golden.py — shape 权威源。req-analysis 读它做 shape_equiv 自检
        # （从张量索引/view 推断 input rank）。镜像 reference_code 文件拷贝模式
        # （单 Path，非 dict）。preflight 已保证 golden_path 非 None（requires），
        # exists() 为防御。SKILL 早要求 agent 读 golden.py（math-equiv），此处补
        # 工程层物化——修 advance_step_v2「agent 被告知读 golden 却找不到」真根因。
        if state.golden_path and state.golden_path.exists():
            (wd / "golden.py").write_text(
                state.golden_path.read_text(), encoding="utf-8")

    def _build_analysis_prompt(self, state: State, iteration: int) -> str:
        sections = []

        # D2: skill delivery is NOT baked into the prompt body — that is a
        # claude-only slash mechanism (opencode does not expand `/<skill>`). The
        # assigned skill travels via SpawnAgent.primary_skill and is rendered
        # natively at the backend boundary (see actions()).
        if state.mode == "incremental":
            sections.append("## 模式：增量开发\n对已有算子进行变更，请以变更需求为重点分析。")

        # F2: requirement document is now materialized as a CWD file (see
        # _materialize_inputs). The prompt only points at it — no content
        # injection. Preserves the 10,000-char size guard via the file itself.
        if state.requirement_path and state.requirement_path.exists():
            sections.append(
                "## 需求文档\n当前工作目录已放置 `requirement_doc.md`——"
                "这是你分析的唯一需求来源。从该文件读取需求内容。")

        # Auxiliary requirement material (--requirement-aux, e.g. a cann-bench
        # task's desc.md). Materialized name-preserving by _materialize_inputs;
        # prompt only lists what's available — the agent reads them from CWD.
        # Supplementary to requirement_doc.md (never a second authority — golden
        # remains the behavioral truth, §1.13).
        if state.requirement_aux_paths:
            aux_lines = []
            for p in state.requirement_aux_paths:
                if Path(p).exists():
                    aux_lines.append(f"- `{Path(p).name}`（来源: {p}）")
            if aux_lines:
                sections.append(
                    "## 附加需求材料（当前工作目录）\n"
                    "主需求文档之外，另提供以下补充需求材料，请一并阅读以辅助需求理解"
                    "（主需求仍以 `requirement_doc.md` 为准；与 golden 冲突时 golden 为唯一权威）：\n"
                    + "\n".join(aux_lines))

        if state.mode == "incremental" and state.op_identity:
            sections.append(f"## 已有算子信息\n算子: {state.op_name}\n代码目录: {state.op_identity.op_dir}")
            if state.op_identity.files:
                sections.append(f"已有文件: {', '.join(state.op_identity.files.keys())}")

        # F2: reference code materialized as ref_*.{cpp,h,...} files in CWD.
        # The prompt lists what's available; the agent reads them from CWD.
        if state.reference_code:
            sections.append("## 参考/已有算子代码（当前工作目录）")
            for path in state.reference_code:
                sections.append(f"- `ref_{Path(path).name}`（来源: {path}）")

        # P121: golden.py materialized as CWD file — shape 权威源。点名让 agent
        # 读它做 shape_equiv 自检（SKILL.md golden 段既有 math-equiv，此处补 shape
        # rank 推断）。镜像 requirement_doc.md 的点名写法（不注入内容）。
        if state.golden_path and state.golden_path.exists():
            sections.append(
                "## Golden 参考实现（当前工作目录）\n"
                "当前工作目录已放置 `golden.py`——算子行为的**唯一权威真值源**（math 语义 + "
                "shape rank 均以 golden 为准，§1.13）。从该文件读取：① **shape rank 权威**：从张量"
                "索引/`.shape`/`view` 操作推断 input rank（如 `x[:n]`→1D；`view(-1,k)` 是内部 "
                "reshape 不改 input rank）——**golden 是 shape 权威、需求描述作辅助印证**：以 golden "
                "推出的 rank 为准，需求描述用于互相印证；仅当 golden 本身语义模糊判断不了时才用 "
                "resolve_ambiguity 问用户（默认以 golden 为准），不用含糊的需求描述压过 golden 的明确指示。"
                "② math 等价性（既有 math-equiv-golden 自检）。")

        if iteration > 1 and state.unclear_items:
            sections.append("## 待澄清项（来自上一轮）")
            for item in state.unclear_items:
                sections.append(f"- Q: {item.question}\n  Resolution: {item.resolution or '待确认'}")

        # Inject user feedback from interactive review
        if state.user_feedback:
            sections.append(
                f"## 用户反馈\n以下是用户针对上一版本需求分析的修改意见：\n\n"
                f"{state.user_feedback}\n\n"
                f"请根据以上反馈重新分析需求文档。"
            )

        # design-gate loopback feedback (review design_input_invalid → requirement
        # via escalate-bubble): the gate's blocking_issues on what it rejected, so
        # requirement re-runs informed, not blind. Shared renderer with design
        # substage prompts (render_loopback_feedback_section).
        from ascendc_devkit.orchestration.issue_render import render_loopback_feedback_section
        fb_section = render_loopback_feedback_section(state)
        if fb_section:
            sections.append(fb_section)

        sections.append(
            self.artifact_contract().render_output_requirements(
                intro="请分析需求文档，输出 JSON 格式的需求规格，"
                      "并使用 Bash 或 Edit 工具写入当前工作目录："
            )
        )

        return "\n\n".join(sections)

    def transition(self, state: State, result: dict) -> State:
        decision = result.get("decision", "")

        # —— User chose to abort ——
        if decision == "abort":
            from ascendc_devkit.domain.exceptions import DecisionPendingError
            raise DecisionPendingError(
                question="User aborted requirement stage",
                options=["resume"],
                workspace_dir=str(state._workspace.dir) if state._workspace else "",
            )

        # —— User requested revision: read feedback, don't commit artifacts ——
        if decision == "revise":
            try:
                feedback = input(
                    "请输入修改意见（Enter 提交，Ctrl+C 跳过）: "
                ).strip()
            except (EOFError, KeyboardInterrupt):
                feedback = ""
            return state.with_updates(
                user_feedback=feedback,
                requirement=None,
                requirement_clarified=False,
            )

        # —— Default (approve): process agent artifacts normally ——
        agent_result = result.get("agent_result")

        if agent_result is None:
            return state.with_updates(requirement_clarified=False, user_feedback="")

        # 孤儿就地恢复（20260821 F3 全局收口）：requirement 走 agent-dict 契约
        # （非盘读 locate），dict 为空时 agent 可能是把 requirement.json 写到了
        # wd 之外——transcript 证据 → 搬回 wd → 从盘读回并注入 artifacts，走同
        # 一契约解析。拒搬/无证据 → 行为=收口前（落下方 agent-failed 分支）。
        if not agent_result.artifacts:
            wd = (state._workspace.artifacts / "requirement"
                  if state._workspace else None)
            transcript = getattr(agent_result, "transcript", None)
            if wd is not None and transcript is not None:
                from ascendc_devkit.orchestration.artifact_recovery import (
                    recover_orphan_artifact)
                if recover_orphan_artifact(
                        transcript, "requirement.json", wd, state, "requirement"):
                    req_file = wd / "requirement.json"
                    if req_file.is_file():
                        try:
                            import json as _json
                            agent_result = AgentResult(
                                agent_name=agent_result.agent_name,
                                status="ok",
                                artifacts={
                                    "requirement.json":
                                        req_file.read_text(encoding="utf-8")},
                                transcript=transcript)
                        except OSError:
                            pass  # 读失败 → 落回 agent-failed 分支，不炸

        if agent_result.artifacts:
            # Schema-validated parse: requirement output must conform to
            # requirement.json (required_keys: op_name, inputs, outputs), the
            # same contract the SKILL.md carries — single source, no drift.
            parsed, errors = self.artifact_contract().parse(agent_result.artifacts)
            # §1.3 加载期自洽校验：mutation_mode ⇔ 同名 input-output 对
            # （in_place 算子须有同名 read_write 状态张量）。不符→schema_violation 重试。
            errors.extend(self._validate_mutation_mode_consistency(parsed.get("requirement")))
            # P121: golden_alignment 杜绝 "pending" 流过（advance_step_v2 真根因之一）。
            # required_keys 兜 presence；此处校 status ∈ {pass,diff}（拒 pending/畸形）。
            errors.extend(self._validate_golden_alignment(parsed.get("requirement")))
            if errors:
                # Schema violation → record error, let the runner retry.
                from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
                return state.with_updates(
                    last_error=ErrorFeedback(
                        stage_name="requirement",
                        error_type="schema_violation",
                        message="; ".join(errors),
                    ),
                    requirement_clarified=False,
                    user_feedback="",
                )
            req_data = parsed.get("requirement")
            if req_data is not None:
                # Agent produces "op_name" but OperatorSpec.from_dict expects "name"
                if "op_name" in req_data and "name" not in req_data:
                    req_data["name"] = req_data.pop("op_name")
                # A 方案主修复（precision-tensorlist-harness-contract）：确定性派生
                # TensorList 的 is_list + param_type=DYNAMIC。proto.yaml 的
                # ``operator.inputs[].is_list: true`` 与 ``operator.schema`` 签名
                # ``Tensor[]`` 是结构信号（§1.12 不认算子名、§1.13 proto 是接口契约
                # 权威）；requirement 误把 Tensor[] 标 REQUIRED → runner DYNAMIC 闸门
                # 永不触发 → list-of-lists 用例全被 PD-CONTRACT 拒 → upstream halt
                # （foreach 类算子历史根因）。此处确定性派生，不靠 LLM 手写。
                self._derive_tensorlist_param_type(req_data, state.requirement_path)
                # 加载期交叉校验（§1.3）：is_list=true 但 param_type≠DYNAMIC 仍非法。
                # 派生已把 proto 声明的 TensorList 修正为 DYNAMIC，此处兜 agent 手写
                # ``is_list: true`` 却标错 param_type 的残余——契约不一致大声失败。
                errors.extend(self._validate_tensorlist_param_type(req_data))
                # step-105 防线2：attr 类型声明必须在文法上可表达 + 与 golden
                # 用例值结构 cross-check（只拦矛盾不拦细化——L4 红线2）。
                errors.extend(self._validate_attr_type_grammar(req_data, state.requirement_path))
                if errors:
                    from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
                    return state.with_updates(
                        last_error=ErrorFeedback(
                            stage_name="requirement",
                            error_type="schema_violation",
                            message="; ".join(errors),
                        ),
                        requirement_clarified=False,
                        user_feedback="",
                    )
                from ascendc_devkit.domain.operator import OperatorSpec, filter_known_fields
                if isinstance(req_data.get("inputs"), list) and isinstance(req_data.get("outputs"), list):
                    op_spec = OperatorSpec.from_dict(req_data)
                    # P69: agent's requirement.json drops precision_thresholds
                    # (schema is op_name/inputs/outputs only); the proto (state.
                    # requirement_path) is the single source. Re-read it and patch
                    # the recovered thresholds + per-output compare flags onto the
                    # agent-built op_spec (whose inputs/outputs/attrs are richer
                    # than proto's list-dtype form — patch, not rebuild).
                    op_spec = self._attach_proto(op_spec, state.requirement_path)
                    # proto.yaml ``operator.schema`` — plugin 接口 + harness 调用契约的权威
                    # （54/54 proto.yaml 均声明）。优先于 agent 重表达的 op_spec：cannbench_adapt
                    # 对齐基准、codegen C.{plugin} 自检基准都是它，而非 codegen_manifest（二手）。
                    proto_schema = read_proto_schema(state.requirement_path)
                    unclear = [UnclearItem(**filter_known_fields(UnclearItem, u))
                               for u in req_data.get("unclear_items", [])]
                    constraints = [Constraint(**filter_known_fields(Constraint, c))
                                   for c in req_data.get("constraints", [])]
                    # Non-interactive severity policy: blocking-unresolved →
                    # L1: agent skill has been trained to NOT misclassify C API
                    # required-parameters as blocking (see requirement-analyst.md).
                    # L2: if an item still arrives as blocking+unresolved, do NOT
                    # hard-abort. Inject a loopback feedback asking the agent to
                    # re-evaluate — the next iteration will apply the corrected
                    # classification without human intervention. Only a true
                    # underspecification (missing inputs/outputs, unknown semantics)
                    # that the agent re-confirms as blocking on the second pass
                    # will then escalate to PreconditionError.
                    if state.non_interactive:
                        unclear, feedback = self._apply_non_interactive_severity(
                            state, unclear)
                        if feedback:
                            return state.with_updates(
                                user_feedback=feedback,
                                requirement=None,
                                unclear_items=None,
                                requirement_clarified=False,
                            )
                    requirement = Requirement(
                        op_spec=op_spec,
                        design_doc_path=state.requirement_path,
                        constraints=constraints,
                        unclear_items=unclear,
                    )
                    pending = [u for u in unclear if not u.resolution]
                    state = state.with_updates(
                        requirement=requirement,
                        proto_schema=proto_schema,
                        unclear_items=unclear,
                        requirement_clarified=len(pending) == 0,
                        user_feedback="",
                    )
                    # P81 (step-58): design_target_chip authority = CLI > 需求文档
                    # 显式 canonical 字段 > runtime 兜底(dispatch 设)。agent 产的
                    # constraint 不再是 chip 来源(run 20260717-070202-53f685:
                    # requirement-analyst 照搬 schema example A5 凭空产 hardware
                    # constraint,_apply 无条件信它)。设计独立于硬件——A2 机器可做
                    # A5 设计;构建/运行 gate(deploy/verify)才校验 design==runtime。
                    doc_chip = self._read_design_chip_from_doc(state)
                    if doc_chip:
                        state = self._apply_design_target_chip(state, doc_chip)
                    return state

        # Agent failed — store error
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        # P116: propagate error_type="infra" (was: agent_result.status, which
        # drops the infra signal — mirrors codegen.py:1325-1338). The runner-level
        # infra halt uses agent_result.error_type directly (not last_error), but
        # other consumers (own_error display, halt_reason.message, downstream
        # prompts, stage-level guards) read state.last_error.error_type and need
        # the honest class.
        is_infra = is_infra_error_type(agent_result.error_type)
        # F5：干净完成 + 零产物不再有独立 status——error_type 落既有 selffix 类目
        # incomplete_output（可重试语义），message 如实说零产物；crash 类保持
        # status 诊断（partial/fatal），不让 "ok" 字面量泄入 error_type。
        _clean_empty = (agent_result.status == "ok"
                        and not agent_result.artifacts)
        return state.with_updates(
            last_error=ErrorFeedback(
                stage_name="requirement",
                error_type=(agent_result.error_type if is_infra
                            else "incomplete_output" if _clean_empty
                            else agent_result.status),
                message=(
                    "Infrastructure error (bounded retry exhausted): "
                    f"{(agent_result.metrics or {}).get('failure_reason', '')}"
                    if is_infra
                    else (f"Agent {agent_result.agent_name} 干净完成但零产物"
                          f"（未产出 requirement.json）" if _clean_empty
                          else f"Agent {agent_result.agent_name} returned: "
                               f"{agent_result.status}")),
            ),
            requirement_clarified=False,
            user_feedback="",
        )

    def _validate_mutation_mode_consistency(self, req_data: object) -> list[str]:
        """§1.3 加载期校验：mutation_mode 与 inputs/outputs 同名关系自洽。

        in_place ⇔ 存在与 input 同名的 output（read_write 状态张量原地更新）；
        out_of_place ⇔ output 与 input 不同名（独立输出）。
        必填/枚举合法性由 required_keys + schema 负责；此处只管跨字段自洽。
        不符 → 返回 error（并入 parse errors → schema_violation → agent 重试）。
        """
        if not isinstance(req_data, dict):
            return []
        mode = req_data.get("mutation_mode")
        if mode not in ("in_place", "out_of_place"):
            return []  # 必填/枚举合法性交给 required_keys + schema
        inputs = req_data.get("inputs") or []
        outputs = req_data.get("outputs") or []
        input_names = {i.get("name") for i in inputs if isinstance(i, dict)}
        output_names = {o.get("name") for o in outputs if isinstance(o, dict)}
        has_alias = bool(input_names & output_names)
        if mode == "in_place" and not has_alias:
            return ["requirement.json: mutation_mode=in_place 但无与 input 同名的 output"
                    "（in-place 算子须有 read_write 状态张量：某 output.name 须等于某 input.name）"]
        if mode == "out_of_place" and has_alias:
            return ["requirement.json: mutation_mode=out_of_place 但存在与 input 同名的 output"
                    "（out-of-place 算子 output 须与 input 不同名；若实为原地更新改 in_place）"]
        return []

    def _validate_golden_alignment(self, req_data: object) -> list[str]:
        """P121 §1.3 加载期校验：golden_alignment.status ∈ {pass, diff}，禁 "pending"。

        advance_step_v2（9d6e61）真根因之一：agent 产 golden_alignment.status="pending"
        （"未检"）一路流过无人查（schema 无 enum、from_dict 丢弃）→ shape 未对齐
        golden → codegen 硬化错 shape → harness 错配 → EZ1001 halt。

        与 mutation_mode 平行（required_keys 兜 presence + cross-field 校验器兜值）：
        - presence/缺失 → required_keys 兜（parse 报），本方法遇 None 不重复报；
        - 非 dict 畸形值（present 但非对象）→ 报（malformed）；
        - status="pending"（未检）/ 非 pass|diff → 报，强制重试让 agent 真读 CWD 的
          golden.py 做 shape_equiv（推 input rank）+ math_equiv 自检后置 pass。
        真根因是 S1-物化（_materialize_inputs 写 golden.py → agent 能读 → 产 pass，
        pending 自然消失）；本校验器兜"agent 仍产 pending"的残余 + presence 完整契约。
        """
        if not isinstance(req_data, dict):
            return []
        ga = req_data.get("golden_alignment")
        if ga is None:
            return []  # 缺失由 required_keys 兜（parse 报）；不重复报
        if not isinstance(ga, dict):
            return ['requirement.json: golden_alignment 须是对象 '
                    '{status, differences, notes}（present 但非对象=malformed）']
        status = ga.get("status")
        if status == "pending":
            return ['requirement.json: golden_alignment.status="pending"（未实际对照 '
                    "golden.py）——读 CWD 的 golden.py 做 shape_equiv（从张量索引/view "
                    "推 input rank）+ math_equiv 自检后置 pass；golden 判断不了用 "
                    "resolve_ambiguity 问用户"]
        if status not in ("pass", "diff"):
            return [f"requirement.json: golden_alignment.status={status!r} 非法，"
                    "须取 pass|diff（pending=未检，禁止）"]
        return []

    @staticmethod
    def _derive_tensorlist_param_type(req_data: dict, proto_path) -> None:
        """A 方案主修复：proto 结构信号确定性派生 TensorList 的 is_list + param_type。

        proto.yaml 用两个结构信号声明 TensorList 输入（§1.12 不认算子名）：
        ``operator.inputs[].is_list: true`` 与 ``operator.schema`` 签名 ``Tensor[]``。
        requirement 误把 Tensor[] 标 param_type=REQUIRED（应 DYNAMIC）→ runner 的
        DYNAMIC 闸门永不触发 → list-of-lists 用例全被 PD-CONTRACT 拒 → upstream halt。
        此处直接改写 req_data["inputs"]：命中 proto TensorList 的输入补 ``is_list: true``
        并派生 ``param_type=DYNAMIC``（§1.3 留痕 WARN 当 agent 标了非 DYNAMIC 时）。

        幂等、确定性；proto 缺失/未声明 → 不改写（fallback 交给 from_dict 的
        is_list 派生 + runner hint，§1.2 宽容兜底）。
        """
        if not isinstance(req_data, dict):
            return
        tensorlist_names = read_proto_tensorlist_inputs(proto_path)
        if not tensorlist_names:
            return
        inputs = req_data.get("inputs")
        if not isinstance(inputs, list):
            return
        from ascendc_devkit.infra.logger import Logger
        for inp in inputs:
            if not isinstance(inp, dict):
                continue
            name = inp.get("name")
            if name not in tensorlist_names:
                continue
            if inp.get("is_list") is not True:
                inp["is_list"] = True
            if str(inp.get("param_type", "REQUIRED")).upper() != "DYNAMIC":
                old = inp.get("param_type", "REQUIRED")
                inp["param_type"] = "DYNAMIC"
                Logger.warn(
                    f"requirement input {name!r}: proto 声明 TensorList（结构信号）但 "
                    f"param_type={old!r} — TensorList 在 CANN 必须 DYNAMIC，派生为 DYNAMIC。")

    def _validate_attr_type_grammar(self, req_data: object, proto_path) -> list[str]:
        """step-105 防线2：attr 类型声明的文法可表达性 + golden 用例值 cross-check。

        a) 每个声明类型经翻译点后必须落在文法上（base | list[T] | T1|T2）——
           否则 requirement 期的响亮报错（三选一处置指引），杜绝"静默压平造假"
           （20260829 interpolate 事故根因：类型系统表达不了 → LLM 自创编码）。
        b) 声明与 golden 用例值（proto 同目录 cases.yaml 的 attrs）结构
           cross-check——只拦**矛盾**（声明标量/扁平 vs 样例列表/嵌套），
           不拦**细化**（样例兼容声明=通过；L4 红线2 禁止结构相等比对）。
        """
        import yaml
        from ascendc_devkit.domain.operator import (
            check_attr_value, canonical_attr_type, is_grammar_type)

        errors: list[str] = []
        attrs = []
        if isinstance(req_data, dict):
            raw_attrs = req_data.get("attrs") or []
            attrs = raw_attrs if isinstance(raw_attrs, list) else []
        decl: dict[str, str] = {}
        for a in attrs:
            if isinstance(a, dict) and a.get("name") and a.get("type"):
                decl[str(a["name"])] = str(a["type"])
        if not decl:
            return errors

        # a) 文法可表达性（翻译后判定；透传标签 = 不可表达）。
        for name, raw in decl.items():
            canon, _ = canonical_attr_type(raw)
            if not is_grammar_type(canon):
                errors.append(
                    f"attrs[{name!r}].type {raw!r} 无法解析为类型文法"
                    f"（文法: 基础类型 | list[T] 任意嵌套 | T1|T2）。"
                    f"处置三选一: 收录新拼写别名 / 扩展文法形状 / 该属性改声明为"
                    f"可表达类型并保持 golden 语义; 禁止为迁就类型系统发明编码变换"
                    f"（压平/序列化）。canonical={canon!r}")

        # b) golden 用例值 cross-check（样例来自 cases.yaml attrs）。样例载体
        # 只有 cases.yaml——cases.csv 是 13 列规格型用例表、无可读 attrs 样例，
        # 列它当候选只会制造「看似支持实则跳过」的假象，故不列。
        sample: dict[str, list] = {}
        try:
            cases_file = None
            if proto_path:
                _yaml = Path(proto_path).parent / "cases.yaml"
                if _yaml.is_file():
                    cases_file = _yaml
            if cases_file is not None:
                data = yaml.safe_load(cases_file.read_text(encoding="utf-8")) or []
                for case in data if isinstance(data, list) else []:
                    if not isinstance(case, dict):
                        continue
                    for k, v in (case.get("attrs") or {}).items():
                        sample.setdefault(str(k), []).append(v)
        except Exception:  # noqa: BLE001 — best-effort cross-check, 样例缺失不算错
            sample = {}
        for name, raw in decl.items():
            if name not in sample:
                continue
            canon, _ = canonical_attr_type(raw)
            if not is_grammar_type(canon):
                continue  # a) 已报
            for v in sample[name]:
                if not check_attr_value(v, canon):
                    errors.append(
                        f"attrs[{name!r}] 声明类型 {raw!r}（canonical={canon!r}）与 "
                        f"golden 用例值结构矛盾: 值={v!r}。声明须忠实 golden 语义"
                        f"（如嵌套列表声明 list[list[int]]，禁止压平编码）。")
                    break  # 每属性报一次
        return errors

    @staticmethod
    def _validate_tensorlist_param_type(req_data: object) -> list[str]:
        """§1.3 加载期交叉校验：is_list=true 但 param_type≠DYNAMIC → schema_violation。

        TensorList（is_list=true）在 CANN 必须 DYNAMIC；标 REQUIRED/OPTIONAL 是语义矛盾
        （runner 的 DYNAMIC 闸门不认 → list-of-lists 用例全拒 → upstream halt）。
        _derive_tensorlist_param_type 已按 proto 结构信号修正；本校验兜「agent 手写
        is_list=true 却标错 param_type」且 proto 未声明的残余——契约不一致大声失败。
        """
        if not isinstance(req_data, dict):
            return []
        inputs = req_data.get("inputs")
        if not isinstance(inputs, list):
            return []
        errors: list[str] = []
        for inp in inputs:
            if not isinstance(inp, dict):
                continue
            flag = inp.get("is_list")
            is_list = (flag is True
                       or (isinstance(flag, str)
                           and flag.strip().lower() in ("1", "true", "yes")))
            if not is_list:
                continue
            pt = str(inp.get("param_type", "REQUIRED")).upper()
            if pt != "DYNAMIC":
                name = inp.get("name", "?")
                errors.append(
                    f"requirement.json input {name!r}: is_list=true（TensorList）但 "
                    f"param_type={inp.get('param_type', 'REQUIRED')!r} — TensorList "
                    "在 CANN 必须 DYNAMIC，须改 param_type=DYNAMIC")
        return errors

    @staticmethod
    def _attach_proto(op_spec, proto_path):
        """Patch proto-sourced precision_thresholds + per-output compare/
        index_gather flags onto an agent-built op_spec (P69).

        The requirement agent's output carries op_name/inputs/outputs but not
        precision_thresholds (that is the proto's job, and proto is the single
        source of precision tolerance). Recover it here deterministically rather
        than trusting the agent to echo it. Graceful: proto missing/unreadable/
        undeclared → op_spec unchanged (precision_thresholds stays None;
        downstream applies the default table + explicit "no spec declared"
        marker, never silent).
        """
        thresholds, compares, index_gathers = read_proto_precision(proto_path)
        has_meta = any(
            c is not None or g is not None
            for c, g in zip(compares, index_gathers)
        )
        if thresholds is None and not has_meta:
            return op_spec
        new_outputs = list(op_spec.outputs)
        for i, (cmp, ig) in enumerate(zip(compares, index_gathers)):
            if (cmp is not None or ig is not None) and i < len(new_outputs):
                kw = {}
                if cmp is not None:
                    kw["compare"] = cmp
                if ig is not None:
                    kw["index_gather"] = ig
                new_outputs[i] = dc_replace(new_outputs[i], **kw)
        return dc_replace(
            op_spec, precision_thresholds=thresholds, outputs=new_outputs
        )

    @staticmethod
    def _read_design_chip_from_doc(state: "State") -> str | None:
        """P81 (step-58): deterministically read design_target_chip from the
        requirement doc's explicit top-level YAML field. Agent-produced
        constraints are NOT a chip source (照搬 schema example A5 污染,
        run 20260717-070202-53f685). Returns the canonical chip or None.

        Authority (state.py): CLI > requirement-doc explicit field > runtime
        fallback. This reads the doc layer; CLI/runtime are set at dispatch.
        """
        import yaml
        from ascendc_devkit.domain.chip import is_known_generation
        path = getattr(state, "requirement_path", None)
        if not path or not Path(path).exists():
            return None
        try:
            data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return None  # non-YAML / unreadable doc → no chip (keep entry fallback)
        if not isinstance(data, dict):
            return None
        chip = data.get("design_target_chip")
        if not isinstance(chip, str) or not is_known_generation(chip):
            return None  # unknown generation ignored; canonical 单一源 domain/chip.py
        return chip

    def _apply_design_target_chip(self, state: "State", chip: str) -> "State":
        """Override design_target_chip + rebuild RunContext.hardware_target from a
        requirement-declared design_target_chip (hardware constraint).

        Design is independent of hardware: the declared generation drives design
        (hw_params), while build/runtime gates (deploy/verify) enforce
        design==runtime. Only hardware_target is swapped — hardware_env and
        software_env (the run-ON / run-WITH facts) are preserved. An unmapped
        chip degrades to a bare HardwareTarget (mirrors ContextStage) so an
        unverifiable spec never aborts a pure-design run.
        """
        from dataclasses import replace
        from ascendc_devkit.orchestration.run_context import (
            build_hardware_target, HardwareTarget, RunContext,
        )
        from ascendc_devkit.infra.logger import Logger
        try:
            new_target = build_hardware_target(chip)
        except (KeyError, FileNotFoundError) as e:
            Logger.warn(
                f"design_target_chip {chip!r} has no chip-spec mapping ({e}); "
                f"hw_params unverifiable for design"
            )
            new_target = HardwareTarget(chip=chip)
        if state.run_context is None:
            new_rc = RunContext(hardware_target=new_target)
        else:
            new_rc = replace(state.run_context, hardware_target=new_target)
        Logger.info(f"design_target_chip override: design_target_chip -> {chip}")
        return state.with_updates(
            design_target_chip=chip,
            run_context=new_rc)

    def _apply_non_interactive_severity(
        self, state: State, unclear: list[UnclearItem]
    ) -> tuple[list[UnclearItem], str | None]:
        """Non-interactive resolution policy for pending unclear items.

        Returns ``(updated_unclear_items, feedback | None)``.

        - blocking + unresolved, first occurrence
          → do NOT abort. Return the items unchanged plus a feedback message
          asking the agent to re-evaluate its classification. The runner will
          iterate, the agent will see the feedback in its next prompt, and
          resolve the item if the document is actually complete (e.g. C API
          required-parameter with all values enumerated).

        - blocking + unresolved, second occurrence (feedback already set)
          → the agent has re-evaluated and still considers it blocking. This
          is a genuine underspecification → raise PreconditionError.

        - choice + unresolved → auto-resolve with a recorded default
          assumption so the pipeline can proceed deterministically.

        Already-resolved items pass through untouched.
        """
        from dataclasses import replace
        from ascendc_devkit.domain.exceptions import PreconditionError

        blocking = [u for u in unclear
                    if u.severity == "blocking" and not u.resolution]
        if blocking:
            questions = "; ".join(u.question for u in blocking)

            # L2 guard: first time we see blocking+unresolved in non-interactive
            # mode, inject a loopback feedback instead of aborting. This gives the
            # agent one chance to re-evaluate — L1 skill training should have
            # already taught it not to misclassify C API required-parameters.
            # Only if the agent re-confirms blocking after this feedback do we
            # treat it as a genuine underspecification and abort.
            if not state.user_feedback:
                item_lines = "\n".join(f"- {u.question}" for u in blocking)
                feedback = (
                    "## 自动反馈（框架层 L2 兜底检查）\n\n"
                    "上一轮分析中你标记了以下 items 为 blocking 且 resolution=null：\n\n"
                    f"{item_lines}\n\n"
                    "请逐一重新评估每一 item：\n"
                    "- 若该参数/配置在文档中**已完整列出全部合法值**（如 mode=0/1/2/3），"
                    "仅 API 签名中无默认值 → 这是 C API 必传参数的正常语义，非需求缺失。"
                    "将该 item 设为 `severity: \"choice\"`，`resolution` 填入类似"
                    "\"必须由调用方显式指定，文档已枚举全部合法值\" 的描述。\n"
                    "- 仅在算子**核心语义缺失**时（如：输出 shape 无法确定、计算公式未定义、"
                    "dtype 集完全未知）才保留 blocking+null。\n\n"
                    "请根据以上反馈重新输出完整 requirement.json，不清空已正确判断的其他字段。"
                )
                return (unclear, feedback)

            # Second pass: agent still considers it blocking. This is a genuine
            # underspecification — escalate to hard error.
            raise PreconditionError(
                self.name,
                "requirement underspecified — "
                f"{len(blocking)} blocking item(s) need clarification but the run "
                f"is non-interactive: {questions}. Supplement the requirement "
                "document and re-run.",
            )

        resolved: list[UnclearItem] = []
        for u in unclear:
            if not u.resolution and u.severity != "blocking":
                resolved.append(replace(
                    u, resolution="(default assumption — non-interactive run)"))
            else:
                resolved.append(u)
        return (resolved, None)

