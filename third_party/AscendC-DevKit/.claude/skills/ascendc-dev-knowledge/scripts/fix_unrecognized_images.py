#!/usr/bin/env python3
"""
修复 [图片无法识别] / [公式无法识别] 占位符

扫描 references/ 下已转换的 markdown 文件，找出 Vision API 转换失败的占位符，
从 git 历史中恢复原始图片引用和图片文件。不调用 Vision API。

用法:
    python3 fix_unrecognized_images.py --scan                    # 扫描统计
    python3 fix_unrecognized_images.py --fix                     # 执行恢复
    python3 fix_unrecognized_images.py --fix --dry-run           # 预览不写入
    python3 fix_unrecognized_images.py --fix --limit 5           # 限制处理文件数
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Import constants from convert_images_to_text
# ---------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).resolve().parent))
from convert_images_to_text import CONVERTED_MARKER

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent / "references"
REPO_ROOT = SCRIPT_DIR.parent.parent.parent  # ascendskills/
PRE_CONVERSION_COMMIT = "9b6ac1e"
LOG_FILE = SCRIPT_DIR / "fix_unrecognized.log"

IMAGE_REF_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
FAILURE_PATTERN = re.compile(
    r"<!-- img2text -->\n"
    r"(?:```(?:text)?\n)?"          # optional opening code fence
    r"\[(?:图片|公式)无法识别\]"
    r"(?:\n```)?"                    # optional closing code fence
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FailureEntry:
    """A single failed conversion in a markdown file."""
    md_file: Path
    match_start: int
    match_end: int
    matched_text: str
    original_ref: str       # original "![alt](path)" from git
    image_rel_path: str     # cleaned relative image path


@dataclass
class FileReport:
    """Scan result for a single file."""
    md_file: Path
    failure_count: int
    failures: list[FailureEntry]


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8"),
        ],
    )


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def scan_failures(base_dir: Path = BASE_DIR) -> list[FileReport]:
    """Find all files with unrecognized image/formula placeholders."""
    reports = []
    for root, _dirs, files in os.walk(base_dir):
        for f in files:
            if not f.endswith(".md"):
                continue
            md_path = Path(root) / f
            content = md_path.read_text(encoding="utf-8")
            matches = list(FAILURE_PATTERN.finditer(content))
            if matches:
                entries = [
                    FailureEntry(
                        md_file=md_path,
                        match_start=m.start(),
                        match_end=m.end(),
                        matched_text=m.group(),
                        original_ref="",
                        image_rel_path="",
                    )
                    for m in matches
                ]
                reports.append(FileReport(
                    md_file=md_path,
                    failure_count=len(matches),
                    failures=entries,
                ))
    reports.sort(key=lambda r: (-r.failure_count, str(r.md_file)))
    return reports


def print_scan_report(reports: list[FileReport]):
    """Print a summary of scan results."""
    total_files = len(reports)
    total_failures = sum(r.failure_count for r in reports)
    print(f"\n扫描结果: {total_files} 个文件, {total_failures} 处失败\n")
    if not reports:
        print("没有发现 [图片无法识别] 或 [公式无法识别] 占位符。")
        return
    print(f"{'文件':<80} {'失败数':>6}")
    print("-" * 88)
    for r in reports:
        rel = r.md_file.relative_to(BASE_DIR)
        print(f"{str(rel):<80} {r.failure_count:>6}")
    print("-" * 88)
    print(f"{'合计':<80} {total_failures:>6}")


# ---------------------------------------------------------------------------
# Git history helpers
# ---------------------------------------------------------------------------

def _git_show_text(commit: str, repo_rel_path: str) -> str | None:
    """Read a text file from git history."""
    try:
        result = subprocess.run(
            ["git", "show", f"{commit}:{repo_rel_path}"],
            capture_output=True, cwd=REPO_ROOT, timeout=30,
        )
        if result.returncode != 0:
            return None
        return result.stdout.decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning("git show failed (%s): %s", repo_rel_path, e)
        return None


def _git_show_binary(commit: str, repo_rel_path: str, output_path: Path) -> bool:
    """Extract a binary file from git history to disk."""
    try:
        result = subprocess.run(
            ["git", "show", f"{commit}:{repo_rel_path}"],
            capture_output=True, cwd=REPO_ROOT, timeout=30,
        )
        if result.returncode != 0:
            return False
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(result.stdout)
        return True
    except Exception as e:
        logger.warning("git show binary failed (%s): %s", repo_rel_path, e)
        return False


# ---------------------------------------------------------------------------
# Matching failures to original image refs
# ---------------------------------------------------------------------------

def match_failures_to_images(report: FileReport) -> bool:
    """Match each failure entry to its original image ref via git history.

    Returns True if matching succeeded, False if the file should be skipped.
    """
    md_path = report.md_file
    try:
        repo_rel = md_path.relative_to(REPO_ROOT)
    except ValueError:
        logger.warning("文件不在仓库内: %s", md_path)
        return False

    # Read pre-conversion version from git
    old_content = _git_show_text(PRE_CONVERSION_COMMIT, str(repo_rel))
    if old_content is None:
        logger.warning("无法从 git 获取旧版本: %s", repo_rel)
        return False

    # Extract original image refs (ordered)
    old_refs = IMAGE_REF_RE.findall(old_content)  # list of (alt, path)

    # Count <!-- img2text --> markers in current file
    current_content = md_path.read_text(encoding="utf-8")
    marker_count = current_content.count(CONVERTED_MARKER)

    if len(old_refs) != marker_count:
        logger.warning(
            "数量不匹配，跳过: %s (旧版图片引用: %d, 当前标记: %d)",
            repo_rel, len(old_refs), marker_count,
        )
        return False

    # Find all <!-- img2text --> positions in order
    marker_positions = []
    start = 0
    while True:
        idx = current_content.find(CONVERTED_MARKER, start)
        if idx == -1:
            break
        marker_positions.append(idx)
        start = idx + len(CONVERTED_MARKER)

    # Map each failure to its marker index
    for entry in report.failures:
        try:
            marker_idx = marker_positions.index(entry.match_start)
        except ValueError:
            logger.warning("无法定位失败标记: offset=%d in %s", entry.match_start, md_path.name)
            return False

        alt_text, ref_path = old_refs[marker_idx]
        # Clean path: handle "path title" format like convert_images_to_text does
        clean_path = ref_path.split('"')[0].strip()

        entry.original_ref = f"![{alt_text}]({ref_path})"
        entry.image_rel_path = clean_path

    return True


# ---------------------------------------------------------------------------
# Fix pipeline
# ---------------------------------------------------------------------------

def fix_failures(
    base_dir: Path = BASE_DIR,
    limit: int = 0,
    dry_run: bool = False,
):
    """Main fix pipeline: restore original image refs for failed conversions."""
    reports = scan_failures(base_dir)
    if not reports:
        print("没有需要修复的文件。")
        return

    total_files = len(reports)
    total_failures = sum(r.failure_count for r in reports)
    logger.info("发现 %d 个文件, %d 处失败", total_files, total_failures)

    if limit > 0:
        reports = reports[:limit]
        logger.info("限制处理文件数: %d", limit)

    # Phase 1: Match failures to original images via git
    logger.info("阶段1: 从 git 历史匹配原始图片引用...")
    matched_reports = []
    for report in reports:
        if match_failures_to_images(report):
            matched_reports.append(report)
        else:
            logger.warning("跳过文件: %s", report.md_file.name)

    all_entries = [e for r in matched_reports for e in r.failures]
    logger.info("成功匹配: %d 个文件, %d 处失败", len(matched_reports), len(all_entries))

    if not all_entries:
        print("没有可处理的失败条目。")
        return

    # Phase 2: Restore image files from git
    logger.info("阶段2: 从 git 恢复图片文件...")
    restored_images = 0
    skipped_images = 0

    for entry in all_entries:
        md_dir = entry.md_file.parent
        dest = md_dir / entry.image_rel_path

        if dest.exists():
            # Image already on disk, no need to extract
            continue

        # Build git path
        try:
            image_repo_rel = md_dir.relative_to(REPO_ROOT) / entry.image_rel_path
        except ValueError:
            skipped_images += 1
            continue

        if not dry_run:
            if _git_show_binary(PRE_CONVERSION_COMMIT, str(image_repo_rel), dest):
                restored_images += 1
            else:
                logger.warning("无法提取图片: %s", image_repo_rel)
                skipped_images += 1
        else:
            restored_images += 1

    logger.info("图片恢复: %d, 跳过: %d", restored_images, skipped_images)

    # Phase 3: Replace failure blocks with original image refs
    logger.info("阶段3: 替换失败块...")
    replaced_count = 0

    by_file: dict[Path, list[FailureEntry]] = defaultdict(list)
    for entry in all_entries:
        by_file[entry.md_file].append(entry)

    for md_path, entries in by_file.items():
        content = md_path.read_text(encoding="utf-8")
        # Sort by position descending so replacements don't shift offsets
        entries.sort(key=lambda e: e.match_start, reverse=True)

        for entry in entries:
            content = (
                content[:entry.match_start]
                + entry.original_ref
                + content[entry.match_end:]
            )
            replaced_count += 1

        if not dry_run:
            md_path.write_text(content, encoding="utf-8")

    action = "预览" if dry_run else "修复"
    logger.info("=" * 60)
    logger.info(
        "%s完成: 恢复图片引用 %d, 恢复图片文件 %d, 跳过 %d",
        action, replaced_count, restored_images, skipped_images,
    )
    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="修复 [图片无法识别] / [公式无法识别] 占位符 — 恢复原始图片引用",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--scan", action="store_true", help="扫描统计失败数量")
    group.add_argument("--fix", action="store_true", help="执行恢复")

    parser.add_argument("--dry-run", action="store_true", help="预览不写入")
    parser.add_argument("--limit", type=int, default=0, help="限制处理文件数 (0=不限)")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细日志")

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.scan:
        reports = scan_failures()
        print_scan_report(reports)
    elif args.fix:
        fix_failures(limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
