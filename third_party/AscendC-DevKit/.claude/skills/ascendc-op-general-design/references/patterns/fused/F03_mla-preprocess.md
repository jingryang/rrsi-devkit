# 融合模式 F03：MLA-Preprocess（Norm-MatMul-Rope-Cache 交替链）

> ⚠️ **范围红线**：本文件严格限定在"概要设计"职责范围内。不包含 TilingData 字段结构、Buffer 大小数值、Kernel 循环代码、API 调用细节。平台硬件参数见 `general_design_common_knowledge.md`。
>
> 🔑 **匹配键 = SubOp 链签名**：`[A01(RMSNorm+quant)→C01→A01→C01→A01(RoPE)→C01]→G01`（Vector 归一/量化 与 Cube 投影**交替多趟** → 按 slot 散射写 KV cache）。**命中此链拓扑即匹配本模式，与算子叫什么名字无关**。区别于 F01（纯 Vector 无 Cube）与 F04（纯 Cube+激活无规约/无散射）的关键：**本模式 Vector 与 Cube 交替、且末端含 index 散射写 cache**。
>
> **语料来源**：`ops-transformer/attention/mla_preprocess_v2`（实地核实 op_def 24 输入/5 输出 + kernel `ProcessCube`/`ProcessVector` 分离 + `RmsNormAndRopeConvergence1`）。同类可参照 `mla_preprocess`、`mla_prolog`。

---

## 一、三维分类标识（LP8 固定 + SubOp 链）

### LP 循环结构模式

```
类型: LP8(多阶段异构)
描述: 同一行 hidden_state 经【RMSNorm+量化→下投影MatMul→RMSNorm+量化→上投影MatMul
      →RMSNorm+RoPE→wuk MatMul】多趟 Vector/Cube 交替变换，最后按 slot_mapping
      散射写入 KV cache——阶段间依赖拓扑反复在 Vector↔Cube 间切换，多阶段异构
处理规则: 分解为 SubOp 序列 → 各 SubOp 独立匹配 LP1~LP7 → SubOp 链匹配本融合模式
```

### SubOp 链的 (LP, CP, ES) 列表

```
SubOp1: RMSNorm+量化(对 hidden_state) → (LP4, CP1, ES2) → 命中原子模式 B01(量化变体)
SubOp2: MatMul(wdqkv 下投影, INT8) → (LP6, CP3, ES1) → 命中原子模式 C01
SubOp3: RMSNorm+量化(对下投影输出) → (LP4, CP1, ES2) → 命中原子模式 B01(量化变体)
SubOp4: MatMul(wuq 上投影) → (LP6, CP3, ES1) → 命中原子模式 C01
SubOp5: RMSNorm+RoPE(convergence, 对 q/k 的 rope 段) → (LP1+LP4, CP1, ES4) → A01+B01
SubOp6: MatMul(wuk) → (LP6, CP3, ES1) → 命中原子模式 C01
SubOp7: ScatterCache(按 slot_mapping 写 kv_cache/kr_cache) → (LP2, CP2, ES1) → G01
```

> 注：真实 kernel 用 `ProcessCube()`（承载 SubOp2/4/6 三趟 MatMul，走 L0A/L0B/L0C Cube 流水）与 `ProcessVector()`（承载 SubOp1/3/5 的 RMSNorm/量化/RoPE）**分离编排**，两者经 GM 中间张量（s1Gm/s2Gm/s3Gm 类）串接。散射写 `slotValue == -1` 时跳过该行（与 F01 同语义）。

### 融合整体的 ES（执行结构）

```
类型: ES3(多阶段WS)
判定依据: Cube 投影输出（如下投影结果）经 GM workspace 中转给后续 Vector 阶段，
          Vector↔Cube 交替的中间结果无法全程驻 UB（投影输出维度大 + Cube 写出走 GM），
          故落 workspace——这是与 F01(ES4 恒 UB 内) 的本质分野
```

### L1 张量签名（属性参数）

