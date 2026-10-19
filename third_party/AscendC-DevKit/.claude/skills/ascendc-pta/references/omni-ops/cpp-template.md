# omni-ops C++ Binding Template

## Pattern A: Simple forward-only op (no autograd)

```cpp
/**
 * Copyright (c) 2026 Huawei Technologies Co., Ltd.
 * Licensed under CANN Open Software License Agreement Version 2.0.
 */

#include <torch/library.h>
#include "../../../../csrc_base/ops_common.h"

namespace custom {
using namespace at_npu::native;

// NPU forward implementation
// Adjust signature to match actual inputs/outputs; pre-allocate all output tensors
// before calling EXEC_NPU_CMD_V1 — the NPU cmd writes into them, it does not allocate.
at::Tensor npu_{op_name}_npu(const at::Tensor& x, const at::Tensor& weight)
{
    at::Tensor y = at::empty_like(x);
    EXEC_NPU_CMD_V1(aclnn{OpName}, x, weight, y);
    return y;
}

// Meta implementation: shape/dtype inference only, no NPU execution.
// Return empty tensors of the correct shape/dtype — no device required.
at::Tensor npu_{op_name}_meta(const at::Tensor& x, const at::Tensor& weight)
{
    return at::empty_like(x);
}

// Register NPU dispatch — TORCH_LIBRARY_IMPL must be inside namespace custom {}
TORCH_LIBRARY_IMPL(custom, PrivateUse1, m) {
    m.impl("npu_{op_name}", &custom::npu_{op_name}_npu);
}

// Register Meta dispatch
TORCH_LIBRARY_IMPL(custom, Meta, m) {
    m.impl("npu_{op_name}", &custom::npu_{op_name}_meta);
}

} // namespace custom
```

## Pattern B: Op with multiple outputs

```cpp
std::tuple<at::Tensor, at::Tensor> npu_{op_name}_npu(
    const at::Tensor& x, const at::Tensor& y)
{
    at::Tensor out1 = at::empty_like(x);
    at::Tensor out2 = at::empty_like(y);
    EXEC_NPU_CMD_V1(aclnn{OpName}, x, y, out1, out2);
    return std::make_tuple(out1, out2);
}

// Meta follows the same pattern — return tuple of empty tensors
std::tuple<at::Tensor, at::Tensor> npu_{op_name}_meta(
    const at::Tensor& x, const at::Tensor& y)
{
    return std::make_tuple(at::empty_like(x), at::empty_like(y));
}
```

## Pattern C: Op with autograd

Only add when the op needs a custom backward pass. Requires entries in `function.h` and `PYBIND11_MODULE`. See the mhc reference operators for examples.

## Common signature patterns for `m.def()`

```cpp
// Single input → single output
m.def("npu_{op_name}(Tensor x) -> Tensor");

// Multiple inputs → single output
m.def("npu_{op_name}(Tensor x, Tensor weight) -> Tensor");

// Multiple outputs
m.def("npu_{op_name}(Tensor x) -> (Tensor, Tensor)");

// With scalar args
m.def("npu_{op_name}(Tensor x, float scale=1.0, int? dim=None) -> Tensor");
```

## Key Rules

- aclnn symbol = `aclnn{OpName}` where `{OpName}` is PascalCase from the OpDef class name
- All `TORCH_LIBRARY_IMPL` blocks **must** be inside `namespace custom {}`
- Output tensors must be pre-allocated with `at::empty_like` before `EXEC_NPU_CMD_V1`
- `m.def()` signature must exactly match what Python callers will use
- Add `m.def()` to `TORCH_LIBRARY_FRAGMENT` only, **not** `PYBIND11_MODULE` (unless autograd)
