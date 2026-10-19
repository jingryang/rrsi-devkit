# 融合模式 F01：KV-RmsNorm-Rope-Cache

> ⚠️ **范围红线**：本文件严格限定在"概要设计"职责范围内。不包含 TilingData 字段结构、Buffer 大小数值、Kernel 循环代码、API 调用细节。平台硬件参数见 `general_design_common_knowledge.md`。
>
> 🔑 **匹配键 = SubOp 链签名**：`[A01(LP1×CP1×ES4) ∥ B01(LP4×CP1×ES2)] → G01(LP2×CP2×ES1)`（逐元素变换 ∥ D轴规约 → 索引散射写）。**命中此签名即匹配本模式，与算子叫什么名字无关**。文件名里的 `kv_rms_norm_rope_cache` 只是代表算子/落点示例；签名相同的算子（qkv/dequant 等）挂「已知变体」行，不另立文件。
>
> **语料来源**：`ops-transformer/posembedding/kv_rms_norm_rope_cache`（arch35 实现）。同类可参照 `qkv_rms_norm_rope_cache`、`dequant_rope_quant_kvcache`、`rope_quant_kvcache`。

---

## 一、三维分类标识（LP8 固定 + SubOp 链）

### LP 循环结构模式

```
类型: LP8(多阶段异构)
描述: 同一输入 kv 的 D 维被拆成两段(Dk/Dv)走不同计算路径(RoPE/RMSNorm)，
      再各自按 index 散射写入不同 cache——阶段间依赖拓扑变化，故为多阶段异构
处理规则: 分解为 SubOp 序列 → 各 SubOp 独立匹配 LP1~LP7 → SubOp 链匹配本融合模式
```

### SubOp 链的 (LP, CP, ES) 列表

```
SubOp1: RoPE(对 kv 的 Dk 段) → (LP1, CP1, ES4) → 命中原子模式 A01
SubOp2: RMSNorm(对 kv 的 Dv 段) → (LP4, CP1, ES2) → 命中原子模式 B01
SubOp3: ScatterUpdate(按 index 写 cache) → (LP2, CP2, ES1) → 命中原子模式 G01
```

> 注：真实代码执行顺序为 RoPE → RMSNorm，两者作用于同一行 kv 的不同 D 段（Dk 走 RoPE、Dv 走 RMSNorm），相互独立无数据依赖，各自算完即散射写出。这与 E01（融合算子参考）里"规约→逐元素→搬运"的示意顺序略有出入——以本文件实测为准。

### 融合整体的 ES（执行结构）

```
类型: ES4(多阶段UB内)
判定依据: RoPE/RMSNorm 的输出在 UB(LocalTensor) 内完成后直接散射写 GM cache，
          阶段间无 GM workspace 中转（workspace 仅 32B 元数据）
```

### L1 张量签名（属性参数）

```
输入: kv[B,1,S,D] (D=Dk+Dv), gamma[Dv], cos/sin[B,1,S,Dk]或[B,1,1,Dk], index[B,S](int64)
      可选: k_rope_scale/c_kv_scale/offset(量化, FP32)
输出/inout: k_cache, ckv_cache (输入输出复用同地址); 可选输出 k_rope/c_kv
角色: [data(kv), weight(gamma), data(cos/sin 广播), index, cache(inout)]
维度语义: [B, 1, S, D]——固定 numHead=1; D 拆 Dk(RoPE)+Dv(RMSNorm)
```

### L4 关键工程约束（属性参数）

```
是否变长/动态 shape: 支持 unknown rank, 但无通用 TND varlen; kv 必须 4D
是否含 Mask: 无（index=-1 表示跳过该行写出，类 mask 语义）
是否需要 Index/Cache 写: 有(核心特征)——index 驱动散射写 k_cache/ckv_cache
是否需要核间通信: 否
关键约束: cos/sin 的 S 维可广播; cache 5 种 layout(Norm/PA/PA_NZ/PA_BLK_BNSD/PA_BLK_NZ),
          NZ 模式需 32B 对齐; 支持 K/V 独立量化(INT8/FP8 等)
```

---

## 二、模式总览

| 字段 | 内容 |
|------|------|
| **融合名称** | KV-RmsNorm-Rope-Cache |
| **SubOp 链** | RoPE(Dk段) ∥ RMSNorm(Dv段) → ScatterUpdate(按 index 写 cache) |
| **阶段数** | 3（RoPE / RMSNorm 可视为并列两路 + 散射写） |
| **一句话描述** | 对 KV 输入的 D 维分段做 RoPE 与 RMSNorm，结果按 index 散射写入 KV cache，中间结果全程驻 UB，免 GM 往返 |
| **典型算子** | `ops-transformer/posembedding/kv_rms_norm_rope_cache`、`qkv_rms_norm_rope_cache`、`dequant_rope_quant_kvcache` |
| **适用条件** | 推理 KV cache 写入场景：归一化 + 位置编码 + 按槽位(index)写 cache 的融合 |

