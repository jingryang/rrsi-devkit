# 详设关键词 → coding_index 知识引用 路由表

> **用途**：S2 在生成 `coding_index`（JSON 权威源 + MD 渲染镜像）的 `知识/经验` 字段/列时查阅本表——详设中出现的关键词按下表映射为对应的引用协议。
>
> **S4 的角色**：无需再查本表；只按 `coding_index` 已挂载的引用去查目标文档。
>
> **加法**：新增关键词→路径映射时，追加对应分组表格的一行即可。新增知识文档时先加到 `ascendc-dev-knowledge/` 或 `regbase-vf-test/references/` 下，再回本表加一行指向它。

---

## 使用协议（S2 §2.4.1）

1. **一次性加载**：本次开发首次进入 §2.4.1 时 Read 本文件一次并缓存到 context
2. **一次性 grep**：把下方各表的 `详设关键词` 列拼成一条 `grep -oE` 命令，对详设文档执行一次
3. **命中即挂**：对命中的关键词，按对应行的 `推荐引用` 填入 `coding_index.json` 对应步骤 `steps[].knowledge` 数组（`coding_index.md` `知识/经验` 列由 §2.4.4 从 JSON 渲染）
4. **详设约束追加**：详设明确编号的约束（如 `C-1`、`R-1`）按 `requirements.md` §6 的"绑定步骤"列，将 `design-constraint:{编号}` 挂载到对应编码步骤行的知识/经验列。绑定多个步骤的约束只挂首个编码步骤，不重复扩散
5. **经验回捞**：Glob 兄弟目录同类算子的 `vf_lesson.md`，命中即追加 `lesson:{op_name}:{vf_or_step}`

---

## 变量约定

以下变量在 `推荐引用` / `目标位置` 列中出现时，S2/S4 使用时按下表替换：

| 变量 | 替换为 |
|------|-------|
| `${SKILL_ROOT}` | 主 SKILL 注入的 ascendc-dev skill 绝对路径 |
| `${kb_root}` | `${SKILL_ROOT}/../ascendc-dev-knowledge/references` |
| `${vf_root}` | `${SKILL_ROOT}/../regbase-vf-test/references` |
| `${record_dir_sibling}` | `$(dirname $RECORD_DIR)` |

---

## A. Compute / Cast / VF Regbase 类

| 详设关键词 | 推荐引用 | 目标位置 | 该挂到哪一步 | 提示 |
|-----------|---------|---------|-------------|------|
| `FLOAT_OVERFLOW_MODE_CTRL` / `SetCtrlSpr` / `GetCtrlSpr` | `api:SetCtrlSpr` | `${kb_root}/api_reference_docs/SIMD_API/基础API/系统变量访问/` | C.0 或 C.3 | FP8/FP4 转换前保存-清零-恢复；对应详设常见约束「浮点溢出模式」 |
| `Cast<` 出现 + `FP8_E4M3` / `FP8_E5M2` / `fp8_e4m3fn_t` / `fp8_e5m2_t` | `vf-instructions:cast_fp8` | `${vf_root}/vf-instructions/cast.md` | C.3, C.3.VT.* | SrcType 必须为实际浮点类型，禁止 `uint8_t` 替代 |
| `Cast<` 出现 + `FP4_E1M2` / `FP4_E2M1` / `fp4x2_e2m1_t` | `vf-instructions:cast_fp4` | `${vf_root}/vf-instructions/cast.md#fp4` | C.3, C.3.VT.* | FP4 每字节存放 2 个元素；输入字节数 = totalBlockNum × BLOCK_SIZE / 2 |
| `LoadAlign` / `StoreAlign` / `DIST_E2B_B32` / `DIST_BRC` | `vf-instructions:load_align` | `${vf_root}/vf-instructions/load-align.md` + `store-align.md` | C.3, C.3.VT.* | `__simd_vf__` 内 LoadAlign 仅两参数重载（dst, src）；DIST_E2B_B32 读 8 float 广播到 64 slot |
| `Interleave` / `layout register` | `vf-instructions:interleave` | `${vf_root}/vf-instructions/interleave.md` | C.3, C.3.VT.* | 顺序恢复两级：先 cross-pair (0+2, 1+3)，再 merge pair (0+1, 2+3) |
| `VF_CALL` / `__simd_vf__` / `__simt_vf__` / `__simd_callee__` | `kb:regbase_programing_guide` | `${vf_root}/ascend_regbase_programing_guide.md` | C.1, C.3 | 三层调用链、Hardware Loop 规范、寄存器管理 |
| `RegTensor` / `MaskReg` | `kb:regbase_programing_guide§寄存器管理` | `${vf_root}/ascend_regbase_programing_guide.md` | C.3 | 单个 VF 内 RegTensor ≤ 32；MaskReg ≤ 8 |
| `MicroAPI::Add` / `MicroAPI::Mul` / `MicroAPI::` | `api:MicroAPI` | `${kb_root}/api_reference_docs/SIMD_API/基础API/Reg矢量计算/` | C.3 | A5 Vector 执行域内使用 MicroAPI，禁止 A3 高阶 API |

