---
name: ascendc-precision-vector-error-debug
description: |
  Pipeline 叶子 skill（A5 Regbase 专用）：当 A5 precision_debug 的
  baseline、kernel_debug、vf_test 或 kernel_debug 修复后全量 KernelLaunch
  返回 VECTOR_ERROR 时，
  通过运行时证据归一化、A5 RegBase/VF 静态风险扫描、Top-K 定向安全
  消融、区域二分和行级确认定位 device vector error，实施修复并回验。
  单次运行返回阶段结论，不派下级 subagent。
allowed-tools: Read, Write, Bash, Glob, Grep, Edit
---

# A5 VECTOR_ERROR 定位与修复

## 定位与边界

本 skill 是 A5 `precision_debug` 的条件叶子阶段。仅在上游结果明确包含
`error_type=VECTOR_ERROR` 时执行。

负责：

- 用失败单 case 稳定复现原始 VECTOR_ERROR。
- 按五层顺序缩小范围：A5 静态规则 → Top-K 安全消融 → 区域 → 行 →
  多根因增量。
- 定位后实施实际修复，并用同一 case 确认原错误签名消失。
- 将过程写入 `{debug_dir}/vector-error/vector_error_round_{round}_result.json`。

不负责：

- 不判断普通数值精度问题，不运行全量精度回归。
- 修复成功后 Driver 路由回 `kernel_debug`，不进入 `pipeline_sync`（已删除）。
- 不控制阶段路由，不写 `debug_result.json`。
- 不更新 `checkpoint.json.best_snapshot`。VECTOR_ERROR 没有有效数值结果。
- 不修改 `checkpoint.json` 的 `status`、`phase`、任何 `*_round`、
  任何 `*_status` 或 `history`；这些路由字段只由框架维护。

## 输入

Driver 注入：

| 参数 | 说明 |
|------|------|
| `code_dir` | 算子源码目录，也是 cwd |
| `op_name` | 算子名 |
| `debug_dir` | precision debug 产物/日志根目录（`{debug_dir}/checkpoint.json` 及阶段产物） |
| `source_phase` | 发现 VECTOR_ERROR 的阶段 |
| `source_result_path` | 来源阶段 result JSON |
| `vector_error_evidence` | Driver 归一化后的 case、kernel、PC、错误码、日志等运行时证据 |
| `active_error_fingerprint` | Driver 基于稳定标识生成的当前错误指纹 |
| `build_command` | 重新编译部署命令 |
| `test_command` | run-cases 命令 |
| `current_round` | 当前 vector 调试轮次 |

开始前读取 `{debug_dir}/checkpoint.json`、`source_result_path` 及已有
`vector_error_round_*_result.json`。跨轮次必须沿用已有
`bisect_progress`、`experiments` 和 `located_roots`，不得重复实验。

修复成功后 Driver 回 `kernel_debug` 做回归验证，不跑全量回归。

## 统一判定信号

只使用编译、单 case 运行结果和错误签名：

| 结果 | 判定 |
|------|------|
| `same_error` | 仍出现与 baseline 相同的 VECTOR_ERROR/error_code/fingerprint |
| `error_disappeared` | 原 VECTOR_ERROR 消失，且没有新的 device exception |
| `different_error` | 原错误消失但出现另一错误；不能视为根因已确认 |
| `compile_fail` | 临时消融无法编译，实验无效 |
| `not_reproduced` | 未修改源码时原始问题不再出现 |

禁止使用 device-side `printf` 作为证据。发生 VECTOR_ERROR 的 kernel
可能无法刷新输出。

每次运行只执行目标 case：

```bash
{test_command} --case "<case_id>"
```

如果 evidence 没有 `case_id`，从来源 result 的 failed cases 中选择首个
`failure_type/error_type=VECTOR_ERROR` 的 case。仍找不到时返回
`unresolved`，不得运行全量用例代替。

## Step 0：归一化证据并建立复现基线

1. 读取 Driver 提供的 `vector_error_evidence` 和
   `active_error_fingerprint`。证据可能包含：
   `case_id/error_code/kernel_name/pc/pc_offset/fault_va/exception_type/
    run_log/plog/stderr_excerpt/device_id/task_id/stream_id/tiling_key/
    source_phase`。
