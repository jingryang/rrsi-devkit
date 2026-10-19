# 融合模式 F02：MoeGatingTopK（Softmax + TopK）

> ⚠️ **范围红线**：本文件严格限定在"概要设计"职责范围内。不包含 TilingData 字段结构、Buffer 大小数值、Kernel 循环代码、API 调用细节。平台硬件参数见 `general_design_common_knowledge.md`。
>
> 🔑 **匹配键 = SubOp 链签名**：`B01(LP4×CP1×ES2) → H01(LP7×CP1×ES1)`（D轴规约 → 选择排序）。**命中此签名即匹配本模式，与算子叫什么名字无关**。文件名里的 `moe_gating_top_k` 只是代表算子/落点示例；签名相同的算子挂「已知变体」行，不另立文件。
>
> **语料来源**：`ops-transformer/moe/moe_gating_top_k_softmax`（含通用 / 310P / arch35 多变体）。同类可参照 `moe_gating_top_k`、`moe_gating_top_k_softmax_v2`、`moe_gating_top_k_backward`。

---

## 一、三维分类标识（LP8 固定 + SubOp 链）

### LP 循环结构模式

```
类型: LP8(多阶段异构)
描述: 先对 gating logits 做 Softmax(规约型)，再对归一化结果做 TopK(选择排序型)——
      两阶段循环结构本质不同(规约 vs 排序选择)，故为多阶段异构
处理规则: 分解为 SubOp 序列 → 各 SubOp 独立匹配 LP1~LP7 → SubOp 链匹配本融合模式
```

### SubOp 链的 (LP, CP, ES) 列表

```
SubOp1: Softmax(沿 expert 维) → (LP4, CP1, ES2) → 命中原子模式 B01
SubOp2: TopK(选前 k 个 expert) → (LP7, CP1, ES1) → 命中原子模式 H01(选择排序)
```

> Softmax 沿最后一维(num_experts)做 max→exp→sum 归一，属 D 轴规约(LP4)。TopK 按值排序选前 k、输出位置依赖值大小，属选择排序(LP7) ——这是 LP7 特征的典型范例。

### 融合整体的 ES（执行结构）⭐

```
类型: ES4(多阶段UB内) —— 主变体; 个别平台变体退化为 ES3(多阶段WS)
判定依据: 主变体(K_FullLoad/E_K_FullLoad)中 workspaceSize=0, Softmax 输出留
          LocalTensor, TopK 直接读同一 UB buffer, 阶段间无 GM 中转 → ES4
          仅 310P 变体因 UB 小、放不下, 用 GM workspace 中转 → ES3
```

### L1 张量签名（属性参数）

```
输入: x(gating logits)[num_tokens, num_experts] (2D, 或 3D 展平); 可选 finished[num_tokens](bool)
属性: k (1~1024)
输出: y[num_tokens, k](topk 值), expertIdx[num_tokens, k](int32), rowIdx[num_tokens, k](int32)
角色: [data(logits), mask(finished 可选)] → [data(值), index(expert), index(row)]
维度语义: [num_tokens(行), num_experts(规约/选择维)]
```

### L4 关键工程约束（属性参数）

```
是否变长/动态 shape: 支持动态 num_tokens; num_experts 影响是否需列方向分块
是否含 Mask: 可选(finished 标记已完成 token)
是否需要 Index 输出: 有——TopK 输出 expert 索引和 row 索引
是否需要核间通信: 否(各行独立)
关键约束: TopK 输出位置依赖值(排序); softmax/topk 均 IS_REUSE_SOURCE=true 复用源 buffer;
          num_experts 大时需沿列分块(影响是否落 WS)
```

---

## 二、模式总览

| 字段 | 内容 |
|------|------|
| **融合名称** | MoeGatingTopK（Softmax + TopK） |
| **SubOp 链** | Softmax(沿 expert 维) → TopK(选前 k) |
| **阶段数** | 2 |
| **一句话描述** | 对 MoE gating logits 逐行 Softmax 归一，再选 top-k expert，输出 topk 值与 expert/row 索引；主变体中间结果驻 UB 免 GM 往返 |
| **典型算子** | `ops-transformer/moe/moe_gating_top_k_softmax`、`moe_gating_top_k`、`moe_gating_top_k_softmax_v2` |
| **适用条件** | MoE 路由：gating 归一化 + top-k expert 选择的融合 |

