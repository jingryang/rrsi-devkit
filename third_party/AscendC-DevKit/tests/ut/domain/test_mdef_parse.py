"""UT: domain.mdef_parse — m.def schema 解析原语（§2.5 唯一通路）。

聚焦 ``parse_mdef_op_name``（从 ``m.def`` 提取算子真实 C++ 注册名）—— codegen regbase
fallback 用它构造 ``callable_target.symbol``，避免盲拼 op_name（注册名常为避 torch 内置名
冲突的 ``npu_<name>``，如 exp → npu_exp）。并回归从 cannbench_adapt 迁入的
``parse_mdef_params`` / ``rename_mdef_schema``（搬移后行为不变）。
"""
from __future__ import annotations

from ascendc_devkit.domain.mdef_parse import (
    parse_mdef_op_name,
    parse_mdef_param_types,
    parse_mdef_params,
    rename_mdef_schema,
    validate_schema_against_proto,
    validate_schema_param_order,
)


# —— parse_mdef_op_name（注册名 = `(` 前末尾标识符）——————————————

class TestParseMdefOpName:
    def test_npu_prefixed_name(self):
        # codegen 避 torch 内置 exp 冲突 → 注册成 npu_exp（b4fa39 真实场景）
        src = ('TORCH_LIBRARY_FRAGMENT(cann_bench, m) {\n'
               '    m.def("npu_exp(Tensor x, float base=-1, float scale=1, '
               'float shift=0) -> Tensor");\n}')
        assert parse_mdef_op_name(src) == "npu_exp"

    def test_plain_name_with_attrs(self):
        src = '    m.def("swi_glu(Tensor x, int dim=-1) -> Tensor");'
        assert parse_mdef_op_name(src) == "swi_glu"

    def test_name_equal_op_name_no_suffix(self):
        # 注册名与 op_name 一致的常见情形
        src = '    m.def("add(Tensor x, Tensor y) -> Tensor");'
        assert parse_mdef_op_name(src) == "add"

    def test_no_params(self):
        src = '    m.def("foo() -> Tensor");'
        assert parse_mdef_op_name(src) == "foo"

    def test_takes_first_mdef(self):
        # 一个 plugin 只注册一个算子；多 m.def 时取首个
        src = ('m.def("first(Tensor x) -> Tensor");\n'
               'm.def("second(Tensor y) -> Tensor");')
        assert parse_mdef_op_name(src) == "first"

    def test_no_mdef_returns_none(self):
        assert parse_mdef_op_name("// no m.def here") is None

    def test_empty_source_returns_none(self):
        assert parse_mdef_op_name("") is None

    def test_mdef_without_paren_returns_none(self):
        # 防御：schema 无 `(`（理论不出现，但不该崩）
        assert parse_mdef_op_name('m.def("bogus");') is None

    def test_concatenated_string_literals(self):
        # C++ 相邻字符串字面量拼接（长签名换行书写的惯用法，advance_step_v2 真实场景）
        src = ('TORCH_LIBRARY_FRAGMENT(cann_bench, m) {\n'
               '    m.def("advance_step_v2("\n'
               '          "Tensor input_tokens, Tensor sampled_token_ids, "\n'
               '          "int num_seqs, int num_queries, int block_size"\n'
               '          ") -> (Tensor, Tensor, Tensor, Tensor)");\n}')
        assert parse_mdef_op_name(src) == "advance_step_v2"


# —— parse_mdef_params：tuple 返回类型 + 拼接字面量 ————————————

class TestParseMdefParamsTupleReturn:
    def test_tuple_return_last_param_clean(self):
        # -> (Tensor, Tensor) 的收尾 `)` 不得污染最后一个参数（配对括号定位）
        src = 'm.def("foo(Tensor x, int n) -> (Tensor, Tensor)");'
        assert parse_mdef_params(src) == ["x", "n"]

    def test_concatenated_multi_param_signature(self):
        src = ('m.def("advance_step_v2("\n'
               '      "Tensor input_tokens, Tensor sampled_token_ids, "\n'
               '      "int num_seqs, int block_size"\n'
               '      ") -> (Tensor, Tensor)");')
        assert parse_mdef_params(src) == [
            "input_tokens", "sampled_token_ids", "num_seqs", "block_size"]


