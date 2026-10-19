# 知识引用挂载规则

> **用途**：S2 §2.4.1 生成 `coding_index` 时的**详细挂载策略手册**——决定"什么详设特征应挂什么前缀、挂到哪一步"。
>
> **S2 的角色**：Read 本文件一次，缓存到 context；扫描详设时按本文件的 5 大段规则挂引用；然后 §2.4.1 步骤 3-8 完成剩余的类别策展和 JSON 生成。
>
> **S4 的角色**：不读本文件（本文件是 S2 决策规则，S4 只按 `coding_index` 已挂引用执行）。
>
> **与 `design-knowledge-map.md` 的分工**：
> - `design-knowledge-map.md` = **关键词 → 前缀** 表驱动路由（机械 grep 匹配）
> - `knowledge-mapping.md`（本文件）= **场景 → 挂载策略** 语义驱动判定（S2 判断触发条件、按需追加、处理例外）

---

## §1 C.1 类框架步骤的默认引用规则（A3 / A5 强制填入）

对于 `A3 Membase` 和 `A5 Regbase` 两条路径，S2 生成 `coding_index` 时**必须**为 C.1 行强制填入以下引用作为总入口：

| 列 | 默认填入内容 | 说明 |
|---|---|---|
| `知识/经验` | `tpipe:类框架同步映射` | 指向 `tpipe-usage-guide.md` §2 完整样例 + §3 API→HardEvent 映射；S4 编写 Kernel 类框架时一次性读入，理解 EnQue/DeQue/Alloc/Free 的同步语义 |
| `参考代码`（新增开发且 `ref_op` 缺失时） | `example:regbase-vf-test/SingleOperatorLaunch/examples/add_custom.cpp:60-104` | 指向仓库中最简可抄的 TQue 三阶段样例；如 `ref_op` 存在则优先使用参考算子对应文件 |

**追加规则**（S2 按需判断）：

- Compute 或 Tiling 涉及 DoubleBuffer 时 → C.3 行 `知识/经验` 追加 `tpipe:双缓冲`
- 有多个输入 TQue（多输入算子）→ C.2 行追加 `tpipe:多队列`
- 简单算子（Compute 只有一个 Vector API 调用）→ 无需追加，C.1 默认引用已足够
- Compute 涉及临时缓冲（TBuf 场景）→ 按下表追加：

| TBuf 场景 | 追加前缀 | 指向 | 挂到哪一行 |
|---|---|---|---|
| bf16/fp16 → fp32 Cast 中间产物 / SoftMax/LayerNorm/TopK 高阶 API workspace / ReduceSum/ReduceMax 中间累加 | `tpipe:tbuf场景速览` | `tpipe-usage-guide.md` §7.5 | C.3 Compute |
| bias/scale 广播复用 | `tpipe:tbuf样例` + `tpipe:tbuf手动同步` | §7.3 + §7.4 | C.1 类框架 |
| 跨流水读写 TBuf（Init 阶段搬 bias，Process 阶段用）| **必须** `tpipe:tbuf手动同步` | §7.4 | 对应行 |

---

## §2 Float Overflow Mode 追加规则（仅 A5 Regbase）

⚠️ 仅适用于 `meta.json.programming_model == A5 Regbase`。A3 Membase 路径**禁止**填入 `overflow_mode:` 引用。

**触发条件**（S2 从 `requirements.md` / `design_doc` / 参考算子 OpDef 提取输出/量化后 dtype 判定）：

- **触发**：输出 dtype ∈ `{hifloat8_t, fp8_e5m2_t, fp8_e4m3fn_t, fp4x2_e2m1_t, fp4x2_e1m2_t}` 或 Compute 中间态涉及 FP8/FP4 转换（如 MxQuant 类）
- **不触发**：输出 dtype 为整数（int8/int4/int32/uint*）或常规浮点（float/bfloat16_t/half）

**触发时强制填入**（C.1 类框架行 `知识/经验`）：`overflow_mode:总入口` → 指向 `overflow-mode-guide.md` §1+§2+§5+§6

**按需追加**：

- Compute 内有 FP8/FP4 转换段（非全程需要）→ C.3 追加 `overflow_mode:代码模板`（§6，S4 参考模式 C 局部包裹）
- 原子操作与 FP8/FP4 输出并存 → **必须** C.3 追加 `overflow_mode:陷阱清单`（§8，重点关注陷阱 4：`DataCacheCleanAndInvalid` 前置约束）

---

## §3 Workspace 申请追加规则（按需）

S2 从 `requirements.md` / `design_doc` / 参考算子设计判定是否需要**额外用户 workspace（usrSize > 0）**。

