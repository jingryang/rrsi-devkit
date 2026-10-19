"""step-8 §P1 task 5 — data-flow (c): per-template tiling isolation + re-injection.

Covers:
  - TilingStage._working_dir isolates each template under
    design/tiling/<template>/ (cures P2 product overwrite).
  - design_artifacts_to_state rebuilds State fields from materialized products,
    reusing each stage's artifact_contract().parse() (single-sourced schema).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.kernel.action import SpawnAgent
from ascendc_devkit.orchestration.stages.design_substages import (
    TilingStage, GeneralDesignStage,
)
from ascendc_devkit.orchestration.design_artifacts import (
    design_artifacts_to_state,
)


class _FakeWorkspace:
    def __init__(self, root: Path):
        self.artifacts = root


class TestTilingWorkingDirIsolation:
    def test_each_template_gets_own_subdir(self, tmp_path):
        state = State.empty().with_updates(
            _workspace=_FakeWorkspace(tmp_path),
            template_division={"templates": [{"name": "T1"}, {"name": "T2"}]})
        wd1 = TilingStage(template={"name": "T1"})._working_dir(state)
        wd2 = TilingStage(template={"name": "T2"})._working_dir(state)
        assert wd1 == tmp_path / "design" / "tiling" / "T1"
        assert wd2 == tmp_path / "design" / "tiling" / "T2"
        assert wd1 != wd2

    def test_tiling_stage_working_dir(self, tmp_path):
        state = State.empty().with_updates(_workspace=_FakeWorkspace(tmp_path))
        wd = TilingStage(template={"name": "T1"})._working_dir(state)
        assert wd == tmp_path / "design" / "tiling" / "T1"

    def test_non_tiling_substage_keeps_design_name_dir(self, tmp_path):
        state = State.empty().with_updates(_workspace=_FakeWorkspace(tmp_path))
        wd = GeneralDesignStage()._working_dir(state)
        assert wd == tmp_path / "design" / "general-design-generator"

    def test_no_workspace_returns_none(self):
        wd = TilingStage(template={"name": "T1"})._working_dir(State.empty())
        assert wd is None

class TestDesignArtifactsToState:
    @staticmethod
    def _materialize(root: Path):
        """Write a minimal but contract-valid set of design products."""
        design = root / "design"
        # general_design
        (design / "general-design-generator").mkdir(parents=True)
        (design / "general-design-generator" / "general_design.json").write_text(
            json.dumps({"op_name": "rope", "sections": {"axis": ["N"]}}))
        # template_division
        (design / "template-division").mkdir(parents=True)
        (design / "template-division" / "template_division.json").write_text(
            json.dumps({"templates": [{"name": "T1"}], "locked_decisions": {}}))
        # tiling per-template
        for tmpl, axis in (("T1", "N"), ("T2", "M")):
            d = design / "tiling" / tmpl
            d.mkdir(parents=True)
            (d / "tiling_split.json").write_text(
                json.dumps({"template": tmpl, "split": {"axis": axis}}))
        # tiling_vf_design (A5 only — present for T1, absent for T2/Membase)
        (design / "tiling" / "T1" / "tiling_vf_design.json").write_text(
            json.dumps({"template": "T1", "vf_design": {"vf_count": 2, "pattern": 3}}))
        # synthesize (integrate) contract pieces
        (design / "synthesize").mkdir(parents=True)
        (design / "synthesize" / "design_spec.json").write_text(
            json.dumps({"op_name": "rope", "inputs": [{"name": "x"}],
                        "outputs": [{"name": "y"}]}))
        (design / "synthesize" / "tiling_strategy.json").write_text(
            json.dumps({"approach": "multi_template"}))

    def test_rebuilds_simple_fields(self, tmp_path):
        self._materialize(tmp_path)
        out = design_artifacts_to_state(tmp_path)
        assert out["general_design"]["op_name"] == "rope"
        assert out["template_division"]["templates"][0]["name"] == "T1"
        assert out["design_spec"]["op_name"] == "rope"
        assert out["tiling_strategy"]["approach"] == "multi_template"

    def test_rebuilds_tiling_results_per_template(self, tmp_path):
        self._materialize(tmp_path)
        out = design_artifacts_to_state(tmp_path)
        tr = out["tiling_results"]
        assert tr["T1"]["split"] == {"axis": "N"}
        assert tr["T2"]["split"] == {"axis": "M"}

    def test_rebuilds_vf_design_segment(self, tmp_path):
        """The vf-design segment (A5) is rebuilt into tiling_results when its
        product is on disk (P64); T2 (no vf_design product, Membase) simply
        lacks the slice — _rebuild_tiling_results must include the new segment."""
        self._materialize(tmp_path)
        out = design_artifacts_to_state(tmp_path)
        tr = out["tiling_results"]
        assert tr["T1"]["vf_design"] == {"vf_count": 2, "pattern": 3}
        assert "vf_design" not in tr.get("T2", {})

    def test_edited_product_drives_value(self, tmp_path):
        """Editing a product file on disk changes the re-injected value
        (the debug workflow §5.4 promises)."""
        self._materialize(tmp_path)
        f = tmp_path / "design" / "tiling" / "T1" / "tiling_split.json"
        f.write_text(json.dumps({"template": "T1", "split": {"axis": "EDITED"}}))
        out = design_artifacts_to_state(tmp_path)
        assert out["tiling_results"]["T1"]["split"] == {"axis": "EDITED"}

    def test_missing_dir_returns_empty(self, tmp_path):
        assert design_artifacts_to_state(tmp_path) == {}

    def test_partial_reinjection(self, tmp_path):
        """Only the products present are rebuilt — a partial set is valid."""
        design = tmp_path / "design"
        (design / "general-design-generator").mkdir(parents=True)
        (design / "general-design-generator" / "general_design.json").write_text(
            json.dumps({"op_name": "rope", "sections": {}}))
        out = design_artifacts_to_state(tmp_path)
        assert "general_design" in out
        assert "tiling_results" not in out
        assert "design_spec" not in out
