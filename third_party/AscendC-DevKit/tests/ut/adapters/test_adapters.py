"""Unit tests for L6 Adapters."""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path

import pytest

from ascendc_devkit.domain.operator import OperatorSpec, OperatorIdentity
from ascendc_devkit.domain.repository import (
    RepositoryProfile, BuildVariant, BuildStage, OpNaming,
)
from ascendc_devkit.adapters.repository.base import RepositoryAdapter
from ascendc_devkit.adapters.repository.generic import GenericRepositoryAdapter
from ascendc_devkit.adapters.repository.profile_loader import ProfileLoader
from ascendc_devkit.adapters.toolchain.cann import CANNToolchain


def _profile(name="test", variants=None, prefix=""):
    return RepositoryProfile(
        name=name,
        op_naming=OpNaming(prefix=prefix),
        build_variants=tuple(variants or ()),
    )


class TestRepositoryAdapterABC:
    def test_abc_cannot_instantiate(self):
        with pytest.raises(TypeError):
            RepositoryAdapter()  # abstract

    def test_generic_adapter_creates(self):
        adapter = GenericRepositoryAdapter(_profile())
        assert adapter.profile.name == "test"


class TestGenericRepositoryAdapter:
    def test_materialize_new_operator(self):
        adapter = GenericRepositoryAdapter(_profile())
        with tempfile.TemporaryDirectory() as tmpdir:
            op_dir = Path(tmpdir) / "ops" / "test_op"
            op = OperatorSpec(name="test_op")
            sources = {"kernel.cpp": "// kernel code", "kernel.h": "// header"}
            files = adapter.materialize_new_operator(op, sources, Path(tmpdir), op_dir=op_dir)

            assert len(files) == 2
            assert (op_dir / "kernel.cpp").exists()
            assert (op_dir / "kernel.h").exists()

    def test_materialize_with_subdirs(self):
        adapter = GenericRepositoryAdapter(_profile())
        with tempfile.TemporaryDirectory() as tmpdir:
            op_dir = Path(tmpdir) / "ops" / "sub_op"
            op = OperatorSpec(name="sub_op")
            sources = {"sub/dir/file.cpp": "// code"}
            files = adapter.materialize_new_operator(op, sources, Path(tmpdir), op_dir=op_dir)

            assert len(files) == 1
            assert (op_dir / "sub" / "dir" / "file.cpp").exists()

    def test_materialize_creates_missing_op_dir(self):
        """New operators don't exist yet; the op_dir is created on demand."""
        adapter = GenericRepositoryAdapter(_profile())
        with tempfile.TemporaryDirectory() as tmpdir:
            op_dir = Path(tmpdir) / "brand" / "new" / "ai_infra_foo"
            files = adapter.materialize_new_operator(
                OperatorSpec(name="foo"), {"k.cpp": "// code"}, Path(tmpdir), op_dir=op_dir,
            )
            assert len(files) == 1
            assert op_dir.is_dir()

    def test_materialize_falls_back_to_dest_root(self):
        """When op_dir is omitted, dest_root is used as the target base."""
        adapter = GenericRepositoryAdapter(_profile())
        with tempfile.TemporaryDirectory() as tmpdir:
            files = adapter.materialize_new_operator(
                OperatorSpec(name="x"), {"k.cpp": "// code"}, Path(tmpdir),
            )
            assert len(files) == 1
            assert (Path(tmpdir) / "k.cpp").exists()

    def test_build_no_variant_match_fails(self):
        """An op_dir matching no variant yields a failed build with guidance."""
        variant = BuildVariant(name="inference", match_prefix="inference/ascendc/src",
                               stages=(BuildStage(name="ascendc", cwd=".",
                                                  command_template="true"),))
        adapter = GenericRepositoryAdapter(_profile(variants=[variant]))
        op = OperatorIdentity(spec=OperatorSpec(name="x"), repo_root=Path("/tmp"),
                              op_dir=Path("/tmp/unmatched/x"))
        result = adapter.build(Path("/tmp"), op, "A2")
        assert result.passed is False
        assert "match_prefix" in result.stderr

    def test_build_no_enabled_stages_passes(self):
        """A matched variant with only disabled stages is a no-op pass."""
        variant = BuildVariant(name="default", match_prefix="",
                               stages=(BuildStage(name="torch", enabled=False),))
        adapter = GenericRepositoryAdapter(_profile(variants=[variant]))
        op = OperatorIdentity(spec=OperatorSpec(name="x"), repo_root=Path("/tmp"),
                              op_dir=Path("/tmp/x"))
        result = adapter.build(Path("/tmp"), op, "A2")
        assert result.passed is True

    def test_build_runs_enabled_stage_command(self, tmp_path):
        """The variant's enabled stage command runs in its cwd with full_op_name."""
        op_dir = tmp_path / "src" / "ai_infra_foo"
        op_dir.mkdir(parents=True)
        marker = tmp_path / "stamp.txt"
        variant = BuildVariant(
            name="default", match_prefix="src",
            stages=(BuildStage(name="ascendc", cwd=".",
                               command_template=f"echo {{full_op_name}} > {marker}"),),
        )
        adapter = GenericRepositoryAdapter(_profile(variants=[variant]))
        op = OperatorIdentity(spec=OperatorSpec(name="foo"), repo_root=tmp_path, op_dir=op_dir)
        result = adapter.build(tmp_path, op, "A2")
        assert result.passed is True
        assert marker.read_text().strip() == "ai_infra_foo"

    def test_scan_existing_operator_finds_files(self, tmp_path):
        op_dir = tmp_path / "custom_ops" / "test_op"
        op_dir.mkdir(parents=True)
        (op_dir / "test_op.h").write_text("// header")
        (op_dir / "test_op.cpp").write_text("// kernel")
        adapter = GenericRepositoryAdapter(_profile())
        result = adapter.scan_existing_operator(tmp_path, "test_op", op_dir=op_dir)
        assert result.spec.name == "test_op"
        assert result.op_dir == op_dir
        assert len(result.files) >= 2

    def test_scan_requires_op_dir(self, tmp_path):
        adapter = GenericRepositoryAdapter(_profile())
        with pytest.raises(ValueError, match="op_dir"):
            adapter.scan_existing_operator(tmp_path, "test_op")

    def test_scan_with_nested_files_uses_relative_paths(self, tmp_path):
        """Recursive scan uses relative paths from op_dir as keys."""
        op_dir = tmp_path / "ops" / "nested_op"
        op_dir.mkdir(parents=True)
        (op_dir / "top_level.h").write_text("// top")
        host_dir = op_dir / "op_host"
        host_dir.mkdir()
        (host_dir / "nested_op.cpp").write_text("// nested")
        kernel_dir = op_dir / "op_kernel"
        kernel_dir.mkdir()
        (kernel_dir / "nested_op_kernel.cpp").write_text("// kernel")

        adapter = GenericRepositoryAdapter(_profile())
        result = adapter.scan_existing_operator(tmp_path, "nested_op", op_dir=op_dir)
        assert len(result.files) >= 3
        file_keys = list(result.files.keys())
        assert "top_level.h" in file_keys
        assert any("op_host" in k for k in file_keys)
        assert any("op_kernel" in k for k in file_keys)


