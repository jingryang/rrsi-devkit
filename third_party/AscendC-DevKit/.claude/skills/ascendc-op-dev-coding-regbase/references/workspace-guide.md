# Workspace 申请指南（Host / Kernel 双侧）

> **文档定位**：给 S4 编码阶段提供 **算子额外 workspace 申请** 的完整实操指南——Host 侧标准三段式、Kernel 侧接收姿势、反模式警告、双侧一致性检查。由 S2 在 `coding_index.md` 通过 `workspace_setting:XXX` 前缀引用。
>
> **触发条件**（只有以下**两类**才引用本文档）：
> 1. **需求说明书 / 详设明确写了需要额外的 workspace**（用户显式提出）
> 2. **算子功能或设计上明显涉及"多核同步后需在 workspace 上开辟空间"**（如多核 reduce 中转、多 Stage 跨核共享中间态）
>
> **不引用**：简单 elementwise 算子、单核完成的算子、所有中间态在 UB TBuf 内的算子。
>
> **不覆盖**：UB 内的 TBuf 临时缓冲（见 `tpipe-usage-guide.md` §7）；核间同步机制（见 `ascendc-sync` skill）。

---

## §1 快速定位

| 场景 | 直接读本文档哪一节 |
|---|---|
| 判断算子是否需要额外 workspace | §2 触发场景与决策 |
| 写 Tiling 侧 workspace 申请代码 | §3 Host 侧标准写法 |
| 写 Kernel 侧接收 workspace 参数 | §4 Kernel 侧接收姿势 |
| 计算 usrSize（多核 / 多 Stage / SyncAll） | §5 usrSize 计算模板 |
| 遇到 AIC error 排查 workspace | §5 反模式清单（含高频错误标注）|
| Host / Kernel 双侧一致性自检 | §6 双侧一致性快速自检 |

---

## §2 触发场景与决策

### §2.1 什么时候需要额外 workspace

**判断依据**：需求说明书 / 详设是否显式提出，或算法设计上是否明显涉及多核同步后需在 workspace 上开辟空间。

| 场景 | 用途 | 是否需要 usrSize |
|---|---|:-:|
| **需求说明书/详设明确要求额外 workspace** | 用户显式提出 | ✅ |
| 多核 reduce / 归约 | 各核局部结果暂存到 GM，SyncAll 后二次归约（**多核同步类型**）| ✅ |
| 多 Stage 中间态跨核共享 | Stage1 输出写 workspace，Stage2 从 workspace 读（**多核同步类型**）| ✅ |
| `SyncAll` / `Synchronized` 每核占 1 BLOCK 作 sync buffer | **多核同步类型** | ✅ |
| bf16 → fp32 → bf16 中间转换 | 放 UB TBuf 即可，**不用 workspace** | ❌ |
| 简单 elementwise / 单核完成的算子 | 无跨核跨阶段依赖 | ❌ |

### §2.2 workspace 层级速览（避免与 UB 混淆）

| 层级 | 位置 | 容量级别 | API |
|---|---|---|---|
| **sysWorkspace** | GM（系统 LibAPI 预留区）| 由 CANN 动态决定 | `PlatformAscendC.GetLibApiWorkSpaceSize()` |
| **usrWorkspace** | GM（紧跟 sysWorkspace 之后）| 用户按需申请 | Tiling 侧手动计算 |
| **TBuf 临时缓冲** | UB（片上）| 数百 KB | `pipe.InitBuffer(tbuf, size)` |

**usrWorkspace 与 UB TBuf 的选型**：能放 UB 就放 UB（快、无跨核问题）；只有**必须跨 tile 持久化** 或 **跨核共享** 时才走 usrWorkspace。

---

## §3 Host 侧标准写法（三段式）

### §3.1 完整代码模板

```cpp
// Tiling 类的 GetWorkspaceSize() 方法内（或 GetPlatform() 内一次搞定，见 §3.3）
ge::graphStatus XxxTiling::GetWorkspaceSize()
{
    // (1) 通过平台接口拿到系统 workspace 大小（关键：不能硬编码！）
    fe::PlatFormInfos* platformInfoPtr = context_->GetPlatformInfo();
    OP_CHECK_NULL_WITH_CONTEXT(context_, platformInfoPtr);
    auto ascendcPlatform = platform_ascendc::PlatformAscendC(platformInfoPtr);
    uint32_t sysWorkspaceSize = ascendcPlatform.GetLibApiWorkSpaceSize();

    // (2) 计算用户额外 workspace 字节数（见 §5 模板）
    size_t usrSize = <per_core_bytes> * <core_count>;   // 视算子情况

    // (3) 通过框架获取 workspace 指针数组，写入 sys + usr
    size_t* currentWorkspace = context_->GetWorkspaceSizes(1);
    OP_CHECK_NULL_WITH_CONTEXT(context_, currentWorkspace);
    currentWorkspace[0] = usrSize + sysWorkspaceSize;   // ⚠️ 关键：sys + usr

    return ge::GRAPH_SUCCESS;
}
```

