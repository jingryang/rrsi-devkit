# 融合模式 F04：FFN（MatMul-激活-MatMul 两层前馈）

> ⚠️ **范围红线**：本文件严格限定在"概要设计"职责范围内。不包含 TilingData 字段结构、Buffer 大小数值、Kernel 循环代码、API 调用细节。平台硬件参数见 `general_design_common_knowledge.md`。
>
> 🔑 **匹配键 = SubOp 链签名**：`C01→A01(激活)→C01`（MatMul1 → 逐元素激活 → MatMul2）。**命中此链拓扑即匹配本模式，与算子叫什么名字无关**。区别于 F03（Vector/Cube 交替多趟 + 散射写 cache）：本模式 **纯 Cube 主导、仅一个激活夹在两层 MatMul 之间、无规约无散射**。
>
> **语料来源**：`ops-transformer/ffn/ffn`（实地核实 op_def REQUIRED x/weight1/weight2 + attr `activation` + kernel `mm1`→`Elewise(activation)`→`mm2`，`mm1WorkspaceGm`/`mm2WorkspaceGm`）。同类可参照 `ffn_glu`、MoE 专家 FFN、各类 `*_ffn`。

---

## 一、三维分类标识（LP8 固定 + SubOp 链）

### LP 循环结构模式

```
类型: LP8(多阶段异构)
描述: x 经第一层投影 MatMul → 中间隐层做逐元素激活(GELU/SILU/RELU/FASTGELU)
      → 第二层投影 MatMul 回原维度——阶段间 Cube→Vector→Cube 拓扑切换，多阶段异构
处理规则: 分解为 SubOp 序列 → 各 SubOp 独立匹配 LP1~LP7 → SubOp 链匹配本融合模式
```

### SubOp 链的 (LP, CP, ES) 列表

```
SubOp1: MatMul1(x × weight1, 升维到隐层) → (LP6, CP3, ES1) → 命中原子模式 C01
SubOp2: 激活(activation: GELU/SILU/RELU/FASTGELU) → (LP1, CP1, ES1) → 命中原子模式 A01
SubOp3: MatMul2(激活输出 × weight2, 降维回原) → (LP6, CP3, ES1) → 命中原子模式 C01
```

> 注：真实 kernel 用 `mm1.IterateAll(mm1WorkspaceGm)` 写出第一层结果到 workspace，`Elewise1HighPrecision`/`Elewise2`（内含 `Gelu/Silu/Relu/FasterGelu` 按 `activeType` 分发）做激活，再 `mm2` 读激活结果做第二层。激活是**唯一的 Vector 阶段**，夹在两个 Cube 阶段之间。

### 融合整体的 ES（执行结构）

```
类型: ES3(多阶段WS)
判定依据: MatMul1 输出（隐层，维度大）经 GM workspace(mm1WorkspaceGm) 中转给激活，
          激活输出再经 workspace(mm2WorkspaceGm) 给 MatMul2——
          两层投影中间隐层超 UB，必须落 GM
```

### L1 张量签名（属性参数）

```
输入(REQUIRED): x, weight1, weight2
输入(OPTIONAL): expert_tokens(MoE 分组), bias1/bias2, scale/offset(量化),
      deq_scale1/2(反量化), antiquant_scale1/2 + antiquant_offset1/2(权重反量化)
输出: y（降维回原 hidden 维度）
角色: [data(x), weight(weight1/weight2), bias, 量化参数 ×多组, index(expert_tokens 可选)]
维度语义: x[tokens, H] → MatMul1 → [tokens, H_inner] → 激活 → MatMul2 → y[tokens, H]
```

### L4 关键工程约束（属性参数）

```
是否变长/动态 shape: 支持 DynamicShape + DynamicRank; expert_tokens 驱动变长分组
是否含 Mask: 无
是否需要 Index/Cache 写: 无散射写 cache; expert_tokens 仅作分组边界(非散射 index)
是否需要核间通信: 否（Cube/Vector 跨阶段经 GM 同步）
关键约束: activation attr 必填(运行期选 GELU/SILU/RELU/FASTGELU);
          inner_precise 双模板(高精度 ffn_high_precision / 高性能 ffn_high_performence);
          weight NZ layout(部分平台); 多种量化(INT8/INT4 权重 + per-channel 反量化);
          支持 MoE grouped FFN(expert_tokens 分专家); A2/A3/310p/kirin 四平台
```

---

## 二、模式总览

