# L1 问题记录：排序类算子算法可实施性盲区 + int→fp 精度知识缺口

> 层级：**L1 / 问题记录**。只记客观事实（哪里坏了、凭什么这么说），不提方案、不排顺序、不写决策。
> 配套：`02-analysis.md`（L3 方案分析）、`03-impl.md`（L4 实施方案）。
> 记录者：Claude。日期：2026-08-23。

---

## P1：算法可实施性分析缺失——排序/去重/逆映射类高复杂度算法被整段压给 codegen

### 事实

两次独立 batch（20260810、20260822）跑同一类高复杂度算子，均因"设计指定的算法无法在单会话内正确实现"失败：

| 批次 | 模型 | 卡点 | 现象 |
|---|---|---|---|
| 20260810（unique） | deepseek-v4-flash | codegen 163 回合过度推演不落盘 → halt | 设计指定 bitonic 排序 + 二次散射 |
| 20260822（unique） | deepseek-v4-flash | codegen 落盘但算法设备级失败 → debug 无解 | 同一设计指定 bitonic 排序 + 二次散射，kernel 全崩 507035 |

### 证据

- `docs/plan/self-evolution/batch-20260810-172452-1725d0-analysis.md` P2：codegen 收到设计明确指定 bitonic 排序 + 二次散射，163 回合持续设计推演未写码 → empty_artifacts → halt。
- 20260822 批 diagnose 产出：`BlockedBitonicSortGM`/`DedupCompactionGM`/`CompareExchange` 用 TBuf+DataCopyPad 接 V 运算零同步（sync bug）；且 int64 索引经 fp32 中转排序产生错乱（unique_8 max_err=5.34e18）。6 phase debug 全跑仍失败，budget 耗尽。

### 事实主张（只陈述，不归因）

1. 设计阶段（template-division 等）**不评估指定算法的 codegen 可实施性**：不检查 dtype 约束是否可行、是否复杂到需拆解/换方案。
2. 结果：高复杂度算法（排序/去重/逆映射）被整段交给单个 codegen 会话，失败则 debug 无解或熔断。

---

## P2：知识库精度文档覆盖盲区——int 索引/排序键转 fp 比较

### 事实

`ascendc-api-best-practices/references/api-precision.md` 的 Cast 规则表（L19-29）：

| 转换方向 | RoundMode | 注释（现状） |
|---|---|---|
| half → float | CAST_NONE | 低→高，无损失 |
| float → half | CAST_ROUND | 高→低，有损失 |
| half → int32 | CAST_RINT | 量化场景 |
| **int32 → float** | **CAST_NONE** | **"整数→浮点，无精度损失"** |

### 事实主张

1. **`int32 → float` "无精度损失" 不准确**：|int32| > 2^24（16,777,216）时 fp32 丢尾数（fp32 尾数仅 24bit）。int64 → fp32 更是**必丢**（64bit 值域 vs 24bit 尾数）。
2. 文档**无**"int 索引/排序键转 fp 比较有精度风险"条目，也无 comparable 位序范式（无精度地比较 int 排序键）。
3. 实际 kernel 佐证：本次 unique kernel 的 `TLess`/`TEqual`（标量 comparable，float/half 位序转换）已实现位序比较，但主排序路径 `BlockedBitonicSortGM` 用 `LocalTensor<float>` 向量比较，未用 comparable → 命中精度盲区。

### 事实主张（边界）

- `api-precision.md` 已正确覆盖：half/float 升降精度、8bit→32bit 的 half 中转、MX 量化、混合精度。
- 缺的是：**int 大值 / int64 → fp 中转的精度损失**，以及 **int 索引/排序键在 A2 原语约束下（Select 仅 half/float）如何无精度比较**。

---

## P3：precision_debug 六 phase 对算法级缺陷失配

### 事实

20260822 批 precision_debug 六 phase 全跑（run_tests → scope_guard → bounds_check → diagnose → printf_location ×2），仍无法定位：

- bounds_check（40min）：判 SysWorkSpace 未叠加 + 4 越界，`post_critical=0`，但 507035 仍在（假阴性）。
- diagnose（50min）：44 个命名变体目录（barrier/sysprobe/win0/fullfix/fix_top/p1only/p2v2/ubmerge/scalar/rawsort/probe...）——一次 diagnose 内尝试几十种同步修复变体。
- printf_location（31 + 220min）：74 bash + 42 read 全卡"printf 输出不可见"（调日志级别），仅 5 edit，从未定位。

### 事实主张

- 失败根因（Compare/Select mask 位序、int64 fp32 精度、TBuf 同步）**不是任何 phase 能定位的**：bounds_check 禁读 CANN 头文件、printf 对 Heisenbug（时序相关）无效、candidate_pool 枚举错误类型。
- 与 `docs/plan/precision-debug-blindspot/01-analysis.md` 的漏检根因分析一致（§3.1-3.5）。

---

## P4：既有设计优化（H01 排序算法族）生效但存在枚举盲区

### 事实

2026-08-14 针对 unique 的排序方案做了 skill 优化（commit `0113f600`/`2b56dd0a`）：H01 排序算法族补全（比较排序 / LSD radix / presence bitmap 三族选型 + 去重变体 + 陷阱）。2026-08-15 又删了 4 个设计质量门（`2520e6ed`）。

**本次 20260822 unique 查证结果（实证）**：
- **H01 排序算法族生效了**：本次设计阶段产物 `template_division.json` 明确按 H01 选了双模板（T2 presence bitmap 走 int8/uint8，T1 比较排序去重走其余 dtype），`decision_log` 提到"T2 presence bitmap 纳入正式模板（用户裁决）"、"A2 无 Histograms，bitmap 需 256-pass 向量比较"——均源自 H01 内容。
- **删门也生效了**：本次设计阶段无任何 gate（`build_general_design_group` 注释明确"no review gate — generator 自检"，`_DETAILED_DESIGN_TRANSITION_TABLE` 只剩 dd-intake 一条，`design_checks.py` 不存在）。
- **但 H01 存在枚举盲区**：H01 §3.5 比较排序行的"已知陷阱"写了"硬件原语约束多，使用前必须逐条对质 API 约束 + 实测验证"，**却没把"int64 索引转 fp32 排序键丢精度"列为必查项**。radix 行写了"浮点/有符号整数须先做位序变换"、bitmap 行写了"int64 全域不可行"，唯独"比较排序 + int64 索引"这行漏了。本次 T1 恰栽在这。

### 事实主张

- H01 生效（选了算法族框架）但没有机械保障"对质 API 约束"一定发生 → int64+比较排序组合漏网。
- **这是枚举式补 skill 的必然盲区**：补了 radix 的位序陷阱、bitmap 的 int64 限制，漏了"比较排序 + int64 索引"组合；未来还会漏别的组合。§1.14「枚举 = 打补丁」实证。
- 结论：不能靠继续枚举补 skill，需**不依赖枚举的通用对质机制**（设计阶段对质 dtype 转换 + 知识库补明确精度边界 + codegen 兜底）。

---

## 产权与关联

- 本问题组产权在**设计阶段（可实施性自检）+ 知识库（精度文档）**，不在 precision_debug。
- 关联：`docs/plan/precision-debug-blindspot/`（debug 减法方案，P3 与之一致）、`docs/plan/self-evolution/batch-20260810-172452-1725d0-analysis.md`（P2 算法可实施性门缺口）、`docs/plan/unique-codegen-scalar-collapse/`（codegen 向量化降级护栏）。