# —— 迁移回归：parse_mdef_params（搬移后行为不变）——————————

class TestParseMdefParamsRegression:
    def test_tensor_int(self):
        assert parse_mdef_params(
            'm.def("swi_glu(Tensor x, int dim=-1) -> Tensor");'
        ) == ["x", "dim"]

    def test_tensor_list_float_default(self):
        assert parse_mdef_params(
            'm.def("foreach_norm(Tensor[] x, float p=2.0) -> Tensor[]");'
        ) == ["x", "p"]

    def test_no_params_empty(self):
        assert parse_mdef_params('m.def("foo() -> Tensor");') == []

    def test_no_mdef_empty(self):
        assert parse_mdef_params("// none") == []


# —— 迁移回归：rename_mdef_schema（搬移后行为不变）——————————

class TestRenameMdefSchemaRegression:
    def test_rename_input(self):
        s = 'm.def("swi_glu(Tensor x, int dim=-1) -> Tensor");'
        assert rename_mdef_schema(s, ["x", "dim"], ["input", "dim"]) == \
            'm.def("swi_glu(Tensor input, int dim=-1) -> Tensor");'

    def test_count_mismatch_no_rename(self):
        s = 'm.def("op(Tensor x) -> Tensor");'
        assert rename_mdef_schema(s, ["x"], ["input", "dim"]) == s


# —— parse_mdef_param_types（type+name 序，schema 序校验的基础）——————————

class TestParseMdefParamTypes:
    def test_tensor_scalar_tensor(self):
        # run 20260727-144633-2a1db8 gather 的真实违例 schema
        src = 'm.def("gather(Tensor input, int dim, Tensor index) -> Tensor");'
        assert parse_mdef_param_types(src) == [
            ("Tensor", "input"), ("int", "dim"), ("Tensor", "index"),
        ]

    def test_single_tensor(self):
        assert parse_mdef_param_types('m.def("geglu(Tensor input) -> Tensor");') == [
            ("Tensor", "input"),
        ]

    def test_tensor_list_float_default(self):
        assert parse_mdef_param_types(
            'm.def("foreach_norm(Tensor[] x, float p=2.0) -> Tensor[]");'
        ) == [("Tensor[]", "x"), ("float", "p")]

    def test_const_ref(self):
        assert parse_mdef_param_types(
            'm.def("op(const Tensor& x, int dim) -> Tensor");'
        ) == [("const Tensor&", "x"), ("int", "dim")]

    def test_multi_tensors_then_scalar(self):
        assert parse_mdef_param_types(
            'm.def("op(Tensor a, Tensor b, float eps=1e-6) -> Tensor");'
        ) == [("Tensor", "a"), ("Tensor", "b"), ("float", "eps")]

    def test_no_params_empty(self):
        assert parse_mdef_param_types('m.def("foo() -> Tensor");') == []

    def test_no_mdef_empty(self):
        assert parse_mdef_param_types("// none") == []


# —— validate_schema_param_order（scalar 不得夹在 Tensor 中间）—————————

class TestValidateSchemaParamOrder:
    def test_scalar_between_tensors_is_violation(self):
        """gather(Tensor, int, Tensor) —— dim 夹中间 → 违例 + 确定性诊断。"""
        src = 'm.def("gather(Tensor input, int dim, Tensor index) -> Tensor");'
        ok, detail = validate_schema_param_order(src)
        assert ok is False
        assert detail is not None
        # 诊断含实际 type 序、违例位置、约束说明、修复方向
        assert "['Tensor', 'scalar', 'Tensor']" in detail
        assert "位置 2" in detail
        assert "func(*inputs, **attrs)" in detail

    def test_single_tensor_ok(self):
        assert validate_schema_param_order('m.def("geglu(Tensor input) -> Tensor");') == (True, None)

    def test_tensors_then_scalar_ok(self):
        # 正确序：Tensor... 在前、scalar 在后
        assert validate_schema_param_order(
            'm.def("gather(Tensor input, Tensor index, int dim) -> Tensor");'
        ) == (True, None)

    def test_tensor_then_scalar_ok(self):
        assert validate_schema_param_order(
            'm.def("swi_glu(Tensor x, int dim=-1) -> Tensor");'
        ) == (True, None)

    def test_two_tensors_ok(self):
        assert validate_schema_param_order(
            'm.def("add(Tensor x, Tensor y) -> Tensor");'
        ) == (True, None)

    def test_tensor_list_then_scalar_ok(self):
        assert validate_schema_param_order(
            'm.def("foreach_norm(Tensor[] x, float p=2.0) -> Tensor[]");'
        ) == (True, None)

    def test_no_params_ok(self):
        assert validate_schema_param_order('m.def("foo() -> Tensor");') == (True, None)

    def test_no_mdef_ok(self):
        # 无 m.def → 平凡合法（不校验）
        assert validate_schema_param_order("// no m.def") == (True, None)

    def test_leading_scalar_is_violation(self):
        """int 在最前（Tensor 之前）也是违例：scalar 后出现 Tensor。"""
        src = 'm.def("op(int dim, Tensor x) -> Tensor");'
        ok, detail = validate_schema_param_order(src)
        assert ok is False
        assert detail is not None
        assert "位置 1" in detail