| 字段 | 内容 |
|------|------|
| **融合名称** | FFN（MatMul-激活-MatMul 两层前馈） |
| **SubOp 链签名** | `C01→A01(激活)→C01` |
| **阶段数** | 3（升维 MatMul → 激活 → 降维 MatMul） |
| **一句话描述** | 标准两层前馈网络：x 经第一层 MatMul 升维、中间做激活、第二层 MatMul 降维回原；两层投影中间隐层经 GM 中转，激活是唯一 Vector 阶段 |
| **典型算子** | `ops-transformer/ffn/ffn`、`ffn_glu`、MoE 专家 FFN |
| **适用条件** | Transformer 前馈块：两层线性投影夹一个激活，可选量化/权重反量化/MoE 分组 |

---

## 三、SubOp 分解表 ⭐

| 阶段 | SubOp | LP | CP | ES | 命中原子模式 | 输入 → 输出 |
|------|-------|----|----|----|------------|-----------|
| 1 | MatMul1（升维 x×weight1 +bias1） | LP6 | CP3 | ES1 | C01 | x + weight1 → 隐层(mm1WorkspaceGm) |
| 2 | 激活（GELU/SILU/RELU/FASTGELU） | LP1 | CP1 | ES1 | A01 | 隐层 → 激活输出(mm2WorkspaceGm) |
| 3 | MatMul2（降维 ×weight2 +bias2） | LP6 | CP3 | ES1 | C01 | 激活输出 + weight2 → y |

> 阶段在 Cube(1)→Vector(2)→Cube(3) 间切换，靠 mm1/mm2 workspace 串接；含量化时激活前后插反量化/量化。

---

## 四、阶段编排与数据流 ⭐

### 4.1 阶段间数据流拓扑

- **编排方式**：真实 kernel 以 Cube 为主体——`mm1`（MatMul1 实例）`IterateAll` 写隐层到 `mm1WorkspaceGm`，`Elewise1/Elewise2`（按 `activeType` 分发 Gelu/Silu/Relu/FasterGelu）做激活并写 `mm2WorkspaceGm`，`mm2`（MatMul2 实例）读激活结果产出 y。Cube 双实例 + 跨阶段 SetFlag/WaitFlag（`SyncBeforeMM1`/`CheckSyncBeforeMM1` 管理 MM1↔MM2 并行）。
- **数据流**：
  ```
  x ─C:MatMul1(weight1,+bias1)→ GM(mm1Workspace, 隐层)
    ─V:激活(activeType 分发)→ GM(mm2Workspace)
    ─C:MatMul2(weight2,+bias2)→ y
  ```

### 4.2 阶段间中间结果驻留层级 ⭐（ES3 vs ES4 判定核心）

- **本模式 = ES3（多阶段 GM workspace）**：隐层维度 H_inner 通常是 H 的数倍（FFN 升维比），中间隐层张量 [tokens, H_inner] **远超 UB**，必须落 mm1WorkspaceGm；激活输出同理落 mm2WorkspaceGm。
- 判定依据：①FFN 升维比使隐层巨大；②Cube(L0C)→Vector(UB)→Cube 的跨单元传递经 GM；③两层 MatMul 天然以 GM 为边界。**无法 ES4**。

### 4.3 公共切分轴

- **公共切分轴 = token 行（M 轴）**：MatMul1 的 M = token 行，激活沿同行逐元素，MatMul2 的 M 同。N/K 轴在各 MatMul 内部按 Cube 分形切。
- MoE 分组：`expert_tokens` 把 token 行按专家分段，每段独立走 MatMul1→激活→MatMul2（grouped FFN）。

---

## 五、阶段间 UB/Workspace 共存验证（概设层：仅"能否放下"）

> 与 F01/F03 不同，本模式 UB 压力集中在**激活阶段**（唯一 Vector 阶段），workspace 压力在两层隐层。

**必须落 GM workspace 的中间项**：

| 数据项 | 来自阶段 | 说明 | 驻留 |
|--------|---------|------|------|
| 隐层（MatMul1 输出） | SubOp1 | [tokens, H_inner]，升维后巨大 | **GM workspace (mm1Workspace)** |
| 激活输出 | SubOp2 | 供 MatMul2 读 | **GM workspace (mm2Workspace)** |
| 激活 tile 输入/输出/临时 | SubOp2 | 逐元素，分块流式 | per-iter UB |
| 量化/反量化参数 | 各量化点 | per-channel/per-tensor | UB 常驻（量化时） |

