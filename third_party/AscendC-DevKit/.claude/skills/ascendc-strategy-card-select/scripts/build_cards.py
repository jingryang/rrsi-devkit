#!/usr/bin/env python3
"""七字段短卡生成器：从外部策略库的卡元数据投影出检索用的短卡。

用法：
    build_cards.py --strategy-root <path> (--category <c> | --all) --out <dir>
                   [--curator-scripts <path>] [--retrieval-terms <path>]
                   [--md-dir strategies]

产物（不随仓跟踪，按运行期生成；这是 §2.5 单源与 sha256 冻结纪律的共同要求）：
    <out>/cards/common.texts.json              全类通用池
    <out>/cards/op-class/<class>.texts.json    common ∪ 该类 的合并池

## 字段来源（「动作」是唯一必填，无来源的字段整行省略）

| 字段   | 来源 |
|--------|------|
| 动作   | `mechanism`；`classification` 为 negative_boundary/lesson 时加证伪前缀 |
| 适用   | `applicability.required_conditions` |
| 限制   | `applicability.excluded_conditions` + `.constraints` + `risks` |
| 范围   | generality 标签 + `operator_scope` |
| 检索词 | `resources/retrieval_terms.json`（唯一需 LLM 补齐的字段）；缺失时回退 |
| 机会   | `feature_signature.bottleneck`；缺失时回退 `intent` |

## 为什么不产出「代价」字段

上游格式含「代价」，但本策略库的卡元数据里**没有任何字段对应它**。凭空编造一个值会
制造一个看似有依据、实则无来源的判据，正是 §2.12 要禁止的"错误诱导源"。故整个字段
从 cardlib 的 FIELD_LABELS 中移除，而不是留空占位——留一个永远填不上的字段只会诱导
后来者去编。若策略库将来新增代价来源，再加回字段即可。

## 证伪前缀的作用

粗筛规则把「动作」以 `反模式：`/`负向边界：` 开头的卡识别为**已证伪方向**，命中时选入
并标 uncertain，由全 md 核对阶段确认边界与逃生路径。没有前缀，这 42 张卡（30 张
negative_boundary + 12 张 lesson）会以正面策略的面貌进入粗筛，误导判定。
映射：negative_boundary → 「负向边界：」，lesson → 「反模式：」。

## 确定性

同一输入两次运行必须字节一致：条目按 strategy_id 升序、无时间戳、无随机。
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cardlib as C  # noqa: E402
from _strategy_catalog import StrategyCatalog  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TERMS = SKILL_DIR / "resources" / "retrieval_terms.json"

NEGATIVE_PREFIX = {
    "negative_boundary": "负向边界：",
    "lesson": "反模式：",
}


def die(msg: str, code: int = 2):
    print(f"错误：{msg}", file=sys.stderr)
    raise SystemExit(code)


def clip(text: str, budget: int) -> str:
    """按 `；` 边界裁剪到预算内；无可用边界时硬截断。"""
    if len(text) <= budget:
        return text
    cut = text.rfind("；", 0, budget)
    if cut > 0:
        return text[:cut]
    return text[:budget]


def join_nonempty(values, sep: str = "；") -> str:
    if not isinstance(values, list):
        return ""
    return sep.join(str(v).strip() for v in values if str(v).strip())


def field_line(label: str, content: str) -> str:
    """渲染一行；内容为空则整行省略（空字段不是「无约束」，是「无来源」）。"""
    content = (content or "").strip()
    if not content:
        return ""
    return f"{label}：{clip(content, C.FIELD_BUDGETS[label])}"


def build_text(entry: dict, terms: dict, fallbacks: list) -> str:
    """把一张卡的元数据投影为六字段短卡正文。"""
    slug = entry["slug"]
    classification = str(entry.get("classification", ""))
    mech = str(entry.get("mechanism", "") or "").strip()
    action = NEGATIVE_PREFIX.get(classification, "") + mech

    app = entry.get("applicability") or {}
    applicable = join_nonempty(app.get("required_conditions"))
    limits = join_nonempty(
        list(app.get("excluded_conditions") or [])
        + list(app.get("constraints") or [])
        + list(entry.get("risks") or []))

    generality = str(entry.get("generality", ""))
    if generality == "op_class":
        gen_tag = f"op-class：{entry.get('operator_class', '')}"
    else:
        gen_tag = "common（跨类通用）"
    scope = join_nonempty([gen_tag, str(entry.get("operator_scope", "") or "")])

    term = str(terms.get(slug, "") or "").strip()
    if not term:
        sig = entry.get("feature_signature") or {}
        parts = [str(sig.get("pattern", "") or "")]
        parts += [str(x) for x in (sig.get("structure") or [])]
        parts += [str(x) for x in (sig.get("bottleneck") or [])]
        term = join_nonempty(parts, " ")
        fallbacks.append(slug)

    sig = entry.get("feature_signature") or {}
    opportunity = join_nonempty(sig.get("bottleneck"))
    if not opportunity:
        opportunity = str(entry.get("intent", "") or "")

    lines = [
        field_line("动作", action),
        field_line("适用", applicable),
        field_line("限制", limits),
        field_line("范围", scope),
        field_line("检索词", term),
        field_line("机会", opportunity),
    ]
    return "\n".join(x for x in lines if x)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="生成七字段检索短卡")
    ap.add_argument("--strategy-root", required=True,
                    help=f"外部策略库根（等价环境变量 {C.ENV_STRATEGY_ROOT}）")
    ap.add_argument("--md-dir", default=C.MD_ROOT_DEFAULT,
                    help=f"策略 md 树在库根下的目录名（默认 {C.MD_ROOT_DEFAULT}）")
    ap.add_argument("--curator-scripts", default=None,
                    help="策略库 _catalog.py 所在目录（默认由 strategy-root 派生）")
    ap.add_argument("--retrieval-terms", default=str(DEFAULT_TERMS),
                    help="slug → 检索词 的表（默认 skill 内 resources/retrieval_terms.json）")
    ap.add_argument("--out", required=True, help="产物根目录（其下写 cards/）")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--category", help="只生成某一类的合并池")
    g.add_argument("--all", action="store_true", help="生成全部池")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    root = Path(args.strategy_root).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()

    try:
        valid_categories = C.categories(root, args.md_dir)
    except ValueError as e:
        die(str(e))
    if args.category and args.category not in valid_categories:
        die(f"非法类别 {args.category!r}。可选类别（{len(valid_categories)} 个）: "
            f"{'、'.join(valid_categories)}")

    terms_file = Path(args.retrieval_terms).expanduser()
    terms = {}
    if terms_file.is_file():
        raw = json.loads(terms_file.read_text(encoding="utf-8"))
        terms = raw.get("terms", raw) if isinstance(raw, dict) else {}
        if not isinstance(terms, dict):
            die(f"{terms_file}: terms 须为对象")
    else:
        print(f"警告：检索词表不存在，全部回退：{terms_file}", file=sys.stderr)

    try:
        catalog = StrategyCatalog(root, args.curator_scripts)
    except ValueError as e:
        die(str(e))
    entries, card_errors = catalog.load_all()
    if not entries:
        die(f"策略库中未加载到任何卡片（root={root}）")

    by_slug = {}
    for item in entries:
        slug = item["entry"].get("slug")
        if slug:
            by_slug[slug] = item

    targets = valid_categories if args.all else [args.category]
    report = {"strategy_root": str(root), "md_dir": args.md_dir,
              "pools": {}, "card_errors": card_errors, "terms_fallback": []}
    all_errors = []

    for category in targets:
        try:
            pool_ids = C.pool_members(root, category, args.md_dir)
        except ValueError as e:
            die(str(e))
        rows = []
        missing = sorted(i for i in pool_ids if i not in by_slug)
        for slug in sorted(pool_ids):
            item = by_slug.get(slug)
            if item is None:
                continue
            text = build_text(item["entry"], terms, report["terms_fallback"])
            rows.append({"strategy_id": slug, "text": text,
                         "text_sha256": C.sha256_text(text)})
        errs = C.validate_card_rows(rows, source=f"{category}.texts.json")
        all_errors.extend(errs)
        rel = (Path("cards") / f"{category}.texts.json"
               if category == C.COMMON_CATEGORY
               else Path("cards") / C.OP_CLASS_DIR / f"{category}.texts.json")
        C.write_text_atomic(out / rel, C.render_cards_doc(rows))
        report["pools"][category] = {
            "path": str(out / rel), "count": len(rows),
            "skipped_not_in_catalog": missing,
        }

    report["terms_fallback"] = sorted(set(report["terms_fallback"]))
    report["ok"] = not all_errors and not card_errors
    report["errors"] = all_errors

    if not args.quiet:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    if card_errors:
        print(f"警告：{len(card_errors)} 张卡元数据解析失败（已跳过）", file=sys.stderr)
    if report["terms_fallback"]:
        print(f"警告：{len(report['terms_fallback'])} 张卡缺检索词，已用结构标签回退："
              f"{'、'.join(report['terms_fallback'][:5])}"
              f"{' 等' if len(report['terms_fallback']) > 5 else ''}", file=sys.stderr)
    if all_errors:
        print(f"错误：生成物未通过卡片格式校验（{len(all_errors)} 条）", file=sys.stderr)
        for e in all_errors[:10]:
            print(f"  {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
