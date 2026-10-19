# R1: missing_artifact 烧稀缺的 iteration 预算，无独立重试通道

**状态**: 待修
**层归**: L1 问题记录（只述事实，不提方案）

## 哪里坏了？

设计子阶段（tiling 等）的产物缺失（missing_artifact）**直接消耗该 stage 的 iteration 预算**，而 iteration 预算被配得非常小（tiling=2），导致一次"文件放错目录"的确定性错误就能把预算烧光、直接 halt。

## 凭什么这么说？（证据）

**事实 1：T2 两次 iteration 都被 missing_artifact / 质量不过 占用，预算 2 次即耗尽**

`output/20260821-111953-bca2fa/20260821-111953-af8b09/events.jsonl`：
```
11:38:35  iteration_start  iteration=1  reason=""
11:45:09  iteration_start  iteration=1  reason="contract unsatisfied: tiling_results"
11:52:34  iteration_start  iteration=2  reason="quality check not satisfied"
11:55:20  stage_complete（halt）
```

T2 总共只有 2 次 iteration 预算，两次都被"产物未就位"（缺 tiling_split.json）消费。第 2 次后预算耗尽 → `fail_strategy=halt`。

**事实 2：iteration 预算来自配置，tiling 仅 2**

`resources/orchestration-config.json`:
```json
"iterations": { "stages": { "tiling": 2, ... } }
```
`src/ascendc_devkit/orchestration/base.py` Stage 基类默认 `default_max_iterations: int = 3`，但 tiling 被配置覆盖成 2。

**事实 3：codegen 有独立 artifact-retry，设计子阶段没有**

`resources/orchestration-config.json`:
```json
"codegen": { "artifact_max_retries": 5 }
```
codegen 的 manifest 非契约走独立 `artifact_max_retries`（不烧 codegen 的 40 次迭代预算），而设计子阶段的 missing_artifact **没有独立重试通道**，直接烧 iteration 预算。

**事实 4：missing_artifact 是"确定性可纠正错误"，与"模型迭代能力"语义不同**

`src/ascendc_devkit/orchestration/stages/design_substages.py` 的 `_missing_artifact_error` docstring 明确写着设计意图：
> "The iteration budget exists precisely so a misplaced product gets corrected with a targeted hint, not halted on first miss."

但实现上没有给 misplaced product 独立 retry 通道，导致它和"迭代产出不达标"共用同一份稀缺预算。

## 影响

- 一次"文件放错目录"（agent 路径幻觉，模型行为问题，可纠正）就能让一个算子 halt，浪费整条 worktree/推理链。
- 与 codegen 的 `artifact_max_retries` 设计不一致——同为"产物未按契约就位"，一个走独立重试、一个烧迭代预算。
- tiling 是 ForkJoin 分支（T1/T2…），一个分支 halt 整组 halt，放大影响。

## 与既有问题编号的边界

- **F10**（budget-vs-failure-mode, 4a7af7db）："各 stage 重试预算与失败模式不匹配"。F10 是**跨 stage 统一预算语义**的收口（A3/A5 codegen 统一 40）；R1 是**设计子阶段内部** missing_artifact 与 iteration 预算的归并，是 F10 语义在设计子阶段的落点空白。R1 修后补全 F10 未覆盖的设计侧。
- **F11**（silent-cut-not-counted-in-iteration, 73a85f75）："silent-cut 不消耗 iteration 计数，日志读数误导"。F11 已修（silent-cut 恢复日志标注两套计数）；R1/R2 是在 F11 之上**仍存的**"真正的 missing_artifact 重试也烧预算且不可观测"的问题。F11 修的是"cut 不烧预算但日志不标"，R1 是"非 cut 的缺产物重试烧预算且无独立通道"。
- 两批（20260820 与 20260821）同为 pangu 模型，但 F 系列批的 halt 是 F1/F3（孤儿产物收集）+ F5（empty_artifacts 语义），R 系列批的 halt 是 missing_artifact 预算归并——根因不同，独立跟踪。
