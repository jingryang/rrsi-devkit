"""step-63 heavy_llm: req-analysis 自闭环——真 LLM 产 requirement.json（非 op_spec.json）.

背景（P86 / step-63）：req-analysis SKILL 文档刚从 op_spec.json/md 收敛为 requirement.json
（工程层早读 requirement.json，真实 run agent 早写对）。本测试用真 LLM 验证收敛后
agent 仍正确产 requirement.json 且过 schema——区分"agent 真按新 SKILL 产 requirement.json"
与"agent 仍产旧 op_spec.json"（文档收敛回归）。

heavy_llm by §3.11（real LLM full-flow, minute-scale）— marked @llm + @heavy_llm so
`-m "not heavy_llm"`（默认 sweep）排除；按名/`-m heavy_llm` 显式跑。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ascendc_devkit.orchestration.stages.requirement import RequirementStage
from tests._llm_env import has_anthropic as _has_anthropic, load_settings_env

load_settings_env()

_SKILLS_ROOT = (Path(__file__).resolve().parents[2]
                / ".claude" / "skills")
_MAX_ATTEMPTS = 3
_REQ_SKILL = "ascendc-op-req-analysis"


def _schema() -> dict:
    return json.loads((_SKILLS_ROOT / _REQ_SKILL / "schema" / "requirement.json")
                      .read_text(encoding="utf-8"))


def _output_requirements() -> str:
    s = _schema()
    lines = ["## 输出要求",
             "请使用 Bash（cat > 文件）将以下 JSON 写入当前工作目录：",
             f"### requirement.json — {s.get('description', '')}",
             f"（required_keys: {', '.join(s.get('required_keys', []))}）",
             "```json",
             json.dumps(s.get("example", {}), ensure_ascii=False, indent=2),
             "```"]
    return "\n".join(lines)


def _seed_add(wd: Path) -> None:
    """灌 add 算子（逐元素加，计算类）Golden 代码 + prompt 给公式."""
    wd.mkdir(parents=True, exist_ok=True)
    (wd / "golden.py").write_text(
        "import torch\n"
        "\n"
        "def add(x, y):\n"
        "    # element-wise add: y = x + y\n"
        "    # x, y: same shape, same dtype (fp16/fp32)\n"
        "    return x + y\n",
        encoding="utf-8")


def _seed_inplace(wd: Path) -> None:
    """灌一个 in-place 算子 golden：state 张量被 clone 后更新再 return（cann-bench
    的真实 in-place 范式——clone 避免污染评测共享输入）。neutral 命名（§1.12：
    fixture 不点名真实算子）。in_place 语义只在 golden 行为里，需 agent 读 golden
    判定（工程无法静态确定性提取——见 inplace-mutation-mode-two-layers）。"""
    wd.mkdir(parents=True, exist_ok=True)
    (wd / "golden.py").write_text(
        "import torch\n"
        "\n"
        "def state_update(state, delta):\n"
        "    # in-place semantics: `state` (1-D) is updated by `delta` and\n"
        "    # returned. clone() avoids polluting the evaluator-shared input.\n"
        "    state = state.clone()\n"
        "    state.copy_(state + delta)\n"
        "    return state\n",
        encoding="utf-8")


def _spawn_req_op(wd: Path, op_name: str, semantics: str) -> None:
    """通用 spawn：不同 golden 用同一 SKILL 链路（区别只在 op_name/语义描述）。"""
    from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
    from ascendc_devkit.orchestration.skill_config import skill_allowlist
    primary = _REQ_SKILL
    prompt = (
        f"/{primary}\n\n"
        f"算子：{op_name}（{semantics}）。"
        "Golden 代码见当前工作目录 golden.py。按标准模式提取算子规格，产出 "
        "requirement.json（结构化规格模型，供概要设计 Skill 直接读取）。\n\n"
        + _output_requirements())
    backend = SDKBackend(interactive=False, working_dir=wd.parent,
                         on_decision="default", decision_workspace=wd)
    backend.spawn("requirement-analyst", prompt, {},
                  skills=skill_allowlist(primary),
                  working_dir=wd, stage_name="tui")


def _spawn_req(wd: Path) -> None:
    _spawn_req_op(wd, "add",
                  "逐元素加 y = x + y，计算类，两输入同 shape 同 dtype")


def _mutation_mode_consistent(req: dict) -> bool:
    """mutation_mode 与 inputs/outputs 同名关系自洽——复用 RequirementStage 加载期校验
    （in_place ⇔ 同名 input-output 对），单一源不重复校验逻辑。"""
    return not RequirementStage()._validate_mutation_mode_consistency(req)


@pytest.mark.llm
@pytest.mark.heavy_llm
class TestReqAnalysisProducesRequirementJson:
    """step-63: req-analysis 真 LLM 产 requirement.json（非 op_spec.json）且过 schema.

    验证文档收敛（op_spec.json → requirement.json）后 agent 仍正确：
    (1) 产 requirement.json（文件存在 + 合法 JSON）
    (2) 过 schema required_keys（op_name/mutation_mode/inputs/outputs 齐全且非空）
    (3) 不产旧 op_spec.json（收敛回归——agent 不再走旧文件名）
    (4) mutation_mode 自洽（in_place⇔同名 input-output 对；in-place/out-of-place 交付契约）
    有界重试（§3.10）吸收 LLM 抖动，至少一次触发即 PASS。
    """

    def test_produces_requirement_json_passes_schema(self, tmp_path):
        if not _has_anthropic():
            pytest.skip("Anthropic not configured")
        required = set(_schema()["required_keys"])
        last = None
        for attempt in range(_MAX_ATTEMPTS):
            wd = tmp_path / f"ws_{attempt}"
            _seed_add(wd)
            _spawn_req(wd)
            out = wd / "requirement.json"
            stale = wd / "op_spec.json"
            if not out.is_file():
                last = "no requirement.json produced"
                continue
            try:
                req = json.loads(out.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                last = "requirement.json not valid JSON"
                continue
            # schema 守: required_keys 齐全（含 mutation_mode）+ 关键值非空
            # + mutation_mode 自洽（in-place/out-of-place 交付契约）+ 不产旧 op_spec.json
            if (required.issubset(req.keys())
                    and req.get("op_name")
                    and req.get("inputs")
                    and req.get("outputs")
                    and _mutation_mode_consistent(req)
                    and not stale.exists()):
                return  # PASS: 产 requirement.json、过 schema、mutation_mode 自洽
            last = json.dumps({"keys": list(req.keys()),
                               "op_name": req.get("op_name"),
                               "mutation_mode": req.get("mutation_mode"),
                               "op_spec_exists": stale.exists()},
                              ensure_ascii=False)
        pytest.fail(
            "req-analysis 未正确产 requirement.json（schema 不过或仍产 op_spec.json）"
            f"——step-63 文档收敛回归。last={last}")


@pytest.mark.llm
@pytest.mark.heavy_llm
class TestReqAnalysisMutationModeFromGolden:
    """全维度锚 golden（档 C）看护：in-place 语义只在 golden 行为里（state 被 clone
    后更新再 return），工程无法静态确定性提取，须 agent 读 golden 判定。验证真 LLM
    按新 SKILL 判据（以 golden 为源头，非算子名模式匹配）正确产出：
    (1) mutation_mode == "in_place"（golden 是某入参的原地更新）
    (2) 存在与某 input 同名的 output（in-place 状态张量的忠实转写）
    (3) mutation_mode 与同名关系自洽（复用工程加载期校验）
    有界重试（§3.10）吸收 LLM 抖动，至少一次触发即 PASS。
    """

    def test_inplace_mutation_mode_grounded_in_golden(self, tmp_path):
        if not _has_anthropic():
            pytest.skip("Anthropic not configured")
        last = None
        for attempt in range(_MAX_ATTEMPTS):
            wd = tmp_path / f"ws_{attempt}"
            _seed_inplace(wd)
            _spawn_req_op(
                wd, "state_update",
                "state 状态张量被 delta 原地更新后返回（in-place 语义，见 golden）")
            out = wd / "requirement.json"
            if not out.is_file():
                last = "no requirement.json produced"
                continue
            try:
                req = json.loads(out.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                last = "requirement.json not valid JSON"
                continue
            in_names = {i.get("name") for i in (req.get("inputs") or [])
                        if isinstance(i, dict)}
            out_names = {o.get("name") for o in (req.get("outputs") or [])
                         if isinstance(o, dict)}
            aliased = bool(in_names & out_names)
            if (req.get("mutation_mode") == "in_place"
                    and aliased
                    and _mutation_mode_consistent(req)):
                return  # PASS: agent 以 golden 为源头判 in_place + 忠实转写同名
            last = json.dumps({"mutation_mode": req.get("mutation_mode"),
                               "in_names": sorted(n for n in in_names if n),
                               "out_names": sorted(n for n in out_names if n),
                               "aliased": aliased},
                              ensure_ascii=False)
        pytest.fail(
            "req-analysis 未以 golden 为源头正确判 in-place（应 mutation_mode=in_place "
            f"且 output 与 input 同名）——档 C golden 锚定回归。last={last}")
