# block_dim 运行时动态 + 典型值修正 — 实施方案（L4）

> 精确到改哪个 skill 哪段 / 哪个函数、什么顺序、怎么验证。
> 事实见 `01-problems.md`，方案见 `02-analysis.md`。

## 实施单元与顺序

| # | 单元 | 文件 | 性质 | 依赖 |
|---|---|---|---|---|
| U1 | 典型值修正 | `run_context.py`（`_DEFAULT_VARIANT`） | 代码（改名 + 换值 + 注释） | 无（最隔离，先做） |
| U2 | tiling-split 自检规则 | `ascendc-op-tiling-split/SKILL.md` | skill 文本 | 无 |
| U3 | anchor 门补盲点 | `ascendc-op-design-anchor-per-template/SKILL.md` | skill 文本 | 无 |
| U4 | codegen 维3 硬门增强 | `ascendc-op-dev-coding/SKILL.md` | skill 文本 | 无 |
| U5 | 验证 | UT + 非 heavy ST | — | U1-U4 |

U1-U4 互相独立，U5 最后。

## U1 — run_context.py 典型值修正

- `_DEFAULT_VARIANT`（定义 + 2 引用：`_extract_hw_params` / `build_hardware_target`）整体重命名 `_TYPICAL_VARIANT`（§1.4 不留 alias）。
- A5 值 `910_950z` → `910_9582`（8 核→32 核，治 P2）；A2 `910B3`、A3 `910_9362` 核数不变。
- 注释改：语义从「entry / mainstream SKU」→「typical SKU，仅供设计期性能预估；block_dim 须运行时 `GetCoreNumAiv()`，与该值无关」。
- 影响：探测拿不到 variant 时用典型 variant —— 核数仅供性能预估。

## U2 — tiling-split SKILL.md 自检规则（producer 自检，§2.9 优先）

- 第 85 行「A5：blockIdx 公式需支持动态核数适配」→ 提升为所有代际通用规则：
  「block_dim / blockIdx 禁止读 hw_params 核数字段（`ai_core_cnt`/`cube_core_cnt`/`vector_core_cnt`）的字面值；
  核数上限须运行时取（`GetCoreNumAiv()` 等），`block_dim = min(运行时核数, ⌈totalLength/tileLength⌉)`」。
  补理由：代际内 SKU 跨档（A5: 8/28/32/36），任何静态核数换 SKU 必失效（P1）。
- 「输出自检」清单加必检项：
  `[ ] block_dim/blockIdx 公式来源是运行时核数 API，非 hw_params 核数字面值（违 P1）`

## U3 — anchor-per-template SKILL.md 补盲点（跨段门）

- 阻断码表加 AC4：「block_dim/blockIdx claim 的 `source_pointer` 指向 hw_params 核数字段 → 阻断；
  正确 source 须为运行时核数 API（`GetCoreNumAiv`/`GetBlockNum`）」。
- 步骤 2 对质逻辑补：block_dim claim 即便与 hw_params 核数「一致」也判违规 —— 读核数字段本身即错，不走 AC2「一致即通过」。
- 盲点实锤：run 里 anchor 用 AC2 否决 `block_dim=16`(vector_core_cnt) 却放行 `block_dim=8`(ai_core_cnt) —— AC2「与 hw_params 一致→通过」给字面核数留后门，AC4 补此。

## U4 — codegen SKILL.md 维3 硬门增强（末端兜底）

- 维3 红线（「禁硬编码硬件参数」）增强：现状禁裸 `CORE_NUM`/`BLOCK_NUM` 常数，但「过滤 TilingData 字段」给 block_dim 字面值留后门。
  增补：block_dim 即便经 TilingData 字段传递，其 host 端（`*_tiling.cpp`）赋值源头须为 `GetBlockNum()`/`GetCoreNumAiv()` 派生；
  若 host 把 hw_params 核数字面值直接赋给 `TilingData.blockDim`/`blockNum` → 违规（P1）。
- 失败处理：改 host tiling 用运行时核数 API 派生 block_dim。

## U5 — 验证

- **U1 UT**：`load_hw_params("A5")` / `build_hardware_target("A5")` 返回 `variant=910_9582`、`ai_core_cnt=32`（断言典型值生效）；A2/A3 核数不变。
- **U2/U3/U4**：skill 文本契约 UT（grep 断言规则文本落位）。
- **回归**：UT 全量 + 非 heavy_llm ST；存量算子设计产物不变（典型值仅影响性能预估数值，不改行为契约）。
- **heavy_llm e2e**（真实跑 design→codegen 验 block_dim 走运行时 `GetCoreNumAiv`）：列清单待用户确认（§3.11）。

---

## §10 as-built（实施回填）

**实际 commits**：
- `b0725ad` — block_dim 运行时动态化 + 典型 variant（U1-U4 主体）
- `0b0eaff` — TestCodegenManifest profile 修复（**偏差**：U5 验证发现 3 个 pre-existing ST 失败，额外修 `context.py` reload fallback + `test_self_evolution_stages.py` 3 用例补 profile；超出 L4 原 U1-U4 范围，§3.4 一并修）

**测试结果**：
- UT：**2739 passed / 7 skipped**（零回归）
- 契约 UT（U2/U3/U4 规则文本守护）：**12 passed**
- 非 heavy e2e ST：**116 passed / 23 deselected**（3 pre-existing 修复后全绿；context fallback 无新回归）
- **heavy_llm e2e：未跑**（§3.11 待用户确认）—— 规则行为验证缺口，跑前须列清单

**典型 SKU 选型（实施确认）**：A2=`910B3`、A3=`910_9362`、A5=`910_9582`（32 核，治 P2 低估 4 倍）

**附带发现（follow-up，非本工作范围）**：
- §3.11 heavy_llm 分类 gap：40 个"单次 design stage"llm ST 真实调 LLM 却未标 heavy_llm，非 heavy ST 仍 23min（CPU 49s vs wall 23min）
- PROVENANCE `detected_chip=null` 与 `chip_decision runtime_chip=A5` 口径不一致（双探针）

**review**：`reviews/PR-blockdim-runtime-dynamic-review.{md,json}`（verdict request_changes，3 major：M1 context fallback 可诊断 / M2 heavy_llm 待跑 / M3 本 as-built）