---

## B. 数据搬运类

| 详设关键词 | 推荐引用 | 目标位置 | 该挂到哪一步 | 提示 |
|-----------|---------|---------|-------------|------|
| `DataCopyPad` / `srcStride` / `dstStride` / `DataCopyExtParams` | `tips:DT-03` + `api:DataCopyPad` | `${kb_root}/basic_data_api_docs/DataCopyPad/` | C.2, C.4 | srcStride/dstStride 单位统一为 block 数（除以 BLOCK_SIZE）；常见错误：单位混淆 |
| `32B 对齐` / `512B 对齐` / `对齐` / `alignNum` | `tips:DT-03` | ascendc-tips DT-03 | C.2, C.4 | 非末维最后一维非 512B 对齐时分行搬运 |
| `DataCopy` / `GlobalTensor` / `SetGlobalBuffer` | `api:DataCopy` | `${kb_root}/basic_data_api_docs/DataCopy/` | C.2, C.4 | 32B 对齐基地址；GM↔UB 搬运 |

---

## C. Tiling / Host 类

| 详设关键词 | 推荐引用 | 目标位置 | 该挂到哪一步 | 提示 |
|-----------|---------|---------|-------------|------|
| `PlatformAscendC` / `GetCoreNumAiv` / `GetCoreMemSize` | `tips:SC-01` + `api:PlatformAscendC` | `${kb_root}/api_reference_docs/AI_CPU_API/PlatformAscendC/` | B2 | 硬件参数（核数/UB 大小）必须通过 PlatformAscendC 动态获取，禁止硬编码 |
| `GetCompileInfo` / `TilingParse` | `kb:Tiling编程指南§CompileInfo` | `${kb_root}/basic_knowledge_docs/Tiling/` | B2 | CompileInfo 读取协议 |
| `memcpy_s` / `WriteTilingData` | `kb:Tiling编程指南§WriteTilingData` | `${kb_root}/basic_knowledge_docs/Tiling/` | B2 | TilingData 写入必须使用 `memcpy_s`，不得使用 `memcpy` |
| `Workspace` / `GetWorkspaceSize` / `workspaceSize` | `api:GetWorkspaceSize` | `${kb_root}/basic_data_api_docs/GetWorkspaceSize/` | B2 | 即使 workspaceSize=0 也必须显式设置 |
| `TilingContext` / `GetInputShape` / `GetAttrPointer` / `GetAttr` | `tips:SC-01` + `api:TilingContext` | `${kb_root}/api_reference_docs/AI_CPU_API/TilingContext/` | B2 | TilingContext vs InferShapeContext 区分；GetAttrPointer 返回值需判空；**存在 OPTIONAL 输入时（design_spec 任一输入 `param_type==OPTIONAL`）对该输入的 shape/tensor 查询必须用 `GetOptionalInputShape`/`GetOptionalInputTensor`（IR 索引，缺席返回 nullptr），REQUIRED 输入才用 `GetInputShape`——实例化后索引左移，用 `GetInputShape(proto_idx)` 会读错输入（历史实证：可选输入缺席变体全部 VECTOR_CORE_EXCEPTION）** |
| `IMPL_OP_OPTILING` / `REG_OP` / `IMPL_OP_INFERSHAPE` | `api:IMPL_OP_OPTILING` | `${kb_root}/api_reference_docs/AI_CPU_API/` | B1 | Tiling / InferShape 注册宏 |

