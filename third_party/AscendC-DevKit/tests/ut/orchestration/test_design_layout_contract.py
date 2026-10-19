"""step-111 (P10) — design product physical-invariant layer guards.

Two deterministic (no-LLM) guard families so the layout-contract contract
can't silently regress:

  F2 (TilingStage.transition mechanical presence check):
    workspace contract present (dict) but ``layout_contract`` missing/empty/
    wrong-typed → same-agent artifact-retry (incomplete_output + user_feedback
    naming the missing field); ``workspace='none'``/absent → no obligation.

  Source guards (A1/A2/F1 landing):
    - tiling-buffer-kernel SKILL carries the 物理层展开边界 criteria
      (载体点名 / 同构测试 / three structural signals) + layout_contract
      delivery clause in the GM workspace budget;
    - coder SKILL carries the layout_contract consumption line (直译 +
      known_issues 交棒);
    - schema example documents layout_contract (list form);
    - §1.12: the new contract paragraphs cite no concrete operator names.
"""

from __future__ import annotations

import json
from pathlib import Path

from ascendc_devkit.capabilities.agent.backend import AgentResult
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.design_substages import TilingStage

_REPO = Path(__file__).resolve().parents[3]
_TILING_SKILL = (_REPO / ".claude" / "skills"
                 / "ascendc-op-tiling-buffer-kernel" / "SKILL.md")
_TILING_SCHEMA = (_REPO / ".claude" / "skills"
                  / "ascendc-op-tiling-buffer-kernel" / "schema"
                  / "tiling_buffer_kernel.json")
_CODER_SKILL = (_REPO / ".claude" / "skills"
                / "ascendc-op-dev-coding" / "SKILL.md")

# §1.12：契约条款是结构信号驱动的通用判据，不得锚定具体算子（本批实例名
# 全列——CamelCase 与 snake 两种形态）。
_OP_NAME_BLACKLIST = [
    "unique_dim", "UniqueDim",
    "logcumsumexp", "Logcumsumexp",
    "interpolate", "Interpolate",
    "take_along", "TakeAlong",
    "upsample", "Upsample",
    "mse", "Mse", "MseLoss",
]


def _ar(artifacts):
    return AgentResult(agent_name="x", status="ok", artifacts=artifacts)


def _res(wd, files):
    for fn, content in files.items():
        (wd / fn).write_text(content, encoding="utf-8")
    return {"_working_dir": str(wd), "agent_result": _ar({})}


def _segment_files(buffer_kernel_obj: dict) -> dict:
    """Three required tiling segment files; buffer_kernel payload injectable."""
    return {
        "tiling_split.json": json.dumps(
            {"template": "T1", "split": {"axis": "N"}}),
        "tiling_buffer_kernel.json": json.dumps(
            {"template": "T1", "buffer_kernel": buffer_kernel_obj}),
        "tiling_precision_perf.json": json.dumps(
            {"template": "T1", "precision_perf": {"compute_dtype": "fp32"}}),
    }


def _run(buffer_kernel_obj: dict, tmp_path):
    wd = tmp_path / "wd"
    wd.mkdir(exist_ok=True)  # 多形态循环复用同一 tmp_path（文件全量重写）
    return TilingStage(template={"name": "T1"}).transition(
        State.empty(), _res(wd, _segment_files(buffer_kernel_obj)))


# —— F2：在位检查六态 ——

