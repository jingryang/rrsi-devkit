# golden_precision harness-eval 对齐 — 实施方案（L4）

> 具体改哪个函数、什么顺序、怎么验证。对应 L1 P1/P2、L3 方案 A。

## 改动清单

### 1. golden_precision 契约化（链路：CLI → State → golden_contract → harness）
| 文件 | 改动 |
|---|---|
| `orchestration/kernel/state.py` | State 新增 `golden_precision: str = ""`（默认空，契约处落 fp64_cpu）+ `_SNAPSHOT_FIELDS` 增加 `("golden_precision", "")` |
| `cli/commands/run.py` | 新增 `--golden-precision {fp64_cpu,native_cpu}`（默认 None）+ `run_cmd` 签名与 task_request 透传 |
| `application/dispatcher.py` | `golden_precision = task_request.get("golden_precision") or ""` → 传 State |
| `application/debug_service.py` | golden_contract 增加 `"precision": state.golden_precision or "fp64_cpu"` |
| `adapters/npu/runner.py` | `g_precision = gc.get("precision") or "fp64_cpu"` → 渲染模板变量 `$golden_precision` |

### 2. `_harness_template.py` 实现 golden_precision
| 位置 | 改动 |
|---|---|
| 模板头部 | 新增 `golden_precision = $golden_precision` 变量 + 注释 |
| 新增 `_upcast_golden_inputs(_inputs)` | 浮点 tensor `.double()`；TensorList 逐元素；int/None 不变。镜像 cann-bench `tensors_to_fp64_cpu`（只读借鉴） |
| CANN 路径 golden 调用（torch） | `_golden_core(_upcast_golden_inputs(_torch_inputs) if golden_precision == 'fp64_cpu' else _torch_inputs, _attrs)` |
| CANN 路径 golden 调用（非 torch fallback） | `fp64_cpu` 时 numpy 浮点 `astype(np.float64)`（任意 golden_input_type 下参考一致） |
| 独立 fallback 路径 golden 调用 | `fp64_cpu` 时 `_np_inputs` 原地 numpy 浮点 `astype(np.float64)`（保留 `golden_fn(*_np_inputs)` 不变式） |

> 关键语义：比较器 `compare.py:350` 已按 kernel dtype 截断 golden —— 上抛 fp64 后与 eval
> 判定构造性一致（§2.9：不做 discover+regenerate，golden 参考由契约 + 上抛构造保证）。

### 3. 测试
| 文件 | 用例 |
|---|---|
| `tests/ut/adapters/npu/test_golden_binding.py` | ①fp64_cpu 烘焙出 `golden_precision='fp64_cpu'` + `_upcast_golden_inputs` + CANN 路径上抛；②缺 precision → 默认 fp64_cpu；③native_cpu → 不升精度；④`_upcast_golden_inputs` 行为（fp16/bf16→fp64、int/None 不变、TensorList 逐元素） |
| `tests/ut/adapters/fixtures/harness_devkit_golden.txt` | 重新生成（A1 快照回归门） |

### 4. 验证
- `pytest tests/ut/ --quick` 全绿（含非 heavy_llm ST 见 §3.2）。
- 端到端：重跑 resize_bilinear precision_debug → harness 应诚实显示 13/20（不再 20/20），
  debug loop 继续修 7 例至 fp64 参考达标（kernel 侧：去掉 fp16/bf16 权重量化 → fp32 权重 +
  近精确累加 + 末尾一次舍入，由 debug loop 完成，框架不手写）。

## 不做的事
- 不改 cann-bench（用户约束：非 bug 不改）。`evaluator.py` / `compare.py` / `bench_registry.py`
  只读借鉴。
- 不把 golden_precision 默认改成 native_cpu（L3 方案 B 否决）。
- 不实施动态读 cann-bench bench config（L3 方案 C 否决：DevKit 进程 import 不了 cann-bench）。

