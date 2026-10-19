"""pytest configuration for AscendC DevKit tests.

Default mode runs the FULL real environment (LLM + NPU + CANN). This is
deliberate: silently stubbing on every missing dependency hides real errors,
so the default lane exercises real backends and fails loudly. When a required
environment (network/LLM, NPU, or CANN) is unavailable, the pre-check reports
which one is missing and asks the user whether to continue anyway (non-TTY/CI
aborts by default).

Developers who want a fast inner loop opt OUT explicitly:
    pytest --quick           # exclude llm/npu/slow/cann, skip env pre-check
    pytest -m "not llm"      # custom marker selection (honoured as-is)
    pytest --no-env-check    # run full set but skip the env pre-check

Other options: --ut / --st for directory filtering.
"""

from pathlib import Path
import os

import pytest


# ---------------------------------------------------------------------------
# torch_npu autoload guard (must precede any `import torch` in this session)
# ---------------------------------------------------------------------------
# With torch + torch_npu installed in the conflicting combo, the FIRST
# `import torch` triggers device-backend auto-loading → 'npu and npu' conflict
# → RuntimeError. That first import happens in the NPU env-check probe
# (_probe_npu → _check_torch_npu), so plain `pytest` INTERNALERROR-crashes for
# anyone in this state unless they know to export TORCH_DEVICE_BACKEND_AUTOLOAD=0.
# Bake it in here (setdefault = an explicit export is still honoured) so plain
# `pytest` just works. torch_npu functionality comes from explicit
# `import torch_npu` (autoload-independent); DevKit applies the same guard in its
# cannbench/deploy/e2e scripts. See memory: torch-npu-autoload-conflict.
os.environ.setdefault("TORCH_DEVICE_BACKEND_AUTOLOAD", "0")

# ---------------------------------------------------------------------------
# step 104：编排主进程纯 Python 守卫 —— pytest 宿主上下文豁免（逃生门）
# ---------------------------------------------------------------------------
# 生产语义：dispatch() 入口安装 import 守卫，torch_npu 已预载即抛（fail-fast）。
# pytest 宿主不适用该语义：本会话有插件在启动期预载 torch_npu（与被测代码
# 无关，见 tests/ut/infra/test_import_guard.py 的同类处理），真跑 dispatch 的
# 用例会因此误炸。守卫自身的双分支语义由 test_import_guard.py 显式覆盖
# （该文件会摘除此 env），生产不变式不受本豁免影响。
os.environ.setdefault("DEVKIT_ALLOW_INPROC_TORCH", "1")


# ---------------------------------------------------------------------------
# cann-bench parity 用例前置：把 cann-bench/src 挂进 sys.path（§3.7 诚实补全）
# ---------------------------------------------------------------------------
# ``TestParityCannBench``（ut/adapters/test_precision_compare.py）对拍 cann-bench
# 真实 ``kernel_eval``，需 ``cann-bench/src`` 可导入（等同 ``PYTHONPATH=<cann-bench>/src``，
# 且 ``TORCH_DEVICE_BACKEND_AUTOLOAD=0`` 已在上方 setdefault）。默认 pytest 不配
# PYTHONPATH → 该套件整组 skipif（全量 UT 的 11 个 skipped 全在此，观感"多"实为同类）。
# 此处按单一解析路径（tests._testrepos.resolve_test_repo：env → 本地配置 → 兄弟目录，
# §2.5 唯一通路，不另造路径逻辑）解析 cann-bench，可用则把 ``src/`` 挂进 ``sys.path``
# → parity 用例默认真跑（确定性 UT，0.2s，无 LLM/NPU/CANN）。解析不到 → 保持原样，
# 用例按 skipif 诚实 skip（外部参考仓缺失是可选前置，§3.7）。
def _mount_cannbench_src() -> None:
    try:
        from tests._testrepos import resolve_test_repo
    except Exception:  # noqa: BLE001 — resolution is best-effort, never blocks
        return
    try:
        repo = resolve_test_repo("ASCENDC_TEST_CANN_BENCH", "cann-bench")
    except Exception:  # noqa: BLE001
        return
    if repo is None:
        return
    src = repo / "src"
    if not src.is_dir():
        return
    import sys
    src_str = str(src)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)


_mount_cannbench_src()


