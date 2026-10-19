"""UT: claude SDK 后端 turn-stall 看门狗（_stream_with_turn_stall）。

wall-clock 网关静默看门狗：SDK query 流长时间无任何事件（网关不回包）→ 抛
_SdkTurnStallAbort；有事件则刷新 deadline 永不 abort；turn_stall_s=0 关闭透传。
对齐 opencode 的 turn_stall_s 看门狗（P117），这是 claude SDK 的对称实现——补上
「慢网关 → 空等」的止损缺口（opencode 有 120s turn-stall，claude SDK 此前没有）。
"""

from __future__ import annotations

import anyio
import pytest

from ascendc_devkit.capabilities.agent.sdk_backend import (
    SDKBackend, _SdkTurnStallAbort,
)


def _silent_query(prompt, options):
    """模拟网关静默：不 yield 任何事件，阻塞到被看门狗取消（比 turn_stall_s 长得多）。"""
    async def _gen():
        await anyio.sleep(10)
        yield "never-reached"
    return _gen()


def _streaming_query(prompt, options, n=10, gap=0.05):
    """模拟慢但活着的网关：每 gap 秒 yield 一个事件 → 刷新 deadline，永不 abort。"""
    async def _gen():
        for _ in range(n):
            await anyio.sleep(gap)
            yield "event"
    return _gen()


def test_silent_gateway_raises_turn_stall():
    """网关静默（无事件）超过 turn_stall_s → _SdkTurnStallAbort（不是卡死空等）。"""
    backend = SDKBackend(interactive=False, turn_stall_s=0.3)

    async def _run():
        async for _ in backend._stream_with_turn_stall(_silent_query, "p", {}):
            pytest.fail("silent gateway must not yield any event")

    with pytest.raises(_SdkTurnStallAbort):
        anyio.run(_run)


def test_streaming_events_reset_deadline_no_abort():
    """每有事件就刷新 deadline → 慢但活着的流不误判为 stall，全部事件透传。"""
    backend = SDKBackend(interactive=False, turn_stall_s=0.3)

    async def _run():
        n = 0
        async for _ in backend._stream_with_turn_stall(_streaming_query, "p", {}):
            n += 1
        return n

    assert anyio.run(_run) == 10


def test_turn_stall_zero_disables_watchdog():
    """turn_stall_s=0 → 关闭看门狗，原流透传（含静默流——交给别的止损机制）。"""
    backend = SDKBackend(interactive=False, turn_stall_s=0)

    async def _run():
        n = 0
        async for _ in backend._stream_with_turn_stall(_streaming_query, "p", {}):
            n += 1
        return n

    assert anyio.run(_run) == 10
