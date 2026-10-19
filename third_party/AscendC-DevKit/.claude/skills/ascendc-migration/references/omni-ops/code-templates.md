# Code Templates

Production framework code templates for AscendC operator migration.

## Table of Contents

1. [tiling.h Template](#tilingh-template)
2. [tiling.cpp Template](#tilingcpp-template)
3. [tiling_base.cpp Template](#tiling_basecpp-template)
4. [def.cpp Template](#defcpp-template)
5. [kernel.h Template](#kernelh-template)
6. [kernel.cpp Template](#kernelcpp-template)
7. [CMakeLists.txt Templates](#cmakeliststxt-templates)

---

## tiling.h Template

```cpp
#pragma once

#include <cstdint>
#include <register/tilingdata_base.h>
#include <tiling/tiling_api.h>

namespace optiling {
BEGIN_TILING_DATA_DEF({OpName}TilingData)
TILING_DATA_FIELD_DEF(uint32_t, totalItems);
TILING_DATA_FIELD_DEF(uint32_t, itemsPerCore);
// Add operator-specific fields here
END_TILING_DATA_DEF;

REGISTER_TILING_DATA_CLASS({OpName}, {OpName}TilingData)

struct {OpName}CompileInfo {
    uint32_t aicNum;
    uint32_t aivNum;
};
} // namespace optiling
```

---

## tiling.cpp Template

```cpp
#include <cmath>
#include <algorithm>
#include "register/op_def_registry.h"
#include "tiling_base/tiling_templates_registry.h"
#include "tiling_base/tiling_base.h"
#include "platform/platform_info.h"
#include "{op_name}_tiling.h"

namespace optiling {

constexpr uint64_t TILING_KEY_GENERALIZED = 0;

class {OpName}TilingBase : public Ops::Transformer::OpTiling::TilingBaseClass {
public:
    explicit {OpName}TilingBase(gert::TilingContext *context)
        : TilingBaseClass(context) { Reset(); }

    void Reset(gert::TilingContext *context) override {
        TilingBaseClass::Reset(context);
        Reset();
    }

protected:
    bool IsCapable() override { return true; }

    ge::graphStatus GetPlatformInfo() override {
        auto platformInfo = context_->GetPlatformInfo();
        if (!platformInfo) return ge::GRAPH_FAILED;
        auto ascendcPlatform = platform_ascendc::PlatformAscendC(platformInfo);
        aicoreParams_.blockDim = ascendcPlatform.GetCoreNumAiv();
        uint64_t ubSize;
        ascendcPlatform.GetCoreMemSize(platform_ascendc::CoreMemType::UB, ubSize);
        aicoreParams_.ubSize = ubSize;
        return ge::GRAPH_SUCCESS;
    }

    ge::graphStatus GetShapeAttrsInfo() override {
        // Extract shape info from inputs
        return ge::GRAPH_SUCCESS;
    }

    ge::graphStatus DoOpTiling() override {
        ComputeTiling();
        return ge::GRAPH_SUCCESS;
    }

    ge::graphStatus DoLibApiTiling() override { return ge::GRAPH_SUCCESS; }

    uint64_t GetTilingKey() const override { return TILING_KEY_GENERALIZED; }

    ge::graphStatus GetWorkspaceSize() override {
        auto platformInfo = context_->GetPlatformInfo();
        if (!platformInfo) return ge::GRAPH_FAILED;
        auto ascendcPlatform = platform_ascendc::PlatformAscendC(platformInfo);
        workspaceSize_ = ascendcPlatform.GetLibApiWorkSpaceSize();
        return ge::GRAPH_SUCCESS;
    }

    ge::graphStatus PostTiling() override {
        context_->SetBlockDim(usedCores_);
        size_t *ws = context_->GetWorkspaceSizes(1);
        ws[0] = workspaceSize_;
        tilingData_.SaveToBuffer(
            context_->GetRawTilingData()->GetData(),
            context_->GetRawTilingData()->GetCapacity());
        context_->GetRawTilingData()->SetDataSize(tilingData_.GetDataSize());
        return ge::GRAPH_SUCCESS;
    }

    void Reset() {
        usedCores_ = 0;
    }

private:
    void ComputeTiling() {
        // Implement tiling computation
    }

    uint32_t usedCores_ = 0;
    {OpName}TilingData tilingData_;
};

REGISTER_OPS_TILING_TEMPLATE({OpName}, {OpName}TilingBase, 2000);
} // namespace optiling
```

---

## tiling_base.cpp Template

```cpp
#include "{op_name}_tiling.h"
#include "register/op_def_registry.h"
#include "tiling_base/tiling_base.h"
#include "tiling_base/tiling_templates_registry.h"
#include "kernel_tiling/kernel_tiling.h"

namespace optiling {

static ge::graphStatus TilingFor{OpName}(gert::TilingContext *context) {
    return Ops::Transformer::OpTiling::TilingRegistry::GetInstance().DoTilingImpl(context);
}

static ge::graphStatus TilingPrepareFor{OpName}(gert::TilingParseContext *context) {
    (void)context;
    return ge::GRAPH_SUCCESS;
}

IMPL_OP_OPTILING({OpName})
    .Tiling(TilingFor{OpName})
    .TilingParse<{OpName}CompileInfo>(TilingPrepareFor{OpName});

} // namespace optiling
```

---

## def.cpp Template

```cpp
#include "register/op_def_registry.h"

namespace ops {

class {OpName} : public OpDef {
public:
    explicit {OpName}(const char *name) : OpDef(name) {
        // Define inputs
        this->Input("input_name")
            .ParamType(REQUIRED)
            .DataType({ge::DT_BF16})
            .Format({ge::FORMAT_ND})
            .UnknownShapeFormat({ge::FORMAT_ND});

        // Define outputs
        this->Output("output_name")
            .ParamType(REQUIRED)
            .DataType({ge::DT_BF16})
            .Format({ge::FORMAT_ND})
            .UnknownShapeFormat({ge::FORMAT_ND});

        // Configure AICore
        OpAICoreConfig aicore_config;
        aicore_config.DynamicCompileStaticFlag(true)
            .DynamicFormatFlag(true)
            .DynamicRankSupportFlag(true)
            .DynamicShapeSupportFlag(true)
            .NeedCheckSupportFlag(false)
            .PrecisionReduceFlag(true)
            .ExtendCfgInfo("aclnnSupport.value", "support_aclnn");
        this->AICore().AddConfig("ascend910_93", aicore_config);
        this->AICore().AddConfig("ascend910b", aicore_config);
    }
};

OP_ADD({OpName});

} // namespace ops
```

---

## kernel.h Template

Kernel class implementation file.

```cpp
#ifndef {OP_NAME_UPPER}_H
#define {OP_NAME_UPPER}_H

#include "kernel_operator.h"
#include "kernel_tiling/kernel_tiling.h"

namespace {OpName} {
using namespace AscendC;

class Kernel{OpName} {
private:
    TPipe pipe;

    // Queues and buffers
    TQue<TPosition::VECIN, 1> inputQueue;
    TQue<TPosition::VECOUT, 1> outputQueue;
    TBuf<TPosition::VECCALC> calcBuf;

    // Global memory tensors
    GlobalTensor<half> inputGm;
    GlobalTensor<half> outputGm;

    // Tiling parameters
    uint32_t tileLength;
    uint32_t totalLength;

public:
    __aicore__ inline Kernel{OpName}() {}

    __aicore__ inline void Init(GM_ADDR input, GM_ADDR output,
                                const {OpName}TilingData *tilingData)
    {
        // Extract tiling parameters
        this->tileLength = tilingData->tileLength;
        this->totalLength = tilingData->totalLength;

        // Set global memory
        inputGm.SetGlobalBuffer((__gm__ half*)input, totalLength);
        outputGm.SetGlobalBuffer((__gm__ half*)output, totalLength);

        // Initialize buffers
        pipe.InitBuffer(inputQueue, 1, tileLength * sizeof(half));
        pipe.InitBuffer(outputQueue, 1, tileLength * sizeof(half));
    }

    __aicore__ inline void Process()
    {
        uint32_t nTiles = (totalLength + tileLength - 1) / tileLength;
        for (uint32_t i = 0; i < nTiles; i++) {
            CopyIn(i);
            Compute(i);
            CopyOut(i);
        }
    }

private:
    __aicore__ inline void CopyIn(uint32_t tileId) { /* ... */ }
    __aicore__ inline void Compute(uint32_t tileId) { /* ... */ }
    __aicore__ inline void CopyOut(uint32_t tileId) { /* ... */ }
};

} // namespace {OpName}

#endif
```

---

## kernel.cpp Template

Kernel entry function file.

```cpp
#include "kernel_operator.h"
#include "kernel_tiling/kernel_tiling.h"
#include "{op_name}.h"

using namespace AscendC;
using namespace {OpName};

extern "C" __global__ __aicore__ void {op_name}(
    GM_ADDR input, GM_ADDR output,
    GM_ADDR workspace, GM_ADDR tiling)
{
    GET_TILING_DATA(tilingData, tiling);

    Kernel{OpName} op;
    op.Init(input, output, &tilingData);
    op.Process();
}
```

---

## TilingBaseClass Notes

### All 7 pure virtual functions

The base class (`tiling_base/tiling_base.h`) requires all of these:

| Method | Purpose | Typical implementation |
|--------|---------|----------------------|
| `IsCapable()` | Can this class handle the current context? | `return true;` |
| `GetPlatformInfo()` | Read core count and UB size | Use `PlatformAscendC`, set `aicoreParams_` |
| `GetShapeAttrsInfo()` | Extract input shapes, dtypes, attrs | Read from `context_->GetInputShape(0)` |
| `DoOpTiling()` | Compute tiling parameters | Set `blockDim_`, fill tiling struct |
| `DoLibApiTiling()` | Tiling for high-level library APIs | `return ge::GRAPH_SUCCESS;` (if unused) |
| `GetWorkspaceSize()` | Compute workspace bytes needed | Set `workspaceSize_` |
| `PostTiling()` | Finalize: SetBlockDim + SaveToBuffer | Use `blockDim_` and `workspaceSize_` |

### Base class member variables (available to subclasses)

```cpp
gert::TilingContext* context_;                  // tiling context
AiCoreParams aicoreParams_;                     // blockDim, ubSize, etc.
uint32_t blockDim_;                             // set in DoOpTiling, used in PostTiling
uint64_t workspaceSize_;                        // set in GetWorkspaceSize, used in PostTiling
```

The base class calls `context_->SetTilingKey(GetTilingKey())` **automatically** after `PostTiling()`. Never call it manually.

### Elementwise op core allocation pattern (max cores)

```cpp
ge::graphStatus DoOpTiling() override {
    uint32_t platformBlockDim = static_cast<uint32_t>(aicoreParams_.blockDim);
    uint32_t total = static_cast<uint32_t>(totalElems_);

    // Use all available cores (don't cap at element count artificially)
    uint32_t usedCores = (platformBlockDim < total) ? platformBlockDim : total;
    uint32_t elementsPerCore = (total + usedCores - 1) / usedCores;  // ceil
    uint32_t lastCoreElems = total - (usedCores - 1) * elementsPerCore;

    tiling_.set_elementsPerCore(elementsPerCore);
    tiling_.set_lastCoreElems(lastCoreElems);
    tiling_.set_usedCores(usedCores);
    blockDim_ = usedCores;
    return ge::GRAPH_SUCCESS;
}
```

Kernel handles tail core:
```cpp
uint32_t myElems = (GetBlockIdx() == tilingData->usedCores - 1)
                   ? tilingData->lastCoreElems
                   : tilingData->elementsPerCore;
```

### Vector API alignment

`Maxs`, `Cast`, and other vector ops require 32-byte aligned element counts:
- fp16/bf16: multiple of 16 elements
- fp32: multiple of 8 elements

Safe pattern (16 works for all dtypes):
```cpp
uint32_t alignedElems = (myElems + 15) / 16 * 16;
// CopyIn: DataCopyPad with myElems (zero-pads tail)
// Compute: Maxs/Cast with alignedElems (extra zeros → safe result)
// CopyOut: DataCopyPad with myElems (writes only actual data)
```

### TILING_KEY_IS: all branches must be explicit

```cpp
// Wrong — "else{}" does not generate a binary entry for key 2
} else { KernelOp<float> op; ... }

// Correct — every key needs its own TILING_KEY_IS
} else if (TILING_KEY_IS(CUSTOM_OP_FP32)) { KernelOp<float> op; ... }
```

Missing binary entries cause runtime error: `BinaryGetFunctionByEntry failed, funcEntry=N`


### Top-level CMakeLists.txt

```cmake
message(STATUS "=== Debug: start {op_name}.CMakeLists.txt ")
file(GLOB CURRENT_DIRS RELATIVE ${CMAKE_CURRENT_SOURCE_DIR} ${CMAKE_CURRENT_SOURCE_DIR}/*)
foreach(SUB_DIR ${CURRENT_DIRS})
    if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/${SUB_DIR}/CMakeLists.txt")
        add_subdirectory(${SUB_DIR})
    endif()
endforeach()
```

### op_host/CMakeLists.txt

```cmake
message(STATUS "=== Debug: start {op_name}.op_host.CMakeLists.txt ")

add_ops_compile_options(
    OP_NAME {OpName}
    OPTIONS --cce-auto-sync=ON
            -Wno-deprecated-declarations
            -Werror
            -mllvm -cce-aicore-hoist-movemask=false
            --op_relocatable_kernel_binary=true
            -O2
)

set({op_name}_depends {target_path}/{op_name} PARENT_SCOPE)

target_sources(op_host_aclnn PRIVATE
    {op_name}_def.cpp
)

target_sources(optiling PRIVATE
    {op_name}_tiling.cpp
    {op_name}_tiling_base.cpp
)

if (NOT BUILD_OPEN_PROJECT)
    target_sources(opmaster_ct PRIVATE
        {op_name}_tiling.cpp
        {op_name}_tiling_base.cpp
    )
endif()

target_include_directories(optiling PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../common/include/tiling_base
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../common/include
)
```
