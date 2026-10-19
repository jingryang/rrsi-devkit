# Checkpoint 约定（共享定义）

> 本文件定义 `ascendc-op-*` 系列 skill 间的**产物字段约定 + 查证/自检规则**（verifiable_claims / decisions / self_check_summary 等）。
>
> **范围说明**：manifest.json planner 拓扑是 v2 历史范式，DevKit 工程层走 stage contract（`STAGE_SKILL_MAP` + 各 stage input/output_contract + 各自 artifact.json），**不消费 manifest/planner 拓扑**（planner 已不存在，下游 skill 硬编码上游产物路径，不走 manifest 动态发现）。本文档保留的是跨 skill 的**字段定义与查证规则**（被 tiling 三段 schema / knowledge_policy / validate GV9 引用）；manifest.json 段已删。

---

## 目录结构

所有 checkpoint JSON 存放于 `{workdir}/checkpoints/` 目录下：

```
checkpoints/
├── req-analysis.json                      ← step=req-analysis
├── general-design.json                    ← step=general-design
├── template-division.json                 ← step=template-division
├── tiling-split-template_A.json           ← step=tiling-split, template=template_A
├── tiling-buffer-kernel-template_A.json   ← step=tiling-buffer-kernel, template=template_A
├── tiling-precision-perf-template_A.json  ← step=tiling-precision-perf, template=template_A
├── tiling-split-template_B.json           ← step=tiling-split, template=template_B
├── tiling-buffer-kernel-template_B.json   ← step=tiling-buffer-kernel, template=template_B
├── tiling-precision-perf-template_B.json  ← step=tiling-precision-perf, template=template_B
├── integrate.json                         ← step=integrate
├── docgen.json                            ← step=docgen
└── validate.json                          ← step=validate
```

---

## 单步 JSON 文件格式

每个步骤输出自己的 `{step_name}.json`，包含以下字段：

```json
{
  "step":         "<skill-name>",
  "templates":    ["<template_1>", "<template_2>"],   // template-division/tiling 专用；其他 skill 可省略
  "status":       "completed",

  "decisions": [
    {
      "id":           "<DR-XXX-001>",      // 全局唯一决策 ID
      "topic":        "<决策主题>",
      "question":     "<决策问题>",
      "answer":       "<最终选择>",
      "alternatives": ["<被否方案A>", "<被否方案B>"],
      "rationale":    "<选择理由>",
      "impact":       "<该决策影响的范围描述>"
    }
  ],

  "key_parameters": {
    // 该 skill 推导出的关键数值参数（字段名与含义因 skill 而异）
  },

  "freeform_notes": [
    {
      "type":     "<warning|cross_template_dependency|design_hint|custom>",
      "title":    "<标题>",
      "content":  "<详细内容，可多行>"
    }
  ],

  "self_check_summary": {
    "passed":  <number>,
    "failed":  <number>,
    "details": [
      { "check": "<自检项描述>", "status": "pass|fail" }
    ]
  },

  "verifiable_claims": [
    {
      "claim":        "<对外部世界的断言，如 'S1 gather 用标量 SetValue'>",
      "claim_type":   "hardware_api_capability | repo_convention | numeric_derivation",
      "evidence": {
        "source_pointer": "<已查证源定位：ascendc-dev-knowledge 锚点 / platform_diff.md 章节 / 产品表行 / 仓库文件:行 / 用户输入>",
        "attempt_log":    "<查证过程简述：查了哪个源、如何映射/等价推理得出结论>",
        "why_unverifiable": "<仅 verification==UNVERIFIED 时必填：做了哪些查证尝试、为何仍查不动>"
      },
      "verification": "api_checked | repo_aligned | derived | UNVERIFIED",
      "alternatives_ruled_out": ["<被排除方案>: <排除依据>"]
    }
  ],

  "external_verification": "none"
}
```

### 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `step` | 是 | 来源 Skill 名称，与文件名中的 step 一致 |
| `templates` | 否 | template-division 和 tiling-split/tiling-buffer-kernel/tiling-precision-perf 专用，包含该步骤涉及的模板列表 |
| `status` | 是 | 固定为 `"completed"`（写入时自检已通过） |
| `decisions` | 是 | 结构化决策记录，零条时可为 `[]`（仍保留字段） |
| `key_parameters` | 否 | 关键数值参数，按 skill 自行定义 |
| `freeform_notes` | 否 | 自由扩展信息，零条时可为 `[]` 或省略 |
| `self_check_summary` | 是 | 自检结果快照 |
| `verifiable_claims` | 含骨架级决策的步骤必填 | 对外部世界（硬件/仓库）的可核验断言清单；纯内部决策步骤可为 `[]` |
| `external_verification` | 是 | 本产物的外部验证程度，默认 `none`，**不得**因自检通过而提升 |

