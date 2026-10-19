"""UT: harness 模板的 dtype 处理 —— bf16 不能被当 fp16。

DevkitBackend（全局 debug fallback）走 harness 的 fallback path，用 ``gen_input``
生成输入。numpy 无原生 bf16，``gen_input`` 历史上 ``astype(np.float16)`` 把 bf16
截断成 fp16，``torch.from_numpy`` 再得到 ``torch.float16``（而非 bfloat16）——
kernel 收到错误 dtype。这是 DevkitBackend 的真实缺陷（在 aggregate_hidden_grad
0 分调查中定位到 ``_harness_template.py:150/199/428``）。

修复契约（本文件守护）：
  1. numpy 用 float32 作 bf16 的中间表示（无损承载；e3m5/fp8 同理）；
  2. fallback path 的 ``torch.from_numpy`` 后 ``.to(目标 torch dtype)``，确保
     bf16 经 float32 numpy 后 cast 回 ``torch.bfloat16``。
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

HARNESS_SRC = (
    Path(__file__).resolve().parents[3]
    / "src/ascendc_devkit/adapters/npu/_harness_template.py"
)


def _read_harness() -> str:
    return HARNESS_SRC.read_text(encoding="utf-8")


def test_np_dict_uses_float32_intermediate_for_bf16() -> None:
    """bf16 的 numpy 中间表示必须是 float32，不是 float16。

    numpy 无原生 bf16；float32 是能无损承载 bf16 的最窄 numpy 浮点类型。
    用 float16 会改变值（bf16 与 fp16 的指数位/尾数位布局不同，直接 astype
    是重解释+截断，不是升精度）。e3m5/fp8 等未来低精度浮点同理走 float32。
    """
    src = _read_harness()
    m = re.search(r"_NP\s*=\s*(\{[^\n]+\})", src)
    assert m, "_NP 映射表未找到"
    ns: dict = {"np": np}
    exec("_NP = " + m.group(1), ns)
    assert ns["_NP"]["bf16"] == np.float32, (
        "bf16 numpy 中间表示必须是 np.float32（当前被当 fp16，会截断/重解释值）"
    )


def test_np_table_covers_int16_uint8() -> None:
    """_NP 表必须覆盖本批算子出现的全部 dtype：int16/uint8（gcd/transpose、
    masked_scale/strided_slice/top_k/unique）此前缺键 → FALLBACK 路径生成时
    KeyError 或兜底 fp16 错 dtype。"""
    src = _read_harness()
    m = re.search(r"_NP\s*=\s*(\{[^\n]+\})", src)
    assert m, "_NP 映射表未找到"
    ns: dict = {"np": np}
    exec("_NP = " + m.group(1), ns)
    assert ns["_NP"]["int16"] == np.int16
    assert ns["_NP"]["uint8"] == np.uint8


def test_np_table_covers_full_name_float_dtypes() -> None:
    """_NP 表必须覆盖 test-design CSV 产出的全名浮点 dtype（float16/float32/
    bfloat16）——merge_test_cases.py 契约写全名，缺键会让 ``_NP.get`` 落
    np.float16 兜底：float32 用例数据被 fp16 量化、bfloat16 用例数据非 float32
    载体（与 bf16 契约矛盾），大数值（>65504）直接溢出。float16→np.float16，
    float32/bfloat16→np.float32 载体（numpy 无原生 bf16，float32 无损承载）。"""
    src = _read_harness()
    m = re.search(r"_NP\s*=\s*(\{[^\n]+\})", src)
    assert m, "_NP 映射表未找到"
    ns: dict = {"np": np}
    exec("_NP = " + m.group(1), ns)
    assert ns["_NP"]["float16"] == np.float16
    assert ns["_NP"]["float32"] == np.float32
    assert ns["_NP"]["bfloat16"] == np.float32, (
        "bfloat16 全名缺键 → FALLBACK 生成走 np.float16 兜底，"
        "数据被 fp16 量化/溢出，违 bf16 float32 载体契约"
    )


def test_cann_path_count_mismatch_fails_explicitly() -> None:
    """unique 假通过根因①：compare_tensors 输出数量不匹配（passed=False +
    空 output_results）时，harness 必须产出显式失败 comparison（passed=False
    + error_msg 透传），不得丢弃 passed 让下游空真通过。"""
    src = _read_harness()
    assert re.search(
        r"getattr\(_cr, 'passed', True\) is False and not \(_cr\.output_results or \[\]\)",
        src,
    ), "CANN-BENCH PATH 未检测 compare_tensors 的 count-mismatch 失败信号"
    assert re.search(
        r"'error_msg': getattr\(_cr, 'error_msg', ''\)", src,
    ), "synthetic 失败条目未透传 compare_tensors 的 error_msg"
    assert re.search(
        r"'passed': False,\n\s+'mismatch_count': 0", src,
    ), "synthetic 失败条目必须是 passed=False"
    assert re.search(
        r"_k0_dtype = \(str\(_k_first\.dtype\)\.replace\('torch\.', ''\)\s*\n\s+if _k_first is not None else ''\)",
        src,
    ), "synthetic 失败条目取 dtype 必须防空列表/None 输出（kernel 0 输出或 optional 占位时崩）"
    assert re.search(
        r"output_results\(%d\) != kernel outputs\(%d\)",
        src,
    ), "output_results/kernel 输出数对齐守护缺失（枚举索引错位时无留痕）"


def test_fallback_path_casts_numpy_to_target_torch_dtype() -> None:
    """fallback path 的 torch.from_numpy 后必须 .to(目标 torch dtype)。

    bf16 经 float32 numpy 中间表示后，必须 cast 回 torch.bfloat16；否则
    kernel 收到 torch.float16。判据：fallback path 出现带 .to 的 from_numpy。
    """
    src = _read_harness()
    assert re.search(r"torch\.from_numpy\([^)]*\)\.to\(", src), (
        "fallback path 未把 numpy intermediate cast 到目标 torch dtype"
        "（bf16 经 float32 numpy 后会变成 fp16，而非 bfloat16）"
    )
