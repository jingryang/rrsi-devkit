# anchor 真值表漂移 + 迭代/loopback 可观测性 + read-only gate 正向修正 — 实施方案（第四层）

> 状态：动手前配方（待 L3 §9 待确认点拍板后执行）
> 日期：2026-07-04
> 层级：**第四层 / 实施方案**。改哪个符号、什么顺序、每步怎么验证（TDD：先红后绿）。
> 覆盖问题：P24 / P25 / P26。配套 L3：`17-anchor-truth-loopback-analysis.md`。
> 约定：按符号定位（不写 file:line）；外部依赖（CANN / chip spec JSON）只读。

---

## 0. 总览：改动清单 + 顺序 + 依赖

| # | 主题 | 覆盖 | 关键改动 | 依赖 |
|---|---|---|---|---|
| 1 | 建立 RunContext 统一运行环境上下文（三段）+ 序列化 round-trip | P27（+承载 P24） | frozen RunContext{hardware_target/hardware_env/software_env}；State 增 run_context；context 阶段一次填充（复用 CannAdapter+npu/detect+chip-spec loader）；自动物化 run_context 片段到 substage cwd（**不经 _upstream_inputs 声明**）；chip_version/npu_id 留 State 作 canonical（run_context 派生）；`from_snapshot` 重建 run_context | — |
| 2 | 删 anchor P6-a 内置真值表，改消费 `hw_params` | P24 | anchor-per-template / anchor-consistency SKILL：删硬件常量表，改「读注入的 hw_params」 | 1 |
| 3 | 降级其余硬件常量副本 | P24 | `platform_diff.md` 数值列改引用；`check_feasibility.py` 去 default、必由 `hw_params` | 1 |
| 4 | 统一可读 issue 渲染器 | P25 | 抽 `render_issue`；runner 迭代 reason 复用（带 detail）；loopback payload 携完整 detail | — |
| 5 | anchor 两 stage `max_iterations=1` | P26 | `AnchorPerTemplateStage` / `AnchorConsistencyStage` 声明 `default_max_iterations=1` | 1,2,3（闭环依赖单源去假阳性） |
| 6 | 集成验证 | 全部 | 非 heavy ST + heavy_llm e2e（用户确认后） | 1-5 |

顺序：1 是地基（无单源通路，2/3 无处消费）；4 与 1-3 可并行；5 必须在 1-3 之后（否则真问题 forward 也闭不上环）。全部 TDD：每步先写红测、再改、转绿。

---

## 1. 建立 RunContext 统一运行环境上下文（P27 地基，三段一次性全做）

### 现状（凭什么要新建）

run 不变的环境事实散落：`chip_version`/`npu_id` 是 State 字段；`hw_params` 不存在；detected_chip 在 `npu/detect.py` 不回存；`ASCEND_TOOLKIT_HOME`/CANN/版本散读 `os.environ` 于 `CannAdapter` + `verify_env` + `verify.preflight_diagnostic`。逐 stage `_upstream_inputs` 声明 = 传递丢失载体（忘声明则静默丢失）。

### TDD（先红）

1. **UT-1.1（hw_params 单源载入）**：`chip="ascend910b"` → `run_context.hardware_target.hw_params["ub_size_bytes"] == 196608`（与 chip spec `ascend_910b.json` 的 910B3 variant 一致）。先断言 → 红（run_context 不存在）。
2. **UT-1.2（三段填充）**：context 阶段后 `run_context` 三段结构齐备；`software_env.cann_toolkit_path` 与 `CannAdapter` 检测一致；`hardware_env.detected_chip` 与 `npu/detect.py` 一致（纯设计/cross-compile 场景 hardware_env/software_env 可 None）。先断言 → 红。
3. **UT-1.3（自动物化、不经声明）**：任一 design substage 跑后 cwd 含 `hw_params.json`，且**该 substage 的 `_upstream_inputs` 未声明 hw_params**——证明走自动物化、非逐 stage 声明（消除传递丢失）。先断言 → 红。
4. **UT-1.4（frozen + 随 State）**：RunContext frozen；`with_updates` 产新实例；不随 stage 改变（run 内不变式）。先断言 → 红。

### 改动点

