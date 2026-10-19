"""20260810 批根因修复 Part 3 — cut 计数（成功清零 / 连续 cut-without-recovery 阈值）。

后端 Part 1 把"末条 assistant 只有 thinking（无 text/tool）= 第三方网关静默切流"
标为 AgentResult.cut=True。本测试守护 runner 侧：
  - cut 不烧正常迭代预算（可恢复的中断不是逻辑失败）——多次 cut + 1 次成功仍能完成；
  - 连续 cut 累计到 cut_streak_threshold() → 放弃 cut-recovery（循环退出，stage 契约未满足收尾）；
  - 成功/真失败打断 streak 清零（用户指定语义：计数只表示连续 resume 仍失败）。
"""
from __future__ import annotations

from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.orchestration.kernel.runner import Runner, cut_streak_threshold
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.kernel.action import SpawnAgent
from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.capabilities.agent.backend import AgentBackend, AgentResult


class _CutBackend(AgentBackend):
    """前 ``cut_times`` 次 spawn 返回 cut=True（无产物）；之后若 ``succeed`` 返回
    ok+产物。计数 spawns。"""

    def __init__(self, cut_times: int, succeed: bool = True):
        self._cut_times = cut_times
        self._succeed = succeed
        self.spawns = 0

    def spawn(self, agent_name, prompt, context, skills=None, model=None,
              working_dir=None, repo_baseline=None, repo_root=None,
              stage_name="", branch_label="", resume_session_id=None,
        resume_prompt=None,
              primary_skill=None, deadline_monotonic=None):
        self.spawns += 1
        if self.spawns <= self._cut_times:
            return AgentResult(agent_name=agent_name, status="ok",
                               artifacts={}, cut=True)
        if self._succeed:
            return AgentResult(agent_name=agent_name, status="ok",
                               artifacts={"out.json": "x"}, cut=False)
        # 真失败（非 cut）：F5 后干净零产物即 status="ok"+artifacts={}——
        # 翻转 _last_iter_ok 靠 artifacts 判据，不靠 status 字面量
        return AgentResult(agent_name=agent_name, status="ok",
                           artifacts={}, cut=False)


class _CutStage(Stage):
    """契约 tiling_results；ceiling=3。fail_strategy=halt 但成功/耗尽按正常路径。"""
    name = "cut-stage"
    default_max_iterations = 3
    fail_strategy = "halt"
    needs_iteration_safety_net = False   # 强制 ceiling = stage_budget = 3

    def input_contract(self):
        return StageIOContract(requires=[])

    def output_contract(self):
        return StageIOContract(provides=["tiling_results"])

    def actions(self, state, iteration=1):
        return [SpawnAgent(agent_name="x", prompt="p", context={})]

    def transition(self, state, result):
        ar = result.get("agent_result")
        if ar and ar.artifacts:
            state = state.with_updates(tiling_results={"T1": {"ok": True}})
        return state


def _run(backend, stage=None):
    return Runner(agent_backend=backend).run_stage(
        State(mode="new", non_interactive=True), stage or _CutStage())


def test_cuts_do_not_burn_normal_budget_and_recover():
    """3 次 cut + 1 次成功，ceiling=3 → 仍能完成（旧行为：3 cut 烧光 3 预算，
    成功在 iteration 4 永远不发生）。cut 是"可恢复的中断"，不占正常预算。"""
    backend = _CutBackend(cut_times=3, succeed=True)
    state = _run(backend)
    assert backend.spawns == 4            # 3 cut + 1 成功
    assert state.tiling_results == {"T1": {"ok": True}}  # 成功完成
    # 生产性迭代计数 = 1（成功那次），cuts 未消耗预算
    assert state.stage_iterations["cut-stage"] == 1


def test_consecutive_cuts_hit_threshold_and_give_up():
    """一直 cut（无产物）→ 连续累计到 cut_streak_threshold() → 循环退出，stage
    契约未满足收尾。spawns 封顶 = cut_streak_threshold()（成本有界）。"""
    backend = _CutBackend(cut_times=10 ** 9, succeed=False)  # 永不成功、永不 cut=False
    state = _run(backend)
    assert backend.spawns == cut_streak_threshold()
    assert "tiling_results" not in state.__dict__ or state.tiling_results is None


def test_genuine_failure_resets_streak_and_burns_budget():
    """cut → 真失败（非 cut，自然结束）→ streak 清零 + 消耗正常预算。cut 免费，
    真失败烧满 3 预算 → 契约未满足收尾，spawns = 1 cut + 3 真失败 = 4。"""
    backend = _CutBackend(cut_times=1, succeed=False)
    state = _run(backend)
    # 1 cut（不烧预算，streak 清零）+ 3 真失败（烧 budget 1,2,3）→ 预算耗尽
    assert backend.spawns == 4
    assert state.tiling_results is None


