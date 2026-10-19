"""L6 Adapters — cann-bench environment assembly (shared, single source).

cann-bench kernel_eval runs as a subprocess that must resolve cann-bench's own
tool modules (``kernel_eval``, ``cann_bench_utils``) plus the per-op cann_bench
operator package. The env to make all three importable used to be assembled
inline in ``CannbenchEvalStage`` (stage layer) AND duplicated in
``adapters/npu/runner.py`` — they drifted, and the stage copy missed cann-bench's
src-layout, causing the namespace-package shadowing that zeroed scatter_pa_kv_cache
(batch 20260728_214817; see step-82 analysis fact 1).

This module is the single authority for that env. ``CannbenchScorer`` and the
NPURunner path both reach for it; the stage layer never assembles cann-bench env
itself (§1.6 business layer holds the adapter, not the mechanism; §2.5 single path).

Non-intrusive: sets env vars only, never modifies cann-bench code.
"""

from __future__ import annotations

import os
from pathlib import Path


def cann_lib_paths() -> list[str]:
    """Resolve CANN system library paths needed by any deployed .so.

    Single source (was duplicated byte-for-byte in runner.py:461-477 and the old
    cannbench_eval.py:495-510). Used by both the kernel_eval subprocess env and
    the NPURunner harness env.
    """
    paths: list[str] = []
    ascend_home = os.environ.get(
        "ASCEND_HOME_PATH",
        os.environ.get("ASCEND_HOME", "/usr/local/Ascend"),
    )
    arch = os.uname().machine
    toolkit_lib = Path(ascend_home) / f"{arch}-linux" / "lib64"
    if toolkit_lib.is_dir():
        paths.append(str(toolkit_lib))
    asc_lib = Path(ascend_home) / f"{arch}-linux" / "asc" / "lib64"
    if asc_lib.is_dir():
        paths.append(str(asc_lib))
    return paths


def cannbench_src_layout_paths(repo_root: Path) -> list[str]:
    """All PYTHONPATH entries needed to import cann-bench's ``src/`` packages.

    cann-bench mixes two layouts under ``src/``:

      - **flat**: ``src/<pkg>/__init__.py`` (e.g. ``kernel_eval``) — importable
        with just ``src/`` on the path.
      - **src-layout nested**: ``src/<proj>/<pkg>/__init__.py`` where the outer
        ``<proj>`` dir has NO ``__init__.py`` (e.g.
        ``src/cann_bench_utils/cann_bench_utils/__init__.py``) — importable only
        with ``src/<proj>/`` on the path.

    The bug: putting only ``src/`` on PYTHONPATH makes the nested case resolve
    ``cann_bench_utils`` to the outer ``src/cann_bench_utils/`` dir — a namespace
    package ("unknown location") with no ``cann_bench_warmup`` → ImportError in
    kernel_eval's ``perf_eval.py:237``.

    Fix: put each nested ``src/<proj>/`` dir BEFORE ``src/`` so ``import <pkg>``
    hits the real inner package first; ``src/`` stays for flat packages. Ordering
    is load-bearing (nested-first, src-last).

    Robust to cann-bench adding new src-layout sub-packages (§1.2 可扩展) — scans
    ``src/`` rather than hardcoding a package list. Returns ``[]`` when there is
    no ``src/``.
    """
    src_dir = repo_root / "src"
    if not src_dir.is_dir():
        return []
    nested: list[str] = []
    for child in sorted(src_dir.iterdir()):
        if not child.is_dir():
            continue
        # src-layout nested: src/<proj>/<proj>/__init__.py
        if (child / child.name / "__init__.py").is_file():
            nested.append(str(child))
    # nested project dirs first (shadow src/'s namespace view), then src/ for flat
    return nested + [str(src_dir)]