# ---------------------------------------------------------------------------
# Per-test cleanup of thread-local run-log binding (log_capture)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _unbind_run_log_after_each_test():
    """dispatch() binds a thread-local run.log handle (Logger._emit mirrors
    console output into it). pytest runs tests sequentially in the main thread,
    so a binding left open by one test leaks into the next and diverts its
    Logger output — e.g. test_resume_cli's CliRunner ``result.output`` comes
    back empty in full-suite runs (the "不一致" message goes to the stale
    run.log instead of the captured stream). Unbind after each test to close
    the current thread's handle. Idempotent no-op when nothing is bound.

    (P-BC1: the binding is now thread-local, not the retired process-global
    ``_Tee`` on ``sys.stderr``; the per-test teardown need is unchanged because
    sequential tests share the main thread.)"""
    yield
    from ascendc_devkit.infra.log_capture import unbind_run_log
    unbind_run_log()


# ---------------------------------------------------------------------------
# 1. Custom options
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    parser.addoption("--quick", action="store_true", default=False,
                     help="Fast dev lane: exclude llm/npu/slow/cann and skip "
                          "the env pre-check")
    parser.addoption("--st", action="store_true", default=False,
                     help="Only collect tests/st/")
    parser.addoption("--ut", action="store_true", default=False,
                     help="Only collect tests/ut/")
    parser.addoption("--no-env-check", action="store_true", default=False,
                     help="Skip LLM/NPU/CANN environment pre-check")


# ---------------------------------------------------------------------------
# 2. Directory filtering (collection-level)
# ---------------------------------------------------------------------------

def pytest_ignore_collect(collection_path, config):
    """--st/--ut directory filter: skip collection at the path level."""
    path_str = str(collection_path)
    if config.getoption("--st") and "st" not in Path(path_str).parts:
        return True
    if config.getoption("--ut") and "ut" not in Path(path_str).parts:
        return True
    return None


# ---------------------------------------------------------------------------
# 3. Marker filtering
# ---------------------------------------------------------------------------

_QUICK_EXCLUDE = "not llm and not slow and not npu and not cann and not external_repo"


def pytest_collection_modifyitems(config, items):
    """Default runs everything (full real environment). --quick switches to the
    fast lane (exclude external-dependency markers). An explicit -m is always
    honoured as-is and overrides both."""
    # External reference repos: surface missing ones (banner) and, in a TTY,
    # interactively prompt the user to configure them once (persisted to
    # tests/.testrepos.local.json — no env var needed). Precise — only when
    # collected items actually need a missing repo. Skipped under --quick.
    if not config.getoption("--quick"):
        _handle_external_repos(items)

    # User passed -m explicitly → respect their choice, don't overlay defaults.
    if config.getoption("-m", None):
        return
    if config.getoption("--quick"):
        config.option.markexpr = _QUICK_EXCLUDE
        return
    # §3.11 default: ``pytest`` = UT 全量 + 非 heavy_llm 的 ST + 预检. heavy_llm is
    # EXCLUDED from the default run (minutes-level runtime + token cost; needs
    # explicit user confirmation per §3.11 before execution). Opt in with
    # ``-m heavy_llm`` (or any explicit ``-m``, which short-circuits above).
    config.option.markexpr = "not heavy_llm"


# ---------------------------------------------------------------------------
# 4. Environment pre-check (LLM / NPU / CANN)
# ---------------------------------------------------------------------------

def pytest_configure(config):
    """Pre-check the real environment before collection.

    For each capability that the selected tests may exercise, verify it is
    available. If any are missing, report them together and ask the user
    whether to continue (non-TTY/CI aborts). --quick / --no-env-check /
    --collect-only skip the pre-check entirely.
    """
    if (config.getoption("--quick")
            or config.getoption("--no-env-check")
            or config.getoption("--collect-only")):
        return

    missing: list[str] = []
    if _may_need_llm(config):
        ok, detail = _probe_llm()
        print(f"[pre-check] LLM: {'OK' if ok else 'FAIL'} — {detail}")
        if not ok:
            missing.append(f"LLM ({detail})")
    if _may_need_npu(config):
        ok, detail = _probe_npu()
        print(f"[pre-check] NPU: {'OK' if ok else 'FAIL'} — {detail}")
        if not ok:
            missing.append(f"NPU ({detail})")
    if _may_need_cann(config):
        ok, detail = _probe_cann()
        print(f"[pre-check] CANN: {'OK' if ok else 'FAIL'} — {detail}")
        if not ok:
            missing.append(f"CANN ({detail})")

    # External reference repos (cann-bench/ops-nn) are NOT probed here: their
    # handling (banner + interactive prompt) runs in pytest_collection_modifyitems,
    # which is precise (only when collected items need a missing repo) and can
    # set env vars seen by the fixtures that run after. They never abort —
    # unlike LLM/NPU/CANN, which the default full suite requires.

    if missing:
        _decide_on_missing_env(missing)


