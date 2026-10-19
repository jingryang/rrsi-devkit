# SIMT 间接寻址 gather 三种形态（逐元素 / 行段 / 除法链）

## 适用判据

输出 `y[p]` 源地址由索引表 + 坐标计算派生，SIMT thread-per-element 标量读 GM。三种形态由布局决定：
- **逐元素**：`y[e+i] = x[o*dimSize + idx]`，`o=(e+i)/idxDim`
- **行段**：`y[p] = x[(o*dimSize+idx)*innerSrc + jBase + j]`，`p = lr*jElem + j`（Case A 行对齐批 / Case B 超长行内块共用）
- **除法链**：`srcOff = Σ_{k≠dim} c_k·xDimStrides[k] + idx[i]·xDimStrides[normalizedDim]`，`c_k` 由 tt 按 `idxDimStrides[k+1]` 链式分解（任意 rank 收缩布局）

## 关键实现要点

1. **两层结构（SIMT 等价形态）**：`__simt_vf__ __launch_bounds__(256)` 蓝图体（`__gm__ DX*` 源 + `__ubuf__` 索引/输出 + 标量）→ `__aicore__` wrapper 保持权威 Tensor/数组签名，`GetPhyAddr()` 提取裸指针转发。
2. **线程映射**：
   - 逐元素/除法链：`for (i = threadIdx.x; i < n; i += blockDim.x)` stride 循环 + 空转保护 `if (threadIdx.x >= curElems) return`。
   - 行段：外层行循环顺序 + 内层 `for (j = threadIdx.x; j < jElem; j += blockDim.x)` 行内元素映射；R6 **行级不变量** `rowBaseOff = o*dimSize*innerSrc + jBase` 提出行循环一次计算（分配律等价）。
   - **chunk 分块（UB 行内子块）**：行内按 UB chunk 切块时，块内线程位置 `p` 必须换算到**全局行内下标** `g = chunkOff + p`，再用 `g` 参与行内 inner 偏移/行号分解（`m = g % inner`）——**禁**用线程局部位置 `p` 直接取模（`p % inner`）：奇数 chunk（`chunkOff` 非 `inner` 整数倍）会整体错位（历史实证：索引聚集 VF 用 `p % inner`，奇数 chunk 全部读错源地址）。
3. **寻址全程 uint64**（`(e+i)/idxDim`、`o*dimSize+idx` 中间量驻寄存器），native 位搬运零 cast。
4. **除法链（rank 收缩）**：`rem=tt` 逐维 `c_k = rem/div; rem -= c_k*div`；尾维 `div = (k==rankUsed-1) ? 1 : idxStrides[k+1]` 三元编译期折叠免除法；`if (k != normalizedDim)` 分支在 SIMT 体合法。
5. **stride 表 UB 常驻**：16×uint64=128B 经独立 GM 参数 + `DataCopyPad(MTE2)` 一次搬入共享内存窗口头部，与 index 同批 MTE2、同一 `SetFlag/WaitFlag<MTE2_V>` 覆盖可见性（避免 `__aicore__` scalar 写 UB 与 V 流水顺序风险）。
6. **runtime dtype 分派**：tiling 带 dtypeCode，kernel 入口 switch 18 case 调用模板实例，单次编译覆盖全 dtype 矩阵。
7. **golden（bit-exact）**：向量化除法链（`t=arange(e,e+n); rem=t.copy(); for k: ...`）或行段 `r=p//jElem; j=p%jElem; src=(o*dimSize+index.astype(u64))*innerSrc+jBase+j`；`np.array_equal` 比较（位搬运无容差）。

## 坑位与对策

| 现象 | 根因 | 对策 |
|------|------|------|
| golden IndexError（host 越界） | case 参数违反布局契约（如 `innerSrc < innerIdx`）或 idxDimStrides 语义错（用不含自身版本） | `innerIdx ≤ innerSrc` 显式校验；`idxDimStrides` 用**含自身后缀积** `prod(shape[k:])`，`xDimStrides` 用不含自身标准 stride |
| 数组参数入 VF 编译拒 | `const uint64_t*` ↔ `__ubuf__` 指针禁直接 cast | `reinterpret_cast<uintptr_t>` 整数中转 |
| 单批数据超共享内存窗口 | 单批 buffer 超过 launch 配置的 SIMT 共享内存窗口（默认 8KB，可放大，见 infra 条目） | 压批到 ≤ 配置窗口（默认 8KB 时 (int64,int64)=16B/elem 预算 n ≤ 480~496），或放大窗口 |
| chunk 内行内偏移丢块基址 → 精度错（奇数 chunk 全错） | VF 按 UB chunk 分块处理行内元素时用线程局部位置 `m = p % inner`，未加 chunk 基址 | 行内偏移一律含 chunk 基址：`m = (chunkOff + p) % inner`；`chunkOff` 按 chunk 序号×块内元素数推进，不从 0 重计 |
| device 0 不可用 | 环境设备异常 | 先 `DeviceInfo()` 选 Health:OK（本机默认 device 1） |

## 可复用模式（最小骨架）

```cpp
template <typename DX, typename DI>
__simt_vf__ __launch_bounds__(256) inline void GatherKernel(
    __gm__ DX* xPtr, __ubuf__ DI* idxPtr, __ubuf__ DX* yPtr, uint64_t... scalars)
{
    if (threadIdx.x >= curElems) { return; }
    for (uint32_t i = (uint32_t)threadIdx.x; i < curElems; i += (uint32_t)blockDim.x) {
        uint64_t o = (e + (uint64_t)i) / idxDim;
        uint64_t srcOff = o * dimSize + (uint64_t)idxPtr[i];
        yPtr[i] = xPtr[srcOff];
    }
}
```

## 横切标签

`simt-async`（见 `experience-simt-async-infra.md`）、`multi-dtype`。

## 实证来源

- `gather` `compute_gather_simt` / `compute_gather_row_segment` / `compute_gather_stride`（57/57、57/57、60/60 bit-exact，18/18 dtype 组合）
