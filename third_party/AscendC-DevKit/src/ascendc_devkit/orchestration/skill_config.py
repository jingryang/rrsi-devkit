"""Per-design-substage skill assignment (step-8 §P1 task 3, decision D7).

Reads the "skills" section of resources/orchestration-config.json (the single
source of truth for orchestration tuning), mirroring model_config.py. Maps a
design substage (stage.name) to the flat skill (bare ``name`` = the
``.claude/skills/<name>/`` directory, globally unique) carrying that step's
methodology.

The role agent (``agent_name`` on the Stage class) provides the tool/permission
profile; this map provides the per-step methodology. The orchestration triggers
that methodology by leading the spawn's first message with ``/<skill>`` (bare
name); both backends discover the flat ``.claude/skills`` tree natively (claude
via a workspace skills symlink anchor + ``setting_sources``, opencode via a
cwd→git-worktree walk). A substage not listed here gets ``skills=None`` (inherit
the default — all skills discoverable), never ``[]`` (which would suppress all
skills; see step-8 §P1 root cause 4).

The "skills.tail_calls" section (P47) additionally maps a primary skill to the
aux skills its SKILL.md tail-calls via the Skill tool; ``skill_allowlist()``
folds these into the spawn allowlist so the CLI does not reject the tail-call
with "not in this session's skills allowlist".

If the file or section is missing, STAGE_SKILL_MAP / STAGE_TAIL_CALL_MAP are empty.
"""

from __future__ import annotations

import json
from pathlib import Path


def _load() -> dict[str, str]:
    config_path = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "resources" / "orchestration-config.json"
    )
    if not config_path.exists():
        return {}
    data = json.loads(config_path.read_text())
    return data.get("skills", {}).get("stages", {})


STAGE_SKILL_MAP: dict[str, str]
STAGE_SKILL_MAP = _load()


def _load_tail_calls() -> dict[str, list[str]]:
    """Read the "skills.tail_calls" section of orchestration-config.json.

    Maps a PRIMARY skill (bare ``name``) to the auxiliary skills its SKILL.md
    tail-calls via the Skill tool (e.g. the precision-debug skills tail-call
    knowledge/check skills). Keyed by primary skill rather than substage name because
    the tail-call is intrinsic to the skill's methodology, so the production
    substage and the TUI self-closure test resolve the same closure from the same
    key. Missing file/section → empty map.
    """
    config_path = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "resources" / "orchestration-config.json"
    )
    if not config_path.exists():
        return {}
    data = json.loads(config_path.read_text())
    return data.get("skills", {}).get("tail_calls", {})


STAGE_TAIL_CALL_MAP: dict[str, list[str]]
STAGE_TAIL_CALL_MAP = _load_tail_calls()


def skill_allowlist(primary: str | None) -> list[str] | None:
    """The full session skills allowlist for a spawn led by ``primary``.

    The allowlist must carry the primary skill AND every skill it tail-calls
    (P47): the session enforces the allowlist on explicit ``Skill`` tool
    invocations, so a tail-call to a loaded-but-unlisted skill is rejected with
    "not in this session's skills allowlist". Both the production substage
    (``actions()``) and the TUI self-closure test build their allowlist through
    this single helper so the closure never drifts between them.

    Returns ``None`` when ``primary`` is falsy (no assigned skill → inherit the
    default, never ``[]`` which would suppress all skills). Primary stays first;
    tail-calls follow with order-preserving dedup.
    """
    if not primary:
        return None
    allowlist = [primary]
    for aux in STAGE_TAIL_CALL_MAP.get(primary, []):
        if aux not in allowlist:
            allowlist.append(aux)
    return allowlist


def _skills_root() -> Path:
    """The flat ``.claude/skills`` root (single canonical source both backends discover).

    Factored so load-time validators (``_flat_skills_on_disk``,
    ``validate_skill_map``) share one root — and so tests can monkeypatch this
    single symbol to point at a synthetic tree.
    """
    return (Path(__file__).resolve().parent.parent.parent.parent
            / ".claude" / "skills")


def _flat_skills_on_disk() -> set[str]:
    """The set of bare skill names that actually exist in the flat tree.

    Scans ``.claude/skills/<name>/SKILL.md`` (the single canonical source both
    backends discover) so the consistency check (§P4) compares STAGE_SKILL_MAP's
    assigned skills against reality. A bare directory name is globally unique by
    construction — the filesystem forbids two entries with the same name in one
    directory — so bare-name existence here doubles as the uniqueness guarantee
    for the assigned/tail-called names.
    """
    skills_dir = _skills_root()
    if not skills_dir.is_dir():
        return set()
    return {
        d.name
        for d in skills_dir.iterdir()
        if d.is_dir() and (d / "SKILL.md").exists()
    }


def validate_skill_map() -> list[str]:
    """Check every assigned + tail-called skill resolves to a real skill on disk.

    §P4 consistency guard (mirrors §P1's "load-time validation over runtime
    surprise"): every skill a substage is assigned must exist in the flat
    ``.claude/skills`` tree, else the slash trigger ``/<skill>`` would expand to
    nothing and the agent would run skill-dead again. P47 extends this to
    tail_calls: both the primary key and every aux skill must exist, else the
    allowlist would carry a phantom entry and the tail-call would still fail at
    runtime. Returns error strings (empty = consistent).

    Each assigned bare ``<skill>`` is checked against the flat on-disk set. When
    the flat dir is absent (installed layout / tests) the check is skipped
    silently.
    """
    errors: list[str] = []
    on_disk = _flat_skills_on_disk()
    if not on_disk:
        return errors  # flat dir absent (installed layout / tests) — skip

    def _check(skill: str, where: str) -> None:
        if ":" in skill:
            errors.append(
                f"{where} = '{skill}' still carries a '<plugin>:' prefix; "
                f"skills are bare flat names now")
            return
        if skill not in on_disk:
            errors.append(
                f"{where} = '{skill}' but no such skill exists under "
                f".claude/skills/ (available: {sorted(on_disk)})")

    for stage, skill in STAGE_SKILL_MAP.items():
        _check(skill, f"STAGE_SKILL_MAP['{stage}']")
    for primary, aux_skills in STAGE_TAIL_CALL_MAP.items():
        _check(primary, f"STAGE_TAIL_CALL_MAP key")
        for aux in aux_skills:
            _check(aux, f"STAGE_TAIL_CALL_MAP['{primary}'] aux")
    return errors