class TestProfileLoader:
    def test_load_omni_ops(self):
        profile = ProfileLoader.load("omni-ops")
        assert profile.name == "omni-ops"
        assert profile.op_naming.prefix == "ai_infra_"
        names = [v.name for v in profile.build_variants]
        assert "inference" in names and "training" in names

    def test_load_ops_nn(self):
        profile = ProfileLoader.load("ops-nn")
        assert profile.name == "ops-nn"
        assert profile.op_naming.prefix == ""
        v = profile.select_variant("conv/conv3d")
        assert v is not None and v.name == "default"
        assert "--ops={full_op_name}" in v.stages[0].command_template

    def test_list_profiles(self):
        profiles = ProfileLoader.list_profiles()
        assert "omni-ops" in profiles
        assert "ops-nn" in profiles

    def test_load_nonexistent_raises(self):
        with pytest.raises(FileNotFoundError):
            ProfileLoader.load("nonexistent-profile")

    def test_all_shipped_profiles_pass_schema(self):
        """Every YAML in resources/repository-profiles/ validates against the
        profile JSON Schema (schema门禁)."""
        for name in ProfileLoader.list_profiles():
            ProfileLoader.load(name)  # raises ValueError on schema violation

    def test_cann_bench_has_deploy_capability(self):
        """G3/D6-2: cann-bench declares install_runtime + install_python + smoke
        role stages, so it is deploy-capable (the deploy chain is declared as
        profile roles, consumed in-session by codegen's Deployer redeploy post-P57)."""
        p = ProfileLoader.load("cann-bench")
        rel = "examples/aclnn_launch_example/csrc/ops/add"
        assert p.has_deploy_capability(rel) is True
        roles = [s.role for s in p.deploy_stages(rel)]
        assert roles == ["install_runtime", "install_python", "smoke"]

    def test_omni_ops_variants_deploy_capable(self):
        """omni-ops 两个 variant 都声明了完整部署链。

        ``has_deploy_capability`` 是框架的硬契约（deploy.py 部署前调用，不满足即报
        'declares no deploy roles' 退出）。两个 variant 缺任一都让对应路径下的算子无法
        部署，且只在真机 deploy 时暴露，故在加载期用 UT 兜住（§1.3）。
        """
        p = ProfileLoader.load("omni-ops")
        for rel in ("inference/ascendc/src/ops/x/my_op",
                    "training/ascendc/src/ops/x/my_op"):
            assert p.has_deploy_capability(rel) is True, f"{rel} 不可部署"
            assert [s.role for s in p.deploy_stages(rel)] == [
                "install_runtime", "install_python", "smoke"]

    def test_omni_ops_install_opp_targets_framework_view(self):
        """install_opp 必须把 OPP 装到框架读的那个位置。

        框架 smoke/harness 无条件把 ``ASCEND_CUSTOM_OPP_PATH`` 指向
        ``<per_op_opp_dir>/vendors/custom_ops``（deploy.py smoke env / runner.py），
        故 install_runtime 阶段必须：(a) 用 ``--install-path={per_op_opp_dir}`` 装进
        per-op 目录（而非某个固定 CANN 根）；(b) 把 install.sh 产出的 vendor 目录落到
        ``{per_op_opp_dir}/vendors/custom_ops``。落点错 → 算子注册信息找不到，kernel
        不执行。
        """
        p = ProfileLoader.load("omni-ops")
        for rel in ("inference/ascendc/src/ops/x/my_op",
                    "training/ascendc/src/ops/x/my_op"):
            variant = p.select_variant(rel)
            runtime = [s for s in variant.enabled_stages() if s.role == "install_runtime"]
            assert len(runtime) == 1, f"{variant.name}: 需恰好一个 install_runtime stage"
            cmd = runtime[0].command_template
            assert "--install-path={per_op_opp_dir}" in cmd, (
                f"{variant.name}: 未装进 per-op 目录（框架只读该位置的视图）")
            assert "{per_op_opp_dir}/vendors/custom_ops" in cmd, (
                f"{variant.name}: 未把 vendor 落到框架约定的 vendors/custom_ops")

    def test_profile_templates_use_no_absolute_paths(self):
        """所有 shipped profile 的 command_template 不得出现绝对路径。

        profile 随仓分发，写死机器专属路径（如 /home/<user>/...）换台机器即失效；路径
        应经模板变量（per_op_opp_dir / whl_pkg / run_pkg 等）由框架注入（§1.7）。历史
        故障：install_runtime 写死某个 CANN 根 → 换机后装到了 CANN 不搜索的位置。
        """
        import re
        # 不要求前导分隔符：绝对路径常紧跟 '=' （如 --install-path=/home/...），
        # 加前缀约束会漏判。
        abs_path = re.compile(r"/(home|root|usr/local|tmp|opt)/")
        for name in ProfileLoader.list_profiles():
            p = ProfileLoader.load(name)
            for v in p.build_variants:
                for s in v.stages:
                    assert not abs_path.search(s.command_template), (
                        f"{name}/{v.name}/{s.name}: command_template 含绝对路径 "
                        f"→ 换机即失效：{s.command_template!r}")

    def test_schema_rejects_unknown_role(self, tmp_path):
        """G2: an illegal stage role fails schema validation at load time."""
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "name: bad\n"
            "scaffolding:\n"
            "  supported: [torch_op]\n"
            "  selected: torch_op\n"
            "build_variants:\n"
            "  - name: default\n"
            "    match_prefix: ops\n"
            "    stages:\n"
            "      - name: s\n"
            "        role: bogus\n"
        )
        with pytest.raises(ValueError, match="schema"):
            ProfileLoader.load("bad", resources_root=tmp_path)

    def test_schema_rejects_unknown_top_level_key(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "name: bad\n"
            "scaffolding:\n"
            "  supported: [torch_op]\n"
            "  selected: torch_op\n"
            "build_variants:\n"
            "  - name: default\n"
            "    stages: []\n"
            "bogus_field: 1\n"
        )
        with pytest.raises(ValueError, match="schema"):
            ProfileLoader.load("bad", resources_root=tmp_path)

    def test_schema_rejects_missing_build_variants(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "name: bad\n"
            "scaffolding:\n"
            "  supported: [torch_op]\n"
            "  selected: torch_op\n"
        )
        with pytest.raises(ValueError, match="schema"):
            ProfileLoader.load("bad", resources_root=tmp_path)

    def test_schema_accepts_minimal_valid_profile(self, tmp_path):
        ok = tmp_path / "ok.yaml"
        ok.write_text(
            "name: ok\n"
            "scaffolding:\n"
            "  supported: [torch_op]\n"
            "  selected: torch_op\n"
            "build_variants:\n"
            "  - name: default\n"
            "    match_prefix: \"\"\n"
            "    stages:\n"
            "      - name: ascendc\n"
            "        command_template: \"make\"\n"
        )
        profile = ProfileLoader.load("ok", resources_root=tmp_path)
        assert profile.name == "ok"
        assert profile.build_variants[0].name == "default"


class TestCANNToolchain:
    def test_cann_detects_compiler_on_path(self, monkeypatch):
        """is_available is True when a CANN compiler sentinel is on PATH."""
        import ascendc_devkit.adapters.toolchain.cann as cann_mod
        monkeypatch.setenv("ASCEND_TOOLKIT_HOME", "/opt/cann")
        monkeypatch.setattr(cann_mod.shutil, "which",
                            lambda n: "/opt/cann/bin/ccec" if n == "ccec" else None)
        tc = CANNToolchain()
        assert tc.is_available is True

    def test_cann_unavailable_when_no_compiler(self, monkeypatch):
        """is_available is False when no compiler sentinel is on PATH."""
        import ascendc_devkit.adapters.toolchain.cann as cann_mod
        monkeypatch.setattr(cann_mod.shutil, "which", lambda _: None)
        tc = CANNToolchain()
        assert tc.is_available is False

    def test_cann_is_available_property(self):
        """is_available property reflects detection result."""
        tc = CANNToolchain()
        assert isinstance(tc.is_available, bool)

    def test_diagnostic_hint_toolkit_set_but_no_compiler(self, monkeypatch):
        """F2: ASCEND_TOOLKIT_HOME set but compiler missing → suggest
        sourcing set_env.sh, with the path derived from ASCEND_TOOLKIT_HOME."""
        import ascendc_devkit.adapters.toolchain.cann as cann_mod
        monkeypatch.setenv("ASCEND_TOOLKIT_HOME",
                           "/usr/local/Ascend/cann-9.0.0-beta.2")
        monkeypatch.setattr(cann_mod.shutil, "which", lambda _: None)
        tc = CANNToolchain()
        hint = tc.diagnostic_hint()
        assert "source" in hint
        assert "set_env.sh" in hint
        assert "cann-9.0.0-beta.2" in hint

    def test_diagnostic_hint_toolkit_home_latest_layout(self, monkeypatch):
        """F2: .../cann-x/ascend-toolkit/latest layout resolves set_env.sh to
        the cann-x root."""
        import ascendc_devkit.adapters.toolchain.cann as cann_mod
        monkeypatch.setenv(
            "ASCEND_TOOLKIT_HOME",
            "/usr/local/Ascend/cann-8.0/ascend-toolkit/latest")
        monkeypatch.setattr(cann_mod.shutil, "which", lambda _: None)
        tc = CANNToolchain()
        hint = tc.diagnostic_hint()
        assert "set_env.sh" in hint
        assert "cann-8.0" in hint

    def test_diagnostic_hint_no_toolkit_home(self, monkeypatch):
        """F2: ASCEND_TOOLKIT_HOME unset → suggest install / confirm path."""
        import ascendc_devkit.adapters.toolchain.cann as cann_mod
        monkeypatch.delenv("ASCEND_TOOLKIT_HOME", raising=False)
        monkeypatch.setattr(cann_mod.shutil, "which", lambda _: None)
        tc = CANNToolchain()
        hint = tc.diagnostic_hint()
        assert "未安装" in hint or "安装" in hint


