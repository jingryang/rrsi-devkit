#!/usr/bin/env python3
"""
CANN 知识库图片转 Markdown 文本工具

通过 LLM Vision API 将文档中的图片转为纯文本/LaTeX/ASCII art，
替换原始 markdown 中的 ![](path) 引用。

- 公式图 → LaTeX 数学表达式
- 示意图/架构图 → ASCII art + 文字说明

用法:
    python3 convert_images_to_text.py --scan                    # 扫描统计
    python3 convert_images_to_text.py --clean-icons             # 清理图标引用
    python3 convert_images_to_text.py --convert --limit 5       # 小批量转换
    python3 convert_images_to_text.py --convert                 # 全量转换
    python3 convert_images_to_text.py --convert --dry-run       # 预览不写入
    python3 convert_images_to_text.py --cleanup                 # 删除所有图片文件和空目录
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from threading import Lock
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent / "references"

IMAGE_REF_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

ICON_PATTERNS = [
    "public_sys-resources/icon-",
    "public_sys-resources/",
]

EXCLUDED_DIRS: set[str] = set()

FORMULA_ID = "formulaimage"

LOG_FILE = Path(__file__).resolve().parent / "convert_images.log"

CONVERTED_MARKER = "<!-- img2text -->"

MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

FORMULA_PROMPT = """\
这是一张来自华为昇腾(Ascend)技术文档中的数学公式截图。请将图片中的数学公式转换为 LaTeX 格式。

要求:
1. 直接输出公式，不要任何前缀说明文字（禁止"根据..."、"以下是..."、"这是..."等开头）
2. 输出格式: 用 $...$ 包裹行内公式，用 $$...$$ 包裹独立公式
3. 如果有多个公式或条件分支，分行输出
4. 如果图片中有文字说明（如"其中"、"where"），也一并输出
5. 如果看不清或无法识别，输出: [公式无法识别]

以下是图片在文档中的上下文:
--- 前文 ---
{context_before}
--- 后文 ---
{context_after}
"""

DIAGRAM_PROMPT = """\
这是一张来自华为昇腾(Ascend)技术文档中的技术示意图/架构图。请将图片内容转换为 ASCII art + 文字标注。

严格要求:
1. 直接输出内容，禁止任何前缀说明（禁止"根据..."、"以下是..."、"这是一张..."、"该图展示..."等开头）
2. 使用 ASCII 字符绘制框图、箭头等（如 ┌ ┐ └ ┘ │ ─ ├ ┤ ┬ ┴ → ← ↑ ↓ ▼ ▲）
3. 用代码块格式（``` 包裹）呈现 ASCII art 部分
4. 保留图中的所有文字标注、数据和标签
5. 仅当图中内容无法从 ASCII art 本身理解时才添加"说明:"段落，否则不要添加任何说明
6. 如果图中内容简单（如只有文字或简单箭头），直接用文字描述即可
7. 如果看不清或无法识别，输出: [图片无法识别]
8. 禁止输出任何思考过程（如"Wait,"、"Let me"、"looking at"等）
9. 原图中用颜色区分的区域：**禁止**在代码块的框图结构中添加颜色标签（如 [蓝色]┌──），如有区分颜色信息的必要，只在下方说明文字中说明颜色区分（如"图中蓝色区域表示..."），但前提是这些颜色信息对于理解图的内容是必要的，否则不要添加任何颜色说明
10. 数据布局图的参数标注规则：
    a. 代码块内画数据块的框图结构，在框图下方用**两行**标注每个参数：第一行只画纯箭头线 `<─────────────>` 标记范围，第二行在箭头下方写参数名和值。**禁止使用竖线 `|`**
    b. **对齐流程**：画完框图后，先确定每个数据块单元格的起止字符列号（如第1块: 列1-12，第2块: 列13-24），然后在箭头行中将 `<` 放在目标块的起始列、`>` 放在目标块的结束列，中间全部用 `─` 填充（不混入文字）。第二行在箭头范围内居中写参数名
    c. **每个参数占两行**（箭头行 + 文字行），禁止在同一行放多个范围标记
    d. **宽度适配规则**：如果参数名文本（如 `srcStride=1`）的字符宽度大于箭头跨度，则在框图中**加宽对应数据块的单元格**（用额外空格填充）
    e. 代码块下方**必须**用文字列表提供精确的参数描述，这是权威信息源
    f. 文字列表中**每行只描述一个参数的一个区域界限**，格式为"- 参数名=值: 覆盖第X-Y块(具体内容)"
    g. 如果同一个参数在图中出现多次（如重复的数据块组），每次出现单独一行描述
11. 如果图中某些元素之间的映射/对应关系过于复杂，无法用 ASCII art 准确复现（如多对多的斜向箭头映射），**不要强行画**，改用代码块下方的文字描述说明对应关系

输出格式示例（数据布局图，注意 srcStride=1 比 1Byte 宽所以加宽了该单元格）:
```
src(GM)
┌──────────┬──────────┬───────────────┬──────────┬──────────┬───────────────┐
│ 32Bytes  │ 32Bytes  │    1Byte      │ 32Bytes  │ 32Bytes  │    1Byte      │
└──────────┴──────────┴───────────────┴──────────┴──────────┴───────────────┘
<─────────────────────>
      blockLen=64
                       <─────────────>
                        srcStride=1