---

## 三、SubOp 分解表 ⭐

| 阶段 | SubOp | LP | CP | ES | 命中原子模式 | 输入 → 输出 |
|------|-------|----|----|----|------------|-----------|
| 1 | RoPE（interleave 复数旋转） | LP1 | CP1 | ES4 | A01 | kv[...,Dk] + cos/sin → k_rope(UB) |
| 2 | RMSNorm（FP32 规约 + gamma 缩放） | LP4 | CP1 | ES2 | B01 | kv[...,Dv] + gamma → c_kv(UB) |
| 3 | ScatterUpdate（index 驱动写） | LP2 | CP2 | ES1 | G01 | k_rope/c_kv + index → k_cache/ckv_cache(GM) |

> 阶段1与阶段2作用于同一行 kv 的不同 D 段，彼此独立（无阶段间数据依赖），可并行编排；阶段3 是两路各自的出口。

---

## 四、阶段编排与数据流 ⭐

### 4.1 阶段间数据流拓扑

- **编排方式**：阶段1(RoPE) 与阶段2(RMSNorm) 对同一行的不同 D 段独立计算，无相互依赖，可在同一 per-iter 循环内并列处理；各自算完后立即走阶段3（按同一 index 散射写各自的 cache）。
- **数据流**：
  ```
  GM(kv[...,Dk]) ─CopyIn→ UB(rope) ┐
  GM(cos/sin)    ─CopyIn→ UB        ├─Compute(Vector)→ UB(k_rope)  ─Scatter(index)→ GM(k_cache)
  GM(kv[...,Dv]) ─CopyIn→ UB(x)    ┐
  GM(gamma常驻)  ───────────────────├─Compute(VF FP32)→ UB(c_kv)   ─Scatter(index)→ GM(ckv_cache)
  ```

### 4.2 阶段间中间结果驻留层级 ⭐（ES3 vs ES4 判定核心）

- **本模式 = ES4（UB 内传递）**：RoPE/RMSNorm 输出在 UB 完成后直接散射写 GM cache，阶段间**不经 GM workspace 中转**（workspace 仅 32B 元数据）。
- 判定依据：单行的中间结果（k_rope 占 Dk、c_kv 占 Dv）连同输入、gamma、cos/sin、归约临时缓冲，总量可在目标平台 UB 预算内共存 → 无需落 WS。这是 ES4 的典型成立条件。

### 4.3 公共切分轴

- **公共切分轴 = B×S（行维）**：RoPE 与 RMSNorm 共享同一行循环框架，沿 B×S 展开做核间均衡分配。
- per-core 循环：`blockFactor` 行/核，核内 `ubLoop = ceil(blockFactor / ubFactor)`，每次处理 ubFactor 行；同一 tile 内先 RoPE 段后 RMSNorm 段、tile 粒度一致。

---

## 五、阶段间 UB 共存验证（概设层：仅"能否放下"）

> 用参数级表达式验证各阶段数据能否在 UB 预算内共存。设 ubFactor=单次处理行数，T_KV=输入元素字节。

**必须同时驻留 UB 的数据项**：

| 数据项 | 来自阶段 | 大小（参数级表达式） | 常驻/流式 |
|--------|---------|-------------------|----------|
| gamma | RMSNorm | `Dv × sizeof(T_KV)` | **常驻**（全程复用） |
| 输入 x（双 buffer） | RoPE+RMSNorm | `2 × ubFactor × max(Dk,Dv) × sizeof(T_KV)` | per-iter |
| cos/sin 4 分量（双 buffer） | RoPE | `2 × ubFactor × 4 × (Dk/2) × sizeof(T_KV)` | per-iter |
| 输出（双 buffer） | RoPE+RMSNorm | `2 × ubFactor × max(Dk,Dv) × sizeof(T_KV)` | per-iter |
| RoPE FP32 工作区 | RoPE | `2 × VL_FP32 × sizeof(float)` | per-iter |
| RMSNorm 规约工作区 | RMSNorm | `ubFactor × Dv × sizeof(float)` | per-iter |
| 量化 scale/offset（若量化） | 散射写 | `(4×(Dk/2) + 2×Dv) × sizeof(float)` | **常驻** |

**共存约束式**：
```
gamma + 量化参数(常驻) + ubFactor×[2×inX + 2×cosSin + 2×out + rmsNormWsp] + ropeWsp ≤ UB 可用容量
→ 反解 ubFactor 上限；ubFactor ≥ 1 行才可行
```
- 超标降级方向：减小 ubFactor（极限到 1 行）→ 若 1 行仍超（极大 D），切换到 **recompute 模板族**（D 维分块循环 + 二分折叠累加，见「已知变体」），而非脱离本模式。full_load 与 recompute 是同模式下并列的两个模板族。

