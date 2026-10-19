# batch_self_evolve 批跑 runlog — token 401 全 FAIL（2026-07-20）

> 任务：拉起 `scripts/batch_self_evolve.sh` 批跑算子生成。拉起前读历史日志发现今日（18:46）
> 那一批已全 FAIL，定位到根因 = **agent 执行环境问题（LLM 凭证失效）**，按用户授权属「agent 执行
> 本身的问题，不救援」那一类。本文诚实记录现象、根因、性质判定与修复指引，未擅自重跑注定失败的批。

## 0. 触发与范围

- 用户指令：拉起 `scripts/batch_self_evolve.sh` 批跑算子生成；只负责拉起 + 读日志发现问题；
  流程性小问题可救援，agent 执行本身/大方案问题不救援。
- 拉起前检查（非环境预检，是读历史日志）：发现今日已有一批 `batch_id=20260720-104711-bf84a2`
  （worktree `cann-bench-batch/20260720_184658/`，2026-07-20 18:46 起跑），**5/5 算子全 FAIL（exit 65）**，
  失败模式完全一致。先诊断再决定是否重跑。

## 1. 现象（客观事实）

总日志 `logs/batch_20260720_184658.log` 尾部汇总：

```
batch_id: 20260720-104711-bf84a2
batch 20260720-104711-bf84a2: 0/5 succeeded
  [FAIL(exit 65)] advance_step_v2                                    exec=20260720-104711-66e20f
  [FAIL(exit 65)] scatter_pa_kv_cache                                exec=20260720-104711-21a819
  [FAIL(exit 65)] ai_infra_aggregate_hidden_grad                     exec=20260720-104711-dfc9e1
  [FAIL(exit 65)] ai_infra_manifold_constrained_hyper_connection_post exec=20260720-104711-88df2a
  [FAIL(exit 65)] multi_add_rms_norm_dynamic_quant                   exec=20260720-104711-346712
```

每个算子（以 advance_step_v2 为例）的失败链路一致：

```
[WARN] Stage 'requirement' reached max iterations (10) without satisfying output_contract: ['requirement', 'unclear_items', 'requirement_clarified']
       ↳ requirement_doc.md (54 lines, 1995 bytes)        # 只产出 md，没产出 requirement.json
[WARN] → schema_violation: requirement.json: required artifact not produced
[ERROR] Stage 'general-design-generator' aborted: input validation failed:
        - neither requirement nor design_doc_path is available
[ERROR] Halting workflow — a required upstream artifact is missing
        • repo_rollback op_dir restored
```

`report.json`（advance_step_v2）印证 stage 视角：

```json
"requirement": {"status": "ok", "iterations": 10, "elapsed_ms": 106854}  # stage 自身没报错，是子 agent 秒退
"general-design-generator": {"status": "aborted", "iterations": 0}
```

## 2. 根因（凭据 + 证据）

**根因：opencode backend 的 LLM apiKey 凭证失效，所有 agent 子调用 401 秒退、零产出。**

证据链：

1. **每个 requirement agent 只跑 2 turn、~10s、零产出即退出**。`agents/requirement-analyst-01.jsonl`
   （5 个算子全部 2225 字节、同构）：
   - turn 1（assistant 注入 prompt）：要求 agent 读 `requirement_doc.md` 并用 Bash/Edit 写 `requirement.json`。
   - turn 2（API 调用）：
     ```json
     error: APIError Unauthorized
     data.message: 'Invalid token (request id: ...)'  type: new_api_error
     statusCode: 401   isRetryable: false
     url: http://192.168.0.212:3000/v1/messages
     ```
   - 5 个算子（66e20f/21a819/dfc9e1/88df2a/346712）turn2 error 全部同一 401 Invalid token。

2. **凭证配置点**：`output/<batch>/<exec>/.opencode_home/opencode-config.json`
   ```json
   "anthropic": {
     "options": {
       "baseURL": "http://192.168.0.212:3000/v1",
       "apiKey": "{env:OPENCODE_SECRET_ANTHROPIC_APIKEY}"
     }
   },
   "model": "GLM-5.2"
   ```
   apiKey 取自 env `OPENCODE_SECRET_ANTHROPIC_APIKEY`。

