# L4 FA 注意力家族设计规范

> **这份文件承载的是「L2/L3 规范管不到、但决定 FA 类算子成败」的部分。**
>
> L4 Flash-Attention 家族（`mha` / `gqa` / `mla` / `sparse_flash_attention` / `mla_prolog`）
> 都是 `softmax(Q·Kᵀ·scale)·V` 的注意力融合算子，`category: FusedComposite`，`difficulty: L4`。
> 它们和 L1/L2/L3 有三点结构性不同，直接决定了用例与文档要怎么写：
>
> 1. **固定 4D、只有 fp16/bf16**：没有 1D~5D 维度档、没有整型、inf/nan 特殊值没有意义。
>    → 校验器已对 `L4` 关闭 G10 的对齐/特殊值/维度数启发式，换成 **G10-scenario**（场景 + head dim）。
> 2. **场景驱动，不是骨架驱动**：20 例按 prefill / decode / cross / MTP / causal 的计算模式铺，
>    维度取真实 head dim（64/128/256），不套 L1 的 shape/dtype/对齐 20 行骨架。
> 3. **有 shape 之外的语义等价不变量**：MLA 的 `v == k_nope`、sparse 的 `value == key[..., :Dv]`，
>    G15（只看 shape 耦合）检测不到，G13（喂独立随机数）不会崩但数值无意义 —— **只能靠文字兜底**。
>
> 另有一条格式差异：**L4 FA 家族的 `desc.md` 不写 `## 6. 额外信息`**，只有前五节
> （§1 简介 / §2 定义 / §3 接口 / §4 精度 / §5 golden）。注意力算子没有可复现的 `.so`
> 直调示例，§6 无信息量；G6 门对 L4 期望五节，出现第 6 节判 FAIL。
> （非 FA 类仍有 §6 调用示例，但也**不写** `torch.ops.load_library(...)` 与「接口契约」收尾
> blockquote —— 见 `format-contract.md §5.3`。）
>
> 本文是**规范**：下列写法是 FA 类算子的通行做法。开始前必读，动笔时对号入座。

---

## 0. 先认清 FA 类的失败模式

FA 类不像 L2/L3 那样在 `--run-golden` 时大面积报「造数造不出合法组合」——
注意力的输入全是浮点张量 + 少量 float/bool/str/int attr，通用随机造数**跑得起来**。
它的坑在别处：

```
NaN 出现在 is_causal=True 且 S > S_kv 时（整行被 mask → softmax 0/0）
数值无意义：MLA 喂了 v != k_nope 的随机数，golden 不崩但结果没物理含义
G13 绿得空洞：真实 head dim 下单例超 4M 被 skip（mla 18/20、mla_prolog 20/20 skip）
sparseIndices 越界：随机 int32 落到 [0, S_kv-1] 之外 → G13-unsynth（预期，非缺陷）
```

**关键推论**：FA 类的正确性主要靠 **golden 实现里的保护** + **desc.md 里写清的不变量**，
校验门只能证明「跑得起来 / 有没有写下来」，证明不了「数值对不对」。

---

## 1. 注意力符号维度 —— 先起名，再写 shape

和 L2/L3 一样，支持范围表的行名必须是**符号维度**，不是「query 各维大小」。
FA 家族的符号维度是固定的一套：

| 符号 | 含义 | 出现在 |
|---|---|---|
| `B` | batch | 全部 |
| `S` | query 序列长度 | 全部 |
| `S_kv` | key/value 序列长度 | 全部（自注意力时 `S == S_kv`） |
| `N` / `N_q` | 注意力头数 / query 头数 | MHA 用 `N`；GQA/MLA 用 `N_q` |
| `N_kv` | KV 头数 | GQA（`N_q % N_kv == 0`）、MLA、sparse |
| `D` | 每头维度 | MHA / GQA |
| `d_nope` / `d_rope` | MLA 的 nope / rope 分量 | MLA（`D_qk = d_nope + d_rope`，V 维 = `d_nope`） |
| `Dk` / `Dv` | sparse 的 K 维 / V 维（可不同） | sparse_flash_attention |
| `topK` | sparse 每 query 选取的 KV 数 | sparse_flash_attention |
| `G` | 分组比 `N_q / N_kv` | GQA / sparse |