class TestLayoutContractPresence:
    def test_present_nonempty_list_passes(self, tmp_path):
        out = _run({
            "buffer_num": 2,
            "workspace": {
                "user_workspace_bytes": 196608,
                "rationale": "cross-core reduce staging",
                "layout_contract": [
                    "planeA: blockDim*rows*sizeof(T)",
                    "planeA.stride: rows",
                    "publishDst === foldSrc",
                ],
            },
        }, tmp_path)
        assert out.last_error is None, (
            f"在位且非空 layout_contract 不应触发：{out.last_error}")
        ws = out.tiling_results["T1"]["buffer_kernel"]["workspace"]
        assert ws["layout_contract"] == [
            "planeA: blockDim*rows*sizeof(T)",
            "planeA.stride: rows",
            "publishDst === foldSrc",
        ]

    def test_missing_triggers_retry(self, tmp_path):
        out = _run({
            "buffer_num": 2,
            "workspace": {
                "user_workspace_bytes": 196608,
                "rationale": "cross-core reduce staging",
            },
        }, tmp_path)
        assert out.last_error is not None
        assert out.last_error.error_type == "incomplete_output"
        assert "layout_contract" in out.last_error.message
        assert "layout_contract" in (out.user_feedback or "")

    def test_empty_list_triggers_retry(self, tmp_path):
        out = _run({
            "workspace": {"user_workspace_bytes": 8, "layout_contract": []},
        }, tmp_path)
        assert out.last_error is not None
        assert out.last_error.error_type == "incomplete_output"
        assert "layout_contract" in out.last_error.message

    def test_blank_entries_trigger_retry(self, tmp_path):
        out = _run({
            "workspace": {"user_workspace_bytes": 8,
                          "layout_contract": ["   "]},
        }, tmp_path)
        assert out.last_error is not None
        assert out.last_error.error_type == "incomplete_output"

    def test_wrong_type_triggers_retry(self, tmp_path):
        out = _run({
            "workspace": {"user_workspace_bytes": 8,
                          "layout_contract": {"planeA": "formula"}},
        }, tmp_path)
        assert out.last_error is not None
        assert out.last_error.error_type == "incomplete_output"
        # R1 归类：产物已交付、字段漏写、喂提示可确定性纠正 → artifact-retry 桶
        # （独立预算、不烧 iteration），而非 schema_violation 的迭代语义。
        assert TilingStage(template={"name": "T1"}).is_artifact_retry_error(
            out.last_error.error_type)

    def test_workspace_none_string_no_obligation(self, tmp_path):
        out = _run({"buffer_num": 2, "workspace": "none"}, tmp_path)
        assert out.last_error is None

    def test_workspace_absent_no_obligation(self, tmp_path):
        out = _run({"buffer_num": 2}, tmp_path)
        assert out.last_error is None

    def test_workspace_null_no_obligation(self, tmp_path):
        # JSON null = 显式未使用，与缺省等义（合法形态集：缺省/null/'none'/object）
        out = _run({"buffer_num": 2, "workspace": None}, tmp_path)
        assert out.last_error is None

    def test_workspace_malformed_shape_triggers_retry(self, tmp_path):
        # §1.2 可诊断：载体畸形不得静默进产物、推迟到 codegen 期 LLM 自报
        for malformed in (196608, ["planeA"], "196608"):
            out = _run({"buffer_num": 2, "workspace": malformed}, tmp_path)
            assert out.last_error is not None, (
                f"畸形形态 {malformed!r} 应被打回")
            assert out.last_error.error_type == "incomplete_output"
            assert "object" in out.last_error.message
            assert "workspace" in (out.user_feedback or "")


# —— F2 反馈消费闭环（§2.9②：反馈必须可被责任 agent 确定性消费，否则是噪音门）——

