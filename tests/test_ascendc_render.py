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
"""ascendc-devkit 证据渲染：源码段不得吃掉轨迹段。

背景（20261026 r0）：DevKit 在算子目录里植入 ``.claude/skills`` 软链，
``copy_op_sources`` 用默认的 ``symlinks=False`` 把它解引用成数千个技能文件，
``_read_tree`` 又按字典序遍历、预算在 skill 文件上耗尽，于是
"SUBMITTED OPERATOR SOURCE" 段里一个算子文件都没有、却撑爆了整篇文档，
把 ``=== TRAJECTORY ===`` 挤到 ;0 条 step。五个 digester 全部
"hit max turns without returning"，分析报告为空。

    python3 -m pytest -q tests/test_ascendc_render.py
"""

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "domains" / "ascendc-devkit"))
sys.path.insert(0, str(ROOT / "domains" / "ascendc-devkit" / "bench"))

import adapter  # noqa: E402
import render  # noqa: E402
import run_tasks  # noqa: E402


def _skill_tree(root: Path, files: int = 40) -> tuple[Path, Path]:
    """模拟 DevKit 植入的技能锚点：软链指向一棵大得多的技能树。

    返回 ``(worktree, op_dir)``，布局与 cann-bench 一致
    （``<worktree>/examples/aclnn_launch_example/csrc/ops/swi_glu``）。
    """
    target = root / "outside_skills"
    for i in range(files):
        d = target / f"skill{i:02d}" / "scripts"
        d.mkdir(parents=True, exist_ok=True)
        (d / "helper.py").write_text("x = 1\n" * 500, encoding="utf-8")
    worktree = root / "wt"
    op = worktree / run_tasks.cfg.OP_SUBDIR / "swi_glu"
    (op / ".claude").mkdir(parents=True, exist_ok=True)
    (op / ".claude" / "skills").symlink_to(target)
    for name in ("CMakeLists.txt", "op_kernel/kernel.cpp", "op_host/tiling.cpp"):
        p = op / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"// {name}\n" + "int x;\n" * 200, encoding="utf-8")
    return worktree, op


def test_copy_op_sources_does_not_follow_skill_symlink(tmp_path):
    """`.claude` 不拷、软链不解引用——否则 trial 目录被技能树灌满。"""
    worktree, _op = _skill_tree(tmp_path)
    dst = tmp_path / "op_src"
    copied = run_tasks.copy_op_sources(worktree, "swi_glu", dst)

    assert copied == 3, _tree(dst)
    assert not (dst / ".claude").exists(), "the skill anchor was copied"
    assert not (dst / "outside_skills").exists(), "the symlink was dereferenced"
    assert (dst / "op_kernel" / "kernel.cpp").is_file()


def _tree(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def test_read_tree_prefers_operator_dirs_and_skips_dot_dirs(tmp_path):
    """预算先给 op_*，点开头目录与软链一律不进源码表。"""
    _wt, op = _skill_tree(tmp_path, files=40)
    (op / "zzz_after_budget.txt").write_text("late\n", encoding="utf-8")
    sources = adapter.AscendCDevKitDomain._read_tree(op)

    assert set(sources) == {"CMakeLists.txt", "op_kernel/kernel.cpp",
                            "op_host/tiling.cpp", "zzz_after_budget.txt"}, sources
    assert not any(k.startswith(".") for k in sources)
    # 算子实现目录排在散文件之前，预算先用在这里。
    assert list(sources)[0].startswith("op_")


def test_read_tree_survives_skill_pollution(tmp_path):
    """即使 op_src 已经被旧版本污染（真实 .claude 目录），也不返回技能文件。"""
    _wt, op = _skill_tree(tmp_path, files=5)
    skills = op / ".claude" / "skills"
    skills.unlink()
    shutil.copytree(tmp_path / "outside_skills", skills)
    sources = adapter.AscendCDevKitDomain._read_tree(op)

    assert "op_kernel/kernel.cpp" in sources
    assert not any(".claude" in k for k in sources), sources


def _rec(tmp_path: Path, sources: dict) -> dict:
    run_dir = tmp_path / "run"
    agents = run_dir / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    recs = [{"role": "agent", "blocks": [
        {"kind": "text", "text": f"step text {i} " + "y" * 200}]} for i in range(120)]
    (agents / "coder-1.jsonl").write_text(
        "\n".join(json.dumps(r) for r in recs), encoding="utf-8")
    return {"task_id": "swi_glu", "op": {"name": "swi_glu"}, "meta": {},
            "verdict": {"overall_score": 71.28, "compile_score": 20.0,
                        "function_score": 30.0, "performance_score": 21.28},
            "report": {}, "run_dir": str(run_dir), "sources": sources}


def test_trajectory_survives_a_bloated_source_listing(tmp_path):
    """回归：源码段再大也不能把轨迹段挤出文档。"""
    sources = {f"op_kernel/file{i:02d}.cpp": "z" * 20_000 for i in range(40)}
    for detail in (False, True):
        text = render.render_full(_rec(tmp_path, sources), detail=detail)
        assert "=== TRAJECTORY ===" in text
        body = text[text.find("=== TRAJECTORY ==="):]
        assert "[step 1]" in body, f"detail={detail}: no step 1"
        assert "[step 100]" in body, f"detail={detail}: trajectory truncated"
        limit = render.MAX_CHARS_DETAIL if detail else render.MAX_CHARS
        assert len(text) <= limit


def test_source_section_budget_is_bounded(tmp_path):
    sources = {f"f{i}.cpp": "q" * 50_000 for i in range(10)}
    text = render.render_sources(sources, detail=True, budget=12_000)
    assert len(text) <= 12_000 + 200
    assert "more file(s) omitted" in text


def test_detail_document_keeps_the_whole_transcript(tmp_path):
    """detail 文档给 digester 用：600 步以内的轨迹必须完整，不出现断档。"""
    rec = _rec(tmp_path, {"op_kernel/k.cpp": "w" * 30_000})
    text = render.render_full(rec, detail=True)
    steps = [int(s) for s in __import__("re").findall(r"\[step (\d+)\]", text)]
    assert steps == list(range(1, 121)), "steps missing from the detail document"
