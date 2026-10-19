# Per-Sub-Stage 编码自检 Profile

> S4 Agent 在每个 sub-stage 的 Phase 2（自检）中，逐条执行本章对应章节的检查项。
> 每条检查项的结果写入 SELFCHECK 表格的"检查项"列，来源标注为 `agent内置`。

## 4.0 — 编码前置

| # | 检查项 | 检查方法 |
|---|--------|---------|
| 1 | ref_cache/ 非空（若 ref_op 非空） | `find "$RECORD_DIR/ref_cache/" -name "*.h" -o -name "*.cpp"` |
| 2 | coding_index_kb_cache.md 存在 | `test -f` |
| 3 | 前置文档已读取（A5 路径；A3 无此要求，跳过） | 对照 coding_index.md "前置读取"列表 |

## A — TilingData 结构体 (.h)

| # | 检查项 | 检查方法 |
|---|--------|---------|
| 1 | 字段名与设计文档一致 | 逐字段对比 struct vs 设计文档（详设章节或 tiling_strategy.json） |
| 2 | 字段类型正确（uint32_t/uint64_t/float/bool） | 逐字段类型校验 |
| 3 | 无设计外的残留字段 | 字段集合 ⊆ 设计字段集合 |

## B1 — Host Tiling 声明 (.h / _def.cpp)

| # | 检查项 | 检查方法 |
|---|--------|---------|
| 1 | include guard 存在 | grep `#pragma once` 或 `#ifndef` |
| 2 | `#include` tilingdata 文件名正确 | 文件名字符串匹配 |
| 3 | OpDef 注册宏参数与设计一致 | Input/Output 数量、dtype、format 对照 |
| 4 | TilingKey 宏覆盖所有 dtype | ASCENDC_TPL_DATATYPE_SEL 实例数 |

## B2 — Host Tiling 实现 (.cpp)

| # | 检查项 | 检查方法 |
|---|--------|---------|
| 1 | PlatformAscendC API 获取硬件参数 | grep 硬编码数字模式（如 `coreNum = 20`） |
| 2 | TilingKey 模板参数组合完整 | host 用 `ASCENDC_TPL_SEL_PARAM`；`ASCENDC_TPL_ARGS_SEL`/`ASCENDC_TPL_SEL` 穷举的组合覆盖 `ASCENDC_TPL_ARGS_DECL` 声明的所有参数维度 |
| 3 | 函数实现与 B1 声明一致（函数名、参数名、参数数量、参数顺序） | 逐个函数对比 .cpp 实现 vs .h 声明 |
| 4 | set 方法与 TilingData struct 字段一一对应 | 逐字段核对 set 调用 |
| 5 | GM workspace 契约 | grep `GetWorkspaceSizes` → 其赋值（`ws[0]`/`currentWorkspace[0]`）须含 `GetLibApiWorkSpaceSize()`；只设用户量或写死常量（`=0`/`=16*1024*1024`）→ fail「ws[0] 漏 sysWorkspaceSize → 工程模式框架偏移系统区致 GM 越界 507015，改 `userWs + GetLibApiWorkSpaceSize()`」 |
| 6 | **OPTIONAL 输入查询 API 选择（host tiling / InferShape）** | 先查 `design_spec.json` 是否有任一输入 `param_type==OPTIONAL`：无 → 通过。有 → 对 `*_tiling.cpp` / `*_infershape.cpp` 中每个 OPTIONAL 输入（按 design_spec 输入名对号入座），其 shape/tensor 查询**必须用 `GetOptionalInputShape`/`GetOptionalInputTensor`（IR 索引，缺席返回 nullptr 须判空），禁止用 `GetInputShape`/`GetInputTensor`**——`GetInputShape(index)` 的 index 是实例化后（紧凑化）实际索引，任一 OPTIONAL 缺席则后续索引左移，tiling 字段系统性错位（历史实证：可选输入缺席变体全 crash `ACL_ERROR_RT_VECTOR_CORE_EXCEPTION`）。REQUIRED 输入才允许 `GetInputShape` | 命中「对 OPTIONAL 输入用 `GetInputShape`/`GetInputTensor`」→ fail「OPTIONAL 输入 {name} 须用 `GetOptionalInputShape`/`GetOptionalInputTensor`（IR 索引+判空），`GetInputShape` 是实例化后索引，可选缺席左移读错输入」，就地改 |
| 7 | **SIMT 模板 host 必配 Dynamic UB（`SetDynUBufSize`）** | 先按结构信号判本模板是否 SIMT（设计产物编程模型/计算单元为 SIMT：VF 走 Simt 线程化或 SIMT 直访 GM；不认算子名）：非 SIMT → 通过。SIMT → `*_tiling.cpp` 末尾须有 `context->SetDynUBufSize(usableUb)`（当前接口；`SetLocalMemorySize` 是同一函数废弃名，生成代码不用旧名），`usableUb = 平台 UB（`Ops::Base::GetUbSize(context)`，禁硬编码）− DCache（32K/58K/128K 按算子选）− 静态预留`，与 kernel 的 TPipe/InitBuffer 分配用同一个数。缺 → fail「SIMT host tiling 漏声明 Dynamic Unified Buffer（默认 0 = 不声明 → SIMT 共享内存窗口不足 / DCache 未预留，大 shape 越界 VEC_ERROR；详见 ascendc-simt-operator-design-patterns/references/workspace-contract.md §3），加 `context->SetDynUBufSize(...)`」，就地改 |