**共存约束式（概设级）**：
```
workspace 总量 = mm1Workspace(隐层) + mm2Workspace(激活输出) ≤ 平台 workspace 预算
激活单趟 UB = tile 输入 + tile 输出 + 激活临时(如 Gelu 的 erf 工作区) ≤ UB 可用容量
Cube 分形 = L0A/L0B/L0C 容纳 MatMul1/2 的 basic block
→ 三阶段经 GM 解耦，分别核算；激活 tile 沿 H_inner 分块流式即可
```
- 与 F01/F03 的对照：F01 全程 UB（ES4）；F03 因 norm/rope 中间态 + 投影交替落 GM（ES3）；F04 因**升维隐层巨大**落 GM（ES3）。三者 ES 差异根源不同，均由"中间态能否驻 UB"决定。

---

## 六、平台相关设计考量

> ⚠️ 本算子真实支持 **A2/A3（910b/910_93）+ 310p + kirin（x90/9030）** 四类平台（语料 op_def AddConfig）。310p 与 kirin 的 weight/x layout 配置不同（310p 走 NZ，kirin 走 ND）。

### 以 A3 为基准的设计要点

| 维度 | 如何影响本融合模式的概要设计 |
|------|---------------------------|
| Cube + Vector 双单元 | mm1/mm2 双 Cube 实例 + 激活 Vector；MM1/MM2 可跨核并行（CheckSyncBeforeMM1 判定），融合收益来自省去两层 MatMul 间整个隐层的算子边界 GM 往返（但内部仍有隐层 GM 中转） |
| L0A/L0B/L0C 容量 | 约束 MatMul1/2 的分形 basic block；升维比大时 MatMul1 的 N 轴需多趟 |
| workspace 预算 | 决定可否容纳隐层 + 激活输出两块；不足则减小 token tile |
| 高精度 vs 高性能模板 | inner_precise attr → Elewise1HighPrecision（FP32 中间）vs Elewise2（低精快路） |

### 其他平台的概设差异

- **310p**：weight/x 走 FRACTAL_NZ，输出 NZ；需配合对齐。
- **kirin（x90/9030）**：weight/x 走 ND，单独 config。
- **A5（语料未列，预留）**：若移植，Regbase 不改变隐层落 GM 的 ES3 本质。

---

## 七、已知变体

| 变体 | 触发条件 | 与主模式的差异 |
|------|---------|--------------|
| **激活类型（GELU/SILU/RELU/FASTGELU）** | activation attr（运行期） | SubOp2 的逐元素函数不同；属 A01 内部分支，按差分清单记录不另立文件 |
| **高精度 vs 高性能** | inner_precise attr | 激活与累加中间精度不同（FP32 vs 低精）→ 两套 kernel 模板（ffn_high_precision / ffn_high_performence） |
| **量化 FFN（INT8/INT4 权重）** | x/weight 为 INT8/INT4 + deq_scale/antiquant | MatMul 前后插反量化/量化；权重 INT4 需特殊 antiquant；量化参数常驻 UB |
| **MoE grouped FFN** | expert_tokens 非空 | token 行按专家分组，每组独立两层投影；公共切分轴仍 token 行，增分组边界处理 |
| **GLU 门控（ffn_glu）** | 门控前馈 | MatMul1 输出拆两半，一半激活一半门控相乘 → SubOp2 变 `A01(激活)∥直通→Mul`，链微调为 `C01→[A01∥-]→A01(mul)→C01` |
| **bias 缺省** | bias1/bias2 OPTIONAL | 跳过 bias 加；ClearBias 分支 |

> **与 F03 的边界**：F03 含 norm 规约 + rope + 散射写 cache（链里有 B01/G01），是注意力前处理；F04 纯 `C01→A01→C01` 无规约无散射，是前馈块。共享 C01（MatMul）但**有无 norm/rope/cache 写**是分流键。

---

## 八、关键决策记录

| 决策问题 | 选择 | 替代方案 | 理由（含融合 vs 分离的收益量化方向） |
|---------|------|---------|--------------------------------|
| 融合 vs 分离 | 融合（两层 MatMul + 激活单算子） | MatMul1 / 激活 / MatMul2 三独立算子 | 免去隐层 [tokens, H_inner]（升维后巨大）在算子间落 GM 再重读；收益 ≈ 2×(tokens×H_inner×sizeof) 的算子边界 GM 往返 |
| 中间隐层 UB vs GM | 落 GM workspace（ES3） | 全 UB（ES4） | 升维隐层远超 UB，物理上无法 ES4——与 F01 的根本不同 |
| MM1/MM2 编排 | 双 Cube 实例 + 跨核并行判定 | 严格串行 | MM1 算完部分即可启 MM2（流水重叠），CheckSyncBeforeMM1 按核数决定；提升 Cube 利用率 |
| 激活精度 | 双模板（高精 FP32 / 高性能低精） | 单模板 | 精度敏感场景走 FP32 中间，否则走低精快路；inner_precise 路由 |
