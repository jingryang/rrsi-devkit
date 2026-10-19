# L4 precision_report.md 渲染缺陷 — 实施方案

> 前置：L1 `01-problems.md`（P1-P7）、L3 `02-analysis.md`（决策汇总）。
> 目标：按 L3 §0 目标态重构报告函数，TDD 先写测试再改代码（§3.1），用本批 8 算子 control.json 快照做回归对照。

> **实施状态（2026-08-09）✅ 已实施**：`precision_debug_substages.py` 重构 `_write_precision_report_impl` + 新增 `_report_total`/`_report_fix_rows`/`_merge_fix_into_ledger` + P7 写点移出 if 块 + Fix/BoundsCheck transition 接入 ledger 合并。TDD 测试 `TestWritePrecisionReportRendering` 10 用例（T1-T8+T4b/c/d）+ 既有 `TestBestMetrics` 7 用例全过；orchestration UT 全量 1890 passed 零回归。8 算子快照回放验证：transpose（痛点）轮次 5 / 全过 ✅ / 分母 20 / None→- / 5 个修复 commit 全可见；resize_bilinear/group_norm/unique（running）正常渲染。sigmoid/swi_glu/apply_rotary_pos_emb 轮次=history max round（其 round 计数器未递增，属框架轮次计数语义既有现象，非报告渲染问题）。

---

## 1. 改动范围

- **改动文件**：`src/ascendc_devkit/orchestration/stages/precision_debug_substages.py`
- **报告侧（P1/P2/P3/P5/P6）**：
  - 改 `_write_precision_report_impl`（`:570-673`）
  - 新增纯函数 `_report_total(cp, history) -> int`（P2 优先级链）
- **写侧（P4 归一化）**：
  - `FixSubstage.transition`：agent summary 有 `git_commit` 且 fix 已应用 → 合并 resolved 条目进 `cp.root_cause_ledger`
  - `BoundsCheckSubstage.transition`：agent summary 有 `commit_sha` → 同样合并
  - printf 维持写 ledger（skill 契约不动，不加代码）
- **改调用点 1 处**：`RunTestsSubstage.transition` `:1933-1935`，报告写从 `if` 块内移出（L3 P7）
- **删旧通路（§1.4）**：报告不再读 history 的 `git_commit`/`commit_sha`/`ledger_updates` 4 载体；commit 只来自 `cp.root_cause_ledger` 单一源。
- 不新增持久化字段、不改 schema、不改路由、不改函数签名（`_write_precision_report(cp, debug_dir)` 不变）。

## 2. 函数改动细节

### 2.1 `_report_total`（P2）

```python
def _report_total(cp: dict, history: list) -> int:
    """报告用「用例总数」：best_total_count → history run_tests max(total_count) → 求和 → 0。"""
    total = int(cp.get("best_total_count") or 0)
    if not total:
        totals = [int((e.get("content") or {}).get("total_count") or 0)
                  for e in history if e.get("phase") == "run_tests"]
        if totals:
            total = max(totals)
    if not total:
        total = (int(cp.get("best_passed_count") or 0)
                 + int(cp.get("best_failed_count") or 0)
                 + int(cp.get("best_crashed_count") or 0))
    return total
```

理由（L3 P2 拍板 B）：三来源逐级回退。实测 transpose→20、resize_bilinear→20、unique→2（sentinel 下限，可解释）。

### 2.2 `_report_fix_rows`（P4 只读 ledger 单一源）

写侧归一化（见 §2.3）后，`root_cause_ledger` 是唯一权威：printf/diagnose 本就写，fix/bounds_check 由 transition 补齐（§2.3）。报告只读 ledger，不再 scavenge history 4 载体。

```python
def _report_fix_rows(cp: dict, history: list) -> list:
    """修复历史 commit 行：单一权威源 root_cause_ledger（CLAUDE.md §2.5 唯一通路）。

    - 有 fix_commit 的 resolved 条目 → commit 行（commit | 来源 | id+evidence）。
    - 无 commit 的纯根因分析行（diagnose/printf 的 root_cause/finding 文本）→ commit 列 '-'，
      从 history 渲染，保留审计价值。
    - 按 commit 去重（短 12 位）。
    """
    rows = []
    seen: set[str] = set()
    for rcl in cp.get("root_cause_ledger") or []:
        if not isinstance(rcl, dict):
            continue
        fc = rcl.get("fix_commit")
        if not fc:
            continue
        short = str(fc)[:12]
        if short in seen:
            continue
        seen.add(short)
        root = f"{rcl.get('id') or '?'}: {(rcl.get('evidence') or '')[:100]}"
        rows.append((short, "root_cause", root[:120]))
    # 纯根因分析行（无 commit）——来自 history 的 root_cause/finding 文本
    for entry in history:
        if not isinstance(entry, dict):
            continue
        content = entry.get("content")
        if not isinstance(content, dict):
            content = {}
        root = str(content.get("root_cause") or "")
        if not root:
            finding = content.get("finding")
            if finding:
                root = str(finding)[:200]
        if not root and content.get("aborted"):
            continue
        if not root:
            continue
        plan_id = str(content.get("applied_plan_id") or "")
        if plan_id:
            root = f"{plan_id}: {root}" if root else plan_id
        rows.append(("-", str(entry.get("phase") or "?"), root[:120]))
    return rows
```