---

## 三、SubOp 分解表 ⭐

| 阶段 | SubOp | LP | CP | ES | 命中原子模式 | 输入 → 输出 |
|------|-------|----|----|----|------------|-----------|
| 1 | Softmax（沿 num_experts） | LP4 | CP1 | ES2 | B01 | x[行,experts] → prob(UB) |
| 2 | TopK（选前 k） | LP7 | CP1 | ES1 | H01 | prob(UB) → y/expertIdx/rowIdx |

> 阶段2 强依赖阶段1 输出（TopK 选的是 Softmax 归一后的概率），故为串行依赖链——与 F01 的并列两路不同。

---

## 四、阶段编排与数据流 ⭐

### 4.1 阶段间数据流拓扑

- **编排方式**：串行（Softmax 输出 → TopK 输入），同一行内顺序完成。
- **数据流**（主变体 K_FullLoad）：
  ```
  GM(x 行) ─CopyIn→ UB(gating) ─Softmax(max→exp→sum 归一)→ UB(prob, 覆盖源)
                                                              │
                                  UB(prob) ─TopK(排序选前k)→ UB(y/expertIdx/rowIdx) ─CopyOut→ GM
  ```

### 4.2 阶段间中间结果驻留层级 ⭐（ES3 vs ES4 判定核心，与 F01 对比）

> **本模式是 ES3-vs-ES4 判定的活教材**：同一融合算子，不同平台落点不同。

- **主变体（K_FullLoad / E_K_FullLoad，A2/A3/A5）= ES4**：`GetWorkspaceSize` 返回 0；Softmax 输出留 `LocalTensor`，TopK 直接读同一 UB buffer（且 `IS_REUSE_SOURCE=true` 复用源），阶段间无 GM 中转。成立条件：一行的 logits + softmax 统计量 + topk 候选/临时 buffer 能在 UB 内共存。
- **310P 变体 = ES3**：因 310P 的 UB 较小，单行数据 + topk 排序临时空间放不下，改用 GM workspace（`~kAlign × row × core × (int16+int32)`）中转。
- **判定法则**（可迁移到其他融合算子）：融合默认追求 ES4（UB 内传递省 GM 往返）；**当且仅当**中间结果 + 各阶段 buffer 在目标平台 UB 预算内放不下时，才退化为 ES3 落 WS。**ES3/ES4 由"平台 UB 预算 vs 共存需求"决定，而非算子语义固有**——这正是与 F01（恒 ES4）的关键对比。

### 4.3 公共切分轴

- **公共切分轴 = num_tokens（行维, dim0）**：Softmax 与 TopK 共享行循环，沿 num_tokens 做核间均衡分配。
- per-core：`blockFormer` 行/核；当 num_experts(列)较大时，核内对列再做 `ubLoop` 分块（分块会影响 Softmax 的跨块累加，进而影响是否需 WS）。

---

## 五、阶段间 UB 共存验证（概设层：仅"能否放下"）

> 概设只回答"Softmax 与 TopK 的输入/输出/临时缓冲能否在 UB 预算内共存"，不回答"具体怎么放"。用参数级表达式。设 ubFormer=单次处理行数，E=num_experts，k=topk 数。

**必须同时驻留 UB 的数据项**：

| 数据项 | 来自阶段 | 大小（参数级表达式） | 常驻/流式 |
|--------|---------|-------------------|----------|
| gating 行（双 buffer） | Softmax | `2 × ubFormer × E × sizeof(T)` | per-iter |
| Softmax 统计量（max/sum/expMax） | Softmax | `~3 × ubFormer × 32B`（按行对齐） | per-iter |
| Softmax 临时区 | Softmax | `GetSoftMaxFlashV2*TmpSize(ubFormer,E)` | per-iter |
| prob（归一结果，复用 gating 源） | Softmax→TopK | `IS_REUSE_SOURCE=true` 复用上方 gating buffer | per-iter |
| TopK 值/索引候选区 | TopK | `~ubFormer × (E 对齐) × (sizeof(T)+sizeof(int32))` | per-iter |
| TopK 临时区（排序网络） | TopK | `GetTopKTmpSize(ubFormer,E,k)` | per-iter |
| rowIdx / finished（若有） | TopK / 输入 | `ubFormer × (k + 1) × sizeof(int32/bool)` | per-iter |