各算子的 shape 骨架（BSND layout）：

```
MHA:   query [B, S, N, D]        key/value [B, S_kv, N, D]          → y [B, S, N, D]
GQA:   query [B, S, N_q, D]      key/value [B, S_kv, N_kv, D]       → y [B, S, N_q, D]   (N_q % N_kv == 0)
MLA:   q_nope [B,S,N_q,d_nope] q_rope [B,S,N_q,d_rope]
       k_nope [B,S_kv,N_kv,d_nope] k_rope [B,S_kv,N_kv,d_rope] v [B,S_kv,N_kv,d_nope]   → y [B,S,N_q,d_nope]
sparse:query [B,S1,N1,Dk] key [B,S2,N2,Dk] value [B,S2,N2,Dv]
       sparseIndices [B,S1,N2,topK](int32)                          → y [B,S1,N1,Dv]
```

表后必须有一行 `约束：` 集中声明跨输入关系（G15 会检查 ≥3 输入是否有这一行）。

---

## 2. 场景覆盖矩阵 —— 20 例按计算模式铺

FA 类的 20 例不是「dtype × 规模 × 对齐 × 值域 × 维度 × 特殊值」六维骨架，而是按
**注意力计算场景**铺。校验器的 **G10-scenario** 就统计这些 slug（写进 note）与 head dim 覆盖。

| 场景 slug | 含义 | 典型 shape 特征 |
|---|---|---|
| `prefill` | 首 token 全量计算 | `S == S_kv`，S 与 S_kv 同量级（128~1024） |
| `decode` | 增量推理 | `S == 1`，`S_kv` 大（512~4096） |
| `cross` | 交叉注意力 | `S != S_kv`（如 Sq=128, Skv=256） |
| `MTP` | multi-token prediction | `S == 2 或 4`，`S_kv` 大 |
| `causal` | 因果掩码 | `is_causal=True`，配 prefill / MTP |

**覆盖要求（G10-scenario 会 warn 若不足）**：
- prefill / decode / cross / MTP / causal 至少命中 **3 类**；
- head dim（`D` / `d_nope` 等最后一维）至少覆盖 **64/128/256 中 2 档**。

dtype 只有 `{float16, bfloat16}`，两者都要覆盖；Q/K/V 三者 dtype 必须一致（同一例三列相同）。
note 语法沿用 §2.4 但值域档换成场景 slug，例如：
```
S-float16-B2S128N8D64-prefill-causal
M-float16-B1S1Skv2048N32D128-decode-single-batch
L-bfloat16-B96Sq2Skv4096N32D128-MTP-large-batch-causal
```

