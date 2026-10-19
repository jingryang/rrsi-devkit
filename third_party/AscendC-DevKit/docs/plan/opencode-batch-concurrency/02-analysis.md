# opencode 后端批跑并发 — L3 方案分析

> 层次：L3（选项 + 取舍 + 理由）。事实见 `01-problems.md`（L1），改动配方见 `03-impl-*.md`
> （L4，拍板后产出）。调研中演进、拍板后冻结。
> 范围：P-BC1（Logger 串流）/ P-BC2（stderr 吞）/ P-BC3（空烧 1h）/ P-BC4（design 5 并发死锁）。
> 约束：四把尺子（§1.2 可维护/可扩展/可诊断/架构合理）+ §1.2 根因优先 + §1.3 暴露非静默
> + §2.5 单一通路 + external-infra-not-framework-responsibility（外部故障 framework 只负责
> 留信号/不空烧，不修外部）。

## §0 边界划分（哪些归 framework 修、哪些不归）

| 问题 | 归属 | 依据 |
|---|---|---|
| P-BC1 run.log 串流 | **framework 自身 bug**（Logger/_Tee 走进程全局 sys.stderr） | §1.2 根因 |
| P-BC2 stderr 被吞 | **framework 自身 bug**（_start_serve DEVNULL） | §1.3 暴露、external-infra「留信号」 |
| P-BC3 空烧 1h | **framework 自身缺陷**（无 keepalive） | external-infra「不空烧」 |
| P-BC4 design 死锁 | **待定位**：framework spawn 并发 bug → framework 修；opencode 多实例限制 → 不归 framework 修（控并发是架构边界） | §1.2 根因优先 + external-infra |

P-BC1/BC2/BC3 是 framework 职责内必修（无争议）；P-BC4 必须先定位再判归属，**不能未定位就控并发**（否则违反 §1.2 规避）。

## §1 P-BC1 修法（Logger 并发串流）

### 选项
- **A. Logger 改 thread-local run context**：`bind_run_log` 不再绑全局 `sys.stderr`，改为 set **thread-local** 当前 run 的 run.log file 句柄；`Logger` 各写入方法 `print` 到 **console（sys.stderr，共享 interleave 可接受——console 本就是共享终端）+ thread-local run.log（per-exec 独立）**。`_Tee` 退出 run.log 路径（仅留 console 或整体退役）。
- **B. 每 exec 独立进程**（multiprocessing 替代 ThreadPoolExecutor）：进程隔离 sys.stderr，天然不串。
- **C. 维持现状**：run.log best-effort 容忍，events.jsonl 权威（即 framework 当前注释立场）。

### 四把尺子
| 尺子 | A thread-local | B 多进程 | C 维持 |
|---|---|---|---|
| 可维护 | ✅ run.log 单一写入点=Logger（§2.5），thread-local 是标准并发解 | ❌ 多进程改造波及 ThreadPoolExecutor 全部调用方 + 进程间状态共享重写 | ⚠️ 容忍=债留 |
| 可扩展 | ✅ 任意并发数 run.log 都正确 | ⚠️ 多进程模型对新 stage/并发点要求高 | ❌ 并发越高串越狠 |
| 可诊断 | ✅✅ run.log 不串/不丢，design 卡点可读 | ✅ | ❌ 当前 design 卡点正因 run.log 串而不可读 |
| 架构合理 | ✅ 根因（sys.stderr 全局）→ thread-local，对症 | ⚠️ 为日志问题动并发模型，越层 | ❌ 已知 race 不修 |

### 决策
**A**。根因是 `sys.stderr`/`_BINDING` 进程全局 + sibling thread 共享；thread-local 路由是对症修复，且落实 §2.5（run.log 唯一写入点收敛到 Logger，退役 _Tee 这条 sibling-unsafe 通路）。B 越层（为日志动并发模型），C 留债。

## §2 P-BC2 修法（stderr 被吞）

### 选项
- **A. DEVNULL → `cwd/.opencode-serve-<port>.log`**（stdout/stderr 合并同文件，per-exec 和产物同目录便于关联）。
- B. 落 scratch_dir 集中。
- C. 维持 DEVNULL。

### 决策
**A**。唯一合理选项（§1.3 暴露非静默；external-infra「留可诊断信号」）。UT 用 `_FakeServe` override `_start_serve`，改动不影响 UT。file 句柄生命周期：存 `proc.serve_log_handle`，`_stop_serve` 关闭（不泄漏）。

## §3 P-BC3 修法（空烧 1h）

### 选项
- **A. SSE keepalive 判活**：SSE 已订阅 `/event`（v0.2.0），用 `session.idle`/事件流判 agent 是否真在跑；N 秒无任何事件 → 报 fatal（不静默等 1h）。
- **B. 缩短 message_timeout + fatal**：3600s → 合理值（如 stage_timeout），超即 fatal。
- **C. A + B**：keepalive 判活为主、timeout 兜底。

### 四把尺子
| 尺子 | A keepalive | B 缩 timeout | C A+B |
|---|---|---|---|
| 可诊断 | ✅ 区分"真在跑"vs"死锁" | ⚠️ 超时只知"没完成" | ✅✅ |
| 可维护 | ✅ 复用已有 SSE 订阅 | ✅ 简单 | ✅ |
| 架构合理 | ✅ 事件驱动判活，对症 | ⚠️ 可能误杀慢 agent（design-generator turn 多） | ✅ keepalive 准 + timeout 兜底 |