### §3.2 三段式的**每一段都不能省**

任一段缺失都会导致 AIC error 或未来技术债。详细症状与正确做法见 §5 反模式 1-3。

### §3.3 GetPlatform 与 GetWorkspaceSize 的位置

不同算子把 workspace 申请放在不同位置：
- 简单场景：直接在 `GetPlatform()` 内一次搞定
- 复杂场景：拆到独立 `GetWorkspaceSize()` 方法（如涉及多种 tiling 分支或计算流程）

两者等价，**关键是 `sysWorkspaceSize + usrSize` 必须成对**。

---

## §4 Kernel 侧接收姿势

### §4.1 标准写法

```cpp
extern "C" __global__ __aicore__ void xxx_custom(
    GM_ADDR x, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling)
{
    // ⚠️ 关键：调用 GetUserWorkspace 偏移过系统 workspace 区域
    GM_ADDR usrWorkspace = GetUserWorkspace(workspace);

    KernelXxx op;
    op.Init(x, y, usrWorkspace, tiling);   // 传入的是 usr 部分，不是原始 workspace
    op.Process();
}
```

### §4.2 为什么必须调 `GetUserWorkspace`

两种开发方式下 `workspace` 参数的语义不同：

- **工程化算子开发方式**（主流）：`workspace` 指向"整块 workspace 起点"（sys 在前，usr 在后），`GetUserWorkspace(workspace)` = `workspace + sysWorkspaceSize` 偏移过 sys 区
- **Kernel 直调开发方式**（测试常用）：`workspace` 可能直接就是 usr 起点，此时 `GetUserWorkspace` 是 no-op

**结论**：**始终写 `GetUserWorkspace(workspace)`**——两种开发方式都兼容，工程化下是 no-op（无性能损失），Kernel 直调下是必须的。

> 官方性能文档 `核函数内删除Workspace相关冗余操作.md` 提到工程化方式下可省，但代码库主流做法（100+ 算子）仍显式调用，理由：兼容性 + 语义明确。**推荐始终调用**。

---

### §3.4 usrSize 对齐要求

usrSize 的**具体计算由算子设计决定**（多核策略、Stage 数、shape 等），本文档不给固定模板。但**对齐规则是通用的**，S4 计算完 usrSize 后必须按下表对齐：

| 场景 | 最小对齐 |
|---|---|
| 一般 DataCopy 到 workspace | **32B**（BLOCK_SIZE）|
| SyncAll / Synchronized 同步块 | **32B**（每 slot 必须整 block）|
| 多核并发 write，避免 cache line 竞争 | **64B / 512B**（视芯片而定）|

计算公式：`aligned = ((size + align - 1) / align) * align`。

**注意**：usrWorkspace 起点由 sysWorkspaceSize 保证对齐（LibAPI 内部预留对齐），开发者只需管 usrSize 内部的分块对齐。

---

## §5 反模式清单（AIC error 高频源）

| # | 反模式 | 症状 | 正确做法 |
|---|---|---|---|
| 1 | **只申请 usrSize，未加 sysWorkspaceSize** | Kernel 用 `GetUserWorkspace` 偏移后越界 → **AIC error** | `currentWorkspace[0] = usrSize + sysWorkspaceSize;`（永远配对） |
| 2 | **只申请 sysWorkspaceSize，忘了 usrSize** | Kernel 访问 usr 区域越界 → **AIC error** | 同上 |
| 3 | **sysSize 硬编码**（如 `constexpr uint32_t MINIMAL_WORKSPACE = 16 * 1024 * 1024;` 或类似固定常量）| 当前 CANN 版本可能能跑；未来 LibAPI 需求增长时崩 | 用 `ascendcPlatform.GetLibApiWorkSpaceSize()` 动态获取 |
| 4 | Kernel 侧 host 已加 sysSize，但**未调 `GetUserWorkspace`** | 数据破坏（写入 sys 区域）或 usr 区域偏移错 | Kernel 入口**始终**调 `GetUserWorkspace(workspace)` |
| 5 | Kernel 侧 host 未加 sysSize，但**调了 `GetUserWorkspace`** | Kernel 越界读写 → AIC error | 双侧对齐：要么两边都做，要么都不做（推荐两边都做）|
| 6 | 多核并发 write，但 usrSize 只算了单核 | 数据覆盖 / 竞态 | `usrSize = coreNum × per_core_bytes` |
| 7 | usrSize 未对齐到 32B | DataCopy 可能报错或数据错乱 | 用 `((size + 31) / 32) * 32` 对齐到 BLOCK_SIZE |
| 8 | 用常量塞占位（如 `constexpr uint32_t MINIMAL_WORKSPACE = 32;`）| 当前不出错，未来算子加入新的高阶 API 依赖时会崩 | 即使无 usrSize 需求也要写 `usrSize = 0; currentWorkspace[0] = sysWorkspaceSize;`（不能省略 sysWorkspaceSize）|
| 9 | Tiling 侧 workspace 计算涉及 tiling 数据字段，但字段还未计算完 | workspace 值不对 | workspace 申请必须在所有相关 tiling 字段计算完成**之后** |