3. **该 env 当前未提供**：
   - 当前 session `env | grep` 无 `OPENCODE_SECRET_ANTHROPIC_APIKEY`（只有给 Claude Code 主进程用的 `ANTHROPIC_AUTH_TOKEN`，两者不同源）。
   - `grep -rn OPENCODE_SECRET_ANTHROPIC_APIKEY scripts/ src/ascendc_devkit/adapters/` **零命中**——脚本与工程都不注入它。
   - profile 扫描（`~/.bashrc`/`~/.bash_profile`/`~/.profile`/`~/.zshrc`/`/etc/profile`/`~/.config/opencode/*`）也**零命中**；仓内无 `.env`/`.opencode*`。
   - → 结论修正：token 不是「过期失效」，而是**从未配置进任何运行环境**（今日 18:46 那批 FAIL 同因）。apiKey 解析为空/字面量 → new-api 网关返回 `Invalid token` 401。

4. **为什么 stage 显示 `status: ok` 却 FAIL**：stage 把「agent 进程正常退出」当 `result: ok`
   （agent 秒退不是 crash），但 `output_contract`（`requirement.json` 未产出）判 unsatisfied →
   重试 10 轮全 401 → 耗尽 → 下游 general-design 因缺 `requirement` 输入 abort → halt。
   即：**失败在 agent 子调用层（LLM 401），不在 stage 编排层**。

## 3. 性质判定（按用户授权分类）

| 维度 | 判定 |
|---|---|
| 是脚本 bug 吗？ | 否。脚本正确建 worktree / 生成 manifest / 派发 / 记 batch_id，全按设计跑。 |
| 是 requirement stage 设计问题吗？ | 否。stage 契约、10 轮重试、halt 逻辑都正常工作（恰恰是它们正确检测到了 agent 零产出）。 |
| 是 agent 逻辑问题吗？ | 否。agent 没机会执行——首个 LLM 请求即 401。 |
| 是方案问题吗？ | 否。无需调整架构/流程。 |
| **归类** | **agent 执行环境问题（LLM 凭证失效）** |

→ 按用户授权「**agent 执行本身的问题，不需要你来动手救援**」，**不救援**。修 token 是用户侧动作
（我不知道有效 token 值，也无法代为配置 env）。

## 4. 修复指引（用户侧）

任选其一让 opencode 拿到有效 apiKey 后再拉起：

- 设 env：`export OPENCODE_SECRET_ANTHROPIC_APIKEY=<有效token>`（写进拉起脚本的同一 shell 或 profile）；
- 或确认该 token 是否已在 `http://192.168.0.212:3000`（new-api 网关）侧过期/被禁，续期后同 env 名复用。

验证（轻量、不跑全流程）：设好 env 后可先单算子探活，例如
`ascendc-devkit run --resume 20260720-104711-66e20f`（续 advance_step_v2 一个），看 requirement stage
是否产出 `requirement.json`；产出即 token 已通。

## 5. 下一步（等用户确认 token 后由我执行）

token 修复后，拉起方式二选一（待用户拍）：

- **续跑本批**：`RESUME=1 bash scripts/batch_self_evolve.sh`（读 `.batch_id=20260720-104711-bf84a2`，
  复用 worktree `20260720_184658/`，框架续跑 5 个未完成算子）。
- **首跑新批**：`bash scripts/batch_self_evolve.sh`（默认清单 5 算子，建新 worktree）。

> 注：本批 5 算子全 FAIL 在 requirement stage 早期（无任何下游产物沉淀），续跑 ≈ 重跑 requirement，
> 与首跑在该 stage 上的代价相当；续跑省的是 worktree 重建。

## 6. 验证诚实性