**只有以下两类情况触发**：

1. 需求说明书 / 详设明确写了需要额外的 workspace（用户显式提出）
2. 算子功能或设计上明显涉及"多核同步后需在 workspace 上开辟空间"：
   - 多核 reduce / 归约（各核局部结果先存 GM workspace，SyncAll 后二次归约）
   - 多 Stage 中间态跨核共享（Stage1 输出到 workspace → Stage2 从 workspace 读）

**不触发**：简单 elementwise 算子（Add/Mul）/ 单核内完成算子 / 所有中间态都在 UB TBuf 内的算子

**触发时强制填入**（B2 Tiling 实现行 `知识/经验`）：`workspace_setting:总入口` → 指向 `workspace-guide.md` §1-§4

**按需追加**：

- Kernel 侧涉及跨阶段/多 tile 读写 workspace → C.1 追加 `workspace_setting:Kernel接收`（§4，`GetUserWorkspace` 用法）
- Host/Kernel 双侧对齐检查 → F 自检行追加 `workspace_setting:一致性检查`（§6）

**⚠️ 不触发场景**：S2 不填 `workspace_setting:` 引用，但 S4 编写 Tiling 侧代码时**仍应至少写** `usrSize = 0; currentWorkspace[0] = sysWorkspaceSize;`（不能省略 sysWorkspaceSize），此为通用工程规范。

---

## §4 VF Instructions 追加规则（仅 A5 Regbase）

⚠️ 仅当 `meta.json.programming_model == A5 Regbase` 时适用。A3 Membase 路径**禁止**填入 `vf-instructions:` 引用（可继续用 `api:` 前缀查询官方文档）。

### §4.1 三前缀分工

- `api:{函数名}` → 官方 API 参考，适用**简单指令**（无隐藏行为、参数直观）
- `vf-instructions:{文件名}` → **深度指令原理**，适用有 Layout/粒度/配对陷阱的指令
- `vf-instructions:pattern-{X.Y}` → **多指令组合模式**，适用流水线级场景

### §4.2 类型 A：简单指令（用 `api:` 前缀）

Compute 使用以下简单指令（无隐藏行为、官方文档足够）时，追加 `api:{函数名}`：

| 指令类别 | 指令清单 |
|---|---|
| 基础二元算术 | Add, Sub, Mul, Div, Mull |
| 标量参与二元 | Adds, Muls, Maxs, Mins |
| 一元数学 | Abs, Neg, Sqrt, Exp, Log, Ln, Log2, Log10, Relu, LeakyRelu, Prelu |
| 逻辑运算 | And, Or, Xor, Not |
| 位移 | ShiftLeft, ShiftRight, ShiftLefts, ShiftRights |
| 复合计算 | Axpy, MulAddDst, MulDstAdd, AbsSub, ExpSub, MulsCast |
| 类型转换（简单）| Truncate |
| 广播/复制 | Duplicate, Copy, Move |
| 打包/解包（简单）| Pack, UnPack |
| 归约 | Reduce, PairReduceElem, ReduceDataBlock |
| 比较/选择 | Compare, Compares, Select, Squeeze |
| 索引 | Arange |
| 离散聚合 | Gather, GatherB, Scatter |
| 系统变量 | ClearSpr, GetSpr |

### §4.3 类型 B：深度指令（用 `vf-instructions:{文件名}` 前缀）

Compute 使用以下指令，需要**理解行为本质、Layout 语义、配对陷阱**时追加：

| 场景 | 前缀 | 指向 |
|---|---|---|
| Cast 多布局转换（Layout/CastTrait/ZEROING）| `vf-instructions:cast` | cast.md |
| Interleave 数据重排（粒度/Src0-Src1 顺序）| `vf-instructions:interleave` | interleave.md |
| LoadAlign + LoadDist 广播/解交错 | `vf-instructions:load-align` | load-align.md |
| StoreAlign + StoreDist 存储模式 | `vf-instructions:store-align` | store-align.md |
| CreateMask + UpdateMask + MaskMergeMode + 粒度对齐 | `vf-instructions:mask-model` | mask-model.md |
| LocalMemBar VF 内同步屏障（多 pass / in-place）| `vf-instructions:localmembar` | localmembar.md |

> **Cast 场景建议成对挂载**：`vf-instructions:cast` 只讲**指令原理**，不给可搬运代码。凡详设出现 dtype 转换（bf16/fp16↔fp32、int8/int32→fp32、fp32→fp8/fp4 等），**建议同时挂 `vf-examples:cast-index`**（见 §4.3a），让 S4 拿到已验证 helper 作参考；S4 仍可自行声明 CastTrait 手写 Cast（尤其注意 4B→2B 窄化，见 cast_index.md §4）。