# —— 裸 proto.yaml schema 字符串解析（parser 兼容两种形态）—————————

class TestParseBareProtoSchema:
    """proto.yaml ``operator.schema`` 是裸字符串（无 ``m.def`` 包裹），与 ``m.def`` schema
    同构，复用同一 parser（不经 agent 重新表达）。"""

    def test_parse_bare_param_types(self):
        proto = "gather(Tensor x, Tensor index, int dim=0) -> Tensor y"
        assert parse_mdef_param_types(proto) == [
            ("Tensor", "x"), ("Tensor", "index"), ("int", "dim"),
        ]

    def test_parse_bare_param_names(self):
        proto = "gather(Tensor x, Tensor index, int dim=0) -> Tensor y"
        assert parse_mdef_params(proto) == ["x", "index", "dim"]

    def test_parse_softmax_proto(self):
        assert parse_mdef_params("softmax(Tensor x, int dim=-1) -> Tensor y") == ["x", "dim"]


# —— 多输出（tuple 返回类型）schema：返回类型括号不得污染参数体 ————————
# run 20260803-143122-30031b dynamic_quant 根因：parse 用 rfind(')') 取「最后」')'
# 当参数体右界，对 `(Tensor x) -> (Tensor y, Tensor scale)` 把返回类型元组的 ')'
# 当成参数体结束 → 参数体变成垃圾 `Tensor x) -> (Tensor y, Tensor scale` →
# CannbenchAdapter 注入非法 wrapper（def dynamic_quant(Tensor x) -> (...)）→
# cann_bench/__init__.py SyntaxError → import 崩 → eval 全 0 分。
# 修复：用「首个 ( 的配对 )」（括号深度匹配），而非 rfind。

class TestMultiOutputTupleReturn:
    def test_params_bare_proto(self):
        s = "dynamic_quant(Tensor x) -> (Tensor y, Tensor scale)"
        assert parse_mdef_params(s) == ["x"]

    def test_params_mdef(self):
        s = 'm.def("dynamic_quant(Tensor x) -> (Tensor y, Tensor scale)");'
        assert parse_mdef_params(s) == ["x"]

    def test_param_types_bare_proto(self):
        s = "dynamic_quant(Tensor x) -> (Tensor y, Tensor scale)"
        assert parse_mdef_param_types(s) == [("Tensor", "x")]

    def test_param_types_mdef(self):
        s = 'm.def("dynamic_quant(Tensor x) -> (Tensor y, Tensor scale)");'
        assert parse_mdef_param_types(s) == [("Tensor", "x")]

    def test_rename_preserves_return_tuple(self):
        # rename 只改输入参数名，返回类型元组原样保留
        s = 'm.def("dynamic_quant(Tensor x) -> (Tensor y, Tensor scale)");'
        assert rename_mdef_schema(s, ["x"], ["input"]) == \
            'm.def("dynamic_quant(Tensor input) -> (Tensor y, Tensor scale)");'

    def test_multi_input_multi_output(self):
        s = "op(Tensor a, Tensor b) -> (Tensor y, Tensor z)"
        assert parse_mdef_params(s) == ["a", "b"]
        assert parse_mdef_param_types(s) == [("Tensor", "a"), ("Tensor", "b")]

    def test_multi_input_scalar_attr_then_tuple_return(self):
        s = "op(Tensor x, int dim=0) -> (Tensor y, Tensor scale)"
        assert parse_mdef_params(s) == ["x", "dim"]
        assert parse_mdef_param_types(s) == [("Tensor", "x"), ("int", "dim")]

    def test_validate_against_proto_multi_output_ok(self):
        proto = "dynamic_quant(Tensor x) -> (Tensor y, Tensor scale)"
        plugin = 'm.def("dynamic_quant(Tensor x) -> (Tensor y, Tensor scale)");'
        assert validate_schema_against_proto(plugin, proto) == (True, None)