class TestNPURunner:
    """NPURunner tests (Slice 5)."""

    def test_stub_method_removed_from_runner(self):
        """P1: _stub_execute no longer exists on NPURunner — adapter is pure executor."""
        from ascendc_devkit.adapters.npu.runner import NPURunner

        runner = NPURunner(chip_version="A2")
        assert not hasattr(runner, "_stub_execute"), (
            "_stub_execute must not exist on NPURunner (stub logic moved to gate layer)")

    def test_environment_detection_populates_flag(self):
        """_check_environment sets _torch_npu_available."""
        from ascendc_devkit.adapters.npu.runner import NPURunner

        runner = NPURunner()
        info = runner._check_environment()
        assert "torch_available" in info
        assert "torch_npu_available" in info
        assert "device_count" in info
        assert isinstance(runner._torch_npu_available, bool)

    def test_harness_generated_for_test_cases(self):
        """_build_test_harness produces valid Python with shape info."""
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.operator import OperatorSpec, TensorSpec
        from ascendc_devkit.domain.requirement import TestCase

        runner = NPURunner(chip_version="A2")
        op = OperatorSpec(
            name="gelu",
            inputs=[TensorSpec(name="x", dtype="fp16", shape=[128, 256])],
            outputs=[TensorSpec(name="y", dtype="fp16", shape=[128, 256])],
        )
        test_cases = [
            TestCase(
                name="basic",
                inputs=[{"name": "x", "shape": [128, 256], "dtype": "fp16"}],
            ),
        ]
        harness = runner._build_test_harness(op, test_cases, callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.op"})
        assert "import json" in harness
        assert "gelu" in harness
        assert "128" in harness
        assert "256" in harness
        assert "time.perf_counter()" in harness

    def test_harness_with_empty_test_cases_uses_default(self):
        """Empty test_cases → harness uses default [1024] shape."""
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.operator import OperatorSpec

        runner = NPURunner(chip_version="A2")
        op = OperatorSpec(name="test_op")
        harness = runner._build_test_harness(op, [], callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.op"})
        assert "1024" in harness

    def test_harness_with_arange_generator(self):
        """generator='arange' → harness uses np.arange data init path."""
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.operator import OperatorSpec
        from ascendc_devkit.domain.requirement import TestCase

        runner = NPURunner(chip_version="A2")
        op = OperatorSpec(name="test_op")
        test_cases = [
            TestCase(
                name="arange_test",
                generator="arange",
                generator_params={"seed": 1},
                inputs=[{"name": "x", "shape": [64], "dtype": "fp16"}],
            ),
        ]
        harness = runner._build_test_harness(op, test_cases, callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.op"})
        assert "arange" in harness
        # 总元素数从 np.prod(shape) 改为 _flatten_shape(shape)（TensorList 嵌套
        # shape 支持：[[d1,d2],...] → 展平计元素数），arange 路径消费其 total。
        assert "_flatten_shape" in harness
        assert "np.arange" in harness

    def test_harness_without_generator_defaults_to_random_uniform(self):
        """No generator specified → generates random_uniform data."""
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.operator import OperatorSpec
        from ascendc_devkit.domain.requirement import TestCase

        runner = NPURunner(chip_version="A2")
        op = OperatorSpec(name="test_op")
        test_cases = [
            TestCase(
                name="default_gen",
                inputs=[{"name": "x", "shape": [128], "dtype": "fp16"}],
            ),
        ]
        harness = runner._build_test_harness(op, test_cases, callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.op"})
        assert "random_uniform" in harness

    def test_harness_forwards_attrs_as_kwargs(self):
        """A2 (P8): a case with attrs serializes them and the harness forwards
        them as kwargs to BOTH kernel and golden, so non-default branches are
        actually exercised (e.g. exp with scale=1.5 instead of the default)."""
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.operator import OperatorSpec
        from ascendc_devkit.domain.requirement import TestCase

        runner = NPURunner(chip_version="A2")
        op = OperatorSpec(name="exp")
        test_cases = [
            TestCase(
                name="scale_branch",
                inputs=[{"name": "x", "shape": [64], "dtype": "fp16"}],
                attrs={"base": 2.0, "scale": 1.5, "shift": 1.0},
            ),
        ]
        harness = runner._build_test_harness(op, test_cases, callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.op"})
        # attrs values land in the serialized case payload
        assert "1.5" in harness and "scale" in harness
        # harness forwards attrs as kwargs to both kernel and golden
        assert "kernel_fn(*_npu_inputs, **_attrs)" in harness
        assert "golden_fn(*_np_inputs, **_attrs)" in harness

    def test_harness_attrless_case_still_single_kwargs_path(self):
        """A2 (P8): a case with no attrs keeps the same single code path
        (forwards **_attrs, an empty dict — a no-op). Attr-less operators
        regress to pure positional calls; no branching on attrs presence."""
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.operator import OperatorSpec
        from ascendc_devkit.domain.requirement import TestCase

        runner = NPURunner(chip_version="A2")
        op = OperatorSpec(name="add")
        test_cases = [
            TestCase(name="basic",
                     inputs=[{"name": "x", "shape": [64], "dtype": "fp16"}]),
        ]
        harness = runner._build_test_harness(op, test_cases, callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.op"})
        assert "kernel_fn(*_npu_inputs, **_attrs)" in harness
        assert "golden_fn(*_np_inputs, **_attrs)" in harness

    # —— per-input value_range / output_dtype (harness 数据生成 bug 修复) ——

    def test_harness_per_input_value_range_propagated(self):
        """每个 input 自带的 value_range 必须原样透传到 harness，禁止压扁成
        case 级单一 range 再广播。回归 case 7/12 假通过：clipped_swiglu 的
        group_index 该生成在 [1,2]，被错广播成 [-1,1] → sum≤0 → golden 全 0。"""
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.operator import OperatorSpec
        from ascendc_devkit.domain.requirement import TestCase

        runner = NPURunner(chip_version="A2")
        op = OperatorSpec(name="clipped_swiglu")
        test_cases = [
            TestCase(
                name="dim0_interleaved",
                inputs=[
                    {"name": "x", "shape": [48, 16], "dtype": "fp16",
                     "value_range": [-1.0, 1.0]},
                    {"name": "group_index", "shape": [28], "dtype": "int64",
                     "value_range": [1.0, 2.0]},
                ],
                attrs={"dim": 0, "interleaved": True},
            ),
        ]
        harness = runner._build_test_harness(op, test_cases, callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.op"})
        # 两个 input 各自的 range 都进 case payload（apply_adam_w 4 输入同理）。
        # harness 经 _json_to_py=pprint.pformat 序列化 test_cases，value_range 是
        # 单引号 Python dict repr（库上版 pprint 实现，防算子名 substring 误伤，
        # 非 json.dumps 双引号 JSON）。
        assert "'value_range': [-1.0, 1.0]" in harness
        assert "'value_range': [1.0, 2.0]" in harness
        # harness 按 per-input 列表取 range，不再用单一 _lo/_hi 广播
        assert "_vr_list" in harness
        assert "value_ranges=_vr_list" in harness
        assert "value_ranges=[[_lo, _hi] for _ in _tc['inputs']]" not in harness
        assert "_vr = _tc.get('value_range')" not in harness

    def test_harness_does_not_guess_output_dtype(self):
        """output dtype 不再从输入 dtype 猜测。原实现取第一个输入 dtype 当输出
        dtype，对 argmax（fp16→int64）/cast 是反例——输出 dtype 与输入 dtype 间无
        一般关系。真实输出 dtype 由 runtime compare_tensors 返回（_sr.dtype），
        harness 无需也禁止提前猜测。故 case payload 与模板里都不应残留
        output_dtype / _out_dtype。"""
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.operator import OperatorSpec
        from ascendc_devkit.domain.requirement import TestCase

        runner = NPURunner(chip_version="A2")
        op = OperatorSpec(name="clipped_swiglu")
        test_cases = [
            TestCase(
                name="idx_case",
                inputs=[
                    {"name": "x", "shape": [48, 16], "dtype": "fp16"},
                    {"name": "group_index", "shape": [28], "dtype": "int64"},
                ],
            ),
        ]
        harness = runner._build_test_harness(op, test_cases, callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.op"})
        # case payload 不再携带 output_dtype 字段；模板不再定义/使用 _out_dtype
        assert "output_dtype" not in harness
        assert "_out_dtype" not in harness

    def test_harness_input_without_value_range_falls_back_to_gen(self):
        """无 per-input value_range 的 input 回退到 GEN_LOW/GEN_HIGH，harness
        仍生成有效代码（单输入无 range 行为与修复前等价）。"""
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.operator import OperatorSpec
        from ascendc_devkit.domain.requirement import TestCase

        runner = NPURunner(chip_version="A2")
        op = OperatorSpec(name="exp")
        test_cases = [
            TestCase(name="no_vr",
                     inputs=[{"name": "x", "shape": [64], "dtype": "fp16"}]),
        ]
        harness = runner._build_test_harness(op, test_cases, callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.op"})
        assert "_vr_list" in harness
        assert "GEN_LOW" in harness and "GEN_HIGH" in harness
        # 该 input 未序列化 value_range 字段（带冒号区分 _i.get('value_range')）
        assert "'value_range':" not in harness

    def test_harness_per_input_value_range_inf_nan_sentinels(self):
        """per-input value_range 含 inf/nan（apply_adam_w case12 [-inf,inf] /
        case13 [nan,nan]）时，loader 的 float() 已把 csv 字符串 "-inf"/"nan"
        转成真 float；runner 序列化用 __INF__/__NAN__/__NINF__ sentinel 避开
        JSON NaN/Infinity 限制，harness _resolve_vr 还原回 float。整条链对
        inf/nan 等价普通数值。"""
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.operator import OperatorSpec
        from ascendc_devkit.domain.requirement import TestCase

        runner = NPURunner(chip_version="A2")
        op = OperatorSpec(name="apply_adam_w")
        test_cases = [
            TestCase(
                name="inf_nan_case",
                inputs=[
                    {"name": "var", "shape": [8], "dtype": "fp32",
                     "value_range": [float("-inf"), float("inf")]},
                    {"name": "exp_avg", "shape": [8], "dtype": "fp32",
                     "value_range": [float("nan"), float("nan")]},
                ],
            ),
        ]
        harness = runner._build_test_harness(op, test_cases, callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.op"})
        # sentinel 序列化（避开 JSON NaN/Infinity）
        assert "'__NINF__'" in harness and "'__INF__'" in harness
        assert "'__NAN__'" in harness
        # harness 运行时还原为 float
        assert "float('-inf')" in harness
        assert "float('inf')" in harness
        assert "float('nan')" in harness
        # per-input 列表仍生效（不被 inf/nan 短路）
        assert "value_ranges=_vr_list" in harness

    # —— A4: golden contract (P9, D1/D2/D3) ——

    def test_harness_golden_contract_resolves_entry_and_torch_type(self):
        """A4/D3: given a golden contract (cann-bench style: entry=op name,
        input_type=torch), the harness emits code that loads the source golden,
        resolves the entry BY NAME, converts numpy→torch, and exposes a single
        reference wrapper. String assertion — no real machine needed."""
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.operator import OperatorSpec
        from ascendc_devkit.domain.requirement import TestCase

        runner = NPURunner(chip_version="A2")
        op = OperatorSpec(name="exp")
        test_cases = [TestCase(name="c",
                               inputs=[{"name": "x", "shape": [8], "dtype": "fp16"}])]
        contract = {
            "path": "tasks/level1/exp/golden.py",
            "entry": "exp",
            "input_type": "torch",
        }
        harness = runner._build_test_harness(
            op, test_cases, golden_contract=contract, callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.op"})
        # contract values flow into the harness
        assert "golden_entry = 'exp'" in harness
        assert "golden_input_type = 'torch'" in harness
        assert "tasks/level1/exp/golden.py" in harness
        # entry resolved by name (getattr by golden_entry), not a hardcoded fallback
        assert "getattr(golden_mod, golden_entry" in harness
        # torch conversion present for input_type=torch
        assert "torch.from_numpy" in harness
        # D3 collapse: the run/compute fallback chain is gone (single entry)
        assert "golden_mod, 'run'" not in harness
        assert "golden_mod, 'compute'" not in harness

    def test_harness_golden_contract_numpy_skips_torch_conversion(self):
        """A4: input_type=numpy (hand-written fixture convention) → no
        numpy→torch conversion emitted; golden fed numpy arrays directly."""
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.operator import OperatorSpec
        from ascendc_devkit.domain.requirement import TestCase

        runner = NPURunner(chip_version="A2")
        op = OperatorSpec(name="add")
        test_cases = [TestCase(name="c",
                               inputs=[{"name": "x", "shape": [8], "dtype": "fp16"}])]
        contract = {"path": "/abs/golden.py", "entry": "reference", "input_type": "numpy"}
        harness = runner._build_test_harness(
            op, test_cases, golden_contract=contract, callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.op"})
        assert "golden_input_type = 'numpy'" in harness
        assert "golden_entry = 'reference'" in harness

    def test_harness_no_golden_contract_is_none(self):
        """A4: no golden contract → golden_fn stays None (existing no-golden
        behavior: results = -1.0, bottleneck=no_golden). Zero regression for
        paths that legitimately run without a golden."""
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.operator import OperatorSpec

        runner = NPURunner(chip_version="A2")
        op = OperatorSpec(name="add")
        harness = runner._build_test_harness(op, [], golden_contract=None, callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.op"})
        assert "golden_fn = None" in harness or "golden_fn = _golden_wrap" in harness
        # no source path baked in
        assert "golden_source_path = None" in harness

    def test_execute_with_npu_unavailable_raises(self):
        """P1: NPURunner is pure executor — unavailable NPU always raises, no fallback."""
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.operator import OperatorSpec
        from ascendc_devkit.domain.exceptions import EnvironmentNotAvailableError

        runner = NPURunner(chip_version="A2")
        runner._torch_npu_available = False
        with pytest.raises(EnvironmentNotAvailableError, match="torch_npu"):
            runner.execute(OperatorSpec(name="test"), [], npu_id=0)

    def test_execute_smoke_test_added(self):
        """P1: smoke test verifies NPU is truly functional, not just importable."""
        from ascendc_devkit.adapters.npu.runner import NPURunner
        runner = NPURunner()
        info = runner._env_info
        assert "torch_npu_available" in info
        # Smoke test should detect real NPU availability (not just import)
        assert isinstance(runner._torch_npu_available, bool)

    # —— multi-output / structured-input operators (moe_re_routing L3) ——
    # The harness was built for single-input/single-output ops (exp/add/sqrt).
    # moe_re_routing is the first multi-output (4 outputs) + optional-input +
    # integer-input + structurally-constrained (sum==A) operator, exposing 5
    # latent gaps. These pin the fixes so single-output ops don't regress.

    def test_harness_compares_every_output_not_just_first(self):
        """Fix A: multi-output op (kernel returns a tuple) → the harness compares
        EVERY output via a _to_np_list + zip loop, not ``kernel_out[0]`` (which
        silently dropped outputs 2..N). String assertion — no real machine."""
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.operator import OperatorSpec
        from ascendc_devkit.domain.requirement import TestCase

        runner = NPURunner(chip_version="A2")
        op = OperatorSpec(name="moe_re_routing")
        test_cases = [TestCase(name="c",
                               inputs=[{"name": "x", "shape": [8], "dtype": "fp16"}])]
        harness = runner._build_test_harness(op, test_cases, callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.op"})
        # the old single-output slice is gone
        assert "kernel_out[0]" not in harness
        # multi-output normalization + zip-compare present: kernel and golden
        # are both normalized via _to_np_list, then zip-compared output-by-output
        # (fused with the precision-debug diagnostics: enumerate → output_index).
        assert "_to_np_list" in harness
        # FALLBACK path now uses compare_outputs (MERE/MARE) instead of raw zip loop
        assert "compare_outputs" in harness

    # —— proto idx 语义（compare:false + index_gather，TopK 类算子）——

    def test_harness_bakes_ignore_indices(self):
        """proto ``compare: false`` 输出 → harness 烘焙 ``_IGNORE_INDICES`` 并在
        两条比较路径（fallback compare_outputs / CANN _compare_tensors）传参。"""
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.operator import OperatorSpec, TensorSpec
        from ascendc_devkit.domain.requirement import TestCase

        runner = NPURunner(chip_version="A2")
        op = OperatorSpec(
            name="top_k",
            outputs=[
                TensorSpec(name="y", dtype="fp16", shape=["K"]),
                TensorSpec(name="idx", dtype="int64", shape=["K"], compare=False),
            ],
        )
        test_cases = [TestCase(name="c",
                               inputs=[{"name": "x", "shape": [8], "dtype": "fp16"}])]
        harness = runner._build_test_harness(
            op, test_cases,
            callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.op"})
        assert "_IGNORE_INDICES = [1]" in harness
        assert "ignore_indices=_IGNORE_INDICES" in harness        # fallback 路径
        assert "ignore_output_indices=_IGNORE_INDICES" in harness  # CANN 路径

    def test_harness_bakes_index_gather_specs(self):
        """proto ``index_gather`` → harness 烘焙 ``_INDEX_GATHER``（名字已解析为
        索引）+ fallback 路径 compare_outputs 传参。"""
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.operator import OperatorSpec, TensorSpec
        from ascendc_devkit.domain.requirement import TestCase

        runner = NPURunner(chip_version="A2")
        op = OperatorSpec(
            name="top_k",
            inputs=[TensorSpec(name="x", dtype="fp16", shape=["N"])],
            outputs=[
                TensorSpec(name="y", dtype="fp16", shape=["K"]),
                TensorSpec(name="idx", dtype="int64", shape=["K"], compare=False,
                           index_gather={"input": "x", "dim_attr": "dim",
                                         "value_output": "y"}),
            ],
        )
        test_cases = [TestCase(name="c",
                               inputs=[{"name": "x", "shape": [8], "dtype": "fp16"}])]
        harness = runner._build_test_harness(
            op, test_cases,
            callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.op"})
        assert ("_INDEX_GATHER = {1: {'input_idx': 0, 'dim_attr': 'dim', "
                "'value_output_idx': 0}}" in harness)
        assert "index_gather_specs=_INDEX_GATHER" in harness
        assert "inputs=_torch_in" in harness
        assert "case_attrs=_attrs" in harness

    def test_harness_index_gather_unresolvable_raises(self):
        """index_gather 引用的 input/value_output 名字解析不到 → 加载期
        HarnessContractError（§1.3 暴露配置问题，不静默丢弃）。"""
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.exceptions import HarnessContractError
        from ascendc_devkit.domain.operator import OperatorSpec, TensorSpec
        from ascendc_devkit.domain.requirement import TestCase

        runner = NPURunner(chip_version="A2")
        op = OperatorSpec(
            name="top_k",
            inputs=[TensorSpec(name="x", dtype="fp16", shape=["N"])],
            outputs=[
                TensorSpec(name="y", dtype="fp16", shape=["K"]),
                TensorSpec(name="idx", dtype="int64", shape=["K"],
                           index_gather={"input": "x", "dim_attr": "dim",
                                         "value_output": "nonexistent"}),
            ],
        )
        test_cases = [TestCase(name="c",
                               inputs=[{"name": "x", "shape": [8], "dtype": "fp16"}])]
        with pytest.raises(HarnessContractError, match="value_output"):
            runner._build_test_harness(
                op, test_cases,
                callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.op"})

    def test_harness_loads_optional_get_input(self):
        """Fix D: when a golden module is loaded, the harness also resolves an
        optional ``get_input`` (structural-validity fixer). moe_re_routing
        enforces sum(expert_token_num)==A; random ints violate it, so the golden
        ships a get_input that redistributes. Without calling it every case
        hits the golden's assert → 999 → spurious exhaust."""
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.operator import OperatorSpec
        from ascendc_devkit.domain.requirement import TestCase

        runner = NPURunner(chip_version="A2")
        op = OperatorSpec(name="moe_re_routing")
        test_cases = [TestCase(name="c",
                               inputs=[{"name": "x", "shape": [8], "dtype": "fp16"}])]
        contract = {"path": "tasks/level3/moe_re_routing/golden.py",
                    "entry": "moe_re_routing", "input_type": "torch"}
        harness = runner._build_test_harness(
            op, test_cases, golden_contract=contract, callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.op"})
        # get_input resolved from the golden module (None-safe: absent → skipped)
        assert "_get_input = getattr(golden_mod, 'get_input', None)" in harness
        assert "if _get_input is not None:" in harness

    def test_harness_golden_tuple_to_numpy_list(self):
        """Fix B: a golden returning a tuple/list of tensors (moe_re_routing →
        4 outputs) is converted to a list of numpy arrays, not a single array
        (np.asarray on a tuple shapes-merges → nonsense diff)."""
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.operator import OperatorSpec
        from ascendc_devkit.domain.requirement import TestCase

        runner = NPURunner(chip_version="A2")
        op = OperatorSpec(name="moe_re_routing")
        test_cases = [TestCase(name="c",
                               inputs=[{"name": "x", "shape": [8], "dtype": "fp16"}])]
        harness = runner._build_test_harness(op, test_cases, callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.op"})
        assert "def _to_np(" in harness
        assert "def _to_np_list(" in harness
        # _golden_wrap normalizes via _to_np_list (no single-Tensor-only branch)
        assert "return _to_np_list(_out)" in harness

    def test_harness_np_dict_covers_integer_dtypes(self):
        """Fix F: _NP must map int32/int64 (moe_re_routing's
        expert_token_num_per_rank is int32/int64). Without them gen_input
        silently defaulted to float16 → integer ops on float garbage."""
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.operator import OperatorSpec
        runner = NPURunner(chip_version="A2")
        op = OperatorSpec(name="moe_re_routing")
        harness = runner._build_test_harness(op, [], callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.op"})
        assert "'int32': np.int32" in harness
        assert "'int64': np.int64" in harness

    # —— card value reaches the NPU subprocess spawn boundary (op-level pin) ——
    # NPURunner.execute receives npu_id = the authoritative op card resolved once
    # at the dispatch boundary (resolve_op_card / op-level lease) — the runner
    # never touches the pool. The card must land in BOTH real injection points —
    # the subprocess env via card_pin_env (ASCEND_RT_VISIBLE_DEVICES=<physical>
    # with remap semantics + ASCEND_NPU_ID=0) and the harness body (set_device(0),
    # the remapped logical id). Only the OS subprocess boundary is mocked (to
    # capture, since no real NPU); NPURunner + card_pin_env are real (§3.9 real
    # link guarded; §3.5 no real NPU → no npu marker). This is the runner-side
    # analog of the CLI --npu-id → task_request UT.

    @staticmethod
    def _capture_subprocess_run():
        """Mock subprocess.run capturing env + reading the harness tempfile.

        execute writes the harness to a NamedTemporaryFile(delete=False) and
        unlinks it in a ``finally`` after subprocess.run returns — so the harness
        must be read INSIDE the fake run, before the finally fires. Returns a
        (captured-dict, side_effect) pair."""
        from subprocess import CompletedProcess
        captured: dict = {}

        def _fake(argv, **kwargs):
            harness_path = argv[1]  # [sys.executable, harness_path]
            captured["env"] = dict(kwargs.get("env", {}))
            captured["harness"] = Path(harness_path).read_text()
            return CompletedProcess(
                args=argv, returncode=0,
                stdout='{"total_ms":1.0,"max_diff":0.0}', stderr="",
            )
        return captured, _fake

    def test_npu_id_hard_pin_flows_to_subprocess_env_and_harness(self):
        """P13 (step-116)：npu_id=2（dispatch 解析的权威 op 卡）→ spawn env 双
        变量 pin（VISIBLE_DEVICES=2 + NPU_ID=0）+ harness set_device(0)（remap
        后逻辑号）。物理卡只由 VISIBLE_DEVICES 携带；runner 不再碰池。"""
        from unittest import mock
        from types import SimpleNamespace
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.requirement import TestCase
        runner = NPURunner(chip_version="A2")
        runner._torch_npu_available = True  # bypass availability gate (its own UT)
        captured, fake = self._capture_subprocess_run()
        with mock.patch("ascendc_devkit.adapters.npu.runner.subprocess.run",
                        side_effect=fake):
            runner.execute(
                OperatorSpec(name="add"),
                [TestCase(name="c", inputs=[{"name": "x", "shape": [8], "dtype": "fp16"}])],
                npu_id=2,
                deploy_result=SimpleNamespace(
                    python_path="/tmp/p", install_path="/tmp/o", ld_library_path_add=""),
                callable_target={"kind": "torch_ops", "symbol": "cann_bench.add"},
            )
        assert captured["env"]["ASCEND_RT_VISIBLE_DEVICES"] == "2"
        assert captured["env"]["ASCEND_NPU_ID"] == "0"
        assert "set_device(0)" in captured["harness"]

    def test_op_card_flows_to_subprocess_env_as_pin_pair(self):
        """P13 (step-116)：npu_id = dispatch 解析的权威 op 卡 → spawn env 双变量
        pin（VISIBLE_DEVICES=物理卡 + NPU_ID=0）+ harness set_device(0)（remap
        后逻辑号）。span 级池租约已退役——runner 不再碰池。"""
        from unittest import mock
        from types import SimpleNamespace
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.requirement import TestCase
        runner = NPURunner(chip_version="A2")
        runner._torch_npu_available = True
        captured, fake = self._capture_subprocess_run()
        with mock.patch("ascendc_devkit.adapters.npu.runner.subprocess.run",
                        side_effect=fake):
            runner.execute(
                OperatorSpec(name="add"),
                [TestCase(name="c", inputs=[{"name": "x", "shape": [8], "dtype": "fp16"}])],
                npu_id=3,
                deploy_result=SimpleNamespace(
                    python_path="/tmp/p", install_path="/tmp/o", ld_library_path_add=""),
                callable_target={"kind": "torch_ops", "symbol": "cann_bench.add"},
            )
        assert captured["env"]["ASCEND_RT_VISIBLE_DEVICES"] == "3"
        assert captured["env"]["ASCEND_NPU_ID"] == "0"
        assert "set_device(0)" in captured["harness"]

    def test_execute_without_resolved_card_fails_fast(self):
        """None npu_id = 调用方跳过了唯一解析点——确定性报错而非静默落 0。"""
        from unittest import mock
        from types import SimpleNamespace
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.requirement import TestCase
        runner = NPURunner(chip_version="A2")
        runner._torch_npu_available = True
        captured, fake = self._capture_subprocess_run()
        with mock.patch("ascendc_devkit.adapters.npu.runner.subprocess.run",
                        side_effect=fake), pytest.raises(ValueError):
            runner.execute(
                OperatorSpec(name="add"),
                [TestCase(name="c", inputs=[{"name": "x", "shape": [8], "dtype": "fp16"}])],
                npu_id=None,
                deploy_result=SimpleNamespace(
                    python_path="/tmp/p", install_path="/tmp/o", ld_library_path_add=""),
                callable_target={"kind": "torch_ops", "symbol": "cann_bench.add"},
            )


class TestDevRecord:
    """write_dev_record tests for incremental mode (Slice 7)."""

    def test_write_dev_record_creates_file(self, tmp_path):
        """write_dev_record creates .lingxi/dev_record.md."""
        adapter = GenericRepositoryAdapter(_profile())
        op_dir = tmp_path / "ops" / "test_op"
        op_dir.mkdir(parents=True)

        entry = {
            "timestamp": "2026-05-28T10:00:00",
            "change_summary": "Optimized tiling",
            "target_files": ["kernel.cpp", "kernel.h"],
            "requirement_path": "/tmp/req.md",
        }
        record_path = adapter.write_dev_record(op_dir, entry)

        assert record_path.exists()
        assert record_path.name == "dev_record.md"
        assert record_path.parent.name == ".lingxi"
        content = record_path.read_text()
        assert "Optimized tiling" in content
        assert "kernel.cpp" in content
        assert "kernel.h" in content
        assert "/tmp/req.md" in content
        assert "2026-05-28T10:00:00" in content

    def test_write_dev_record_appends_newest_first(self, tmp_path):
        """New entries are prepended so newest comes first."""
        adapter = GenericRepositoryAdapter(_profile())
        op_dir = tmp_path / "ops" / "test_op"
        op_dir.mkdir(parents=True)

        entry1 = {
            "timestamp": "2026-05-28T09:00:00",
            "change_summary": "First change",
            "target_files": ["a.cpp"],
            "requirement_path": "req1",
        }
        adapter.write_dev_record(op_dir, entry1)

        entry2 = {
            "timestamp": "2026-05-28T10:00:00",
            "change_summary": "Second change",
            "target_files": ["b.cpp"],
            "requirement_path": "req2",
        }
        adapter.write_dev_record(op_dir, entry2)

        content = (op_dir / ".lingxi" / "dev_record.md").read_text()
        second_pos = content.index("Second change")
        first_pos = content.index("First change")
        assert second_pos < first_pos  # newer entry first

    def test_write_dev_record_creates_lingxi_dir(self, tmp_path):
        """.lingxi directory is created if it doesn't exist."""
        adapter = GenericRepositoryAdapter(_profile())
        op_dir = tmp_path / "ops" / "new_op"
        op_dir.mkdir(parents=True)
        # .lingxi does not exist yet

        entry = {
            "timestamp": "2026-05-28T10:00:00",
            "change_summary": "Initial implementation",
            "target_files": [],
            "requirement_path": "N/A",
        }
        record_path = adapter.write_dev_record(op_dir, entry)
        assert record_path.exists()
        assert (op_dir / ".lingxi").is_dir()


class TestNPUSlotManager:
    """Verify NPU Slot Manager device allocation."""

    def test_default_init(self):
        from ascendc_devkit.adapters.npu.slot import NPUSlotManager
        mgr = NPUSlotManager(max_devices=4)
        assert mgr.total_devices == 4
        assert mgr.available_count == 4

    def test_acquire_returns_id(self):
        from ascendc_devkit.adapters.npu.slot import NPUSlotManager
        mgr = NPUSlotManager(max_devices=4)
        npu_id = mgr.acquire()
        assert npu_id == 0
        assert npu_id in mgr.list_acquired()

    def test_acquire_specific_id(self):
        from ascendc_devkit.adapters.npu.slot import NPUSlotManager
        mgr = NPUSlotManager(max_devices=4)
        npu_id = mgr.acquire(npu_id=2)
        assert npu_id == 2
        assert 2 in mgr.list_acquired()

    def test_acquire_already_acquired_raises(self):
        from ascendc_devkit.adapters.npu.slot import NPUSlotManager
        mgr = NPUSlotManager(max_devices=4)
        mgr.acquire(npu_id=1)
        with pytest.raises(RuntimeError, match="already acquired"):
            mgr.acquire(npu_id=1)

    def test_acquire_invalid_id_raises(self):
        from ascendc_devkit.adapters.npu.slot import NPUSlotManager
        mgr = NPUSlotManager(max_devices=4)
        with pytest.raises(ValueError, match="out of range"):
            mgr.acquire(npu_id=99)

    def test_release(self):
        from ascendc_devkit.adapters.npu.slot import NPUSlotManager
        mgr = NPUSlotManager(max_devices=4)
        npu_id = mgr.acquire()
        assert npu_id in mgr.list_acquired()
        mgr.release(npu_id)
        assert npu_id not in mgr.list_acquired()

    def test_release_nonexistent_no_error(self):
        from ascendc_devkit.adapters.npu.slot import NPUSlotManager
        mgr = NPUSlotManager(max_devices=4)
        mgr.release(99)  # should not raise

    def test_list_available(self):
        from ascendc_devkit.adapters.npu.slot import NPUSlotManager
        mgr = NPUSlotManager(max_devices=4)
        assert mgr.list_available() == [0, 1, 2, 3]
        mgr.acquire(npu_id=0)
        mgr.acquire(npu_id=3)
        assert mgr.list_available() == [1, 2]

    def test_acquire_all_exhausts_nonblocking(self):
        # Phase 1 (P69 subprocess 级领卡)：acquire 改阻塞语义后，
        # timeout=0 = 非阻塞逃生口（旧行为的等价），池空立即 raise CardAcquireTimeout。
        from ascendc_devkit.adapters.npu.slot import NPUSlotManager
        from ascendc_devkit.domain.exceptions import CardAcquireTimeout
        mgr = NPUSlotManager(max_devices=2)
        mgr.acquire()
        mgr.acquire()
        with pytest.raises(CardAcquireTimeout, match="All 2 NPU devices"):
            mgr.acquire(timeout=0)

    def test_acquire_blocks_when_empty_then_wakes_on_release(self):
        # subprocess 级领卡核心：池空 acquire 阻塞等卡，他线程 release 后唤醒。
        from ascendc_devkit.adapters.npu.slot import NPUSlotManager
        mgr = NPUSlotManager(max_devices=1)
        mgr.acquire()  # 占满唯一卡
        acquired: list[int] = []

        def waiter():
            acquired.append(mgr.acquire(timeout=5))

        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.2)  # 等 waiter 进入 acquire 阻塞
        mgr.release(0)   # 唤醒 waiter
        t.join(timeout=5)
        assert not t.is_alive(), "waiter thread blocked past release + join timeout"
        assert acquired == [0]

    def test_acquire_timeout_raises_card_acquire_timeout(self):
        from ascendc_devkit.adapters.npu.slot import NPUSlotManager
        from ascendc_devkit.domain.exceptions import CardAcquireTimeout
        mgr = NPUSlotManager(max_devices=1)
        mgr.acquire()  # 占满
        start = time.monotonic()
        with pytest.raises(CardAcquireTimeout):
            mgr.acquire(timeout=0.3)
        elapsed = time.monotonic() - start
        # 至少等了 ~0.3s（吸收调度抖动，给下界）
        assert elapsed >= 0.25

    def test_acquire_context_releases_on_normal_exit(self):
        from ascendc_devkit.adapters.npu.slot import NPUSlotManager
        mgr = NPUSlotManager(max_devices=2)
        with mgr.acquire_context(timeout=1) as card:
            assert card in mgr.list_acquired()
        # 退出后还卡
        assert mgr.list_acquired() == []
        assert mgr.available_count == 2

    def test_acquire_context_releases_on_exception(self):
        from ascendc_devkit.adapters.npu.slot import NPUSlotManager
        mgr = NPUSlotManager(max_devices=2)

        class _Boom(Exception):
            pass

        with pytest.raises(_Boom):
            with mgr.acquire_context(timeout=1) as card:
                assert card in mgr.list_acquired()
                raise _Boom("subprocess crashed mid-flight")
        # 异常路径也还卡（subprocess timeout/crash 等价语义）
        assert mgr.list_acquired() == []

    def test_acquire_hard_pin_specific_card(self):
        # 硬领（--npu-id / task npu_id）语义保留：指定卡可领、被占即 raise（不阻塞）。
        from ascendc_devkit.adapters.npu.slot import NPUSlotManager
        mgr = NPUSlotManager(max_devices=4)
        assert mgr.acquire(npu_id=3) == 3
        with pytest.raises(RuntimeError, match="already acquired"):
            mgr.acquire(npu_id=3)

    def test_allowed_subset_restricts_pool(self):
        # batch 卡池四级 fallback 的结果以 allowed 子集限定可用卡。
        from ascendc_devkit.adapters.npu.slot import NPUSlotManager
        mgr = NPUSlotManager(max_devices=8, allowed=[0, 2])
        assert mgr.list_available() == [0, 2]
        assert mgr.acquire() == 0
        assert mgr.acquire() == 2
        # allowed 子集耗尽 → 池空
        from ascendc_devkit.domain.exceptions import CardAcquireTimeout
        with pytest.raises(CardAcquireTimeout):
            mgr.acquire(timeout=0)
        # allowed 外的卡即便在 max_devices 内也不可领
        with pytest.raises(ValueError, match="out of range|not in allowed"):
            mgr.acquire(npu_id=5)

    def test_dead_card_warns_when_lease_exceeds_threshold(self, caplog):
        # 死卡检测（best-effort 诊断）：某卡被领时间超阈值且池空时 acquire 打 warn，
        # 不强制回收（强制回收需 lease，L3 §2.1 否定项）。
        import logging
        from ascendc_devkit.adapters.npu.slot import NPUSlotManager
        from ascendc_devkit.domain.exceptions import CardAcquireTimeout
        mgr = NPUSlotManager(max_devices=1, lease_warn_threshold=0.05)
        mgr.acquire()  # 卡 0 lease 计时开始
        time.sleep(0.1)  # 超 0.05s 阈值
        with caplog.at_level(logging.WARNING):
            with pytest.raises(CardAcquireTimeout):
                mgr.acquire(timeout=0)  # 池空触发死卡检测
        msgs = [r.getMessage() for r in caplog.records]
        assert any("lease" in m.lower() or "long" in m.lower() for m in msgs), msgs

    def test_acquire_after_release(self):
        from ascendc_devkit.adapters.npu.slot import NPUSlotManager
        mgr = NPUSlotManager(max_devices=2)
        a = mgr.acquire()
        b = mgr.acquire()
        mgr.release(a)
        c = mgr.acquire()
        assert c == a
        assert mgr.available_count == 0


class TestPTAToolchain:
    """Verify PTA Toolchain code generation and build."""

    def test_generate_basic_op(self):
        from ascendc_devkit.adapters.toolchain.pta import PTAToolchain
        from ascendc_devkit.domain.operator import OperatorSpec

        tc = PTAToolchain()
        op_spec = OperatorSpec(name="gelu")
        source = tc.generate(op_spec)

        assert "def gelu" in source
        assert "torch.ops.custom_ops.gelu" in source
        assert "Library" in source

    def test_generate_includes_schema(self):
        from ascendc_devkit.adapters.toolchain.pta import PTAToolchain
        from ascendc_devkit.domain.operator import OperatorSpec

        tc = PTAToolchain()
        op_spec = OperatorSpec(name="addmm")
        source = tc.generate(op_spec)

        assert "addmm(Tensor x) -> Tensor" in source

    def test_build_writes_file(self, tmp_path):
        from ascendc_devkit.adapters.toolchain.pta import PTAToolchain
        from ascendc_devkit.domain.operator import OperatorSpec

        tc = PTAToolchain()
        op_spec = OperatorSpec(name="gelu")
        code = tc.generate(op_spec)

        result = tc.build(code, tmp_path / "pta_output")
        assert result.passed
        assert result.stubbed
        pta_file = tmp_path / "pta_output" / "pta_registration.py"
        assert pta_file.exists()
        content = pta_file.read_text()
        assert "def gelu" in content

    def test_build_creates_output_dir(self, tmp_path):
        from ascendc_devkit.adapters.toolchain.pta import PTAToolchain
        from ascendc_devkit.domain.operator import OperatorSpec

        tc = PTAToolchain()
        op_spec = OperatorSpec(name="gelu")
        code = tc.generate(op_spec)

        out_dir = tmp_path / "nonexistent" / "pta_output"
        result = tc.build(code, out_dir)
        assert result.passed
        assert out_dir.exists()

    def test_pta_registration_dataclass(self):
        from ascendc_devkit.adapters.toolchain.pta import PTARegistration

        reg = PTARegistration(
            source="print('hello')",
            op_name="gelu",
            namespace="custom_ops",
        )
        assert reg.full_name == "torch.ops.custom_ops.gelu"
        assert "gelu" in reg.call_signature


# —— NPU chip detection + compatibility (canonical = A2/A3/A5) ——

class TestChipDetection:
    @pytest.fixture(autouse=True)
    def _fresh_probe_cache(self, monkeypatch):
        """step 104 进程级探测缓存：用例间隔离（fake 硬件每例不同）。"""
        import ascendc_devkit.adapters.npu.detect as detect_mod
        monkeypatch.setattr(detect_mod, "_PROBE_CACHE", None)

    def test_detect_returns_known_generation(self):
        """detect_chip_version 返回契约：∈ {A2, A3, A5, UNKNOWN}。

        无 NPU（torch_npu 不可用 / 0 设备 / 未知设备名）时返回 UNKNOWN（§3.7 诚实，
        不静默猜 A2——见 detect.py）；有 NPU 时返回真实代际。UT 守「返回值必在文档集合
        内、不返回垃圾串」这一确定性契约；真实硬件探测属 ST（@pytest.mark.npu），
        UT 不探机（§3.8 纯逻辑）。"""
        from ascendc_devkit.adapters.npu.detect import detect_chip_version
        from ascendc_devkit.domain.chip import CHIP_GENERATIONS, UNKNOWN
        chip = detect_chip_version()
        assert chip in {*CHIP_GENERATIONS, UNKNOWN}

    def _stub_torch_npu(self, monkeypatch, device_name):
        import sys, types
        fake = types.ModuleType("torch_npu")

        class _Npu:
            @staticmethod
            def device_count():
                return 1

            @staticmethod
            def get_device_name(idx):
                return device_name

        fake.npu = _Npu()
        monkeypatch.setitem(sys.modules, "torch_npu", fake)

    def test_detect_maps_910c_to_a3(self, monkeypatch):
        """Regression: 910C must map to A3, NOT be mis-read as 910B/A2 via the
        bare "Ascend910" prefix (the bug that existed before generation naming)."""
        self._stub_torch_npu(monkeypatch, "Ascend910C1")
        from ascendc_devkit.adapters.npu.detect import detect_chip_version
        assert detect_chip_version() == "A3"

    def test_detect_maps_910b_to_a2(self, monkeypatch):
        """910B maps to A2 (corrects the old drift where detect called it A3)."""
        self._stub_torch_npu(monkeypatch, "Ascend910B3")
        from ascendc_devkit.adapters.npu.detect import detect_chip_version
        assert detect_chip_version() == "A2"

    def test_detect_maps_950_to_a5(self, monkeypatch):
        self._stub_torch_npu(monkeypatch, "Ascend950")
        from ascendc_devkit.adapters.npu.detect import detect_chip_version
        assert detect_chip_version() == "A5"


class TestChipMismatchReason:
    """chip_mismatch_reason — single-source precondition message (§1.9, §2.5).

    The codegen precondition (validate_inputs) + deploy's deep-defense entry both
    call this ONE helper, so design≠runtime is diagnosed by a single comparison
    with a single concrete message. Pure comparison (step-34): the runtime chip
    was resolved once at dispatch, so this is a cheap pure gate with NO
    NPU-driver I/O. Returns None on match / empty design; a reason naming BOTH
    values otherwise.

    runtime=UNKNOWN (probe couldn't identify the hardware) is a DISTINCT
    non-mismatch state: surfaced as a "cannot verify" reason, not silently passed
    nor reported as a design≠hardware mismatch.

    The retired ``assume_chip`` bypass and the probe-timeout propagation formerly
    tested here moved with their behavior: ``assume_chip`` is gone entirely
    (§1.4 — ``--runtime_target_chip`` is a different, fallback-only semantic), and
    a probe timeout is handled at dispatch via ``--runtime_target_chip`` fallback
    / ``EX_DATAERR`` (covered by test_dispatcher_chip_resolution.py) — the gate no
    longer probes, so there is no timeout path here to test.
    """

    def test_match_returns_none(self):
        from ascendc_devkit.adapters.npu.detect import chip_mismatch_reason
        assert chip_mismatch_reason("A2", "A2") is None

    def test_mismatch_names_both_values(self):
        from ascendc_devkit.adapters.npu.detect import chip_mismatch_reason
        reason = chip_mismatch_reason("A5", "A2")
        assert reason is not None
        assert "'A5'" in reason   # the design target surfaces
        assert "'A2'" in reason   # the runtime hardware surfaces
        assert "design_target_chip" in reason  # actionable fix hint

    def test_empty_design_is_no_constraint(self):
        # Empty design → no build constraint (mirrors deploy's empty-chip
        # auto-detect): don't block, return None.
        from ascendc_devkit.adapters.npu.detect import chip_mismatch_reason
        assert chip_mismatch_reason("", "A2") is None
        assert chip_mismatch_reason(None, "A2") is None  # defensive: None like ""

    def test_forward_compat_low_gen_on_high_gen(self):
        # P65: compatibility is by programming model. A2/A3 are Membase; A5
        # hardware runs Membase (backward compatible), so a low-gen Membase
        # design is forward-compatible with an A5 box — NOT a mismatch. This is
        # the reverse direction of the (A5,A2) hard block in test_mismatch_names
        # _both_values, and was wrongly reported as a mismatch before the matrix.
        from ascendc_devkit.adapters.npu.detect import chip_mismatch_reason
        assert chip_mismatch_reason("A2", "A5") is None
        assert chip_mismatch_reason("A3", "A5") is None

    def test_membase_portable_across_a2_a3(self):
        # A2↔A3 are the same Membase generation — portable, never a mismatch.
        from ascendc_devkit.adapters.npu.detect import chip_mismatch_reason
        assert chip_mismatch_reason("A2", "A3") is None
        assert chip_mismatch_reason("A3", "A2") is None

    def test_runtime_unknown_is_distinct_cannot_verify(self):
        from ascendc_devkit.adapters.npu.detect import chip_mismatch_reason
        from ascendc_devkit.domain import chip
        reason = chip_mismatch_reason("A5", chip.UNKNOWN)
        assert reason is not None
        assert "无法校验" in reason or "未知" in reason
        assert "不兼容" not in reason  # distinct from a true incompatibility


class TestDetectProbeTimeout:
    """detect_chip_version bounds the torch_npu probe in a daemon thread so a
    hung driver (hdcdrv_connect_wait_reply — a kernel ioctl with no
    Python-visible exception) can't block the run indefinitely (§3.7 honest
    error: report it, don't hang). A healthy probe is sub-second; the bound
    cleanly separates "healthy" from "stuck"."""

    def test_returns_chip_when_probe_completes_fast(self, monkeypatch):
        # Fast probe → completes well within the bound → returns its value.
        # (step 104: probe signature carries timeout_sec for the subprocess path.)
        from ascendc_devkit.adapters.npu.detect import detect_chip_version
        monkeypatch.setattr(
            "ascendc_devkit.adapters.npu.detect._probe_chip_blocking",
            lambda timeout_sec=None: "A5")
        assert detect_chip_version(timeout_sec=1.0) == "A5"

    def test_raises_when_probe_exceeds_bound(self, monkeypatch):
        # Probe that blocks longer than the bound → join() times out → raise
        # EnvironmentProbeTimeout, returned NEAR the bound (not after the sleep).
        from ascendc_devkit.adapters.npu.detect import (
            detect_chip_version, EnvironmentProbeTimeout)

        def _slow(timeout_sec=None):
            time.sleep(2)
            return "A5"
        monkeypatch.setattr(
            "ascendc_devkit.adapters.npu.detect._probe_chip_blocking", _slow)
        start = time.monotonic()
        with pytest.raises(EnvironmentProbeTimeout):
            detect_chip_version(timeout_sec=0.1)
        elapsed = time.monotonic() - start
        assert elapsed < 1.0   # bounded: did NOT wait for the 2s sleep


class TestChipDisplay:
    def test_display_name_covers_generations(self):
        from ascendc_devkit.domain.chip import chip_display_name
        assert "950" in chip_display_name("A5")
        assert "910B" in chip_display_name("A2")
        assert "910C" in chip_display_name("A3")

    def test_unknown_chip_returns_raw_string(self):
        from ascendc_devkit.domain.chip import chip_display_name
        assert chip_display_name("A9") == "A9"