dst(VECIN/VECOUT)
┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
│ 32Bytes  │ 32Bytes  │ 32Bytes  │ 32Bytes  │ 32Bytes  │ 32Bytes  │
└──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘
<─────────────────────>
      blockLen=64
                       <─────────>
                       dstStride=1
```
- blockLen=64: src 覆盖第1-2块(32Bytes+32Bytes)
- srcStride=1: src 第1组与第2组之间间隔，即第3块(1Byte)
- blockLen=64: dst 覆盖第1-2块(32Bytes+32Bytes)
- dstStride=1: dst 第1组与第2组之间间隔，即第3块(32Bytes，1个dataBlock)

输出格式示例（架构图/流程图）:
```
┌──────────┬──────────┐
│  模块A   │  模块B   │
└──────────┴──────────┘
```

以下是图片在文档中的上下文:
--- 前文 ---
{context_before}
--- 后文 ---
{context_after}
"""

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ImageRef:
    md_file: Path
    full_match: str
    alt_text: str
    ref_path: str
    clean_path: str
    abs_image_path: Path
    category: str          # "icon", "formula", "diagram"
    line_num: int
    context_before: str = ""
    context_after: str = ""


@dataclass
class ScanResult:
    total_md_files: int = 0
    files_with_images: int = 0
    refs: list[ImageRef] = field(default_factory=list)

    @property
    def icons(self) -> list[ImageRef]:
        return [r for r in self.refs if r.category == "icon"]

    @property
    def formulas(self) -> list[ImageRef]:
        return [r for r in self.refs if r.category == "formula"]

    @property
    def diagrams(self) -> list[ImageRef]:
        return [r for r in self.refs if r.category == "diagram"]


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


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def classify_image(ref_path: str) -> str:
    lower = ref_path.lower()
    for pattern in ICON_PATTERNS:
        if pattern in lower:
            return "icon"
    if lower.endswith(".gif"):
        return "icon"
    if FORMULA_ID in lower:
        return "formula"
    return "diagram"


def get_context(lines: list[str], line_idx: int, window: int = 5) -> tuple[str, str]:
    start = max(0, line_idx - window)
    end = min(len(lines), line_idx + window + 1)
    before = "\n".join(lines[start:line_idx])
    after = "\n".join(lines[line_idx + 1:end])
    return before, after


def _collect_md_files(base_dir: Path, paths: list[Path] | None = None) -> list[Path]:
    """Collect .md files from given paths or walk base_dir."""
    md_files = []
    if paths:
        for p in paths:
            p = p.resolve()
            if p.is_file() and p.suffix == ".md":
                md_files.append(p)
            elif p.is_dir():
                for root, dirs, files in os.walk(p):
                    dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
                    for f in files:
                        if f.endswith(".md"):
                            md_files.append(Path(root) / f)
            else:
                logger.warning("跳过无效路径: %s", p)
    else:
        for root, dirs, files in os.walk(base_dir):
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
            for f in files:
                if f.endswith(".md"):
                    md_files.append(Path(root) / f)
    return md_files


def scan_all(base_dir: Path = BASE_DIR, paths: list[Path] | None = None) -> ScanResult:
    result = ScanResult()
    md_files = _collect_md_files(base_dir, paths)

    for md_path in md_files:
        result.total_md_files += 1

        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()

        if "![" not in content:
            continue

        result.files_with_images += 1
        lines = content.split("\n")

        for line_idx, line in enumerate(lines):
            for m in IMAGE_REF_RE.finditer(line):
                alt_text = m.group(1)
                ref_path = m.group(2)
                clean_path = ref_path.split('"')[0].strip()
                abs_path = (md_path.parent / clean_path).resolve()
                category = classify_image(ref_path)
                ctx_before, ctx_after = get_context(lines, line_idx)

                result.refs.append(ImageRef(
                    md_file=md_path,
                    full_match=m.group(0),
                    alt_text=alt_text,
                    ref_path=ref_path,
                    clean_path=clean_path,
                    abs_image_path=abs_path,
                    category=category,
                    line_num=line_idx + 1,
                    context_before=ctx_before,
                    context_after=ctx_after,
                ))

    return result


def print_scan_report(result: ScanResult):
    print("=" * 60)
    print("CANN 知识库图片扫描报告")
    print("=" * 60)
    print(f"总 .md 文件数:     {result.total_md_files}")
    print(f"含图片的文件数:    {result.files_with_images}")
    print(f"总图片引用数:      {len(result.refs)}")
    print("-" * 60)
    print(f"  图标 (icon):     {len(result.icons)}")
    print(f"  公式 (formula):  {len(result.formulas)}")
    print(f"  示意图 (diagram): {len(result.diagrams)}")
    print("-" * 60)
    existing = sum(1 for r in result.refs if r.abs_image_path.is_file())
    missing = len(result.refs) - existing
    print(f"  图片文件存在:    {existing}")
    print(f"  图片文件缺失:    {missing}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Icon Cleaning
# ---------------------------------------------------------------------------

def clean_icons(base_dir: Path = BASE_DIR, dry_run: bool = False, paths: list[Path] | None = None):
    result = scan_all(base_dir, paths=paths)
    icons = result.icons

    if not icons:
        print("没有找到图标引用，无需清理。")
        return

    print(f"找到 {len(icons)} 个图标引用，准备清理...")

    by_file: dict[Path, list[ImageRef]] = {}
    for ref in icons:
        by_file.setdefault(ref.md_file, []).append(ref)

    cleaned_files = 0
    cleaned_refs = 0

    for md_path, refs in by_file.items():
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()

        original = content
        for ref in refs:
            content = content.replace(ref.full_match, "")
            cleaned_refs += 1

        content = re.sub(r"\n{3,}", "\n\n", content)

        if content != original:
            cleaned_files += 1
            if not dry_run:
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(content)

    action = "预览" if dry_run else "已清理"
    print(f"{action}: {cleaned_refs} 个图标引用 (来自 {cleaned_files} 个文件)")


# ---------------------------------------------------------------------------
# Vision API
# ---------------------------------------------------------------------------

def encode_image_base64(image_path: Path) -> str | None:
    if not image_path.is_file():
        return None
    with open(image_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def call_vision_api(
    image_ref: ImageRef,
    model: str = "gpt-5.4",
    max_retries: int = 3,
) -> str | None:
    """Use vision API to convert an image to text (LaTeX or ASCII art).
    Automatically retries on timeout or transient errors.
    """
    import httpx

    img_data = encode_image_base64(image_ref.abs_image_path)
    if img_data is None:
        logger.warning("图片文件不存在: %s", image_ref.abs_image_path)
        return None

    media_type = MIME_MAP.get(image_ref.abs_image_path.suffix.lower(), "image/png")

    if image_ref.category == "formula":
        prompt = FORMULA_PROMPT.format(
            context_before=image_ref.context_before[:500],
            context_after=image_ref.context_after[:500],
        )
    else:
        prompt = DIAGRAM_PROMPT.format(
            context_before=image_ref.context_before[:500],
            context_after=image_ref.context_after[:500],
        )

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")

    for attempt in range(1, max_retries + 1):
        try:
            resp = httpx.post(
                f"{base_url}/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 8000,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": media_type,
                                        "data": img_data,
                                    },
                                },
                                {
                                    "type": "text",
                                    "text": prompt,
                                },
                            ],
                        }
                    ],
                },
                timeout=90.0,
            )

            result = resp.json()
            logger.debug("API 返回结构 (%s): %s", image_ref.abs_image_path.name, json.dumps(result, ensure_ascii=False)[:500])
            if "content" in result and result["content"]:
                # Find the text block (skip thinking blocks)
                text = ""
                for block in result["content"]:
                    if block.get("type") == "text" and block.get("text", "").strip():
                        text = block["text"].strip()
                        break
                return text if text else None
            else:
                error = result.get("error", {})
                logger.error("API 返回错误 (%s): keys=%s, error=%s", image_ref.abs_image_path.name, list(result.keys()), error)
                # Don't retry on non-transient API errors (e.g. invalid request)
                if resp.status_code < 500:
                    return None

        except Exception as e:
            logger.warning(
                "API 调用失败 (%s), 第 %d/%d 次: %s",
                image_ref.abs_image_path.name, attempt, max_retries, e,
            )

        if attempt < max_retries:
            wait = attempt * 5  # 5s, 10s
            logger.info("  %d 秒后重试...", wait)
            time.sleep(wait)

    logger.error("API 调用最终失败 (%s), 已重试 %d 次", image_ref.abs_image_path.name, max_retries)
    return None


# ---------------------------------------------------------------------------
# Conversion pipeline
# ---------------------------------------------------------------------------

def convert_images(
    base_dir: Path = BASE_DIR,
    limit: int = 0,
    dry_run: bool = False,
    model: str = "gpt-5.4",
    categories: list[str] | None = None,
    workers: int = 8,
    paths: list[Path] | None = None,
):
    """Convert image references to text via LLM vision API (concurrent)."""
    result = scan_all(base_dir, paths=paths)

    if categories is None:
        categories = ["formula", "diagram"]
    refs_to_convert = [r for r in result.refs if r.category in categories]

    # Skip already converted (marked with CONVERTED_MARKER)
    unconverted = []
    file_cache: dict[Path, str] = {}
    for ref in refs_to_convert:
        if ref.md_file not in file_cache:
            with open(ref.md_file, "r", encoding="utf-8") as f:
                file_cache[ref.md_file] = f.read()
        content = file_cache[ref.md_file]
        if ref.full_match in content:
            unconverted.append(ref)

    logger.info("总引用: %d, 待转换: %d (已跳过已转换的)", len(refs_to_convert), len(unconverted))

    if limit > 0:
        unconverted = unconverted[:limit]
        logger.info("限制处理数量: %d", limit)

    processable = [r for r in unconverted if r.abs_image_path.is_file()]
    skipped_missing = len(unconverted) - len(processable)
    if skipped_missing:
        logger.warning("跳过 %d 个图片文件不存在的引用", skipped_missing)

    total = len(processable)
    logger.info("开始并发转换: %d 张图片, %d 线程", total, workers)

    # --- Phase 1: concurrent API calls ---
    api_results: dict[int, str | None] = {}
    counter_lock = Lock()
    done_count = [0]

    def _call_api(idx: int, ref: ImageRef) -> tuple[int, str | None]:
        text = call_vision_api(ref, model=model)
        with counter_lock:
            done_count[0] += 1
            n = done_count[0]
        if text:
            logger.info("[%d/%d] OK %s (%d chars)", n, total, ref.abs_image_path.name, len(text))
        else:
            logger.warning("[%d/%d] FAIL %s", n, total, ref.abs_image_path.name)
        return idx, text

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_call_api, i, ref): i for i, ref in enumerate(processable)}
        for fut in as_completed(futures):
            idx, text = fut.result()
            api_results[idx] = text

    # --- Phase 2: sequential file writes (group by file) ---
    success_count = 0
    fail_count = 0

    by_file: dict[Path, list[tuple[int, ImageRef]]] = defaultdict(list)
    for i, ref in enumerate(processable):
        by_file[ref.md_file].append((i, ref))

    for md_path, items in by_file.items():
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()

        modified = False
        for idx, ref in items:
            text = api_results.get(idx)
            if text is None:
                fail_count += 1
                continue
            if ref.full_match not in content:
                logger.warning("引用未找到: %s in %s", ref.full_match[:80], md_path.name)
                fail_count += 1
                continue
            replacement = f"{CONVERTED_MARKER}\n{text}"
            content = content.replace(ref.full_match, replacement, 1)
            modified = True
            success_count += 1

        if modified and not dry_run:
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(content)

    action = "预览" if dry_run else "转换"
    logger.info("=" * 60)
    logger.info("%s完成: 成功 %d, 失败 %d, 总计 %d", action, success_count, fail_count, total)
    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def cleanup_all_images(base_dir: Path = BASE_DIR, dry_run: bool = False, paths: list[Path] | None = None):
    """Delete ALL image files and empty image directories under base_dir or given paths."""
    all_images: list[Path] = []
    walk_roots = []
    if paths:
        for p in paths:
            p = p.resolve()
            if p.is_file() and p.suffix.lower() in MIME_MAP:
                all_images.append(p)
            elif p.is_dir():
                walk_roots.append(p)
            elif p.is_file() and p.suffix == ".md":
                # For .md files, look for images in the same directory
                walk_roots.append(p.parent)
    else:
        walk_roots.append(base_dir)

    for wr in walk_roots:
        for root, dirs, files in os.walk(wr):
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
            for fname in files:
                if fname.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                    all_images.append(Path(root) / fname)

    if not all_images:
        print("没有找到图片文件。")
        return

    total_size = sum(f.stat().st_size for f in all_images if f.is_file())
    print(f"总图片文件: {len(all_images)}")
    print(f"总大小: {total_size / 1024 / 1024:.1f} MB")

    if dry_run:
        for img in all_images[:20]:
            print(f"  [DRY-RUN] 将删除: {img}")
        if len(all_images) > 20:
            print(f"  ... 还有 {len(all_images) - 20} 个")
        return

    deleted = 0
    for img in all_images:
        try:
            img.unlink()
            deleted += 1
        except OSError as e:
            logger.warning("删除失败: %s: %s", img, e)

    IMAGE_DIR_NAMES = {"images", "figures", "public_sys-resources"}
    for root, dirs, _files in os.walk(base_dir, topdown=False):
        if Path(root).name in EXCLUDED_DIRS:
            continue
        for d in dirs:
            dir_path = Path(root) / d
            if d in IMAGE_DIR_NAMES and dir_path.is_dir() and not any(dir_path.iterdir()):
                dir_path.rmdir()
                logger.info("删除空目录: %s", dir_path)

    print(f"已删除 {deleted} 个图片文件")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="CANN 知识库图片转 Markdown 文本工具 (LLM Vision)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--scan", action="store_true", help="扫描统计图片引用")
    group.add_argument("--clean-icons", action="store_true", help="清理图标引用")
    group.add_argument("--convert", action="store_true", help="图片转文本 (LaTeX/ASCII art)")
    group.add_argument("--cleanup", action="store_true", help="删除所有图片文件和空目录")

    parser.add_argument("--limit", type=int, default=0, help="限制处理数量 (0=不限制)")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际修改文件")
    parser.add_argument("--model", default="gpt-5.4", help="模型名称")
    parser.add_argument("--category", choices=["formula", "diagram", "all"], default="all",
                        help="仅转换指定类别 (默认: all)")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细日志")
    parser.add_argument("--workers", "-w", type=int, default=16, help="并发线程数 (默认: 16)")
    parser.add_argument("--base-dir", type=Path, default=BASE_DIR, help="基础目录")
    parser.add_argument("paths", nargs="*", type=Path, help="指定文件或目录 (默认: 全量)")

    args = parser.parse_args()
    setup_logging(args.verbose)
    target_paths = args.paths or None

    if args.scan:
        result = scan_all(args.base_dir, paths=target_paths)
        print_scan_report(result)

    elif args.clean_icons:
        clean_icons(args.base_dir, dry_run=args.dry_run, paths=target_paths)

    elif args.convert:
        categories = None
        if args.category != "all":
            categories = [args.category]
        convert_images(
            base_dir=args.base_dir,
            limit=args.limit,
            dry_run=args.dry_run,
            model=args.model,
            categories=categories,
            workers=args.workers,
            paths=target_paths,
        )

    elif args.cleanup:
        cleanup_all_images(args.base_dir, dry_run=args.dry_run, paths=target_paths)


if __name__ == "__main__":
    main()