覆盖（transpose 实测）：ledger 4 条 → `605af87`/`be4857e`/`6969dd0`/`59abb23`；bounds_check 的 `be17c2c` 由 §2.3 写侧合并进 ledger 后同样可见（全 5 个 commit）。swi_glu 的 2 个 fix-phase commit 由 §2.3 的 FixSubstage 合并进 ledger 后可见。diagnose/printf 纯根因行保留 `-`。

### 2.3 写侧归一化：fix / bounds_check transition 合并 ledger（P4）

**`FixSubstage.transition`**：在读取 agent summary 后、`_append_history` 前后，追加：

```python
def _merge_fix_into_ledger(cp: dict, summary: dict, phase: str) -> None:
    """把 agent 已报告的 commit（确定性字段）合并进 root_cause_ledger（§2.5 单一源）。

    fix: summary.git_commit；bounds_check: summary.commit_sha。
    追加 resolved 条目，按 fix_commit 去重。不增 open 数 → 不扰 diagnose 路由/停滞检测。
    """
    commit = summary.get("git_commit") or summary.get("commit_sha") or ""
    if isinstance(commit, list):
        commit = commit[0] if commit else ""
    if not commit:
        return
    short = str(commit)[:12]
    ledger = cp.setdefault("root_cause_ledger", [])
    for rcl in ledger:
        if isinstance(rcl, dict) and str(rcl.get("fix_commit") or "")[:12] == short:
            return                                    # 已存在，去重
    plan_id = str(summary.get("applied_plan_id") or summary.get("plan_id") or "")
    ledger.append({
        "id": f"{phase}-{short}",
        "type": "runtime" if phase == "bounds_check" else "precision",
        "state": "known",
        "status": "resolved",
        "fix_commit": str(commit),
        "evidence": (plan_id or f"{phase} applied commit {short}"),
        "last_result": f"resolved via commit {short}",
    })
```

调用点：
- `FixSubstage.transition`：summary 读入后 `_merge_fix_into_ledger(cp, summary, "fix")`，再 `_append_history`。
- `BoundsCheckSubstage.transition`：同样 `_merge_fix_into_ledger(cp, summary, "bounds_check")`。

合并是纯追加 + 去重，不改路由字段（不增 `status=open`）；若 agent summary 无 commit（refuted/未应用）则 no-op。

### 2.4 `_write_precision_report_impl` 重构（P1/P3/P5/P6 + 目标态 1）

