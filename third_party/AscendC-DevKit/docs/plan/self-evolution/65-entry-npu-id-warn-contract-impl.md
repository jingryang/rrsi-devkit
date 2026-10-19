# 65 — entry npu_id 契约归位 + runner WARN 文案精准化（L4 实施）

> 配套 L1：P92（`06-problems.md`）。覆盖问题：P92-a / P92-b。
> 触发场景：`scripts/batch_self_evolve.sh` 首跑 batch `20260720-104711-bf84a2`，5/5 entry stage 误报 WARN。

## 背景（一句话）

batch 自检跑 5/5 entry stage 误报 `reached max iterations without satisfying output_contract`，WARN 文案列出 6 个 provides 字段像「全崩」。根因**不是配置**（npu_id 运行时分配是用户意图），是 entry 契约越界 + runner 文案误导。详见 P92。

## 改动（L4 代码配方）

### 1. `src/ascendc_devkit/orchestration/stages/entry.py` — `output_contract()`

`npu_id` 从 `provides` 移到 `optional_provides`（紧挨 `target_repo` / `requirement_path`），注释说明：npu_id 是运行时填充字段（None=用卡池 / int=硬钉），entry 只 transition 透传、不「produce」它，故不进 `has_all` 早终止判定。

- `entry.py:113` `npu_id=tr.get("npu_id", 0)` **不改**：batch 下透传 None（用池，合法）/ single-op default 0（CLI 默认卡 0），行为正确，非 bug。

### 2. `src/ascendc_devkit/orchestration/kernel/runner.py`

- 新增 module-level `_unsatisfied_contract_fields(state, provides) -> list[str]`（`RunnerCancelledError` 后、`class Runner` 前）：返回 provides 中 absent 或 None 的字段，**镜像 `State.has_all` 的 `is None` 判据**（falsy-but-non-None 如 0/False/"" 算满足）。
- `runner.py` per-iteration reason（原 `:345-348`）与最终 WARN（原 `:370-374`）共用该 helper（单一源，DRY，二者不再各写一份列表推导）。
- WARN 文案：`f"...without satisfying output_contract: {output_contract.provides}"` → `f"...without satisfying output_contract; missing: {missing}"`，精准列缺失字段。

## 四把尺子（§1.2）

- **可维护**：npu_id 的 None 语义完整保留，下游 `card_context` 的 None/int 分支零影响；复用 entry 已有 `optional_provides` 机制，不引入新概念；不留 None-vs-0 歧义。
- **可扩展**：确立规则——「运行时/框架注入字段不进 stage 硬 `provides`；硬 `provides` 只声明 stage 真正产出的字段」。后续新 stage 引入运行时字段按此归位，不撞 provides→WARN。
- **可诊断**：消除 entry 误报（不再狼来了），真告警（如本次 401）不被噪声埋没；WARN 文案列 `missing`，未来真有 stage 契约未满足时精准指明缺哪个字段。
- **架构合理**：entry 职责 = 解析 task_request + 确定 mode/workflow，它**推导** mode/workflow_name/op_name/repo_profile_name/non_interactive（留硬 provides）；npu_id 是 passthrough/卡池产物，entry 对其做非 None 担保属**越界**。修复落在 entry 本地契约声明 + runner 文案，不动 state/dispatcher 语义、不越层。

## 否决方案

- **A（`tr.get("npu_id") or 0`）**：None→0 后 `card_context(0, pool)` 当硬钉卡 0（skip pool），5 并发算子全抢卡 0 → 卡分配回归/并发崩。可维护、架构双破，否决。
- **B（只把 WARN 降级 INFO）**：entry 仍判 `[partial]`，状态本身错，治标否决。

## 验证（TDD，§3.1）

- TDD：先写 UT 红（`test_output_contract` 的 npu_id 断言改 optional；`test_entry_no_spin_when_npu_id_none` has_all 失败），改代码后绿。
- 新增 UT（`tests/ut/orchestration/test_stages.py`）：
  - `TestEntryStage.test_entry_no_spin_when_npu_id_none` — batch None 场景 has_all 通过、不 spin（**核心回归守护**）
  - `TestEntryStage.test_entry_hardpin_npu_id_passthrough` — 硬钉 int 透传不改
  - `TestEntryStage.test_entry_singleop_default_npu_id_zero` — CLI 无 key → 0
  - `TestRunnerContractWarn.test_unsatisfied_contract_fields_helper` — helper 纯逻辑 + falsy-but-non-None 算满足
  - `TestRunnerContractWarn.test_warn_names_missing_not_full_provides` — WARN 含 missing、不含 satisfied 字段
  - 同步更新 `TestEntryStage.test_output_contract`（npu_id 断言从 provides 移到 optional_provides）。
- 回归：`tests/ut/orchestration/` 全量 **1351 passed**（含 `test_stages.py` 156 / `TestStageContractNoSpin` 4）。

## 不改 agent 产物

本修复只动框架契约声明（entry `output_contract`）+ runner 告警判定/文案（runner helper + WARN），不碰任何 agent/skill 产出（用户红线）。

## 后续观察（不在本次范围）

- `perf.py:153` `requires=[..., "npu_id"]` 与「npu_id 可 None」存在张力（perf 跑时若仍 None，requires 满足性依赖别处填充）。本次修改不改变 npu_id 值流向，不引入新风险，但该张力建议另立 L1 跟踪。
