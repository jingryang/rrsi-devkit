# Copyright 2026 The rrsi Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""LLM 调用的重试窗口与 max_tokens 升级。

背景（20261027 13:42）：proposer 跑了 2 小时后死在
`generate failed after 6 tries: empty response`。原排程的总退避只有 61 秒
（1+2+4+8+16+30），网关持续几分钟的抽风足以让 6 次重试全部落空，而这一轮
已经做过的工作（含一次真实编辑）随进程退出全部丢失。同时 max_tokens 的
自动升级只在响应里出现 thinking 块时触发，而 claude-opus 返回的空响应
thinking 长度是 0，永远走不到那个分支。

    python3 -m pytest -q tests/test_llm_retry.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import rrsi.llm as llm  # noqa: E402


class _Block:
    def __init__(self, kind: str, text: str = "", thinking: str = ""):
        self.type = kind
        self.text = text
        self.thinking = thinking


class _Resp:
    def __init__(self, blocks, stop_reason="end_turn"):
        self.content = blocks
        self.stop_reason = stop_reason


class _Client:
    """每次调用返回预置响应，并记录收到的 max_tokens。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.budgets: list[int] = []
        self.messages = self

    def create(self, **kwargs):
        self.budgets.append(kwargs["max_tokens"])
        return self.responses.pop(0) if self.responses else _Resp([])


def _run(monkeypatch, responses, max_retries, max_tokens=1_000):
    client = _Client(responses)
    sleeps: list[float] = []
    monkeypatch.setattr(llm, "_client_for", lambda idx: client)
    monkeypatch.setattr(llm.time, "sleep", lambda s: sleeps.append(s))
    try:
        llm.generate("p", max_retries=max_retries, max_tokens=max_tokens)
    except RuntimeError as e:
        err = str(e)
    else:
        err = None
    return client, sleeps, err


def test_backoff_outlasts_a_multi_minute_gateway_outage():
    """总窗口必须够长——61 秒撑不过一次真实的网关故障。"""
    total = sum(llm._retry_sleep(i) for i in range(llm.MAX_RETRIES - 1))
    assert total >= 300, total
    assert llm._retry_sleep(0) >= 5
    assert llm._retry_sleep(50) == llm.RETRY_BACKOFF_MAX


def test_empty_responses_are_retried_with_widening_backoff(monkeypatch):
    client, sleeps, err = _run(monkeypatch, [_Resp([])] * 4, max_retries=4)
    assert err is not None and "empty response" in err
    assert sleeps == [5.0, 10.0, 20.0], sleeps      # 递增，不是恒定
    assert len(client.budgets) == 4


def test_blank_reply_without_thinking_still_escalates_the_cap(monkeypatch):
    """回归：claude 的空响应 thinking=0，旧逻辑永远不升级 max_tokens。"""
    client, _sleeps, err = _run(monkeypatch, [_Resp([]), _Resp([]), _Resp([])],
                                max_retries=3, max_tokens=1_000)
    assert client.budgets == [1_000, 1_000, 2_000], client.budgets
    assert err is not None


def test_thinking_only_reply_escalates_immediately(monkeypatch):
    """deepseek 那种只吐 thinking 的响应：第一次就该涨预算。"""
    client, _sleeps, _err = _run(
        monkeypatch,
        [_Resp([_Block("thinking", thinking="x" * 500)]), _Resp([])],
        max_retries=2, max_tokens=1_000)
    assert client.budgets == [1_000, 2_000], client.budgets


def test_cap_growth_is_bounded(monkeypatch):
    responses = [_Resp([]) for _ in range(llm.MAX_RETRIES)]
    client, _sleeps, _err = _run(monkeypatch, responses, max_retries=8,
                                 max_tokens=1_000)
    assert max(client.budgets) <= llm.MAX_TOKENS_CAP


def test_successful_reply_returns_without_retrying(monkeypatch):
    client, sleeps, err = _run(
        monkeypatch, [_Resp([_Block("text", text='{"action": "done"}')])],
        max_retries=4)
    assert err is None and sleeps == []
    assert len(client.budgets) == 1
