# L1 — batch 20260813_004235 全链路耗时问题记录

> 批次：`20260812-164258-b8c210`（本地时区 2026-08-13 00:42 启动，workflow_timeout 36000s）
> 算子：resize_bilinear（OK 77.20）、grid_sampler_3d（FAIL exit124，eval 23.01）、unique（FAIL exit124，eval -）
> 本文件只记录客观事实与证据，不提方案、不排顺序（§1.8 L1 边界）。
> 数据源：`logs/batch_20260813_004235.log`、`output/20260812-164258-b8c210/<run>/events.jsonl`、`run.log`、`agents/*.jsonl` transcript。

---

## 批次总览

| 算子 | run_id | 总耗时 | 结果 | 终评 |
|---|---|---|---|---|
| resize_bilinear | 20260812-164258-58ae72 | 7.66h（459.5m） | ✅ workflow-done | 77.20（pass 100%） |
| grid_sampler_3d | 20260812-164258-fcd57e | 10.40h（623.8m） | ❌ FAIL(exit 124) | 23.01（pass 10%） |
| unique | 20260812-164258-a27922 | 5.39h（被截断） | ❌ FAIL(exit 124) | -（codegen 未完成） |

三个算子设计阶段全链走通（requirement→概设→详设→测试设计），差异集中在 codegen 与 precision_debug。

---

## P1 — codegen 是最大时间黑洞（占单算子 34%~58%）

事件源：`events.jsonl` 的 `stage_enter`/`stage_complete` 精确墙钟。

| 阶段 | resize | grid_sampler_3d | unique |
|---|---|---|---|
| requirement | 8m | 17m | 6m |
| 概设（gen+review） | 25m | 14m | 61m |
| 详设 tiling+anchor（含回炉） | 107m（2 次全循环） | 210m（3 次全循环） | 156m（2-3 次） |
| integrate+docgen+validate | 26m | 120m（2 轮） | 90m（2 轮） |
| **codegen** | **267m（58%）** | **210m（34%）** | 189m+（未完成） |
| precision_debug | 7m | 47m | - |
| cannbench_eval | 14m | 21m | - |

**结论**：codegen 是绝对大头；详设回炉次之（2-3h/算子）。

---

## P2 — coder 单会话 turn 数量爆炸（真正的 codegen 耗因）

事件源：`run.log` 中 `agent_stream [<op>/codegen] ascendc-coder` 行，按会话累计秒（`Xs` 字段）回退分段。

**修正说明**：`Xs` 是**会话累计秒**，不是单 turn 耗时。逐 turn 墙钟间隔统计证实：**不存在 >10 分钟的慢 turn**。耗因是 turn **数量**，不是 turn 时长。

| 算子 | coder 会话数 | 各会话 turn 数 | turn 墙钟间隔分布 |
|---|---|---|---|
| resize_bilinear | 5 | [76, 111, **185**, 76, 30] | 77% <30s，22% 30s-2m，**0 个 >10m** |
| grid_sampler_3d | 6 | [83, 18, 62, 8, 14, 20] | 42% <30s，57% 30s-2m |
| unique | 5 | [33, 26, 109, 34, **212**] | 80% <30s，20% 30s-2m |

- resize 单会话（iter4，build 重试轮）跑 **185 turn / 104 分钟**；unique 单会话（iter5）跑 **212 turn / 124 分钟**（后触发 hard_timeout 7417s）。
- turn 间隔平均 22-37s（含模型生成 + 工具执行，其中 bash 多为编译/读文件）。
- **核心事实**：写一个算子，coder 一个会话要 30-212 个 turn。对比：熟练人力或收敛 skill 预期 ~20-40 turn。

---

## P3 — coder 前期「过度调研零写盘」（silent-cut）

事件源：`agents/ascendc-coder-*.jsonl` transcript 工具调用统计。

