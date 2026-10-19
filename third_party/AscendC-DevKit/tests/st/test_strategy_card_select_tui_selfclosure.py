"""Real-link system test: 策略卡检索 skill 在 TUI 下自闭环（无 DevKit 框架）。

THE acceptance guard for 外部挂载：skill 必须能在 Claude Code TUI 里、在没有 DevKit
框架（无 Stage / Runner / GraphExecutor / State）的情况下，从外部策略库挂载卡片、
跑完 Phase 0–4、产出契约合规的 selection.json。这同时是对两件事的实测：

  1. driver 类 skill 的仓外依赖声明是否真的可解析（ASCENDC_STRATEGY_ROOT）；
  2. tail-called skill 能否定位到自身 scripts/——这正是方案评审时标记的未决点，
     若本用例失败，说明 `<skill_dir>` 解析在该加载路径下不成立。

Spawns agents DIRECTLY, exactly as a human typing /<skill> would.
Marked @pytest.mark.llm + @pytest.mark.heavy_llm: NOT in the default sweep
(§3.11 — real LLM full-flow, minute-scale); run explicitly by name or -m llm,
on user decision.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = "ascendc-strategy-card-select"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / SKILL
SCRIPTS = SKILL_DIR / "scripts"

# 外部策略库（跨仓单源依赖）。缺失即 skip，不伪造。
EXTERNAL_CATALOG = Path(os.environ.get("ASCENDC_STRATEGY_ROOT",
                                       "/home/l00940202/pangu/ascendc-strategy-opt"))

_MAX_ATTEMPTS = 3


from tests._llm_env import load_settings_env  # 单一解析点（§1.15）：settings env 折叠不再各写一份

load_settings_env()


def _has_anthropic() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()
                or os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip())


def _catalog_available() -> bool:
    return (EXTERNAL_CATALOG / "strategies" / "common").is_dir() \
        and (EXTERNAL_CATALOG / ".claude" / "skills"
             / "ascendc-strategy-curator" / "scripts" / "_catalog.py").is_file()


def _spawn(work_dir: Path, slash_skill: str, instruction: str):
    """Spawn a design generator agent in TUI mode: first message leads with the
    /<skill> slash command, then a short instruction. No State, no Stage — only
    the files already in work_dir are available."""
    from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
    from ascendc_devkit.orchestration.skill_config import skill_allowlist
    primary = slash_skill
    prompt = f"/{primary}\n\n{instruction}"
    backend = SDKBackend(interactive=False, working_dir=work_dir.parent,
                         on_decision="default", decision_workspace=work_dir)
    backend.spawn("ascendc-design-generator", prompt, {},
                  skills=skill_allowlist(primary),
                  working_dir=work_dir, stage_name="tui")


def _seed_design_doc(d: Path) -> Path:
    """Minimal design doc with recognizable operator semantics → Query 可构建。"""
    d.mkdir(parents=True, exist_ok=True)
    p = d / "requirement.json"
    p.write_text(json.dumps({
        "op_name": "top_k",
        "mathematical_definition": "沿末轴取最大的 k 个值与对应索引，并列时按下标升序保持稳定",
        "inputs": [{"name": "x", "dtype": "float16", "shape": ["B", "S"]}],
        "outputs": [{"name": "values", "dtype": "float16", "shape": ["B", "k"]},
                    {"name": "indices", "dtype": "int32", "shape": ["B", "k"]}],
        "shape_support": ["B ∈ [1, 1024]", "S ∈ [16, 4096]", "k ∈ [1, S]"],
        "dtype_support": ["float16", "bfloat16"],
        "target_chip": "A5",
        "precision_requirement": "索引必须与 golden 完全一致；值按 atol=1e-3 比对",
        "performance_requirement": "无 profiling 数据，以官方评测为验收",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


@pytest.mark.llm
@pytest.mark.heavy_llm
class TestStrategyCardSelectSelfClosure:
    """skill 在裸目录里跑通 Phase 0–4 并产出契约合规的 selection.json。"""

    def test_phase0_scripts_run_outside_framework(self, tmp_path):
        """无 LLM 的确定性部分：脚本链在框架外可用，且外部库可解析。"""
        if not _catalog_available():
            pytest.skip(f"外部策略库不可用: {EXTERNAL_CATALOG}")
        out = tmp_path / "sel"
        env = {**os.environ, "ASCENDC_STRATEGY_ROOT": str(EXTERNAL_CATALOG)}
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "build_cards.py"),
             "--strategy-root", str(EXTERNAL_CATALOG), "--all",
             "--out", str(out), "--quiet"],
            capture_output=True, text=True, env=env)
        assert r.returncode == 0, r.stderr
        pools = list((out / "cards").rglob("*.texts.json"))
        assert len(pools) >= 11, f"应有 11 个池，实际 {len(pools)}"

        doc = _seed_design_doc(tmp_path / "ws")
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "select_prepare.py"), "--prepare",
             "--op-name", "top_k", "--out-dir", str(out),
             "--design-doc", str(doc), "--category", "sort-select",
             "--cards-file", str(out / "cards" / "op-class" / "sort-select.texts.json")],
            capture_output=True, text=True, env=env)
        assert r.returncode == 0, r.stderr
        ri = json.loads((out / "run_inputs.json").read_text(encoding="utf-8"))
        assert ri["strategy_root"] == str(EXTERNAL_CATALOG)
        assert ri["source_md_digest"] and ri["cards_file_sha256"]
        assert "created_at" not in ri, "run_inputs 必须可字节复现"

    def test_llm_flow_produces_conforming_selection(self, tmp_path):
        """真实 LLM 全流程：跑完 Phase 0–4，selection.json 过门禁且路径真实存在。"""
        if not _has_anthropic():
            pytest.skip("Anthropic not configured")
        if not _catalog_available():
            pytest.skip(f"外部策略库不可用: {EXTERNAL_CATALOG}")
        os.environ["ASCENDC_STRATEGY_ROOT"] = str(EXTERNAL_CATALOG)

        for attempt in range(_MAX_ATTEMPTS):
            wd = tmp_path / f"ws_{attempt}"
            doc = _seed_design_doc(wd)
            _spawn(wd, SKILL,
                   "这是一个通路验证测试，不要做深度设计推理。按你的 SKILL.md 跑 "
                   "Phase 0–4：类别用 sort-select；设计文档是当前目录的 requirement.json；"
                   "输出目录用当前目录下的 strategy_selection/。"
                   "粗筛不要凑数——池内不合适的就别选，shortfall_reason 写明即可。"
                   "最终必须落盘 selection.json 与 selection_report.md。")
            out = wd / "strategy_selection"
            sel = out / "selection.json"
            if not sel.is_file():
                continue
            # 门禁：契约合规 + 路径真实
            r = subprocess.run(
                [sys.executable, str(SCRIPTS / "select_finalize.py"),
                 "--stage", "selection", "--out-dir", str(out)],
                capture_output=True, text=True,
                env={**os.environ, "ASCENDC_STRATEGY_ROOT": str(EXTERNAL_CATALOG)})
            assert r.returncode == 0, f"selection 门禁未过:\n{r.stdout}\n{r.stderr}"
            data = json.loads(sel.read_text(encoding="utf-8"))
            for item in data.get("selected_strategies", []):
                p = Path(item["strategy_path"])
                assert p.is_file(), f"策略 md 路径不存在: {p}"
                assert p.name[:-3] == item["strategy_id"]
                # 必须落在外部策略库内（证明是挂载而非副本）
                assert str(p.resolve()).startswith(str(EXTERNAL_CATALOG.resolve()))
            assert (out / "selection_report.md").is_file(), "缺少人读报告"
            return
        pytest.fail("多轮尝试后仍未产出合规 selection.json（skill 自闭环失败）")
