---
name: ascendc-migration
description: Migrate AscendC operators from DSL Pipeline output to production repository. Supports two repository types — custom op repo (omni-ops) and mainline repos (ops-transformer / ops-nn). Use when user requests "迁移到生产环境", "迁移到生产仓", "production migration", or wants to integrate a DSL-generated operator into any production codebase.
---

# AscendC Production Migration

Migrate DSL-generated operators to production repository structure.

## Step 0: Select Target Repository

Before proceeding, determine the target repository:

```yaml
AskUserQuestion:
  question: "算子要迁移到哪个生产仓库？"
  header: "目标仓库"
  options:
    - label: "自定义算子仓 (omni-ops)"
      description: "omni-ops 仓，迁移 DSL 生成的算子到生产目录结构"
    - label: "主线仓 (ops-transformer / ops-nn)"
      description: "CANN 主线仓（暂未支持，敬请期待）"
```

- If user selects **自定义算子仓 (omni-ops)** → proceed to [omni-ops 迁移流程](#自定义算子仓-omni-ops-迁移)
- If user selects **主线仓 (ops-transformer / ops-nn)** → proceed to [主线仓迁移](#主线仓迁移待补充)

---

# 自定义算子仓 (omni-ops) 迁移

## Migration Workflow

### Phase 0: Analyze Target Repository

**Before migration, analyze the target repository structure:**

1. If user provides target path, analyze existing operators in that repository
2. Find a reference operator with similar structure (same category or similar functionality)
3. Identify the repository's conventions:
   - Directory structure (`op_host/`, `op_kernel/`, etc.)
   - File naming patterns (`{op_name}_tiling.h`, `{op_name}_def.cpp`, etc.)
   - Kernel split pattern (`.cpp` entry + `.h` implementation, or single file)
   - CMakeLists.txt structure and dependencies
   - Tiling framework (TilingBaseClass vs simple TilingFunc)

**Key questions to determine:**

- Does target use `TilingBaseClass` inheritance? (production pattern)
- Does target use `IMPL_OP_OPTILING` macro? (production pattern)
- Does target use `OpAICoreConfig`? (production pattern)
- Is kernel split into `.h` (implementation) + `.cpp` (entry)?
- Is there a `torch_ops_extension/` directory? (→ PTA layer needed)

### Phase 1: Pre-flight Check

1. Confirm DSL Pipeline evaluation passed (accuracy + performance)
2. Identify source: `output/{op_name}/{OpName}Custom/`
3. Identify target directory based on repository analysis

### Phase 2: Create Directory Structure

```bash
mkdir -p {target_path}/{op_name}/{op_host,op_kernel}
```

### Phase 3: Migrate Files

Based on target repository analysis, perform necessary conversions:

| Source (output/)                  | Target                       | Conversion                           |
|-----------------------------------|------------------------------|--------------------------------------|
| op_host/{op}.cpp (TilingData)     | op_host/{op}_tiling.h        | Extract + add CompileInfo            |
| op_host/{op}.cpp (TilingFunc)     | op_host/{op}_tiling.cpp      | Rewrite as TilingBaseClass           |
| (new file)                        | op_host/{op}_tiling_base.cpp | Create IMPL_OP_OPTILING              |
| op_host/{op}.cpp (OpDef)          | op_host/{op}_def.cpp         | Remove SetTiling, add OpAICoreConfig |
| op_kernel/{op}.cpp                | op_kernel/{op}.h             | Extract kernel class                 |
| op_kernel/{op}.cpp                | op_kernel/{op}.cpp           | Keep entry function only             |

### Phase 4: Create CMakeLists.txt

Follow the target repository's CMakeLists.txt patterns. See [code-templates.md](references/omni-ops/code-templates.md) for common templates.

### Phase 5: Build & Install Operator Package

```bash
# Build — -c specifies chip version, e.g.:
#   ascend910b   → 910B (A2)
#   ascend910_93 → 910C (A3)
bash build.sh -c "{chip_version}" -n "{op_name}"

# Install — use $ASCEND_OPP_PATH (points to the active toolkit's opp dir)
cd build/
./CANN-omni_training_custom_ops--linux.aarch64.run \
    --install-path=${ASCEND_OPP_PATH}
```

### Phase 6: PTA Layer (if torch_ops_extension exists)

After the operator package is built and installed, invoke the **`ascendc-pta` skill** to add the `torch.ops.custom.npu_{op_name}` Python interface.

> Note: `ascendc-pta` skill 内含仓库路由，会自动识别目标仓库类型。

## Key Conversions

### TilingFunc → TilingBaseClass

**Before (DSL output):**

```cpp
static ge::graphStatus TilingFunc(gert::TilingContext* context) {
    context->SetBlockDim(BLOCK_DIM);
    tiling.SaveToBuffer(...);
}
```

**After (production):**

```cpp
class {OpName}TilingBase : public Ops::Transformer::OpTiling::TilingBaseClass {
protected:
    bool IsCapable() override { return true; }
    ge::graphStatus GetPlatformInfo() override;   // get aicoreParams_.blockDim from platform
    ge::graphStatus GetShapeAttrsInfo() override; // extract shape/attrs
    ge::graphStatus DoOpTiling() override;        // compute tiling, set blockDim_
    ge::graphStatus DoLibApiTiling() override { return ge::GRAPH_SUCCESS; }
    ge::graphStatus GetWorkspaceSize() override;  // set workspaceSize_
    ge::graphStatus PostTiling() override;        // SetBlockDim + SaveToBuffer
    uint64_t GetTilingKey() const override;       // base class calls SetTilingKey automatically
};
REGISTER_OPS_TILING_TEMPLATE({OpName}, {OpName}TilingBase, 2000);
```

**Critical TilingBaseClass rules:**
- All 7 pure virtual functions must be implemented (see code-templates.md for full list)
- `context_->SetTilingKey()` is called automatically by the base class after `PostTiling()` — do NOT call it manually
- `blockDim_` and `workspaceSize_` are base class members — assign in `DoOpTiling()` / `GetWorkspaceSize()`, use in `PostTiling()`
- Use `GetPlatformInfo()` to read actual core count: `aicoreParams_.blockDim = ascendcPlatform.GetCoreNumAiv()` (910B = 40)

### OpDef → OpAICoreConfig

**Before (DSL output):**

```cpp
this->SetInferShape(ge::InferShape).SetInferDataType(ge::InferDataType);
this->AICore().SetTiling(optiling::TilingFunc);
this->AICore().AddConfig("ascend910b");
```

**After (production):**

```cpp
// InferShape/InferDataType defined as static functions in the same file (no extern)
static ge::graphStatus InferShape(gert::InferShapeContext *context) { ... }
static ge::graphStatus InferDataType(gert::InferDataTypeContext *context) { ... }

// In OpDef constructor — NO SetTiling call
this->SetInferShape(InferShape).SetInferDataType(InferDataType);
OpAICoreConfig aicore_config;
aicore_config.DynamicCompileStaticFlag(true)
    .DynamicFormatFlag(true)
    .DynamicRankSupportFlag(true)
    .DynamicShapeSupportFlag(true)
    .NeedCheckSupportFlag(false)
    .PrecisionReduceFlag(true)
    .ExtendCfgInfo("aclnnSupport.value", "support_aclnn");
this->AICore().AddConfig("ascend910b", aicore_config);
this->AICore().AddConfig("ascend910_93", aicore_config);
```

### Kernel Split Pattern

**Before (single file):**

```cpp
// op_kernel/{op}.cpp - contains both class and entry
class KernelOp { ... };
extern "C" __global__ void {op}(...) { ... }
```

**After (split):**

```cpp
// op_kernel/{op}.h - kernel class implementation
namespace {OpName} {
class Kernel{OpName} { ... };
}

// op_kernel/{op}.cpp - entry function only
#include "{op}.h"
extern "C" __global__ __aicore__ void {op}(...) {
    KERNEL_TASK_TYPE_DEFAULT(KERNEL_TYPE_AIV_ONLY);
    GET_TILING_DATA_WITH_STRUCT({OpName}TilingData, tiling_data_in, tiling);
    const {OpName}TilingData *__restrict tilingData = &tiling_data_in;
    if (TILING_KEY_IS(KEY_0)) {
        Kernel{OpName}<half> op;
        op.Init(x, y, tilingData);
        op.Process();
    } else if (TILING_KEY_IS(KEY_1)) { ... }
    // IMPORTANT: use explicit TILING_KEY_IS for every branch
    // A bare "else {}" does NOT generate a binary entry → runtime crash
}
```

## Checklist

**Operator Package:**
- [ ] Analyze target repository structure
- [ ] Find reference operator for patterns
- [ ] Create directory structure
- [ ] Migrate tiling.h (pragma once, CompileInfo with aicNum/aivNum)
- [ ] Migrate tiling.cpp (TilingBaseClass with all 7 pure virtuals)
- [ ] Create tiling_base.cpp (IMPL_OP_OPTILING → TilingRegistry)
- [ ] Migrate def.cpp (InferShape inline, OpAICoreConfig, no SetTiling)
- [ ] Split kernel files (.h + .cpp, explicit TILING_KEY_IS for all keys)
- [ ] Create CMakeLists.txt
- [ ] Build: `bash build.sh -c "{chip_version}" -n "{op_name}"` (910B→`ascend910b`, 910C→`ascend910_93`)
- [ ] Install to `${ASCEND_OPP_PATH}`

**PTA Layer (if applicable):** → invoke `ascendc-pta` skill after install

---

# 主线仓迁移（待补充）

> 目标仓库：[ops-transformer](https://gitcode.com/cann/ops-transformer) / [ops-nn](https://gitcode.com/cann/ops-nn)

主线仓（CANN 官方 ops-transformer / ops-nn 仓库）的迁移流程暂未支持。

如需将算子迁移到主线仓，请参考对应仓库的现有算子结构手动迁移，或等待后续版本更新。

<!-- TODO: 补充主线仓迁移流程，包括：
  - 主线仓目录结构约定
  - 与 omni-ops 的差异点（编译系统、注册方式等）
  - 迁移步骤 & 代码模板
-->

---

## References

- [Code Templates (omni-ops)](references/omni-ops/code-templates.md): 自定义算子仓生产框架代码模板
- [Code Templates (mainline)](references/mainline/code-templates.md): 主线仓代码模板（待补充）
