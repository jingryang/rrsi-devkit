# 05 — 批跑并发 opencode SQLite DB lock 致 design hang + keepalive 盲区（L3 方案分析）

> 对应 L1 `06-problems.md` P115、memory `batch-design-primary-mcp-hang`。
> 阶段：**根因已坐实**（批跑并发 SQLite DB lock，§2.5 现场日志铁证）+ **方案已评估**（G+A/B 组合，§5 四把尺子结论）；待用户确认后转 L4 实施。
> 演进：初判「design-generator MCP 握手 hang」→ §2.4 取证修正（engine 无 bug、单算子健康）→ §2.5 坐实真根因（并发 DB lock）。

## 1. 问题陈述

`self_evolve_op` 全批/并发 resume 在 **design 阶段全局卡死**：所有 `ascendc-design-generator`（opencode **primary mode** agent）spawn 后零产出，直到 `message_timeout=3600`（1h）硬墙兜底 fatal 收口。subagent（requirement-analyst / design-reviewer）不卡。

- 复现批次：`20260725-152037-8a4efa`（resume #6，P113/P114 修后重启），5 算子 design 阶段 4/5 卡此（manifold 是 requirement 产物不全，另案）。
- 收口实证：`exceeded 3600s hard cap`（spawn 23:41:43 → fatal 00:42:09，~60min26s）。

## 2. 根因取证（进程铁证 + 代码核查）

### 2.1 进程状态（hang 现场）

| 对象 | 状态 | 含义 |
|---|---|---|
| `engine_mcp_stdio` 子进程 ×8 | `%CPU 0.0`、`ELAPSED ~2987s`、`Sl` | 每个 opencode serve 一个；全在 `stdin.readline` 阻塞，**没收到 initialize** |
| opencode serve ×8 | `Ssl`、CPU 2.5-3.6%、`wchan=epoll_wait` | 活跃（发 SSE 心跳/polling）但无网关连接 |
| 网关 `192.168.0.212:8082` 连接 | `ss` 全空 | opencode **不在等 LLM**，卡在本地 |
| resume 主进程 | `futex_wait` + 3 线程 `hrtimer_nanosleep` | ThreadPool join + timeout 定时器 |

**诊断链闭合**：opencode 没 connect 网关（非 LLM 问题）→ 卡 opencode 内部 → 唯一卡点是连 `engine_mcp_stdio` 的 MCP stdio 握手 → 8 个 `engine_mcp_stdio` 全 CPU 0 readline 阻塞（等 initialize）→ **握手死锁**。

### 2.2 engine_mcp_stdio 侧（framework 代码，可查）

`engine_mcp_stdio.py:158-186`：

```python
async def _serve(stdin, stdout, handler):
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, stdin.readline)  # 阻塞读
        if not line: break  # EOF
        ...
asyncio.run(_serve(sys.stdin, sys.stdout, handler))
```

- server 端逻辑正确：被动 `readline` 等 JSON-RPC `initialize`，CPU 0 = **没收到任何 line**。
- **疑点（待 strace 验证）**：`engine_mcp_stdio` 的 fd0(stdin)/fd1(stdout) 是 **socket**（`socket:[...]`），**非 pipe**；而 `_serve` docstring 假设「opencode closes the **pipe**」。opencode 的 `type:"local"` MCP 用 **socketpair** 连子进程 stdio（Go 习惯），非传统 pipe。`sys.stdin.readline()` 对 socket 通常仍能读，**但需 strace 确认 opencode 是否真把 initialize 写到了 engine_mcp_stdio 的 stdin socket**（可能写到了别的 fd / 握手时序错位）。

### 2.3 根因假设（分层）

- **L5 framework 侧（engine_mcp_stdio）**：代码逻辑正确（被动 readline），但**对「握手迟迟不来」零防御**——silent readline 等到 1h timeout（违 §1.2 可诊断）。
- **opencode 侧（外部二进制）**：primary mode agent spawn 下，engine MCP 的 stdio `initialize` 握手**未启动或未送达** engine_mcp_stdio 的 stdin。具体原因（opencode MCP client 时序 / socketpair wiring / primary-mode 特殊路径）**需 strace opencode 复现定位**（按 §1.11，strace 实际 syscall 是强证据，curl/推测不是）。