2. 记录 `evidence_quality`：
   - `pc_mapped`：有 kernel 且有 PC/PC offset；
   - `runtime_identified`：有 kernel 和 error code；
   - `partial`：只有 case 或 error code；
   - `insufficient`：缺少以上稳定标识。
   不得自行用 `run_log/plog/stderr_excerpt` 等每次运行会变化的文本替换
   Driver 指纹。
   Driver 只会解析 phase result 中显式携带的 `stderr_excerpt`，或
   `runtime_evidence.stderr/log_text/plog_text/exception_text/message`
   文本；不会自动查找、读取“最新”或全局 plog，也不会把 `run_log/plog`
   路径当作日志正文。若关键证据缺失，leaf 只能读取输入中明确给出的
   `run_log/plog` 路径补证，并在结果中记录实际读取路径。
3. 检查工作树，记录调试前已有改动。不得覆盖用户原有修改。
4. 使用当前源码执行一次 `{build_command}`。
5. 运行目标 case，记录 error code、kernel、PC、关键日志和复现结果。
6. 与 `source_result_path` 对比：
   - 相同错误：进入定位。
   - 暂时不复现：再执行最多两次；仍不复现则返回 `not_reproduced`。
   - 变成其他错误：记录 `different_error`，返回 `unresolved`。
7. 记录 `reproducibility`，至少包含执行次数、失败次数和
   `stable/intermittent/not_reproduced` 判定。
8. 创建本轮 `error_signature`，沿用 `active_error_fingerprint`，后续所有
   实验以它为 baseline。若 `evidence_quality=insufficient`，只允许补充
    运行证据或保守复现，不得宣称已定位根因。

## Step 1：A5 静态规则扫描与候选排序

复现 baseline 后、修改源码前，必须先运行 skill 自带的确定性扫描器：

```bash
python3 "${skill_dir}/scripts/scan_a5_vector_risks.py" \
  --operator-dir "${code_dir}" \
  --evidence "${debug_dir}/checkpoint.json" \
  --output "${debug_dir}/vector-error/vector_error_round_${current_round}_static_scan.json" \
  --pretty
```

扫描器只读 C/C++ 源码，自动排除 `build/output/.git` 等生成目录。它会：

- 忽略注释和字符串中的 API 名。
- 轻量识别 SIMD/SIMT VF 范围和 API 调用，不假装是完整 C++ parser。
- 覆盖 `gm_ub_transport/ub_reg_load_store/mask_tail/address_generation/
  layout_cast_dist/vf_call_abi/incore_sync/queue_lifecycle/
  crosscore_tscm/tiling_boundary`。
- 用 P0 evidence 调整排序：trap/fault address 偏向访存和地址；VF 现场
  偏向 Load/Store、Mask、ABI；finalize/double/intermittent 偏向同步。
- 只输出 `candidate/suspected`，不会输出 confirmed root cause，不修改源码。
- 将分数约束在 0..100；kernel/PC 只作为运行时证据，不虚构 PC→源码映射。

若只需检查已知源码，可用 `--source file1.cpp file2.h` 代替
`--operator-dir`。证据 JSON 可为 checkpoint、phase result、P0
`vector_error_evidence` 或本阶段已有结果。

读取扫描结果中的 `classification/static_findings/candidate_ranking`。
优先消费尚未出现在 `experiments/located_roots` 的 Top-K 候选。只针对
实际进入 Top-K 的 subtype 按需读取
`references/a5-static-rules.md` 对应小节，避免一次加载无关规则。

扫描器是候选生成器而不是裁决器：

- 命中 API 只表示需要结合 tiling/runtime 复核。
- 所有对齐、dtype、LoadDist/StoreDist、资源等接口规则必须查询目标
  SoC 和当前 CANN 的 910D API 文档；禁止凭摘要硬编码结论。
- `evidence_quality=insufficient` 或无候选时保持保守，进入 Step 3
  区域二分，不得声称静态扫描已确认根因。

## Step 2：P2 受控实验计划与安全门

这是默认入口，优先于区域二分。不得根据自由文本临时设计消融；必须先把
P1 Top-K 转成稳定计划：

```bash
python3 "${skill_dir}/scripts/plan_a5_vector_experiments.py" plan \
  --static-scan "${static_scan_path}" \
  --evidence "${debug_dir}/checkpoint.json" \
  --build-command "${build_command}" \
  --test-command "${test_command}" \
  --baseline-reproduced \
  --output "${experiment_plan_path}" --pretty
```

