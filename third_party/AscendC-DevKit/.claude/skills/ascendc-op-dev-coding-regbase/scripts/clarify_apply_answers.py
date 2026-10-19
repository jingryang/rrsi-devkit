#!/usr/bin/env python3
"""AscendC Stage 3 clarification atomic apply tool.

Reads clarification.md and answers.json, replaces all [待澄清] markers with
[已澄清], injects the selected answer text, and writes the entire file back
in one shot. This eliminates the need for multiple Edit/Update calls.

Usage:
    python3 clarify_apply_answers.py \
        --clarification /path/to/clarification.md \
        --answers /path/to/answers.json \
        [--output /path/to/clarification.md]

If --output is omitted, the input clarification.md is overwritten.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def save_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def die(msg: str) -> int:
    print(f"ERROR: {msg}", file=sys.stderr)
    return 1


def apply_answers(text: str, answers: dict[str, Any]) -> tuple[str, int, int]:
    """Return (new_text, replaced_count, missing_count)."""

    # Match lines that contain an item header and a [待澄清] marker.
    # Supported formats:
    #   ### 项 1 — 标题 ... [待澄清]
    #   - 项 1 — 标题 ... [待澄清]
    #   **项 1** ... [待澄清]
    header_pattern = re.compile(
        r"^(?P<prefix>(?P<heading>###|\s*[-*]|\*\*)\s*)"
        r"(?P<body>项\s*(?P<id>\d+)[^\n]*?)"
        r"(?P<marker>\[待澄清\])"
        r"(?P<suffix>[^\n]*)$",
        re.MULTILINE,
    )

    replaced = 0
    missing = 0
    positions: list[tuple[int, int, str, str, str]] = []

    for m in header_pattern.finditer(text):
        qid = m.group("id")
        ans = answers.get(qid)
        if ans is None:
            missing += 1
            continue

        start, end = m.span()
        prefix = m.group("prefix")
        body = m.group("body")
        suffix = m.group("suffix")
        value = ans.get("value", "")
        answer_text = ans.get("text", "")
        description = ans.get("description", "")

        conclusion = f"\n{prefix}  **澄清结论**：选项 {value} — {answer_text}"
        if description:
            conclusion += f"（{description}）"

        new_line = f"{prefix}{body}[已澄清]{suffix}{conclusion}"
        positions.append((start, end, new_line, qid, value))

    # Apply replacements from end to start so indices remain valid.
    new_text = text
    for start, end, replacement, qid, value in reversed(positions):
        new_text = new_text[:start] + replacement + new_text[end:]
        replaced += 1

    return new_text, replaced, missing


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Atomically apply clarification answers to clarification.md"
    )
    parser.add_argument("--clarification", required=True, help="Input clarification.md path")
    parser.add_argument("--answers", required=True, help="Input answers.json path")
    parser.add_argument("--output", default=None, help="Output path (default: overwrite input)")
    args = parser.parse_args()

    clarification_path = Path(args.clarification)
    answers_path = Path(args.answers)
    output_path = Path(args.output) if args.output else clarification_path

    if not clarification_path.exists():
        return die(f"clarification file not found: {args.clarification}")
    if not answers_path.exists():
        return die(f"answers file not found: {args.answers}")

    text = load_text(clarification_path)
    answers_data = load_json(answers_path)
    answers = answers_data.get("answers", {})

    if not answers:
        return die("answers.json contains no answers")

    new_text, replaced, missing = apply_answers(text, answers)

    save_text(output_path, new_text)
    print(f"OK: applied {replaced} answers, {missing} missing, wrote {output_path}")
    return 0 if missing == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
