#!/usr/bin/env python3
"""
AscendC Knowledge Base Restructurer

Transforms flat spider output into hierarchical directory structure:
- Parse title breadcrumbs to build directory tree
- Clean content (strip boilerplate, fix links, remove noise)
- Generate tree-form INDEX.md per section
- Relocate images to follow their pages

Usage:
    python3 restructure_kb.py -v 850 [OPTIONS]
    python3 restructure_kb.py -v 900
    python3 restructure_kb.py -v 850 -s api_reference  # single section
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Per-section suffix chains to strip from title breadcrumbs.
# These are the "root" segments that appear at the END of every title.
# Order: innermost → outermost (matching is done right-to-left).
SECTION_SUFFIXES_BY_VERSION = {
    "850": {
        "api_reference": [
            "Ascend C算子开发接口", "API", "CANN社区版8.5.0开发文档", "昇腾社区",
        ],
        "basic_knowledge": [
            "Ascend C算子开发", "算子开发", "CANN社区版8.5.0开发文档", "昇腾社区",
        ],
        "basic_data_api": [
            "基础数据结构和接口", "API", "CANN社区版8.5.0开发文档", "昇腾社区",
        ],
        "troubleshooting": [
            "故障处理", "参考", "CANN社区版8.5.0开发文档", "昇腾社区",
        ],
        "log_reference": [
            "日志参考", "参考", "CANN社区版8.5.0开发文档", "昇腾社区",
        ],
    },
    # Note: "CANN社区版9.0.0-beta.1开发文档" splits by '-' into two segments.
    "900beta1": {
        "api_reference": [
            "Ascend C算子开发接口", "API", "CANN社区版9.0.0", "beta.1开发文档", "昇腾社区",
        ],
        "basic_knowledge": [
            "Ascend C算子开发", "算子开发", "CANN社区版9.0.0", "beta.1开发文档", "昇腾社区",
        ],
        "basic_data_api": [
            "基础数据结构和接口", "API", "CANN社区版9.0.0", "beta.1开发文档", "昇腾社区",
        ],
        "troubleshooting": [
            "故障处理", "参考", "CANN社区版9.0.0", "beta.1开发文档", "昇腾社区",
        ],
        "log_reference": [
            "日志参考", "参考", "CANN社区版9.0.0", "beta.1开发文档", "昇腾社区",
        ],
    },
    "900": {
        "api_reference": [
            "Ascend C API", "API参考", "CANN社区版9.0.0开发文档", "昇腾社区",
        ],
        "basic_knowledge": [
            "Ascend C算子开发", "编程指南", "CANN社区版9.0.0开发文档", "昇腾社区",
        ],
        "basic_data_api": [
            "基础数据结构和接口", "参考", "CANN社区版9.0.0开发文档", "昇腾社区",
        ],
        "troubleshooting": [
            "故障处理", "参考", "CANN社区版9.0.0开发文档", "昇腾社区",
        ],
        "log_reference": [
            "日志参考", "参考", "CANN社区版9.0.0开发文档", "昇腾社区",
        ],
    },
}

_SKILL_REF = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "references")
DEFAULT_PATHS = {
    "850":      (f"{_SKILL_REF}/cache", _SKILL_REF),
    "900beta1": (f"{_SKILL_REF}/cache", _SKILL_REF),
    "900":      (f"{_SKILL_REF}/cache", _SKILL_REF),
}

# Suffix appended to section directory names in the output
SECTION_OUTPUT_SUFFIX_BY_VERSION = {
    "850":      "_docs",
    "900beta1": "_docs",
    "900":      "_docs",
}

# Set by main() based on --version
SECTION_SUFFIXES: dict[str, list[str]] = {}
SECTION_OUTPUT_SUFFIX: str = "_docs"

# Characters not allowed in directory/file names (filesystem-safe)
UNSAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Repeated boilerplate lines to remove from content
BOILERPLATE_PATTERNS = [
    # Common constraint references that appear in many API pages
    re.compile(
        r"^-?\s*操作数地址(?:对齐|重叠)(?:要求|约束)请参[见考].*$",
        re.MULTILINE,
    ),
    # Dead link text: "更多样例可参考LINK" (LINK is a stripped hyperlink remnant)
    re.compile(
        r"^.*更多样例可参考\s*LINK\s*[。.]?\s*$",
        re.MULTILINE,
    ),
    # Empty return value section: "#### 返回值说明\n\n无" (adds no information)
    re.compile(
        r"####\s*返回值说明\s*\n+\s*无\s*\n",
    ),
]

# Non-breaking space and zero-width characters to clean
INVISIBLE_CHARS_RE = re.compile("[\u00a0\u200b\u200c\u200d\ufeff]")

# Internal link pattern: [text](page_id.html#anchor) or [text](page_id.md)
# Negative lookbehind (?<!!) excludes image references ![text](path)
INTERNAL_LINK_RE = re.compile(
    r"(?<!!)"                  # not preceded by !
    r"\[([^\]]*)\]"           # [text]
    r"\("                      # (
    r"(?!https?://)"           # not absolute URL
    r"(?!/document/)"          # not site-absolute URL
    r"[^)]*"                   # link target
    r"\)",                     # )
)

# Absolute hiascend.com links
ABSOLUTE_LINK_RE = re.compile(
    r"(?<!!)"                  # not preceded by !
    r"\[([^\]]*)\]"
    r"\("
    r"(?:https?://www\.hiascend\.com|/document/detail)/[^)]*"
    r"\)",
)

# Image reference pattern
IMAGE_REF_RE = re.compile(
    r"!\[([^\]]*)\]\(\.\./images/([^)]+)\)"
)

# ZH-CN_TOPIC anchor reference (standalone, not in a link)
ANCHOR_REF_RE = re.compile(
    r"\[([^\]]*)\]\(#ZH-CN_TOPIC[^)]*\)"
)

# Multiple blank lines
MULTI_BLANK_RE = re.compile(r"\n{3,}")

# Broken image marker produced by stripped or incomplete image links, e.g. a lone "!["
BROKEN_IMAGE_MARKER_RE = re.compile(r"^!\[\s*$", re.MULTILINE)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger("restructure_kb")


# ---------------------------------------------------------------------------
# Breadcrumb Parsing
# ---------------------------------------------------------------------------

def parse_title_breadcrumb(
    title: str, section: str
) -> tuple[str, list[str]]:
    """
    Parse a page title breadcrumb into (page_name, [dir_segments]).

    Title format: "PageName-Level2-Level3-...-SectionRoot-...-昇腾社区"
    Returns: ("PageName", ["Level3", "Level2"])  # path from root to leaf

    The dir_segments are REVERSED so they form a natural directory path
    from shallowest to deepest.
    """
    # Split by '-' separator
    parts = title.split("-")

    # Strip known suffix segments from the right
    suffixes = SECTION_SUFFIXES.get(section, [])
    # Match and remove suffix segments from the end
    suffix_set = set(suffixes)
    while parts and parts[-1].strip() in suffix_set:
        parts.pop()

    if not parts:
        return title, []

    page_name = parts[0].strip()
    # Remaining parts (after page_name) are the hierarchy, innermost first
    # Reverse to get root → leaf order
    dir_segments = [p.strip() for p in reversed(parts[1:])]

    return page_name, dir_segments


def sanitize_filename(name: str) -> str:
    """Make a string safe for use as a filename."""
    name = UNSAFE_FILENAME_RE.sub("_", name)
    # Replace problematic chars
    name = name.replace("/", "_").replace("\\", "_")
    # Replace spaces with underscores (avoid broken markdown links)
    name = name.replace(" ", "_")
    # Replace half-width parentheses with full-width (avoid breaking markdown link syntax)
    name = name.replace("(", "（").replace(")", "）")
    # Collapse multiple underscores
    name = re.sub(r"_+", "_", name)
    # Trim
    name = name.strip("_. ")
    if not name:
        name = "_unnamed"
    return name


# ---------------------------------------------------------------------------
# TOC Detection
# ---------------------------------------------------------------------------

def is_toc_page(body: str) -> bool:
    """
    Detect if a page is TOC-only (just navigation links, no real content).

    A TOC page typically has:
    - A heading
    - A list of bold links like: - **[Title](page.md)**
    - No tables, no code blocks, minimal text
    """
    lines = body.strip().split("\n")

    has_table = "| ---" in body or "|---" in body
    has_code = "```" in body

    if has_table or has_code:
        return False

    # Count non-link, non-header, non-blank content lines
    content_lines = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("---"):
            continue
        # Link list items: - **[text](url)** or - [text](url)
        if re.match(r'^-\s+\*?\*?\[', stripped):
            continue
        if len(stripped) > 10:
            content_lines += 1

    return content_lines < 5


# ---------------------------------------------------------------------------
# Content Cleaning
# ---------------------------------------------------------------------------

def clean_content(
    content: str,
    page_name: str,
    page_id: str,
    source_url: str,
    old_images_dir: str,
    new_images_dir: str,
) -> tuple[str, list[tuple[str, str]]]:
    """
    Clean page content. Returns (cleaned_text, [(old_img_path, new_img_path)]).
    """
    image_moves: list[tuple[str, str]] = []

    # 1. Strip the metadata header (first 4-5 lines: title, page_id, source, ---)
    #    and reconstruct with clean title
    lines = content.split("\n")
    body_start = 0
    for i, line in enumerate(lines):
        if line.strip() == "---" and i > 0:
            body_start = i + 1
            break
    body = "\n".join(lines[body_start:])

    # 2. Strip duplicate H1 heading (body often starts with "# PageName"
    #    which duplicates the header we add in step 8)
    body = re.sub(r"^\s*#\s+" + re.escape(page_name) + r"\s*\n+", "", body, count=1)

    # 3. Clean invisible characters (non-breaking space, zero-width chars)
    body = INVISIBLE_CHARS_RE.sub(" ", body)

    # 4. Handle image references FIRST - before any link stripping
    def replace_image(m):
        alt = m.group(1)
        img_filename = m.group(2)
        old_img_path = os.path.join(old_images_dir, img_filename)
        new_img_filename = img_filename
        new_img_path = os.path.join(new_images_dir, new_img_filename)
        image_moves.append((old_img_path, new_img_path))
        return f"![{alt}](images/{new_img_filename})"

    body = IMAGE_REF_RE.sub(replace_image, body)

    # 5. Strip internal links → keep text only
    body = INTERNAL_LINK_RE.sub(r"\1", body)

    # 6. Strip absolute links → keep text only
    body = ABSOLUTE_LINK_RE.sub(r"\1", body)

    # 7. Strip anchor references
    body = ANCHOR_REF_RE.sub(r"\1", body)

    # 8. Remove boilerplate lines
    for pattern in BOILERPLATE_PATTERNS:
        body = pattern.sub("", body)

    # 8.5. Drop broken standalone image markers left after link stripping
    body = BROKEN_IMAGE_MARKER_RE.sub("", body)

    # 9. Collapse multiple blank lines
    body = MULTI_BLANK_RE.sub("\n\n", body)

    # 10. Build final content with clean header
    clean = (
        f"# {page_name}\n\n"
        f"**页面ID:** {page_id}  \n"
        f"**来源:** {source_url}\n\n"
        f"---\n\n"
        f"{body.strip()}\n"
    )

    return clean, image_moves


# ---------------------------------------------------------------------------
# Page Processing
# ---------------------------------------------------------------------------

class PageInfo:
    """Parsed info about a single documentation page."""

    def __init__(
        self,
        page_id: str,
        original_title: str,
        page_name: str,
        dir_segments: list[str],
        is_toc: bool,
        content: str,
        source_url: str,
        image_files: list[str],
    ):
        self.page_id = page_id
        self.original_title = original_title
        self.page_name = page_name
        self.dir_segments = dir_segments
        self.is_toc = is_toc
        self.content = content
        self.source_url = source_url
        self.image_files = image_files

    @property
    def dir_path(self) -> str:
        """Directory path relative to section root."""
        return "/".join(self.dir_segments) if self.dir_segments else ""

    @property
    def safe_name(self) -> str:
        """Filesystem-safe page name."""
        return sanitize_filename(self.page_name)


def read_page(filepath: str) -> tuple[str, str, str, str]:
    """
    Read a page file and extract metadata.
    Returns: (page_id, title, source_url, full_content)
    """
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")

    # Line 1: # Title
    title = lines[0].lstrip("# ").strip() if lines else ""

    # Line 2-3: **页面ID:** xxx and **来源:** url
    page_id = ""
    source_url = ""
    for line in lines[1:5]:
        if line.startswith("**页面ID:**"):
            page_id = line.replace("**页面ID:**", "").strip()
        elif line.startswith("**来源:**"):
            source_url = line.replace("**来源:**", "").strip()

    return page_id, title, source_url, content


# ---------------------------------------------------------------------------
# Section Processor
# ---------------------------------------------------------------------------

def process_section(
    input_dir: str,
    output_dir: str,
    section: str,
    output_section: str | None = None,
) -> dict:
    """
    Process one section: read all pages, restructure, clean, write.
    Returns metadata for INDEX generation.
    """
    if output_section is None:
        output_section = section
    pages_dir = os.path.join(input_dir, section, "pages")
    images_dir = os.path.join(input_dir, section, "images")
    out_section = os.path.join(output_dir, output_section)

    if not os.path.isdir(pages_dir):
        logger.error("Pages directory not found: %s", pages_dir)
        return {"section": section, "pages": [], "toc_removed": 0}

    # Phase 1: Read and parse all pages
    pages: list[PageInfo] = []
    toc_count = 0
    fallback_page_ids: set[str] = set()  # pages whose title fetch failed

    for filename in sorted(os.listdir(pages_dir)):
        if not filename.endswith(".md"):
            continue

        filepath = os.path.join(pages_dir, filename)
        page_id, title, source_url, content = read_page(filepath)

        if not page_id:
            page_id = filename.replace(".md", "")

        # Fallback title: when spider failed to fetch real title,
        # extract page name from the first # heading in body
        if "昇腾社区官网" in title or "昇腾万里" in title:
            fallback_page_ids.add(page_id)
            body_lines_tmp = content.split("\n")
            bs = 0
            for ii, ln in enumerate(body_lines_tmp):
                if ln.strip() == "---" and ii > 0:
                    bs = ii + 1
                    break
            for ln in body_lines_tmp[bs:]:
                ln_s = ln.strip()
                if ln_s.startswith("# ") and len(ln_s) > 2:
                    fallback_name = ln_s[2:].strip()
                    logger.info(
                        "[%s] 回退标题: %s -> %s (%s)",
                        section, title, fallback_name, filename,
                    )
                    title = fallback_name
                    break

        # Parse breadcrumb
        page_name, dir_segments = parse_title_breadcrumb(title, section)

        # Extract body for TOC detection
        body_lines = content.split("\n")
        body_start = 0
        for i, line in enumerate(body_lines):
            if line.strip() == "---" and i > 0:
                body_start = i + 1
                break
        body = "\n".join(body_lines[body_start:])

        # Detect TOC pages
        toc = is_toc_page(body)
        if toc:
            toc_count += 1

        # Find associated images
        img_files = []
        for m in IMAGE_REF_RE.finditer(content):
            img_files.append(m.group(2))

        pages.append(PageInfo(
            page_id=page_id,
            original_title=title,
            page_name=page_name,
            dir_segments=dir_segments,
            is_toc=toc,
            content=content,
            source_url=source_url,
            image_files=img_files,
        ))

    logger.info(
        "[%s] 读取 %d 页面 (%d 内容页, %d TOC页将被删除)",
        section, len(pages), len(pages) - toc_count, toc_count,
    )

    # Phase 1.5: Fix directory placement for fallback-title pages.
    # These pages lost their breadcrumb, so dir_segments is empty.
    # Borrow dir_segments from neighboring pages (by page_id numeric order).
    # Only apply to pages that were actual fallback-title pages, NOT legitimately
    # top-level pages whose dir_segments is naturally empty.
    page_by_id: dict[str, PageInfo] = {p.page_id: p for p in pages}
    for page in pages:
        if page.page_id not in fallback_page_ids:
            continue
        if page.dir_segments:
            continue
        # Extract numeric suffix from page_id, e.g. "atlasascendc_api_07_0184" → ("atlasascendc_api_07_", 184)
        m = re.match(r"^(.*?)(\d+)$", page.page_id)
        if not m:
            continue
        prefix, num = m.group(1), int(m.group(2))
        # Search neighbors: prefer -1 first (same subsection), then +1, then wider
        # Only borrow from pages with original breadcrumbs (not other fallbacks)
        for delta in [-1, 1, -2, 2, -3, 3, -4, 4, -5, 5]:
            neighbor_id = f"{prefix}{num + delta:0{len(m.group(2))}d}"
            neighbor = page_by_id.get(neighbor_id)
            if neighbor and neighbor.dir_segments and neighbor_id not in fallback_page_ids:
                page.dir_segments = list(neighbor.dir_segments)
                logger.info(
                    "[%s] 从邻居 %s 借用目录: %s -> %s",
                    section, neighbor_id, page.page_name,
                    "/".join(page.dir_segments),
                )
                break

    # Phase 2: Resolve filename conflicts
    # Group content pages by (dir_path, safe_name)
    name_usage: dict[str, list[PageInfo]] = defaultdict(list)
    for page in pages:
        if page.is_toc:
            continue
        key = f"{page.dir_path}/{page.safe_name}"
        name_usage[key].append(page)

    # Phase 3: Write content pages
    written = 0
    all_image_moves: list[tuple[str, str]] = []
    page_tree: dict[str, list[dict]] = defaultdict(list)  # dir_path → [{name, file}]

    for page in pages:
        if page.is_toc:
            continue

        # Determine output filename
        safe_name = page.safe_name
        key = f"{page.dir_path}/{safe_name}"
        conflicts = name_usage[key]
        if len(conflicts) > 1:
            # Append page_id suffix to disambiguate
            safe_name = f"{safe_name}_{page.page_id}"

        # Determine output path
        if page.dir_segments:
            dir_parts = [sanitize_filename(s) for s in page.dir_segments]
            out_dir = os.path.join(out_section, *dir_parts)
        else:
            out_dir = out_section

        os.makedirs(out_dir, exist_ok=True)
        out_file = os.path.join(out_dir, f"{safe_name}.md")

        # Determine images directory for this page
        new_images_dir = os.path.join(out_dir, "images")

        # Clean content
        cleaned, img_moves = clean_content(
            page.content,
            page.page_name,
            page.page_id,
            page.source_url,
            images_dir,
            new_images_dir,
        )

        # Write page
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(cleaned)
        written += 1

        all_image_moves.extend(img_moves)

        # Track for INDEX generation
        rel_path = os.path.relpath(out_file, out_section)
        page_tree[page.dir_path].append({
            "name": page.page_name,
            "file": rel_path,
            "page_id": page.page_id,
        })

    # Phase 4: Move images
    img_moved = 0
    for old_path, new_path in all_image_moves:
        if os.path.isfile(old_path):
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            shutil.copy2(old_path, new_path)
            img_moved += 1
        else:
            logger.debug("图片不存在: %s", old_path)

    logger.info(
        "[%s] 写入 %d 内容页, 移动 %d 图片, 删除 %d TOC页",
        section, written, img_moved, toc_count,
    )

    return {
        "section": section,
        "pages": pages,
        "page_tree": dict(page_tree),
        "toc_removed": toc_count,
        "content_written": written,
        "images_moved": img_moved,
    }


# ---------------------------------------------------------------------------
# INDEX.md Generation
# ---------------------------------------------------------------------------

def generate_index(output_dir: str, section: str, page_tree: dict,
                   output_section: str | None = None):
    """Generate a tree-form INDEX.md for a section."""
    if output_section is None:
        output_section = section
    out_section = os.path.join(output_dir, output_section)
    index_path = os.path.join(out_section, "INDEX.md")

    # Build a tree structure from page_tree
    # page_tree: {dir_path: [{name, file, page_id}]}
    tree: dict = {}  # nested dict representing directory tree

    for dir_path, pages in sorted(page_tree.items()):
        if dir_path:
            parts = dir_path.split("/")
        else:
            parts = []

        node = tree
        for part in parts:
            if part not in node:
                node[part] = {}
            node = node[part]

        if "_pages" not in node:
            node["_pages"] = []
        node["_pages"].extend(sorted(pages, key=lambda p: p["name"]))

    # Render tree to markdown
    lines = [f"# {section} 文档索引\n\n"]

    def render_tree(node: dict, depth: int = 0):
        # Render subdirectories first (sections before individual pages)
        for key in sorted(node.keys()):
            if key == "_pages":
                continue
            prefix = "#" * min(depth + 2, 6)
            lines.append(f"{prefix} {key}\n\n")
            render_tree(node[key], depth + 1)

        # Render pages at this level
        if "_pages" in node:
            for p in node["_pages"]:
                lines.append(f"- [{p['name']}]({p['file']})\n")
            lines.append("\n")

    render_tree(tree)

    with open(index_path, "w", encoding="utf-8") as f:
        f.write("".join(lines))

    logger.info("[%s] INDEX.md 已生成: %s", section, index_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="AscendC Knowledge Base Restructurer",
    )
    parser.add_argument(
        "-v", "--version",
        required=True,
        choices=list(SECTION_SUFFIXES_BY_VERSION.keys()),
        help="CANN 版本 (850, 900, 900beta1)",
    )
    parser.add_argument(
        "-i", "--input",
        default=None,
        help="输入目录 (爬虫原始输出, 默认: skill/references/cache[_90])",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="输出目录 (默认: skill/references/, 各 section 加 _docs 后缀)",
    )
    parser.add_argument(
        "-s", "--sections",
        nargs="+",
        default=None,
        help="要处理的分类 (默认: 全部)",
    )
    parser.add_argument(
        "--keep-cache",
        action="store_true",
        default=False,
        help="保留 cache 目录 (默认: 清洗完成后删除)",
    )

    args = parser.parse_args()

    # Set version-specific globals
    global SECTION_SUFFIXES, SECTION_OUTPUT_SUFFIX
    SECTION_SUFFIXES = SECTION_SUFFIXES_BY_VERSION[args.version]
    SECTION_OUTPUT_SUFFIX = SECTION_OUTPUT_SUFFIX_BY_VERSION[args.version]

    # Apply version defaults for input/output paths
    default_input, default_output = DEFAULT_PATHS[args.version]
    if args.input is None:
        args.input = default_input
    if args.output is None:
        args.output = default_output

    # Default sections: all available
    if args.sections is None:
        args.sections = list(SECTION_SUFFIXES.keys())

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info("输入: %s", args.input)
    logger.info("输出: %s", args.output)
    logger.info("分类: %s", ", ".join(args.sections))

    os.makedirs(args.output, exist_ok=True)

    total_content = 0
    total_toc = 0
    total_images = 0

    for section in args.sections:
        out_name = section + SECTION_OUTPUT_SUFFIX
        result = process_section(args.input, args.output, section, out_name)
        generate_index(args.output, section, result.get("page_tree", {}), out_name)

        total_content += result.get("content_written", 0)
        total_toc += result.get("toc_removed", 0)
        total_images += result.get("images_moved", 0)

    logger.info("=" * 50)
    logger.info("重构完成:")
    logger.info("  内容页: %d", total_content)
    logger.info("  TOC页删除: %d", total_toc)
    logger.info("  图片移动: %d", total_images)
    logger.info("  输出目录: %s", args.output)
    logger.info("=" * 50)

    # Delete cache after successful restructure (default behavior)
    if not args.keep_cache and os.path.isdir(args.input):
        logger.info("删除 cache 目录: %s", args.input)
        shutil.rmtree(args.input)
        logger.info("cache 已删除")


if __name__ == "__main__":
    main()
