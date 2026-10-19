# L1 问题记录 — run_test 与 cann-bench 耦合

> **性质**：L1 问题/需求记录。只记录客观事实（哪里坏了、凭什么这么说），不提方案、不排顺序、不写决策。
> **纪律**：遵守 `plan-doc-discipline`（语义锚点、不写 file:line、不引用会话临时文件）。每个事实只在此层有产权，其他层只引用。

---

## P1: run_test 路径单独适配了 cann-bench 的测试任务，违反「架构不应内部实现测试、应直接使用外部测试指令」的设计原则

### 事实

- **观测**：架构的 run_test（精度测试执行）路径在 commit `42ffca0`（"update run_tests for cann-bench task"）中被单独适配，新增了 cann-bench 任务目录结构的内部解析逻辑。具体表现为：
  - 新增 `try_load_cannbench_task()` 函数，硬编码 cann-bench 任务目录布局（`tasks/level*/<op_name>`），内部搜索并解析 cann-bench 的 task 定义来获取 test_cases、golden_contract、dtype_thresholds
  - `DebugService.run_cases()` 新增「priority path」分支：优先从 cann-bench task 目录加载用例，state.test_cases 降级为 fallback
  - 新增 `ASCENDC_TEST_CANN_BENCH` 环境变量查找逻辑，用于定位 cann-bench 仓根目录
  - 新增 `task_loader.py` 模块（298 行），专门解析 cann-bench task 的 proto/cases/golden 定义格式
  - `run_precision_cases()` 签名新增 `dtype_thresholds` 参数，用于传递 cann-bench task 定义的 per-dtype 精度阈值
  - `NPURunner.execute()`（587 行变更）内部直接构造并执行 cann-bench 风格的测试 harness 脚本

- **根因**：架构没有把「测试执行」定义为「调用外部测试命令 + 解析结果」的通用契约，而是在框架内部实现了 cann-bench 特定的测试用例加载和测试执行逻辑。当外部测试系统（cann-bench）的任务格式、目录布局、评测方式发生变化时，框架内部代码也必须跟随修改。

- **违反原则**：
  - **架构分层**（CLAUDE.md §1.1）：测试执行是外部系统的职责，不应内化到 L2（debug_service）/L3（precision_debug stage）/L6（NPURunner adapter）中。框架应定义「外部测试命令」的接口契约，由外部系统实现，框架仅负责调用和结果解析。
  - **单一职责**（CLAUDE.md §1.2）：`DebugService` 本应是「debug CLI 的 L2 delegate」，却承担了 cann-bench task 目录解析、用例加载、阈值提取等多重不属于 debug 服务层的职责。
  - **扩展性**（CLAUDE.md §1.2 可扩展尺子）：如果后续接入新的测试系统（如 ATK、TTK、自定义评测脚本），按当前模式会继续在框架内部追加新的 `try_load_xxx_task()` 分支，导致不断膨胀的 if-else 链。

- **证据**：
  - commit `42ffca0` 一次提交同时改了 `debug_service.py`（L2）、`precision_debug.py`（L3）、`runner.py`（L6）、新增 `task_loader.py`（L6）——跨四层改动都围绕「让框架认识 cann-bench task 格式」这一件事
  - `try_load_cannbench_task()` 的 docstring 明确写「Searches `<repo_root>/tasks/level*/<op_name>` for a cann-bench task directory」——这是 cann-bench 的内部目录约定，不应泄漏到框架代码中
  - `DebugService.run_cases()` 的 docstring 写「Priority path: when a cann-bench task directory exists for this operator, load case shapes / value ranges / per-dtype thresholds from it (same pattern as `kernel_eval.cli eval`)」——框架在模仿外部工具的内部行为模式，而非调用外部工具
  - `CannbenchEvalStage`（`cannbench_eval.py`）直接硬编码 `python -m kernel_eval.cli eval` 命令及 cann-bench 报告文件路径——同样是 cann-bench 内部实现细节泄漏到框架

- **影响范围**：所有当前和未来的测试执行路径——包括 precision_debug stage（in-stage 精度调试闭环）、debug CLI（`run-cases` 命令）、cann-bench 评测（`CannbenchEvalStage`）。当前只适配了 cann-bench 一种测试后端，但架构上未预留接入其他测试后端的通用机制。

### 关联

- 与 CLAUDE.md §1.1（7 层分层架构严格向下依赖）冲突：当前测试执行相关的 cann-bench 知识散布在 L2/L3/L6 三层
- 与 CLAUDE.md §1.2 可扩展性尺子冲突：新增测试系统需要修改框架内部代码
- 与 CLAUDE.md §1.5（算子知识不进 Python 代码）精神一致：cann-bench task 格式属于外部系统的知识，不应硬编码在框架中

---

## 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-14 | 初版：记录 P1（run_test 路径单独适配 cann-bench task，违反架构对外部测试指令的使用原则） |
