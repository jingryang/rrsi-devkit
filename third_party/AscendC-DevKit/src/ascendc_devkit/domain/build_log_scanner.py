"""Detect kernel compile failures swallowed by build_run.sh's ``||`` RC-masking.

第 5 类隐患(Plan lovely-painting-aurora):cann-bench ``build_run.sh`` 用
``cmake --build --target binary || { echo WARNING; }`` 把 kernel 编译失败吞成 RC=0,
于是 ``deploy.py:_run_command`` 在 RC=0 分支 ``return True, "", None`` 丢弃整个 stdout
(含 ``error: no matching function for call to 'Cast'``)。本模块是该分支的「真传感器」:
扫描 build role 的 stdout+stderr,命中编译失败信号则视为 build 失败,复用现有 RC≠0 通路
(落盘 ``subprocess/*.log`` + 返回 False),供 codegen in-session 自修循环捕获。

匹配的是 CANN 构建工具链诊断模式(asc_opc/TBE/clang),**非算子知识**(§1.5 不冲突)。
信号清单来自真实 ``/tmp/cel_build.log``(CEL:Cast×3 + DataCopyPad×2,6 tiling_key 全挂)。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# —— 真信号(CANN kernel 编译失败)——
# A7: clang error 行,最具体。CANN 9.1 的 g++/ccec 输出里 location 与错误消息分两行:
#   ``/path/op_host/foo.cpp:40:11:``
#   ``  error: 'TypedContinuousVector' does not name a type``
# 原正则只匹配单行 ``op_kernel/<file>.h:<line>:<col>: error:``(asc_opc/TBE 的单行
# 形态),2026-09-10 transpose 实证漏掉 host 侧 g++ 跨行形态——footer 提取为空、
# 真错不进 feedback,分类成 unknown。故新增跨行正则覆盖 ``path:line:col:`` 紧跟
# ``error:`` 两行形态;单行形态保留(asc_opc 仍走单行)。两态共用同一去重与结构化。
_RE_CLANG_ERROR = re.compile(
    r"op_kernel/(?P<file>[^:]+\.h):(?P<line>\d+):\d+: error: (?P<msg>.+)"
)
# 跨行形态:上一行 ``<path>:<line>:<col>:``,下一行(或同行冒号后)``error: <msg>``。
_RE_CLANG_ERROR_MULTILINE = re.compile(
    r"(?P<file>[^\s:][^:\n]*\.(?:cpp|cc|c|h)):(?P<line>\d+):\d+:\s*\n\s*error: (?P<msg>[^\n]+)"
)
# A2: 结构化失败记录 → op 名(kernelName 哈希同日志多处,op 名只需取一次)。
_RE_OP_COMPILE_FAILED = re.compile(
    r"Op\[(?P<op>[A-Za-z_]\w*)\] of index\[\d+\] compile failed"
)
# A4: RuntimeError 兜底 op 名来源(无 A2 时)。
_RE_KERNEL_COMPILATION_ERROR = re.compile(
    r"Kernel Compilation Error: OpType (?P<op>\S+)"
)
# A1/A2/A4 存在性:无 clang error 行时判定「确有编译失败」的兜底 marker。
_STRUCT_FAILURE_MARKERS = (
    "Opc tool compile failed",
    "compile failed, kernelName",
    "Kernel Compilation Error: OpType",
)

# —— build 错误分类（阶段2 改动1）——
# 口径对齐 .claude/skills/ascendc-op-dev-coding-regbase/scripts/classify_compile_error.sh 的
# C-API/C-SYM/C-TYP/C-LNK 桶，但用 Python 实现（框架不耦合 skill 脚本 §2.1；两源统一收敛到 domain
# 层登记为后续 tech debt）。顺序即优先级：多类命中时先返回最可修的（签名类 > 类型 > 符号 > 链接）。
_BUILD_ERROR_CLASSES: list[tuple[str, re.Pattern[str]]] = [
    ("C-API", re.compile(
        r"no matching function for call to|no member named|"
        r"too many arguments|too few arguments")),
    ("C-TYP", re.compile(
        r"cannot convert|no viable conversion|incompatible type|static assertion")),
    ("C-SYM", re.compile(
        r"undefined reference|undeclared identifier|has not been declared|"
        r"does not name a type")),
    ("C-LNK", re.compile(
        r"ld returned|undefined symbol|cannot open [^\n]*\.so")),
]


def classify_build_error(text: str | None) -> str:
    """Classify a build failure into a coarse bucket for retry-gradient routing.

    Returns one of ``C-API`` / ``C-TYP`` / ``C-SYM`` / ``C-LNK`` / ``unknown``.
    Multiple classes → the first match in priority order (signature/type/symbol/
    link), because the most-fixable class is the one to steer the agent toward.
    ``unknown`` covers the truly-silent linker symptom (``ld.lld cannot open .o``
    with no clang diagnostic) — it has no class-specific strategy, so callers
    skip the gradient hint for it.
    """
    if not text:
        return "unknown"
    for cls, rx in _BUILD_ERROR_CLASSES:
        if rx.search(text):
            return cls
    return "unknown"




@dataclass(frozen=True)
class KernelCompileError:
    """One kernel compile failure that ``||`` masked into RC=0."""

    op_name: str = ""
    source: str = ""    # op_kernel/<file>:<line>;空则无 clang 定位
    message: str = ""   # 编译器原文(no matching function for call to 'Cast')
    kernel: str = ""    # kernel 哈希名;空则未关联到具体 tiling_key


def scan_kernel_compile_errors(text: str | None) -> list[KernelCompileError]:
    """Scan build output for kernel compile failures masked into RC=0.

    Returns ``[]`` when the output carries no real failure signal — a clean
    build, or only benign lines (``WARNING: ... may have errors`` is the ``||``
    trigger not the error; ``Opc tool start working`` also appears on success;
    clang ``note:`` is candidate context). On a real kernel compile failure,
    returns deduplicated errors the agent can act on (file:line + compiler msg).
    """
    if not text:
        return []

    # 1. clang error 行(最具体),按 (file,line,msg) 去重 — 同一 .h:line 跨 tiling_key
    #    复现多次(CEL:6 tiling_key × 5 位置 = 30 次)只记一条。单行(asc_opc/TBE)
    #    与跨行(g++/ccec host 编译)两态都收——任一命中即有真错误可给 agent。
    clang_errors: list[tuple[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for rx in (_RE_CLANG_ERROR, _RE_CLANG_ERROR_MULTILINE):
        for m in rx.finditer(text):
            file, line, msg = m["file"], m["line"], m["msg"].strip()
            key = (file, line, msg)
            if key in seen:
                continue
            seen.add(key)
            clang_errors.append((f"{file}:{line}", msg))

    # 2. op 名:A2 结构化信号优先,A4(RuntimeError)兜底。
    op_name = ""
    m = _RE_OP_COMPILE_FAILED.search(text)
    if m:
        op_name = m["op"]
    elif (m := _RE_KERNEL_COMPILATION_ERROR.search(text)):
        op_name = m["op"]

    # 3. 有 clang error → 每条一个 KernelCompileError(带 op 名 + 文件:行定位)。
    if clang_errors:
        return [
            KernelCompileError(op_name=op_name, source=src, message=msg)
            for src, msg in clang_errors
        ]

    # 4. 无 clang error 行,但结构化信号(A1/A2/A4)表明确有编译失败 → 兜底一条。
    if any(marker in text for marker in _STRUCT_FAILURE_MARKERS):
        return [
            KernelCompileError(
                op_name=op_name,
                message="kernel compile failed (no source-line captured; "
                        "see full build log for compiler diagnostics)",
            )
        ]

    return []


_MAX_SUMMARY_ERRORS = 8


def format_kernel_error_summary(errors: list[KernelCompileError]) -> str:
    """Format errors for ``ErrorFeedback.details['stderr_tail']``.

    Op name + first N compiler errors so the agent sees the actionable gist in
    the redeploy CLI output without opening the full log.
    """
    if not errors:
        return ""
    op = errors[0].op_name
    head = errors[:_MAX_SUMMARY_ERRORS]
    lines = [f"kernel compile failed in op {op} ({len(errors)} errors):"]
    for e in head:
        lines.append(f"  {e.source}  {e.message}" if e.source else f"  {e.message}")
    if len(errors) > _MAX_SUMMARY_ERRORS:
        lines.append(
            f"  ... ({len(errors) - _MAX_SUMMARY_ERRORS} more, see full log)")
    return "\n".join(lines)


def build_failure_analysis_footer(
    stdout: str | None,
    stderr: str | None,
    programming_model: str,
    knowledge_root: "Path",
) -> str:
    """Framework-analysis footer to append to a build-failure subprocess log.

    Enriches the raw build output the codegen agent reads in its in-session
    redeploy loop with two deterministic, actionable sections
    (Plan cozy-wiggling-emerson 阶段1, OPT-A+OPT-B 合并):

    1. **Structured clang error summary** — surfaces ``op_kernel/<file>:<line>``
       cleanly even when buried under linker/host noise, so the agent acts on
       the real compiler error rather than a downstream symptom (the 70×
       ``ld.lld cannot open .o`` redeploy-loop trap).
    2. **AscendC API signature hint** — authoritative knowledge-base doc paths
       for signature-class errors (``no matching function for call to '<API>'``),
       so the agent Reads the verbatim signature instead of guessing from
       memory (the 244-turn thrash root cause).

    Returns ``""`` when neither applies — a clean-ish log, or a *pure* linker
    symptom with no recoverable compiler signal in the captured output (the
    truly-silent case has nothing to enrich here; it needs the kernel_meta
    compile log, out of scope). No noise is ever added to an un-enrichable log.

    The footer is wrapped in labeled sentinels so it is never confused with raw
    compiler output.
    """
    text = f"{stdout or ''}\n{stderr or ''}"
    parts: list[str] = []
    errors = scan_kernel_compile_errors(text)
    if errors:
        parts.append(format_kernel_error_summary(errors))
    # Lazy import — keeps build_log_scanner decoupled from the knowledge layer
    # at import time (api_signature_lookup pulls KnowledgeBase / pathlib).
    from ascendc_devkit.domain.api_signature_lookup import (
        build_signature_hint_section,
    )
    hint = build_signature_hint_section(text, programming_model, knowledge_root)
    if hint:
        parts.append(hint)
    if not parts:
        return ""
    return (
        "\n=== 框架错误分析（自动生成，非编译器输出） ===\n"
        + "\n\n".join(parts)
        + "\n=== end 框架错误分析 ==="
    )
