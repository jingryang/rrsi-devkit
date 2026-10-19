"""Gate 回归：torch_op 注册契约校验（``_resolve_torch_registration`` /
``_torch_plugin_contract_error``）—— codegen 实际 halt 的接缝。

真实缺陷（batch 20260731-132818 advance_step_v2）：11 形参的长签名被 coder agent
写成 C++ 相邻字符串字面量跨行拼接（合法、语义等价单串），旧 ``m.def`` 正则只认单字面量
→ ``_resolve_torch_registration`` 返回 None → 契约校验误报"无有效注册" → ``fail_strategy=halt``
停整条 pipeline。产物其实正确（smoke 已过）。

底层解析原语的回归在 ``tests/ut/domain/test_mdef_parse.py``；本文件钉住 gate 层：拼接签名
必须判为"契约通过"（不 halt），而真正缺失/半注册仍必须报错。纯字符串逻辑、无环境依赖 → UT。
"""
from __future__ import annotations

from ascendc_devkit.orchestration.stages.codegen import CodegenStage
from ascendc_devkit.orchestration.kernel.state import State


def _resolve(plugin_src: str):
    stage = CodegenStage.__new__(CodegenStage)
    artifacts = {"op_plugin/op_plugin.cpp": plugin_src}
    return stage._resolve_torch_registration(State(mode="new"), artifacts)


def _contract_error(plugin_src: str):
    stage = CodegenStage.__new__(CodegenStage)
    artifacts = {"op_plugin/op_plugin.cpp": plugin_src}
    return stage._torch_plugin_contract_error(State(mode="new"), artifacts)


# —— 真实缺陷：拼接字面量长签名必须判为契约通过（不 halt）——————————————

_CONCAT_PLUGIN = (
    'TORCH_LIBRARY_FRAGMENT(cann_bench, m) {\n'
    '    m.def("advance_step_v2("\n'
    '          "Tensor input_tokens, Tensor sampled_token_ids, "\n'
    '          "Tensor input_positions, Tensor seq_lens, Tensor slot_mapping, "\n'
    '          "Tensor block_tables, Tensor spec_token, Tensor accepted_num, "\n'
    '          "int num_seqs, int num_queries, int block_size"\n'
    '          ") -> (Tensor, Tensor, Tensor, Tensor)");\n'
    '}\n')


def test_resolves_concatenated_literal_signature():
    assert _resolve(_CONCAT_PLUGIN) == ("cann_bench", "advance_step_v2")


def test_no_contract_error_on_concatenated_signature():
    # advance_step_v2 真实 halt 的接缝：契约必须放行，不产生 ErrorFeedback。
    assert _contract_error(_CONCAT_PLUGIN) is None


# —— 单字面量常规注册（回归）————————————————————————————

def test_resolves_single_literal_signature():
    src = ('TORCH_LIBRARY_FRAGMENT(cann_bench, m) {\n'
           '    m.def("add(Tensor x, Tensor y) -> Tensor");\n}')
    assert _resolve(src) == ("cann_bench", "add")
    assert _contract_error(src) is None


def test_resolves_mainline_namespace():
    # 主线仓（ops-nn/ops-transformer）同为 torch_op，namespace 非 cann_bench。
    src = ('TORCH_LIBRARY_FRAGMENT(npu, m) {\n'
           '    m.def("npu_swiglu(Tensor x, int dim=-1) -> Tensor");\n}')
    assert _resolve(src) == ("npu", "npu_swiglu")


# —— 真正的缺失/半注册仍必须报错（不因放宽解析而漏判）————————————

def test_contract_error_when_fragment_missing():
    # 有 m.def 但无 TORCH_LIBRARY_FRAGMENT → 半注册 → 报错。
    src = '    m.def("op(Tensor x) -> Tensor");\n'
    assert _resolve(src) is None
    err = _contract_error(src)
    assert err is not None
    assert err.details["reason"] == "torch_op_plugin_missing_or_invalid"


def test_contract_error_when_mdef_missing():
    # 有 fragment 但无 m.def → 半注册 → 报错。
    src = 'TORCH_LIBRARY_FRAGMENT(cann_bench, m) {\n    // no m.def\n}\n'
    assert _resolve(src) is None
    assert _contract_error(src) is not None


def test_contract_error_when_no_plugin_source():
    stage = CodegenStage.__new__(CodegenStage)
    assert stage._torch_plugin_contract_error(State(mode="new"), {}) is not None
