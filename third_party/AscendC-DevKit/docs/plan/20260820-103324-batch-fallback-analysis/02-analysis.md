# L3 方案分析：批跑兜底重试失效 — 根因归属与改进方向

> 本文件回答"有哪些选项、选了哪个、为什么"。证据见 `01-problems.md`。

## 一、责任划分：模型能力 vs 工程缺陷

**结论先行**：三个算子的失败都是**模型能力问题为主**（路径幻觉 + thinking 空转），但**兜底重试确实在工程上有三处失效点**——即使模型能力不变，这三处修复后能显著提高兜底成功率。

| 现象 | 责任 | 理由 |
|------|------|------|
| 写孤儿目录（丢 `103324-` 前缀） | **模型** | session directory 全对、cwd 正确、纠正反馈已注入仍不遵守 |
| 巨量 thinking 不产出 | **模型** | 11 万字符 thinking，turn 耗尽仍零落盘 |
| 收到纠正反馈仍写错 | **模型为主** | 反馈内容正确、正确路径明确 |
| 兜底重试"空转耗尽" | **工程** | 下述三处失效点 |

## 二、兜底重试失效的工程根因（对应问题文件）

> 完整问题清单见 `01-problems.md`（F1-F11 各一份独立文档）。此处只列与本方案相关的核心失效点。

### 失效点 A：孤儿产物对框架不可见，契约永远不满足（F1/F2/F7）

`_scan_working_dir` 只扫 working_dir。agent 写错目录后，框架永远看不到产物，只能靠"重试 + 反馈"指望 LLM 自觉，直到预算耗尽（F1）。

**关键观察**：框架其实**已经知道**孤儿产物的确切路径——`_harvest_relocation_evidence` 从 transcript 提取了 Write 证据，反馈里能写出 `actual_path`，并设置了 `state.pending_relocation=RelocationEvidence(stage_name, filename, wd, actual_path)`。但**这份证据只用于注入反馈，没有反哺产物收集**（F2）。收集与定位两套逻辑不共享证据（F7）。

### 失效点 B：非交互 batch 下 pending_relocation 自动选 KEEP（不搬）（F3）

`design_substages.py:292-300`：检测到 pending_relocation 时 `actions()` 返回 AskUserQuestion（MOVE/KEEP），`default_index=0` = KEEP（安全项：不搬）。`runner.py:1066-1072` 非交互（on_decision=default）自动选 default_index → **KEEP**（F3）。

后果：batch 下框架**明知文件在 `actual_path`，却选择不搬**，重 spawn 让 LLM 自己重写。模型能力差时这就是死循环。

### 失效点 C：同一 session 无限 resume，thinking 泥潭放大（F4）

silent-cut 后 `_clear_session_sidecar` 不执行（cut 保留 sidecar 作 resume 句柄），下次 spawn 自动 resume 同一 session。模型在同一上下文里重复 thinking，状态不重置。d8d4d9 requirement 连 resume 3 次，rms_norm design 连 resume 1 次。

**注意**：`_resume_attempts` 退化 spawn 机制存在（opencode_backend.py:545-575），但它的触发条件需要 `resume_fails` 计数，而 silent-cut 的 resume 成功后计数会**重置**（`_resume_fails` 只在 resume 失败时累计）。silent-cut→resume→silent-cut→resume 这种"每次 resume 都成功完成一次 cut"的循环，`resume_fails` 不增长，永远不触发退化（F4）。

## 三、改进方向（候选，按优先级）

### 方案 1（推荐）：孤儿产物自动回收 + 反哺收集

框架已通过 `_harvest_relocation_evidence` 拿到 `actual_path`。改进：
- 契约检查时，若 pending_relocation 有证据，**自动搬回**（构造性证明文件存在，搬回即可通过解析），而非只注入反馈。
- `_scan_working_dir` 增强：扫描时若发现 wd 外同 run 的已知产物，纳入收集。
- 非交互 batch 下 MOVE 应作为默认（框架已证明产物存在，搬回是确定性修复，不是猜测），仅交互模式保留 MOVE/KEEP 询问。

**四把尺子**：
- 可维护：复用既有 `RelocationEvidence`，不新增概念。
- 可扩展：所有写错目录的场景自动归位，不靠 LLM 自觉。
- 可诊断：搬回动作记日志（moved from→to），保留可观测性。
- 架构合理：落在 design_substages（已持有证据）与 _shared（收集）边界。
- 风险：需防"搬错"（actual_path 非本 run 产物）。校验：actual_path 必须是本 run 目录下（含 batch 前缀）的文件，且文件名匹配契约。

### 方案 2：silent-cut 连续 resume 达到阈值后强制 fresh

区分"resume 成功推进"与"resume 后又 cut"。silent-cut 的 resume 应计一次"无效 resume"，累计达到阈值（如 2）后强制 fresh（清 sidecar + 新 session + 全量 prompt），而不是无限 resume。

- 现有 `_resume_attempts` 只计 resume 失败；需新增"resume 后仍 cut"的计数路径。
- 可维护：复用 resume_fails 语义，改为"resume 后未推进即 +1"。
- 风险：可能牺牲部分上下文连续性；但 thinking 泥潭下 fresh 是更优解。

### 方案 3：empty_artifacts 语义统一（F5）

codegen 把 empty_artifacts 当连续失败（3 次熔断），runner 把它当 ok。应统一为业务语义：
- "该 stage 必须有产物"（codegen/design/tiling）→ empty_artifacts 是失败。
- "可能无产物的 stage"（某些 continue 类）→ 保持 ok。
- 判据用 stage 的 `output_contract.provides` 是否非空（有 provides 却 empty → 失败），而非 status 字面量。

**但注意**：codegen 熔断 3 次即 halt 是**合理设计**（防止无限烧 token）；真正的改进是让前 2 次重试**有效**（方案 1/2 已覆盖），而非延长熔断阈值。

### 方案 4：d8d4d9 requirement 成功却记 failed（F6）

这个是 stage_status 判定在 cut 场景下的边界问题。实际影响有限（fail_strategy=continue，成功产物已进入 state 并被下游消费），但 events 记录不诚实。改进：stage_complete status 判定时应以**最终 state 是否满足契约**为准（契约满足即 ok），而非只看最后一次 agent_status。

## 四、结论

兜底重试**并非完全失效**——框架正确地检测到了孤儿产物、正确地注入了纠正反馈、正确地触发了熔断防止无限烧 token。**失效的是"重试能否真正修复问题"**：

1. 框架已知产物位置却不搬回（方案 1）→ 重试依赖 LLM 自觉，模型差时必失败。
2. resume 放大 thinking 泥潭（方案 2）→ 重试在同一上下文空转。
3. empty_artifacts 语义冲突（方案 3）→ 判定与意图不一致。

其中**方案 1 是成本最低、确定性最强的改进**：框架已有 `actual_path` 证据，自动搬回是构造性修复，不依赖模型能力。