```python
def _write_precision_report_impl(cp: dict, debug_dir: Path) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    op = str(cp.get("operator") or cp.get("op_name") or "unknown")
    best_commit = str(cp.get("best_commit") or "unknown")
    best_passed = int(cp.get("best_passed_count") or 0)
    best_failed = int(cp.get("best_failed_count") or 0)
    best_crashed = int(cp.get("best_crashed_count") or 0)
    status = str(cp.get("status") or "unknown")
    best_err = cp.get("best_real_max_err")
    err_str = "-" if best_err is None else str(best_err)          # P5
    history: list = cp.get("history") or []
    total = _report_total(cp, history)                            # P2
    # P1: 迭代轮次从 history 派生
    rounds = max([int(e.get("round") or 0) for e in history
                  if isinstance(e, dict) and e.get("phase") == "run_tests"] or [1])

    lines = [
        f"# Precision Debug Report — {op}",
        "",
        f"- **最优 commit**: `{best_commit}`",
        f"- **通过/失败/崩溃**: {best_passed}/{best_failed}/{best_crashed}",
        f"- **最大误差**: {err_str}",
        f"- **状态**: {status}",                                  # 目标态 1
        f"- **更新时间**: {now}",
        f"- **迭代轮次**: {rounds}",
        "",
        "## 失败用例状态",                                         # P3 表头诚实化
        "",
        "| # | Case | Shape | Dtype | Status | Max Err | Failure Type | Attempts |",
        "|---|------|-------|-------|--------|---------|-------------|----------|",
    ]
    queue = cp.get("failed_case_queue") or []
    if queue:
        for i, case in enumerate(queue, 1):
            if not isinstance(case, dict):
                continue
            case_id = str(case.get("case_id") or "?")
            shape = str(case.get("shape") or "?")
            dtype = str(case.get("dtype") or "?") or "-"
            cstatus = str(case.get("status") or "pending")
            max_err = case.get("max_err")
            ftype = str(case.get("failure_type") or "?")
            attempts = int(case.get("attempt_count") or 0)
            short_id = case_id.rsplit("/", 1)[-1] if "/" in case_id else case_id
            lines.append(f"| {i} | {short_id} | {shape} | {dtype} | {cstatus} "
                         f"| {max_err} | {ftype} | {attempts} |")
    else:
        # P3: 全过态显式渲染成功摘要，不留误导性空表
        ok = f"{best_passed}/{total}" if total else str(best_passed)
        lines.append(f"> ✅ **{ok}** 用例全部通过，无待处理失败用例。")

    lines.append("")
    lines.append("## 修复历史")
    lines.append("")
    lines.append("| # | Commit | Phase | 根因 / 发现 |")
    lines.append("|---|--------|-------|-------------|")
    for i, (commit, phase, root) in enumerate(_report_fix_rows(cp, history), 1):  # P4
        lines.append(f"| {i} | {commit} | {phase} | {root} |")

    # P2/P6 收敛趋势：分母用 total；去 fc>0 过滤；同轮去重（last wins）
    lines.append("")
    lines.append("## 收敛趋势")
    lines.append("")
    by_round: dict[int, tuple[int, int]] = {}
    for entry in history:
        if not isinstance(entry, dict) or entry.get("phase") != "run_tests":
            continue
        c = entry.get("content") or {}
        r = int(entry.get("round") or 0)
        if r <= 0:
            continue
        fc = int(c.get("failed_count") or 0)
        tc = int(c.get("total_count") or 0)
        by_round[r] = (fc, tc)                                    # last wins
    for r in sorted(by_round):
        fc, tc = by_round[r]
        total_r = tc or total
        passed_r = total_r - fc if total_r else best_passed
        lines.append(f"- 第 {r} 轮: {passed_r}/{total_r} passed ({fc} failed)")
    lines.append(f"- **当前最优**: {best_passed}/{total} passed")

    report_path = debug_dir / "precision_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
```

### 2.5 调用点改（P7）

`RunTestsSubstage.transition` `:1933-1935`，把报告写从 `if` 块内移出：

```python
        if _update_best_metrics(cp, run_result):
            _snapshot_best_commit(cp, _operator_dir(state))
        _write_precision_report(cp, _debug_artifacts_dir(state))   # 每次全量回归后刷新
```

`_snapshot_best_commit` 保持条件执行（仅 best 改善才更新）；报告无条件刷新 = 最近一次全量回归后的状态视图。`_sync_debug_result` 的 `:1209` 终态写保留作兜底（幂等，最后写胜）。

## 3. TDD 测试（先写测试，再改代码）

位置：`tests/ut/orchestration/test_precision_debug_stage.py` 的 `TestWritePrecisionReport*` 类（现 2 用例：`test_write_precision_report_creates_file` / `..._noop_without_debug_dir`）。复用 `_control(...)` fixture 与 history 结构。