- grid_sampler_3d 首轮 coder：**78 read + 55 bash + 1 skill + 1 grep + 0 Write/Edit**——整轮只调研参考算子/知识库/repo 结构，从不写码 → silent-cut（`no artifact, thinking-only terminal`）。
- 框架 WARN `Stage 'codegen' agent silent-cut` 记录：resize 2 次、grid_sampler_3d 2 次、unique 2 次（部分在 deploy 重试阶段）。
- silent-cut 后框架 `auto-resume next iteration`，**下一轮从零重新探索**（不注入上一轮结论）。
- 每次 silent-cut 白耗 24-42 分钟（iter1 墙钟：resize 24.1m、grid 42.1m、unique 15.8m）。

---

## P4 — codegen build 失败循环（kernel 编译错误，属 codegen 自身职责）

事件源：`run.log` `codegen build failed` + `subprocess/build_ascendc.log`。

| 算子 | build 尝试 | 失败类别 | build 间隔 |
|---|---|---|---|
| resize_bilinear | 5 次失败 + 1 成功 | C-API（kernel 头文件 C++ 编译错误：resize_bilinear.h:100/181/182/204） | 34m / **104m** / 27m / 7.5m / 0.8m |
| grid_sampler_3d | 4 次失败 + 1 成功 | 同上 | 23m / 57m / **89m** |
| unique | 1 次失败后未完成 | - | 15m |

- build 失败是**代码生成的编译错误**（kernel C++ 头文件），属 codegen 职责内，非框架/上游缺陷。
- 但**单次 build 失败→下次 build 尝试间隔高达 104 分钟**（resize iter3→iter4），此间隔内 coder 在反复迭代编译错误（对应 P2 的 185-turn 会话）。

---

## P5 — 网关不稳定（thinking 模式 400 + 429 + validation error）

事件源：`run.log` 中 `server-side message error` / `Type validation failed` / `429 backoff`。

| 算子 | API 网关错误 | 429/infra_backoff | 现象 |
|---|---|---|---|
| resize_bilinear | 5 | 6 | `content[].thinking must be passed back`（400，多次）；`Type validation failed: expected number, received undefined at usage.output_tokens` |
| grid_sampler_3d | 2 | 10 | 同前 |
| unique | 3 | 7 | 同前 |

- 每次网关错误触发 `server error; immediately resuming session` + 429 backoff（sleep 20-40s）。
- 这是**外部网关层故障**（§1.11：以实际链路证据为准，此处是 SDK 实际运行日志），非框架逻辑缺陷；框架的 resume 链路成功兜底。

---

## P6 — coder 上下文膨胀到 25 万 token

事件源：网关错误响应中的 `input_tokens` 字段 + transcript。

- 观测到 `input_tokens: 251938`（25 万）的单次请求。
- coder 单会话 185-212 turn，每 turn 积累工具结果/文件内容到上下文；turn 越多上下文越大，后续 turn 生成越慢。
- 上下文膨胀与 P2（turn 数量）、P5（网关慢/错）相互放大。

---

## P7 — 详设 tiling↔anchor 回炉循环（2-3 轮）

事件源：`events.jsonl` 阶段时序（同一 tiling 子阶段多次 `stage_enter`）。

- resize：tiling 全链跑 2 轮（split/buffer-kernel/precision-perf/anchor/consistency ×2），第二轮回炉 ~35m。
- grid_sampler_3d：tiling 全链 3 轮（T1+T2 双模板并行），回炉累计 ~2h。
- unique：2-3 轮。
- `iteration_start reason` 记录含 `contract unsatisfied: tiling_results`（resize 1 次、unique 1 次）——tiling 产物契约不满足触发重跑。
- 每次回炉是全量重跑该模板的所有 tiling 子阶段，不是只重跑被指认的子阶段。

---

## P8 — 单算子超时截断（unique）

事件源：批日志 `[ERROR] Timeout: Workflow timeout: exceeded 36000s budget (ran 36030.5s)`。

