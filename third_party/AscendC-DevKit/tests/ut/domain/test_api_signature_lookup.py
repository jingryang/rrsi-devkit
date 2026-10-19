"""UT for domain.api_signature_lookup — codegen 签名失败 → 权威 doc 指路。

守护的不变式（Plan cozy-wiggling-emerson OPT-A）：codegen ascendc-coder 反复用
错误记忆猜 AscendC API 签名（transcript 实测 244 次编译失败，'no matching function
for call to ReduceSum'×10、Sqrt×6、Round×6、ReduceMax×3 等）。本模块从编译 stderr
抽出失败的 API 名（结构信号，非白名单 §1.12），解析其在 ascendc-dev-knowledge 的
权威 doc 路径，供 codegen prompt 注入「逐字使用」确定性指路。

核心契约：
- extract_failing_apis：只抽**签名类**错误里的 API 名（no matching function / no
  member named）；非签名错误（undefined reference / 纯链接器 cannot open）返回 []，
  交回既有处理，不误报。
- resolve_api_docs：rglob 知识库 api_reference_docs 下所有 `{API}.md` 候选（一个
  API 有 高阶/基础 × A3根/A5-SIMD 多变体）。
- select_preferred_doc：按 programming_model（Membase→非SIMD / Regbase→SIMD_API）+
  高阶API 优先 选最可能匹配的；选不出回 None（caller 走 INDEX.md 兜底）。
- build_signature_hint_section：组装 prompt 段；含反锚定条款（逐字用后仍失败 =
  KB↔CANN 不符，停下报告，勿循环同一写法）。
"""

from __future__ import annotations

from pathlib import Path

from ascendc_devkit.capabilities.knowledge import KnowledgeBase
from ascendc_devkit.domain.api_signature_lookup import (
    build_signature_hint_section,
    extract_failing_apis,
    resolve_api_docs,
    select_preferred_doc,
)

# 真实 codegen transcript 抽取的 stderr 片段（multi_add_rms_norm_dynamic_quant）。
STDERR_SIGNATURE = """\
op_kernel/multi_add_rms_norm_dynamic_quant.h:540:10: error: no matching function for call to 'ReduceSum'
op_kernel/multi_add_rms_norm_dynamic_quant.h:548:9: error: no matching function for call to 'Sqrt'
op_kernel/multi_add_rms_norm_dynamic_quant.h:440:9: error: no matching function for call to 'ReduceMax'
op_host/multi_add_rms_norm_dynamic_quant_tiling.cpp:95:20: error: 'class ops::OpAttrDef' has no member named 'FloatAttr'
"""
STDERR_LINKER_ONLY = """\
ld.lld: error: cannot open /home/.../aclnn_launch_example/build/Op_ascend910b/kernel_0/kernel_meta/op_9.o: No such file or directory
"""  # 纯链接器症状，无 clang 签名行 → extract 必须返回 []
STDERR_NONSIGNATURE = """\
undefined reference to 'some_symbol'
error: use of undeclared identifier 'foo'
"""

KB_ROOT = KnowledgeBase().root  # in-repo, self-contained (§1.7)


# —— extract_failing_apis ——


def test_extract_signature_apis_in_order_dedup():
    apis = extract_failing_apis(STDERR_SIGNATURE)
    # 首现顺序、去重（ReduceSum 只一次）。no-member（FloatAttr）也抽为签名类信号
    # （查不到 doc 时 build_signature_hint 走 INDEX.md 兜底，诚实不瞎指）。
    assert apis == ["ReduceSum", "Sqrt", "ReduceMax", "FloatAttr"]


def test_extract_ignores_non_signature_errors():
    assert extract_failing_apis(STDERR_NONSIGNATURE) == []


def test_extract_linker_only_returns_empty():
    # 关键：纯链接器症状（70× 静默失败案例）无 API 名可抽 → []，不误报。
    assert extract_failing_apis(STDERR_LINKER_ONLY) == []


def test_extract_none_and_empty_safe():
    assert extract_failing_apis(None) == []
    assert extract_failing_apis("") == []


def test_extract_dedups_repeated_api():
    stderr = (
        "error: no matching function for call to 'Cast'\n"
        "error: no matching function for call to 'Cast'\n"
        "error: no matching function for call to 'Round'\n"
    )
    assert extract_failing_apis(stderr) == ["Cast", "Round"]


# —— resolve_api_docs ——


def test_resolve_finds_high_level_and_simd_variants():
    docs = resolve_api_docs("ReduceSum", KB_ROOT)
    # ReduceSum 在 KB 里至少有 4 个变体（高阶/基础 × 根/SIMD）。
    assert len(docs) >= 2
    names = [str(d) for d in docs]
    # A3 高阶（codegen 实际用的）必须在内。
    assert any("高阶API" in n and "ReduceSum接口" in n for n in names)


def test_resolve_unknown_api_returns_empty():
    assert resolve_api_docs("NoSuchApi_XYZ", KB_ROOT) == []


# —— select_preferred_doc ——


def test_select_membase_prefers_non_simd_highlevel():
    docs = resolve_api_docs("ReduceSum", KB_ROOT)
    pref = select_preferred_doc(docs, "Membase")
    assert pref is not None
    s = str(pref)
    # A3 Membase → 非 SIMD 路径 + 高阶API。
    assert "SIMD_API" not in s
    assert "高阶API" in s


def test_select_regbase_prefers_simd():
    docs = resolve_api_docs("ReduceSum", KB_ROOT)
    pref = select_preferred_doc(docs, "Regbase")
    assert pref is not None
    assert "SIMD_API" in str(pref)


def test_select_empty_docs_returns_none():
    assert select_preferred_doc([], "Membase") is None


# —— build_signature_hint_section ——


def test_hint_contains_doc_path_and_directive():
    section = build_signature_hint_section(STDERR_SIGNATURE, "Membase", KB_ROOT)
    # 段标题 + 每个 API 的权威 doc 路径 + 逐字使用指令。
    assert "API 签名修正" in section
    assert "ReduceSum" in section
    assert "高阶API" in section  # 选中的 A3 高阶路径
    assert "逐字" in section or "Read" in section


def test_hint_has_antianchoring_clause():
    # 反锚定：逐字用后仍失败 = KB↔CANN 不符，停下报告，勿循环同一写法。
    section = build_signature_hint_section(STDERR_SIGNATURE, "Membase", KB_ROOT)
    assert "KB" in section or "CANN" in section or "停下" in section or "勿" in section


def test_hint_empty_when_no_signature_error():
    # 非签名错误 → 不注入（返回 ""），避免噪音。
    assert build_signature_hint_section(STDERR_LINKER_ONLY, "Membase", KB_ROOT) == ""
    assert build_signature_hint_section(STDERR_NONSIGNATURE, "Membase", KB_ROOT) == ""


def test_hint_caps_apis_to_avoid_bloat():
    # 多个失败 API 时截断到 max_apis，防爆上下文。
    stderr = "\n".join(
        f"error: no matching function for call to 'Api{i}'" for i in range(20)
    )
    section = build_signature_hint_section(stderr, "Membase", KB_ROOT, max_apis=5)
    # 截断后仍有"更多"提示，且不列出 20 个。
    assert "Api0" in section
    assert "Api19" not in section