# —— capability-selection predicates ————————————————————————————————

def _marker_selected(config, marker: str) -> bool:
    """True when the selected set may include tests carrying *marker*.

    Default (no -m, no --quick) selects everything → True.
    Explicit -m → only when the expression includes (and doesn't negate) it.
    --quick excludes all external markers → False.
    """
    if config.getoption("--quick"):
        return False
    markexpr = config.getoption("-m", None) or ""
    if markexpr:
        return marker in markexpr and f"not {marker}" not in markexpr
    return True  # default full run


def _may_need_llm(config) -> bool:
    if not _marker_selected(config, "llm"):
        return False
    # --ut carries no @llm tests; --st and default may.
    return not config.getoption("--ut")


def _may_need_npu(config) -> bool:
    if not _marker_selected(config, "npu"):
        return False
    return not config.getoption("--ut")


def _may_need_cann(config) -> bool:
    if not _marker_selected(config, "cann"):
        return False
    return not config.getoption("--ut")


# —— probes (return (ok, detail)) ————————————————————————————————————

def _probe_llm() -> tuple[bool, str]:
    from tests._llm_env import llm_precheck
    return llm_precheck()


def _probe_npu() -> tuple[bool, str]:
    from ascendc_devkit.cli.commands.verify_env import (
        _check_torch_npu, _check_npu_driver, _check_npu_device,
    )
    for fn in (_check_torch_npu, _check_npu_driver, _check_npu_device):
        result = fn()
        if not result.passed:
            return False, result.detail
    return True, "torch_npu + driver + device available"


def _probe_cann() -> tuple[bool, str]:
    """Strict CANN check: a CANN compiler (ccec / bishengir-compile / asc_opc)
    must be on PATH (not merely ASCEND_TOOLKIT_HOME set). Reuses the same
    diagnostic the runtime emits."""
    from ascendc_devkit.adapters.toolchain.cann import CANNToolchain
    tc = CANNToolchain()
    return tc.is_available, tc.diagnostic_hint()


# External reference operator-repos used as integration subjects (§1.7: not
# vendored in this project). Each entry: (repo_name, env_var). Resolution
# (env var → sibling dir → None) is delegated to tests._testrepos.resolve_test_repo
# so it stays single-source — never reimplement path logic here.
_EXTERNAL_REPOS: list[tuple[str, str]] = [
    ("cann-bench", "ASCENDC_TEST_CANN_BENCH"),
    ("ops-nn", "ASCENDC_TEST_OPS_NN"),
]


def _probe_external_repos() -> list[tuple[str, str, bool, str]]:
    """Probe each external reference repo via the single resolution path.

    Returns [(name, env_var, available, detail)] per repo. ``detail`` distinguishes
    available / set-but-not-a-dir / not-set for honest messaging (§3.7). Runs at
    configure time, BEFORE collection, so it reports availability only — not how
    many tests skip (the dependent tests' pytest.skip() reason already states that;
    the banner just makes the aggregate visible).
    """
    import os
    from tests._testrepos import resolve_test_repo

    results: list[tuple[str, str, bool, str]] = []
    for name, env_var in _EXTERNAL_REPOS:
        explicit = os.environ.get(env_var)
        available = resolve_test_repo(env_var, name) is not None
        if available:
            detail = explicit or f"sibling ./{name}"
        elif explicit:
            detail = f"{env_var}={explicit} 不是目录"
        else:
            detail = (f"未配置 — set {env_var}=<path>,"
                      f"或把 {name}/ 放成本仓兄弟目录")
        results.append((name, env_var, available, detail))
    return results


# —— external-repo banner + interactive prompt (post-collection) ——————————