- unique 在 codegen 阶段被 workflow_timeout 截断（run 自身 5.39h，批墙钟 10h 到点），op_dir 回滚到运行前状态。
- unique 的 coder 单会话（sess5）触发 `exceeded 7417s hard cap`（约 2h 的单个 spawn 硬超时）。
- grid_sampler_3d 越过 deadline 后因 `cannbench_adapt` 标记 uninterruptible 获 soft let-through，完成 eval 出分 23.01。

---

## P9 — resize_bilinear 精度一次通过（"几乎没干活"）

事件源：`run.log` precision 阶段 + `events.jsonl`。

- precision_debug/run_tests 墙钟 **7m22s，status=ok，直接进入 cannbench_adapt**（无 scope_guard/bounds_check/diagnose 阶段）。
- eval 用例 `max_diff 0.0`（输出与 golden 完全一致）。
- **事实**：resize 的最终代码一次通过精度验证；其 codegen 的 4.45h 中真正修 bug 的时间≈0，几乎全是 P2/P3/P4 的死时间。这也解释了"阶段几乎没干活"——不是没干活，是干活（codegen）的效率问题。

---

## P10 — inotify ENOSPC 报错：是资源上限，不是磁盘满，也**不是** turn_stall 的原因

事件源：各 run 的 `.opencode_home/.opencode-serve-*.log`。

**报错含义（先澄清）**：`inotify_add_watch on '.../.git' failed: No space left on device` 的 ENOSPC **不是磁盘空间**。inotify 是内核文件监听机制，有每用户硬上限：`/proc/sys/fs/inotify/max_user_watches=8192`（可添加的 watch 总数）、`max_user_instances=128`（可创建的实例数）。ENOSPC 报在 `add_watch` 上指 **watch 数达到 8192 上限**（实例上限在 `inotify_init` 时报，不同）。

**现象**：
- 当前批 **101 个 serve 日志**出现此错（78 个指向主仓 .git、其余指向 worktree）。
- 主仓 **28.2 万文件，其中 output/ 占 27.3 万（97%）**——35 个批次累积的产物（transcript、opencode_home/node_modules、serve 日志）。
- 批结束 serve 退出后 inotify 使用回 0（`/proc` 实测）——**无泄漏**，是运行期并发耗尽。

**时序反证（关键）**：
- **GLM 时代（8/9-8/11）：314/38/50 个 serve，0 inotify 错误**——同限制下并发更大也正常。
- **8/12 14:32 起：4 个 serve 就 3 个错**——与换三方代理（deepseek-v4-flash @ 1.95.37.146:3000）时间吻合。
- 但 inotify 是内核机制，代理无法直接影响其限制。inotify 报错与换代理**时序相关但非因果**——更可能是仓库随批次累积变大（output/ 主导 watch 数）+ 代理期 serve 存活更久（慢/卡响应）叠加的环境现象。

**逻辑上排除 inotify 是 turn_stall 原因**：turn_stall 检测器（`opencode_backend.py:1577-1601`）只监控 `sse.state["turn_ts"]`（模型 SSE 流活性）与 chars；inotify 是文件监听路径，与 SSE 流**完全独立**——inotify 失败不可能导致「600s 无 SSE」。且 101 个 inotify 错 serve 中仅 11 次 stall，绝大多数带错的 serve 正常工作。

## P11 — turn_stall 根因：网关对新鲜会话不产流（代理层）

事件源：批日志 turn_stall abort 行 + run.log 网关错误。

- **11 次 stall 中 9 次卡在 `last turn 2`**：新鲜 spawn → turn 1（skill steer，全 agent 恒为 `(text), 0 chars`）→ turn 2 首个真实模型响应 → **600s 无任何 SSE 输出** → turn_stall abort。
- `chars static 600-610s` = 模型既无 thinking 也无 text 流（真无输出，非在思考）。
- 网关侧同源证据（P5）：三方代理 `content[].thinking must be passed back`（400）多次、`usage.output_tokens` 类型校验失败、429。
- **模型标识**：当前批 `deepseek-v4-flash @ http://1.95.37.146:3000/v1`（三方代理）。
- **结论**：turn_stall 根因是**网关（三方代理）对部分请求不产流/慢产流**，非端侧代码问题，也非 inotify。GLM 时代无此现象（响应正常→turn 正常流式）。框架 turn_stall→resume 恢复链路正确兜底（11 次全自愈），但每次 10 分钟死等是代理不产流直接造成的。

