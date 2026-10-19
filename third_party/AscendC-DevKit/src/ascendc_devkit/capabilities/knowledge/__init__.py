"""L5 Capabilities — Knowledge base document loader and search."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class IndexNode:
    """A node in the knowledge base index tree."""
    name: str
    path: Path | None = None
    children: dict[str, IndexNode] = field(default_factory=dict)


class KnowledgeBase:
    """Load and search AscendC knowledge base documents.

    Default root: <project>/.claude/skills/ascendc-dev-knowledge/references/
    INDEX.md files use markdown headings for hierarchy and markdown links
    for document references.
    """

    @staticmethod
    def _find_project_root() -> Path:
        """Walk up from this source file to find the project root (pyproject.toml)."""
        current = Path(__file__).resolve().parent
        for _ in range(8):
            if (current / "pyproject.toml").exists():
                return current
            current = current.parent
        raise FileNotFoundError(
            "Cannot locate project root: no pyproject.toml found in ancestor directories"
        )

    def __init__(self, root: Path | None = None):
        if root is None:
            # ascendc-dev-knowledge lives in the flat canonical skill tree; its
            # reference docs travel inside the skill dir.
            root = (
                self._find_project_root()
                / ".claude" / "skills"
                / "ascendc-dev-knowledge" / "references"
            )
        self._root = Path(root)
        self._cache: dict[str, str] = {}

    @property
    def root(self) -> Path:
        return self._root

    def load_index(self, index_path: Path | None = None) -> IndexNode:
        """Parse an INDEX.md file into a navigable document tree.

        Markdown headings (# ## ### ...) create nested IndexNodes.
        Link lines (- [Title](relative/path.md)) create leaf nodes with paths.

        If index_path is not absolute, it is resolved relative to self._root.
        """
        if index_path is None:
            index_path = self._root / "basic_knowledge_docs" / "INDEX.md"
        elif not index_path.is_absolute():
            index_path = self._root / index_path

        if not index_path.exists():
            return IndexNode(name=index_path.stem)

        content = index_path.read_text(encoding="utf-8")
        return self._parse_index_content(content, index_path.parent)

    def _parse_index_content(self, content: str, base_dir: Path) -> IndexNode:
        """Parse INDEX.md content into tree.

        The top-level # heading sets the root node's name.
        ## / ### / ... headings create nested children.
        - [Title](path) links create leaf nodes under the current heading.
        """
        root = IndexNode(name="root", path=None)
        # Stack of (heading_level, node). Level 0 = root.
        stack: list[tuple[int, IndexNode]] = [(0, root)]
        first_heading = True

        for line in content.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue

            heading_match = re.match(r'^(#{1,6})\s+(.+)', stripped)
            if heading_match:
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()

                if first_heading and level == 1:
                    # Top-level # heading renames the root
                    root.name = title
                    first_heading = False
                    continue

                first_heading = False
                node = IndexNode(name=title)

                # Pop until stack top level < current level
                while stack and stack[-1][0] >= level:
                    stack.pop()
                parent = stack[-1][1]
                parent.children[title] = node
                stack.append((level, node))
                continue

            # Link — add leaf node under current parent
            link_match = re.match(r'^[-*]\s+\[([^\]]+)\]\(([^)]+)\)', stripped)
            if link_match:
                title = link_match.group(1).strip()
                rel_path = link_match.group(2).strip()
                abs_path = (base_dir / rel_path).resolve()
                parent = stack[-1][1]
                parent.children[title] = IndexNode(name=title, path=abs_path)

        return root

    def load_document(self, doc_path: Path) -> str:
        """Read a knowledge document and return its full text."""
        if not doc_path.is_absolute():
            doc_path = self._root / doc_path

        key = str(doc_path)
        if key in self._cache:
            return self._cache[key]

        if not doc_path.exists():
            return ""

        try:
            content = doc_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

        self._cache[key] = content
        return content

    def search_api(self, api_name: str) -> dict | None:
        """Search for an API in the API reference index.

        Returns {"name": ..., "doc": ..., "path": ...} or None if not found.
        """
        index_path = self._root / "api_reference_docs" / "INDEX.md"
        if not index_path.exists():
            return None

        tree = self.load_index(index_path)

        def _find(node: IndexNode, target: str) -> IndexNode | None:
            if node.name == target and node.path is not None:
                return node
            for child in node.children.values():
                result = _find(child, target)
                if result is not None:
                    return result
            return None

        found = _find(tree, api_name)
        if found is None or found.path is None:
            return None

        doc_content = self.load_document(found.path)
        return {
            "name": found.name,
            "doc": doc_content,
            "path": str(found.path),
        }

    def list_available_indices(self) -> list[Path]:
        """List all INDEX.md files under the knowledge root."""
        results = []
        for p in sorted(self._root.rglob("INDEX.md")):
            results.append(p)
        return results
