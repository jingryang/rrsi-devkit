# gather-scatter — 索引聚集 VF 范式

> 类别范式总纲：判据 → 指令链选型 → 结构模板 → 陷阱。检索先读本文件，再读下方条目。

> **SIMT 泛化参考**：SIMT 编程的通用知识（线程模型/内存 8KB 窗口/同步/坑位）已提炼为独立的 `references/simt/` 参考（`INDEX.md` → `simt-programming-model.md`/`simt-memory-access.md`/`simt-sync.md`/`simt-pitfalls.md`/`simt-examples-map.md`），横切标签 `simt-async` 的条目与其互为印证，检索 SIMT 场景两处都查。

## 判据（结构信号）

VF 核心是**间接寻址搬运**：输出 `y[i]` 的源地址由索引表/坐标计算派生（`y[i]=x[f(i, idx)]`），非线性布局读取。常见形态：
- 逐元素 gather（SIMT thread-per-element 标量读 GM）
- 行段 gather（行对齐批 / 超长行内块）
- stride 表除法链 gather（任意 rank 收缩布局）
- UB 内 Gather（转置、广播取数、交织提取——见 `layout` / `reduce` / `sort-select` 交叉引用）

## 指令链选型

| 形态 | 标准链 | 要点 |
|------|--------|------|
| SIMT 间接读 GM | `__simt_vf__` thread-per-element + stride 循环 + `uint64` 寻址，`yPtr[i]=xPtr[srcOff]` | 零 cast 位搬运；空转保护 `if (threadIdx.x >= curElems) return` |
| SIMD 域 UB Gather | `Arange(idx) → Muls(×pitch) → Gather(dst, src, idx, mask)` | 索引单位=**元素**；16bit dtype 配 `uint16` 索引、32/64bit 配 `uint32`；Gather 不支持 B64 源 |
| 交织 (val,idx) 对跨步读取 | `Arange→Muls(周期)→Add(基址)` 构造索引，分粒度 `Gather` | baseAddr 恒 32B 对齐缓冲首 + 索引承载全部域偏移 |
| 标量广播取数 | `Duplicate(idxReg, t) + Gather(reg, src, idxReg, maskAll)` | 全 lane 同索引 = 广播单元素 |

## 结构模板

SIMT 两层：`__aicore__` wrapper（保持权威 Tensor 签名）→ `__simt_vf__`（裸 `__ubuf__`/`__gm__` 指针 + 标量）。**SIMT 不受 SIMD 硬件循环规则约束**（可用指针下标/运行时分支/uint32 循环）。同步结构见 `experience-simt-async-infra.md`。

## 横切标签

`simt-async`（本类别核心）、`multi-dtype`（18 组合 dtype 分派）、`unaligned-2d`。

## 常见陷阱（最高频）

1. **SIMT UB 读写窗口 = launch 配置的 SIMT 共享内存窗口**（SingleOperatorLaunch 默认 8KB，可经 `simt_share_memory_size`/`dynUBufSize` 放大到 ≈216KB，**非绝对 8KB 硬上限**，见 infra 条目实测证据）；单批 buffer ≤ 窗口即可，不要求排 offset 0 单窗口。
2. **TQue EnQue/DeQue 不保证 async SIMT 完成**：必须显式 `SetFlag/WaitFlag<HardEvent::MTE2_V/V_MTE3>(0)`。
3. **`asc_vf_call` dim3 版**：`kernel_operator.h` 只有纯透传版，须 `#include "simt_api/common_functions.h"`，且 `cce::dim3(256)`（裸 dim3 报 undeclared）。
4. **地址空间指针 cast 禁止**：普通指针 ↔ `__ubuf__` 指针须经 `reinterpret_cast<uintptr_t>` 整数中转。
5. **数组参数入 VF**：权威签名数组参数 decay 为普通指针，需整数中转为 `__ubuf__`。
6. **golden 越界排查**：`innerIdx ≤ innerSrc` 对齐布局契约、`idxDimStrides` 含自身后缀积（`prod(shape[k:])`）——golden 构造错≠kernel 错。
7. **chunk 内行内偏移丢块基址**：UB 行内按 chunk 分块时，inner 偏移须 `(chunkOff+p)%inner`，**禁** `p%inner`——奇数 chunk（chunkOff 非 inner 整数倍）整体错位。

## 条目索引

| 条目 | 内容 | 标签 |
|------|------|------|
| `experience-simt-async-infra.md` | SIMT 启动形态（asc_vf_call/simt_api 头文件）、SIMT 共享内存窗口（默认 8KB、可放大）、HardEvent 同步结构、设备/import 环境（**跨类别共享**） | `simt-async` |
| `experience-simt-gather.md` | 逐元素/行段/除法链三种 gather 形态、uint64 寻址、行级不变量提取、dtype 分派、位级 golden | `simt-async`, `multi-dtype` |

## 实证来源

`gather/compute_gather_{simt,row_segment,stride}_lesson.md`（已迁移，原 lesson 在算子 record dir）。