| # | 用例 | 输入 | 断言 |
|---|---|---|---|
| T1 | `test_report_rounds_derived_from_history` | history run_tests rounds `[1,1,2,3,4,5]`，无 `cp.rounds` | 头部含 `迭代轮次: 5` |
| T2 | `test_report_all_pass_renders_success` | best 20/0/0、queue=[]、status=passed、history 末轮 fc=0 | 用例区含 `全部通过`；`最大误差: -`；`**状态**: passed`；趋势含 `第 5 轮: 20/20 passed`；`当前最优: 20/20` |
| T3 | `test_report_total_priority_chain` | `best_total_count` 缺、history total_count=20 | `当前最优` 分母为 20（非 0） |
| T4 | `test_report_fix_rows_from_ledger` | `root_cause_ledger` 3 条 resolved（各带 fix_commit）+ history 有诊断根因文本无 commit | 修复历史含 3 个 commit 行（commit 列非 `-`），纯根因行 commit 列 `-`；重复 fix_commit 去重 |
| T4b | `test_merge_fix_into_ledger_fix_phase` | summary `{git_commit: <c>}`，cp.ledger 空 | ledger 新增 `{id: fix-<c[:12]>, status: resolved, fix_commit: <c>}` |
| T4c | `test_merge_fix_into_ledger_bounds` | summary `{commit_sha: <c>}` | ledger 新增 `type: runtime` 的 resolved 条目 |
| T4d | `test_merge_fix_into_ledger_dedup_and_noop` | 同 commit 再合并 → 不重复；summary 无 commit → no-op | ledger 无重复、不新增 |
| T5 | `test_report_trend_dedupes_same_round` | history 两条 run_tests 均 round=1（fc=20 与 fc=12） | 趋势只有一行 `第 1 轮`，值为 12 |
| T6 | `test_report_max_err_none_rendered_dash` | `best_real_max_err=None` | 含 `最大误差: -`（不含 `最大误差: None`） |
| T7 | `test_report_keeps_legacy_fixrows` | 既有 `test_write_precision_report_creates_file` 的 history（comment_bisect 根因、无 commit） | 纯根因行 commit 列 `-` 仍渲染（既有断言 `host tiling` 保留） |
| T8 | `test_report_status_line` | status=exhausted | 含 `**状态**: exhausted` |

既有 `test_write_precision_report_creates_file` 断言（`test_op`/`abc123`/`3/20`/`host tiling`/`c1`/`resolved_pending`）必须在重构后仍全过——它覆盖失败态渲染的回归（`3/20` 来自 total 链第 2 级 history total_count=20）。

## 4. 验证

1. **TDD**：新增 T1-T8 + T4b/T4c/T4d 先红后绿，既有 `TestWritePrecisionReport*` 2 用例不回归。
2. **全量 UT**：`pytest tests/ut/orchestration/`（相关 stage 测试），预期 0 回归。
3. **真实快照回归对照（关键，一次性脚本，不进仓 §1.7）**：本批 8 算子 `control.json` 是**改动前**的数据（写侧归一化尚未发生过：swi_glu ledger 空、transpose 缺 bounds commit）。故脚本先**回放写侧归一化**（对 history 中带 `git_commit`/`commit_sha` 的条目调 `_merge_fix_into_ledger`，模拟新 transition 行为），再调 `_write_precision_report` 渲染，逐份核验：
   - **transpose**：`迭代轮次: 5`、`最大误差: -`、`状态: passed`、用例区含 `20/20 ... 全部通过`、修复历史 5 个 commit（`be17c2c`/`605af87`/`be4857e`/`6969dd0`/`59abb23`）、趋势含 `第 5 轮: 20/20 passed (0 failed)`、`当前最优: 20/20 passed`。
   - **swi_glu**：回放后 ledger 得 2 个 commit（`a96ab21a5d82`/`9541b25cf2e4`），报告修复历史可见。
   - **resize_bilinear**：`迭代轮次: 4`、趋势分母 20（非 0）、用例表 14 行保留。
   - **unique**：不崩、有内容（`0/1/1`、1 行队列或 sentinel 说明）。
4. **P7 验证**：code-review 确认 `:1933-1935` 写点移出 if 块；可选加一个 transition 级 UT（若现测试框架易测）。
5. **真实运行验证（可选，heavy_llm，§3.11）**：跑一个全过算子的 precision_debug 全流程，确认终态报告即本文目标态。成本高，用户决策是否跑。

## 5. 边界与风险

- **total=0 兜底**：`_report_total` 全空时返回 0，报告用 `ok=str(best_passed)`、趋势 `passed_r=best_passed`，不除零、不崩（§3.7 诚实降级，不假装有 total）。
- **history 空**：rounds 回退 1、趋势空、修复历史空——报告仍可写（`_write_precision_report` 外层 try/except 兜底不变）。
- **去重以 12 位短 commit 为 key**：同 commit 前缀碰撞概率可忽略；长 commit 尾差异不入 key。
- **写侧归一化风险**：`_merge_fix_into_ledger` 动 Fix/BoundsCheck 两个 transition——合并是纯追加 resolved 条目 + 去重，不增 `status=open`、不改任何路由字段（§1.2 可诊断：不静默改路由），T4b-T4d 守护；若 agent summary 无 commit 则 no-op，零影响。
- **改动前快照局限**：旧批次 ledger 已散乱，快照验证需回放写侧归一化（§4.3）才能看到全 5 commit——这不代表修复失效，是历史数据形态限制；新运行自动落在正确形态。
- **不改 `_sync_debug_result` 的 `:1209` 终态写**：保留作兜底，避免动终态路径。
