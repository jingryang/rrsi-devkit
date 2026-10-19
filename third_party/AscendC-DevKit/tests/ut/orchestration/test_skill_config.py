"""STAGE_SKILL_MAP loading + §P4 consistency guard (validate_skill_map).

Also covers STAGE_TAIL_CALL_MAP + skill_allowlist (P47): a stage skill that
tail-calls another skill via the Skill tool must carry that aux skill in the
same session allowlist, else the CLI rejects the call with "not in this session's
skills allowlist".
"""

from ascendc_devkit.orchestration import skill_config
from ascendc_devkit.orchestration.skill_config import (
    STAGE_SKILL_MAP, STAGE_TAIL_CALL_MAP, skill_allowlist, validate_skill_map,
)


class TestStageSkillMap:
    def test_dd_intake_points_at_design_intake(self):
        # L4-c (D4): dd-intake's skill was renamed detailed-design → design-intake.
        assert STAGE_SKILL_MAP["dd-intake"] == "ascendc-op-design-intake"

    def test_detailed_design_no_longer_referenced(self):
        # The deleted skill must not be assigned to any substage.
        assert "ascendc-op-detailed-design" not in STAGE_SKILL_MAP.values()


class TestSkillAllowlist:
    _FEEDBACK = "ascendc-op-design-feedback-selfcheck"

    def test_non_tailcall_skill_stays_singleton(self):
        # A skill with no tail-call gets an allowlist of just itself.
        # NB: general-design now tail-calls template-select (P47) — it is no
        # longer a no-tailcall example; template-division has none.
        p = "ascendc-op-design-template-division"
        assert skill_allowlist(p) == [p]

    def test_none_primary_inherits_cli_default(self):
        # No assigned skill → None (inherit CLI default), never [] (suppress all).
        assert skill_allowlist(None) is None
        assert skill_allowlist("") is None

    def test_allowlist_dedups_preserving_order(self, monkeypatch):
        # A self-referential / duplicate tail-call never doubles an entry.
        p = "ascendc-op-tiling-split"
        monkeypatch.setattr(skill_config, "STAGE_TAIL_CALL_MAP",
                            {p: [self._FEEDBACK, self._FEEDBACK, p]})
        assert skill_allowlist(p) == [p, self._FEEDBACK]

    def test_general_design_tail_calls_strategy_card_select(self):
        # Pin the concept-design → strategy retrieval hook. Without this, a later
        # config edit could silently un-wire it and the Skill call would be
        # rejected at runtime with "not in this session's skills allowlist".
        assert "ascendc-strategy-card-select" in \
            STAGE_TAIL_CALL_MAP["ascendc-op-general-design"]

    def test_strategy_card_select_reaches_general_design_allowlist(self):
        assert "ascendc-strategy-card-select" in \
            skill_allowlist("ascendc-op-general-design")


class TestValidateSkillMap:
    def test_live_map_is_consistent(self):
        # Every assigned stage-design skill resolves to a real skill on disk.
        assert validate_skill_map() == []

    def test_missing_skill_is_reported(self, monkeypatch):
        # A substage assigned a non-existent skill must be flagged (the slash
        # trigger would otherwise expand to nothing → skill-dead agent).
        bad = dict(STAGE_SKILL_MAP)
        bad["phantom"] = "ascendc-op-does-not-exist"
        monkeypatch.setattr(skill_config, "STAGE_SKILL_MAP", bad)
        errors = validate_skill_map()
        assert any("phantom" in e and "ascendc-op-does-not-exist" in e for e in errors)

    def test_any_real_flat_skill_is_accepted(self, monkeypatch):
        # Flat model: there is no "out of scope" — any assigned skill is checked
        # against the single flat tree. A real skill (even one not normally a
        # design substage) resolves fine.
        bad = dict(STAGE_SKILL_MAP)
        bad["foo"] = "ascendc-tiling-strategy"
        monkeypatch.setattr(skill_config, "STAGE_SKILL_MAP", bad)
        assert validate_skill_map() == []

    def test_namespaced_prefix_is_rejected(self, monkeypatch):
        # §4.3: skills are bare flat names now. A residual '<plugin>:' prefix must
        # be flagged at load time — the slash trigger '/<plugin>:skill' would not
        # match any flat SKILL.md and the agent would run skill-dead.
        bad = dict(STAGE_SKILL_MAP)
        bad["legacy"] = "stage-design:ascendc-op-general-design"
        monkeypatch.setattr(skill_config, "STAGE_SKILL_MAP", bad)
        errors = validate_skill_map()
        assert any("legacy" in e and "prefix" in e for e in errors)

    def test_flat_names_are_globally_unique_on_disk(self):
        # Bare-name uniqueness is guaranteed by the filesystem: two dirs with the
        # same name cannot coexist in one directory. _flat_skills_on_disk returns
        # a set keyed by bare name; asserting it matches the raw dir count proves
        # no name collides (a collision would shrink the set below the count).
        from pathlib import Path
        skills_dir = (
            Path(skill_config.__file__).resolve().parent.parent.parent.parent
            / ".claude" / "skills"
        )
        on_disk = skill_config._flat_skills_on_disk()
        raw = [
            d.name for d in skills_dir.iterdir()
            if d.is_dir() and (d / "SKILL.md").exists()
        ]
        assert len(raw) == len(set(raw)) == len(on_disk)

    def test_phantom_tail_call_aux_is_reported(self, monkeypatch):
        # P47: a tail-call to a non-existent aux skill must be flagged at load
        # time, else the allowlist carries a phantom and the tail-call fails at
        # runtime with "not in this session's skills allowlist".
        monkeypatch.setattr(skill_config, "STAGE_TAIL_CALL_MAP",
                            {"ascendc-op-tiling-split":
                             ["ascendc-op-does-not-exist"]})
        errors = validate_skill_map()
        assert any("ascendc-op-does-not-exist" in e for e in errors)
