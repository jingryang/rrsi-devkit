# L1 问题记录 — diagnose 阶段设计上下文缺失与结构降级修复无守护

> 记录客观事实（哪里坏了、凭什么这么说）。不提方案、不排顺序、不写决策。
> 方案见 `02-analysis.md`（L3），实施见 `03-impl-design-context.md`（L4）。

## P1：diagnose 认知输入缺「设计」层，对算子的全局理解仅限代码本身

diagnose 是 precision_debug 闭环的定位+自实施 phase，其「全局理解」输入只有 kernel 源码 + golden + 失败证据，设计产物（design_spec / tiling_strategy / kernel_architecture）在 skill、框架 prompt、物理布局三个层面均不可达：

- **skill 层**：`.claude/skills/ascendc-precision-diagnose/SKILL.md` 第 0 步「先全局理解（动手前必做）」定义为「读完整 kernel 源码 + golden + 失败证据」；全文（输入表 / 定位方法 / 参考文件索引）零处提及设计产物。
- **框架层**：`orchestration/stages/precision_debug_substages.py` 的 `DiagnoseSubstage._phase_prompt`（:2270）注入参数为 control_path / phase_json_path / operator_dir / skill_dir / op_name / build_command / test_command——无任何设计产物路径；整个 2500+ 行文件零处引用 `design_spec` / `tiling_strategy` / `kernel_architecture`。
- **物理层**：设计产物物化在 `{workspace.artifacts}/staging/`（`codegen.py:697 _materialize_inputs`，即 codegen 的输入），diagnose agent 的 cwd 是算子仓 op_dir——两处隔整棵目录树，prompt 中唯一 workspace 侧路径是 control_path，无引导则 agent 不可知设计产物存在。
- **框架有条件而未注入**：State 全程持有 `design_spec / tiling_strategy / kernel_architecture` 字段（`orchestration/kernel/state.py:175-177`）。
- **对照事实**：A5 侧 precision_debug 管线已向 agent 提供 staging 设计产物目录（`precision_debug_a5.py:62-66 _a5_codegen_dir` → `_common_context._get_record_dir`）；缺口仅存在于 A3 diagnose 循环。

后果（机制性）：代码是 codegen 参考设计实现的投影，存在实现与设计偏差的可能；diagnose 只看代码时会把实现现状当作「算子本来的样子」，「实现 vs 设计偏差」这一假设方向在其假设空间中不存在。skill 允许全局症状时「可重写整段」，重写时无设计参照的偏离风险最大。

## P2：无结构守护——「干净的语义降级修复」能过精度但性能下降，闭环内不被拦

闭环内唯一验证是 run-cases 精度；性能分要到批跑末端 cannbench_eval 才出，此时 debug commit 已固化进算子仓。现有纪律只防裸注释探针（`comment-bisect.md`「commit 前删所有注释实验痕迹——commit 只含逻辑修复」），防不住带 predict、能过验证的语义性降级修复。实证：

- **实证 1**（批 `20260823-125944-7d3451`，算子 unique，commit `7839265`）：`ShiftF32` 尾部填充将向量化 `Duplicate` 改为标量 for 循环 `SetValue`；agent 自述 "scalar fill is cheap"——无性能测量、无设计参照的猜测，且该段位于 bitonic exchange 调用路径。
- **实证 2**（批 `20260818-152906-dde0d9`，算子 adaptive_avg_pool3d，commit `2f95939c`）：fp32 输出段 `DataCopy→Adds(+0)`——用向量单元「加零」替代搬运，绕开跨流水线同步问题，占用向量计算资源。

## P3：结构偏离不可归因

`fix_code_log`（`schema/precision_diagnose.json`）无「结构偏离设计」标记字段；cannbench_eval 性能分下降后，需人工翻算子仓 git log 逐 commit 比对才能定位是哪个 debug commit 牺牲了性能结构。

## 关联

- CLAUDE.md §1.13 已确立 golden 为数值唯一权威；结构维度（tiling 切分 / 流水编排 / 搬运路径 / 精度策略）的对应权威源（设计产物）当前未进入 diagnose 消费链路。
- 记忆 `precision-upstream-halt-eval-loss-v020`：upstream halt 曾致整 run 0 评分——本问题修复不得新增 halt 触发面。