---

## D. Kernel 入口 / 配置类

| 详设关键词 | 推荐引用 | 目标位置 | 该挂到哪一步 | 提示 |
|-----------|---------|---------|-------------|------|
| `KERNEL_TASK_TYPE_DEFAULT` / `KERNEL_TYPE_AIV_ONLY` / `KERNEL_TYPE_MIX_AIC_1_1` | `api:KERNEL_TASK_TYPE_DEFAULT` | `${kb_root}/api_reference_docs/SIMD_API/基础API/资源管理/` | C.0 | **纯矢量算子入口必须显式声明** `KERNEL_TASK_TYPE_DEFAULT(KERNEL_TYPE_AIV_ONLY)`。`GET_TILING_DATA_WITH_STRUCT` 关闭 ld.lld 的 kernel 类型自动推导，漏加则编译报 `auto derivate failed`（C-SYM）；ref_op 侥幸通过不可依赖。详见 `error-handling.md` §5.3 陷阱 8 + `ascendc-tips` RB-3 |
| `TILING_KEY_IS` / `GET_TPL_TILING_KEY` / `REGISTER_TILING_DEFAULT` | `kb:kernel_launch_dispatch` | `${kb_root}/basic_knowledge_docs/` | C.0 | TilingKey 路由分支；每个 TilingKey 值必须有对应分支 |
| `GET_TILING_DATA_WITH_STRUCT` / `GET_TILING_DATA` | `api:GET_TILING_DATA` | `${kb_root}/basic_data_api_docs/` | C.0 | Kernel 侧 TilingData 解析 |
| `OpDef` / `AICoreConfig` / `AddConfig` / `.AutoContiguous()` | `tips:OD-02` + `api:OpDef` | `${kb_root}/api_reference_docs/AI_CPU_API/OpDef/` | B1 | OpDef 属性/配置声明；`.AutoContiguous()` 用于允许非连续输入 |

---

## E. dtype 分派 / 精度类

| 详设关键词 | 推荐引用 | 目标位置 | 该挂到哪一步 | 提示 |
|-----------|---------|---------|-------------|------|
| `if constexpr` + `DstType` / `SrcType` / `template <` | `tips:CA-05` | ascendc-tips CA-05 | C.3 | 多 dtype 组合展开：SrcType × DstType 矩阵通过 if constexpr 消除运行时分支 |
| `Cast` + `RoundMode` / `AscendC::RoundMode` | `api:AscendC::RoundMode` | `${kb_root}/api_reference_docs/SIMD_API/基础API/Memory矢量计算/Cast` | C.3 | RoundMode 属于 `AscendC` 命名空间，不是 `AscendC::Reg` |
| `FP16→FP32 升精度` / `BF16→FP32` / `中间精度` | `tips:CA-05` | ascendc-tips CA-05 | C.3 | 中间计算使用 FP32，最终 Cast 回目标 dtype |

---

## F. 同步类