# —— validate_schema_against_proto（plugin m.def vs proto.yaml schema 全等）——

class TestValidateSchemaAgainstProto:
    def test_equal_returns_ok(self):
        proto = "gather(Tensor x, Tensor index, int dim=0) -> Tensor y"
        plugin = 'm.def("gather(Tensor x, Tensor index, int dim) -> Tensor");'
        assert validate_schema_against_proto(plugin, proto) == (True, None)

    def test_order_mismatch_violation(self):
        proto = "gather(Tensor x, Tensor index, int dim=0) -> Tensor y"
        plugin = 'm.def("gather(Tensor x, int dim, Tensor index) -> Tensor");'
        ok, detail = validate_schema_against_proto(plugin, proto)
        assert ok is False
        assert detail is not None
        assert "proto.yaml operator.schema" in detail
        assert "plugin m.def" in detail

    def test_name_mismatch_violation(self):
        """名字错（input vs proto 的 x）也检出 —— 纯结构校验抓不了，proto 全等校验能抓。"""
        proto = "gather(Tensor x, Tensor index, int dim=0) -> Tensor y"
        plugin = 'm.def("gather(Tensor input, Tensor index, int dim) -> Tensor");'
        ok, detail = validate_schema_against_proto(plugin, proto)
        assert ok is False
        # detail 显示 proto（权威名 x）vs plugin（套 torch 名 input）的名字差异
        assert "Tensor input" in detail
        assert "Tensor x, Tensor index" in detail

    def test_no_proto_degrades_to_structural(self):
        """proto_schema None → 退化为结构校验（只抓 scalar 夹 Tensor 中间）。"""
        plugin = 'm.def("gather(Tensor input, int dim, Tensor index) -> Tensor");'
        ok, detail = validate_schema_against_proto(plugin, None)
        assert ok is False
        assert "scalar" in detail

    def test_no_proto_legal_order_ok(self):
        plugin = 'm.def("gather(Tensor input, Tensor index, int dim) -> Tensor");'
        assert validate_schema_against_proto(plugin, None) == (True, None)


    def test_rename_alias_actually_changes_source(self):
        src = 'm.def("op(Tensor(a!) self) -> Tensor");'
        assert rename_mdef_schema(src, ["self"], ["out"]) == \
            'm.def("op(Tensor(a!) out) -> Tensor");'


# —— parse_mdef_return_signature / plugin_impl_return_kinds（方案 A 解析原语）——————

from ascendc_devkit.domain.mdef_parse import (
    parse_mdef_return_signature,
    plugin_impl_return_kinds,
)


class TestParseMdefReturnSignature:
    def test_single_tensor(self):
        assert parse_mdef_return_signature(
            'm.def("softmax(Tensor x, int dim) -> Tensor")') == ["Tensor"]

    def test_single_optional(self):
        assert parse_mdef_return_signature(
            'm.def("op(Tensor x) -> Tensor?")') == ["Tensor?"]

    def test_var_length(self):
        assert parse_mdef_return_signature(
            'm.def("foreach_norm(Tensor[] x, float p=2.0) -> Tensor[]")') == ["Tensor[]"]

    def test_tuple_of_two(self):
        assert parse_mdef_return_signature(
            'm.def("op(Tensor x) -> (Tensor, Tensor)")') == ["Tensor", "Tensor"]

    def test_tuple_with_optional(self):
        assert parse_mdef_return_signature(
            'm.def("unique(Tensor x) -> (Tensor, Tensor?)")') == ["Tensor", "Tensor?"]

    def test_single_in_parens(self):
        # `-> (Tensor)` 单元素元组按单返回处理
        assert parse_mdef_return_signature(
            'm.def("op(Tensor x) -> (Tensor)")') == ["Tensor"]

    def test_none_return(self):
        assert parse_mdef_return_signature(
            'm.def("op(Tensor x) -> ()")') == []
        assert parse_mdef_return_signature(
            'm.def("op(Tensor x) -> None")') == []

    def test_concatenated_literal_returns(self):
        # advance_step_v2 长签名拼接形式（4 返回元组）
        src = ('m.def("advance_step_v2("\n'
               '          "Tensor input_tokens, Tensor sampled_token_ids, "\n'
               '          ") -> (Tensor, Tensor, Tensor, Tensor)");')
        assert parse_mdef_return_signature(src) == \
            ["Tensor", "Tensor", "Tensor", "Tensor"]

    def test_no_return_arrow(self):
        assert parse_mdef_return_signature('m.def("bogus");') is None
        assert parse_mdef_return_signature("") is None

    def test_alias_annotation_stripped(self):
        # 返回侧 alias 标注 Tensor(a) 剥掉，只留 Tensor 标记
        assert parse_mdef_return_signature(
            'm.def("op(Tensor(a!) x) -> (Tensor(a), Tensor)")') == ["Tensor", "Tensor"]