- ✅ 已做：读历史日志 + per-exec transcript + opencode-config + env，定位到 token 401 根因（全算子同因）。
- ❌ 未做：未拉起任何新批（根因确定且当前 session 无 token，重跑必然同 FAIL，避免制造噪音日志与无意义耗时；非「跳过」，是「条件不满足先报告」）。
- ❌ 未做：未修 token（属 agent 执行环境，按授权不救援；且不知有效值）。
- 覆盖声明：本次为**批跑前置诊断**，未触发任何 heavy_llm 执行（上一批 5 算子的 requirement 秒退也不消耗 LLM token——401 在网关侧拒绝）。

## 7. 重跑结果（2026-07-20 22:52 首跑新批）— token 已通，批跑正常推进

> 用户授权重跑（选「首跑新批」）。本节纠正 §2/§4 的悲观结论。

- **重跑前探测**：我这个 shell 的 `OPENCODE_SECRET_ANTHROPIC_APIKEY` 仍不可见、`~/.opencode_token` 不存在、profile 零命中。但**直接拉起后 token 实际已通**——证明 opencode 子进程有独立 auth 通路（非仅靠本 shell env）。§2「env 唯一通路」判断不准确，**以本节重跑结果为准**（用户侧已在某层修好凭证，机制未究）。
- **新批句柄**：`batch_id=20260720-145235-3b8963`，worktree `cann-bench-batch/20260720_225222/`，日志 `logs/batch_20260720_225222.log`，5 算子 level2 全派发，卡数 8。
- **硬指标体检**（spawn 后 ~245s）：5 算子 requirement transcript 全部 68–78KB / 7–8 turn / **无 401**，且**全部产出 `requirement.json`（10–15KB）**——与上一批 2225 字节/2 turn/401 天壤之别。
- **requirement stage** 进入正常迭代（部分算子 iteration 2/10 补 `unclear_items`，非 401 死循环）。
- **观察项（warning 级，非阻塞）**：advance_step_v2 spec 解析大量 `OperatorSpec.from_dict: inputs/outputs entry '...' has role=None / no shape; routing it to attrs instead of tensors`——算子 spec 质量/解析逻辑告警，持续观察是否影响下游。
- **后续**：持续监控全流程 stage（general-design / 详设 / codegen / precision / cannbench_adapt / eval / perf），按用户授权只记录问题、不干预 agent 执行；流程性小问题尝试救援，agent/方案问题不救援。

## 8. 后续异常：design 阶段 5 算子集体卡死（opencode serve 层，非网关）

> requirement 全过后（§7），批跑进入 design 阶段即集体卡死。本节为监控中诚实记录的发现。

- **全貌（5 算子全卡 design 子 stage iteration 1，~23:22 诊断时已僵 15–27min）**：
  - scatter / aggregate / multi_add → 卡 `general-design-generator`（22:55 起 27min）
  - manifold → 卡 `design-review`（23:01 起 21min）
  - advance → 卡 `template-division` 后的 `split`（23:07 起 15min）
- **卡死特征**：design agent 的 `session.json` 已创建（90B，`blocks=[]`），但**第一个 turn 从未发起**（无 turn1 transcript 落盘）。5 个 opencode serve 进程全 `wchan=epoll`、**CPU 时间 4s 间隔零增长**、`ss` 无到网关连接——在空等一个不会来的事件。
- **排除网关**：`192.168.0.212:3000` TCP 通、HTTP `/v1/models` 无 auth 秒回 401、**带 auth 秒回 200（3.5ms）**——网关健康、token 有效、响应极快。**非网关问题**。
- **排除脚本/framework**：`ascendc-devkit run` 主进程活、错误/WARN 扫描计数 0、requirement 5/5 正常完成证明编排与 stage 机制正常。
- **关键对比**：requirement-analyst（第一波，时间错开）全部正常 spawn→turn1→turn2→产出 `requirement.json`；design 类 agent（design-generator/split/design-reviewer，第二波，5 并发）session 建后集体卡死。差异在 **agent 类型 + 并发波次**。
- **诊断受限**：opencode serve 的 stderr/stdout → `/dev/null`（框架启动 opencode serve 时丢弃输出），无 opencode 内部日志可查 design 卡死的具体卡点（skill 加载 / MCP 调用 / 并发争用 / opencode 自身 bug 均有可能）。design-generator agent 定义本身无明显异常（`mode=primary`，prompt 正常）。
- **定性**：agent 执行层（**opencode serve**）在 design 阶段并发卡死。属「**agent 执行本身的问题**」，按用户授权**不救援**（不修 opencode、不改框架重启策略、不擅自 kill 重跑）。
- **处置**：批跑已僵——进程活着但 27min 零进展、无 CPU 活动，**不会自恢复**。**未擅自 kill**（kill 重跑属干预 agent 执行，且根因未明、重跑仍会在 design 阶段卡死）。留用户决策（见正文报告）。
- **待用户侧排查方向**（供参考，非我执行）：① 让 opencode serve stderr 落盘后重跑，抓 design 阶段卡死的具体输出；② 复核 design 子 stage 的 5 并发是否触发 opencode 争用（对比降低并发/串行是否复现）；③ design-generator 与 requirement-analyst 的 opencode 启动路径差异。

