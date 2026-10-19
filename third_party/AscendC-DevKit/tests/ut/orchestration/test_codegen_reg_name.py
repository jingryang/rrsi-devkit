"""UT: codegen AICore 注册名派生源机械校验（P 361001 / adaptive_avg_pool_3d）。

判据（近零误判）：op_host/*_def.cpp 的 ``OP_ADD`` / op_api/*.cpp 的
``ADD_TO_LAUNCHER_LIST_AICORE`` 首参 = driver kernel 注册 Pascal。CANN runtime 按它反推
config 文件名去找落盘 config；注册名若抄 proto 数字段大写（``AdaptiveAvgPool3D``），反推
候选不命中落盘目录名（``op_name`` snake）→ 361001。正确写法 = 从 ``op_name`` 经
snake_to_pascal 派生（每 ``_`` 段 capitalize），必命中。

- torch 的 ``m.def``/``op_plugin`` **不**参与比对——它驱动 eval 符号、可合法加前缀，
  与 config 查找无直接因果。
"""
from __future__ import annotations

from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.codegen import CodegenStage


def _stage_state(artifacts: dict, op_name: str = "adaptive_avg_pool_3d"):
    return CodegenStage(), State(mode="new", op_name=op_name), artifacts


def _def_cpp(reg: str) -> str:
    return f"""
namespace ops {{
class {reg} : public OpDef {{
public:
    explicit {reg}(const char *name) : OpDef(name) {{
        this->Input("x").ParamType(REQUIRED).DataType({{ge::DT_FLOAT}});
        this->Output("y").ParamType(REQUIRED).DataType({{ge::DT_FLOAT}});
    }}
}};
OP_ADD({reg});
}}  // namespace ops
"""


def _op_api_cpp(reg: str) -> str:
    return f"""
#include "op_api_common.h"

static const aclTensor* {reg}AiCore(const aclTensor* x, aclOpExecutor* executor) {{
    auto ret = ADD_TO_LAUNCHER_LIST_AICORE({reg}, OP_INPUT(x), OP_OUTPUT(out));
    return out;
}}
"""


class TestAicoreRegistrationMismatch:
    def test_def_cpp_proto_copy_blocked(self):
        """op_host def.cpp OP_ADD 抄 proto(AdaptiveAvgPool3D) → 命中 reg_name_mismatch。"""
        stage, state, artifacts = _stage_state(
            {"op_host/adaptive_avg_pool_3d_def.cpp": _def_cpp("AdaptiveAvgPool3D")})
        err = stage._aicore_registration_mismatch_error(state, artifacts)
        assert err is not None, "proto 大写 D 应命中"
        assert err.details["reason"] == "reg_name_mismatch"
        assert err.details["registered_name"] == "AdaptiveAvgPool3D"
        assert err.details["expected_derived"] == "AdaptiveAvgPool3d"

    def test_def_cpp_derived_passes(self):
        """op_host def.cpp OP_ADD 从 op_name 派生(AdaptiveAvgPool3d) → 放行。"""
        stage, state, artifacts = _stage_state(
            {"op_host/adaptive_avg_pool_3d_def.cpp": _def_cpp("AdaptiveAvgPool3d")})
        assert stage._aicore_registration_mismatch_error(state, artifacts) is None

    def test_op_api_proto_copy_blocked(self):
        """op_api ADD_TO_LAUNCHER_LIST_AICORE 抄 proto → 命中。"""
        stage, state, artifacts = _stage_state(
            {"op_api/adaptive_avg_pool_3d.cpp": _op_api_cpp("AdaptiveAvgPool3D")})
        err = stage._aicore_registration_mismatch_error(state, artifacts)
        assert err is not None
        assert err.details["reason"] == "reg_name_mismatch"
        assert err.details["macro"] == "ADD_TO_LAUNCHER_LIST_AICORE"

    def test_op_api_derived_passes(self):
        """op_api ADD_TO_LAUNCHER_LIST_AICORE 从 op_name 派生 → 放行。"""
        stage, state, artifacts = _stage_state(
            {"op_api/adaptive_avg_pool_3d.cpp": _op_api_cpp("AdaptiveAvgPool3d")})
        assert stage._aicore_registration_mismatch_error(state, artifacts) is None

    def test_no_boundary_disk_derived_passes(self):
        """无 pool/3d 边界的落盘名(adaptive_avg_pool3d) + 派生注册 → 放行。"""
        stage = CodegenStage()
        state = State(mode="new", op_name="adaptive_avg_pool3d")
        artifacts = {"op_host/adaptive_avg_pool3d_def.cpp": _def_cpp("AdaptiveAvgPool3d")}
        assert stage._aicore_registration_mismatch_error(state, artifacts) is None

    def test_no_op_name_skips(self):
        """无 op_name(op_dir 也空) → 无从校验,放行不误伤。"""
        stage, state, artifacts = _stage_state({}, op_name="")
        assert stage._aicore_registration_mismatch_error(state, artifacts) is None

    def test_plugin_mdef_not_scanned(self):
        """op_plugin m.def 的 snake 不参与比对(它驱动 eval 符号,可加 npu_ 前缀)。"""
        stage, state, artifacts = _stage_state(
            {"op_host/x_def.cpp": _def_cpp("AdaptiveAvgPool3d"),
             "op_plugin/x_plugin.cpp": """
TORCH_LIBRARY_FRAGMENT(cann_bench, m) {
    m.def("npu_adaptive_avg_pool_3d(Tensor x, int[] output_size) -> Tensor");
}"""}, op_name="adaptive_avg_pool_3d")
        assert stage._aicore_registration_mismatch_error(state, artifacts) is None

    def test_prefixed_profile_disk_is_dirname_not_short_name(self):
        """带前缀 profile(目录名=前缀+短名≠op_name):比对基准=op_dir 目录名(编译器
        config 派生源)。从目录名正确派生的注册名(AiInfraFoo)须放行——用短名比对
        会误拦;反之从短名派生(Foo)在 prefix 仓是真错误,须拦。"""
        from pathlib import Path
        stage = CodegenStage()
        state = State(mode="new", op_name="foo",
                      op_dir=Path("/repo/csrc/ops/ai_infra_foo"))
        # 正确:注册名从目录名 ai_infra_foo 派生
        ok = {"op_host/ai_infra_foo_def.cpp": _def_cpp("AiInfraFoo")}
        assert stage._aicore_registration_mismatch_error(state, ok) is None, \
            "prefix 仓从目录名派生的注册名不应被误拦"
        # 真错误:注册名从短名 foo 派生(runtime 反推 foo ≠ 目录名 ai_infra_foo)
        bad = {"op_host/ai_infra_foo_def.cpp": _def_cpp("Foo")}
        err = stage._aicore_registration_mismatch_error(state, bad)
        assert err is not None, "prefix 仓从短名派生的注册名应被拦"
        assert err.details["expected_derived"] == "AiInfraFoo"