## P12 — coder turn 行为：185-turn 会话仅 6 次写码

事件源：transcript `ascendc-coder-04.jsonl`（resize sess4/iter4）。

| 动作 | turn 数 | 占比 |
|---|---|---|
| bash | 125 | 68% |
| read | 51 | 28% |
| write/edit | **6** | **3%** |
| 其他 | 3 | 2% |

- bash 内容：`ls/find/cat/cd` 大量目录侦查 + **自建 `/tmp/opencode/rbcheck` 沙箱用 `g++ -fsyntax-only` 反复试 cast 语法**。
- **事实**：4 小时会话只改了 6 次码，176 个 turn 在「编译-读错-试探」机械循环。

## P13 — 设计回炉的两类根因（AC2 真实问题 vs AC3 证据缺失）

事件源：`artifacts/design/**/anchor_report.json`。

- **AC2（blocker/infeasible）真实设计问题**：grid_sampler_3d 有 8 个——如「逐位置标量 GM→UB DataCopyPad 直写」与 API 文档语义不符、「8 邻域 gather 超 UB 预算」等。这类回炉是真实设计修正，值得跑。
- **根因深化（见 L3 Q15）**：grid_sampler 算法本质是 gather + 三线性插值（golden=`torch.nn.functional.grid_sample`），但设计把「8 邻域 gather」建模成「逐元素 GM→UB DataCopyPad 单元素事务」——这是**方案层建模错误**，非 API 用错。最终 kernel（`grid_sampler_3d.h:442-544`）仍逐元素搬移（每输出点 8×DataCopyPad + 8×GetValue + 8×SetValue，全标量），anchor remediation 给的治本路径「整块搬入 + UB 内掩码/移位（分块搬入 + UB 内偏移索引，见 L3 Q15）」未被采纳（只采纳了降 F + 固定 slot 绕对齐）。后果：2 个残余 DataCopyPad 问题携带到 precision 18/20 fail。
- **AC3（warning/unverified）证据缺失**：resize 8 个、grid 8 个——`tiling_shared_summary.json` 的 **split 段与 buffer_kernel 段为空**（无 TilingKey 字段定义、无 workspace 分配记录、无 dtype 路由表），anchor 无法跨模板对质 → 回炉全量重跑。
- **事实**：resize 无 AC2（设计逻辑本身正确，回炉全因 AC3 证据缺失）；grid 两者都有。
- **关键**：AC3 类回炉是「证据缺失」而非「设计错误」，本可在 tiling 产出时校验段非空而避免，却在 anchor 阶段以全量重跑为代价暴露（违反 §1.3 加载期校验优于运行期暴露）。

## P14 — thinking 块规模与 turn 间隔对比

事件源：transcript thinking 块 + run.log turn 间隔。

- coder 平均 thinking 块 4679-9546 chars（design-generator 为 3826-4748）；最大 100k+ chars。
- turn 间隔：coder avg 22-37s / p90 46-74s；design-generator avg 7-8s / p90 11-16s——**coder 慢 3-5 倍**（同模型同网关）。
- **事实**：coder 慢 turn = 上下文大（250k，P6）+ 重型 bash 工具执行（编译），非正常模型延迟。

## P15 — session resume 两条通路并存，codegen 绕过 degrade（设计不一致）

事件源：run.log `agent_resume`/`agent_session` 日志 + `codegen.py`/`opencode_backend.py`/`base_backend.py` 代码。

**现象**：同样的 turn_stall，恢复路径不同——
- **design 阶段（9 次 stall）**：日志 `agent_resume ... auto-resuming session (sidecar present)` + `agent_session (cross-run resume)`。走 **backend 层**通用 sidecar resume。
- **codegen 阶段（2 次 stall）**：仅 `agent_session ... (cross-run resume)`，**无** `agent_resume` 日志。走 **stage 层**显式 resume。

