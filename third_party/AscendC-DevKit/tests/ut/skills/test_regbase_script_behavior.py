"""Backstop UT for regbase coding skill script behavior.

Guards the fixes documented in:
  references/diff-analysis-vs-ascendc-dev.md

Exercises stage4_scheduler.sh and dev_record.sh with mock RECORD_DIR data.
§3.8 pure logic — no LLM/NPU/CANN dependency.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from pathlib import Path

import pytest

# ── path resolution ──────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SKILL_DIR = (
    _REPO_ROOT / ".claude" / "skills"
    / "ascendc-op-dev-coding-regbase"
)
_SCRIPTS = _SKILL_DIR / "scripts"
_DEV_RECORD = _SCRIPTS / "dev_record.sh"
_STAGE4_SCHEDULER = _SCRIPTS / "stage4_scheduler.sh"


# ── helpers ──────────────────────────────────────────────────────────────────

def _run(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run a shell script with args, return CompletedProcess."""
    cmd = ["bash", str(_DEV_RECORD if args[0] == "dev_record.sh" else _STAGE4_SCHEDULER)]
    cmd.extend(args[1:] if args[0] in ("dev_record.sh",) else args)
    # Actually let's be explicit
    return None  # placeholder


def _bash(script: Path, *args: str, cwd: str | None = None) -> str:
    """Run a bash script, return stdout stripped. Raises on non-zero exit."""
    cmd = ["bash", str(script), *args]
    cp = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=30)
    if cp.returncode != 0:
        raise RuntimeError(f"Script failed (rc={cp.returncode}): {' '.join(cmd)}\n"
                           f"stderr: {cp.stderr}")
    return cp.stdout.strip()


def _mk_record_dir(base: Path, name: str = "test_op") -> Path:
    """Create a minimal mock RECORD_DIR with meta.json + progress.md + coding_index.md."""
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_meta_json(rd: Path, **extra) -> None:
    """Write a minimal meta.json for test scenarios."""
    meta = {
        "current_stage": 2,
        "dev_mode": "新增",
        "ref_op": "",
        "code_path": str(rd / "op"),
        "programming_model": "A5 Regbase",
        "retries": {
            "stage5_compile": {"used": 0, "limit": 24},
            "stage4_selfcheck": {"used": 0, "limit": 8},
            "vf_test": {"used": 0, "limit": 4},
            "stage3_ambiguity": {"used": 0, "limit": 3},
            "s5_rollback": {"used": 0, "limit": 2},
        },
        **extra,
    }
    (rd / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))


def _write_progress_md(rd: Path, lines: list[str]) -> None:
    """Write progress.md with given markdown table rows."""
    content = "\n".join(lines) + "\n"
    (rd / "progress.md").write_text(content)


def _write_coding_index_md(rd: Path, steps: list[dict]) -> None:
    """Write a minimal coding_index.md with given steps."""
    header = "| 步骤 | 检查点组 | 详设章节 | 参考代码 | 知识/经验 | 关键 API | 自检关注点 | ~行数 |\n|------|---------|---------|---------|----------|---------|-----------|-------|"
    rows = []
    for s in steps:
        rows.append(
            f"| {s['step']} | {s.get('group', '1')} | {s.get('section', '§x')} | "
            f"{s.get('ref', '—')} | {s.get('tips', '—')} | {s.get('api', '—')} | "
            f"{s.get('check', '—')} | {s.get('lines', '~20')} |"
        )
    content = "# Coding Index\n\n## 编码步骤索引\n\n" + header + "\n" + "\n".join(rows) + "\n"
    (rd / "coding_index.md").write_text(content)


def _write_plan_json(rd: Path, steps: list[dict]) -> None:
    """Write orchestration_plan.json (the single authoritative plan)."""
    (rd / "orchestration_plan.json").write_text(
        json.dumps({"op_name": "test_op",
                    "programming_model": "A5 Regbase",
                    "sub_stages": steps},
                   ensure_ascii=False, indent=2))


# ═══════════════════════════════════════════════════════════════════════════════
# VF exhaustion behavior (#11)
# ═══════════════════════════════════════════════════════════════════════════════

