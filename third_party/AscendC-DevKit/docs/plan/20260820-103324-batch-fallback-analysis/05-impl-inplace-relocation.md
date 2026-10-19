# L4 实施方案：孤儿产物全局收口（就地搬回 + 检测统一 + 全消费方接入）

> 对应问题：F3（非交互 batch 下 pending_relocation 自动选 KEEP 不搬回）为直接靶点；本方案
> 按"问题类"定范围升级为**孤儿产物（agent 产物写在其定位根之外）的全局一次性收口**——
> 用户明确要求："方案要尽量是全局解决方案，不要每次都打补丁或散弹式修改"。
> 前置：commit `4a066149`（F1 方案 A+B）落地了"自动搬回分支 + cwd prompt 注入"，但保留了
> pending_relocation/AskUserQuestion 状态机作为独立通路（§2.5 违例的过渡态）；F2 又把检测
> helper 复制成两份。本方案一次收干净。
> 用户决策（2026-08-20/21 确认）：选方案 D；**搬回动作必须在日志上有呈现**（run.log WARN
> + events.jsonl 事件双通道）；precision-debug 纳入全局方案（豁免撤回）。

## 〇、全局架构与覆盖矩阵

**问题类定义**：agent 产物写到其框架定位根（working_dir / debug_artifacts_dir / op_dir）
之外。四层结构，每层全局唯一：

```
预防层   prompt 注入定位根绝对路径          —— 统一文案源（design `_output_boundary` /
                                          codegen repo_rules / precision prompt 已各有，
                                          实施时核对共用一个表述模板，不强制合并函数）
检测层   transcript → 孤儿证据             —— 唯一权威源 capabilities/agent/_shared.py
处置层   一个恢复函数 + 一个事件类型        —— 防御性搬回 recover_orphan_artifact()
                                          （新文件 orchestration/artifact_recovery.py，
                                          与既有 design_artifacts.py 同层同粒度先例）+
                                          events.jsonl artifact_relocated 事件
策略层   按资产性质分派（显式枚举，非隐式）：
          小 JSON 单产物 → 搬回 + 同轮继续解析（就地自愈）
          代码树        → 路径反馈 + 重生成（F2 已落地，codegen）
```

**覆盖矩阵**（每个从磁盘定位 agent 产物的消费方，要么接入、要么不适用——无豁免行）：

| 消费方 | 产物 | 定位机制 | 孤儿策略 | 本次动作 |
|---|---|---|---|---|
| design 子阶段 ×7（general/tiling×2/synthesize/docgen/dd-intake/template-division） | 小 JSON | `_read_disk_artifacts` locate | 搬回 + 同轮自愈 | 改造收口（改动点 1-4） |
| test-design 子阶段 ×3 | JSON + CSV/report | 继承 `_read_disk_artifacts` + 自有 `_locate_csv`/`_locate_report` | 同 design | **补线**：`_locate_csv`/`_locate_report` 失败点接恢复函数（当前盲区） |
| requirement | requirement.json | 实施时核实（盘读 wd / agent dict） | 小文件同 design | **核实 + 补线**：盘读则接同一收口点；agent-dict 模式则顺手收口到盘读 + 恢复函数（design P62 已判 agent-dict 旁路非法并废除，同构处理） |
| codegen | op_dir 代码树 | manifest/deployer | 路径反馈 + 重生成（用户已拍板，2026-08-20） | 已落地（daaf5ef8），仅 import 切到统一检测源 |
| precision-debug | control.json（路由命脉） | `_load_control` | 搬回（小 JSON 同性质） | **接入**（改动点 7；豁免经核实撤回——详见下） |
| precision-debug phase json | precision_*.json | `_phase_path` + stale 检测 | 单 phase 重试（已有 stale 检测兜底） | 不接（代价可控；同一恢复函数加一行即可，若实测出现再接，不留债） |
| verify/perf/smoke/finalize/cannbench 等 | 不从 wd 定位 LLM 产物 | — | 不适用 | 无动作 |

**同类新情况自动归位**（§1.2 可扩展）：新增小文件 stage → import 恢复函数一行接入；新增
代码树 stage → 照 codegen 模式接同一检测 API。矩阵做完即闭类，无第三种路径。

## 一、方案对比结论（L3 摘要）

| 候选 | 形态 | 裁决 |
|---|---|---|
| B | 发问 + default=MOVE + 删方案A分支 | 合规次选；保留决策点但每孤儿多烧一轮预算（tiling=2/dd-intake=1 场景致命） |
| C | 非交互 NoOp 载体触发搬回 | **撤回**：被 B/D 双支配（双通路 + stage_skipped 事件语义失真） |
| **D** | **证据在手就地搬，删整套提问机制** | **采纳**：四把尺子唯一满分 |

