# 多输入算子空 dtype 穿透 — 方案分析（L3）

> 调研中演进、拍板后冻结。本文列选项 + 定性判定 + 取舍 + 理由。
> 事实依据见同目录 `01-problems.md`（L1，产权所在）；本文只引用不重复。

## 问题本质（一句话）

「多输入算子的用例 dtype 只声明一次（广播语义），而消费端没有按上游约定展开/校验」——cann-bench
场景下 DevKit loader 未转写其「单 dtype = 全体共享」约定（P1），产出空串穿透到 precision harness
致 20/20 崩溃（P2）；devkit 场景下同类用例会静默截断输入或静默降级 fp16（P5）。三者同源，但
**定性和处置必须不同**，核心是：dtype 缺失到底是「合法可推理」还是「输入错误」？

## 定性判定准则（先于方案）

> **dtype 缺失是否合法可推理，取决于缺失有没有上游格式显式背书的依据。**
> 有依据 → 合法，该推理（忠实转写）；无依据 → 输入错误，该报错；已存在无依据 → 兜底并告警。

| 情形 | 缺失来源 | 上游依据 | 定性 | 处置 |
|---|---|---|---|---|
| ① cann-bench 单元素 dtype | cases.csv `dtype=["float32"]` + 多输入 | **有**：cann-bench 格式显式定义广播（`cann_loader.py:386-388` 背书） | **合法可推理** | loader 按约定展开（§1.13 忠实转写） |
| ② devkit 契约少填 | testcase_csv `stc_input_dtypes` 短于输入数 | **无**：契约要求逐输入声明（并行数组） | **输入错误**（producer 违约） | 加载期校验报错（§1.3） |
| ③ 旧 state_snapshot 残值 | 历史 loader bug 持久化的空串 | **无**（但已存在） | 无依据存量 | 兜底继承 + WARN，不冒充合法语义 |

**对 `foreach_addcdiv_scalar`（本案）的定性：合法可推理（情形①）**——理由链：
1. 数据源本身合法：`dtype=["float32"]` 是 cann-bench 格式标准写法，非 producer 漏填。
2. 上游显式背书：cann-bench 自家 loader 为「单 dtype + 多输入」写了广播（`cann_loader.py:386-388`）。
3. 语义自洽无歧义：`y = x1 + x2/x3 * scalar` 天然要求三输入同 dtype，广播后每个输入 dtype 唯一确定。
4. 强佐证（P4）：同一份 cases.csv 在 cann-bench 自家消费端合法（eval 路径正常到 kernel）——
   数据没问题，缺陷是 DevKit loader 没转写。
5. 反证：若按「输入错误」报错，会误杀 cann-bench 全部多输入同 dtype 算子（foreach 族/elementwise 族
   cases.csv 均为单 dtype 约定）——显然与上游格式语义相悖。

## 必须守住的不变式（方案不能破的）

1. **合法推理只在有上游依据处进行**：只有 cann-bench 格式背书了「单 dtype=广播」；「继承 input_0」
   这类推理**不得**上升为通用合法规则（多输入算子并非都共享 dtype——`moe_re_routing` 是 int32 索引
   + fp16 数据）。
2. **不在通用层耦合 cann-bench 约定**：广播展开只在 cann-bench adapter 边界（`cann_bench_cases_loader.py`）
   做；通用层（runner/harness）只能用**结构语义**判据（§1.12 同类新算子自动归位）。
3. **输入错误在加载期暴露，不静默吞**：devkit 契约违约应报错（§1.3），不静默截断/静默降级。
4. **存量兜底可带 WARN，但不得冒充合法语义**：旧快照残值防崩即可，且必须留可观测信号。
5. **不耦合具体算子（§1.12）**：所有判据用客观结构信号（dtype 列表长度 vs 输入数、是否空串），
   不认算子名。

## 选项分析（每个过四把尺子 §1.2：可维护 / 可扩展 / 可诊断 / 架构合理）

### 选项 A — loader 广播（cann-bench adapter 边界，合法推理）

**做法**：`cann_bench_cases_loader.parse_cann_bench_csv` 在读取 dtype 后：
- 裸串归一：`isinstance(dtypes, str) → [dtypes]`（cann-bench 允许 dtype 为裸串）；
- 广播：`len(dtypes)==1 且非空输入数>1 → dtypes * 输入数`；
- 结构不齐 WARN：`1 < len(dtypes) < 输入数 → logger.warning(...)`。

| 尺子 | 评估 |
|---|---|
| 可维护 | ✅ 把「单 dtype=全体共享」收敛到唯一 adapter 点，与 `cann_loader._parse_case` 语义对齐 |
| 可扩展 | ✅ 任何「多输入+单 dtype」cann-bench 算子自动归位，无需逐个打补丁 |
| 可诊断 | ✅ 结构性不齐打 WARN，不静默 |
| 架构合理 | ✅ 落在 loader（cann-bench 格式产权层）；§1.13 忠实转写上游事实，非「修正」非「报错」 |

**评估**：主修复。定性为「合法可推理」的唯一正确落点。

### 选项 B — runner/harness 空/缺失 dtype 继承用例声明 dtype + WARN（通用兜底）

