"""step-97 — 判死前取证（pre-trip evidence）+ 杀工具不杀会话。

L3 冻结（docs/plan/turn-stall-pretrip-evidence/）：看门狗（turn_stall /
keepalive）判死只看 SSE 静默，而 bash 执行期 opencode 不发任何帧——三信号
同时失明；同一时刻「工具在飞/已跑多久/部分输出」躺在本 spawn 的 opencode db
（99c4c0 kill-3 实证：bash status="running" 605s 被误杀）。判死前查一次 db：

  - running 且未超 tool_grace_s → 存活复位（+节流透出部分输出一行）；
  - running 超界 → **杀工具进程树不杀 serve**（agent 带工具错误继续，
    会话/上下文/工作树全保住）；
  - 无 running 证据 / 超界且无活进程匹配（serve 楔死）→ 现行 kill-serve。

决策表闭合性：第三行依赖「超界 + 匹配失败 → kill-serve」——它是 serve 楔死
形态（子进程死透、part 状态卡 running）的唯一检出通路。hard cap 不受门控。
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import threading
import time
import types
from pathlib import Path

import pytest

from ascendc_devkit.capabilities.agent.opencode_backend import (
    OpenCodeBackend, _KeepaliveAbort)


# ———————————————————————— probe 单元 ————————————————————————

def _make_db(tmp_path: Path, parts: list[dict]) -> Path:
    ws = tmp_path / "ws"
    db = ws / ".opencode_home" / "data" / "opencode" / "opencode.db"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE part (id TEXT PRIMARY KEY, session_id TEXT, "
        "data TEXT, time_created INTEGER)")
    now = int(time.time() * 1000)
    for i, p in enumerate(parts):
        conn.execute(
            "INSERT INTO part (id, session_id, data, time_created) "
            "VALUES (?, 's1', ?, ?)",
            (f"p{i}", json.dumps(p), now + i))
    conn.commit()
    conn.close()
    return ws


def _tool_part(status: str, *, started_ms=None, command="repro.py",
               output=None) -> dict:
    state = {"status": status, "input": {"command": command}}
    if started_ms is not None:
        state["time"] = {"start": started_ms}
    if output is not None:
        state["metadata"] = {"output": output}
    return {"type": "tool", "tool": "bash", "state": state}


class TestProbeRunningTool:
    def _backend(self, ws) -> OpenCodeBackend:
        b = OpenCodeBackend.__new__(OpenCodeBackend)
        b._decision_workspace = str(ws)
        return b

    def test_running_tool_found_with_partial_output(self, tmp_path):
        ws = _make_db(tmp_path, [
            {"type": "text", "text": "thinking..."},
            _tool_part("running", started_ms=int(time.time() * 1000) - 5000,
                       command="python3 /tmp/repro/run_case.py n=458752",
                       output="n=458752 run1: \n"),
        ])
        ev = self._backend(ws)._probe_running_tool("s1")
        assert ev is not None
        assert ev["status"] == "running"
        assert "run_case.py" in ev["command"]
        assert "n=458752" in ev["output_tail"]
        assert ev["started_ms"] is not None

    def test_completed_tool_found(self, tmp_path):
        ws = _make_db(tmp_path, [_tool_part("completed")])
        ev = self._backend(ws)._probe_running_tool("s1")
        assert ev["status"] == "completed"

    def test_no_db_returns_none(self, tmp_path):
        b = self._backend(tmp_path / "nonexistent")
        assert b._probe_running_tool("s1") is None

    def test_no_session_returns_none(self, tmp_path):
        ws = _make_db(tmp_path, [_tool_part("running")])
        assert self._backend(ws)._probe_running_tool("other") is None

    def test_no_workspace_returns_none(self):
        b = OpenCodeBackend.__new__(OpenCodeBackend)
        b._decision_workspace = None
        assert b._probe_running_tool("s1") is None


# ———————————————————————— 判定三分支 ————————————————————————

class TestPretripVerdicts:
    def _backend(self, grace=1800.0) -> OpenCodeBackend:
        b = OpenCodeBackend.__new__(OpenCodeBackend)
        b._decision_workspace = None
        b._tool_grace_s = grace
        return b

    def _sse(self):
        return types.SimpleNamespace(
            state={"turn_ts": time.time() - 999, "last_event_ts": time.time() - 999})

    def test_alive_resets_baselines(self, monkeypatch):
        b = self._backend()
        monkeypatch.setattr(b, "_probe_running_tool", lambda sid: {
            "status": "running", "command": "x",
            "output_tail": "partial", "started_ms": int(time.time() * 1000)})
        sse = self._sse()
        assert b._pretrip_tool_evidence(None, sse, "s1", "ag", "", time.time()) == "alive"
        assert sse.state["turn_ts"] > time.time() - 5
        assert sse.state["last_event_ts"] > time.time() - 5

    def test_over_grace_kill_matched_returns_killed(self, monkeypatch):
        b = self._backend(grace=10.0)
        monkeypatch.setattr(b, "_probe_running_tool", lambda sid: {
            "status": "running", "command": "x", "output_tail": "",
            "started_ms": int(time.time() * 1000) - 60_000})
        killed = []
        monkeypatch.setattr(b, "_kill_running_tool_subtree",
                            lambda proc, cmd: killed.append(cmd) or True)
        sse = self._sse()
        assert b._pretrip_tool_evidence("PROC", sse, "s1", "ag", "",
                                        time.time()) == "killed"
        assert killed == ["x"]
        assert sse.state["turn_ts"] > time.time() - 5  # baselines re-armed

    def test_over_grace_no_match_returns_trip(self, monkeypatch):
        """serve 楔死形态（子进程死透、part 卡 running）→ 匹配失败 → trip
        （kill-serve 是该形态的唯一检出通路——决策表闭合性）。"""
        b = self._backend(grace=10.0)
        monkeypatch.setattr(b, "_probe_running_tool", lambda sid: {
            "status": "running", "command": "x", "output_tail": "",
            "started_ms": int(time.time() * 1000) - 60_000})
        monkeypatch.setattr(b, "_kill_running_tool_subtree",
                            lambda proc, cmd: False)
        assert b._pretrip_tool_evidence(
            "PROC", self._sse(), "s1", "ag", "", time.time()) == "trip"

    def test_no_evidence_returns_trip(self, monkeypatch):
        b = self._backend()
        monkeypatch.setattr(b, "_probe_running_tool", lambda sid: None)
        assert b._pretrip_tool_evidence(
            None, self._sse(), "s1", "ag", "", time.time()) == "trip"

    def test_grace_zero_disables_kill_only(self, monkeypatch):
        """tool_grace_s=0 = 禁用杀工具：running 永远判 alive（只复位）。"""
        b = self._backend(grace=0.0)
        monkeypatch.setattr(b, "_probe_running_tool", lambda sid: {
            "status": "running", "command": "x", "output_tail": "",
            "started_ms": int(time.time() * 1000) - 999_999})
        killed = []
        monkeypatch.setattr(b, "_kill_running_tool_subtree",
                            lambda proc, cmd: killed.append(cmd) or True)
        assert b._pretrip_tool_evidence(
            None, self._sse(), "s1", "ag", "", time.time()) == "alive"
        assert killed == []


# ———————————————————————— 看门狗集成 ————————————————————————

def _watched(b, sse, proc="PROC"):
    hang = threading.Event()

    def _hang(*a, **k):
        hang.wait(30.0) or {}
        return {}
    b._http_json = _hang
    b._stop_serve = lambda p: None
    try:
        b._post_message_watched("http://x", "s1", {}, sse, proc, "ag", "")
        return None
    except _KeepaliveAbort as e:
        return str(e)
    finally:
        hang.set()


def test_turn_stall_alive_tool_not_killed(monkeypatch):
    """kill-3 形态回归门：静默超界但 db 证据=running → 存活复位，不误杀；
    worker（模拟工具结束后返回）正常带回消息。"""
    b = OpenCodeBackend(keepalive_idle_s=100.0, keepalive_poll_s=0.02,
                        message_timeout=30.0, turn_stall_s=0.2,
                        tool_grace_s=1800.0)
    out = {"parts": [{"type": "text", "text": "done"}]}
    release = threading.Event()

    def delayed(*a, **k):
        release.wait(10.0)
        return out
    b._http_json = delayed
    b._stop_serve = lambda p: None
    monkeypatch.setattr(b, "_probe_running_tool", lambda sid: {
        "status": "running", "command": "python3 repro.py",
        "output_tail": "case 3 invoking", "started_ms": int(time.time() * 1000)})
    sse = types.SimpleNamespace(state=b._new_sse_log_state())
    sse.state["turn"] = 195
    sse.state["block_types"] = {"text", "thinking", "tool:bash"}
    sse.state["chars"] = 62000
    sse.state["turn_ts"] = time.time() - 100     # way past turn_stall_s
    t = threading.Thread(target=lambda: (time.sleep(0.6), release.set()))
    t.start()
    msg = b._post_message_watched("http://x", "s1", {}, sse, "PROC", "ag", "")
    t.join()
    assert msg == out   # survived: probe said the tool is alive


def test_turn_still_trips_with_no_evidence(monkeypatch):
    """kill-1/2 人群（真静默，无 running 证据）→ 判死保持。"""
    b = OpenCodeBackend(keepalive_idle_s=100.0, keepalive_poll_s=0.05,
                        message_timeout=30.0, turn_stall_s=0.2)
    monkeypatch.setattr(b, "_probe_running_tool", lambda sid: None)
    sse = types.SimpleNamespace(state=b._new_sse_log_state())
    sse.state["turn"] = 12
    sse.state["block_types"] = {"thinking"}
    sse.state["turn_ts"] = time.time() - 100
    msg = _watched(b, sse)
    assert msg is not None and "no new turn" in msg


def test_hard_cap_not_gated_by_probe(monkeypatch):
    """hard cap（workflow 墙）不受取证门控——probe 判 alive 也照样到期必杀。"""
    b = OpenCodeBackend(keepalive_idle_s=0.2, keepalive_poll_s=0.02,
                        message_timeout=0.4, turn_stall_s=100.0,
                        tool_grace_s=1800.0)
    monkeypatch.setattr(b, "_probe_running_tool", lambda sid: {
        "status": "running", "command": "x", "output_tail": "",
        "started_ms": int(time.time() * 1000)})
    sse = types.SimpleNamespace(state=b._new_sse_log_state())
    hang = threading.Event()
    b._http_json = lambda *a, **k: hang.wait(30.0) or {}
    b._stop_serve = lambda p: None
    try:
        with pytest.raises(_KeepaliveAbort) as ei:
            b._post_message_watched("http://x", "s1", {}, sse, "PROC", "ag", "")
        assert "hard cap" in str(ei.value)
    finally:
        hang.set()


def test_over_grace_kills_tool_not_serve_then_survives(monkeypatch):
    """running 超界 + 匹配成功 → 杀工具、复位、serve 不死；agent（worker）
    随后带工具错误返回 → 会话/工作树全保住。"""
    b = OpenCodeBackend(keepalive_idle_s=100.0, keepalive_poll_s=0.02,
                        message_timeout=30.0, turn_stall_s=0.2,
                        tool_grace_s=0.3)
    out = {"parts": [{"type": "text", "text": "tool killed, adapting"}]}
    release = threading.Event()

    def delayed(*a, **k):
        release.wait(10.0)
        return out
    b._http_json = delayed
    stopped = []
    b._stop_serve = lambda p: stopped.append(p)
    monkeypatch.setattr(b, "_probe_running_tool", lambda sid: {
        "status": "running", "command": "python3 repro.py",
        "output_tail": "", "started_ms": int(time.time() * 1000) - 60_000})
    monkeypatch.setattr(b, "_kill_running_tool_subtree",
                        lambda proc, cmd: True)
    sse = types.SimpleNamespace(state=b._new_sse_log_state())
    sse.state["turn"] = 195
    sse.state["block_types"] = {"tool:bash"}
    sse.state["chars"] = 1000
    sse.state["turn_ts"] = time.time() - 100
    t = threading.Thread(target=lambda: (time.sleep(0.6), release.set()))
    t.start()
    msg = b._post_message_watched("http://x", "s1", {}, sse, "PROC", "ag", "")
    t.join()
    assert msg == out
    assert stopped == []          # serve NOT killed


def test_keepalive_blindness_gated_by_probe(monkeypatch):
    """keepalive 门（无任何 SSE 帧）在工具执行期同样失明——取证 alive 复位。"""
    b = OpenCodeBackend(keepalive_idle_s=0.3, keepalive_poll_s=0.02,
                        message_timeout=30.0, turn_stall_s=0.3,
                        tool_grace_s=1800.0)
    out = {"parts": [{"type": "text", "text": "done"}]}
    release = threading.Event()

    def delayed(*a, **k):
        release.wait(10.0)
        return out
    b._http_json = delayed
    b._stop_serve = lambda p: None
    monkeypatch.setattr(b, "_probe_running_tool", lambda sid: {
        "status": "running", "command": "x", "output_tail": "",
        "started_ms": int(time.time() * 1000)})
    sse = types.SimpleNamespace(state=b._new_sse_log_state())
    sse.state["turn_ts"] = time.time() - 100      # turn gate will consult probe
    sse.state["last_event_ts"] = time.time() - 100  # keepalive would trip too
    sse.state["chars"] = 10
    t = threading.Thread(target=lambda: (time.sleep(0.6), release.set()))
    t.start()
    msg = b._post_message_watched("http://x", "s1", {}, sse, "PROC", "ag", "")
    t.join()
    assert msg == out


# ———————————————————————— 杀工具进程树（真实 syscall） ————————————————————————

def test_kill_running_tool_subtree_kills_descendant_match():
    """真实进程验证：serve 后裔中 cmdline 命中命令 token 的子树被 SIGKILL，
    范围限定后裔（根=serve 本身永不匹配——杀 serve 恰是本机制要避免的）。"""
    b = OpenCodeBackend.__new__(OpenCodeBackend)
    marker = "step97_distinctive_marker"
    # 父 bash（模拟 serve）后台一个 exec -a 改名 argv 的子进程（模拟工具命令）
    parent = subprocess.Popen(
        ["bash", "-c", f"exec -a {marker} sleep 3000 & wait"])
    try:
        assert parent.poll() is None
        # bash fork+exec -a 改名需要时间：等改名后的子进程真正出现在父的直系
        # 后裔里再杀。此前零等待，负载高时 /proc 扫描跑在 fork 之前 → 假失败
        # （fixture 竞态，非被测逻辑缺陷——生产调用点在工具已运行 grace 秒后
        # 才扫描，不存在此竞态）。有界等待吸收 fork 抖动。
        deadline = time.monotonic() + 10.0
        found = False
        while time.monotonic() < deadline:
            for entry in os.listdir("/proc"):
                if not entry.isdigit():
                    continue
                try:
                    with open(f"/proc/{entry}/stat", "rb") as f:
                        stat = f.read().decode("utf-8", "replace")
                    ppid = int(stat[stat.rindex(")") + 2:].split()[1])
                    with open(f"/proc/{entry}/cmdline", "rb") as f:
                        cmd = f.read()
                except (OSError, ValueError, IndexError):
                    continue
                if ppid == parent.pid and marker.encode() in cmd:
                    found = True
                    break
            if found:
                break
            time.sleep(0.05)
        assert found, (
            "fixture: 改名子进程 10s 内未出现在父后裔 — fork/exec 环境异常")
        killed = b._kill_running_tool_subtree(
            parent, f"python3 {marker} --case 3")
        assert killed is True
        # 子进程被杀后 bash 的 wait 返回、父进程自行退出
        parent.wait(timeout=10)
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait()


def test_kill_running_tool_subtree_dead_parent_no_match():
    """父进程已死（无后裔）→ False（退化 kill-serve 的闭合分支）。"""
    b = OpenCodeBackend.__new__(OpenCodeBackend)
    dead = subprocess.Popen(["true"])
    dead.wait()
    assert b._kill_running_tool_subtree(dead, "python3 some_long_command") is False


def test_kill_running_tool_subtree_no_distinctive_token():
    """命令无可辨识 token（无路径、无长词）→ 不猜，返回 False。"""
    b = OpenCodeBackend.__new__(OpenCodeBackend)
    assert b._kill_running_tool_subtree(None, "ls -la") is False


# ———————————————————————— 配置面 ————————————————————————

class TestToolGraceConfig:
    def test_default_1800(self, tmp_path):
        import ascendc_devkit.orchestration.runtime_config as rc
        orig = rc._RAW
        rc._RAW = {}
        try:
            assert rc.opencode_timeouts()["tool_grace_s"] == 1800.0
        finally:
            rc._RAW = orig

    def test_raw_override_and_zero(self, tmp_path):
        import ascendc_devkit.orchestration.runtime_config as rc
        orig = rc._RAW
        rc._RAW = {"timeouts": {"opencode_tool_grace_s": 300.0}}
        try:
            assert rc.opencode_timeouts()["tool_grace_s"] == 300.0
        finally:
            rc._RAW = orig
        rc._RAW = {"timeouts": {"opencode_tool_grace_s": 0}}
        try:
            assert rc.opencode_timeouts()["tool_grace_s"] == 0.0
        finally:
            rc._RAW = orig

    def test_negative_rejected(self):
        import ascendc_devkit.orchestration.runtime_config as rc
        from ascendc_devkit.domain.exceptions import ConfigError
        orig = rc._RAW
        rc._RAW = {"timeouts": {"opencode_tool_grace_s": -1}}
        try:
            with pytest.raises(ConfigError) as ei:
                rc.opencode_timeouts()
            assert "opencode_tool_grace_s" in str(ei.value)
        finally:
            rc._RAW = orig