## C.0 — Kernel 入口

| # | 检查项 | 检查方法 |
|---|--------|---------|
| 1 | 入口函数名 = snake_case(算子名) | 字符串转换比对 |
| 2 | GM 参数顺序：Input→Output→workspace→tiling | 与 OpDef 声明对比 |
| 3 | Kernel 入口为 `template<typename D_T_X,...> __global__ __aicore__` 模板函数 | grep `template` + `__global__ __aicore__` |
| 4 | TilingKey 机制一致（host↔kernel） | host 用 `ASCENDC_TPL_SEL_PARAM` 且 kernel 入口为 template 模板函数 + `if constexpr` 编译期路由；两侧同走 ASCENDC_TPL（任一侧缺正向特征即 fail） |
| 5 | 纯矢量（无 Cube）算子入口显式声明任务类型（A5 强制） | grep `KERNEL_TASK_TYPE_DEFAULT(KERNEL_TYPE_AIV_ONLY)` 在位（`REGISTER_TILING_DEFAULT(...)` 后、`GET_TILING_DATA_WITH_STRUCT(...)` 前）。**根因**：`GET_TILING_DATA_WITH_STRUCT` 关闭 ld.lld 类型自动推导，漏加则编译报 `auto derivate failed, please manually add the function type attribute`（C-SYM）；曾有 ref_op 因 DataCopyPad+向量 API 全路径覆盖而侥幸通过、不可依赖 |

## C.1 — Kernel 类框架

| # | 检查项 | 检查方法 |
|---|--------|---------|
| 1 | 类名 = 算子名（大驼峰） | 字符串匹配 |
| 2 | Init/Process 声明完整 | 签名检查 |
| 3 | TQue/TBuf/TPipe 声明完整（A3/A5 通用）；A5 额外检查 RegTensor/RegPipe 声明 | 按编程模型检查成员变量 |
| 4 | CopyIn/Compute/CopyOut 函数声明占位 | 函数签名存在 |
| 5 | Kernel 入口函数已就绪（C.0 产出）：入口函数名 = snake_case(算子名)，入口中实例化的类名与当前类名一致 | 对比 kernel 入口 .cpp vs 算子名 + 当前类声明 |

## C.2~C.n — 函数体

### CopyIn 类

| # | 检查项 | 检查方法 |
|---|--------|---------|
| 1 | 函数签名与 C.1 类声明一致（函数名、参数类型、参数数量、参数顺序） | 对比函数实现 vs 类声明 |
| 2 | DataCopy/LoadAlign 地址 32B 对齐 | 偏移量为 32 倍数 |
| 3 | EnQue/DeQue 配对 | 计数匹配 |
| 4 | mask 值范围 0~255 | 检查常量 |

### Compute 类（A3 Membase）

| # | 检查项 | 检查方法 |
|---|--------|---------|
| 1 | 函数签名与 C.1 类声明一致（函数名、参数类型、参数数量、参数顺序） | 对比函数实现 vs 类声明 |
| 2 | Vector API 参数类型/顺序 | API 签名对比 |
| 3 | TBuf/UB 分配释放配对 | 计数匹配 |
| 4 | 循环边界/tail 处理 | 逻辑走查 |

### Compute 类（A5 Regbase）

> VF 函数内部合规性已由 `ascendc-vf-test-agent` 在 `.VT.{M}` 步骤中验证。
> 以下检查针对**集成到 Compute() 之后**的代码，确保集成过程中未引入新问题。

