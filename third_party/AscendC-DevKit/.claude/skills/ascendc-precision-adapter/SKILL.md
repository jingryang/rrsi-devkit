---
name: ascendc-precision-adapter
description: TUI 版精度调试适配器入口。在不动 diagnose phase skill 的前提下,用用户自定义的编译命令 + 测试工具驱动完整精度调试闭环(run_tests 纯 Python 化后由框架确定性测量,脚本在框架包)。扮演框架 CompositeGroup 的角色:用 scripts/transition.py 做确定性状态推进,用 scripts/run_with_adapter.py 把任意测试产出适配成标准 result.json(case_details[])。diagnose skill 自带实施模式(定位后就地 Edit→build→test→commit),无独立 fix 阶段。触发词:精度调试适配器、TUI 精度调试、自定义测试工具跑精度、adapter precision debug。输入:一份 adapter_config.yaml/json(见 schema/adapter_config.json + examples/adapter_config.yaml)。
allowed-tools: Bash, Read, Write, Grep, Glob, Agent
---

# ascendc-precision-adapter —— TUI 精度调试适配器入口

> **定位**:本 skill 是 **driver(编排层)**,扮演框架 `CompositeGroup + GraphExecutor` 的角色,
> 把 2 个 phase skill 串成闭环。**不修改、不内联** 2 个 phase skill 的任何内容(§2.1 即插即用)——
> 它们保持独立,本 skill 通过「派 subagent + slash 投递(§4.3)」复用它们。
>
> **依赖声明（driver 类 skill，§2.1 唯一例外）**：本 skill 与 diagnose phase skill 共存于同一棵 `.claude/skills/` 扁平树;并单源引用（不 vendor 副本，§2.5）框架包内两个 standalone 脚本
> `<repo>/src/ascendc_devkit/orchestration/stages/precision_debug_run_tests/scripts/{init-checkpoint,build-failed-case-queue}.py`(standalone,
> 无框架依赖;run_tests 纯 Python 化后脚本迁入框架包)。若被单独取出,需连同 diagnose phase skill
> 与上述两个脚本一起。

## 核心思想:用 wrapper 把自定义命令"嫁接"进 phase skill

2 个 phase skill 期望 `control.json.build_command` / `test_command` 是可执行的命令字符串(原本是
`ascendc-devkit redeploy/run-cases`)。适配器的关键嫁接点:**把这两个字段填成本 skill 的 wrapper
命令**,wrapper 内部再调用户在 `adapter_config` 里声明的真实命令,并把任意格式的测试产出适配成
标准 `result.json`(`case_details[]`),让 `build-failed-case-queue.py` 直接消费。

```
control.json.build_command = "python3 <adapter>/scripts/run_with_adapter.py build   --config <cfg>"
control.json.test_command  = "python3 <adapter>/scripts/run_with_adapter.py run-test --config <cfg>"
```

phase skill 调 `test_command --case "<id>"` 做单用例时,wrapper 的 `run-test` 子命令本就接受
`--case`,内部用 `adapter_config.test_command_case`(含 `{case_id}` 占位符)跑用户真实单用例命令。
衔接零摩擦。

## 输入

调用方式:`/ascendc-precision-adapter <adapter_config 绝对路径>`

`adapter_config` 字段契约见 `schema/adapter_config.json`,可填模板见 `examples/adapter_config.yaml`。
必填:`operator_dir` / `op_name` / `chip` / `build_command` / `test_command` / `result_adapter`。

## 执行流程

### 0. 前置检查(失败即停,报清原因)

- diagnose phase skill 在位:`.claude/skills/ascendc-precision-diagnose/SKILL.md`（run_tests 已纯 Python 化，无 skill）。
- 测量脚本在位:`<repo>/src/ascendc_devkit/orchestration/stages/precision_debug_run_tests/scripts/{init-checkpoint,build-failed-case-queue}.py`。
- Ascend 环境:`npu-smi info` 可跑(否则提示用户先 `ascend-hardware`)。
- `adapter_config` 可读且必填项齐全(缺项列出来,不擅自默认)。

### 1. 解析配置,约定路径

从 `adapter_config` 读出:`operator_dir` / `op_name` / `chip` / `compile_work_dir` /
`debug_artifacts_dir`(缺省 `<operator_dir>/.precision-fix/debug/<op_name>/`)/ `max_rounds`(缺省 30)/
`time_budget_sec`(整轮时间预算,缺省 36000)。

