#!/usr/bin/env python3
"""
AscendC Knowledge Base Spider

Crawls documentation from hiascend.com for six categories:
  - api_reference        (Ascend C算子开发接口)
  - basic_knowledge      (编程指南)
  - best_practice        (算子实践参考)
  - basic_data_api       (基础数据结构和接口)
  - troubleshooting      (故障处理)
  - log_reference        (日志参考)

Converts HTML to Markdown and generates INDEX.md files compatible
with the existing AscendC_knowledge directory structure.

Usage:
    python3 ascendc_spider.py -v 850 [OPTIONS]
    python3 ascendc_spider.py -v 900 -s best_practice -o /tmp/test_kb
    python3 ascendc_spider.py -v 850 -o /root/.claude/AscendC_knowledge
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import logging
import os
import re
import signal
import sys
import threading
import time
from html.parser import HTMLParser
import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_DOMAIN = "https://www.hiascend.com"
CONTENT_API_TPL = BASE_DOMAIN + "/doc_center/source/{base_path}/{page}"
DETAIL_PAGE_TPL = BASE_DOMAIN + "/document/detail/{base_path}/{page}"

SECTIONS_BY_VERSION = {
    "850": {
        "api_reference": {
            "base_path": "zh/CANNCommunityEdition/850/API/ascendcopapi",
            "root_page": "atlasascendc_api_07_0003.html",
            "page_prefixes": ["atlasascendc_api_07_"],
        },
        "basic_knowledge": {
            "base_path": "zh/CANNCommunityEdition/850/opdevg/Ascendcopdevg",
            "root_page": "atlas_ascendc_map_10_0004.html",
            "page_prefixes": ["atlas_ascendc_10_", "atlas_ascendc_map_10_", "atlas_ascendc_best_practices_10_"],
            "seed_pages": ["atlas_ascendc_best_practices_10_0001.html"],
        },
        "basic_data_api": {
            "base_path": "zh/CANNCommunityEdition/850/API/basicdataapi",
            "root_page": "atlasopapi_07_00001.html",
            "page_prefixes": ["atlasopapi_07_", "atlasgeapi_07_"],
        },
        "troubleshooting": {
            "base_path": "zh/CANNCommunityEdition/850/maintenref/troubleshooting",
            "root_page": "troubleshooting_0001.html",
            "page_prefixes": ["troubleshooting_", "atlaserrorcode_"],
            "seed_pages": ["troubleshooting_0002.html"],
        },
        "log_reference": {
            "base_path": "zh/CANNCommunityEdition/850/maintenref/logreference",
            "root_page": "logreference_0001.html",
            "page_prefixes": ["logreference_"],
            "scan_range": (1, 30),
            "scan_format": "logreference_{:04d}.html",
        },
    },
    "900beta1": {
        "api_reference": {
            "base_path": "zh/CANNCommunityEdition/900beta1/API/ascendcopapi",
            "root_page": "atlasascendc_api_07_0003.html",
            "page_prefixes": ["atlasascendc_api_07_"],
        },
        "basic_knowledge": {
            "base_path": "zh/CANNCommunityEdition/900beta1/opdevg/Ascendcopdevg",
            "root_page": "atlas_ascendc_map_10_0004.html",
            "page_prefixes": ["atlas_ascendc_10_", "atlas_ascendc_map_10_", "atlas_ascendc_best_practices_10_"],
            "seed_pages": ["atlas_ascendc_best_practices_10_0001.html"],
        },
        "basic_data_api": {
            "base_path": "zh/CANNCommunityEdition/900beta1/API/basicdataapi",
            "root_page": "atlasopapi_07_00001.html",
            "page_prefixes": ["atlasopapi_07_", "atlasgeapi_07_"],
        },
        "troubleshooting": {
            "base_path": "zh/CANNCommunityEdition/900beta1/maintenref/troubleshooting",
            "root_page": "troubleshooting_0001.html",
            "page_prefixes": ["troubleshooting_", "atlaserrorcode_"],
            "seed_pages": ["troubleshooting_0002.html"],
        },
        "log_reference": {
            "base_path": "zh/CANNCommunityEdition/900beta1/maintenref/logreference",
            "root_page": "logreference_0001.html",
            "page_prefixes": ["logreference_"],
            "scan_range": (1, 30),
            "scan_format": "logreference_{:04d}.html",
        },
    },
    "900": {
        "api_reference": {
            "base_path": "zh/CANNCommunityEdition/900/API/ascendcopapi",
            "root_page": "atlasascendc_api_07_0003.html",
            "page_prefixes": ["atlasascendc_api_07_"],
        },
        "basic_knowledge": {
            "base_path": "zh/CANNCommunityEdition/900/programug/Ascendcopdevg",
            "root_page": "atlas_ascendc_map_10_0002.html",
            "page_prefixes": ["atlas_ascendc_10_", "atlas_ascendc_map_10_", "atlas_ascendc_best_practices_10_"],
            "seed_pages": ["atlas_ascendc_best_practices_10_0001.html"],
        },
        "basic_data_api": {
            "base_path": "zh/CANNCommunityEdition/900/maintenref/basicdataapi",
            "root_page": "atlasopapi_07_00001.html",
            "page_prefixes": ["atlasopapi_07_", "atlasgeapi_07_"],
        },
        "troubleshooting": {
            "base_path": "zh/CANNCommunityEdition/900/maintenref/troubleshooting",
            "root_page": "troubleshooting_0001.html",
            "page_prefixes": ["troubleshooting_", "atlaserrorcode_"],
            "seed_pages": ["troubleshooting_0002.html"],
        },
        "log_reference": {
            "base_path": "zh/CANNCommunityEdition/900/maintenref/logreference",
            "root_page": "logreference_0001.html",
            "page_prefixes": ["logreference_"],
            "scan_range": (1, 30),
            "scan_format": "logreference_{:04d}.html",
        },
    },
}

# Set at runtime by CLI --version
SECTIONS: dict = {}

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# HTML to Markdown converter
# ---------------------------------------------------------------------------


class HtmlToMarkdown(HTMLParser):
    """Convert HTML to GitHub-Flavored Markdown using only the stdlib."""

    # Tags whose entire subtree should be suppressed
    SKIP_TAGS = {"script", "style", "nav"}
    SKIP_CLASSES = {"familylinks", "relinfo"}

    def __init__(self, page_id: str = "", base_url: str = ""):
        super().__init__(convert_charrefs=True)
        self.page_id = page_id
        self.base_url = base_url  # for resolving figure/ images

        # output buffer
        self._parts: list[str] = []

        # skip tracking: when > 0, all content is suppressed
        self._skip_depth = 0
        self._skip_tags: list[str] = []  # tag names that started each skip level

        # link stack for <a> tags
        self._link_stack: list[str] = []  # href values

        # list state
        self._list_stack: list[str] = []  # "ul" or "ol"
        self._ol_counter: list[int] = []

        # table state
        self._in_table = False
        self._current_row: list[str] = []  # list of cell strings
        self._cell_buf: list[str] = []  # accumulator for current cell
        self._in_cell = False
        self._in_caption = False
        self._caption_buf: list[str] = []
        self._header_row = False
        self._table_rows: list[list[str]] = []

        # code table state (syntax-highlighted <table class="highlighttable">)
        self._code_table = False
        self._skip_linenos = False

        # inline state
        self._in_pre = False
        self._pre_buffer: list[str] = []
        self._in_code = False

        # note/notice state
        self._in_note = False
        self._note_depth = 0  # nesting depth of the note div

        # image counter
        self.image_urls: list[tuple[str, str]] = []  # (src_url, local_name)
        self._img_counter = 0

    # -- helpers --

    @property
    def _skipping(self) -> bool:
        return self._skip_depth > 0

    def _emit(self, text: str):
        if self._skipping or self._skip_linenos:
            return
        if self._in_pre:
            self._pre_buffer.append(text)
            return
        if self._in_caption:
            self._caption_buf.append(text)
            return
        if self._in_cell:
            self._cell_buf.append(text)
            return
        self._parts.append(text)

    def _ensure_newlines(self, n: int = 2):
        """Ensure at least n trailing newlines in the output."""
        if self._skipping or self._in_cell:
            return
        tail = "".join(self._parts[-5:]) if self._parts else ""
        existing = len(tail) - len(tail.rstrip("\n"))
        needed = max(0, n - existing)
        if needed:
            self._parts.append("\n" * needed)

    def _list_indent(self) -> str:
        depth = max(0, len(self._list_stack) - 1)
        return "  " * depth

    def _convert_href(self, href: str) -> str:
        """Convert internal .html links to .md references."""
        if not href:
            return href
        if href.startswith(("#", "http://", "https://", "/")):
            return href
        if href.endswith(".html"):
            return href.replace(".html", ".md")
        return href

    # -- parser callbacks --

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        attr_dict = dict(attrs)
        cls = attr_dict.get("class", "") or ""

        # Check for skip conditions
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
            self._skip_tags.append(tag)
            return
        if any(sc in cls for sc in self.SKIP_CLASSES):
            self._skip_depth += 1
            self._skip_tags.append(tag)
            return

        if self._skipping:
            # Track same-named tags inside skip region to handle nesting
            if self._skip_tags and tag == self._skip_tags[-1]:
                self._skip_depth += 1
            return

        # -- block elements --
        if tag in ("h1", "h2", "h3", "h4", "h5"):
            level = int(tag[1])
            self._ensure_newlines(2)
            self._emit("#" * level + " ")

        elif tag == "p":
            if not self._in_table:
                self._ensure_newlines(2)

        elif tag == "br":
            self._emit("\n")

        elif tag == "pre":
            self._in_pre = True
            self._pre_buffer = []
            self._ensure_newlines(2)

        elif tag == "code":
            if not self._in_pre:
                self._in_code = True
                self._emit("`")

        elif tag in ("strong", "b"):
            self._emit("**")

        elif tag in ("em", "i"):
            self._emit("*")

        elif tag == "ul":
            if not self._in_table:
                self._ensure_newlines(2)
            self._list_stack.append("ul")

        elif tag == "ol":
            if not self._in_table:
                self._ensure_newlines(2)
            self._list_stack.append("ol")
            self._ol_counter.append(0)

        elif tag == "li":
            if self._list_stack:
                if not self._in_table:
                    self._ensure_newlines(1)
                indent = self._list_indent()
                if self._list_stack[-1] == "ol":
                    self._ol_counter[-1] += 1
                    self._emit(f"{indent}{self._ol_counter[-1]}. ")
                else:
                    self._emit(f"{indent}- ")

        elif tag == "table":
            classes = cls.split()
            if "highlighttable" in classes:
                # Syntax-highlight code table: skip line numbers, let <pre> render normally
                self._code_table = True
                self._ensure_newlines(2)
            else:
                self._code_table = False
                self._in_table = True
                self._table_rows = []
                self._caption_buf = []
                self._ensure_newlines(2)

        elif tag == "caption":
            self._in_caption = True
            self._caption_buf = []

        elif tag == "thead":
            self._header_row = True

        elif tag == "tr":
            if not self._code_table:
                self._current_row = []

        elif tag in ("th", "td"):
            if self._code_table:
                # In code tables, skip the linenos column
                if "linenos" in cls.split():
                    self._skip_linenos = True
            else:
                if tag == "th":
                    self._header_row = True
                self._in_cell = True
                self._cell_buf = []

        elif tag == "a":
            href = attr_dict.get("href", "") or ""
            self._link_stack.append(href)
            if href:
                self._emit("[")

        elif tag == "img":
            src = attr_dict.get("src", "") or ""
            alt = attr_dict.get("alt", "") or ""
            # Skip system resource icons (note/caution/warning icons)
            if src and "public_sys-resources/" not in src:
                self._img_counter += 1
                img_name = f"{self.page_id}_img_{self._img_counter:03d}.png"
                # Resolve image URL
                if src.startswith(("http://", "https://")):
                    full_url = src
                elif self.base_url:
                    full_url = self.base_url.rsplit("/", 1)[0] + "/" + src
                else:
                    full_url = src
                self.image_urls.append((full_url, img_name))
                self._emit(f"![{alt}](../images/{img_name})")

        elif tag == "div":
            classes = cls.split()
            if any(c in ("note", "notice", "caution", "warning") for c in classes):
                self._in_note = True
                self._note_depth = 0
                self._ensure_newlines(2)
                self._emit("> **注意:** ")

        # Track div nesting inside a note block
        if tag == "div" and self._in_note:
            self._note_depth += 1

    def handle_endtag(self, tag: str):
        # Handle skip stack
        if self._skipping:
            if self._skip_tags and tag == self._skip_tags[-1]:
                self._skip_depth -= 1
                if self._skip_depth == 0:
                    self._skip_tags.pop()
            return

        if tag in ("h1", "h2", "h3", "h4", "h5"):
            self._ensure_newlines(2)

        elif tag == "p":
            if not self._in_table:
                self._ensure_newlines(2)

        elif tag == "pre":
            code_text = "".join(self._pre_buffer).strip()
            self._in_pre = False
            self._pre_buffer = []
            self._emit(f"```\n{code_text}\n```")
            self._ensure_newlines(2)

        elif tag == "code":
            if self._in_code:
                self._emit("`")
                self._in_code = False

        elif tag in ("strong", "b"):
            self._emit("**")

        elif tag in ("em", "i"):
            self._emit("*")

        elif tag == "ul":
            if self._list_stack and self._list_stack[-1] == "ul":
                self._list_stack.pop()
            if not self._in_table:
                self._ensure_newlines(2)

        elif tag == "ol":
            if self._list_stack and self._list_stack[-1] == "ol":
                self._list_stack.pop()
            if self._ol_counter:
                self._ol_counter.pop()
            if not self._in_table:
                self._ensure_newlines(2)

        elif tag == "thead":
            self._header_row = False

        elif tag == "caption":
            self._in_caption = False

        elif tag in ("th", "td"):
            if self._code_table:
                self._skip_linenos = False
            else:
                # Finalize current cell
                cell_text = "".join(self._cell_buf).strip().replace("\n", " ").replace("|", "\\|")
                self._current_row.append(cell_text)
                self._in_cell = False
                self._cell_buf = []

        elif tag == "tr":
            if not self._code_table and self._current_row is not None:
                if self._header_row:
                    self._header_row = False
                self._table_rows.append(self._current_row)
            self._current_row = []

        elif tag == "table":
            if self._code_table:
                self._code_table = False
                self._ensure_newlines(2)
            else:
                self._flush_table()
                self._in_table = False
                self._ensure_newlines(2)

        elif tag == "a":
            href = self._link_stack.pop() if self._link_stack else ""
            if href:
                md_href = self._convert_href(href)
                self._emit(f"]({md_href})")

        elif tag == "div":
            if self._in_note:
                self._note_depth -= 1
                if self._note_depth <= 0:
                    self._in_note = False
                    self._ensure_newlines(2)

    def handle_data(self, data: str):
        if self._skipping or self._skip_linenos:
            return
        if self._in_pre:
            self._pre_buffer.append(data)
            return
        if self._in_caption:
            self._caption_buf.append(data)
            return
        if self._in_cell:
            self._cell_buf.append(data)
            return
        # Skip whitespace-only data (from HTML indentation / structural tags)
        if not data.strip():
            return
        if self._in_note:
            self._parts.append(data.replace("\n", "\n> "))
            return
        self._parts.append(data)

    def _flush_table(self):
        """Render accumulated table rows as GFM table."""
        # Emit caption if present
        caption_text = "".join(self._caption_buf).strip()
        if caption_text:
            self._parts.append(caption_text + "\n\n")

        if not self._table_rows:
            return

        # Ensure all rows have the same number of columns
        max_cols = max(len(r) for r in self._table_rows) if self._table_rows else 0
        if max_cols == 0:
            return

        for row in self._table_rows:
            while len(row) < max_cols:
                row.append("")

        # First row is header (or becomes header)
        header = self._table_rows[0]
        self._parts.append("| " + " | ".join(header) + " |\n")
        self._parts.append("| " + " | ".join(["---"] * max_cols) + " |\n")
        for row in self._table_rows[1:]:
            self._parts.append("| " + " | ".join(row) + " |\n")

    def get_markdown(self) -> str:
        text = "".join(self._parts)
        # Remove lines that contain only whitespace
        text = re.sub(r"\n[ \t]+\n", "\n\n", text)
        # Collapse 3+ consecutive blank lines to 2
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip() + "\n"


def html_to_markdown(html_content: str, page_id: str = "", base_url: str = "") -> tuple[str, list[tuple[str, str]]]:
    """
    Convert HTML string to Markdown.

    Returns:
        (markdown_text, [(image_url, local_filename), ...])
    """
    converter = HtmlToMarkdown(page_id=page_id, base_url=base_url)
    converter.feed(html_content)
    return converter.get_markdown(), converter.image_urls


# ---------------------------------------------------------------------------
# Link extraction (also stdlib-based)
# ---------------------------------------------------------------------------

class LinkExtractor(HTMLParser):
    """Extract href links from HTML."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if tag == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self.links.append(value)