---

## 六、平台相关设计考量

> ⚠️ 本算子真实支持 **A2/A3（910b/910_93）+ A5（950）+ kirin（x90/9030）** 四类平台（语料 op_def.cpp 的 AddConfig）。模板族按平台分流：A2/A3 走 **DS 模板族**（非 regbase），A5 走 **regbase full_load / recompute**，kirin 单独 config。以下 A3 要点对 DS 模板族适用，A5 段描述 regbase 差异。

### 以 A3 为基准的设计要点（DS 模板族，910b/910_93）

| 维度 | 如何影响本融合模式的概要设计 |
|------|---------------------------|
| UB 容量（见 hw_params.json） | 约束 ubFactor：gamma+量化参数常驻后，剩余空间决定单次处理行数 |
| 同步机制（SetFlag/WaitFlag） | RoPE/RMSNorm 计算与散射写（MTE3）之间的流水同步 |

### 其他平台的概设差异

- **A5（本模式主平台）**：Regbase + SIMT。RoPE/RMSNorm 的逐元素/规约从显式 `for` 简化为 VF 线程映射；中间结果留寄存器，UB 压力主要来自 gamma/cos-sin/量化参数常驻项。**寄存器预算（每 VF 最多 32 RegTensor）需与 UB 预算同时核算**——RoPE 的 cos/sin 4 分量 + RMSNorm 的输入/累加器/gamma 同时在寄存器易触顶，必要时将 RoPE 与 RMSNorm 拆成独立 VF。cache 的 NZ layout 需配合 Fixpipe/对齐处理。
- **A6（预留）**：待补充。

---

## 七、已知变体

| 变体 | 触发条件 | 与主模式的差异 |
|------|---------|--------------|
| **full_load 模板族** | D 维（连同各 buffer）能在 UB/寄存器预算内整行全载 | 整行 D 一次载入算完；TilingData 含 `inUbSize/outUbSize/dkAlign/halfDk` 类字段。对应 regbase full load（语料 TilingKey 10000） |
| **recompute 模板族** | D 维过大，全载超 UB/寄存器预算 | D 维分块循环 + **二分折叠累加**重算；TilingData 含 `ubFactorDvTail/ubFactorDkTail/ubFactorDvLoopCountCeil/basicBlockLoop/mainFoldCount` 类字段。对应 regbase recompute（语料 TilingKey 20000）。**这是 full_load 放不下时的并列模板族，非简单"降级"——概设须显式列出，否则下游漏掉 D 超大实现路径** |
| **DS 模板族（非 regbase 平台）** | 目标平台为 A2/A3（910b/910_93） | 走非 regbase 的 DS 实现（语料 TilingKey 1000~5011 共 18 变体，按 cacheMode×量化开关展开） |
| 量化 cache（dequant_rope_quant_kvcache） | k_cache/ckv_cache 为 INT8/FP8 | 散射写前增量化（scale/offset），常驻量化参数占 UB |
| QKV 三路（qkv_rms_norm_rope_cache） | 同时处理 Q/K/V | SubOp 链扩展为三路并列，公共切分轴不变 |
| PA 分页 cache（PA/PA_NZ/PA_BLK_*） | KV cache 按 block 分页存储 | index 语义变为 block 内偏移，散射写地址计算更复杂；NZ 需 32B 对齐 |
| cos/sin 广播 | cos/sin 为 [B,1,1,Dk] | S 维广播，cos/sin 常驻单行即可，省 UB |

> **模板族路由优先级**（语料 tiling.h priority 常量）：DS(1000，A2/A3) < full_load(2000，A5 优先) < recompute(3000，A5 兜底)。同平台内 full_load 优先于 recompute，仅当 D 全载超预算才落 recompute。

---

## 八、关键决策记录

| 决策问题 | 选择 | 替代方案 | 理由（含融合 vs 分离的收益量化方向） |
|---------|------|---------|--------------------------------|
| 融合 vs 分离 | 融合（RoPE+RMSNorm+写 cache 单 kernel） | 三个独立算子 | 免去 RoPE/RMSNorm 中间结果落 GM 再重读；收益 ≈ 2×(B×S×D×sizeof(T)) GM 往返 |
| 阶段间数据传递 | UB 内传递（ES4） | 落 GM workspace | 单行中间结果可与各 buffer 共存，无需 WS；延迟 ns 级 vs us 级 |
| RoPE 与 RMSNorm 是否合 VF（A5） | 视寄存器预算 | 强制合并 | 合并省调度但 RegTensor 易超 32 触发 spill；超则拆分摊压力 |
| index=-1 行的处理 | 跳过散射写 | 写默认值 | 跳过避免污染 cache，符合 PA 场景"空槽不写"语义 |
