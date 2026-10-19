# L1 问题记录：op_plugin schema 参数序 + op_spec 畸形

> 层级：L1（事实快照，写定即冻结）。仅记录「哪里坏、凭什么这么说」，不提方案、不排顺序、不写决策。
> 来源 run：`20260727-144633-2a1db8`（gather 算子，cann-bench eval 20/20 case 0 分、halt）。

## P1 — op_plugin m.def schema 参数序：scalar attr 夹在 Tensor 输入中间

**现象**：
- run `20260727-144633-2a1db8` 的 gather 算子，cannbench_eval 20/20 case 全 0 分；
  `artifacts/precision_debug_a5/checkpoint.json` 的 `halt_reason` 指向 op_plugin schema arg-order。
- `max_diff=999.0` 是 framework 的 no-measurement 错误哨兵（非真实精度误差）。

**凭什么这么说（证据）**：
- proto.yaml（cann-bench 权威接口定义，54/54 算子均声明 `operator.schema`）的 gather 权威 schema：
  `gather(Tensor x, Tensor index, int dim=0) -> Tensor y`（序 `x,index,dim`、名 `x/index/dim`）。
  codegen 产出的 `gather(Tensor input, int dim, Tensor index)` 不仅顺序错、连参数名都偏离 proto.yaml
  （`input` vs `x`）—— proto.yaml 才是权威，codegen 套 torch 标准签名是接口对齐 bug。
- codegen 生成的 `gather_plugin.cpp` 的 `m.def` schema：
  `gather(Tensor input, int dim, Tensor index) -> Tensor` —— 标量 attr `dim` 夹在两个 Tensor
  输入中间（`/tmp/harness_direct.out` 的 torch dispatcher 原始报错 `Declaration` 字段；
  `baseline_result.json.supplementary_direct_harness_run` 在 device 3 绕开 507033 复现）。
- cann-bench eval harness 按 `func(*tensor_inputs, **attrs)` = `gather(input, index, dim=0)`
  调用 → position 1 的 `index` Tensor 被绑到 `int dim` → pybind cast 失败：
  `Expected a value of type 'int' for argument 'dim' but instead found type 'Tensor'`。
- kernel binary 从未被执行（cast 在 schema 校验阶段就失败）。

**根因事实**：
- codegen（LLM agent ascendc-dev-s4-coding）生成 m.def schema 时镜像了 torch 内置算子
  `torch.gather(input, dim, index)` 的规范签名，把 scalar `dim` 放在两个 Tensor 之间。
- proto（`codegen_manifest`：`inputs=[x,index], attrs=[dim]`）的正确序应为
  `[Tensor, Tensor, scalar]`，但 codegen 产出 `[Tensor, scalar, Tensor]`。
- 「Tensor inputs 在前、scalar attrs 在后」这条顺序契约，此前无任何 codegen skill/stage
  声明或校验 —— 仅作为**假设**存在于 `cannbench_adapt.py` 的 `align_schema_params` docstring
  注释里（consumer 声明、producer 无感知的跨层不变式失效）。
- 注：官方框架那次 init_iter-0 eval 实际崩在 NPU device 507033（zombie context 耗尽，
  `harness.py:180 set_device`），gather 调用点未到达；schema 缺陷由 supplementary direct
  run（device 3）独立确证。507033 是并存的独立环境问题，见 memory `npu-device-context-exhaustion-zombie`。

## P2 — op_spec 畸形：inputs/outputs 全被路由进 attrs（output `y` 进了 wrapper 参数）

**现象**：
- deployed `cann_bench/__init__.py` wrapper：`def gather(x, index, y, dim)` —— 多了 output `y`
  （应为 `def gather(x, index, dim)`）。

**凭什么这么说（证据）**：
- `state_snapshot.json` 中 gather 的 `op_spec`（design_spec 产物）：
  `{name: Gather, inputs: [], outputs: [], attrs: {x, index, y, dim}}` —— inputs/outputs 均
  空、全部参数（含 output `y`，其 `type=""`）被塞进 `attrs`。
- 同一 state 的 `codegen_manifest`（codegen 产物）正确：`inputs=[x,index], outputs=[y], attrs=[dim]`。
- `cannbench_adapt._generate_and_inject_wrapper` 此前从 `state.op_spec`（畸形）派生 wrapper 参数
  名序 → `[x, index, y, dim]` → `y` 进 wrapper；并使 P10 rename 因参数数量 4≠3 被跳过
  （`adapt_result.schema_renamed == []`）。

**根因事实**：
- `op_spec` 的畸形源自 requirement/design stage 的产物（`OperatorSpec.from_dict._route` 把
  inputs/outputs 全归入 attrs —— output `y` 的 `type=""` 是其被误分类的信号）。
- `codegen_manifest` 是 codegen agent 独立生成的，正确区分 inputs/outputs/attrs —— 与 op_spec
  形成「双真相源分裂」。
- 下游影响：`y` 进 wrapper 参数；P10 rename 因 count 不匹配被跳过（间接放大 P1 —— 即便
  schema 名对齐逻辑也因 count 失配而未运行）。
