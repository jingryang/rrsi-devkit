# Copyright 2026 The rrsi Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""轨迹的可寻址性：多阶段按流水线排序、区间读真的生效、grep 便宜。

背景（20261027 r0）：一次 trial 的轨迹有 22 个 agent 会话 / 2400+ 步。
渲染按**文件名**排序（`ascendc-design-generator-01` < `ascendc-dev-s4-coding-01`），
再用 600 步上限一刀切，于是只有第一个 agent 出现在文档里，coding / compile /
precision 阶段一条都没有；而 `_read_trace` 的区间过滤把 `in_grades` 置真后再
不复位，`read_trace(30,60)` 与 `read_trace(500,520)` 返回完全相同的内容。

    python3 -m pytest -q tests/test_ascendc_trace_access.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "domains" / "ascendc-devkit"))

import adapter  # noqa: E402
import render  # noqa: E402
import rrsi.propose as propose  # noqa: E402


def _session(path: Path, ts: int, turns: int, agent_tag: str) -> None:
    recs = [{"ts": ts + i, "role": "agent",
             "blocks": [{"kind": "text", "text": f"{agent_tag} turn {i} " + "z" * 120},
                        {"kind": "tool_use", "tool_name": "bash",
                         "tool_input": {"cmd": f"echo {i}"}}]}
            for i in range(turns)]
    path.write_text("\n".join(json.dumps(r) for r in recs), encoding="utf-8")


def _run_dir(root: Path) -> Path:
    """三阶段会话；文件名顺序与流水线顺序故意相反。"""
    rd = root / "run"
    agents = rd / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    (rd / "state_snapshot.json").write_text("{}", encoding="utf-8")
    _session(agents / "zzz-coding-01.jsonl", 3000, 30, "CODING")     # 最后跑
    _session(agents / "aaa-design-01.jsonl", 1000, 60, "DESIGN")     # 最先跑
    _session(agents / "mmm-compile-01.jsonl", 2000, 20, "COMPILE")   # 中间
    return rd


def test_sessions_follow_pipeline_order_not_filename(tmp_path):
    rows = render.sessions(_run_dir(tmp_path))
    assert [a for _t, _p, a in rows] == ["aaa-design", "mmm-compile", "zzz-coding"]
    assert "DESIGN" not in rows[0][1].read_text()[:200] or True   # first is design
    assert "DESIGN" in rows[0][1].read_text()


def test_step_budget_is_spread_across_stages(tmp_path):
    """600 步上限下，每个阶段都要有代表（曾经只有第一个阶段）。"""
    text = render.render_transcript(_run_dir(tmp_path), detail=True, max_steps=60)
    assert "DESIGN" in text and "COMPILE" in text and "CODING" in text
    step_nums = [int(s) for s in __import__("re").findall(r"\[step (\d+)\]", text)]
    assert step_nums == sorted(step_nums)          # 单调，无错位


def test_allocate_budget_keeps_every_stage_and_respects_cap():
    counts = [600, 40, 40]
    alloc = render._allocate_step_budget(counts, 120, floor=12)
    assert sum(alloc) <= 120
    assert all(a > 0 for a in alloc), alloc
    assert alloc[0] < counts[0]                    # 大阶段被压缩


def test_allocate_budget_without_pressure_returns_everything():
    assert render._allocate_step_budget([5, 5], 100) == [5, 5]


def test_index_lists_every_stage_and_is_cheap(tmp_path):
    index = render.render_index(_run_dir(tmp_path))
    rows = [ln for ln in index.splitlines() if ln.strip().startswith("stage ")]
    assert len(rows) == 3, index
    assert "coding" in index and "design" in index and "compile" in index
    assert len(index) < 2_000, len(index)


def test_stage_files_are_written_one_per_session(tmp_path):
    rd = _run_dir(tmp_path)
    names = render.render_stage_files(rd, tmp_path / "out", detail=True)
    assert "index.txt" in names and len(names) == 4
    joined = "\n".join(n for n in names if n != "index.txt")
    assert joined.count(".txt") == 3


def _domain_rec(tmp_path: Path) -> dict:
    return {"task_id": "op", "op": {"name": "op"}, "meta": {}, "verdict": {},
            "report": {}, "run_dir": str(_run_dir(tmp_path)), "sources": {}}


def test_read_trace_window_is_honoured(tmp_path):
    """回归：区间读曾经是空操作，任何区间都返回整篇。"""
    rec = _domain_rec(tmp_path)
    traces = {"op": rec}
    cache: dict = {}
    lo = propose._read_trace(render and adapter.AscendCDevKitDomain(), traces, "op",
                             10, 12, cache, False)
    hi = propose._read_trace(adapter.AscendCDevKitDomain(), traces, "op",
                             100, 102, cache, False)
    assert lo != hi, "different windows returned identical text"
    steps_lo = [int(s) for s in __import__("re").findall(r"\[step (\d+)\]", lo)]
    assert steps_lo and min(steps_lo) >= 10 and max(steps_lo) <= 12


def test_read_trace_reaches_late_stages_via_stage_index(tmp_path):
    """回归：2400 步的 run 里，后面的阶段曾经完全不可达。"""
    rec = _domain_rec(tmp_path)
    traces = {"op": rec}
    cache: dict = {}
    out = propose._read_trace(adapter.AscendCDevKitDomain(), traces, "op",
                              1, 5, cache, True, stage=3)   # 最后一个阶段
    assert "CODING" in out, out[:400]
    assert "[step " in out


def test_grep_trace_returns_only_matching_step_lines(tmp_path):
    rec = _domain_rec(tmp_path)
    out = propose._grep_trace(adapter.AscendCDevKitDomain(), {"op": rec}, "op",
                              "CODING turn 7", 5, {})
    assert "CODING turn 7" in out
    assert len(out) < 2_000
    assert all(line.startswith("[step ") for line in out.splitlines())


def test_transcript_fold_keeps_the_newest_and_stubs_the_oldest(monkeypatch):
    monkeypatch.setattr(propose, "TRANSCRIPT_BUDGET", 5_000)
    monkeypatch.setattr(propose, "ELIDE_MIN_CHARS", 1_000)
    entries = [f'\n[you] {{"action":"read_trace","n":{i}}}\n[result] ' + "x" * 4_000
               for i in range(4)]
    out = propose._fold_transcript(entries)
    assert len(out) <= 5_000 + 1_000
    assert "x" * 4_000 in out                      # the newest survives intact
    assert "[result elided" in out                 # the oldest is stubbed
    assert '"n":0' in out                          # …but its action line stays
