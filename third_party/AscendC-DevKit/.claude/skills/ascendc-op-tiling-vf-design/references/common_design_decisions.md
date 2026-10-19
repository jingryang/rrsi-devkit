# 通用 VF 设计决策框架

抽象自 14 类算子范式总结的**通用设计决策点**。不暴露具体算子信息。

模式详情见 [`vf_archetypes.md`](./vf_archetypes.md)（5 个 VF 编排模式的定义、示意图、ops-nn 实例）。

---

## 决策树：给定算子，如何选模式

```
几个 VF（__VEC_SCOPE__ 块）？

├─ 1 个 VF
│   ├─ loopCount == 1 → 模式 1（单 VF 串行）
│   └─ loopCount ≥ 2 → 模式 2（单 VF 双 buffer ping-pong）
│
├─ ≥2 个 VF
│   ├─ VF 间有数据依赖（串行）
│   │   ├─ N=2  → 模式 3（双 VF，算法阶段依赖）
│   │   ├─ N=3  → 模式 4（三 VF 全流水）
│   │   └─ N≥4 → 模式 4 推广（N VF 顺序编排，极少）
│   │
│   └─ VF 间无依赖（独立）
│       → 模式 5（多 VF 独立，顺序无约束）
```

> 📝 **vf_count 条件化**：当 C5/C6 判定依赖的容量或输出条件随 shape/attr 变化时，入口的"几个 VF"本身就是条件值——先按各分支分别走完决策树，产物 `vf_count` 写条件表达式（如 `"1 (H<2048) / 3 (H≥2048)"`，分支 ≤3、逐支注明判据、模板维度与模式），规则见 SKILL.md 步骤 1④。

**关键分叉点**：

| 分叉 | 判断依据 | 决定 |
|------|---------|------|
| 统计量是否为算子输出 | requirement outputs 中是否有 rstd/scale/mean 类输出 | 触发 C6 → 默认在物化点拆分（弱默认拆；豁免条件见 SKILL.md C6 说明块）；无论拆合 handoff_notes 均记录物化点 |
| VF 数 = 1 vs ≥2 | 切分规则 C1-C9 判定后剩几个计算段（见 SKILL.md 步骤 1② 判定表） | 模式组 |
| loopCount | tiling 后单核需要几轮？ | 模式 1 vs 2 |
| VF 间依赖 | vf_B 的输入是否依赖 vf_A 的输出？ | 模式 3/4 vs 5 |

---

## 决策 1：VF 数量决策

### 从算子特征到模式

> ⚠️ 下表为 A5 Regbase 典型结果（固定前提：统计量驻留寄存器、不占 UB，聚合边界不自动成切分线——见 SKILL.md 步骤 1②）。
> 先跑 C1-C9，最后才查本表确认量级。

| 算子特征（C1-C9 判定后） | VF 数 | 模式 | 典型场景 |
|---------|-------|------|---------|
| 单闭式 element-wise（无跨元素统计量） | 1 | 模式 1（loopCount=1）或 2（loopCount≥2） | 闭式激活函数 |
| 单统计轴规约 + 应用（C1 融合，无第二轴/第二轮语义） | 1~2 | 模式 1/2/3 | 单轴 normalize |
| 单统计轴规约 + 统计量是输出（C6 弱默认拆 + finalize 独立性） | 2~3 | 模式 3/4 | rms_norm 类：rstd 派生含 Sqrt/Div 属超越函数 → finalize 段默认独立 → 3（统计 / finalize / 应用，模式 4）；仅当 finalize 为单遍标量一步（如 scale 类仅 `s·avg`，无超越函数/迭代）且行全载与归约可内联（C8 证据支）三条件豁免成立时退化为 2（模式 3） |
| 两种统计轴（C2 切：如 row 轴 + col 轴） | ≥2 | 模式 3/4 | 双向归一化、softmax（A5 下 reduce+apply 融合） |
| 跨轮次不同语义段（C3 切：首轮含 softmax shift vs 后续纯归一） | ≥2 | 模式 3/4 | 迭代归一化算法 |
| 多级归约链 + 统计量是输出（C7；统计量 finalize 段默认独立） | 4 | 模式 4 推广 | LayerNorm 类：M / V / R(finalize) / Y 各一段（单遍归约豁免时 M+V 折叠为统计段 → 3：统计 / finalize / 应用，模式 4） |
| 跨核两阶段归约（C9：核间切分轴与统计轴相同） | 2 | 模式 3 | foreach 类多核归约 |
| 多输入 + 独立子问题（VF 间无依赖）| ≥2 | 模式 5 | 多路输入各自独立变换 |

