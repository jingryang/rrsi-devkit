# 02 — 实施方案（L4）：批次1 —— 经验库澄清（防 codegen 复发）+ codegen 最小指针（可选）

> 本文是**独立批次 1** 的实施方案，可单独修改、单独提交，与批次 2（`03-impl-precision-debug.md`）互不依赖。
> 依据 `01-analysis.md` 的 P1（Cast `CAST_NONE` 静默留垃圾）+ P3（count 型 Compare/Select 256B 对齐）两个根因。
> **归位原则（§2.8 + 本仓约束）**：P1/P3 是 **API 规格/经验事实（公共知识）**，归**我们自己的经验库**（`ascendc-api-best-practices` / `ascendc-tips`），**不进 `ascendc-dev-knowledge`**（那是官方文档离线镜像，加我们的总结会在下次同步时冲突、混淆官方与推断）。

---

## 一、改动目标

P1/P3 的根因事实：P3 的「256B 对齐」**已在** `ascendc-api-best-practices/references/api-restrictions.md` §2.1 但**只覆盖 Compare、漏了 Select 和尾块后果**；P1 的「8bit→32bit 无直连 Cast」**缺失**。本批次**澄清/补齐我们自己的经验库**，不新增知识到官方镜像、不往 coding skill 塞事实。

## 二、改动清单

### 1. `ascendc-api-best-practices/references/api-precision.md` —— 补 Cast 8bit→32bit 中转

在「Cast RoundMode 选择」表后补一条（这是我们自己的实测结论，非官方文档）：

- **A2（dav_c220）无 `int8_t/uint8_t → int32_t/uint32_t` 直连 Cast**（`CastIntrinsicsImpl` 无该重载，直连编译报 `no matching`）。需 **half 中转**：`8bit→half（CAST_NONE，精确，half 10bit 尾数精确表示 |v|≤2048）→ int32（CAST_RINT）`。
- **`half→int32` 无 `CAST_NONE`**（仅 `CAST_RINT/FLOOR/CEIL/ROUND/TRUNC`）。用 `CAST_NONE` 时走 `ASCENDC_DEBUG_ASSERT(false)`，release 构建下展开为空 → **dst 静默留未初始化垃圾**（数据错/越界，不报错）。

### 2. `ascendc-api-best-practices/references/api-restrictions.md` §2.1 —— 扩展 256B 对齐

把标题「Compare API 256字节对齐约束」扩展为「Compare / Select（mask 相关 count 型）256字节对齐约束」，并补：

- `Select`（`VSEL_TENSOR_TENSOR_MODE` 经 `set_cmpmask` 消费打包 mask）与 `Compare` 同受「count 256B 对齐」约束。
- **尾块后果**：尾块 `len` 非 128 倍数（half）时，末段部分 chunk（`len%128`）的打包 mask 消费错位 → **该段结果残留初始值**（稀疏、随 N 变、max_diff 可达满量程）。
- 修复公式：`lenAligned = ((len+127)/128)*128`，向量 op 用 `lenAligned`、写回/输出仍按 `len` 短写（填充段不落地）。

### 3. `ascendc-tips` CA-1 —— 修正误导注记（可选，消除矛盾）

CA-1 现有「This 256-byte count alignment is specific to CompareScalar. Most other vector APIs do not have this requirement」——**不准确**（Compare tensor 也需 256B）。改为「256-byte count alignment applies to CompareScalar / Compare / Select（mask 相关 count 型）；多数纯算术 API 无此要求」。

### 4. codegen skill（可选 · 最小指针，不内联事实）

`ascendc-op-dev-coding/SKILL.md` Step 3「知识库查阅」加一条**指针**（指向我们的经验库，非官方镜像）：

- 「凡 `int8_t/uint8_t → int32_t/uint32_t` 拓宽、或 count 型 mask op（`Compare`/`Select`）尾块，必查 `ascendc-api-best-practices` 的 Cast 支持 / count 对齐约束」。

**此条可选**：经验库澄清后 codegen 本应能读对，指针只是降低读漏概率。是否加由用户决定。

## 三、设计阶段（`general_design` / `tiling_strategy` / `tiling_results`）：无需改

两个事实都是 kernel 实现细节：设计阶段不产出「具体 Cast API / 尾块对齐方式」。且尾块本就由 `N mod tile` 产生（运行时输入），设计层无法消除；`ubTileLen` 已 128 对齐（6912=128×54），问题只在尾块——这是 codegen/kernel 层该处理的。若用户希望设计层显式声明「dtype 中转路径 / 尾块对齐策略」，可在 `general_design.json` 的 precision 策略加一句注记，但**非必需、不阻塞**本批次。

## 四、改动顺序

1. 补 `api-precision.md`（Cast 中转）→ 扩展 `api-restrictions.md` §2.1（Select + 尾块）→（可选）修 `ascendc-tips` CA-1。
2. （可选）coding skill Step 3 加指针。
3. grep 全仓确认注记落位、无与旧措辞冲突（尤其 `ascendc-tips` CA-1 与 `api-restrictions.md` §2.1 的"Compare vs CompareScalar"表述不再矛盾）。

## 五、验证

- **经验库一致性**：grep 确认注记落位、措辞与 `01-analysis.md` 根因一致；确认 `api-restrictions.md` §2.1 扩展后与 `ascendc-tips` CA-1 不矛盾。
- **UT/ST 是否需补**：**不需**。改动是经验库/coding skill 的 prose 澄清，不触 §3.9（LLM/NPU 真实链路）。
- **可选 heavy_llm 验证**（§3.11 用户决策项，非本次默认跑）：用「8bit 输入 + 尾块非 128 对齐」结构复现 codegen，验证澄清后能生成「half 中转 + `CAST_RINT` + 尾块 `lenAligned`」。跑前须向用户列清单。

## 六、边界（本批次不碰）

- 不改 `precision_debug` 的任何 agent/skill（`ascendc-precision-*`）——批次 2（`03-impl-precision-debug.md`）。
- **不改 `ascendc-dev-knowledge`**（官方镜像，加我们的总结会同步冲突）。
- **不往 coding skill 内联事实**（§2.8 知识归经验库；coding skill 只加可选指针）。
- 不改算子代码（`unique` kernel 已修复）。

## 七、待决议题（独立于本批次，不在批次1 内解决）

**`ascendc-tips` 去留**：与 `ascendc-api-best-practices` 职责重叠（速查库 vs 分域详述），需单独决策。

- **覆盖事实**（已查实）：best-practices 覆盖 CA/MM/DT ≈ 60%（计算/数据面），**不覆盖** SC/OD/UT/HA/RB ≈ 40%（host shape / OpDef / 测试 / 硬件 / Regbase 无对应 reference）。
- **两条候选路径**：① 去重叠 + 瘦身（删 tips 里已覆盖的 CA/MM/DT，保留 SC/OD/UT/HA/RB 作非计算面速查）；② 彻底迁移 + 删除（14 条非计算面 tips 分迁 OpDef→op-design-shared、Regbase→官方 910D、HA→ascend-hardware、SC→host 知识，再删 tips）。
- **本批次只做**：修 `ascendc-tips` CA-1 的「specific to CompareScalar」误导（§二.3），**不决定、不执行** tips 去留。

