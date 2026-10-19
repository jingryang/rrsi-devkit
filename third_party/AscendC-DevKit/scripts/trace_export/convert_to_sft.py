#!/usr/bin/env python3
"""
Convert the reconstructed opencode request records (from
reconstruct_opencode_request.py, saved under <input_dir>) to 2.0 SFT JSONL,
in the 2.0 SFT schema (version/meta_info/tools/messages).

Each canonical record becomes ONE 2.0 SFT record, written as one JSONL line:

    {version: "2.0.0", meta_info, tools, messages}
    messages: [system, user, assistant(reasoning_content/content/tool_calls), tool, ...]

Thinking split (快慢思考):
    - slow_thinking.jsonl — at least one assistant turn carries non-empty
      reasoning_content (慢思考);
    - fast_thinking.jsonl — ALL assistant turns have empty reasoning_content (快思考).

Ordering: within each JSONL file, sessions are strictly ordered by their start
time (session.time_created), ascending.

teacher (教师模型): defaults to each record's OWN logged model id
(session.model.id — the model that actually generated the trajectory);
--teacher overrides it for all records.

Structural normalization (kept for SFT validity): consecutive assistant turns
are merged, trailing tool messages truncated, tool_calls removed from the final
assistant turn, consecutive byte-identical user messages collapsed (backoff-
resume replays append the same framework feedback to the db multiple times
while the model answered only once — the SFT record keeps what the model
actually saw).

Usage:
    python3 convert_to_sft.py [--input-dir canonical] [--output-dir test]
                              [--teacher MODEL_ID]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_INPUT_DIR = Path(__file__).resolve().parent / "canonical"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "test"

# —— meta_info constants (2.0 SFT schema) ————————————————
# All instance-facing fields are configurable at call time; the constants
# here are only non-instance defaults. teacher derives per record from the
# session's own logged model id (derive_teacher); owner defaults to a neutral
# placeholder that users override per export (--owner / shell OWNER var).
DEFAULT_META = {
    "teacher": "",
    "query_source": "operator",
    "response_generate_time": "",
    "response_update_time": "",
    "owner": "unknown",
    "language": "en",
    "category": "code",
    "rounds": 0,
    "unique_info": {},
}


def detect_language(text: str) -> str:
    """Return 'zh' when Chinese chars dominate (>5%), else 'en'."""
    if not text:
        return "en"
    chinese = len(re.findall(r'[\u4e00-\u9fff]', text))
    total = len(text.strip())
    if total == 0:
        return "en"
    return "zh" if chinese / total > 0.05 else "en"


def derive_teacher(record: dict) -> str:
    """The logged teacher: the session's own model id (what actually ran)."""
    model = record.get("session", {}).get("model")
    if isinstance(model, dict):
        return model.get("id", "") or ""
    if isinstance(model, str):
        return model
    return ""