> 📝 统计量 finalize 段（含超越函数/迭代求精/多级部分和合并的 rstd·scale 派生）**默认独立成 VF**（并入豁免三条件：单遍标量一步 + 行全载 + 归约可内联）——判据以 SKILL.md 步骤 1②「统计量 finalize 段独立性判据」为准，本文件不重复定义。

### 什么时候需要多个 VF（按切分规则归位）

- **C2（跨轴必切）**：两个计算段统计轴不同（row vs col / 末维 vs 非末维）
- **C3（跨轮次不同语义必切）**：首轮与后续轮操作序列不同且分属不同遍历轮次
- **C4（控制流不等价禁融合）**：相同循环次数/嵌套、无（或相同）条件分支不满足（引用 `a5_regbase_design.md` 规则 VF-2）
- **C5（A5 平局拆分）**：二次遍历（统计量→应用）且中间量驻留 ≥8KB 或活跃 vreg>32 → 融合收益归零，默认于聚合边界拆分（模块化优先）
- **C6（弱默认拆）**：统计量/中间量本身是算子输出（rstd/scale 类）→ 默认在物化点拆分（豁免须融合后单 VF op_count≤10（8-10 须标注 chain_length_risk）且活跃 RegTensor <20，并记录理由）；无论拆合，物化点都入 handoff_notes（另含 register_risk 容量/链长风险与 cross_core_stats 跨核物化两类）；op_count 红线（>7 标注、>12 入 register_risk）同属移交标注体系
- **C7（多遍历归约链按统计阶段分段）**：统计量是输出（C6 成立）且存在串行依赖的多级归约（Var 依赖 Mean）或归约段与应用段需重复遍历 x → 每级归约（M/V 段）与应用归一化（Y 段）各自成 VF（含单遍归约豁免：矩法/Welford 同遍同算 Σx/Σx² 时 M+V 折叠为统计段）；**统计量 finalize 段默认独立成 VF**（三条件豁免才并入，见 SKILL.md finalize 独立性判据）
- **C8（实现约束段边界）**：计算链须走高级 API（ReduceSum/Sort32/Gather 等不可内联进自定义 `__VEC_SCOPE__` 的库调用）或折叠/二分归约对齐 → API 调用点为天然段边界，前后自定义 `__VEC_SCOPE__` 各自成 VF；**前置默认**：reduce/max/sum/softmax 类归约在 A5 上默认假设不可内联，无单遍可内联证据时按 C8 拆或写条件表达式
- **C9（跨核归约终段成 VF）**：核间切分轴与统计轴相同（单核只产部分统计量）→ 跨核 finalize（GM workspace + SyncAll 后的最终归约）计为独立 VF，vf_count +1

> 📝 **不要拆分过细**：单闭式 element-wise 即使寄存器密集（14 个 vreg），切分型规则（C2-C5、C6、C8）未触发就不拆——拆 VF 引入额外 load/store，反而劣化。用 `CompareScalar + Select` 合并条件分支即可。C5 触发（二次遍历且中间量驻留 ≥8KB，融合收益归零）时按平局裁定拆分；C6 触发（统计量是输出）时按弱默认拆在物化点拆分。
> 📝 **不要凭聚合数量数 VF**：聚合点数量 ≠ VF 数量；每处聚合先过 C1（同轴同轮消费 → 融合），只有 C2/C3/C4 触发才切。

---

## 决策 2：流水阶段划分

### 阶段边界规则

| 边界类型 | 举例 | 同步 |
|---------|------|------|
| 外层搬运 ↔ VF | CopyIn (mte2) → VF / VF → CopyOut (mte3) | `EnQue`/`DeQue`（TQue 流水同步） |
| VF ↔ VF（有依赖） | vf_A (reduce) → vf_B (normalize) | 无（同 V 引擎顺序执行，依赖由 `data_flow` 表达） |
| VF ↔ VF（无依赖） | 模式 5 各 VF 独立，顺序无约束 | 无 barrier（同 V 引擎顺序执行，顺序任意） |

### 与模式的关系

```
模式 1/2 单 VF:  CopyIn ──[EnQue/DeQue]──→ vf_0 ──[EnQue/DeQue]──→ CopyOut
模式 3 双 VF:    CopyIn ──[EnQue/DeQue]──→ vf_A → vf_B ──[EnQue/DeQue]──→ CopyOut
模式 4 三 VF:    CopyIn ──[EnQue/DeQue]──→ vf_1 → vf_2 → vf_3 ──[EnQue/DeQue]──→ CopyOut
模式 5 独立 VF:  CopyIn(a,b) ──[EnQue/DeQue]──→ vf_0 → vf_1(顺序任意) ──[EnQue/DeQue]──→ CopyOut

[EnQue/DeQue] = TQue 流水同步：生产者 EnQue → 消费者 DeQue 阻塞等待.
VF 间（→）为同 V 引擎顺序执行，无显式同步.
```