**⚠️ 排查 AIC error 时**：优先检查反模式 1（只申请 usrSize）——这是最高频的坑。

---

## §6 双侧一致性快速自检

编写完 Tiling 和 Kernel 后，逐项自检——**大部分自检项直接对应 §5 反模式**：

- [ ] Host 侧 `currentWorkspace[0] = usrSize + sysWorkspaceSize;`（涵盖 §5 反模式 1/2/3/8）
- [ ] Host 侧 `sysWorkspaceSize` 通过 `ascendcPlatform.GetLibApiWorkSpaceSize()` 动态获取，无硬编码常量（涵盖 §5 反模式 3）
- [ ] Host 侧 `usrSize` 涵盖所有核 + 已按 32B 对齐（涵盖 §5 反模式 6/7）
- [ ] Kernel 侧入口调 `GM_ADDR usrWorkspace = GetUserWorkspace(workspace);`（涵盖 §5 反模式 4）
- [ ] Kernel 侧所有 `SetGlobalBuffer(workspace, ...)` 都改为 `SetGlobalBuffer(usrWorkspace, ...)`
- [ ] **Kernel 侧访问的最大偏移量 ≤ Host 侧申请的 usrSize**（本项独立于 §5，需算子自行推算）

---

## §7 与其他知识源的关系

| 知识层 | 关系 |
|---|---|
| `ascendc-dev-knowledge` 官方文档 | 本文档提炼自 `basic_knowledge_docs/附录/常用操作/如何使用workspace.md`、`api_reference_docs/Utils_API/平台信息获取/PlatformAscendC/GetLibApiWorkSpaceSize.md`、`api_reference_docs/SIMD_API/基础API/资源管理/临时空间管理/workspace/GetUserWorkspace.md`、`basic_data_api_docs/gert命名空间/TilingContext/GetWorkspaceSizes.md`；深入 API 语义请查官方文档 |
| `tpipe-usage-guide.md`（本目录）| 讲 UB 内 TBuf 临时缓冲；本文档讲 GM workspace。**边界**：能放 UB 就放 UB（tpipe），跨核跨 tile 持久化才走 workspace |
| `ascendc-sync` skill | 讲 SyncAll 等同步机制；SyncAll 场景下的 workspace 也需按 §3.4 对齐要求申请 |
| `evolution-knowledge/a3/ascendc_api/common_pitfalls.md` #13 "Workspace Buffer Overflow" | 提及多核并发 workspace 大小错误；本文档 §5 反模式 6 已收纳并扩展 |
| `ascendc-tips` MM 类别 | 未覆盖 workspace；本文档补齐 |

---

## §8 引用协议（S2 使用）

S2 在生成 `coding_index.md` 时，通过 `workspace_setting:XXX` 前缀引用本文档。**仅在算子需要额外 usrSize 时使用**——简单 elementwise / 无 usrSize 需求的算子不必引用。

| 前缀 | 指向章节 | 使用场景 |
|---|---|---|
| `workspace_setting:总入口` | §1 + §2 + §3 + §4 | **需要 usrSize 的算子在 B2（Tiling 实现）行强制填入** |
| `workspace_setting:Host模板` | §3 | Tiling 侧编码时快速定位三段式（含 usrSize 对齐要求 §3.4）|
| `workspace_setting:Kernel接收` | §4 | Kernel 入口编码时快速定位 GetUserWorkspace 用法 |
| `workspace_setting:反模式` | §5 | 自检关注点（**尤其反模式 1/3/4 是 AIC error 高频源**）|
| `workspace_setting:一致性检查` | §6 | 编码完成后 Host/Kernel 双侧自检 |

**S4 解析 `workspace_setting:XXX` 时**：Read `${SKILL_ROOT}/references/workspace-guide.md`，定位到对应章节。
