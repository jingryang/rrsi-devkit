# 44 — proto precision_thresholds 全链路贯穿 + 比较方法对齐 cann-bench（L3 方案分析）

> 工作线：self-evolution
> 状态：**已拍板冻结 + 已实施**（2026-07-14）
> 关联 L4：`48-precision-spec-threading-impl.md`
> L1 问题：`06-problems.md` P78

## 背景（DQ 冤杀）

六算子批跑 DQ（dynamic_quant）—— devkit `precision_debug` 判 8 case failing、触发上百分钟 false-alarm grind；cann-bench eval 判 20/20 全过（kernel bit-exact 一致）。**同源 golden.py + bit-exact kernel，差异 100% 在精度判定层**。devkit 与 cann-bench 的精度判定有**两处分歧**：

- **分歧 A（容差）**：devkit runner 硬编 `atol=1e-2`（`runner.py:101/:228`），**不读** proto.yaml `precision_thresholds: {int8: 1.0}`，不分 dtype、不逐输出。DQ int8 `.5` 边界合法 ±1 量化差（CPU half-to-even vs NPU 取整）：cann-bench `1.0 ≤ 1.0` 通过；devkit `1.0 > 0.01` 失败 → 冤杀。
- **分歧 B（比较方法）**：devkit 所有 dtype 一律 max-abs-diff（`runner.py:496-500` cast float64）；cann-bench 浮点走 MERE/MARE 相对误差、整数走精确匹配 + abs-diff、另有 bit-exact / 小值域 / 相消兜底。

**权威源**：proto.yaml 是 cann-bench（devkit 同级仓）产物，**「precision_thresholds 怎么用」由 cann-bench 定义**。devkit 的目标是精度判定 == cann-bench（否则 devkit 报的精度结果不可信）。

**与 P10/P12 同构**：规格的一面（P10=schema 参数名 / P12=golden / P78=precision_thresholds）没进 requirement spec → 下游自造。P10/P12 已修，本方案承接 P78。

## cann-bench 精度判定规格（对齐基准——语义参考，**非代码来源**）

> 以下是对齐目标**语义**（devkit 自实现要复刻的*行为*），行号指 cann-bench 仅供 parity 对照，devkit **不 import** cann-bench（§1.7 自闭环）。

- **逐输出**（compare.py:755-834）：每输出 tensor 各自判，`all_passed = 全输出 AND`；按**输出运行时实际 dtype**（`str(out.dtype)`）查阈值。
- **阈值合并**（evaluator.py:891-911 `_get_merged_thresholds`）：`merged = dict(默认表)` → `merged.update(proto.precision_thresholds)`（proto 覆盖优先级最高）。
- **dtype→阈值**（compare.py:703-708）：dtype in merged → merged[dtype]；否则默认表 → 最终回退 float32=2⁻¹³。
- **整数路径**（compare.py:291-347）：`torch.equal` 精确匹配；不等再 `abs(output.long()-golden.long()) > max(threshold,0)` 计 mismatch；`int8:1.0` = 允许 ±1。
- **bit-exact 浮点**（threshold==0 且浮点，compare.py:230-288）：`.view(int_dtype)` 字节级比（区分 ±0.0 / NaN payload）。
- **浮点 MERE/MARE**（compare.py:420-502）：`relative_error = |actual-golden|/(|golden|+1e-7)`；排除 NaN/Inf；**第一阶段** `MERE<thr AND MARE<10*thr` → 通过。
- **第二阶段兜底**（compare.py:504-667，仅第一阶段不通过时）：小值域（`|golden|<small_value_threshold`）+ 相消（output≈0 且 golden 在边界）——`ErrorCount_npu / max(ErrorCount_native,1) ≤ 2`；正常值域 #92 同精度兜底（native 自身脏时 `≤2×`，否则严格）。`native_output=None` 时用 golden 截断当参考（cpu_diff=0）→ 分母为 1（容忍 ≤2 个小值域误差，2026-08-10 对齐后不再「NPU 必须 0 错」）。
- **NaN/Inf**（compare.py:356-418）：NaN 位置不匹配 → fail；单边 inf → 饱和替换为 dtype 最大有限值续比；双边同号 inf → 匹配。
- **默认表**（thresholds.py:28-46）：float16=2⁻¹⁰、bfloat16=2⁻⁷、float32/float64=2⁻¹³、hifloat32=2⁻¹¹、float8_e4m3fn=2⁻³、float8_e5m2=2⁻²、int*/uint*=0。另 3 组数据：`SMALL_VALUE_THRESHOLDS` / `SMALL_VALUE_ERROR_THRESHOLDS` / `CANCEL_BOUNDARY`+`CANCEL_ZERO`（thresholds.py:50-127）。
- **无 golden**（compare.py:757-767）：output/golden 一边 None → FAIL（除非双边 None）；proto output `compare:false` → ignore_output_indices → 跳过（passed=True）。

