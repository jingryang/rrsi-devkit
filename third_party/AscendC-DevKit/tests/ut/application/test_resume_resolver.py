"""UT for L2 resume_resolver — unify ``--resume <id>`` by id LOCATION.

See docs/plan/self-evolution/54-batch-id-hierarchy-resume-impl.md §2.4.
Three detection states (mutually exclusive by location, not string — batch_id
and execution_id share the ts+uuid format):
  1. output/<id>/state_snapshot.json      → flat single run
  2. output/<id>/ contains run subdirs    → batch
  3. output/*/<id>/state_snapshot.json    → nested execution (single)
Pure filesystem logic, no backend.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ascendc_devkit.application.resume_resolver import resolve_resume_target
from ascendc_devkit.domain.exceptions import ConfigError


def _make_run(d: Path) -> None:
    """Create a dir that looks like a run (has state_snapshot.json)."""
    d.mkdir(parents=True)
    (d / "state_snapshot.json").write_text("{}", encoding="utf-8")


def _output_root(tmp_path: Path) -> str:
    return str(tmp_path / "output")


class TestResolveResumeTarget:
    def test_flat_single_run(self, tmp_path):
        rid = "20260717-120000-aaaaaa"
        _make_run(tmp_path / "output" / rid)
        t = resolve_resume_target(rid, _output_root(tmp_path))
        assert t.kind == "single"
        assert t.id == rid
        assert t.output_root == _output_root(tmp_path)

    def test_top_batch(self, tmp_path):
        bid = "20260717-120000-bbbbbb"
        _make_run(tmp_path / "output" / bid / "20260717-120000-cccccc")
        _make_run(tmp_path / "output" / bid / "20260717-120000-dddddd")
        t = resolve_resume_target(bid, _output_root(tmp_path))
        assert t.kind == "batch"
        assert t.id == bid
        assert t.output_root == _output_root(tmp_path)

    def test_nested_execution_is_single_scoped_to_batch(self, tmp_path):
        bid = "20260717-120000-bbbbbb"
        eid = "20260717-120000-eeeeee"
        _make_run(tmp_path / "output" / bid / eid)
        t = resolve_resume_target(eid, _output_root(tmp_path))
        assert t.kind == "single"
        assert t.id == eid
        # output_root scoped to the batch dir so dispatch loads the nested run
        assert t.output_root == str(tmp_path / "output" / bid)

    def test_not_found_raises(self, tmp_path):
        (tmp_path / "output").mkdir()
        with pytest.raises(ConfigError):
            resolve_resume_target("20260717-120000-nope", _output_root(tmp_path))

    def test_empty_batch_dir_not_treated_as_batch(self, tmp_path):
        """A dir that exists but holds no run subdirs is neither a run nor a
        batch → falls through to nested glob → 0 matches → ConfigError."""
        bid = "20260717-120000-empty"
        (tmp_path / "output" / bid).mkdir(parents=True)
        with pytest.raises(ConfigError):
            resolve_resume_target(bid, _output_root(tmp_path))

    def test_batch_takes_priority_over_nested_glob(self, tmp_path):
        """If an id is BOTH a top-level batch dir AND happens to nest somewhere,
        the direct batch dir wins (state 2 before state 3). Construct: a batch
        dir B containing exec E, and E's name also used as a flat run — resuming
        E resolves to the flat run (state 1), resuming B resolves to batch."""
        bid = "20260717-120000-batch1"
        eid = "20260717-120000-exec1"
        _make_run(tmp_path / "output" / bid / eid)      # nested exec
        _make_run(tmp_path / "output" / eid)            # also a flat run
        # eid direct → flat single run (state 1 wins, direct snapshot exists)
        t = resolve_resume_target(eid, _output_root(tmp_path))
        assert t.kind == "single"
        # bid → batch
        t2 = resolve_resume_target(bid, _output_root(tmp_path))
        assert t2.kind == "batch"
