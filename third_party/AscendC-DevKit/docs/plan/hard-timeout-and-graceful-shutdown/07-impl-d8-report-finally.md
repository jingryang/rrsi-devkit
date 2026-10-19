# D8 重 scope 实施方案 — report 收口（dispatcher finally，覆盖所有退出路径）

> 层级：**L4 / 实施方案**。本切片是对 L3 D8 原处方的**重 scope**（原处方有缺陷，见 `02-analysis.md` D8 末尾 + 用户已认同）。
> 决策：report 生成留在 dispatcher（唯一能看到整次运行 + 所有退出路径的组件），改 `finally`-block 覆盖**含 timeout 在内的所有终止退出**；清 FinalizeStage 的 inert `GenerateReport` action + 误导性 `report_generated` 死代码。

## 背景（为何不按 L3 原处方）

- **report** = 整次算子生成流水线的运行总结（markdown+json，从 events.jsonl 渲染），框架级产物，**非 cann-bench**。cann-bench 只是产 `eval_result` 分数的一个 stage。
- **dispatcher** = 框架顶层入口（L7），跑 workflow、捕获所有异常、写 snapshot、生成 report。report 必须每种退出都生成 → 落在 dispatcher 是固有正确耦合。
- 原处方「搬进 `FinalizeStage.teardown` + 删 dispatcher 调用」有缺陷：FinalizeStage 只在跑到最后才执行；timeout/early-stage 中断时**没跑** → 删 dispatcher 调用丢异常路径 report；且 `GenerateReport` action 是 inert marker（runner `else:pass`、transition 不引用）。
- **现状缺口**：timeout(:940)/env/card/sigint/cancel 路径**无 report**——硬超时场景目前就没有运行报告。

## 改动清单

### 1. `application/dispatcher.py`（核心）
- 主 try（:920）的 except 链后加 `finally:`：
  ```python
  _report_on_exit = True   # 在 try 前声明
  try:
      ...execute...
  except RunnerCancelledError...: ...; return EX_SIGINT
  except DecisionPendingError...:
      _report_on_exit = False   # pause 非终止，resume 时重生成；且 _generate_report
                                # 末尾扫 skills anchors 不该在 pause 跑
      ...; return EX_DECISION_PENDING
  except (WorkflowTimeoutError, StageTimeoutError)...: ...; return EX_TIMEOUT
  ...（其余 except 不变）...
  finally:
      if _report_on_exit:
          _generate_report(workspace,
                           run_elapsed_ms=int((time.monotonic()-run_start)*1000))
  ```
- 删 PreconditionError 分支里的显式 `_generate_report`（:955）——finally 覆盖。
- 删正常路径的显式 `_generate_report`（:997）——finally 覆盖（finally 在 try 正常结束时也跑，先于 :996+ 代码）。

### 2. `orchestration/stages/finalize.py`（清死代码）
- `actions()` 删 `GenerateReport(workspace=...)`（inert marker，runner 不执行、transition 不引用）。
- `transition()` 删 `report_generated=True`（re-scope 后 report 由 dispatcher 生成，FinalizeStage 设该 flag 是误导）。
- `output_contract()` 的 `provides` 删 `"report_generated"`。

### 3. `orchestration/kernel/state.py`
- 删 `report_generated: bool = False` 字段（无生产读处，仅测试断言）。

### 4. 测试/fixture 跟新
- `tests/fixtures/resume_all_done_state.json`：删 `"report_generated": false`。
- `tests/ut/orchestration/test_stages.py`：删 3 处 `report_generated` 断言（:1980/:2015/:2180）。
- `tests/st/test_integration.py::test_report_generated`：**不动**（它查 report.md/report.json 文件，与 re-scope 一致；finally 让它覆盖更强）。

## TDD

1. 新增 UT（红）：dispatcher 在 **timeout 路径**生成 report（mock executor 抛 `WorkflowTimeoutError` → exit EX_TIMEOUT + report.md 存在）；`DecisionPendingError` 路径**不**生成 report（pause）。
2. 落 finally + flag + 删显式调用 → 绿。
3. 清 FinalizeStage/state 死代码 + 跟新测试 → 全绿。
4. 全量回归。

## 验证

- 新增 timeout-report UT 绿；现有 `test_report_generated`（halt 路径）不回归。
- 全量 UT 零回归。
- **不跑** heavy_llm ST（真机超时 report 落盘属 S5，§3.11 用户确认）。

## 不在本切片范围
- 具体 stage teardown 重载 → 各 stage L4（S3 已落 hook）。
- SIGTERM / 进程组 / atexit → S4。
- heavy_llm ST → S5。
