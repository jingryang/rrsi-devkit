"""L3 Orchestration — Deployer: profile-role-driven build → install → smoke.

Self-evolution: deterministic shell-command service (no agent, no longer a
stage). Bridges the gap between "compiled" and "callable" — moves an operator
to a runnable state so callers can invoke the real kernel.

Generalized (D6-2, P7): the deploy steps are NOT hardcoded here. They are
declared in the target repo's profile.json as build_variant.stages with typed
roles (build / install_runtime / install_python / smoke). The Deployer runs the
skeleton (build → install → smoke → assemble DeployResult) driven by the
profile, so cann-bench / ops-nn / omni-ops each deploy their own way without a
per-repo stage class.

Per-op isolation (02 D plan): opp → per-op opp dir via --install-path, whl →
pip --target per-op python dir, never global. These per-op paths are injected
into the profile command templates as {per_op_opp_dir} / {per_op_python_dir}
alongside {run_pkg} / {whl_pkg} / {full_op_name} / {chip_version}.

P54 D3: deploy 链抽成 ``Deployer`` 服务（§2.5 单一通路）——the codegen +
precision_debug agents（经 CLI ``redeploy``）共用同一 deploy 链。
``Deployer.deploy()`` 是唯一公共入口；其余 ``_``-前缀方法为 deploy 链内部步骤。

P57：deploy 不再作为 stage 存在（``DeployStage`` 已删）。build/install/smoke 下沉
为 agent 会话内调用的原子能力（codegen 在 session 内 build 自修，precision_debug
经 CLI ``redeploy`` 复用 ``Deployer``），删除确定性 shell stage 以消除跨 stage 错误
传递（fail_strategy=halt 抢占 deploy_failed→codegen 路由）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ascendc_devkit.domain.build_log_scanner import (
    build_failure_analysis_footer,
    classify_build_error,
    format_kernel_error_summary,
    scan_kernel_compile_errors,
)
from ascendc_devkit.domain.chip import (
    chip_programming_model,
    is_known_generation,
    to_soc_version,
)
from ascendc_devkit.domain.verification import DeployResult
from ascendc_devkit.domain.operator import CANON_ATTR_CHECKERS
from ascendc_devkit.infra.logger import Logger

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State, ErrorFeedback
    from ascendc_devkit.domain.repository import RepositoryProfile, BuildStage


# Per-op install command timeout (seconds); build gets a longer budget.
_BUILD_TIMEOUT = 600
_INSTALL_TIMEOUT = 120


def _rc_label(rc: int | None) -> str:
    """进程死亡方式（通道不变式：框架观测到的一切必须到达重试消费者）。

    rc<0 → ``signal N (SIGxxx)``（subprocess 以负数回报信号死亡）；rc>0 →
    ``exit N``；None/0 → 空串。signal 名经 ``signal.Signal`` 解析，未知信号
    （如 SIGRT 区段）回退 ``signal N``。静默死亡（空输出）时这是唯一能区分
    「native 段错误」vs「Python 异常退出」的信号（99c4c0 gelu：框架判了
    rc≠0 却丢弃 rc 值，反馈退化为字面量）。
    """
    if rc is None or rc == 0:
        return ""
    import signal as _signal
    if rc < 0:
        try:
            return f"signal {-rc} ({_signal.Signals(-rc).name})"
        except (ValueError, KeyError):
            return f"signal {-rc}"
    return f"exit {rc}"


# Real-call smoke runs a kernel on NPU: the per-process cost is dominated by
# case's kernel is sub-millisecond. 60s leaves headroom over the old 30s
# getattr-only probe (which never touched the device).
_SMOKE_TIMEOUT = 60


def _source_identity(source_dir: Path) -> str:
    """纯 git 探测 source_dir 所在仓 → ``{HEAD 短12}-{clean|dirty-{n}}``。

    source_identity 记录「这份编译产物是哪份代码编出来的」，供 eval/debug 关联被测
    binary 与源码 commit，杜绝「跑错代码无人知」。**关键 dirty 标记**：deploy 先于
    commit、工作区 dirty 时（事故 16:47 deploy / 16:52 commit），裸 ``rev-parse HEAD``
    记到的是修复前 commit、非被测内容——故必须含「是否有未提交改动」的编码，否则
    provenance 假安全。

    - 纯 git 探测（复用 infra.provenance 的公共 probe_source，§1.15 单点），
      **不读 commit message、不由模型写**——A3 侧交付决策模型彻底无法影响。
    - 非 git / git 不可用 → 返回 ``""``（空串，下游按「无来源信息」处理，诚实非伪造）。
    - ``{n}`` = dirty 文件数，让「有脏改动」可量化（改了多少文件的 private diff）。
    """
    from ascendc_devkit.infra.provenance import probe_source
    _, ident = probe_source(source_dir)
    return ident

# build 失败重试状态文件名（阶段2 改动3）：per-run 单文件，记录同类/累计失败计数，
# 供 build-retry gradient 判「同策略 / 换策略 / 升级」。落在 ws.subprocess_log 与
# build 失败日志同目录——agent 读 subprocess/*.log 时同处可见状态由来。
_BUILD_RETRY_STATE_FILENAME = "build_retry_state.json"

# Minimal legal default values for a REQUIRED attr (AttrSpec.default is None) by
# AttrSpec.type — used only when smoke must SYNTHESIZE a case (no test_cases).
# Best-effort: a required dtype/enum attr typed "str" can't be told apart from
# a plain string here ("" may be an illegal dtype) — such complex ops may fail
# the synthetic probe honestly; production relies on state.test_cases[0]
# (test_design guarantees legal inputs+attrs).
_SMOKE_ATTR_DEFAULTS = {
    "int": 0, "float": 0.0, "str": "", "bool": False,
    "list[int]": [], "list[float]": [],
}
# §2.5/§1.3: smoke-default keys must stay aligned with the canonical attr-type
# vocabulary (single source: domain CANON_ATTR_CHECKERS). Drift → loud fail at
# import, so a canonical type without a smoke default, or a stray key, is caught.
assert set(_SMOKE_ATTR_DEFAULTS).issubset(CANON_ATTR_CHECKERS), (
    "_SMOKE_ATTR_DEFAULTS keys drifted from canonical attr types: "
    f"unknown={sorted(set(_SMOKE_ATTR_DEFAULTS) - set(CANON_ATTR_CHECKERS))}"
)


def _smoke_required_tensor(ts) -> bool:
    """A tensor the smoke probe must feed (REQUIRED/DYNAMIC). OPTIONAL tensors
    are omitted so the op uses its own default (typically None) — feeding a
    synthetic tensor to an optional slot (e.g. a mask) could steer the op into
    an untested branch and fail smoke for a non-defect reason."""
    return getattr(ts, "param_type", "REQUIRED") != "OPTIONAL"


@dataclass(frozen=True)
class _ResolvedInputs:
    """Resolved deploy inputs shared by deploy() and build_install().

    Captures everything _resolve() computes past the chip gate + repo/profile
    checks, so the two public entries share one resolve path (§2.5: no
    duplicated resolve logic between the full chain and the build_install
    subset).
    """

    profile: "RepositoryProfile"
    variant: object  # BuildVariant
    repo_root: Path
    source_dir: Path
    op_name: str
    per_op_opp_dir: str
    per_op_python_dir: str
    tvars: dict
    source_identity: str = ""


class Deployer:
    """Profile-driven build → install → smoke deploy chain (§2.5 单一通路).

    Single source for the codegen agent (in-session build) + CLI ``redeploy``
    (+ precision_debug's agent, which reaches deploy via the ``redeploy`` CLI).
    Deterministic shell chain, no agent. Two public entries: ``deploy()`` runs
    build → install → smoke (``smoke_passed=True`` means actually callable);
    ``build_install()`` runs build → install only, for callers that don't need
    the real-call smoke gate (cannbench_adapt — §2.9: adapt smoke has no repair
    channel). Both share one resolve path (``_resolve``) and the build+install
    steps (``_run_build_install``); deploy() additionally chains
    ``_run_smoke_phase``. Every other method is an ``_``-prefixed internal step.
    """

    # —— public entries ——

    def _resolve(
        self, state: State,
    ) -> tuple[_ResolvedInputs | None, ErrorFeedback | None]:
        """Shared chip-gate + repo/profile/variant/per-op resolve for deploy()
        and build_install(). Returns (inputs, err); err is None on success.

        §1.9 build-chip gate — SECONDARY deep-defense entry (Option D). The
        PRIMARY gate is codegen.validate_inputs → PreconditionError (clean
        halt, codegen never spawns). deploy/build_install are reachable via the
        ``redeploy`` CLI / direct callers that BYPASS the pipeline (no
        validate_inputs runs), so the same check is re-applied here as a safety
        net. Both share chip_mismatch_reason (§2.5: one compare + one message).

        step-34: pure comparison against the dispatch-resolved runtime chip
        (probe authority) — no probe here, hence no env_probe_timeout path (a
        probe timeout is handled at dispatch via --runtime_target_chip fallback
        / EX_DATAERR). Single-sourced by chip_mismatch_reason (§2.5).
        """
        from ascendc_devkit.adapters.npu.detect import chip_mismatch_reason
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback

        chip_reason = chip_mismatch_reason(
            state.design_target_chip,
            state.runtime_target_chip,
        )
        if chip_reason:
            return None, ErrorFeedback(
                stage_name="deploy",
                error_type="chip_mismatch",
                message=chip_reason,
                details={"design_target_chip": state.design_target_chip or ""},
            )

        op_name = state.op_name or ""
        repo_root = self._resolve_repo_root(state)
        profile = state.profile

        if not repo_root or not op_name:
            return None, self._resolve_fail("resolve", "missing repo_root or op_name")
        if profile is None:
            return None, self._resolve_fail("resolve", "no repository profile on state")

        rel_op_dir = self._rel_op_dir(state, repo_root)
        if not profile.has_deploy_capability(rel_op_dir):
            return None, self._resolve_fail(
                "resolve",
                f"profile '{profile.name}' declares no deploy roles "
                f"(install_runtime + smoke) for '{rel_op_dir}'",
            )

        variant = profile.select_variant(rel_op_dir)
        source_dir = (repo_root / (variant.stages[0].cwd if variant.stages else ".")).resolve()
        full_op_name = state.full_op_name or op_name
        # Per-op isolation paths (02 D plan).
        # `_workspace` is attached by dispatcher/CLI/debug-service as the run
        # root (§4 invariant). Direct callers that bypass those entries
        # (test_npu's real-kernel guard stages State manually) surface a proper
        # resolve failure — NOT a bare AssertionError — so the error is honest
        # and diagnosable (§1.3/§3.7), and the fixture documents that it must
        # attach a workspace explicitly.
        ws = getattr(state, "_workspace", None)
        if ws is None:
            return None, self._resolve_fail(
                "resolve",
                "no run workspace attached (`state._workspace` is None); direct "
                "Deployer callers must construct the State with `_workspace=` "
                "(see tests/st/test_npu.py::deployed_add)",
            )
        per_op_opp_dir = self._per_op_path(ws, "opp", op_name)
        per_op_python_dir = self._per_op_path(ws, "python", op_name)
        # Template variables injected into every role command.
        tvars = self._template_vars(state, full_op_name, per_op_opp_dir, per_op_python_dir)
        return _ResolvedInputs(
            profile=profile, variant=variant, repo_root=repo_root,
            source_dir=source_dir, op_name=op_name,
            per_op_opp_dir=per_op_opp_dir, per_op_python_dir=per_op_python_dir,
            tvars=tvars,
            # step-119: 构建源码的来源标识（纯 git 探测，含 dirty 指纹）。source_dir
            # = repo_root/variant cwd = 真正构建的目录所在仓；对 cann-bench 是
            # examples/aclnn_launch_example。注入 DeployResult 供 eval/debug 关联。
            source_identity=_source_identity(source_dir),
        ), None

    def build_install(
        self, state: State, clean_build: bool = False,
    ) -> tuple[DeployResult, ErrorFeedback | None]:
        """build + install only (no smoke). Returns (DeployResult, ErrorFeedback|None).

        For callers that don't need the real-call smoke gate — cannbench_adapt
        (§2.9: the cannbench_adapt smoke has no repair channel; kernel
        callability is owned by codegen's smoke + precision_debug's run_tests).
        ``DeployResult.smoke_passed`` is always False here (smoke not run) —
        callers must NOT treat it as a gate (cannbench_eval is decoupled from
        smoke_passed for this reason). Pure data in/out (no State mutation),
        mirroring deploy().

        ``clean_build=True`` clears ``variant.clean_dirs`` before building so a
        newly-added operator is collected into ``_C.abi3.so`` (P96: CMake GLOB
        cache trap).
        """
        inputs, err = self._resolve(state)
        if err is not None:
            return DeployResult(smoke_passed=False), err
        self._programming_model = chip_programming_model(
            getattr(state, "design_target_chip", "") or "")
        return self._run_build_install(state, inputs, clean_build=clean_build)

    def compile(
        self, state: State, clean_build: bool = False,
    ) -> tuple[DeployResult, ErrorFeedback | None]:
        """build only（方案 2 D6 / L4 改动 1b）——不 install、不 smoke。

        codegen transition 用它做「编译验证门」：compile 错 → resume agent 修；compile 过 →
        才 install+smoke（install_and_smoke 复用本产物，不重 build）。返回的 DeployResult
        只带 run_package/wheel_package，install_path/python_path 留空（未 install）。
        """
        inputs, err = self._resolve(state)
        if err is not None:
            return DeployResult(smoke_passed=False), err
        self._programming_model = chip_programming_model(
            getattr(state, "design_target_chip", "") or "")
        return self._run_build_install(
            state, inputs, clean_build=clean_build, build_only=True)

    def install_and_smoke(
        self, state: State, compile_result: DeployResult,
    ) -> tuple[DeployResult, ErrorFeedback | None]:
        """复用 compile() 已产出的 .run/.whl 做 install + smoke（跳过 build 段）。

        L4 改动 1d / 质疑后修正：compile 过 → install+smoke 不重 build（无码改动不得做两次
        build）。compile_result 须带 run_package/wheel_package。smoke_passed=True 表示
        可调用（真 fn() call）。
        """
        inputs, err = self._resolve(state)
        if err is not None:
            return DeployResult(smoke_passed=False), err
        self._programming_model = chip_programming_model(
            getattr(state, "design_target_chip", "") or "")
        run_pkg = compile_result.run_package or ""
        whl_pkg = compile_result.wheel_package or ""
        if not run_pkg:
            return (
                DeployResult(smoke_passed=False),
                self._err("build", "install_and_smoke: compile_result 无 run_package"),
            )
        ws = getattr(state, "_workspace", None)
        tvars = dict(inputs.tvars)
        tvars["run_pkg"] = run_pkg
        tvars["whl_pkg"] = whl_pkg
        inst_result, inst_err = self._run_install_stages(
            inputs, tvars, run_pkg, whl_pkg, ws=ws)
        if inst_err is not None:
            return inst_result, inst_err
        return self._run_smoke_phase(state, inst_result, inputs)

    def deploy(
        self, state: State, clean_build: bool = False,
    ) -> tuple[DeployResult, ErrorFeedback | None]:
        """build + install + smoke (full chain). Returns (DeployResult, ErrorFeedback|None).

        Entry for CLI ``redeploy`` (+ codegen/precision_debug agents via that
        CLI): _resolve → _run_build_install → _run_smoke_phase.
        ``smoke_passed=True`` means actually callable (real fn() call). Pure
        data in/out (no State mutation) so the CLI can call it without
        constructing a stage-lifecycle State wrapper. Callers that don't need
        the smoke gate use build_install() instead.

        ``clean_build=True`` clears ``variant.clean_dirs`` before building so a
        newly-added operator is collected into ``_C.abi3.so`` (P96: CMake GLOB
        cache trap). Default False — existing callers (codegen/debug_service)
        keep incremental behavior.
        """
        inputs, err = self._resolve(state)
        if err is not None:
            return DeployResult(smoke_passed=False), err
        # 阶段1: 记录编程模型，供 _run_command 的 build 失败 footer 选对 API doc 变体
        # （A3 Membase→非SIMD 高阶API；A5 Regbase→SIMD_API）。_run_command 经 getattr
        # 安全读取，此处不设则取 ""（footer 仍给有效 doc 路径，仅可能非最优变体）。
        self._programming_model = chip_programming_model(
            getattr(state, "design_target_chip", "") or "")
        build_result, build_err = self._run_build_install(
            state, inputs, clean_build=clean_build)
        if build_err is not None:
            return build_result, build_err
        return self._run_smoke_phase(state, build_result, inputs)

    # —— repo/path resolution ——

    @staticmethod
    def _resolve_repo_root(state: State) -> Path | None:
        if state.repo_root:
            return state.repo_root
        if state.op_identity and state.op_identity.repo_root:
            return state.op_identity.repo_root
        return None

    @staticmethod
    def _rel_op_dir(state: State, repo_root: Path) -> str:
        """op_dir relative to repo_root (forward slash); falls back to state.rel_op_dir."""
        if state.rel_op_dir:
            return state.rel_op_dir
        op_dir = state.op_dir or (state.op_identity.op_dir if state.op_identity else None)
        if op_dir is None:
            return ""
        try:
            return Path(op_dir).resolve().relative_to(Path(repo_root).resolve()).as_posix()
        except ValueError:
            return Path(op_dir).name

    @staticmethod
    def _per_op_path(ws, kind: str, op_name: str) -> str:
        """Build a per-op isolation directory path (02 D plan).

        <run-artifacts>/per-op/<op_name>/<kind>/ — per-op 隔离目录是 run 内产物，
        _workspace 由 dispatcher new-run/resume/单-stage 全入口 attach（§4 不变式），
        不存在无 workspace 的真实 deploy 路径；历史 ~/.cache 兜底分支无调用者且违反
        §1.7（外部路径）——已删（§1.4/§2.5）。
        """
        assert ws is not None, "_per_op_path 需要 run workspace(dispatcher 全入口 attach)"
        p = ws.artifacts / "per-op" / op_name / kind
        p.mkdir(parents=True, exist_ok=True)
        return str(p)

    @staticmethod
    def _find_file(directory: Path, glob_pattern: str) -> str:
        """Find the first file matching a glob, return its absolute path or ''."""
        if not directory.exists():
            return ""
        matches = sorted(directory.glob(glob_pattern))
        return str(matches[0]) if matches else ""

    @staticmethod
    def _template_vars(state, full_op_name: str, per_op_opp_dir: str,
                       per_op_python_dir: str) -> dict:
        """Build the template-variable dict injected into every role command_template.

        ``soc_version`` = canonical chip → CANN soc_version(单一翻译点, to_soc_version);
        非 canonical(空/未知)→ 留空,让算子仓 build.sh 自动检测(与历史行为一致)。

        Compile target = RUNTIME chip first, design fallback (P65 dual source):
        在 A5 真机验证 A2/A3 Membase 代码时,产物用本机(runtime=A5)的 soc_version
        编译——代码风格由 design 决定,编译目标由真机决定。

        抽成静态方法以便 UT 直接守护 soc_version 派生——防止 command_template 占位符
        (如 ``{soc_version}``) 与 tvars 键漂移(NPU 真机用例曾因 tvars 漏 soc_version 而
        ``unknown template var 'soc_version'`` 全 skip,见 test_deploy.py)。
        """
        chip = state.runtime_target_chip or state.design_target_chip or ""
        soc_version = to_soc_version(chip) if is_known_generation(chip) else ""
        return {
            "full_op_name": full_op_name,
            "chip_version": chip,
            "soc_version": soc_version,
            "per_op_opp_dir": per_op_opp_dir,
            "per_op_python_dir": per_op_python_dir,
            "run_pkg": "",   # filled after build locates dist artifacts
            "whl_pkg": "",
        }

    @staticmethod
    def _cann_lib_paths() -> list[str]:
        """CANN system library dirs to prepend to LD_LIBRARY_PATH so the per-op
        _C.abi3.so can resolve libopapi / libascendcl / the CANN runtime stack."""
        paths: list[str] = []
        ascend_home = os.environ.get(
            "ASCEND_HOME_PATH",
            os.environ.get("ASCEND_HOME", "/usr/local/Ascend"),
        )
        arch = os.uname().machine  # aarch64
        toolkit_lib = Path(ascend_home) / f"{arch}-linux" / "lib64"
        if toolkit_lib.is_dir():
            paths.append(str(toolkit_lib))
        asc_lib = Path(ascend_home) / f"{arch}-linux" / "asc" / "lib64"
        if asc_lib.is_dir():
            paths.append(str(asc_lib))
        return paths

    @staticmethod
    def _callable_target(state) -> dict | None:
        """Read callable_target{kind, symbol} from codegen_manifest (G1/D7)."""
        manifest = state.codegen_manifest or {}
        ct = manifest.get("callable_target")
        if isinstance(ct, dict) and ct.get("kind") and ct.get("symbol"):
            return ct
        return None

    @staticmethod
    def _persist_subprocess_output(ws, role: str, stage_name: str,
                                   stdout: str, stderr: str,
                                   analysis_footer: str = "",
                                   rc_label: str = "",
                                   archive: bool = False) -> str | None:
        """Persist FULL stdout+stderr to ``<run>/subprocess/<role>_<stage>.log``.

        Best-effort (P57-B): the agent reads the full output via the returned
        path instead of a truncated ``stderr[:1500]`` slice. Returns the path
        str, or ``None`` when there is no workspace or the write fails (caller
        still carries a stderr tail so the error is never empty — §1.2 宽容兜底).

        ``analysis_footer`` (Plan cozy-wiggling-emerson 阶段1): a labeled
        framework-analysis section appended AFTER the raw output — structured
        clang error summary + AscendC API signature hints, so the codegen agent
        reading this log in its in-session redeploy loop sees the actionable
        error + authoritative signature instead of guessing from raw stderr.
        Empty by default (no enrichment when there's nothing to add).

        ``rc_label``（通道不变式）: 进程死亡方式（``_rc_label`` 形态，如
        ``signal 11 (SIGSEGV)``）。非空时以 ``=== rc ===`` 头部行写进日志——
        静默死亡（空输出）时这是日志里唯一区分「native 段错误」vs「正常退出
        但失败」的信号；所有 role（build/install/smoke）共用本单点。

        ``archive``（2026-09-10，M2 收口）：``True`` 时额外写一份
        ``<stem>_retry{N}.log`` 归档（N 取自刚 bump 的 retry-state total）。
        只由调用方在 **build 失败** 分支传 ``True``（见 ``_run_command``）——
        本函数保持「落盘一份」的纯粹职责，不内建角色分支；install/smoke 失败
        没有多轮重试语义（retry-state 只记 build 类），调用方不传 archive。
        """
        if ws is None:
            return None
        try:
            log_dir = ws.subprocess_log
            log_dir.mkdir(parents=True, exist_ok=True)
            stem = f"{role}_{stage_name}" if stage_name else role
            path = log_dir / f"{stem}.log"
            content = ""
            if rc_label:
                # 单行头：rc 值并入 === 行——结构行统一以 === 开头，消费端
                # （_first_smoke_error_line 等）按前缀跳过即可，不会把 rc 值
                # 误当首条错误行。
                content += f"=== rc === {rc_label}\n"
            content += (
                f"=== stdout ===\n{stdout or ''}\n=== stderr ===\n{stderr or ''}\n"
            )
            if analysis_footer:
                content += f"{analysis_footer}\n"
            path.write_text(content, encoding="utf-8")
            # 归档（仅 build 失败调用方传 archive=True）：<stem>.log 覆盖写丢历史
            # （transpose 2026-09-10 根因：首轮 CeilDiv 被物理覆盖，后续反馈只能
            # 读到当轮残影），额外留一轮一个的 _retry{N}.log 供回溯。attempt 号
            # 取自 retry-state total——调用方在 _build_failure_footer 里已 bump
            # （footer 先于本函数调用），时序契约在调用方保证；total 读不到时
            # 缺省 1（best-effort，§1.2）。
            if archive:
                st = Deployer._read_retry_state(ws)
                attempt = st.get("total") or 1
                archive_path = log_dir / f"{stem}_retry{attempt}.log"
                archive_path.write_text(content, encoding="utf-8")
            return str(path)
        except Exception:  # noqa: BLE001 — persistence must never mask the real error
            return None

    @staticmethod
    def _err(step: str, stderr: str, log_path: str | None = None,
             extra: dict | None = None):
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        details = {
            "step": step,
            "log": log_path or "",
            "stderr_tail": (stderr or "")[-2000:],
        }
        if extra:
            details.update(extra)   # 结构化补充（rc_label/smoke_context，§2.10）
        return ErrorFeedback(
            stage_name="deploy",
            error_type="deploy_failed",
            message=f"deploy step '{step}' failed",
            # Structured: agent reads FULL output via ``log``; ``stderr_tail`` is
            # a quick peek. Single shape regardless of persistence (§1.4).
            details=details,
        )

    @staticmethod
    def _resolve_fail(step: str, msg: str):
        """Resolve-phase failure (missing repo_root/profile/capability): log + ErrorFeedback.

        No subprocess ran → no log file; ``stderr_tail`` carries the reason.
        Mirrors ``_err``'s details shape so downstream readers stay uniform.
        """
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        Logger.error(f"Deployer: [{step}] {msg}")
        return ErrorFeedback(
            stage_name="deploy",
            error_type="deploy_failed",
            message=f"deploy step '{step}' failed: {msg}",
            details={"step": step, "log": "", "stderr_tail": msg[-2000:]},
        )

    # —— build retry-state（阶段2 改动3）——

    @staticmethod
    def _read_retry_state(ws) -> dict:
        """Read per-run build-retry state. Best-effort: missing/corrupt file
        (or no workspace) → empty state, never crashes (§1.2 宽容兜底).

        Shape: ``{"per_class": {<class>: <count>}, "total": <count>,
        "last_class": <class>}``. ``per_class`` keyed by ``classify_build_error``
        buckets (C-API/C-TYP/C-SYM/C-LNK/unknown).
        """
        empty = {"per_class": {}, "total": 0, "last_class": ""}
        if ws is None:
            return empty
        try:
            import json
            path = ws.subprocess_log / _BUILD_RETRY_STATE_FILENAME
            if not path.exists():
                return empty
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — corrupt/missing → empty, not fatal
            return empty
        if not isinstance(data, dict):
            return empty
        raw_per_class = data.get("per_class")
        if not isinstance(raw_per_class, dict):
            raw_per_class = {}
        # M1: 强转值为 int、丢弃非数值项——防损坏值（如 "garbage"）让 _bump_retry_state
        # 的 `+1` 抛 TypeError、被外层 except 兜成 (1,1) 且写回语句在异常后永不执行，
        # 致该类 gradient 永久卡「第1次/同策略」。丢弃后下次 bump 用干净值算出新状态并
        # 覆盖损坏文件（自愈）；丢弃时留 warning（§1.3 可观测）。
        per_class: dict[str, int] = {
            k: int(v) for k, v in raw_per_class.items()
            if not isinstance(v, bool) and isinstance(v, (int, float))
        }
        dropped = len(raw_per_class) - len(per_class)
        if dropped:
            Logger.warn(
                f"Deployer: build_retry_state.json had {dropped} non-numeric "
                f"per_class value(s); dropped (self-heal on next bump)")
        try:
            total = int(data.get("total") or 0)
        except (TypeError, ValueError):
            total = 0
        last_class = data.get("last_class") or ""
        return {"per_class": per_class, "total": total, "last_class": last_class}

    @classmethod
    def _bump_retry_state(cls, ws, error_class: str) -> tuple[int, int]:
        """Increment per-class + total build-failure count, persist, return
        ``(class_count_after_bump, total_after_bump)``.

        Drives the retry-gradient: caller builds the strategy hint from these
        counts (1st→同策略 / 2nd→换策略 / >=3→升级) instead of blindly same-
        strategy retrying. Best-effort: any I/O failure → ``(1, 1)`` so the
        agent still gets a benign 'same strategy' hint rather than crashing
        (§1.2 — retry tracking must never mask the real build error).
        """
        state = cls._read_retry_state(ws)
        try:
            import json
            per_class = dict(state["per_class"])
            per_class[error_class] = per_class.get(error_class, 0) + 1
            total = state["total"] + 1
            new_state = {
                "per_class": per_class, "total": total, "last_class": error_class,
            }
            if ws is not None:
                path = ws.subprocess_log / _BUILD_RETRY_STATE_FILENAME
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(new_state), encoding="utf-8")
            return per_class[error_class], total
        except Exception:  # noqa: BLE001
            return 1, 1

    # —— role command execution ——

    def _run_command(self, stage: "BuildStage", repo_root: Path, tvars: dict,
                     ws=None) -> tuple[bool, str, str | None]:
        """Render + run one role command_template. Returns ``(ok, stderr, log_path)``.

        On failure the FULL stderr is returned (no truncation) and, when ``ws``
        is provided, stdout+stderr are persisted to the run's subprocess log —
        the agent reads the full output via ``log_path`` (P57-B).
        """
        try:
            cmd = stage.command_template.format(**tvars)
        except KeyError as e:
            return False, f"unknown template var {e} in stage '{stage.name}'", None
        if not cmd.strip():
            return True, "", None  # empty command (e.g. smoke handled separately)
        cwd = (repo_root / stage.cwd).resolve()
        Logger.action("deploy", f"[{stage.role}/{stage.name}] {cmd} (cwd={cwd})")
        timeout = _BUILD_TIMEOUT if stage.role == "build" else _INSTALL_TIMEOUT
        # P99: pip --target --force-reinstall 不覆盖已存在的包文件（__init__.py 等），
        # redeploy 后 per-op 包会残留旧版——agent 改的 wrapper 进了 whl 却到不了 per-op
        # （scan_interfaces 发现不到新算子，operators=[]）。per_op_python_dir 是 per-op
        # 隔离的 whl target dir（_per_op_path），pip 前清空其内容让新 whl 干净覆盖。
        if stage.role == "install_python":
            tgt = tvars.get("per_op_python_dir", "")
            if tgt and Path(tgt).exists():
                for child in Path(tgt).iterdir():
                    if child.is_dir():
                        shutil.rmtree(child, ignore_errors=True)
                    else:
                        child.unlink(missing_ok=True)
        try:
            r = subprocess.run(
                cmd, shell=True, cwd=str(cwd),
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return False, f"[{stage.name}] timed out after {timeout}s", None
        except Exception as e:  # noqa: BLE001 — surface any spawn failure
            return False, f"[{stage.name}] {e}", None
        if r.returncode != 0:
            footer = self._build_failure_footer(stage, ws, r.stdout, r.stderr)
            log_path = self._persist_subprocess_output(
                ws, stage.role, stage.name, r.stdout, r.stderr,
                analysis_footer=footer, rc_label=_rc_label(r.returncode),
                # M2/M3（2026-09-10）：归档只在 build 失败分支触发（RC≠0 是所有
                # role 的通用失败分支，install/smoke 不传 archive）。footer 已在此
                # 前 bump retry-state total → persist 读到的即本轮 attempt 号
                # （时序契约在调用方保证，见 _persist 参数文档）。
                archive=(stage.role == "build"))
            return False, r.stderr, log_path
        # 第5类隐患:cann-bench build_run.sh 的 ``||`` 把 kernel 编译失败吞成 RC=0。
        # 扫描 build role 输出,命中 → 视为 build 失败,复用上面 RC≠0 通路(落盘
        # subprocess/*.log + 返回 False),让 codegen in-session 自修循环捕获
        # (agent prompt 已指向 {run_dir}/subprocess/*.log,codegen.py:637)。
        if stage.role == "build":
            errors = scan_kernel_compile_errors(
                (r.stdout or "") + (r.stderr or ""))
            if errors:
                footer = self._build_failure_footer(stage, ws, r.stdout, r.stderr)
                log_path = self._persist_subprocess_output(
                    ws, stage.role, stage.name, r.stdout, r.stderr,
                    analysis_footer=footer, archive=True)
                return False, format_kernel_error_summary(errors), log_path
        return True, "", None

    def _build_failure_footer(self, stage: "BuildStage", ws,
                              stdout: str | None, stderr: str | None) -> str:
        """Framework-analysis footer for a build-role failure log.

        Deterministic enrichment the codegen agent reads in its in-session
        redeploy loop (Plan cozy-wiggling-emerson):
        - **阶段1**: structured clang error summary (surface file:line even when
          buried under linker noise) + AscendC API signature hints (authoritative
          doc path for ``no matching function for '<API>'``).

        Returns "" for non-build roles. Best-effort — any failure returns the
        partial footer (or "") so enrichment can never mask the real build error
        (§1.2 宽容兜底). Per-roll classification/counting only when ``ws``
        present (state must persist + the archive attempt number consumes it).
        """
        if getattr(stage, "role", "") != "build":
            return ""
        # 阶段1: clang 摘要 + 签名指路（domain 纯函数，不依赖 ws）。
        try:
            from ascendc_devkit.capabilities.knowledge import KnowledgeBase
            footer = build_failure_analysis_footer(
                stdout, stderr,
                getattr(self, "_programming_model", ""),
                KnowledgeBase().root)
        except Exception:  # noqa: BLE001 — enrichment is best-effort
            footer = ""
        # 阶段2: 同签名 stop-loss 计数（M2/M3 收口，2026-09-10）。
        # 防盲重试的判据 = 「同一错误连续重试无进展」→ 机械数签名 streak；
        # 分类器只在此做 `_bump_retry_state` 的 per_class/total 递增（供
        # 归档 attempt 号与 codegen 侧签名 streak 判断），advisory 文案已废弃
        # （signature 检测接管）——不再向日志追加 gradient。
        if ws is not None:
            try:
                text = f"{stdout or ''}\n{stderr or ''}"
                error_class = classify_build_error(text)
                self._bump_retry_state(ws, error_class)
            except Exception:  # noqa: BLE001 — counting is best-effort
                pass
        return footer

    def _smoke_script(self, callable_target: dict, per_op_python_dir: str) -> str:
        """Fail-closed probe script for kinds with NO real callable execution
        probe (aclnn / unknown).

        torch_op / pybind do NOT come here — ``_run_smoke`` routes them through
        ``_build_smoke_harness`` (the shared precision_debug harness) which does
        a REAL ``fn()`` call, so ``smoke_passed=True`` means actually callable,
        not merely registered. Any kind that reaches this method has no
        python-side execution probe the toolchain certifies, so it fails
        honestly (§3.7) rather than printing a false OK — the exact false-green
        that once let broken scaffolding earn smoke_passed=True and only blow up
        later in precision_debug.
        """
        symbol = callable_target["symbol"]
        kind = callable_target["kind"]
        return "\n".join([
            f"import sys; sys.path.insert(0, {per_op_python_dir!r})",
            f"raise SystemExit('smoke FAIL: no execution probe for callable kind "
            f"{kind!r} symbol {symbol} — wire a real probe before selecting this "
            f"kind (torch_op/pybind run a real fn() call via the harness)')",
        ])

    def _build_smoke_harness(
        self, state, callable_target: dict, per_op_python_dir: str,
        per_op_opp_dir: str, ld_path: str,
    ) -> str:
        """Build a REAL-call smoke harness for torch_op/pybind by reusing the
        precision_debug harness (``NPURunner._build_test_harness``) with ONE
        minimal case + no golden.

        The harness resolves the symbol AND invokes ``fn()`` with a real NPU
        tensor — so ``smoke_passed=True`` means actually callable, closing the
        codegen↔precision_debug 断裂点. step-31 §5 wired smoke as a symbol-
        resolution-only gate; this extends its boundary to 接线+可执行 (precision
        is still owned by run-cases — the harness ignores golden/precision fields).

        Reusing the SAME execution mechanism as precision_debug is the point:
        a smoke pass now constructively guarantees run-cases can call the op —
        no more "smoke green but debug crashes". Input case prefers
        ``state.test_cases[0]`` (test_design's real acceptance case → legal
        shape/dtype/attrs); synthesizes a tiny [1024] fp16 case when empty.
        """
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.operator import OperatorSpec, TensorSpec
        from ascendc_devkit.domain.requirement import TestCase

        # op_spec: prefer requirement's (carries real io); else synthesize a
        # minimal one — the harness only uses operator.name for display, the
        # actual call goes through callable_target.symbol.
        op_spec = None
        req = getattr(state, "requirement", None)
        if req is not None and getattr(req, "op_spec", None):
            op_spec = req.op_spec
        ident = getattr(state, "op_identity", None)
        if op_spec is None and ident is not None and getattr(ident, "spec", None):
            op_spec = ident.spec
        if op_spec is None:
            op_name = callable_target["symbol"].split(".")[-1] or "op"
            # Match the synthetic op_spec's REQUIRED-input count to the smoke
            # case that will actually feed the harness (state.test_cases[0] when
            # present — e.g. the fixture's binary-add 2-tensor case). A hardcoded
            # single input collides with any multi-input case at the harness
            # positional-coupling guard (test_cases.inputs count > op_spec.inputs
            # count → HarnessContractError), which is exactly the §1.10 silent-
            # misjudgment the guard defends — here it would wrongly fire on a
            # legal multi-input smoke case only because the synthetic spec
            # under-counts. op_spec here is display/positional-only (the real
            # call routes through callable_target.symbol), so N generic REQUIRED
            # tensors is a faithful placeholder.
            _smoke_tcs = list(getattr(state, "test_cases", None) or [])
            _n_in = len(_smoke_tcs[0].inputs) if (
                _smoke_tcs and getattr(_smoke_tcs[0], "inputs", None)) else 1
            op_spec = OperatorSpec(
                name=op_name,
                inputs=[TensorSpec(name=f"x{_i}", dtype="fp16", shape=["N"])
                        for _i in range(_n_in)],
                outputs=[TensorSpec(name="y", dtype="fp16", shape=["N"])],
            )

        # Production relies on state.test_cases[0] (test_design produces it; smoke
        # and precision_debug's run-cases both consume it — "no test_cases" can't
        # happen in the real pipeline, because run-cases would have nothing to
        # run either). The synthetic fallback below is a best-effort courtesy for
        # edge paths that bypass test_design (e.g. direct Deployer.deploy() in
        # fixtures): feed only REQUIRED tensors (OPTIONAL omitted → op uses its
        # default None) + REQUIRED attrs (AttrSpec.default is None) by type-
        # default. A required dtype/enum attr typed "str" can't be told from a
        # plain string ("" may be illegal) → such complex ops fail the synthetic
        # probe honestly (§3.7) — accepted, since the real pipeline never lands here.
        test_cases = list(state.test_cases or [])
        if not test_cases:
            # M4 (PR-42 review): a DYNAMIC (TensorList) input needs a
            # list-of-lists shape — a flat [1024] would fail the harness's
            # _validate_case_form (DYNAMIC requires list[list[int]]) and give a
            # false smoke failure on the no-test_cases edge path.
            synth_inputs = [
                {"shape": ([[1024]] if getattr(inp, "param_type", "") == "DYNAMIC"
                            else [1024]),
                 "dtype": getattr(inp, "dtype", None) or "fp16"}
                for inp in (op_spec.inputs or []) if _smoke_required_tensor(inp)
            ] or [{"shape": [1024], "dtype": "fp16"}]
            synth_attrs = {
                name: _SMOKE_ATTR_DEFAULTS.get(getattr(spec, "type", ""), 0)
                for name, spec in (getattr(op_spec, "attrs", None) or {}).items()
                if getattr(spec, "default", "__none__") is None
            }
            test_cases = [TestCase(
                name="smoke", inputs=synth_inputs, attrs=synth_attrs)]

        # P13 (step-116)：harness 内设备号恒 0（remap）——物理卡由 smoke 子进程
        # env 的 ASCEND_RT_VISIBLE_DEVICES 携带（见 _run_smoke 的 env 组装）。

        # _build_test_harness is an instance method reading self._chip_version
        # (for to_soc_version). Construct a probe-free instance (the formal
        # pathway, step-106: NPURunner.probe_free) — script GENERATION needs no
        # device probe (which would import torch in-process, breaking the
        # main-process purity invariant).
        runner = NPURunner.probe_free(chip_version=state.design_target_chip or "A2")

        deploy_result = DeployResult(
            python_path=per_op_python_dir, install_path=per_op_opp_dir,
            ld_library_path_add=ld_path,
        )
        return runner._build_test_harness(
            op_spec, test_cases[:1],
            golden_contract=None, deploy_result=deploy_result,
            callable_target=callable_target,
            smoke_probe=True,
        )

    @staticmethod
    def _smoke_case_error(stdout: str) -> str | None:
        """Extract the first case's ``error`` from the harness JSON stdout line.

        The harness prints one JSON object (its last stdout line); a per-case
        kernel exception lands in ``case_details[0].error`` while the script
        still exits 0 (_harness_template.py swallows case exceptions to keep
        running other cases). Returns the error string when ``fn()`` raised,
        else None (callable OK). On unparseable stdout returns None — the
        symbol-resolution-failure path already sys.exit(1)'d before reaching
        here, so exit 0 with no JSON is an edge we tolerate rather than
        silently failing a real pass.
        """
        import json
        if not stdout:
            return None
        line = ""
        for ln in stdout.splitlines():
            if ln.strip().startswith("{"):
                line = ln.strip()
        if not line:
            return None
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return None
        details = data.get("case_details") or []
        if details and isinstance(details[0], dict):
            return details[0].get("error") or None
        return None

    def _run_smoke(
        self, state, op_name: str, per_op_opp_dir: str,
        per_op_python_dir: str, ld_path: str,
    ) -> tuple[bool, str, str | None, dict]:
        """Run the callable_target-driven smoke check.

        Returns ``(ok, stderr, log_path, smoke_context)`` — ``smoke_context``
        （通道不变式：框架观测到的一切必须到达重试消费者）携带 ``rc_label``
        （进程死亡方式）、``script_path``（落盘的 smoke 脚本，可 ``python -u``
        复现）与 ``env_summary``（框架注入 env 的确定性子集）——调用方透传进
        ErrorFeedback.details，coder 反馈据此呈现完整失败现场，不再逆向重建
        （99c4c0 gelu：iter2 花 65min 复现框架 smoke 就为拿到这些信息）。

        torch_op/pybind: REAL ``fn()`` call via the shared harness (one minimal
        case, no golden) — ``smoke_passed=True`` means actually callable.
        aclnn/unknown: fail-closed (no execution probe; the script raises
        SystemExit → returncode != 0).

        Judgement: ``returncode==0`` AND (for torch_op/pybind) the harness JSON
        ``case_details[0]`` has no ``error`` — the harness swallows per-case
        kernel exceptions into exit 0 + an error field, so returncode alone
        re-opens the false-green hole that let registered-but-broken ops pass
        and only fail later in precision_debug.

        子进程 ``-u``：harness 逐用例进度打点（``[harness] case N start/...``）
        即时进 OS 管道（内核态缓冲，进程死亡不波及）——native 崩溃时部分
        进度存活，「kernel 是否执行过」从不可判变为可判。
        """
        ct = self._callable_target(state)
        if ct is None:
            return False, ("codegen_manifest.callable_target missing/invalid — "
                           "cannot verify the operator is callable"), None, {}
        kind = ct.get("kind", "")

        if kind in ("torch_op", "pybind"):
            script = self._build_smoke_harness(
                state, ct, per_op_python_dir, per_op_opp_dir, ld_path)
        else:
            # aclnn/unknown: fail-closed script (raises SystemExit → returncode!=0)
            script = self._smoke_script(ct, per_op_python_dir)

        Logger.info(f"Deployer: smoke test for {op_name} → {ct['symbol']}")
        env = os.environ.copy()
        # NPU 子进程统一卫生：smoke 子进程在 NPU 上下文跑算子包，可能 import torch_npu。
        # 给 torch_npu 官方 autoload=0 默认值，避免 npu 被注册两次（与 cannbench_eval 一致，
        # 详见 cannbench_eval._run_eval 同名注释）；setdefault 不覆盖显式设置。
        env.setdefault("TORCH_DEVICE_BACKEND_AUTOLOAD", "0")
        env["PYTHONPATH"] = per_op_python_dir
        # step-108: 值形态单源（vendor 级由 env_contract 拼出，§1.15）
        from ascendc_devkit.infra.env_contract import expected_ascend_custom_opp
        env["ASCEND_CUSTOM_OPP_PATH"] = expected_ascend_custom_opp(per_op_opp_dir)
        # P13 (step-116)：op 卡双变量 pin。物理卡只由 ASCEND_RT_VISIBLE_DEVICES
        # 携带（remap 后 harness 内设备号恒 0）。解析走唯一解析点
        # resolve_op_card（无池语境：pin env > state.npu_id > legacy env > 0，
        # 内层 CLI 子进程从命令前缀继承 pin env 读回同一张卡）。
        from ascendc_devkit.adapters.npu.card_pin import (
            card_pin_env, resolve_op_card)
        env.update(card_pin_env(resolve_op_card(state.npu_id, None)[0]))
        ld_parts: list[str] = []
        if ld_path:
            ld_parts.append(ld_path)
        ld_parts.extend(self._cann_lib_paths())
        existing = env.get("LD_LIBRARY_PATH", "")
        if existing:
            ld_parts.append(existing)
        env["LD_LIBRARY_PATH"] = ":".join(ld_parts)
        # 完整调用现场（通道不变式）：script 落盘（可 python -u 复现）+ env 摘要。
        # best-effort——落盘失败不阻断 smoke 本身（§1.2 宽容兜底，现场缺失由
        # rc/日志兜住）。
        ws = getattr(state, "_workspace", None)
        script_path = ""
        if ws is not None:
            try:
                from pathlib import Path as _P
                sp = _P(ws.subprocess_log) / "smoke_script.py"
                sp.parent.mkdir(parents=True, exist_ok=True)
                sp.write_text(script, encoding="utf-8")
                script_path = str(sp)
            except Exception:  # noqa: BLE001
                script_path = ""
        env_summary = {
            "PYTHONPATH": per_op_python_dir,
            "ASCEND_CUSTOM_OPP_PATH": env["ASCEND_CUSTOM_OPP_PATH"],
            "LD_LIBRARY_PATH": env["LD_LIBRARY_PATH"],
            "ASCEND_RT_VISIBLE_DEVICES": env["ASCEND_RT_VISIBLE_DEVICES"],
            "ASCEND_NPU_ID": env["ASCEND_NPU_ID"],
        }
        try:
            r = subprocess.run(
                [sys.executable, "-u", "-c", script], env=env,
                capture_output=True, text=True, timeout=_SMOKE_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return (False, f"smoke timed out after {_SMOKE_TIMEOUT}s", None,
                    {"rc_label": "", "script_path": script_path,
                     "env_summary": env_summary})
        except Exception as e:  # noqa: BLE001
            return (False, str(e), None,
                    {"rc_label": "", "script_path": script_path,
                     "env_summary": env_summary})
        smoke_ctx = {"rc_label": _rc_label(r.returncode),
                     "script_path": script_path, "env_summary": env_summary}
        if r.returncode != 0:
            log_path = self._persist_subprocess_output(
                ws, "smoke", "", r.stdout, r.stderr,
                rc_label=smoke_ctx["rc_label"])
            return False, r.stderr, log_path, smoke_ctx
        # torch_op/pybind: the harness swallows per-case kernel exceptions into
        # exit 0 + case_details[0].error. Parse the JSON to confirm fn() ran
        # without raising — returncode==0 alone would re-open the false-green
        # hole. (aclnn/unknown already failed at the returncode check above.)
        if kind in ("torch_op", "pybind"):
            case_err = self._smoke_case_error(r.stdout)
            if case_err:
                log_path = self._persist_subprocess_output(
                    ws, "smoke", "", r.stdout, r.stderr)
                return False, (f"smoke FAIL: kernel call raised — {case_err} "
                               f"(full output in subprocess log)"), log_path, smoke_ctx
        Logger.info(f"Deployer: smoke passed — {r.stdout.strip()}")
        return True, "", None, smoke_ctx

    def _run_build_install(
        self, state: State, inputs: _ResolvedInputs,
        clean_build: bool = False, build_only: bool = False,
    ) -> tuple[DeployResult, ErrorFeedback | None]:
        """Run build → install role stages (no smoke). Returns
        (DeployResult, ErrorFeedback|None). On success ``smoke_passed`` is False
        (smoke is deferred to _run_smoke_phase) but the result carries the
        produced run/whl/install/python paths.

        ``clean_build=True`` removes ``variant.clean_dirs`` under the build cwd
        before building — forces CMake reconfigure so a new operator enters
        ``_C.abi3.so`` (P96: GLOB cache trap). No-op when variant declares no
        clean_dirs.

        ``build_only=True`` (方案 2 D6/L4 改动 1): stops after build — does NOT
        run install stages. Returns a DeployResult carrying only the produced
        run_package/wheel_package (install_path/python_path LEFT EMPTY — nothing
        was installed, so non-empty would mislead downstream into thinking the
        op is deployable, §1.2).
        """
        ws = getattr(state, "_workspace", None)
        variant = inputs.variant
        repo_root = inputs.repo_root
        per_op_opp_dir = inputs.per_op_opp_dir
        per_op_python_dir = inputs.per_op_python_dir
        tvars = dict(inputs.tvars)

        # —— build role stages: compile → dist/*.run + *.whl ——
        build_stages = [s for s in variant.enabled_stages() if s.role == "build"]
        build_cwd = (repo_root / (build_stages[0].cwd if build_stages else ".")).resolve()
        # clean rebuild: clear CMake GLOB cache dirs so a newly-added operator
        # is collected into _C.abi3.so (P96 — INTERNAL cache + file(GLOB) without
        # CONFIGURE_DEPENDS). No-op when variant declares no clean_dirs.
        if clean_build and getattr(variant, "clean_dirs", ()):
            import glob
            for d in variant.clean_dirs:
                for p in glob.glob(str(build_cwd / d)):
                    shutil.rmtree(p, ignore_errors=True)
            Logger.info(
                f"Deployer: clean_build cleared {variant.clean_dirs} under {build_cwd}"
            )
        for st in build_stages:
            ok, err, log_path = self._run_command(st, repo_root, tvars, ws=ws)
            if not ok:
                return (
                    DeployResult(smoke_passed=False),
                    self._err("build", err, log_path),
                )

        # Locate produced packages under <build cwd>/dist/
        dist_dir = build_cwd / "dist"
        run_pkg = self._find_file(dist_dir, "*.run")
        whl_pkg = self._find_file(dist_dir, "*.whl")
        if not run_pkg:
            return (
                DeployResult(smoke_passed=False),
                self._err("build", f"no .run package found in {dist_dir}"),
            )
        tvars["run_pkg"] = run_pkg
        tvars["whl_pkg"] = whl_pkg

        # —— build_only（方案 2 D6/L4 改动 1a）：只编译验证，不 install ——
        # 返回 DeployResult 只带产物路径，install_path/python_path 留空（未 install，
        # 非空会误导下游以为已可部署，§1.2）。
        if build_only:
            return (
                DeployResult(
                    run_package=run_pkg, wheel_package=whl_pkg,
                    smoke_passed=False, source_identity=inputs.source_identity,
                ),
                None,
            )

        # —— install role stages ——
        return self._run_install_stages(inputs, tvars, run_pkg, whl_pkg, ws=ws)

    def _run_install_stages(
        self, inputs: _ResolvedInputs, tvars: dict,
        run_pkg: str, whl_pkg: str, ws=None,
    ) -> tuple[DeployResult, ErrorFeedback | None]:
        """Install stages only (no build, no smoke) — §1.15 单点：_run_build_install
        (build+install) 与 install_and_smoke (复用 compile 产物 install+smoke) 共用同一
        install 逻辑，不复制两份。返回 install 成功后的中间 DeployResult（含 per-op 路径，
        smoke_passed=False），由调用方决定是否接 _run_smoke_phase。
        """
        variant = inputs.variant
        repo_root = inputs.repo_root
        per_op_opp_dir = inputs.per_op_opp_dir
        per_op_python_dir = inputs.per_op_python_dir
        for st in variant.enabled_stages():
            if st.role not in ("install_runtime", "install_python"):
                continue
            ok, err, log_path = self._run_command(st, repo_root, tvars, ws=ws)
            if not ok:
                return (
                    DeployResult(
                        run_package=run_pkg, wheel_package=whl_pkg,
                        install_path=per_op_opp_dir, smoke_passed=False,
                    ),
                    self._err(st.role, err, log_path),
                )

        # install OK; smoke NOT run here — caller decides (deploy() chains
        # _run_smoke_phase; build_install()/install_and_smoke() stop here or chain).
        return (
            DeployResult(
                run_package=run_pkg, wheel_package=whl_pkg,
                install_path=per_op_opp_dir, python_path=per_op_python_dir,
                smoke_passed=False, source_identity=inputs.source_identity,
            ),
            None,
        )

    def _probe_env_contract_or_raise(self, per_op_opp_dir: str) -> None:
        """step-108 deploy 尾 env 契约探针：真实生产值经子进程回读比对。

        失配 = 外部环境毒（解释器启动钩子改写框架 env），非算子代码问题——
        raise ``EnvironmentNotAvailableError``（pause 家族：preserve + EX_CONFIG，
        树不回滚、修复环境后 resume 续跑）。装包后、烧任何 smoke 子进程前拦截，
        不空烧。批 20260829-142941-49134b P3 的 10h 空烧路径由此关闭。
        """
        from ascendc_devkit.domain.exceptions import EnvironmentNotAvailableError
        from ascendc_devkit.infra import env_contract
        violation = env_contract.probe_env_contract({
            **os.environ,
            "ASCEND_CUSTOM_OPP_PATH": (
                env_contract.expected_ascend_custom_opp(per_op_opp_dir)),
        })
        if violation is not None:
            for line in env_contract.diagnose_env_hooks():
                Logger.error(f"  候选成因：{line}")
            raise EnvironmentNotAvailableError(
                stage_name="deploy",
                missing=f"env contract ({violation})",
                help_hint="环境问题非算子代码问题——清理解释器启动钩子后 resume 续跑",
            )

    def _run_smoke_phase(
        self, state: State, build_result: DeployResult, inputs: _ResolvedInputs,
    ) -> tuple[DeployResult, ErrorFeedback | None]:
        """Run the real-call smoke on an already built+installed package.
        Returns (final DeployResult, ErrorFeedback|None).

        smoke role: verify callable per codegen_manifest.callable_target —
        ``smoke_passed=True`` means actually callable (real fn() call).
        """
        # step-108: 先过 env 契约探针（毒环境零 smoke 子进程，不空烧）
        self._probe_env_contract_or_raise(inputs.per_op_opp_dir)
        ld_path = f"{inputs.per_op_opp_dir}/vendors/custom_ops/op_api/lib"
        smoke_ok, smoke_err, smoke_log, smoke_ctx = self._run_smoke(
            state, inputs.op_name, inputs.per_op_opp_dir, inputs.per_op_python_dir, ld_path,
        )
        if not smoke_ok:
            return (
                DeployResult(
                    run_package=build_result.run_package,
                    wheel_package=build_result.wheel_package,
                    ld_library_path_add=ld_path, install_path=inputs.per_op_opp_dir,
                    python_path=inputs.per_op_python_dir, smoke_passed=False,
                    # 本轮 smoke 失败的确切输出路径（''= 未跑到 smoke 的 build 失败不
                    # 会误读到旧日志 —— _regbase_smoke_phase 的新鲜度锚点，review m6）。
                    smoke_log_path=smoke_log or "",
                    source_identity=build_result.source_identity,
                ),
                self._err("smoke", smoke_err, smoke_log, extra={
                    "rc_label": smoke_ctx.get("rc_label", ""),
                    "smoke_context": smoke_ctx,
                }),
            )

        return (
            DeployResult(
                run_package=build_result.run_package,
                wheel_package=build_result.wheel_package,
                ld_library_path_add=ld_path, smoke_passed=True,
                install_path=inputs.per_op_opp_dir, python_path=inputs.per_op_python_dir,
                source_identity=build_result.source_identity,
            ),
            None,
        )