**根因（代码实证）**：
- backend 层 resume（`opencode_backend.py:563-599`）：spawn 时 framework 未传 `resume_session_id` → backend 读 sidecar（session_id + `resume_fails`）→ 若 `resume_fails >= resume_attempts(3)` 退化 fresh，否则 resume。
- codegen stage 层 resume（`codegen.py:602-626`）：`actions()` 里**自己读 sidecar，只读 `session_id`、不读 `resume_fails`**，直接 `return [SpawnAgent(resume_session_id=_sid)]`。
- 后果：codegen 显式传 `resume_session_id` → backend 走 `if resume_session_id:` 分支，`_resume_fails` 初始为 0 写回 sidecar → **覆盖了 crash-salvage `_bump_session_resume_fails` 累加的 resume_fails**。

**影响**：codegen 的坏 session 反复 stall 时 `resume_fails` 永远归零、**永不退化 fresh**，违背 094d60e7「resume 数次不成功退化 spawn」的设计意图。本次批跑未触发危害（resume 后 session 都恢复），但这是潜在死循环风险。

**性质**：违反 §2.5「同一职责只允许一条实现通路」——「读 sidecar 决定 resume」在 backend 层与 codegen stage 层各有一份，且 stage 层实现不完整（未跟上 backend 层的 degrade 演进）。

## P16 — 增量构建未生效：每次 build 全量重编所有算子 .o（CMake GLOB）

事件源：`resources/repository-profiles/cann-bench.yaml` + `subprocess/build_ascendc.log`。

**配置**：cann-bench profile 有 `incremental_command_template`（`if [ -f build/CMakeCache.txt ]; then ... cmake --build build ...; else bash build.sh; fi`），意图复用 build/ 增量只重编改动 kernel。

**实际（日志反证）**：build 日志显示 `cmake --build build` 触发 re-configure（`-- Configuring done`）后，**从 [3%] 到 [97%] 全量编译 add/sqrt/resize_bilinear 三个算子共 51 个 .o 文件**（`csrc/ops/add/`、`csrc/ops/sqrt/`、`csrc/ops/resize_bilinear/` 各 17 个）。

- 根因：cann-bench 的 CMakeLists 用 **GLOB 收集 `csrc/ops/` 下所有算子源文件**（memory `cann-bench-deploy-builds-all-ops`），coder 每次改动文件 → GLOB 结果/时间戳变化 → re-configure + 全量重编。
- **影响分层**：host .o 编译快（`--parallel $(nproc)` 并行，51 个小文件约 30s）；真正耗时是 **kernel TBE 编译**（`resize_bilinear.h` → kernel binary，失败那次 62s 才报出 cast 错误）。
- 成功 build 34s/12s：12s 那次 kernel 未重编（前次已编译成功，仅重新打包 dist/whl），说明 **kernel 层有缓存，host .o 层无增量**。

## P17 — 两种「编译」需区分：deploy build（框架跑的）不误判，coder bash 工具（opencode 跑的）可能误判

事件源：`deploy.py:61/_run_command`（deploy build）+ `opencode_backend.py:1577-1606`（turn_stall/keepalive）。

**关键区分（此前分析混淆，经用户纠正）**：codegen 阶段存在两种「编译」，框架对它们的可见性完全不同：

| | deploy build（正规构建） | coder bash 工具编译（试探） |
|---|---|---|
| 谁跑的 | **框架 `subprocess.run(timeout=600, capture_output=True)` 直接跑**（`deploy.py:504-546`） | opencode 的 bash 工具 |
| 框架可见性 | **完全可见**：有 Popen/poll、`build_ascendc.log` 完整落盘、`TimeoutExpired` 超时处理 | 仅 SSE 知道「发了 tool:bash」，看不到 subprocess |
| 超时机制 | 自己的 `_BUILD_TIMEOUT=600`（`deploy.py:61`） | 受 turn_stall/keepalive 600s 影响 |
| 是否被 turn_stall 误判 | **否**（时序不重叠：coder 返回后才跑 deploy build；deploy build 不是 agent POST） | **可能**（coder 在 agent 会话内用 bash 编译 >600s 时） |

