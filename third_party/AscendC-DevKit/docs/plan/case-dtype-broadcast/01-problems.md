# 多输入算子空 dtype 穿透致 precision_debug halt — 问题记录（L1）

> 纯事实快照（哪里坏了 / 凭什么这么说）。不提方案、不排顺序、不写决策。
> 来源：批跑 run `20260805-100200-f778c4` 下算子 `foreach_addcdiv_scalar`
> （工作区 `output/home/x00584171/AscendC-DevKit/output/20260805-100200-f778c4/20260805-100200-c00f72/`）
> 的 run.log + 精度调试产物 + DevKit/cann-bench 源码。RCA 与定性判定详见会话分析；
> 本文只固化客观事实。
>
> **并发说明**：本工作子目录暂未挂载 L2 总纲（并发期保守起见不写共享文件
> `docs/plan/00-status-summary.md`），待统一挂载。独立新目录，不触碰共享索引。

## 背景：halt 发生在哪

整条流水线 entry → context → requirement → design → test_design → codegen 全部 done，算子编译
出包部署。precision_debug 首轮（iter-0/1）因**环境阻塞** halt（torch_npu 不可用 + ACL 500001 +
缺 `decorator` 模块 + GELib/OpsManager init failed，5 条 evidence 全归 `category=env`）——该阻塞是
环境问题，经人工处理后（iter-5）解除，非代码缺陷，本文不展开。

环境阻塞解除后，iter-5 run_tests 暴露**新阻塞**：全部 20 用例在 **input tensor 生成阶段**
（`elapsed_ms=-1.0`，kernel 从未执行）因**空 dtype 字符串**触发 `ValueError`；scope_guard 重判
`scope_verdict=upstream, upstream_stage=golden` → workflow 路由 `upstream → __halt__` → **整 run
终止**，`cannbench_eval` / `finalize` 未完成（该算子本批 0 有效评分产出）。

## P1 — cann-bench「单元素 dtype = 全体输入共享」约定未被 DevKit loader 广播，产出空串 dtype

**现象**：cann-bench `foreach_addcdiv_scalar` 的 cases.csv 对 3 个 tensor 输入声明
`dtype=["float32"]`（**单元素数组**，cann-bench 格式语义 = 全部输入共享该 dtype）。DevKit
`cann_bench_cases_loader.parse_cann_bench_csv` 把它当「每输入一个 dtype」的并行数组逐位取，
i≥1 时越界落到 `""`。

**证据**：
- `tasks/level1/foreach_addcdiv_scalar/cases.csv`（cann-bench 仓，5 行级）：每行
  `input_shape=[[[1024,1024],[1024,1024]], [[1024,1024],[1024,1024]], [[1024,1024],[1024,1024]]]`、
  `dtype=["float32"]`（单元素）。
- `src/ascendc_devkit/domain/cann_bench_cases_loader.py:92`：
  ```python
  raw_dtype = (dtypes[i] if i < len(dtypes) else "") or ""   # i≥1 → ""
  ```
  无广播、无长度归一。同一文件 docstring 自证该 loader 为 cann-bench 专属（「列名 / dtype map /
  value_range→generator 均按 cann-bench 约定」）。
- `artifacts/staging/test_cases.json`：全部 20 case 的 `input_0` 有真实 dtype（`fp32/fp16/bf16`），
  `input_1`、`input_2` 均为 `"dtype": ""`。

**影响**：DevKit 侧 `TestCase` 里多输入同 dtype 算子的后续输入 dtype 为空串 `""`（key 存在但值为
空），是后续 ValueError 的直接输入。

## P2 — 空串 dtype 穿透 harness → cann-bench data_generator `str_to_torch_dtype("")` ValueError → 20/20 kernel 前全灭

**现象**：iter-5 run_tests 全部 20 用例在 input 生成阶段抛
`ValueError("不支持的数据类型: . 支持的类型: [...float16, float32, ...]")`，`elapsed_ms=-1.0`
（kernel 未执行）、`diff=999.0`（sentinel 失败标记）。

**证据**：
- `artifacts/debug/foreach_addcdiv_scalar/run_tests_iter-5/run.log` traceback（每个 case 一致）：
  ```
  npu_harness_*.py:593 generate_input_tensors_from_case(
  cann-bench .../src/kernel_eval/data/data_generator.py:114 _generate_tensors
    :315 generate_input_tensor
    :53   torch_dtype = str_to_torch_dtype(dtype)
    .../src/kernel_eval/utils/dtype_mapper.py:82  raise ValueError(f"不支持的数据类型: {dtype_str}...")
  ```
- `artifacts/debug/foreach_addcdiv_scalar/run_tests_iter-5/harness.py`（materialized）：20 case 的
  `inputs[1]`、`inputs[2]` 均 `'dtype': ''`；harness 构建 dtypes 列表：
  `_DTYPE_NORM.get(i.get('dtype','fp16'), i.get('dtype','fp16'))` → `''` 原样进入列表。
- `run_tests_iter-5/run.log` stdout：`{"elapsed_ms": -1.0, "diff": 999.0, "output_comparisons": []}`
  ×20，全部一致（系统性 fixture 缺陷，非 kernel 缺陷）。

**影响**：DevKit loader 的空串经 runner（`runner.py:777 inp.get("dtype","fp16")` 对空串不生效）→
harness → cann-bench `data_generator.generate_input_tensors_from_case`。cann-bench 的广播
（`data_generator.py:108-109`）只处理 `len(dtypes) < num_inputs`（此处 3==3 不触发），空串直接落入
`str_to_torch_dtype("")` 抛错。

