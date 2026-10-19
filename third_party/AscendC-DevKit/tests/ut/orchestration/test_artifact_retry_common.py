"""R1/R2 回归测试 — 产物契约未满足（missing_artifact）走公共 artifact-retry，不烧 iteration。

守护 runner 侧公共抽象（L4 03-impl-common-artifact-retry.md 步骤 3）：
  - missing_artifact 错误 → 独立 artifact_retries 计数递增，不烧 iteration 预算；
  - artifact-retry 耗尽后落回 iteration 预算；
  - R2：artifact-retry 过程在日志/事件中可观测（artifact_missing_retry 事件 + retry-N）。

设计意图（对照 test_cut_allowance.py 的 cut 语义）：
  - cut（agent 没跑完）→ cut_streak++，不烧 iteration（既有）
  - infra（spawn 失败）→ infra_retry++，不烧 iteration（既有，P116）
  - **artifact（跑完但产物放错目录/缺产物）→ artifact_retries++，不烧 iteration（本测试守护的新增公共通道）**
"""
from __future__ import annotations

from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.orchestration.kernel.runner import Runner
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.kernel.action import SpawnAgent
from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.capabilities.agent.backend import AgentBackend, AgentResult


class _ArtifactBackend(AgentBackend):
    """前 ``artifact_times`` 次 spawn 返回缺产物错误（transition 会设 missing_artifact）；
    之后若 ``succeed`` 返回 ok+产物。计数 spawns。"""

    def __init__(self, artifact_times: int, succeed: bool = True):
        self._artifact_times = artifact_times
        self._succeed = succeed
        self.spawns = 0

    def spawn(self, agent_name, prompt, context, skills=None, model=None,
              working_dir=None, repo_baseline=None, repo_root=None,
              stage_name="", branch_label="", resume_session_id=None,
              resume_prompt=None, primary_skill=None, deadline_monotonic=None):
        self.spawns += 1
        # agent "跑完了"（status=ok，有 process fact）但产物缺失——返回空 artifacts，
        # transition 会因契约不满足而报 missing_artifact。区分于 cut（thinking-only 终止）。
        if self.spawns <= self._artifact_times:
            return AgentResult(agent_name=agent_name, status="ok",
                               artifacts={}, cut=False)
        if self._succeed:
            return AgentResult(agent_name=agent_name, status="ok",
                               artifacts={"out.json": "x"}, cut=False)
        return AgentResult(agent_name=agent_name, status="ok",
                           artifacts={}, cut=False)


class _ArtifactStage(Stage):
    """契约 tiling_results；ceiling=2（对齐 config tiling=2）。error_type=missing_artifact。
    缺产物时 transition 设 last_error（模拟 _missing_artifact_error），让 runner 公共分支识别。"""

    name = "artifact-stage"
    default_max_iterations = 2
    fail_strategy = "halt"
    needs_iteration_safety_net = False   # 强制 ceiling = stage_budget = 2
    artifact_retry_max = 3               # 独立 artifact-retry 预算 3

    def input_contract(self):
        return StageIOContract(requires=[])

    def output_contract(self):
        return StageIOContract(provides=["tiling_results"])

    def actions(self, state, iteration=1):
        return [SpawnAgent(agent_name="x", prompt="p", context={})]

    def transition(self, state, result):
        ar = result.get("agent_result")
        if ar and ar.artifacts:
            # 成功产出，但**不清 last_error**——忠实模拟真实 TilingStage 行为
            # （注释"收尾清错统一归 runner"，success return 用裸 with_updates）。
            # runner 公共 artifact-retry 分支的 has_all 守卫必须兜住：产物就位 →
            # 不 artifact-retry（last_error 过时），走正常收尾 F6 清错。
            return state.with_updates(tiling_results={"T1": {"ok": True}})
        # 缺产物 → 报 missing_artifact（对齐 design _missing_artifact_error）
        return state.with_updates(
            last_error=ErrorFeedback(
                stage_name=self.name, error_type="missing_artifact",
                message="产物 tiling_split.json 未在正确目录找到"))

    def is_satisfied(self, state):
        err = getattr(state, "last_error", None)
        if err is not None and getattr(err, "stage_name", None) == self.name:
            return False
        return bool(getattr(state, "tiling_results", None))