D 的核心洞察：证据在失败那一轮的 transition 里就已到手（`_missing_artifact_error` 收证时），
不需要推迟到下一轮。locate 失败 → 收证 → 就地搬回 → 重新 locate → 继续解析，同一轮内自愈，
孤儿成本从 +1 轮降为 **0**。

### D 相对现状/候选的原则符合性

| 原则 | 体现 |
|---|---|
| §2.5 唯一通路 | 方案 A 分支（:809）与 decision 分支（:854）并存正是"新旧并存"过渡态；D 连根删：字段、类、两分支、actions 门、相关测试 |
| §2.9 构造性保证/原地修改 | 失败点自愈，"谁发现谁改、只改那一处"，不绕决策路由回炉 |
| §1.14 最小结构 | 删「控模型」结构：跨迭代 sticky 状态机是既有 bug 源（stale evidence 需显式清） |
| §1.4 不向后兼容 | 要么彻底改要么不改；retired key 在 from_snapshot strip 一次，不留 alias |
| §1.1 Event Sourcing | 搬回落 events.jsonl（新 `artifact_relocated` 事件），运行历史权威记录完整 |
| §1.3 可诊断 | WARN 即真相；消灭"auto-KEEP 后又搬了"的日志谎言 |

### 现状残留的三个问题（本方案全消）

- a **日志撒谎**：非交互下 runner 先记 auto-KEEP（default_index=0），transition 的方案 A 分支无视决策照搬——事后读日志会得出与事实相反的结论。
- b **双通路死代码**：decision MOVE/KEEP 分支（:854-863）在非交互下永不可达。
- c **abort+resume 语义 bug**：`on_decision=abort` 的 run 暂停等人响应、人答了 KEEP、resume 重放后，方案 A 分支（只看 `non_interactive`，不感知 on_decision）仍先把文件搬走——**人的 KEEP 被静默推翻**。
- d（附加收益）非 TTY 交互盲区（EOFError → KEEP → 真不搬）随提问机制一起消失。

## 二、改动点

> 结构：改动点 1-4 是 F3 收口（§2.5 删旧通路 + 就地搬回）；改动点 5 是检测层统一
> （消除 F1/F2 遗留的双份拷贝）；改动点 6-7 是全消费方接入（矩阵行逐行勾销）。
> **处置层恢复函数**（`orchestration/artifact_recovery.py::recover_orphan_artifact`）是
> 改动点 2/6/7 的共同依赖：签名 `(transcript, filename, wd, state, stage_name) -> bool`
> （True=搬回成功可继续 locate），内部封装四重约束 + 防御性 move + WARN + 事件发射。
> 方案 A 分支（:809-853）的防御逻辑**迁移进该函数**（不重写），原分支删除。

### 改动点 1：`_missing_artifact_error` 收证即搬（核心）

`design_substages.py` `_missing_artifact_error`（:700-749）。当前：证据成立 → 组 msg、
设 `pending_relocation`、返回 error state。改为：**证据成立 → 先执行防御性搬回 → 搬回成功
则返回不带 relocate 语义的正常 error（重新 locate 会成功）**。

关键机制衔接：`_missing_artifact_error` 的调用方在 `_read_disk_artifacts` 的 locate 失败
路径（:875-885）。搬回必须发生在**返回 error 之前**、且返回后调用方要能**重新 locate 成功**。
两条实现路径：

- **1a（推荐）**：搬回逻辑放 `_read_disk_artifacts` 的 locate 失败处（:875-885），收证成功
  → 就地搬回 → **重新 locate 一次**（`_locate_artifact(wd, fn)`），成功则继续正常解析流，
  失败才走 `_missing_artifact_error`。好处：单点收口（与成功路径 stray sweep :907 同位置
  对称），`_missing_artifact_error` 保持"纯错误构造"职责。
- 1b：搬回放 `_missing_artifact_error` 内部，返回特殊标记让调用方重 locate。缺点：错误
  构造函数产生副作用（搬文件），职责混杂。

**采纳 1a**。`_missing_artifact_error` 相应简化：不再写 `pending_relocation`（字段删除后
也不存在了），证据成立的分支改为只组"写错目录"的明确 msg（教育性文案保留——agent 下轮
看到路径级纠正；虽然搬回后多数情况本轮已成功，msg 只在搬回失败时出现）。

### 改动点 2：防御性搬回（沿用既有四重约束 + move 防御）