若存在上一轮 result，额外传 `--history`，planner 会跳过
`experiments/located_roots` 中已检查候选。每轮最多规划 4 个实验，稳定
`experiment_id`，详细 recipe 按需读取
`references/a5-experiment-patterns.md`。layout/cast/dist 无当前 SoC/CANN
等价证明时必须 blocked/deferred；不得试改模板参数。

在修改任一源码前建立只读 SHA256 baseline：

```bash
python3 "${skill_dir}/scripts/plan_a5_vector_experiments.py" manifest \
  --operator-dir "${code_dir}" --plan "${experiment_plan_path}" \
  --output "${baseline_manifest_path}" --pretty
```

严格按 plan 一次执行一个实验：仅应用其局部 patch，编译，只运行目标 case，
按原 fingerprint 分类 outcome，然后反向应用该 patch。禁止裸删
DataCopy，禁止破坏 Queue/Event/producer-consumer，禁止用
`git reset/checkout` 回滚。若实验需要修改 plan 未声明的源码文件，必须 defer
并重新生成显式覆盖该文件的计划，不得绕过 manifest。

每次回滚后更新 execution records，并调用只读 guard：

```bash
python3 "${skill_dir}/scripts/plan_a5_vector_experiments.py" validate \
  --operator-dir "${code_dir}" --plan "${experiment_plan_path}" \
  --manifest "${baseline_manifest_path}" --records "${experiment_records_path}" \
  --output "${experiment_validation_path}" --pretty
```

只有 `valid_for_inference=true` 的 `same_error/error_disappeared` 才能影响
候选判断；`compile_fail/different_error/not_reproduced/not_run`、单变量或
不变量未确认、build/run 缺失、rollback hash 失败均无效。只有有效的
`error_disappeared` 可进入 Step 4。guard 要求 execution record 记录本次
run 对原 fingerprint 的观测，并在源码 hash 恢复后再次运行目标 case、复现
原 fingerprint；缺少恢复后运行证据不得用于推理。
候选完成仍无结果时进入 Step 3。

## Step 3：区域二分

按实际 kernel 结构建立区域，不要求函数名完全一致：

```text
CopyIn / address calculation
Compute / VF
CopyOut
Tail
Queue and synchronization
```

对区域做可编译的语义闭合替代：

- 保留输出、队列和同步协议需要的最小占位路径。
- 不允许直接删除生产者后仍执行消费者。
- 不允许破坏所有核都必须参与的同步。

区域替代后重新编译并运行单 case：

- 原错误消失：根因在被替代区域内。
- 原错误仍在：根因在保留区域内。
- 出现不同错误或编译失败：该划分无效，恢复并选择更安全边界。

持续二分至一个小代码块，将 `bisect_progress.granularity` 设置为
`line`。若本轮已达到 4 个实验，保存当前边界并返回 `unresolved`，
下一轮继续。

## Step 4：行级确认

先消费 P2 guard 中 `valid_for_inference=true`、
`root_cause_confirmation_allowed=true`、outcome 为 `error_disappeared` 的
实验。该实验还必须同时通过 `outcome_fingerprint_consistent`、SHA256
rollback、`changed_files_within_scope`，并在恢复源码后再次观测到 P0 原
fingerprint。它只允许进入行级确认，不能直接进入修复层；对于 runtime
case、buffer/core 差分尤其不得把“因素相关”误写成具体代码行根因。

在候选锚点执行一次最小依赖组确认，必须同时满足：未修改 baseline 复现、
安全消融后原错误消失、恢复后原 fingerprint 再次出现、A5 invariants
不被破坏。缺一项都不得进入修复层。

动态确认记录示例：

```json
{
  "experiment_id": "a5ve-...",
  "file": "relative/path.cpp",
  "line": 123,
  "api": "DataCopyPad",
  "fingerprint": "a5-vector-v1|...",
  "evidence": "baseline -> disappeared -> restored",
  "error_code_before": "...",
  "error_code_after": "",
  "confidence": "confirmed",
  "confirmation": {
    "baseline_reproduced": true,
    "error_disappeared": true,
    "restored_original_fingerprint": true,
    "invariants_verified": true
  }
}
```

静态 `candidate/suspected` 不能写成 confirmed。将通过上述动态门禁的记录
追加到 experiment records 的 `located_roots` 及阶段结果；后续轮次跳过已
确认并修复根因。

## Step 5：P3 修复计划、实施与回验

实施修复前必须运行只读 P3 planner：