## 选项

### A. 只修分歧 A（容差贯穿），分歧 B（比较方法）留 max-abs-diff ✗ 否决

只把 proto `precision_thresholds` 贯穿进 spec、runner 按阈值判，比较方法仍用 devkit 原有 max-abs-diff。
- ✗ **不彻底**：DQ int8 靠 `int8:1.0` 阈值放宽能过，但**浮点路径仍与 cann-bench 语义发散**——MERE/MARE（相对误差）对小数值/大动态范围算子（softmax/exp/reduce）的判定与 max-abs-diff（绝对误差）系统性不同，cann-bench 判过的 devkit 仍可能误杀、反之漏判。差异没根除，只是 DQ 这一例碰巧被阈值盖住。
- ✗ 违「方案合理性第一」（§1.2）：既确认了权威语义是 cann-bench，只对齐一半 = 留半套第二通路（§2.5）。
- 用户决策明确否决：「分歧 A+B 一起修（完整对齐）」。

### B. A+B 一起修：devkit 自实现标准方法 + 阈值作传递数据 ✅ 选定

- **比较方法来源 = devkit 自实现标准方法**：MERE/MARE、bit-exact、exact-int 是**通用精度指标**（非 cann-bench 专有，数值计算教科书标准定义），devkit 用自己的命名/结构实现，按 cann-bench 语义（dtype→方法派生）执行。既非"逐字镜像/同名复制"的克隆式耦合，也非运行时 import cann-bench（§1.7）。**parity UT 对拍 cann-bench 原版**守护语义一致。
- **阈值来源 = 默认表作传递数据**：默认 per-dtype 阈值是**数据**（dict literal，值对齐 cann-bench），经 spec 管线传递（proto 覆盖优先），runner 消费合并结果。不是 cann-bench 代码、不是散落硬编常量。
- ✅ §1.7（零运行时外部依赖：不 import cann-bench，纯 torch/numpy）。
- ✅ §2.5（单通路：精度判定语义/阈值唯一来源 = proto 进 spec → runner）。
- ✅ §1.2 可维护（复刻既有不变式「devkit 精度判定 == cann-bench」）+ 可扩展（新 dtype 只需在默认表加一行，自动归位）+ 可诊断（逐输出 `passed`/mere/mare/mismatch_count 全留痕）+ 架构合理（比较数学落 adapters，规格落 domain，对齐分层）。
- ✅ §3.4/§3.9（parity UT 是安全网：devkit 标准方法逐 case 对拍 cann-bench，回归可察觉语义漂移）。

### C. 入参注入 cann-bench callable（"DI 化"原 A）✗ 否决（= 原 A 换皮）

把 cann-bench 的 compare callable 作为参数注入 devkit runner，运行时动态 `import`。
- ✗ **可行性核查否决**：cann-bench import 名是 `kernel_eval`（非 `cann_bench`）、pyproject `package=false` 默认不可 import；加 `PYTHONPATH=<cann-bench>/src` 后 import 触发 **torch_npu autoload 冲突**（需 `TORCH_DEVICE_BACKEND_AUTOLOAD=0` 才不挂）。`import` 写死 vs 入参字符串动态 import，**运行时外部依赖完全相同**——DI 化妆不改变 §1.7 的「运行时外部路径依赖」这一实质。即 P78 既定「否决原 A」同一物。
- ✗ proto 里**没有独立的"方法"字段可传**——cann-bench 方法完全由 dtype+threshold 派生，而 dtype+threshold 已作为数据进 spec，故"传递比较方法信息"在实质上已由阈值贯穿完成，无剩余空缺。
- 即「否决原 A」的 DI 变体，本会话补可行性证据后再次否决。

