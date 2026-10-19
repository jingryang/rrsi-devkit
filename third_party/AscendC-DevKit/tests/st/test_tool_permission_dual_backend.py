"""相2 §2.4 Spike-3 — dual-backend tool-permission enforcement (Bash-create allow).

Proves LIVE that the ``permission`` block each backend assembles is actually
CONSUMED by the real agent runtime: an agent granted a file-producing tool
produces a real file artifact through the real transport, on BOTH backends
(directive: 相2 每步 claude + opencode 双侧真跑，不留单边盲区).

Why a Bash-create and not "let the model pick a tool":
  - design-generator's manifest grants ``Bash`` (create-capable) and ``Edit``,
    but NOT ``Write``. ``Edit`` does string-replace on an EXISTING file — it
    cannot CREATE a new one. So the only granted tool that can create the probe
    file is ``Bash``. An earlier version of this test told the model to "create
    a file" and let it choose the tool; the model intermittently picked the
    ungranted ``Write`` (correctly denied) → no file → flaky FAIL that looked
    like a permission regression but was really tool-choice non-determinism
    against an unavailable tool. Instructing ``Bash`` explicitly removes that
    ambiguity while still exercising the real capability under test: a *granted*
    file-producing tool is honored end-to-end. A real permission regression
    (Bash removed from the allow policy / not projected to the runtime) still
    fails this test; only the model's tool-lottery non-determinism is removed
    (§3.10 — bounded determinism, not masking).
  - This is the exact capability the whole codegen pipeline stands on: without a
    granted file-producing tool honored end-to-end, no operator source is ever
    produced. So it is the high-value live signal (§3.7).

Marked @pytest.mark.llm (single-spawn write, seconds-scale — NOT heavy_llm: no
minutes-long multi-turn pipeline).
"""

from __future__ import annotations

import pytest

from tests.st._dual_backend import (
    ensure_rg_on_path,
    has_anthropic,
    load_settings_env,
    make_backend,
)

load_settings_env()

_MAX_ATTEMPTS = 3
_ARTIFACT_NAME = "permission_probe.txt"
_ARTIFACT_TOKEN = "BASH_ALLOWED_OK"

_WRITE_PROMPT = (
    "这是一个工具权限验证测试。请**使用 `Bash` 工具**在当前工作目录下创建一个名为 "
    f"`{_ARTIFACT_NAME}` 的文件，文件内容为一行文本：`{_ARTIFACT_TOKEN}`"
    f"（例如：`echo '{_ARTIFACT_TOKEN}' > {_ARTIFACT_NAME}`）。"
    "创建完成后即可结束，不需要读取或运行任何其它东西。"
)


@pytest.mark.llm
@pytest.mark.parametrize("kind", ["claude", "opencode"])
def test_edit_permission_lets_agent_write_artifact_dual_backend(kind, tmp_path):
    """Permission parity: an agent with a granted file-producing tool (Bash)
    actually creates a file through the real backend runtime, on BOTH backends."""
    if not has_anthropic():
        pytest.skip("Anthropic not configured")
    if kind == "opencode":
        ensure_rg_on_path()

    wrote = False
    for attempt in range(_MAX_ATTEMPTS):
        ws = tmp_path / f"ws_{attempt}"
        ws.mkdir(parents=True, exist_ok=True)
        backend = make_backend(kind, ws)
        backend.spawn(
            "ascendc-design-generator", _WRITE_PROMPT, {},
            skills=[],
            primary_skill=None,
            working_dir=ws,
            stage_name="permcheck",
            branch_label="edit",
        )
        probe = ws / _ARTIFACT_NAME
        if probe.exists() and _ARTIFACT_TOKEN in probe.read_text(errors="ignore"):
            wrote = True
            break

    assert wrote, (
        f"[{kind}] the agent never produced {_ARTIFACT_NAME} across "
        f"{_MAX_ATTEMPTS} attempts — the granted Bash file-producing tool was "
        "not honored by the real runtime (permission regression: check the "
        "assembled permission block and how the backend passes it to the agent)")