搬回前置条件（全部沿用，不改判据）：
1. 文件名匹配产物契约（required/optional 列表内）
2. transcript 证据证明本次 agent 所写（`_harvest_relocation_evidence_detailed`）
3. 路径在 wd 之外
4. 同 batch（`_batch_dir_anchor` 双侧可解析且相同才放行跨 run 拒绝语义——即：能明确判定
   不同则拒，任一 None 放行）

move 防御（从方案 A 分支原样移植，不重写）：
- target 不存在 → `shutil.move`，WARN + **events.jsonl 事件**
- target 存在且 samefile → 幂等跳过，落回解析
- target 存在且不同文件 → 拒绝覆盖，WARN + 清理走 missing（既有语义）
- 证据文件已不存在 → WARN + 走 missing

### 改动点 3：搬回的日志呈现（用户明确要求）

双通道：

1. **run.log**：既有 `Logger.warn` 模式保留（"[{stage}] 搬回孤儿产物 {from} → {to}"）。
2. **events.jsonl**：新增 `artifact_relocated` 事件构造器（`kernel/event.py`）：

```python
def artifact_relocated(stage_name: str, filename: str,
                       from_path: str, to_path: str, outcome: str) -> dict:
    """Emitted when a design substage relocates a transcript-evidenced orphan
    product back into its working_dir (artifact-location-provenance, in-place
    deterministic repair — same-iteration self-heal). outcome ∈ {"moved",
    "idempotent_skip", "refused_target_exists", "refused_cross_batch",
    "orphan_gone"} so the operator can audit every relocation from events.jsonl
    without opening run.log."""
    return make_event("artifact_relocated", stage=stage_name,
                      filename=filename, from_path=from_path,
                      to_path=to_path, outcome=outcome)
```

**发射点与所有权**：events.jsonl 由 runner 的 `EventLog`（线程安全 append）持有，
stage 层不持有 runner 引用。但 `state._workspace.events_path` 可达（`workspace.py:125`），
且既有先例：dispatcher 直接 `EventLog(workspace.events_path)` 或 append。采用**共享实例
追加**（20260821 加固后定稿）：搬回点经 `EventLog.for_path(state._workspace.events_path)`
（进程级 per-path 共享，与 runner 同锁串行化）append
`evt.artifact_relocated(...)`——不依赖 O_APPEND 原子性，不引入 stage→runner
反向依赖（§1.1 L3 不依赖 L4）。workspace 不可达（State.empty()/UT）→ 只 WARN 跳过事件，
不炸主流程（可诊断降级，非静默——WARN 本身就是信号）。

### 改动点 4：删除清单（§2.5 收口）

| 位置 | 删除内容 |
|---|---|
| `kernel/state.py` | `RelocationEvidence` 类（:41-49）、`pending_relocation` 字段（:355）、`from_snapshot` 的 retired-key strip（新增 `data.pop("pending_relocation", None)`，防旧快照 resume 崩——e9ed199e 同款教训） |
| `design_substages.py` | `_RELOCATE_KEEP`/`_RELOCATE_MOVE` 常量（:101-102）、actions() 的 pending_relocation 门（:344-357）、`_read_disk_artifacts` 的方案 A 自动搬回分支（:809-853）与 decision 分支（:854-863）、`_missing_artifact_error` 的 pending_relocation 写入、tiling transition/integrate 成功出口的 `pending_relocation=None` 清理（:971/:986/:2101——字段没了自动消失，显式引用需删） |
| `kernel/runner.py` | 无（decision 重放逻辑通用，其他 AskUserQuestion 仍用） |

注：`AskUserQuestion` action 类型本身保留——requirement/base.py 的审查提问仍用（那是真实
交互决策点：approve/revise/abort）。只删 relocation 这一个用途。

### 改动点 5：检测层统一（收编 design_substages 本地副本，单一权威源）

F2 实施时把 `design_substages` 的两个 helper **复制**到 `_shared.py`（docstring 自述
"Mirrors ... shared copy"）——两份拷贝靠人肉同步，且 design_substages 本就 import
`_shared`（`is_infra_error_type`），复制无任何架构理由（§1.2 规避方案）。收编：

- `_shared.py` 成为孤儿检测的**唯一权威源**：`_extract_write_target_shared`、
  `_batch_dir_anchor_shared`、`_harvest_relocation_evidence`（从 design_substages
  迁入，含 detailed 变体）、`_transcript_orphan_paths`（F2 已在此）。
- `design_substages.py` 删本地 `_extract_write_target` / `_batch_dir_anchor` /
  `_harvest_relocation_evidence(_detailed)`，改 import `_shared` 版本。