def _text_content(content) -> str:
    """Join an OpenAI-compatible content array into a plain string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    texts = [b.get("text", "") for b in content
             if isinstance(b, dict) and b.get("type") == "text" and b.get("text")]
    return "\n\n".join(texts)


def _reasoning_content(reasoning) -> str:
    """Join reasoning (list of strings or a string) with newlines."""
    if not reasoning:
        return ""
    if isinstance(reasoning, str):
        return reasoning
    return "\n".join(r for r in reasoning if r)


def convert_tools(tools: list[dict]) -> list[dict]:
    """Map reconstructed tools {name, description, input_schema} to the 2.0
    SFT shape {type: function, function: {name, description, parameters}}."""
    out = []
    for t in tools or []:
        params = dict(t.get("input_schema") or {})
        if "$schema" not in params:
            params = {"$schema": "https://json-schema.org/draft/2020-12/schema", **params}
        out.append({
            "type": "function",
            "function": {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": params,
            },
        })
    return out


def convert_record(record: dict, meta_overrides: dict | None = None) -> dict:
    """Convert one canonical record to a 2.0 SFT record (no dropping).

    ``meta_overrides``: {teacher/owner/query_source/category: value}; absent
    keys keep defaults — teacher derives from the session's own logged model
    id (与日志记录保持一致), owner falls back to "unknown".
    """
    overrides = meta_overrides or {}
    session = record.get("session", {})
    provider = record.get("messages", {}).get("provider", [])

    converted: list[dict] = [{"role": "system", "content": record.get("system", "")}]
    all_text = ""
    for msg in provider:
        role = msg.get("role")
        if role == "user":
            text = _text_content(msg.get("content"))
            if text:
                prev = converted[-1]
                if prev.get("role") == "user" and prev.get("content") == text:
                    # Consecutive byte-identical user message: a resume/retry
                    # replay artifact (the model answered only once) — collapse.
                    continue
                converted.append({"role": "user", "content": text})
                all_text += text
        elif role == "assistant":
            ast = {
                "role": "assistant",
                "reasoning_content": _reasoning_content(msg.get("reasoning_content")),
                "content": _text_content(msg.get("content")),
            }
            tool_calls = msg.get("tool_calls") or []
            if tool_calls:
                ast["tool_calls"] = tool_calls
            converted.append(ast)
            all_text += ast["content"]
        elif role == "tool":
            converted.append({
                "role": "tool",
                "tool_call_id": msg.get("tool_call_id", ""),
                "content": msg.get("content", ""),
            })

    # Merge consecutive assistant turns (no tool result in between) so the
    # sequence stays SFT-valid.
    merged: list[dict] = [converted[0]]
    for m in converted[1:]:
        prev = merged[-1]
        if m["role"] == "assistant" and prev["role"] == "assistant":
            prev_c, curr_c = prev.get("content", "") or "", m.get("content", "") or ""
            prev["content"] = (prev_c + "\n\n" + curr_c).strip() if prev_c and curr_c else (prev_c or curr_c)
            prev_r, curr_r = prev.get("reasoning_content", "") or "", m.get("reasoning_content", "") or ""
            prev["reasoning_content"] = (prev_r + "\n" + curr_r).strip() if prev_r and curr_r else (prev_r or curr_r)
            if "tool_calls" in m:
                prev["tool_calls"] = m["tool_calls"]
        else:
            merged.append(m)
    converted = merged

    # Truncate trailing tool messages so the last message is assistant.
    while len(converted) > 1 and converted[-1]["role"] != "assistant":
        converted.pop()
    if converted and converted[-1]["role"] == "assistant":
        converted[-1].pop("tool_calls", None)

    # 快慢思考: all assistant reasoning empty → fast; any non-empty → slow.
    assistant_reasoning = [
        m.get("reasoning_content", "") or ""
        for m in converted if m["role"] == "assistant"
    ]
    has_thinking = any(r.strip() for r in assistant_reasoning)

    assistant_count = sum(1 for m in converted if m["role"] == "assistant")
    today = datetime.now().strftime("%Y-%m-%d")
    meta = dict(DEFAULT_META)
    meta["teacher"] = overrides.get("teacher") or derive_teacher(record)
    meta["owner"] = overrides.get("owner") or DEFAULT_META["owner"]
    meta["query_source"] = overrides.get("query_source") or DEFAULT_META["query_source"]
    meta["category"] = overrides.get("category") or DEFAULT_META["category"]
    meta["response_generate_time"] = today
    meta["response_update_time"] = today
    meta["rounds"] = assistant_count
    meta["language"] = detect_language(all_text)
    meta["unique_info"] = {"session_id": session.get("id", "")}

    return {
        "version": "2.0.0",
        "meta_info": meta,
        "tools": convert_tools(record.get("tools", [])),
        "messages": converted,
        "_has_thinking": has_thinking,
    }


def check_record(rec: dict) -> list[str]:
    """Quality checks on one 2.0 record. Return issue strings (empty = clean)."""
    issues: list[str] = []
    sid = rec.get("meta_info", {}).get("unique_info", {}).get("session_id", "?")
    msgs = rec.get("messages", [])
    tools = {t.get("function", {}).get("name") for t in rec.get("tools", [])}

    # ① 结构：首条 system、末条 assistant、角色合法
    if not msgs or msgs[0].get("role") != "system":
        issues.append(f"{sid}: 首条消息不是 system")
    if not msgs or msgs[-1].get("role") != "assistant":
        issues.append(f"{sid}: 末条消息不是 assistant")
    for prev, cur in zip(msgs, msgs[1:]):
        if prev.get("role") == "assistant" and cur.get("role") == "assistant":
            issues.append(f"{sid}: 存在相邻 assistant 消息（未合并干净）")
        if (prev.get("role") == "user" and cur.get("role") == "user"
                and prev.get("content") == cur.get("content")):
            issues.append(f"{sid}: 存在相邻且内容相同的 user 消息（未去重干净）")

    # ② 工具注册：每条 tool_calls 的 name 必须在 tools 中
    for m in msgs:
        if m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls", []):
            name = tc.get("function", {}).get("name", "")
            if name and name not in tools:
                issues.append(f"{sid}: 未注册的 tool_call '{name}'")

    # ③ 工具结果配对：assistant 的每个 tool_call 都有对应 tool 消息，反之亦然
    call_ids = [tc.get("id") for m in msgs if m.get("role") == "assistant"
                for tc in m.get("tool_calls", [])]
    result_ids = [m.get("tool_call_id") for m in msgs if m.get("role") == "tool"]
    orphan = [cid for cid in result_ids if cid not in call_ids]
    missing = [cid for cid in call_ids if cid not in result_ids]
    if orphan:
        issues.append(f"{sid}: {len(orphan)} 个 tool 结果无对应 tool_call {orphan[:3]}")
    if missing:
        issues.append(f"{sid}: {len(missing)} 个 tool_call 无对应 tool 结果 {missing[:3]}")

    # ④ 快慢思考自洽：fast 文件不应含 reasoning（由调用方按文件归属判定）
    return issues


def export_jsonl(records: list[dict], output_dir: Path,
                 **meta_overrides) -> tuple[int, int, int]:
    """Convert canonical records → slow/fast JSONL + quality checks.

    Records are sorted by session start time before writing, so both files
    are strictly time-ordered by construction. ``meta_overrides`` accepts
    teacher/owner/query_source/category. Returns (slow_count, fast_count,
    issue_count); checks are report-only (no data dropped).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    loaded = sorted(records, key=lambda r: r.get("session", {}).get("time_created", 0))

    slow, fast = [], []
    for record in loaded:
        converted = convert_record(record, meta_overrides=meta_overrides)
        (slow if converted.pop("_has_thinking") else fast).append(converted)

    slow_path = output_dir / "slow_thinking.jsonl"
    fast_path = output_dir / "fast_thinking.jsonl"
    with slow_path.open("w", encoding="utf-8") as f:
        for r in slow:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with fast_path.open("w", encoding="utf-8") as f:
        for r in fast:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"slow_thinking (有思考): {len(slow)} -> {slow_path}")
    print(f"fast_thinking (全空)  : {len(fast)} -> {fast_path}")
    print(f"Total converted: {len(slow) + len(fast)}")

    total_issues = 0
    for path, bucket in ((slow_path, slow), (fast_path, fast)):
        n_ok = n_issue = 0
        for rec in bucket:
            issues = check_record(rec)
            if issues:
                n_issue += 1
                for it in issues:
                    print(f"[CHECK FAIL] {path.name}: {it}")
            else:
                n_ok += 1
        print(f"[CHECK {'OK' if n_issue == 0 else 'FAIL'}] {path.name}: "
              f"{n_ok} clean / {n_issue} with issues")
        total_issues += n_issue

    print(f"[ORDER OK] {slow_path.name} / {fast_path.name} "
          f"(sorted by session.time_created before write)")
    return len(slow), len(fast), total_issues


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR,
                    help="directory of reconstructed canonical records (default: canonical/)")
    ap.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
                    help="where to write the two JSONL files (default: test/)")
    ap.add_argument("--teacher", default=None,
                    help="override meta_info.teacher for ALL records "
                         "(default: each record's own logged session model id)")
    ap.add_argument("--owner", default=None,
                    help="meta_info.owner (default: unknown)")
    ap.add_argument("--query-source", default=None,
                    help="meta_info.query_source (default: operator)")
    ap.add_argument("--category", default=None,
                    help="meta_info.category (default: code)")
    args = ap.parse_args(argv)

    if not args.input_dir.is_dir():
        print(f"input dir not found: {args.input_dir}", file=sys.stderr)
        return 2

    files = sorted(args.input_dir.glob("*.json"))
    print(f"Found {len(files)} records in {args.input_dir}")

    loaded = []
    for path in files:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001 — per-file best-effort
            print(f"[ERROR] {path.name}: {e}", file=sys.stderr)
            continue
        loaded.append(record)

    overrides = {k: v for k, v in (("teacher", args.teacher), ("owner", args.owner),
                                   ("query_source", args.query_source),
                                   ("category", args.category)) if v is not None}
    _, _, total_issues = export_jsonl(loaded, args.output_dir, **overrides)
    return 0 if total_issues == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