```bash
python3 "${skill_dir}/scripts/plan_a5_vector_repairs.py" plan \
  --evidence "${debug_dir}/checkpoint.json" --static-scan "${static_scan_path}" \
  --experiment-plan "${experiment_plan_path}" \
  --experiment-validation "${experiment_validation_path}" \
  --experiment-records "${experiment_records_path}" \
  --located-roots "${experiment_records_path}" \
  --api-verification "${api_verification_path}" \
  --output "${repair_plan_path}" --pretty
```

`--located-roots` 是必需的流程门禁；缺少与 P2 experiment 绑定的完整行级
确认时 planner 必须 refused。若存在历史 repair result，再传 `--history`。
只允许实施 `status=ready/executable=true` 的最小修改意图；
详细 subtype 规则按需读取 `references/a5-repair-patterns.md`。所有 A5 API
修复必须先完成目标 910D/当前 CANN 的 `api_verification=verified`，不得保留
实验占位逻辑。

实施后写 repair execution record，再运行：

```bash
python3 "${skill_dir}/scripts/plan_a5_vector_repairs.py" validate \
  --repair-plan "${repair_plan_path}" --records "${repair_records_path}" \
  --output "${repair_validation_path}" --pretty
```

validator 要求 build passed、有 evidence；原 case 连续至少 2 次未出现原
fingerprint、无不同 device exception；修改范围、A5 invariants、API 证据、
restore artifact 和所有 ready verification matrix 均通过。只有
`repair_verified/vector_error_fixed_allowed=true` 才可返回 `fixed`。
普通精度失败只写 `next_hint`，不否定 VECTOR_ERROR 已清除。Driver 随后回到
`kernel_debug`，本阶段不跑全量回归。

## 输出文件

原子写入：

```text
{debug_dir}/vector-error/vector_error_round_{current_round}_result.json
```

Schema：

```json
{
  "phase": "vector_error_debug",
  "round": 1,
  "source_phase": "baseline",
  "vector_error_status": "fixed",
  "conclusion": "{一段话总结 crash 定位与修复结论，如 'case_2 VECTOR_ERROR 指纹为 VF_MEMORY/ub_reg_load_store，区域二分定位到 VF 输出越界写 UB，已修复并回验不再复现'}",
  "error_signature": {
    "error_type": "VECTOR_ERROR",
    "error_code": "",
    "kernel_name": "",
    "pc": "",
    "pc_offset": "",
    "fault_va": "",
    "exception_type": "",
    "fingerprint": "",
    "case_id": "",
    "run_log": "",
    "plog": "",
    "source_phase": "kernel_debug",
    "tiling_key": "",
    "evidence_quality": "pc_mapped"
  },
  "reproducibility": {
    "status": "stable",
    "run_count": 3,
    "failure_count": 3
  },
  "static_scan_path": "vector_error_round_1_static_scan.json",
  "experiment_plan_path": "vector_error_round_1_experiment_plan.json",
  "baseline_manifest_path": "vector_error_round_1_baseline_manifest.json",
  "experiment_validation_path": "vector_error_round_1_experiment_validation.json",
  "repair_plan_path": "vector_error_round_1_repair_plan.json",
  "repair_validation_path": "vector_error_round_1_repair_validation.json",
  "classification": {
    "fault_domain": "VF_MEMORY",
    "subtype": "ub_reg_load_store",
    "confidence": 0.88,
    "evidence_quality": "pc_mapped"
  },
  "static_findings": [],
  "candidate_ranking": [],
  "bisect_progress": {
    "granularity": "a5_static_topk",
    "suspect_region": "",
    "remaining_range": "",
    "dc_tqueue_candidates": [],
    "dc_tqueue_examined": []
  },
  "experiment_summary": {
    "planned_count": 0,
    "valid_for_inference_count": 0,
    "rollback_all_verified": false
  },
  "experiments": [],
  "located_roots": [],
  "repair_summary": {
    "ready_count": 0,
    "repair_verified_count": 0,
    "vector_error_fixed_allowed": false
  },
  "repairs": [],
  "root_cause": {
    "status": "confirmed",
    "file": "",
    "line": 0,
    "evidence": ""
  },
  "code_modified": true,
  "fix_summary": "",
  "verification": {
    "reproduce_case_passed": true,
    "vector_error_cleared": true,
    "repeat_count": 2
  },
  "error_type": "",
  "next_hint": ""
}
```

