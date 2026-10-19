# SIMT 内存访问（GM 直读写 / UB 窗口 / 对齐）

> SIMT 与 SIMD 最大的内存差异：**SIMD 必须 GM→UB→Reg 三级搬运；SIMT 可直接读写 GM（经 DCache）或读写 UB**。据此决定 buffer 布局与 8KB 窗口约束的取舍。

## 内存层级

| 内存 | 作用域 | 特点 |
|------|--------|------|
| GM（Global Memory） | 所有核 | 大容量、低带宽；SIMT 经 DCache 访问 |
| UB（Unified Buffer） | 单核 Thread Block 共享 | 256KB（静态区 + 动态区 + 8KB 预留 + Data Cache ≥32KB） |
| SIMT 寄存器 | Thread 私有 | 极小、极高带宽，数量由 `__launch_bounds__` 决定 |

- 混合编程下 UB 划分：静态内存（编译期定）→ 动态内存 → **8KB 预留空间** → **Data Cache（SIMT 专有，≥32KB）**。
- DataCache = min(256KB − 静态 − 动态 − 8KB, 128KB)；DataCache < 32KB 会编译/校验报错。

## 规则 1：GM 直读直写（优先，避开 8KB 窗口）

`__simt_vf__` 内可直接：

```cpp
__simt_vf__ __launch_bounds__(256) inline void CopySimt(
    __gm__ float *x, __gm__ float *y, uint32_t total)
{
    if (threadIdx.x >= total) { return; }
    y[threadIdx.x] = x[threadIdx.x];   // GM 直读直写
}
```

- 输出直接写 GM 时**无需为输出申请 UB**，不受 SIMT 8KB UB 窗口约束（gather 样例即此形态）。
- 输入 index/数据表可直接从 GM 读（离散寻址是 SIMT 主场）。

## 规则 2：UB 访问必须落在单 8KB 窗口（工具链硬约束）

**实证（Ascend950DT / CANN 9.1.0~9.2.0 / SingleOperatorLaunch）**：SIMT VF 的 **UB 读写窗口 = 绝对 `[0, 8192B)`**，与分配方式无关（TPipe/TBuf、LocalMemAllocator、手工 LocalTensor、静态 `__ubuf__` 池均实测受限）。

- 需要在 SIMT 内读/写 UB 时，把 buffer 排在 **UB offset 0 起的单个 8KB 窗口内**：

```cpp
LocalTensor<uint8_t> pool(VECCALC, 0, 8192);
__ubuf__ DI *idxPtr = (__ubuf__ DI *)pool.GetPhyAddr();
__ubuf__ DX *yPtr   = (__ubuf__ DX *)(pool.GetPhyAddr() + idxBytesAligned); // 段间 32B 对齐
```

- 生产集成预警：大批粒度 / 双 buffer ping-pong 会超 8KB 窗口，须按 per-dtype 压批。

## 规则 3：对齐

- **GM 直读直写**：标量寻址无 32B 对齐约束（每线程独立地址计算）。
- **UB 访问**：同一窗口内多 buffer 段间保持 32B 对齐；UB 上若后续用 SIMD `LoadAlign` 消费，数据必须 32B 对齐排布。
- **SIMT → SIMD 接力**：SIMT 写 UB（连续按线程号写）后由 SIMD `LoadAlign` 读，UB 首地址须对齐，且经 `LocalMemBar`/HardEvent 同步（见 `simt-sync.md`）。

## 规则 4：地址空间指针转换（编译硬约束）

`ccec` **禁止普通指针 ↔ `__ubuf__`/`__gm__` 指针的 C-style 直接 cast**。必须经 `reinterpret_cast<uintptr_t>` 整数中转：

```cpp
uintptr_t addr = reinterpret_cast<uintptr_t>(localTensor.GetPhyAddr());
__ubuf__ DI *idxPtr = reinterpret_cast<__ubuf__ DI *>(addr);
```

- 数组参数 decay 为普通指针入 VF 时同样需要整数中转。
- GM 侧 `GM_ADDR` → `__gm__ T*` 用 `(__gm__ T*)gmAddr` 是官方允许形态（示例通用）。

## 规则 5：短向量 / cache hint / bank conflict（性能向）

- **短向量合并访存**：SIMT 每线程相邻短向量（如 `float2`/`float4`/`int2`）读取比逐元素高带宽，适合带宽瓶颈场景（`simt_api/vector_functions.h`）。
- **cache hint**：`asc_ldcg`（bypass L2）/`asc_ldca`（L2 分配）/`asc_stcg`/`asc_stwt` 控制读写缓存策略，离散读用默认即可。
- **UB bank conflict**：SIMT 写 UB 时若多线程访问同一 bank 组会串行化；按线程号线性排布可避免。

## 常见错误示例

```cpp
// 错误：跨地址空间直接 cast（编译拒）
__ubuf__ uint32_t *p = (__ubuf__ uint32_t *)local.GetPhyAddr();

// 正确：整数中转
uintptr_t base = reinterpret_cast<uintptr_t>(local.GetPhyAddr());
__ubuf__ uint32_t *p = reinterpret_cast<__ubuf__ uint32_t *>(base);
```

```cpp
// 错误：SIMT 写 UB 超过 8KB 窗口（VEC_ERROR / 数据错位）
for (uint32_t i = threadIdx.x; i < 100000; i += blockDim.x) { yUb[i] = xGm[i]; } // 越窗口

// 正确：要么 GM 直写，要么按 8KB 窗口压批多次 SIMT 调用
```

## 参考样例

- GM 直写形态：`references/examples_simt/gather.cpp`、`adds.cpp`、`scatter.cpp`。
- 8KB 窗口 + GM 读 + UB 写形态（gather→SIMD 接力）：`vf_experiences/gather-scatter/experience-simt-async-infra.md` 最小骨架。