| # | 检查项 | 检查方法 |
|---|--------|---------|
| 1 | 函数签名与 C.1 类声明一致（函数名、参数类型、参数数量、参数顺序） | 对比 Compute() 实现 vs 类声明 |
| 2 | VF_CALL 中所有 LocalTensor 已通过 GetPhyAddr() 转换为 `__ubuf__*` | 检查 VF_CALL 调用点的参数 |
| 3 | 集成后 VF 函数签名仍为 `inline void`，参数仅 `__ubuf__*` 或 PoD | 逐个 VF grep（集成可能误改签名） |
| 4 | **集成后 VF 函数体与 vf-test 已验证代码逐字一致** | diff 当前源码中的 VF 函数体 vs `{vf_func}_custom.cpp` 对应片段；任何非调用侧适配的改动均视为违规 |
| 5 | **算子所需 dtype 组合 ⊆ VF 规格表 `支持的 dtype 组合`** | 对照 `coding_index.md` VF 规格表与算子 `op_spec`/`template_division.json` 的 dtype 需求；发现缺口 → 返回 CK |
| 6 | 集成后 RegTensor ≤ 32、MaskReg ≤ 8 | grep 统计（集成新增的临时寄存器可能超限） |
| 7 | 集成后 SIMD/SIMT 隔离未破坏 | 检查 callee 调用链 |
| 8 | 集成后 Membase API 未误入 VF 域 | grep DataCopy/TILING_KEY_IS/AscendC:: |
| 9 | 所有 VF 函数文件已就绪（`vf_verified/kernel_test/{vf_func}_test/{vf_func}_custom.cpp` 存在） | 逐一检查 coding_index.md VF 规格表中列出的文件路径 |

### CopyOut 类

| # | 检查项 | 检查方法 |
|---|--------|---------|
| 1 | 函数签名与 C.1 类声明一致（函数名、参数类型、参数数量、参数顺序） | 对比函数实现 vs 类声明 |
| 2 | StoreAlign/DataCopy 地址 32B 对齐 | 偏移量为 32 倍数 |
| 3 | EnQue/DeQue 配对 | 计数匹配 |
| 4 | mask 正确 | 检查常量 |

## C.{plugin} — op_plugin 注册

> 仅 kernel_architecture 声明 plugin_code section 时执行。cann-bench eval harness 按
> `func(*tensor_inputs, **attrs)` 调用，要求 m.def schema **所有 Tensor 输入在前、scalar
> attrs 在后** —— 否则位参 binding 把 Tensor 强转 scalar → pybind cast 失败、kernel 从未执行
> （run 20260727-144633-2a1db8 gather 全 0 分根因）。

| # | 检查项 | 检查方法 |
|---|--------|---------|
| 1 | `TORCH_LIBRARY_FRAGMENT(namespace, m)` 与可解析 `m.def("op(...)")` 同源存在 | grep 同一 `*_plugin.cpp` |
| 2 | **m.def schema 必须 == proto.yaml schema**（type+name+order 全等）；**禁止套 torch 规范签名**（proto.yaml 权威是 `gather(Tensor x, Tensor index, int dim=0)`，套 torch 的 `gather(input,dim,index)` 是接口对齐 bug） | 比对 plugin m.def vs `state.proto_schema`（= proto.yaml `operator.schema`，54/54 proto.yaml 均声明）的 type+name 序全等；proto.yaml 是 plugin 接口 + harness 调用契约的共同权威 |
| 3 | `<op>_meta` / `<op>_npu` C++ 实现函数签名参数顺序与 m.def schema 一致（dispatcher 按 schema 顺序传位参给 fn） | 对比 fn 形参序 vs m.def schema 参数序 |
| 4 | namespace 与 `codegen_manifest.callable_target.symbol` 末段一致 | 字符串比对 |
| 5 | schema 参数名与 proto.yaml 一致（cann-bench 关键字调用 `func(**params)`） | 比对 m.def 名 vs `state.proto_schema` 参数名 |

> 检查项 2/3 违例时由 s4-coding **就地 Edit 修正**：重排 m.def schema 参数序 + 同步重排对应
> C++ 实现函数签名（参数名不变、只挪顺序，fn body 按名引用无需改）。禁止外推给下游门。

## C.{api} — L0 API / aclnn 适配（op_api 层）

> 仅 kernel_architecture 声明 api_code section 时执行（aclnn_*.cpp：L2 API aclnn{Name}GetWorkspaceSize
> + aclnn{Name}，L0 API = OP_TYPE_REGISTER + InferShape + AiCore dispatch）。
> **attr 在四层重复声明（design_spec attrs / OpDef / plugin schema / L0 宏），L0 launcher 宏的 `OP_ATTR(...)`
> 是 attr → tiling 的唯一传递管道**——漏声明不崩不报错，只行为默认值不对（历史实证：unique 缺
> `OP_ATTR(returnInverse)` → host tiling 读 flag 恒 0 → 逆索引全零，RC/KL 双跑才暴露）。