### §4.3a 类型 B+：代码级样例索引（用 `vf-examples:{名称}` 前缀）

指向 `regbase-vf-test/references/examples/` 下的**可直接搬运代码**（与类型 B 的"原理文档"互补）：

| 场景 | 前缀 | 指向 | S4 解析动作 |
|---|---|---|---|
| 任意 dtype 转换需要落地代码 | `vf-examples:cast-index` | `examples/cast_index.md` | Read 速查表定位 helper + 行号 → 各 helper 的用法/代码片段/红线已内联在 `cast_common.h` 对应函数上方注释，Read 头文件即得完整上下文 |

**路径解析**：`$AGENT_ROOT/../skills/regbase-vf-test/references/examples/{文件名}`（与 `vf-instructions:` 同源，只是子目录不同）。

### §4.4 类型 C：组合模式（用 `vf-instructions:pattern-{X.Y}` 前缀）

Compute 涉及**多指令流水线**时追加对应 Pattern：

| 场景 | 前缀 | Pattern 状态 |
|---|---|---|
| FP8 反量化 → FP32 输出 | `vf-instructions:pattern-1.1` | 已有 |
| FP8 反量化 → BF16/FP16 输出 | `vf-instructions:pattern-1.2` | 已有 |
| FP4 反量化（手动）| `vf-instructions:pattern-1.3` | 已有 |
| FP4 反量化（DIST_UNPACK4_B8 硬件解包）| `vf-instructions:pattern-1.4` | 已有 |
| Scale 预处理 FP8_E8M0→BF16→FP32 | `vf-instructions:pattern-1.5` | 已有 |
| Scale 预处理 FP8_E8M0→BF16 only | `vf-instructions:pattern-1.6` | 已有 |
| Scale 广播扩展（Self-Interleave）| `vf-instructions:pattern-1.7` | 已有 |
| element-wise + DAG 编排（激活/foreach）| `vf-instructions:pattern-2.x` | 待建 |
| Reduce+Broadcast（RmsNorm/LayerNorm）| `vf-instructions:pattern-3.x` | 待建 |
| Softmax 3-pass | `vf-instructions:pattern-4.x` | 待建 |
| int8/int32 反量化 | `vf-instructions:pattern-5.x` | 待建 |
| Dynamic quantization | `vf-instructions:pattern-6.x` | 待建 |
| MX quant | `vf-instructions:pattern-7.x` | 待建 |
| 非对齐搬运 pipeline | `vf-instructions:pattern-8.x` | 待建 |
| Gather 索引流水线 | `vf-instructions:pattern-9.x` | 待建 |
| GatherMask 压缩输出 | `vf-instructions:pattern-10.x` | 待建 |
| Bitmask 累积（Pooling/Argmax）| `vf-instructions:pattern-11.x` | 待建 |
| 多 pass + LocalMemBar | `vf-instructions:pattern-12.x` | 待建 |

### §4.5 S2 判断口诀

1. **先看是否有 Pattern 匹配**（多指令流水线场景）→ 优先 `vf-instructions:pattern-X.Y`
2. **再看单指令是简单还是深度**：
   - 简单（类型 A 白名单）→ `api:{函数名}`
   - 深度（类型 B 白名单）→ `vf-instructions:{文件名}`
3. **Pattern 和单指令可以叠加**：反量化算子的 C.3 行可能同时填 `vf-instructions:pattern-1.5, vf-instructions:cast, api:Muls`

### §4.6 深度指令细粒度锚点（用 `#` 后缀精准触发章节）

| 前缀 + 锚点 | 触发场景 |
|---|---|
| `vf-instructions:mask-model#tail` | 循环 tail 场景 |
| `vf-instructions:mask-model#粒度` | 多类型宽度切换的量化路径 |
| `vf-instructions:mask-model#merge-mode` | 累积计算、状态更新场景 |
| `vf-instructions:mask-model#accumulate` | MaskOr/MaskAnd 累积场景 |
| `vf-instructions:mask-model#gather-mask` | 变长输出场景 |
| `vf-instructions:localmembar#raw` | 树形 reduce / 多 pass 写-读依赖 |
| `vf-instructions:localmembar#war` | in-place 累加 / split 累积（读后写）|
| `vf-instructions:localmembar#waw` | Pool pad+data 双写 |
| `vf-instructions:localmembar#cross-pipe` | 跨 Vector/Scalar 流水混合场景 |
| `vf-instructions:localmembar#in-place-reduce` | in-place 二分归约每轮之间 |
| `vf-instructions:localmembar#multi-pass` | 完整多 pass 融合算子 |

