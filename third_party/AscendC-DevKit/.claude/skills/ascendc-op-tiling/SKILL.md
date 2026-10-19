---
name: ascendc-op-tiling
description: 对单个算子计算模板完成完整 Tiling 推导（split → vf-design → buffer-kernel → precision-perf），在单一会话内串行 tail-call 四个子 skill，产出四份 schema 文件
triggers:
  - tiling
  - tiling 推导
  - 单模板 tiling
---

# AscendC 单模板完整 Tiling 推导（编排门面）

## 职责

对**单个模板**完成从切分到精度/性能的完整 tiling 推导。本 skill 是编排门面：**不重复四个子
skill 的方法论**，只负责**串行调度**它们并在单一会话内维持上下文（跨段不一致构造性消解——同一
个 agent 一个上下文里写完整 tiling，不可能自相矛盾）。

四个子 skill（按序 tail-call）：

1. `ascendc-op-tiling-split` —— 核间/核内切分（ubFactor 推导）
2. `ascendc-op-tiling-vf-design` —— A5 Regbase VF 编排（**仅 A5**；A2/A3 跳过）
3. `ascendc-op-tiling-buffer-kernel` —— Buffer 设计 + Kernel 伪代码
4. `ascendc-op-tiling-precision-perf` —— 精度 + 性能

**类目特定知识**：当本模板属某已知类目（规约 / 排序 / 逐元素 / 广播 / 布局转换，按**结构判据**判定，
不认算子名）时，四个子 skill 应查共享类目参考
`ascendc-op-design-shared/references/tiling-patterns/index.md`，按其中的路由取该类目的场景分支树、
UB 预算公式与算法选型；它是知识库，不替代 split/buffer-kernel 的方法主线，只补类目套路。
（MatMul / FlashAttention 等不在该库，走各自专项设计流。）

## 流水线位置

```
template-division → 【本 skill（每模板）】→ integrate
```

## 输入（从当前工作目录读文件）

- `general_design.json`：概设产物（轴优先级、循环框架、Buffer 可行性约束）。
- `template_division.json`：模板划分（锁定决策）。
- `tiling_current_template.json`：本模板已完成段（增量场景；首轮为空或缺失）。
- 硬件参数：工作目录 `hw_params.json`（编排从 ascend-hardware 单一来源载入）。
- 当前模板已在 prompt 提供（「## 当前模板」段）。

> 不读其它模板的中间文件。

## 输出（用 Bash（`cat`）写到当前工作目录）

| 产物 | 必需 | 说明 |
|---|---|---|
| `tiling_split.json` | 是 | split 段（`split` 键） |
| `tiling_vf_design.json` | 仅 A5 | vf_design 段（`vf_design` 键）；A2/A3 不产出 |
| `tiling_buffer_kernel.json` | 是 | buffer_kernel 段（`buffer_kernel` 键） |
| `tiling_precision_perf.json` | 是 | precision_perf 段（`precision_perf` 键） |

> 每份产物的 schema 由对应子 skill 目录下的 `schema/*.json` 约束（DevKit 适配层逐份校验）。
> 产出不符合 schema → 适配层拒绝，重试。

## 执行步骤

### 0. 判定 A5 是否需跑 vf-design

从 prompt「## 算子」段读目标芯片（或 `hw_params.json` 的 chip 字段）。**编程模型为 Regbase
（A5）→ 跑 vf-design；Membase（A2/A3）→ 跳过 vf-design**（无 VF 概念，buffer-kernel 维持 A3
Vector 伪代码、无 VF_CALL）。

### 0.5 SIMT 模板先查 SIMT 模式库（A5 + 结构命中时）

当本模板属 SIMT 场景（概设/模板划分锁定决策已判 LP2 索引间接 / LP7 选择排序 / 条件分支密集，
或 buffer-kernel 将走 SIMT 线程化路径）时，进入四段推导前先读 `ascendc-simt-operator-design-patterns`
skill：分核/线程映射/workspace 契约约束 split，VF(thread) 编程/索引寻址/数据搬运/同步原子/写冲突
确定性谱系约束 buffer-kernel，精度与性能约束 precision-perf——`ascendc-op-tiling-vf-design` 明确不
覆盖 SIMT 场景，其 VF 编排空白由该模式库补位。非 SIMT 模板跳过本步。

