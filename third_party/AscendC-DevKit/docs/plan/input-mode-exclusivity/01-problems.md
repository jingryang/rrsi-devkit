# 输入模式互斥未加载期校验 + dd-intake 短路缺陷 — 问题记录（L1）

> 纯事实快照（哪里坏了 / 凭什么这么说）。不提方案、不排顺序、不写决策。
> 来源：`h00616010` 机一次 `ascendc-devkit run --workflow self_evolve_op` 的真实执行记录
> （run-id `20260716-165751-78dfe1`，已在本仓 `output/` 下只读分析，不在本仓复现执行）。
> 该 run 跑到 `docgen` 未能生成《详细设计说明书》，但 `report.md`/`report.json` 全部 stage 显示 `ok`。

## P1 — generation workflow + `--detailed-design`(reuse) 输入互斥，加载期无校验致模式混搭

**现象**：调用方对 `self_evolve_op` 同时提供了 cann-bench 需求（`requirement_path`）与一份
已存在的详设说明书（`detailed_design_path`，指向另一个 run `20260715-035019-b23030` 的 docgen 产物）。
工程未在加载期识别并拒绝这个组合，而是让流程跑完需求分析、概设生成、详设 intake 短路、validate、
anchor-consistency、integrate，最终在 `docgen` 因缺料失败，且失败被报告掩盖。

**证据**：
- `state_snapshot.json` 的 `task_request` 同时含 `requirement_path`（`cann-bench/tasks/level1/swi_glu/proto.yaml`）
  与 `detailed_design_path`（`.../20260715-035019-b23030/.../swi_glu_详细设计说明书.md`）；`resume_iteration=0`（非续跑，是启动参数带入）。
- `self_evolve_op` 根树（`_design_root`，`before_names=["entry","context","requirement"]`）无条件把
  `requirement` + general-design generation 挂在 detailed-design group 之前，与 `detailed_design_path` 无关。
- `detailed_design_path` 非空触发 `DetailedDesignIntakeStage.resolve_condition` 返回 `"short_circuit"`，
  transition 路由 `dd-intake → validate`（`route_type="validation"`），跳过 template-division / tiling / anchor-forkjoin。
- tiling ForkJoin `children=[]`（0 分支，`total_elapsed_ms=0`），因 `template_division=None`；
  `tiling_results` 全程为 `None`。
- `docgen/decision_log.json` 自报 `status=BLOCKED`（缺 `kernel_pseudo_code`/`precision_perf`）；
  `run.log` 记 `Stage 'docgen' failed with fail_strategy=halt`；但 `report.json` 中 `docgen` 为 `status=ok`、`errors=[]`。
- `state.node_status` 与报告不一致：`docgen=failed`、`detailed-design=failed`、`self_evolve_op=failed`（state 层诚实，聚合层失真）。
- 加载期 preflight（`_preflight_input_topology` 等）把 `detailed_design_path` 仅当作 codegen 的输入校验，
  未校验"含 generation 前置的 workflow 与 reuse 输入互斥"；`validate_chain` 是纯静态契约校验，
  看不到运行期 short_circuit 绕开 provides 节点。

**影响**：流程跑约 30 分钟、消耗大量 agent token 后才在 `docgen` 失败；失败被 `report` 显示为全绿；
真正的根因（两种互斥输入模式同时存在）未在加载期暴露，排查被下游表象（"tiling_results 缺失"）带偏。

## P2 — `dd-intake` 短路路径设计缺陷（follow-up，本次不解决）

**现象**：`DetailedDesignIntakeStage` 的 `short_circuit` 路径（`detailed_design_path` 非空时）存在多个
相互关联的设计缺陷，是 P1 现象的下游放大器。本次仅记录，不在当前步骤解决。

**证据**：
- short_circuit 的 `transition` 只回填 `design_spec`/`tiling_strategy`/`data_flow`/`design_doc`，
  **不回填 `template_division`/`tiling_results`/`anchor_report`**；而下游 `validate`/`docgen` 的
  `input_contract.requires` 含这些字段（generation 产物）。
- `dd-intake` 的 `input_contract` 声明 `requires=["general_design"]`，但 short_circuit 解析路径
  （`_upstream_inputs`/`_materialize_extra`/`transition`）实际不消费 `general_design`（声明与实际不符；
  该 requires 是为正常 generation 路径下 template-division 消费 general_design 而声明）。
- short_circuit transition 路由到 `validate`，而 `validate.requires` 含 `tiling_results`/`template_division`/
  `anchor_report`——"跳过 generation 却去校验 generation 产物"的语义矛盾。
- P1 落地（加载期拒绝"从零设计 + detailed_design_path"组合）后，`dd-intake` 的 short_circuit
  分支、`existing_detailed_design.md` 物化、`dd-intake→validate` 路由均退化为**休眠代码**
  （待 R1 复用 workflow 启用时配套修复，非当前须清理的死代码）。

**影响**：短期被 P1 的加载期拒绝兜住（不再被触发）。short_circuit 当前是**休眠代码而非死代码债**——
它有明确的未来承载点（R1 的复用 workflow），故保留无害、不违反 §2.5/§1.4。当 R1 落地、复用 workflow
启用 short_circuit 时，其回填缺口（`template_division`/`tiling_results`/`anchor_report`）须一并修复，
否则会再次引发同类缺料故障。

## R1 —「从已有详设生成算子」应新增专门复用 workflow（需求，YAGNI 待触发）

**需求**：当未来出现"从一份已有详设说明书直接生成算子代码"的真实需求时，应**新增一个专门复用
workflow**（不走 `requirement`/`general-design`，直接 `dd-intake` 解析详设 → codegen），而非在现有
generation workflow（generate_ascendc/dev/self_evolve_op）里支持 `--detailed-design`。

**理由**（为何独立 workflow，而非在 generation workflow 里支持）：
- generation（从零设计：requirement→general-design→detailed-design 生成）与 reuse（复用详设）是**互斥
  模式**——"先做本算子需求/概设、再接一份详设去生成代码"没有合理场景（见 P1 论证：详设是本算子的→
  重跑冗余且可能矛盾；是别算子的→纯语义错配）。二者须分属不同 workflow，职责单一（§1.2/§2.1）。
- `detailed_design_path` 的正确承载点是"纯复用 workflow"；当前无此 workflow，故 `--detailed-design`
  在所有 generation workflow 都是错配（P1 加载期拒绝即纠正此错配）。

**dd-intake short_circuit 修复时机**：随 R1 落地——届时 short_circuit 才有合法承载点，配套修复 P2
（回填 `tiling_results` 等，或 short_circuit 跳过 docgen 直达 codegen）。当前无复用 workflow，提前修
short_circuit 是为不存在的需求改代码（§2.7 YAGNI）。

**触发条件**：用户/场景明确提出"已有详设、想直接生成代码"时立项 R1；此前仅作记录。
