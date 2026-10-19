---
name: ascendc-tips
description: 33 essential AscendC programming tips and common pitfalls for correct kernel development. Organized into 8 categories — Shape & Context APIs, OpDef & Attributes, Compute APIs, Memory Management, Data Transfer & Mask, Unit Testing, Hardware Abstraction, Regbase Programming. Use when writing or reviewing AscendC kernel code.
---

# AscendC Programming Tips

**IMPORTANT**: These 33 tips cover the most common pitfalls and correct usage patterns in AscendC kernel development, organized into 8 categories. Always consult these before writing or reviewing kernel code.

## Shape & Context APIs

**SC-1.** Calculate the shape based on input tensor shapes or retrieve from an input attribute.

**SC-2.** In **TilingContext**, call `GetInputShape(index)` then `GetOriginShape()` to get the shape.

- Total size: `uint32_t totalLength = context->GetInputShape(0)->GetOriginShape().GetShapeSize();`
- Dimension count: `uint32_t dims = context->GetInputShape(0)->GetOriginShape().GetDimNum();`
- Specific dimension: `uint32_t batch = context->GetInputShape(0)->GetOriginShape().GetDim(0);`

**SC-3.** In **InferShapeContext**, set output shape via `GetOutputShape(index)`:

- Set dim count: `context->GetOutputShape(0)->SetDimNum(3);`
- Set dim value: `context->GetOutputShape(0)->SetDim(0, 128);`

**SC-4.** In **InferShapeContext**, get input shape directly (no `GetOriginShape()` needed):

- Get dim count: `context->GetInputShape(0)->GetDimNum();`
- Get dim value: `context->GetInputShape(0)->GetDim(0);`

## OpDef & Attributes

**OD-1.** There is no `HasAttr` API. Get attributes directly as they have default values.

- Float default: use `AttrType(OPTIONAL).Float(0.0)` (no 'f' suffix).

**OD-2.** Do not get input tensor values in tiling (op_host side). Only read attribute values on op_host. Read tensor values on op_kernel side.

**OD-3.** In OpDef, input/output fields DataType, Format, and UnknownShapeFormat must have the same number of parameters.

## Compute APIs

**CA-1.** **CompareScalar**: scalar value must be the **third** parameter.

- Correct: `CompareScalar(dstLocal, src0Local, 1.0f, CMPMODE::LT, tileLength)`
- Wrong: `CompareScalar(dstLocal, 1.0f, src0Local, CMPMODE::LT, tileLength)`
- Output is a bitmask, not usable for math directly. Use Select or Duplicate to fill a tensor from the bitmask.
- Output type must be `LocalTensor<uint8_t>`.
- tileLength must be 256-byte aligned: `tileLength = (tileLength * sizeof(T) + 255) / 256 * 256 / sizeof(T)`.
- This 256-byte count alignment also applies to Compare / Select（mask 相关 count 型 API）；多数纯算术 API 无此要求。

**CA-2.** Use `Muls` and `Adds` for scalar operations. No `Subs` or `Divs` exist.

- Subtract: `Adds(dst, src, -1.0f, len)`
- Divide: `Muls(dst, src, 1.0f/factor, len)`

**CA-3.** **Select** API takes 6 arguments: `Select(dst, mask, src0, src1, MODE, len)`

- Tensor vs scalar: `VSEL_TENSOR_SCALAR_MODE`, scalar as **fourth** param.
- Tensor vs tensor: `VSEL_TENSOR_TENSOR_MODE`.

**CA-4.** Formula `(1 - beta1) * grad`:

- Option A: `Muls(tmpLocal, gradLocal, 1.0f - beta1, len);`
- Option B: `Duplicate(buf, 1.0f - beta1, len);` then `Mul(tmpLocal, gradLocal, buf, len);`

**CA-5.** Cast from `int32_t` to `half`: roundMode is ignored; must call `SetDeqScale((half)1.000000e+00f)` first. This is the int32→half specific Cast path (dequantization scenario, scale=1.0 means no scaling).

**CA-6.** Split even/odd elements (GLU pattern):

- `Arange(offset, (int32_t)0, (int32_t)8, len)`
- `Gather(x_glu, src, offsetU32, (uint32_t)0, count)` for even
- `Gather(x_linear, src, offsetU32, (uint32_t)4, count)` for odd

**CA-7.** Cast float to int8: must go float → half → int8 (two steps).

**CA-8.** **bf16 is not natively supported by many vector compute APIs** on A2 (`dav_c220`). `Muls`/`Adds`/`Mul`/`Add`/`Sub`/`Div`/`Exp`/`Log`/`Sqrt`/`Reciprocal` etc. raise a `static_assert` when instantiated with `bfloat16_t`, so a bf16 kernel path fails to **compile**.

