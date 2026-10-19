"""ST — batch_self_evolve.sh 脚本结构守护（方案 E，L4 §54）。

验证瘦身后脚本的两条核心路径（不跑真实 LLM/NPU/CANN，用 fake cann-bench
git 仓 + fake ascendc-devkit CLI）：
  - 首跑：生成 manifest.yaml + 调 `run --batch` + 捕获 batch_id 写 .batch_id
  - 续跑：读 .batch_id → 调 `run --resume <batch_id> --cards ...`

DEFAULT_TASKS（脚本头部声明式路径，如 tasks/level2/<op>）由脚本解析得到——
fake cann-bench 按这些路径创建同名 task 目录，让 manifest 非空。

注：fake CLI 必须落可执行文件系统（pytest 默认 tmp_path 在 /tmp，常 noexec）。
使用仓库根目录下的进程级临时目录承载可执行物，兼容 HOME 只读的受限运行环境。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "batch_self_evolve.sh"


def _default_tasks_from_script() -> list[str]:
    """Parse the declarative ``DEFAULT_TASKS=(...)`` paths from the script head.

    Single source of truth: the fake cann-bench carries exactly the task dirs
    the script declares (e.g. ``tasks/level2/<op>``), so the fixture cannot
    drift from the script. Previously it hardcoded ``tasks/level1/<op>`` while
    the script moved to declarative ``tasks/level2/<op>`` paths → every op
    failed ``no_task_dir`` and the manifest came up empty.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    m = re.search(r"DEFAULT_TASKS=\(([^)]*)\)", text, re.S)
    assert m, "DEFAULT_TASKS=(...) block not found in batch_self_evolve.sh"
    paths = [ln.strip() for ln in m.group(1).splitlines()
             if ln.strip().startswith(("tasks/", "bench_lab/"))]
    assert paths, "no task paths parsed from DEFAULT_TASKS in batch_self_evolve.sh"
    return paths


# Derived from the script itself (not hand-maintained). NOTE: op 名 ≠ 目录
# basename——脚本现从 golden.py 顶层入口派生 op（§1.13），断言用 fixture 写出的
# golden 入口名，不再假设 basename==op。
DEFAULT_TASKS = _default_tasks_from_script()


@pytest.fixture
def work():
    """Exec-capable temp dir in the writable repository checkout."""
    d = SCRIPT.parents[1] / f".ascendc_bstest_{os.getpid()}"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir()
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _fake_cannbench(root: Path, task_paths: list[str]) -> dict[str, str]:
    """A git repo whose HEAD carries each declared task dir
    (<task_rel>/{proto.yaml,golden.py}) so the script's declarative
    DEFAULT_TASKS paths all resolve. ``git worktree add --detach`` from it
    carries those task dirs into the worktree.

    golden.py entry: one top-level function PER TASK, uniquely named — the
    script now derives ``op`` from the golden entry (not the dir basename,
    §1.13), and its dup_basename guard drops every task that shares an entry
    (all-``reference`` made 2/3 tasks vanish → manifest empty of them). Returns
    {task_rel: entry_name} so the manifest assertion checks the golden-derived
    op names (the script's actual naming rule), not a re-implemented
    "op == basename"."""
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    entries: dict[str, str] = {}
    for i, task_rel in enumerate(task_paths):
        d = root / task_rel
        d.mkdir(parents=True, exist_ok=True)
        (d / "proto.yaml").write_text(f"op: {d.name}\n", encoding="utf-8")
        entry = f"golden_impl_{i}"   # 唯一入口 → 脚本派生 op 互不冲突
        (d / "golden.py").write_text(
            f"def {entry}(*a, **k):\n    return a\n", encoding="utf-8")
        entries[task_rel] = entry
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", "init"],
        cwd=root, check=True)
    return entries