### 决策
**C**。keepalive（A）判活精准（复用 SSE，死锁即报），timeout（B）作硬兜底（防 SSE 自身异常）。不空烧（external-infra）。

## §4 P-BC4 定位 + 修法（design 5 并发死锁）

### §4.1 定位路径（强制前置，§1.2 根因优先）
1. 先做 P-BC2（stderr 落盘）→ design 卡死时 opencode serve + engine MCP 的 stderr 可见。
2. 5 并发复现，读 stderr：观察 5 个 opencode serve / 5 个 engine_mcp_stdio 在 primary agent session 创建后卡在哪一行（MCP 握手？opencode primary 初始化？stdio pipe？全局文件争用？）。
3. 对照单算子 stderr（正常）找差异。

### §4.2 修法（按定位结果——控并发已撤回，见 §4.3）
- **路径甲：framework spawn 并发 bug**（如 5 sibling thread 共享了不该共享的 fd/cwd/env/config 句柄）→ **修 framework**（§1.2 根因；属 framework 产权）。**P-BC4 唯一解决路径**。
- ~~路径乙：控并发~~ —— **【用户决策 2026-07-21 撤回】** 5 并发是批跑并发功能的核心价值（8 卡 NPU 远多于 5 算子），控并发=退化成单算子调用，摧毁并发意义；若为控并发而控并发，并发功能本身就没必要存在。
- **若 §4.1 定位指向 opencode 多实例限制**（external-infra，不归 framework 修）且路径甲不成立：**本工作不解决 P-BC4**，留作后续——可能关联 `opencode-streaming-transport` L3 §10「纯 A（prompt_async 异步）收敛」（异步不阻塞或可绕过多实例死锁），另立工作评估。

### §4.3 强约束（红线，用户决策更新 2026-07-21）
- **控并发不作为 P-BC4 解决手段**（§4.2 路径乙撤回）。
- P-BC4 解决 = §4.1 定位 → 路径甲（修 framework）；不成立则本工作不解决（不控并发掩盖）。
- 仍守 §1.2：定位前不定修法；不得为"让批跑能跑"而规避根因。

## §5 实施顺序（step 依赖 + 约束核对）

| step | 内容 | 依赖 | 约束核对 | 状态 |
|---|---|---|---|---|
| S1 | P-BC1 Logger thread-local（§1 决策 A） | 无 | §1.2 根因、§2.5 单通路（run.log 写入点收敛 Logger）、可诊断 | ✅ 完成 + UT（7/7，含并发隔离回归） |
| S2 | P-BC2 stderr 落盘（§2 决策 A） | 无 | §1.3 暴露、external-infra 留信号 | ✅ 完成 + UT（2/2） |
| S3 | P-BC4 定位（§4.1：stderr 复现观测） | **S2**（stderr 落盘后才能看 opencode 内部） | §1.2 根因优先 | ✅ 完成（根因 = `external_directory` 默认 `ask`，见 03-impl） |
| S4 | P-BC4 修法（§4.2：path 甲） | **S3** | §1.2；路径甲（framework config 补 `external_directory: allow`） | ✅ 完成 + 运行时验证（design turn 7→20+，产出 general_design.json） |
| S5 | P-BC3 keepalive+timeout（§3 决策 C） | S1/S2 可并行；复用 v0.2.0 SSE | external-infra 不空烧 | ✅ 完成 + UT（3/3） |

**顺序刚性**：S3 必须在 S2 之后（stderr 落盘是定位前置）；S4 必须在 S3 之后（定位前置修法）。S1/S2 是 framework 自身 bug，可先做且互不依赖。S5 可与 S1-S4 并行或收尾。

**当前进度（2026-07-21）**：S1/S2/S3/S4/S5 **全部完成**。P-BC4 根因经运行时复现定位 =
opencode `external_directory` 权限默认 `ask`（config 漏设）→ 非交互批跑 design-generator
探 worktree 时触发 ask 无 resolver → 无限阻塞（requirement 读 cwd 内文件不触发，故正常）。
S4 = `_assemble_config` 补 `external_directory: allow`（path 甲，framework 产权）。运行时验证：
修复后 design turn 7→20+ 持续推进 + 产出 general_design.json（修复前 stall 12+ min 零产物）。
**S5 gap**（独立 follow-up）：keepalive 被 opencode 心跳帧绕过（permission-block 期间 last_event_ts
仍刷新），只抓 SSE 静默、抓不到 permission-block；与 P-BC4（已由 S4 解决）独立，另立工作。
详情见 `03-impl.md`。

## §6 待用户拍板项
1. 整体方案（§1-§5）是否通过。
2. P-BC4 §4.2 两条路径的预案是否接受（尤其路径乙"控并发是架构边界"的定性）。
3. 是否同意 S1/S2 先做（framework 自身 bug，无争议），S3/S4 顺序刚性。
4. P-BC1 决策 A 涉及 Logger 改造（thread-local + 退役 _Tee 的 run.log 路径），改动面确认接受。
