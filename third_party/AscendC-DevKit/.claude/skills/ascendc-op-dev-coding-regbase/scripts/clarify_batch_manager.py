#!/usr/bin/env python3
"""AscendC Stage 3 clarification batch manager.

Used by the ascendc-dev orchestrator to split clarification questions into
batches (max 4 questions per batch, max 4 options per question), drive
AskUserQuestion rounds, and merge user answers back into a single answers.json.

Sub-commands:
    make-batches    Group questions.json into batches.json.
    next-batch      Return the next unanswered batch (or {"done": true}).
    answer-batch    Map raw user labels to structured answers for one batch.
    merge-answers   Merge one batch answer into answers.json.partial.
    finalize        Validate completeness and produce final answers.json.
    to-ask-yaml     Render a batch as AskUserQuestion YAML for the orchestrator.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

MAX_QUESTIONS_PER_BATCH = 4
MAX_OPTIONS_PER_QUESTION = 4

PRIORITY_ORDER = {"高": 0, "中": 1, "低": 2}


def load_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def die(msg: str) -> int:
    print(f"ERROR: {msg}", file=sys.stderr)
    return 1


def validate_questions(questions: dict) -> list[str]:
    errors: list[str] = []
    items = questions.get("items")
    if not items:
        errors.append("questions.json 'items' is empty or missing")
        return errors
    if not isinstance(items, list):
        errors.append("questions.json 'items' must be a list")
        return errors

    seen_ids = set()
    for item in items:
        qid = item.get("id")
        if not qid:
            errors.append("item missing 'id'")
            continue
        if qid in seen_ids:
            errors.append(f"duplicate item id '{qid}'")
        seen_ids.add(qid)

        opts = item.get("options")
        if not isinstance(opts, list):
            errors.append(f"item '{qid}' options must be a list")
            continue
        if len(opts) < 2:
            errors.append(f"item '{qid}' has fewer than 2 options")
        if len(opts) > MAX_OPTIONS_PER_QUESTION:
            errors.append(
                f"item '{qid}' has more than {MAX_OPTIONS_PER_QUESTION} options"
            )
        for idx, opt in enumerate(opts):
            for key in ("label", "value", "text"):
                if key not in opt:
                    errors.append(
                        f"item '{qid}' option {idx} missing '{key}'"
                    )
    return errors


def priority_key(item: dict) -> int:
    return PRIORITY_ORDER.get(item.get("priority", "中"), 1)


def make_batches(questions: dict) -> dict:
    items = sorted(questions.get("items", []), key=priority_key)
    batches: list[dict] = []
    current: list[dict] = []
    current_ids: list[str] = []

    record_dir = questions.get("record_dir", "")
    op_name = questions.get("op_name", "")

    for item in items:
        if len(current) >= MAX_QUESTIONS_PER_BATCH:
            batches.append(
                {
                    "batch_id": len(batches) + 1,
                    "record_dir": record_dir,
                    "op_name": op_name,
                    "item_ids": current_ids,
                    "questions": current,
                }
            )
            current = []
            current_ids = []
        current.append(item)
        current_ids.append(item["id"])

    if current:
        batches.append(
            {
                "batch_id": len(batches) + 1,
                "record_dir": record_dir,
                "op_name": op_name,
                "item_ids": current_ids,
                "questions": current,
            }
        )

    return {
        "version": "1.0",
        "record_dir": questions.get("record_dir", ""),
        "op_name": questions.get("op_name", ""),
        "total": len(items),
        "batch_count": len(batches),
        "batches": batches,
    }


def cmd_make_batches(args: argparse.Namespace) -> int:
    data = load_json(Path(args.questions))
    if data is None:
        return die(f"questions file not found: {args.questions}")
    errors = validate_questions(data)
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1
    batches = make_batches(data)
    save_json(Path(args.output), batches)
    print(
        f"OK: generated {batches['batch_count']} batches, total {batches['total']} items"
    )
    return 0


def cmd_next_batch(args: argparse.Namespace) -> int:
    batches = load_json(Path(args.batches))
    if batches is None:
        return die(f"batches file not found: {args.batches}")

    partial_path = Path(args.answers) if args.answers else None
    completed: set[int] = set()
    if partial_path and partial_path.exists():
        partial = load_json(partial_path)
        if partial is not None:
            completed = set(partial.get("completed_batches", []))

    for batch in batches["batches"]:
        bid = batch["batch_id"]
        if bid not in completed:
            save_json(Path(args.output), batch)
            print(f"OK: next batch={bid} items={batch['item_ids']}")
            return 0

    save_json(Path(args.output), {"batch_id": None, "done": True})
    print("OK: all batches completed")
    return 0


def _build_option_map(batch: dict) -> dict[str, dict]:
    """Build map from option label to full option metadata per question."""
    mapping: dict[str, dict] = {}
    for item in batch.get("questions", []):
        qid = item["id"]
        mapping[qid] = {opt["label"]: opt for opt in item.get("options", [])}
    return mapping


def cmd_answer_batch(args: argparse.Namespace) -> int:
    batch = load_json(Path(args.batch))
    if batch is None:
        return die(f"batch file not found: {args.batch}")

    raw_mapping = json.loads(args.mapping)
    if not isinstance(raw_mapping, dict):
        return die("mapping must be a JSON object like '{\"1\": \"A\"}'")

    option_map = _build_option_map(batch)
    answers: dict[str, dict] = {}
    for qid, label in raw_mapping.items():
        if qid not in option_map:
            return die(f"question id '{qid}' not in batch")
        opt = option_map[qid].get(label)
        if opt is None:
            return die(
                f"invalid label '{label}' for question '{qid}'"
            )
        answers[qid] = {
            "label": opt["label"],
            "value": opt["value"],
            "text": opt["text"],
            "description": opt.get("description", ""),
        }

    batch_answers = {
        "version": "1.0",
        "batch_id": batch.get("batch_id"),
        "record_dir": batch.get("record_dir", ""),
        "op_name": batch.get("op_name", ""),
        "answers": answers,
    }
    save_json(Path(args.output), batch_answers)
    print(f"OK: answered batch={batch['batch_id']} items={list(answers.keys())}")
    return 0


def cmd_merge_answers(args: argparse.Namespace) -> int:
    batch_answers = load_json(Path(args.batch))
    if batch_answers is None:
        return die(f"batch answers file not found: {args.batch}")

    partial_path = Path(args.answers)
    partial = load_json(partial_path)
    if partial is None:
        partial = {
            "version": "1.0",
            "record_dir": batch_answers.get("record_dir", ""),
            "op_name": batch_answers.get("op_name", ""),
            "completed_batches": [],
            "answers": {},
        }

    batch_id = batch_answers.get("batch_id")
    if batch_id is not None:
        completed = partial.setdefault("completed_batches", [])
        if batch_id in completed:
            print(f"WARN: batch {batch_id} already merged", file=sys.stderr)
        else:
            completed.append(batch_id)

    for qid, ans in batch_answers.get("answers", {}).items():
        partial["answers"][qid] = ans

    save_json(partial_path, partial)
    print(
        f"OK: merged batch {batch_id}, total answered={len(partial['answers'])}"
    )
    return 0


def cmd_finalize(args: argparse.Namespace) -> int:
    batches = load_json(Path(args.batches))
    if batches is None:
        return die(f"batches file not found: {args.batches}")
    partial = load_json(Path(args.answers))
    if partial is None:
        return die(f"partial answers file not found: {args.answers}")

    expected_ids = {
        item["id"]
        for batch in batches["batches"]
        for item in batch["questions"]
    }
    answered_ids = set(partial.get("answers", {}).keys())
    missing = expected_ids - answered_ids
    if missing:
        for m in sorted(missing):
            print(f"ERROR: missing answer for item {m}", file=sys.stderr)
        return 1

    final = {
        "version": "1.0",
        "record_dir": partial.get("record_dir", ""),
        "op_name": partial.get("op_name", ""),
        "completed_batches": partial.get("completed_batches", []),
        "answers": partial["answers"],
    }
    save_json(Path(args.output), final)
    print(f"OK: finalized answers for {len(final['answers'])} items")
    return 0


def _yaml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def cmd_to_ask_yaml(args: argparse.Namespace) -> int:
    batch = load_json(Path(args.batch))
    if batch is None:
        return die(f"batch file not found: {args.batch}")

    print("AskUserQuestion:")
    print("  questions:")
    for item in batch.get("questions", []):
        print(f"    - question: \"{_yaml_escape(item.get('question', ''))}\"")
        print(f"      header: \"{_yaml_escape(item.get('header', item.get('id', '')))}\"")
        print(f"      multiSelect: false")
        print(f"      options:")
        for opt in item.get("options", []):
            label_text = f"{opt['label']}: {opt['text']}"
            print(f"        - label: \"{_yaml_escape(label_text)}\"")
            desc = opt.get("description", "")
            if desc:
                print(f"          description: \"{_yaml_escape(desc)}\"")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AscendC Stage 3 clarification batch manager"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("make-batches", help="Group questions.json into batches.json")
    p.add_argument("--questions", required=True, help="Input questions.json path")
    p.add_argument("--output", required=True, help="Output batches.json path")

    p = sub.add_parser("next-batch", help="Get next unanswered batch")
    p.add_argument("--batches", required=True, help="Input batches.json path")
    p.add_argument("--answers", default=None, help="Input answers.json.partial path")
    p.add_argument("--output", required=True, help="Output next_batch.json path")

    p = sub.add_parser("answer-batch", help="Map user labels to structured batch answers")
    p.add_argument("--batch", required=True, help="Input batch.json path")
    p.add_argument(
        "--mapping",
        required=True,
        help='JSON mapping from question id to chosen option label, e.g. \'{"1":"A","2":"A"}\'',
    )
    p.add_argument("--output", required=True, help="Output answers_batch_N.json path")

    p = sub.add_parser("merge-answers", help="Merge batch answers into partial")
    p.add_argument("--batch", required=True, help="Input answers_batch_N.json path")
    p.add_argument("--answers", required=True, help="Input/output answers.json.partial path")

    p = sub.add_parser("finalize", help="Validate and produce final answers.json")
    p.add_argument("--batches", required=True, help="Input batches.json path")
    p.add_argument("--answers", required=True, help="Input answers.json.partial path")
    p.add_argument("--output", required=True, help="Output answers.json path")

    p = sub.add_parser("to-ask-yaml", help="Render batch as AskUserQuestion YAML")
    p.add_argument("--batch", required=True, help="Input batch.json path")

    args = parser.parse_args()
    handlers = {
        "make-batches": cmd_make_batches,
        "next-batch": cmd_next_batch,
        "answer-batch": cmd_answer_batch,
        "merge-answers": cmd_merge_answers,
        "finalize": cmd_finalize,
        "to-ask-yaml": cmd_to_ask_yaml,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