**代码事实**：
- turn_stall（`opencode_backend.py:1577-1601`）监控的是 **agent message POST**（模型生成 + coder 的 opencode 工具），判定条件只有「`turn_ts` 超时」+「chars static」；`block_types` 仅用于 reason 日志，不参与判断。
- deploy build 是框架在 coder 返回后、stage transition 里跑的 subprocess，**不在 turn_stall 监控范围**，有自己的超时和日志。

**真正的风险（重新定位）**：
1. **coder bash 工具编译**（opencode 跑的，如 `/tmp/opencode/rbcheck` 沙箱 g++ 试探）：若 >600s 会被 turn_stall 误判。但试探编译通常短命（单文件 g++ 几秒-几十秒），本批 11 次 stall 全部是「模型不吐字」的 turn 2，无一次是工具执行误判。
2. **deploy build 的 `_BUILD_TIMEOUT=600`（`deploy.py:61`）硬编码**：复杂算子（多模板/大 kernel）编译 >600s 时，**框架会在 deploy 层判为超时失败**——这才是「600s 不合理」的精确落点。但 deploy 层框架**能精确控制**（poll subprocess + build 日志可判断 build 是否真在跑/卡死），不像 turn_stall 只能从 SSE 猜。

**性质**：
- turn_stall 误判「coder bash 工具编译」是低风险（试探编译短命）。
- deploy `_BUILD_TIMEOUT=600` 误判「正规构建 >600s」是**中风险**（复杂算子真实可能），且框架有精确信号（poll + 日志）可修，不必依赖 SSE。
- 结论：**「构建编译」不依赖 opencode SSE——deploy build 是框架自己跑的，有日志 + poll + 超时**。我之前把它与 coder bash 工具混淆，是本分析的一个错误，已修正。

## P18 — 设计 agent 读取失控：重复读上游产物 + 大量目录侦查

事件源：`agents/ascendc-design-generator-T1-*.jsonl`（resize T1 各子阶段）工具调用统计。

**事实**：
- 73 次 read，**去重目标仅 31 个**，平均每个文件读 2.4 次。重复最严重：`template_division.json` 读 6 次、`general_design.json` 读 6 次、`hw_params.json` 读 5 次、`decision_log.json` 读 5 次。
- bash 大量目录侦查：`ls -la` 14 次、`cd` 11 次、`find` 多处、`python3 json.load` 6 次——「找文件在哪 + 读 JSON」的侦查。
- 但**读的范围收敛**（31 个去重目标 = 上游产物 ~15 + skill 参考 ~10 + 知识库 API 4 + 框架代码 1），**不是读无关文件**，是「重复读 + 侦查方式」失控。
- 另有 43 次 read 是 **aborted**（turn_stall 中断导致），与 P11 死等同源。

**性质**：不是「自己读 vs 注入 prompt」的本质差距，而是**读取纪律失控**（重复读 + 目录侦查）。优化方向是「skill 明确上游产物路径清单 + 每个文件读一次」，而非笼统的「注入 prompt」（注入有 prompt 过长 + 违反 §2.8 按需 Read 的风险）。

---

## 附：数据可信度说明

- 阶段墙钟：`events.jsonl` 权威，精确到秒。
- turn 会话分段：run.log `agent_stream` + 会话累计秒回退，可靠（5-6 会话/算子与 codegen 迭代数吻合）。
- 早期「单 turn 60-120 分钟」的观测**有误**（误读会话累计秒为 turn 耗时），本文件以逐 turn 墙钟间隔为准（P2 修正）。
- transcript 的 `ts` 字段为写入时间不可用于计时，未采用。
