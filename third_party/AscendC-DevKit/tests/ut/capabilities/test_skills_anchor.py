"""相1: SDKBackend._ensure_skills_anchor — per-workspace symlink to the flat tree.

Claude discovers flat ``.claude/skills/<name>/SKILL.md`` ONLY at ``cwd/.claude/skills``
(shallow, no walk-up; add_dirs does not trigger discovery — V1/V5/V7). Agents are
spawned with a deep artifacts cwd, so the canonical repo tree is invisible unless
anchored. These UTs pin the anchor contract: create when absent, idempotent when
correct, rebuild when stale, never clobber a real non-symlink dir.
"""

from pathlib import Path

from ascendc_devkit.capabilities.agent import sdk_backend
from ascendc_devkit.capabilities.agent.sdk_backend import _ensure_skills_anchor

_REPO_SKILLS = (
    Path(sdk_backend.__file__).resolve()
    .parent.parent.parent.parent.parent / ".claude" / "skills"
)


class TestEnsureSkillsAnchor:
    def test_creates_symlink_to_canonical_tree(self, tmp_path):
        _ensure_skills_anchor(tmp_path)
        anchor = tmp_path / ".claude" / "skills"
        assert anchor.is_symlink()
        assert anchor.resolve() == _REPO_SKILLS.resolve()

    def test_idempotent_when_correct(self, tmp_path):
        _ensure_skills_anchor(tmp_path)
        anchor = tmp_path / ".claude" / "skills"
        _ensure_skills_anchor(tmp_path)  # second call: no error, still correct
        assert anchor.is_symlink()
        assert anchor.resolve() == _REPO_SKILLS.resolve()

    def test_rebuilds_stale_symlink(self, tmp_path):
        anchor = tmp_path / ".claude" / "skills"
        anchor.parent.mkdir(parents=True)
        anchor.symlink_to(tmp_path)  # wrong target
        _ensure_skills_anchor(tmp_path)
        assert anchor.is_symlink()
        assert anchor.resolve() == _REPO_SKILLS.resolve()

    def test_leaves_real_dir_untouched(self, tmp_path):
        # A pre-existing non-symlink at the anchor (e.g. cwd IS a real repo) is
        # never clobbered — it is left in place, diagnosable via a warning.
        anchor = tmp_path / ".claude" / "skills"
        anchor.mkdir(parents=True)
        (anchor / "sentinel").write_text("keep me")
        _ensure_skills_anchor(tmp_path)
        assert not anchor.is_symlink()
        assert (anchor / "sentinel").read_text() == "keep me"

    def test_noop_when_cwd_none(self):
        _ensure_skills_anchor(None)  # must not raise
