"""ST — cann-bench 跨仓契约真实守护（§3.9）。

守两条用真实 cann-bench kernel_eval 代码才能验证的跨仓契约（确定性、秒级、无
NPU/LLM；cann-bench src 缺失按 §3.7 诚实 skip）：

1. **P112 发现链路**：``CannbenchAdaptStage`` 确定性注入 ``cann_bench/__init__.py``
   wrapper → 真实 cann-bench ``scan_interfaces`` 据此发现算子——不依赖
   LLM/codegen/build（那些由各自 UT + 实跑批覆盖）。
2. **step-121 任务级 scoping 契约**：DevKit ``CannbenchScorer._resolve_task_dir``
   传任务目录 → cann-bench ``resolve_task_dir`` 拆成 bench_root（评测集根，
   match_operators/golden/baseline 不变）+ filter_prefix（用例集构造性限定到
   目标任务）。kernel_eval 的 --operator 过滤大小写不敏感，仅差大小写的重名
   孪生任务靠名字无法区分——路径是任务的唯一身份。cann-bench 若改变
   resolve_task_dir 对任务级目录的分解语义，本 ST 在测试期报警（运行期由
   scorer 的多 operator 守卫兜底暴露）。

为什么是确定性 ST 而非 heavy_llm 全流水线（review M2 复检决策）：
  - ``scan_interfaces`` 发现算子靠 ``dir(cann_bench)``（cann-bench
    package_manager.py:569-586）—— wrapper 提供的 Python 命名空间入口即足够，
    ``torch.ops.cann_bench`` 探测只是 enrichment，发现本身不依赖编译产物 ``_C.so``。
  - 故「wrapper → 发现」这条 P112 链路可用确定性、秒级、真实 ``scan_interfaces``
    直接验证，无需（也不应）被 LLM codegen 能力门控（heavy_llm 全流水线在难算子如
    manifold 上卡在 codegen，与 P112 正交——曾在 spawn 抖动后卡 codegen，两轮均未
    触达发现链路）。

wrapper 生成本身（manifest → wrapper 三维）由 ``test_cannbench_adapt_schema.py``
UT 充分守护；本 ST 聚焦「生成的 wrapper 是否真能被 scan_interfaces 发现」这条真实链路。
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

from ascendc_devkit.adapters.evaluation.cannbench_adapt import (
    _build_wrapper,
    _inject_wrapper_block,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _cann_bench_src() -> Path | None:
    """cann-bench 仓的 ``src/``（含 kernel_eval）。env > 常见路径，缺则 None。"""
    for p in (
        os.environ.get("CANN_BENCH"),
        str(Path.home() / "code" / "cann-bench"),
        "/home/x00584171/code/cann-bench",
    ):
        if p and (Path(p) / "src" / "kernel_eval").is_dir():
            return Path(p) / "src"
    return None


CANN_BENCH_SRC = _cann_bench_src()
pytestmark = pytest.mark.skipif(
    CANN_BENCH_SRC is None,
    reason="cann-bench src (kernel_eval) not found — set $CANN_BENCH; real integration target absent (§3.7)",
)


@pytest.fixture
def synthetic_cann_bench(tmp_path: Path):
    """隔离的 cann_bench 包：``<tmp>/cbroot/cann_bench/__init__.py`` + 注入 sys.path。

    scan_interfaces 做 ``import cann_bench`` + ``dir(cann_bench)``，故只需一个可导入
    的 cann_bench 包，wrapper 落在其 ``__init__.py``。teardown 清 sys.path + sys.modules
    防污染其它用例（cann_bench 是全局模块名）。
    """
    cb_root = tmp_path / "cbroot"
    pkg = cb_root / "cann_bench"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    sys.path.insert(0, str(cb_root))
    sys.modules.pop("cann_bench", None)
    yield pkg / "__init__.py"
    sys.modules.pop("cann_bench", None)
    try:
        sys.path.remove(str(cb_root))
    except ValueError:
        pass


def _scan_interfaces() -> list[str]:
    """调真实 cann-bench ``PackageManager.scan_interfaces``，返回发现的接口名。"""
    assert CANN_BENCH_SRC is not None
    sys.path.insert(0, str(CANN_BENCH_SRC))
    # 强制重新发现 cann_bench（synthetic fixture 已 pop + re-insert sys.path）
    sys.modules.pop("cann_bench", None)
    from kernel_eval.data.package_manager import PackageManager  # type: ignore

    pm = PackageManager()
    return [i.name for i in pm.scan_interfaces()]


def _inject(init_path: Path, op_name: str, symbol_last: str, params: list[str]) -> None:
    """用 CannbenchAdaptStage 的确定性注入原语落 wrapper（与 transition 同路径）。"""
    wrapper = _build_wrapper(op_name, symbol_last, params)
    block = f"# {op_name} wrapper (deterministic, cannbench_adapt)\n{wrapper}"
    init_path.write_text(
        _inject_wrapper_block(init_path.read_text(encoding="utf-8"), op_name, block),
        encoding="utf-8",
    )


class TestCannbenchDiscoveryLink:
    """P112 真实发现链路：确定性 wrapper 注入 → 真实 scan_interfaces 发现算子。"""

    def test_wrapper_injection_makes_op_discoverable(self, synthetic_cann_bench):
        """核心不变式：注入 wrapper 后，真实 scan_interfaces 发现该算子。"""
        _inject(synthetic_cann_bench, "p112_disc_op", "npu_p112_disc_op",
                ["input", "dim"])
        discovered = _scan_interfaces()
        assert "p112_disc_op" in discovered, (
            f"scan_interfaces failed to discover the wrapper-injected op "
            f"(P112 discovery link broken); discovered={discovered}"
        )

    def test_absent_wrapper_not_discovered(self, synthetic_cann_bench):
        """负对照：无 wrapper（空 __init__）→ scan_interfaces 不发现该算子。

        证明「发现」确由 wrapper 提供，而非其它机制——锁定 P112 因果链方向。"""
        discovered = _scan_interfaces()
        assert "p112_disc_op" not in discovered

    def test_idempotent_inject_keeps_single_def_and_discoverable(self, synthetic_cann_bench):
        """幂等注入两次（模拟 adapt 重跑）→ 仍只 1 个 def + scan_interfaces 发现一次。"""
        for _ in range(2):
            _inject(synthetic_cann_bench, "p112_idem_op", "npu_p112_idem_op", ["x"])
        content = synthetic_cann_bench.read_text(encoding="utf-8")
        assert content.count("def p112_idem_op(") == 1  # no duplicate def
        discovered = _scan_interfaces()
        assert discovered.count("p112_idem_op") == 1

    def test_wrapper_with_unregistered_target_still_discovered(self, synthetic_cann_bench):
        """文档化不变式边界：wrapper 转发到未注册的 torch.ops 目标（无 _C.so），scan_interfaces
        仍**发现**它——发现靠 dir(cann_bench)（wrapper），不靠目标可调（_C 注册）。

        这正是 P112 的要点：harness（torch.ops 直调）能跑、cann-bench（scan_interfaces）
        发现不到的缺口，由 wrapper 补上。发现 ≠ 可调；本用例锁定「发现」这一半。"""
        _inject(synthetic_cann_bench, "p112_unreg_op", "npu_never_registered",
                ["x", "y"])
        discovered = _scan_interfaces()
        assert "p112_unreg_op" in discovered  # 发现不依赖转发目标是否注册


class TestTaskDirScopingContract:
    """step-121 任务级 scoping 跨仓契约：DevKit 解析任务目录 → cann-bench
    resolve_task_dir 分解为 bench_root + filter_prefix。

    fixture 复刻孪生任务布局（批 20260908-130718-a62158 实证形态）：目标任务
    ``tasks/level3/<op>`` 与仅差大小写重名的 aten 孪生任务
    ``tasks/level2/task_XXXX_aten_<op 去下划线变体>``——kernel_eval 的 --operator
    过滤大小写不敏感（lower 相等），名字无法区分二者，必须靠路径。"""

    @staticmethod
    def _twin_tasks_tree(tmp_path: Path) -> tuple[Path, Path]:
        """synthetic tasks 树：目标 + 仅差大小写重名的孪生。返回 (repo_root, 目标任务目录)。"""
        repo = tmp_path / "repo"
        target = repo / "tasks" / "level3" / "adaptive_avg_pool_3d"
        target.mkdir(parents=True)
        (target / "cases.yaml").write_text("cases: []")
        twin = repo / "tasks" / "level2" / "task_0258_aten_adaptive_avg_pool3d"
        twin.mkdir(parents=True)
        (twin / "cases.yaml").write_text("cases: []")
        return repo, target

    def test_devkit_resolves_task_dir_and_cannbench_decomposes_it(self, tmp_path):
        """契约两半在同一棵树上成立：(a) DevKit _resolve_task_dir 返回任务目录
        （非评测集根）；(b) 真实 cann-bench resolve_task_dir 把该目录拆成
        bench_root=评测集根 + filter_prefix=<level>/<op>——match_operators 等
        以 bench_root 为根的机制不受影响，用例集被 prefix 构造性限定。"""
        assert CANN_BENCH_SRC is not None
        from ascendc_devkit.adapters.evaluation.cannbench_scorer import CannbenchScorer

        repo, target = self._twin_tasks_tree(tmp_path)
        resolved = CannbenchScorer()._resolve_task_dir(repo, "adaptive_avg_pool_3d")
        assert resolved == str(target), (
            "DevKit side broken: --task-dir must carry the task directory "
            f"(got {resolved}) — the twin task will leak back in via the "
            "case-insensitive --operator filter")

        sys.path.insert(0, str(CANN_BENCH_SRC))
        from kernel_eval.utils.path_resolver import resolve_task_dir  # type: ignore

        bench_root, filter_prefix = resolve_task_dir(resolved, repo)
        assert Path(bench_root) == repo / "tasks", (
            f"cann-bench side drifted: bench_root expected the bench-set root "
            f"{repo / 'tasks'}, got {bench_root} — match_operators/golden/"
            "baseline would break")
        assert filter_prefix == "level3/adaptive_avg_pool_3d", (
            f"cann-bench side drifted: filter_prefix expected the task rel "
            f"path, got {filter_prefix!r} — case scoping is not constructive "
            "anymore; twin task re-enters via the name filter")

    def test_twin_names_are_name_indistinguishable(self, tmp_path):
        """前提事实守护（自证测试动机）：孪生任务的算子名与目标仅差大小写，
        lower 后相等——名字过滤（kernel_eval cli 的大小写不敏感比较）无法
        区分二者，路径 scoping 是唯一判据。cann-bench 若把过滤改为大小写
        敏感/按 rel_path，本前提失效，此测试应当删除连同 scoping 依据重评。"""
        target_op = "AdaptiveAvgPool3D"   # tasks/level3/<op> proto 的算子名
        twin_op = "AdaptiveAvgPool3d"     # tasks/level2/task_XXXX_aten_* 的算子名
        assert target_op.lower() == twin_op.lower()