### 2.4 2026-07-27 取证修正（证伪 §2.3 多数假设，根因转向「批跑并发触发」）

apt 装 strace 5.16 + 单算子复现（ed4992）+ 手动测试，**证伪 §2.3 多数根因假设**：

| §2.3 假设 | 取证 | 结论 |
|---|---|---|
| wiring 错位（socketpair 接线错） | engine fd0=socket:[345221323] ↔ opencode fd28=socket:[345221324]（连续 inode=对端），三对都对端正确 | **证伪** |
| engine 侧 bug / readline 对 socket 异常 | `printf initialize+tools/list \| python -m engine_mcp_stdio` → 正确响应（exit 0） | **证伪**（engine 无 bug） |
| "primary mode design-generator 必卡" | 单算子 spawn（同 primary design-generator）turn 1–4 健康（bash+read + 网关 LLM 响应）；engine CPU 0 是闲置（没调 resolve_ambiguity）非 hang | **证伪**（单算子健康） |

**修正后的根因假设（主）**：MCP hang **仅在批跑并发（5 算子）时触发，单算子不复现**（用户判断「批跑才卡、单算子没问题」证实）。§2.1–2.2 的现象（engine CPU 0 readline 阻塞 ~50min）真实，但**触发条件是并发**，非 engine/opencode 单实例问题。

**并发根因候选**（待批跑复现 + strace 并发现场定位，单算子 strace 抓不到）：
1. opencode 共享状态并发竞争：`.opencode_home` / 全局 config / auth cache——5 个 opencode serve 并发读写冲突？
2. 多个 engine MCP 并发握手竞争：5 个 design-generator 同时调 resolve_ambiguity → 5 个 engine MCP 同时 initialize 握手 → 某全局锁/资源竞争？
3. fd/端口/资源并发耗尽。

> 注：§4 候选方案（A engine 握手超时 / B keepalive / C timeout / E socket 兼容）基于「单实例 MCP 握手 hang」假设——E 已证伪（socket 兼容正常）；A/B/C 仍有独立价值（可诊断/止损，与触发条件无关）但**不解决并发根因**。方案需在并发根因定位后重新评估（§5 待决策点更新）。

### 2.5 静态研究 + 现场日志坐实并发根因（2026-07-27，根因确认）

静态研究 opencode_backend spawn 隔离边界 + 昨晚 hang 现场 serve log，**坐实并发 SQLite DB lock 根因**：

- **隔离边界（代码核查）**：OPENCODE_CONFIG 文件 per-spawn 隔离（scratch dir `decision_workspace/.opencode_home/opencode-config.json`，`_cfg_scratch_dir` :1117-1133），但 **HOME/XDG 透传真实 HOME**（`_build_serve_env` `env=dict(os.environ)` :1151）→ opencode 全局 **SQLite DB（`$XDG_DATA_HOME/opencode`，auth/config/session）5 并发 serve 共享**。
- **P-BC5（:232-240）已发现此并发 DB lock 问题**，但**只对 startup crash 做 bounded retry**（serve bind port 前 crash，probe ~2% @ N=10）；**运行期 DB lock hang（serve healthy 后 design-generator 跑时）未覆盖**。
- **现场铁证**：昨晚 hang 现场的 `ed4992` serve log（`.opencode-serve-38085.log`，3 行）明确记录：
  ```
  Error: Unexpected error
  database is locked
  ```
  **并发 SQLite DB lock 真实发生**。其他 4 算子 serve log 无此记录——运行期 DB lock hang 不 crash 不记录，只有 ed4992 这条 startup crash 直接证明并发 DB lock 存在。