- Pattern: `Cast(x → fp32 tmp)` → do all math in fp32 → `Cast(result → bf16 out)`. Branch with `if constexpr (IsSameType<T, bfloat16_t>::value) { ...fp32 path... } else { ...native path... }`; fp16/fp32 use the native path.
- Needs an extra fp32 scratch buffer: `TBuf<QuePosition::VECCALC> fp32Buf;` + `pipe.InitBuffer(fp32Buf, n * sizeof(float))`.
- Verify per-API/per-chip against the knowledge base before assuming bf16 works — some APIs/newer chips do support it natively; the cast workaround is the safe default when unsure.

## Memory Management

**MM-1.** TBuf usage:

```cpp
// Declaration
AscendC::TBuf<AscendC::QuePosition::VECCALC> tmp1, tmp2;
// Init
pipe.InitBuffer(tmp1, this->tileDataNum * sizeof(half));
// Use
AscendC::LocalTensor<float> p1 = tmp1.Get<float>();
```

**MM-2.** Use `using namespace AscendC;` to avoid the `AscendC::` prefix.

**MM-3.** TBuf InitBuffer: only pass buffer and size. Do NOT pass BUFFER_NUM.

- Correct: `pipe.InitBuffer(tmpBuf1, this->tileLength * sizeof(float));`

**MM-4.** Name PI constants differently, e.g. `custom_pi`.

**MM-5.** Set core count: `context->SetBlockDim(core_num);`

**MM-6.** Tile length calculation: count ALL pipes sharing UB (inputs + outputs + tbufs). E.g., 1 input + 1 output + 2 tbufs = 4 pipes.

**MM-7.** For shape-(1) tensor on kernel side (GM_ADDR):

```cpp
lrGm.SetGlobalBuffer((__gm__ float *)lr, 1);
this->lrLocal = lrGm.GetValue(0);
```

Must call SetGlobalBuffer before GetValue(0).

**MM-8.** AllocTensor() on VECOUT TQue requires pipe.InitBuffer() in Init() first.

**MM-9.** Sync before CopyOut with EnQue/DeQue:

```cpp
outQueue_.EnQue<int8_t>(yOut);
yOut = outQueue_.DeQue<int8_t>();
```

**MM-10.** GM workspace 契约（host tiling 函数末尾）：`ws[0]` 必须 = 用户 workspace **+ 系统 workspace**，缺一不可。

工程（OpDef）模式下框架在 workspace 总分配前端预留系统区、并把 kernel 入口 workspace 指针**偏移过系统区**。只设用户 workspace（或写死 `=0`/`=16*1024*1024`）→ 总分配 < 偏移量 → GM 越界 → aicore exception(**507015**)。**对纯低阶 API 算子（无 Matmul）同样成立**——比知识库「使用 Matmul 等高阶 API 时才需加」字面措辞更强。

```cpp
// tiling.cpp TilingFunc 末尾（SetBlockDim 之后）
auto ascendcPlatform = platform_ascendc::PlatformAscendC(context->GetPlatformInfo());
uint32_t sysWorkspaceSize = ascendcPlatform.GetLibApiWorkSpaceSize();  // 平台相关，禁硬编码
size_t* ws = context->GetWorkspaceSizes(1);
ws[0] = userWorkspaceSize + sysWorkspaceSize;   // 一律加，禁 ws[0] = userWorkspaceSize
```

- `GetLibApiWorkSpaceSize()` 是权威源（平台/CANN 版本相关），**禁写死 16M 或任何常量**。
- 注意区分：本条是 **tiling 函数的 `ws[0]`**（GM workspace，kernel 用）；ACLNN `aclnn{Name}GetWorkspaceSize`（executor workspace）是另一回事，不手动估算。

## Data Transfer & Mask

**DT-1.** For non-32-byte-aligned data, use **DataCopyPad**:

- CopyIn: `DataCopyPad(dstLocal, srcGlobal, copyParams, padParams)`
- CopyOut: `DataCopyPad(dstGlobal, srcLocal, copyParams)`
- copyParams: `{{blockCount, static_cast<uint16_t>(len * sizeof(T)), srcStride, dstStride}}`
- padParams: `{{false, 0, 0, 0}}`

**DT-2.** Mask value range depends on operand data type. **Wrong mask = wrong results, no error.**

- **Bit-wise mode**: 16-bit → array[2], 32-bit → array[1] in (0, 2^64-1], 64-bit → array[1] in (0, 2^32-1].
- **Continuous mode**: 16-bit → [1, 128], 32-bit → [1, 64], 64-bit → [1, 32].