| # | 检查项 | 检查方法 |
|---|--------|---------|
| 1 | 每个 attr 都经 `OP_ATTR(...)` 在 L0 launcher 宏声明 | 取 `design_spec.json` attrs 名集合；在 `aclnn_*.cpp` 中核对 launcher 宏（如 `ADD_TO_LAUNCHER_LIST_AICORE`/`ADD_TO_LAUNCHER_LIST`，以目标仓既有算子为准）的 `OP_ATTR(...)` 参数逐一覆盖每个 attr（attr 无默认值或 tiling 需读值必传；宏内顺序按宏契约） |
| 2 | `OP_ATTR` 参数名/类型与 OpDef attrs 一致 | 比对 L0 宏 `OP_ATTR` 名 vs `{op}_def.cpp` 注册的 attr 名/类型 |
| 3 | L2/L0 签名一致 | `aclnn{Name}GetWorkspaceSize` ↔ `aclnn{Name}` 参数序一致；workspace 大小经 executor 图构建获取，不手动估算 |

## E — CMakeLists.txt

| # | 检查项 | 检查方法 |
|---|--------|---------|
| 1 | 所有源文件已列出 | 对比 coding_plan.md |
| 2 | target 名称一致 | grep target |
| 3 | include 路径完整 | 检查 -I 路径 |

## F — 编码后综合自检

> F 不重复各 sub-stage 已执行的检查，只做跨 sub-stage 一致性 + 回归扫描。

| # | 检查项 | 检查方法 |
|---|--------|---------|
| 1 | TilingData Host↔Device 字段一致性（终检） | 跨 A + C 系列交叉对比 |
| 2 | OpDef↔Kernel 入口 GM 一致性（终检） | 跨 B1 + C.0 交叉对比 |
| 3 | CTX_DRIFT:major 逐条复核 | 读 history.log |
| 4 | 前序 sub-stage 自检结果回归扫描 | 读取 `$RECORD_DIR/selfcheck_4.*.md`，逐文件确认各 sub-stage 的 ✅ 项仍有效（代码未被后续步骤意外修改） |
| 5 | coding_index.md 字段映射表终检 | Host set ↔ Device read 全链路 |
| 6 | **RegBase SIMD 函数静态预检（KernelStaticCheck）** | 对 A5 Regbase 算子，在 `ccec` 编译前调用 `$SKILL_ROOT/KernelStaticCheck/check_kernel.py {CODE_PATH} --recursive --format json --strict`，确认 `__simd_vf__` / `__simd_callee__` 无 inline/ubuf/GM/hardware-loop/branch/UpdateMask mutation 违规；违规 → 返回 CK，定位到具体文件行号 |
| 7 | **Plugin launch 形态 ↔ Tiling/Kernel 列表级设计一致性（跨层对账）** | 与 F.1~F.6 纵向自洽检查**正交**的横向对账——查「设计声明的迭代维度是否在实际 launch 路径上真正生效」。**两侧同时命中即违规**：① `op_plugin/*.cpp` 的 `*_npu` 内存在「遍历列表的 `for` 循环 + 循环体内 aclnn/launch 调用」（`ACLNN_CMD`/`aclnn{Op}`/`launch_*`）；② `op_host/*_tiling.cpp` / `op_kernel/*` 存在列表级痕迹（`listLen`/`tensorLens[]`/`MAX_TENSOR_LIST_LEN`/`coreStartTensor`）且取值非恒 `= 1`。**违规语义**：tiling/kernel 列表路径成**死代码** + 每次调用付 L 次 launch 与 L 遍 host 栈开销（历史实证 foreach_norm：plugin 逐张量循环调单张量 aclnn → `listLen≡1`，完整实现的 L 轴均分 + D 轴拆分全废，L=2~4 用例各付 L 次 launch）。**处置二选一**：A. 列表语义上提 plugin（TensorList 整体传参 + 单次 launch，默认）；B. 保留逐元素 launch 须在 `decision_log.json.known_issues` 记录理由并在证据列引用 `decision_log.known_issues[{i}]`，**理由缺失判 ❌**。**不触发**：单张量算子（plugin 无遍历循环）或 host/kernel 无列表级痕迹——两侧条件缺一即不触发 |

### F.6 KernelStaticCheck 集成说明

- **调用位置**：4.F 综合自检内，s5-compile 之前；也可在 s5-compile 的编译前置检查中再次执行作为兜底。
- **适用范围**：仅 `programming_model == "A5 Regbase"`；Membase / Cube 路径跳过。
- **输入**：`{CODE_PATH}`（= `meta.json.code_path`，即 op_dir）。KernelStaticCheck 只识别 `__simd_vf__` / `__simd_callee__` 函数，因此扫描整个 op_dir（含 op_host / op_kernel / op_api / op_plugin）不会产生 RegBase 规则误报；如希望只扫描 kernel 目录，可读取 `kernel_architecture.json` 的 `kernel_code.directory`（默认 `op_kernel`）。
- **输出**：文本或 JSON 报告；`--strict` 模式下发现失败时返回非零退出码。
- **失败处理**：检查项失败视为 `CK` 类错误，进入 s4 retry/rollback 流程；s4-coding agent 必须根据报告定位到行号并就地修复，不得跳过进入 s5。
