# L3 方案分析 — cann-bench 增量构建 mtime 陷阱（已拍板，冻结）

- 拍板时间：2026-08-28，用户拍板
- 输入：`01-problems.md`（L1 事实）

## 候选方案

### 选项 a — cann-bench 删增量、只走全量（✅ 拍板采纳）

删 `cann-bench.yaml` 的 `incremental_command_template` 字段，deploy 回落
`command_template`（`bash build.sh` 全量，既有通路，零新代码）。profile 体系
对可选增量字段的支持机制**保留**，真实算子仓将来即插即用。

- 优点：风险彻底消除（零知识依赖——不需要理解 cann-bench 构建内部结构）；
  与 origin-only 外部仓的保守消费原则一致；额外覆盖 diagnose 场景（其 redeploy
  走同一命令，同样暴露）；成本可忽略（+35 s/deploy，run 级 ~6 min）。
- 缺点：放弃省时收益（但实测收益仅 35 s/次，注释宣称的 2-3min 已过时）。

### 选项 b — 保留增量 + mtime 比对防御（否决）

增量前比对 `csrc` 源 mtime > build 内部标记 → 先删标记再增量。

- 否决理由：需 cann-bench 构建内部结构的确切知识（`copy_kernel_src.timestamp`
  的路径/语义在其源码中 grep 不可得），写死外部仓内部路径 = 脆弱耦合，
  cann-bench 升级即**静默失效**；且根因（用户无法修改 cann-bench）不可修，
  防御只能防已知形态。

### 选项 c — 按场景收紧（codegen 全量 / diagnose 增量）（否决）

- 否决理由：diagnose 同样暴露（改 kernel 源后 redeploy，本批正是靠 agent 自行
  干净重编绕过），收紧只护一半；两套策略的维护复杂度不值 35 s/次收益。

## 拍板结论（冻结）

1. **cann-bench 只走全量**：删 `incremental_command_template`；**通路机制保留**
   在 profile 体系，真实算子仓（ops-nn / ops-transformer 等）后续可启用——
   真实仓构建系统由产权团队维护，增量正确性有背书方。
2. **边界原则（后续启用增量的前提，冻结）**：某仓启用增量通路的条件 = 该仓
   构建系统的增量正确性由**仓产权方背书**（或经实测验证）；devkit 不为外部仓
   的构建正确性兜底——依赖的维护责任跟着仓产权走。
3. 实施注意（给 L4）：
   - 删字段时一并删过时的"省 2-3min"动机注释（§2.12 不留误导断言）；
   - UT 回归守护：cann-bench profile **不得**含 `incremental_command_template`
     （防将来误加回）；
   - 成本影响记录：+35 s/deploy（run 级 ~6 min），接受。

## 关联

- step-93（coder 归属判定/known_issues 交棒——本次识破陷阱的机制）、
  step-94（smoke 反馈通道——循环期间反馈失真的通路）、
  step-100（同批发现的 schema-retry 会话策略问题）。
