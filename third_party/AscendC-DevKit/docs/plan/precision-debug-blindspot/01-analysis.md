# precision_debug 定位盲区分析：unique P1/P3 根因为何漏检，及其框架级归因

> 本文是独立完整分析报告。以 `unique` 算子两个根因（P1 Cast `CAST_NONE` 静默留垃圾、P3 count 型 Compare/Select 256B 对齐）为案例，回答一个框架级问题：**为什么 precision_debug 阶段（scope_guard → bounds_check → diagnose → printf_location/comment_bisect）始终无法定位这两个根因，而交互会话能定位？** 并按 §1.14「帮模型 vs 控模型」判据，逐条评估 precision_debug 的规则与结构哪些是"帮模型"、哪些是"控模型"（副作用）。
>
> **实施方案已拆两份独立 L4**：批次1（设计+codegen 引导）→ `02-impl-codegen.md`；批次2（precision_debug 优化）→ `03-impl-precision-debug.md`。二者可分别评审、分别提交。
>
> 证据来源：`unique` 运行产物（`docs/plan/unique-507035-optional-output/01-problems.md`）、precision_debug 各 agent 定义（`.claude/agents/ascendc-precision-*.md`）、diagnose skill（`.claude/skills/ascendc-precision-diagnose/SKILL.md`）、CANN 头文件（`kernel_operator_vec_vconv_impl.h` / `kernel_log.h`）。

---

## 一、结论摘要

precision_debug 漏检的根因**不在"模型算不准"，而在工具链的系统性设计**——它把定位手段从「ground-truth 源头 + 受控实验」替换成了「症状分类 + 枚举错误类型」，并明文禁止了 ground-truth 查询：

1. **封死了 ground-truth 查询**：`diagnose` 规则 4「Never grep CANN 系统路径」、`bounds_check` 规则 7「never read knowledge-base docs or CANN headers」——而 Cast 根因的唯一事实来源恰是 CANN 头文件（`CastIntrinsicsImpl` 重载全集 + `ASCENDC_DEBUG_ASSERT` 空展开）。
2. **bounds_check 禁了 GM_OOB**：规则 6「GM_OOB checks are disabled」——而 507035 恰是 GM 越界（"MTE invalid GM address"），被设计排除在检查范围外。
3. **症状分类 + 枚举错误类型**：Gate1 靠 curated `common-traps` 枚举，漏掉「库外新错误类型」（256B 对齐、"静默失败"这类不在库里的）。
4. **假阴性被下游采信**：bounds_check shadow 对「数据依赖越界」（垃圾数据 → 垃圾索引 → 越界）判 `post_critical=0`，diagnose 的 route_to 自检第 3 问「结构性排除」直接采信这个假阴性 → 路由到 fix 修了 DCache，把 507035 掩盖。

这四条都属于 §1.14 说的「控模型」结构（枚举错误类型 + 填表），而非「帮模型」（ground-truth 前置 + 最小骨架）。

---

## 二、案例事实（两个根因 + precision_debug 的实际产出）

### 2.1 两个根因（最终坐实）

| # | 根因 | 机制 | 症状 |
|---|------|------|------|
| P1 | `Cast(int32, half, CAST_NONE)` 在 A2(dav_c220) 是 unsupported | `CAST_NONE` 走 `ASCENDC_DEBUG_ASSERT(false)`，release 下该宏展开为空 → dst 留**未初始化**；UB 残留为 0 → K=1（数据错），为垃圾 → `presence.SetValue(grp)` 越界 → 507035（崩溃） | 507035 + K=1 同源 |
| P3 | count 型 `Compare`/`Select`（打包 mask）256B 对齐被尾块违反 | 尾块 `len` 非 128 倍数时末段 chunk（`len%128`）打包 mask 消费错位 → 该段 inverse 残留初始 0 | 稀疏 inverse mismatch（max_diff=255） |

### 2.2 precision_debug 的实际产出（未定位到 P1/P3）

- `bounds_check`：判唯一 CRITICAL 为「SysWorkSpace 未叠加」，修复后 `post_critical=0`、`shadow_recheck_passed=true`。**但 507035 仍在**（假阴性）。
- `diagnose`：root_cause 判「GlobalTensor::SetValue 标量 GM 写只落各核私有 DCache → K=0 → y 空」（一个**真** bug），修复后 `best_passed_count=5`。**但 507035 未被定位**，且把「崩溃（地址错）」与「数据错（DCache）」混在一起。
- 最终 `cannbench_eval`：`overall=5.00 pass_rate=10%`（2/20，5 failed + 13 cascade）。

### 2.3 交互会话如何定位（对照）

