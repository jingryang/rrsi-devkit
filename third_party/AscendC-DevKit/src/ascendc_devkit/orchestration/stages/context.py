"""L3 Orchestration — Context Stage: load profile, init adapter, collect reference code."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.domain.operator import OperatorSpec, OperatorIdentity
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.orchestration.registry import register_stage
from ascendc_devkit.orchestration.kernel.action import (
    LoadProfile, InitAdapter, CollectReferenceCode, Action, NoOp,
    ScanExistingOperator, ReadOperatorCode, BuildBaseline, ReadOperatorFromPath,
    AskUserQuestion, Option,
)
from ascendc_devkit.adapters.repository.profile_loader import ProfileLoader
from ascendc_devkit.adapters.repository.generic import GenericRepositoryAdapter
from ascendc_devkit.domain.chip import is_known_generation
from ascendc_devkit.orchestration.run_context import (
    build_run_context, RunContext, HardwareTarget,
)
from ascendc_devkit.infra.logger import Logger

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State


@register_stage
class ContextStage(Stage):
    name = "context"
    description = "Load RepositoryProfile, initialize adapter, collect reference code"
    default_max_iterations = 1
    needs_iteration_safety_net = False  # deterministic single pass, no agent

    def __init__(self, repo_guard=None):
        # DI seam (L3→L7): tests inject a stubbed/disabled RepoGuard; production
        # leaves None and a real guard is lazily built in transition() once the
        # workspace (backup_root for non-git repos) is known.
        self._repo_guard = repo_guard

    def input_contract(self) -> StageIOContract:
        return StageIOContract(
            # op_name/target_repo/repo_profile_name are dual-purpose: IO inputs
            # AND dispatcher preflight signals for "must be user-provided"
            # (enforced per mode — interactive prompts, non-interactive errors).
            # Keep them in `requires` or preflight loses its enforcement hook.
            requires=["mode", "op_name", "target_repo", "repo_profile_name"],
            # non_interactive always carries a safe default (False); reading it
            # never fails, so requiring it is noise — declare it optional.
            optional=["reference_op_path", "code_source", "non_interactive"],
        )

    def output_contract(self) -> StageIOContract:
        return StageIOContract(
            provides=["profile", "adapter", "op_identity", "reference_code"],
        )

    def actions(self, state: State, iteration: int = 1) -> list[Action]:
        base = [
            LoadProfile(profile_name=state.repo_profile_name),
            InitAdapter(profile=None, repo_root=state.target_repo),
        ]

        if state.mode == "new":
            return base + [CollectReferenceCode(ref_path=state.reference_op_path)]

        # == incremental mode ==
        # Path 1: CLI provided reference path → use directly
        if state.reference_op_path:
            return base + [ReadOperatorFromPath(path=state.reference_op_path)]

        # Path 2: non-interactive → auto-scan
        if state.non_interactive:
            return base + self._scan_and_read(state)

        # Path 3: interactive — ask user on iteration 1
        if iteration == 1:
            return base + [
                AskUserQuestion(
                    question=f"\\u5982\\u4f55\\u5b9a\\u4f4d\\u7b97\\u5b50 '{state.op_name}' \\u7684\\u5df2\\u6709\\u4ee3\\u7801\\uff1f",
                    options=[
                        Option(label="\\u81ea\\u52a8\\u641c\\u7d22",
                               description=f"\\u5728 {state.target_repo} \\u4e2d\\u6309 profile \\u7ea6\\u5b9a\\u641c\\u7d22"),
                        Option(label="\\u624b\\u52a8\\u6307\\u5b9a\\u8def\\u5f84",
                               description="\\u8f93\\u5165\\u5df2\\u6709\\u4ee3\\u7801\\u7684\\u76ee\\u5f55\\u8def\\u5f84"),
                    ],
                ),
            ]

        # iteration 2: act on user choice
        if state.code_source == "manual":
            return [ReadOperatorFromPath(path=state.reference_op_path)]
        return self._scan_and_read(state)

    def _scan_and_read(self, state: State) -> list[Action]:
        return [
            ScanExistingOperator(
                adapter=state.adapter,
                op_name=state.op_name,
                repo_root=state.target_repo,
            ),
            ReadOperatorCode(op_identity=state.op_identity),
            BuildBaseline(
                adapter=state.adapter,
                op=state.op_identity,
                design_target_chip=state.design_target_chip,
            ),
        ]

    def transition(self, state: State, result: dict) -> State:
        profile = None
        adapter = None
        op_identity = None
        # Always a dict (never None): "no reference code" is a legitimate state
        # for new-mode ops without a reference. Keeping it non-None lets the
        # output_contract be satisfied and avoids spinning to the iteration ceiling.
        reference_code: dict[str, str] = {}

        # Load profile by name; fall back to a pre-set profile ONLY when the
        # name was not declared (e.g. cross-compile presets / tests that inject
        # one directly). A declared-but-missing name is a config error — warn
        # loudly (§1.2 可诊断) rather than silently masking it with a preset.
        try:
            profile = ProfileLoader.load(state.repo_profile_name)
        except FileNotFoundError:
            if state.repo_profile_name:
                Logger.warn(
                    f"profile '{state.repo_profile_name}' not found (declared "
                    f"but missing) — falling back to pre-set profile; fix the "
                    f"profile name or register it"
                )
            profile = state.profile

        # Init adapter
        if profile and state.target_repo:
            adapter = GenericRepositoryAdapter(profile)

        # Build OperatorIdentity from the resolved op_dir (from --op-dir). The
        # op_dir is the absolute operator directory; repo_root is its repo. No
        # template synthesis — the user supplied the target directory directly.
        if profile and state.op_dir:
            short_name = state.op_name or profile.derive_op_name(
                state.full_op_name or Path(state.op_dir).name
            )
            op_spec = OperatorSpec(name=short_name)
            # INVARIANT: op_identity.op_dir is DERIVED from the top-level
            # state.op_dir (the single authority, written by EntryStage), never an
            # independent value. Fallback readers do
            # ``state.op_dir or op_identity.op_dir`` — correct only while the two
            # can't diverge. Do NOT add a second writer that sets
            # op_identity.op_dir from a different source without also updating
            # state.op_dir, or the fallback would silently prefer a stale
            # top-level (§1.4 single authority). Guarded by
            # test_context_op_dir_invariant.
            op_dir = Path(state.op_dir)
            repo_root = Path(state.repo_root) if state.repo_root else (
                state.target_repo or op_dir.parent
            )
            # When the operator directory already exists (incremental, or new
            # over an existing tree), discover its source files via the adapter
            # (recursive scan, keyed by op_dir-relative path). New operators
            # whose directory doesn't exist yet get an empty file map.
            files: dict = {}
            if adapter is not None and op_dir.is_dir():
                try:
                    scanned = adapter.scan_existing_operator(
                        repo_root, short_name, op_dir=op_dir,
                    )
                    files = scanned.files
                except (FileNotFoundError, ValueError) as e:
                    Logger.warn(f"operator scan skipped: {e}")
            op_identity = OperatorIdentity(
                spec=op_spec,
                repo_root=repo_root,
                op_dir=op_dir,
                files=files,
            )

        # Collect reference code if path provided
        if state.reference_op_path:
            ref_path = Path(state.reference_op_path)
            if ref_path.exists():
                for f in ref_path.rglob("*"):
                    if f.suffix in (".cpp", ".h", ".hpp", ".py"):
                        reference_code[str(f.relative_to(ref_path))] = f.read_text()

        # Resolve reference search roots: variant default first, then the
        # user's --reference values (appended). Repo-relative roots are
        # resolved against repo_root; absolute (cross-repo) roots pass through.
        reference_roots: list[str] = []
        if profile is not None and hasattr(profile, "reference_roots"):
            base_root = Path(state.repo_root) if state.repo_root else state.target_repo
            for r in profile.reference_roots(state.rel_op_dir, state.reference_roots):
                rp = Path(r)
                if not rp.is_absolute() and base_root is not None:
                    rp = Path(base_root) / r
                reference_roots.append(str(rp))

        # step-34: single authority chain for the DESIGN target (修正 #2):
        #   CLI (--design_target_chip, resolved at dispatch into the field)
        #   > profile default_chip > probe-if-known (the on-box runtime chip,
        #   when the probe could identify it). design drives code STYLE only
        #   (programming_model = chip_programming_model(design)); the COMPILE
        #   target (soc_version/chip_code) is derived from runtime, design
        #   fallback (P65 dual source) — runtime_target_chip also feeds the
        #   build gate. Requirement-doc constraint is applied later by
        #   RequirementStage (_apply_design_target_chip), above profile.
        design_chip = state.design_target_chip  # CLI (dispatch) — highest, keep if set
        if not design_chip and profile is not None and hasattr(profile, "select_variant"):
            variant = profile.select_variant(state.rel_op_dir)
            if variant is not None:
                enabled = variant.enabled_stages()
                if enabled and enabled[0].default_chip:
                    design_chip = enabled[0].default_chip
        if not design_chip and is_known_generation(state.runtime_target_chip):
            # auto-detect: no CLI, no profile default → target the box's chip
            design_chip = state.runtime_target_chip

        # Plan-A safety net: establish the pre-write baseline so hard-failure
        # rollback can restore op_dir. Only when we have a real target repo and
        # a resolved op_dir (new/incremental both write the repo). Pure-design
        # deliveries (no target_repo) skip this entirely.
        target_repo_baseline_ref = state.target_repo_baseline_ref
        if state.target_repo and op_identity is not None:
            target_repo_baseline_ref = self._establish_baseline(state, op_identity)

        # P27: build the frozen, run-invariant RunContext once (design-target
        # hw from chip spec + current-hw/software-env probes). Degrade gracefully
        # — an unmapped chip must not abort the whole design run; downstream sees
        # empty hw_params and treats hardware claims as unverifiable instead of
        # false-positive-blocking (cures the AC2 class of bug).
        run_context = self._build_run_context(state, design_chip)

        return state.with_updates(
            profile=profile,
            adapter=adapter,
            op_identity=op_identity,
            reference_code=reference_code,
            reference_roots=reference_roots or state.reference_roots,
            design_target_chip=design_chip,
            run_context=run_context,
            target_repo_baseline_ref=target_repo_baseline_ref,
        )

    @staticmethod
    def _build_run_context(state: "State", design_chip: str) -> RunContext:
        try:
            return build_run_context(design_chip, getattr(state, "npu_id", 0))
        except Exception as e:  # unmapped chip / spec read failure
            Logger.warn(f"RunContext build failed ({e}); hw_params unverifiable")
            return RunContext(hardware_target=HardwareTarget(chip=design_chip))

    def _establish_baseline(self, state: State, op_identity) -> str:
        """Pre-flight clean check + baseline creation (decision D4 / Task 3.2)."""
        guard = self._get_repo_guard(state)
        repo_root = op_identity.repo_root
        op_dir = op_identity.op_dir
        # Pre-flight: a dirty op_dir means a later checkout+clean rollback would
        # also wipe pre-existing uncommitted changes. Warn (non-interactive) or
        # confirm (interactive) before proceeding.
        if not guard.is_clean(repo_root, op_dir):
            if state.non_interactive:
                Logger.warn(
                    f"op_dir '{op_dir}' has uncommitted changes; failure "
                    f"rollback (checkout HEAD + clean) will also discard them "
                    f"(rollback boundary imprecise)."
                )
            elif not self._confirm_dirty_baseline(op_dir):
                Logger.warn("User declined to proceed with a dirty op_dir baseline.")
                # Proceed anyway but skip baseline so no destructive rollback fires.
                return ""
        ref = guard.create_baseline(repo_root, op_dir)
        if ref:
            Logger.info(f"Repo baseline established: {ref[:40]}")
        return ref

    def _get_repo_guard(self, state: State):
        if self._repo_guard is not None:
            return self._repo_guard
        from ascendc_devkit.infra.repo_guard import RepoGuard
        backup_root = None
        if state._workspace is not None:
            backup_root = state._workspace.dir / "repo_backup"
        ignore_globs = []
        if state.profile is not None:
            ignore_globs = list(getattr(state.profile, "artifacts_ignore", []) or [])
        return RepoGuard(backup_root=backup_root, ignore_globs=ignore_globs)

    def _confirm_dirty_baseline(self, op_dir) -> bool:
        from ascendc_devkit.infra.terminal import Terminal
        if not Terminal.stdin_is_tty():
            return False
        Logger.warn(
            f"op_dir '{op_dir}' 内已有未提交改动。失败回滚 "
            f"(git checkout HEAD + clean) 会把这些改动一并清掉。"
        )
        try:
            ans = input("是否继续并以当前 HEAD 为回滚基线？[y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        return ans in ("y", "yes")
