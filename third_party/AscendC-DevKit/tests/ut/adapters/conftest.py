"""tests/ut/adapters 共享 fixture。

§1.15 单点：跨测试文件复用的结构契约只此一份——此前同一「完整产物结构」
在两个测试文件各内联一份，改一处忘另一处不会报警，标定守护面悄悄分叉。
"""

import pytest


@pytest.fixture
def full_structure():
    """8 张量（3 入 5 出、bfloat16/int32/float32 混合）+ 2 标量 + domain 嵌套的
    完整产物结构（内联合成，标识符通用化；结构形态取自历史事故 run 的真实
    产物——合成小 fixture 只有 1-2 个张量，覆盖不到多张量完整组合的规模面，
    历史丢参缺陷恰发生在该层面）。返回 (requirement, design_spec)。

    消费方：convert 标定（不丢参）与对质标定（不误报）共用同一结构，
    保证两个标定守护的是同一份契约。"""
    tensors_in = [
        {"name": "x_table", "dtype": "bfloat16", "shape": ["*", "D_last"],
         "format": "ND", "param_type": "REQUIRED"},
        {"name": "x_index", "dtype": "int32", "shape": ["*"],
         "format": "ND", "param_type": "REQUIRED"},
        {"name": "x_max", "dtype": "bfloat16", "shape": ["*"],
         "format": "ND", "param_type": "REQUIRED"},
    ]
    tensors_out = [
        {"name": "y_gathered", "dtype": "float32", "shape": ["*"],
         "format": "ND", "param_type": "REQUIRED"},
        {"name": "y_reduced", "dtype": "float32", "shape": ["*"],
         "format": "ND", "param_type": "REQUIRED"},
        {"name": "y_mapped", "dtype": "float32", "shape": ["*", "D_last"],
         "format": "ND", "param_type": "REQUIRED"},
        {"name": "y_offset", "dtype": "int32", "shape": ["*"],
         "format": "ND", "param_type": "REQUIRED"},
        {"name": "y_mask", "dtype": "int32", "shape": ["*"],
         "format": "ND", "param_type": "REQUIRED"},
    ]
    attrs = [
        {"name": "range_start", "type": "int", "default": None},
        {"name": "range_end", "type": "int", "default": None},
    ]
    req = {
        "op_name": "fused_shift_gather_reduce",
        "aclnn_name": "aclnnFusedShiftGatherReduce",
        "op_type": "elementwise_reduce_fusion",
        "mutation_mode": "out_of_place",
        "inputs": tensors_in,
        "outputs": tensors_out,
        "attrs": attrs,
        "golden_alignment": {"status": "pass", "differences": [], "notes": ""},
        "domain": {
            "inputs": [
                {"name": "x_table", "dtypes": ["float32", "bfloat16"],
                 "rank": {"min": 1, "max": 3}},
                {"name": "x_index", "dtypes": ["int32"], "rank": {"min": 1, "max": 3}},
                {"name": "x_max", "dtypes": ["float32", "bfloat16"],
                 "rank": {"min": 1, "max": 3}},
            ],
            "attrs": [
                {"name": "range_start", "domain": {"kind": "scalar_int"}},
                {"name": "range_end", "domain": {"kind": "scalar_int"}},
            ],
        },
    }
    ds = {"op_name": "fused_shift_gather_reduce",
          "inputs": tensors_in, "outputs": tensors_out, "attrs": attrs}
    return req, ds