确定两个绝对路径常量(后续命令反复用):
- `ADAPTER = <本 skill 目录>/scripts/run_with_adapter.py`
- `TRANSITION = <本 skill 目录>/scripts/transition.py`
- `INIT_CKPT = <repo>/src/ascendc_devkit/orchestration/stages/precision_debug_run_tests/scripts/init-checkpoint.py`
- `BUILD_QUEUE = <repo>/src/ascendc_devkit/orchestration/stages/precision_debug_run_tests/scripts/build-failed-case-queue.py`
- `CFG = adapter_config 绝对路径`

构造 wrapper 命令(写进 control.json):
- `BUILD_WRAP = python3 {ADAPTER} build   --config {CFG}`
- `TEST_WRAP  = python3 {ADAPTER} run-test --config {CFG}`

### 2. 初始化(若 control.json 不存在)

```bash
python3 {INIT_CKPT} \
  --operator-dir   {operator_dir} \
  --output-dir     {debug_artifacts_dir} \
  --test-command   "{TEST_WRAP}" \
  --build-command  "{BUILD_WRAP}" \
  --compile-work-dir {compile_work_dir} \
  --op-name        {op_name} \
  --time-budget-sec {time_budget_sec}
```

预创建 phase 产物目录(各 phase subagent 首次写入需要):
`{debug_artifacts_dir}/phases/{run_tests,diagnose}/`。

> init-checkpoint 会备份算子源码到 `{operator_dir}/.precision-fix/original_backup/`、记 git baseline、
> 写 control.json(含 wrapper 命令)+ 空 `precision_run_tests.json` + 空 `report.json`。

### 3. 闭环(run_tests 纯 Python 测量 + diagnose subagent + 确定性 transition)

```
phase = transition.py get-start --control {control}   # 首轮 = run_tests(或已 passed = DONE)
while phase not in (DONE, HALT):
    if phase == "run_tests":
        # 3.1 run_tests phase = 纯 Python 测量(不派 subagent)
        #     跑 wrapper 测试命令 → result.json → build-failed-case-queue.py 建队列
        python3 {BUILD_QUEUE} --result-json ... --output ...   # 建 failed_case_queue
        写 phases/run_tests/precision_run_tests.json(_summary: test_result/failed_count/total_count/max_err)
        RESULT = "RUN_TESTS_OK"      # 或测量命令失败 → RESULT="MEASURE_FAILED"(走 abort 退火)
    else:  # diagnose
        # 3.2 派 general-purpose subagent 执行 diagnose phase skill(§4.3 slash 投递)
        subagent prompt 首行 = /ascendc-precision-diagnose
        后续行 = 参数块(见下「diagnose subagent 派发模板」)
        收 subagent 返回文本 → grep 出 "RESULT: <CODE>"

    # 3.3 确定性推进 control.json + 决定下一 phase
    transition.py post-phase \
      --control {control} --phase {phase} \
      --result <CODE> --phase-json {debug_artifacts_dir}/phases/{phase}/{precision_<phase>.json} \
      --max-rounds {max_rounds}
    → stdout: "NEXT_PHASE=<target>  REASON=<...>"

    phase = <target>
```

> **abort 退火（run_tests 测量失败）**：`RESULT=MEASURE_FAILED`（wrapper 非零退出 / subprocess 异常）
> 与 diagnose agent abort 共用 `consecutive_aborts` 退火——连续 ≥3 次 → `abort_exhausted` → HALT，
> 否则回 run_tests 重试。与框架的 `measure_result.returncode != 0` 判据一致。

#### diagnose subagent 派发模板

