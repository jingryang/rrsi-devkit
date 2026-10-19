# codegen.py 单类职责过载（God module 趋势）— L1 问题记录

> 层级：**L1 / 问题记录**。只陈述客观事实（哪里坏了、凭什么这么说）。不提方案、不排顺序、不写决策。
> 来源：2026-09-08 未推区间 review（`reviews/unpushed-v020-2e83c62d-review.md` m1）在 D8 软件架构维度标记。

## P1：CodegenStage 单类聚合多职责，持续膨胀为 God module

### 现象（事实）

- `src/ascendc_devkit/orchestration/stages/codegen.py` 现 **4299 行**，`CodegenStage` 单类承载：
  - **transition/契约门**：`_transition_membase` / section 校验 / manifest 契约 / OpDef 输出、
    OpDef 输出 OPTIONAL、标量点契约、AICore 注册名校验、plugin schema / host offload 门；
  - **定向 retry 与反馈**：`_plugin_schema_retry` / `_artifact_retry` / `_collect_*_feedback`
    / `_render_build_feedback_section`（fresh prompt 与 resume 共用渲染）；
  - **agent 投递与 prompt 组装**：`_build_coder_prompt` 段 / staging / `_plugin_sources`；
  - **部署编排**：直接调 `Deployer().compile` / `install_and_smoke` / `_persist_sources`。
- 类自身无单一职责；`>400 行` 阈值（checklist D8「上帝对象」机械信号）远超。
- **本批（4 commit）再增 +218 行**（注册名校验 172 行 + 新反馈段），趋势持续。

### 影响（可观测后果）

- 可维护性：改一处契约门要在一 4.3K 行文件里定位/保证不牵连其余职责；
- 可测试性：UT 需 mock 的 Deployer/workspace/完整 State 字段组合随文件膨胀变多；
- review/回炉成本：每批 codegen 改动 diff 大、review 负担线性上升（本批即如此）。

### 判定边界（诚实）

- 非本次两方案引入的新问题（两方案遵循既有归属惯例：知识单点外置 `domain/op_name.py`
  从职责上是**正确方向**）；这是历史累积 + 本批放大的**结构债**，修法（拆分模块）动线大、
  风险随行为回归，须独立立项实施，不当场顺手拆。
- 拆分须保持 `CodegenStage` 公共 API（stage 注册 / transition 签名）不变（§1.1 编排层
  consumer 依赖），只内部按内聚切模块。

## 关联

- 本仓 `domain/` 已有若干单点模块（`chip.py` / `mdef_parse.py` / `op_name.py`）可作拆分落点先例。
- `docs/plan/codegen-build-ownership/`：本批 10ceabd5 已在 deploy 侧做 `compile/install_and_smoke`
  拆分（Deployer 层），codegen 侧主体未动。
- review 报告：`reviews/unpushed-v020-2e83c62d-review.md`。