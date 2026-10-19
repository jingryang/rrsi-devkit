"""P-BC4 regression guard — opencode ``external_directory`` permission (S4 fix).

Proves LIVE that the real opencode runtime honors ``permission.external_directory:
"allow"`` (``_assemble_config``, ``opencode_backend.py``): a real primary agent
told to read a file OUTSIDE its spawn cwd (mirroring the worktree-external-path
pattern that triggered the original bug — see
``docs/plan/opencode-batch-concurrency/{01-problems,03-impl}.md``) completes
without hanging on opencode's default ``external_directory: "ask"`` (which has
no resolver in headless/non-interactive spawns and blocks indefinitely).

Why this shape and not a 5-concurrent full batch repro:
  - The bug's ROOT MECHANISM is a single opencode permission check
    (``permission=external_directory action=ask``) fired the first time any
    tool call (Bash/Read) touches a path outside the session's project
    directory. The 5-concurrent design-generator stall observed in production
    was 5 INDEPENDENT instances of this same single-spawn mechanism, not an
    emergent concurrency-only failure — proving the mechanism fixed for one
    spawn covers the regression surface. A full concurrent-batch ST would be
    expensive/flaky (worktree setup, cann-bench dependency, minutes-scale) for
    the same signal a single deterministic spawn already gives.
  - The original repro used open-ended agent exploration (``find``/``ls``)
    that organically wandered outside cwd over several turns before hitting the
    ask. Here the agent is instructed EXACTLY which Bash command to run against
    a known external path — deterministic, single-turn, seconds-scale. This
    mirrors ``test_tool_permission_dual_backend.py``'s established precedent:
    an explicit tool instruction removes model tool-choice non-determinism
    while still exercising the real capability under test end-to-end.

Marked @pytest.mark.llm (single-spawn, explicit-instruction, seconds-to-low-
minutes scale — NOT heavy_llm: no open-ended multi-turn pipeline). Bounded by
``message_timeout=180s`` (``make_backend``) — if the permission fix regresses,
this test fails in ≤180s via the S5 keepalive/hard-timeout watchdog rather than
hanging pytest indefinitely.
"""

from __future__ import annotations

import pytest

from tests.st._dual_backend import load_settings_env, make_backend, require_live_opencode

load_settings_env()

_MAX_ATTEMPTS = 3
_PROBE_NAME = "external_read_probe.txt"
_EXTERNAL_TOKEN = "EXTERNAL_DIRECTORY_PBC4_PROBE_OK"


def _write_prompt(external_path) -> str:
    return (
        "这是一个工具权限验证测试。当前工作目录**之外**存在一个文件：\n"
        f"`{external_path}`\n\n"
        f"请**使用 `Bash` 工具**读取该文件的内容，并将其原样写入当前工作目录下的 "
        f"`{_PROBE_NAME}` 文件（例如：`cat {external_path} > {_PROBE_NAME}`）。"
        "完成后即可结束，不需要读取或运行任何其它东西。"
    )


@pytest.mark.llm
def test_external_directory_permission_lets_agent_read_outside_cwd():
    """P-BC4 regression guard: a real primary agent (opencode) reading a file
    OUTSIDE its spawn cwd must complete, not hang on external_directory=ask.

    Root-cause context: production 5-concurrent design-generator spawns all
    stalled 12+ min on this exact opencode permission check when exploring a
    worktree path outside the per-exec artifacts cwd
    (docs/plan/opencode-batch-concurrency/01-problems.md P-BC4). Fixed by
    ``_assemble_config`` adding ``permission.external_directory: "allow"``.
    """
    require_live_opencode()

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # External file lives as a SIBLING of the agent's cwd (ws), mirroring
        # the real worktree layout (cann-bench-batch/<ts>/<op>/ sits outside the
        # per-exec artifacts/design/<agent> cwd) — outside opencode's session
        # project directory, so it trips external_directory if not allowed.
        external_dir = tmp_path / "external_task_dir"
        external_dir.mkdir(parents=True)
        external_file = external_dir / "task_file.txt"
        external_file.write_text(_EXTERNAL_TOKEN + "\n", encoding="utf-8")

        wrote = False
        last_status = None
        for attempt in range(_MAX_ATTEMPTS):
            ws = tmp_path / f"ws_{attempt}"
            ws.mkdir(parents=True, exist_ok=True)
            backend = make_backend("opencode", ws)
            result = backend.spawn(
                "ascendc-design-generator", _write_prompt(external_file), {},
                skills=[],
                primary_skill=None,
                working_dir=ws,
                stage_name="permcheck",
                branch_label="external_directory",
            )
            last_status = result.status
            probe = ws / _PROBE_NAME
            if probe.exists() and _EXTERNAL_TOKEN in probe.read_text(errors="ignore"):
                wrote = True
                break

        assert wrote, (
            f"the agent never produced {_PROBE_NAME} with the external file's "
            f"content across {_MAX_ATTEMPTS} attempts (last status={last_status}) "
            "— external_directory permission regression: the real opencode "
            "runtime blocked/hung on a path outside the spawn cwd. Check "
            "OpenCodeBackend._assemble_config's permission block still sets "
            "external_directory: allow.")
