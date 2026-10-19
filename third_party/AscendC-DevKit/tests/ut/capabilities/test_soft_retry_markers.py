"""P131b (trial-20260730): in-session 软重试集扩到 503/ServiceUnavailable/APITimeout。

根因：trial storm 里网关同时以 429 与 503/ServiceUnavailable/APITimeout 拒绝；
后三种不含 "(429)" 子串，漏过 429 软重试门，被当「逻辑失败」——in-session 退避
从不触发。修复：新增 _SOFT_RETRY_MARKERS + _is_soft_retry_error，与 429 并入
后端 in-session 退避门（共享机制、各留诚实措辞）。永久 infra(401/config) 与
真 429 均不受影响。
"""
from __future__ import annotations

from ascendc_devkit.capabilities.agent._shared import (
    _is_soft_retry_error, _is_rate_limit_error, _classify_error_type,
    should_server_backoff, server_backoff_strategy, advance_backoff,
)


def test_503_is_soft_retry():
    assert _is_soft_retry_error("litellm.ServiceUnavailableError: ... 503")
    assert _is_soft_retry_error("API Error: 503 upstream")
    assert _is_soft_retry_error("Service Unavailable")


def test_apitimeout_is_soft_retry():
    assert _is_soft_retry_error("litellm.APITimeout: request timed out")
    assert _is_soft_retry_error("APIConnectionError: connection reset")


def test_soft_retry_disjoint_from_infra_and_429():
    # 503/APITimeout 不应被误判为永久 infra（那会立即 halt 而非退避）。
    assert _classify_error_type("API Error: 503 upstream") is None
    assert _classify_error_type("ServiceUnavailable") is None
    # 也不是 429（各留各的诊断措辞）。
    assert not _is_rate_limit_error("API Error: 503 upstream")


def test_non_soft_errors_ignored():
    assert not _is_soft_retry_error("API Error: 401 auth")
    assert not _is_soft_retry_error("schema mismatch: field foo")
    assert not _is_soft_retry_error(None)
    assert not _is_soft_retry_error("")


def test_should_server_backoff_blacklist_exclusion():
    """黑名单排除语义（A+，§2.5 单一来源）：非 infra 服务端错误一律应 in-session
    backoff resume（含 429/503/APIError/type validation/未知兜底）。"""
    # 已识别的服务端错误 → True
    assert should_server_backoff("Request rejected (429)")
    assert should_server_backoff("API Error: 503 upstream")
    assert should_server_backoff("APITimeout")
    # 本批实证的确定性协议错误 → True
    assert should_server_backoff(
        "The `content[].thinking` in the thinking mode must be passed back to the API")
    assert should_server_backoff(
        "Type validation failed: Value: {\"type\":\"message_delta\",...}")
    # 未知服务端错误 → True（兜底：不在不可重试清单即 resume）
    assert should_server_backoff("model overloaded")
    assert should_server_backoff("upstream gateway hiccup 500")
    # infra（不可重试 auth/quota/config）→ False
    assert not should_server_backoff("API Error: 401 Unauthorized")
    assert not should_server_backoff("No available channel")
    assert not should_server_backoff("Usage limit reached")
    assert not should_server_backoff("price not configured")
    # 成功 / 空 → False
    assert not should_server_backoff(None)
    assert not should_server_backoff("")


def test_server_backoff_strategy():
    """策略分离（20260812）：429/503 → backoff(sleep 等窗口)；其他非 infra 服务端
    错误（APIError/type validation/未知）→ resume（立即续跑不 sleep，避免误判空等）；
    infra/空 → None（调用方处理）。"""
    # 429/503 → backoff（需要 sleep 等窗口）
    assert server_backoff_strategy("Request rejected (429)") == "backoff"
    assert server_backoff_strategy("API Error: 503 upstream") == "backoff"
    assert server_backoff_strategy("APITimeout") == "backoff"
    # 其他非 infra 服务端错误 → resume（立即，不 sleep）
    assert server_backoff_strategy(
        "The `content[].thinking` in the thinking mode must be passed back to the API") == "resume"
    assert server_backoff_strategy(
        "Type validation failed: Value: {\"type\":\"message_delta\",...}") == "resume"
    assert server_backoff_strategy("model overloaded") == "resume"
    # infra（不可重试）→ None（调用方 halt）
    assert server_backoff_strategy("API Error: 401 Unauthorized") is None
    assert server_backoff_strategy("No available channel") is None
    # 成功/空 → None
    assert server_backoff_strategy(None) is None
    assert server_backoff_strategy("") is None


def test_advance_backoff_budget():
    """预算推进（A+）：累计 sleep 达 max_total 或 attempt 达 max_retries → 耗尽
    （sleep_s=None），否则指数退避 + 推进。"""
    kw = dict(base_s=1.0, factor=2.0, max_total_s=1000.0, max_retries=3)
    s0, a1, e1 = advance_backoff(0, 0.0, **kw)
    assert (s0, a1, e1) == (1.0, 1, 1.0)
    s1, a2, e2 = advance_backoff(a1, e1, **kw)
    assert (s1, a2, e2) == (2.0, 2, 3.0)
    s2, a3, e3 = advance_backoff(a2, e2, **kw)
    assert (s2, a3, e3) == (4.0, 3, 7.0)
    # attempt 达 max_retries → 耗尽，attempt/elapsed 不推进
    s3, a4, e4 = advance_backoff(a3, e3, **kw)
    assert s3 is None and (a4, e4) == (a3, e3)
    # 累计 elapsed 达 max_total 封顶 → 耗尽（elapsed >= max_total）
    s_cap, a_cap, e_cap = advance_backoff(0, 1000.0, **kw)
    assert s_cap is None and (a_cap, e_cap) == (0, 1000.0)
    # elapsed 逼近 cap 时仍有一次退避，但推进后达 cap
    s_near, a_near, e_near = advance_backoff(0, 999.0, **kw)
    assert (s_near, a_near, e_near) == (1.0, 1, 1000.0)
