# golden_precision harness-eval 分裂 — 方案分析（L3）

> 选项 → 取舍 → 拍板。调研演进、拍板后冻结。

## 决策：devkit harness 对齐 cann-bench eval 的 golden_precision（默认 fp64_cpu）；不改 cann-bench

### 背景约束
- 用户决策（2026-08-10）：**devkit 必须对齐 cann-bench；只要不是 cann-bench 的 bug 就不允许修改它**。
- cann-bench `BenchConfig.golden_precision` 默认 `"fp64_cpu"`，是每个 bench 可配置字段
  （`bench_registry.py:56`），evaluator 按它升 fp64 计算 golden 参考。
- 因此权威参考 = eval 实际用的参考（fp64_cpu）。harness 必须复刻，否则「debug 过 / eval 挂」的
  假收敛会反复出现（本轮 resize_bilinear 实证 20/20 vs 13/20）。

### 候选方案

**方案 A — devkit harness 实现 golden_precision（默认 fp64_cpu，与 eval 同语义）【采纳】**
- golden contract 增加 `golden_precision`（默认 `fp64_cpu`），经 State → debug_service →
  runner → harness 模板透传。
- `_harness_template.py` 两处 golden 调用点上抛：
  - CANN 路径：`fp64_cpu` 时浮点输入 `.double()` 再喂 golden（镜像 cann-bench `tensors_to_fp64_cpu`）；
  - fallback 路径：numpy 浮点输入 `astype(np.float64)` 再喂 golden。
- 比较器 `compare.py:350` 已按 kernel dtype 截断 golden → 与 eval 判定一致（构造性保证，§2.9）。
- 优点：harness 与 eval **逐位同参考**，从机制上消灭假收敛；cann-bench 零改动；golden_precision
  成为显式契约，可 per-op 声明（CLI `--golden-precision` / manifest）。
- 缺点：对齐后 debug loop 会诚实显示 7 例失败，resize_bilinear 需要进一步 kernel 优化才能过
  fp64 参考（见下文「对齐后的算子侧影响」）。

**方案 B — 把 eval 的 golden_precision 改成 native_cpu【否决】**
- 让 eval 也用原生参考（当前 kernel == native torch 即 20/20 过）。
- 否决理由：① 违反用户「不改 cann-bench」约束；② 偏离 desc.md 声明的生态算子精度标准
  （fp64-referenced MERE/MARE）；③ 放宽标准掩盖真实精度损失——「把评测调松让 kernel 过」是
  §1.2 反对的规避方案。

**方案 C — harness 运行时读 cann-bench bench config 的 golden_precision【备选，已否决】**
- devkit 在 harness 构建时查询 `BenchRegistry.get('cann').golden_precision`。
- **否决（2026-08-10 确认）**：DevKit 进程实测 import 不了 cann-bench（`ModuleNotFoundError`，
  只有子进程 harness 通过结构锚点能定位）；动态读需把 cann-bench 挂进 DevKit 进程 sys.path，
  违反 §1.7 自闭环。CannBenchBackend 在 DevKit 进程侧同样不可行。保持方案 A 的静态默认
  fp64_cpu（与 cann-bench 当前默认一致）；若 cann-bench 将来改默认，devkit 改一行默认值即可。

### 对齐后的算子侧影响（resize_bilinear）
- 对齐后 harness 判 13/20（与 eval 一致），debug loop 会继续修 7 例。
- 7 例失败的参考侧根因：kernel 当前用 **fp16/bf16 权重量化**（round-2 为对齐 native torch 引入）
  偏离 fp64 精确权重；且近零输出上 fp16 舍入/相消被 MARE 放大。
- 可达性实证：native torch fp16 相对 fp64 截断参考 MERE=0.000777/MARE=0.147（挂）；
  干净 fp32 加权和 MARE 仍挂（相消误差 ~1e-5 绝对）；**需「fp32 权重（去掉量化）+ 近精确累加
  （FmaSoft 级，误差 ~2^-48）+ 末尾一次舍入」**才可过 MARE 阈值（相对误差 ~1e-3 < 9.77e-3）。
- 该 kernel 改进由对齐后的 precision_debug loop 自行完成（harness 会诚实报 7 例失败并引导修复），
  框架不手写 kernel。