**SIMT host 契约（读该 skill 时必取）**：SIMT 模板的 host tiling 必须声明 Dynamic Unified Buffer
= RTS SIMT 共享内存窗口——`context->SetDynUBufSize(usableUb)`（API 默认 0 = 不声明，不声明则共享
buffer / DCache 越界；`SetLocalMemorySize` 为同函数废弃名，主线仓 arch35 仍大量用旧名，语义一致，
生成代码用 `SetDynUBufSize`）；`usableUb = 平台 UB − DCache（32K/58K/128K 按算子选）− 静态预留`，
host 私有化决策与 device TPipe 分配必须用同一个数（见该 skill `references/workspace-contract.md` §3）。
本步 split 的 ubFactor / buffer-kernel 的 UB 预算须以该声明值为上限推导。

### 0.6 执行纪律（防过度求索——每一段都适用）

四段推导中，多数 token 消耗来自**数值参数反复自我重推**与**契约措辞自我确认**。遵守以下纪律：

1. **契约速答（C1）**：四段产物的机器契约是固定的——顶层只允许
   `template/<段>/step/status/decisions/external_verification/self_check_summary`（自检在顶层，
   `self_check_summary` 顶层是允许的）；`verifiable_claims` / `key_parameters` 一律放**段对象内层**
   （split/vf_design/buffer_kernel/precision_perf 各自内层）；`verifiable_claims` 字段定义与
   verification 等级见 `ascendc-op-design-shared/references/checkpoint_convention.md` §105-123
   （方案 S + schema 闭合）。**写产物前不需要再翻 schema 反复确认**——按本段直接写，校验交给
   DevKit 适配层。
2. **数值推导收敛（C2）**：
   - 先查同族已验真值表 / 公式（`evolution-knowledge`、`ascendc-op-design-shared/references/`、
     `ascendc-api-best-practices`）再推，禁止无参照地从零反复重推。
   - 核间负载均衡直接用 `load-balance-formula.md` 闭式（见 split skill R3），**禁止凭估 + 多轮
     脚本反推**。
   - 每个数值决策点**最多 1 轮脚本验算即收敛**；结果与公式矛盾时，先核对口径（unit vs 元素、
     尾 unit 不齐、是否按元素算），**不得推翻公式立即重推**。同一参数同一推导禁止超过两轮。
3. **API 特殊值/精度语义**：elementwise Max/Min/Exp/Cast 等特殊值语义在选 API 当下按
   `knowledge_policy.md` 的"特殊值语义对齐门"处理（先查语义对照表，default 用 Compare/Select 复合，
   不依赖未文档化语义）。
4. **芯片命名**：代际/产品名映射（950PR/950DT/950 = Atlas 350 加速卡 = A5；910D 目录即该系）
   已在 `ascend-hardware/SKILL.md` 定义，不要在推理中反复猜测（见 CLAUDE.md §1.9）。要查芯片
   事实走 Tier 1 `ascend-hardware`。

### 1. 串行 tail-call 四个子 skill

对每个子 skill：用 Skill 工具调用 `/ascendc-op-tiling-<段名>`，读该子 skill 的 SKILL.md 方法体并
按它执行。**每完成一段，把该段结果合并进 `tiling_current_template.json` 供下一段读**（接力，§2.3）：

- split 完成后 → `tiling_current_template.json = {"split": <tiling_split.json 的 split 键>}`
- vf-design 完成后（仅 A5）→ 追加 `"vf_design": <tiling_vf_design.json 的 vf_design 键>`
- buffer-kernel 完成后 → 追加 `"buffer_kernel": <tiling_buffer_kernel.json 的 buffer_kernel 键>`
- precision-perf 完成后 → 追加 `"precision_perf": <tiling_precision_perf.json 的 precision_perf 键>`

接力文件 `tiling_current_template.json` 供子 skill 读上游段结论（切分方案/ubFactor/VF 编排既定
前提），不要求子 skill 重新推导上游。

### 2. 输出自检

- [ ] 四个（或 A2/A3 三个）子 skill 已按序执行完
- [ ] 每份 schema 文件的 required_keys 已满足（逐份 Read 确认）
- [ ] `tiling_current_template.json` 已含本模板全部已产段
- [ ] A2/A3 下未产出 `tiling_vf_design.json`（无 VF 概念）
- [ ] 跨段一致性已满足：buffer-kernel 的 Buffer 表与 split 的 ubFactor/循环结构一致；precision-perf 的 compute_dtype 与 buffer-kernel 的 Cast 时机一致（同一会话内就地修，不回炉）
- 自检失败 → 就地修正直到通过

## 约束

- 只推导当前模板，不修改其他模板文件。
- 四个子 skill 的方法论在其各自 SKILL.md，本 skill 只调度、不复述。
- 推导中遇到需要用户决策的点，直接 AskUserQuestion。