| 详设关键词 | 推荐引用 | 目标位置 | 该挂到哪一步 | 提示 |
|-----------|---------|---------|-------------|------|
| `EnQue` / `DeQue` / `AllocTensor` / `FreeTensor` / `TQue` | `sync:tque-pipeline` | ascendc-sync skill | C.1~C.4 | TQue 双缓协议；EnQue/DeQue 配对；BUFFER_NUM 影响 |
| `PipeBarrier` / `SetFlag` / `WaitFlag` / `eventID` | `sync:pipeline-barrier` | ascendc-sync skill | C.1~C.4 | 核内单流水/多流水同步 |
| `SyncAll` / `IBSet` / `IBWait` / `CrossCoreSetFlag` | `sync:cross-core` | ascendc-sync skill | C.1~C.4 | 核间同步 |

---

## G. 详设约束条款提示（识别硬约束用）

| 详设关键词 | 推荐引用 | 目标位置 | 该挂到哪一步 | 提示 |
|-----------|---------|---------|-------------|------|
| 详设中已编号的约束（如 `C-1`、`R-1`、`约束1`） | `design-constraint:{编号}` | `$RECORD_DIR/requirements.md` §6 或详设原文 | 按 `requirements.md` §6 的"绑定步骤"列挂载到对应编码步骤行 | 硬约束，各步骤 §4.5 Phase 2 就近核对 |
| 未编号但用 `必须` / `禁止` / `需要` / `不得` / `强制` 表述的段落 | `design-constraint:§{章节号}` | 详设章节号定位 | 结合语义人工绑定步骤 | S2 尝试从上下文推断编号或用章节号代替 |

---

## H. 沉淀经验回捞（后续算子自动使用）

| 详设关键词 | 推荐引用 | 目标位置 | 该挂到哪一步 | 提示 |
|-----------|---------|---------|-------------|------|
| 命中同类算子 | `lesson:{op_name}:{vf_or_step}` | `${record_dir_sibling}/{op}_dev_*/vf_verified/kernel_test/{vf}_test/vf_lesson.md` | 对应步骤 | S2 生成时自动 Glob 兄弟目录；S4 只读摘要（vf_lesson.md 前 4 行加粗要点） |

---

## I. 固定编程知识（跨类别通用编程范式）

> 这三类知识**不属于某个算子类别独占**——是走 Vector Pipeline 都可能用到的通用编程范式。本节基于详设关键词按需追挂。

### I.1 TPipe / UB 内存管理（`tpipe:` 前缀）

| 详设关键词 | 推荐引用 | 目标位置 | 该挂到哪一步 | 提示 |
|-----------|---------|---------|-------------|------|
| `TPipe` / `TQue` / `EnQue` / `DeQue` / `AllocTensor` / `FreeTensor` | `tpipe:类框架同步映射` | `${SKILL_ROOT}/references/tpipe-usage-guide.md` §2+§3 | C.1 | Vector Pipeline 场景 Kernel 类框架默认必挂 |
| 多个输入 TQue（多输入算子） | `tpipe:多队列` | `${SKILL_ROOT}/references/tpipe-usage-guide.md` §5 | C.2 | 多个 CopyIn TQue 并存时追加 |
| `CopyIn` / `MTE2` / `GM→UB` 搬入 | `tpipe:CopyIn同步` | `${SKILL_ROOT}/references/tpipe-usage-guide.md` §3.1+§3.2 | C.2 | CopyIn 函数体编码前追加 |
| `CopyOut` / `MTE3` / `UB→GM` 搬出 | `tpipe:CopyOut同步` | `${SKILL_ROOT}/references/tpipe-usage-guide.md` §3.1+§3.2 | C.4 | CopyOut 函数体编码前追加 |
| `DoubleBuffer` / `double buffer` / `双缓冲` / `BUFFER_NUM` | `tpipe:双缓冲` | `${SKILL_ROOT}/references/tpipe-usage-guide.md` §4 | Compute 或 Tiling | 涉及 DoubleBuffer 时追加 |
| `eventID 上限` / `TQue Buffer 总数` / `硬件资源上限` | `tpipe:硬件上限` | `${SKILL_ROOT}/references/tpipe-usage-guide.md` §4.3 | C.1 或 B2 | 需核对是否超 eventID 上限时追加 |
| 详设明确"单缓冲" / "UB 放不下双缓" / "整块处理" | `tpipe:单缓冲降级` | `${SKILL_ROOT}/references/tpipe-usage-guide.md` §4.5 | C.1 | 明确需降级到单缓冲时追加 |
| `TBuf` / `Get<>` / `临时缓冲` / `tmp` / `workspace`（UB 内）| `tpipe:tbuf选型` | `${SKILL_ROOT}/references/tpipe-usage-guide.md` §7.1 | Compute | 需判断走 TQue 还是 TBuf 时 |
| `bf16 → fp32 → bf16` / `Cast 中间产物` / `Reduce 累加缓冲` / `bias 广播复用` | `tpipe:tbuf样例` + `tpipe:tbuf场景速览` | `${SKILL_ROOT}/references/tpipe-usage-guide.md` §7.3+§7.5 | Compute | Compute 内需要写 tmp 缓冲时 |
| `TBuf 跨流水` / `V→MTE3` / `MTE2→V` / `SetFlag<HardEvent>` 与 TBuf 联用 | `tpipe:tbuf手动同步` | `${SKILL_ROOT}/references/tpipe-usage-guide.md` §7.4 | Compute | 涉及跨流水 TBuf 读写时（**关键，必读**） |