### D. devkit 自造一套与 cann-bench 不同的容差语义 ✗ 否决（§2.5）

devkit 自己定义容差值/比较逻辑（第二份语义），proto 仅作可选输入。
- ✗ §2.5（同一职责双通路）；§1.2（不维持「devkit==cann-bench」不变式）。
- **关键区分**：被否决的 D 是 devkit *自创*与 cann-bench *不同*的语义。选定方案 B 是**实现 cann-bench 所用的标准方法 + 阈值作数据**——单一规格、自包含、parity 守护，不属此否决项。

### E. DI port + 可选 cann-bench adapter（预留扩展点）⏸ 暂缓（§1.4）

定义抽象 `PrecisionComparator` port，devkit 自实现是默认 adapter，预留 cann-bench adapter 插槽。
- ⏸ 当前唯一出题方 = cann-bench，cann-bench adapter 空置属 §1.4「不留 unused flexibility」；且不省重写（B 仍需作 §1.7 默认比较器）。
- 未来若出现第二出题方再立 port；当下 B 已满足「不与具体出题方耦合」（实现标准方法 + 数据传递，非绑定 cann-bench 代码）。

## 决策

**选 B**：分歧 A+B 一起修。
- **方法**：devkit 自实现 cann-bench 所用的标准精度方法（MERE/MARE/bit-exact/exact-int + NaN/Inf 饱和 + 小值域/相消二阶段），零 import cann-bench（§1.7）。
- **阈值**：默认 per-dtype 表作**数据**经 spec 管线传递，proto `precision_thresholds` 覆盖优先；runner 消费合并结果。
- **贯穿**：proto `precision_thresholds` → `OperatorSpec.precision_thresholds` → runner harness（确定性 post-step 重读 proto，非 LLM 提取——契约值非算子知识，§1.5/§2.7）。
- **native=None**：devkit 无 native CPU 参考时走 cann-bench 同路径（golden 截断当参考，cpu_diff=0）。
- **parity 守护**：UT 对拍 cann-bench 原版逐 case 一致（cann-bench 在场才跑，否则 §3.7 skip）。

> **补注（2026-08-10）**：P69 复刻基线是 2026-07-14 的 cann-bench `compare.py`。此后 cann-bench 有两处演进未同步，devkit 与 cann-bench 生产判定出现分歧，已由 `docs/plan/cannbench-precision-alignment/` 完全对齐：
> 1. **small_value/cancel**：devkit 曾刻意加「无 CPU 参考零容忍」（2026-08-01 决策 `924d0438`，防 golden=1e-6/output=65504 假阳性）——gelu 复盘实证此偏离把正确 kernel 误杀，2026-08-10 已反转回恒 ratio≤2。
> 2. **normal 区 #92 兜底**：cann-bench `855d3ef`（2026-07-24，晚于复刻基线 10 天）为正常值域补同精度兜底，devkit 未同步——已补齐。
> 3. **harness native 参考 + fp64 golden**：P69 时 `native=None → cpu_diff=0` 是「无参考退化」；现 harness 已按 cann-bench `golden_precision=fp64_cpu` 跑两遍 golden（fp64 权威 + 原生同精度参考），`native_output`/`native_refs` 真实传入。

**关键区分（本方案 ≠ 否决的 D 自造语义）**：被否决的是 devkit 自创*不同*语义/第二通路；本方案是实现*权威方所用标准方法* + 阈值作数据 —— 单一规格、自包含、parity 守护，满足 §1.7 且不违 §2.5。默认表回退 = cann-bench 自己的合并行为（默认 ⊕ proto 覆盖），非凭空兜底。

**本会话纠正的两次偏离**：①「闭世界 loud-fail 不兜默认」是我自造原则（仓内零命中「闭世界」/「框架不应」），与 P78 既定（允许 cann-bench 对齐默认表兜底）相反——作废。②比较方法 max-abs-diff vs MERE/MARE 不是「out of scope」，用户决定一并修。

详见 L4。