```
输入(实测 24, REQUIRED): input(hidden), gamma_0/1/2 + beta_0/1(norm 权重),
      quant_scale_0/1 + quant_offset_0/1(量化参数), wdqkv/wuq/wuk(三组投影权重, NZ),
      descale_0/1 + bias_0/1(反量化), cos/sin(RoPE), kv_cache/kv_cache_rope(inout cache),
      slot_mapping(散射 index, int32), ctkv_scale/q_nope_scale(输出量化)
输出(实测 5): q_out, kv_cache_out, q_rope_out, kr_cache_out, q_down_out
角色: [data(hidden), weight(gamma/beta×3组), weight(wdqkv/wuq/wuk), data(cos/sin 广播),
       index(slot_mapping), cache(inout), 量化参数 ×多组]
维度语义: 沿 token 行(B×S)切分; D 维经下投影压缩→上投影展开; rope 段单独 RoPE
```

### L4 关键工程约束（属性参数）

```
是否变长/动态 shape: 支持 DynamicShape + DynamicRank
是否含 Mask: 无（slot_mapping=-1 表示跳过该行写出，类 mask 语义）
是否需要 Index/Cache 写: 有(核心特征)——slot_mapping 驱动散射写 kv_cache/kr_cache
是否需要核间通信: 否（但 Cube/Vector 跨 ProcessCube/ProcessVector 需经 GM 同步）
关键约束: 三组投影权重 NZ layout; INT8 量化 + per-token/per-tensor 双量化模式;
          cacheMode 0-3 × 输入/权重/cache 三路 DataFormat(ND/NZ) 组合 → 模板膨胀;
          仅 A2/A3(910b/910_93) 实现
```

---

## 二、模式总览

| 字段 | 内容 |
|------|------|
| **融合名称** | MLA-Preprocess（Norm-MatMul-Rope-Cache 交替链） |
| **SubOp 链签名** | `[A01(norm+quant)→C01→A01→C01→A01(rope)→C01]→G01` |
| **阶段数** | 7（3 趟 Vector 归一/量化/rope + 3 趟 Cube 投影 + 1 散射写） |
| **一句话描述** | MLA 注意力前处理：hidden 经多趟 RMSNorm+量化与 MatMul 投影交替，q/k 做 RoPE，最后按 slot 散射写 KV cache；Cube 与 Vector 交替、中间结果经 GM 中转 |
| **典型算子** | `ops-transformer/attention/mla_preprocess_v2`、`mla_preprocess`、`mla_prolog` |
| **适用条件** | MLA/低秩投影类注意力前处理：归一化 + 低秩下/上投影 + 位置编码 + 写 KV cache 的融合 |

---

## 三、SubOp 分解表 ⭐

| 阶段 | SubOp | LP | CP | ES | 命中原子模式 | 输入 → 输出 |
|------|-------|----|----|----|------------|-----------|
| 1 | RMSNorm + 量化（hidden） | LP4 | CP1 | ES2 | B01(量化变体) | input + gamma_0/quant_scale_0 → 量化激活(UB→GM) |
| 2 | MatMul 下投影（wdqkv, INT8） | LP6 | CP3 | ES1 | C01 | 量化激活 + wdqkv → 下投影(GM) |
| 3 | RMSNorm + 量化（下投影输出） | LP4 | CP1 | ES2 | B01(量化变体) | 下投影 + gamma_1/quant_scale_1 → 量化(GM) |
| 4 | MatMul 上投影（wuq） | LP6 | CP3 | ES1 | C01 | 量化 + wuq → 上投影 q(GM) |
| 5 | RMSNorm + RoPE（convergence） | LP1+LP4 | CP1 | ES4 | A01+B01 | 投影输出 + gamma_2/cos/sin → q_rope/k_rope(UB) |
| 6 | MatMul（wuk） | LP6 | CP3 | ES1 | C01 | → kv 投影 |
| 7 | ScatterCache（slot 驱动写） | LP2 | CP2 | ES1 | G01 | q/kv/rope + slot_mapping → kv_cache/kr_cache(GM) |