def _fake_cli(bin_dir: Path, call_log: Path) -> None:
    """Fake ascendc-devkit: records argv to call_log; prints a batch_id on
    --batch (so the script captures it); exits 0."""
    fake = bin_dir / "ascendc-devkit"
    fake.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        echo "$@" >> {call_log}
        if [[ "${{2:-}}" == "--batch" ]]; then
            echo "batch_id: 20260717-120000-a1b2c3" >&2
            echo "batch 20260717-120000-a1b2c3: 1/1 succeeded"
            exit 0
        elif [[ "${{2:-}}" == "--resume" ]]; then
            echo "resume batch ${{3:-}}" >&2
            exit 0
        fi
        exit 99
    """), encoding="utf-8")
    fake.chmod(0o755)


def _env(work: Path, bin_dir: Path, cann_bench: Path,
         worktree_root: Path) -> dict:
    # bin_dir FIRST so the fake CLI shadows any pyenv shim of the same name.
    return {
        **os.environ,
        "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
        "CANN_BENCH": str(cann_bench),
        "CANN_ENV_SCRIPT": "",           # skip sourcing CANN
        "WORKTREE_ROOT": str(worktree_root),
        "SKIP_INSTALL": "1",
        "NPU_COUNT": "2",
        "KEEP_WORKTREES": "0",           # clean worktrees after
    }


class TestBatchSelfEvolveScript:
    def test_first_run_generates_manifest_and_captures_batch_id(self, work):
        cann_bench = work / "cann-bench"
        entries = _fake_cannbench(cann_bench, DEFAULT_TASKS)
        bin_dir = work / "bin"
        bin_dir.mkdir()
        call_log = work / "cli_calls.log"
        _fake_cli(bin_dir, call_log)
        wt_root = work / "batch"

        completed = subprocess.run(
            ["bash", str(SCRIPT)],
            env=_env(work, bin_dir, cann_bench, wt_root),
            capture_output=True, text=True,
        )
        assert completed.returncode == 0, completed.stderr[-2000:]

        # manifest generated with one task per golden entry（op 名 = golden 入口，
        # 非目录 basename；golden_path 携带 task 相对路径）
        manifest = (wt_root / "manifest.yaml").read_text(encoding="utf-8")
        for task_rel, entry in entries.items():
            assert entry in manifest, f"golden 入口 {entry}（{task_rel}）未进 manifest"
            assert task_rel in manifest, f"{task_rel} 未进 manifest（golden_path）"
        assert "cards: [0,1]" in manifest
        assert "repo_profile: cann-bench" in manifest  # worktree path → explicit profile
        assert "workflow: self_evolve_op" in manifest
        assert "mode: new" in manifest
        # fake CLI invoked with run --batch <manifest>
        calls = call_log.read_text(encoding="utf-8").strip().splitlines()
        assert any(c.startswith("run --batch ") for c in calls), calls
        # batch_id captured to .batch_id (single handle, no per-op sidecars)
        bid_file = wt_root / ".batch_id"
        assert bid_file.exists()
        assert bid_file.read_text(encoding="utf-8").strip() == "20260717-120000-a1b2c3"
        # framework owns run records now — no per-op sidecars
        assert not list(wt_root.glob(".runid.*"))
        assert not list(wt_root.glob(".status.*"))
        assert not list(wt_root.glob(".lock.*"))
        # KEEP_WORKTREES=0 → 首跑创建的 worktree 已清理（按 golden 入口名删，非 basename）
        leftover = [p.name for p in wt_root.iterdir() if p.is_dir()]
        assert leftover == [], f"worktree 未清理（泄漏）: {leftover}"

    def test_resume_run_routes_to_run_resume_batch_id(self, work):
        # 续跑不建 worktree、不查 OPS task；fake cann-bench 仅满足 git 前置校验
        cann_bench = work / "cann-bench"
        _fake_cannbench(cann_bench, [])
        bin_dir = work / "bin"
        bin_dir.mkdir()
        call_log = work / "cli_calls.log"
        _fake_cli(bin_dir, call_log)
        wt_root = work / "batch"
        wt_root.mkdir()
        (wt_root / ".batch_id").write_text(
            "20260717-120000-existing", encoding="utf-8")

        env = _env(work, bin_dir, cann_bench, wt_root)
        env["RESUME"] = "1"
        completed = subprocess.run(
            ["bash", str(SCRIPT)],
            env=env, capture_output=True, text=True,
        )
        assert completed.returncode == 0, completed.stderr[-2000:]

        calls = call_log.read_text(encoding="utf-8").strip().splitlines()
        # 续跑路由到 run --resume <batch_id> --cards 0,1
        assert any(
            c.startswith("run --resume 20260717-120000-existing") and
            "--cards 0,1" in c for c in calls), calls
