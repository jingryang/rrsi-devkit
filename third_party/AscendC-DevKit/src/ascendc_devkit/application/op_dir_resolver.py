"""L2 Application — Resolve an absolute --op-dir into domain fields.

One path in, many facts out (§3.1):

    /home/x/omni-ops/inference/ascendc/src/ops-transformer/posembedding/ai_infra_rope
                     └──────── rel_op_dir (under repo_root) ──────────┘ └ full_op_name ┘
            └ repo_root ┘
    └ profile_name = "omni-ops" (matched against the known-profile list) ┘

Layer note: the resolution *logic* lives here (L2). The result type
``OpDirResolution`` is an L4 domain dataclass so every layer may depend on it.
The known-profile-name list is fetched through ``application/profile_loader``
(the existing thin L2→L6 delegate), introducing no new layer violation.
"""

from __future__ import annotations

from pathlib import PurePath

from ascendc_devkit.domain.repository import (
    RepositoryProfile, OpDirResolution,
)
from ascendc_devkit.orchestration.profile_loader import (
    load_profile, list_profiles,
)


class OpDirResolveError(Exception):
    """Raised when an op_dir cannot be resolved and no CLI fallback closes the gap."""


def _segments(op_dir: str) -> list[str]:
    return [p for p in PurePath(str(op_dir)).parts if p not in ("/", "")]


def _identify_profile(
    segments: list[str], known: list[str]
) -> tuple[str | None, int, str]:
    """Locate a known profile name among the path segments.

    Returns (profile_name | None, repo_root_segment_index, confidence).
    repo_root_segment_index is the index of the matched segment (the repo dir
    name); repo_root is everything up to and including it.

    The repo directory is always an *ancestor* of the repo's internal group
    structure, so when a profile name also appears deeper as a group dir (e.g.
    ``ops-transformer`` is a group inside ``omni-ops``), the *shallowest* hit is
    the real repo boundary. Confidence:
      - "matched"   : a known profile name was found (shallowest taken as repo)
      - "ambiguous" : the *same* profile name repeats (nested checkout) — the
                      boundary is uncertain and the caller should confirm
      - "unmatched" : no known profile name in the path
    """
    hits: list[tuple[str, int]] = []
    for idx, seg in enumerate(segments):
        if seg in known:
            hits.append((seg, idx))
    if not hits:
        return None, -1, "unmatched"
    first_name, first_idx = hits[0]
    # Ambiguity = the same repo name appears more than once (nested checkout).
    same_name_repeats = sum(1 for n, _ in hits if n == first_name) > 1
    confidence = "ambiguous" if same_name_repeats else "matched"
    return first_name, first_idx, confidence


def resolve_op_dir(
    op_dir: str,
    *,
    profile_override: str | None = None,
    repo_root_override: str | None = None,
    op_name_override: str | None = None,
    known_profiles: list[str] | None = None,
) -> OpDirResolution:
    """Resolve an absolute op_dir into an :class:`OpDirResolution`.

    ``profile_override`` / ``repo_root_override`` / ``op_name_override`` are the
    non-interactive CLI fallbacks (§5). When repo identification fails or is
    ambiguous and no override is supplied, an :class:`OpDirResolveError` is
    raised describing exactly what to provide.
    """
    if not op_dir or not str(op_dir).strip():
        raise OpDirResolveError("--op-dir is required (absolute path to the operator directory).")

    segments = _segments(op_dir)
    if not segments:
        raise OpDirResolveError(f"--op-dir '{op_dir}' has no path segments.")

    full_op_name = segments[-1]
    known = known_profiles if known_profiles is not None else list_profiles()

    profile_name, repo_idx, confidence = _identify_profile(segments, known)

    # —— Graded fallback (§5) ——
    if profile_override:
        profile_name = profile_override
        confidence = "matched"
        # Recompute repo boundary from the (possibly overridden) profile name if
        # it appears in the path; otherwise rely on repo_root_override.
        _, repo_idx_o, _ = _identify_profile(segments, [profile_override])
        repo_idx = repo_idx_o if repo_idx_o >= 0 else repo_idx

    # profile resolution is MANDATORY (§1.3 加载期校验): a known profile must
    # identify from the path, or be supplied via profile_override. repo_root_override
    # only pins the repo ROOT *path* — it does NOT substitute for the profile.
    # Downstream stages need the profile object (variant / scan_existing_operator /
    # deploy capability / reference_roots); returning profile_name='' here would
    # silently degrade them (reference_roots=[] lost) or defer the failure to a
    # harder-to-locate downstream stage (deploy smoke_passed=False). Failing at the
    # resolution layer is correct (§1.2 可诊断/架构合理 — this layer owns profile
    # parsing; §3.4 不掩盖). profile_override above already sets profile_name when
    # given, so this fires only on genuine unmatched-without-override.
    if profile_name is None:
        raise OpDirResolveError(
            f"Could not identify a known repository profile in --op-dir '{op_dir}'. "
            f"Known profiles: {known}. "
            f"Provide --repo-profile (the repo-root path alone is NOT enough — the "
            f"profile describes the repo structure/capabilities downstream stages need)."
        )

    # —— repo_root ——
    if repo_root_override:
        repo_root = str(repo_root_override).rstrip("/")
        # rel_op_dir is op_dir relative to the explicit repo_root.
        rel = _relativize(op_dir, repo_root)
    else:
        # repo_root = path up to and including the matched profile segment.
        repo_parts = segments[: repo_idx + 1]
        prefix = "/" if str(op_dir).startswith("/") else ""
        repo_root = prefix + "/".join(repo_parts)
        rel = "/".join(segments[repo_idx + 1:])

    # —— Resolve naming + variant against the profile ——
    # profile_name resolved (path match or profile_override) MUST load: a name
    # without a YAML is a config error, fail at the resolution layer (§1.3 加载期
    # 校验) rather than silently returning profile_name with no variant — which
    # would make context's later load_profile() FileNotFoundError again and set
    # profile=None (the silent degradation 疑似3 fixed). Covers both sources: a
    # path segment that equals a profile name whose YAML isn't installed, AND a
    # misspelled profile_override.
    variant_name = ""
    op_name = op_name_override or full_op_name
    if profile_name:
        try:
            profile: RepositoryProfile = load_profile(profile_name)
        except FileNotFoundError as e:
            raise OpDirResolveError(
                f"Profile '{profile_name}' (resolved for --op-dir '{op_dir}') "
                f"has no YAML in resources/repository-profiles/. {e}"
            ) from e
        if not op_name_override:
            op_name = profile.derive_op_name(full_op_name)
        variant = profile.select_variant(rel)
        if variant is None:
            raise OpDirResolveError(
                f"--op-dir '{op_dir}' (relative '{rel}') matches no build "
                f"variant of profile '{profile_name}'. "
                f"Legal match_prefix values: {profile.match_prefixes()}."
            )
        variant_name = variant.name

    return OpDirResolution(
        profile_name=profile_name or "",
        repo_root=repo_root,
        rel_op_dir=rel,
        full_op_name=full_op_name,
        op_name=op_name,
        variant_name=variant_name,
        confidence=confidence,
    )


def _relativize(op_dir: str, repo_root: str) -> str:
    """Return op_dir relative to repo_root using string segments (no FS access)."""
    op_parts = _segments(op_dir)
    root_parts = _segments(repo_root)
    if op_parts[: len(root_parts)] == root_parts:
        return "/".join(op_parts[len(root_parts):])
    # repo_root not a prefix of op_dir — fall back to the basename.
    return op_parts[-1]