def _handle_external_repos(items) -> None:
    """Banner + interactive prompt for external reference repos.

    Scans collected items for ``@pytest.mark.external_repo("<repo>")`` (the repo
    name is the first marker arg), probes each dependent repo, prints an honest
    banner, and — in a TTY — prompts the user to supply a path for each MISSING
    repo. Answers apply to this run (``os.environ``) and optionally persist to
    ``tests/.testrepos.local.json`` so later runs auto-resolve with no env var
    and no re-prompt. Non-TTY: banner only (dependent tests skip honestly, §3.7).

    Why post-collection (not ``pytest_configure``): we act only when collected
    items actually need a missing repo, so a plain UT run is never prompted; and
    env vars set here are visible to the fixtures (``resolve_test_repo``) that
    run next.
    """
    import sys

    # repo_name → count of collected items needing it
    deps: dict[str, int] = {}
    for item in items:
        marker = item.get_closest_marker("external_repo")
        if not marker or not marker.args:
            continue
        repo = marker.args[0]
        deps[repo] = deps.get(repo, 0) + 1
    if not deps:
        return  # no external_repo tests collected this run → leave the user alone

    tty = sys.stdin.isatty()
    for name, _env_var, available, detail in _probe_external_repos():
        if name not in deps:
            continue
        tag = "OK" if available else "MISSING (optional)"
        print(f"[pre-check] {name} repo: {tag} — {detail}")
        if not available and tty:
            _prompt_for_repo(name, _env_var, deps[name])


def _prompt_for_repo(name: str, env_var: str, count: int) -> None:
    """TTY prompt for one missing repo. On a valid path: set env for this run and
    offer to persist. On Enter: skip (the dependent tests then skip honestly)."""
    import os
    from pathlib import Path
    from tests._testrepos import write_local_repo

    print(f"\n[pre-check] {name} 仓库未配置 — {count} 个真实链路用例需要它,否则将 skip。")
    while True:
        try:
            ans = input(f"  输入 {name} 路径(回车=本次跳过): ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if not ans:
            return  # user chose to skip this repo this run
        candidate = Path(ans).expanduser().resolve()
        if not candidate.is_dir():
            print(f"  ✗ 不是目录: {candidate} — 请重输(或回车跳过)")
            continue
        os.environ[env_var] = str(candidate)  # takes effect for this run
        try:
            persist = input(
                "  持久化到 tests/.testrepos.local.json?(下次免再问) [Y/n]: "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            persist = "n"
        if persist in ("", "y", "yes"):
            write_local_repo(env_var, str(candidate))
            print(f"  ✓ 已持久化,后续运行自动使用 {candidate}")
        else:
            print(f"  ✓ 本次生效(仅本会话)")
        return


# —— missing-env decision ————————————————————————————————————————————

def _decide_on_missing_env(missing: list[str]) -> None:
    """Report missing capabilities and let the user decide whether to continue.

    The point of the full-environment default is to surface real failures, not
    to stub around them. So when something is missing we do NOT auto-stub — we
    stop and ask. Non-interactive sessions (CI, no TTY) abort, since there is no
    one to answer. Set ASCENDC_TEST_CONTINUE_ON_MISSING=1 to force-continue in
    automation that knowingly wants to run the available subset.
    """
    import os
    import sys
    import pytest

    summary = "; ".join(missing)
    msg = (
        f"真实环境缺失: {summary}. "
        "默认全量测试需要真实 LLM/NPU/CANN 环境。"
    )
    print(f"\n[pre-check] {msg}")
    print("[pre-check] 提示: 用 --quick 跑快速子集（排除 llm/npu/slow/cann），"
          "或用 -m 显式选择标签，或 --no-env-check 跳过本检查。")

    if os.environ.get("ASCENDC_TEST_CONTINUE_ON_MISSING") == "1":
        print("[pre-check] ASCENDC_TEST_CONTINUE_ON_MISSING=1 → 继续运行可用子集。")
        return

    if not sys.stdin.isatty():
        pytest.exit(
            f"ERROR: {msg} 非交互环境默认中止。"
            "（--quick / -m / --no-env-check / ASCENDC_TEST_CONTINUE_ON_MISSING=1）",
            returncode=1,
        )

    try:
        answer = input("[pre-check] 是否仍要继续运行？相关用例可能失败 [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer not in ("y", "yes"):
        pytest.exit(f"ERROR: {msg} 用户选择中止。", returncode=1)
    print("[pre-check] 用户选择继续。相关用例若失败将如实报告，不做打桩。")