**不写 `| baseline_kernels: ...`**（下游 profiling 回填的度量，生成侧无法测量）——
从 cann-bench 取材时务必把这段后缀删掉（examples/level4/* 已删）。

---

## 3. 按角色分配 value_range

| 输入角色 | 值域策略 | 说明 |
|---|---|---|
| **Q / K / V 数据主体** | `[-1, 1]` 高斯常态 | 注意力输入约定就是标准正态量级 |
| **全零退化例** | `[0, 0]` | 保留 1 例全零输入（softmax(0)=均匀，验证退化正确性）。三列同值域即可 |
| **scaleValue（attr）** | `-1.0`（auto=1/√D）与显式 `≈1/√D`（如 D=128 → `0.08838`） | 两种取值都要覆盖：auto 分支 + 显式分支 |
| **sparseIndices（int32 输入）** | **合法索引带 `[0, S_kv-1]`** | 上界 `hi+1` 必须等于某真实维（G14 会校验）。但通用随机造数**造不出「同 query 内索引互异」**，故 §5 |
| **is_causal / inputLayout（attr）** | 见 §4 / §6 | bool / str，两值都要覆盖 |

GQA 特有：不设「特殊值槽位」，改用**退化行**覆盖分组比边界 —— 至少各留 1 例
`N_kv == 1`（MQA）与 `N_kv == N_q`（退化 MHA），外加常态 `1 < N_kv < N_q`（如 G=4）。

---

## 4. is_causal 约束 + 全 mask 行 NaN 保护（最容易漏）

**约束**：`is_causal=True` 时要求 `S ≤ S_kv`。否则右下角对齐的因果掩码会把某些 query 行
**整行**置 -inf，softmax 得 0/0 = **NaN**。这条必须写进 desc.md 的「规则与约束」与「支持范围」的 `约束：` 行。

**保护（golden.py 必带）**：即便满足 `S ≤ S_kv`，稳妥起见 golden 也应对「整行 -inf」加显式保护，
把该行权重置 0（对齐 cann-bench 的做法）：

```python
scores = scores.masked_fill(causal_mask, float('-inf'))
# 全 mask 行 (整行 = -inf) 在 softmax 时得 0/0 = NaN，显式保护 → 全 mask 行权重置 0
scores_max = scores.max(dim=-1, keepdim=True).values
all_masked = torch.isinf(scores_max) & (scores_max < 0)
attn_weights = torch.nn.functional.softmax(scores, dim=-1)
attn_weights = torch.where(all_masked, torch.zeros_like(attn_weights), attn_weights)
```

> **desc.md §5 展示 golden 可以省略这段保护**，只写主干 `softmax(scores)`，以突出核心公式；
> 但 **`golden.py` 必须内联它**，否则 `--run-golden`（G13）遇到 causal 用例会算出 NaN → 判 FAIL。
> 两者函数名与签名保持一致即可，实现细节允许差异（`format-contract.md §6` 已许可）。
> 见 `examples/level4/mha/golden.py`（带保护）与其 desc.md §5（省略保护）+ 一句差异说明。

---

## 5. shape 之外的语义等价不变量 —— G15 检测不到，只能写文字

FA 家族有一类 **数值等价**约束，不是 shape 耦合，G15（只统计 shape 恒等式）看不到，
G13（喂各自独立的随机张量）也不会崩 —— 但结果没有物理意义。**必须写进 desc.md**：

| 算子 | 不变量 | 写在哪 |
|---|---|---|
| **MLA** | `v` 与 `k_nope` 数值**完全相同**（共享同一份 latent KV cache，生产即同段 HBM；接口保留独立入参仅为兼容通用 API） | 输入参数说明 + 规则与约束 |
| **sparse** | `value == key[..., :Dv]`（同一 latent 的前缀视图）；`Dk==Dv` 时退化为 `value == key` | 同上 |
| **sparse** | `sparseIndices` 同一 (b, query, kv-head) 组内**索引互异、无重复**，且 ∈ `[0, S_kv-1]` | 单开 `### sparseIndices 说明` 小节 |
| **GQA** | `N_q % N_kv == 0`，第 i 个 query head 用第 `⌊i·N_kv/N_q⌋` 个 KV head | 数学公式 + 规则与约束 |

`sparseIndices` 的「互异」约束通用随机造数满足不了 —— `--run-golden` 会以
`index out of range` / 越界报 **`G13-unsynth`（WARN，非 FAIL）**。这与 l2-l3 的规约一致：
**看到 `G13-unsynth` 不要当噪音，回 desc.md 确认该不变量已写清楚供下游造数。**

---

## 6. inputLayout BSND / BNSD（MLA / sparse 的 str attr）

MLA 与 sparse 支持 `inputLayout ∈ {"BSND", "BNSD"}`，两者仅交换 S 与 N 维的顺序：

```
BSND: [B, S, N, D]      BNSD: [B, N, S, D]
```

- 所有张量（含 sparseIndices 与输出）**布局保持一致**。
- 20 例中两个取值都要出现（G5 期望每个 attr 取值都被用到）。
- golden.py 按 `inputLayout` 分支 permute；G13 靠形参名 `inputLayout` 绑定该 str，可正常跑。

---

## 7. G13 的 skip 现实 —— 别让绿色骗了你

`--run-golden` 的 G13 对**多输入**算子只会跳过（不缩放）过大的用例
（`_scale_shape` 只作用于单输入；多输入且 `> 4×max_numel` 直接 skip）。
FA/MLA 在真实 head dim 下单例常超默认 `max_numel = 4M`：

- `mha` / `gqa`：约 8~9 / 20 例实跑，其余 skip（仍覆盖到 causal）——**够用**。
- `mla`：约 2/20 实跑。
- `mla_prolog`：权重巨大（如 `w_uq_qr = [7168, 24576]`），**20/20 全 skip → G13 绿得空洞**。

对策（写进交付报告，别默默略过）：
1. **留 1~2 个刻意小规格的 smoke 例**（小 B/S/D），保证每个算子至少有实跑覆盖；
2. 或交付时用 `--max-numel <更大值>` 手动跑一遍确认；
3. 报告里**点名** G13 实跑了几例、skip 了几例，避免下游误以为全量复算通过。

---

## 8. precision_thresholds

FA 注意力家族 **不设** `precision_thresholds`，继承默认样板阈值表
（`2^-10 / 2^-7 / 2^-13 / 2^-11 / 2^-3 / 2^-2`，见 `format-contract.md §5.2`）。
desc.md §4 直接抄默认样板即可，不要写 bit-exact（注意力输出是连续浮点，非索引/计数）。

> 对比：RNN（gru/lstm）与 MoE 量化（grouped_matmul_swiglu_quant）**会**覆写
> `precision_thresholds`，但它们不是注意力类，**不在本 skill 当前支持范围内**。

---

## 9. FA 类生成检查清单

写完后逐条自查（校验门只覆盖其中 3~4 条）：

- [ ] `difficulty: L4`，目录在 `level4/`，`category: FusedComposite`
- [ ] **desc.md 只有前五节，不写 `## 6. 额外信息`**（G6 对 L4 期望五节）
- [ ] 支持范围表行名是**注意力符号维度**（B/S/S_kv/N/D...），不是「query 各维大小」
- [ ] 表后有 `约束：` 行，声明 shape 共享维 + `N_q%N_kv==0`（GQA）+ `S≤S_kv`（causal）
- [ ] 20 例场景覆盖 ≥3 类（prefill/decode/cross/MTP/causal），head dim ≥2 档（64/128/256）
- [ ] float16 与 bfloat16 都覆盖；Q/K/V 三列 dtype 每例相同
- [ ] scaleValue 覆盖 `-1.0`（auto）与显式 `≈1/√D` 两种；is_causal 两值都有
- [ ] 保留 1 例 `[0,0]` 全零退化输入
- [ ] GQA：留了 `N_kv==1`（MQA）与 `N_kv==N_q`（MHA）退化行
- [ ] **golden.py 内联了全 mask 行 NaN 保护**（desc §5 可省略并加一句差异说明）
- [ ] 语义等价不变量（MLA `v==k_nope` / sparse `value==key[...:Dv]` / sparse 索引互异）已写进 desc.md
- [ ] inputLayout（若有）两值都覆盖，所有张量布局一致
- [ ] note 已删除 `| baseline_kernels: ...` 后缀
- [ ] 交付报告点名 G13 实跑/skip 例数；`mla_prolog` 这类全 skip 的要显式说明或加 smoke 例
- [ ] `--run-golden` 若报 `G13-unsynth`（sparse 索引），确认该不变量已在 desc.md 写明

**最后一条同 l2-l3：`G13-unsynth` 是核心信号，不是噪音。**
它列出的每条「通用造数满足不了的约束」，都是下游 developer 同样会撞上的坑。

## 参考样例

- `examples/level4/mha/` —— 注意力家族最简形态：3 输入、scaleValue、is_causal、`[0,0]` 退化例、
  golden 带 NaN 保护、desc §5 省略保护并加差异说明。0 fail 0 warn。
- `examples/level4/gqa/` —— 分组耦合：`N_q % N_kv == 0`、MQA/MHA 退化行、G 分组比。0 fail 0 warn。

mla / sparse_flash_attention / mla_prolog 结构更重（BSND/BNSD、稀疏索引、多输出前处理），
不单独入库为样例，按本文 §1/§5/§6 的规约撰写即可。
