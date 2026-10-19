"""P131c (trial-20260730): infra_backoff() 跨-run 退避重跑预算，缺省可用、可配。

opencode turn_stall / message_timeout 默认值已收敛到 test_runtime_config.py
TestOpencodeTimeouts（code==config 一致性，不重复断言字面量）。
"""
from __future__ import annotations

import pytest

from ascendc_devkit.orchestration import runtime_config as rc


def test_infra_backoff_defaults():
    b = rc.infra_backoff()
    assert b["max_retries"] == 4
    assert b["backoff_base_s"] == 20.0
    assert b["backoff_factor"] == 2.0
    assert b["backoff_max_total_s"] == 600.0
    # resume 连续失败后退化 spawn 的阈值，默认 3（< max_retries=4 → 预算内 resume 3 次 + 1 发 fresh）。
    assert b["resume_attempts"] == 3


def test_infra_backoff_resume_attempts_lt_max_retries_required(monkeypatch):
    """加载期交叉校验（§1.3）: resume_attempts >= infra_retry_max_retries →
    ConfigError——预算内必须留一发 fresh 退化，否则退化永远轮不到。"""
    orig = rc._RAW
    try:
        rc._RAW = {"agent": {"resume_attempts": 3,
                             "infra_retry_max_retries": 3}}
        with pytest.raises(rc.ConfigError):
            rc.infra_backoff()
    finally:
        rc._RAW = orig


def test_infra_backoff_resume_attempts_negative_rejected(monkeypatch):
    """resume_attempts 非正 → ConfigError（沿用 _positive_int 严格校验）。"""
    orig = rc._RAW
    try:
        rc._RAW = {"agent": {"resume_attempts": 0}}
        with pytest.raises(rc.ConfigError):
            rc.infra_backoff()
    finally:
        rc._RAW = orig


def test_infra_backoff_resume_attempts_custom_accepted(monkeypatch):
    """resume_attempts 合法自定义值（< max_retries）→ 正常接受并返回。"""
    orig = rc._RAW
    try:
        rc._RAW = {"agent": {"resume_attempts": 2, "infra_retry_max_retries": 4}}
        assert rc.infra_backoff()["resume_attempts"] == 2
    finally:
        rc._RAW = orig
