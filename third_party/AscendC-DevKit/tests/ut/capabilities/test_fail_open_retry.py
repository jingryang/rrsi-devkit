"""fail-open（infra-fail-open-retry）：连接重置/未知 crash 归类为瞬时 infra，值得有界重试。

根因（batch 20260813-164600-f65f5b grid_sampler_3d）：spawn 期连接重置
`Remote end closed connection without response` 既没被 `_is_hard_timeout_exc` 判为 aborted，
也没被 `_INFRA_ERROR_MARKERS` 文案匹配判为 infra，掉进「中性失败」夹缝 → fail_strategy=halt
无重试。修复：`classify_spawn_exception` 按异常**类型**判连接故障为 `infra_transient`；
`_build_result` 对未知 crash 兜底 `infra_transient`；`is_infra_failure` 以
error_type/aborted 为权威「没干成活」信号（默认 fail-open）。
"""
from __future__ import annotations

from http.client import RemoteDisconnected

from ascendc_devkit.capabilities.agent._shared import (
    classify_spawn_exception,
    is_infra_error_type,
    is_infra_failure,
)
from ascendc_devkit.capabilities.agent.backend import AgentResult


def _ar(**kw) -> AgentResult:
    d = dict(agent_name="x", status="fatal")
    d.update(kw)
    return AgentResult(**d)


# —— classify_spawn_exception：异常类型 → error_type ——

def test_connection_error_classified_transient():
    assert classify_spawn_exception(ConnectionError("x"), "boom") == "infra_transient"


def test_remote_disconnected_classified_transient():
    # http.client.RemoteDisconnected 是 ConnectionResetError→ConnectionError 子类；
    # str() 正是 batch 日志里的 "Remote end closed connection without response"。
    exc = RemoteDisconnected("Remote end closed connection without response")
    assert classify_spawn_exception(exc, str(exc)) == "infra_transient"


def test_permanent_marker_still_infra():
    assert classify_spawn_exception(None, "API Error: 401 Unauthorized") == "infra"
    assert classify_spawn_exception(None, "No available channel") == "infra"


def test_unknown_text_none():
    assert classify_spawn_exception(None, "schema mismatch: field foo") is None
    assert classify_spawn_exception(None, None) is None


# —— is_infra_error_type：error_type 值是否属 infra 类 ——

def test_is_infra_error_type():
    assert is_infra_error_type("infra")
    assert is_infra_error_type("infra_transient")
    assert not is_infra_error_type(None)
    assert not is_infra_error_type("fatal")
    assert not is_infra_error_type("schema_violation")


# —— is_infra_failure：权威「没干成活」信号（error_type / aborted，不看 status）——

def test_is_infra_failure_by_error_type():
    assert is_infra_failure(_ar(error_type="infra"))
    assert is_infra_failure(_ar(error_type="infra_transient"))


def test_is_infra_failure_by_aborted():
    assert is_infra_failure(_ar(aborted="hard_timeout"))


def test_is_infra_failure_false_for_logic():
    # status="fatal" 但 error_type/aborted 均空 → 逻辑失败（不进 infra 重试）。
    assert not is_infra_failure(_ar(status="fatal", error_type=None, aborted=None))


def test_is_infra_failure_false_for_cut_only():
    assert not is_infra_failure(_ar(status="ok", cut=True))


def test_is_infra_failure_false_for_clean():
    assert not is_infra_failure(_ar(status="ok"))