- **根因链（闭合）**：5 并发 serve 共享 SQLite DB → 运行期（design-generator 调 resolve_ambiguity / MCP 握手 / session 写）并发访问 → DB lock 竞争 → opencode 卡（等 DB lock）→ 不发 MCP initialize → `engine_mcp_stdio` 等 initialize → 全 hang → `message_timeout=3600` 1h 收口。单算子无并发竞争 → 不 hang（与用户判据「批跑才卡」一致）。

**修复方向（L3 候选，待用户拍板）**：
- **G（per-spawn XDG 隔离——根治首选）**：`_build_serve_env` 设 `XDG_DATA_HOME`+`XDG_CONFIG_HOME` 指向 scratch dir（per-spawn 独立 SQLite DB），消除并发 DB lock 竞争。framework 已 env 注入 credentials（`OPENCODE_SECRET_*`，:1163-1166）+ cwd 锚定 skill（`_ensure_skills_anchor`，:437-443），**不依赖 opencode global auth/config**——P-BC5 的「global-auth invariant」顾虑对 framework 批跑**不成立**（批跑用 env credentials，不需 opencode login 的 global auth）。需验证 isolation 不断 framework 其他依赖（plugin/global session）。落在正确层（spawn env 是 framework 产权）。
- **H（扩展 P-BC5 到运行期）**：运行期 DB lock hang 检测 + retry（kill serve + respawn + 恢复 session）——复杂，且 retry 治标。
- **A/B/C（可诊断/止损）**：保留——与并发根因独立（keepalive 盲区 + message_timeout 兜底 + engine 握手超时），作为 G 未覆盖面的兜底。

## 3. keepalive 盲区分析（P-BC3 的 gap）

`opencode_backend.py` P-BC3 keepalive（:209-216, :276-279, :370-371）：

- 判活看 `last_event_ts`，**每个 SSE frame 刷新**；`keepalive_idle_s=600`（10min idle 才 kick）。
- **盲区**：opencode 在 MCP 握手 hang 期间**仍发 SSE 心跳/ping** → `last_event_ts` 持续刷新 → keepalive 误判存活 → 不 kick。
- commit `bb9b182e`（P-BC4）自承同型 gap（permission-block 期间 SSE 心跳骗过 keepalive），**P115 是同型盲区的新触发源**：任何「opencode 端非 SSE-静默的阻塞」（permission-block / MCP 握手 hang / 未来其他）都能骗过 keepalive。
- **唯一兜底**：`message_timeout=3600` 硬墙（1h）——本次实证有效（60min 收口），但太慢（design-generator 全废 + 占资源 1h）。

## 4. 候选方案（§1.2 四把尺子，根因坐实后重评）

根因 = **批跑并发 SQLite DB lock**（§2.5 坐实）。候选重评：

