# L4 实施方案 — card 隔离 subprocess 修复（TDD）

> 对应 L3 冻结方案四项改动。

## 改动清单

1. **`card_context`**（adapters/npu/card_context.py）：pool None 分支加 env 兜底
   （`ASCEND_NPU_ID` 合法 int → 该卡；否则 0），docstring 更新优先级链。
2. **deploy.py** smoke 卡解析：删内联 `state.npu_id or 0`，`with card_context(state.npu_id, None)`
   包住 smoke 子进程段（仅卡解析收拢，env 构造逻辑不动）。
3. **precision_debug_substages.py**：
   - `_acquire_card_lease(state) -> int`（模块级或 base 方法）：hard-pin 直返；pool 模式
     `acquire()` + 写 control.json `card_lease`；无池返回 0 不写字段。
   - `_release_card_lease(state)`：读 `card_lease`，非 null → `pool.release` + 清字段；幂等。
   - `RunTestsSubstage.actions` / `DiagnoseSubstage.actions`：`_phase_setup` 后调用 acquire
     （返回值不需持有——`_common_context` 从 control.json 读）。
   - `_common_context`：解析本轮卡（hard-pin > card_lease > 0）；`build_command`/`test_command`
     前缀 `ASCEND_NPU_ID=<card> `；`device_id` 用同卡。
   - 两个 substage `transition()` 首行 `_release_card_lease(state)`。
4. **UT**（tests/ut/adapters/npu/test_card_context_env.py +
   tests/ut/orchestration/test_precision_card_lease.py）：见 L3 改动 4 清单。

## 不做清单

1. 不动 SpawnAgent/RunMeasure Action 定义与两 backend（L3 否决项）。
2. 不动 A5（precision_debug_a5.py）——同事产权；L1 记共享层受益。
3. 不改池阻塞/lease 语义（维持 in-process 边界既有行为）。
4. 不给快照持久化卡（L1 P2）。

## 验证

targeted UT → 全量 `tests/ut --quick`（PYTHONPATH=src）。heavy_llm 真实并发批跑（多算子
pool 模式挤卡回归验证）§3.11 待用户决策；下批跑自然观测 device 分布。

## as-built（2026-08-25）

- **改动 1**：`card_context` pool-None 分支加 `ASCEND_NPU_ID` env 兜底（合法 int → 该卡，否则 0），docstring 记录四级优先级。
- **改动 2**：deploy.py smoke 卡解析收拢 `with card_context(state.npu_id, None)`（删内联旁路；narrow with-span，pool=None 无 acquire/release 语义差异）。
- **改动 3**：`_resolve_round_card`（只读：hard-pin > card_lease > 0）+ `_acquire_card_lease`（pool 阻塞 acquire + 租约写 control.json；_save_control 自建目录覆盖首轮未建场景）/`_release_card_lease`（幂等，清字段 + pool.release）；base actions 与 RunTestsSubstage.actions 各加 acquire；两个 transition 首行 release；`_common_context` 的 build_command/test_command 前缀 `ASCEND_NPU_ID=<card> `、device_id 同卡。
- **验证**：TDD `test_precision_card_lease.py` **13 passed** 先红后绿（card_context 四态 ×5、租约生命周期 ×4 含 abort 早退释放与幂等、前缀注入 ×4）；全量 `tests/ut --quick` **3631 passed / 0 failed**（+13 零回归，无既有测试依赖旧命令格式）；非 LLM ST（self_evolution_stages + integration）**66 passed**。heavy_llm 并发批跑 §3.11 待用户决策；下批跑观测 device 分布。

## as-built 追加（2026-08-26）：租约 sidecar 迁移（P4 回归修复）

- **改动**：`_card_lease_path`/`_read_card_lease` 新增；`_acquire_card_lease` 租约写
  `debug_artifacts_dir/card_lease.fw.json`（不再触碰 control.json）；`_release_card_lease`
  删 sidecar + 还池；`_resolve_round_card` 读 sidecar（hard-pin > sidecar > 0）。
- **构造性保证**：init-checkpoint 的闸门（control.json 存在性）与租约持久化不再共享同一
  文件——框架侧任何提前写盘都不可能吞掉规范初始化。
- **验证**：`test_precision_card_lease.py` **14 passed**（13 迁移改写 + 新增
  `test_acquire_never_creates_control_json` 回归守护：acquire 后 control.json 仍不存在、
  sidecar 存在）；全量 `tests/ut --quick` **3639 passed / 0 failed**。
