"""step 104 — 编排主进程纯 Python import 守卫测试。

钉住（docs/plan/dispatch-npu-probe-subprocess/02-impl.md 条目 3）：
- 主进程 import torch/torch_npu（含子模块）→ 确定性 InProcessTorchImportError
  （不继承 ImportError——不被历史 ``except ImportError`` 降级分支静默吞掉）；
- 非守护模块 import 不受影响；
- 幂等安装；安装时已预载 → 直接抛错；
- 逃生门 ``DEVKIT_ALLOW_INPROC_TORCH=1`` → 不装守卫。

注意：本 pytest 环境有插件在启动期预载 torch_npu（与被测代码无关），用例内
先摘除再测，monkeypatch 自动还原。
"""
from __future__ import annotations

import importlib
import sys

import pytest

import ascendc_devkit.infra.import_guard as guard_mod
from ascendc_devkit.infra.import_guard import (
    InProcessTorchImportError, install_purity_guard, uninstall_purity_guard)


@pytest.fixture(autouse=True)
def _clean_guard_state(monkeypatch):
    """摘除预载的守护模块族（顶层+子模块——pytest 插件启动期预载 torch_npu
    会连带留下子模块键，`import_module("torch.nn")` 可直接命中缓存绕过
    import 路径）+ 摘除 tests/conftest 的宿主豁免 env（本文件要真测守卫的
    双分支）+ 保证用例结束守卫不残留。monkeypatch 自动还原。"""
    monkeypatch.delenv("DEVKIT_ALLOW_INPROC_TORCH", raising=False)
    for name in list(sys.modules):
        if name in guard_mod.GUARDED_MODULES or name.startswith(
                tuple(p + "." for p in guard_mod.GUARDED_MODULES)):
            monkeypatch.delitem(sys.modules, name)
    uninstall_purity_guard()
    yield
    uninstall_purity_guard()


class TestBlockOnImport:
    @pytest.mark.parametrize("name", ["torch", "torch_npu"])
    def test_import_blocked(self, name):
        install_purity_guard()
        with pytest.raises(InProcessTorchImportError, match="DEVKIT_ALLOW_INPROC_TORCH"):
            importlib.import_module(name)
        assert name not in sys.modules, "第0位拦截：父模块不得开始执行（无半加载残留）"

    def test_submodule_blocked(self):
        install_purity_guard()
        with pytest.raises(InProcessTorchImportError):
            importlib.import_module("torch.nn")

    def test_error_not_import_error_subclass(self):
        """不继承 ImportError：历史 ``except ImportError`` 降级分支拦不住它。"""
        assert not issubclass(InProcessTorchImportError, ImportError)

    def test_unguarded_import_unaffected(self):
        install_purity_guard()
        assert importlib.import_module("json") is not None


class TestInstallSemantics:
    def test_idempotent(self):
        install_purity_guard()
        install_purity_guard()  # 第二次不重复装
        blockers = [f for f in sys.meta_path if isinstance(f, guard_mod._PurityBlocker)]
        assert len(blockers) == 1

    def test_preloaded_raises_at_install(self, monkeypatch):
        import types
        monkeypatch.setitem(sys.modules, "torch", types.ModuleType("torch"))
        with pytest.raises(InProcessTorchImportError, match="已加载"):
            install_purity_guard()

    def test_escape_hatch_env_skips_install(self, monkeypatch):
        monkeypatch.setenv("DEVKIT_ALLOW_INPROC_TORCH", "1")
        install_purity_guard()
        assert not any(isinstance(f, guard_mod._PurityBlocker) for f in sys.meta_path)