> 阶段在 Vector(1/3/5) 与 Cube(2/4/6) 间反复切换，靠 GM 中间张量串接；阶段7 是各路出口，slot=-1 跳过。

---

## 四、阶段编排与数据流 ⭐

### 4.1 阶段间数据流拓扑

- **编排方式**：真实 kernel 拆成 `ProcessCube()` 与 `ProcessVector()` 两条执行体——Cube 体专做 SubOp2/4/6 的 MatMul（走 L0A/L0B/L0C 分形流水），Vector 体专做 SubOp1/3/5 的 RMSNorm/量化/RoPE。两者**交替推进**，靠 GM 中间张量（s1Gm/s2Gm/s3Gm 类）传递每趟结果，并以 SetFlag/WaitFlag 跨体同步。
- **数据流**：
  ```
  hidden ─V:RMSNorm+quant→ GM(s1) ─C:MatMul(wdqkv)→ GM(s2)
         ─V:RMSNorm+quant→ GM ─C:MatMul(wuq)→ GM(s3)
         ─V:RMSNorm+RoPE→ UB(q_rope/k_rope) ─C:MatMul(wuk)→ kv
         ─Scatter(slot_mapping)→ GM(kv_cache / kr_cache)
  ```

### 4.2 阶段间中间结果驻留层级 ⭐（ES3 vs ES4 判定核心）

- **本模式 = ES3（多阶段 GM workspace）**：与 F01 最大的不同。Cube 投影输出维度大、且 Cube 单元结果须先落 GM 才能被下一趟 Vector 读入，**无法像 F01 那样全程驻 UB**。
- 判定依据：①投影矩阵 wdqkv/wuq/wuk 的输出张量超 UB 单趟容量；②Cube(L0C)→Vector(UB) 的跨单元传递经 GM 最直接；③三趟交替使中间态无法压缩进单次 UB 预算。故落 workspace（s1/s2/s3）。

### 4.3 公共切分轴

- **公共切分轴 = token 行（B×S）**：各 SubOp 共享 token 行循环；Cube 的 M 轴 = token 行，Vector 沿同一行展开。
- per-core：按 token 行均衡分核（vectorBlockIdx × row_work）；Cube 侧按 [M,K,N] 分形 basic block。

---

## 五、阶段间 UB/Workspace 共存验证（概设层：仅"能否放下"）

> 与 F01 不同，本模式核心约束在 **workspace 分配**（中间投影结果）而非 UB 单趟共存。

**必须落 GM workspace 的中间项**：

| 数据项 | 来自阶段 | 说明 | 驻留 |
|--------|---------|------|------|
| 下投影输出 (s1/s2) | SubOp2 | Cube 写出，供 SubOp3 Vector 读 | **GM workspace** |
| 上投影输出 (s3) | SubOp4 | 供 SubOp5 RoPE 读 | **GM workspace** |
| gamma/beta×3 组 | 各 RMSNorm | 全程复用 | UB 常驻 |
| 量化 scale/offset×多组 | 各量化 | per-token/per-tensor | UB 常驻 |
| cos/sin | SubOp5 RoPE | 单行 | per-iter UB |

**共存约束式（概设级）**：
```
workspace 总量 = Σ(各趟投影输出张量字节)  ≤ 平台 workspace 预算
单趟 UB = norm 权重常驻 + 量化参数常驻 + 当前趟 tile 输入/输出/规约工作区 ≤ UB 可用容量
→ Vector 趟与 Cube 趟分别核算；交替点经 GM 解耦，故不要求两者 UB 同时共存
```
- 与 F01 的对照：F01 因中间态小可全程驻 UB（ES4）；本模式因 Cube 投影中间态大，**必须经 GM 中转（ES3）**——这是同为"norm+rope+cache"语义但 ES 不同的活范例。

---

## 六、平台相关设计考量

