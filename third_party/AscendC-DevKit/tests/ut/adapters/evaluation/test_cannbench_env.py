"""UT for cannbench_env — the shared cann-bench environment assembly.

Guards the namespace-shadowing root-fix (step-82 analysis fact 1): cann-bench's
src-layout nested packages (``src/cann_bench_utils/cann_bench_utils/``) must have
their outer project dir on PYTHONPATH BEFORE ``src/``, or ``import
cann_bench_utils`` resolves to a namespace package → ImportError on
``cann_bench_warmup`` (the scatter_pa_kv_cache all-zero failure).

Also pins the kernel_eval subprocess env invariants previously tested via the
stage (autoload=0, PYTHONPATH composition, ASCEND_CUSTOM_OPP_PATH, LD) — now that
assembly lives here, the invariants are guarded at their new home (§3.1 TDD).
"""

import os
from pathlib import Path

from ascendc_devkit.adapters.evaluation.cannbench_env import (
    build_kernel_eval_env,
    cann_lib_paths,
    cannbench_src_layout_paths,
    resolve_cann_bench_pkg_root,
)


def _make_cannbench_src(repo: Path) -> None:
    """Build a cann-bench-like src/ tree: flat kernel_eval + nested cann_bench_utils."""
    src = repo / "src"
    # flat package: src/kernel_eval/__init__.py
    (src / "kernel_eval").mkdir(parents=True)
    (src / "kernel_eval" / "__init__.py").write_text("")
    # src-layout nested: src/cann_bench_utils/cann_bench_utils/__init__.py
    # (outer src/cann_bench_utils/ has NO __init__.py → namespace package if src/ alone)
    nested = src / "cann_bench_utils" / "cann_bench_utils"
    nested.mkdir(parents=True)
    (nested / "__init__.py").write_text("def cann_bench_warmup(*a, **k): ...\n")