- `codegen.py` 已 import `_shared`（F2 就位），不动。
- 检测 API 语义对齐：`_harvest_relocation_evidence_detailed`（单文件 + 拒绝原因）与
  `_transcript_orphan_paths`（全量孤儿清单）是同层两个视图，共享底层解析，不再各自维护。

### 改动点 6：precision-debug 接入（control.json，豁免撤回）

**豁免为何撤回**（2026-08-21 核实）：原豁免理由"FW 不门禁其产物"仍成立，但检测+恢复不是
门禁，是基础设施。现状行为链（已逐行核实）：

```
_load_control: 不存在/读不了 → {}               (precision_debug_substages.py:236)
  → run_tests transition: summary 同样读不到 → abort 分支（rounds+1、history 记
    "aborted"、run_iter_counter+1）→ resolve_condition 继续循环 re-spawn
  → 终界: rounds > max_iterations(30) / time_budget(10h)
```

fail-open 有界重试方向正确（不死锁、不空烧无限 token），但**无恢复能力且不可诊断**：
框架手里有 transcript 却不用——`{}` 掩盖了"写错位置"与"没写"的区别；agent 持续路径幻觉时
30 轮 × 全量回归，代价不小；history 只有 "aborted"，事后无法分辨原因。

接入（全部复用全局件，零新机制）：

- **检测**：`_load_control` 返回 `{}` 且 control.json 不存在时，对上一 spawn 的 transcript
  调 `_shared` 检测（`_harvest_relocation_evidence_detailed`，filename="control.json"，
  wd=debug_artifacts_dir）。
- **恢复**：命中 → 同一 `recover_orphan_artifact()` + `artifact_relocated` 事件；搬回后
  `_ensure_control_contract` 照常收口（既有加载期校验复用）。
- **拒搬**：沿用全局判据（target 冲突 / 跨 batch / 文件没了）→ WARN 落回现有 abort-retry
  循环（行为=现状，但 WARN 说明原因——可诊断补齐）。
- **phase json 不接**：走 `_phase_path` 归档 + stale 检测重试，错位只烧单 phase 且有既有
  兜底；同一恢复函数加一行即可接入，实测出现再接，不预支。

### 改动点 7：requirement / test-design 补线（盲区清零）

- **test-design**：`_locate_csv`/`_locate_report`（test_design_substages.py:211/224）失败
  时接 `recover_orphan_artifact()`——CSV/report 属小产物，与 design 同性质。JSON 部分继承
  `_read_disk_artifacts` 自动获得。
- **requirement**：实施时核实 requirement.json 读取路径（盘读 wd 还是 agent dict 透传）。
  盘读 → locate 失败点接同一恢复函数；agent-dict → 收口到盘读 + 恢复函数（design P62 判
  agent-dict 旁路非法的同构处理，顺带消灭最后一个旁路）。

### 改动点 8：prompt 侧不动

方案 B（cwd 绝对路径注入，`_output_boundary`）保留——源头降路径幻觉概率与就地搬回兜底
互补，不冲突。

## 三、控制流对比

**改前（方案 A 后现状）**：
```
iter N:   agent 写孤儿 → locate 失败 → 收证 → pending_relocation + error
iter N+1: actions() 问 MOVE/KEEP → runner auto-KEEP → transition:
          方案A分支(non_interactive) 无视决策照搬 → 解析继续
```
（日志显示 KEEP、实际搬了——撒谎；交互模式走 decision 分支；abort+resume 有 KEEP 被推翻 bug）

**改后（D）**：
```
iter N:   agent 写孤儿 → locate 失败 → 收证 → 防御性搬回 → 重新 locate →
          成功 → 继续解析（同轮自愈，孤儿成本 0）
          搬回被拒（target 冲突/跨batch/文件没了）→ _missing_artifact_error →
          正常重试（预算消耗与改前一致）
```

## 四、验证方案（TDD：先改测试）

### 删除/改写的测试（test_design_substages.py）

| 类 | 处置 |
|---|---|
| `TestRelocationGate`（:1278，3 用例） | **删**——门没了 |
| `TestRelocationAutoMove`（:1707，6 用例） | **改写**为 `TestInplaceRelocation`：同一批场景（非交互搬回成功/missing 清证据→现为纯 missing/跨batch拒搬/target 冲突拒覆盖/samefile 幂等），但驱动方式改为"locate 失败 + transcript 证据"路径（构造真实孤儿文件 + transcript，走 `_read_disk_artifacts`，断言同轮 raw 读回 + 事件落盘） |
| `TestTilingStagePendingRelocationCleared`（:1386） | **删**——字段没了 |
| :468/:499 两个 sticky-clear 断言里的 `pending_relocation` 构造 | **删引用**——`last_error` 清理断言保留（P5 语义不变） |
| `TestRelocationEvidenceDetailed`（:1871） | **保留**——`_harvest_relocation_evidence_detailed` 仍是被消费的判据函数 |
| `TestHarvestRelocationEvidence`（:1036） | **保留**——同上 |
| `TestOutputBoundary*` | **保留**——改动点 5 不动 |