class TestDispatchImportSurfacePurity:
    """M1 整改（review eadc7763）：dispatch 导入面的纯度回归网。

    背景：pytest 宿主会话被插件预载 torch_npu + conftest 全会话豁免 env，
    宿主内的用例**无法**暴露「dispatch 路径重新引入进程内 torch import」的
    回归（守卫 no-op、sys.modules 恒真短路）。本用例在**子进程**里跑——天然
    隔离预载，unset 豁免 env，装真守卫，import dispatch 全导入面（含 stage
    注册链与 skill 扫描），断言零 torch + 故意 import 必被拦。确定性、无
    NPU/CANN/LLM 依赖（§3.5 无标记）。
    """

    def test_dispatch_import_surface_never_loads_torch(self):
        import os
        import subprocess
        from pathlib import Path

        import ascendc_devkit

        src_root = Path(ascendc_devkit.__file__).resolve().parents[1]
        code = (
            "import sys\n"
            "from ascendc_devkit.infra.import_guard import (\n"
            "    install_purity_guard, InProcessTorchImportError)\n"
            "install_purity_guard()\n"
            "import ascendc_devkit.application.dispatcher\n"
            "from ascendc_devkit.orchestration.registry import (\n"
            "    _ensure_stages_loaded, _ensure_workflows_loaded)\n"
            "_ensure_stages_loaded()\n"
            "_ensure_workflows_loaded()\n"
            "from ascendc_devkit.orchestration.skill_config import validate_skill_map\n"
            "validate_skill_map()\n"
            "leaked = [m for m in sys.modules\n"
            "          if m == 'torch' or m == 'torch_npu'\n"
            "          or m.startswith(('torch.', 'torch_npu.'))]\n"
            "assert not leaked, f'IMPURE dispatch import surface: {leaked}'\n"
            "try:\n"
            "    import torch  # noqa: F401 — 故意触发，验证守卫拦截\n"
            "    raise SystemExit('GUARD-FAILED: import torch did not raise')\n"
            "except InProcessTorchImportError:\n"
            "    pass\n"
            "print('PURE-OK')\n"
        )
        env = {k: v for k, v in os.environ.items()
               if k != "DEVKIT_ALLOW_INPROC_TORCH"}
        env["PYTHONPATH"] = str(src_root) + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True,
            timeout=120, env=env)
        assert result.returncode == 0 and "PURE-OK" in result.stdout, (
            f"dispatch 导入面纯度子进程失败 rc={result.returncode}\n"
            f"stderr_tail={result.stderr[-800:]}")

    def test_perf_stage_surface_never_loads_torch(self):
        """step-106 第五向量回归网：perf 主进程路径（PerfStage 可用性检查 +
        probe-free 构造 + execute 编排入口）全程零 torch。

        现场：perf.py 两处 ``NPURunner(...)`` 主进程构造（123 在 try 外、179 包在
        except Exception 内——守卫错误被吞成静默"NPU 不可用"）。修复 = 子进程探测
        单点 + probe_free 通路。本用例子进程（无豁免 env）装真守卫重放该路径。
        """
        import os
        import subprocess
        from pathlib import Path

        import ascendc_devkit

        src_root = Path(ascendc_devkit.__file__).resolve().parents[1]
        code = (
            "import sys\n"
            "from ascendc_devkit.infra.import_guard import install_purity_guard\n"
            "install_purity_guard()\n"
            "from ascendc_devkit.adapters.npu.runner import NPURunner\n"
            # probe-free 构造（perf.py:123 修复后通路）
            "runner = NPURunner.probe_free(chip_version='A3')\n"
            "assert runner._chip_version == 'A3' and runner._torch_npu_available is None\n"
            # execute 编排入口：probe-free 跳 NPU 闸门、落在 deploy 产物闸门
            "from ascendc_devkit.domain.exceptions import EnvironmentNotAvailableError\n"
            "from ascendc_devkit.domain.operator import OperatorSpec\n"
            "from types import SimpleNamespace\n"
            "tc = SimpleNamespace(name='c',\n"
            "    inputs=[{'shape': [4], 'dtype': 'fp16'}], attrs={}, expected={})\n"
            "try:\n"
            "    runner.execute(OperatorSpec(name='t'), [tc], 0, deploy_result=None)\n"
            "    raise SystemExit('UNEXPECTED: no gate fired')\n"
            "except EnvironmentNotAvailableError as e:\n"
            "    assert 'deploy artifacts' in str(e), f'wrong gate: {e}'\n"
            # perf stage 类导入面 + 可用性检查方法存在性（不发真探测）
            "from ascendc_devkit.orchestration.stages.perf import PerfStage\n"
            "assert hasattr(PerfStage, '_check_npu_available')\n"
            "leaked = [m for m in sys.modules\n"
            "          if m == 'torch' or m == 'torch_npu'\n"
            "          or m.startswith(('torch.', 'torch_npu.'))]\n"
            "assert not leaked, f'IMPURE perf surface: {leaked}'\n"
            "print('PERF-SURFACE-PURE-OK')\n"
        )
        env = {k: v for k, v in os.environ.items()
               if k != "DEVKIT_ALLOW_INPROC_TORCH"}
        env["PYTHONPATH"] = str(src_root) + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True,
            timeout=120, env=env)
        assert result.returncode == 0 and "PERF-SURFACE-PURE-OK" in result.stdout, (
            f"perf 主进程路径纯度子进程失败 rc={result.returncode}\n"
            f"stderr_tail={result.stderr[-800:]}")

    def test_smoke_harness_build_never_loads_torch(self):
        """step-104 第四向量回归网（20260829 批 upsample_custom 实证）。

        现场回放：codegen 尾段 deploy → smoke harness 生成（主进程）经
        ``_build_test_harness(rule=None)`` lazy import precision_compare 拿
        ``merge_thresholds`` —— precision_compare 顶层 import torch → 守卫拦下、
        stage halt。修复 = 阈值核心上移 domain/precision（torch-free）。

        本用例在子进程（无豁免 env、无插件预载）装真守卫，原样重放该路径：
        默认 rule 解析 + ``NPURunner.__new__`` + ``_build_test_harness(
        smoke_probe=True)`` 全程零 torch 泄漏。确定性、无 NPU/CANN/LLM 依赖。
        """
        import os
        import subprocess
        from pathlib import Path

        import ascendc_devkit

        src_root = Path(ascendc_devkit.__file__).resolve().parents[1]
        code = (
            "import sys\n"
            "from ascendc_devkit.infra.import_guard import install_purity_guard\n"
            "install_purity_guard()\n"
            # 原 lazy import 点的默认 rule 解析（现走 domain，模块级）
            "from ascendc_devkit.domain.precision import CompareRule, merge_thresholds\n"
            "rule = CompareRule(dtype_thresholds=merge_thresholds(None))\n"
            # codegen smoke harness 生成全路径（deploy._build_smoke_harness 同构）
            "from ascendc_devkit.adapters.npu.runner import NPURunner\n"
            "from ascendc_devkit.orchestration.stages.deploy import DeployResult\n"
            "from ascendc_devkit.domain.operator import OperatorSpec, TensorSpec\n"
            "from ascendc_devkit.domain.requirement import TestCase\n"
            "runner = NPURunner.__new__(NPURunner)\n"
            "runner._chip_version = 'A2'\n"
            "runner._torch_npu_available = True\n"
            "op = OperatorSpec(name='smoke_op',\n"
            "    inputs=[TensorSpec(name='x0', dtype='fp16', shape=['N'])],\n"
            "    outputs=[TensorSpec(name='y', dtype='fp16', shape=['N'])])\n"
            "tc = TestCase(name='smoke',\n"
            "    inputs=[{'shape': [1024], 'dtype': 'fp16'}], attrs={})\n"
            "deploy_result = DeployResult(\n"
            "    python_path='/tmp/devkit-purity-per-op-python',\n"
            "    install_path='/tmp/devkit-purity-per-op-opp',\n"
            "    ld_library_path_add='/tmp/devkit-purity-per-op-ld')\n"
            "script = runner._build_test_harness(\n"
            "    op, [tc], golden_contract=None, deploy_result=deploy_result,\n"
            "    callable_target={'kind': 'torch_op',\n"
            "                      'symbol': 'cann_bench.smoke_op'},\n"
            "    smoke_probe=True)\n"
            "assert script and 'smoke_op' in script, 'harness script must render'\n"
            "leaked = [m for m in sys.modules\n"
            "          if m == 'torch' or m == 'torch_npu'\n"
            "          or m.startswith(('torch.', 'torch_npu.'))]\n"
            "assert not leaked, f'IMPURE smoke-harness build: {leaked}'\n"
            "print('SMOKE-HARNESS-PURE-OK')\n"
        )
        env = {k: v for k, v in os.environ.items()
               if k != "DEVKIT_ALLOW_INPROC_TORCH"}
        env["PYTHONPATH"] = str(src_root) + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True,
            timeout=120, env=env)
        assert result.returncode == 0 and "SMOKE-HARNESS-PURE-OK" in result.stdout, (
            f"smoke harness 生成纯度子进程失败 rc={result.returncode}\n"
            f"stderr_tail={result.stderr[-800:]}")
