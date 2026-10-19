#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Independent AscendC / RegBase kernel source static checker.

This module provides a lightweight, regex-based static analysis for AscendC
kernel source code. It is intended to catch common RegBase/AscendC programming
mistakes before the expensive NPU compilation/launch pipeline.

The checks are intentionally independent from ``SingleOperatorLaunch`` so that
they can be imported and executed in isolation, used as a library, or wrapped
by other tooling without pulling in the full single-operator launch stack.

Rules currently enforced:

1. ``__simd_vf__`` / ``__simd_callee__`` function definitions must be marked
   ``inline``.
2. Inside ``__simd_vf__`` / ``__simd_callee__`` bodies, ``__ubuf__`` pointers
   must not be accessed directly with ``[]`` or ``*`` dereference operators;
   use ``AscendC::Reg`` APIs instead.
3. ``__simd_vf__`` / ``__simd_callee__`` functions must not touch GM/HBM
   memory directly (``GM_ADDR``, ``__gm__``, ``GlobalTensor``,
   ``SetGlobalBuffer``).
4. Hardware Loop constraints in ``__simd_vf__`` / ``__simd_callee__``:
   - ``for`` loops should use ``uint16_t`` iteration variables.
   - No runtime ``if/else`` or ternary ``?:`` inside loops
     (``if constexpr`` is allowed).
5. Variables passed to ``AscendC::Reg::UpdateMask`` inside a loop must not be
   mutated elsewhere in the same loop body, because ``UpdateMask`` already
   handles the internal decrement.
6. ``__simd_vf__`` / ``__simd_callee__`` functions must not contain runtime
   branches at function level (outside any loop body).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class CheckResult:
    """Result of a single static-check rule."""

    name: str
    passed: bool
    message: str = ""
    line_no: Optional[int] = None


@dataclass
class StaticCheckReport:
    """Aggregated report for all static checks."""

    results: List[CheckResult] = field(default_factory=list)

    def add(self, result: CheckResult) -> None:
        self.results.append(result)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def failures(self) -> List[CheckResult]:
        return [r for r in self.results if not r.passed]

    def __str__(self) -> str:
        lines = ["AscendC static check report:", "-" * 40]
        for r in self.results:
            status = "PASS" if r.passed else "FAIL"
            loc = f" (line {r.line_no})" if r.line_no is not None else ""
            lines.append(f"[{status}] {r.name}{loc}: {r.message}")
        if self.failures:
            lines.append("-" * 40)
            lines.append(f"Failed checks: {len(self.failures)}")
        return "\n".join(lines)