## 9. 止损处置（用户授权 kill，不重跑）

用户授权「**kill 止损不重跑**」。执行：

- `TaskStop bkrd70q2h`（停 background bash task）+ kill 这批进程：`ascendc-devkit run --batch` 主进程 + 5 个 `opencode serve`（端口 40637/56067/43515/49997/37759）全部清理。
- **最终确认**：✓ 这批零进程残留、✓ 无 opencode serve、✓ 无 ascendc-devkit run、✓ batch_self_evolve.sh 已停。
- **保留进程 930082**：它是 VS Code remote terminal（父 pid 74465 = 终端 bash）拉起的**用户 opencode 会话**（启动 22:50:04，早于批跑 22:52，cwd=项目根），**非本批进程，不动**。
- **现场保留**：worktree `cann-bench-batch/20260720_225222/`、output `output/20260720-145235-3b8963/`（5 个 exec，含 requirement 产物 + 卡死的 design session.json/transcript）、log `logs/batch_20260720_225222.log`。
- ⚠️ **`.batch_id` 未写入**：脚本仅在 batch 正常结束时（末尾 `grep batch_id` 行）写 `.batch_id`，本次未跑完被 kill，故**无续跑句柄**——`RESUME=1` 续跑本批不可用。output 目录仍在，排查现场完整。
- **根因未修**：design 阶段 opencode serve 并发卡死（§8）未解决，**重跑（无论首跑/续跑）仍会在 design 阶段卡死**，需用户先排查 opencode design 卡死根因（§8 三条待排查方向）后再重跑。

## 10. 本轮总结（给用户）

- **做对了什么**：token 401 根因定位（§2）→ 重跑 token 已通、requirement 5/5 全过（§7）→ design 阶段卡死早期发现并完整诊断（§8）→ 按授权 kill 止损、保留现场（§9）。全程只记录/诊断，未越权改 opencode/框架/方案。
- **两个真实问题（均 agent 执行层，未救援）**：
  1. 上一批 token 401（§1–§6）——凭证从未配进运行环境，重跑时用户侧已修通。
  2. 本批 design 阶段 opencode serve 并发卡死（§8）——根因待用户排查（opencode stderr 被 /dev/null 吞，需先让 stderr 落盘）。
- **下一步建议（用户侧）**：先让 opencode serve stderr 落盘（改框架启动 opencode 时的 stdout/stderr 重定向），小规模（1–2 算子）重跑复现 design 卡死，抓 opencode 内部输出定位根因；定位后再恢复 5 算子并发批跑。

## 11. design 阶段卡死根因分析（用户要求深挖，2026-07-20）

> §8 定性为「opencode serve design 阶段卡死」但未深入。本节是用户要求的根因深挖。

### 结论

