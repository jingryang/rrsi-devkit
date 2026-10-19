"""step-105 — 算子属性类型语法（递归文法 + 翻译点）UT。

钉住 docs/plan/op-attr-type-system/（L3 决策①）：
- 规范记法 = Python typing 拼写（base | list[T] | T1|T2，任意嵌套深度）；
- ``check_attr_value`` 单一递归检查器（JSON Schema 结构语义：array+items /
  anyOf=union / null=可空）；
- ``_canonical_attr_type`` 翻译点覆盖语料全部拼写形态（cann-bench proto.yaml
  全量回放 1112 例中 1107 例可翻；透传 5 例=语义不完整/真引用类型——响亮暴露
  正是设计行为）；
- 固定长度经 ``AttrSpec.length`` 承载（规范类型串不带 N——JSON 可序列化）。

回归锚（20260829 interpolate 事故，docs/issue-analysis/
20260829-interpolate-pd-contract-attr-type-gap.md）：
- 嵌套值 [[1,1]] 对契约 list[int] 必拒（旧枚举表的 fallback 反而放过标量列表、
  拒绝嵌套——两头都错）；
- 嵌套契约 list[list[int]] 与嵌套值互认。
"""
from __future__ import annotations

import pytest

from ascendc_devkit.domain.operator import (
    CANON_ATTR_CHECKERS,
    AttrSpec,
    canonical_attr_type,
    check_attr_value,
    is_grammar_type,
)


# ── 递归检查器：文法语义 ────────────────────────────────────────────────────


class TestCheckAttrValue:
    def test_leaf_types(self):
        assert check_attr_value(3, "int")
        assert not check_attr_value(True, "int")      # bool 不是 int（语义区分）
        assert not check_attr_value(3.0, "int")
        assert check_attr_value(3.5, "float") and check_attr_value(3, "float")
        assert not check_attr_value(True, "float")
        assert check_attr_value("a", "str") and not check_attr_value(3, "str")
        assert check_attr_value(True, "bool") and not check_attr_value(1, "bool")

    def test_list_any_depth(self):
        assert check_attr_value([1, 2], "list[int]")
        assert not check_attr_value([1, True], "list[int]")
        assert check_attr_value([[1, 1], [2, 2]], "list[list[int]]")
        assert not check_attr_value([1, 1], "list[list[int]]")       # 扁平喂嵌套
        assert check_attr_value([[1], [2, 3], []], "list[list[int]]")  # 变长内层
        assert check_attr_value((1, 2), "list[int]")                  # tuple 值语义
        assert not check_attr_value("ab", "list[int]")

    def test_union_and_nullable(self):
        assert check_attr_value(3, "int|float") and check_attr_value(3.5, "int|float")
        # null 只在显式 union 成员时合法（JSON Schema null 语义）
        assert check_attr_value(None, "int|None")
        assert check_attr_value(None, "list[int]|None")
        assert not check_attr_value(None, "int")
        assert check_attr_value([1, 2], "list[int]|None")

    def test_nongrammar_label_falls_back_false(self):
        """透传标签（Tensor/enum）→ False，调用方走泛化 fallback（遗留行为）。"""
        assert not check_attr_value(5, "Tensor")
        assert not check_attr_value(5, "")
        assert not check_attr_value(5, "RoundMode")

    def test_empty_and_edge(self):
        assert check_attr_value([], "list[int]")            # 空列表是合法 list
        assert check_attr_value([], "list[list[int]]")
        assert not check_attr_value(None, None)


# ── 翻译点：语料拼写全谱 ────────────────────────────────────────────────────


