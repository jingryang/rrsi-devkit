# Codegen execution group 实施方案

## 1. TDD

在 `test_codegen_s4_dispatch.py` 和 `test_codegen_regbase_phases.py` 先增加：

1. 连续同组步骤解析；VF 强制单例；缺 execution_group 安全降级。
2. COMPLETED 批量推进完整组。
3. FAILED/PARTIAL 只提交合法连续前缀并从失败点恢复。
4. 越界、乱序 completed_sub_stages 拒绝推进。
5. S4 prompt 携带授权子阶段列表，且不跨 VT。

## 2. 状态机

- `codegen_s4.py` 新增 `resolve_execution_group()` 和完成前缀校验/提交函数。
- `parse_return_signal()` 解析 `completed_sub_stages` 与 `failed_sub_stage`。
- `dispatch()` 按本次工作单元批量推进；无结构化列表时保守单步推进。
- `codegen.py` 调度 S4 时传入 `current_sub_stages`/`execution_group`，移除旧
  `vt_boundary` 扫描通路。

## 3. 生产者契约

- orchestration plan schema 增加 required `execution_group`。
- S2 prompt/Agent 说明按职责生成连续执行组，VF 仍单例。
- S4 Agent/phase prompt/编排说明从“一次一个 sub-stage”改为“一次一个
  execution group，组内逐 sub-stage 自检”。

## 4. 验证

- 定向：codegen S4 dispatch + Regbase phases + skill contract/shell tests。
- 回归：`tests/ut/orchestration/test_codegen_*.py`。
- 真实 heavy_llm codegen e2e 属分钟级/token 成本测试，按工程 §3.11 在用户确认后执行，
  不在本次默认测试中自动启动。

## 5. As-built（2026-08-13）

已完成：

1. `orchestration_plan.json` 增加 required `execution_group`；S2 按职责生成连续组，
   VF 强制单例，旧计划缺字段时消费端安全退化为单阶段。
2. S4 一次派发完整 `current_sub_stages`，并携带逐步骤 `checkpoint_groups`，避免
   Host/Tiling、API/Plugin 等跨旧检查点组时继承错误上下文。
3. Agent RETURN 增加 `completed_sub_stages`/`failed_sub_stage`；COMPLETED 必须覆盖
   整组，PARTIAL/FAILED 只提交合法连续前缀。backend fatal/partial 不采信文本进度。
4. 每个 sub-stage 仍逐项执行 Phase 0/1/2、自检落盘与变更摘要；VT、S5 保持独立门禁。

验证结果：

- 定向状态机与 Regbase phase：141 passed。
- codegen 相关回归：224 passed。
- 全量快速 UT：4137 passed，3 deselected。
- 全量快速 ST：93 passed，4 skipped，58 deselected。
- Skill 调度/集成/脚本全流程：18 + 130 + 63 passed。
- `compileall` 与 `git diff --check` 通过。

默认真实环境测试预检未满足：当前环境缺 LLM credentials、`torch_npu` 和 CANN
环境变量/编译器；heavy_llm 未经用户确认未运行。快速回归期间同时修复了三个既有的
环境可移植性问题：Skill 缺失 `get_repo_root.sh`、UT 依赖开发者绝对 output 路径、
ST 写只读 HOME；另修正 `CANN_ENV_SCRIPT=` 未按文档表示“沿用当前 shell”的脚本错误。