> **`conclusion`（必填，一段话字符串）**：本阶段结论，框架会把它物化到跨阶段接力文件
> `{debug_dir}/conclusions.json`（`conclusions_path`），后续阶段 agent 开工前读它即可
> 看到流程中其他 agent 的结论。请用自然语言写一段话，覆盖：本阶段干了什么、发现了什么、
> 得出什么结论。

字段规则：

- `vector_error_status` 只能是 `fixed/unresolved/not_reproduced`。
- `fixed` 时 `error_type=""` 且
  `verification.vector_error_cleared=true`。
- `unresolved/not_reproduced` 时 `error_type="VECTOR_ERROR"`。
- `error_signature.fingerprint` 必须沿用 Driver 提供的
  `active_error_fingerprint`；日志路径和日志正文不参与指纹。
- `evidence_quality` 只能是
  `pc_mapped/runtime_identified/partial/insufficient`。
- `reproducibility.status` 只能是
  `stable/intermittent/not_reproduced/unknown`。
- `static_scan_path` 使用稳定文件名
  `vector_error_round_{current_round}_static_scan.json`。
- `experiment_plan_path/baseline_manifest_path/experiment_validation_path`
  使用同一 round 的稳定文件名。`experiments` 必须保留 planner id、outcome、
  `valid_for_inference/root_cause_confirmation_allowed` 和各 gate 结果。
- `repair_plan_path/repair_validation_path` 使用同一 round 的稳定文件名。
  `fixed` 必须有至少一个 repair 的
  `repair_verified/vector_error_fixed_allowed=true`。
- `static_findings/candidate_ranking` 保留扫描器字段和稳定排序；每项
  `status` 只能是 `candidate/suspected`。静态规则不得写 confirmed。
- `classification` 是本轮候选优先级摘要，不替代 Step 4 的动态确认。
- 跨轮次复制并追加 `experiments/located_roots`，不得清空历史。
- 失败分支也必须写完整结果文件。

## 返回协议

写完结果文件后，输出一行简要结论和且仅一个标记：

```text
RESULT: VECTOR_ERROR_FIXED
RESULT: VECTOR_ERROR_RETRY
RESULT: VECTOR_ERROR_NOT_REPRODUCED
```

对应关系：

| status | RESULT |
|--------|--------|
| `fixed` | `VECTOR_ERROR_FIXED` |
| `unresolved` | `VECTOR_ERROR_RETRY` |
| `not_reproduced` | `VECTOR_ERROR_NOT_REPRODUCED` |

**最后一行必须再输出 `## RETURN:` 完成信号行**（编排层据此做路由判据之一；
缺失/非 COMPLETED 会判为 agent 自报状态异常并重试本 agent）：

```text
## RETURN: status=COMPLETED, phase=vector_error_debug, vector_error_status=fixed, code_modified={true|false}
## RETURN: status=COMPLETED, phase=vector_error_debug, vector_error_status=unresolved, code_modified=false
## RETURN: status=COMPLETED, phase=vector_error_debug, vector_error_status=not_reproduced, code_modified=false
## RETURN: status=FAILED, phase=vector_error_debug, error_type=ENV, code_modified=false
```

`vector_error_status` 与上面 RESULT 标记一致（`fixed` / `unresolved` / `not_reproduced`）。

> **语言硬要求**：`RESULT` 行、`## RETURN:` 行及其全部字段名（`status=` /
> `phase=` / `vector_error_status=` …）必须与模板**逐字英文/ASCII**，不得意译为
> 中文（如 `状态=`）。编排层按固定英文字段名做确定性解析——字段名写成中文会令
> 完成信号解析失败/错位（历史实证：`状态=COMPLETED` 未被识别时，
> `vector_error_status=fixed` 中的 `status=fixed` 子串被误读为状态，整轮结果废弃
> 并重派本 agent）。自然语言说明文字可用中文，机器可读标记一律英文。

## 硬规则

1. 单次调用最多 4 个消融实验。
2. 只跑目标 case，不跑全量测试。
3. 不依赖 device-side printf。
4. 不裸注释 DataCopy，不破坏 TQue 生命周期。
5. 每个临时消融实验必须恢复；只保留最终修复。
6. 不覆盖用户原有工作树改动，不提交临时消融。
7. 不写 `current_stage`、`debug_result.json` 或其他阶段 result。
8. 不更新 `best_snapshot`。
