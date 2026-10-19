
# Perf — 性能调优

> **所属架构**：[ascendc-devkit 架构总览](../architecture-overview.md) > §3 统一 Pipeline
> **实现状态**：已实现 ✓（自动注册, 由 GraphExecutor 经 AtomicStage 驱动）
> **位于 L3**: `orchestration/stages/perf.py`

---

## 1. 定位

在编译和精度验证通过后，对算子进行性能调优。Perf Stage 有自己的 Agent（`perf-tuner`）、自己的 Gate、自己的迭代循环。**修改代码发生在 Perf Stage 内部，不跳回 codegen stage。** 事件流保持线性。

性能修改分两类，Perf Stage 只处理第一类：

| 类型 | 例子 | 谁来做 | 在哪里做 |
|---|---|---|---|
| **战术性** | loop unrolling、流水排布、UB 双缓冲、数据预取 | `perf-tuner` Agent | Perf Stage 内部迭代循环 |
| **战略性** | 换 Tiling 策略、拆分子 Kernel、改变数据流拓扑 | 回到 design stage | 新 workflow run（`--resume --restart-from design`） |

战术性修改的判别标准：**不改变 TilingData 结构体、不新增 TilingKey 分支、不改变 Kernel 的 Init/CopyIn/Compute/CopyOut 流程骨架**。

---

## 2. Mode 差异

无差异。new 和 incremental 共用同一 Perf Stage——编译通过的算子逐 shape 跑性能基准，不达标则战术调优。

---

## 3. IO 契约

### 3.1 input_contract

```python
def input_contract(self) -> StageIOContract:
    return StageIOContract(
        requires=["build_result", "precision_result", "op_identity", "requirement", "npu_id"],
        optional=["generated_sources", "perf_baseline", "last_perf_profile"]
    )
```

### 3.2 output_contract

```python
def output_contract(self) -> StageIOContract:
    return StageIOContract(
        provides=[
            "performance_result",       # PerformanceResult (passed + metrics)
            "perf_iterations",          # int: 实际迭代次数
            "perf_needs_redesign",      # bool: 战术性修改无法满足目标
            "perf_profile_report",      # 性能分析报告（含 bottleneck 定位）
        ]
    )
```

---

## 4. Gate

`PrecisionPassedGate`：Verify stage 的精度验证已经通过。

如果需求中没有性能目标（`requirement.constraints.perf_baseline` 不存在），本 Stage 自动跳过（`gate() → SkipGate`），直接进入 integrate stage。

---

## 5. Actions

```python
def actions(self, state: State, iteration: int) -> list[Action]:
    # 1. 跑性能基准
    actions = [
        RunGate(
            gate_name="performance",
            evidence={
                "compiled_kernel": state.build_result.artifacts,
                "baseline": state.requirement.constraints.perf_baseline,
                "npu_id": state.npu_id,
            },
        ),
    ]

    # 2. 如果性能不达标 → Agent 分析瓶颈 + 战术调优
    perf_result = state.performance_result
    if perf_result and not perf_result.passed:
        # 先判断是否需要战略性修改
        if self._needs_strategic_change(perf_result, iteration):
            state = state.with_updates(perf_needs_redesign=True)
            # Stage 以 needs_redesign 退出
            return []

        # 战术性修改：Agent 在算子仓 op_dir 内调优
        actions.append(
            SpawnAgent(
                agent_name="perf-tuner",
                prompt=self._build_tuning_prompt(state, iteration),
                context={
                    "current_code": state.generated_sources,
                    "performance_result": perf_result,
                    "last_perf_profile": state.last_perf_profile,
                    "hardware": {"chip_version": state.chip_version},
                },
                skills=["ascendc-profiling"],
                # cwd = 算子仓 op_dir，Edit 直接改仓；改动经 git diff 收集
                working_dir=state.op_identity.op_dir if state.op_identity else None,
                repo_baseline=state.repo_baseline_ref or None,
                repo_root=state.op_identity.repo_root if state.op_identity else None,
            ),
        )

    return actions

def _needs_strategic_change(self, result, iteration: int) -> bool:
    """判断是否需要战略性修改。条件：已经试过 3 次战术调优仍不达标。"""
    if iteration >= 3 and not result.passed:
        return True
    return False
```

---

## 6. Agent 交互

| Agent | 关联 Skill | 用途 |
|---|---|---|
| `perf-tuner` | `ascendc-profiling`（性能分析） | 分析瓶颈 + 战术调优 |

Prompt 关键要素：
- 当前性能数据（逐 shape 耗时 + baseline + 差距）
- 性能分析报告（bottleneck 定位：计算密集 vs 访存密集 vs 流水空泡）
- 上次调优的修改摘要和效果（如有）
- 硬件参数（UB 大小、带宽、核数）
- **约束**：不能改 TilingData 结构、不能新增 TilingKey、不能改 Kernel 流程骨架

---

## 7. 迭代行为

`max_iterations = 3`（非交互模式默认；可在 `resources/orchestration-config.json` 的 `iterations.stages.perf` 全局调整）。

```
iteration 1: 跑 perf → 不达标 → Agent 分析瓶颈 → loop unrolling
  → 重编译 → 跑 perf → 快了 15%，仍不达标
iteration 2: 跑 perf → 不达标 → Agent 分析 → UB 双缓冲
  → 重编译 → 跑 perf → 快了 30%，达标 ✓
→ Stage 完成
```