class TestAicoreRegTransition:
    """经 _transition_membase 全路径：注册名错 → 定向 retry(不 halt、feedback kind=reg_name)。"""

    def _drive(self, artifacts: dict, op_name: str = "adaptive_avg_pool_3d"):
        stage = CodegenStage()
        state = State(mode="new", op_name=op_name, profile=None)
        from types import SimpleNamespace
        agent_result = SimpleNamespace(status="ok", artifacts=artifacts)
        result = {"agent_result": agent_result}
        return stage._transition_membase(state, result, agent_result)

    def test_transition_reg_mismatch_retries(self):
        """注册名抄 proto → transition 定向 retry：last_error 不设、build_feedback 带
        kind='reg_name'、deploy_result 不写(runner 重 spawn)。"""
        st = self._drive({"op_host/adaptive_avg_pool_3d_def.cpp":
                          _def_cpp("AdaptiveAvgPool3D")})
        assert st.last_error is None, "定向 retry 不 halt"
        fb = st.codegen_build_feedback
        assert fb is not None and fb.get("kind") == "reg_name", \
            f"应带 reg_name 反馈, got {fb}"
        assert fb.get("expected_derived") == "AdaptiveAvgPool3d"
        assert fb.get("disk_op_name") == "adaptive_avg_pool_3d", \
            "反馈应携带落盘目录名(供 coder 对齐)"
        assert fb.get("runtime_candidates"), "反馈应携带 runtime 反推候选"

    def test_transition_derived_passes_to_deploy(self):
        """注册名从 op_name 派生 → 不触发 reg_name 定向 retry(落到 deploy 层;profile-less
        单元态 deploy 因缺 repo 报错是既有行为,与注册名门无关)。"""
        st = self._drive({"op_host/adaptive_avg_pool_3d_def.cpp":
                          _def_cpp("AdaptiveAvgPool3d")})
        # 未触发 reg_name 定向 retry = 注册名门放行;deploy resolve 错是 profile-less 环境的
        # 独立既有行为,不在此断。
        assert st.codegen_build_feedback is None, \
            f"派生注册名不应触发 reg_name retry, got {st.codegen_build_feedback}"