- **新增 frozen dataclasses**（`domain/` 或 `orchestration/`）：`RunContext` + `HardwareTarget{chip, hw_params}` + `HardwareEnvironment{npu_id, detected_chip, driver_version?}` + `SoftwareEnvironment{cann_toolkit_path, cann_version?, compiler?, python_version, torch_npu_version?}`。可选段（`?`）允许 None，不强求真实硬件。
- **State**：增 `run_context: RunContext | None = None`；迁移 `chip_version` → `run_context.hardware_target.chip`、`npu_id` → `run_context.hardware_env.npu_id`（§1.4 不留兼容字段）。
- **chip-spec loader**（新增，~几十行）：`chip → ascend-hardware/references/chips/<file>.json` 映射表（与 ascend-hardware SKILL.md 文档表一致＝单源），读 `variants[型号]` 取扁平字段（`ub_size_bytes`/`l1_size_bytes`/`l2_size_bytes`/`vector_core_cnt`/…）产 `hw_params`。chip→file 映射是 infra 级查表、非算子知识（§1.5 不冲突）。
- **填充落点**：context 阶段（已解析 chip/npu_id），调用既有 `CannAdapter`（software_env）+ `npu/detect.py`（hardware_env.detected_chip）+ 新 loader（hardware_target.hw_params）收口——**只收口、不重做检测**。
- **自动物化**（消除传递丢失的关键）：`_materialize_inputs` 增「总是写 run_context 片段」——`hw_params.json`（首期）写进每个 design substage cwd，与 `_upstream_inputs` 声明解耦；新 stage 自动获得。skill 相对路径读（§2.1/2.3）。
- **reader 迁移：决定不做（避免过度设计）**：`chip_version`/`npu_id` 本就是 canonical、全局可达的 State 字段，从未有「传递丢失」问题（那是 hw_params，已由 run_context 单源解决）。把它们迁出 State 既无单源收益，又要补 run_context 序列化 + 单 stage CLI 两条风险路径。改为：chip_version/npu_id 留 State 作 canonical，run_context 是其**派生展开**（State 字段注释明示：chip 真值=chip_version；hw_params 真值=chip spec via run_context）。
- **run_context 序列化 round-trip（必要修复）**：`to_snapshot` 用 `asdict` 把 frozen RunContext 扁平成嵌套 dict，`from_snapshot` 若直接 `cls(**data)` 则 resume 后 `state.run_context` 是 dict、属性访问（`.hardware_target.hw_params`）炸。新增 `run_context_from_dict` + `from_snapshot` 重建（UT-1.5）。

### 验证

UT-1.1~1.5 转绿（含 round-trip UT-1.5）；run_context 经 `to_snapshot`/`from_snapshot` 重建为 RunContext（非 dict）；既有 deploy/compile/gates/resume 行为不回归（UT 1513 + 非 heavy ST）。

---

## 2. 删 anchor P6-a 内置真值表，改消费 `hw_params`（P24）

### TDD（先红）

4. **UT-2.1（契约）**：anchor-per-template / anchor-consistency 的 SKILL 输入契约（`ArtifactContract` / skill 输入说明）声明消费 `hw_params`，且 SKILL 正文**不再含**「UB 总大小 = 245760」「240KB」「不需查文档」等内置常量断言。先断言（grep SKILL 正文）→ 红。

> 说明：SKILL.md 是 prose，UT 用「契约字段 + 关键串反断言」守护（契约要求 hw_params；正文不得出现已删的硬常量串）。

### 改动点

- `ascendc-op-design-anchor-per-template/SKILL.md`：删除「硬件参数真值表（P6-a 锁定）」整段（含 UB 245760/240KB、L1、带宽、reg、对齐表）；删除「硬件参数（UB 240KB 等）已在本 skill 给出，不需查文档」「禁止以上游 self_check 为依据…必须自己对照内置真值表判定」。
- 改写为：**「硬件 ground truth 来自运行期注入的 `hw_params`（来自 ascend-hardware chip spec，唯一源）。对质 tiling 产物的硬件 claim 时，与 `hw_params` 比对；冲突即写 blocking_issues。独立性 = 我直接读权威源 `hw_params`，不复刻、不盲信产物的 self-citation。」** —— 保独立性、去副本。
- `ascendc-op-design-anchor-consistency/SKILL.md`：同步（一致性合并也以 `hw_params` 为唯一硬件参照）。
- 工具约束段保留（禁 Glob、Grep 靶向 API 查证）。

