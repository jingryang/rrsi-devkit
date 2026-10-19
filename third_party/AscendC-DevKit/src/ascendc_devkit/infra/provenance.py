"""L7 Infrastructure — Run provenance: immutable record of WHAT produced a run.

``build_provenance`` is the single translation point (cf. ``domain/chip.py``)
that collects, at run start, every signal needed to answer "which DevKit
version / which backend / which environment / which user runtime config
produced THIS run" — so a foreign run's logs are self-describing and a
reviewer can stop guessing whether the reporter ran an old commit, a dirty
working tree, or a different agent backend.

Written once to ``<run>/PROVENANCE.json`` (immutable) AND mirrored into the
first ``events.jsonl`` line as a ``run_started`` event — events.jsonl is the
authoritative record (run.log is best-effort tee; see bind-run-log memory).

All paths point at THIS repo / THIS host (§1.7 self-contained): the git
identity is read from the DevKit repo root; the *operator repo* baseline is
recorded separately as ``target_repo_baseline_ref`` (renamed from
``repo_baseline_ref`` to disambiguate — that field was the target operator
repo's HEAD used by the rollback safety net, NOT DevKit's own commit).

Every probe is best-effort and never raises: a signal that cannot be obtained
is recorded as ``null`` (+ an ``error`` reason where useful), never silently
dropped, so the absence itself is diagnostic (§1.2 可诊断, §3.7 诚实报错).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import socket
import subprocess
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path


# —— Danger-value thresholds (§1.3 load-time warn) ——
# A model output token limit at/below this very likely truncates agent output
# (user-reported root cause: opencode.json limit.output=8192 silently cut
# results, invisible in any product). Surfaced as a provenance warning so the
# danger is named at run start, not discovered after a debugging detour.
LOW_OUTPUT_TOKEN_THRESHOLD = 8192


# —— Dataclasses (frozen; serialized via asdict for PROVENANCE.json) ———————


@dataclass(frozen=True)
class GitProvenance:
    commit: str | None = None
    commit_short: str | None = None
    branch: str | None = None
    describe: str | None = None
    dirty: bool | None = None
    dirty_file_count: int | None = None
    repo_root: str | None = None
    error: str | None = None       # why git was unavailable, when it was


@dataclass(frozen=True)
class DevkitProvenance:
    version: str | None = None     # importlib.metadata.version("ascendc-devkit")
    git: GitProvenance = field(default_factory=GitProvenance)


@dataclass(frozen=True)
class OrchestrationProvenance:
    agent_backend: str | None = None       # "claude" | "opencode"
    backend_sdk_version: str | None = None
    orchestration_config_hash: str | None = None
    skill_manifest_fingerprint: str | None = None
    agent_manifest_fingerprint: str | None = None


@dataclass(frozen=True)
class RuntimeConfig:
    """User-controlled settings that change LLM behaviour (P3). Recorded
    verbatim so a truncation/misbehaviour can be correlated to the config that
    caused it, not inferred after the fact."""
    model: str | None = None
    max_turns: int | None = None
    output_token_limit: int | None = None
    context_token_limit: int | None = None
    base_url: str | None = None
    source: str = "unknown"        # "opencode.json" | "claude_sdk" | "unknown"


@dataclass(frozen=True)
class EnvironmentProvenance:
    cann_version: str | None = None
    python_version: str | None = None
    torch_npu_version: str | None = None
    compiler: str | None = None
    detected_chip: str | None = None       # canonical A2/A3/A5
    soc_version: str | None = None         # CANN literal, e.g. ascend910b
    driver_version: str | None = None
    npu_device_count: int | None = None
    hostname: str | None = None


@dataclass(frozen=True)
class Provenance:
    run_id: str
    built_at: str                          # ISO UTC, stamped here
    devkit: DevkitProvenance = field(default_factory=DevkitProvenance)
    orchestration: OrchestrationProvenance = field(default_factory=OrchestrationProvenance)
    runtime_config: RuntimeConfig = field(default_factory=RuntimeConfig)
    environment: EnvironmentProvenance = field(default_factory=EnvironmentProvenance)
    target_repo_baseline_ref: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# —— Probes (each best-effort, never raises) ———————————————————————————


def probe_git_head_and_dirty(repo_dir, scope=None) -> tuple[str | None, list[str]]:
    """L7 公共 git 探测：HEAD commit + 工作区 dirty 行（单点，§1.15）。

    Deploy 的 source_identity 与 provenance._git 共享同一 git 探测能力（rev-parse
    HEAD + status --porcelain + dirty 判定），避免同一行为两处实现逐点复制
    （漏改一处即分叉）。纯探测，不读 commit message、不写盘。

    - 非 git / git 不可用 → ``(None, [])``（调用方按「无来源信息」诚实处理）。
    - 返回 ``(commit, dirty_lines)``——commit 为完整 sha，dirty_lines 为
      ``git status --porcelain`` 非空行（数量即 dirty 文件数）。
    - ``scope``：只统计 ``scope`` 子路径内的 dirty 行（None=全仓）。一仓多 op
      布局下 op 级探测只应计本 op 的脏改动（§review-m2），兄弟 op/仓根的脏
      改动不计入；HEAD 本就是全仓粒度，不受 scope 影响。
    """
    def _run(*args: str) -> str | None:
        try:
            r = subprocess.run(["git", "-C", str(repo_dir), *args],
                               capture_output=True, text=True, timeout=5)
            if r.returncode != 0:
                return None
            return r.stdout.strip() or None
        except Exception:
            return None
    commit = _run("rev-parse", "HEAD")
    if commit is None:
        return None, []
    status_args = ["status", "--porcelain"]
    if scope is not None:
        status_args += ["--", str(scope)]
    status = _run(*status_args) or ""
    dirty_lines = [ln for ln in status.splitlines() if ln.strip()]
    return commit, dirty_lines


def probe_source(repo_dir, scope=None) -> tuple[str | None, str]:
    """HEAD + dirty 探测 → ``(完整 commit sha, {sha12}-{clean|dirty-N} 标签)``。

    单点（§1.15）：deploy 的 source_identity 与 precision 测量行的来源标签共用
    同一探测 + 格式化。返回的**完整 sha 是合法 git ref**，作收敛/回滚锚点；
    标签是溯源标识**非 git ref**——``{sha}-dirty-N`` 传给 ``git checkout`` 会
    静默失败（20260915 批实证：converge 拿标签当锚点 → rollback no-op 却打
    成功日志）。非 git / git 不可用 → ``(None, "")``（诚实：无来源信息）。
    ``scope`` 语义同 probe_git_head_and_dirty（op 级探测限定 op_dir）。
    """
    commit, dirty_lines = probe_git_head_and_dirty(repo_dir, scope=scope)
    if commit is None:
        return None, ""
    if dirty_lines:
        return commit, f"{commit[:12]}-dirty-{len(dirty_lines)}"
    return commit, f"{commit[:12]}-clean"


def _git(repo_root: Path) -> GitProvenance:
    # §1.15 单点：commit/dirty 探测复用公共 probe_git_head_and_dirty；此处仅补充
    # provenance 特有的 branch/describe 探测与结构封装。
    def _run(*args: str) -> str | None:
        try:
            r = subprocess.run(["git", "-C", str(repo_root), *args],
                               capture_output=True, text=True, timeout=5)
            if r.returncode != 0:
                return None
            return r.stdout.strip() or None
        except Exception:
            return None
    commit, dirty_lines = probe_git_head_and_dirty(repo_root)
    if commit is None:
        return GitProvenance(
            repo_root=str(repo_root),
            error="git rev-parse HEAD failed (not a git repo or git unavailable)")
    return GitProvenance(
        commit=commit,
        commit_short=commit[:12],
        branch=_run("rev-parse", "--abbrev-ref", "HEAD"),
        describe=_run("describe", "--tags", "--always", "--dirty"),
        dirty=bool(dirty_lines),
        dirty_file_count=len(dirty_lines),
        repo_root=str(repo_root),
    )


def _devkit_version() -> str | None:
    try:
        from importlib.metadata import PackageNotFoundError, version
        try:
            return version("ascendc-devkit")
        except PackageNotFoundError:
            return None
    except Exception:
        return None


def _backend_sdk_version(backend: str) -> str | None:
    if backend == "claude":
        try:
            import claude_agent_sdk  # type: ignore
            return getattr(claude_agent_sdk, "__version__", None)
        except Exception:
            return None
    if backend == "opencode":
        bin_ = shutil.which("opencode")
        if not bin_:
            return None
        try:
            r = subprocess.run([bin_, "--version"], capture_output=True,
                               text=True, timeout=5)
            return ((r.stdout or "") + (r.stderr or "")).strip() or None
        except Exception:
            return None
    return None


def _config_hash(repo_root: Path) -> str | None:
    p = repo_root / "resources" / "orchestration-config.json"
    try:
        h = hashlib.sha256()
        with p.open("rb") as fh:
            h.update(fh.read())
        return h.hexdigest()
    except Exception:
        return None


def _dir_content_hash(paths: list[Path]) -> str | None:
    """Aggregate sha256 over (relpath + content) of every file under each path.
    A content fingerprint of the skill/agent manifest so 'same skill name,
    different content' — the hazard of discover-by-name — is detectable."""
    h = hashlib.sha256()
    found = False
    for base in paths:
        if not base or not base.exists():
            continue
        for f in sorted(base.rglob("*")):
            if not f.is_file():
                continue
            try:
                rel = str(f.relative_to(base))
                h.update(rel.encode())
                h.update(b"\0")
                h.update(f.read_bytes())
                h.update(b"\0")
                found = True
            except Exception:
                continue
    return h.hexdigest() if found else None


