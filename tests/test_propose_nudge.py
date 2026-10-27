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
"""proposer 的空转提醒。

背景（20261027 r0）：proposer 用 29 次工具调用、1 小时 56 分读证据，只做了
1 次编辑就死在网关抖动上。运行期没有任何东西告诉它"你已经没时间只读了"，
轮次预算全花在探索上。digester 自 20261023 起就有同款提醒，proposer 漏了。

    python3 -m pytest -q tests/test_propose_nudge.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import rrsi.propose as P  # noqa: E402


class _Domain:
    name = "test"
    source_exts = {".py"}
    briefs = {"proposer": "brief"}

    def task_row(self, tid, rec, tr):
        return f"{tid}"

    def render_trace(self, rec, detail=False):
        return "[step 1] AGENT a TEXT: hello"

    def product_experiences(self, runs):
        return ""


def _harness(tmp_path: Path) -> Path:
    d = tmp_path / "harness"
    d.mkdir()
    (d / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    return d


def _run(tmp_path, monkeypatch, script, max_turns=None):
    """用脚本化响应跑一遍 propose，返回 (result, prompts)。"""
    if max_turns is not None:
        monkeypatch.setattr(P, "MAX_TURNS", max_turns)
    prompts: list[str] = []

    def fake_generate(prompt, **kw):
        prompts.append(prompt)
        step = script.pop(0) if script else {"action": "done", "summary": "s",
                                             "edits": [{"id": "C1",
                                                        "component": "prompt",
                                                        "hypothesis": "h",
                                                        "targets_mode": "m",
                                                        "predicted_affected": ["t"],
                                                        "retroactive_check": "r"}]}
        return json.dumps(step)

    monkeypatch.setattr(P, "generate", fake_generate)
    out = P.propose(_Domain(), _harness(tmp_path), {}, [], "", "", 4,
                    {"text": ""}, False, [], traces={}, per_task={},
                    findings=[], scoreboard=[], variant_brief="", model="m")
    return out, prompts


def test_nudge_fires_when_turns_half_gone_with_no_edits(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "MAX_TURNS", 8)
    script = [{"action": "list_files"} for _ in range(8)]
    out, prompts = _run(tmp_path, monkeypatch, script)
    nudged = [p for p in prompts if "ZERO file changes" in p]
    assert nudged, "no nudged prompt was ever sent"
    # 第 4 轮（8 的一半）那条 prompt 里就应该带上提醒
    assert "ZERO file changes" not in prompts[2]
    assert "ZERO file changes" in prompts[3]


def test_nudge_does_not_fire_once_a_file_was_edited(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "MAX_TURNS", 8)
    script = [
        {"action": "edit_file", "path": "mod.py",
         "old": "return 1", "new": "return 2"},
        *[{"action": "list_files"} for _ in range(7)],
    ]
    _out, prompts = _run(tmp_path, monkeypatch, script)
    assert not any("ZERO file changes" in p for p in prompts), \
        "nudged a candidate that had already edited"


def test_second_nudge_at_three_quarters(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "MAX_TURNS", 8)
    script = [{"action": "list_files"} for _ in range(8)]
    _out, prompts = _run(tmp_path, monkeypatch, script)
    # 6/8 = 3/4，应该再多一条（两条提醒各自只出现一次）
    first = [p for p in prompts if "ZERO file changes" in p]
    assert len(first) >= 2, f"expected 3/4 nudge too, got {len(first)}"


def test_nudge_keeps_the_candidate_admissible(tmp_path, monkeypatch):
    """提醒只是加一行系统消息，不能改变 done() 的判定。"""
    monkeypatch.setattr(P, "MAX_TURNS", 8)
    script = [{"action": "list_files"} for _ in range(4)]
    script.append({"action": "done", "summary": "s",
                   "edits": [{"id": "C1", "component": "prompt", "hypothesis": "h",
                              "targets_mode": "m", "predicted_affected": ["t"],
                              "retroactive_check": "r"}]})
    out, _prompts = _run(tmp_path, monkeypatch, script)
    # 没有任何编辑时 done 会被打回并要求真的改文件，这是既有行为
    assert out["status"] != "done" or out["n_edits"] > 0