```
iteration 3 仍不达标:
  → _needs_strategic_change() 返回 True
  → state.perf_needs_redesign = True
  → Stage 以 "needs_redesign" 退出
  → 退出码告知外部：需要战略性修改（回到 design stage 重新设计）
```

**为什么只有 perf 能升级回 design**：性能瓶颈往往由 tiling 粒度、多核切分、数据流编排等设计决策决定，且 perf 是在穷尽战术调优（loop unrolling / 双缓冲 / 预取等）之后才升级，归因明确指向设计。相比之下，verify 的编译/精度失败穷尽后是 `__halt__` 停机而非回 design——那类失败几乎都是实现 bug，自动改设计会帮倒忙。详见 `docs/stages/verify.md` §9。

**关键**：每次 Agent 修改后必须重编译 + 跑分——Perf Stage 内部有自己的编译流程。这与 Verify Stage 不同（Verify 不写代码，只验证；Perf 写代码 + 编译 + 验证）。

---

## 8. 错误分类

| 错误 | 类别 | 处理 |
|---|---|---|
| 性能不达标（iteration < 3） | Recoverable | 注入 profile 报告 → Agent 战术调优 |
| 性能不达标（iteration >= 3） | needs_redesign | 标记 perf_needs_redesign → 退出码建议重新设计 |
| Agent 调优后编译失败 | Recoverable | 注入编译错误 → Agent 修复（不计入迭代） |
| NPU 不可用 | Fatal | 退出码 78 |
| 编译超时 | Transient | 自动重试 |

---

## 9. 事件 schema

```jsonl
{"ts":"...","type":"stage_enter","stage":"perf","stage_name":"perf"}
{"ts":"...","type":"iteration_start","stage":"perf","iteration":1}
{"ts":"...","type":"action_start","action":"run_gate","gate":"performance"}
{"ts":"...","type":"action_complete","action":"run_gate","gate":"performance","result":"perf_insufficient","gap_pct":35}
{"ts":"...","type":"action_start","action":"spawn_agent","agent":"perf-tuner"}
{"ts":"...","type":"action_complete","action":"spawn_agent","result":"ok","changes":"loop_unrolling,double_buffer"}
{"ts":"...","type":"iteration_complete","stage":"perf","iteration":1,"result":"recoverable_error"}
{"ts":"...","type":"iteration_start","stage":"perf","iteration":2}
{"ts":"...","type":"action_start","action":"run_gate","gate":"performance"}
{"ts":"...","type":"action_complete","action":"run_gate","gate":"performance","result":"ok","gap_pct":3}
{"ts":"...","type":"iteration_complete","stage":"perf","iteration":2,"result":"ok"}
{"ts":"...","type":"stage_complete","stage":"perf","total_iterations":2}
```

### needs_redesign 退出的事件

```jsonl
{"ts":"...","type":"stage_enter","stage":"perf","stage_name":"perf"}
{"ts":"...","type":"iteration_start","stage":"perf","iteration":3}
{"ts":"...","type":"action_start","action":"run_gate","gate":"performance"}
{"ts":"...","type":"action_complete","action":"run_gate","gate":"performance","result":"perf_insufficient","gap_pct":45}
{"ts":"...","type":"iteration_complete","stage":"perf","iteration":3,"result":"needs_redesign"}
{"ts":"...","type":"stage_complete","stage":"perf","total_iterations":3,"exit_reason":"needs_redesign"}
```

---

## 10. 与邻 Stage 的关系

| 方向 | Stage | 传递数据 |
|---|---|---|
| 前置 | verify | build_result, precision_result, op_identity |
| 后置 | integrate | op_identity（调优后代码在 op_dir 内）, performance_result |
| 回退 | design | perf_profile_report (作为 `--resume --restart-from design` 的附加上下文) |

---

## 11. 战略性修改的回退路径

当 Perf Stage 以 `needs_redesign` 退出时，外部调度器或用户可以重新运行 workflow：

```bash
# 从 design stage 重新开始，带上 Perf Stage 的分析结论
ascendc-devkit run --workflow generate_ascendc --mode incremental \
    --resume <run_id> --restart-from design \
    --additional-context "perf_findings: tiling 策略需从 2-core 改为 4-core 分块"
```

这保持了 event sourcing 的线性模型：**每次 run 有自己的不可变事件流**，不出现 Stage 之间跳来跳去的复杂图。重构 design 后的新 run 从 events.jsonl 中读取前序上下文，Agent 看到修正后的 prompt。

---

## 附录：requirement.yaml — Constraint 性能字段

perf stage 独立运行时，通过 `--requirement` 注入性能基线。`constraints` 中 `kind: performance` 的字段：

```yaml
constraints:
  - kind: performance
    baseline_ms: 2.5
    shapes:
      - [1024, 2048]
      - [512, 4096]
    chip_version: "910D"
```

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `kind` | string | 是 | 固定值 `"performance"` |
| `baseline_ms` | float | 是 | 性能基线耗时 (ms)。Perf gate 判断实际耗时是否在此值以内 |
| `shapes` | list[list[int]] | 是 | 逐 shape 跑性能基准 |
| `threshold` | float | 否 | perf gate 的通过上界——实际耗时 ≤ threshold 即通过。不填则用 `baseline_ms` |
| `chip_version` | string | 否 | 限制芯片型号（默认当前检测到的芯片） |

`requirement.yaml` 中 `test_cases` 字段详见 [`verify.md`](verify.md) §附录。