### tiling 段产物的字段嵌套（方案 S，[[P100]]/方案73）

上表是**通用单步格式**（`step`/`decisions`/`key_parameters`/`self_check_summary`/`verifiable_claims`/`external_verification` 均为顶层）。但 **tiling 三段（split / buffer_kernel / precision_perf）+ vf_design** 的产物有额外约束：**gate-relevant 设计内容必须放进段对象内层，不得作为顶层兄弟**。

原因：段聚合 `design_substages.py:2050` 的 `tmpl_entry[segment_key]=payload.get(segment_key)` **只搬 segment 内层对象**，顶层兄弟会被结构性丢弃。历史 bug（[[P100]]，run 20260724-045259-898837）：producer 把 `verifiable_claims` 产成顶层兄弟 → 聚合丢弃 → anchor AC0/validate GV9-a 永远看不到 → AC0 死循环。

方案 S 双路径消除：
- **内容重构**：`verifiable_claims` / `key_parameters`（+ buffer_kernel 的 `kernel_structure`）放进段对象内层，随聚合天然带过到消费门（构造性保证）。
- **schema 闭合**：四段 schema 各设 `allowed_top_level_keys = {template, <segment>, step, status, decisions, external_verification, self_check_summary}`；顶层只许纯簿记 + 过程元数据（对质原则门不读）。产出方若把 gate-relevant 字段放顶层，DevKit 适配层 `validate_payload` 在段 transition 读产物时即拒为 `schema_violation`（重 spawn），根本到不了聚合。

因此 tiling 段产物的实际形态是：
```json
{
  "template": "T1",
  "split": { "...段字段...": "...", "key_parameters": { }, "verifiable_claims": [ ] },
  "self_check_summary": { "passed": 0, "failed": 0, "details": [ ] }
}
```
（`self_check_summary` 留顶层——唯一消费者 `feedback-selfcheck` 从源文件读、不经聚合；非 load-bearing，见 selfcheck 边界。）其余通用字段（`step`/`status`/`decisions`/`external_verification`）按上表，仍可顶层。

### 契约速答（TL;DR，写产物前先看这里，勿反复翻 schema 或措辞自查）

1. **顶层键**（split / vf_design / buffer_kernel / precision_perf 四段，且仅此七键）：
   `template` + 该段键（`split`/`vf_design`/`buffer_kernel`/`precision_perf`）+
   `step` / `status` / `decisions` / `external_verification` / `self_check_summary`。
   `self_check_summary` 留在顶层（允许），`template` 必须有。
2. **gate 相关内容全部放段对象内层**：`<段>.verifiable_claims`、`<段>.key_parameters`
   （buffer_kernel 还有 `<段>.kernel_structure`）。放顶层会被适配层拒为 schema_violation 重 spawn。
3. **verifiable_claims**：先查证再落（查得到标 `derived`/`api_checked`/`repo_aligned`，附
   `evidence.source_pointer` + `attempt_log`）；只有查不动才 `UNVERIFIED` 且**必填**
   `evidence.why_unverifiable`。措辞不必反复自我打磨——按此规则写即可，机器校验归适配层。
4. **决策**：凡影响下游/正确性的选择记 `decisions`（零条用 `[]`，字段保留）。

---

## Decision Record 编写规则

### 哪些决策必须记录

涉及以下维度之一的决策必须记入 `decisions`：

- 算子类型 / 计算模式的选择
- 模板划分方案
- TilingKey 路由策略
- Buffer 分配方案
- 精度方案（数据类型取舍）
- 对其他步骤有影响的关键参数选择

### 自由扩展区使用规则

`freeform_notes` 用于记录无法用固定字段表达的信息：

- **上游只管记录，不替下游判断**：上游如实写下发现（技术说明、警告、跨模板依赖、性能提示等），不做 "这条下游需不需要知道" 的标注
- **下游主动筛选**：下游 Skill 启动时，根据自身专业知识自行判断哪些 notes 与自身相关
- **type 可扩展**：不预定义完整 type 列表，允许任意自定义 type

