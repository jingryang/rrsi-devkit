"""L5 Capabilities — Skill discovery and agent manifest parsing.

Skills are DISCOVERED natively from the single canonical flat tree
``.claude/skills/<name>/SKILL.md``; there is no plugin packaging layer. Both
backends walk this tree (claude via a per-workspace ``.claude/skills`` symlink
anchor placed at the spawn cwd, opencode via a cwd→git-worktree walk). Skill
names are bare and globally unique — the flat directory forbids duplicates.
"""

from __future__ import annotations

import re
import yaml
from pathlib import Path

from ascendc_devkit.domain.skill import SkillSpec, AgentManifest


class SkillLoader:
    """Discover available skills from skill directories.

    Each skill is a subdirectory containing a SKILL.md entry point.
    The claude_agent_sdk handles actual skill execution — the framework
    only needs to know which skill names are valid for validation.

    Discovery scans:
      1. <project>/.claude/skills/ (Claude Code native skill directory)
      2. Any additional paths passed via extra_paths.
    """

    @staticmethod
    def _find_skill_dirs(base_dir: Path) -> set[str]:
        """Scan a directory for subdirectories containing SKILL.md."""
        skills: set[str] = set()
        if not base_dir.exists():
            return skills
        for entry in base_dir.iterdir():
            if entry.is_dir():
                skill_md = entry / "SKILL.md"
                if skill_md.exists():
                    skills.add(entry.name)
        return skills

    @staticmethod
    def _read_skill_description(skill_dir: Path) -> str:
        """Read the first heading line from SKILL.md as description."""
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            return ""
        try:
            first_line = skill_md.read_text(encoding="utf-8").split("\n", 1)[0].strip()
            if first_line.startswith("# "):
                return first_line[2:].strip()
            if first_line.startswith("#"):
                return first_line[1:].strip()
            return first_line
        except (OSError, UnicodeDecodeError):
            return ""

    @staticmethod
    def _scan_dir_for_skills(base_dir: Path) -> set[SkillSpec]:
        """Scan a single directory for skill subdirectories."""
        specs: set[SkillSpec] = set()
        for name in SkillLoader._find_skill_dirs(base_dir):
            skill_dir = base_dir / name
            specs.add(SkillSpec(
                name=name,
                path=skill_dir,
                description=SkillLoader._read_skill_description(skill_dir),
            ))
        return specs

    @staticmethod
    def discover(resources_root: Path | None = None,
                 extra_paths: list[Path] | None = None) -> set[SkillSpec]:
        """Return the union of all available skills with metadata.

        Args:
            resources_root: Deprecated. Used only to locate project root and
                            kept for backward compatibility. Defaults to
                            <project>/resources/.
            extra_paths: Additional directories to scan for skills.
                         Each directory is scanned for subdirectories
                         containing SKILL.md.

        Scans by default:
            1. <project>/.claude/skills/   (shared with Claude Code TUI)
            2. extra_paths
        """
        if resources_root is None:
            resources_root = Path(__file__).parent.parent.parent.parent.parent / "resources"

        project_root = resources_root.parent

        specs: set[SkillSpec] = set()
        specs |= SkillLoader._scan_dir_for_skills(project_root / ".claude" / "skills")

        if extra_paths:
            for p in extra_paths:
                specs |= SkillLoader._scan_dir_for_skills(p)

        return specs

    @staticmethod
    def list_available(resources_root: Path | None = None,
                       extra_paths: list[Path] | None = None) -> list[SkillSpec]:
        """Return sorted list of all available skill specs."""
        return sorted(SkillLoader.discover(resources_root, extra_paths),
                      key=lambda s: s.name)

    @staticmethod
    def validate(skill_names: list[str],
                 resources_root: Path | None = None,
                 extra_paths: list[Path] | None = None) -> list[str]:
        """Check which requested skills are missing. Returns list of missing names."""
        available = {s.name for s in SkillLoader.discover(resources_root, extra_paths)}
        return [name for name in skill_names if name not in available]


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown content.

    Returns (frontmatter_dict, body_text).
    If no frontmatter found, returns ({}, content).
    """
    if content.startswith("---\n"):
        parts = content.split("---\n", 2)
        if len(parts) >= 3:
            try:
                fm = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                fm = {}
            return fm, parts[2]
    return {}, content


def _extract_name_from_content(content: str, filename: str) -> str:
    """Extract agent name from content or fall back to filename stem."""
    match = re.search(r'\bnamed\s+([\w-]+)', content)
    if match:
        return match.group(1)
    return filename


def _extract_paragraph(content: str) -> str:
    """Extract the first non-empty text paragraph (max 200 chars)."""
    lines = content.strip().split("\n")
    paragraph_lines = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            if paragraph_lines:
                break
            continue
        paragraph_lines.append(line)
    text = " ".join(paragraph_lines)
    if len(text) > 200:
        text = text[:197] + "..."
    return text


def load_agent_manifest(agent_name: str, resources_root: Path | None = None) -> AgentManifest:
    """Parse .claude/agents/<name>.md and extract manifest.

    Supports two formats:
      1. YAML frontmatter:
         ---
         name: ascendc-coder
         skills: [skill-a, skill-b]
         ---
         Body content...
      2. Plain text (no frontmatter):
         Extracts name from "named <name>" pattern in first few lines.
         Defaults skills to empty list.
    """
    if resources_root is None:
        resources_root = Path(__file__).parent.parent.parent.parent.parent / "resources"

    project_root = resources_root.parent
    agent_path = project_root / ".claude" / "agents" / f"{agent_name}.md"
    if not agent_path.exists():
        return AgentManifest(name=agent_name, skills=[], description="")

    try:
        content = agent_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return AgentManifest(name=agent_name, skills=[], description="")

    fm, body = _parse_frontmatter(content)

    if fm:
        return AgentManifest(
            name=fm.get("name", agent_name),
            skills=fm.get("skills", []),
            description=fm.get("description", _extract_paragraph(body)),
            allowed_tools=fm.get("allowed_tools", []),
            disallowed_tools=fm.get("disallowed_tools", []),
            max_turns=fm.get("max_turns"),
        )

    extracted_name = _extract_name_from_content(body, agent_name)
    return AgentManifest(
        name=extracted_name,
        skills=[],
        description=_extract_paragraph(body),
    )


def resolve_skills(agent_name: str, requested: list[str],
                   resources_root: Path | None = None,
                   extra_paths: list[Path] | None = None) -> list[SkillSpec]:
    """Filter requested skills against agent's frontmatter whitelist.

    If the agent manifest declares a skills whitelist, only skills in that
    list are returned. If no whitelist is declared, all requested skills
    pass through (no filtering).
    """
    manifest = load_agent_manifest(agent_name, resources_root)
    all_skills = SkillLoader.discover(resources_root, extra_paths)
    skill_map = {s.name: s for s in all_skills}

    if manifest.skills:
        allowed = set(manifest.skills)
        return [skill_map[n] for n in requested if n in allowed and n in skill_map]

    return [skill_map[n] for n in requested if n in skill_map]


def validate_manifest(manifest: AgentManifest,
                      resources_root: Path | None = None,
                      extra_paths: list[Path] | None = None) -> list[str]:
    """Validate an AgentManifest at load time. Returns a list of error messages.

    Checks (D2: surface failures, don't silently skip):
      1. Declared skills all exist in SkillLoader.discover().
      2. Tool names are non-empty strings; MCP tools follow the
         ``mcp__<server>__<tool>`` convention (e.g. mcp__engine__resolve_ambiguity).

    An empty list means the manifest is valid.
    """
    errors: list[str] = []

    available = {s.name for s in SkillLoader.discover(resources_root, extra_paths)}
    for skill in manifest.skills:
        if skill not in available:
            errors.append(
                f"agent '{manifest.name}': skill '{skill}' not found in .claude/skills/"
            )

    for field_name, tools in (("allowed_tools", manifest.allowed_tools),
                              ("disallowed_tools", manifest.disallowed_tools)):
        for t in tools:
            if not isinstance(t, str) or not t.strip():
                errors.append(
                    f"agent '{manifest.name}': {field_name} contains an empty/invalid tool name"
                )
                continue
            if t.startswith("mcp_") and not _is_valid_mcp_tool_name(t):
                errors.append(
                    f"agent '{manifest.name}': MCP tool '{t}' must match "
                    f"mcp__<server>__<tool>"
                )

    if manifest.max_turns is not None and (
        not isinstance(manifest.max_turns, int) or manifest.max_turns <= 0
    ):
        errors.append(
            f"agent '{manifest.name}': max_turns must be a positive int, got {manifest.max_turns!r}"
        )

    return errors


def _is_valid_mcp_tool_name(name: str) -> bool:
    """An MCP tool name is mcp__<server>__<tool> with non-empty server and tool."""
    if not name.startswith("mcp__"):
        return False
    rest = name[len("mcp__"):]
    server, sep, tool = rest.partition("__")
    return bool(server) and bool(sep) and bool(tool)