**简单场景兜底**：Compute 只有一个 Vector API 调用、无 TBuf、无跨流水、无 DoubleBuffer → 只挂 `tpipe:类框架同步映射`（默认必挂）即可，无需追加其他 `tpipe:*` 引用。

### I.2 Float Overflow Mode（`overflow_mode:` 前缀，仅 A5 Regbase）

> 触发条件：`programming_model == A5 Regbase` **且**（输出/量化目标 dtype ∈ FP8/FP4 家族 **或** 中间态涉及 FP8/FP4 转换）。A3 Membase 场景禁止填入。

| 详设关键词 | 推荐引用 | 目标位置 | 该挂到哪一步 | 提示 |
|-----------|---------|---------|-------------|------|
| `hifloat8_t` / `fp8_e5m2_t` / `fp8_e4m3fn_t` / `FP8_E4M3` / `FP8_E5M2` / `HiFP8` | `overflow_mode:总入口` | `${SKILL_ROOT}/references/overflow-mode-guide.md` §1+§2+§5+§6 | C.1（Kernel 类框架）| FP8 输出/中间态 dtype 命中即挂 |
| `fp4x2_e2m1_t` / `fp4x2_e1m2_t` / `FP4_E1M2` / `FP4_E2M1` | `overflow_mode:总入口` | 同上 | C.1 | FP4 输出/中间态 dtype 命中即挂 |
| `MxQuant` / `mxscale` / `e8m0` + `Cast` 组合 | `overflow_mode:总入口` | 同上 | C.1 | MxQuant 类算子无条件挂（中间态一定涉及 FP8/FP4）|
| `SetCtrlSpr` / `GetCtrlSpr` / `FLOAT_OVERFLOW_MODE_CTRL` | `overflow_mode:代码模板` | `${SKILL_ROOT}/references/overflow-mode-guide.md` §6 | C.3 | Compute 内有 FP8/FP4 转换段（非全程都需要溢出模式）时按需追加，参考模式 C 局部包裹 |
| `SetFloatOverflowModeForRegbase` / helper 惯用写法 | `overflow_mode:helper` | `${SKILL_ROOT}/references/overflow-mode-guide.md` §7 | C.1 | 使用社区 helper 时追加 |
| `SetAtomicAdd` + FP8/FP4 输出 / SuperKernel 场景 / 生产级严谨 restore | `overflow_mode:陷阱清单` | `${SKILL_ROOT}/references/overflow-mode-guide.md` §8 | F（自检）或 C.3 | 原子操作与 FP8/FP4 输出并存时**必挂**（陷阱 4：`DataCacheCleanAndInvalid` 前置约束）；其他场景作为通用自检 |