class TestCannbenchSrcLayoutPaths:
    """src-layout scan: nested project dirs BEFORE src/ (the root-fix)."""

    def test_nested_before_src(self, tmp_path):
        repo = tmp_path / "repo"
        _make_cannbench_src(repo)
        paths = cannbench_src_layout_paths(repo)
        # both the nested project dir and src/ are present...
        assert str(repo / "src" / "cann_bench_utils") in paths
        assert str(repo / "src") in paths
        # ...and nested comes BEFORE src/ (load-bearing ordering)
        assert paths.index(str(repo / "src" / "cann_bench_utils")) < paths.index(
            str(repo / "src")
        )

    def test_flat_package_does_not_double_add(self, tmp_path):
        """kernel_eval is flat (src/kernel_eval/__init__.py) → not a nested entry;
        only src/ covers it."""
        repo = tmp_path / "repo"
        _make_cannbench_src(repo)
        paths = cannbench_src_layout_paths(repo)
        # src/kernel_eval/ is NOT separately added (it's flat, src/ covers it)
        assert str(repo / "src" / "kernel_eval") not in paths

    def test_no_src_returns_empty(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        assert cannbench_src_layout_paths(repo) == []

    def test_pure_flat_repo(self, tmp_path):
        """Repo with only flat packages → just [src/]."""
        repo = tmp_path / "repo"
        (repo / "src" / "kernel_eval").mkdir(parents=True)
        (repo / "src" / "kernel_eval" / "__init__.py").write_text("")
        assert cannbench_src_layout_paths(repo) == [str(repo / "src")]

    def test_multiple_nested_packages_all_covered(self, tmp_path):
        """cann-bench adding a new src-layout sub-package (e.g. auto_pipeline) is
        auto-covered without code change (§1.2 可扩展)."""
        repo = tmp_path / "repo"
        src = repo / "src"
        for proj in ("cann_bench_utils", "auto_pipeline"):
            inner = src / proj / proj
            inner.mkdir(parents=True)
            (inner / "__init__.py").write_text("")
        paths = cannbench_src_layout_paths(repo)
        assert str(src / "cann_bench_utils") in paths
        assert str(src / "auto_pipeline") in paths
        assert str(src) in paths  # flat fallback always last


class TestResolveCannBenchPkgRoot:
    """Operator package discovery — moved here from the stage."""

    def test_resolves_example_root_containing_cann_bench(self, tmp_path):
        repo = tmp_path / "repo"
        example = repo / "examples" / "aclnn_launch_example"
        (example / "cann_bench").mkdir(parents=True)
        src_dir = example / "csrc" / "ops" / "exp"
        src_dir.mkdir(parents=True)
        assert resolve_cann_bench_pkg_root(src_dir, repo) == example.resolve()

    def test_returns_none_when_no_cann_bench_ancestor(self, tmp_path):
        repo = tmp_path / "repo"
        src_dir = repo / "csrc" / "ops" / "exp"
        src_dir.mkdir(parents=True)
        assert resolve_cann_bench_pkg_root(src_dir, repo) is None

    def test_does_not_escape_repo_root(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        outside = tmp_path / "elsewhere"
        (outside / "cann_bench").mkdir(parents=True)
        assert resolve_cann_bench_pkg_root(outside, repo) is None


class TestCannLibPaths:
    """Single-source CANN lib resolution (dedup of runner.py)."""

    def test_returns_list_str(self):
        paths = cann_lib_paths()
        assert isinstance(paths, list)
        assert all(isinstance(p, str) for p in paths)

    def test_only_existing_dirs(self, tmp_path, monkeypatch):
        """Only existing lib dirs are returned (no phantom paths)."""
        arch = os.uname().machine
        ascend = tmp_path / "ascend"
        (ascend / f"{arch}-linux" / "lib64").mkdir(parents=True)  # exists
        # asc/lib64 NOT created → must be absent
        monkeypatch.setenv("ASCEND_HOME_PATH", str(ascend))
        paths = cann_lib_paths()
        assert str(ascend / f"{arch}-linux" / "lib64") in paths
        assert str(ascend / f"{arch}-linux" / "asc" / "lib64") not in paths


class TestBuildKernelEvalEnv:
    """kernel_eval subprocess env — all invariants at their new home."""

    def test_autoload_forced_zero_even_when_parent_overrides(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TORCH_DEVICE_BACKEND_AUTOLOAD", "1")
        repo = tmp_path / "repo"
        _make_cannbench_src(repo)
        env = build_kernel_eval_env(repo, repo)
        assert env["TORCH_DEVICE_BACKEND_AUTOLOAD"] == "0"

    def test_pythonpath_nested_before_src(self, tmp_path, monkeypatch):
        """THE root-fix: src/cann_bench_utils/ must precede src/ on PYTHONPATH."""
        monkeypatch.delenv("PYTHONPATH", raising=False)
        repo = tmp_path / "repo"
        _make_cannbench_src(repo)
        env = build_kernel_eval_env(repo, repo)
        parts = env["PYTHONPATH"].split(":")
        assert str(repo / "src" / "cann_bench_utils") in parts
        assert str(repo / "src") in parts
        assert parts.index(str(repo / "src" / "cann_bench_utils")) < parts.index(
            str(repo / "src")
        )

    def test_pythonpath_usercustomize_first(self, tmp_path, monkeypatch):
        """usercustomize dir leads PYTHONPATH (startup torch_npu preload)."""
        monkeypatch.delenv("PYTHONPATH", raising=False)
        repo = tmp_path / "repo"
        _make_cannbench_src(repo)
        ucd = str(tmp_path / "uc")
        env = build_kernel_eval_env(repo, repo, usercustomize_dir=ucd)
        assert env["PYTHONPATH"].split(":")[0] == ucd

    def test_pythonpath_includes_per_op_and_pkg_root(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PYTHONPATH", raising=False)
        repo = tmp_path / "repo"
        example = repo / "examples" / "aclnn_launch_example"
        (example / "cann_bench").mkdir(parents=True)
        src_dir = example / "csrc" / "ops" / "exp"
        per_op = str(tmp_path / "perop_py")
        env = build_kernel_eval_env(repo, src_dir, per_op_python=per_op)
        parts = env["PYTHONPATH"].split(":")
        assert per_op in parts
        assert str(example.resolve()) in parts
        # Source wrapper version must lead per-op python: a converge-rollback can
        # install a stale cann_bench (missing the current wrapper) into per-op
        # python, which would shadow the adapted source package and empty the
        # scan (operators=[] discovery-broken, batch 20260805_183550).
        assert parts.index(str(example.resolve())) < parts.index(per_op)

    def test_ascend_custom_opp_path(self, tmp_path):
        repo = tmp_path / "repo"
        _make_cannbench_src(repo)
        opp = str(tmp_path / "perop_opp")
        env = build_kernel_eval_env(repo, repo, per_op_opp=opp)
        assert env["ASCEND_CUSTOM_OPP_PATH"] == f"{opp}/vendors/custom_ops"

    def test_ld_includes_deploy_and_cann_libs(self, tmp_path, monkeypatch):
        monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)
        repo = tmp_path / "repo"
        _make_cannbench_src(repo)
        deploy_ld = str(tmp_path / "deploy_ld")
        env = build_kernel_eval_env(repo, repo, deploy_ld=deploy_ld)
        parts = env["LD_LIBRARY_PATH"].split(":")
        assert parts[0] == deploy_ld  # deploy ld leads

    def test_ld_includes_per_op_opapi_lib(self, tmp_path, monkeypatch):
        """Regression guard: per-op op_api/lib must be in LD_LIBRARY_PATH for
        libcust_opapi.so to be found at runtime (fixes 507035 eval crash)."""
        monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)
        repo = tmp_path / "repo"
        _make_cannbench_src(repo)
        per_op_opp = str(tmp_path / "perop_opp")
        env = build_kernel_eval_env(repo, repo, per_op_opp=per_op_opp)
        parts = env["LD_LIBRARY_PATH"].split(":")
        expected = f"{per_op_opp}/vendors/custom_ops/op_api/lib"
        assert expected in parts, f"Expected {expected} in LD_LIBRARY_PATH"
        assert parts[0] == expected, "per-op op_api/lib should be first (highest priority)"

    def test_ld_per_op_opapi_before_deploy_ld(self, tmp_path, monkeypatch):
        """per-op op_api/lib leads deploy_ld (per-op overrides global)."""
        monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)
        repo = tmp_path / "repo"
        _make_cannbench_src(repo)
        per_op_opp = str(tmp_path / "perop_opp")
        deploy_ld = str(tmp_path / "deploy_ld")
        env = build_kernel_eval_env(repo, repo, per_op_opp=per_op_opp, deploy_ld=deploy_ld)
        parts = env["LD_LIBRARY_PATH"].split(":")
        expected_opapi = f"{per_op_opp}/vendors/custom_ops/op_api/lib"
        assert parts[0] == expected_opapi
        assert parts[1] == deploy_ld

    def test_no_empty_pythonpath_segments(self, tmp_path, monkeypatch):
        """Unresolvable cann_bench pkg root → no empty/None segments leak in."""
        monkeypatch.delenv("PYTHONPATH", raising=False)
        repo = tmp_path / "repo"
        _make_cannbench_src(repo)
        env = build_kernel_eval_env(repo, repo)  # no cann_bench/ ancestor
        assert "" not in env["PYTHONPATH"].split(":")
