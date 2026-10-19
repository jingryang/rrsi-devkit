# 19 — resume 强杀续跑：方案分析（L3）

> 工作线：step-16（覆盖问题 P29）
> 状态：**拍板冻结**（2026-07-04）
> 关联 L1：`06-problems.md` P29；L4：`20-resume-hardkill-impl.md`

## 问题复述（详见 L1 P29）

强杀（SIGKILL / 未捕获 SIGTERM/SIGHUP）后 `--resume <run_id>` 无法从断点续跑，会从头重跑。根因：

- resume 跳过已完成节点的**唯一权威是 `state_snapshot.json` 的 `node_status`**：`_resume_node_status` 仅 `return dict(state.node_status)`。
- snapshot 只在三时机落盘：运行开始前（初始）、整个 workflow 跑完、优雅 SIGINT（`RunnerCancelledError` 分支写 `executor.latest_state`）。运行中逐节点**无任何落盘**——GraphExecutor 在内存随节点完成更新 `node_status`，但只在上述三时机一次性 flush。
- 强杀三时机都到不了 → 内存 `node_status` 丢失 → 磁盘 snapshot 永久停在启动初始态（`node_status: {}`、数据字段全 null）。

## 选项

### A. 逐节点原子 flush state snapshot（**选定**）

GraphExecutor 的 `_execute_node` 是所有节点（atomic 叶子 / sequential group / forkjoin group）的递归汇聚点。在其末尾——每个节点完成（含失败标记、group 聚合）后——回调 flush 当前 state 到 `state_snapshot.json`。`_write_state_snapshot` 改原子写（temp + `os.replace`）。

- 一次 flush 同时持久化 `node_status` 与 `requirement`/`general_design` 等数据字段 → 附带解决 P29「数据字段也 null」、下游 stage 续跑有输入。
- snapshot 在任一时刻都反映「最后一个已完成节点的规范态」；强杀后 resume 跳过已完成、只重跑在途节点。
- SideTask（异步、state 不变）与 resume-skip（无变化）不触发 flush。
- ForkJoin 分支（线程池里跑、局部 state 非规范态）不 flush；只有主 executor 在 `merge_forkjoin` 后由 `_execute_node` 末尾 flush 一次 → 避免线程竞争写同一文件。
- flush 用 try/except 包，失败只 warn 不中断 run（§1.2 可诊断、不掩盖；但也不让持久化 hiccup 崩主流程）。

### B. resume 时从 events.jsonl 重建 node_status（**否决**）

`stage_complete` 事件的 scoped `stage` 字段（runner 用 `stage_label = f"{_scope_prefix}/{stage.name}"` 发射）确实 == `_path` 产出的 node_status key，理论上能重建。但否决：

1. **违反刻意决策**：commit `aa472e3`「make node_status the sole resume authority; drop bridge debt」明确把 node_status（snapshot）定为唯一权威、删掉重建 bridge。重引入 = 推翻该决策。
2. **违反 §2.5（唯一通路，不留旧债）**：会再造第二条 resume 路径（snapshot vs events），需要 reconciliation 逻辑。
3. **fragility 仍在**：当年 bridge 不可靠的根因——`stage_complete` 有两个发射点，取消路径用裸 `stage.name`、正常完成才用 scoped `stage_label`；rebuild 必须过滤取消事件且只取 scoped 路径，否则重蹈「detailed-design `integrate` 子 stage 与 top-level `integrate` 撞名误跳」覆辙。
4. **独有价值有限**：events-rebuild 唯一不能被 A 覆盖的场景是救援**已被强杀的旧 run**（snapshot 已停留在初始态）。但那是一次性的事——重跑或单独手动修即可，不值得为它引入永久第二通路。

EventLog.append 已 `flush()+fdatasync`，events.jsonl 本身耐用，继续作人类可读审计日志（§1），只是不作 resume 输入——与 `aa472e3` 意图一致。

### C. A + B 组合（**否决**）

A 已充分（snapshot 逐节点原子落盘 = 真正耐用的唯一权威）。叠加 B 只引入 B 的复杂度与风险，无额外正确性收益。否决。

## 决策

**选 A：逐节点原子 flush state snapshot。** 让 snapshot 真正耐用、继续作为唯一权威（不引入第二通路、不推翻 `aa472e3`）。

## 适用范围（诚实边界）

- 本修复**前向**：修复后所有新 run 强杀都能续。
- **不救援**已被强杀的旧 run（其 snapshot 已停留在初始态）——如 `20260704-053333-c2911b`，需重跑或单独手动修。
- `os.replace` 的 crash-safety 由 POSIX 原子 rename 语义保证：mid-write 强杀最坏情况是保留上一份完整 snapshot（仍是上一个节点的规范态），绝不会截断/清空。

## 评估（§1.2 四把尺子）

- **可维护**：单一 flush 点（`_execute_node` 末尾），不散落；snapshot 保持唯一权威，无 reconciliation。
- **可扩展**：新增节点类型自动经 `_execute_node` → 自动 flush，无需逐处改。
- **可诊断**：snapshot 始终反映真实前沿；flush 失败 warn 入日志不静默。
- **架构合理**：持久化职责仍归 dispatcher 的 `_write_state_snapshot`（GraphExecutor 只回调），不越层。