## Unit Testing

**UT-1.** Tiling UT 中三种"空"语义不同，不可混用：

- **Tensor 空指针**（输入不存在）：`InputShapes({..., nullptr, ...})`；aclnn 侧 `INPUT(nullptr, ...)`
- **Tensor 空 shape**（输入存在但无元素）：`{{{}, {}}, dtype, format}`（DimNum=0）或 `{{{0}, {0}}, dtype, format}`（ShapeSize=0）；aclnn 侧 `TensorDesc({}, dtype, format)`
- **Attr 未传**（属性缺失）：attrs `{}` 中省略该属性 → `GetAttrPointer<T>(idx)` 返回 `nullptr`，需用 `(ptr == nullptr) ? defaultVal : *ptr` 安全解引用
- 部分 UT 框架（如 DO_TILING 宏）会将 DimNum==0 的 shape 自动转为 nullptr
- Tiling 代码推荐双重检查：`tensor != nullptr && tensor->GetShapeSize() != 0`

## Hardware Abstraction

**HA-1.** GM offset variables (`blockOffSet_`, `currOffSet_`) and variables involved in offset multiplication (`blockTilingSize_`) must use `uint64_t` / `int64_t`. When total output elements exceed `UINT32_MAX` (~4.2 billion), `uint32_t` offsets overflow and cause wrong write addresses.

- GM offsets (`blockOffSet_`, `currOffSet_`): `uint64_t` / `int64_t` — directly involved in GM address calculation, may exceed 4GB.
- Tiling params in GM offset multiplication (`blockTilingSize_`): `int64_t` — intermediate results like `normalCoreProNum * blockIdx` may overflow.
- UB-related size variables (`ubTilingSize_`): `uint32_t` — UB size is far below 4GB.
- UB-related size variables (perf-optimized): `uint16_t` — only when tiling design is verified safe from address overflow.
- Core count, loop count, flags: `uint32_t` — small value range.

**HA-2.** Never hardcode hardware parameters. Different chips have different specs:

- UB size: 910=192KB, 310P=256KB, 910B/C=256KB (usable ~192KB), 950=256KB (8KB reserved + ≥32KB DataCache).
- Core mode: 910/310P=coupled, 910B/C/950=separated (1AIC+2AIV per core).
- Programming model: 910/310P/910B/C=Membase/SIMD, 950=Regbase/SIMD+SIMT.
- UB bank structure: 910/310P/910B/C=16 groups × 3 banks, 950=8 groups × 2 banks (16KB/bank).

**HA-3.** Host-side and Kernel-side have separate hardware query APIs. **Do not mix them.**

- **Host side** (`op_host/*_tiling.cpp`): runtime query from `platformInfo`, works on all chips.
  - `GetCoreNumAiv()`: AIV core count (910B: 40 cores; returns Vector Core count in separated mode).
  - `GetCoreNumAic()`: AIC core count (same as `GetCoreNum()` in coupled mode).
  - `GetCoreMemSize(CoreMemType::UB, size)`: UB size in bytes.
  - `CalcTschBlockDim()`: auto-calculate blockDim for fused operators.
- **Kernel side** (`op_kernel/*.h`): compiler built-in `constexpr` constants.
  - `Ops::Base::GetUbBlockSize()`: UB block alignment size (Regbase only, 950).
  - `Ops::Base::GetVRegSize()`: vector register width, equivalent to `AscendC::GetVecLen()` (Regbase only, 950).
  - `AscendC::GetBlockNum()`: logical core count (value set by Host-side `SetBlockDim`), works on all chips.
  - `AscendC::GetBlockIdx()`: current core ID, works on all chips.

```cpp
// Host side: op_host/xxx_tiling.cpp
auto ascendcPlatform = platform_ascendc::PlatformAscendC(context->GetPlatformInfo());
uint32_t aivNum = ascendcPlatform.GetCoreNumAiv();
uint64_t ubSize = 0;
ascendcPlatform.GetCoreMemSize(platform_ascendc::CoreMemType::UB, ubSize);

// Kernel side: op_kernel/xxx.h
constexpr uint16_t BLOCK_SIZE = Ops::Base::GetUbBlockSize();   // do NOT write 32
constexpr uint32_t VREG_SIZE  = Ops::Base::GetVRegSize();      // do NOT write 256
uint32_t blockNum = AscendC::GetBlockNum();
```

**HA-4.** `GetBlockNum()` trap in separated mode: under `KERNEL_TYPE_MIX_AIC_1_2` (1:2 mode), AIV-side `GetBlockNum()` returns `blockDim * 2`. Must account for this when calculating data offsets.