`ascendc-design-generator` 是 opencode **primary mode** agent。opencode 的 primary agent 会启动并连接配置的 `engine` MCP server（`ascendc_devkit.capabilities.engine_mcp_stdio`，stdio 类型）；**该 MCP 的启动/握手在 primary 并发 spawn 下 hang**，primary agent 的 `POST /session/:id/message` 永不返回；framework `message_timeout=3600s`（1h），故批跑僵死 27min 仍在等、不报错。subagent mode 不连 MCP，全部正常。

### 证据链

1. **5/5 算子全卡 `ascendc-design-generator`**，无一例外（events.jsonl：9c0159/e6e5ed/3bfefd/e376b2/8c265b 最后未完成 spawn 的 agent 全是 design-generator）。
2. subagent（requirement-analyst、design-reviewer）**全部正常**，5 并发也正常。
3. 卡在 `POST /session/:id/message`（blocking），session 已创建成功（session.json + agent_session 日志）。
4. opencode serve `epoll` 空转、**CPU 4s 间隔零增长**、`ss` **无网关连接** → 没到 LLM 调用，卡在 opencode 内部。
5. `message_timeout=3600.0`（1h）→ 27min 仍在等、没超时（opencode_backend.py:108）。
6. design-generator vs requirement-analyst **唯一一致差异 = opencode `mode`**（primary vs subagent）；两者都传 primary_skill、skill steer 仅 ~80 字节、skill 体积也不是因（advance 卡 11KB tiling-split、manifold 卡 6.7KB template-division，比 requirement 的 20KB 还小照样卡）。
7. opencode-config 顶层挂 `engine` MCP（`ascendc_devkit.capabilities.engine_mcp_stdio`，`enabled:true`）；opencode 的 **primary agent 加载 MCP、subagent 默认不加载**（opencode primary/subagent MCP 访问模型）。

### 三个"为什么"

- **requirement 5 并发不卡、design 5 并发卡**：并发数相同，差异在 mode→MCP（subagent 不连 engine MCP；primary 连）。
- **5 个 primary 全卡（非个别）**：5 个 design-generator 各自 primary，各自 spawn 时 opencode 各启一个 engine MCP（stdio per-spawn），5 个并发握手都 hang。
- **第一轮定位不到**：`opencode_backend.py:863-864` `_start_serve` `stdout=DEVNULL, stderr=DEVNULL`——framework 吞掉 opencode serve + engine MCP 全部输出，卡死零诊断信号（违反 §1.2 可诊断性）。

### 关键代码位置

- `src/ascendc_devkit/capabilities/agent/opencode_backend.py:255-257`（blocking message POST，`timeout=self._message_timeout`）
- `src/ascendc_devkit/capabilities/agent/opencode_backend.py:108`（`message_timeout: float = 3600.0`）
- `src/ascendc_devkit/capabilities/agent/opencode_backend.py:215-226`（primary_skill → system steer，仅 primary 路径带 `body["system"]`；但 requirement 也传 primary_skill，故非差异点）
- `src/ascendc_devkit/capabilities/agent/opencode_backend.py:857-864`（`_start_serve`：DEVNULL 吞输出 ← 诊断盲点）
- `src/ascendc_devkit/capabilities/engine_mcp_stdio.py`（engine MCP server，疑似握手 hang 处）
- opencode-config.json：`agent.ascendc-design-generator.mode=primary`、顶层 `mcp.engine.enabled=true`

### 确切卡点（待实测，不改判断方向）

"primary + engine MCP 握手 hang"高度可信；具体 hang 位置（`engine_mcp_stdio` 初始化 hang / opencode↔MCP stdio 通信死锁 / 并发 5 实例争用）需 stderr 落盘后实测：改 `_start_serve` stderr→文件 + 单 design-generator 复现，看 opencode/MCP stderr。

### 性质 + framework 侧可缓解点

- 根因在 opencode/MCP 层（agent 执行），按 §external-infra-not-framework-responsibility 不归 framework 修。
- framework 两个该补的诊断/止损点：① **stderr 落盘**（DEVNULL→文件，§1.2，当前最该补）；② **message timeout/keepalive**（1h→加 keepalive 或缩短 + 明确报错，避免卡死空等 1h）。