> ⚠️ 本算子真实仅支持 **A2/A3（910b/910_93）**（语料 op_def 仅 `AddConfig("ascend910b")` + `AddConfig("ascend910_93")`），无 A5/310p/kirin config。

### 以 A3 为基准的设计要点

| 维度 | 如何影响本融合模式的概要设计 |
|------|---------------------------|
| Cube + Vector 双单元 | ProcessCube/ProcessVector 分体编排，跨单元经 GM + SetFlag/WaitFlag 同步——融合收益来自省去算子间 GM 往返，但内部仍有 Cube↔Vector 的 GM 中转（ES3 本质） |
| UB 容量（见 hw_params.json） | 约束单趟 Vector 的 tile 行数；norm 权重×3 组 + 量化参数常驻后决定 |
| L0A/L0B/L0C 容量 | 约束 Cube 投影的分形 basic block 大小 |
| workspace 预算 | 决定可否容纳 3 趟投影中间张量；不足则需减小 token tile |

### 其他平台的概设差异

- **A5（未实现，预留）**：若移植，Regbase 可把部分 Vector 中间结果留寄存器、减少 GM 中转，但三趟大投影输出仍大概率落 GM，ES3 性质难改。
- **A6（预留）**：待补充。

---

## 七、已知变体

| 变体 | 触发条件 | 与主模式的差异 |
|------|---------|--------------|
| **量化模式（PER_TOKEN_SYMM / PER_TENSOR_ASYMM）** | quant_mode attr | 量化粒度不同 → 量化参数 buffer 与反量化分支不同；属 B3 量化属性，按差分清单记录不另立 |
| **cacheMode 0-3** | cache_mode attr | KV cache 存储布局（含 PA 分页）；散射写地址计算随 mode 变 |
| **三路 DataFormat（ND/NZ 组合）** | 输入/权重/cache 各自 ND 或 NZ | 模板膨胀主因（语料 MLAOperation 模板按 `<dtype, cacheMode, FmtA, FmtB, FmtC, QuantMode>` 展开）；NZ 需对齐 |
| **mla_prolog（轻量变体）** | 仅 RMSNorm→MatMul→RoPE，无多趟交替 | SubOp 链缩短为 `A01→C01→A01`，可视为本模式的前缀子链 |
| **do_rms_norm=false** | 跳过归一化 | SubOp1/3 退化，链缩短 |

> **与 F01 的边界**：F01 = 纯 Vector（RoPE∥RMSNorm）+ 散射，ES4 恒 UB 内，无 Cube；F03 = Vector/Cube 交替多趟投影 + 散射，ES3 经 GM。二者都含"norm+rope+写 cache"语义，但**有无 Cube 投影**是分流键——这正是"匹配链签名而非算子名"的价值：同含 RoPE+RMSNorm+cache，签名里有没有 C01 决定落 F01 还是 F03。

---

## 八、关键决策记录

| 决策问题 | 选择 | 替代方案 | 理由（含融合 vs 分离的收益量化方向） |
|---------|------|---------|--------------------------------|
| 融合 vs 分离 | 融合（norm+投影+rope+写 cache 单算子） | 6+ 个独立算子 | 免去每趟 norm/投影/rope 中间结果在算子间反复落 GM 再重读；收益 ≈ 多趟 (token×D×sizeof) 的算子边界 GM 往返 |
| Cube/Vector 编排 | 分体 ProcessCube + ProcessVector，经 GM 串接（ES3） | 强行单体 UB 内传递 | 投影输出大无法全驻 UB，分体可让 Cube/Vector 各自打满流水；代价是接受 Cube↔Vector 的 GM 中转 |
| 中间结果落 GM vs UB | 落 GM workspace（ES3） | 全 UB（ES4，如 F01） | 三趟投影中间态超 UB 预算，必须落 GM——这是与 F01 的本质设计分野 |
| slot=-1 行处理 | 跳过散射写 | 写默认值 | 与 F01 一致，避免污染 cache，符合空槽不写语义 |