class TestFeedbackConsumptionLoop:
    def _fire(self, tmp_path):
        wd = tmp_path / "wd"
        wd.mkdir()
        stage = TilingStage(template={"name": "T1"})
        fired = stage.transition(State.empty(), _res(wd, _segment_files({
            "buffer_num": 2,
            "workspace": {"user_workspace_bytes": 196608,
                          "rationale": "cross-core reduce staging"},
        })))
        assert fired.last_error is not None
        return stage, wd, fired

    def test_feedback_reaches_next_spawn_prompt(self, tmp_path):
        stage, _wd, fired = self._fire(tmp_path)
        # 本分支未满足 → 重试被启用（不短路终止）
        assert stage.is_satisfied(fired) is False
        # 定向反馈必须进入下一次 spawn 的 prompt——重试 agent 看得到要修什么
        prompt = stage._build_prompt(fired, iteration=2)
        assert "用户反馈" in prompt
        assert "layout_contract" in prompt

    def test_backfill_converges_and_clears_feedback(self, tmp_path):
        stage, wd, fired = self._fire(tmp_path)
        assert fired.user_feedback
        # 同 agent 增量回填：同一工作目录，只补 layout_contract
        (wd / "tiling_buffer_kernel.json").write_text(json.dumps({
            "template": "T1",
            "buffer_kernel": {
                "buffer_num": 2,
                "workspace": {
                    "user_workspace_bytes": 196608,
                    "rationale": "cross-core reduce staging",
                    "layout_contract": ["planeA: blockDim*rows*sizeof(T)"],
                },
            },
        }, ensure_ascii=False), encoding="utf-8")
        converged = stage.transition(fired, {
            "_working_dir": str(wd), "agent_result": _ar({})})
        # 收敛：契约进产物、反馈消费完毕（success return 清 user_feedback；
        # last_error 的收尾清错归 runner F6 前置归一化——不在 transition 断言，
        # 收敛闭环由 ST 经真实 Runner 验证）
        ws = converged.tiling_results["T1"]["buffer_kernel"]["workspace"]
        assert ws["layout_contract"] == ["planeA: blockDim*rows*sizeof(T)"]
        assert converged.user_feedback == ""


# —— source guards：A1/A2/F1 落位 + §1.12 通用性 ——

class TestSourceGuards:
    def test_tiling_skill_carries_scopeout_criteria(self):
        text = _TILING_SKILL.read_text(encoding="utf-8")
        assert "物理层展开边界" in text
        assert "点名载体" in text
        assert "同构" in text
        # 三条结构信号（可判定的同构测试形态）
        assert "GM 布局" in text
        assert "跨界契约" in text
        assert "同步边界" in text

    def test_tiling_skill_workspace_clause_asks_layout_contract(self):
        text = _TILING_SKILL.read_text(encoding="utf-8")
        # GM workspace 预算条款（:109 一带）须交付 layout_contract
        assert "layout_contract" in text
        line = next(ln for ln in text.splitlines() if "layout_contract" in ln)
        assert "workspace" in "".join(
            text.splitlines()[max(0, text.splitlines().index(line) - 3):
                              text.splitlines().index(line) + 4])

    def test_schema_documents_layout_contract(self):
        d = json.loads(_TILING_SCHEMA.read_text(encoding="utf-8"))
        assert "layout_contract" in d["description"]
        ws = d["example"]["buffer_kernel"]["workspace"]
        lc = ws.get("layout_contract")
        assert isinstance(lc, list) and lc
        assert all(isinstance(e, str) and e.strip() for e in lc)

    def test_coder_skill_carries_consumption_line(self):
        text = _CODER_SKILL.read_text(encoding="utf-8")
        assert "layout_contract" in text
        assert "known_issues" in text
        # 消费语义：契约在位→直译（禁现场重推）
        hit = [ln for ln in text.splitlines() if "layout_contract" in ln]
        window = []
        lines = text.splitlines()
        for i, ln in enumerate(lines):
            if "layout_contract" in ln:
                window.extend(lines[max(0, i - 2):i + 3])
        assert any("直译" in ln for ln in window), (
            "消费行须写明按契约直译（禁现场重推布局）")

    def test_contract_paragraphs_cite_no_operator_names(self):
        # §1.12 删除测试：契约条款不依赖任何具体算子名即可完整判定。
        for path in (_TILING_SKILL, _CODER_SKILL):
            lines = path.read_text(encoding="utf-8").splitlines()
            hits = [i for i, ln in enumerate(lines)
                    if "物理层展开边界" in ln or "layout_contract" in ln]
            scoped = []
            for i in hits:
                scoped.extend(lines[max(0, i - 2):i + 3])
            for ln in scoped:
                for name in _OP_NAME_BLACKLIST:
                    assert name not in ln, (
                        f"{path.name} 契约相关段落耦合算子名 {name!r}：{ln.strip()}")