class TestCanonicalAttrType:
    @pytest.mark.parametrize("raw,canon", [
        # 基础类型 + 大小写/C++ 后缀
        ("int", "int"), ("Int", "int"), ("INT", "int"), ("int64", "int"),
        ("int64_t", "int"), ("uint8", "int"), ("long", "int"),
        ("float", "float"), ("double", "float"), ("float32", "float"), ("float64", "float"),
        ("bool", "bool"), ("BOOL", "bool"), ("str", "str"), ("String", "str"),
        ("string", "str"),
        # 一维列表：ATen/Python/驼峰各形态
        ("int[]", "list[int]"), ("List[int]", "list[int]"), ("ListInt", "list[int]"),
        ("listInt", "list[int]"), ("IntList", "list[int]"), ("ListInt64", "list[int]"),
        ("ListFloat", "list[float]"), ("FloatList", "list[float]"), ("float[]", "list[float]"),
        ("List[bool]", "list[bool]"), ("bool[]", "list[bool]"),
        # 嵌套（事故核心形态）
        ("int[][]", "list[list[int]]"), ("List[List[int]]", "list[list[int]]"),
        ("list[list[int]]", "list[list[int]]"), ("ListListInt", "list[list[int]]"),
        # 语义别名（ATen 词汇表）
        ("Scalar", "int|float"), ("SymInt", "int"), ("ScalarType", "str"),
        ("Dimname", "str"), ("MemoryFormat", "str"),
        # tuple 值语义 → list
        ("tuple[int, int, int]", "list[int]"),
        # 联合（Python 604 / ATen 惯例）
        ("int | float", "int|float"), ("int | int[4]", "int|list[int]"),
        ("SymInt[3] | int", "list[int]|int"),
        ("int | int[2] | (int|None)[2]", "int|list[int]|list[int]|None"),
    ])
    def test_translation(self, raw, canon):
        got, _len = canonical_attr_type(raw)
        assert got == canon, f"{raw!r} → {got!r}, 期望 {canon!r}"

    @pytest.mark.parametrize("raw,canon", [
        ("float?", "float|None"), ("int?", "int|None"),
        ("float[]?", "list[float]|None"), ("int[]?", "list[int]|None"),
        ("List[int] | None", "list[int]|None"),
        ("Optional[int]", "int|None"),
        ("Optional[List[int]]", "list[int]|None"),
        ("ScalarType?", "str|None"),
    ])
    def test_nullable_forms(self, raw, canon):
        got, _len = canonical_attr_type(raw)
        assert got == canon

    def test_prose_suffix_tolerated(self):
        """语料真实形态：`int? (可选 int64，默认 None)` ——? 后的括号说明被剥。"""
        got, _ = canonical_attr_type("int? (可选 int64，默认 None)")
        assert got == "int|None"

    @pytest.mark.parametrize("raw,canon,length", [
        ("int[2]", "list[int]", 2), ("int64[5]", "list[int]", 5),
        ("bool[3]", "list[bool]", 3), ("SymInt[1]", "list[int]", 1),
    ])
    def test_fixed_length_extracted(self, raw, canon, length):
        got, ln = canonical_attr_type(raw)
        assert got == canon and ln == length

    def test_union_branch_length_dropped(self):
        """联合成员带定长：长度对整 attr 无意义 → 摘除（声明 list[T] 才有定长）。"""
        got, ln = canonical_attr_type("int | int[4]")
        assert got == "int|list[int]" and ln is None

    @pytest.mark.parametrize("raw", ["Tensor", "Tensor?", "RoundMode", "list",
                                     "list[int]（长度 3；也接受单 int，此时三个空间维相同）"])
    def test_passthrough_labels(self, raw):
        """不可翻译标签原样透传（下游 requirement 自检响亮报错，绝不静默改写）。"""
        got, _ = canonical_attr_type(raw)
        assert got == raw.strip() or got == raw.rstrip("?").strip() + "?" \
            or not is_grammar_type(got)

    def test_empty(self):
        assert canonical_attr_type("") == ("", None)


# ── AttrSpec 集成 ──────────────────────────────────────────────────────────


class TestAttrSpecGrammar:
    def test_nested_declared_and_checked(self):
        """事故正向锚：嵌套声明成为可能（旧枚举表构造性不可能）。"""
        a = AttrSpec(name="pools", type="int[][]")
        assert a.type == "list[list[int]]" and a.length is None

    def test_fixed_length_rides_attrspec(self):
        a = AttrSpec(name="k", type="int[2]")
        assert a.type == "list[int]" and a.length == 2

    def test_idempotent_canonical(self):
        for c in CANON_ATTR_CHECKERS:
            assert AttrSpec(name="x", type=c).type == c

    def test_passthrough_warns(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="ascendc_devkit.domain.operator"):
            AttrSpec(name="x", type="Tensor")
        assert any("not a recognized type-grammar form" in r.getMessage()
                   for r in caplog.records)

    def test_translatable_no_warn(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="ascendc_devkit.domain.operator"):
            AttrSpec(name="x", type="int[][]")
            AttrSpec(name="x", type="ListInt")
            AttrSpec(name="x", type="Scalar")
        assert not any("not a recognized type-grammar form" in r.getMessage()
                       for r in caplog.records)