```
/ascendc-precision-diagnose

你是 precision_debug 闭环的 diagnose phase agent。按 ascendc-precision-diagnose skill 的定义执行
(已通过本 slash 加载;references/schema 在该 skill 目录下)。

## 参数(cwd = operator_dir)
- control_path:      {debug_artifacts_dir}/control.json
- phase_json_path:   {debug_artifacts_dir}/phases/diagnose/precision_diagnose.json
- operator_dir:      {operator_dir}
- skill_dir:         <repo>/.claude/skills/ascendc-precision-diagnose
- op_name:           {op_name}    chip: {chip}
- build_command:     {BUILD_WRAP}
- test_command:      {TEST_WRAP}
- test_command_case: {TEST_WRAP} --case "<CASE_ID>"   # 单用例验证(diagnose 实施模式用)

## 关键说明(适配器场景)
- build_command / test_command 是适配器 wrapper,内部执行用户的真实编译/测试命令(见 adapter_config),
  并把测试产出适配成标准 result.json(case_details[])。你按 skill 定义调它们即可,无需关心 wrapper 内部。
- run_tests 阶段已纯 Python 化,由 driver 确定性测量——你只负责 diagnose(读 failed_case_queue + 判断失败性质 + 就地修)。
- 单用例(diagnose 实施模式):用 test_command --case "<case_id>",wrapper 会把 case_id 填进用户真实单用例命令。
- **框架打回段(弱模型就绪:拒因可见)**:派 diagnose 前读 control.json 的 `last_reject_reason`——当其
  `round == control.json 的 rounds` 时,把它渲染成 prompt 段(标题「## 框架打回(上轮 diagnose 产物被拒)」,
  含 cond + detail)插在参数块前;round 不匹配或字段缺失则不加。打回原因可见让 retry 带定向引导
  (与框架 `_reject_reason_block` 同语义;rounds 经 run_tests 回归 +1 后旧拒因自动过期)。
- 你 owner 的 phase 产物写到 phase_json_path(固定路径,无 round suffix),并在其中写 _summary。
- 写入纪律见该 skill 的 references/_shared-protocol.md(python3 原子化 read→modify→write)。

## 返回
输出恰好一行 RESULT(如 RESULT: DIAGNOSED_AND_FIXED / DIAGNOSE_UPSTREAM /
FIX_PARTIAL_OUTPUT / DIAGNOSED_NO_FIX),
附一句不超过 50 字概括。
```

phase → phase_json 文件名映射:
| phase | phase_json 文件 |
|---|---|
| run_tests | `phases/run_tests/precision_run_tests.json`(driver 测量写,无 subagent) |
| diagnose | `phases/diagnose/precision_diagnose.json` |

#### 路由(transition.py 内置,忠实复刻框架 transition_table:两段闭环 + 纯 Python run_tests)

- **run_tests**(纯 Python 测量,driver 执行):`status==passed`→DONE;`rounds>max_rounds`→HALT(exhausted);无失败→DONE;否则→diagnose
- **diagnose**(诊断+实施一体):DIAGNOSED_AND_FIXED→run_tests(全量回归确认 resolved_pending);DIAGNOSE_UPSTREAM→HALT(上游 codegen/golden/deploy 缺陷,给 upstream_stage+upstream_reason);FIX_PARTIAL_OUTPUT→run_tests(部分好转回归);DIAGNOSED_NO_FIX→advance case→diagnose(或末 case→run_tests);未知 RESULT→diagnose 重试;stalled 必须带 self_check(缺失打回 retry,§2.9)

### 4. 收尾(NEXT_PHASE ∈ {DONE, HALT})

读 `control.json` 汇总:
- `status==passed`:报告「精度调试通过」,列 history 里 resolved 的 case。
- HALT:报告停止原因——`upstream`(上游 codegen/golden/deploy 缺陷,给出 `upstream_stage` + `upstream_reason`,建议先修上游再回来)/ `exhausted`(轮数耗尽,列仍 skipped 的 case)。
- 列出 `failed_case_queue` 里 `status==skipped` 的未解决 case + 最后一次 `history` 条目的 `max_err`,供用户判断后续。

## 约束(不要做)

- **不改 2 个 phase skill 的任何文件**(§2.1)。本 skill 只编排,不改它们。
- **不写 `debug_result.json`**(框架终态产物,适配器场景以 `control.json` + `report.json` 为权威)。
- **不让 LLM 即兴改 control.json 的路由字段**——所有状态推进走 `transition.py`(确定性)。
- **不自造 result.json 解析**——用 `run_with_adapter.py`,三模式(builtin_preset/mapping/hook)覆盖;都不适用时让用户加 hook。
- **首次无 control.json 才 init**;已存在则跳过 init-checkpoint(支持 resume)。

## 已简化的框架语义(知情)

适配器忠实复刻路由与 history/case 推进,但以下框架优化语义**从略**(不影响闭环正确性):
- `best_*` 指标(stop-loss 用):轻量版未维护;`max_rounds` 仍是硬上限。
- `candidate_pool` 去重 / `corrective_cycles` / `diagnose_stalls` 早转:已删(减法收敛——diagnose 就地定位+修,无候选池/小循环)。
- printf/注释二分:已降为 diagnose skill 的就地技巧(见 `ascendc-precision-diagnose/references/techniques/`),不是独立 phase,adapter 无需路由它们。

需要这些精细语义时,用框架原生 CompositeGroup(DevKit 工程)而非本适配器。