class RegBaseChecker:
    """Light-weight static checker for RegBase/AscendC kernel source."""

    # Regex to locate __simd_vf__ / __simd_callee__ function definitions.
    # It intentionally tolerates template<>, attributes, and namespace-qualified
    # return types, and captures the function name together with the parameter
    # list so that parameter-level checks (e.g. GM_ADDR) work correctly.
    SIMD_FUNC_RE = re.compile(
        r'__(?:simd_vf__|simd_callee__)\s+(?:inline\s+)?'
        r'(?:[\w:\u003c\u003e(),\s]+?)\s+(\w+)\s*\([^)]*\)'
    )

    def __init__(self, source: str, kernel_name: str):
        self.source = source
        self.kernel_name = kernel_name
        self.lines = source.splitlines()
        self.report = StaticCheckReport()
        # source with comments and strings replaced by spaces; positions are
        # preserved so line numbers can be recovered from matches.
        self._code = self._code_only()

    def _code_only(self) -> str:
        """Return source with comments and string literals replaced by spaces.

        Line numbers and overall length are preserved so positions from this
        string can be mapped back to ``self.source``.
        """
        result = list(self.source)
        n = len(self.source)
        in_string = False
        string_char = ""
        escaped = False
        i = 0
        while i < n:
            ch = self.source[i]
            if in_string:
                if escaped:
                    escaped = False
                    result[i] = " "
                elif ch == "\\":
                    escaped = True
                    result[i] = " "
                elif ch == string_char:
                    in_string = False
                    result[i] = " "
                else:
                    result[i] = " "
                i += 1
                continue
            if ch in ('"', "'"):
                in_string = True
                string_char = ch
                result[i] = " "
                i += 1
                continue
            if ch == "/" and i + 1 < n:
                next_ch = self.source[i + 1]
                if next_ch == "/":
                    # Line comment: replace until newline
                    while i < n and self.source[i] != "\n":
                        result[i] = " "
                        i += 1
                    continue
                if next_ch == "*":
                    # Block comment: replace until */
                    result[i] = " "
                    result[i + 1] = " "
                    i += 2
                    while i < n:
                        if (
                            self.source[i] == "*"
                            and i + 1 < n
                            and self.source[i + 1] == "/"
                        ):
                            result[i] = " "
                            result[i + 1] = " "
                            i += 2
                            break
                        result[i] = " "
                        i += 1
                    continue
            i += 1
        return "".join(result)

    @staticmethod
    def _line_no(text: str, pos: int) -> int:
        return text[:pos].count("\n") + 1

    def run_all(self) -> StaticCheckReport:
        """Run the full RegBase check suite."""
        self._check_simd_vf_modifiers()
        self._check_simd_vf_ubuf_access()
        self._check_simd_vf_no_gm_access()
        self._check_hardware_loop_constraints()
        self._check_hardware_loop_var_mutation()
        self._check_vf_function_level_branch()
        return self.report

    # --------------------------------------------------------------------- #
    # Rule 1: __simd_vf__ / __simd_callee__ must be inline
    # --------------------------------------------------------------------- #
    def _check_simd_vf_modifiers(self) -> None:
        failures = []
        for m in self.SIMD_FUNC_RE.finditer(self._code):
            pos = m.start()
            line_no = self._line_no(self._code, pos)
            rest = self._code[pos:]
            brace_idx = self._find_opening_brace_in_text(rest)
            if brace_idx == -1:
                continue
            signature = rest[:brace_idx]
            if "inline" not in signature:
                name_match = re.search(r'\b(\w+)\s*\([^)]*\)\s*$', signature)
                name = name_match.group(1) if name_match else "<unknown>"
                failures.append((name, line_no, "missing inline keyword"))

        self._add_simple_result(
            "simd_vf_modifiers",
            failures,
            "RegBase SIMD functions should be marked inline",
            "RegBase SIMD function modifiers look correct.",
        )

    # --------------------------------------------------------------------- #
    # Rule 2: no direct __ubuf__ [] access inside SIMD functions
    # --------------------------------------------------------------------- #
    def _check_simd_vf_ubuf_access(self) -> None:
        failures = []
        for m in self.SIMD_FUNC_RE.finditer(self._code):
            code_pos = m.end()
            body = self._extract_function_body(code_pos, text=self._code)
            reason = self._find_direct_ubuf_access(body)
            if reason:
                line_no = self._line_no(self._code, m.start())
                failures.append((m.group(1), line_no, reason))

        self._add_simple_result(
            "simd_vf_ubuf_access",
            failures,
            "__simd_vf__ / __simd_callee__ functions must access __ubuf__ through "
            "AscendC::Reg APIs only",
            "No direct __ubuf__ pointer access found in __simd_vf__ / __simd_callee__ functions.",
        )

    @staticmethod
    def _find_direct_ubuf_access(body: str) -> Optional[str]:
        """Return the first direct __ubuf__ access token found, or None.

        Currently checks only array subscript ``ptr[i]``. Pointer dereference
        ``*ptr`` is intentionally not checked because it is hard to distinguish
        from multiplication ``a * b`` with regex-based analysis.
        """
        body = RegBaseChecker._strip_comments(body)
        if re.search(r'[a-zA-Z_]\w*\s*\[', body):
            return "[] subscript"
        return None

    # --------------------------------------------------------------------- #
    # Rule 3: no GM/HBM access inside SIMD functions
    # --------------------------------------------------------------------- #
    def _check_simd_vf_no_gm_access(self) -> None:
        gm_tokens = ("GM_ADDR", "__gm__", "GlobalTensor", "SetGlobalBuffer")
        failures = []
        for m in self.SIMD_FUNC_RE.finditer(self._code):
            func_name = m.group(1)
            code_pos = m.start()
            body = self._extract_function_body(m.end(), text=self._code)
            full_func = self._code[code_pos:m.end()] + body
            for token in gm_tokens:
                if token in full_func:
                    line_no = self._line_no(self._code, code_pos)
                    failures.append((func_name, line_no, f"contains '{token}' GM access"))
                    break

        self._add_simple_result(
            "simd_vf_no_gm",
            failures,
            "__simd_vf__ / __simd_callee__ functions must not access GM/HBM memory",
            "No GM/HBM access found in __simd_vf__ / __simd_callee__ functions.",
        )

    # --------------------------------------------------------------------- #
    # Rules 4a/4b: Hardware loop constraints
    # --------------------------------------------------------------------- #
    def _check_hardware_loop_constraints(self) -> None:
        loop_var_failures = []
        branch_failures = []

        for m in self.SIMD_FUNC_RE.finditer(self._code):
            func_name = m.group(1)
            base_line = self._line_no(self._code, m.start())
            body = self._extract_function_body(m.end(), text=self._code)
            loops = self._extract_loop_info(body)

            for line_offset, init, loop_body in loops:
                if not re.search(r'\buint16_t\b', init):
                    loop_var_failures.append((func_name, base_line + line_offset, init))

                branch = self._find_runtime_branch(loop_body)
                if branch:
                    branch_failures.append((func_name, base_line + line_offset, branch))

        self._add_simple_result(
            "hardware_loop_var_type",
            loop_var_failures,
            "Hardware Loop iteration variables must be uint16_t",
            "All Hardware Loop iteration variables use uint16_t.",
        )
        self._add_simple_result(
            "hardware_loop_branch",
            branch_failures,
            "Hardware Loops must not contain runtime if/else or "
            "ternary operators (use UpdateMask, Select, or if constexpr instead)",
            "No runtime branches found inside Hardware Loops.",
        )

    # --------------------------------------------------------------------- #
    # Rule 5: UpdateMask argument must be a simple variable and not mutated
    # --------------------------------------------------------------------- #
    def _check_hardware_loop_var_mutation(self) -> None:
        mutation_failures = []
        expr_failures = []

        update_mask_re = re.compile(r'\bUpdateMask\s*<[^>]*>\s*\(([^)]*)\)')

        for m in self.SIMD_FUNC_RE.finditer(self._code):
            func_name = m.group(1)
            base_line = self._line_no(self._code, m.start())
            body = self._extract_function_body(m.end(), text=self._code)
            loops = self._extract_loop_info(body)

            for line_offset, _init, loop_body in loops:
                for um in update_mask_re.finditer(loop_body):
                    arg = um.group(1).strip()
                    if not re.match(r'^\w+$', arg):
                        expr_failures.append((func_name, base_line + line_offset, arg))
                    elif self._is_var_modified_in_loop(loop_body, arg):
                        mutation_failures.append((func_name, base_line + line_offset, arg))

        failures = mutation_failures + expr_failures
        if failures:
            msgs = []
            for name, ln, var in mutation_failures:
                msgs.append(
                    f"{name} at line {ln}: variable '{var}' passed to UpdateMask is also "
                    f"mutated inside the loop body (UpdateMask already handles the internal decrement)"
                )
            for name, ln, expr in expr_failures:
                msgs.append(
                    f"{name} at line {ln}: expression '{expr}' passed to UpdateMask; "
                    f"argument must be a simple variable (lvalue) since UpdateMask takes it by reference"
                )
            self.report.add(
                CheckResult(
                    "hardware_loop_var_mutation",
                    False,
                    "UpdateMask argument error: " + "; ".join(msgs),
                    line_no=failures[0][1],
                )
            )
        else:
            self.report.add(
                CheckResult(
                    "hardware_loop_var_mutation",
                    True,
                    "All UpdateMask calls use valid variable arguments "
                    "and are not mutated inside Hardware Loops.",
                )
            )

    # --------------------------------------------------------------------- #
    # Rule 6: no runtime branches at function level in SIMD functions
    # --------------------------------------------------------------------- #
    def _check_vf_function_level_branch(self) -> None:
        failures = []
        for m in self.SIMD_FUNC_RE.finditer(self._code):
            func_name = m.group(1)
            base_line = self._line_no(self._code, m.start())
            body = self._extract_function_body(m.end(), text=self._code)
            body_no_loops = self._remove_for_loop_bodies(body)
            branch = self._find_runtime_branch(body_no_loops)
            if branch:
                failures.append((func_name, base_line, branch))

        self._add_simple_result(
            "vf_function_level_branch",
            failures,
            "RegBase VF functions must not contain runtime if/else or "
            "ternary operators at function level (use for(1) pattern)",
            "No runtime branches found at VF function level.",
        )

    # --------------------------------------------------------------------- #
    # Helpers
    # --------------------------------------------------------------------- #
    def _add_simple_result(
        self,
        name: str,
        failures: List[Tuple[str, int, str]],
        failure_prefix: str,
        success_message: str,
    ) -> None:
        if failures:
            msgs = [f"{name_} at line {ln}: {reason}" for name_, ln, reason in failures]
            self.report.add(
                CheckResult(
                    name,
                    False,
                    failure_prefix + ": " + "; ".join(msgs),
                    line_no=failures[0][1],
                )
            )
        else:
            self.report.add(
                CheckResult(
                    name,
                    True,
                    success_message,
                )
            )

    @staticmethod
    def _find_opening_brace_in_text(text: str) -> int:
        """Return index of first '{' in text, skipping strings/comments."""
        in_string = False
        string_char = ""
        escaped = False
        for i, ch in enumerate(text):
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == string_char:
                    in_string = False
                continue
            if ch in ('"', "'"):
                in_string = True
                string_char = ch
                continue
            if ch == "{":
                return i
        return -1

    def _extract_function_body(self, start_pos: int, text: Optional[str] = None) -> str:
        """Extract the body of a function starting at start_pos.

        Handles balanced braces so the returned string includes the surrounding
        ``{}``. If ``text`` is provided, extract from that string instead of
        ``self.source``.
        """
        source = text if text is not None else self.source
        depth = 0
        in_string = False
        string_char = ""
        escaped = False
        i = start_pos
        end = len(source)
        body_start: Optional[int] = None

        while i < end:
            ch = source[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == string_char:
                    in_string = False
                i += 1
                continue

            if ch in ('"', "'"):
                in_string = True
                string_char = ch
                i += 1
                continue

            if ch == "{":
                if body_start is None:
                    body_start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if body_start is not None and depth == 0:
                    return source[body_start : i + 1]
            i += 1
        return source[start_pos:]

    @staticmethod
    def _strip_comments(text: str) -> str:
        """Remove C/C++ line and block comments from a code snippet."""
        text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
        text = re.sub(r'//.*', '', text)
        return text

    @staticmethod
    def _extract_loop_info(body: str) -> List[Tuple[int, str, str]]:
        """Extract ``for`` loops from a function body.

        Returns a list of ``(line_offset, init_clause, loop_body)`` tuples,
        where ``line_offset`` is the 0-based line offset within ``body``.
        """
        body_no_comments = RegBaseChecker._strip_comments(body)
        loop_re = re.compile(r'for\s*\(\s*([^;]*);\s*([^;]*);\s*([^)]*)\)')
        loops = []
        for m in loop_re.finditer(body_no_comments):
            init = m.group(1).strip()
            body_start = m.end()
            rest = body_no_comments[body_start:].lstrip()
            if rest.startswith("{"):
                loop_body = RegBaseChecker._extract_balanced_braces(body_no_comments, body_start)
            else:
                loop_body = RegBaseChecker._extract_statement(rest)
            line_offset = body_no_comments[: m.start()].count("\n")
            loops.append((line_offset, init, loop_body))
        return loops

    @staticmethod
    def _extract_balanced_braces(text: str, start: int) -> str:
        """Extract a ``{...}`` block starting at ``start`` (which must point at ``{``)."""
        depth = 0
        for j in range(start, len(text)):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    return text[start : j + 1]
        return text[start:]

    @staticmethod
    def _extract_statement(text: str) -> str:
        """Return the first C/C++ statement (up to the matching ``;``) from text."""
        depth = 0
        for i, ch in enumerate(text):
            if ch in "({":
                depth += 1
            elif ch in ")}":
                depth -= 1
            elif ch == ";" and depth == 0:
                return text[: i + 1]
        return text

    @staticmethod
    def _find_runtime_branch(body: str) -> Optional[str]:
        """Detect runtime if/else or ternary operators in a loop body.

        ``if constexpr`` is allowed and ignored.
        """
        body = RegBaseChecker._strip_comments(body)
        body = RegBaseChecker._remove_if_constexpr(body)
        if re.search(r'(?<![<,:])\?\s*[^?:]*\s*:', body):
            return "ternary operator ?:"
        if re.search(r'\bif\b', body):
            return "if/else branch"
        return None

    @staticmethod
    def _remove_if_constexpr(text: str) -> str:
        """Remove ``if constexpr (...) { ... }`` blocks from ``text``."""
        result = []
        i = 0
        n = len(text)
        while i < n:
            m = re.match(r'if\s+constexpr\b', text[i:])
            if m:
                paren_start = text.find("(", i + len(m.group(0)))
                if paren_start == -1:
                    result.append(text[i])
                    i += 1
                    continue
                depth = 0
                header_end = paren_start
                for j in range(paren_start, n):
                    if text[j] == "(":
                        depth += 1
                    elif text[j] == ")":
                        depth -= 1
                        if depth == 0:
                            header_end = j + 1
                            break
                k = header_end
                while k < n and text[k].isspace():
                    k += 1
                if k < n and text[k] == "{":
                    body_end = RegBaseChecker._find_matching_brace(text, k)
                    k = body_end + 1 if body_end != -1 else k
                else:
                    stmt_end = RegBaseChecker._find_statement_end(text, k)
                    k = stmt_end if stmt_end != -1 else k
                # also skip optional else / else if constexpr
                while True:
                    while k < n and text[k].isspace():
                        k += 1
                    if k + 4 <= n and text[k:k + 4] == "else":
                        k += 4
                        while k < n and text[k].isspace():
                            k += 1
                        if k + 10 <= n and text[k:k + 10] == "if constexpr":
                            continue
                        if k < n and text[k] == "{":
                            body_end = RegBaseChecker._find_matching_brace(text, k)
                            k = body_end + 1 if body_end != -1 else k
                        else:
                            stmt_end = RegBaseChecker._find_statement_end(text, k)
                            k = stmt_end if stmt_end != -1 else k
                    else:
                        break
                i = k
                continue
            result.append(text[i])
            i += 1
        return "".join(result)

    @staticmethod
    def _find_matching_brace(text: str, open_idx: int) -> int:
        """Return the index of the matching ``}`` for ``{`` at ``open_idx``."""
        depth = 0
        for j in range(open_idx, len(text)):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    return j
        return -1

    @staticmethod
    def _find_statement_end(text: str, start: int) -> int:
        """Return the index after the first statement starting at ``start``."""
        depth = 0
        for j in range(start, len(text)):
            if text[j] in "({":
                depth += 1
            elif text[j] in ")}":
                depth -= 1
            elif text[j] == ";" and depth == 0:
                return j + 1
        return -1

    @staticmethod
    def _is_var_modified_in_loop(loop_body: str, var_name: str) -> bool:
        """Check if *var_name* is assigned or mutated inside *loop_body*.

        Excludes the ``UpdateMask`` call itself.
        """
        body = RegBaseChecker._strip_comments(loop_body)
        body = re.sub(r'\bUpdateMask\s*<[^>]*>\s*\([^)]*\)', '', body)
        patterns = [
            # Plain assignment: must be at the start of a statement (after
            # ';', '{', or '}', or at the start of the body) to avoid
            # flagging declarations such as ``uint32_t remaining = n;``.
            rf'(?:^|(?<=[;{{}}]))\s*\b{var_name}\s*=(?!=)',
            rf'\b{var_name}\s*\+=',
            rf'\b{var_name}\s*-=',
            rf'\b{var_name}\s*\*=',
            rf'\b{var_name}\s*/=',
            rf'\b{var_name}\s*%=',
            rf'\b{var_name}\s*&=',
            rf'\b{var_name}\s*\|=',
            rf'\b{var_name}\s*\^=',
            rf'\b{var_name}\+\+',
            rf'\+\+{var_name}\b',
            rf'\b{var_name}--',
            rf'--{var_name}\b',
        ]
        for p in patterns:
            if re.search(p, body):
                return True
        return False

    @staticmethod
    def _remove_for_loop_bodies(text: str) -> str:
        """Replace all for-loop bodies with spaces to expose function-level branches."""
        result = list(text)
        loop_re = re.compile(r'for\s*\(\s*([^;]*);\s*([^;]*);\s*([^)]*)\)')
        for m in loop_re.finditer(text):
            for j in range(m.start(), m.end()):
                result[j] = " "
            k = m.end()
            while k < len(text) and text[k].isspace():
                result[k] = " "
                k += 1
            if k < len(text) and text[k] == "{":
                end = RegBaseChecker._find_matching_brace(text, k)
                if end != -1:
                    for j in range(k, end + 1):
                        result[j] = " "
                k = end + 1 if end != -1 else k
            else:
                end = RegBaseChecker._find_statement_end(text, k)
                if end != -1:
                    for j in range(k, end):
                        result[j] = " "
                k = end if end != -1 else k
        return "".join(result)


def check_regbase_source(
    source: str,
    kernel_name: str,
    raise_on_failure: bool = True,
) -> StaticCheckReport:
    """Run RegBase static checks on an AscendC kernel source string.

    Args:
        source: The kernel source code (e.g. contents of a ``.cpp`` file).
        kernel_name: The expected kernel entry function name.
        raise_on_failure: If ``True`` (default), raise ``RuntimeError`` when any
            check fails. Callers that only want the report can pass ``False``.

    Returns:
        A ``StaticCheckReport`` containing every individual check result.

    Raises:
        RuntimeError: If ``raise_on_failure`` is ``True`` and any check fails.
    """
    checker = RegBaseChecker(source, kernel_name)
    report = checker.run_all()
    if raise_on_failure and not report.passed:
        raise RuntimeError(
            "RegBase static check failed. Please fix the following issues "
            f"before compiling:\n{report}"
        )
    return report