def extract_links(html_content: str) -> list[str]:
    """Extract all href values from <a> tags."""
    extractor = LinkExtractor()
    extractor.feed(html_content)
    return extractor.links


# ---------------------------------------------------------------------------
# Title extractor
# ---------------------------------------------------------------------------

class TitleExtractor(HTMLParser):
    """Extract <title> content from partial HTML."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self.title = ""

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def extract_title(html_partial: str) -> str:
    """Extract title from (possibly partial) HTML."""
    ext = TitleExtractor()
    try:
        ext.feed(html_partial)
    except Exception:
        pass
    return ext.title.strip()


# ---------------------------------------------------------------------------
# Spider
# ---------------------------------------------------------------------------

class AscendCSpider:
    """BFS spider for AscendC documentation with concurrent fetching."""

    def __init__(
        self,
        output_dir: str,
        sections: list[str],
        version: str = "850",
        workers: int = 8,
        delay: float = 0.05,
        timeout: int = 15,
        retries: int = 3,
        log_file: str | None = None,
    ):
        self.output_dir = os.path.abspath(output_dir)
        self.sections = sections
        self.version = version
        self.workers = workers
        self.delay = delay
        self.timeout = timeout
        self.retries = retries

        # Global rate limiter (shared across threads)
        self._rate_lock = threading.Lock()
        self._last_request_time = 0.0

        # Set up logging
        self.logger = logging.getLogger(f"ascendc_spider_{version}")
        self.logger.setLevel(logging.DEBUG)
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Console handler
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        ch.setFormatter(fmt)
        self.logger.addHandler(ch)

        # File handler
        if log_file is None:
            log_file = os.path.join(self.output_dir, "spider.log")
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        fh = logging.FileHandler(log_file, mode="w", encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        self.logger.addHandler(fh)

        # HTTP session (thread-safe for requests.Session)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

        # Graceful shutdown
        self._interrupted = False
        signal.signal(signal.SIGINT, self._handle_sigint)

    def _handle_sigint(self, signum, frame):
        self.logger.warning("收到中断信号 (Ctrl+C)，正在保存已完成的数据...")
        self._interrupted = True

    # -- HTTP helpers --

    def _rate_limit(self):
        """Enforce minimum interval between requests across all threads."""
        with self._rate_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self.delay:
                time.sleep(self.delay - elapsed)
            self._last_request_time = time.monotonic()

    def _fetch(self, url: str, stream: bool = False, max_bytes: int = 0) -> requests.Response | None:
        """Fetch a URL with rate limiting, retries and exponential backoff."""
        for attempt in range(1, self.retries + 1):
            self._rate_limit()
            try:
                resp = self.session.get(
                    url, timeout=self.timeout, stream=stream
                )
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", "30"))
                    self.logger.warning(
                        "HTTP 429 限流, 等待 %ds (attempt %d/%d)",
                        retry_after, attempt, self.retries,
                    )
                    time.sleep(retry_after)
                    continue
                resp.raise_for_status()

                if stream and max_bytes > 0:
                    chunks = []
                    received = 0
                    for chunk in resp.iter_content(chunk_size=4096):
                        chunks.append(chunk)
                        received += len(chunk)
                        if received >= max_bytes:
                            break
                    resp._content = b"".join(chunks)
                    resp.close()

                return resp

            except requests.exceptions.RequestException as e:
                wait = 2 ** (attempt - 1)
                self.logger.warning(
                    "请求失败 %s (attempt %d/%d): %s, 等待 %ds",
                    url, attempt, self.retries, e, wait,
                )
                if attempt < self.retries:
                    time.sleep(wait)

        self.logger.error("请求最终失败 (已重试 %d 次): %s", self.retries, url)
        return None

    def fetch_content(self, base_path: str, page: str) -> str | None:
        """Fetch clean HTML content from /doc_center/source/."""
        url = CONTENT_API_TPL.format(base_path=base_path, page=page)
        resp = self._fetch(url)
        if resp is not None:
            resp.encoding = "utf-8"
            return resp.text
        return None

    def fetch_title(self, base_path: str, page: str) -> str:
        """Fetch page title from /document/detail/ (streaming, first 15KB)."""
        url = DETAIL_PAGE_TPL.format(base_path=base_path, page=page)
        resp = self._fetch(url, stream=True, max_bytes=15 * 1024)
        if resp is not None:
            resp.encoding = "utf-8"
            return extract_title(resp.text)
        return ""

    def download_image(self, url: str, save_path: str) -> bool:
        """Download an image file."""
        resp = self._fetch(url)
        if resp is not None:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(resp.content)
            return True
        return False

    # -- Per-page processing (runs in worker threads) --

    def _process_page(
        self,
        base_path: str,
        prefixes: list[str],
        pages_dir: str,
        images_dir: str,
        page_filename: str,
    ) -> tuple[dict | None, list[str]]:
        """
        Fetch, convert and save a single page. Thread-safe.

        Returns:
            (page_meta_dict or None, list_of_discovered_links)
        """
        page_id = page_filename.replace(".html", "")

        # 1. Fetch content
        html_content = self.fetch_content(base_path, page_filename)
        if html_content is None:
            self.logger.error("跳过页面 (内容获取失败): %s", page_id)
            return None, []

        # 2. Fetch title
        title = self.fetch_title(base_path, page_filename)
        if not title:
            title = page_id
            self.logger.warning("标题获取失败，使用 page_id: %s", page_id)

        # 3. Extract and filter links
        new_links = []
        for link in extract_links(html_content):
            if not link.endswith(".html"):
                continue
            if link.startswith(("http://", "https://", "#", "/")):
                continue
            if "/" in link:
                continue
            if not any(link.startswith(p) for p in prefixes):
                continue
            new_links.append(link)

        # 4. Convert HTML to Markdown
        page_content_url = CONTENT_API_TPL.format(
            base_path=base_path, page=page_filename
        )
        md_text, image_list = html_to_markdown(
            html_content, page_id=page_id, base_url=page_content_url
        )

        # 5. Download images
        downloaded_images = []
        for img_url, img_name in image_list:
            img_path = os.path.join(images_dir, img_name)
            if self.download_image(img_url, img_path):
                downloaded_images.append(img_name)
                self.logger.debug("  下载图片: %s", img_name)
            else:
                self.logger.warning("  图片下载失败: %s", img_url)

        # 6. Build and save page .md
        table_count = md_text.count("| ---")
        source_url = DETAIL_PAGE_TPL.format(
            base_path=base_path, page=page_filename
        )
        page_md = (
            f"# {title}\n"
            f"**页面ID:** {page_id}\n"
            f"**来源:** {source_url}\n"
            f"---\n\n"
            f"{md_text}\n"
        )
        md_path = os.path.join(pages_dir, f"{page_id}.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(page_md)

        meta = {
            "page_id": page_id,
            "title": title,
            "source_url": source_url,
            "table_count": table_count,
            "image_count": len(downloaded_images),
            "images": downloaded_images,
        }
        return meta, new_links

    # -- Core crawl logic --

    def _scan_existing_pages(
        self, base_path: str, scan_range: tuple[int, int], scan_format: str,
    ) -> list[str]:
        """Probe page numbers in range to find existing pages (for sparse-linking sections)."""
        start, end = scan_range
        found: list[str] = []
        lock = threading.Lock()

        def probe(num: int):
            page = scan_format.format(num)
            url = CONTENT_API_TPL.format(base_path=base_path, page=page)
            self._rate_limit()
            try:
                resp = self.session.get(url, timeout=self.timeout)
                if resp.status_code == 200 and len(resp.content) > 200:
                    with lock:
                        found.append(page)
            except requests.exceptions.RequestException:
                pass

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.workers
        ) as executor:
            executor.map(probe, range(start, end + 1))

        found.sort()
        return found

    def crawl_section(self, section_name: str) -> dict:
        """Crawl a section using BFS (default) or scan mode (for sparse-linking sections)."""
        cfg = SECTIONS[section_name]
        base_path = cfg["base_path"]
        root_page = cfg["root_page"]
        prefixes = cfg["page_prefixes"]

        section_dir = os.path.join(self.output_dir, section_name)
        pages_dir = os.path.join(section_dir, "pages")
        images_dir = os.path.join(section_dir, "images")
        os.makedirs(pages_dir, exist_ok=True)
        os.makedirs(images_dir, exist_ok=True)

        # Determine initial page set
        scan_range = cfg.get("scan_range")
        seed_pages = cfg.get("seed_pages", [])
        if scan_range:
            scan_format = cfg["scan_format"]
            self.logger.info("=== 开始扫描分类: %s (scan %d-%d, workers=%d) ===",
                             section_name, scan_range[0], scan_range[1], self.workers)
            all_pages = self._scan_existing_pages(base_path, scan_range, scan_format)
            self.logger.info("扫描发现 %d 个有效页面", len(all_pages))
            queue = collections.deque(all_pages)
            visited = set(all_pages)
        else:
            self.logger.info("=== 开始爬取分类: %s (workers=%d) ===",
                             section_name, self.workers)
            self.logger.info("根页面: %s", root_page)
            queue = collections.deque([root_page])
            visited = {root_page}
            # Add extra seed pages for sections where root page lacks child links
            for sp in seed_pages:
                if sp not in visited:
                    visited.add(sp)
                    queue.append(sp)
            if seed_pages:
                self.logger.info("额外种子页: %s", seed_pages)

        self.logger.info("前缀过滤: %s", prefixes)

        pages_meta: list[dict] = []
        total_images = 0
        active: dict[concurrent.futures.Future, str] = {}

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.workers
        ) as executor:
            # Seed initial tasks from queue
            while queue and len(active) < self.workers:
                page = queue.popleft()
                future = executor.submit(
                    self._process_page,
                    base_path, prefixes, pages_dir, images_dir, page,
                )
                active[future] = page

            while active and not self._interrupted:
                # Wait for at least one task to complete
                done, _ = concurrent.futures.wait(
                    active,
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )

                for future in done:
                    page_filename = active.pop(future)
                    page_id = page_filename.replace(".html", "")

                    try:
                        meta, new_links = future.result()
                    except Exception:
                        self.logger.exception(
                            "页面处理异常: %s", page_id
                        )
                        continue

                    if meta:
                        pages_meta.append(meta)
                        total_images += meta["image_count"]
                        self.logger.info(
                            "[%s] 完成 %d (并发: %d, 队列: %d): %s "
                            "| 表格=%d, 图片=%d",
                            section_name,
                            len(pages_meta),
                            len(active),
                            len(queue),
                            meta["title"][:50],
                            meta["table_count"],
                            meta["image_count"],
                        )

                    # Enqueue newly discovered links (also works in scan mode for extra coverage)
                    for link in new_links:
                        if link not in visited:
                            visited.add(link)
                            queue.append(link)

                # Fill worker slots from queue
                while queue and len(active) < self.workers and not self._interrupted:
                    page = queue.popleft()
                    future = executor.submit(
                        self._process_page,
                        base_path, prefixes, pages_dir, images_dir, page,
                    )
                    active[future] = page

        self.logger.info(
            "=== 分类 %s 完成: %d 页面, %d 图片 ===",
            section_name, len(pages_meta), total_images,
        )

        return {
            "section_name": section_name,
            "pages": pages_meta,
            "total_images": total_images,
        }

    def generate_index(self, section_meta: dict):
        """Generate INDEX.md for a section."""
        section_name = section_meta["section_name"]
        pages = section_meta["pages"]
        total_images = section_meta["total_images"]

        index_path = os.path.join(
            self.output_dir, section_name, "INDEX.md"
        )

        lines = [
            f"# {section_name} 文档索引\n",
            f"\n**总页面数**: {len(pages)}",
            f"\n**总图片数**: {total_images}",
            "\n\n---\n",
            "\n## 页面列表\n",
        ]

        for pm in pages:
            lines.append(f"\n### {pm['page_id']}")
            lines.append(f"\n- 标题: {pm['title']}")
            lines.append(
                f"\n- 文件: [pages/{pm['page_id']}.md](pages/{pm['page_id']}.md)"
            )
            lines.append(f"\n- URL: {pm['source_url']}")
            lines.append(
                f"\n- 表格: {pm['table_count']}, 图片: {pm['image_count']}"
            )
            if pm["images"]:
                lines.append("\n- 图片列表:")
                for img in pm["images"]:
                    lines.append(f"\n  - [images/{img}](images/{img})")
            lines.append("\n")

        with open(index_path, "w", encoding="utf-8") as f:
            f.write("".join(lines))

        self.logger.info("INDEX.md 已生成: %s", index_path)

    def run(self):
        """Run the spider for all configured sections."""
        self.logger.info("版本: %s", self.version)
        self.logger.info("输出目录: %s", self.output_dir)
        self.logger.info("爬取分类: %s", ", ".join(self.sections))
        self.logger.info(
            "并发: %d workers, 请求间隔: %.2fs (有效QPS上限≈%.0f), "
            "超时: %ds, 重试: %d",
            self.workers, self.delay,
            1.0 / self.delay if self.delay > 0 else float("inf"),
            self.timeout, self.retries,
        )
        os.makedirs(self.output_dir, exist_ok=True)

        results = {}
        for section in self.sections:
            if section not in SECTIONS:
                self.logger.error("未知分类: %s, 跳过", section)
                continue
            meta = self.crawl_section(section)
            self.generate_index(meta)
            results[section] = meta
            if self._interrupted:
                self.logger.warning("中断处理，已保存 %s 的 INDEX.md", section)
                break

        # Summary
        self.logger.info("=" * 50)
        self.logger.info("爬取完成摘要:")
        for name, meta in results.items():
            self.logger.info(
                "  %s: %d 页面, %d 图片",
                name, len(meta["pages"]), meta["total_images"],
            )
        self.logger.info("=" * 50)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="AscendC Knowledge Base Spider — 从 hiascend.com 爬取文档并转为 Markdown",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-v", "--version",
        required=True,
        choices=list(SECTIONS_BY_VERSION.keys()),
        help="CANN 文档版本 (例如: 850, 900, 900beta1)",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="输出目录 (默认: <skill>/references/cache)",
    )
    parser.add_argument(
        "-s", "--sections",
        nargs="+",
        default=None,
        help="要爬取的分类 (默认: 全部)",
    )
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=8,
        help="并发线程数 (默认: 8)",
    )
    parser.add_argument(
        "-d", "--delay",
        type=float,
        default=0.05,
        help="请求最小间隔秒数, 全局速率控制 (默认: 0.05, 即≈20 QPS)",
    )
    parser.add_argument(
        "-t", "--timeout",
        type=int,
        default=15,
        help="请求超时秒数 (默认: 15)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="最大重试次数 (默认: 3)",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="日志文件路径 (默认: 输出目录下 spider.log)",
    )

    args = parser.parse_args()

    # Select version-specific sections config
    global SECTIONS
    SECTIONS = SECTIONS_BY_VERSION[args.version]

    # Default output path: skill's references/cache directory
    if args.output is None:
        _skill = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "references")
        args.output = os.path.join(_skill, "cache")

    # Default sections: all in the selected version
    if args.sections is None:
        args.sections = list(SECTIONS.keys())
    else:
        # Validate section names
        for s in args.sections:
            if s not in SECTIONS:
                parser.error(f"未知分类 '{s}', 可选: {list(SECTIONS.keys())}")

    spider = AscendCSpider(
        output_dir=args.output,
        sections=args.sections,
        version=args.version,
        workers=args.workers,
        delay=args.delay,
        timeout=args.timeout,
        retries=args.retries,
        log_file=args.log_file,
    )
    spider.run()


if __name__ == "__main__":
    main()