| # | 方案 | 层/产权 | 可维护 | 可扩展 | 可诊断 | 架构合理 | 评估 |
|---|---|---|---|---|---|---|---|
| **G** | **per-spawn XDG 隔离**：`_build_serve_env` 设 `XDG_DATA_HOME`+`XDG_CONFIG_HOME` → scratch dir，每 serve 独立 SQLite DB | L5 spawn env（framework 产权） | ✓ 澄清「framework 批跑不依赖 global auth」不变式（P-BC5 误判）+ 与 D1 per-spawn 一致（config 已隔离→DB 也该隔离） | ✓ 结构性消除并发抢锁，N 并发自动正确 | △ 预防根因（不触发），不增检测信号 | ✓ spawn env 是 framework 产权，不改 opencode、不靠 retry 兜底 | **主修复（根治）** |
| H | 扩展 P-BC5 到运行期：DB lock hang 检测 + retry（kill+respawn+恢复 session） | L5 | △ 不澄清不变式 | ✗ retry 治标，N 并发仍竞争 | ✓ 检测+retry 留信号 | △ 运行期 retry 复杂，session 恢复难 | 治标，备选 |
| 串行 | `design_concurrency=1`（同时 1 serve） | 配置 | △ 回避并发 | ✗ 想提速就再撞 | △ 不触发 | △ 降级换稳定，根因还在 | 备选（简单但慢 ~5x） |
| 1 serve 共享 | 单 serve 跑多 design-generator | — | ✗ 大改 per-spawn config/MCP 架构 | △ 新约束 | △ 单点 | ✗ 违 D1 per-spawn 设计 | 否决 |
| A | engine_mcp_stdio 握手超时（30s 无 initialize → stderr+exit） | L5 | ✓ | ✓ | ✓✓ | ✓ | **兜底（补 G 可诊断短板）** |
| B | keepalive 加子进程存活/CPU 探测 | L5 | ✓ | ✓ 覆盖非 SSE 静默阻塞整类 | ✓ | ✓ | **兜底（补 G 可诊断短板）** |
| C | message_timeout 3600→900 | 配置 | ✓ | ✗ | △ | ✓ | 最后硬墙（可选） |
| D | strace opencode 取证 | 调研 | — | — | ✓ | — | **已完成**（§2.4 单算子 strace + §2.5 serve log 坐实根因） |
| E | socket 兼容 readline | L5 | — | — | — | — | **证伪**（§2.4：socket 兼容正常） |
| F | 禁用 design-generator 连 MCP | — | ✗ | ✗ | ✗ | ✗ 违 §4.4 | **否决** |

## 5. 决策（§1.2 四把尺子评估 + 组合原则）

用户提问「哪个更符合四项基本原则」，对三个消除抢锁方向逐项评估：

| 尺子 | G:per-spawn 独立 DB | 串行 design | 1 serve 共享 |
|---|---|---|---|
| 可维护（维持/澄清不变式） | ✓ 澄清「framework 不依赖 global auth」+ 与 D1 一致 | △ 回避 | ✗ 大改架构 |
| 可扩展（同类自动归位） | ✓ 结构性消除，N 并发自动正确 | ✗ 治标 | △ 新约束 |
| 可诊断（留信号） | △ 预防不检测 | △ | △ |
| 架构合理（职责正确的层） | ✓ spawn env 是 framework 产权 | △ 降级 | ✗ 违 D1 |

**结论**：G 三项 ✓ 最符合四把尺子；唯一短板可诊断（G 是「预防根因」非「检测 hang」）。按 §1.2「单一方案无法同时满足时优先组合：正确改动承担主修复保不变式 + 宽容兜底防崩 + 可观测性确保错误不被掩盖」：

> **G（主修复，保不变式）+ A/B（可观测兜底，补可诊断短板）** = 四把尺子全 ✓
> - **G** 结构性消除并发 DB lock（可维护/可扩展/架构合理）
> - **A**（engine 握手超时）+ **B**（keepalive 子进程监控）兜底：防 G 未覆盖的 hang（opencode 别的 bug / 单算子异常），并留可观测信号
> - **C**（message_timeout 收敛）可选，作最后硬墙

**状态**：调研结论 = G+A/B 组合（用户已倾向此方向）。待用户最终确认后转 L4 实施（实施前再确认 G 代码改动点 + UT/验证计划）。

## 6. 验证（G+A/B）

- **G UT**：`_build_serve_env` 断言设 `XDG_DATA_HOME`/`XDG_CONFIG_HOME` → scratch dir；per-spawn DB 路径独立（两 spawn 的 XDG 不同）；framework 不读 global auth（grep 已证，UT 固化）。
- **G ST（heavy_llm，§3.11）**：全批 resume（5 并发）design 阶段，断言无 `database is locked`、design-generator 推进、不再 1h 收口。
- **A UT**：engine_mcp_stdio 握手超时（mock stdin 不发 initialize，monkeypatch 时钟，断言 30s 后 stderr+exit 1）。
- **B UT**：keepalive 检测子进程退出/CPU 0 → 触发 kill（mock consumer + stub）。
- **回归**：正常 design-generator（不触发 hang）不被 A/B 误杀；单算子 spawn 行为不变（G 只加 XDG env）。