# ── is_grammar_type：结构判定与 check_attr_value 的分派镜像 ────────────────


class TestIsGrammarType:
    @pytest.mark.parametrize("t", ["int", "float", "str", "bool",
                                   "list[int]", "list[list[int]]",
                                   "list[list[list[float]]]",
                                   "int|float", "int|None", "list[int]|None",
                                   "int|list[int]|list[int]|None"])
    def test_grammar(self, t):
        assert is_grammar_type(t)

    @pytest.mark.parametrize("t", ["Tensor", "RoundMode", "list", "", "int[]extra",
                                   "list[Tensor]"])
    def test_not_grammar(self, t):
        assert not is_grammar_type(t)


# ── 递归界：病态标签判不可翻译，不烧递归栈（走既有 WARN/透传路径）────────────


class TestGrammarBounds:
    """深度>16 或标签长>256 → 文法 False / 翻译 ValueError → 透传（AttrSpec
    构造期 WARN 接管）。真实语料最深 2 层、最长 ~60 字符，界只是防御病态输入。"""

    def test_list_depth_beyond_bound_not_grammar(self):
        deep = "int"
        for _ in range(17):
            deep = f"list[{deep}]"
        assert not is_grammar_type(deep)
        v: object = 1
        for _ in range(17):
            v = [v]
        assert not check_attr_value(v, deep)  # 界内判 False，非递归爆栈

    def test_list_depth_at_bound_still_grammar(self):
        ok = "int"
        for _ in range(16):
            ok = f"list[{ok}]"
        assert is_grammar_type(ok)

    def test_overlong_label_not_grammar(self):
        assert not is_grammar_type("a" * 257)
        assert not check_attr_value(1, "a" * 257)

    def test_overlong_label_translates_to_passthrough(self):
        """超长标签经翻译点原样透传（不翻译、不爆栈）——既有 WARN 路径接管。"""
        raw = "int|" + "x" * 300
        got, _ = canonical_attr_type(raw)
        assert got == raw.strip()

    def test_deep_bracket_tail_bounded_no_blowup(self):
        """``int[][]…``（>16 层）：尾部 [] 由翻译点算术计数（单次正则收尽），
        不递归爆栈；产出的 20 层 canon 判非文法 → AttrSpec 既有 WARN 路径接管。"""
        raw = "int" + "[]" * 20
        got, _ = canonical_attr_type(raw)
        assert got.startswith("list[list[")
        assert not is_grammar_type(got)

    def test_deep_fixed_length_tail_translates_to_passthrough(self):
        """``int[2][2]…``（>16 层）逐层递归翻译——超深度界 → ValueError → 原样
        透传（不产出 20 层嵌套 canon）。"""
        raw = "int" + "[2]" * 20
        got, _ = canonical_attr_type(raw)
        assert got == raw


# ── 事故回归锚（20260829 interpolate PD-CONTRACT）──────────────────────────


class TestIncidentAnchors:
    """golden 语义 pools=list[[int]]（嵌套），用例值 [[1,1]]。

    旧系统：requirement 被迫压平声明 list[int] + 用例嵌套值 → PD-CONTRACT halt。
    新系统：嵌套声明构造性可能 + 嵌套值互认。
    """

    GOLDEN_STYLE_LABELS = ["int[][]", "List[List[int]]", "list[list[int]]"]

    @pytest.mark.parametrize("label", GOLDEN_STYLE_LABELS)
    def test_nested_contract_accepts_nested_value(self, label):
        a = AttrSpec(name="pools", type=label)
        assert check_attr_value([[1, 1], [2, 2]], a.type)
        assert check_attr_value([[1, 1]], a.type)

    def test_flat_contract_rejects_nested_value(self):
        """压平声明 + 嵌套值 = 事故形态，必须仍被确定性拒绝（忠实消费，不代偿）。"""
        assert not check_attr_value([[1, 1]], "list[int]")

    def test_nested_contract_rejects_flat_value(self):
        assert not check_attr_value([1, 1, 2, 2], "list[list[int]]")
