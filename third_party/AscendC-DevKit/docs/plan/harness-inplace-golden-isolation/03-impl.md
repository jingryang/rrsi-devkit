# harness in-place golden 输入隔离 — 实施方案（L4）

> 具体改哪个函数、什么顺序、怎么验证。对应 L1 P1/P2/P3、L3 方案 A。

## 改动清单

### 1. `src/ascendc_devkit/adapters/npu/_harness_template.py`（唯一改动文件）

| 位置 | 改动 |
|---|---|
| 新增 `_golden_inputs_copy(_x)`（`:124-141`，紧邻 `$golden_bind_helper` 之后、`_golden_core` 之前） | 对入参做独立副本：`None` 透传；`list`（TensorList）递归；`torch.Tensor` → `.clone()`；`np.ndarray` → `.copy()`；其余原样返回 |
| `_golden_core`（`:153-155`） | bind 前先克隆：`_golden_raw(**bind_golden_args(_golden_raw, _golden_inputs_copy(list(_inputs)), _attrs))` |

要点：
- `_golden_core` 是全部 6 个 golden 调用点的唯一咽喉，只需改这一处（§1.15 / §2.5）：
  - CANN torch 路径：`:545`（native）、`:562`（fp64）直调 `_golden_core`；
  - CANN numpy 路径（`:810/:829`）与独立 fallback 路径（`golden_fn(*_np_inputs,...)` / `golden_fn(*_upcast_fp64(...),...)`）经 `golden_fn = _golden_wrap` → `_golden_core`。
- 只改「交给 golden 的输入」，不动 golden 计算与输出（§1.13）。
- torch / numpy 两类输入在同一函数内一次覆盖（含 `.numpy()` 共享存储的切断）。

### 2. 测试

| 文件 | 改动 |
|---|---|
| `tests/ut/adapters/npu/test_golden_binding.py` | 新增 `test_golden_core_isolates_inplace_golden_inputs`：渲染真实 harness 源码 → 从 AST 取 `_golden_inputs_copy` / `_golden_core` → 在朴素命名空间执行 → 以真实 in-place golden 形态（`x.copy_(x*2); return x`）连调两次，断言 ①输入对象未被写回污染 ②两次参考一致（无隔离时第二次 = 4,8,12 的复合值）。torch-free 环境仅校验 `_golden_inputs_copy` 已在渲染源码中内联 |
| `tests/ut/adapters/fixtures/harness_devkit_golden.txt` | 重新生成（A1 快照回归门；`TestHarnessExtractionSnapshot`，diff 恰为本改动）|

## 验证

- `pytest tests/ut/adapters/npu/test_golden_binding.py --ut` → **23 passed**（含新用例）。
- **变异验证**：临时把 `_golden_core` 还原为不克隆 → 新用例即红（输入被写成 `[4,8,12]`，两次复合）；
  确认用例真守护该缺陷，而非恒绿。
- UT 全量 `pytest tests/ut --ut` → 4681 passed / 50 failed；50 failed 在 **clean tree 逐条一致**
  （环境性：`click` 缺失引发的 collection、opencode/LLM 依赖等），与本次改动无关。
- 非 heavy ST `pytest tests/st -m "not heavy_llm"` → 109 passed / 7 failed；7 failed 在 **clean tree 逐条一致**
  （opencode model 未配置）。
- heavy_llm：本次**未跑**（§3.11 待用户确认），诚实记录。

## 不做的事

- 不改 golden 的行为 / 输出 / mutation 语义（§1.13）；不要求 golden 由原地改为非原地（L3 选项 D 否决）。
- 不改 cann-bench（只读借鉴 `compare.py` / `evaluator.py`）。
- 不按算子类型条件化克隆（L3 选项 B 否决）——保留单点无条件克隆，以鲁棒性与唯一通路优先。
- 不重构 harness 的 golden 调用结构（不大改，仅前置一层输入副本）。

## 遗留（已记录，不阻断本次）

- 仅识别 `list` 容器，`tuple` 会静默不克隆（防御性缺口，当前输入容器约定为 list 不触发）。
- 无 NPU 子进程端到端用例；以 UT（exec 渲染源码）为守护（成本权衡，见 L3「已知取舍」）。