### 新增测试

1. **同轮自愈**：孤儿 + transcript 证据 → `_read_disk_artifacts` 一次调用返回 raw（非
   error），文件已在 wd，孤儿原位置消失。
2. **事件呈现**：同上场景，断言 `events.jsonl` 含 `artifact_relocated` 事件（type、
   from/to、outcome=moved）——用户核心要求。
3. **事件降级**：workspace 不可达 → 不炸，WARN 有、事件无。
4. **交互模式同样搬**：non_interactive=False 时孤儿照样同轮自愈（决策点已删，行为统一）。
5. **多 required 文件部分孤儿**：第一个 locate 成功、第二个孤儿 → 只搬第二个，第一个不
   重复读。
6. **搬回后解析失败走 schema_violation**：孤儿内容坏 → 搬回成功但 parse 挂 → 正常
   schema_violation 重试（不因搬回引入新 halt）。
7. **旧快照 resume**：`from_snapshot` 对含 `pending_relocation` 的 dict 不崩（strip 生效）。
8. **precision-debug control.json**：孤儿 control.json + transcript 证据 → `_load_control`
   读回非空、文件在 debug_artifacts_dir、事件落盘；拒搬场景（target 冲突）→ 返回 {}
   与现状一致 + WARN。
9. **test-design CSV**：`_locate_csv` 失败 + 证据 → 搬回后 locate 成功。
10. **恢复函数单元**：`recover_orphan_artifact` 四种 outcome（moved/idempotent_skip/
    refused/orphan_gone）各自断言。

### 回归

- `tests/ut/orchestration/test_design_substages.py` 全量
- `tests/ut/orchestration/`（runner/state/precision_debug_substages/test_design_substages 联动）
- `tests/ut/capabilities/`（检测层迁移后）
- 全量 UT `--quick`

### 验证补充（改动点 5：检测层统一）

- 收编后 `_shared.py` 单一权威源，design_substages 的既有
  `TestHarvestRelocationEvidence`/`TestRelocationEvidenceDetailed` 用例**迁移**到
  `tests/ut/capabilities/test_agent_shared.py`（或就近既有 `_shared` 测试文件），import
  路径改为 `_shared`——行为断言不变，只有产权搬家。
- `grep -rn "_extract_write_target\|_batch_dir_anchor"` 确认仓内只剩 `_shared.py` 一处
  定义（design_substages 只剩 import 行）。

## 五、风险与边界

- **交互用户失去"强制重生成"选择**：决策点删除后，任何模式都自动搬。已在 L3 论证：搬回后
  照走 parse/validate，内容坏照样重试；先例（stray sweep 自动删）已越过此线。
- **from_snapshot 兼容**：一次性 strip（§1.4 明确允许的"加载期 drop"），旧快照 resume 不崩。
- **EventLog 跨写者串行化（20260821 已加固）**：初版用短生命周期 `EventLog(path)`
  实例，依赖 O_APPEND 单写原子性防撕行（工程判断非构造性保证）。加固为
  `EventLog.for_path(path)`——进程级共享实例（per resolved path），runner 与
  artifact_recovery 两个写者串行化在显式锁上。同路径写者全部走 `for_path`；
  私有日志直接构造仍合法。无副作用（`_shared` dict 每 path 一条、几十字节）。
- **heavy_llm 统一补验（用户决策 2026-08-21）**：本次不跑；F3-F11 全部解决后
  统一补端到端 heavy_llm（真实 agent 写错位置→恢复），届时覆盖三个新接入点
  （requirement/test-design/precision-debug）+ design 同轮自愈。
- **precision-debug transcript 可达性**：`_load_control` 读的是磁盘 control.json，上一
  spawn 的 transcript 路径需从 `_debug_checkpoint`/spawn 记录取——实施时核实拿法；拿不到
  → 行为退化为现状（{} + retry），不比现状差。
- **分层归属**：`artifact_recovery.py` 放 orchestration（处置属编排职责，搬回决策要
  stage 语境）；检测留 capabilities/agent/_shared（transcript 解析属 agent 层）。依赖方向
  orchestration → capabilities，合法。
