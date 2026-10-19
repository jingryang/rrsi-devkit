# integrate transition 误把逐元素算子 wire tensor 当 scalar 搬空 inputs/outputs — 问题记录（L1）

> 纯事实快照（哪里坏了 / 凭什么这么说）。不提方案、不排顺序、不写决策。
> 来源：批跑 run `20260805-152456-8b48b2` 下算子 `Maximum`（工作区
> `output/20260805-152456-8b48b2/20260805-152456-a78810/`）的运行产物 + 框架源码。
> RCA 详见会话分析；本文只固化客观事实。

## 背景：halt 发生在哪

整条 design 流水线（requirement → general-design → detailed-design 全段 → docgen → validate）
全部 `ok`，halt 发生在 `codegen` stage **派发 agent 之前**的前置校验期：
`stage_aborted, elapsed_ms=2, error_type=PreconditionError`（`events.jsonl:193`）。
`codegen` `iterations=0` —— 根本没起 agent。整条 run 以
`Halting workflow — a required upstream artifact is missing` 收尾，`repo_rollback` 回滚算子目录。

---

## P1 — `_is_scalar_param` 用 `shape == []` 判标量，误杀逐元素/广播算子的 wire tensor（致死主因）

**现象**：到达 codegen 的 `design_spec.json` 里 `inputs=[]`、`outputs=[]`，tensor `x1/x2/y`
被全部错位塞进 `attrs`（attr schema：`{name, type, default}`）；codegen 前置校验拒
`inputs/outputs` 空，abort。

**证据**：

- `run.log:2477-2479`：
  ```
  [ERROR] Stage 'codegen' aborted: input validation failed:
    - design_spec.inputs is empty or missing
    - design_spec.outputs is empty or missing
  ```
- 抛错点：`src/ascendc_devkit/orchestration/stages/codegen.py:189-195` `validate_inputs`
  （`inputs = ds.get("inputs", [])` / `if not inputs: errors.append(...)` → 非空 reason
  → runner 抛 `PreconditionError`）。
- design_spec 跨 stage 退化轨迹（`artifacts/design/<stage>/design_spec.json` 实测）：

  | stage 归档 | inputs | outputs | attrs | tensor schema |
  |---|---|---|---|---|
  | `requirement/requirement.json`（源头） | x1,x2 | y | [] | — |
  | `integrate/design_spec.json`（agent 原始产出） | x1,x2 | y | [] | dtype/shape/format/param_type |
  | `docgen/design_spec.json`（下游消费） | **[]** | **[]** | **x1,x2,y** | **type/default**（attr schema） |
  | `validate/design_spec.json`（下游消费） | **[]** | **[]** | **x1,x2,y** | **type/default** |

- `integrate` 正确版里 `x1/x2/y` 的 `shape` 全为 `[]`、`format="ND"`、`role=None`、
  `dtype=["bfloat16","float16","float32","int8","int32","int64"]`（6 元素列表）——
  逐元素广播算子合法地把 shape 写 `[]` 表"任意秩/广播"语义的 wire tensor。

**误判机制**：

- 判据 `src/ascendc_devkit/orchestration/stages/design_substages.py:1946-1961` `_is_scalar_param`：
  ```python
  shape = item.get("shape")
  fmt = (item.get("format") or "").upper()
  return shape == [] or fmt == "SCALAR"
  ```
  `shape == []` → 判 scalar。Maximum 的 x1/x2/y（shape=[]）全员命中。
- 搬运 `design_substages.py:1964-2006` `_route_scalar_params`，把判定为 scalar 的项转成
  attr schema 搬进 `attrs`（`:1992-1994`）：
  ```python
  attr = {"name": name,
          "type": e.get("type") or e.get("dtype", ""),   # x1 无 type → 取 dtype 列表
          "default": e.get("default")}
  ```
  x1 无 `type` 字段 → `type` 取自 `dtype` → 错位版 `attrs[].type=["bfloat16",...]`，与实测逐字节吻合。
- 调用点 `design_substages.py:1840-1848`：`IntegrateStage.transition`（`:1820`）读 agent 产出后
  原地调 `_route_scalar_params(ds)`，把 route 后的 design_spec 喂给下游。

**影响**：任何 design agent 把 tensor `shape` 写成 `[]` 的逐元素/广播算子（Maximum/Add/Mul/Min/…）
都会被清空 inputs/outputs，codegen 必 abort。与具体算子无关（§1.12 通用缺陷）。

**根因深化（重复实现 + 进化不同步 — 系统性病根）**：`_is_scalar_param`
（`design_substages.py:1946`）是权威标量路由器 `OperatorSpec._route`（`domain/operator.py:219`）
的一个**重复实现**，且停留在 `_route` 已废弃的旧判据上：

- 权威 `_route` 判 shape 用**键存在性** `has_shape = "shape" in e`（:268），并对 `dtype` 要求
  **单标量字符串**才认 scalar-ish（:274-276，`isinstance(dtype, str) and dtype.lower() in _SCALAR_TYPES`）。
  Maximum 的 `shape=[]`（键在）→ 张量、`dtype` 是列表 → 张量，**正确**。
- 重复 `_is_scalar_param` 用**值空性** `shape == []`（:1959）→ Maximum `shape=[]` → 标量，**错杀**。
- `design_substages.py:1938-1944` 注释嘴硬称 `_route_scalar_params` "judge by BUSINESS SEMANTICS"，
  实际用 `shape==[]` 机制特征，**名实不符**，bug 因此潜伏到 Maximum 才暴露。
- `_route` 与 `_is_scalar_param` 判据**进化不同步**是更深的病根：权威路由器早已为同类 case
  （shapeless-but-real tensor）修对判据，重复实现未跟上。这是 §2.5（同一职责单一通路）违反的
  典型后果——任一"权威逻辑的重复实现"都会随权威进化而漂移成 bug。

