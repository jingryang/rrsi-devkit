"""Deterministic blocking-issue renderer (P25) + directive lint (P44-C).

Shared by the runner's per-iteration reason log line and the graph_executor's
loop-back/routing summary, so failure causes are human+LLM readable everywhere
instead of a bare ``"quality check not satisfied"``. Deterministic field-select +
truncate — NOT an LLM/NLP compression (no hallucination/latency/cost).

Two length policies, one renderer:
  - detail_limit=int  → compact log line (truncated detail)
  - detail_limit=None → full detail, for loopback payloads injected into a
    downstream prompt (the LLM must act on it without re-lookup, so do not
    truncate to an opaque code like "AC2(tiling)").

P44-C: an issue carries a judgment face ``verdict`` (unverified/infeasible/
verified) and an optional non-binding ``remediation``. The renderer surfaces
verdict as the fact and remediation as advice (clearly marked non-binding) so
downstream agents do not mistake a suggestion for a verdict. ``lint_directives``
flags issues whose free-text ``detail`` still carries structural remediation
directives (dtype/tiling rewrites) — those belong in ``remediation``.
"""

from __future__ import annotations


# P44-C: structural-remediation directives that must live in `remediation`, not
# in the fact-stating `detail`. Split by match policy to avoid false positives:
#   - lower-keyed: safe tokens with no common-word overlap (matched on lower())
#   - case-keyed:  "Cast" matched case-sensitively so "broadcast" is not hit
#   - cn-keyed:    imperative Chinese rewrite verbs
_LOWER_DIRECTIVE_KEYWORDS = ("fp32", "tilelength", "tile_length")
_CASE_DIRECTIVE_KEYWORDS = ("Cast",)
_CN_DIRECTIVE_KEYWORDS = ("分核", "改写", "换成", "改为", "替换为")


def render_issue(issue: dict, detail_limit: int | None = None) -> str:
    """One issue → ``[code→target/template] 判定=verdict: detail（建议非强制：remediation）``.

    P44-C: ``verdict`` is the judgment face; ``remediation`` is optional advice,
    rendered as non-binding. Legacy issues (no verdict/remediation) render
    unchanged as ``[code→target/template] detail``.
    """
    code = issue.get("code", "?")
    target = issue.get("target", "?")
    tmpl = issue.get("target_template")
    verdict = (issue.get("verdict") or "").strip()
    detail = (issue.get("detail") or "").strip()
    remediation = (issue.get("remediation") or "").strip()

    def _trunc(s: str) -> str:
        if detail_limit is not None and len(s) > detail_limit:
            return s[:max(0, detail_limit - 3)] + "..."
        return s

    detail = _trunc(detail)
    remediation = _trunc(remediation)
    tmpl_part = f"/{tmpl}" if tmpl else ""
    head = f"[{code}→{target}{tmpl_part}]"

    if verdict:
        body = f"判定={verdict}" + (f": {detail}" if detail else "")
    else:
        body = detail
    line = f"{head} {body}"
    if remediation:
        line += f"（建议非强制：{remediation}）"
    return line


def render_issues(issues, detail_limit: int | None = None,
                  max_issues: int | None = 5) -> list[str]:
    """First N rendered issues + a ``(+k more)`` tail. Empty list if no issues."""
    issues = list(issues or [])
    if not issues:
        return []
    head_n = len(issues) if max_issues is None else max_issues
    head = [render_issue(i, detail_limit) for i in issues[:head_n]]
    extra = len(issues) - head_n
    if extra > 0:
        head.append(f"(+{extra} more, see events.jsonl)")
    return head


def lint_directives(issues) -> list[str]:
    """P44-C (§6.4): flag issues whose ``detail`` carries structural remediation
    directives (dtype/tiling rewrites). Such directives belong in the optional
    ``remediation`` field, with ``detail`` stating only facts. Advisory — returns
    human-readable hit descriptions; empty list when ``detail`` is pure facts.
    """
    hits: list[str] = []
    for i in issues or []:
        detail = (i.get("detail") or "")
        low = detail.lower()
        matched = [k for k in _LOWER_DIRECTIVE_KEYWORDS if k in low]
        matched += [k for k in _CASE_DIRECTIVE_KEYWORDS if k in detail]
        matched += [k for k in _CN_DIRECTIVE_KEYWORDS if k in detail]
        if matched:
            code = i.get("code", "?")
            hits.append(
                f"[{code}] detail 含改造令 {matched}：判定写 detail 事实，补救写 remediation")
    return hits


def issue_fingerprint(issues) -> str:
    """P45-(a): stable fingerprint of a gate's outstanding blocking issues.

    Used as the stagnation-detection signature (graph_executor ``same>=2`` halt)
    for gate corrective loops, which don't set ``last_error`` so the default
    signature is empty and stagnation never fires. ``issue_id`` is
    engineering-derived (``code@target_template`` or ``code@target``) — stable
    across rounds when the same problem persists, changes when the problem set
    changes (so a genuinely new problem resets the stall counter). Empty issues
    → ``""`` (clean gate → no stagnation trigger).
    """
    ids = []
    for i in issues or []:
        code = i.get("code", "?")
        scope = i.get("target_template") or i.get("target") or "?"
        ids.append(f"{code}@{scope}")
    return ",".join(sorted(ids))


def render_loopback_feedback_section(state) -> str | None:
    """Render ``state._loopback_feedback`` (``{blocking_issues: [...]}``) as a
    ``## 上次反馈`` prompt section; None when no feedback.

    Shared by every loopback target that consumes a gate's structured feedback:
    design substage prompts (via ``_DesignSubstage._feedback_section``) and
    ``RequirementStage`` (NOT a ``_DesignSubstage``, but receives a gate's
    ``_loopback_feedback`` on escalate-bubble, e.g. review design_input_invalid →
    requirement). Pulling this out of ``_DesignSubstage`` lets requirement reuse
    the exact rendering without inheriting design-substage machinery.
    """
    fb = getattr(state, "_loopback_feedback", None) or {}
    issues = fb.get("blocking_issues", []) if isinstance(fb, dict) else []
    if not issues:
        return None
    return "## 上次反馈\n" + "\n".join(render_issue(i, detail_limit=None) for i in issues)
