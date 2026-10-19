"""UT for KnowledgeBase — INDEX.md parsing and API search."""

import tempfile
from pathlib import Path

import pytest

from ascendc_devkit.capabilities.knowledge import KnowledgeBase, IndexNode


class TestIndexNode:
    def test_creation_minimal(self):
        node = IndexNode(name="test")
        assert node.name == "test"
        assert node.path is None
        assert node.children == {}

    def test_creation_with_path(self):
        p = Path("/some/doc.md")
        node = IndexNode(name="Doc", path=p)
        assert node.path == p

    def test_children_mutable(self):
        node = IndexNode(name="parent")
        child = IndexNode(name="child")
        node.children["child"] = child
        assert node.children["child"] is child


class TestKnowledgeBase:
    def test_root_default(self):
        kb = KnowledgeBase()
        assert kb.root.name == "references"

    def test_root_custom(self, tmp_path):
        kb = KnowledgeBase(root=tmp_path)
        assert kb.root == tmp_path

    def test_load_index_basic(self, tmp_path):
        index_content = """# Test Index

## Section A

- [Doc 1](doc1.md)
- [Doc 2](doc2.md)

## Section B

### Sub B

- [Doc 3](sub/doc3.md)
"""
        index_path = tmp_path / "INDEX.md"
        index_path.write_text(index_content)

        kb = KnowledgeBase(root=tmp_path)
        tree = kb.load_index(index_path)

        assert "Section A" in tree.children
        assert "Section B" in tree.children
        section_a = tree.children["Section A"]
        assert "Doc 1" in section_a.children
        assert "Doc 2" in section_a.children
        assert section_a.children["Doc 1"].path is not None
        assert section_a.children["Doc 2"].path is not None

    def test_load_index_nested_hierarchy(self, tmp_path):
        index_content = """# Root

## Level 1

### Level 2

- [Leaf](leaf.md)

## Another L1

- [Direct](direct.md)
"""
        index_path = tmp_path / "INDEX.md"
        index_path.write_text(index_content)

        kb = KnowledgeBase(root=tmp_path)
        tree = kb.load_index(index_path)

        l1 = tree.children["Level 1"]
        l2 = l1.children["Level 2"]
        assert "Leaf" in l2.children
        assert l2.children["Leaf"].path is not None

        al1 = tree.children["Another L1"]
        assert "Direct" in al1.children

    def test_load_index_missing_file(self, tmp_path):
        kb = KnowledgeBase(root=tmp_path)
        tree = kb.load_index(tmp_path / "nonexistent.md")
        assert tree.name == "nonexistent"

    def test_load_index_empty_content(self, tmp_path):
        index_path = tmp_path / "INDEX.md"
        index_path.write_text("")
        kb = KnowledgeBase(root=tmp_path)
        tree = kb.load_index(index_path)
        assert tree.name == "root"
        assert tree.children == {}

    def test_load_document_reads_content(self, tmp_path):
        doc_path = tmp_path / "doc.md"
        doc_path.write_text("# My Doc\nContent here.")

        kb = KnowledgeBase(root=tmp_path)
        content = kb.load_document(doc_path)
        assert "My Doc" in content
        assert "Content here" in content

    def test_load_document_caches(self, tmp_path):
        doc_path = tmp_path / "doc.md"
        doc_path.write_text("v1")
        kb = KnowledgeBase(root=tmp_path)
        kb.load_document(doc_path)
        # Overwrite file
        doc_path.write_text("v2")
        # Should return cached v1
        content = kb.load_document(doc_path)
        assert content == "v1"

    def test_load_document_missing_file(self, tmp_path):
        kb = KnowledgeBase(root=tmp_path)
        content = kb.load_document(tmp_path / "nonexistent.md")
        assert content == ""

    def test_search_api_finds_match(self, tmp_path):
        index_content = """# API Index

## Data Movement

- [DataCopy](DataCopy.md)
- [DataMove](DataMove.md)
"""
        api_dir = tmp_path / "api_reference_docs"
        api_dir.mkdir(parents=True)
        (api_dir / "INDEX.md").write_text(index_content)
        (api_dir / "DataCopy.md").write_text("# DataCopy\n\nCopies data between memory regions.")

        kb = KnowledgeBase(root=tmp_path)
        result = kb.search_api("DataCopy")
        assert result is not None
        assert result["name"] == "DataCopy"
        assert "Copies data" in result["doc"]

    def test_search_api_not_found(self, tmp_path):
        index_content = "# API Index\n\n- [VecAdd](VecAdd.md)"
        index_path = tmp_path / "api_reference_docs" / "INDEX.md"
        index_path.parent.mkdir(parents=True)
        index_path.write_text(index_content)

        kb = KnowledgeBase(root=tmp_path)
        result = kb.search_api("NonExistent")
        assert result is None

    def test_search_api_no_index(self, tmp_path):
        kb = KnowledgeBase(root=tmp_path)
        result = kb.search_api("Anything")
        assert result is None

    def test_list_available_indices(self, tmp_path):
        (tmp_path / "basic_knowledge_docs").mkdir(parents=True)
        (tmp_path / "api_reference_docs").mkdir(parents=True)
        (tmp_path / "basic_knowledge_docs" / "INDEX.md").write_text("# Basic")
        (tmp_path / "api_reference_docs" / "INDEX.md").write_text("# API")

        kb = KnowledgeBase(root=tmp_path)
        indices = kb.list_available_indices()
        assert len(indices) == 2

    def test_real_knowledge_base(self):
        """Integration test: verify the real knowledge base can be loaded."""
        kb = KnowledgeBase()
        # At a minimum, the API reference INDEX should exist
        assert kb.root.exists()

        # Try loading the API reference index
        api_index = kb.root / "api_reference_docs" / "INDEX.md"
        if api_index.exists():
            tree = kb.load_index(api_index)
            assert len(tree.name) > 0  # named after # heading
            assert len(tree.children) > 0

        # Try searching for a known API
        result = kb.search_api("DataCopy")
        if result is not None:
            assert "name" in result
            assert "doc" in result