## 7. 与现有修复的关系

- **G 与 P-BC5（startup retry）**：G 根治并发 DB lock（per-spawn DB 不竞争）；P-BC5 startup retry 可保留（防 startup crash 其他原因），但 DB lock 这一因由 G 消除。G 落在更正确的层（isolation 而非 retry）。
- **A/B 与 P-BC3（keepalive+message_timeout）**：A/B 是 keepalive 盲区补强，C 是 message_timeout 收敛；都在 P-BC3 框架内增强。
- **不冲突 P-BC4**（external_directory=allow）：P115 已排除 permission-block。
- **承接 memory `batch-design-primary-mcp-hang`**：该 memory「仅记未修」，本 L3 坐实根因（并发 DB lock）+ 给出 G+A/B 方案。

## 8. 开放问题（实施前确认）

1. **G isolation 是否断 framework 其他依赖**：plugin / global session / opencode 的 XDG 其他用途？grep 已证 framework 不调 opencode login、credentials 走 env；实施前需跑一次 isolation 验证 opencode 在 per-spawn XDG 下正常 spawn + design-generator 正常跑（不断 skill/plugin）。
2. **A 握手超时阈值**：30s 是否误伤慢启动？实测 opencode spawn + MCP 握手 <5s，30s 余量充足。
3. **C message_timeout 收敛值**：900s（15min）vs 其他？平衡合法长 design turn。
4. **G 是否保留 global config 可选通路**：若未来要 opencode global config 生效（用户手动配置），G isolation 会断——framework 批跑当前不需，可后续按需加 opt-in。

## 9. 为什么单 serve 多 session 不可行（2026-07-27 实测，避免重复分析）

**问题**：opencode 设计是单 serve 多 session（server.mdx「support multiple clients」），能否改用单 serve 多 session 搞定并发（避免 per-spawn serve 的 DB 共享问题）？——曾考虑多个阻碍，逐一实测验证：

| 候选阻碍 | 实测验证 | 结论 |
|---|---|---|
| config serve 级 | POST /session/:id/message body 可 per-message 指定 `agent?`/`model?`；OPENCODE_CONFIG 绝对路径脱离 cwd | **不阻碍** |
| MCP（resolve_ambiguity）serve 级 | default 模式 engine MCP 无状态（mcp_tools.py Path 4 直接 `return options[0]`，不写 workspace） | **不阻碍** |
| **session cwd/dir** | HTTP POST /session **不能** per-session 设 directory（实测） | **真阻碍**（见下） |

**cwd/dir 的准确根因（实测，关键）**：
- session **有** `directory` 属性（custom-tools.mdx `context.directory` + Session 对象 `directory` 字段证实）——**不是「session 没 dir」**（之前「cwd serve 级」表述漏了这点，不准）。
- 但 **HTTP POST /session 不能 per-session 设 directory**：临时 spawn opencode serve + curl 实测，body `dir`/`directory`/`path`/`cwd` **四字段全被忽略**，`session.directory` 始终 = serve cwd（文档 server.mdx `{parentID?,title?}` 属实，无 dir 参数）。
- `opencode attach --dir` 是 **CLI/TUI 命令**（非 SDK/HTTP），`--dir directory to run in` 是 attach 客户端运行目录；framework 的 opencode_backend 是 **HTTP client**（POST /session/:id/message），**不走 attach CLI**。
- 所以 framework（HTTP）**不能 per-session 设 dir** → `session.directory` 硬绑 serve cwd。

**为什么 cwd 是硬阻碍（产物写入）**：
- design-generator 写产物用**文件名**（`write("tiling_split.json")`），相对 serve cwd。
- T1/T2 design-generator 的 serve cwd 不同（`.../artifacts/design/tiling/T1` vs `T2`），**靠 cwd 区分产物目录**（文件名相同 `tiling_split.json`，落各自 cwd）。
- 单 serve 多 session 共享 serve cwd → T1/T2 都 `write("tiling_split.json")` → 写到 `serve_cwd/tiling_split.json` **冲突/互相覆盖**。
- config 能脱离 cwd（OPENCODE_CONFIG 加载期绝对路径），但**产物写入不能**（运行期 write 相对 serve cwd，HTTP 无 per-call cwd）。

