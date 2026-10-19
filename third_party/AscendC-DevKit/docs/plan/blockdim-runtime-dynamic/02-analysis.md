# 设计期核数静态化 — 方案分析（L3）

> 选项 / 取舍 / 决策。事实见 `01-problems.md`（P1/P2）。拍板后冻结。

## 决策

**两层修复：B1（根因）+ 典型值修正。**

- **B1**：design 自检 + codegen 硬门 —— block_dim 禁读 hw_params 任何核数字段，必须运行时 `GetCoreNumAiv()` 动态。
- **典型值修正**：`_DEFAULT_VARIANT` → `_TYPICAL_VARIANT`，值改各代际**典型** SKU（A5: `910_950z`→`910_9582`；
  A2 `910B3`、A3 `910_9362` 核数不变，语义从 entry→typical）。hw_params 按典型 variant 给，供设计期性能预估。

## 关键取舍：为什么探测精确 SKU（A1）被否决

设计期核数**只用于性能预估**（带宽×核数算吞吐，是估算非约束）；block_dim 走运行期 `GetCoreNumAiv()`
取真实核数（那是 kernel 运行时 API，不属「设计期探测」）。故设计期**不需要真实核数**，典型值即够 →

探测精确 SKU 的唯一收益（性能预估从典型值变精确值）边际为零，**A1 砍掉**。

### 探测的正确定位

探测芯片平台**仅为「用户 / 需求都未指定 design 代际时的兜底」**，且只需**代际级**（A2/A3/A5）。
`detect_chip_version` 当前返回代际正好满足——它从来不是 bug。
探测失败且用户未指定 → halt（§3.7 诚实报错，让用户指定代际），不静默套默认。

## 关键取舍：为什么「典型 SKU 降级机制 / spec 标 typical」被否决

- spec 是**客观数据**（每 SKU 真实参数，恒为真值），不该承载「典型 / 真实」属性（数据 / 决策分离）。
  把 `typical:true` 标进 spec = 把选择决策混进客观数据 → 否决。
- 「典型 SKU」是**降级策略的选择**，属代码层（`_TYPICAL_VARIANT`），不进 spec。
- B1 让核数与 block_dim 解耦后，单独建「典型估算 + source 标注 + spec 标记」一整套机制边际价值低 → 砍。
  探测拿不到 SKU 时，hw_params 按代际典型 variant 给即可，无需额外 source 机制。

## design 自检规则（B1 落点）

tiling skill / anchor 增一条核心规则：
**block_dim 禁止等于 / 读自 hw_params 的任何核数字段（`ai_core_cnt` / `cube_core_cnt` / `vector_core_cnt`），
必须表达为运行时 `min(GetCoreNumAiv(), ⌈totalLength/tileLength⌉)` 动态计算。**

现网 anchor 盲点（P1）：anchor 否决了 `block_dim=16`（vector_core_cnt）却放行 `block_dim=8`（ai_core_cnt）——
只防了「用错核数种类」，没防「把任何核数当字面 block_dim」。本规则补此盲点。

## codegen 硬门（B1 兜底）

codegen 加红线：禁止字面核数 / 字面 block_dim；block_dim 必须来自运行时 `GetCoreNumAiv()` 派生。
即便 design 漏检，codegen 拒绝把字面核数写进 kernel / tiling。

## 典型 SKU 选型（已拍板）

| 代际 | 典型 SKU | 核数 | 依据 |
|---|---|---|---|
| A5 | `910_9582` | 32/32/64 | 本机实测即此；8-variant 最集中档；生产主力；改 950z(8)→9582(32) 治 P2 |
| A2 | `910B3` | 20/20/40 | 核数不变，语义 entry→typical |
| A3 | `910_9362` | 20/20/40 | 核数不变，语义 entry→typical（A3 主力 20 vs 24 核无实测，按 20 定） |

A2 / A3 入门档核数恰好是合理典型（20 核主力），A5 入门档（8 核）非典型（32 核才是）——
故 P2 仅在 A5 爆发，本次仅 A5 典型值实质改变。

## 拍板后产出

L4 `03-impl-*.md`：精确到改 tiling skill / anchor 哪段、codegen 硬门加在哪、
`_TYPICAL_VARIANT` 改名换值的位置、按什么顺序、怎么验证（UT + 非 heavy_llm ST + 回归）。