### I.3 Workspace 申请（`workspace_setting:` 前缀）

> 触发条件（**只有以下两类才挂**）：① 需求说明书/详设明确写了需要额外 workspace；② 算子功能或设计上明显涉及"多核同步后需在 workspace 上开辟空间"（多核 reduce 中转、多 Stage 跨核共享中间态、SyncAll 每核 1 BLOCK sync buffer）。简单 elementwise / 单核完成 / 所有中间态在 UB TBuf 内的算子不挂。

| 详设关键词 | 推荐引用 | 目标位置 | 该挂到哪一步 | 提示 |
|-----------|---------|---------|-------------|------|
| `workspace` / `usrWorkspace` / `usrSize` / `GetWorkspaceSize` / `sysWorkspaceSize` | `workspace_setting:总入口` | `${SKILL_ROOT}/references/workspace-guide.md` §1+§2+§3+§4 | B2（Tiling 实现）| 需要 usrSize 的算子强制填入 |
| `PlatformAscendC.GetLibApiWorkSpaceSize` / `LibApiWorkSpaceSize` | `workspace_setting:Host模板` | `${SKILL_ROOT}/references/workspace-guide.md` §3 | B2 | Tiling 侧编码快速定位三段式（含 usrSize 对齐要求 §3.4）|
| `GetUserWorkspace` / Kernel 入口 workspace 参数处理 / Kernel 侧跨阶段或多 tile 读写 workspace | `workspace_setting:Kernel接收` | `${SKILL_ROOT}/references/workspace-guide.md` §4 | C.0 或 C.1 | Kernel 入口编码时定位；类框架成员化 workspace 时同时挂到 C.1 |
| 详设提到"多核 reduce 中转" / "多 Stage 跨核共享" / "SyncAll" + workspace | `workspace_setting:总入口` | 同 §I.3 首行 | B2 + C.0 | 双侧同时挂 |
| AIC error 排查 / usrSize 计算校验 / Host-Kernel 一致性 | `workspace_setting:反模式` + `workspace_setting:一致性检查` | `${SKILL_ROOT}/references/workspace-guide.md` §5+§6 | F（自检）| 尤其反模式 1/3/4 是 AIC error 高频源 |

---

## 引用协议前缀汇总（含本次新增）

| 前缀 | 含义 | 已有/新增 |
|------|------|----------|
| `tips:XX-NN` | ascendc-tips 条目编号 | 已有 |
| `kb:文档路径§章节` | 知识库文档 + 章节 | 已有 |
| `a5_extra:文件路径` | A5 专用知识 | 已有 |
| `sync:场景名` | 同步机制指南 | 已有 |
| `api:函数名` | API 签名查询 | 已有 |
| `a5-api:函数名` | A5 增强 API 用法（调用示例/参数约束，`regbase-vf-test/references/a5-api-enhanced/`，72 个）——A5 Regbase VF 计算指令**优先于 `api:`**（增强文档含实测示例），无对应文件回退官方 `api:` | **新增** |
| `vf-instructions:模式或指令` | A5 Regbase VF 指令组合/单指令参考 | 已有 |
| `design-constraint:{编号}` | 详设约束条款 | 已有 |
| `lesson:{op}:{vf}` | 前序算子经验回捞 | 已有 |
| `tpipe:XXX` | TPipe UB 内存管理（TQue 流水 + TBuf 临时缓冲）| **新增** |
| `overflow_mode:XXX` | Float Overflow Mode（仅 A5 Regbase） | **新增** |
| `workspace_setting:XXX` | Workspace 申请（Host/Kernel 双侧） | **新增** |

---

## 新知识分层归档规则（后续加知识时先读本节）