> 📝 CopyIn / CopyOut 是外层 mte2/mte3 搬运（DataCopyPad），**不是 VF**。VF 数只数 `__VEC_SCOPE__` 块，不数 CopyIn/CopyOut。

---

## 核心心智模型

1. **固定前提：A5 统计量驻留寄存器**：中间结果（含聚合统计量）驻留寄存器、不占 UB——聚合边界不自动成切分线；勿把 membase 平台"见聚合就切"的习惯带入
2. **切分由 C1-C9 判定，不数聚合**：聚合点与同轴同轮消费融合（C1）；跨统计轴（C2）、跨轮次不同语义（C3）、控制流不等价（C4）才切；C5 平局裁定（二次遍历且中间量驻留 ≥8KB 或活跃 vreg>32 → 融合收益归零，模块化优先于聚合边界拆分）；C6 弱默认拆（统计量是算子输出 → 默认在物化点拆分，可显式豁免）；C7 多遍历归约链按统计阶段分段（含单遍归约豁免）；**统计量 finalize 段默认独立成 VF（三条件豁免才并入）**；C8 实现约束段边界（reduce/max/sum/softmax 类前置默认不可内联）；C9 跨核归约终段成 VF
3. **VF 间依赖关系决定顺序约束**：有依赖→模式 3/4（依赖链约束顺序），无依赖→模式 5（独立，顺序任意）
4. **loopCount 决定模式 1/2**：1 轮串行，≥2 轮双 buffer ping-pong
5. **CopyIn/CopyOut 不是 VF**：`__VEC_SCOPE__` 是唯一判断标准
6. **队列深度（DB_BUFFER）是通用配置**：与 VF 数量无关，任何模式都可用
7. **vf_count 可条件化**：结论依赖 shape/attr 时写条件表达式（分支 ≤3 各有判据）——库上同名算子不同 launch 的 VF 数本身可变，单值会被误读为全称结论
8. **分歧显式化**：库上实现与理论拆分的差异动因中，输出物化（C6 弱默认拆）与多核边界（C9 终段成 VF）已在本层定型为默认拆分/计数；其余动因（寄存器容量/链长风险等）落在 handoff_notes 标注里，不在本层消化。三类条目（materialization / register_risk / cross_core_stats）与字段结构以 SKILL.md 步骤 3 及 `vf_design_schema.yaml` 为准，本文件不重复定义（避免双源漂移）

---

## 附录：14 类算子 VF 分布统计

> 📝 以下为 ops-nn / ops-math / ops-transformer 仓库中各类算子的 VF 数量与模式分布的**统计观察**，不是决策规则。具体算子仍需通过决策树分析公式后确定模式。

| 算子类别 | VF 数范围 | 常见模式 | 备注 |
|---------|----------|---------|------|
| activation（激活） | 1 ~ 5 | 1/2 或 3/4 | 闭式=1，softmax 链（A5 融合式）=3~4 |
| norm（归一化） | 1 ~ 5 | 1/2 或 3/4 | ComputeY=1，多阶段=2-5 |
| quant（量化） | 3 | 4 | 固定 scale→offset→quantize 三段 |
| conv（卷积） | 1 ~ 3 | 1/2/3 | im2col 预处理 |
| pooling（池化） | 1 ~ 3 | 1/2/3 | reduce + index |
| loss（损失） | 2 ~ 5 | 3/4 | 多输入多阶段 |
| index（索引） | 1 ~ 2 | 1/3 | 简单 gather/scatter |
| foreach（批量） | 1 | 1/2 | 单计算 × 多输入 |
| conversion（变换） | 1 ~ 2 | 1/3 | idx 生成 + 主循环解耦 |
| math（数学） | 1 ~ 4 | 1/2/3/4 | 取决于公式复杂度 |
| random（随机） | 1 ~ 2 | 1/3 | 生成 + 变换 |
| mhc（多头） | 2 ~ 4 | 3/4 | 多阶段注意力 |
| moe（专家） | 2 ~ 5 | 3/4 | gate + expert dispatch |
| posembedding（位置编码） | 1 ~ 2 | 1/3 | 生成 + 融合 |