## Regbase Programming

**RB-1.** (950 only) Use hardware DIST mode for UB↔register data transfer when bit-width differs (e.g., bf16 16-bit vs register 32-bit). No manual `Pack()` needed.

- CopyIn: `AscendC::MicroAPI::DataCopy<T, AscendC::MicroAPI::LoadDist::DIST_UNPACK_B16>(vReg, ubAddr)` — hardware auto-expands 16-bit to 32-bit register slots.
- CopyOut: `AscendC::MicroAPI::DataCopy<T, AscendC::MicroAPI::StoreDist::DIST_PACK_B32>(ubAddr, vReg, mask)` — hardware auto-compresses 32-bit slots back to 16-bit.
- **Critical trap**: after UNPACK, each element occupies **4 bytes** (32-bit slot). `loopsize` must use expanded size (`sizeof(float)`), not original type size (`sizeof(bfloat16_t)`). Otherwise half the data is skipped.

```cpp
constexpr uint32_t elemSize = (IsSameType<T, float>::value || IsSameType<T, half>::value)
                              ? sizeof(T) : sizeof(float);  // UNPACK expands to 4 bytes
uint32_t loopsize = Ops::Base::GetVRegSize() / elemSize;
```

- This bug is easily masked by single-element test cases (single loop iteration doesn't trigger the skip). Always add multi-element test cases.

**RB-2.** (950 only) `__VEC_SCOPE__` (VF, vector function) is the SIMD vector execution domain with hard constraints:

- **No ternary expressions or if-statements**: generates branch instructions, SIMD pipeline doesn't support conditional branching. Use `UpdateMask<T>(Count)` for auto-decrementing tail handling.
- **Max 4 nested for-loops**: hardware loop controller depth limit. Move outer loops outside VF.
- **DataCopy must use AddrReg**: pointer arithmetic (`ptr + i * loopsize`) generates scalar ALU instructions that block the SIMD pipeline. Use `CreateAddrReg<T>(i, loopsize)` for zero-overhead offset.
- **No class member variable access**: generates extra memory load instructions. Copy to local scalars before entering VF.
- **No scalar division / CeilDiv**: scalar ALU instructions interfere with SIMD pipeline. Complete all division outside VF.

```cpp
// Correct: scalar computation outside VF, only pure vector instructions inside
uint32_t Count = calCount;
uint32_t loopsize = Ops::Base::GetVRegSize() / elemSize;     // division outside
uint16_t looptimes = Ops::Base::CeilDiv(Count, loopsize);    // CeilDiv outside
float rangeVal = to_ - from_;   // copy member variables to local scalars
float offsetVal = from_;

__VEC_SCOPE__
{
    for (uint16_t i = 0; i < looptimes; i++) {
        curMask = MicroAPI::UpdateMask<T>(Count);             // auto-decrement, no ternary/if
        aReg = MicroAPI::CreateAddrReg<T>(i, loopsize);       // AddrReg, no pointer arithmetic
        MicroAPI::DataCopy(vReg0, ubAddr, aReg);              // uses AddrReg
        MicroAPI::Muls(vReg1, vReg0, rangeVal, curMask);      // uses local scalar
        MicroAPI::Adds(vReg2, vReg1, offsetVal, curMask);     // uses local scalar
        MicroAPI::DataCopy(ubAddr, vReg2, aReg, curMask);
    }
}
```

**RB-3.** (A5) Pure-vector (elementwise, no Cube) operators MUST explicitly declare the kernel task type at the kernel entry. `GET_TILING_DATA_WITH_STRUCT` disables ld.lld's auto-derivation of the kernel function type; omitting the declaration fails compilation with `auto derivate failed, please manually add the function type attribute` (C-SYM). Some ref_ops only pass because their copy/compute path fully covers derivable APIs — do NOT rely on that.

```cpp
__global__ __aicore__ void mish(...) {
    REGISTER_TILING_DEFAULT(MishTilingData);
    KERNEL_TASK_TYPE_DEFAULT(KERNEL_TYPE_AIV_ONLY);   // <-- required for pure-vector ops
    GET_TILING_DATA_WITH_STRUCT(MishTilingData, tilingData, tiling);
    ...
}
```

- Placement: after `REGISTER_TILING_DEFAULT(...)`, before `GET_TILING_DATA_WITH_STRUCT(...)`.
- Semantics: pure AIV computation (no Cube) → `KERNEL_TYPE_AIV_ONLY`.
- This is CANN's own pattern: `pkg_inc/atvoss/broadcast/broadcast_sch.h:42`.