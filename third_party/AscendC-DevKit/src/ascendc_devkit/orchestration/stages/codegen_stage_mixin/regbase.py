"""Regbase 专用编排逻辑 — CodegenStage 的 Regbase 职责承载（m1 God module 治理后归属本模块）。

本模块只承载 Regbase（A5 SIMT）编程模型专属的编排方法：staging 初始化、action 多步编排
状态机、transition 状态机、s2/s4/vf/s5 各子阶段 prompt 构造。

Mixin 经 ``CodegenStage(RegbaseMixin, ..., Stage)`` MRO 合并回单类——**mixin 必在
``Stage`` 前**：否则 MRO 中 ``StageProtocol`` 的 abstractmethod（``input_contract``/
``output_contract``）遮蔽 mixin 的 concrete 实现，实例化报 ``TypeError: Can't
instantiate abstract class``。

方法只依赖 ``self.<mixin方法>`` 与模块级常量/函数，无实例属性。

**main 分支移植注记（2026-09-11 cherry-pick God-module 拆分）**：本文件方法体取
main 拆分前 codegen.py 的 Regbase 域**现值原样搬迁**（行为零变更）——main 的 A5 侧
比 v0.2.0 新（RETURN 自报主信号 + dispatch_decision Python 化 + compile probes +
E(t) 移除 + s4 parallel），不可用 v0.2.0 侧旧实现覆盖。A5 域归同事所有，本移植为
纯位置搬迁，语义裁定仍归 A5 产权方。
"""

from __future__ import annotations

import json
import re
from collections import namedtuple
from pathlib import Path
from typing import TYPE_CHECKING

from ascendc_devkit.domain.verification import BuildResult, DeployResult
from ascendc_devkit.orchestration.skill_config import STAGE_SKILL_MAP
from ascendc_devkit.orchestration.kernel.action import SpawnAgent, Action
from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
from ascendc_devkit.orchestration.stages.codegen_s4 import (
    RETRY_COUNTER_LIMITS,
    all_vf_ids,
    bump_retry_counter,
    check_retry_exceeded,
    dispatch as dispatch_decision,
    get_execution_group,
    get_group,
    parse_return_signal,
    pending_vf_ids,
    regenerate_progress,
    resolve_execution_group,
    resolve_sub_stage,
    set_status,
    sync_kernel_steps,
    vf_group_base,
)

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State

# Regbase 错误权重（历史 E(t) 机制已移除，常量保留供测试契约引用）。
ERROR_WEIGHTS: dict[str, int] = {
    "INP": 3, "CHK": 2, "CK": 2, "CK-VF": 2,
    "ENV": 5, "OTH": 1, "C-SYM": 1, "C-TYP": 1,
    "AMB": 2, "DSG": 3, "MEM": 1,
}

# —— Regbase 单类重试上限（limit 值派生自 codegen_s4.RETRY_COUNTER_LIMITS
#    唯一权威表，防止两处漂移；对应 SKILL.md meta.json retries） ——
RETRY_LIMITS: dict[str, tuple[str, int]] = {
    "s5": ("stage5_compile", RETRY_COUNTER_LIMITS["stage5_compile"]),
    "s4": ("stage4_selfcheck", RETRY_COUNTER_LIMITS["stage4_selfcheck"]),
    "s2": ("stage4_selfcheck", RETRY_COUNTER_LIMITS["stage4_selfcheck"]),  # s2 复用 selfcheck 计数器
}

# s5→s4 回退预算：防 s4↔s5 无限乒乓（E(t) 移除后由独立 rollback 计数兜环，
# 上限 2；s5 成功后重置）。
S5_ROLLBACK_LIMIT = 2

# —— VF 测试 UB 容量默认值（bytes）。run_context/hw_params 缺失时的回退值。
# 248KB = 253952，A5 典型 VectorCore UB 大小（与 chip spec 的 shared.memory.ub.size_bytes 一致）。
_REGABASE_DEFAULT_UB_SIZE = 253952

# 轻量 namedtuple：非 agent 返回场景构造标准 error_type。
_FakeAgentResult = namedtuple("_FakeAgentResult", ["error_type"])


