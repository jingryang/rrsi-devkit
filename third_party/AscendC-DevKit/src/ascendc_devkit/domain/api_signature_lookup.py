"""Extract failing AscendC API names from codegen compile stderr and resolve
their authoritative knowledge-base doc paths — deterministic signature hint
for the codegen failure-recovery loop.

背景（Plan cozy-wiggling-emerson OPT-A）：codegen 的 ``ascendc-coder``（Membase
路径）失败恢复循环（codegen.py in-session redeploy loop）只做「读 stderr → 凭记忆
改 → 重试」，无错误分类、无签名重查。transcript 实测 244 次编译失败，其中签名类
``no matching function for call to 'ReduceSum'``×10、Sqrt×6、Round×6、ReduceMax×3
等——agent 看得到 clang 行，却凭写出错误调用的同一份记忆去改，反复失败。

本模块把「失败 → 查权威签名」做成确定性：从 stderr 抽出失败的 API 名（结构信号，
非白名单 §1.12），解析其在 ``ascendc-dev-knowledge`` 的权威 doc 路径，供 codegen
prompt 在失败点注入「逐字使用此签名」指路（§1.5 知识在 resources 非代码）。

契约边界：
- 只处理**签名类**错误（no matching function / no member named）。非签名错误
  （undefined reference / 纯链接器 ``cannot open .o``）返回空，交回既有处理——
  那些不是「签名猜错」，本模块不该误报。
- 一个 API 在 KB 有多变体（高阶/基础 × A3根/A5-SIMD）；select_preferred_doc 按
  programming_model + 高阶API 优先选最可能匹配的，选不出回 None（caller 走 INDEX.md
  兜底）。**不替 LLM 拍板具体 overload**——注入 doc 路径 + directive，由 LLM Read 原文
  选匹配 overload（规避「注入错 overload > 不注入」的锚定风险）。
"""

from __future__ import annotations

import re
from pathlib import Path

# 签名类编译错误的 API 名抽取（复用 classify_compile_error.sh 的 C-API 模式）。
# 1. no matching function for call to '<API>' —— 模板/重载不匹配（最常见）。
_RE_NO_MATCHING = re.compile(r"no matching function for call to '([A-Za-z_]\w*)'")
# 2. has no member named '<member>' / no member named '<member>' —— 类缺成员
#    （如 OpAttrDef 无 FloatAttr）。member 名未必是 API，但常指向 API/属性族。
_RE_NO_MEMBER = re.compile(r"no member named '([A-Za-z_]\w*)'")

# 知识库 api_reference_docs 子目录名（KnowledgeBase.root 下）。
_API_DOCS_SUBDIR = "api_reference_docs"


def extract_failing_apis(stderr: str | None) -> list[str]:
    """Distinct AscendC API names implicated by signature-class compile errors.

    Returns names in first-occurrence order, deduplicated. Returns ``[]`` when
    stderr carries no signature-class error — non-signature failures (undefined
    reference, pure linker ``cannot open .o``) are left to existing handling.
    """
    if not stderr:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for rx in (_RE_NO_MATCHING, _RE_NO_MEMBER):
        for m in rx.finditer(stderr):
            name = m.group(1)
            if name not in seen:
                seen.add(name)
                found.append(name)
    return found


def resolve_api_docs(api_name: str, knowledge_root: Path) -> list[Path]:
    """All candidate doc files for ``api_name`` under the knowledge root.

    globs ``api_reference_docs/**/{api_name}.md``. Multiple candidates exist
    because an API has variants (高阶/基础 × A3-root/A5-SIMD). Returns ``[]`` if
    none — caller falls back to a generic INDEX.md directive.
    """
    base = Path(knowledge_root) / _API_DOCS_SUBDIR
    if not base.exists():
        return []
    return sorted(base.rglob(f"{api_name}.md"))


def select_preferred_doc(docs: list[Path], programming_model: str) -> Path | None:
    """Pick the doc most likely to match ``programming_model`` + high-level use.

    - Regbase (A5) → ``SIMD_API/`` path; Membase (A2/A3) → non-SIMD root path.
    - Prefer ``高阶API`` (the codegen kernel uses high-level APIs with
      sharedTmpBuffer) over ``基础API``.

    Returns ``None`` when ``docs`` is empty. Never raises — a wrong/unknown
    programming_model falls back to the first candidate rather than blocking the
    hint (the directive still points the agent at the API's docs).
    """
    if not docs:
        return None
    want_simd = programming_model == "Regbase"
    by_model = [d for d in docs if ("SIMD_API" in d.parts) == want_simd] or docs
    high_level = [d for d in by_model if "高阶API" in d.parts]
    return high_level[0] if high_level else by_model[0]


# 注入段的反锚定条款：逐字用后仍失败 = KB↔已装 CANN 不符或非签名问题，停下报告，
# 勿循环同一写法（避免 LLM 被「框架说用这个」锚定后不换思路）。
_ANTIANCHORING = (
    "若逐字采用后该 API 仍编译失败，多半是知识库与现场 CANN 版本不符、或属非签名"
    "问题（dtype/模板实参/上下文）——**停下报告**，不要反复试同一写法。"
)


def build_signature_hint_section(
    stderr: str | None,
    programming_model: str,
    knowledge_root: Path,
    max_apis: int = 5,
) -> str:
    """Build the ``## API 签名修正`` prompt section, or ``""`` if not applicable.

    Injected only when ``stderr`` carries signature-class errors naming ≥1 API.
    Each listed API gets its preferred authoritative doc path + a directive to
    Read the 函数原型 and use the matching overload verbatim. Capped at
    ``max_apis`` to avoid prompt bloat.
    """
    all_apis = extract_failing_apis(stderr)
    apis = all_apis[:max_apis]
    if not apis:
        return ""

    lines = [
        "## API 签名修正（权威指路，逐字使用）",
        "",
        "上一版编译失败包含 AscendC API 签名类错误。**禁凭记忆猜签名**——按下方"
        "权威文档（ascendc-dev-knowledge）的「函数原型」段，选用与你的调用上下文"
        f"（programming_model={programming_model}）匹配的 overload **逐字使用**：",
        "",
    ]
    more = len(all_apis) - max_apis
    for api in apis:
        docs = resolve_api_docs(api, knowledge_root)
        pref = select_preferred_doc(docs, programming_model)
        if pref is not None:
            lines.append(f"- `{api}` → Read `{pref}` 的函数原型段，逐字对齐签名。")
        else:
            # 定位失败（API 名不在 KB 命名约定，如 OpAttrDef FloatAttr）→ 兜底指 INDEX.md。
            lines.append(
                f"- `{api}` → 知识库无直接文档；查 `api_reference_docs/INDEX.md` "
                f"或 `ascendc-tips` 确认正确签名/用法。"
            )
    if more > 0:
        lines.append(f"- …（另有 {more} 个签名类失败 API，同法处理，见完整 stderr）")
    lines.extend(["", _ANTIANCHORING])
    return "\n".join(lines)