1. **读 CANN 头文件**：`dav_c220/kernel_operator_vec_vconv_impl.h` 的 `CastIntrinsicsImpl` 重载全集（证明 8bit→32bit 无重载）+ `kernel_log.h`（证明 release 下 `ASCENDC_DEBUG_ASSERT` 展开为空）。
2. **受控复现**：直调 `torch.ops.cann_bench.unique`，变 N 观察到「错块恰 = perCoreElems % 128」的精确模式，坐实 P3。

---

## 三、漏检根因（逐条带证据）

### 3.1 封死 ground-truth 查询（hard rule 4 / bounds_check 规则 7）

- `ascendc-precision-diagnose.md` Hard rule 4：**"Never grep CANN 系统路径（`/usr/local/Ascend/`, `$ASCEND_TOOLKIT_HOME`）"**；"Unfamiliar AscendC API → query knowledge base with fuzzy fallback…都找不到则标 fix_plan 不可行，禁止猜"。
- `ascendc-precision-bounds-check.md` Hard rule 7：**"No external API lookup. All API constraints are in the skill — never read knowledge-base docs or CANN headers"**。

Cast 根因的唯一事实来源是 CANN 头文件。这两条规则把「读 ground-truth 头文件」从工具链里**删掉**了，理由是防「搜 SDK 浪费时间 / 照抄实现」，但代价是连同「确认 API 真实约束」一起删了。

**为什么知识库兜不住**：知识库 `Cast.md` 表6（A2 支持矩阵）**确实正确**记录了「8bit→32bit 无重载、half→int32 无 `CAST_NONE`」。但：
- diagnose 的 runtime 路径（分支 A2）走「错误码解码 + sibling 架构对比」，**根本不查** Cast 约束；
- diagnose 的 precision 路径（Gate1）走「common-traps」枚举，其中「Cast RoundMode」是**泛化检查**（"round mode 对不对"），**不含**「half→int32 的 CAST_NONE 是 unsupported 会静默留垃圾」这条具体事实。

即：**正确信息在知识库里，但工具链没有引导模型去用它查"当前失败的这个 Cast 方向支不支持"**。ground-truth 被封死，知识库又没被定向使用 → 漏检。

### 3.2 bounds_check 禁 GM_OOB（规则 6）

`bounds_check` 规则 6：**"GM_OOB checks are disabled — only check UB_OOB / ALIGN_32B / UB_TOTAL"**。

507035 的定义就是 "MTE invalid GM address"（GM 越界）。bounds_check **按设计**就不查 GM 越界。而 507035 的机制还是**间接的**（未初始化数据 → 垃圾索引 → 下游 GM 越界），连 UB_OOB 的静态影子都覆盖不到（影子脚本只模拟"代码里写死的 offset 越界"，不模拟"数据依赖的越界"）。

### 3.3 症状分类 + 枚举错误类型（Gate1 common-traps）

diagnose 的失败分类是三桶：`compilation / runtime / precision`。Gate1 走「symptom-table → common-traps → case-studies」这个**人工整理的枚举库**。枚举法的本质是**库里有才能命中，库里没有就漏**（§1.14：「错误类型无界，枚举 = 打补丁」）。

P1 的「静默失败」（uninitialized data）和 P3 的「256B 对齐」都不在 common-traps 里（库里有 "VEC 32B 对齐"，没有 "count 型 mask op 256B 对齐"）。而且「静默失败」**跨三个桶**：它编译通过（不是 compilation）、有时不崩（不是 clean runtime）、不是公式错（不是 clean precision）——分类结构本身对它失配。

### 3.4 假阴性被下游采信（route_to 自检第 3 问）

diagnose 的 route_to 自检第 3 问「结构性排除」：**"bounds_check / sync check / printf_location 历史是否已确认 L1（地址/OOB/对齐）和 L2（数据搬移）干净？"**

- bounds_check 判 `post_critical=0`（L1 假阴性）。
- diagnose 自检采信这个假阴性 → 判「L1 干净」→ `route_to=fix` → 修 DCache（真 bug 但不是 507035 根因）→ 507035 被掩盖。

即：**bounds_check 的假阴性，经 route_to 自检的「信任链」，变成了 diagnose 的误判**。结构性排除的可信度完全取决于 bounds_check 的覆盖度，而 bounds_check 的覆盖度（禁 GM_OOB + 静态影子）恰恰覆盖不到这个根因。

### 3.5 附带：printf_location / comment_bisect 也救不了这个根因

- `printf_location`（插 printf 二分）：对 P1 无效——printf 改变时序 → 未初始化 UB 恰好变零 → 崩溃消失（Heisenbug）。diagnose 规则 6 已识别「printf 让失败变 pass → sync 缺失」，但那是**sync 机制**，P1 是**未初始化数据**，机制不同、不在规则覆盖内。
- `comment_bisect`（注释/降级 + crash/no-crash）：对 P1 无效——它的信号是「crash vs no-crash」，而 P1 是「未初始化数据 → 时序相关地或崩或不崩」，注释/降级同样改变时序。对 P3 无效——P3 是「数值错但不崩」，comment_bisect 只看 crash。

