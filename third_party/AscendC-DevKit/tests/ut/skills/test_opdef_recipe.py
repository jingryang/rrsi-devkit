"""OpDef 渲染 recipe 完整性守护（§3 UT）。

recipe（`OpDef渲染规格映射.md`）是治 OpDef 幻觉的确定性解药——docgen/codegen 渲染 OpDef 前必读。
本测试不跑 LLM，只静态断言 recipe 文件**包含** canonical 映射 + 虚构-API 教育性警示 + soc↔chip.py
同步，防回归（有人删了某张映射表或漏了警示，幻觉会复发）。真正的"渲染正确"由 heavy_llm ST +
就地回验覆盖。
"""

from pathlib import Path

import pytest

RECIPE = (Path(__file__).resolve().parents[3]
          / ".claude/skills/ascendc-op-design-shared/references/OpDef渲染规格映射.md")


@pytest.fixture(scope="module")
def text():
    assert RECIPE.exists(), f"recipe 缺失：{RECIPE}"
    return RECIPE.read_text(encoding="utf-8")


@pytest.mark.parametrize("needle", [
    # builder 链 canonical 形态
    "this->Input(",
    ".ParamType(REQUIRED)",
    ".DataType({ge::DT_FLOAT, ge::DT_FLOAT16, ge::DT_BF16})",
    ".Format({ge::FORMAT_ND",
    ".UnknownShapeFormat(",
    ".AutoContiguous()",
    # Attr setter 族
    "this->Attr(\"base\").Float(-1.0f)",
    ".Int(",
    ".Bool(",
    # AICore + 注册
    "OpAICoreConfig",
    "this->AICore().AddConfig(",
    "OP_ADD(",
    "#include \"register/op_def_registry.h\"",
    "explicit Exp(const char *name) : OpDef(name)",
    # chip 翻译
    "to_soc_version",
    "ascend910b",
    "ascend910_93",
    "ascend950",
    # param_type 三值
    "OPTIONAL",
    "DYNAMIC",
])
def test_recipe_contains_canonical_tokens(text, needle):
    assert needle in text, f"recipe 缺 canonical 项：{needle!r}（渲染将无所依据）"


@pytest.mark.parametrize("fiction", [
    "desc.Mut",            # 虚构的 descriptor API
    "MutatableInputDesc",
    "OutputAttrMapping",   # 虚构的 mapping API
    "ScalarValueType",     # 虚构的 attr 类型枚举
    "<SOC_VERSION",        # 占位串（recipe 里只在"警示"语境出现）
])
def test_recipe_warns_about_fictional_apis(text, fiction):
    # The hard gate is now POSITIVE-anchored (no blocklist), but the recipe keeps an
    # educational "虚构 API 警示" so the model recognizes the whole FICTION CLASS and
    # doesn't reinvent it. This guards that warning stays in the recipe — if someone
    # deletes it, the model loses the cue and may hallucinate these APIs again.
    assert fiction in text, (
        f"recipe 未把已知虚构 API {fiction!r} 列入教育性警示——模型失去识别线索，幻觉易复发")


def test_recipe_has_dtype_mapping_table(text):
    # 核心映射表：fp16/fp32/bf16/int32/int64 必须都映射到 ge::DT_*。
    for s, enum in [("fp16", "ge::DT_FLOAT16"), ("fp32", "ge::DT_FLOAT"),
                    ("bfloat16", "ge::DT_BF16"), ("int32", "ge::DT_INT32"),
                    ("int64", "ge::DT_INT64")]:
        assert s in text and enum in text, f"dtype 映射缺：{s}→{enum}"


def test_recipe_soc_table_in_sync_with_chip_py(text):
    # §1.9 单一翻译点：recipe 的 soc 字面量表必须覆盖 chip.py::_SOC_VERSION 的全部当前值。
    # 防 chip.py 改了字面量（如 A3 换 soc）而 recipe 表不跟（漂移 → LLM 渲染过期 soc）。
    # authority 是 chip.py；recipe 是其文档镜像。
    from ascendc_devkit.domain.chip import _SOC_VERSION
    for chip, soc in _SOC_VERSION.items():
        assert soc in text, (
            f"recipe 缺 soc 字面量 {soc!r}（chip.py {chip}→{soc}，recipe 漂移）")
        assert chip in text, f"recipe 缺 canonical 芯片码 {chip!r}"


# —— 消费方 wiring 完整性 ——
# recipe 存在还不够；docgen/codegen 必须真的接上它（指 recipe + canonical 形态门 + chip 通道）。
# 这些是静态守护：有人改 skill 漏了指引，渲染会重新失去依据 → 幻觉复发。真实渲染正确性由
# heavy_llm ST + 就地回验覆盖。

SKILLS = Path(__file__).resolve().parents[3] / ".claude/skills"
DOCGEN_SKILL = SKILLS / "ascendc-op-design-docgen/SKILL.md"
DOCGEN_TMPL = SKILLS / "ascendc-op-design-docgen/references/doc_template_v2.0.md"
CODEGEN_SKILL = SKILLS / "ascendc-op-dev-coding/SKILL.md"


def test_docgen_skill_wired_to_recipe():
    t = DOCGEN_SKILL.read_text(encoding="utf-8")
    assert "OpDef渲染规格映射.md" in t, "docgen §2.3 未指向 recipe"
    assert "hw_params.json" in t and "chip_code" in t, "docgen 未从 hw_params.json.chip_code 取 chip"
    assert "to_soc_version" in t, "docgen 未用 to_soc_version 翻译 chip"
    # canonical 形态门 + 虚构-token 拦截
    assert "OpDef canonical 形态" in t
    for bad in ("desc.Mut", "OutputAttrMapping", "ScalarValueType"):
        assert bad in t, f"docgen 自检未列虚构 token {bad!r}"


def test_docgen_template_points_to_recipe():
    t = DOCGEN_TMPL.read_text(encoding="utf-8")
    assert "OpDef渲染规格映射.md" in t, "doc 模板 §2.3 未指向 recipe"


def test_codegen_skill_wired_to_recipe():
    t = CODEGEN_SKILL.read_text(encoding="utf-8")
    assert "OpDef渲染规格映射.md" in t, "codegen 未指向 recipe"
    assert "meta.json" in t, "codegen 未从 meta.json 取 chip"