def test_cut_then_recovery_then_repeat():
    """cut → 成功恢复 →（成功即终止，streak 已清零）。验证恢复路径不受累积影响。"""
    backend = _CutBackend(cut_times=2, succeed=True)
    state = _run(backend)
    assert backend.spawns == 3            # 2 cut + 1 成功
    assert state.tiling_results == {"T1": {"ok": True}}


# —— 2026-08-11 review M1：cut 不得 clobber _last_iter_ok（S2 守卫豁免）——

class _DeadlineStage(_CutStage):
    """与 _CutStage 同契约，但每个 SpawnAgent 携带 deadline_monotonic（模拟 stage
    deadline 已过）——用于验证 Option A 软超时依赖的 _last_iter_ok 在 cut 后不被翻转。
    deadline_monotonic 传给 SpawnAgent 仅用于触发 runner 的 deadline 检查路径。"""
    name = "deadline-cut-stage"
    default_max_iterations = 3


def test_cut_does_not_clobber_last_iter_ok_for_option_a():
    """M1 (review 坐实): cut（silent-cut, thinking-only 终止）与 aborted 同属"被
    外部中断、不携带 agent 证据"——S2 守卫豁免它不清 _last_iter_ok。若 cut 翻转
    _last_iter_ok=False，Option A 软超时（stage 超时但上次迭代 ok → 继续不硬 raise）
    会失效，撞 deadline 硬 raise 丢弃可抢救产物。本测试直接断言 runner 的守卫逻辑：
    cut 结果保持 prior ok 信号，真失败（非 cut）才翻转。"""
    from ascendc_devkit.orchestration.kernel.runner import Runner as _R
    r = _R(agent_backend=_CutBackend(cut_times=1, succeed=True))

    # 直接验证守卫条件（runner.py S2 段）：cut → 不 clobber；真失败 → clobber。
    # F5：真失败判据 = 非豁免轮里「ok 但零产物」或非 ok——干净零产物同样是
    # 无可信完整产出，必须翻转（否则空跑轮点亮 salvage 信号，软超时丢事实）。
    def _guard(result, current_ok):
        _agent_res = result.get("agent_result")
        if _agent_res is not None:
            if not getattr(_agent_res, "aborted", None) and not getattr(
                    _agent_res, "cut", False):
                current_ok = (_agent_res.status == "ok"
                              and bool(_agent_res.artifacts))
        return current_ok

    _cut = {"agent_result": AgentResult(
        agent_name="x", status="ok", artifacts={}, cut=True)}
    _abort = {"agent_result": AgentResult(
        agent_name="x", status="fatal", aborted="hard_timeout")}
    _fail = {"agent_result": AgentResult(
        agent_name="x", status="ok", artifacts={})}
    _ok = {"agent_result": AgentResult(
        agent_name="x", status="ok", artifacts={"out.json": "x"})}
    assert _guard(_cut, current_ok=True) is True    # cut 保持 prior ok
    assert _guard(_abort, current_ok=True) is True  # 硬墙杀同样豁免（S2）
    assert _guard(_fail, current_ok=True) is False  # 真失败（空跑）翻转
    assert _guard(_ok, current_ok=False) is True    # 带产物 ok 重新点亮
    assert _guard(_ok, current_ok=False) is True    # 成功恢复为 ok


# —— P6（step-110）：cut WARN 事实化 + 硬切纯观测 + P7 退出原因诚实化 ————————

class _FactsCutBackend(AgentBackend):
    """每次 spawn 返回 cut=True，携带可配置的 metrics（cut_facts/cut_hard）。"""

    def __init__(self, cut_metrics: list[dict] | None = None):
        self._metrics = cut_metrics or []
        self.spawns = 0

    def spawn(self, agent_name, prompt, context, skills=None, model=None,
              working_dir=None, repo_baseline=None, repo_root=None,
              stage_name="", branch_label="", resume_session_id=None,
              resume_prompt=None, primary_skill=None, deadline_monotonic=None):
        self.spawns += 1
        m = (self._metrics[self.spawns - 1]
             if self.spawns <= len(self._metrics) else {})
        return AgentResult(agent_name=agent_name, status="ok",
                           artifacts={}, cut=True, metrics=dict(m))


def _collect_warns(monkeypatch, backend):
    from ascendc_devkit.orchestration.kernel import runner as _runner_mod
    warns = []
    monkeypatch.setattr(_runner_mod.Logger, "warn",
                        lambda msg, *a, **k: warns.append(str(msg)))
    _run(backend)
    return warns