## P3 — scope_guard 判 `upstream[golden]` → `upstream → __halt__` → 整 run 终止、0 有效评分

**现象**：scope_guard 末轮重判 `scope_verdict=upstream, upstream_stage=golden`，evidence 指向
「test fixture/case 配置缺 dtype 字段（golden/test_design 产物缺陷，fix 修不到 kernel 代码之外）」；
workflow 路由 `upstream → __halt__`，整 run 终止。

**证据**：
- `run.log:6147` scope_guard verdict（upstream in golden）；`run.log:6187` HALTED 二次确认。
- `run.log:6189`：`Workflow halted: stage 'precision_debug' exhausted its correction budget ...
  at condition 'upstream'.`
- scope_guard evidence（`run.log:6149-6154`）逐条正确：空 dtype 位于 cann-bench 框架
  `src/kernel_eval/`、kernel 未执行、`observed_issues[0].category=golden`、首轮 env 阻塞已解除且
  与 iter-5 无关。**判定本身与事实一致**（非 kernel 缺陷），但触发 `upstream→__halt__` 一刀切终止。

**影响**：问题定性为「上游缺陷」正确（kernel 无责），但**根因链没有找到真正 producer**（DevKit
loader 未转写 cann-bench 广播约定），只归因到「case 配置缺 dtype 字段」这一层表象；run 终止，
该算子本批 0 有效评分。

## P4（对照事实）— eval 路径用 cann-bench 自家 loader 广播正常，不受此 bug 影响

**现象**：同一 run 的 `cannbench_eval`（`CannbenchScorer`）读 cann-bench 自家 `cases.yaml`，走
cann-bench CLI `kernel_eval`，**没有**出现 dtype ValueError。

**证据**：
- `src/ascendc_devkit/adapters/evaluation/cannbench_scorer.py:245-261`：discover bench-set root，
  读 `<op>/cases.yaml`，非 DevKit loader 路径。
- cann-bench `src/kernel_eval/benches/cann_loader.py:386-388`：
  ```python
  if len(dtypes) == 1 and len(input_shapes) > 1:
      dtypes = dtypes * len(input_shapes)
  ```
  自家 loader 显式广播单 dtype → 后续 `data_generator` 拿到完整 dtype，不触发空串。
- `subprocess/cannbench_eval_foreach_addcdiv_scalar.stderr.log`：仅 baseline metadata fallback
  （910b1→910b2）与 NPU padding 警告，**无 ValueError**。

**影响**：同一份 cases.csv 在 cann-bench 自家消费端合法（广播后正常到 kernel）——**证明数据本身
合法，缺陷是 DevKit loader 未转写广播约定**，而非用例数据错误。这也是「合法可推理 vs 输入错误」
定性的关键对照证据（见 `02-analysis.md`）。

## P5 — devkit 模式（非 cann-bench）存在同类根因的不同形态（对照事实）

**现象**：devkit 用例 producer（`adapters/testdesign/csv_to_testcases.py`）对 dtype 的处理与
cann-bench loader 不同，dtype 声明不足时表现各异：

**证据**：
- `src/ascendc_devkit/adapters/testdesign/csv_to_testcases.py:93`：
  ```python
  n = min(len(shapes), len(dtypes), len(formats)) if dtypes and formats else len(shapes)
  ```
  —— formats 非空且 dtypes 短时**静默截断输入数**；formats 空时按 `len(shapes)` 生成，但
  `:96-97` 仅 `if i < len(dtypes)` 才写 `entry["dtype"]` → 后续输入**无 dtype key**。
- testcase_csv.json（`AIInfra-OP-testdesign-generate-case-skill/schema/`）契约：`stc_input_dtypes`
  为**逐输入声明**的并行数组（example `('bfloat16','bfloat16')`），required_keys 含
  `stc_input_dtypes` —— **没有**「省略=广播」约定。
- `_harness_template.py:474`（DevkitBackend 路径）`_dt = i.get('dtype','fp16')`、
  `:491` `_NP2TORCH.get(..., torch.float16)`：缺失/空串 dtype → **静默落 fp16**（`''` 不在映射表
  走默认），不抛错。

**影响**：devkit 场景下若 LLM 对多输入同 dtype 算子按广播习惯只填一个 dtype，会静默截断输入数
（形态 A）或静默降级 fp16（形态 B，input_0 为 fp32/bf16 时测错 dtype、假通过/假失败、零报错）——
比 cann-bench 场景的显式 ValueError 更隐蔽。属「输入错误」（违反自身 schema 契约）而非合法推理。

---

## 不属本轮（排除项）

- **首轮 env 阻塞**（iter-0/1，torch_npu/ACL 500001/缺 decorator/GELib init failed）：环境问题，
  非代码缺陷，不修框架。
- **cann-bench 仓侧改动**：不在本仓修改范围。cann-bench 自家 loader/data_generator 行为正确，
  是 DevKit 未对齐其约定（§1.13 由 adapter 忠实转写上游事实）。
- **`upstream → __halt__` 路由本身**：与 `precision-scope-upstream-halt-eval-loss/` 正交——
  本文 P3 只是该 halt 路由的一次具体触发，不重复产权。
- **`cannbench_eval` 0 评分**（P4/P3 后果）：非本问题根因，不在本轮。
