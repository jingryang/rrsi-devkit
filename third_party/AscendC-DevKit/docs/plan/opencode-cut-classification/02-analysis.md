# opencode 硬切分类修复 — L3 方案分析（2026-09-14，冻结）

> 层级：**L3 / 方案分析**。选项、取舍、拍板。证据见 `01-problems.md`（L1），改动配方见
> `03-impl.md`（L4）。

## 判据的物理事实（选型的出发点）

- delta 事件**不携带内容类型**：`field` 恒 `"text"`（指 part 属性名），按 field 分型不可能。
- 分型信号真实存在于**另一事件**：`message.part.updated` 先行携带完整 part 对象
  （含 `type:"reasoning"|"text"` 与 `id`，text 为空串的 part-start 标记；binary 实证，
  二进制中 delta 循环前的 `I(o,{type:"message.part.updated",…part:{id:c,type:"reasoning",
  text:"",…}})`）。
- delta 事件携带 `partID`，可与 part 对象的 `id` 关联。

## 选项

### A. partID → part 类型关联（拍板 ✅）

`message.part.updated` 时记 `part_kinds[part.id] = kind`（经 `_part_to_block` 归一，
与既有 IR 同源）；`message.part.delta` 到达时按 `partID` 查表，`kind=="thinking"` 才
累计 `step_reasoning_chars` + 打点 `last_reasoning_delta_ts`。表生命周期对齐
`step_reasoning_chars`（step-start 与换轮 role=user 均清空）。

- ✅ 用真实存在的协议信号；语义零失真（text 流不污染体量与 gap 判据）。
- ✅ `step_reasoning_chars` 的「按步计」语义原样保留（step-start 重置不变）。
- ✅ 单点改动（一个 handler 函数 + state 初始化）。

### B. 放弃分型，全部 delta 计入 thinking 证据

- ❌ 正文流会污染体量与末次到达时刻（gap 判据的物理含义被破坏：正文结束距流结束
  的 gap 与思考无关）——语义失真，否决。

### C. 依赖 opencode 升级提供 `field:"reasoning"`

- ❌ 外部版本演进不可控、无承诺；且 SDK 类型 `field: string` 表明 field 本义就是
  属性名而非内容类型——等它改语义不如用已有的 type 标记，否决。

## 配套裁定

1. **死分支删除**（§1.4）：`field == "reasoning"` 分支整删，不留兼容判断。
2. **UT fixture 换真实协议形态**（part-start 标记 + `field:"text"` delta），注释注明
   实证出处（binary + L1 F3）——修 test-drift 的根：fixture 不得按代码假设造数。
3. **sdk backend 不动**（L1 F8：机制不同不受此病），不加对齐代码（无同源判据可对齐）。
4. 未观测到的 delta（订阅中途启动、无 part.updated 先行）→ 不累计（诚实无证据，
   与 classify_cut「无思考流证据→None」的既有语义一致），配负向 UT。
