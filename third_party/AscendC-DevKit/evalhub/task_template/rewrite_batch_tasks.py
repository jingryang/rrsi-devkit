#!/usr/bin/env python3
"""
Deterministically rewrite the DEFAULT_TASKS block of batch_self_evolve.sh.

Usage:
    python3 rewrite_batch_tasks.py <script_path> <task_rel>
    e.g. python3 rewrite_batch_tasks.py \
        /app/src/AscendC-DevKit/scripts/batch_self_evolve.sh tasks/level1/task_exp

Behavior:
  * Locates the DEFAULT_TASKS=( ... ) block by LINE POSITION (no fragile regex
    over file content), and replaces the whole block with a single entry.
  * Idempotent: if the block already contains exactly <task_rel>, exits 0 with
    no change.
  * Self-verifies with `bash -n` after writing.
  * On any failure exits NON-ZERO and prints a reason to stderr, so the caller
    (agent) must stop and must NOT launch the workflow.

Exit codes: 0 = ok; 1 = block missing / bash -n failed; 2 = bad usage.
"""
import os
import re
import subprocess
import sys
import tempfile


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    script_path, task_rel = sys.argv[1], sys.argv[2]

    try:
        with open(script_path, encoding="utf-8") as f:
            lines = f.read().split("\n")
    except OSError as e:
        print(f"[FAIL] 无法读取 {script_path}: {e}", file=sys.stderr)
        return 1

    # 1) find the opening line "DEFAULT_TASKS=(" (whitespace-insensitive)
    start = next(
        (i for i, ln in enumerate(lines) if re.match(r"^\s*DEFAULT_TASKS\s*=\s*\(\s*$", ln)),
        None,
    )
    if start is None:
        print(f"[FAIL] 未找到 DEFAULT_TASKS=( 起始行: {script_path}", file=sys.stderr)
        return 1

    # 2) find the closing line: a lone ")" (block must be well-formed)
    end = next(
        (j for j in range(start + 1, len(lines)) if re.match(r"^\s*\)\s*$", lines[j])),
        None,
    )
    if end is None:
        print(f"[FAIL] DEFAULT_TASKS 块的收尾 ) 未找到（块可能损坏）: {script_path}", file=sys.stderr)
        return 1

    # 3) idempotency: already exactly one entry == task_rel ?
    entries = [ln.strip() for ln in lines[start + 1 : end]]
    if entries == [task_rel]:
        print(f"[OK] DEFAULT_TASKS 已为本算子，无需修改: {task_rel}")
        return 0

    # 4) replace the whole block (keep original indentation)
    indent = re.match(r"^\s*", lines[start]).group(0)
    new_block = [f"{indent}DEFAULT_TASKS=(", f"{indent}    {task_rel}", f"{indent})"]
    lines[start : end + 1] = new_block

    out = "\n".join(lines)

    # 5) self-verify syntax on a TEMP copy BEFORE touching the real file (atomic):
    #    if verification fails (or bash is unavailable), the target stays untouched.
    try:
        fd, tmp = tempfile.mkstemp(
            dir=os.path.dirname(script_path) or ".", suffix=".sh"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(out)
        try:
            r = subprocess.run(["bash", "-n", tmp])
        except FileNotFoundError:
            print("[FAIL] 未找到 bash，无法做语法自检，拒绝改写（请确认容器内有 bash）", file=sys.stderr)
            return 1
        finally:
            os.unlink(tmp)
    except OSError as e:
        print(f"[FAIL] 语法自检临时文件失败: {e}", file=sys.stderr)
        return 1

    if r.returncode != 0:
        print(f"[FAIL] 改写后 bash -n 语法检查未通过，原文件未被修改: {script_path}", file=sys.stderr)
        return 1

    try:
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(out)
    except OSError as e:
        print(f"[FAIL] 无法写入 {script_path}: {e}", file=sys.stderr)
        return 1

    print(
        f"[OK] DEFAULT_TASKS 改写为: {task_rel} "
        f"(原块第 {start + 1}–{end + 1} 行被替换)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