def _run(backend, stage=None):
    return Runner(agent_backend=backend).run_stage(
        State(mode="new", non_interactive=True), stage or _ArtifactStage())


def test_missing_artifact_does_not_burn_iteration_budget():
    """缺产物（missing_artifact）不烧 iteration——独立 artifact-retry 通道。
    artifact_retry_max=3、ceiling=2：若缺产物烧 iteration，2 次即 halt；
    若走独立通道，缺产物 3 次不烧 iteration，第 4 次成功产出。"""
    backend = _ArtifactBackend(artifact_times=3, succeed=True)
    state = _run(backend)
    assert backend.spawns == 4          # 3 次缺产物 + 1 次成功
    assert state.tiling_results == {"T1": {"ok": True}}  # 成功完成
    # 生产性迭代计数 = 1（成功那次），3 次缺产物未烧预算
    assert state.stage_iterations["artifact-stage"] == 1
    # 成功后计数清零（对齐 cut 语义：残留计数浪费后续预算）——3 次缺产物的"不烧
    # iteration"已由 stage_iterations==1 与 spawns==4 验证，无需依赖残留计数。
    assert state.artifact_retries == 0


def test_artifact_retry_exhausted_falls_back_to_iteration():
    """artifact-retry 耗尽（3/3）→ 落回 iteration 预算。
    一直缺产物：3 次独立重试（不烧 iteration）+ 2 次 iteration 预算耗尽 → halt。
    验证"独立通道耗尽后落回 iteration"的边界。"""
    backend = _ArtifactBackend(artifact_times=10 ** 9, succeed=False)
    state = _run(backend)
    # 3 次 artifact-retry（不烧 iteration）+ 2 次 iteration（烧 budget 1,2）→ 预算耗尽
    assert backend.spawns == 3 + 2      # 5
    assert state.artifact_retries == 3  # 独立计数到上限
    assert state.tiling_results is None  # 契约未满足
    # iteration 烧满 2
    assert state.stage_iterations["artifact-stage"] == 2


def test_artifact_retry_after_success_resets_count():
    """缺产物 → 成功 → 计数应重置（成功是确定性产出，streak 不再累积）。
    与 cut 的"成功清零"同构：一次缺产物 + 一次成功，不残留计数影响后续。"""
    backend = _ArtifactBackend(artifact_times=1, succeed=True)
    state = _run(backend)
    assert backend.spawns == 2          # 1 缺产物 + 1 成功
    assert state.tiling_results == {"T1": {"ok": True}}
    assert state.artifact_retries == 0  # 成功后重置（若成功不清零，残留计数会浪费后续预算）


def test_artifact_retry_emits_observable_event(tmp_path):
    """R2 (2026-08-21): artifact-retry 过程可观测——events.jsonl 出现
    artifact_missing_retry 事件，含 attempt/max/error_type/message。之前缺产物
    重试完全静默（只看到 spawn 重复），无法区分"新起"与"重试"（§1.2 可诊断）。"""
    from ascendc_devkit.infra.event_log import EventLog
    from ascendc_devkit.infra.workspace import Workspace

    class _EventStage(_ArtifactStage):
        artifact_retry_max = 2

    backend = _ArtifactBackend(artifact_times=2, succeed=True)
    ws = Workspace.create(str(tmp_path), run_id="r3")
    rb = Runner(agent_backend=backend, workspace=ws)
    rb.run_stage(State(mode="new", non_interactive=True), _EventStage())

    evs = EventLog.read(ws.events_path)
    art_events = [e for e in evs if e.get("type") == "artifact_missing_retry"]
    assert len(art_events) == 2           # 2 次缺产物重试各一次
    e = art_events[0]
    assert e["error_type"] == "missing_artifact"
    assert e["attempt"] == 1
    assert e["max"] == 2
    assert "tiling_split.json" in e["message"]