## 附录：离线重算证据
```
# 真实 kernel == native torch fp16（harness 实证 diff=0.0）。同输入 seed：
#   case_seed = int.from_bytes(SHA256(case_id)[:8], 'big') % 2^31
compare_tensors(output=native_torch_fp16, golden=fp64_interpolate, dtype=float16)
  → case4: passed=False MERE=0.000777 MARE=0.147   （与 eval 报告逐位一致）
compare_tensors(output=native_torch_fp16, golden=native_fp16, dtype=float16)
  → case4: passed=True  MERE=0.0 MARE=0.0          （与 harness 一致）
```

---

## 追加决策（2026-08-11，批跑系统性模式 2/3/4 + 模式1-attrs，逐 log 复核实证）

> 下述决策的 L1 证据 + 现象拆解见 `05-batch-framework-patterns.md`。此处只记「选项 → 选哪个 → 为什么」。

### D1：harness 补缺用例 attrs（模式1-attrs，§2.9 构造性）
- **问题**：resize_bilinear run_tests 崩（`missing value for scale_factor`）——m.def 声明 `float[2]? scale_factor`
  可选类型但无默认（torch 要求 kwarg 必须传），harness 只传用例 attrs（output_size）不补 None。
- **候选**：A=harness 按 op_spec 声明补齐缺的 attrs（optional→None、有默认→默认值）；B=让 codegen m.def
  给 optionals 加 `=None` 默认；C=要求 test_design 用例必含全部 attrs。
- **选 A【采纳】**：镜像输入侧 None 占位语义（§2.5 单一通路），结构信号（op_spec 声明）驱动不认算子名
  （§1.12）；不依赖 test_design 完备性（C 对 XOR 语义不可知）也不改 codegen 生成（B 属 codegen 侧加固）。
  B 的 op_spec⊆m.def 校验归入模式1-codegen 可选加固。

### D2：changed_files 报告构造性派生（模式4，§2.9 构造性 > 检查门）
- **问题**：6/6 假「agent didn't report」——真根因是**读写契约断裂**（skill 让 agent 写 staging、框架从
  op_dir 读，三处错位：位置/格式/路径基准），非 agent 纪律。
- **候选**：A=框架从 git diff 派生权威报告进 artifacts（§2.9 构造性）+ agent 自报降为交叉校验；
  B=强制字段+空报拒绝重试（惩罚框架自己的 bug、烧一整轮 codegen、违背 §2.9 discover+regenerate）。
- **选 A【采纳，用户拍板】**:审计链永远完整不依赖 LLM 纪律；改动面 `_shared.py` 两函数，不穿 backend。
  解析器学会 agent 的 section 格式 + 后缀归一化；skill 改在 cwd 写报告（读端对齐）。

### D3：harness_timeout_sec 框架自有化（模式3，§2.9 机械可派生事实不靠 LLM）
- **问题**：agent 重写 control.json 弄丢 harness_timeout_sec → PD-CONTRACT WARN + 放大值打回默认 120。
  但放大值本来就是确定性脚本（build-failed-case-queue.py）算的——agent 唯一残留责任是「保留字段」，
  属错位责任。
- **候选**：A=框架自有 sidecar（`harness_timeout.fw.json`）+ 契约缺省静默 + debug_service 读
  control.json→sidecar→默认；B=runner 层 TimeoutExpired 自动 ×4 重试（改动面大：runner+skill×2+scope-guard）。
- **选 A【采纳，用户拍板】**:小改直接回答「为何 agent 要输出时间字段」——它不该；sidecar 让放大值
  agent 碰不到。B 作为将来更彻底方向记录。

### D4：eval_seed 契约化（review F3 坐实）
- **问题**：harness 模板硬编码 `_eval_seed = 0`，靠注释对齐 kernel_eval `config.eval_seed` 默认——
  将来 kernel_eval 改默认或 scorer 传非零 → 两侧输入分裂（静默假收敛）。
- **候选**：A=eval_seed 经 golden_contract 显式传（state 字段 + scorer `--eval-seed 0`）；B=保持硬编码。
- **选 A【采纳】**：耦合显式化、可查（contract 字段 + scorer 参数 + UT 断言）；两侧漂移有可见信号。
