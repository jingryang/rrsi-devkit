"""UT for the readable issue renderer (P25).

Covers L4 Step 4. The renderer is deterministic (no LLM compression), shared by
the runner's iteration-reason and the graph_executor loopback summary, and the
loopback payload carries full detail so a downstream LLM can act without re-lookup.
"""

from __future__ import annotations

from ascendc_devkit.orchestration.issue_render import (
    issue_fingerprint,
    lint_directives,
    render_issue,
    render_issues,
)
from ascendc_devkit.orchestration.kernel.state import State


def test_render_issue_format_and_truncation():
    issue = {"code": "AC2", "target": "tiling", "target_template": "T1",
             "detail": "x" * 300}
    out = render_issue(issue, detail_limit=80)
    assert out.startswith("[AC2→tiling/T1] ")
    assert out.endswith("...")
    assert len(out) < 200  # compact log line


def test_render_issue_full_when_no_limit():
    # loopback path: full detail so the downstream LLM needs no re-lookup
    long = "UB 196608B(192KB) vs claimed 245760B(240KB); buffer 160KB fits either way"
    issue = {"code": "AC2", "target": "tiling", "target_template": "T1", "detail": long}
    assert render_issue(issue, detail_limit=None) == f"[AC2→tiling/T1] {long}"


def test_render_issues_tail():
    issues = [{"code": f"C{i}", "target": "tiling", "detail": "d"} for i in range(7)]
    out = render_issues(issues, detail_limit=80, max_issues=5)
    assert len(out) == 6  # 5 + tail
    assert out[-1].startswith("(+2 more")


# —— P44-C: verdict (judgment face) / remediation (optional advice) separation ——


def test_render_issue_with_verdict_and_remediation():
    issue = {"code": "AC2", "target": "tiling", "target_template": "T1",
             "verdict": "infeasible", "detail": "Gather 不可用",
             "remediation": "改用 Gather 重写该段"}
    out = render_issue(issue, detail_limit=None)
    assert "判定=infeasible" in out
    assert "Gather 不可用" in out
    assert "建议" in out and "非强制" in out
    assert "改用 Gather 重写该段" in out


def test_render_issue_verdict_without_remediation():
    issue = {"code": "AC1", "target": "tiling", "verdict": "unverified",
             "detail": "claim 缺证据"}
    out = render_issue(issue, detail_limit=None)
    assert "判定=unverified" in out
    assert "建议" not in out  # no remediation → no advice suffix


def test_render_issue_legacy_five_fields_unchanged():
    # P44-C must not change output for legacy issues (no verdict/remediation).
    issue = {"code": "AC2", "target": "tiling", "target_template": "T1",
             "detail": "plain fact"}
    assert render_issue(issue, detail_limit=None) == "[AC2→tiling/T1] plain fact"


def test_lint_directives_flags_remediation_in_detail():
    # run 20260706-192227 real detail: structural directives belong in
    # `remediation`, not `detail` — flag them (advisory, §6.4).
    issues = [{"code": "AC2", "detail": "Exp 步必须走 fp32，bf16 tileLength 退为 15872"}]
    hits = lint_directives(issues)
    assert len(hits) == 1
    assert "AC2" in hits[0]


def test_lint_directives_clean_for_pure_facts():
    issues = [{"code": "AC2", "detail": "声称 Gather 不可用，但 Gather 指令明文可用"},
              {"code": "AC1", "detail": "claim 缺硬件证据，无法核实"}]
    assert lint_directives(issues) == []


# —— P45-(a): issue fingerprint for gate stagnation detection ——


def test_issue_fingerprint_stable_sorted():
    issues = [
        {"code": "AC2", "target": "tiling", "target_template": "T1"},
        {"code": "AC1", "target": "tiling", "target_template": "T1"},
    ]
    assert issue_fingerprint(issues) == "AC1@T1,AC2@T1"
    # order-independent (sorted) — same problem set across rounds is stable
    assert issue_fingerprint(list(reversed(issues))) == "AC1@T1,AC2@T1"


def test_issue_fingerprint_empty_when_no_issues():
    assert issue_fingerprint([]) == ""
    assert issue_fingerprint(None) == ""


def test_issue_fingerprint_uses_target_when_no_template():
    issues = [{"code": "AC1", "target": "docgen"}]
    assert issue_fingerprint(issues) == "AC1@docgen"
