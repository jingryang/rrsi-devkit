# omni-ops PTA Test Template

## Test Script

```python
#!/usr/bin/env python3
"""Test npu_{op_name} against CPU reference."""
import torch
import torch_npu

def test_npu_{op_name}():
    test_cases = [
        {"shape": (32, 768), "dtype": torch.float16},
        {"shape": (32, 768), "dtype": torch.bfloat16},
        {"shape": (32, 768), "dtype": torch.float32},
    ]
    for case in test_cases:
        shape, dtype = case["shape"], case["dtype"]
        x = torch.randn(shape, dtype=dtype).npu()

        y = torch.ops.custom.npu_{op_name}(x)

        assert y.shape == x.shape, f"shape mismatch: {y.shape} vs {x.shape}"
        assert y.dtype == x.dtype, f"dtype mismatch: {y.dtype} vs {x.dtype}"

        # Verify against CPU reference (replace reference_fn with actual reference)
        y_ref = reference_fn(x.float().cpu()).to(dtype)
        y_npu = y.float().cpu().to(dtype)
        assert torch.allclose(y_npu, y_ref, atol=1e-2, rtol=1e-2), \
            f"max diff: {(y_npu - y_ref).abs().max()}"
        print(f"  shape={shape}, dtype={dtype}: PASS")

if __name__ == "__main__":
    import omni_training_custom_ops  # triggers .so loading
    test_npu_{op_name}()
```

## Run Commands

```bash
# Source environment first
source ${ASCEND_OPP_PATH}/vendors/omni_training_custom_ops/bin/set_env.bash

# Run from OUTSIDE torch_ops_extension/ (prevents circular import)
python3 /absolute/path/to/test/test_npu_{op_name}.py
```

## Notes

- `import omni_training_custom_ops` must come after `import torch_npu`
- Always run test from **outside** `torch_ops_extension/` directory to avoid circular import
- Replace `reference_fn` with the actual CPU reference implementation for the operator
- Test all supported dtypes (fp16, bf16, fp32)