def resolve_cann_bench_pkg_root(source_dir: Path, repo_root: Path) -> Path | None:
    """Directory holding the ``cann_bench`` Python operator package (examples/<ex>/).

    cann-bench places its operator package under each example root, not at the
    repository top level nor in ``src/``. ``scan_interfaces()`` imports
    ``cann_bench`` directly; the eval subprocess runs with cwd=repo_root, so this
    directory MUST be on PYTHONPATH or the import fails. Walk up from
    ``source_dir`` to the nearest ancestor within ``repo_root`` that contains a
    ``cann_bench/`` subdir. Returns None if unresolvable or if ``source_dir``
    escapes ``repo_root`` (never guesses a path).
    """
    try:
        root = repo_root.resolve()
        cur = source_dir.resolve()
    except OSError:
        return None
    while root == cur or root in cur.parents:
        if (cur / "cann_bench").is_dir():
            return cur
        if root == cur:
            break
        cur = cur.parent
    return None


def build_kernel_eval_env(
    repo_root: Path,
    source_dir: Path,
    per_op_python: str = "",
    per_op_opp: str = "",
    deploy_ld: str = "",
    usercustomize_dir: str = "",
) -> dict:
    """Assemble the env dict for the ``python -m kernel_eval.cli`` subprocess.

    This is the kernel_eval subprocess's complete environment (cann-bench adapter
    boundary). The caller owns the ``usercustomize`` temp dir lifecycle (create
    the ``usercustomize.py`` that force-imports torch_npu, pass its dir here, and
    clean up in its own try/finally) — env assembly never touches the filesystem
    beyond reading env vars, so it stays side-effect-free and testable.

    Invariants pinned by tests/ut/orchestration/test_cannbench_eval.py ( autoload,
    PYTHONPATH, card→device-id) must survive any change here.
    """
    ascend_opp = os.environ.get(
        "ASCEND_OPP_PATH",
        os.environ.get("ASCEND_HOME_PATH", "/usr/local/Ascend") + "/opp",
    )

    env = os.environ.copy()
    # kernel_eval's Evaluator imports torch_npu at init; some torch_npu versions
    # don't self-disable device-backend autoload before `import torch`, registering
    # npu twice → RuntimeError "Two accelerators ... npu and npu" (20260709-094500).
    # autoload=0 is torch_npu's official recommendation. Force-override (NOT
    # setdefault): whatever the parent set, the subprocess MUST turn autoload off.
    env["TORCH_DEVICE_BACKEND_AUTOLOAD"] = "0"

    # PYTHONPATH: usercustomize (startup torch_npu preload) → cann_bench operator
    # package root (source wrapper version — FIRST so converge-rollback can't
    # shadow it with a stale deploy copy) → cann-bench src-layout (nested-first
    # to kill namespace shadowing) → per-op python → inherited PYTHONPATH.
    pypath_parts: list[str] = []
    if usercustomize_dir:
        pypath_parts.append(usercustomize_dir)
    cann_bench_pkg_root = resolve_cann_bench_pkg_root(source_dir, repo_root)
    if cann_bench_pkg_root:
        pypath_parts.append(str(cann_bench_pkg_root))
    pypath_parts.extend(cannbench_src_layout_paths(repo_root))
    if per_op_python:
        pypath_parts.append(per_op_python)
    existing_pypath = env.get("PYTHONPATH", "")
    if existing_pypath:
        pypath_parts.append(existing_pypath)
    env["PYTHONPATH"] = ":".join(pypath_parts)

    if per_op_opp:
        # step-108: 值形态单源（vendor 级由 env_contract 拼出，§1.15）
        from ascendc_devkit.infra.env_contract import expected_ascend_custom_opp
        env["ASCEND_CUSTOM_OPP_PATH"] = expected_ascend_custom_opp(per_op_opp)
    env["ASCEND_OPP_PATH"] = ascend_opp

    # CANN system lib paths so the per-op _C.abi3.so resolves libopapi/libascendcl.
    # Also add per-op libcust_opapi.so so ACLNN APIs can be found at runtime.
    ld_parts: list[str] = []
    if per_op_opp:
        ld_parts.append(f"{per_op_opp}/vendors/custom_ops/op_api/lib")
    if deploy_ld:
        ld_parts.append(deploy_ld)
    ld_parts.extend(cann_lib_paths())
    existing_ld = env.get("LD_LIBRARY_PATH", "")
    if existing_ld:
        ld_parts.append(existing_ld)
    env["LD_LIBRARY_PATH"] = ":".join(ld_parts)

    return env
