# 核间切分负载均衡闭式公式（round-robin 余数分配）

> **定位**：详设 split 阶段核间切分的**通用数学工具**（与算子无关）。凡核间把 `W` 个 work
> unit（行块 / 列块 / tile）均分给运行时 `M` 个核（`blockDim = min(AIV 运行时核数, W)`，
> 见 `platform_diff.md`），并做 round-robin / 块循环指派时，直接套本页公式，**禁止从零
> 重新推导**（本页公式已闭式化，可在 1 分钟内核对，无需多轮脚本往返）。
>
> **谁必须读本文件**：`ascendc-op-tiling-split`（核间切分设计当下）。
> 上游 `ascendc-op-general-design` 判定"每核分到的循环次数是否两类及以上"（R5 分组存储）
> 时也引用本页 §3。

---

## 1. 术语

- `W`：work unit 总数（如 `blockFactor = ⌈totalLength / ubFactor⌉` 的 tile 数，或
  `bDim × colTileCount` 的 (b, 列块) 组合数）。
- `M`：实际使用的核数（**运行时** `GetCoreNumAiv()` 动态取，非 hw_params 字面值）；
  通常 `M = min(coreNumAiv, W)`。
- 指派方式：block 线性序 round-robin，`for (w = blockIdx; w < W; w += M)`，
  或等价地"块循环按连续段分派"。

## 2. 核心闭式（余数分配）

令
```
chunk = ⌊W / M⌋        # 每核基本 unit 数
rem   = W mod M        # 余数
```
则标准"前 rem 个核多拿 1 个 unit"的均衡分派为：

| 核索引 c | unit 数 n(c) |
|---|---|
| `0 ≤ c < rem` | `chunk + 1` |
| `rem ≤ c < M` | `chunk` |

- **按 unit 数衡量的不均衡**：`max/min = (chunk+1)/chunk`（当 `rem>0`），否则 `1`。
  以"负载均衡 ≥ 85%"(R3) 为目标的判据是：
  ```
  maxUnit / minUnit ≤ 1/0.85 ≈ 1.176  且  每核负载度量按实际承担元素而非 unit 数
  ```
  单看 unit 数：`chunk ≥ 7` 时 `(chunk+1)/chunk ≥ 0.875`（即 7 vs 8 已经 ≥85%）；
  `chunk ≥ 6` 时 6 vs 7 = 0.857 贴近 85%；`chunk < 6` 时单看 unit 已 <85%，
  必须用 §3 的**按元素**精确衡算，不能只报 unit 比。

- **实际负载度量**：当各 unit 大小不齐（尾 unit 更小）时，均衡度应按
  `平均核负载 / 最大核负载` 计算（元素口径），而不是简单 unit 比。
  经验：`W = q·M + rem`（`q≥1`，`0≤rem<M`）时，若 `rem=0` 且各 unit 等大 → 100%；
  若 `rem>0` → 前 rem 核 `q+1` unit、其余 `q` unit，元素口径下
  ```
  balance = (q·(M−rem) + (q+1)·rem ... 的平均) / (q+1)·unitMax
  ```
  等于用 §3 公式逐核累加，不要把"87.5%"当恒值——尾 unit 变小时实际可能只有 ~75-84%
  （这是多算子踩坑点：**先按 unit 估 87.5%，实算元素口径跌到 84% 以下**）。

## 3. 按元素口径的精确均衡度（尾 unit 不齐时必用）

设第 w 个 unit 的元素数为 `e(w)`（`w ∈ [0,W)`，通常主 unit = `U` 元素、仅尾 unit = `U'≤U`）。
round-robin 下核 c 承担 `S_c = Σ_{w ≡ c (mod M)} e(w)`。
则
```
balance = (Σ_c S_c / M) / max_c S_c = (totalElements/M) / max_c S_c
```
**判定**：`balance ≥ 0.85` 即满足 R3。当 `W ≥ 8M`（即 chunk≥8）且尾 unit 比例不极端时，
round-robin 几乎总 ≥85%（尾 unit 被平均摊薄到各核）；小 `W`（chunk≤5）时尾 unit 落到少数核
会把 balance 拉到 85% 以下——此时**应改判"把尾块也近似均摊"或提高 colTile 细分**，
而不是硬编码一个不达标的 blockDim。

## 4. 使用纪律（防过度求索）

- **先查再推**：本页公式 + 上游概设已给的 W/M 定义即可直接填 `verifiable_claims`
  （claim_type=`numeric_derivation`，verification=`derived`，`evidence.attempt_log` 引用
  本页公式 + 代入的具体 W/M/totalElements）。**禁止**先凭感觉估一个平衡度再用脚本反推。
- **一次脚本验算即收敛**：若确需数值验证，写一次脚本算 balance 表；结果与 §2/§3 公式
  矛盾时，先核对"unit 大小是否不齐 / 是否按元素口径"，**不是立即推翻公式重推**。
- 分核行数两类及以上的分组命名（`main*`/`tail*`）判断见 SKILL R5，不在此重复。

## 5. 适用边界

- 本页针对"无核间通信、纯分块独立"的切分（elementwise / 逐块 reduce / 列块 softmax 等）。
- 含核间归约（partial sum 需二次归约）或 load 不均由数据稀疏决定（非 shape 决定）的场景，
  不适用本页，另按 reduce 策略 / 稀疏策略处理。
