"""Real-LLM guard: 概设对排序/去重算子的排序算法族是否做系统评估。

实证（20260813-164600-d345f0）：设计侧因排序模式库只提供"比较排序 + 归并"单一心智模型，
把值域分桶迭代（LSD radix）与 presence bitmap 排除在选项空间外，押注晦涩硬件排序原语
并在精度闭环黑盒失败。模式库已补三个算法族（比较排序 / LSD radix / presence bitmap）+
选型判据。

本测试用真实 LLM 跑概设（general-design-generator + /ascendc-op-general-design），
输入一个排序/去重类算子（输出按值升序的唯一值集合），断言产物 general_design.json
出现**非比较排序**的算法族信号——若模式库修正未生效，产物只会是单一比较排序路径。

Heavy by nature（真实 LLM、全量概设 skill）→ marked heavy_llm per §3.11。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._llm_env import has_anthropic as _has_anthropic, load_settings_env

load_settings_env()

_SKILLS_ROOT = (Path(__file__).resolve().parents[2] / ".claude" / "skills")
_MAX_ATTEMPTS = 3
_GENERAL_DESIGN_SKILL = "ascendc-op-general-design"
_AGENT = "general-design-generator"


def _output_requirements() -> str:
    s = json.loads((_SKILLS_ROOT / _GENERAL_DESIGN_SKILL / "schema" / "general_design.json")
                   .read_text(encoding="utf-8"))
    lines = ["## 输出要求",
             "请使用 Bash（cat > 文件）或 Edit 工具，将以下 JSON 写入当前工作目录：",
             f"### general_design.json — {s.get('description', '')}",
             "```json",
             json.dumps(s.get("example", {}), ensure_ascii=False, indent=2),
             "```"]
    return "\n".join(lines)


def _seed(wd: Path) -> None:
    """构造一个排序/去重类算子（结构特征：输出按值升序的唯一值集合，位置由值决定）。"""
    wd.mkdir(parents=True, exist_ok=True)
    (wd / "requirement.json").write_text(json.dumps({
        "op": {
            "name": "sorted_unique",
            "category": "SortSelect",
            "description": "对输入 x 展平后做升序排序并去重：输出 y 为按数值升序排列的唯一值集合"
                            "（长度 U 数据相关），y 元素逐位取自 x、无算术；可选输出逆索引。"
                            "输出位置由值的相对大小决定，属选择排序类。",
            "inputs": [{"name": "x", "dtype": ["float32", "float16", "int32", "int64"],
                        "shape": ["N"], "param_type": "REQUIRED"}],
            "outputs": [{"name": "y", "dtype": ["float32", "float16", "int32", "int64"],
                         "shape": ["U"], "param_type": "REQUIRED"}],
            "attrs": [{"name": "return_inverse", "type": "bool", "default": False}],
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def _spawn(wd: Path) -> None:
    from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
    from ascendc_devkit.orchestration.skill_config import skill_allowlist
    primary = _GENERAL_DESIGN_SKILL
    prompt = (
        f"/{primary}\n\n"
        "基于当前工作目录的 requirement.json，生成该算子的概要设计，产出 general_design.json。"
        "注意：该算子输出按值升序的唯一值集合、输出位置由值的相对大小决定（选择排序类），"
        "请在算法层面明确排序机制的选择与理由。\n\n"
        + _output_requirements())
    backend = SDKBackend(interactive=False, working_dir=wd.parent,
                         on_decision="default", decision_workspace=wd)
    backend.spawn(_AGENT, prompt, {},
                  skills=skill_allowlist(primary),
                  working_dir=wd, stage_name="tui")


def _algorithm_family_signal(text: str) -> list[str]:
    """非比较排序的算法选项，或显式算法族选型表述。"""
    signals = ["radix", "基数", "值域分桶", "bitmap", "位图", "算法族", "候选方案", "备选"]
    return [s for s in signals if s in text]


@pytest.mark.llm
@pytest.mark.heavy_llm
class TestGeneralDesignEvaluatesAlgorithmFamily:
    """概设对排序/去重算子评估排序算法族——产物出现非单一比较排序的算法选项。"""

    def test_general_design_lists_sort_algorithm_family(self, tmp_path):
        if not _has_anthropic():
            pytest.skip("Anthropic not configured")
        last = None
        for attempt in range(_MAX_ATTEMPTS):
            wd = tmp_path / f"ws_{attempt}"
            _seed(wd)
            _spawn(wd)
            out = wd / "general_design.json"
            if not out.is_file():
                last = "no general_design.json produced"
                continue
            try:
                text = out.read_text(encoding="utf-8")
            except Exception as e:  # noqa: BLE001
                last = f"general_design.json unreadable: {e}"
                continue
            sig = _algorithm_family_signal(text)
            if sig:
                return  # PASS：出现非比较排序算法族信号，模式库修正生效
            last = f"no algorithm-family signal; produced: {text[:200]}"
        pytest.fail(
            "general-design 未出现排序算法族评估（radix/值域分桶/bitmap/算法族选型任一）——"
            f"模式库修正未被采纳，可能回退到单一比较排序。last={last}")
