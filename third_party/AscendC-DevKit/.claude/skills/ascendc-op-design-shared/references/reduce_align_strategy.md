# ReduceSum 轴 32B 对齐补零策略（A2/A3）

> 详设阶段 `ReduceSum` 算子的对齐真值与补零范式。被 `ascendc-op-tiling-split` /
> `ascendc-op-tiling-buffer-kernel` / `ascendc-op-tiling-precision-perf` 按需 Read。

## 1. 问题：A2/A3 高阶 ReduceSum API 强制最内层轴 32B 对齐

`ReduceSum` 高阶 API 的 `srcInnerPad` 参数：

> 表示实际需要计算的最内层轴数据是否 32Bytes 对齐。
> Atlas A3 训练系列产品 / Atlas A3 推理系列产品，**当前只支持 true**。
> Atlas A2 训练系列产品 / Atlas A2 推理系列产品，**当前只支持 true**。

——来源：`ascendc-dev-knowledge/references/api_reference_docs/高阶API/归约操作/ReduceSum接口/ReduceSum.md` 第 98 行。

**含义**：若 reduce 最内层轴（R 轴对应的连续段）元素数 × dtype 字节数 **非 32B 整除**，
API 不做内部对齐处理，直接以 32B 粒度访问 UB，可能会触发VEC UB OOB错误。

### 1.1 对齐元素数阈值（32B / dtype_size）

| dtype | sizeof | 对齐元素数（32B / sizeof） |
|-------|--------|--------------------------|
| float32 / int32 | 4 | 8 |
| float16 / bfloat16 | 2 | 16 |
| int8 / uint8 | 1 | 32 |

reduce 最内层轴元素数 `D` 必须：`D % alignElems == 0`，否则必须补零到对齐。

### 1.2 dtype 支持

`ReduceSum` 在 A2/A3 上的 T **仅支持 float**，fp16/bf16 输入需先 Cast 到 fp32，
因此实际参与对齐计算的 `alignElems` 恒为 8（32B / 4）；上表其他 dtype 行仅用于
Cast 前的 CopyIn buffer 尺寸推导。

## 2. 解法：DataCopyPad 尾部补零三段式范式

非对齐场景统一用 **DataCopyPad**（不是 DataCopy）搬运，尾部由 GM 端自然补零：

```
CopyIn:  DataCopyPad(ubTensor, gmTensor, {actualElems, 0, 0})  // GM→UB，尾部自动补零
Compute: ReduceSum(dst, ubTensor, sharedTmpBuf, shape, srcInnerPad=true)
         // shape 里传 alignedElems（= AlignUp(actualElems, alignElems)）
         // 补零区参与累加但不改变求和结果（见 §4）
CopyOut: DataCopyPad(gmTensor, ubTensor, {actualElems, 0, 0})  // UB→GM，只写实际长度
```

**关键约束**：
- `DataCopyPad` 的 `DataCopyExtParams.blockLen` 用**实际字节数** `actualElems × sizeof(T)`，
  搬运时硬件自动在 UB 内按 32B 对齐补零。
- Reduce API 的 `srcShape` 传 **alignedElems**（对齐后的元素数），`srcInnerPad=true`。
- Buffer 分配按 **alignedElems** 算（`AlignUp(actualElems, alignElems) × sizeof(T)`，
  再 `AlignUp(..., 32)`）。

## 3. 补零对 ReduceSum 结果的精度影响

补零区的零值会参与求和：`sum(x, 0) = sum(x)`，**补零不改变累加结果，始终安全**。


## 4. tiling 切分与 buffer 设计要点

### 4.1 reduce 轴切分（当 D > UB 单趟上限时）

当 reduce 轴 D 过大需分块时，**每个 tile 的元素数必须是 alignElems 的倍数**（除尾块外）：
```
tileSize = AlignDown(ubFactor, alignElems)   // 主块向下对齐
tileTail = D - (tileNum - 1) × tileSize      // 尾块可为非对齐
tailAligned = AlignUp(tileTail, alignElems)  // 尾块补零后传入 reduce
```

### 4.2 buffer 字节公式

| Buffer | 元素数 | 字节（含 AlignUp） |
|--------|-------|-------------------|
| CopyIn（srcTile） | `AlignUp(tileSize, alignElems)` | `AlignUp(AlignUp(tileSize, alignElems) × sizeof(T), 32)` |
| sharedTmpBuf | — | `GetReduceSumMaxMinTmpSize(...)` 返回的 `minTmpBytes` |
| dstTile（reduce 结果） | outerElems × 1 | `AlignUp(outerElems × sizeof(T), 32)` |

### 4.3 跨核 reduce 的 workspace

若 reduce 轴跨核切分（每个核算部分 reduce，再 SyncAll 合并），需 GM workspace 存各核中间结果：
`user_workspace_bytes = coreNum × outerElems × sizeof(float)`。
**系统 workspace**（`GetLibApiWorkSpaceSize()`）由 codegen 在 host tiling 末尾追加，不在设计产物体现。

## 5. 适用范围与限制

- **适用**：A2/A3（Membase 路径）上使用 `ReduceSum` 高阶 API 的算子。
- **不适用**：A5（Regbase）路径——A5 用 VF 函数 + RegTensor，reduce 对齐约束不同，见
  `a5_regbase_design.md`。
- **fp16/bf16 输入的 ReduceSum**：必须先 Cast 到 fp32（ReduceSum T 仅支持 float），
  Cast 时机 = CopyIn 后立即（buffer-kernel R3）。
- **替代方案**：若补零开销过大或 UB 预算极紧，可绕开高阶 API，用
  `BlockReduceSum`（低阶 API）逐块归约 + 标量累加合并，
  低阶 API 对非对齐 shape 的容忍度更高。
