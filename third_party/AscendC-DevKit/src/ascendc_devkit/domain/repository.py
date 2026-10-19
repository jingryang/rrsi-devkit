"""L4 Domain — Repository profile types.

Redesigned model (2026-06-08): a profile describes only the two truly
invariant facts about a repo — the operator-name *prefix* and the set of
*build variants* (each variant = a project sub-tree + an ordered list of
compile stages). Mutable, repo-specific information (the operator directory,
intermediate path segments, file layout) is no longer encoded here; it is
supplied per-run via the absolute ``--op-dir`` and discovered by scanning.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .chip import to_soc_version


@dataclass(frozen=True)
class BuildStage:
    """One ordered compile/deploy step within a build variant.

    ``cwd`` is relative to the repo root; ``command_template`` is formatted
    with ``full_op_name`` / ``chip_version`` (and, for deploy roles, the per-op
    path variables ``per_op_opp_dir`` / ``per_op_python_dir`` / ``run_pkg`` /
    ``whl_pkg`` injected by Deployer). ``enabled`` lets a stage be
    pre-declared (e.g. the torch extension layer) but skipped until opened.

    ``role`` (D6-2) classifies the step so the generic Deployer knows what a
    stage produces:
      - "build"           : compile → artifacts (.run/.whl/.so)
      - "install_runtime" : install the runtime package to the per-op opp dir
      - "install_python"  : install the python package to the per-op python dir
      - "smoke"           : verify the operator is callable (per codegen_manifest.callable_target)
    A stage without a role is a plain "build" step (the pre-D6-2 default).
    """
    name: str
    cwd: str = "."
    command_template: str = ""
    default_chip: str = ""
    enabled: bool = True
    role: str = "build"


# Deploy-capability roles: a variant is deployable when it declares (at least)
# an install_runtime step and a smoke step. Ordered install roles run in this
# sequence within Deployer.
_INSTALL_ROLES = ("install_runtime", "install_python")
_DEPLOY_ROLES = _INSTALL_ROLES + ("smoke",)


# Scaffolding = the operator's *invocation protocol* (how a deployed op is
# registered and called). A repo may physically support several; exactly one is
# *selected* per profile and is the single authority every consumer reads
# (codegen registration codegen, smoke probe, deploy/precision call, cann-bench
# glue). NEW kinds are added here first — the enum is the one place that lists
# what the toolchain knows how to build/probe for.
VALID_SCAFFOLDING_KINDS = ("torch_op", "aclnn", "pybind")


@dataclass(frozen=True)
class Scaffolding:
    """Repo-level operator invocation protocol (single-select, single authority).

    ``supported`` is the set of protocols the repo *can* build; ``selected`` is
    the one this profile *uses* — the single knob. The invariant ``selected ∈
    supported`` is asserted at load time (§1.3): a violation is a profile-config
    error, not a runtime surprise. Every downstream consumer derives its
    behaviour from ``selected`` — codegen emits the matching registration code,
    Deployer's smoke probes that protocol, the runner/precision call uses it,
    and cann-bench glue adapts to it — so changing this one field switches the
    whole repo coherently with no second truth source (the Agent no longer picks
    the protocol in ``codegen_manifest.callable_target.kind``).
    """
    supported: tuple[str, ...] = ()
    selected: str = ""


@dataclass(frozen=True)
class BuildVariant:
    """A project sub-tree selected by ``match_prefix`` against the op_dir.

    ``match_prefix`` decides which build a given operator belongs to (a fixed
    in-repo boundary). ``default_reference_root`` is the fallback search root
    for reference operators (per-run overridable via ``--reference``). The two
    are intentionally distinct concerns and never merged.
    """
    name: str
    match_prefix: str = ""
    default_reference_root: str = ""
    stages: tuple[BuildStage, ...] = ()
    # Dirs (relative to the build cwd, glob-allowed) removed on a clean rebuild
    # to force CMake reconfigure — e.g. cann-bench's ``build_py`` (its INTERNAL
    # cache + ``file(GLOB)`` without CONFIGURE_DEPENDS keeps new operators out
    # of ``_C.abi3.so`` on incremental build; P96). Empty = no clean (default,
    # preserves current behavior for repos that don't need it).
    clean_dirs: tuple[str, ...] = ()

    def enabled_stages(self) -> list[BuildStage]:
        return [s for s in self.stages if s.enabled]


@dataclass(frozen=True)
class OpNaming:
    """Per-repo operator-name prefix. ``full_op_name = prefix + op_name``."""
    prefix: str = ""


@dataclass(frozen=True)
class PrecisionDebugCommitScope:
    """Repository-specific allow/deny globs for automatic precision commits.

    Patterns are matched against paths relative to the operator directory.
    ``include`` is an allowlist; ``exclude`` narrows it further.  The Git
    safety layer additionally applies non-overridable exclusions for debug
    outputs, backups, caches, and compiled artifacts.
    """
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()


@dataclass(frozen=True)
class OpDirResolution:
    """Result of resolving an absolute ``--op-dir`` into domain fields.

    Pure data (L4): the resolution *logic* lives in L2
    (``application/op_dir_resolver.py``); this object is the shared type every
    layer is allowed to depend on. ``confidence`` records how the repo was
    identified so callers can apply the graded fallback (§5):
      - "matched"   : a known profile name was found uniquely in the path
      - "ambiguous" : the profile name appeared multiple times
      - "unmatched" : no known profile name in the path (renamed repo)
    """
    profile_name: str
    repo_root: str
    rel_op_dir: str
    full_op_name: str
    op_name: str
    variant_name: str = ""
    confidence: str = "matched"


@dataclass(frozen=True)
class RepositoryProfile:
    name: str                       # "omni-ops"
    display_name: str = ""          # "自定义算子仓 (omni-ops)"
    op_naming: OpNaming = field(default_factory=OpNaming)
    build_variants: tuple[BuildVariant, ...] = ()
    # Repo-level one-shot build steps run before cann-bench eval — NOT per-op
    # (no match_prefix): fixed eval-framework components kernel_eval hard-depends
    # on (e.g. cann_bench_utils anti-cheat warmup/cache_clean + its _C). Empty
    # for repos that need no eval-prepare. (step-82 决策1=C 主修复)
    eval_prepare: tuple[BuildStage, ...] = ()
    # Build-artifact globs (relative to repo) excluded from git-diff product
    # collection and rollback so .o/.so/build/ don't pollute the change set.
    artifacts_ignore: tuple[str, ...] = ()
    # Operator invocation protocol (single authority; see Scaffolding). Default
    # empty = unset; ``scaffolding_kind`` falls back to "torch_op" only when a
    # profile predates this field, but new profiles must declare it.
    scaffolding: Scaffolding = field(default_factory=Scaffolding)
    # Files under op_dir that precision_debug may automatically commit.
    # Empty include uses the safety layer's source-file defaults. Kept after
    # existing fields so positional construction remains backward compatible.
    precision_debug_commit: PrecisionDebugCommitScope = field(
        default_factory=PrecisionDebugCommitScope)

    # —— Naming ——

    def full_op_name(self, op_name: str) -> str:
        """Prefix the short name. Idempotent if already prefixed."""
        prefix = self.op_naming.prefix or ""
        if not prefix or op_name.startswith(prefix):
            return op_name
        return f"{prefix}{op_name}"

    def derive_op_name(self, full_op_name: str) -> str:
        """Strip the prefix to recover the short name."""
        prefix = self.op_naming.prefix or ""
        if prefix and full_op_name.startswith(prefix):
            return full_op_name[len(prefix):]
        return full_op_name

    def identity_key(self, full_op_name: str) -> str:
        """Globally-unique key = ``profile_name + full_op_name``.

        Short names collide across repos (and omni-ops customs are likely to be
        upstreamed), so the unique key must carry repo context.
        """
        return f"{self.name}/{full_op_name}"

    # —— Scaffolding (invocation protocol) ——

    def scaffolding_kind(self) -> str:
        """The selected operator invocation protocol — the single authority.

        Every consumer (codegen registration, smoke probe, deploy/precision
        call, cann-bench glue) reads this instead of re-deciding. The profile
        MUST declare a ``scaffolding.selected`` — there is no default. Profiles
        are validated at load time (§1.3), so ``selected`` is always non-empty
        and ``selected ∈ supported``.
        """
        return self.scaffolding.selected

    # —— Build variant selection ——

    def select_variant(self, rel_op_dir: str) -> "BuildVariant | None":
        """Pick the variant whose ``match_prefix`` best matches ``rel_op_dir``.

        Longest matching prefix wins; an empty ``match_prefix`` is a catch-all
        fallback used only when no concrete prefix matched. Returns None when
        nothing matches (caller errors with the legal prefix list).
        """
        rel = str(rel_op_dir).replace("\\", "/").lstrip("/")
        best: BuildVariant | None = None
        best_len = -1
        fallback: BuildVariant | None = None
        for v in self.build_variants:
            mp = (v.match_prefix or "").strip("/")
            if mp == "":
                if fallback is None:
                    fallback = v
                continue
            if rel == mp or rel.startswith(mp + "/"):
                if len(mp) > best_len:
                    best, best_len = v, len(mp)
        return best if best is not None else fallback

    def match_prefixes(self) -> list[str]:
        """Legal ``match_prefix`` values, for error messages."""
        return [v.match_prefix for v in self.build_variants]

    def build_commands(self, rel_op_dir: str, full_op_name: str,
                       chip_version: str = "") -> list[str]:
        """Rendered **build-role** stage commands for the variant matching
        rel_op_dir — a display/prompt helper for the codegen prompt only.

        Only ``role == "build"`` stages are rendered (mirrors Deployer's own
        build-stage filter). Deploy-role templates (install_runtime /
        install_python / smoke) carry runtime placeholders (``{run_pkg}`` /
        ``{whl_pkg}`` / ``{per_op_opp_dir}``) that Deployer injects at run
        time; rendering them here would raise KeyError before codegen spawns
        its agent. The adapter runs the real builds. Returns [] when no variant
        matches.
        """
        variant = self.select_variant(rel_op_dir)
        if variant is None:
            return []
        cmds = []
        for s in variant.enabled_stages():
            if s.role != "build":
                continue
            chip = chip_version or s.default_chip
            cmds.append(s.command_template.format(
                full_op_name=full_op_name, chip_version=chip,
                soc_version=to_soc_version(chip)))
        return cmds

    def deploy_stages(self, rel_op_dir: str) -> list["BuildStage"]:
        """Enabled install/smoke stages of the matching variant, in order.

        These are the steps the generic Deployer runs after ``build`` to
        move an operator from "compiled" to "callable" (D6-2). Returns [] when
        no variant matches or the variant declares no deploy roles.
        """
        variant = self.select_variant(rel_op_dir)
        if variant is None:
            return []
        return [s for s in variant.enabled_stages() if s.role in _DEPLOY_ROLES]

    def has_deploy_capability(self, rel_op_dir: str) -> bool:
        """True when the matching variant can deploy: it declares an
        install_runtime step and a smoke step (D8 load-time capability check).
        """
        roles = {s.role for s in self.deploy_stages(rel_op_dir)}
        return "install_runtime" in roles and "smoke" in roles

    def reference_roots(self, rel_op_dir: str, extra: list[str] | None = None) -> list[str]:
        """Reference search roots: variant default first, then --reference extras.

        Per §6/§9, user-supplied references are *appended after* the profile's
        default reference root (the fallback). Duplicates are removed preserving
        order.
        """
        roots: list[str] = []
        variant = self.select_variant(rel_op_dir)
        if variant is not None and variant.default_reference_root:
            roots.append(variant.default_reference_root)
        for r in (extra or []):
            if r:
                roots.append(r)
        seen: set[str] = set()
        ordered: list[str] = []
        for r in roots:
            if r not in seen:
                seen.add(r)
                ordered.append(r)
        return ordered

    # —— Parsing ——

    @staticmethod
    def from_yaml(data: dict) -> "RepositoryProfile":
        naming = OpNaming(prefix=(data.get("op_naming") or {}).get("prefix", ""))
        variants = []
        for v in data.get("build_variants", []) or []:
            stages = tuple(
                RepositoryProfile._parse_build_stage(s)
                for s in (v.get("stages") or [])
            )
            variants.append(BuildVariant(
                name=v.get("name", ""),
                match_prefix=v.get("match_prefix", ""),
                default_reference_root=v.get("default_reference_root", ""),
                stages=stages,
                clean_dirs=tuple(v.get("clean_dirs", []) or []),
            ))
        eval_prepare = tuple(
            RepositoryProfile._parse_build_stage(s)
            for s in (data.get("eval_prepare") or [])
        )
        precision_commit = data.get("precision_debug_commit") or {}
        return RepositoryProfile(
            name=data["name"],
            display_name=data.get("display_name", data["name"]),
            op_naming=naming,
            build_variants=tuple(variants),
            eval_prepare=eval_prepare,
            artifacts_ignore=tuple(data.get("artifacts_ignore", []) or []),
            precision_debug_commit=PrecisionDebugCommitScope(
                include=tuple(precision_commit.get("include", []) or []),
                exclude=tuple(precision_commit.get("exclude", []) or []),
            ),
            scaffolding=RepositoryProfile._parse_scaffolding(data),
        )

    @staticmethod
    def _parse_build_stage(s: dict) -> BuildStage:
        """Parse one build/eval-prepare step dict → BuildStage (shared by
        build_variants.stages and eval_prepare; §2.5 single parse path)."""
        return BuildStage(
            name=s.get("name", ""),
            cwd=s.get("cwd", "."),
            command_template=s.get("command_template", ""),
            default_chip=s.get("default_chip", ""),
            enabled=bool(s.get("enabled", True)),
            role=s.get("role", "build"),
        )

    @staticmethod
    def _parse_scaffolding(data: dict) -> Scaffolding:
        """Parse + load-time-validate the ``scaffolding`` block (§1.3).

        The block is mandatory (§1.4: no legacy fallback). Enforces three
        invariants: (1) the block is present, (2) every entry is a known kind,
        and (3) ``selected ∈ supported``. A violation raises ``ValueError`` —
        the profile loader surfaces it at load, not at deploy time.
        """
        sc = data.get("scaffolding")
        if not sc:
            raise ValueError(
                f"profile '{data.get('name', '?')}' is missing the required "
                f"'scaffolding' block — every profile must declare its "
                f"invocation protocol (selected ∈ supported)"
            )
        supported = tuple(sc.get("supported", []) or [])
        selected = sc.get("selected", "") or ""
        unknown = [k for k in (*supported, selected) if k and k not in VALID_SCAFFOLDING_KINDS]
        if unknown:
            raise ValueError(
                f"scaffolding declares unknown kind(s) {unknown}; "
                f"valid kinds are {list(VALID_SCAFFOLDING_KINDS)}"
            )
        if selected and selected not in supported:
            raise ValueError(
                f"scaffolding.selected '{selected}' is not in supported "
                f"{list(supported)} — a profile must select one of the "
                f"protocols it declares support for"
            )
        return Scaffolding(supported=supported, selected=selected)

    # verify_repo.py and other callers use from_dict; keep it as an alias.
    from_dict = from_yaml
