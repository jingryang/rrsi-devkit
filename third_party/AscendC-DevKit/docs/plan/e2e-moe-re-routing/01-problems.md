# e2e-self-evolve 跑 moe_re_routing — 问题记录（L1）

> 纯事实快照（哪里坏了 / 凭什么这么说）。不提方案、不排顺序、不写决策。
> 算子：moe_re_routing（cann-bench L3，纯 gather/路由，4 输出，可选第 3 输入，int8/int32/int64）。

## P1 — e2e 脚本 chip 默认与硬件不一致
脚本曾默认 `CHIP=A2`（注释「对齐本机 910B3 硬件」），但本机为 Ascend950DT。
证据：`domain/chip.py`（A5 = David/950）、`adapters/npu/detect.py`（Ascend950 → A5）。
（已对齐为 A5；用户定调「都按 A5 来」。）

## P2 — precision_debug 耗尽掐断链路，跑不出 cann-bench 分数
链路末端 `cannbench_eval`（② 权威 LOSS 评分器）才产出分数，但前置 `precision_debug`（① 本地预检）
耗尽后 transition 落到 `__halt__`，链路中断、② 永不执行。
证据：`orchestration/workflow.py` SelfEvolveOpWorkflow TRANSITION_TABLE
`precision_debug.exhausted → (__halt__, escalation)`。

## P3 — devkit ① harness 按单输入单输出设计，对 moe_re_routing 失真
harness（`adapters/npu/runner.py` `_build_test_harness` + `domain/cann_bench_cases_loader.py`）
为 exp/add/sqrt 这类单输入单输出算子设计。moe_re_routing 是首个多输出算子，暴露 6 个失真点：

- **P3a**：多输出只比第 1 个（`kernel_out = kernel_out[0]`），后 3 个输出丢弃。
- **P3b**：golden 返回 tuple，`_golden_wrap` 只转单个 Tensor，tuple 经 `np.asarray` 形状错位合并。
- **P3c**：可选输入（case 4/5/7/17 的 per_token_scales）的 null shape 被解析成 `[None]` 喂进 kernel。
- **P3d**：未加载 golden 的 `get_input`；随机生成的 `expert_token_num_per_rank` 不满足
  `sum == A`，golden 直接 `assert` 崩 → 每个案例 max_diff=999。
- **P3e**：所有输入共用一个 `[low,high]`（tokens 误用 expert_token_num 的 [1,128]）。
- **P3f**：`_NP` 字典无 int32/int64 → 整数输入静默回落 float16，整数运算失真。

## P4 — 4 个 pre-existing UT 失败（与本轮改动无关）
`test_stages.py` / `test_plan_a_inrepo.py` 的 codegen `validate_inputs` 用例失败。
证据：失败信息「build target chip 'A2' 与当前硬件 'A5' 不匹配」——用例硬编码 target=A2，
本机 A5，codegen chip 门按设计报错。`git stash` 验证：干净 baseline 上同样 4 个失败。
属环境前置条件（A2-硬编码 UT 跑在 A5 机），不挡 A5 的 E2E 跑（CLI 传 A5，A5==A5 无 mismatch）。