### 验证

UT-2.1 转绿；手检两 SKILL 全文无残留硬常量。

---

## 3. 降级其余硬件常量副本（P24）

### TDD（先红）

5. **UT-3.1（脚本不硬编码）**：`check_feasibility.py` 无 `196608`/`192KB` 字面 default；`ub_size` 必由传入的 `hw_params` 取得，缺则报错（§3.7 诚实报错，不静默打桩）。先断言 → 红。
6. **UT-3.2（platform_diff 去数值）**：`platform_diff.md` 的「核心参数对比」表 UB 行不再含 `~192KB`/`~248KB` 数值，改为「见 ascend-hardware chip spec」。先断言 → 红。

### 改动点

- `ascendc-profiling-analysis/scripts/check_feasibility.py`：删 `ub_size_bytes: 196608` 等字面 default；函数签名要求 `hw_params`，`ub_size = hw_params["ub_size_bytes"]`；缺则 `raise` 明确错误。
- `platform_diff.md`：「核心参数对比」表的 UB 数值列删除/改引用；保留定性架构差异（Membase/Regbase、同步、Cast 时机等——这些是 platform_diff 的正当职责）。
- `general_design_common_knowledge.md`：删除自相矛盾的 UB 数值行（「256KB 物理/~192KB 可用」「248KB」），改引用 chip spec。
- pattern md 里的「UB 容量（~192KB）」属**定性约束提示**（非精确常量），可保留为「受 UB 容量约束（具体见 hw_params）」—— 不逐处删，但去掉会被当作 ground truth 的精确数。

### 验证

UT-3.1/3.2 转绿；`grep -rn "245760\|196608"` 在 design/anchor 相关 skill 与脚本中归零（仅 chip spec 与知识库原文保留）。

---

## 4. 统一可读 issue 渲染器（P25）

### 现状

`graph_executor._summarize_issue` 已是确定性 field-select 渲染（`[code→target/template] detail`），但（a）只在 routing transition 触发、不在 stage 内迭代行触发；（b）detail 截断 80 字符过短。runner 的 `_iteration_reason` quality 分支只赋固定串「quality check not satisfied」。

### TDD（先红）

7. **UT-4.1（迭代行带 detail）**：构造 stub stage，`is_satisfied→False`、`blocking_issues=[{code:"AC2",target:"tiling",target_template:"T1",detail:"<长 detail>"}]`；跑 runner，断言产出的迭代 reason 含 `AC2`、`tiling`、`T1` 与 detail 前 N 字符——**不再是裸「quality check not satisfied」**。先断言 → 红。
8. **UT-4.2（loopback 完整）**：`AnchorConsistencyStage.loopback_feedback(state)` 返回的 payload 含完整 `blocking_issues`（code/target/target_template/detail 原文不截断）。先断言 → 红。
9. **UT-4.3（渲染确定性）**：同一 issue dict 多次渲染结果一致（非 LLM 压缩）。先断言 → 绿（复用既有机制）。

### 改动点

- 抽公共渲染器 `render_issue(issue, detail_limit=None)`：`detail_limit=None` 时不截断（loopback 用）、给正整数时截断（日志行用）。落点：与现有 `_summarize_issue` 同模块，复用并替换之。
- runner 构造迭代 reason 处：`quality_ok=False` 分支改为调 `render_issue` 渲染 stage 的 `blocking_issues(state)`（带 detail_limit，如 240 字符/issue；多 issue 取前 N + 总数），拼进 reason。
- gate 的 `loopback_feedback`：确保返回完整 issue 结构（不截断）；下游 tiling prompt 注入处用 `render_issue(detail_limit=None)` 渲染——保证 LLM 拿到可直读、可行动的上下文。

### 验证

UT-4.1/4.2 转绿（4.3 维持绿）；人工读迭代日志行能直接看出「哪类问题、指向哪个模板、具体冲突」。

---

## 5. anchor 两 stage `max_iterations=1`（P26）

### 现状