class RegbaseMixin:
    """Regbase 专用编排逻辑 mixin（职责见模块 docstring，经 MRO 合并回 CodegenStage）。"""


    # —— 以下为 main 拆分前 codegen.py 现值原样随迁（2026-09-11 移植，行为零变更）：
    #    A5/Regbase 域全部方法 + A5 依赖的 helper（v0.2.0 拆分 shell 未携带）。
    #    main 的 A5 侧比 v0.2.0 新（RETURN 自报 + compile probes + E(t) 移除），
    #    不可用 v0.2.0 旧实现覆盖；A5 域产权归同事，本块为纯位置搬迁。 ——

    # Circuit breaker: stop re-spawning the coder after this many *consecutive*
    # hard agent failures (status != "ok"). Without this, a persistently failing
    # agent (e.g. a server-side API error before any file is written) leaves
    # generated_sources unset, so the output_contract is never satisfied and the
    # runner spins up to its 100-iteration safety net doing no useful work.
    # 20260820：熔断只对"空跑"（transcript 无 Write 证据，0 产出）与"超豁免窗口的
    # 连续孤儿"（F8，2026-08-21）计费——重试无意义（模型没进入写阶段 / 无视确定性
    # 路径反馈），阈值后 halt 防空烧 token。窗口内孤儿豁免，走迭代预算（1000，修
    # bug）重试（见 _transition_membase 的 artifact_misplaced 分支）。
    # 阈值收敛进 orchestration-config retry_budgets.consecutive_failures_max
    # （§1.15 方案 B）；不再用类属性 max_consecutive_failures。
    # A5 Regbase VF pre-verification 并行策略：plan 首个 `.VT.{M}` 步骤（VT.0）
    # 串行单派发（先行建立 vf_verified 测试脚手架），其后步骤 VT.1/VT.2/...
    # 每 iteration 至多并发 `max_concurrent_vf` 个 vf-test-agent。VF 函数互相
    # 独立（各为单例 execution unit），并行安全；此 cap 约束并行编译/LLM 资源占用。
    max_concurrent_vf = 2

    def _regbase_record_dir(self, state: State) -> str:
        """RECORD_DIR = staging 目录本身（与 SKILL.md '$RECORD_DIR 兼作 staging' 一致）。"""
        ws = self._workspace(state)
        if ws is None:
            return ""
        return str(Path(ws.artifacts) / "staging")


    @staticmethod
    def _regbase_s2_deliverables_ok(rd: str) -> tuple[bool, str]:
        """s2→s4 确定性门控：s2 必须真实产出 s4 前置产物。

        检查 orchestration_plan.json（合法 JSON + 非空 sub_stages）与 coding_index.md
        （非空）是否就绪。此门控在编排层（§1.3 加载期校验）而非 agent 前置检查
        （LLM 执行非确定）——s2 返回 COMPLETED 但缺产物时不得放行进入 s4。
        """
        plan_path = Path(rd) / "orchestration_plan.json"
        ci_path = Path(rd) / "coding_index.md"
        if not plan_path.is_file():
            return False, "orchestration_plan.json 缺失"
        if not ci_path.is_file():
            return False, "coding_index.md 缺失"
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except Exception:
            return False, "orchestration_plan.json 不可解析"
        if not plan.get("sub_stages"):
            return False, "orchestration_plan.json 的 sub_stages 为空"
        if not ci_path.read_text(encoding="utf-8").strip():
            return False, "coding_index.md 为空"
        return True, ""


    def _regbase_skill_root(self, state: State) -> str:
        """SKILL_ROOT 2 级 fallback（对应 SKILL.md SKILL_ROOT 节）。

        注意：state.repo_root 是目标算子仓库（如 cann-bench），不是 DevKit 自身。
        skill 在 DevKit 项目内，优先用 DevKit 自身路径。

        §1.7 仓自闭环：所有路径必须指向项目自身，禁止依赖 Path.home() / ~/.claude
        等外部路径。找不到 → 返回空字符串，由调用方报错。
        """
        # ① DevKit 项目自身（从本文件路径推导：regbase.py → codegen_stage_mixin/
        #    → stages/ → orchestration/ → ascendc_devkit/ → src/ → DevKit root）
        devkit_root = Path(__file__).resolve().parent.parent.parent.parent.parent.parent
        devkit_candidate = (devkit_root / ".claude" / "skills"
                            / "ascendc-op-dev-coding-regbase")
        if (devkit_candidate / "scripts").is_dir() and (
                devkit_candidate / "references").is_dir():
            return str(devkit_candidate)

        # ② 目标仓库内路径（仅项目内，不走家目录）
        if state.repo_root:
            repo_candidate = (Path(str(state.repo_root)) / ".claude" / "skills"
                              / "ascendc-op-dev-coding-regbase")
            if (repo_candidate / "scripts").is_dir() and (
                    repo_candidate / "references").is_dir():
                return str(repo_candidate)

        # ①② 均失败 → 报错，不静默降级到家目录搜索
        from ascendc_devkit.infra.logger import Logger
        Logger.error(
            "Cannot locate ascendc-op-dev-coding-regbase skill root: "
            "not found under DevKit project or target repo. "
            "Ensure the skill is installed in .claude/skills/ under the project root."
        )
        return ""


    def _regbase_agent_root(self, state: State, agent_name: str) -> str:
        """AGENT_ROOT = skill_root 同一 .claude 根下的 agents/{name}.md

        与 _regbase_skill_root 共享同一 .claude 根（skill 在 DevKit 项目内时
        agent 也必须在 DevKit 项目内），保证 SKILL_ROOT 与 AGENT_ROOT 的
        .claude 路径一致；skill_root 解析失败 → 返回空串由调用方报错。
        """
        skill_root = self._regbase_skill_root(state)
        if not skill_root:
            return ""
        # skill_root = <root>/.claude/skills/ascendc-op-dev-coding-regbase
        # → .claude 根 = skill_root 的上上两级
        claude_root = Path(skill_root).parent.parent
        return str(claude_root / "agents" / f"{agent_name}.md")


    def _regbase_scripts_dir(self, state: State) -> str:
        return str(Path(self._regbase_skill_root(state)) / "scripts")


    @staticmethod
    def _regbase_vf_ref_dir(state: State) -> str:
        """VF 指令参考目录"""
        repo = str(state.repo_root or "")
        return str(Path(repo) / ".claude" / "skills"
                   / "regbase-vf-test" / "references" / "vf-instructions")


    @staticmethod
    def _regbase_ub_size(state: State) -> int:
        """VF 测试 UB 容量约束的权威 UB 大小（bytes）。

        优先从 ``state.run_context.hardware_target.hw_params.ub_size_bytes`` 读取
        （context stage 已从 chip spec JSON 加载，单一权威源，cures P24 drift）；
        run_context 缺失/未带 hw_params 时回退默认值 248KB（253952，A5 典型 UB 大小）。
        vf-test 流程只读 meta.json.ub_size，不再自行调用 ascend-hardware。
        """
        rc = getattr(state, "run_context", None)
        hw = getattr(getattr(rc, "hardware_target", None), "hw_params", None) or {}
        return int(hw.get("ub_size_bytes", 0) or _REGABASE_DEFAULT_UB_SIZE)


    @staticmethod
    def _is_vf_step(sub_stage: str) -> bool:
        """判断是否为 .VT.{M}（VF 精度预验证）子步骤。"""
        return bool(sub_stage and re.match(r'.*\.VT\.[0-9]+$', sub_stage, re.IGNORECASE))


    @staticmethod
    def _first_vt_in_group(rd: str, current_sub_stage: str, group: str) -> str | None:
        """扫描 coding_index.md 中当前检查点组内，current_sub_stage 之后的第一个 VT 步骤。

        返回步骤 ID（如 ``C.3.VT.0``），若无 VT 步骤返回 None。
        仅用于 VT 边界拆分——当 s4-coding 所在的 Group 内含 VT 步骤时，
        编排器必须让 s4-coding 在 VT 前停下来，交还给 ascendc-vf-test-agent。
        """
        index_path = Path(rd) / "coding_index.md"
        if not index_path.is_file():
            return None
        # coding_index.md 步骤列本身无 4. 前缀（C.1 / C.2.VT.0，与
        # stage4_scheduler.sh get-group 同源）；current_sub_stage 来自 progress.md
        # 带 4. 前缀 → 比对前统一去前缀，两边都是规范形后相等。
        lookup = current_sub_stage[2:] if current_sub_stage.startswith("4.") else current_sub_stage
        found_current = False
        with open(index_path, encoding="utf-8") as f:
            in_table = False
            for line in f:
                if line.strip().startswith("| 步骤 "):
                    in_table = True
                    continue
                if not in_table or not line.strip().startswith("|"):
                    if in_table and not line.strip().startswith("|"):
                        break
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 3:
                    continue
                step, grp = parts[1], parts[2]
                # 步骤列去 4. 前缀后再比对（真实 coding_index.md 恒无前缀）
                step_key = step[2:] if step.startswith("4.") else step
                if step_key == lookup:
                    found_current = True
                    continue
                if not found_current:
                    continue
                if grp != group:
                    break  # 跨出当前组，停止扫描
                if re.match(r'.*\.VT\.[0-9]+$', step, re.IGNORECASE):
                    # 返回 4. 前缀格式，与 sub_stage 命名一致
                    return f"4.{step}" if not step.startswith("4.") else step
        return None


    def _check_section_dirs_have_files(self, state: State) -> bool:
        """检查 op_host/op_kernel 等 section 目录是否有源文件产出（对应 SKILL.md line 307）。"""
        code_path = state.op_dir or (
            state.op_identity.op_dir if state.op_identity else None)
        if not code_path:
            return False
        for d in ("op_host", "op_kernel", "op_api", "op_plugin"):
            section = Path(code_path) / d
            if section.is_dir():
                if any(section.glob("*.cpp")) or any(section.glob("*.h")):
                    return True
        return False


    def _regbase_ensure_init(self, state: State) -> None:
        """幂等创建 RECORD_DIR 下的初始文件（meta.json / progress.md / history.log 等）。

        调用时机：首次进入 _actions_regbase() 且 progress.md 不存在时。
        _materialize_inputs 已先行创建 staging 目录并写入设计 JSON + 基础 meta.json；
        本方法补充 Regbase 编排所需的完整字段与记录文件。
        """
        rd = self._regbase_record_dir(state)
        if not rd:
            return
        root = Path(rd)
        root.mkdir(parents=True, exist_ok=True)

        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # —— meta.json：基于 schema 模板，合并 _materialize_inputs 已写入的基础字段 ——
        meta_path = root / "meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        else:
            meta = {}
        # 补全 Regbase 编排所需字段（保留已有值）
        meta.setdefault("op_name", state.op_name or "")
        meta.setdefault("created_at", now)
        meta.setdefault("updated_at", now)
        meta.setdefault("dev_mode", state.mode or "new")
        meta.setdefault("code_path", str(state.op_dir or ""))
        meta.setdefault("chip_model", state.design_target_chip or "")
        meta.setdefault("ub_size", self._regbase_ub_size(state))
        meta.setdefault("compile_cmd", "")
        meta.setdefault("design_doc", state.design_doc or "")
        meta.setdefault("ref_op", str(state.reference_op_path or ""))
        meta.setdefault("golden_ref", str(state.golden_path or ""))
        meta.setdefault("vf_ref_dir", self._regbase_vf_ref_dir(state))
        # Repository profile is the single authority for the invocation
        # protocol.  Persist it for S2/S4 agents so a detailed-design statement
        # cannot incorrectly override a mandatory torch plugin delivery.
        meta["scaffolding_kind"] = self._profile_scaffolding_kind(state)
        meta["required_codegen_sections"] = self._required_codegen_sections(state)
        meta.setdefault("interaction_mode", "auto")
        meta.setdefault("kernel_steps", [])
        meta.setdefault("current_stage", 1)
        # retries 默认值从 RETRY_COUNTER_LIMITS 唯一权威表派生（limit 与
        # 编排层判定一致，仅作展示镜像）
        meta.setdefault("retries", {
            **{k: {"used": 0, "limit": v}
               for k, v in RETRY_COUNTER_LIMITS.items()},
            "s5_rollback": {"used": 0, "limit": S5_ROLLBACK_LIMIT},
        })
        meta.setdefault("last_gate", "-")
        meta["updated_at"] = now
        meta_path.write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

        # —— progress.md ——
        progress_path = root / "progress.md"
        if not progress_path.exists():
            progress_path.write_text(
                "| Stage | 状态 | 完成时间 | 备注 |\n"
                "|-------|------|---------|------|\n"
                "| 1 环境确认 | ✅ | - | 非本编排阶段（环境由编排层就绪） |\n"
                "| 2 需求分析 | ⏳ | - | - |\n"
                "| 3 需求澄清 | ✅ | - | 非本编排阶段（无 Stage 3） |\n"
                "| 4.0 编码前置 | ⏳ | - | - |\n"
                "| 4.A 数据结构层（TilingData） | ⏳ | - | - |\n"
                "| 4.B1 OpDef + InferShape | ⏳ | - | - |\n"
                "| 4.B2 Host Tiling | ⏳ | - | - |\n"
                "| 4.C Kernel 实现 | ⏳ | - | - |\n"
                "| 4.E 构建配置（CMakeLists） | ⏳ | - | - |\n"
                "| 4.F 编码后自检 | ⏳ | - | - |\n"
                "| 5 编译出包 | ⏳ | - | - |\n",
                encoding="utf-8")

        # —— history.log ——
        history_path = root / "history.log"
        if not history_path.exists():
            history_path.write_text(
                f"[{now}] [STAGE_START] Regbase 编排开始\n",
                encoding="utf-8")

        # —— 空占位文件 ——
        for fn in ("env_snapshot.md", "requirements.md",
                    "clarification.md", "coding_plan.md"):
            p = root / fn
            if not p.exists():
                p.touch()

        # —— issues/ 目录 ——
        (root / "issues").mkdir(parents=True, exist_ok=True)


    def _actions_regbase(self, state: State, iteration: int) -> list[Action]:
        """Regbase 多步编排入口。"""
        rd = self._regbase_record_dir(state)

        # 0. Idempotent init（record dir 不存在时创建）
        if not (Path(rd) / "progress.md").exists():
            self._regbase_ensure_init(state)

        # 1. NEEDS_AGENT 暂存处理：上一轮请求了外部 agent，本轮代其启动
        if state.codegen_pending_agent:
            return self._actions_regbase_needs_agent(state)

        # 2. Phase 路由
        phase = state.codegen_phase
        if not phase or phase == "s2":
            return self._actions_regbase_s2(state)
        elif phase == "s4":
            return self._actions_regbase_s4(state)
        elif phase == "s5":
            return self._actions_regbase_s5(state)
        else:  # "done"
            return []


    def _actions_regbase_s2(self, state: State) -> list[Action]:
        """Phase s2：派发 ascendc-dev-s2-analysis。"""
        rd = self._regbase_record_dir(state)
        skill_root = self._regbase_skill_root(state)
        agent_s2 = self._regbase_agent_root(state, "ascendc-dev-s2-analysis")
        code_path = str(state.op_dir or "")
        prompt = self._build_s2_prompt(state, rd, skill_root, agent_s2, code_path)
        return [SpawnAgent(
            agent_name="ascendc-dev-s2-analysis",
            prompt=prompt,
            primary_skill=STAGE_SKILL_MAP.get("codegen_regbase"),
            working_dir=code_path or None,
            context={"mode": state.mode, "codegen_phase": "s2",
                     "record_dir": rd},
        )]


    def _actions_regbase_s4(self, state: State) -> list[Action]:
        """Phase s4：根据 codegen_s4 状态机解析 sub-stage 并路由。"""
        rd = self._regbase_record_dir(state)

        # reason 选择 + sub-stage 确定
        if not state.codegen_s4_sub_stage:
            # 首次进入 s4
            sub_stage = resolve_sub_stage(rd, "first_enter")
        elif state.last_error:
            # retry/rollback 场景：dispatch 已设置了明确的 sub_stage
            sub_stage = state.codegen_s4_sub_stage
        else:
            # 正常推进
            sub_stage = resolve_sub_stage(rd, "continue")

        if sub_stage == "DONE":
            return []  # transition → advance to s5

        # 查检查点组（仅用于本次 prompt 构造）
        group = get_group(rd, sub_stage)

        if self._is_vf_step(sub_stage):
            return self._actions_regbase_vf(state, rd, sub_stage)
        else:
            return self._actions_regbase_s4_step(state, rd, sub_stage, group)


    def _actions_regbase_s4_step(self, state: State, rd: str,
                                  sub_stage: str, group: str) -> list[Action]:
        """构造 S4 Coding prompt + 派发 ascendc-dev-s4-coding。"""
        code_path = str(state.op_dir or "")
        sub_stages = resolve_execution_group(rd, sub_stage)
        execution_group = get_execution_group(rd, sub_stage) or sub_stage
        checkpoint_groups = {sid: get_group(rd, sid) for sid in sub_stages}
        prompt = self._build_s4_prompt(
            state, rd, sub_stages, execution_group, group, code_path,
            checkpoint_groups=checkpoint_groups)
        return [SpawnAgent(
            agent_name="ascendc-dev-s4-coding",
            prompt=prompt,
            working_dir=code_path or None,
            context={"mode": state.mode, "codegen_phase": "s4",
                     "record_dir": rd,
                     "current_sub_stage": sub_stage,
                     "current_sub_stages": sub_stages,
                     "execution_group": execution_group,
                     "checkpoint_group": group,
                     "checkpoint_groups": checkpoint_groups},
        )]


    def _actions_regbase_vf(self, state: State, rd: str,
                             sub_stage: str) -> list[Action]:
        """构造 VF prompt + 派发 ascendc-vf-test-agent（先串行后并行）。

        策略：plan 顺序的首个 ``.VT.{M}`` 步骤完成前，只派发它一个（串行——由其
        先行建立 ``vf_verified`` 测试脚手架）；完成后，其余 pending VF 步骤每
        iteration 并行派发至多 ``max_concurrent_vf`` 个 SpawnAgent，由 runner 在
        线程池中并行执行（``agent_results`` 列表返回）。重试场景仅剩当前步骤时
        退化为单派发。

        并行批量**按模板组隔离**（``vf_group_base``）：批内只取与当前 frontier
        同组（同 ``.VT.`` 基名）的 pending VF，不跨模板混批——T1 的 VT 不提前
        混入 T2 的 VT、T2 的 VT 不被 4.C.3~4.C.5 等普通步骤压后。
        """
        code_path = str(state.op_dir or "")
        # 扫描已完成的 VF 结果（整批共享同一快照，供各 VF prompt 引用）
        vf_dir = Path(rd) / "vf_verified"
        previous_vf_results: list[str] = []
        if vf_dir.is_dir():
            previous_vf_results = sorted(
                str(p.relative_to(vf_dir)) for p in vf_dir.rglob("*.cpp"))

        # 批量收集：重试路径（sub_stage 已被 dispatch 设定）与正常推进共用
        # pending_vf_ids；sub_stage 在列则以其为起点，否则取全部 pending。
        pending = pending_vf_ids(rd)
        if sub_stage in pending:
            start = pending.index(sub_stage)
        else:
            start = 0
        # 先串行后并行：plan 首个 VF 步骤（无论状态）仍 pending → 只派发它，建立
        # vf_verified 测试脚手架后（done/exhausted）再对后续 VF 并行批量。
        first_vf = (all_vf_ids(rd) or [""])[0]
        if first_vf in pending:
            batch = [first_vf]
        else:
            # 同模板 VF 组并行：批内只取与当前 frontier 同组（.VT. 基名相同）的
            # pending VF（§P2 组隔离）。否则取「全部 pending VF 前 N 个」会把
            # 其他模板组的 VF 提前混入本批、剩余 VF 被普通步骤压后（log_softmax
            # 批实证：4.C.6.VT.0 混入 T1 批、4.C.6.VT.1/VT.2 排到 4.C.3~4.C.5 后）。
            group = vf_group_base(sub_stage)
            group_pending = [sid for sid in pending[start:]
                             if vf_group_base(sid) == group]
            batch = group_pending[:self.max_concurrent_vf] or [sub_stage]

        agents: list[Action] = []
        for vs in batch:
            prompt = self._build_vf_prompt(
                state, rd, vs, code_path,
                previous_vf_results=previous_vf_results)
            agents.append(SpawnAgent(
                agent_name="ascendc-vf-test-agent",
                prompt=prompt,
                working_dir=code_path or None,
                # §P2 并行分支隔离：branch_label=sub_stage 使并行批次内每个 VF
                # 各得独立 transcript + session sidecar（transcript 已按 branch
                # 隔离，sidecar 键亦含 branch_label）。否则同 (agent, stage) 的
                # 并行兄弟共享同一 sidecar 路径——后者会读到前者刚写入的
                # sidecar 而误 auto-resume 前者会话（VT.2 顶替 VT.1 实测）。
                branch_label=vs,
                context={"mode": state.mode, "codegen_phase": "s4",
                         "record_dir": rd,
                         "current_sub_stage": vs},
            ))
        return agents


    def _actions_regbase_s5(self, state: State) -> list[Action]:
        """Phase s5：编译前置检查 + 派发 ascendc-dev-s5-compile。"""
        rd = self._regbase_record_dir(state)
        code_path = str(state.op_dir or "")

        # 3.1 编译前检查（SKILL.md line 323-329）
        if not self._code_path_has_source_files(code_path):
            return []  # No files → transition sets last_error

        # NEEDS_AGENT 目标完成后重调时注入完成标记
        extra_context: dict = {}
        if state.codegen_pending_resume_point:
            extra_context = {
                "agent_completed": "true",
                "resume_point": state.codegen_pending_resume_point,
            }
        prompt = self._build_s5_prompt(state, rd, code_path)
        return [SpawnAgent(
            agent_name="ascendc-dev-s5-compile",
            prompt=prompt,
            working_dir=code_path or None,
            context={"mode": state.mode, "codegen_phase": "s5",
                     "record_dir": rd, **extra_context},
        )]


    def _actions_regbase_needs_agent(self, state: State) -> list[Action]:
        """暂存 agent 消费：返回 SpawnAgent 给暂存的目标 agent。"""
        agent_name = state.codegen_pending_agent
        resume_pt = state.codegen_pending_resume_point or "needs-agent-resume"
        return [SpawnAgent(
            agent_name=agent_name,
            prompt=f"[NEEDS_AGENT] continue from resume point: {resume_pt}",
            context={"mode": state.mode,
                     "resume_point": resume_pt,
                     "codegen_phase": state.codegen_phase},
            working_dir=str(state.op_dir or ""),
        )]


    def _regbase_smoke_phase(self, state: State,
                             smoke_log_path: str = "") -> str | None:
        """Regbase s5 smoke 失败阶段分类："kernel" | "host" | None。

        s5-compile 在会话内跑 ``ascendc-devkit redeploy``，Deployer 把 smoke 子进程
        完整输出落盘（``smoke_log_path``，DeployResult 本轮实测路径）。Regbase 的
        transition 没有 ``Deployer.deploy()`` 返回的 ErrorFeedback（redeploy 经 CLI
        跑），因此从该日志读全文、复用与 Membase 一致的 ``_classify_smoke_text``
        词汇表（§2.5 单一通路：kernel 阶段 vector error 不归 codegen 重试，交
        precision）。

        新鲜度锚点（review m6）：只信**本轮** deploy 的 smoke 失败日志。smoke.log
        是复用的固定文件名，build 阶段失败（未跑到 smoke）时上一 iteration 的
        smoke.log 仍在盘上——``deploy_result.smoke_log_path`` 只有本轮 smoke 真正
        失败才非空，空 → None（歧义区，维持既有 CK 重试，不读 stale 日志误分类）。
        """
        if not smoke_log_path:
            return None
        log_path = Path(smoke_log_path)
        if not log_path.is_file():
            return None
        try:
            full = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        return self._classify_smoke_text(full)


    def _transition_regbase(self, state: State, agent_result) -> State:
        """Regbase 多步编排 transition 入口。"""

        # 0. NEEDS_AGENT 暂存处理：上一轮设置了 codegen_pending_agent，
        #    本轮目标 agent 已完成 → 清除暂存 → 重调原 phase
        if state.codegen_pending_agent:
            return self._transition_regbase_needs_agent_done(state, agent_result)

        phase = state.codegen_phase

        # 1. 路由到对应 phase 的 transition handler
        if not phase:
            # 首次进入：s2 刚完成，标记 phase="s2"
            result = self._transition_regbase_s2(state, agent_result)
            if result.codegen_phase == "":
                result = result.with_updates(codegen_phase="s2")
            return result
        elif phase == "s2":
            return self._transition_regbase_s2(state, agent_result)
        elif phase == "s4":
            return self._transition_regbase_s4(state, agent_result)
        elif phase == "s5":
            return self._transition_regbase_s5(state, agent_result)
        else:  # "done"
            return state


    def _transition_regbase_s2(self, state: State, agent_result) -> State:
        """Phase s2 transition：完成判定与 s4 对称（RETURN 自报主信号 + backend 兜底）。

        s2-analysis 是纯分析 stage：交付物（orchestration_plan.json / coding_index.md）
        全部写在 staging record_dir，spawn working_dir（op_dir）无新增文件 → backend
        恒报 empty_artifacts。因此完成判定不能只认 status=="ok"（508430c9 回归根因，
        run 20260807-100841-d9de37 死循环：s2 每次成功都被当失败重试 4+ 次），而是：
          - backend fatal/partial → 硬失败，文本自报不得覆盖；
          - 否则 backend ok/empty_artifacts → 兜底 COMPLETED（empty_artifacts 属
            纯分析 stage 正常完成，与 s4 dispatch_status 同源）；
          - agent 最后一轮回复的 RETURN 自报（COMPLETED/FAILED + error_type）作为
            完成判定的主信号覆盖 backend 推断（与 _transition_regbase_s4 同源）；
          - 有最终回复但无 RETURN 块 → 不静默抬成 COMPLETED（2026-08-06 防线）。
        """
        rd = self._regbase_record_dir(state)
        scripts_dir = self._regbase_scripts_dir(state)
        dr = str(Path(scripts_dir) / "dev_record.sh")

        # Map SDK status → dispatch status（empty_artifacts = 纯分析 stage 正常完成）
        dispatch_status = {"ok": "COMPLETED", "failed": "FAILED",
                           "partial": "PARTIAL", "paused": "PAUSED",
                           "empty_artifacts": "COMPLETED", "fatal": "FAILED"}
        status = dispatch_status.get(
            getattr(agent_result, 'status', 'failed'), "FAILED")

        effective_error_type = getattr(
            agent_result, 'error_type', 'OTH') or "OTH"

        # agent 最后一轮回复的 RETURN 自报（COMPLETED/FAILED + error_type）作为
        # 完成判定的主信号：解析到即覆盖 framework 推断。
        # 前提：backend 未崩溃（fatal/partial 是硬失败，文本自报不得覆盖）。
        _backend_status = getattr(agent_result, 'status', '') or ""
        final_response = getattr(agent_result, 'final_response', None)
        ret = parse_return_signal(final_response)
        if _backend_status not in ("fatal", "partial"):
            if ret.get("status") in ("COMPLETED", "FAILED"):
                status = ret["status"]
            if ret.get("error_type"):
                effective_error_type = ret["error_type"]
            # 有最终回复但既无 RETURN 块也无 VF_TEST_RESULT 块：不得把 backend
            # ok/empty_artifacts 静默抬成 COMPLETED —— 完成判定只能来自 agent 自报
            # （与 s4 同源防线：RETURN 缺失一律 FAILED）。
            if final_response and not ret and status == "COMPLETED":
                from ascendc_devkit.infra.logger import Logger
                Logger.warn(
                    "codegen s2: agent final_response present but no "
                    "RETURN/VF_TEST_RESULT block parsed; treating as FAILED "
                    "instead of backend-inferred COMPLETED")
                status = "FAILED"
                effective_error_type = effective_error_type or "OTH"

        if status == "COMPLETED":
            # s2→s4 门控（编排层确定性检查）：s2 返回 COMPLETED 但前置产物缺失
            # （orchestration_plan.json / coding_index.md）时，不进入 s4——按 s2
            # 失败重派（message 落 last_error.md，经 s2 重试轮诊断注入读取）。状态跳转
            # 完全由 Python 决定，不依赖 agent 自检。
            ok, reason = self._regbase_s2_deliverables_ok(rd)
            if not ok:
                return self._handle_regbase_failure(
                    state, _FakeAgentResult(error_type="INP"), "s2",
                    message=f"s2 返回 COMPLETED 但前置产物缺失：{reason}")
            # 派生 progress.md + kernel_steps 到 meta.json（框架侧同步，供 human/旧工具可读）
            regenerate_progress(rd)
            sync_kernel_steps(rd)
            self._bash(dr, "append-history", rd,
                       "STAGE_COMPLETE", "s2-analysis 完成")
            return state.with_updates(codegen_phase="s4",
                                      codegen_s4_sub_stage="")

        # 失败 → 用 RETURN 自报的 error_type（Layer 1 重试/权重按 agent 判定）；
        # RETURN 未报 error_type → 回退 backend 推断。_FakeAgentResult 只承载
        # error_type（_handle_regbase_failure 仅消费该字段，既有 s5 用法同源）。
        if ret.get("error_type"):
            agent_result = _FakeAgentResult(error_type=effective_error_type)
        return self._handle_regbase_failure(state, agent_result, "s2")


    def _complete_regbase_s4(self, state: State) -> State:
        """Advance to s5 only after repository invocation requirements hold."""
        if self._profile_scaffolding_kind(state) == "torch_op":
            contract_error = self._torch_plugin_contract_error(state)
            if contract_error is not None:
                return state.with_updates(last_error=contract_error)
        return state.with_updates(codegen_phase="s5", codegen_s4_sub_stage="")


    def _transition_regbase_s4(self, state: State, agent_result) -> State:
        """Phase s4 transition：dispatch 驱动。"""
        rd = self._regbase_record_dir(state)
        scripts_dir = self._regbase_scripts_dir(state)
        dr = str(Path(scripts_dir) / "dev_record.sh")

        # 空 actions 路径：resolve-sub-stage 已返回 DONE。区分「计划合法完成」
        # 与「计划缺失/为空」——后者是 s2 未真实产出（状态损坏/恢复异常），
        # 不得静默推进到 s5，按编排层门控报错（状态跳转完全由 Python 决定）。
        if agent_result is None:
            sub_stage = resolve_sub_stage(rd, "continue")
            if sub_stage == "DONE":
                ok, reason = self._regbase_s2_deliverables_ok(rd)
                if not ok:
                    return state.with_updates(last_error=ErrorFeedback(
                        stage_name="codegen", error_type="incomplete_output",
                        message=f"s4 前置产物缺失，无法推进 s5：{reason}"))
                return self._complete_regbase_s4(state)
            return state  # 异常：理论上不会到这里

        # Map SDK status → dispatch status
        # empty_artifacts：s4-coding 跑非产码 sub-stage（4.0 编码前置 / VF 测试）时，
        # code_path 无新增文件 → _build_result 返回 empty_artifacts，属正常推进而非失败
        # fatal：agent crashed 无产出 → 失败。二者原漏于 mapping 落默认 FAILED，导致
        # 4.0（编码前置）永不标 ✅、s4 反复从 4.0 重来（run 20260731-050229 死循环根因）。
        # COMPLETED 不再做磁盘 section 检查（2026-08-06）：s4-coding 是否完成以
        # agent 最后一轮回复的 RETURN 自报为主信号（见下），backend 状态兜底崩溃。
        dispatch_status = {"ok": "COMPLETED", "failed": "FAILED",
                           "partial": "PARTIAL", "paused": "PAUSED",
                           "empty_artifacts": "COMPLETED", "fatal": "FAILED"}
        status = dispatch_status.get(
            getattr(agent_result, 'status', 'failed'), "FAILED")

        effective_error_type = getattr(
            agent_result, 'error_type', 'OTH') or "OTH"

        # agent 最后一轮回复的 RETURN 自报（COMPLETED/PARTIAL/FAILED + error_type）作为
        # 完成判定的主信号：解析到即覆盖 framework 推断（status/error_type）。
        # 前提：backend 未崩溃（fatal/partial 是硬失败，文本自报不得覆盖）；缺失
        # final_response（旧 backend / 早期 fatal）→ 回退到上述推断信号。
        _backend_status = getattr(agent_result, 'status', '') or ""
        final_response = getattr(agent_result, 'final_response', None)
        ret = parse_return_signal(final_response)
        if _backend_status not in ("fatal", "partial"):
            if ret.get("status") in ("COMPLETED", "PARTIAL", "FAILED"):
                status = ret["status"]
            if ret.get("error_type"):
                effective_error_type = ret["error_type"]
            if ret.get("next_sub_stage") and ret["next_sub_stage"] != "DONE":
                try:
                    from ascendc_devkit.infra.logger import Logger
                    Logger.info(
                        f"codegen s4 RETURN next_sub_stage="
                        f"{ret['next_sub_stage']} (audit only; routing "
                        f"由 orchestration_plan.json 决定)")
                except Exception:  # noqa: BLE001 — best-effort audit log
                    pass
            # 有最终回复但既无 RETURN 块也无 VF_TEST_RESULT 块：不得把 backend
            # ok/empty_artifacts 静默抬成 COMPLETED —— Stage 4 子阶段的完成判定只能
            # 来自 agent 自报（orchestrator-logic.md §2 兜底逻辑：RETURN 缺失一律
            # FAILED）。2026-08-06 group_norm 4.C.3.VT.0 失败无重试的通用防线。
            if final_response and not ret and status == "COMPLETED":
                from ascendc_devkit.infra.logger import Logger
                Logger.warn(
                    "codegen s4: agent final_response present but no "
                    "RETURN/VF_TEST_RESULT block parsed; treating as FAILED "
                    "instead of backend-inferred COMPLETED")
                status = "FAILED"
                effective_error_type = effective_error_type or "OTH"

        # progress ✅ 标记由 dispatch 内部按 agent 返回的 COMPLETED 完成
        # （orchestrator-logic.md §7.4）；此处禁止预标 ✅，否则 dispatch 的
        # resolve_next('continue') 会跳过刚完成的 sub。

        dispatch_kwargs: dict = {}
        # fatal/partial backend outcomes are hard failures: ignore every piece
        # of textual progress metadata, not only the textual status. Otherwise
        # a stale RETURN could commit an unverified group prefix after a crash.
        if _backend_status not in ("fatal", "partial"):
            if "completed_sub_stages" in ret:
                dispatch_kwargs["completed_sub_stages"] = ret["completed_sub_stages"]
            if ret.get("failed_sub_stage"):
                dispatch_kwargs["failed_sub_stage"] = ret["failed_sub_stage"]
        dispatch = dispatch_decision(
            rd, status, effective_error_type, **dispatch_kwargs)

        action = dispatch.get("action", "paused")

        if action == "finish":
            return self._complete_regbase_s4(state)
        elif action in ("call_s4", "call_vf_test"):
            return state.with_updates(
                codegen_s4_sub_stage=dispatch.get("next_sub_stage", ""))
        elif action == "retry_s4":
            # E(t) 已移除：重试预算由 dispatch 的 per-type 计数器（check_retry_exceeded）
            # 决定；此处仅推进到下一 sub-stage，不累计任何加权错误分。
            return state.with_updates(
                codegen_s4_sub_stage=dispatch.get("next_sub_stage", ""))
        elif action == "rollback_s4":
            # 计数器耗尽后的确定性升级：s4 自检/编码持续失败 → 回退 s2
            # （设计可能是根因；保留原 E(t)>=5 的状态跳转，去加权）。
            return state.with_updates(
                codegen_phase="s2",
                codegen_s4_sub_stage="",
                last_error=ErrorFeedback(
                    stage_name="codegen", error_type="deploy_failed",
                    message=f"s4 自检/编码持续失败，回退 s2："
                            f"{dispatch.get('reason', '')}"))
        elif action == "vf_exhausted":
            exhausted_stage = dispatch.get(
                "exhausted_sub_stage", state.codegen_s4_sub_stage)
            # 编排计划是唯一权威：标 exhausted（progress.md 镜像 ⚠️）
            set_status(rd, exhausted_stage, "exhausted")
            self._bash(dr, "append-history", rd,
                       "CTX_DRIFT",
                       f"VF {exhausted_stage} 精度预验证未通过，标记⚠️继续")
            return state.with_updates(codegen_s4_sub_stage=exhausted_stage)
        elif action == "paused":
            return state.with_updates(
                last_error=ErrorFeedback(
                    stage_name="codegen", error_type="exhausted",
                    message=dispatch.get("pause_reason", "")))
        elif action == "call_agent":
            return state.with_updates(
                codegen_pending_agent=dispatch.get("agent_name", ""))
        elif action == "rollback_stage":
            return state.with_updates(
                codegen_s4_sub_stage=dispatch.get("rollback_target", ""))
        return state


    def _transition_regbase_s4_parallel(self, state: State,
                                        agent_results: list) -> State:
        """Phase s4 transition（P9 并行 VF 批次）。

        一次迭代内并行跑多个 ``ascendc-vf-test-agent``（每个对应一个
        ``.VT.{M}`` 步骤），此方法把各自结果合并推进编排计划：

        - COMPLETED → 标 done（progress.md 镜像 ✅）
        - FAILED → 重试预算未超限则保持 pending（下一轮重跑），超限则标
          exhausted（⚠️ 继续，graceful-continue 与串行 dispatch 一致）

        全部 VF 处理完后 resolve 下一个 pending sub-stage（可能是编码步骤）。
        """
        rd = self._regbase_record_dir(state)
        scripts_dir = self._regbase_scripts_dir(state)
        dr = str(Path(scripts_dir) / "dev_record.sh")

        dispatch_status = {"ok": "COMPLETED", "failed": "FAILED",
                           "partial": "PARTIAL", "paused": "PAUSED",
                           "empty_artifacts": "COMPLETED", "fatal": "FAILED"}

        for ar_it in agent_results:
            ar = ar_it.get("agent_result")
            action = ar_it.get("action")
            if ar is None:
                continue
            sub_stage = ""
            if action is not None:
                ctx = getattr(action, "context", None) or {}
                sub_stage = ctx.get("current_sub_stage", "")
            if not sub_stage:
                sub_stage = state.codegen_s4_sub_stage

            status = dispatch_status.get(
                getattr(ar, 'status', 'failed'), "FAILED")
            effective_error_type = getattr(ar, 'error_type', 'OTH') or "OTH"
            final_response = getattr(ar, 'final_response', None)
            ret = parse_return_signal(final_response)
            if getattr(ar, 'status', '') not in ("fatal", "partial"):
                if ret.get("status") in ("COMPLETED", "PARTIAL", "FAILED"):
                    status = ret["status"]
                if ret.get("error_type"):
                    effective_error_type = ret["error_type"]
                # 有最终回复但无 RETURN/VF_TEST_RESULT 块：不得把 backend
                # ok/empty_artifacts 静默抬成 COMPLETED（与串行 dispatch 同源，
                # 2026-08-06 group_norm 防线）。
                if final_response and not ret and status == "COMPLETED":
                    status = "FAILED"
                    effective_error_type = effective_error_type or "OTH"

            if status == "COMPLETED":
                set_status(rd, sub_stage, "done")
                continue
            if status == "PARTIAL":
                # 部分完成视为失败：保持 pending，下轮重试该步骤
                continue
            if status == "FAILED":
                # §6 编排层计数（per-substage）：每个 FAILED 成员先递增**该 VF 子
                # 阶段**的重试计数，再判是否耗尽（否则该 VF 反复失败永不 exhausted）。
                bump_retry_counter(rd, sub_stage, effective_error_type)
                exceeded, reason = check_retry_exceeded(rd, sub_stage,
                                                        effective_error_type)
                if exceeded:
                    set_status(rd, sub_stage, "exhausted")
                    self._bash(dr, "append-history", rd, "CTX_DRIFT",
                               f"VF {sub_stage} 精度预验证未通过，标记⚠️继续")
                    continue  # 下轮不再重跑该步骤
                # 未超限：保持 pending，下轮重跑该步骤
                continue
            # PAUSED / 其他：保持 pending

        nxt = resolve_sub_stage(rd, "continue")
        if nxt == "DONE":
            return self._complete_regbase_s4(state)
        return state.with_updates(codegen_s4_sub_stage=nxt)


    def _transition_regbase_s5(self, state: State, agent_result) -> State:
        """Phase s5 transition：编译前置检查 + 收尾。"""
        rd = self._regbase_record_dir(state)
        scripts_dir = self._regbase_scripts_dir(state)
        dr = str(Path(scripts_dir) / "dev_record.sh")

        # 空 actions 路径：s5 编译前检查失败（_actions_regbase_s5 返回 []）
        if agent_result is None:
            return state.with_updates(
                codegen_phase="done",
                last_error=ErrorFeedback(
                    stage_name="codegen", error_type="incomplete_output",
                    message="编码阶段无文件产出，编译前检查失败"))

        # NEEDS_AGENT 处理（SKILL.md line 335-339）
        agent_status = getattr(agent_result, 'status', 'failed')
        if agent_status == "needs_agent":
            agent_name = getattr(agent_result, 'agent_name', '') or "ascendc-tiling-strategy"
            self._bash(dr, "append-history", rd,
                       "NEEDS_AGENT", f"agent={agent_name}")
            return state.with_updates(
                codegen_pending_agent=agent_name,
                codegen_pending_resume_point="s5-recompile")

        if agent_status == "ok" and getattr(agent_result, 'artifacts', None):
            artifacts = agent_result.artifacts

            # 契约信号源 = 磁盘（§2.3）：s5-compile 把 CMakeLists.txt 写到 op_dir，
            # 不保证进入回传 artifacts dict —— 用 dict key 判定会在「产物已落盘」
            # 时误判缺失并死循环（run 20260730-072625-bec36b 根因）。
            if not self._cmake_on_disk(state):
                return self._handle_regbase_failure(
                    state.with_updates(last_error=ErrorFeedback(
                        stage_name="codegen", error_type="incomplete_output",
                        message=f"CMakeLists.txt missing on disk "
                                f"(op_dir={state.op_dir}); s5-compile must write "
                                f"CMakeLists.txt to the op directory")),
                    _FakeAgentResult(error_type="INP"), "s5")
            # generated_sources 自描述完整：磁盘有但回传 dict 缺则补读，使下游
            # 消费方拿到完整源码集（契约信号与产物权威统一为磁盘）。
            cmake_p = Path(state.op_dir or "") / "CMakeLists.txt"
            if cmake_p.is_file() and "CMakeLists.txt" not in artifacts:
                try:
                    artifacts = {
                        **artifacts,
                        "CMakeLists.txt": cmake_p.read_text(encoding="utf-8"),
                    }
                except OSError:
                    pass

            # codegen_manifest.json：优先用 agent 产出的。仅 torch_op 且存在
            # 可解析的真实 plugin 注册时，才允许从注册源码兜底生成 manifest；
            # 禁止在无 op_plugin 时盲拼 torch.ops symbol。
            manifest = None
            cm_content = artifacts.get("codegen_manifest.json")
            if cm_content:
                try:
                    manifest = json.loads(cm_content)
                except json.JSONDecodeError:
                    pass

            profile_kind = self._profile_scaffolding_kind(state)
            manifest_kind = ""
            if isinstance(manifest, dict):
                ct = manifest.get("callable_target")
                if isinstance(ct, dict):
                    manifest_kind = ct.get("kind", "")
            effective_kind = profile_kind or manifest_kind

            registration = self._resolve_torch_registration(state, artifacts)
            # Legacy snapshots/tests may lack a materialized profile.  A real
            # TORCH_LIBRARY_FRAGMENT+m.def pair is sufficient evidence to infer
            # torch_op; absence of registration is never inferred as success.
            if not effective_kind and registration is not None:
                effective_kind = "torch_op"
            if effective_kind == "torch_op":
                contract_error = self._torch_plugin_contract_error(state, artifacts)
                if contract_error is not None:
                    return self._regbase_gate_retry(
                        state, artifacts, contract_error)
                host_offload_error = self._plugin_host_offload_error(state, artifacts)
                if host_offload_error is not None:
                    return self._regbase_gate_retry(
                        state, artifacts, host_offload_error)
            if manifest is None:
                if effective_kind != "torch_op" or registration is None:
                    return self._regbase_gate_retry(
                        state, artifacts,
                        ErrorFeedback(
                            stage_name="codegen",
                            error_type="incomplete_output",
                            message=(
                                "codegen_manifest.json missing; a manifest may be "
                                "derived only from a valid torch op_plugin registration"
                            ),
                            details={
                                "reason": "manifest_missing",
                                "scaffolding_kind": effective_kind,
                            },
                        ))
                namespace, real_name = registration
                op_name = state.op_name or "unknown"
                manifest = {
                    "op_name": op_name,
                    "callable_target": {
                        "kind": "torch_op",
                        "symbol": f"torch.ops.{namespace}.{real_name}",
                    },
                    "_fallback": True,
                }

            if profile_kind:
                self._inject_scaffolding_kind(state, manifest)

            ct = manifest.get("callable_target")
            if not (isinstance(ct, dict) and ct.get("kind") and ct.get("symbol")):
                return self._regbase_gate_retry(
                    state, artifacts,
                    ErrorFeedback(
                        stage_name="codegen",
                        error_type="incomplete_output",
                        message="codegen_manifest.json missing callable_target{kind, symbol}",
                        details={"reason": "callable_target_missing"},
                    ))

            if ct["kind"] == "torch_op":
                # profile injection may have changed kind after the initial check.
                if registration is None:
                    contract_error = self._torch_plugin_contract_error(state, artifacts)
                    if contract_error is not None:
                        return self._regbase_gate_retry(
                            state, artifacts, contract_error)
                    registration = self._resolve_torch_registration(state, artifacts)
                namespace, real_name = registration
                expected_symbol = f"torch.ops.{namespace}.{real_name}"
                if ct["symbol"] != expected_symbol:
                    return self._regbase_gate_retry(
                        state, artifacts,
                        ErrorFeedback(
                            stage_name="codegen",
                            error_type="incomplete_output",
                            message=(
                                f"callable_target.symbol '{ct['symbol']}' conflicts "
                                f"with op_plugin registration '{expected_symbol}'"
                            ),
                            details={
                                "reason": "torch_op_symbol_mismatch",
                                "manifest_symbol": ct["symbol"],
                                "registered_symbol": expected_symbol,
                            },
                        ))

            # Parse decision_log.json if present
            decision_logs = dict(state.decision_logs)
            dl_content = artifacts.get("decision_log.json")
            if dl_content:
                try:
                    dl = json.loads(dl_content)
                    decision_logs[self.name] = dl
                except json.JSONDecodeError:
                    pass

            # deploy_result + build_result：满足 output_contract 要求，确保
            # Runner 的 has_all() 检查通过 → codegen 终止。
            # s5-compile agent 编译后必须已在会话内完成 redeploy 并写出 last_deploy.json；
            # 未写则视为 deploy_failed，不再伪造成功结果。
            deploy_result = self._read_deploy_result(state)
            if deploy_result is None:
                return self._handle_regbase_failure(
                    state.with_updates(last_error=ErrorFeedback(
                        stage_name="codegen", error_type="deploy_failed",
                        message="s5-compile completed but no last_deploy.json found — "
                                "agent did not run `ascendc-devkit redeploy --workspace <run_dir>`")),
                    _FakeAgentResult(error_type="ENV"), "s5")
            build_result = BuildResult(
                passed=deploy_result.smoke_passed and bool(deploy_result.run_package))

            if not build_result.passed:
                # smoke 失败分流（镜像 Membase D4，codegen.py:2691-2723）：
                #   kernel 已执行（507035/507057/AICORE 等运行期崩溃，vector error）→
                #     非 codegen 可修 —— 带 deploy_result(smoke_passed=False) 前进交
                #     precision_debug scope_guard 分类（scope_guard → vector_error_debug）。
                #   host 阶段 / 歧义区 → 维持 CK 重试/rollback（codegen 自闭环修脚手架）。
                # 新鲜度锚点：只信本轮 smoke 失败日志（deploy_result.smoke_log_path），
                # build 阶段失败不读 stale smoke.log（review m6）。
                smoke_phase = self._regbase_smoke_phase(
                    state, deploy_result.smoke_log_path)
                if smoke_phase == "kernel":
                    from ascendc_devkit.infra.logger import Logger
                    Logger.warn(
                        "codegen s5: redeploy smoke_passed=False 但 kernel 已执行 "
                        f"(smoke_phase={smoke_phase}) —— 不重试/不回退，带 "
                        "deploy_result(smoke_passed=False) 前进交 precision_debug "
                        "scope_guard/vector_error_debug 分类")
                    self._bash(dr, "append-history", rd,
                               "STAGE_COMPLETE",
                               "s5 redeploy smoke 失败但 kernel 已执行，交 precision_debug")
                    return state.with_updates(
                        codegen_phase="done",
                        last_error=None,
                        generated_sources=artifacts,
                        codegen_iterations=state.codegen_iterations + 1,
                        codegen_consecutive_failures=0,
                        codegen_pending_agent="",
                        codegen_pending_resume_point="",
                        decision_logs=decision_logs,
                        codegen_manifest=manifest,
                        build_result=build_result,
                        deploy_result=deploy_result,
                    )
                return self._handle_regbase_failure(
                    state.with_updates(last_error=ErrorFeedback(
                        stage_name="codegen", error_type="deploy_failed",
                        message=f"s5-compile redeploy smoke_passed=False; "
                                f"build_result.passed=False — fix compilation or test errors")),
                    _FakeAgentResult(error_type="CK"), "s5")

            self._bash(dr, "append-history", rd,
                       "STAGE_COMPLETE", "编码+编译全部完成")

            # last_error 必须清：regbase s5 是「成功即 done」路径，但重试可能把
            # 上一迭代的 deploy_failed 残留挂在 state 上——runner 的 own_error 判定
            # (runner.py 读 sticky last_error) 会把它当成本轮失败 → fail_strategy=halt
            # 误杀已 smoke_passed=true 的 stage（run 20260805-144048 root cause）。
            # s5_rollback 预算同步重置：s5 成功 = 修复生效，回退预算回满。
            self._reset_s5_rollback(rd)
            return state.with_updates(
                codegen_phase="done",
                last_error=None,
                generated_sources=artifacts,
                codegen_iterations=state.codegen_iterations + 1,
                codegen_consecutive_failures=0,
                codegen_orphan_streak=0,
                codegen_pending_agent="",
                codegen_pending_resume_point="",
                decision_logs=decision_logs,
                codegen_manifest=manifest,
                build_result=build_result,
                deploy_result=deploy_result,
            )
        else:
            return self._handle_regbase_failure(state, agent_result, "s5")


    def _transition_regbase_needs_agent_done(
            self, state: State, agent_result) -> State:
        """目标 agent 完成后处理。"""
        agent_status = getattr(agent_result, 'status', 'failed') if agent_result else "failed"

        if agent_status == "ok":
            # 清除暂存 → 保持 codegen_phase 不变，下轮 actions 重调原 agent
            return state.with_updates(
                codegen_pending_agent="",
                # 保留 codegen_pending_resume_point 供注入 agent_completed=true
            )
        else:
            # failed/paused → 升级为 PAUSED
            reason = ""
            if agent_result and hasattr(agent_result, 'metrics') and agent_result.metrics:
                reason = agent_result.metrics.get('failure_reason', '')
            return state.with_updates(
                codegen_pending_agent="",
                codegen_pending_resume_point="",
                last_error=ErrorFeedback(
                    stage_name="codegen", error_type="exhausted",
                    message=f"NEEDS_AGENT target failed: {reason or agent_status}"))


    def _handle_regbase_failure(self, state: State, agent_result,
                                 phase: str, message: str = "") -> State:
        """阶段失败处理：per-type 计数器重试 → 计数器耗尽后按阶段确定性升级。

        E(t) 加权累计已移除：重试预算收敛为 meta.json 的 per-type 计数器
        （RETRY_LIMITS）。计数器耗尽后保留原状态跳转结构（retry → rollback →
        halt），但升级决策由阶段/类别确定性给出，不再按错误码加权：
          - s2 分析耗尽 → PAUSED（交付物产不出，人工介入）
          - s4 编码耗尽 → 回退 s2（设计可能是根因）
          - s5 编译耗尽 → 回退 s4（代码需修），受 s5_rollback 预算约束防 s4↔s5 乒乓
        """
        error_type = (getattr(agent_result, 'error_type', 'OTH') or "OTH"
                      if agent_result else "OTH")
        # 消息注入：写入 history.log 供审计；Layer1 重试时 runner 会重 spawn，
        # message 落 last_error.md，由 s2/s4 重试轮 prompt 的
        # _render_last_error_diagnostic_block 注入段读取（本文件写、重试轮读）。
        if message:
            try:
                from ascendc_devkit.infra.logger import Logger
                Logger.warn(f"codegen regbase {phase} failure: {message}")
            except Exception:  # noqa: BLE001 — logging best-effort
                pass
            try:
                rd = self._regbase_record_dir(state)
                (Path(rd) / "last_error.md").write_text(
                    message, encoding="utf-8")
            except Exception:  # noqa: BLE001 — best-effort
                pass

        # Layer 0: 读取 meta.json 的 retries
        rd = self._regbase_record_dir(state)
        meta_path = Path(rd) / "meta.json"
        retries: dict = {}
        if meta_path.exists():
            try:
                retries = json.loads(
                    meta_path.read_text(encoding="utf-8")).get("retries", {})
            except Exception:
                pass

        # per-type 重试计数器（E(t) 移除后的唯一重试预算）
        counter_key, limit = RETRY_LIMITS.get(
            phase, ("stage4_selfcheck", 8))
        used = retries.get(counter_key, {}).get("used", 0)
        if used < limit:
            retries[counter_key] = {"used": used + 1, "limit": limit}
            self._update_meta_retries(rd, retries)
            return state  # 未超限，Runner 自动重试

        # 计数器耗尽 → 按阶段确定性升级（保留原状态跳转结构，去 E(t) 加权）
        retries[counter_key] = {"used": used + 1, "limit": limit}
        self._update_meta_retries(rd, retries)

        # 带上最近一次具体失败原因（调用方 s5 失败分支常先 with_updates(last_error=…)
        # 传入 CMakeLists missing / deploy_failed 等细节，供回退后的 s4 重做 agent 通过
        # last_error.md 注入段拿到——否则 message 只剩笼统的 "failed after N attempts"）。
        prev_reason = ""
        prev_err = getattr(state, "last_error", None)
        if prev_err is not None and getattr(prev_err, "message", None):
            prev_reason = str(prev_err.message).strip()[:300]

        def _with_reason(base: str) -> str:
            return (f"{base} (previous: {prev_reason})"
                    if prev_reason else base)

        if phase == "s2":
            # s2 产不出前置交付物 → 人工介入
            return state.with_updates(
                last_error=ErrorFeedback(
                    stage_name="codegen", error_type="exhausted",
                    message=_with_reason(
                        f"s2 failed after {used + 1} attempts "
                        f"({counter_key}={used + 1}/{limit})")))
        if phase == "s4":
            # s4 自检/编码持续失败 → 回退 s2（设计可能是根因）
            return state.with_updates(
                codegen_phase="s2",
                codegen_s4_sub_stage="",
                last_error=ErrorFeedback(
                    stage_name="codegen", error_type="deploy_failed",
                    message=_with_reason(
                        f"s4 failed after {used + 1} attempts, "
                        "rolling back to s2")))
        # phase == "s5"：回退 s4 修代码，受 s5_rollback 预算约束防 s4↔s5 无限乒乓
        rb = retries.get("s5_rollback") or {}
        rb_used = rb.get("used", 0)
        rb_limit = rb.get("limit", S5_ROLLBACK_LIMIT)
        if rb_used >= rb_limit:
            return state.with_updates(
                last_error=ErrorFeedback(
                    stage_name="codegen", error_type="exhausted",
                    message=_with_reason(
                        f"s5 failed after {used + 1} attempts and "
                        f"s4↔s5 rollback budget exhausted "
                        f"(s5_rollback={rb_used}/{rb_limit})")))
        retries["s5_rollback"] = {"used": rb_used + 1, "limit": rb_limit}
        self._update_meta_retries(rd, retries)
        return state.with_updates(
            codegen_phase="s4",
            last_error=ErrorFeedback(
                stage_name="codegen", error_type="deploy_failed",
                message=_with_reason(
                    f"s5 failed after {used + 1} attempts, "
                    "rolling back to s4")))


    def _regbase_gate_retry(self, state: State, artifacts: dict,
                            error: ErrorFeedback, phase: str = "s5") -> State:
        """s5 产物质量门失败 → 定向修复路由（§1.15 单点，与 Membase 同判据门对齐）。

        plugin 注册 / 维10③ host 往返 / manifest 结构等机械门命中 = 「会话内可修的
        产物不合格」，走 `_handle_regbase_failure` 既有预算链：s5 重试（last_error
        经 s5 重跑 prompt 的【上次重试错误】段注入，message 落 last_error.md 供回退
        s4 后的重做轮注入）→ 计数器耗尽回退 s4 改码 → s5_rollback 耗尽 exhausted。

        禁止 `codegen_phase="done"` + sticky last_error 的旧形态：`_actions_regbase`
        对 done 恒返空 actions，artifact-retry 与 resume 均无法重派修复 agent →
        stage 必然 fail_strategy=halt 且 resume 死锁；且门先于 smoke 分类 return
        会抢跑「kernel 已执行 → D4 前进 precision_debug」的路由
        （run 20260903-141248-2cd845 维10③ 分支实证）。
        """
        self._persist_sources(state, artifacts)
        detail = getattr(error, "details", None) or {}
        extra = " ".join(
            f"[{k}={v}]" for k, v in detail.items()
            if k in ("reason", "plugin_file", "line", "pattern"))
        return self._handle_regbase_failure(
            state.with_updates(last_error=error, generated_sources=artifacts),
            _FakeAgentResult(error_type="INP"), phase,
            message=f"{error.message} {extra}".strip())


    def _build_s2_prompt(self, state: State, rd: str, skill_root: str,
                         agent_s2: str, code_path: str) -> str:
        """构造 ascendc-dev-s2-analysis 的 prompt（对应 C.2 模板）。"""
        design_doc = state.design_doc or ""
        vf_ref_dir = self._regbase_vf_ref_dir(state)
        op_name = state.op_name or ""
        ref_op = str(state.reference_op_path or "")
        design_spec_path = Path(rd) / "design_spec.json"
        tiling_path = Path(rd) / "tiling_strategy.json"
        kernel_arch_path = Path(rd) / "kernel_architecture.json"

        lines = [
            "【上下文】",
            f"- 算子名: {op_name}，开发模式: 新增",
            f"- 开发记录目录: {rd}",
            f"- SKILL_ROOT: {skill_root}",
            f"- AGENT_ROOT: {agent_s2}",
            "",
            "【需求来源 — 直接使用，不收集】",
        ]
        scaffold_kind = self._profile_scaffolding_kind(state)
        lines.extend([
            "",
            "【仓库调用协议 — 强制契约，优先级高于详设交付矩阵】",
            f"- profile.scaffolding.selected: {scaffold_kind or '(未解析)'}",
            "- selected=torch_op 时，op_plugin/*.cpp、TORCH_LIBRARY_FRAGMENT 和 "
            "m.def 注册均为必交付；不得因详设写“PTA 可选/不交付”而省略",
            "- kernel_architecture.json 声明的 plugin_code 不得被 Markdown 详设覆盖",
            "- 若详设与本契约冲突，在 clarification.md 记录 CTX_DRIFT，并以本契约生成 "
            "coding_index.md/coding_plan.md",
        ])
        if design_doc:
            lines.append(f"- 主 Agent 注入了 design_doc（Markdown 详设路径）→ 优先使用: {design_doc}")
        else:
            lines.append("- JSON 模式：设计文件位于 $RECORD_DIR 下")
            if design_spec_path.exists():
                lines.append(f"  - {design_spec_path} — IO spec / 公式 / dtype")
            if tiling_path.exists():
                lines.append(f"  - {tiling_path} — 切分方案")
            if kernel_arch_path.exists():
                lines.append(f"  - {kernel_arch_path} — section 声明")

        # TDD 验收用例（test_design 产物）：Membase 路径的 _build_codegen_prompt
        # 早已把 test_cases.json 列为「codegen 须满足」，Regbase 多步编排此前
        # 只物化到 staging 却未在 prompt 里指名——补上这处口子，让 s2/s4 的编码
        # 有边界依据（不满足即回归失败）。
        tc_path = Path(rd) / "test_cases.json"
        if tc_path.exists():
            lines.append(
                f"- 验收用例（TDD，codegen 须满足）: {tc_path} — "
                "L0/L1/L2 用例清单（形状/dtype/attrs/精度阈值）；实现须满足其组合与"
                "边界覆盖，不得依赖子集/安全输入蒙混过关")

        lines.extend([
            "",
            "【预置输入 — 已写入 RECORD_DIR/meta.json 或 prompt 注入，S2 直接读取】",
            "- 编程模型 / code_path / dev_mode / ref_op",
            "",
            "【已在主 SKILL 收集的项（可选，缺失不影响流程）】",
            f"- design_doc: {design_doc or '(未提供)'}",
            f"- vf_ref_dir: {vf_ref_dir}（仅 A5 Regbase）",
            "",
            "【零交互纪律】",
            "- 禁止 AskUserQuestion",
            "- 设计文档无法读取 → status=FAILED, error_type=INP",
            "- 设计文档缺少关键字段，且默认决策表无法覆盖 → status=FAILED, error_type=INP",
            "- 设计文档缺少关键字段，但默认决策表可覆盖 → 标记 [默认决策]",
            "",
            "【编排计划 orchestration_plan.json 生成规范 — 强制】",
            "- 按 [`references/orchestration-plan.schema.json`]($SKILL_ROOT/references/orchestration-plan.schema.json) "
            "生成 `$RECORD_DIR/orchestration_plan.json`——Stage 4 状态机的**唯一权威输入**，框架只读 JSON 不再解析 markdown。",
            "- `sub_stages` 按执行顺序列出全部 sub-stage：id 带 `4.` 前缀（如 `4.C.2`），含 checkpoint_group/execution_group/kind/deliverables/status。",
            "- `execution_group` 是单次 s4-coding Agent 工作单元，按职责合并连续步骤：host_tiling=4.0/A/B1/B2；kernel_base=C.0/C.1/C.2（或首个 VT 前的基础实现）；每个 VT 独立唯一组；kernel_finalize=VT 后集成与 Kernel 收尾；finalize=API/Plugin/E/F。复杂计划可加数字后缀。**多模板算子（template_division.json 含 2+ 模板）时，Compute 集成步骤按模板拆子步骤（如 C.3.T1/C.3.T2），每个子步骤独占一个 execution_group（如 kernel_finalize_t1/kernel_finalize_t2），互不混批——单次 s4-coding 会话只集成一个模板的 VF 调用链。**",
            "- 强制边界：同名 execution_group 必须连续；kind=vf 必须独立；非 VF 组不得跨越 VF；每个步骤只属于一个 execution_group。",
            "- `deliverables` 为**供人读/审计的说明列表**（建议填真实文件路径或通配符，如 `op_kernel/{op_name}.h`；亦可填 `(CopyIn 实现)` 类描述）",
            "——框架不再按它做磁盘校验或格式校验，Stage 4 完成判定只信 s4-coding 的返回。",
            "- C 系列多个子步骤（C.2/C.3/C.4）可各自列出同一 kernel 类文件路径，也可用 `*.h` 通配符；VT 步骤 kind=vf、deliverables 可为空。",
            "- 初始 `status` 全部填 `pending`（框架 dispatch 负责写 done/exhausted，agent 禁止改动）。",
            "- 生成后自检：合法 JSON + 全部字段符合 schema + execution_group 连续性/VF 单例边界成立（详见 §2.7）。",
            "",
            "【建议默认值 — 详设未明确时自动采用】",
            "| 1 | 分核方式 | 单核（blockDim=1） |",
            "| 2 | 核内 tile 策略 | 保守单 tile（不拆分） |",
            "| 3 | tail block 处理 | 连续 mask 截断 |",
            "| 4 | 双 buffer | 关闭（BUFFER_NUM=1） |",
            "| 5 | dtype 支持 | 仅详设明确列出的 |",
            "| 6 | 对齐假设 | 32 字节对齐 |",
            "| 7 | TilingKey 路由 | 单一模板，统一用 ASCENDC_TPL 参数化 |",
            "| 8 | 属性默认值 | int→0, float→0.0, bool→false |",
            "| 9 | workspace 空间 | 0 |",
            "",
            "【编排器阶段契约】\n"
            "- 本编排器为 3 阶段流水线：s2（分析）→ s4（编码）→ s5（编译）。\n"
            "- 你属于 s2。COMPLETED 且产物检查通过后，编排层会自动将阶段推进到 s4。\n"
            "- 因此 COMPLETED 时必须返回 `next_stage=4`，禁止返回 `next_stage=3` 或其它值。\n"
            "- 失败时返回 FAILED 并附带准确的 `error_type`；编排层会根据错误权重做 Layer1 "
            "重试 / Layer2 回退 / halt 的决策，不需要你在 RETURN 中指定跳转目标。",
        ])
        if ref_op:
            lines.insert(-3, f"- ref_op: {ref_op}（参考算子代码路径，缺失不影响流程）")
        # 上轮失败诊断注入（s2 重试轮）：_handle_regbase_failure 写 last_error.md，
        # s2 重做 agent 先修上轮问题再分析，避免盲目重跑。
        lines.extend(self._render_last_error_diagnostic_block(rd))
        return "\n".join(lines)


    @staticmethod
    def _render_last_error_diagnostic_block(rd: str) -> list[str]:
        """上轮失败诊断注入段（s2/s4 重试共用，§1.15 单点渲染）。

        last_error.md 写入端：dispatch（error_detail，codegen_s4.py）与
        ``_handle_regbase_failure``（s2/s5 失败 message）；清除端：dispatch
        COMPLETED 提交（codegen_s4._clear_last_error_md）。文件存在即注入，
        不猜内容语义——agent 自行读取处理。文件不存在 → 空段。
        """
        p = Path(rd) / "last_error.md"
        if not p.is_file():
            return []
        return [
            "",
            "【上次失败诊断 — 必须先修复】",
            f"- 读取并处理: {p}",
            "- 这是上一轮失败后框架记下的待修问题；先针对性修复，再交付本组产物。",
            "- 若你确认该诊断对应的问题已在本次会话中被修复，可忽略并正常交付。",
        ]


    def _build_s4_prompt(self, state: State, rd: str,
                         sub_stages: list[str] | str,
                         execution_group: str, checkpoint_group: str,
                         code_path: str,
                         checkpoint_groups: dict[str, str] | None = None) -> str:
        """构造 ascendc-dev-s4-coding 的 prompt（对应 C.3 S4 模板）。"""
        if isinstance(sub_stages, str):
            sub_stages = [sub_stages]
        sub_stage = sub_stages[0]
        sub_stage_list = ", ".join(sub_stages)
        checkpoint_groups = checkpoint_groups or {
            sid: checkpoint_group for sid in sub_stages}
        checkpoint_group_list = ", ".join(
            f"{sid}={checkpoint_groups.get(sid, 'UNKNOWN')}"
            for sid in sub_stages)
        design_doc = state.design_doc or ""
        ref_op = str(state.reference_op_path or "")
        op_name = state.op_name or ""
        skill_root = self._regbase_skill_root(state)
        agent_s4 = self._regbase_agent_root(state, "ascendc-dev-s4-coding")

        lines = [
            "【上下文】",
            f"- 算子名: {op_name}",
            f"- 开发记录目录: {rd}",
            f"- SKILL_ROOT: {skill_root}",
            f"- AGENT_ROOT: {agent_s4}",
            f"- current_sub_stage: {sub_stage}",
            f"- current_sub_stages: [{sub_stage_list}]",
            f"- execution_group: {execution_group}",
            f"- checkpoint_group: {checkpoint_group}",
            f"- checkpoint_groups: [{checkpoint_group_list}]",
        ]
        scaffold_kind = self._profile_scaffolding_kind(state)
        lines.extend([
            "",
            "【仓库调用协议 — 强制契约，优先级高于详设/coding_plan】",
            f"- profile.scaffolding.selected: {scaffold_kind or '(未解析)'}",
            "- selected=torch_op 时必须生成 op_plugin/*.cpp，且包含 "
            "TORCH_LIBRARY_FRAGMENT(namespace, m) + m.def(\"op(...)\")",
            "- 详设或 coding_plan 中“无 op_plugin/本期不交付”与该契约冲突时，"
            "忽略该错误裁剪并补齐 plugin；不得以设计决策覆盖 repository profile",
        ])
        lines.extend([
            "",
            "【已在主 SKILL 收集的项】",
            f"- code_path: {code_path}（也写入 meta.json.code_path）",
        ])
        if design_doc:
            lines.append(f"- design_doc: {design_doc}（Markdown 详设路径）")
        if ref_op:
            lines.append(f"- ref_op: {ref_op}（参考算子代码路径）")
        # TDD 验收用例（test_design 产物）：Regbase 多步编排此前未在 prompt 指名
        # test_cases.json（只物化未消费）。补上，让每个 execution_group 的编码有
        # 明确的边界依据（形状/dtype/attrs 组合与边界覆盖须满足）。
        tc_path = Path(rd) / "test_cases.json"
        if tc_path.exists():
            lines.append(
                f"- 验收用例（TDD，须满足）: {tc_path} — "
                "编码须覆盖其形状/dtype/attrs 组合与边界，勿实现仅满足单一形状的窄解")
        lines.extend([
            "",
            "【s4 完成信号】",
            f"- 本次只授权 execution_group={execution_group}，按顺序执行：[{sub_stage_list}]。",
            "- 必须对列表中每个 sub-stage 分别执行原有编码、自检并写 selfcheck_<id>.md；"
            "合并会话不合并质量检查。",
            f"- 全部完成时返回 `completed_sub_stages=[{sub_stage_list}]`。",
            "- 中途失败时，completed_sub_stages 只能填写从列表起点开始的已完成连续前缀，"
            "并填写 failed_sub_stage；禁止跳项或越界。",
            "- next_sub_stage 只作审计；编排层依据 orchestration_plan.json 自行计算后续步骤。",
            "",
            "【零交互约束 — 最高优先级】",
            "- 禁止 AskUserQuestion",
            "- 交互模式固定为 auto（每步不确认，直接完成）",
            "",
            "【参考来源纪律】",
            "- 从 coding_index.md 参考代码列 + 详设章节（JSON 或 Markdown）+ 知识库模板生成",
            "- 禁止自行全局搜索参考实现",
            "- A5 Compute 步骤：VF 指令参考已由 ascendc-vf-test-agent 查阅并缓存，",
            "  s4-coding 直接读 coding_index_kb_cache.md 即可",
            "- sub-stage 为 ACLNN API / Plugin 步骤时，参考目标仓现有算子的",
            "  aclnn_*.cpp / *_plugin.cpp 文件模式生成，遵循仓特定的注册宏与 include 路径",
        ])
        # 上轮失败诊断注入：s5→s4 回退（_handle_regbase_failure 写 last_error.md）或
        # s4 内部 retry（dispatch error_detail 写）留下的待修问题，必须注入重做轮。
        # 某 group 完成提交（dispatch COMPLETED）时文件被清除，不会陈旧残留。
        lines.extend(self._render_last_error_diagnostic_block(rd))
        return "\n".join(lines)


    def _build_vf_prompt(self, state: State, rd: str, sub_stage: str,
                          code_path: str,
                          previous_vf_results: list[str] | None = None) -> str:
        """构造 ascendc-vf-test-agent 的 prompt（对应 C.3 VF 模板）。"""
        design_doc = state.design_doc or ""
        ref_op = str(state.reference_op_path or "")
        op_name = state.op_name or ""
        skill_root = self._regbase_skill_root(state)
        agent_vf = self._regbase_agent_root(state, "ascendc-vf-test-agent")
        vf_ref_dir = self._regbase_vf_ref_dir(state)
        prev_list = previous_vf_results or []

        lines = [
            "【上下文】",
            f"- 开发记录目录: {rd}",
            f"- 算子名: {op_name}",
            f"- current_sub_stage: {sub_stage}",
            f"- SKILL_ROOT: {skill_root}",
            f"- AGENT_ROOT: {agent_vf}",
            f"- output_dir: {rd}/vf_verified",
            f"- previous_vf_results: {chr(10).join(prev_list) if prev_list else '(首次为空)'}",
            "",
            "【已在主 SKILL 收集的项】",
            f"- code_path: {code_path}",
        ]
        if design_doc:
            lines.append(f"- design_doc: {design_doc}")
        if ref_op:
            lines.append(f"- ref_op: {ref_op}")
        if vf_ref_dir:
            lines.append(f"- vf_ref_dir: {vf_ref_dir}（仅 A5 Regbase；VF 指令参考文档目录路径）")
        lines.extend([
            "",
            "【零交互约束】禁止 AskUserQuestion",
        ])
        return "\n".join(lines)


    def _build_s5_prompt(self, state: State, rd: str, code_path: str) -> str:
        """构造 ascendc-dev-s5-compile 的 prompt（对应 C.4 模板）。"""
        op_name = state.op_name or ""
        skill_root = self._regbase_skill_root(state)
        agent_s5 = self._regbase_agent_root(state, "ascendc-dev-s5-compile")

        # 从 meta.json 读取 compile_cmd
        compile_cmd = ""
        meta_path = Path(rd) / "meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                compile_cmd = meta.get("compile_cmd", "")
            except Exception:
                pass

        run_dir = self._run_dir(state)

        lines = [
            "【上下文】",
            f"- 算子名: {op_name}",
            f"- 开发记录目录: {rd}",
            f"- SKILL_ROOT: {skill_root}",
            f"- AGENT_ROOT: {agent_s5}",
            "",
            "【编译指令】",
            f"- code_path: {code_path}（也写入 meta.json.code_path）",
            f"- 编译指令: {compile_cmd or '（从 meta.json 读取；缺失时 s5-compile 自行确认）'}",
            "",
            "【部署闭环】",
            f"- run_dir: {run_dir}",
            "编译完成后，**必须在会话内**执行以下命令以完成部署闭环：",
            f"  `ascendc-devkit redeploy --workspace {run_dir}`",
            "redeploy 会读取本次 run 的快照执行 build → install → smoke，并将结果写入：",
            f"  `{run_dir}/artifacts/debug/{op_name}/last_deploy.json`",
            "只有 redeploy 完成后，transition 才会读取 last_deploy.json 确认 smoke_passed，否则视为 deploy_failed。",
            "",
            "【s5 完成信号】",
            "- 编译通过且 redeploy 的 `smoke_passed=true` 后，使用 dev_record.sh 标记 Stage 5 ✅。\n"
            "- **smoke 失败但 kernel 已执行（vector error 类，如 507035/507057/AICORE）**：这是运行期"
            " kernel 缺陷，**不是 codegen 可修的编译/脚手架问题**——禁止继续重试编译，正常收尾返回完成，"
            "编排层 `_transition_regbase_s5()` 会从 smoke.log 分类出 kernel 阶段并带 "
            "`deploy_result(smoke_passed=False)` 前进交 precision_debug scope_guard/vector_error_debug 分类。\n"
            "- 编排层 `codegen.py:_transition_regbase_s5()` 会校验 `codegen_manifest.json` 与 "
            "`last_deploy.json`，随后将 `codegen` stage 置为 `done`，整个 codegen 阶段结束。\n"
            "- 禁止在 redeploy 未完成时返回成功；smoke 失败但属 kernel 已执行（vector error）场景除外（见上）。",
        ]
        if state.last_error is not None:
            lines.append("")
            lines.append("【上次重试错误】")
            lines.append(f"- error_type: {state.last_error.error_type}")
            lines.append(f"- message: {state.last_error.message}")
            lines.append("- 请参考以上错误整改，确保本轮修复后不再触发相同问题。")
        lines.extend([
            "",
            "【零交互约束】",
            "- 禁止 AskUserQuestion",
        ])
        return "\n".join(lines)


    @staticmethod
    def _workspace(state: State):
        return getattr(state, "_workspace", None)


    @staticmethod
    def _run_dir(state: State) -> str:
        ws = RegbaseMixin._workspace(state)
        return str(ws.dir) if ws is not None else "<run_dir>"


    @staticmethod
    def _classify_smoke_text(full: str) -> str | None:
        """从 smoke 完整日志文本分类失败阶段："kernel" | "host" | None。

        Part B（20260810）的分类词汇表（§1.12 结构信号，不认算子名）：
        - "kernel"：kernel 执行过（507035/507057/AICORE/aivec/越界文本）→ 维持 D4 交 precision。
        - "host"：kernel 未执行（tiling/infershape/attr 接线/注册/launch，EZ1008/561001/561002
          家族 + "Failed to execute tiling/inferShape"）→ 回 codegen（生产者自闭环修自己的
          host 脚手架产物，§2.9）。判据是黑名单结构：只枚举 kernel 执行证据，host 侧是宽信号，
          新错误码自动归位 codegen。
        - None：无证据/未知 → 歧义区，交给 coder 判归属（不静默默认 D4）。
        507057 类（kernel 崩溃但根因 host OpDef）已由 F5 静态门 pre-deploy 拦截，正常到不了
        这里；到了也按 kernel 处理（运行期崩溃，根因追溯走 precision）——已知局限。
        """
        # kernel 执行证据（特异性强，优先）
        for mk in ("507035", "507057", "AICORE", "aivec",
                   "GM address exceeds", "UB out of bounds"):
            if mk in full:
                return "kernel"
        # host 阶段证据（宽信号：错误码家族 + host 函数/阶段文本）
        for hk in ("EZ1008", "561001", "561002", "EZ1001", "EZ1006", "EZ1007",
                   "Failed to execute tiling", "Failed to execute inferShape",
                   "GetShapeAttrsInfo", "GetWorkspace", "kernel never executed",
                   "TilingFunc", "inferShape"):
            if hk in full:
                return "host"
        return None


    def _invalidate_last_deploy(self, state) -> None:
        """派发会跑 redeploy 的 agent 前清掉既存 last_deploy.json，使「文件存在」
        唯一由本次 agent 真的跑了 redeploy 决定（absence 即证据，§1.2 可诊断）。

        防止上一 codegen iteration 的 smoke_passed 残留被沿用：last_deploy.json
        路径含 <run_id>，跨 run 不残留，但同 run 内 iter N 写下 smoke_passed=True、
        iter N+1 没重跑 redeploy 时会被 _read_deploy_result 误读为成功
        （run 20260730-072625-bec36b P2）。仅在 fresh spawn 前调用，不动 resume
        路径（同一次 agent 会话的 redeploy 是连贯的）。
        """
        ws = self._workspace(state)
        if ws is None:
            return
        op_name = (state.op_name
                   or (state.op_identity.spec.name if state.op_identity else "op"))
        p = ws.dir / "artifacts" / "debug" / op_name / "last_deploy.json"
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass


    @staticmethod
    def _cmake_on_disk(state) -> bool:
        """CMakeLists.txt 契约信号以磁盘为准（§2.3 I/O=文件）。

        s5-compile 按 skill 契约把构建文件写到 op_dir，不保证进入回传
        artifacts dict —— 用 dict key 判定会在「产物已落盘」时误判缺失
        并触发死循环（run 20260730-072625-bec36b 的致命断链点）。
        """
        code_path = state.op_dir or ""
        return bool(code_path) and (Path(code_path) / "CMakeLists.txt").is_file()


    def _reset_s5_rollback(self, rd: str) -> None:
        """s5 成功后重置 s5_rollback 回退预算（修复生效 → 预算回满）。"""
        meta_path = Path(rd) / "meta.json"
        if not meta_path.exists():
            return
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            retries = meta.get("retries") or {}
            if "s5_rollback" in retries:
                retries["s5_rollback"] = {"used": 0, "limit": S5_ROLLBACK_LIMIT}
                meta["retries"] = retries
                meta_path.write_text(
                    json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:  # noqa: BLE001 — best-effort reset
            pass