---

## 四、逐规则评估（帮模型 vs 控模型，§1.14 判据）

判据（§1.14）：一项结构若属「控制模型」，默认不加；留「帮模型」和「框架骨架」，删「控模型」。「帮模型」= 知识前置 / ground-truth 可达；「控模型」= 抓模型错的 gate / 枚举规则 / 回炉机制 / 让模型填表的结构。

| # | 规则/结构 | 归属 | 评估 | 建议（减法，§1.14） |
|---|----------|------|------|------|
| 1 | diagnose 规则4「禁 grep CANN 路径」 | **控模型** | 封死 ground-truth，直接致漏检；「防照抄/防浪费」的正向意图被"一刀切禁"绑架 | **删**规则；定位靠"就地问 API 约束"（agent 自然动作），防照抄/防浪费由**知识前置**（经验库预置正确约束）承接 |
| 2 | bounds_check 规则7「禁读 CANN headers / 知识库」 | **控模型** | 同上 | **删**（随 bounds_check 整体删，见行 3） |
| 3 | bounds_check 规则6「禁 GM_OOB」+ Python shadow checker | **控模型** | 静态影子覆盖不到"数据依赖越界"，判 post_critical=0 假阴性；且 checker 本身是"抓模型错" | **删整个 bounds_check**（静态 checker 非"帮模型"；越界由 golden 比对兜底暴露） |
| 4 | Gate1「symptom-table → common-traps → case-studies」枚举 | **控模型** | 枚举错误类型，库外新错误必漏（§1.14「枚举=打补丁」） | **删**（§1.14「不靠枚举规则」） |
| 5 | 症状三桶分类（compilation/runtime/precision） | **控模型** | 对跨桶症状失配，强制分类误导 | **删**；失败只留"崩 / 数值错 / 上游"的粗略路由（非根因分类） |
| 6 | candidate_pool（hits≤2 + priority + verified + excluded） | **控模型** | "填表而非解算子"（§1.14） | **删** |
| 7 | route_to 三问自检 | **控模型（有假阴性传导）** | 第 3 问采信 bounds_check 假阴性 → 误判 | **删** |
| 8 | printf_location 独立 phase（bisect_progress/max_rounds/RESULT 协议） | **控模型（回炉编排）** | 回炉机制；且对 Heisenbug 无效 | **删独立 phase**；printf 二分降为"诊断+修复"阶段内可用的**技巧**（进 skill references） |
| 9 | comment_bisect 独立 phase（Layer0/1/2 + 实验预算） | **控模型（回炉编排）** | 同上 | **删独立 phase**；注释/降级降为技巧 |
| 10 | scope_guard 独立 phase（入口守卫） | **控模型（门）** | 门；但"拦 upstream 缺陷避免空转"有真实价值 | **删独立 phase**；"拦 upstream"降为"诊断+修复"入口的**一句判据**（保留价值、删门结构） |
| 11 | "failure_type 分流 + 池耗尽再 bisect"串行编排 | **控模型** | 把定位排在枚举之后 | **删**（无枚举、无回炉，自然无此编排） |

---

## 五、结论：precision_debug 该做减法（§1.14），不是加法

P1/P3 的漏检，根子不是"少了一个定位手段"，而是"多了一套控模型结构"。按 §1.14，precision_debug 的「枚举错误类型 + 候选池 + 回炉」这套是"控模型"，应**删**，而不是"加 ground-truth 查询/受控复现"去补它。

定位的正确方式（§1.13/§1.14）：「**比对 golden 一致即对，不一致就地修**」——不一致时**就地**查对应 API 的约束/支持矩阵/round mode、插 printf 二分收敛发散点、改那一处，**不枚举错误类型、不生成候选池、不回炉重生成**。

最小化后的 precision_debug = **「run_tests（golden 比对）+ 一个诊断修复阶段」**，定位是 agent 的自然动作，不是框架编排的独立 phase。

删除清单与分阶段实施见 `03-impl-precision-debug.md`（批次 2）。本报告只给分析 + 结论，不直接改。

---

## 六、关联

- 案例事实与 P1/P2/P3 根因坐实：`docs/plan/unique-507035-optional-output/01-problems.md`。
- §1.14 判据（过度结构化/枚举错误类型/golden 唯一兜底）：`CLAUDE.md §1.14`、`§1.13`。
- 同源历史（假阴性/枚举盲区）：memory `precision-debug-abort-false-positive`（abort 判据单维度误杀）、`precision-harness-rejects-optional-attrs`（scope_guard 按错误形态误判归属）、`batch-20260809-systematic-patterns-fixed`（模式 2/3/4 结构自身缺陷）。
- 本报告对应的文档产权：L1 问题 + L3 方案分析（本文即分析；L4 实施待方案评审后单开）。