**共存约束式**：
```
ubFormer × [2×gating(=prob复用) + 统计量 + softmaxTmp + topk候选 + topkTmp + rowIdx(+finished)] ≤ UB 可用容量
→ 反解 ubFormer 上限；ubFormer ≥ 1 行才可行（ES4 成立的下界）
```
- **判定核心**：一行的 gating(E) + softmax 统计/临时 + topk 候选/临时若能在目标平台 UB 内共存 → ES4（中间 prob 留 UB）；若 **1 行都放不下**（E 极大 + 平台 UB 小，如 310P）→ 退化 ES3，prob 经 GM workspace 中转。
- 超标降级方向：先减小 ubFormer（极限到 1 行）→ 仍超则沿 E（列）分块、Softmax 跨块累加 → 列分块 + 平台 UB 不足共同触发落 WS（即 310P 路径）。

---

## 六、平台相关设计考量

> 本算子语料覆盖 A2/A3/A5(950) 主变体 + 310P + arch35 专用变体，是"同算子多平台落点不同"的范例。

### 以 A3 为基准的设计要点

| 维度 | 如何影响本融合模式的概要设计 |
|------|---------------------------|
| UB 容量（见 hw_params.json） | 约束 ubFormer：E 较大时单次处理行数下降；A3 通常仍可 ES4（prob 留 UB） |
| 同步机制（SetFlag/WaitFlag） | Softmax(V) 与 TopK(V) 同 V-pipe 串行，阶段内 double-buffer 流水；CopyIn/Out 与 Compute 间 MTE-V 同步 |

### 其他平台的概设差异

- **310P（关键反例）**：UB 较小，单行 gating + softmax/topk 临时空间放不下 → 改用 GM workspace（`~kAlign × row × core × (int16+int32)`）中转 prob → **退化为 ES3**。这是本模式 ES3-vs-ES4 判定的活范例。
- **A5（arch35 专用变体）**：Regbase + SIMT。Softmax 的 max/exp/sum 规约、TopK 的比较选择从显式 `for` 简化为 VF 线程映射；统计量/候选值留寄存器，UB 压力下降，更易维持 ES4。**寄存器预算（每 VF 最多 32 RegTensor）需核算**——TopK 排序网络同时保持的候选 RegTensor 较多，k 大时易触顶，必要时分段处理。
- **A6（预留）**：待补充。

---

## 七、已知变体

| 变体 | 触发条件 | 与主模式的差异 |
|------|---------|--------------|
| `moe_gating_top_k_softmax_v2` | 接口升级版 | 输出/属性细节差异，SubOp 链(Softmax→TopK)不变 |
| `moe_gating_top_k` | 无 Softmax 归一 | 退化为单 SubOp(TopK)，不属本融合模式（LP7 原子模式 H01） |
| `moe_gating_top_k_softmax_backward` | 反向梯度 | SubOp 链反向：按 topk 索引散射梯度 + softmax 反向，拓扑不同 |
| 310P 变体 | 平台 UB 小 | prob 落 GM workspace → ES3（见六） |
| finished mask | 传入 finished[num_tokens] | 已完成 token 跳过/置默认，类 mask 语义，常驻单列 |

---

## 八、关键决策记录

| 决策问题 | 选择 | 替代方案 | 理由（含融合 vs 分离的收益量化方向） |
|---------|------|---------|--------------------------------|
| 融合 vs 分离 | 融合（Softmax+TopK 单 kernel） | 两个独立算子 | 免去 Softmax 概率结果落 GM 再重读；收益 ≈ 2×(num_tokens×num_experts×sizeof(T)) GM 往返 |
| 阶段间数据传递 | UB 内传递（ES4，主变体） | 落 GM workspace（ES3） | 一行 gating+临时可共存时 prob 留 UB；延迟 ns 级 vs us 级 |
| prob 是否复用 gating 源 | 复用（IS_REUSE_SOURCE=true） | 另开 buffer | 省 UB，归一为原地变换，源 gating 后续无需保留 |
| ES3/ES4 由谁决定 | 平台 UB 预算 vs 共存需求 | 算子语义固有 | 同算子 A2/A3/A5 走 ES4、310P 走 ES3——驻留层级是平台决策非语义固有（与 F01 恒 ES4 的关键对比） |