新增知识按"变化频率 + 使用触发方式"分三层，各层归档位置和触发方式固定，避免知识积累后失控。

### 三层归档速览

| 层 | 知识类型 | 归档目录 | 触发方式 | 命名规范 |
|---|---|---|---|---|
| **A** | 固定编程范式知识（跨类别通用、变化极慢） | `${SKILL_ROOT}/references/{topic}-guide.md` | S2 按详设关键词命中本文档 I 章节路由，S4 按前缀解析 | 文件名 `{topic}-guide.md`；引用前缀 `{topic}:XXX` |
| **C** | 开发中常见错误和坑（分散且高频） | **分层归档，不集中一处**（见下表） | S4 §4.5 Phase 2 自检时通过对应引用命中 | 见下表 |

### C 类常见错误的进一步归档规则

| 错误性质 | 归档位置 | 使用协议 |
|---|---|---|
| **C1**：跟某个编程范式绑定的错误（EnQue 不配对、SPR 忘 restore 等） | 直接放在该范式的 `{topic}-guide.md` 的 §"常见陷阱"节 | 由 `{topic}:陷阱清单` 引用（或直接在总入口引用中隐含涵盖）|
| **C3**：跨范式/跨类别的通用编码陷阱（32B 对齐、TilingContext vs InferShapeContext 等） | 走外部 skill `ascendc-tips`（已有 26 条 tips + 6 分类）| 由 `tips:XX-NN` 前缀引用；不在本仓库重复 |
| **C4**：前序算子实战踩过的坑 | 分两类：**跨算子类别级经验** → `regbase-vf-test/references/vf_experiences/{类别}/experience-*.md`（按 VF 计算模式归档）；**同算子续作过程资产** → `vf_verified/kernel_test/{vf_func}_test/vf_lesson.md` | 跨算子经验由 `vf-exp:{类别}` 前缀按类别定位；同算子续作由 `lesson:{op}:{vf}` 前缀，S2 自动 Glob 兄弟目录回捞 |

**关键原则**：**不要新建"通用错误集合"文件**（例如 `common-errors.md`）——错误必须**贴着它的原因归档**：
- 跟 API 用法有关 → 放 `{topic}-guide.md`
- 跟通用规范有关 → 走 `ascendc-tips`
- 跟实战踩坑有关 → **跨算子抽象经验走 `vf_experiences/{类别}/experience-*.md`**（按计算模式，不按算子复制）；**同算子续作接力走 `vf_lesson.md`**（过程资产，留在算子 record dir）

### 新增各类知识的操作流程

**新增一个"固定编程范式"知识**（A 层，如未来 `atomic-ops-guide.md`）：
1. 在 `${SKILL_ROOT}/references/` 下新建 `{topic}-guide.md`
2. 文档内定义引用前缀（`{topic}:XXX`）+ S4 解析规则（约定 Read 哪个文件、定位哪节）
3. 在本文件（`design-knowledge-map.md`）新增或追加对应章节，登记"详设关键词 → 前缀"映射
4. 在 `agents/ascendc-dev-s2-analysis.md §2.4.1` 和 `agents/ascendc-dev-s4-coding.md §4.3` 的引用协议表追加前缀行

**新增一个"错误陷阱"**（C 层）：按 C1/C3/C4 分类归档到对应位置，**不动 agent**。

---

## 后续维护

- **加新映射**：追加对应分组（A-I）表格的一行；无需同步其他文件
- **加新知识文档**：先加到 `ascendc-dev-knowledge/references/` 或 `regbase-vf-test/references/` 或 `${SKILL_ROOT}/references/`，再回本表加一行指向它
- **加新引用协议前缀**：需同步更新 `s2-analysis.md §2.4.1 引用协议表` + `s4-coding.md §4.3 Step 4 引用协议表` + 本文件"引用协议前缀汇总"
- **删除映射**：先确认已完成算子的 `coding_index.json` / `coding_index.md` 中无引用该映射的记录