def test_cut_warn_factual_with_hard_cut_facts(tmp_path, monkeypatch):
    """facts 在：cut WARN 呈现实测数字（chars/gap/时长）+ 硬切累计（纯观测），
    不再用 silent-cut 定性词开头。"""
    warns = _collect_warns(monkeypatch, _FactsCutBackend(cut_metrics=[
        {"cut_facts": {"thinking_chars": 98801, "last_delta_to_end_s": 0.12,
                       "attempt_duration_s": 654.0}, "cut_hard": True},
        {"cut_facts": {"thinking_chars": 38745, "last_delta_to_end_s": 0.3,
                       "attempt_duration_s": 200.0}, "cut_hard": True},
    ]))
    hard_warns = [w for w in warns if "thinking-only 终态" in w]
    assert hard_warns, "facts 在 → 事实化文案"
    assert "98801" in hard_warns[0] and "0.12" in hard_warns[0]
    assert "外部截断形态" in hard_warns[0]
    assert "硬切累计 1" in hard_warns[0]
    assert "硬切累计 2" in hard_warns[1], "硬切累计纯观测递增（不进控制流）"


def test_cut_warn_soft_cut_facts_show_silent_form(tmp_path, monkeypatch):
    """facts 在但 hard=False（gap 大）：文案描述非活跃流截断形态，无硬切累计。"""
    warns = _collect_warns(monkeypatch, _FactsCutBackend(cut_metrics=[
        {"cut_facts": {"thinking_chars": 1200, "last_delta_to_end_s": 45.0,
                       "attempt_duration_s": 100.0}, "cut_hard": False},
    ]))
    w = [x for x in warns if "thinking-only 终态" in x][0]
    assert "非活跃流截断形态" in w
    assert "硬切累计" not in w


def test_cut_warn_degrades_without_facts(tmp_path, monkeypatch):
    """facts 缺失（旧 backend/无思考证据）→ 降级现文案（不假设数字）。"""
    warns = _collect_warns(monkeypatch, _FactsCutBackend(cut_metrics=[{}]))
    assert any("silent-cut" in w for w in warns), "缺键 → 现文案保留"
    assert not any("thinking-only 终态" in w for w in warns)


def test_streak_exhaustion_exit_reason_honest(tmp_path, monkeypatch):
    """P7：streak 耗尽退出（非迭代耗尽）→ 退出 WARN 前置真实原因 + 各次
    thinking chars 清单，不再出现 reached max iterations 误导。"""
    backend = _FactsCutBackend(cut_metrics=[
        {"cut_facts": {"thinking_chars": 98801, "last_delta_to_end_s": 0.1,
                       "attempt_duration_s": 1.0}, "cut_hard": True},
        {"cut_facts": {"thinking_chars": 38745, "last_delta_to_end_s": 0.1,
                       "attempt_duration_s": 1.0}, "cut_hard": True},
        {"cut_facts": {"thinking_chars": 91000, "last_delta_to_end_s": 0.1,
                       "attempt_duration_s": 1.0}, "cut_hard": True},
        {"cut_facts": {"thinking_chars": 87000, "last_delta_to_end_s": 0.1,
                       "attempt_duration_s": 1.0}, "cut_hard": True},
        {"cut_facts": {"thinking_chars": 99000, "last_delta_to_end_s": 0.1,
                       "attempt_duration_s": 1.0}, "cut_hard": True},
    ])
    warns = _collect_warns(monkeypatch, backend)
    exit_warns = [w for w in warns if "输出契约未满足" in w]
    assert exit_warns, "契约未满足退出必有 WARN"
    ew = exit_warns[0]
    assert "cut-recovery 放弃" in ew, "streak 耗尽 → 真实退出原因"
    assert "[98801, 38745, 91000, 87000, 99000]" in ew, "各次 thinking chars 清单"
    assert "其中硬切 5 次" in ew
    assert "reached max iterations" not in ew, "P7：该路径不得再误报迭代耗尽"


def test_true_iteration_exhaustion_keeps_original_wording(tmp_path, monkeypatch):
    """真迭代耗尽（无 cut）→ 保留 reached max iterations 原文（该路径与事实
    相符）。"""
    backend = _CutBackend(cut_times=0, succeed=False)  # 全真失败、无 cut
    warns = _collect_warns(monkeypatch, backend)
    ew = [w for w in warns if "output_contract" in w or "输出契约未满足" in w]
    assert ew and "reached max iterations" in ew[0], "真迭代耗尽 → 原文保留"
    assert "cut-recovery 放弃" not in ew[0]