### §4.7 不触发场景

- 非 A5 Regbase 路径：`vf-instructions:` 前缀禁止填入（可继续用 `api:` 引用官方文档）
- 算子不涉及 VF Pipeline（如纯 Cube）：只填 `api:` 或不填

---

## §5 Sync 触发规则（按需）

S2 从 `requirements.md` / `design_doc` / 参考算子 kernel 逻辑判定是否涉及**手动同步操作**（TQue EnQue/DeQue 自动同步无法覆盖的场景）。触发时**必须**追加 `sync:XXX` 引用到对应行。

### §5.1 触发决策表

| 算子设计特征 | 追加 `sync:` 前缀 | 挂到哪一行 | 依据（`ascendc-sync` skill 章节）|
|---|---|---|---|
| Compute 内 `SetValue` 写 UB 后接 `DataCopy` 出 GM（scalar → MTE3）| `sync:scalar流水` | C.3 Compute | SKILL.md §3.2 + common-pitfalls #10 |
| Compute 内 `SetValue` 后接 Vector 计算（scalar → V）| `sync:scalar流水` | C.3 Compute | 同上 |
| Compute 内 MTE2 搬入后 `GetValue` 读 UB（MTE2 → S）| `sync:scalar流水` | C.3 Compute | 同上 |
| Compute 内层循环反复调用 `FetchEventID` | `sync:eventID池` | C.3 Compute | common-pitfalls #11（eventID 池回绕）|
| 多核 reduce / SyncAll 全核屏障 | `sync:全核屏障` | B2 + C.3 | SKILL.md §4.2 |
| 核 A → 核 B 点对点同步（IBSet/IBWait）| `sync:IBSet` | C.3 Compute | SKILL.md §4.1 |
| AIC/AIV 分离模式或 Cube+Vector 混合 | `sync:CrossCore` | C.0 + C.3 | SKILL.md §4.4 |
| SuperKernel 融合（`SetNextTaskStart`/`WaitPreTaskEnd`）| `sync:任务间` | C.0 + C.4 | SKILL.md §5 |
| 两次 DataCopy 目的地址重叠 | `sync:同流水依赖` | C.2 或 C.4 | SKILL.md §3.1（PipeBarrier）|
| Compute 内同一 UB 段被两个 Vector 指令读写（V→V）| `sync:同流水依赖` | C.3 Compute | 同上（编译器通常自动，手动打 barrier 才需要）|
| `SetAtomicAdd` 前后 | `sync:同流水依赖` + `sync:陷阱` | C.3 Compute | SKILL.md §3.1 + common-pitfalls |
| 涉及同步但机制不明确 | `sync:决策树` | C.1 类框架 | SKILL.md §2 决策树 |
| 判断可能有同步陷阱但不确定 | `sync:陷阱` | F 自检行 | common-pitfalls.md |

### §5.2 S2 判断口诀

**"看一段 UB 最后是哪条流水写的（V? MTE2? S?），后续哪条流水读它（V? MTE3? S?）"** —— 只要跨流水就需要 `sync:` 引用。

TQue 自动同步只覆盖 CopyIn(MTE2)→Compute(V)→CopyOut(MTE3) 三阶段主链路；一切偏离主链路的场景（scalar 参与、多核间、跨阶段访问同一 UB 段）都需要手动同步。

### §5.3 不触发场景

- Compute 只有一个 Vector API 调用、无 scalar 参与、无跨核依赖
- 所有数据流严格遵循 CopyIn → Compute → CopyOut 三阶段，无跨阶段访问 UB（TQue 自动同步已覆盖）

---

## §6 纯 Cube 路径的挂载约束

- `tpipe:` 引用 **不填入**（Cube 侧不走 Vector Pipeline TQue 模式）
- `overflow_mode:` 引用 **不填入**（Cube 侧不涉及 FP8/FP4 Vector Cast）
- `workspace_setting:` **可适用**（仅在详设明确要求或涉及多核同步 workspace 时才追加）
- `sync:` **可适用**（Cube 侧可能涉及 CrossCore、任务间同步等场景）

---

## 后续维护

- 加新触发规则 → 在对应 §1-§5 段追加行
- 新增编程模型（如 Cube 新变种）→ 更新 §6 挂载约束
- 本文件与 `design-knowledge-map.md` 的关系：本文件是**语义规则**（S2 判断"这个场景要挂什么"），design-knowledge-map.md 是**关键词表**（详设扫描时匹配），两者互补 —— 不要把语义规则塞进 design-knowledge-map.md 表里