**做法**：`runner.py` 烘焙用例时，把 `inp.get("dtype","fp16")` 改为「空串/缺失视同未声明 → 继承用例
首声明 dtype」，触发即 WARN。

| 尺子 | 评估 |
|---|---|
| 可维护 | ⚠️ 修正了「`get` 默认值对空串失效」的隐性坑，但「继承」含猜测成分 |
| 可扩展 | ✅ 覆盖所有 producer（cann-bench 空串 / devkit 缺失 / 旧快照） |
| 可诊断 | ✅ 触发必 WARN（§1.3），不再静默 |
| 架构合理 | ⚠️ 若当通用合法规则则违不变式 1（混合 dtype 算子猜错风险）；只能作「存量兜底」 |

**评估**：不能当主修复（把继承上升为通用规则 = 无依据推理 + 猜错风险）。**保留为存量兜底**（情形③
旧快照残值防崩），且必须 WARN、明确非合法语义。对新数据不承载「继承」——新数据要么被 A 合法展开、
要么被 D 校验挡下。

### 选项 C — csv_to_testcases `n = len(shapes)` 去掉截断，交给下游继承（devkit 宽容）

**做法**：改 `csv_to_testcases.py:93` 的 `min(...)` 为 `len(shapes)`，dtype 不足的输入留空由 B 继承。

**评估**：❌ **否决**。devkit 缺失是**契约违约**（情形②，输入错误），宽容继承会掩盖 producer 错误、
让坏用例溜进 kernel；§1.3 要求加载期校验报错而非运行期静默兜底。原 `min` 的「gracefully degrade」
意图是防 malformed 行，但「dtype 少填」不是 malformed，是违反 schema，应显式暴露。

### 选项 D — csv_to_testcases 契约校验报错（devkit 边界，输入错误）

**做法**：`csv_to_testcases` 解析时校验 `len(dtypes) == 输入数`（tensor 输入），不等 → `ValueError`
带行号/列名/两个计数，让 producer（LLM/skill）修正。

| 尺子 | 评估 |
|---|---|
| 可维护 | ✅ 契约（schema required_keys）本就要求逐输入 dtype，校验使其可执行 |
| 可扩展 | ✅ 任何 producer 少填都显式暴露，同类新情况自动归位 |
| 可诊断 | ✅ 加载期报错，错误信息含行列定位（§1.3） |
| 架构合理 | ✅ 落在 producer 边界（testdesign 适配层），正是校验该在的位置 |

**评估**：情形②的唯一正确处置。注意报错是**逐行**的（单行违约报单行），不连坐整份 CSV。

## 推荐组合（§1.2：正确改动主修复 + 宽容兜底 + 可观测性）

**主修复 = A**（cann-bench loader 广播）：合法推理的唯一正确落点，落在格式产权层，从根上消除
cann-bench 场景的空串穿透（P1→P2），让精度 harness 与 eval 两条链路都拿到合法 dtype。

**契约校验 = D**（csv_to_testcases 报错）：devkit 场景把「输入错误」在加载期显式暴露（§1.3），
替代现状的静默截断（`n=min`）与静默降级（fp16），不掩盖 producer 违约。**C 否决**（宽容继承会
掩盖错误）。

**宽容兜底 = B**（runner 继承 + WARN）：仅对**存量**无依据数据（旧 state_snapshot 空串残值）防崩，
明确不冒充合法语义；新数据经 A/D 后不会带空 dtype 到达 runner。

**可观测性**：
- A 的结构不齐 WARN（`1 < len(dtypes) < 输入数`）；
- B 的继承触发 WARN（带 case+input+继承值）；
- D 的报错信息含行列定位。

**三处职责划分（各守其责）**：

| 层 | 职责 | 定性 |
|---|---|---|
| A：`cann_bench_cases_loader.py` | 广播展开单元素 dtype | 合法推理（忠实转写上游约定） |
| D：`csv_to_testcases.py` | dtype 数 ≠ 输入数 → 加载期校验报错 | 输入错误（producer 违约，§1.3） |
| B：`runner.py` | 存量空/缺失 dtype → 继承用例声明 dtype + WARN | 存量防崩兜底（last resort，不冒充合法） |

## 待决策点（不拍板，需用户/后续讨论）

1. **B 的继承语义是否保留**：仅当存在「旧快照 resume」这类真实存量场景才需要；若接受「旧快照即旧
   bug 产物、不兼容（§1.4）」的立场，B 可简化为「空/缺失 dtype → WARN + 保持 fp16 默认」或直接
   报错。倾向保留（本 run 自身就是 3 次 resume，存量场景真实存在），但边界值待确认。
2. **D 的报错是否连坐**：逐行报错（推荐）还是整份失败？推荐逐行——单行 producer 违约不应当掉其余
   合法用例。
3. **B 的 WARN 级别**：logger.warning 已够，还是需要进 run.log 的 `[WARN]` 通道（与框架其他告警
   一致）？实施时对齐仓库现有日志样式。
4. **修改 2 与修改 3 的实施顺序**：A 先行（本次 halt 的根修），D/B 视风险是否同轮跟进。
