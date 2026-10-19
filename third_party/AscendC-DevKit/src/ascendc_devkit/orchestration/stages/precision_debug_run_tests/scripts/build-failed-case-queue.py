#!/usr/bin/env python3
"""Build failed_case_queue from result.json — deterministic, correct case_id.

Reads the ``ascendc-devkit run-cases`` output (result.json) and populates
``control.json``'s ``failed_case_queue`` with canonical ``case_id`` values
directly from ``case_details[].case_id`` (e.g. "level2/dynamic_quant_1").

This script REPLACES the error-prone inline approach where the run_tests
sub-agent manually extracts case_id from result.json. By using a deterministic
script we guarantee case_id always matches the cann-bench format usable by
``--case`` single-case re-runs.

Scope (54-*.md §4.2): writes ONLY ``failed_case_queue`` to control.json — it is
the cross-domain shared structure (run_tests writes, fix updates case status,
FW advances current_case_index). The run-level counts (failed_count /
total_count) and ``last_result_json`` are NOT control.json fields; they are
printed to stdout for the framework (RunTestsSubstage.transition — N1 纯
Python, no agent) to fold into the history entry (control.json.history[])
and ``last_result_json`` (precision_run_tests.json).

Failure authority: ``case_details[].accuracy.passed == false`` OR a case-level
``error``. Do NOT re-invent thresholds (the old ``diff > 1e-2`` rule is dead —
it mis-kills legitimate DQ int8 ±1 quantization differences).

Usage::

    python3 build-failed-case-queue.py \\
        --result-json /path/to/result.json \\
        --control     /path/to/control.json
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any


# ── Shape extraction ──────────────────────────────────────────────────────────

def _extract_shape(case_detail: dict) -> str:
    """Extract a canonical shape string like "1024x1024" from a case_detail."""
    input_shapes: list | None = case_detail.get("input_shapes")
    if input_shapes and isinstance(input_shapes, list) and len(input_shapes) > 0:
        first = input_shapes[0]
        if isinstance(first, list):
            return "x".join(str(d) for d in first)
    case_name: str = case_detail.get("case", "")
    if ":" in case_name:
        tail = case_name.rsplit(":", 1)[-1].strip()
        if tail:
            return tail
    return ""


# ── Dtype extraction ──────────────────────────────────────────────────────────

_DTYPE_PATTERN = re.compile(
    r"\b(float16|float32|bfloat16|fp16|fp32|bf16|int8|int32|int64)\b",
    re.IGNORECASE,
)


def _extract_dtype(case_detail: dict) -> str:
    case_name: str = case_detail.get("case", "")
    m = _DTYPE_PATTERN.search(case_name)
    if m:
        return m.group(1).lower()
    for out in case_detail.get("output_results", []):
        od = out.get("dtype", "")
        if od:
            return od.lower()
    return ""


# ── Max error extraction ──────────────────────────────────────────────────────

def _extract_max_err(case_detail: dict) -> float | None:
    acc = case_detail.get("accuracy")
    if isinstance(acc, dict) and "max_diff" in acc:
        return acc["max_diff"]
    diff = case_detail.get("diff")
    if isinstance(diff, (int, float)):
        return float(diff)
    best: float | None = None
    for out in case_detail.get("output_results", []):
        d = out.get("diff", 0)
        if isinstance(d, (int, float)):
            best = max(best or 0, d)
    return best


# ── max_diff_location extraction ──────────────────────────────────────────────

def _extract_max_diff_location(case_detail: dict) -> dict | None:
    """Extract max_diff_location from the output with the largest diff.

    Only the five small fields are kept (kernel/golden_context are too large for
    control.json; diagnose re-reads result.json when it needs the full context).
    """
    outputs = case_detail.get("output_results", [])
    if not outputs:
        return None
    best_out: dict | None = None
    best_diff = -1.0
    for out in outputs:
        d = out.get("diff", 0)
        if isinstance(d, (int, float)) and d > best_diff:
            best_diff = d
            best_out = out
    if best_out is None:
        return None
    loc = best_out.get("max_diff_location")
    if not isinstance(loc, dict) or not loc:
        return None
    return {
        "flat_index": loc.get("flat_index"),
        "multi_index": loc.get("multi_index"),
        "output_index": best_out.get("index", 0),
        "kernel_value": loc.get("kernel_value"),
        "golden_value": loc.get("golden_value"),
    }


# ── Failure type (initial guess; agent refines from logs) ─────────────────────

def _initial_failure_type(case_detail: dict) -> str:
    """Initial failure_type from result.json alone.

    "runtime" when the case_detail carries an error field (NPU crash/timeout);
    "schema_contract" when the error is a python 契约/注册校验（PD-CONTRACT /
    schema 拒绝 / 注册失败，非 C++ 编译器输出——kernel 未真正运行）;
    "precision" otherwise. diagnose refines per-case judgment downstream
    (N2 判断决策权在 diagnose：读 result.json/run.log 修正初始分类).
    """
    err = case_detail.get("error") or ""
    err_l = err.lower()
    if case_detail.get("error"):
        # 契约/注册类（python 侧校验，kernel launch 前后）：definite 信号，
        # 其余 error（NPU crash/超时/编译失败文本）按 runtime 走，由 agent 精修。
        if ("pd-contract" in err_l or "pd_contract" in err_l
                or "schema" in err_l and "reject" in err_l
                or "not registered" in err_l
                or "cannot find registered" in err_l
                or "torch.ops" in err_l and "not found" in err_l):
            return "schema_contract"
        return "runtime"
    return "precision"


# ── Failure determination ─────────────────────────────────────────────────────

def _is_failed(cd: dict) -> bool:
    """True when a case_detail entry represents a failure.

    Authority: ``accuracy.passed == false`` (runner already applies proto
    precision_thresholds + cann-bench semantics per output) OR a case-level
    ``error`` (execution crash/timeout).
    """
    acc = cd.get("accuracy")
    if isinstance(acc, dict) and acc.get("passed") is False:
        return True
    if cd.get("error"):
        return True
    return False


def _extract_outputs(case_detail: dict) -> list[dict] | None:
    """Extract per-output diff/passed/status from output_results.

    Returns ``None`` for single-output cases or when output_results is absent.
    Only meaningful for multi-output operators where per-output tracking
    prevents one failing output from masking an improved one.

    Pass/fail judgment uses the harness's own ``passed`` field (which applies
    ``mere ≤ threshold`` etc.), NOT a raw diff comparison — the harness is
    the single authority on per-output correctness.
    """
    outputs = case_detail.get("output_results", [])
    if len(outputs) <= 1:
        return None
    olist: list[dict] = []
    for o in outputs:
        d = o.get("diff")
        olist.append({
            "index": o.get("index", 0),
            "diff": float(d) if isinstance(d, (int, float)) else None,
            "passed": o.get("passed", False),
            "status": "passing" if o.get("passed") else "failing",
        })
    return olist


def build_queue(result_json_path: str) -> tuple[list[dict], bool, int]:
    """Read result.json, return (new_failed_case_queue, crash_sentinel_mode, total_count).

    crash_sentinel_mode=True when harness died before printing any case output
    (top-level runtime_crash + both case_details and tested_cases empty).
    In that scenario the queue contains one synthetic sentinel entry so the
    framework has a queue item to route; the caller must also set
    control.json["crash_sentinel_mode"] = True so RunTestsSubstage.transition
    labels the round as crash_sentinel. Post-P3 routing: the sentinel entry
    flows into diagnose (comment-bisect is a diagnose in-place technique, not
    a separate phase); diagnose reads the crash evidence (run.log / crash dump).

    When ``case_details`` is empty (harness killed by subprocess timeout before it
    could print results), falls back to ``tested_cases`` — each tested case gets a
    queue entry with real ``case_id`` from the harness, marked as ``runtime``
    (the harness died before producing per-case verdicts). This avoids the
    synthetic ``hard_error`` placeholder that later phases (fix/printf) cannot
    match against real test cases.

    ``total_count`` is always consistent with the actual queue source:
    - Normal path (case_details used): ``len(case_details)``
    - Fallback path (tested_cases used): ``len(tested_cases)``
    - Crash sentinel (both empty): ``0``

    This prevents passed_count inflation when case_details has structural entries
    but no accuracy/error fields (partial harness output before crash): the old
    ``len(case_details) or len(tested_cases)`` OR-chain would short-circuit on the
    non-empty case_details and return 20 while the queue only has 1 tested_cases
    entry, making passed_count = 20 - 1 = 19 (wrong).
    """
    with open(result_json_path) as f:
        result = json.load(f)
    case_details: list[dict] = result.get("case_details", [])

    new_queue: list[dict] = []
    for cd in case_details:
        if not _is_failed(cd):
            continue
        entry = _build_entry(cd)
        new_queue.append(entry)

    # —— fallback: case_details yielded no failures (harness timed out / partial
    # output — entries present but accuracy/error fields absent) ——
    # Track whether fallback was used so total_count stays consistent with queue source.
    used_fallback = False
    if not new_queue:
        tested_cases: list[dict] = result.get("tested_cases", [])
        if tested_cases:
            used_fallback = True
            for tc in tested_cases:
                entry: dict[str, Any] = {
                    "case_id": tc.get("case_id", ""),
                    "shape": str(tc.get("shape", "")),
                    "dtype": "",
                    "status": "pending",
                    "max_err": None,
                    "failure_type": "runtime",
                    "attempt_count": 0,
                    "tried_fix_plan_ids": [],
                    "last_fix_commit": None,
                }
                new_queue.append(entry)

    # total_count must match the source used for the queue so that
    # passed_count = total_count - failed_count is meaningful.
    if used_fallback:
        total_count = len(tested_cases)  # reuse already-read local var
    else:
        total_count = len(case_details)

    # —— crash sentinel: harness died before any output (SIGSEGV/signal kill) ——
    # tested_cases also empty means the harness never reached the case loop at all.
    # Synthesize a sentinel entry so the queue is non-empty. Post-P3 routing:
    # the sentinel entry enters diagnose (comment-bisect is diagnose's in-place
    # technique, not a phase); diagnose reads crash evidence off run.log/dump.
    crash_sentinel_mode = False
    if not new_queue and result.get("failure_type") == "runtime_crash":
        crash_sentinel_mode = True
        total_count = 0  # harness never ran cases; no meaningful total
        new_queue.append({
            "case_id": "",
            "shape": "",
            "dtype": "",
            "status": "pending",
            "max_err": None,
            "failure_type": "runtime",
            "attempt_count": 0,
            "tried_fix_plan_ids": [],
            "last_fix_commit": None,
            "crash_sentinel": True,
        })
    return new_queue, crash_sentinel_mode, total_count


def _build_entry(cd: dict) -> dict[str, Any]:
    """Build a single queue entry from a case_detail dict."""
    entry: dict[str, Any] = {
        "case_id": cd.get("case_id", ""),
        "shape": _extract_shape(cd),
        "dtype": _extract_dtype(cd),
        "status": "pending",
        "max_err": _extract_max_err(cd),
        "failure_type": _initial_failure_type(cd),
        "attempt_count": 0,
        "tried_fix_plan_ids": [],
        "last_fix_commit": None,
    }
    loc = _extract_max_diff_location(cd)
    if loc:
        entry["max_diff_location"] = loc
    # §per-output: track per-output diff/status for multi-output cases
    outs = _extract_outputs(cd)
    if outs:
        entry["outputs"] = outs
    return entry


# —— 大 shape 超时确定性放大（取代 LLM 判断）——
#
# 历史教训（unique d61245）：harness 看门狗 120s 超时 + 大 shape（百万级元素，
# golden 本身就可能数十秒——unique_6 268M 元素 CPU 排序 ~93s）时，放大超时是
# 机械决策，不该依赖 LLM 判断——历史上 run_tests agent（已删，N1）误判
# 「环境/死锁」就跳过放大，整轮 run_tests 在假阴性超时上白跑。本脚本
# （RunMeasure 每轮必跑）确定性判定并写回 control.json.harness_timeout_sec
# （debug_service.run_cases 自动消费），测量命令的 AMPLIFIED 循环收到信号后
# 用新超时重跑 run-cases。
_DEFAULT_HARNESS_TIMEOUT_SEC = 120.0        # 与 runtime_config 默认对齐
_DEFAULT_HARNESS_TIMEOUT_MAX_SEC = 1200.0   # 放大上限（与 SKILL/run_tests.md 一致）
_DEFAULT_LARGE_SHAPE_ELEMENTS = 1_000_000   # 大 shape 判据（SKILL「数百万级起步」的确定性化）
_AMPLIFY_FACTOR = 4                         # SKILL 同款 T' = min(T×4, cap)


def amplify_timeout_if_large_shape(result: dict, control: dict) -> tuple[bool, str]:
    """Determine and apply large-shape timeout amplification (in place).

    Returns ``(amplified, reason)``:
    - (True, "large_shape_amplified")  — control["harness_timeout_sec"] was
      raised (×4, capped) for a re-run with a larger budget.
    - (False, "large_shape_over_cap")  — already at the cap; re-running again
      will not help (report honestly as such).
    - (False, "non_large_shape")       — timeout with no ≥1M-element case;
      likely a deadlock/environment issue, amplification would only delay.
    - (False, "")                      — not a timeout at all.

    Cap and large-shape threshold read from control.json (``harness_timeout_max_sec``
    / ``harness_large_shape_elements``) when present, else built-in defaults —
    the script is stdlib-only (§2.1 skill self-containment), no devkit import.
    """
    is_timeout = (
        result.get("failure_type") == "timeout"
        or "timed out" in str(result.get("error", ""))
    )
    if not is_timeout:
        return False, ""
    tested: list[dict] = result.get("tested_cases", []) or []
    max_elems = max(
        (tc.get("max_input_elements") or 0 for tc in tested), default=0)
    large_threshold = control.get("harness_large_shape_elements")
    if not isinstance(large_threshold, (int, float)) or large_threshold <= 0:
        large_threshold = _DEFAULT_LARGE_SHAPE_ELEMENTS
    if max_elems < large_threshold:
        return False, "non_large_shape"
    current = control.get("harness_timeout_sec")
    if not isinstance(current, (int, float)) or current <= 0:
        current = _DEFAULT_HARNESS_TIMEOUT_SEC
    cap = control.get("harness_timeout_max_sec")
    if not isinstance(cap, (int, float)) or cap <= 0:
        cap = _DEFAULT_HARNESS_TIMEOUT_MAX_SEC
    new_t = min(current * _AMPLIFY_FACTOR, cap)
    if new_t <= current:
        return False, "large_shape_over_cap"
    control["harness_timeout_sec"] = round(new_t, 1)
    return True, "large_shape_amplified"


def merge_with_existing(new_queue: list[dict], old_queue: list[dict]) -> list[dict]:
    """Merge new structural data into an existing queue, preserving metadata.

    Matches by (shape, dtype) — the most stable identifier across iterations.
    On match, case_id/shape/dtype/max_err come from the new entry while
    failure_type / tried_fix_plan_ids / last_fix_commit / attempt_count
    are preserved from the old entry (sub-agent-written metadata).

    §P3: status is conditionally preserved — if the case still fails in the
    new result (max_err is non-zero), ``resolved_pending`` reverts to ``pending``
    (the fix didn't actually work).  If the case passes (max_err == 0 or not
    present), the old status is kept — the framework's RunTestsSubstage.transition
    will write ``resolved`` on full-suite pass (3d).

    §per-output: per-output diffs come from the new entry (fresh measurement);
    per-output status and diff_before are preserved from the old entry where
    the old entry carries an ``outputs`` array matched by index.
    """
    if not old_queue:
        return new_queue

    old_by_key: dict[tuple[str, str], dict] = {}
    for oe in old_queue:
        old_by_key[(oe.get("shape", ""), oe.get("dtype", ""))] = oe

    merged: list[dict] = []
    for ne in new_queue:
        oe = old_by_key.get((ne.get("shape", ""), ne.get("dtype", "")))
        if oe is not None:
            for preserve_key in (
                "failure_type", "tried_fix_plan_ids", "last_fix_commit",
                "attempt_count",
            ):
                if preserve_key in oe:
                    ne[preserve_key] = oe[preserve_key]
            # §P3: conditional status preserve
            new_max = ne.get("max_err")
            if new_max is not None and new_max != 0:
                # Case still failing → revert resolved_pending to pending
                if oe.get("status") == "resolved_pending":
                    ne["status"] = "pending"
                else:
                    ne["status"] = oe.get("status", ne.get("status"))
            else:
                # Case passes in new result → keep old status
                ne["status"] = oe.get("status", ne.get("status"))
            # §per-output: preserve old per-output status (fix may have
            # improved individual outputs); new diff measurements always win.
            old_outs = oe.get("outputs")
            new_outs = ne.get("outputs")
            if old_outs and new_outs:
                old_by_index = {o["index"]: o for o in old_outs if "index" in o}
                for no in new_outs:
                    oo = old_by_index.get(no.get("index"))
                    if oo:
                        no["status"] = oo.get("status", "failing")
                        old_diff = oo.get("diff")
                        if old_diff is not None:
                            no["diff_before"] = old_diff
        merged.append(ne)
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build failed_case_queue from result.json into control.json"
    )
    parser.add_argument("--result-json", required=True, help="Path to result.json")
    parser.add_argument("--control", required=True,
                        help="Path to .precision-fix/control.json")
    args = parser.parse_args()

    result_json_path: str = args.result_json
    control_path: str = args.control

    if not os.path.exists(result_json_path):
        print(f"ERROR: result.json not found at {result_json_path}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(control_path):
        print(f"ERROR: control.json not found at {control_path}", file=sys.stderr)
        sys.exit(1)

    new_queue, crash_sentinel_mode, total_count = build_queue(result_json_path)

    with open(result_json_path) as f:
        result = json.load(f)
    with open(control_path) as f:
        cp = json.load(f)

    # 大 shape 超时确定性放大（写回 control.json.harness_timeout_sec，debug_service
    # 下一轮 run-cases 自动消费）。放大决策不依赖 agent LLM 判断——agent 只负责在
    # 看到 AMPLIFIED 信号后重跑 run-cases（SKILL 指引）。
    _timeout_before = cp.get("harness_timeout_sec")
    amplified, amp_reason = amplify_timeout_if_large_shape(result, cp)
    if amp_reason:
        # 归因标注：超时无数值结果的 runtime 条目（fallback 路径产物）补
        # timeout_reason，供 diagnose/fix 与报告读取。
        for e in new_queue:
            if (e.get("failure_type") == "runtime"
                    and e.get("max_err") is None
                    and not e.get("crash_sentinel")):
                e["timeout_reason"] = amp_reason
    old_queue: list[dict] = cp.get("failed_case_queue", [])
    merged = merge_with_existing(new_queue, old_queue)

    # Write ONLY failed_case_queue back (cross-domain shared structure, §4.2).
    # Run-level counts + last_result_json are NOT control.json fields — they go
    # into the history entry + precision_run_tests.json (printed below for
    # the framework transition to fold in — N1: no agent).
    cp["failed_case_queue"] = merged
    # crash_sentinel_mode: harness died before any case output (SIGSEGV/signal).
    # RunTestsSubstage.resolve_condition reads this to route directly to
    # comment_bisect, bypassing diagnose/fix (which need per-case log data).
    if crash_sentinel_mode:
        cp["crash_sentinel_mode"] = True
    else:
        cp.pop("crash_sentinel_mode", None)
    cp["last_updated"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with open(control_path, "w") as f:
        json.dump(cp, f, indent=2, ensure_ascii=False)

    # —— 框架自有 sidecar 持久化放大超时（§2.9 构造性）——
    # control.json.harness_timeout_sec 曾被 run_tests agent（已删，N1）重写时弄丢
    #（历史实证：agent 重写 control.json 时弄丢框架自有字段），放大值落框架自有 sidecar 兜底：
    # debug_service 读 sidecar 恢复，不靠 agent 保留字段。文件名与 runtime_config
    # HARNESS_TIMEOUT_SIDECAR_NAME 对齐（skill 自闭环：本脚本 stdlib-only，常量本地声明）。
    _timeout_now = cp.get("harness_timeout_sec")
    if isinstance(_timeout_now, (int, float)) and _timeout_now > 0:
        _sidecar_path = os.path.join(
            os.path.dirname(control_path), "harness_timeout.fw.json")
        with open(_sidecar_path, "w") as f:
            json.dump({"harness_timeout_sec": float(_timeout_now)},
                      f, indent=2, ensure_ascii=False)

    failed_count = len(merged)
    result_json_abs = os.path.abspath(result_json_path)

    # —— 超时放大信号：agent 据此重跑 run-cases（确定性触发，勿自行判断）——
    if amplified:
        print(
            f"AMPLIFIED: large-shape timeout → harness_timeout_sec "
            f"{_timeout_before!s}s → {cp['harness_timeout_sec']}s "
            f"(cap {cp.get('harness_timeout_max_sec', _DEFAULT_HARNESS_TIMEOUT_MAX_SEC)}s); "
            f"RE-RUN run-cases with the new budget before building the queue verdict")
    elif amp_reason == "large_shape_over_cap":
        print(
            f"TIMEOUT: large shape at cap {_DEFAULT_HARNESS_TIMEOUT_MAX_SEC}s — "
            f"report honestly as large_shape_over_cap (amplification exhausted)")
    elif amp_reason == "non_large_shape":
        print(
            "TIMEOUT: non-large-shape (no ≥1M-element case) — amplification "
            "not applicable; report as non_large_shape (疑似死锁/环境，非预算不足)")

    # —— stdout summary: framework transition reads this to write history + phase json ——
    by_type: dict[str, int] = {}
    for e in merged:
        ft = e.get("failure_type", "unknown")
        by_type[ft] = by_type.get(ft, 0) + 1
    type_summary = ", ".join(f"{v}x {k}" for k, v in sorted(by_type.items()))
    print(f"failed_case_queue: {failed_count} entries written to control.json")
    print(f"failed_count={failed_count} total_count={total_count} ({type_summary})")
    print(f"result_json={result_json_abs}")
    for i, e in enumerate(merged):
        print(f"  [{i}] case_id={e['case_id']}  shape={e.get('shape')}  "
              f"dtype={e.get('dtype')}  failure_type={e.get('failure_type')}")


if __name__ == "__main__":
    main()