`AnchorPerTemplateStage` / `AnchorConsistencyStage` 未覆写 `default_max_iterations`，继承 `base` 的 3；`anchor-consistency → tiling corrective` 边已存在且模板精确（design_tree transition_table + selector）。

### TDD（先红）

10. **UT-5.1（ceiling=1）**：`AnchorPerTemplateStage().effective_max_iterations == 1` 且 `AnchorConsistencyStage().effective_max_iterations == 1`。先断言 → 红。
11. **UT-5.2（首轮即路由）**：构造 anchor-consistency 首轮产出含 `blocking_issues=[{target:"tiling",target_template:"T1"}]`、`is_satisfied=False`；跑 graph_executor，断言**只跑 1 轮**即按 `infeasible → tiling corrective` 路由（不二次 spawn anchor）；selector 圈定仅 T1（模板精确）。先断言 → 红。
12. **UT-5.3（无自迭代空转）**：同输入下，anchor-consistency 的 spawn 次数 == 1（不再 == 3）。先断言 → 红。

### 改动点

- `AnchorPerTemplateStage`：增 `default_max_iterations = 1`（结构只读、无自修复——L3 §5 不变式 II）。
- `AnchorConsistencyStage`：增 `default_max_iterations = 1`。
- 不动 transition_table / selector（边已正确）；UT-5.2 验证「首轮即 forward」自然成立（自迭代不再前置抢占路由）。
- 通用化判据（self_repairable 声明）**不在本步做**（L3 §9.4，最小正确改动；先硬改 anchor 两 stage）。

### 验证

UT-5.1/5.2/5.3 转绿；既有 anchor→tiling 模板精确路由 UT（step-13 落地）维持绿（不回归）。

---

## 6. 集成验证（ST / heavy_llm）

- **非 heavy ST**：design 路由相关 ST（anchor→tiling corrective、模板精确 rerun）维持绿；新增「anchor max_iter=1 + 首轮路由」ST（不 mock 路由层，可 stub agent）。
- **heavy_llm e2e（§3.11，需用户确认后跑）**：重跑 cann-bench profile exp 算子，断言：
  - anchor 两 stage 各只 1 轮（日志 spawn 次数 == 1）；
  - 无 AC2 假阳性（UB 单源后 anchor 与产物读同一 `hw_params`）；
  - 若有真 issue，forward-route 到 tiling 且带可读 detail；
  - 不再撞 3600s 超时、走到 integrate 之后。
  - 预估耗时：分钟级～十分钟级（单算子 e2e）；成本量级：中等。**未跑须诚实记录**（§3.11）。

---

## 7. 回归与不破坏的契约

- **skill 即插即用（§2.1）**：anchor SKILL 删 P6-a 后，从本仓取出须仍可在 TUI 直跑——因 `hw_params` 在 self-evolve 外的场景由 `ascend-hardware` skill 提供，SKILL 须注明「需先经 ascend-hardware 取 hw_params」（文件接力，§2.3），不依赖工程注入。
- **文件 I/O 契约（§2.3）**：`hw_params` 物化为 `hw_params.json` 到 skill cwd，skill 相对路径读。
- **不向后兼容（§1.4）**：删 P6-a、去 default、改 max_iter 直接改干净，不留旧字段/迁移分支。
- **可诊断（§1.2）**：P25 保证每次迭代/路由留可读信号；P26 保证真问题不被 override 静默。
- **回归基线**：UT 全量 + 非 heavy ST 全绿（LLM/NPU/CANN 真实环境，不跳过，§3.2/3.6）；heavy_llm e2e 按 §6 用户确认后跑。

---

## 8. 实施顺序小结（TDD 红→绿 流）

```
1 (hw_params 通路: UT-1.1/1.2/1.3 红→绿)
 └─2 (删 P6-a: UT-2.1 红→绿)
 └─3 (降级副本: UT-3.1/3.2 红→绿)
4 (渲染器: UT-4.1/4.2 红→绿)         ← 与 1-3 并行
 └─5 (max_iter=1: UT-5.1/5.2/5.3 红→绿)   ← 依赖 1-3（闭环）
    └─6 (ST + heavy_llm e2e)
```

每步独立可验证、可回滚；1-3 是 P24 单源、4 是 P25 可读、5 是 P26 闭环；6 证三者合起来收敛。
