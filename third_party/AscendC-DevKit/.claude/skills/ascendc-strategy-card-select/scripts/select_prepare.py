#!/usr/bin/env python3
"""策略选择 skill 的准备端脚本（纯标准库）：环境准备 / Query 冻结 / 粗筛单生成。

三个子命令：
  --prepare        解析类别 → 加载卡片库（不做门禁审计） → 解析已用策略 → 写 run_inputs.json
                   （输入为设计文档，而非算子代码/契约）
  --freeze-query   校验 query.json（内置极简校验器，不依赖 jsonschema）→ 冻结到 out_dir
  --emit-screening 读 run_inputs.json + query.json（sha 核对 + schema 复验）→ 生成
                   screening_worksheet.md（完整冻结 Query + 该类全量卡片剔除 excluded
                   后的全部卡，按 id 排序）

退出码：0 正常；2 校验/门禁失败。

策略库为**外部数据目录**（`ASCENDC_STRATEGY_ROOT` / `--strategy-root`），不随本 skill
打包；卡片文件由 build_cards.py 在运行目录内生成后再喂给 --prepare（见 SKILL.md）。
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cardlib  # noqa: E402

QUERY_TOP_KEYS = ["schema_version", "operator_semantics", "workload", "current_implementation",
                  "bottleneck_hypotheses", "constraints", "current_optimizations",
                  "missing_information", "retrieval_hints"]
OBS_REF_RE = re.compile(r"^O(\d{3,})$")


def die(msg, code=2):
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def out_json(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------- 类别解析

def resolve_category(args, valid_categories):
    """按优先级解析类别。返回 (category, source)；全失败 die 并列出候选类别。

    设计阶段无执行契约/无 profiling，类别由调用方显式指定（按算子数据流特征映射到
    策略库的类目，禁止按算子名）：
    1) --cards-file / STRATEGY_CARDS（.texts.json 路径，basename 定类别且该文件即卡片源）
    2) --category / STRATEGY_CATEGORY

    合法性判据是**对策略库实际类目清单的成员校验**，而不是正则：类目清单由外部目录树
    派生（cardlib.categories），是唯一事实源。成员校验同时充当拼写门——否则 `elementwis`
    这类笔误要到"卡片文件找不到"处才暴露。
    """
    candidates = list(valid_categories)

    def _check(cat, source):
        if cat in candidates:
            return cat, source
        print(f"警告: {source} 给出的类别 {cat!r} 不在策略库类目清单中，忽略",
              file=sys.stderr)
        return None

    # 1. --cards-file / STRATEGY_CARDS：.texts.json 路径 → basename 去后缀
    cards_file = args.cards_file or os.environ.get("STRATEGY_CARDS")
    if cards_file:
        cat = Path(cards_file).name
        if cat.endswith(".texts.json"):
            cat = cat[: -len(".texts.json")]
        hit = _check(cat, f"--cards-file/STRATEGY_CARDS ({cards_file})")
        if hit:
            return hit

    # 2. --category / STRATEGY_CATEGORY
    cat_arg = args.category or os.environ.get("STRATEGY_CATEGORY")
    if cat_arg:
        hit = _check(cat_arg, "--category/STRATEGY_CATEGORY")
        if hit:
            return hit

    die("无法解析策略类别。支持途径：--cards-file/STRATEGY_CARDS（.texts.json 路径）、"
        "--category/STRATEGY_CATEGORY。"
        f"可选类别（{len(candidates)} 个）: {'、'.join(candidates)}"
        "（禁止猜测，请显式指定）")


def parse_used_strategies(path):
    """已用策略文件（每行一个，可带 .md）→ 去 .md 的 id 列表。"""
    ids = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.endswith(".md"):
            s = s[:-3]
        if s:
            ids.append(s)
    return ids


# ---------------------------------------------------------------- --prepare

def cmd_prepare(args):
    out_dir = Path(args.out_dir).resolve()

    # 外部策略库根三态（valid / skipped / invalid）：
    #   未指定（env 与 CLI 皆无）→ 合法「未启用」：写机器可读 skip 标记后正常退出（exit 0），
    #     调用方（概设步骤6）据此走跳过分支——策略库是可选知识源，未配置不得阻塞任务。
    #   指定但无效（路径不存在/非目录）→ 硬停报错（exit 2）——用户显式意图失败，静默跳过
    #     会把配错的路径伪装成「未启用」。
    #   两态都以显式 status 区分，不与「检索过了但没有合适策略」混淆（原反混淆初衷由
    #   状态字段保住，不再靠阻塞保）。
    try:
        strategy_root = cardlib.resolve_strategy_root(args.strategy_root)
    except ValueError as e:
        die(str(e))
    if strategy_root is None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "run_inputs.json").write_text(
            json.dumps({
                "schema_version": 1,
                "op_name": args.op_name,
                "status": "skipped_no_library",
                "reason": (
                    f"未指定策略库：{cardlib.ENV_STRATEGY_ROOT} 未设置且未传 --strategy-root。"
                    "策略检索未执行，属合法跳过——不回退空库、不产出『无适用策略』结论。"),
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        out_json({"status": "skipped_no_library",
                  "run_inputs": str(out_dir / "run_inputs.json")})
        return
    try:
        valid_categories = cardlib.categories(strategy_root, args.md_dir)
    except ValueError as e:
        die(str(e))

    # 设计文档：本轮策略检索的输入（无算子代码、无 profiling）。
    design_doc = None
    if args.design_doc:
        dd = Path(args.design_doc)
        if not dd.is_file():
            die(f"设计文档不存在: {dd}")
        design_doc = str(dd.resolve())

    category, cat_source = resolve_category(args, valid_categories)

    # 卡片文件来源优先级：--cards-file > STRATEGY_CARDS 环境变量。
    # 无默认路径——卡片由 build_cards.py 在运行目录内生成，路径必须由调用方给出。
    cards_file = args.cards_file or os.environ.get("STRATEGY_CARDS")
    if not cards_file:
        die("未指定卡片文件。请先用 build_cards.py 生成本轮卡片，"
            "再用 --cards-file 指向 <out_dir>/cards/<category>.texts.json")
    cards_path = Path(cards_file).resolve()

    # 加载卡片库：不做门禁审计（格式/缺卡/孤儿卡不阻断选择，仅告警）；
    # 文件缺失或整体不可解析时无从粗筛，直接报错。
    excluded_ids = parse_used_strategies(args.used_strategies_file) if args.used_strategies_file else []
    rows, load_errors = cardlib.load_cards_file(cards_path)
    if rows is None:
        die(f"卡片文件不存在或不可解析: {cards_path}\n问题: {load_errors}\n"
            "提示：卡片由 build_cards.py 按运行期生成，请确认已生成本轮卡片且路径正确")
    if load_errors:
        print(f"警告: 卡片库存在 {len(load_errors)} 个格式问题（不做门禁，继续粗筛）: "
              f"{'；'.join(load_errors[:5])}", file=sys.stderr)
    all_ids = {r["strategy_id"] for r in rows}
    unknown_excluded = sorted(set(excluded_ids) - all_ids)
    if unknown_excluded:
        print(f"提示: 已用策略中有 {len(unknown_excluded)} 个不在本类别卡片库，忽略: "
              f"{unknown_excluded[:6]}", file=sys.stderr)
    pool_ids = sorted(all_ids - set(excluded_ids))

    # 记录本轮所见策略正文的版本：Phase 3 直读外部 md，卡片侧 sha 冻结保护不到正文，
    # 故用目录摘要把「本轮读的就是这一版」钉下来，供 finalize 复核漂移。
    try:
        src_digest = cardlib.catalog_digest(strategy_root, pool_ids, args.md_dir)
    except ValueError as e:
        die(f"计算策略正文摘要失败: {e}")

    out_dir.mkdir(parents=True, exist_ok=True)
    run_inputs = {
        "schema_version": 1,
        "op_name": args.op_name,
        "category": category,
        "category_source": cat_source,
        "strategy_root": str(strategy_root),
        "md_dir": args.md_dir,
        "source_md_digest": src_digest,
        "cards_path": str(cards_path),
        "cards_file_sha256": cardlib.sha256_file(cards_path),
        "card_count": len(rows),
        "excluded_ids": excluded_ids,
        "screening_pool_count": len(pool_ids),
        "out_dir": str(out_dir),
        "design_doc": design_doc,
    }
    (out_dir / "run_inputs.json").write_text(
        json.dumps(run_inputs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out_json({"status": "prepared", **run_inputs})
    return 0


# ---------------------------------------------------------------- --freeze-query

def _require(cond, errors, msg):
    if not cond:
        errors.append(msg)


def validate_query(q):
    """内置极简校验器（对齐 query.schema.json v2）。返回 errors 列表。"""
    errors = []

    def non_empty_str(v):
        return isinstance(v, str) and v.strip() != ""

    def evidence_list(ev):
        return (isinstance(ev, list) and len(ev) >= 1
                and all(isinstance(e, dict) and set(e) == {"path", "location", "detail"}
                        and all(non_empty_str(e.get(k)) for k in ("path", "location", "detail"))
                        for e in ev))

    _require(isinstance(q, dict), errors, "query 顶层须为对象")
    if errors:
        return errors
    _require(set(q) == set(QUERY_TOP_KEYS),
             errors, f"顶层键须恰好为 {QUERY_TOP_KEYS}（多: {sorted(set(q)-set(QUERY_TOP_KEYS))}，"
                     f"少: {sorted(set(QUERY_TOP_KEYS)-set(q))}）")
    _require(q.get("schema_version") == 2, errors, "schema_version 须为 2")

    sem = q.get("operator_semantics")
    _require(isinstance(sem, dict) and set(sem) == {"summary", "inputs_outputs", "computation"},
             errors, "operator_semantics 须恰好含 summary/inputs_outputs/computation")
    if isinstance(sem, dict):
        for k in ("summary", "inputs_outputs", "computation"):
            _require(non_empty_str(sem.get(k)), errors, f"operator_semantics.{k} 须为非空字符串")

    wl = q.get("workload")
    _require(isinstance(wl, dict) and set(wl) == {"shapes", "dtypes", "layouts", "distribution"},
             errors, "workload 须恰好含 shapes/dtypes/layouts/distribution")
    if isinstance(wl, dict):
        for k in ("shapes", "dtypes", "layouts"):
            v = wl.get(k)
            _require(isinstance(v, list) and all(non_empty_str(x) for x in v),
                     errors, f"workload.{k} 须为非空字符串数组")
        _require(isinstance(wl.get("distribution"), str), errors, "workload.distribution 须为字符串")

    obs = q.get("current_implementation")
    _require(isinstance(obs, list) and len(obs) >= 1,
             errors, "current_implementation 须为非空数组（至少 1 条有证据的观察）")
    for i, o in enumerate(obs if isinstance(obs, list) else [], 1):
        _require(isinstance(o, dict) and set(o) == {"observation", "evidence"},
                 errors, f"current_implementation[{i}] 须恰好含 observation/evidence")
        if isinstance(o, dict):
            _require(non_empty_str(o.get("observation")),
                     errors, f"current_implementation[{i}].observation 须为非空字符串")
            _require(evidence_list(o.get("evidence")),
                     errors, f"current_implementation[{i}].evidence 须≥1 条 path/location/detail 非空")

    hyps = q.get("bottleneck_hypotheses")
    _require(isinstance(hyps, list) and len(hyps) >= 1,
             errors, "bottleneck_hypotheses 须为非空数组（至少 1 条假设）")
    for i, h in enumerate(hyps if isinstance(hyps, list) else [], 1):
        _require(isinstance(h, dict) and set(h) == {"hypothesis", "confidence",
                                                    "supporting_evidence", "counter_evidence"},
                 errors, f"bottleneck_hypotheses[{i}] 键非法")
        if isinstance(h, dict):
            _require(non_empty_str(h.get("hypothesis")),
                     errors, f"bottleneck_hypotheses[{i}].hypothesis 须为非空字符串")
            c = h.get("confidence")
            _require(isinstance(c, (int, float)) and not isinstance(c, bool) and 0 <= c <= 1,
                     errors, f"bottleneck_hypotheses[{i}].confidence 须在 [0,1]")
            _require(evidence_list(h.get("supporting_evidence")),
                     errors, f"bottleneck_hypotheses[{i}].supporting_evidence 须≥1 条")
            ce = h.get("counter_evidence")
            _require(isinstance(ce, list), errors,
                     f"bottleneck_hypotheses[{i}].counter_evidence 须为数组（可为空）")
            if isinstance(ce, list) and ce:
                _require(evidence_list(ce), errors,
                         f"bottleneck_hypotheses[{i}].counter_evidence 非空时须为合法证据列表")

    for k in ("constraints", "current_optimizations", "missing_information"):
        v = q.get(k)
        _require(isinstance(v, list) and all(non_empty_str(x) for x in v),
                 errors, f"{k} 须为非空字符串数组")

    rh = q.get("retrieval_hints")
    _require(isinstance(rh, dict) and set(rh) == {"direct_strategy_query"},
             errors, "retrieval_hints 须恰好含 direct_strategy_query（v2 已移除原语/搜索动作假设）")
    if isinstance(rh, dict):
        _require(non_empty_str(rh.get("direct_strategy_query")),
                 errors, "retrieval_hints.direct_strategy_query 须为非空字符串")
    return errors


def cmd_freeze_query(args):
    out_dir = Path(args.out_dir).resolve()
    qpath = Path(args.query)
    if not qpath.is_file():
        die(f"query 文件不存在: {qpath}")
    try:
        query = json.loads(qpath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        die(f"query JSON 解析失败: {e}")
    errors = validate_query(query)
    if errors:
        out_json({"status": "rejected", "stage": "freeze-query", "errors": errors})
        raise SystemExit(2)
    out_dir.mkdir(parents=True, exist_ok=True)
    text = qpath.read_text(encoding="utf-8")
    (out_dir / "query.json").write_text(text, encoding="utf-8")
    (out_dir / "query.sha256.txt").write_text(cardlib.sha256_text(text) + "\n", encoding="utf-8")
    out_json({"status": "frozen", "query_path": str(out_dir / "query.json"),
              "query_sha256": cardlib.sha256_text(text),
              "observations": len(query["current_implementation"]),
              "hypotheses": len(query["bottleneck_hypotheses"])})
    return 0


# ---------------------------------------------------------------- --emit-screening

def load_run_inputs(out_dir):
    p = Path(out_dir) / "run_inputs.json"
    if not p.is_file():
        die(f"run_inputs.json 不存在（先跑 --prepare）: {p}")
    ri = json.loads(p.read_text(encoding="utf-8"))
    # 三态守卫：prepare 阶段已判定「未指定策略库」（skipped_no_library）时，下游子命令
    # 不存在可检索的卡片库——干净退出（exit 0），不把 skip 标记当缺字段报校验错。
    if ri.get("status") == "skipped_no_library":
        out_json({"status": "skipped_no_library",
                  "reason": ri.get("reason", ""),
                  "hint": "策略检索未启用（未指定策略库），无下游产物可生成"})
        raise SystemExit(0)
    return ri


def warn_if_md_drifted(ri):
    """复核外部策略正文是否在 prepare 之后被改写，漂移时告警（不阻断）。

    Phase 3 直接读外部 md 全文并"以 md 为准"，而 finalize 只校验路径存在与文件名匹配，
    从不校验内容——中途改库会让判定落在从未冻结过的正文上。这里与 finalize 的
    stage_selection 各查一次，把「本轮读到的是哪一版」这条事实显式化。

    按 prepare 时的同一口径重算：池 = 卡片库 id 全集 − 已用。
    """
    if not ri.get("strategy_root") or not ri.get("source_md_digest"):
        return
    try:
        rows, _ = cardlib.load_cards_file(Path(ri["cards_path"]))
        pool_ids = sorted({r["strategy_id"] for r in (rows or [])}
                          - set(ri.get("excluded_ids", [])))
        now = cardlib.catalog_digest(Path(ri["strategy_root"]), pool_ids,
                                     ri.get("md_dir", cardlib.MD_ROOT_DEFAULT))
    except (ValueError, OSError):
        return
    if now != ri["source_md_digest"]:
        print("警告: 外部策略正文自 prepare 后已变更（source_md_digest 不符）。"
              "Phase 3 以完整 md 为准，本轮判定可能混入未冻结的正文版本——"
              "如需严格可复现，请重跑 --prepare。", file=sys.stderr)


def cmd_emit_screening(args):
    out_dir = Path(args.out_dir).resolve()
    ri = load_run_inputs(out_dir)
    qpath = out_dir / "query.json"
    if not qpath.is_file():
        die(f"query.json 不存在（先跑 --freeze-query）: {qpath}")
    frozen_sha = (out_dir / "query.sha256.txt").read_text(encoding="utf-8").strip()
    query_text = qpath.read_text(encoding="utf-8")
    if cardlib.sha256_text(query_text) != frozen_sha:
        die("query.json 与 query.sha256.txt 不符（query 被改动后未重新冻结）")
    query = json.loads(query_text)
    # 召回时复验（对齐参考库召回脚本重验 Query 的行为）：冻结过的不代表现在仍合法
    q_errors = validate_query(query)
    if q_errors:
        out_json({"status": "rejected", "stage": "emit-screening", "errors": q_errors,
                  "hint": "query.json 未通过 schema 复验——修复后重新 --freeze-query"})
        raise SystemExit(2)

    cards_path = Path(ri["cards_path"])
    rows, errors = cardlib.load_cards_file(cards_path)
    if rows is None or errors:
        die(f"卡片文件不可用 {cards_path}: {errors}")
    if cardlib.sha256_file(cards_path) != ri["cards_file_sha256"]:
        die(f"卡片文件与 prepare 时不符（{cards_path} 已被修改）——重跑 --prepare")
    warn_if_md_drifted(ri)
    excluded = set(ri.get("excluded_ids", []))
    pool = [r for r in rows if r["strategy_id"] not in excluded]  # rows 已按 id 升序

    lines = [
        "# 策略粗筛工作单（screening worksheet）",
        "",
        f"- 类别: {ri['category']}    卡片总数: {len(rows)}    剔除已用: {len(excluded & {r['strategy_id'] for r in rows})}"
        f"    筛选池: {len(pool)}",
        f"- 卡片库 sha256: {ri['cards_file_sha256']}",
        "",
        "## 一、冻结 Query（粗筛的唯一算子侧输入）",
        "",
        "观察编号约定：`current_implementation` 按数组顺序编号 O001、O002…；"
        "`supported` 判定必须引用这些编号。",
        "",
        "```json",
        json.dumps(query, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 二、筛选池全量策略卡（按 strategy_id 升序；禁止预过滤/截断）",
        "",
    ]
    for r in pool:
        lines += [f"### {r['strategy_id']}", "", "```", r["text"], "```", ""]
    lines += [
        "## 三、任务：粗筛 Top10",
        "",
        "按 references/recall-screening.md 判据，从上面筛选池中选出 ≤10 个候选，"
        "输出 screening.json（格式见 SKILL.md Phase 3）。",
    ]
    ws = out_dir / "screening_worksheet.md"
    ws.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out_json({"status": "emitted", "worksheet": str(ws), "pool_count": len(pool),
              "card_count": len(rows), "excluded_in_pool": len(excluded & {r['strategy_id'] for r in rows})})
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--freeze-query", action="store_true")
    ap.add_argument("--emit-screening", action="store_true")
    ap.add_argument("--op-name", default=None)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--design-doc", default=None, help="需求/设计文档路径（Phase 1 Query 构建的输入）")
    ap.add_argument("--used-strategies-file", default=None)
    ap.add_argument("--cards-file", default=None)
    ap.add_argument("--category", default=None)
    ap.add_argument("--strategy-root", default=None,
                    help=f"外部策略库根（等价环境变量 {cardlib.ENV_STRATEGY_ROOT}）")
    ap.add_argument("--md-dir", default=cardlib.MD_ROOT_DEFAULT,
                    help=f"策略 md 树在库根下的目录名（默认 {cardlib.MD_ROOT_DEFAULT}）")
    ap.add_argument("--query", default=None, help="freeze-query 的输入 query.json")
    args = ap.parse_args()

    modes = [m for m, on in (("--prepare", args.prepare), ("--freeze-query", args.freeze_query),
                             ("--emit-screening", args.emit_screening)) if on]
    if len(modes) != 1:
        die("必须恰好指定 --prepare / --freeze-query / --emit-screening 之一")
    if args.prepare:
        if not args.op_name:
            die("--prepare 需要 --op-name")
        return cmd_prepare(args)
    if args.freeze_query:
        if not args.query:
            die("--freeze-query 需要 --query")
        return cmd_freeze_query(args)
    return cmd_emit_screening(args)


if __name__ == "__main__":
    sys.exit(main())
