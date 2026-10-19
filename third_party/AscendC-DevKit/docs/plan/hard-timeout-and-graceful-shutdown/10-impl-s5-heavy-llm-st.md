# S5 实施方案 — heavy_llm ST（hard-timeout 真机验证）+ §3.11 默认排除修复

> 层级：**L4 / 实施方案**。S1-S4 + D8 + precision-debug teardown 代码完成；本切片落 **heavy_llm ST**（真机 dual-backend 验硬超时秒级 kill + resume handle）+ 修 **§3.11 默认排除**合规缺口。

## 范围

- **heavy_llm ST**（`tests/st/test_hard_timeout_e2e.py`，3 用例）：真 SDK transport 验硬墙到点秒级 kill + `aborted='hard_timeout'` + claude session sidecar 保留（resume handle）。
- **§3.11 默认排除修复**（`tests/conftest.py`）：默认 `pytest` 排除 heavy_llm（之前默认「no filter」跑所有含 heavy_llm，违反 §3.11「heavy_llm 不默认自动跑」）。

## heavy_llm 用例（§3.11 执行需用户确认）

`tests/st/test_hard_timeout_e2e.py`，dual-marked `@pytest.mark.llm` + `@pytest.mark.heavy_llm`：

| 用例 | 验证 | 依赖 | 预估 |
|---|---|---|---|
| `test_hard_wall_kills_real_spawn[claude]` | 真 claude SDK：紧 deadline（4s）杀在途 spawn → `aborted='hard_timeout'` + elapsed<30s（S1b anyio 墙 + SDK close escalation） | ANTHROPIC creds | ~30s + ~2k token |
| `test_hard_wall_kills_real_spawn[opencode]` | 真 opencode serve：紧 deadline 收紧 message_timeout → keepalive abort → killpg 杀整组 → `aborted`（S1a/S4） | ANTHROPIC creds + 真 `rg` on PATH | ~serve 启动 + ~30s + ~2k token |
| `test_claude_hard_timeout_keeps_session_sidecar` | 真 claude 硬杀后 session sidecar 留盘（resume handle，S1b 构造性保证） | ANTHROPIC creds | ~30s + ~2k token |

**跑法**：`pytest tests/st/test_hard_timeout_e2e.py -m heavy_llm`（默认 `pytest` 已排除，§3.11）。无 ANTHROPIC creds → `pytest.skip`（§3.7 诚实跳过）。

## §3.11 默认排除修复

`tests/conftest.py::pytest_collection_modifyitems` 默认分支（原「no marker filtering」）→ `config.option.markexpr = "not heavy_llm"`。理由：§3.11「pytest 默认 = UT 全量 + 非 heavy_llm 的 ST」是 OVERRIDE 策略，原 conftest 未落实 = 所有 heavy_llm（含既有 test_session_resume_e2e / test_subagent_dispatch_dual_backend 等）默认自动跑，烧分钟级耗时 + token。改后默认排除；显式 `-m heavy_llm` opt-in（或任意显式 `-m` 短路上述叠加）。

## TDD / 验证

- collect：默认 `pytest ... --co` → heavy_llm 全 deselected；`-m heavy_llm` → 3 用例可选。
- 全量 UT 2919 passed（conftest 改动不影响 UT——UT 无 heavy_llm marker）。
- **真机跑**：用户确认后 `pytest -m heavy_llm tests/st/test_hard_timeout_e2e.py`。

## 不在 S5 范围
- cann-bench uninterruptible / SIGTERM / precision-debug teardown 的真机验证：需全 workflow + NPU + git repo，更重；UT 已覆盖逻辑，真机可后续补 workflow-level heavy_llm。
- A5 precision-debug teardown / codegen teardown 重载 → 待 ownership/语义确认（`09-impl-stage-teardown-overloads.md`）。

## 真机跑结果 + 发现的 opencode 硬墙缺陷（用户确认后跑，§3.11）

3 用例全绿（claude 硬墙 ✓ / opencode 硬墙 ✓ / claude sidecar ✓，~37s）。**heavy_llm 真机暴露了 opencode 硬墙一个 UT 漏检的真缺陷**（§3.9 real-link guard 的价值）：

**缺陷**：`_post_message_watched` 把收紧的 deadline `mt` 同时用作 (a) watchdog hard-cap **和** (b) POST urllib socket timeout。opencode POST 全程 byte-idle（完成时才一个 JSON blob），故 `mt` 的 socket 超时在 keepalive watchdog **之前**触发 → 抛 `URLError`（非 `_KeepaliveAbort`）→ spawn except `isinstance(_KeepaliveAbort)` False → `aborted=None`（硬墙失效）。UT 漏检因 UT mock 了 `_http_json`（无真 socket）。

**修复**（opencode_backend.py）：
- **#1 解耦**：POST socket timeout 改用实例 `self._message_timeout`（大 backstop，≥ mt），让 watchdog hard-cap(mt) 先触发 `_KeepaliveAbort`。socket 仅作 dumb backstop。
- **#2 belt-and-suspenders**：新增 `_is_hard_timeout_exc(e)` —— 识别 `_KeepaliveAbort` **或** urllib socket timeout（`URLError.reason = socket.timeout = TimeoutError`）→ `aborted='hard_timeout'`。spawn except 用它替代 `isinstance(_KeepaliveAbort)`。处理 mt≈message_timeout 等价竞态 + 任何 socket-timeout 路径。
- **UT 守护**：`test_is_hard_timeout_exc_classifies_timeouts`（快速 UT，防回归不必跑 heavy_llm）。

修后：全量 UT 2920 passed；3 个 heavy_llm 真机全绿。
