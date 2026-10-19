#!/usr/bin/env python3
"""策略选择 skill 的收尾门禁脚本（纯标准库）：screening / selection 两阶段校验。

  --stage screening   校验 screening.json（Top10 粗筛结果）
  --stage selection   校验 selection.json（最终选择，兼容字段供主 agent 消费）

退出码：0 通过；2 校验失败（stdout 给出 JSON 明细，须修复后重跑）。
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

TOP_K = 10
SELECT_MAX = 3
ASSESSMENTS = {"supported", "uncertain"}
STATUSES = {"supported", "uncertain", "contradicted"}
SELECTABLE_STATUSES = {"supported", "uncertain"}
SELECTED_KEYS = {"strategy_id", "strategy_path", "applicability_status",
                 "confidence", "bottleneck_fit", "rationale"}
COMPAT_FIELDS = ["applicable", "selected", "selected_strategy", "selected_strategy_path",
                 "selected_strategies", "bottleneck", "candidates_count", "rationale"]


def die(msg, code=2):
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def out_json(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def load_json(path, what):
    p = Path(path)
    if not p.is_file():
        die(f"{what} 不存在: {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        die(f"{what} JSON 解析失败 {p}: {e}")


def load_run_inputs(out_dir):
    ri = load_json(Path(out_dir) / "run_inputs.json", "run_inputs.json（先跑 select_prepare.py --prepare）")
    # 三态守卫：prepare 判定「未指定策略库」时干净退出（exit 0），不把 skip 标记当缺字段报错。
    if ri.get("status") == "skipped_no_library":
        out_json({"status": "skipped_no_library",
                  "reason": ri.get("reason", ""),
                  "hint": "策略检索未启用（未指定策略库），无最终产物可校验"})
        raise SystemExit(0)
    if ri.get("schema_version") != 1:
        die(f"run_inputs.json schema_version 非法: {ri.get('schema_version')}")
    return ri


def append_usage_log(out_dir, ri, sel):
    """usage log（追加式）：选中→逐条记录所用策略；无命中→记录原因说明。

    指定策略库且完成检索后的强制留痕（用户需求 2026-09-24）：selection 门禁通过后由
    本函数确定性追加——不依赖主 agent 自由发挥（§2.10 结构化产出）。落在
    <out_dir>/strategy_usage.log，与 selection.json 同目录同生命周期；追加式书写，
    重跑/复验不覆盖历史。无命中的原因取 selection.rationale（门禁已强制 applicable=false
    时必须写明被否原因）。
    """
    ts = datetime.now().isoformat(timespec="seconds")
    op = ri.get("op_name", "?")
    cat = ri.get("category", "?")
    sels = sel.get("selected_strategies") or []
    lines = [f"[{ts}] op={op} category={cat} "
             f"outcome={'selected' if sels else 'no_match'} count={len(sels)}"]
    if sels:
        for e in sels:
            lines.append(f"  USED {e.get('strategy_id')} "
                         f"status={e.get('applicability_status')} "
                         f"confidence={e.get('confidence')} "
                         f"fit={str(e.get('bottleneck_fit', '')).strip()}")
    else:
        reason = " ".join(str(sel.get("rationale", "")).split())
        lines.append(f"  REASON {reason}")
    p = Path(out_dir) / "strategy_usage.log"
    with p.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def warn_if_md_drifted(ri):
    """复核外部策略正文是否自 prepare 后被改写，漂移时告警（不阻断）。

    Phase 3 以完整 md 为准，但本脚本只校验 strategy_path 存在与文件名匹配，从不校验
    内容。若不查这一项，"以 md 为准"会落在从未冻结过的正文版本上。这里与
    select_prepare 的 emit-screening 各查一次，把事实显式化而非静默。
    """
    root, want = ri.get("strategy_root"), ri.get("source_md_digest")
    if not root or not want:
        return
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import cardlib  # noqa: PLC0415
        rows, _ = cardlib.load_cards_file(Path(ri["cards_path"]))
        pool_ids = sorted({r["strategy_id"] for r in (rows or [])}
                          - set(ri.get("excluded_ids", [])))
        now = cardlib.catalog_digest(Path(root), pool_ids,
                                     ri.get("md_dir", cardlib.MD_ROOT_DEFAULT))
    except Exception:  # noqa: BLE001 — 复核失败不应影响门禁主判定
        return
    if now != want:
        print("警告: 外部策略正文自 prepare 后已变更（source_md_digest 不符）。"
              "本轮 selection 的判定依据可能与冻结时不一致。", file=sys.stderr)


# ---------------------------------------------------------------- screening

def stage_screening(args, out_dir):
    errors = []
    ri = load_run_inputs(out_dir)
    sc = load_json(args.screening or (Path(out_dir) / "screening.json"), "screening.json")

    # 筛选池：从卡片库重算（剔除 excluded），并校验卡片库未被改动
    # cardlib 与本脚本同目录（自包含），不再依赖 ascendc-strategy-card-builder skill。
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import cardlib
    cards_path = Path(ri["cards_path"])
    rows, cerr = cardlib.load_cards_file(cards_path)
    if rows is None or cerr:
        die(f"卡片文件不可用 {cards_path}: {cerr}")
    import hashlib
    if hashlib.sha256(cards_path.read_bytes()).hexdigest() != ri["cards_file_sha256"]:
        die(f"卡片文件与 prepare 时不符（{cards_path} 已被修改）——重跑 --prepare")
    excluded = set(ri.get("excluded_ids", []))
    pool_ids = {r["strategy_id"] for r in rows} - excluded

    def req(cond, msg):
        if not cond:
            errors.append(msg)

    req(isinstance(sc, dict), "screening 顶层须为对象")
    if isinstance(sc, dict):
        sc_keys = {"schema_version", "query_sha256", "top_candidates", "shortfall_reason", "pool_count"}
        req(sc.get("schema_version") == 1, "schema_version 须为 1")
        req(set(sc) == sc_keys,
            f"顶层键须恰好为 schema_version/query_sha256/top_candidates/shortfall_reason/pool_count"
            f"（多: {sorted(set(sc) - sc_keys)}，少: {sorted(sc_keys - set(sc))}）")
        # sha 链：screening 必须基于冻结的那份 query
        sha_path = Path(out_dir) / "query.sha256.txt"
        req(sha_path.is_file(), "query.sha256.txt 不存在（先跑 --freeze-query）")
        if sha_path.is_file():
            frozen_sha = sha_path.read_text(encoding="utf-8").strip()
            req(sc.get("query_sha256") == frozen_sha,
                "query_sha256 与 query.sha256.txt 不符（粗筛必须基于冻结的 query.json）")
        req(sc.get("pool_count") == ri["screening_pool_count"],
            f"pool_count={sc.get('pool_count')} 与 run_inputs 的 {ri['screening_pool_count']} 不符")

        cands = sc.get("top_candidates")
        req(isinstance(cands, list) and len(cands) <= TOP_K,
            f"top_candidates 须为不超过 {TOP_K} 个的数组")
        seen = set()
        query = load_json(Path(out_dir) / "query.json", "query.json")
        n_obs = len(query.get("current_implementation", []))
        if isinstance(cands, list):
            for i, c in enumerate(cands, 1):
                c_keys = {"strategy_id", "assessment", "supporting_observation_refs",
                          "reason", "missing_information", "already_present_scope"}
                req(isinstance(c, dict) and set(c) == c_keys,
                    f"top_candidates[{i}] 键非法（须 {sorted(c_keys)}）")
                if not isinstance(c, dict):
                    continue
                sid = c.get("strategy_id")
                req(isinstance(sid, str) and sid in pool_ids,
                    f"top_candidates[{i}].strategy_id {sid!r} 不在筛选池（或属已用策略被排除）")
                if isinstance(sid, str):
                    req(sid not in seen, f"strategy_id 重复: {sid}")
                    seen.add(sid)
                req(c.get("assessment") in ASSESSMENTS,
                    f"top_candidates[{i}].assessment 须为 supported/uncertain（粗筛阶段不做终判）")
                refs = c.get("supporting_observation_refs")
                req(isinstance(refs, list) and all(isinstance(x, str) for x in refs),
                    f"top_candidates[{i}].supporting_observation_refs 须为字符串数组")
                if c.get("assessment") == "supported":
                    req(isinstance(refs, list) and len(refs) >= 1,
                        f"top_candidates[{i}] supported 必须引用观察编号（O001…）")
                    for r in refs if isinstance(refs, list) else []:
                        m = re_match_obs(r)
                        req(m is not None and 1 <= m <= n_obs,
                            f"top_candidates[{i}] 观察编号 {r!r} 非法（须 O001..O{n_obs:03d}）")
                req(isinstance(c.get("reason"), str) and c["reason"].strip(),
                    f"top_candidates[{i}].reason 须为非空字符串")
                mi = c.get("missing_information")
                req(isinstance(mi, list) and all(isinstance(x, str) and x.strip() for x in mi),
                    f"top_candidates[{i}].missing_information 须为非空字符串数组（可为空）")
                req(isinstance(c.get("already_present_scope"), str) and c["already_present_scope"].strip(),
                    f"top_candidates[{i}].already_present_scope 须为非空字符串（无重叠写「无重叠」）")
            budget = min(TOP_K, ri["screening_pool_count"])
            if len(cands) < budget:
                req(isinstance(sc.get("shortfall_reason"), str) and sc["shortfall_reason"].strip(),
                    f"候选数 {len(cands)} < 预算 {budget}，必须给 shortfall_reason 说明原因（禁止凑数）")

    if errors:
        out_json({"status": "rejected", "stage": "screening", "errors": errors})
        return 2
    out_json({"status": "ok", "stage": "screening", "candidates": len(sc["top_candidates"]),
              "pool_count": ri["screening_pool_count"]})
    return 0


def re_match_obs(ref):
    import re as _re
    m = _re.match(r"^O(\d{3,})$", ref if isinstance(ref, str) else "")
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- selection

def stage_selection(args, out_dir):
    errors = []
    ri = load_run_inputs(out_dir)
    warn_if_md_drifted(ri)
    sel_path = Path(args.selection) if args.selection else Path(out_dir) / "selection.json"
    sel = load_json(sel_path, "selection.json")

    def req(cond, msg):
        if not cond:
            errors.append(msg)

    req(isinstance(sel, dict), "selection 顶层须为对象")
    if not isinstance(sel, dict):
        out_json({"status": "rejected", "stage": "selection", "errors": errors})
        return 2

    for f in COMPAT_FIELDS:
        req(f in sel, f"缺少兼容字段 {f}（主 agent 依赖）")
    if errors:
        out_json({"status": "rejected", "stage": "selection", "errors": errors})
        return 2

    applicable = sel.get("applicable")
    selected = sel.get("selected")
    sid = sel.get("selected_strategy")
    spath = sel.get("selected_strategy_path")
    req(isinstance(applicable, bool), "applicable 须为 bool")
    req(isinstance(selected, bool), "selected 须为 bool")
    req(isinstance(sel.get("candidates_count"), int) and not isinstance(sel.get("candidates_count"), bool)
        and sel["candidates_count"] >= 1, "candidates_count 须为 ≥1 的整数（= 实际核对的候选数）")
    req(isinstance(sel.get("rationale"), str) and len(sel["rationale"].strip()) >= 10,
        "rationale 须为非空字符串（≥10 字，说明适用条件↔设计意图对应关系）")

    excluded = set(ri.get("excluded_ids", []))
    if selected:
        req(applicable, "selected=true 时 applicable 必须为 true")
        req(isinstance(sid, str) and sid.strip(), "selected=true 时 selected_strategy 非空")
        req(isinstance(spath, str) and spath.strip(), "selected=true 时 selected_strategy_path 非空")
        if isinstance(spath, str) and spath.strip():
            p = Path(spath)
            req(p.is_file(), f"selected_strategy_path 不存在: {spath}")
            if p.is_file():
                req(p.name.endswith(".md") and p.name[:-3] == sid,
                    f"selected_strategy_path 的文件名去 .md 须等于 selected_strategy（{p.name} vs {sid}）")
        if isinstance(sid, str) and sid:
            req(sid not in excluded, f"selected_strategy {sid} 在已用策略列表中（防重复选择）")
    else:
        req(sid in ("", None), "selected=false 时 selected_strategy 应为空")

    # selected_strategies（≤3 条，供开发方案吸收）。selected=true 时必须为 1..SELECT_MAX 条，
    # 且 [0] 即 selected_strategy（主策略）；selected=false 时为空数组。
    sels = sel.get("selected_strategies")
    req(isinstance(sels, list), "selected_strategies 须为数组")
    if isinstance(sels, list):
        req(len(sels) <= SELECT_MAX, f"selected_strategies 不得超过 {SELECT_MAX} 条")
        if selected:
            req(len(sels) >= 1, "selected=true 时 selected_strategies 至少 1 条")
        else:
            req(len(sels) == 0, "selected=false 时 selected_strategies 应为空数组")
        seen = []
        for i, e in enumerate(sels, 1):
            req(isinstance(e, dict) and set(e) == SELECTED_KEYS,
                f"selected_strategies[{i}] 键非法（须 {sorted(SELECTED_KEYS)}）")
            if not isinstance(e, dict):
                continue
            eid = e.get("strategy_id")
            epath = e.get("strategy_path")
            req(isinstance(eid, str) and eid.strip(), f"selected_strategies[{i}].strategy_id 非空")
            if isinstance(eid, str) and eid:
                req(eid not in excluded, f"selected_strategies[{i}].strategy_id {eid} 在已用策略列表")
                req(eid not in seen, f"selected_strategies[{i}].strategy_id 重复: {eid}")
                seen.append(eid)
            req(e.get("applicability_status") in SELECTABLE_STATUSES,
                f"selected_strategies[{i}].applicability_status 须为 supported/uncertain（contradicted 不入选）")
            req(isinstance(e.get("confidence"), (int, float)) and not isinstance(e.get("confidence"), bool)
                and 0 <= e["confidence"] <= 1, f"selected_strategies[{i}].confidence 须在 [0,1]")
            req(isinstance(e.get("bottleneck_fit"), str) and e["bottleneck_fit"].strip(),
                f"selected_strategies[{i}].bottleneck_fit 须为非空字符串")
            req(isinstance(e.get("rationale"), str) and len(e["rationale"].strip()) >= 10,
                f"selected_strategies[{i}].rationale 须 ≥10 字")
            if isinstance(epath, str) and epath.strip():
                pp = Path(epath)
                req(pp.is_file(), f"selected_strategies[{i}].strategy_path 不存在: {epath}")
                if pp.is_file() and isinstance(eid, str) and eid:
                    req(pp.name.endswith(".md") and pp.name[:-3] == eid,
                        f"selected_strategies[{i}].strategy_path 文件名去 .md 须等于 strategy_id（{pp.name} vs {eid}）")
            if i == 1 and selected and isinstance(eid, str):
                req(eid == sid, "selected=true 时 selected_strategies[0].strategy_id 须为 selected_strategy（主策略）")
        # 选定策略必须出自粗筛候选集（禁止绕过 recall 直接指定）
        sc_p = Path(out_dir) / "screening.json"
        if selected and isinstance(sels, list) and sels and sc_p.is_file():
            sc = load_json(sc_p, "screening.json")
            cand_ids = {c.get("strategy_id") for c in sc.get("top_candidates", [])}
            for e in sels:
                if isinstance(e, dict) and e.get("strategy_id") not in cand_ids:
                    req(False, f"selected_strategies[{sels.index(e)+1}].strategy_id {e.get('strategy_id')!r} 不在粗筛候选集")

    if not applicable:
        req(not selected, "applicable=false 时 selected 必须为 false")
        req(isinstance(sel.get("rationale"), str) and sel["rationale"].strip(),
            "applicable=false 时 rationale 必须说明原因（也要落盘 selection.json）")

    # ranked_candidates（扩展字段）：若给出须 ⊆ 粗筛候选集，且与 candidates_count 一致
    sc_path = Path(out_dir) / "screening.json"
    ranked = sel.get("ranked_candidates")
    if ranked is not None:
        req(isinstance(ranked, list) and len(ranked) >= 1, "ranked_candidates 须为非空数组（或省略）")
        if isinstance(ranked, list) and sc_path.is_file():
            sc = load_json(sc_path, "screening.json")
            cand_ids = {c.get("strategy_id") for c in sc.get("top_candidates", [])}
            for i, rc in enumerate(ranked, 1):
                req(isinstance(rc, dict) and set(rc) == {"strategy_id", "applicability_status",
                                                         "confidence", "bottleneck_fit"},
                    f"ranked_candidates[{i}] 键非法（须 strategy_id/applicability_status/confidence/bottleneck_fit）")
                if isinstance(rc, dict):
                    req(rc.get("strategy_id") in cand_ids,
                        f"ranked_candidates[{i}].strategy_id 不在粗筛候选集")
                    req(rc.get("applicability_status") in STATUSES,
                        f"ranked_candidates[{i}].applicability_status 须为 supported/uncertain/contradicted")
                    conf = rc.get("confidence")
                    req(isinstance(conf, (int, float)) and not isinstance(conf, bool) and 0 <= conf <= 1,
                        f"ranked_candidates[{i}].confidence 须在 [0,1]")
                    req(isinstance(rc.get("bottleneck_fit"), str) and rc["bottleneck_fit"].strip(),
                        f"ranked_candidates[{i}].bottleneck_fit 须为非空字符串")
            req(sel["candidates_count"] == len(ranked),
                f"candidates_count={sel['candidates_count']} 应等于实际核对的 ranked_candidates 数 {len(ranked)}")
            if selected and isinstance(sid, str):
                req(ranked and ranked[0].get("strategy_id") == sid,
                    "selected=true 时 ranked_candidates[0] 须为 selected_strategy")
        elif isinstance(ranked, list):
            req(False, "给出 ranked_candidates 时必须先有 screening.json")

    if errors:
        out_json({"status": "rejected", "stage": "selection", "errors": errors})
        return 2
    # 门禁通过即落 usage log（选中→逐条 USED；无命中→REASON 原因说明）。写日志失败
    # 不吞掉主结果：报 WARN 但仍返回 0（可观测性缺陷不应把通过的 selection 变失败）。
    try:
        append_usage_log(out_dir, ri, sel)
        usage_log = str(Path(out_dir) / "strategy_usage.log")
    except OSError as e:  # noqa: BLE001 — logging never breaks the verdict
        print(f"[WARN] strategy_usage.log 写入失败: {e}", file=sys.stderr)
        usage_log = ""
    out_json({"status": "ok", "stage": "selection", "applicable": applicable,
              "selected": selected, "selected_strategy": sid or "",
              "selected_count": len(sels) if isinstance(sels, list) else 0,
              "usage_log": usage_log})
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", required=True, choices=["screening", "selection"])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--screening", default=None, help="screening.json 路径（默认 <out-dir>/screening.json）")
    ap.add_argument("--selection", default=None, help="selection.json 路径（默认 <out-dir>/selection.json）")
    args = ap.parse_args()
    out_dir = Path(args.out_dir).resolve()
    if args.stage == "screening":
        return stage_screening(args, out_dir)
    return stage_selection(args, out_dir)


if __name__ == "__main__":
    sys.exit(main())
