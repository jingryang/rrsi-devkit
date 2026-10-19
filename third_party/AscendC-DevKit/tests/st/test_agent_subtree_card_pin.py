"""P13/step-116 — agent 子树卡 pin 的真实链路守护（dual-backend @llm）。

结构 pin 的执行机制是 env 继承：backend ctor 的 ``card_pin`` → serve/CLI 子
进程 env（``_build_serve_env`` / ``ClaudeAgentOptions(env=...)``）→ bash 工具
子进程继承。UT 已锚定 env 组装两侧；本 ST 补最后一环的活体证据——**真实
spawn 的 agent 在自己 bash 里看到的 env 确实携带双变量 pin**（opencode 侧
同时排除「serve 给工具子进程洗 env」的可能；claude 侧核验 SDK ``options.env``
确为增量合并语义——这是 L4 文档挂着的待核验项）。

单 spawn、秒-分钟级：@llm 非 heavy_llm（§3.11）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.st._dual_backend import (
    ensure_rg_on_path,
    has_anthropic,
    load_settings_env,
    make_backend,
    require_live_opencode,
)

load_settings_env()

# 任意非零卡：bash 只打印 env 不碰 NPU，卡无需空闲；非零值让「未注入」
# （继承到机器默认/空）与「注入成功」可区分。
PIN_CARD = 3

_PROMPT = (
    "Run this exact shell command with the Bash tool and reply with ONLY its "
    "raw output, nothing else:\n"
    "env | grep -E '^(ASCEND_RT_VISIBLE_DEVICES|ASCEND_NPU_ID)=' || echo NO_PIN"
)


@pytest.mark.llm
@pytest.mark.parametrize("kind", ["claude", "opencode"])
def test_agent_bash_sees_op_card_pin(kind, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    if kind == "claude" and not has_anthropic():
        pytest.skip("claude: no Anthropic credentials (§3.7 honest env skip)")
    if kind == "opencode":
        require_live_opencode()

    backend = make_backend(kind, ws, card_pin=PIN_CARD)
    result = backend.spawn(
        agent_name="claude",  # catch-all agent（Tools: *）——只需 bash
        prompt=_PROMPT,
        context={},
        skills=None,
    )
    assert result.status == "ok", (
        f"spawn failed: status={result.status} err={getattr(result, 'error', '')}")

    # AgentResult carries the persisted transcript path; the assistant's reply
    # (with the env output) lives there. NOTE: assert on the tool's OUTPUT
    # field only — the command string itself (echoed in tool_input) contains
    # "NO_PIN" and the variable names, which would make a string-containment
    # check vacuously pass / fail spuriously.
    text = ""
    if result.transcript is not None:
        text = Path(result.transcript).read_text(encoding="utf-8", errors="replace")
    import json as _json
    outputs = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            rec = _json.loads(line)
        except _json.JSONDecodeError:
            continue
        for blk in rec.get("blocks", []):
            kind = str(blk.get("kind", ""))
            if kind == "tool_result":            # claude shape
                outputs.append(str(blk.get("content") or ""))
            tool_out = (blk.get("tool_input") or {})   # opencode shape
            if isinstance(tool_out, dict) and "output" in tool_out:
                outputs.append(str(tool_out.get("output") or ""))
    joined = "".join(outputs).replace(" ", "")
    assert joined, "no bash tool output found in transcript (§3.9 real-link needs it)"
    assert f"ASCEND_RT_VISIBLE_DEVICES={PIN_CARD}" in joined, (
        f"agent bash did not see the physical-card pin; outputs: {outputs[:400]}")
    assert "ASCEND_NPU_ID=0" in joined, (
        f"agent bash did not see the logical-0 pin; outputs: {outputs[:400]}")
    assert "NO_PIN" not in joined, "pin variables absent from the agent bash env"