## 第二轮改动（2026-08-10，与 golden_precision 同族收口）
- **harness seed 公式对齐**：`_harness_template.py` seed 计算补 `_eval_seed=0` 项，
  与 cann-bench eval 公式 `(eval_seed + SHA256(case_id)) % 2^31` 逐字一致（防御 eval_seed 非 0）。
- **fallback 比较器验证对齐**：逐行核对 devkit `compare_outputs` 与 cann-bench `compare_tensors`
  均做 `golden.to(target_dtype).double()` 截断 + 同一 DTYPE_THRESHOLDS + 同一 MERE/MARE/
  small_value/cancel 语义；golden_precision 上抛已让 fallback golden 也在 fp64 下计算。
  补 UT 断言固化（`test_rendered_harness_fallback_golden_path_upcasts_fp64`）。
- **重建提速（cann-bench profile 增量构建）**：`BuildStage` 新增
  `incremental_command_template`（声明式能力，devkit-only profile 不受影响）；cann-bench
  profile 的 ascendc build stage 声明增量命令（`[ -d build ]` 门 → cmake 复用 / else 全量
  build.sh），绕开 build_run.sh:43 与 build_wheel.sh:23 的无条件 `rm -rf build`。意图：
  precision_debug fix 循环 23 次 redeploy 从 5-7min/次 降到 ~3min/次。

## 第三轮改动（2026-08-10，#3 设计阶段 skill 层守精度约束）
- **precision-perf skill**（`.claude/skills/ascendc-op-tiling-precision-perf/SKILL.md`）新增
  **R4 golden 算术等价性（目标 dtype 强制）**：kernel 算术公式须在真实 dtype（fp16/bf16/fp32）
  下与 golden 等价，不得只验 fp64（历史实证：lerp 形 vs 加权和形 fp32 下差 ~1 ULP → 整轮返工）。
  golden 算术来源按优先级（requirement.json golden_alignment → 设计公式段 → golden.py），
  取不到显式标「未核对」；golden 权重量化为硬约束；硬件 FMA 语义纳入。同步补执行步骤 + 自检清单。
- **buffer-kernel skill**（`.claude/skills/ascendc-op-tiling-buffer-kernel/SKILL.md`）新增
  **R9 算术形式对齐 golden**：Kernel 伪代码的算术形式书写期就对齐 golden（或给目标 dtype 等价性
  证据），golden 权重量化是硬约束；等价性校验由 precision-perf R4 兜底。
- **golden 算术来源（不跨层跳 requirement）**：tiling 段的既有输入 `general_design.json`
  （概设 narrative/公式段）承载了 golden 算术（实证：resize_bilinear 概设 narrative 含
  公式/加权/插值）——R4/R9 从其取源，符合 §1.1 分层（tiling 消费自然上游概设，不跳
  requirement 层）。requirement.json/golden.py 为可选次级来源，取不到显式标「未核对」。
  曾尝试把 requirement.json 直接物化进 tiling（跨层跳，用户质疑后撤回）。
- 验证：skill 加载/自包含测试 141 过；无问题编号耦合（§2.11）、无算子点名锚定（§1.12）。
  原则审计见 `06-principle-audit.md`。

## 待解决清单（记录在案，后续逐条解决）
- **#2 diagnose 可执行 fix_plan**（见 `04-convergence-analysis.md` §四.2）——未实施。
- **批级模式（见 `05-batch-framework-patterns.md`，2026-08-11 状态）**：
  - 模式 1-attrs/2/3/4/6 已修（harness attrs 补齐 / smoke 标签纠偏 / harness_timeout_sec
    框架自有化 / changed_files 读写契约构造性派生 / golden_precision）；模式 5 用户确认不改。
  - 模式 1-codegen（grid_sampler_3d/unique）已由 a0860df4 路由回 codegen 重试，可选加固=
    静态 m.def attr 默认值校验门（低优先）。