def _skill_fingerprint(repo_root: Path) -> str | None:
    return _dir_content_hash([repo_root / ".claude" / "skills"])


def _agent_fingerprint(repo_root: Path) -> str | None:
    return _dir_content_hash([repo_root / ".claude" / "agents"])


def _runtime_config(backend: str, repo_root: Path,
                    max_turns: int | None = None) -> RuntimeConfig:
    """Read user-controlled LLM knobs. The primary danger-value source is the
    project-root ``opencode.json`` (carries ``limit.output`` — the silent-
    truncation culprit); read it regardless of backend when present so the
    danger is surfaced even on the claude backend. ``max_turns`` (claude SDK
    option) is folded in when supplied by the caller."""
    rc_path = repo_root / "opencode.json"
    if rc_path.is_file():
        try:
            cfg = json.loads(rc_path.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
        if not isinstance(cfg, dict):
            cfg = {}
        model_full = cfg.get("model")            # e.g. "anthropic/GLM-5.2"
        model = model_full.split("/", 1)[-1] if isinstance(model_full, str) else None
        output_limit = context_limit = base_url = None
        providers = cfg.get("provider") or {}
        if isinstance(providers, dict):
            for pv in providers.values():
                if not isinstance(pv, dict):
                    continue
                opts = pv.get("options") or {}
                if isinstance(opts, dict) and opts.get("baseURL") and base_url is None:
                    base_url = opts.get("baseURL")
                models = pv.get("models") or {}
                if isinstance(models, dict) and model and model in models:
                    lim = (models[model] or {}).get("limit") or {}
                    output_limit = lim.get("output")
                    context_limit = lim.get("context")
        return RuntimeConfig(
            model=model, max_turns=max_turns,
            output_token_limit=output_limit,
            context_token_limit=context_limit, base_url=base_url,
            source="opencode.json")
    return RuntimeConfig(
        max_turns=max_turns,
        source="claude_sdk" if backend == "claude" else "unknown")


def _hostname() -> str | None:
    try:
        return socket.gethostname()
    except Exception:
        return None


def _driver_version() -> str | None:
    bin_ = shutil.which("npu-smi")
    if not bin_:
        return None
    try:
        r = subprocess.run([bin_, "info"], capture_output=True, text=True, timeout=8)
        out = (r.stdout or "") + (r.stderr or "")
    except Exception:
        return None
    m = re.search(r"Driver Version\s*[:]?\s*([0-9A-Za-z.\-]+)", out)
    return m.group(1) if m else None


def _npu_device_count() -> int | None:
    # step 104: no in-process torch_npu import (orchestrator main process stays
    # pure Python — docs/plan/dispatch-npu-probe-subprocess/). env declaration
    # first, then npu-smi subprocess count; None (unknown) stays None — this
    # recorder never invents a default.
    from ascendc_devkit.infra.npu_smi import env_device_count, npu_smi_device_count

    count = env_device_count()
    if count is not None:
        return count
    return npu_smi_device_count()


# soc_version translation lives in domain.chip (L4); infra (L7) cannot import
# it (§1.1 layering), so the CALLER translates chip→soc_version and passes it
# into build_provenance(soc_version=...).


def _danger_warnings(rc: RuntimeConfig, devkit_dirty: bool | None) -> list[str]:
    w: list[str] = []
    if (rc.output_token_limit is not None
            and rc.output_token_limit <= LOW_OUTPUT_TOKEN_THRESHOLD):
        w.append(
            f"runtime_config.output_token_limit={rc.output_token_limit} <= "
            f"{LOW_OUTPUT_TOKEN_THRESHOLD} — agent output very likely truncated; "
            f"raise limit.output in opencode.json (or model max_tokens)")
    if devkit_dirty:
        w.append(
            "devkit.git.dirty=true — run produced with uncommitted local changes; "
            "version identity is the commit + a private diff, not a clean release")
    return w


def _probe_cann_version() -> str | None:
    import os
    toolkit = os.environ.get("ASCEND_TOOLKIT_HOME")
    if toolkit:
        for part in Path(toolkit).parts:
            if part.startswith("cann-"):
                return part[len("cann-"):]
    return None


def _probe_python_version() -> str | None:
    import platform
    return platform.python_version()


def _probe_torch_npu_version() -> str | None:
    # step 104: read installed distribution metadata instead of importing
    # torch_npu (the import loads the CANN runtime into this process — the
    # F1/F3 corruption root). Semantic change (pinned by UT): reports the
    # INSTALLED version even when the import itself would be broken.
    try:
        from importlib.metadata import version
        return version("torch_npu")
    except Exception:
        return None


def _probe_compiler() -> str | None:
    return next((shutil.which(s) for s in ("ccec", "c++") if shutil.which(s)), None)


def _probe_environment(run_context, hostname: str | None,
                       soc_version: str | None = None) -> EnvironmentProvenance:
    """Independent env probe — infra MUST NOT import orchestration's run_context
    probe nor domain.chip (§1.1 layering: L7 cannot depend on L3/L4). Probes
    software / driver / hostname / device-count directly; detected_chip comes
    from ``run_context`` when supplied; ``soc_version`` is translated by the
    CALLER (a layer allowed to import domain.chip) and passed in."""
    cann = _probe_cann_version()
    python = _probe_python_version()
    torch = _probe_torch_npu_version()
    comp = _probe_compiler()
    chip = None
    if run_context is not None:
        se = getattr(run_context, "software_env", None)
        he = getattr(run_context, "hardware_env", None)
        if se is not None:
            cann = se.cann_version or cann
            python = se.python_version or python
            torch = se.torch_npu_version or torch
            comp = se.compiler or comp
        if he is not None:
            chip = he.detected_chip
    return EnvironmentProvenance(
        cann_version=cann, python_version=python,
        torch_npu_version=torch, compiler=comp,
        detected_chip=chip, soc_version=soc_version,
        driver_version=_driver_version(),
        npu_device_count=_npu_device_count(),
        hostname=hostname or _hostname(),
    )


# —— Single translation point ———————————————————————————————————————


def build_provenance(*, run_id: str, repo_root: Path,
                     agent_backend: str | None,
                     target_repo_baseline_ref: str = "",
                     run_context=None,
                     max_turns: int | None = None,
                     hostname: str | None = None,
                     soc_version: str | None = None) -> Provenance:
    """Assemble the full Provenance. Called once at run start (dispatcher).

    ``repo_root`` is the DevKit repo root (THIS repo) — where git identity and
    the skill/agent manifests live. ``target_repo_baseline_ref`` is the operator
    repo HEAD kept separately for disambiguation. ``run_context`` is the
    optional RunContext whose software/hardware probes feed the environment
    section (avoiding a re-probe). ``max_turns`` is the claude SDK option when
    known (folded into runtime_config).
    """
    repo_root = Path(repo_root)
    git = _git(repo_root)
    runtime_config = _runtime_config(agent_backend or "", repo_root, max_turns=max_turns)
    return Provenance(
        run_id=run_id,
        built_at=datetime.now(timezone.utc).isoformat(),
        devkit=DevkitProvenance(version=_devkit_version(), git=git),
        orchestration=OrchestrationProvenance(
            agent_backend=agent_backend,
            backend_sdk_version=_backend_sdk_version(agent_backend or ""),
            orchestration_config_hash=_config_hash(repo_root),
            skill_manifest_fingerprint=_skill_fingerprint(repo_root),
            agent_manifest_fingerprint=_agent_fingerprint(repo_root),
        ),
        runtime_config=runtime_config,
        environment=_probe_environment(run_context, hostname, soc_version=soc_version),
        target_repo_baseline_ref=target_repo_baseline_ref,
        warnings=_danger_warnings(runtime_config, git.dirty),
    )


# —— Output helpers ————————————————————————————————————————————————


def write_provenance(run_dir: Path, provenance: Provenance) -> Path:
    """Write <run>/PROVENANCE.json (immutable record)."""
    path = Path(run_dir) / "PROVENANCE.json"
    path.write_text(
        json.dumps(provenance.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8")
    return path


def summary_one_line(p: Provenance) -> str:
    """One-line human glance for the report header."""
    g = p.devkit.git
    parts = [f"devkit={g.commit_short or 'unknown'}" + ("*dirty" if g.dirty else "")]
    if p.orchestration.agent_backend:
        parts.append(f"backend={p.orchestration.agent_backend}")
    if p.environment.cann_version:
        parts.append(f"cann={p.environment.cann_version}")
    if p.environment.detected_chip:
        parts.append(f"chip={p.environment.detected_chip}")
    if p.runtime_config.output_token_limit is not None:
        parts.append(f"output_limit={p.runtime_config.output_token_limit}")
    if p.target_repo_baseline_ref:
        parts.append(f"target_repo={p.target_repo_baseline_ref[:12]}")
    return " | ".join(parts)


def summary_from_dict(d: dict) -> str:
    """One-line summary from a serialized provenance dict (PROVENANCE.json) —
    lets Report.generate render the header without rebuilding a Provenance."""
    g = ((d.get("devkit") or {}).get("git") or {})
    orch = d.get("orchestration") or {}
    env = d.get("environment") or {}
    rc = d.get("runtime_config") or {}
    parts = [f"devkit={g.get('commit_short') or 'unknown'}"
             + ("*dirty" if g.get("dirty") else "")]
    if orch.get("agent_backend"):
        parts.append(f"backend={orch['agent_backend']}")
    if env.get("cann_version"):
        parts.append(f"cann={env['cann_version']}")
    if env.get("detected_chip"):
        parts.append(f"chip={env['detected_chip']}")
    if rc.get("output_token_limit") is not None:
        parts.append(f"output_limit={rc['output_token_limit']}")
    if d.get("target_repo_baseline_ref"):
        parts.append(f"target_repo={str(d['target_repo_baseline_ref'])[:12]}")
    return " | ".join(parts)


def diff_provenance(first: dict, resume: dict) -> dict:
    """Diff a first-run PROVENANCE dict against a re-probed resume provenance
    (bug1, step-68). Returns a ``{<axis>_changed: True, <axis>: {old, new}}``
    dict — one entry per axis that DRIFTED between the runs — so a reviewer
    scanning the ``run_resumed`` event sees exactly what moved, not a full
    re-dump.

    The five axes cover the realistic between-runs drift: a DevKit commit
    upgrade (operator pulled mid-run), an agent-backend switch, an
    output-token-limit config change (the silent-truncation danger), a skill
    manifest content change (same-name-different-content), and the environment
    (CANN / torch_npu / driver / chip bump). Stable identity axes (run_id,
    built_at) are intentionally not diffed: ``built_at`` always differs and
    carries no diagnostic value.

    Both inputs are serialized dicts (``Provenance.to_dict()`` or a
    PROVENANCE.json load). A non-dict input returns ``{}`` (caller degrades to
    "no diff recorded" rather than crashing the resume)."""
    if not isinstance(first, dict) or not isinstance(resume, dict):
        return {}
    changes: dict = {}

    def _maybe(axis_label: str, old, new) -> None:
        if old != new:
            changes[axis_label + "_changed"] = True
            changes[axis_label] = {"old": old, "new": new}

    _maybe("commit",
           ((first.get("devkit") or {}).get("git") or {}).get("commit"),
           ((resume.get("devkit") or {}).get("git") or {}).get("commit"))
    _maybe("backend",
           (first.get("orchestration") or {}).get("agent_backend"),
           (resume.get("orchestration") or {}).get("agent_backend"))
    _maybe("output_limit",
           (first.get("runtime_config") or {}).get("output_token_limit"),
           (resume.get("runtime_config") or {}).get("output_token_limit"))
    _maybe("skill_fingerprint",
           (first.get("orchestration") or {}).get("skill_manifest_fingerprint"),
           (resume.get("orchestration") or {}).get("skill_manifest_fingerprint"))
    _maybe("environment",
           first.get("environment") or {},
           resume.get("environment") or {})
    return changes