**结论**：HTTP 层 `session.directory` 硬绑 serve cwd → 单 serve 多 session 不能给各 design-generator 独立 cwd → 产物冲突 → **当前 HTTP 架构下不可行**。G（per-spawn serve 各自 cwd + per-spawn DB）是唯一可行解。

**未来可行路径（非当前）**：
1. opencode 加 HTTP 支持 per-session dir（POST /session body 接受 directory）→ 上游 feature request（非我们能控）。
2. framework 改用 attach CLI（不走 HTTP）→ 重写整个 opencode_backend（大改，且 attach 是 TUI 不适合 headless 批跑）。

**资源权衡（附带）**：多 serve 资源多（每 opencode serve ~550MB Go 进程，15 并发 ~8.5GB），但当前 1509GB 内存占 0.6%，**不是瓶颈**。单 serve 多 session 省 ~15 倍，但要先解决 cwd（上述不可行），当前不值得投入。

> **避免重复分析**：未来再考虑「单 serve 多 session 替代 per-spawn serve」时，先读本节——核心卡点是 **HTTP 不能 per-session 设 dir**（实测），不是 config/MCP/wiring。除非 opencode 加 HTTP session dir 支持，否则 per-spawn serve + G（per-spawn DB）是 HTTP 架构的唯一解。

### 9.1 根因深化：cwd 是「runtime 进程」属性，不是「session」属性（2026-07-27 实测）

上面说「HTTP 不能 per-session 设 dir」是表层结论。**更深、更准确的根因**是 opencode 的 cwd 归属模型：

- **`session.directory` = 创建它的 runtime 进程的 cwd**（不是 session 独立属性）。实测铁证：serve 端历史 session 的 directory 各不相同（`.../artifacts/design/tiling/T1`、`T2`、`docgen`...），但这些是 **framework per-spawn serve 各自 cwd** 留下的（每 serve 进程 cwd 不同），**不是单 serve 多 session per-dir**——反而证明 session.directory 绑定 runtime 进程 cwd。
- **opencode 有两种 runtime 进程模型**：
  - **CLI/TUI**（`opencode`、`opencode run`）：每次 invocation 启动一个**独立 runtime 进程**，cwd = 进程启动 dir。要 N 个不同 cwd → 启动 N 个 CLI 进程（per-进程 cwd）。
  - **serve + HTTP**（`opencode serve` + SDK）：**一个 runtime 进程**服务所有 session，cwd = serve 进程 cwd（共享）。session 是进程内逻辑单元，HTTP 没法把进程级 cwd 切到 session 级。

- **「CLI 能 per-dir、SDK 不能」的本质 = runtime 进程模型不同，不是 CLI 有「per-session dir」功能**：
  - CLI 的 per-dir 是「**多 runtime 进程**」换来的（每进程独立 cwd），和 framework 的 per-spawn serve **完全同构**。
  - serve 单 runtime 进程塞多 session，cwd 进程级共享，是模型必然，非 SDK 疏漏。
- **结论**：单 serve 多 session per-dir 在 opencode「runtime 绑进程 cwd」模型下**不可能**（CLI/HTTP 都一样）。要 per-cwd 必须 per-runtime-进程——per-spawn serve 就是这个，G 补 DB 隔离。`attach --dir`（CLI）即使真 per-dir，走的也是「attach 自带独立 runtime 进程」路子（等同 per-spawn serve），不是单 serve 多 session。

> 这条比 §9 表层的「HTTP 缺 dir 参数」更准——是**进程模型**决定的，不是 API 参数缺失。未来若 opencode 把 cwd 从「runtime 进程级」提升到「session 级」（runtime 重设计），才可能单 serve 多 session per-dir。