---

## P2 — 归档存 route 前版本，掩盖 transition 改写（致诊断误导）

**现象**：`artifacts/design/integrate/design_spec.json` 是**正确版**（inputs=[x1,x2]），
而下游 `docgen/validate` 归档是**错位版**（inputs=[]）。表面看像"integrate 产出正确、下游搞坏"，
实际是 integrate 自己的 transition 改坏。

**证据**：

- `integrate` 归档 design_spec = 59 lines / 2779 bytes，inputs=[x1,x2]（dtype schema）。
- `docgen/validate` 归档 design_spec = 94 lines / 2923 bytes，inputs=[] / attrs=[x1,x2,y]（type schema）。
  `docgen` 与 `validate` 归档**逐字节完全相同**（`diff` 无输出）。
- 全量扫描 `agents/*.jsonl`：**没有任何 agent 用 write/edit/bash 写过这份错位 design_spec**。
- `agents/ascendc-design-generator-06.jsonl`（docgen round2）启动后**首次 read（turn 1）**
  读到的 `design_spec.json` 已是错位版（`inputs_empty=True / has_type=True / has_dtype=False`）。
  即错位在 docgen agent 运行前已由 transition 写定。

**机制**：`IntegrateStage.transition`（:1820）流程为 `_read_disk_artifacts`（读 agent 原始产出，
正确版）→ `_route_scalar_params(ds)`（原地改写成错位版）→ 写入下游 state/staging。而
`artifacts/design/integrate/` 归档的是 **agent 原始产出（route 前）**，route 后版本不进归档。
归档快照 ≠ 下游消费版本，造成"上游正确"假象，把锅甩给下游。

**影响**：根因被归档掩盖，诊断者会先怀疑 docgen/validate agent 或"上游缺产物"，拉长定位路径。

---

## P3 — WARN 信号产生但无消费者，错误推到 codegen 才炸（§1.2 可诊断失守）

**现象**：`_route_scalar_params` 搬运时打了 WARN，准确描述了根因，但只 warn 不 halt，
后续 validate / codegen 均未消费该信号。

**证据**：

- `run.log:975` 与 `run.log:2145`（两轮 loopback 各一次）：
  ```
  [WARN] [integrate] routed 3 scalar param(s) from inputs/outputs into attrs
  (LLM mis-classified; deterministic normalize): ['inputs/x1', 'inputs/x2', 'outputs/y']
  ```
  信号源 `design_substages.py:1844-1848` `Logger.warn(...)`。
- 该 WARN 未进 `events.jsonl`（无 stage 级结构化记录），未被任何下游门复查。
- 错误最终在 `codegen.validate_inputs`（codegen.py:189）才以 `PreconditionError` 炸出，
  报"empty or missing"（指向"缺产物"），与"框架自己搬空"的真相不符。

**影响**：可观测信号存在却被静默放过，错误从可解释的 transition 行为被推到难定位的下游 codegen。

---

## P4 — validate（reviewer）跑 28 turns 未校验 design_spec schema 完整性（防线失守）

**现象**：`validate` stage 用 `ascendc-design-reviewer` agent（`reviewer-03`，28 turns + 1 次
corrective retry）处理的是错位版 design_spec，但放行了致命错位。

**证据**：

- `artifacts/design/validate/blocking_status.json`：`status=blocked`，唯一 blocking issue 为
  **GV9-b**（int8→int32 一步 Cast 在 A2 表6 不存在，`target=tiling`，design decision 层面）——
  与 inputs/outputs schema 错位**无关**。
- `validate` 归档 design_spec 与 `docgen` 归档逐字节相同 → reviewer **未改 design_spec.json**。
- design_spec 自带 `io_contract_alignment` 字段白纸黑字写
  `"所有 IO 均为 tensor，无标量误列 inputs/outputs"`（`integrate` 正确版即有此字段）——
  reviewer 读到了这句，却未用来反查"既然都是 tensor，为何 inputs/outputs 是空的"。
- `ValidateStage`（`design_substages.py:2366`，transition `:2403`）仅读 `blocking_status.json`
  （reviewer agent 产出），**框架侧无 design_spec.inputs/outputs 非空机械校验**。

**影响**：本可在 validate 抓住并回 integrate 修（有 loopback 反馈渠道）的问题，被放行到 codegen
以 halt 收场（halt 后无自动修复路径）。

---

## P5 — `_is_scalar_param` 第二调用点：docgen OpDef 渲染判定同源受污染

**现象**：`_is_scalar_param` 还被 OpDef 锚点校验用于判定 inputs 项应渲染成
`Attr("<name>")` 还是 `Input("<name>")`，同一判据 bug 会让 tensor 被期望渲染成 `Attr`。

**证据**：

- `design_substages.py:2216`（`_opdef_missing_canonical_anchors`，docgen/review OpDef 锚点校验）：
  ```python
  kind = "Attr" if _is_scalar_param(item) else "Input"
  if f'{kind}("{name}")' not in code:
      missing.append(f'{kind}("{name}")')
  ```
  Maximum 的 x1（shape=[]）会被判 scalar → 期望渲染 `Attr("x1")` 而非 `Input("x1")`，
  若 codegen 正确渲染 `Input("x1")` 反而被这条校验报"missing Attr("x1")"。
- 本 run 因 P1 已在 codegen 前置校验 halt，P5 未爆发；但同源判据不修，docgen/review 的
  OpDef 一致性校验对逐元素算子会持续误报。

**影响**：与 P1 同源，是 `_is_scalar_param` 判据缺陷的第二个出口；修判据可一并治好（§2.5 单一通路）。
