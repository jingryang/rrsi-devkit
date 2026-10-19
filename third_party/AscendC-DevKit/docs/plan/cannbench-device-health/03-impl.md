# L4 实施方案：cann-bench 评测 device 探活 + 选卡泛化

> 层级：L4（动手前写，按需产出）。改哪个函数、什么顺序、怎么验证。
> 解决 L1 的 P1（device 故障被当 LOSS）+ P2（hard-pin 0）。

## 方案决策（取舍摘要）

- **范围 A+B**：A=选卡泛化（解决 P2）、B=探活 halt（解决 P1，本次故障真正解药）。
- **失败策略=halt（非自动换卡）**：最常见的 507033 是全局 context 耗尽，换卡无效，halt 更诚实（§3.7）。
- **探活失败 raise 现成 `EnvironmentNotAvailableError`**（非新造异常/通路）：复用 `domain/exceptions.py`
  + dispatcher halt 处理（`dispatcher.py:1065`，含「非代码缺陷、保留产物」语义）。
- **不改 `fail_strategy`**：cannbench_eval 是无 agent 的纯 transition stage，`runner.py:510` 的 infra
  分支依赖 `last_agent`，对此 stage 不适用；raise 控制流异常是唯一正确的 infra halt 路径。
- **探活落 cannbench_eval 局部（不上提 card_context）**：避免每个 NPU 子进程都探活、放大 driver
  context 消耗；probe_device 抽成独立 helper 便于 precision_debug/perf 将来复用。

## 改动

### B. device 探活 + halt（解决 P1）
1. **新增 `src/ascendc_devkit/adapters/npu/probe.py`**：`probe_device(card, env, timeout=60, stage_name)`
   spawn `python -c "import torch,torch_npu;torch.npu.set_device({card});torch.zeros(1,device='npu')"`，
   复用调用方 env（autoload=0 / usercustomize torch_npu import / PYTHONPATH / LD，走与 kernel_eval
   同一条 open-device 路径，非裸 os.environ）。非0退出 / `TimeoutExpired` → raise
   `EnvironmentNotAvailableError`（带 stderr tail + help_hint：507033/zombie/重启容器提示）。
2. **`cannbench_eval._run_eval`**：`card_context` 内、`subprocess.run(kernel_eval)` 前
   `probe_device(card, env, stage_name="cannbench_eval")`。raise 是控制流异常 → 绕过
   `except TimeoutExpired`（只捕 kernel_eval 自身超时）→ runner emit `stage_aborted` + re-raise
   → dispatcher catch → halt（`EX_CONFIG` + `_preserve_repo_with_hint` 保留算子代码）。
   正常精度 LOSS（device OK、overall=0）行为不变：探活通过 → 跑 eval → overall=0 仍是合法 LOSS。

### A. 选卡泛化（解决 P2，脚本层；框架字段不改）
3. **`scripts/e2e_self_evolve.sh`**：`NPU_ID` 未设时不传 `--npu-id`（条件拼 `ARGS`）；banner 显示 `auto (pool)`。
4. **`scripts/e2e_run.sh`**：`NPU_ID` 默认改空，`cmd` 条件拼 `--npu-id`。

## 验证
- `tests/ut/adapters/test_probe.py`（6）：returncode 0 静默 / 非0 raise / timeout raise /
  卡号入脚本 / env 透传 / stage_name 可定位。
- `tests/ut/orchestration/test_cannbench_eval.py`：autouse fixture stub 探活（现有 21 用例不真实
  spawn python/torch_npu，§3.8）+ `TestDeviceProbe`（2）：探活失败 raise + kernel_eval 未启动；
  探活收到 card_context 解析的真实 card + 注入 autoload=0 的 env。
- 全量：`tests/ut/orchestration tests/ut/adapters` → 2063 passed, 7 skipped（无回归；skip 为
  precision_compare 的 npu 真依赖用例在 UT 环境正常 skip，§3.5）。
- 脚本：`bash -n` 通过；条件拼逻辑验证（NPU_ID 未设→不传、设 N→传 `--npu-id N`）。

## 边界 / 遗留
- report `errors` 列表靠 `stage_aborted` 反映（cannbench_eval status 非 ok）；未单独 emit
  `type=="error"` 事件进 errors 列表（可选增强，不阻塞主修复）。
- 未来若要「卡 0 局部坏自动换卡」：把探活失败从 raise 改为 pool 换卡重试（有限次后 halt）。
- 探活未上提到 card_context 统一层（仅 cannbench_eval 调用）；precision_debug / perf 复用
  probe_device 是后续独立工作。
