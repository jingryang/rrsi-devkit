# codegen skill 多维自检 — 实施（L4）

> 改哪 / 顺序 / 怎么验证。决策见 `02-analysis.md`，事实见 `01-problems.md`。
> 目标文件：`.claude/plugins/stage-codegen/skills/ascendc-op-dev-coding/SKILL.md`
> 纯 skill 内容改动（Step6 自检扩行），**不改 codegen.py**——自检维度是编码后 agent 自检的引导，无 Python 编排变化。
> 与上游复用 ①②③（同 skill）+ ④ A5 红线（同 Step6 表）同改，不冲突。

## 改动 1 — Step6 编码自检：新增维3/维4/维5 行（决策 1/2/3）

Step6 表新增（跨编程模型通用，非 A5 专属）：

| 检查项 | 方法 | 失败处理 |
|---|---|---|
| 【维3】禁硬编码硬件参数 | `op_host/*_tiling.cpp`、`op_kernel/*` 含裸 CORE_NUM/BLOCK_NUM/UB_SIZE/对齐常数（`=32`/`=262144`/`=14336` 等），过滤 sizeof/GetSizeByDataType/GetBlockNum/GetUBSize 等运行时查询 | warning，改运行时查询 GetBlockNum/GetUBSize 或 sizeof(T)/GetSizeByDataType(dtype)/TilingData 字段 |
| 【维4】AR-1 主循环禁 GetValue/SetValue 数据搬送 | 主循环内 GetValue/SetValue 做 GM↔scalar 搬送（过滤注释 + TilingData 元数据读取 + 纯索引计算） | warning，改 DataCopy 批量搬送 |
| 【维4】AR-2 嵌套循环 GM 单点访问 | 嵌套 for 内对 GM GetValue/SetValue 单点（非 LocalTensor 批量） | warning |
| 【维4】AR-3 非对齐用 DataCopyPad | tail/pad/copyLen%ALIGN≠0 场景用 DataCopyPad 而非单点 GetValue/SetValue | warning |
| 【维5】OpDef dtype ⊇ IO spec | `{op}_def.cpp` DataType::X 枚举 vs `design_spec` IO spec dtype 矩阵逐一比对 | 缺失 → status=fail「OpDef 缺 dtype：{X}，详设有定义」 |
| 【维5】Tiling dtype 分支 ⊆ OpDef | `{op}_tiling.cpp` DT_X 运行时分支 ∈ OpDef 枚举 | OpDef 缺 → status=fail「OpDef/Tiling dtype 不一致」 |
| 【维5】Plugin cast 兜底检测 | op_plugin 对非 OpDef dtype 做 cast（过滤注释，查实际 torch API） | warning，记回报 `plugin_cast_dtypes[]` |

> 维3 与 `.claude/rules/ascendc-dev.md`「No hardcoded hardware params」一致（01 P2）。
> 维5 权威源是 `design_spec` IO spec dtype 矩阵（State 源字段，Event Sourcing ground truth，同 ② 字段↔源纪律）——不引用 high_risk_api_registry（DevKit 无，决策 1/3）。
> 维4 不引用 buffer_pipeline_redline E1/E2/E3（DevKit 无，决策 3）——直接内联 AR-1/2/3 判定。

## 顺序

1. TDD 先写测试（见下）。
2. SKILL.md 统一改（④+⑤ 一次改完）：④ 改动（Step3/Step4/Step6 A5 行）+ 本工作维3/维4/维5 行（同 Step6 表追加）。
3. 跑测试至绿。

## 验证（TDD）

`tests/ut/orchestration/test_codegen_selfcheck_dims.py`（参考 `TestSkillDocSourceContract` grep 断言写法）：
- `test_step6_has_dim3_no_hardcoded_hw`：SKILL.md 含「维3」+ `禁硬编码` + `GetBlockNum`/`GetUBSize` + `sizeof`/`GetSizeByDataType`。
- `test_step6_has_dim4_buffer_pipeline`：含「维4」+ AR-1（`主循环` + `GetValue`/`SetValue`）+ AR-2（`嵌套`）+ AR-3（`DataCopyPad`）。
- `test_step6_has_dim5_dtype_consistency`：含「维5」+ `OpDef` + `dtype` + `IO spec` + `Plugin cast`（或 `cast`）。
- `test_no_external_registry_dependency`：SKILL.md 不含 `buffer_pipeline_redline`、`high_risk_api_registry`、`E1`/`E2`/`E3` 标签引用、`C1-C4`（决策 1/3：不补 registry、不照搬标签）。
- 既有 codegen 用例不回归。
全量：`pytest tests/ut -m "not heavy_llm"`，0 回归。

## 后续（不在本轮）

- heavy_llm E2E（§3.11 跑前用户确认）：真跑 codegen 确认维3（无裸常数）/维4（无主循环单点搬送）/维5（dtype 枚举一致）自检能 catch 典型违例。