class TestPluginImplReturnKinds:
    def test_vector_impl(self):
        # unique 20260808 根因形态：m.def 声明元组但实现返回 vector
        src = ('static std::vector<torch::Tensor> unique_npu('
               'const torch::Tensor& x, bool returnInverse) { return {}; }\n'
               'TORCH_LIBRARY_IMPL(cann_bench, PrivateUse1, m) { '
               'm.impl("unique", unique_npu); }')
        assert plugin_impl_return_kinds(src) == ["vector"]

    def test_single_tensor_impl(self):
        src = ('static torch::Tensor softmax_npu(const torch::Tensor& x, '
               'int64_t dim) { return x; }\n'
               'TORCH_LIBRARY_IMPL(cann_bench, PrivateUse1, m) { '
               'm.impl("softmax", softmax_npu); }')
        assert plugin_impl_return_kinds(src) == ["tensor"]

    def test_tuple_impl(self):
        src = ('static std::tuple<torch::Tensor, torch::Tensor> '
               'apply_rotary_pos_emb_npu(const torch::Tensor& x) { return {}; }\n'
               'TORCH_LIBRARY_IMPL(cann_bench, PrivateUse1, m) { '
               'm.impl("apply_rotary_pos_emb", apply_rotary_pos_emb_npu); }')
        assert plugin_impl_return_kinds(src) == ["tuple2"]

    def test_tuple_with_optional_impl(self):
        # namespace 归一：at::Tensor / c10::optional 都要被识别
        src = ('static std::tuple<at::Tensor, std::optional<at::Tensor>> '
               'unique_npu(const at::Tensor& x) { return {}; }\n'
               'TORCH_LIBRARY_IMPL(cann_bench, PrivateUse1, m) { '
               'm.impl("unique", unique_npu); }')
        assert plugin_impl_return_kinds(src) == ["tuple2"]

    def test_meta_and_npu_both_classified(self):
        src = ('static std::tuple<at::Tensor, std::optional<at::Tensor>> '
               'unique_meta(const at::Tensor& x) { return {}; }\n'
               'static std::tuple<at::Tensor, std::optional<at::Tensor>> '
               'unique_npu(const at::Tensor& x) { return {}; }\n'
               'TORCH_LIBRARY_IMPL(cann_bench, Meta, m) { '
               'm.impl("unique", unique_meta); }\n'
               'TORCH_LIBRARY_IMPL(cann_bench, PrivateUse1, m) { '
               'm.impl("unique", unique_npu); }')
        assert plugin_impl_return_kinds(src) == ["tuple2", "tuple2"]

    def test_no_impl_returns_none(self):
        assert plugin_impl_return_kinds(
            'TORCH_LIBRARY_FRAGMENT(cann_bench, m) { '
            'm.def("op(Tensor x) -> Tensor"); }') is None

    def test_void_impl(self):
        src = ('static void inplace_op(const torch::Tensor& x) {}\n'
               'TORCH_LIBRARY_IMPL(cann_bench, PrivateUse1, m) { '
               'm.impl("inplace_op", inplace_op); }')
        assert plugin_impl_return_kinds(src) == ["void"]