### 自检快照规则

`self_check_summary` 记录该步骤自检结果的结构化摘要，只记录自检完毕后的最终结果。零失败时 `failed` 为 0。

**selfcheck 边界（P82 step-58）**：selfcheck 只判**结构 / 逻辑一致性**——公式↔伪代码、Buffer↔Kernel、对齐、UB 占用、字段命名是否自洽。**不判查证充分性**：查证归 `verifiable_claims.verification`（单一权威，§2.5）。selfcheck 不得因"某 claim 标了 UNVERIFIED"而判 fail（那是 claims 的职责），也不得因"selfcheck 通过"而提升 claim 的 verification（破除虚假安全感）。两套机制各司其职，**无需交叉核对一致性**。

### 证据契约字段规则（A2）

- `verification` 等级（从弱到强）——**产出方产出 claim 时即查证**：标 UNVERIFIED 前必须先尝试查证（derived/repo_aligned/api_checked），UNVERIFIED 是 last resort 而非默认：
  - `UNVERIFIED`：**last resort**——产出方已尽力查证仍无法坐实，**必填 `evidence.why_unverifiable`**（查证尝试 + 卡点）。仅设计推断、未对照任何外部源时**不得直接标 UNVERIFIED**——必须先查证。下游 / anchor-consistency / GV9-a 见骨架级此值**必须拦截**。
  - `derived`：由已查证事实经**可复算推导**得出——含数学推导（字节数推导）**与文档推导**（读了 platform_diff / 规格文档等已查证源 + 做了映射/等价推理，结论可被复算。例：读了 `platform_diff.md` 后映射得出"VF split 在 A5 RegBase 下等价于 R 系列 vf_split"——属 `derived`，**非** `UNVERIFIED`）。
  - `repo_aligned`：与目标仓既有实现 / 约定对齐（附 `evidence.source_pointer` 文件出处）
  - `api_checked`：经 `ascendc-dev-knowledge` 明文查证（附 `evidence.source_pointer` 文档锚点）
- `claim_type` 枚举：`hardware_api_capability`（硬件 API 能力，**含其子类**——如 a5_vf_split / regbase_tensor_op / cube_vector_capability 等**一律归 `hardware_api_capability`**，不得自造新 claim_type 值，否则 validate GV9-a 语义匹配漏网）/ `repo_convention` / `numeric_derivation`。
- `external_verification` 默认 `none`，仅当该步全部骨架级 claim 达 `api_checked` / `repo_aligned` 时方可标 `api_checked` / `repo_aligned`；**self_check 通过不改变此值**（破除虚假安全感）。
- **操作数寻址断言（向量 API 偏移/移位路径必填）**：claim 的实现路径依赖向量 API 的操作数**偏移/移位寻址**（移位扫描、交错访问、滑窗等，源/目的操作数以元素粒度偏移进入 API）时，`evidence.attempt_log` 必须含**可复算的对齐断言**：逐个偏移步长的字节换算（`step × sizeof(T)`）+ 该 API 文档**操作数对齐条款**的引用（source_pointer 指到具体文档），逐条判定满足与否；**违约步长必须给出对齐安全的变形**（如小步长段标量处理后再进入对齐安全的向量步）或改选路径，不得带违约放行。结论同时落 `self_check_summary.details[]`（既有通道，不加新字段）。判据纯结构信号（偏移字节 vs 对齐粒度），不涉算子名。
- 凡 `claim_type == hardware_api_capability` 的骨架级 claim，受 `knowledge_policy.md` 的"骨架级 API 强制查证门"约束。

---

## 写入时机

在各 skill 的"输出自检"通过之后立即写入 `{workdir}/checkpoints/{step_name}.json`。

---

## 上游决策记录加载规则

下游 skill 在步骤 0 中加载上游 checkpoint，分为两种等级：

| 等级 | 说明 | 适用 skill | 行为 |
|------|------|-----------|------|
| **强依赖** | 上游步骤的决策记录是当前步骤的必要输入 | template-division, tiling, integrate, docgen | checkpoint 不存在或 status != "completed" → 报错阻断 |
| **可选** | 上游决策记录仅为参考，当前步骤的核心输入来自输出文件本身 | general-design | checkpoint 不存在 → 不影响执行 |

各 SKILL.md 中已硬编码具体检查的上游 checkpoint 路径，不通过 manifest.json 动态发现。

