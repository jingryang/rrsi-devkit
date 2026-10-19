---
name: ascendc-dev-coding-plan-template
description: "ascendc-dev skill 中 coding_plan.md 的标准模板。定义文件级编码状态跟踪表，与 progress.md 的 sub-stage 进度互补。"
---

# Coding Plan 模板

> **用途**：`coding_plan.md` 是**文件级编码状态跟踪表**，与 `progress.md` 的 sub-stage 进度互补。
> - `progress.md` 回答"当前 Stage 4 的哪个 sub-stage 在进行中"。
> - `coding_plan.md` 回答"每个产出文件是否已经修改、修改状态如何"。
>
> **写入方**：Stage 2 (s2-analysis) 按本模板生成初稿；Stage 4 (s4-coding) 每完成一个 sub-stage 调用 `dev_record.sh update-coding-plan` 更新状态列。
> **读取方**：Stage 4 判断文件级进度；跨 session 恢复时快速定位未完成的文件。

---

## 使用约定

- **文件列基准路径**：表中`文件`列均为相对于 `$CODE_PATH` 的相对路径，`$CODE_PATH` 为 Stage 1 收集并写入 `meta.json` 的算子代码目录。
- **Sub-stage 列**：与 `progress.md` 的 Stage 4 sub-stage 对齐，固定为 `A / B1 / B2 / C.0 / C.1~C.n / E`。
  - `C.1~C.n` 是聚合行：C.1 类框架与 C.2~C.n 的 CopyIn/Compute/CopyOut 文件状态都更新到这一行（`dev_record.sh update-coding-plan` 按此映射更新）。
- **状态列**：`❌` 待开始 / `⏳` 进行中 / `✅` 已完成 / `🔄` 需重做。
- **文件列**：可填写具体文件名（如 `add_custom_tiling.h`），也可使用通配模板（如 `*_tiling.h`）。
- **备注列**：记录当前文件的修改摘要、风险点或阻塞原因。

> **本表仅供 human/s4-coding 可读参考，不参与状态转移**。C 系列是否聚合、文件列是否用概念占位符
> 不影响流程正确性；流程推进由各阶段 agent 的返回结果兜底，`orchestration_plan.json` 的 `deliverables` 仅作人读说明。

---

## 标准表格

```markdown
# Coding Plan

| 文件 | Sub-stage | 状态 | 备注 |
|------|-----------|------|------|
| *_tilingdata.h | A | ❌ | TilingData 结构体定义 |
| *_def.cpp | B1 | ❌ | OpDef + InferShape 定义 |
| *_tiling.h | B2 | ❌ | Host Tiling 策略声明 |
| *_tiling.cpp | B2 | ❌ | Host Tiling 策略实现 |
| *.cpp (kernel入口) | C.0 | ❌ | `extern "C" __global__` 入口 + TILING_KEY_IS 路由（A3）/ 简单路由或 VF_CALL 调度（A5） |
| *.h (kernel类) | C.1~C.n | ❌ | Kernel 类框架 + CopyIn/Compute/CopyOut；A3 用 `LocalTensor` + `DataCopy`，A5 用 `RegTensor` + `VF_CALL` |
| CMakeLists.txt | E | ❌ | 构建配置：源文件列表、依赖、编译选项 |
```

---

## 按编程模型的补充说明

### A3 Membase 路径

| 文件 | Sub-stage | 说明 |
|------|-----------|------|
| `*.cpp (kernel入口)` | C.0 | 含 `extern "C" __global__`、`TILING_KEY_IS` 分支路由、Kernel 类实例化 |
| `*.h (kernel类)` | C.1~C.n | 含 `Init` / `CopyIn` / `Compute` / `CopyOut`、成员变量/队列声明 |

### A5 Regbase 路径

| 文件 | Sub-stage | 说明 |
|------|-----------|------|
| `*.cpp (kernel入口)` | C.0 | 含 `extern "C" __global__`、TILING_KEY_IS 分支路由 / 简单 VF_CALL 调度、Kernel 类实例化 |
| *(VF 精度测试临时文件)* | C.{N}.VT.{M} | **由 `ascendc-vf-test-agent` 管理**，不写入 `code_path`；每个 `.VT.{M}` 步骤验证一个 VF 函数，验证后 `s4-coding` 在后续 Compute 步骤中集成已验证的实现 |
| `*.h (kernel类)` | C.1~C.n | 含 `Init` / `CopyIn` / `Compute` / `CopyOut`、成员变量/队列声明；`Compute` 内部使用 `RegTensor` + `LoadAlign`/`StoreAlign` + `VF_CALL`/`asc_vf_call` |

### 纯 Cube 路径

| 文件 | Sub-stage | 说明 |
|------|-----------|------|
| `*.cpp (kernel入口)` | C.0 | 可合并：含 Matmul/Conv 实例化、循环调度 |
| `*.h (kernel类)` | C.1~C.n | 简单算子可标记为 N/A，复杂算子填写 Matmul/Conv 初始化与主循环 |

---

## 与 progress.md / coding_index.md 的关系

```
progress.md          coding_plan.md          coding_index.md
─────────────        ──────────────          ───────────────
| 4.A ...     |  ↔   | *_tilingdata.h |  ←   | A 步骤详设/参考/自检 |
| 4.B1 ...    |  ↔   | *_def.cpp      |  ←   | B1 步骤详设/参考/自检 |
| 4.B2 ...    |  ↔   | *_tiling.h/.cpp|  ←   | B2 步骤详设/参考/自检 |
| 4.C.0 ...   |  ↔   | *.cpp 入口     |  ←   | C.0 步骤详设/参考/自检 |
| 4.C.N.VT.{M} .. |  ↔   | (临时测试文件)  |  ←   | C.N.VT.{M}（规格在底部 VF 函数规格节，每个 .VT.{M} 一个函数）|
| 4.C.1~C.n ...|  ↔   | *.h 类         |  ←   | C.1~C.n 步骤索引 |
| 4.E ...     |  ↔   | CMakeLists.txt |  ←   | E 步骤详设/参考/自检 |
```

---

## 生成时机

- **Stage 2 (s2-analysis)** 在生成 `coding_index.md` 后，按本模板创建 `coding_plan.md` 初稿。
- 初始状态列全部填 `❌`；备注列可预填该文件在本次变更中需要修改的内容摘要。
- 不要在此文件中写入大段需求分析——那些内容应放在 `requirements.md` 中。
- **自检清单**（写完后逐条核对）：
  1. 状态列**全部为 `❌`**，无任何 `✅`/`⏳`（编码尚未开始）。
  2. 文件列填**真实文件路径或通配符**（便于人读；流程正确性由各阶段 agent 返回兜底，此处非强制，
     `(CopyIn 实现)` 类描述亦可）。
  3. C 系列聚合到 `C.1~C.n` 单行、各子步骤改动说明写在该行备注列（`update-coding-plan` 按此映射更新）。