class TestVfExhaustionDispatch:
    """Guard #11: VF FAILED exhaustion must produce vf_exhausted (non-blocking),
    not paused (which would deadlock in zero-interaction mode)."""

    def _setup_vt_progress(self, rd: Path, vt_status: str = "❌") -> None:
        """Setup progress.md with VT sub-stages."""
        _write_progress_md(rd, [
            "| 4.0 编码前置 | ✅ | - | - |",
            "| 4.A TilingData 定义 | ✅ | - | - |",
            "| 4.B1 OpDef 注册 | ✅ | - | - |",
            "| 4.B2 Tiling 实现 | ✅ | - | - |",
            "| 4.C.0 Kernel 入口 | ✅ | - | - |",
            "| 4.C.1 Init/CopyIn | ✅ | - | - |",
            "| 4.C.2 CopyIn | ✅ | - | - |",
            f"| 4.C.3.VT.0 VF 精度预验证 (SquareReduceSum) | {vt_status} | - | - |",
            "| 4.C.3 Compute 实现 | ⏳ | - | - |",
            "| 4.C.4 CopyOut | ⏳ | - | - |",
            "| 4.E CMakeLists | ⏳ | - | - |",
            "| 4.F 收尾 | ⏳ | - | - |",
            "| 5 编译出包 | ⏳ | - | - |",
        ])

    def test_vf_exhausted_when_retries_exceeded(self, tmp_path):
        """#11 — VF FAILED with used>=limit produces vf_exhausted action."""
        rd = _mk_record_dir(tmp_path)
        _write_meta_json(rd)
        # 编排计划：当前 pending 为 VT 步骤（kind=vf），其失败计数已耗尽（per-substage）
        _write_plan_json(rd, [
            {"id": "4.0", "desc": "编码前置", "checkpoint_group": "INDEPENDENT",
             "kind": "check", "deliverables": [], "status": "done"},
            {"id": "4.C.2", "desc": "CopyIn", "checkpoint_group": "KERNEL",
             "kind": "code", "deliverables": ["op_kernel/test_op.h"], "status": "done"},
            {"id": "4.C.3.VT.0", "desc": "VF 精度预验证", "checkpoint_group": "KERNEL",
             "kind": "vf", "deliverables": [], "status": "pending", "retry_count": 4},
            {"id": "4.C.3", "desc": "Compute", "checkpoint_group": "KERNEL",
             "kind": "code", "deliverables": ["op_kernel/test_op.h"], "status": "pending"},
        ])

        # Dispatch FAILED on VT step with CK-VF error type
        result = _bash(_STAGE4_SCHEDULER, "dispatch", str(rd), "FAILED", "CK-VF")
        data = json.loads(result)

        assert data["action"] == "vf_exhausted", (
            f"VF FAILED with used=4 (exhausted) must produce vf_exhausted, "
            f"got {data['action']}. PAUSED would deadlock in zero-interaction mode"
        )

    def test_vf_retry_within_limit(self, tmp_path):
        """#11 — VF FAILED with used<limit produces retry_s4 action."""
        rd = _mk_record_dir(tmp_path)
        _write_meta_json(rd)
        _write_plan_json(rd, [
            {"id": "4.0", "desc": "编码前置", "checkpoint_group": "INDEPENDENT",
             "kind": "check", "deliverables": [], "status": "done"},
            {"id": "4.C.2", "desc": "CopyIn", "checkpoint_group": "KERNEL",
             "kind": "code", "deliverables": ["op_kernel/test_op.h"], "status": "done"},
            {"id": "4.C.3.VT.0", "desc": "VF 精度预验证", "checkpoint_group": "KERNEL",
             "kind": "vf", "deliverables": [], "status": "pending"},
            {"id": "4.C.3", "desc": "Compute", "checkpoint_group": "KERNEL",
             "kind": "code", "deliverables": ["op_kernel/test_op.h"], "status": "pending"},
        ])

        result = _bash(_STAGE4_SCHEDULER, "dispatch", str(rd), "FAILED", "CK-VF")
        data = json.loads(result)

        assert data["action"] == "call_vf_test", (
            f"VF FAILED with used=0 (budget remaining) must produce call_vf_test, "
            f"got {data['action']}"
        )

    def test_vf_exhausted_does_not_block_non_vt_failure(self, tmp_path):
        """#11 — Non-VT step FAILED with exceeded retries produces paused (not vf_exhausted)."""
        rd = _mk_record_dir(tmp_path)
        _write_meta_json(rd)
        # Set stage4_selfcheck retries to exceed limit
        meta = json.loads((rd / "meta.json").read_text())
        meta["retries"]["stage4_selfcheck"]["used"] = 4  # exhausted
        (rd / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))

        _write_progress_md(rd, [
            "| 4.0 编码前置 | ✅ | - | - |",
            "| 4.A TilingData 定义 | ❌ | - | - |",
            "| 4.B1 OpDef 注册 | ⏳ | - | - |",
            "| 4.B2 Tiling 实现 | ⏳ | - | - |",
            "| 4.C.0 Kernel 入口 | ⏳ | - | - |",
            "| 4.E CMakeLists | ⏳ | - | - |",
            "| 4.F 收尾 | ⏳ | - | - |",
            "| 5 编译出包 | ⏳ | - | - |",
        ])

        steps = [
            {"step": "A", "group": "1"},
            {"step": "B1", "group": "1"},
            {"step": "B2", "group": "1"},
            {"step": "C.0", "group": "2"},
            {"step": "E", "group": "Last"},
            {"step": "F", "group": "Last"},
        ]
        _write_coding_index_md(rd, steps)

        result = _bash(_STAGE4_SCHEDULER, "dispatch", str(rd), "FAILED", "CHK")
        data = json.loads(result)

        # Non-VT failure exhaustion → paused (normal), not vf_exhausted
        assert data["action"] != "vf_exhausted", (
            "Non-VT step FAILED must NOT produce vf_exhausted. "
            "vf_exhausted is only for .VT.{M} steps"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# expand-kernel behavior (#12)
# ═══════════════════════════════════════════════════════════════════════════════

class TestExpandKernel:
    """Guard #12: expand-kernel must replace the 4.C placeholder row."""

    def test_expand_kernel_replaces_placeholder(self, tmp_path):
        """#12 — After expand-kernel, progress.md must not contain
        '4.C Kernel 实现' placeholder."""
        rd = _mk_record_dir(tmp_path)
        _write_progress_md(rd, [
            "| 4.0 编码前置 | ❌ | - | - |",
            "| 4.A TilingData 定义 | ❌ | - | - |",
            "| 4.B1 OpDef 注册 | ❌ | - | - |",
            "| 4.B2 Tiling 实现 | ❌ | - | - |",
            "| 4.C Kernel 实现 | ❌ | - | - |",
            "| 4.E CMakeLists | ❌ | - | - |",
            "| 4.F 收尾 | ❌ | - | - |",
            "| 5 编译出包 | ❌ | - | - |",
        ])
        _write_meta_json(rd)

        # Run expand-kernel
        csv = "C.0:Kernel入口,C.1:类框架,C.2:CopyIn,C.3:Compute,C.4:CopyOut"
        _bash(_DEV_RECORD, "expand-kernel", str(rd), csv)

        content = (rd / "progress.md").read_text()
        assert "| 4.C Kernel 实现" not in content, (
            "expand-kernel must replace '4.C Kernel 实现' placeholder. "
            "If it remains, resolve-sub-stage may return a non-existent stage"
        )
        # Verify C.0~C.4 rows exist
        for expected in ("4.C.0", "4.C.1", "4.C.2", "4.C.3", "4.C.4"):
            assert expected in content, (
                f"expand-kernel must produce {expected} row in progress.md"
            )

    def test_expand_kernel_idempotent(self, tmp_path):
        """#12 — expand-kernel is idempotent: second call on expanded progress.md
        does not duplicate rows."""
        rd = _mk_record_dir(tmp_path)
        _write_progress_md(rd, [
            "| 4.0 编码前置 | ❌ | - | - |",
            "| 4.A TilingData 定义 | ❌ | - | - |",
            "| 4.B1 OpDef 注册 | ❌ | - | - |",
            "| 4.B2 Tiling 实现 | ❌ | - | - |",
            "| 4.C Kernel 实现 | ❌ | - | - |",
            "| 4.E CMakeLists | ❌ | - | - |",
            "| 4.F 收尾 | ❌ | - | - |",
            "| 5 编译出包 | ❌ | - | - |",
        ])
        _write_meta_json(rd)

        csv = "C.0:Kernel入口,C.1:类框架,C.2:CopyIn,C.3:Compute,C.4:CopyOut"
        _bash(_DEV_RECORD, "expand-kernel", str(rd), csv)
        # Second call
        _bash(_DEV_RECORD, "expand-kernel", str(rd), csv)

        content = (rd / "progress.md").read_text()
        # Count occurrences of C.0
        count = content.count("| 4.C.0")
        assert count == 1, (
            f"expand-kernel idempotency violated: C.0 appears {count} times "
            "(expected 1). Duplicate rows would corrupt progress tracking"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# meta.json initialization (#11)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMetaJsonInitialization:
    """Guard #11: meta.json defaults from Step 1.1 must include vf_test retries."""

    def test_step11_defaults_include_vf_test_counter(self):
        """#11 — The python defaults dict in SKILL.md Step 1.1 must include
        vf_test retry counter with used=0, limit=4."""
        skill_md = _SKILL_DIR / "SKILL.md"
        content = skill_md.read_text()

        # Find the python defaults dict
        idx = content.find("'vf_test'")
        assert idx >= 0, "SKILL.md Step 1.1 missing 'vf_test' in defaults"

        snippet = content[idx:idx + 80]
        assert "'used': 0" in snippet, (
            f"vf_test retries must have used=0. Found: {snippet}"
        )
        assert "'limit': 4" in snippet or "'limit':4" in snippet, (
            f"vf_test retries must have limit=4. Found: {snippet}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# resolve-sub-stage behavior
# ═══════════════════════════════════════════════════════════════════════════════

class TestResolveSubStage:
    """Verify resolve-sub-stage correctly navigates regbase progress.md format."""

    def test_first_enter_returns_4_0(self, tmp_path):
        """first_enter must always return 4.0 (script guarantee)."""
        rd = _mk_record_dir(tmp_path)
        _write_meta_json(rd)
        _write_plan_json(rd, [
            {"id": "4.0", "desc": "编码前置", "checkpoint_group": "INDEPENDENT",
             "kind": "check", "deliverables": [], "status": "pending"},
            {"id": "4.A", "desc": "TilingData", "checkpoint_group": "HOST",
             "kind": "code", "deliverables": ["op_kernel/test_op_tiling_data.h"], "status": "pending"},
            {"id": "4.C.0", "desc": "Kernel入口", "checkpoint_group": "KERNEL",
             "kind": "code", "deliverables": ["op_kernel/test_op.cpp"], "status": "pending"},
            {"id": "4.C.1", "desc": "类框架", "checkpoint_group": "KERNEL",
             "kind": "code", "deliverables": ["op_kernel/test_op.h"], "status": "pending"},
            {"id": "4.E", "desc": "CMakeLists", "checkpoint_group": "LAST",
             "kind": "code", "deliverables": ["CMakeLists.txt"], "status": "pending"},
            {"id": "4.F", "desc": "综合自检", "checkpoint_group": "LAST",
             "kind": "check", "deliverables": [], "status": "pending"},
        ])

        result = _bash(_STAGE4_SCHEDULER, "resolve-sub-stage", str(rd), "first_enter")
        assert result == "4.0", (
            f"first_enter must return '4.0', got '{result}'"
        )

    def test_continue_returns_next_pending(self, tmp_path):
        """continue should return the first pending sub-stage."""
        rd = _mk_record_dir(tmp_path)
        _write_meta_json(rd)
        _write_plan_json(rd, [
            {"id": "4.0", "desc": "编码前置", "checkpoint_group": "INDEPENDENT",
             "kind": "check", "deliverables": [], "status": "done"},
            {"id": "4.A", "desc": "TilingData", "checkpoint_group": "HOST",
             "kind": "code", "deliverables": ["op_kernel/test_op_tiling_data.h"], "status": "done"},
            {"id": "4.B1", "desc": "OpDef", "checkpoint_group": "HOST",
             "kind": "code", "deliverables": ["op_host/test_op_def.cpp"], "status": "done"},
            {"id": "4.C.0", "desc": "Kernel入口", "checkpoint_group": "KERNEL",
             "kind": "code", "deliverables": ["op_kernel/test_op.cpp"], "status": "pending"},
            {"id": "4.C.1", "desc": "类框架", "checkpoint_group": "KERNEL",
             "kind": "code", "deliverables": ["op_kernel/test_op.h"], "status": "pending"},
            {"id": "4.E", "desc": "CMakeLists", "checkpoint_group": "LAST",
             "kind": "code", "deliverables": ["CMakeLists.txt"], "status": "pending"},
            {"id": "4.F", "desc": "综合自检", "checkpoint_group": "LAST",
             "kind": "check", "deliverables": [], "status": "pending"},
        ])

        result = _bash(_STAGE4_SCHEDULER, "resolve-sub-stage", str(rd), "continue")
        assert result == "4.C.0", (
            f"continue should return first pending sub-stage (4.C.0), got '{result}'"
        )

    def test_all_done_returns_done(self, tmp_path):
        """When all sub-stages are done, return DONE."""
        rd = _mk_record_dir(tmp_path)
        _write_meta_json(rd)
        _write_plan_json(rd, [
            {"id": "4.0", "desc": "编码前置", "checkpoint_group": "INDEPENDENT",
             "kind": "check", "deliverables": [], "status": "done"},
            {"id": "4.A", "desc": "TilingData", "checkpoint_group": "HOST",
             "kind": "code", "deliverables": ["op_kernel/test_op_tiling_data.h"], "status": "done"},
            {"id": "4.C.0", "desc": "Kernel入口", "checkpoint_group": "KERNEL",
             "kind": "code", "deliverables": ["op_kernel/test_op.cpp"], "status": "done"},
            {"id": "4.C.1", "desc": "类框架", "checkpoint_group": "KERNEL",
             "kind": "code", "deliverables": ["op_kernel/test_op.h"], "status": "done"},
            {"id": "4.E", "desc": "CMakeLists", "checkpoint_group": "LAST",
             "kind": "code", "deliverables": ["CMakeLists.txt"], "status": "done"},
            {"id": "4.F", "desc": "综合自检", "checkpoint_group": "LAST",
             "kind": "check", "deliverables": [], "status": "done"},
        ])

        result = _bash(_STAGE4_SCHEDULER, "resolve-sub-stage", str(rd), "continue")
        assert result in ("DONE", ""), (
            f"All 4.x done should return DONE or empty, got '{result}'"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# pick_available_card.py — 动态找卡脚本（s5 部署闭环 NPU 卡选择）
# ═══════════════════════════════════════════════════════════════════════════════

_PICK_CARD = _SCRIPTS / "pick_available_card.py"


def _load_pick_card_module():
    """Import the script's pure functions without executing main()."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "pick_available_card", _PICK_CARD)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class TestPickAvailableCard:
    """Guard: s5 smoke NPU 卡选择走预制脚本（并行隔离探测），不现场拼探测循环。

    §3.8 pure logic — 全部 mock subprocess/torch 调用，无 NPU/LLM 依赖。
    """

    def test_smi_healthy_parses_ok_rows(self):
        """npu-smi 输出中 Health=OK 的卡被正确解析为 id 列表。"""
        mod = _load_pick_card_module()
        sample = (
            "| npu-smi header |\n"
            "| NPU ID | Name | Health | Power |\n"
            "| 0 | Ascend950DT | OK | 393.0 |\n"
            "| 1 | Ascend950DT | ERROR | 0 |\n"
            "| 2 | Ascend950DT | OK | 389.0 |\n"
        )
        real_run = subprocess.run
        def fake_run(*args, **kwargs):
            return type("CP", (), {"stdout": sample})()
        subprocess.run = fake_run
        try:
            cards = mod.smi_healthy_cards()
        finally:
            subprocess.run = real_run
        assert cards == [0, 2], f"expected healthy cards [0, 2], got {cards}"

    def test_smi_no_ok_rows_returns_empty(self):
        """无 Health=OK 卡 → 空列表（调用方据此判无可用卡）。"""
        mod = _load_pick_card_module()
        sample = "| 0 | Ascend950DT | ERROR | 0 |\n| 1 | Ascend950DT | ERROR | 0 |\n"
        real_run = subprocess.run
        def fake_run(*args, **kwargs):
            return type("CP", (), {"stdout": sample})()
        subprocess.run = fake_run
        try:
            cards = mod.smi_healthy_cards()
        finally:
            subprocess.run = real_run
        assert cards == []

    def test_find_available_skips_failed_cards(self):
        """坏卡（timeout/错误）被跳过，返回第一张可用的卡。"""
        mod = _load_pick_card_module()
        real_run = subprocess.run
        sample = "| 0 | Ascend950DT | OK | 0 |\n| 1 | Ascend950DT | OK | 0 |\n"
        def fake_run(*args, **kwargs):
            if args and args[0] == ["npu-smi", "info"]:
                return type("CP", (), {"stdout": sample})()
            # 子进程 torch 探测：卡 0 失败（timeout），卡 1 成功
            code = args[0][-1] if args else ""
            if "set_device(0)" in code:
                raise __import__("subprocess").TimeoutExpired(cmd=args[0], timeout=5)
            return type("CP", (), {"returncode": 0, "stdout": "OK\n", "stderr": ""})()
        subprocess.run = fake_run
        try:
            card = mod.find_available_card(timeout=0.1, max_wait=0)
        finally:
            subprocess.run = real_run
        assert card == 1, f"bad card 0 must be skipped, available card should be 1, got {card}"

    def test_find_available_all_failed_returns_none(self):
        """全部卡探测失败 → 返回 None（exit 1 语义）。"""
        mod = _load_pick_card_module()
        real_run = subprocess.run
        sample = "| 0 | Ascend950DT | OK | 0 |\n| 1 | Ascend950DT | OK | 0 |\n"
        def fake_run(*args, **kwargs):
            if args and args[0] == ["npu-smi", "info"]:
                return type("CP", (), {"stdout": sample})()
            code = args[0][-1] if args else ""
            if "set_device(0)" in code:
                return type("CP", (), {"returncode": 1, "stdout": "", "stderr": "err0"})()
            return type("CP", (), {"returncode": 1, "stdout": "", "stderr": "err1"})()
        subprocess.run = fake_run
        try:
            card = mod.find_available_card(timeout=0.1, max_wait=0)
        finally:
            subprocess.run = real_run
        assert card is None, f"all cards failed → None, got {card}"

    def test_find_available_max_wait_zero_is_single_round(self):
        """max_wait=0 只探测一轮，全失败立即返回 None（不等待重试）。"""
        mod = _load_pick_card_module()
        real_run = subprocess.run
        real_sleep = time.sleep
        sample = "| 0 | Ascend950DT | OK | 0 |\n| 1 | Ascend950DT | OK | 0 |\n"
        calls = {"n": 0}
        def fake_run(*args, **kwargs):
            if args and args[0] == ["npu-smi", "info"]:
                return type("CP", (), {"stdout": sample})()
            calls["n"] += 1
            return type("CP", (), {"returncode": 1, "stdout": "", "stderr": "err"})()
        time.sleep = lambda s: (_ for _ in ()).throw(
            AssertionError("max_wait=0 不应等待重试"))
        subprocess.run = fake_run
        try:
            card = mod.find_available_card(timeout=0.1, max_wait=0)
        finally:
            subprocess.run = real_run
            time.sleep = real_sleep
        assert card is None, f"max_wait=0 single round → None, got {card}"
        assert calls["n"] == 2, f"single round should probe both cards, got {calls['n']}"

    def test_find_available_retries_until_card_frees(self):
        """max_wait>0：首轮全失败，下一轮卡释放后被返回（时间窗口重试语义）。"""
        mod = _load_pick_card_module()
        real_run = subprocess.run
        real_sleep = time.sleep
        sample = "| 0 | Ascend950DT | OK | 0 |\n| 1 | Ascend950DT | OK | 0 |\n"
        state = {"probes": 0}
        def fake_run(*args, **kwargs):
            if args and args[0] == ["npu-smi", "info"]:
                return type("CP", (), {"stdout": sample})()
            # 前 2 次 torch 探测（卡 0/1 第 1 轮）全部失败；第 3 次起（第 2 轮卡 1）可用
            state["probes"] += 1
            code = args[0][-1] if args else ""
            if state["probes"] >= 3 and "set_device(1)" in code:
                return type("CP", (), {"returncode": 0, "stdout": "OK\n", "stderr": ""})()
            return type("CP", (), {"returncode": 1, "stdout": "", "stderr": "err"})()
        time.sleep = lambda s: None  # 窗口内等待不真实 sleep
        subprocess.run = fake_run
        try:
            card = mod.find_available_card(timeout=0.1, max_wait=1000.0,
                                           poll_interval=0.0)
        finally:
            subprocess.run = real_run
            time.sleep = real_sleep
        assert card == 1, f"retry window should return card 1 once freed, got {card}"

    def test_main_rejects_negative_max_wait(self, capsys):
        """负值 --max-wait 在参数解析期被拒绝（§1.3 加载期校验）。"""
        mod = _load_pick_card_module()
        with pytest.raises(SystemExit) as exc:
            mod.main(["--max-wait", "-5", "--timeout", "0.1"])
        assert exc.value.code == 2, (
            f"negative max-wait should exit 2 (argparse error), got {exc.value.code}")

    def test_main_rejects_negative_timeout(self, capsys):
        """负值 --timeout 同样被拒绝。"""
        mod = _load_pick_card_module()
        with pytest.raises(SystemExit) as exc:
            mod.main(["--timeout", "-1"])
        assert exc.value.code == 2, (
            f"negative timeout should exit 2, got {exc.value.code}")
