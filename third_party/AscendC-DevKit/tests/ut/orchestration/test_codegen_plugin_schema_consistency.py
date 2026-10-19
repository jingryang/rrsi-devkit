"""Q3-aggregate: codegen self-checks plugin ``m.def`` schema vs ``manifest.inputs``.

Phantom-input bug (batch 20260727_225324 aggregate_hidden_grad): plugin declared
``Tensor? mask`` in ``m.def`` (4 inputs) but manifest had 3 → ``ACLNN_CMD``
position binding drifted → ``EZ1001``. The self-check pinpoints this mismatch.
"""
import json
from unittest.mock import patch

from ascendc_devkit.orchestration.stages.codegen import CodegenStage
from ascendc_devkit.orchestration.kernel.state import State


def _plugin(mdef_inputs: str) -> str:
    return (
        'TORCH_LIBRARY_FRAGMENT(cann_bench, m) {\n'
        f'    m.def("op({mdef_inputs}) -> (Tensor)");\n'
        '}\n')


def _check(manifest_inputs, plugin_inputs, artifacts=None):
    stage = CodegenStage.__new__(CodegenStage)
    manifest = {"inputs": [{"name": n} for n in manifest_inputs]}
    if artifacts is None:
        artifacts = {"op_plugin/op_plugin.cpp": _plugin(plugin_inputs)}
    with patch("ascendc_devkit.infra.logger.Logger.warn") as m:
        stage._check_plugin_schema_consistency(State(mode="new"), manifest, artifacts)
    return m


def test_warns_on_phantom_input():
    """plugin m.def has 4 Tensor inputs (incl mask) but manifest has 3 → warn.

    This is the exact aggregate_hidden_grad signature that caused EZ1001."""
    m = _check(
        ["grad_output", "input", "weight"],
        "Tensor grad_output, Tensor input, Tensor weight, Tensor? mask=None")
    assert m.called
    msg = m.call_args.args[0]
    assert "mask" in msg and "mismatch" in msg


def test_no_warn_when_consistent():
    m = _check(["a", "b"], "Tensor a, Tensor b")
    assert not m.called


def test_warns_on_equal_length_position_drift():
    """m1 fix: equal-length but wrong-order inputs ([a,b] vs [b,a]) must warn —
    this is the actual EZ1001 danger a count-only (``len !=``) check missed: the
    name set matches, but the sequence drifts ACLNN_CMD position binding. The
    warn classifies it as position/order drift (same names, wrong sequence)."""
    m = _check(["b", "a"], "Tensor a, Tensor b")
    assert m.called
    msg = m.call_args.args[0]
    assert "position/order drift" in msg


def test_no_warn_when_no_plugin_artifact():
    stage = CodegenStage.__new__(CodegenStage)
    with patch("ascendc_devkit.infra.logger.Logger.warn") as m:
        stage._check_plugin_schema_consistency(
            State(mode="new"), {"inputs": [{"name": "a"}]}, {"other.cpp": "x"})
    assert not m.called


def test_no_warn_when_mdef_unparseable():
    """No resolvable m.def → skip (don't block on an unparseable artifact)."""
    m = _check(["a"], None, artifacts={"op_plugin/op_plugin.cpp": "// no m.def\n"})
    assert not m.called


def test_no_warn_on_tensorlist_foreach_input():
    """W3 (precision-tensorlist-harness-contract): a TensorList input
    (``Tensor[] x``, foreach family) is a real tensor input — the schema regex
    must recognize the variadic form. The old regex (``Tensor`` optional-mark
    whitespace word) saw ZERO tensors in ``Tensor[] x, float scalar`` and
    false-positived a phantom/unmatched mismatch on correct TensorList plugins
    (foreach_norm 20260807), while also going blind to genuine Tensor[]-shape
    phantom bugs."""
    m = _check(["x"], "Tensor[] x, float scalar")
    assert not m.called


def test_warns_on_tensorlist_phantom_after_fix():
    """W3: with the variadic form parsed, a genuine Tensor[]-shape phantom
    (manifest *declares* a tensor input that doesn't match the plugin) is still
    caught — the fix must not just silence the check. P1 收敛后检查只在 manifest
    主动声明了非空 inputs 时进行（见 test_no_warn_when_manifest_omits_inputs）。"""
    m = _check(["z"], "Tensor[] x, float scalar")  # manifest 声明 z，plugin 实际是 x
    assert m.called
    msg = m.call_args.args[0]
    assert "x" in msg and "mismatch" in msg


def test_no_warn_when_manifest_omits_inputs():
    """P1 收敛（2026-08-19）：manifest 不声明 inputs（空/缺）→ 不校验不 WARN——
    IO 不被下游消费（harness 绑 golden 用 op_spec），agent 合法选择不回声 IO；
    plugin m.def 是运行时绑定的唯一权威源。旧的「manifest 空 inputs vs plugin 有
    inputs → 报 phantom」语义在此不再成立。"""
    m = _check([], "Tensor[] x, float scalar")
    assert not m.called
    m = _check([], "Tensor a, Tensor b, int dim")
    assert not m.called


def test_no_warn_on_optional_tensorlist_forms():
    """M7 (PR-42): optional variadic forms ``Tensor?[] x`` and ``Tensor[]? x``
    are recognized as tensor inputs — no false phantom warning on correct
    optional-TensorList plugins."""
    m = _check(["x"], "Tensor?[] x, float scalar")
    assert not m.called
    m = _check(["x"], "Tensor[]? x, float scalar")
    assert not m.called


def test_transition_relays_manifest_before_deploy():
    """W4 (precision-tensorlist-harness-contract): the codegen transition must
    relay the just-produced manifest (carrying callable_target) into state
    BEFORE Deployer.compile runs (方案 2: codegen 走 compile→install_and_smoke，不再走
    deploy 全链；compile 内部 _resolve 读 state.codegen_manifest)。Otherwise
    Deployer 读到空 state.codegen_manifest 且 smoke false-fails (foreach_norm
    20260807: codegen smoke_passed=False from "missing callable_target in state";
    the manifest was only written into state at the transition's return)."""
    from ascendc_devkit.domain.operator import OperatorSpec
    from ascendc_devkit.domain.requirement import Requirement
    from ascendc_devkit.domain.repository import RepositoryProfile, Scaffolding
    from ascendc_devkit.domain.verification import DeployResult
    from ascendc_devkit.capabilities.agent.backend import AgentResult

    captured: dict = {}

    class _FakeDeployer:
        # 方案 2（D6/L4 改动 2）：codegen transition 改走 compile → install_and_smoke。
        # W4 不变量（manifest 先 relay 进 state 再 deploy）改由 compile 捕获——compile 内部
        # _resolve 读 state.codegen_manifest，capture 点 = compile 即验证 manifest 已就位。
        def compile(self, state):
            captured["state"] = state
            return DeployResult(
                run_package="/dist/pkg.run", wheel_package="/dist/pkg.whl",
                smoke_passed=False), None

        def install_and_smoke(self, state, compile_result):
            return DeployResult(
                run_package=compile_result.run_package,
                wheel_package=compile_result.wheel_package,
                install_path="/opp", python_path="/py",
                smoke_passed=True), None

    manifest = {
        "op_name": "foreach_norm", "op_pascal": "ForeachNorm",
        "inputs": [{"name": "x", "type": "Tensor[]"}],
        "outputs": [{"name": "y", "type": "Tensor[]"}],
        "attrs": [{"name": "scalar", "type": "float", "default": None}],
        "supported_dtypes": ["float32", "float16", "bfloat16"],
        "callable_target": {"kind": "torch_op",
                            "symbol": "torch.ops.cann_bench.foreach_norm"},
    }
    plugin = ('TORCH_LIBRARY_FRAGMENT(cann_bench, m) {\n'
              '    m.def("foreach_norm(Tensor[] x, float scalar) -> Tensor[]");\n'
              '}\n')
    agent_result = AgentResult(
        agent_name="ascendc-coder", status="ok",
        artifacts={
            "CMakeLists.txt": "# cmake\n",
            "codegen_manifest.json": json.dumps(manifest),
            "op_api/aclnn_foreach_norm.cpp": "// api\n",
            "op_host/foreach_norm_def.cpp": "// host\n",
            "op_kernel/foreach_norm_kernel.cpp": "// kernel\n",
            "op_plugin/foreach_norm_plugin.cpp": plugin,
        })

    with patch("ascendc_devkit.orchestration.stages.deploy.Deployer",
               _FakeDeployer):
        stage = CodegenStage()
        state = State(
            mode="new",
            profile=RepositoryProfile(
                name="omni-ops",
                scaffolding=Scaffolding(
                    supported=("torch_op",), selected="torch_op")),
            requirement=Requirement(op_spec=OperatorSpec(name="foreach_norm")),
            design_target_chip="A2",
            codegen_iterations=0,
            decision_logs={},
        )
        stage.transition(state, {"agent_result": agent_result})

    deploy_state = captured["state"]
    assert deploy_state.codegen_manifest is not None, (
        "W4: manifest must be relayed into state before Deployer.compile")
    assert (deploy_state.codegen_manifest["callable_target"]["symbol"]
            == "torch.ops.cann_bench.foreach_norm")


def test_skips_when_manifest_missing():
    stage = CodegenStage.__new__(CodegenStage)
    with patch("ascendc_devkit.infra.logger.Logger.warn") as m:
        stage._check_plugin_schema_consistency(
            State(mode="new"), None, {"op_plugin/op_plugin.cpp": "x"})
    assert not m.called


# ---------------------------------------------------------------------------
# F5：OpDef 输出 ParamType(OPTIONAL) → __CCE_KernelArgSize 膨胀隐患护栏
# ---------------------------------------------------------------------------

class TestOpdefOptionalOutput:
    """F5：OpDef 输出声明 OPTIONAL → AscendC 编译器多发射 8B kernel 参数槽
    （__CCE_KernelArgSize 48 vs host 40）→ kernel 读垃圾 tiling 指针 → 507057。
    codegen 契约门：warn + 返回 retry 判定 dict（reason/def_file/output_name），
    由 transition 定向 retry 回 codegen 重修（全 kind 防 507057，aclnn smoke 无执行
    探针拦不住运行期异常）。"""

    _DEF_OPTIONAL = (
        'void Register() {\n'
        '  this->Input("x").ParamType(REQUIRED);\n'
        '  this->Output("inverse").ParamType(OPTIONAL);\n'
        '}'
    )
    _DEF_REQUIRED = (
        'void Register() {\n'
        '  this->Input("x").ParamType(REQUIRED);\n'
        '  this->Output("y").ParamType(REQUIRED);\n'
        '  this->Output("inverse").ParamType(REQUIRED);\n'
        '}'
    )

    def _check(self, artifacts):
        stage = CodegenStage.__new__(CodegenStage)
        with patch("ascendc_devkit.infra.logger.Logger.warn") as m:
            verdict = stage._check_opdef_optional_output(
                State(mode="new"), artifacts)
        return m, verdict

    def test_warns_and_returns_verdict_on_optional_output(self):
        m, verdict = self._check({"op_host/op_def.cpp": self._DEF_OPTIONAL})
        assert m.called
        msg = m.call_args.args[0]
        assert "inverse" in msg and "507057" in msg
        # retry 判定 dict 契约：transition 据 reason 路由 _plugin_schema_retry
        assert verdict == {
            "reason": "opdef_optional_output",
            "def_file": "op_host/op_def.cpp",
            "output_name": "inverse",
        }

    def test_dot_prefix_output_form_also_detected(self):
        # 兼容 `.Output("y")`（点前缀）——docstring 声称 `\b` 在 `->`/`.` 后都成立
        src = ('void Register() {\n'
               '  this->Input("x").ParamType(REQUIRED)\n'
               '      .Output("y").ParamType(OPTIONAL);\n'
               '}')
        m, verdict = self._check({"op_host/op_def.cpp": src})
        assert m.called
        assert verdict is not None and verdict["output_name"] == "y"

    def test_multi_chain_state_machine(self):
        # 多链状态机：Output→Input→Output，第二个 Output 才 OPTIONAL → 命中第二个；
        # 且 Input 后跟 OPTIONAL 不误报
        src = ('void Register() {\n'
               '  this->Output("a").ParamType(REQUIRED);\n'
               '  this->Input("mask").ParamType(OPTIONAL);\n'
               '  this->Output("b")\n'
               '      .ParamType(OPTIONAL);\n'
               '}')
        m, verdict = self._check({"op_host/op_def.cpp": src})
        assert m.called
        assert verdict is not None and verdict["output_name"] == "b"

    def test_no_warn_when_required_outputs(self):
        m, verdict = self._check({"op_host/op_def.cpp": self._DEF_REQUIRED})
        assert not m.called
        assert verdict is None

    def test_input_optional_not_false_positive(self):
        # 只查**输出**的 OPTIONAL；输入 OPTIONAL（如 mask=None）不误报
        src = ('void Register() {\n'
               '  this->Input("mask").ParamType(OPTIONAL);\n'
               '  this->Output("y").ParamType(REQUIRED);\n'
               '}')
        m, verdict = self._check({"op_host/op_def.cpp": src})
        assert not m.called
        assert verdict is None

    def test_skips_non_def_cpp(self):
        m, verdict = self._check({"op_host/op_tiling.cpp": "x"})
        assert not m.called and verdict is None
        m, verdict = self._check(
            {"op_kernel/op_kernel.cpp": self._DEF_OPTIONAL})
        assert not m.called and verdict is None

    def test_zero_artifacts_returns_none(self):
        m, verdict = self._check({})
        assert not m.called and verdict is None


def test_collect_schema_feedback_opdef_optional():
    """F5 反馈构造：reason=opdef_optional_output → kind='opdef_optional' 专属段
    （区别于 kind='schema_mismatch' 的返回签名段，避免误导 coder 去查 m.def）。"""
    stage = CodegenStage.__new__(CodegenStage)
    fb = stage._collect_schema_feedback(
        State(mode="new"),
        {"reason": "opdef_optional_output",
         "def_file": "op_host/unique_def.cpp",
         "output_name": "inverse"},
        retries=3)
    assert fb["kind"] == "opdef_optional"
    assert fb["def_file"] == "op_host/unique_def.cpp"
    assert fb["output_name"] == "inverse"
    assert "507057" in fb["hint"] and "REQUIRED" in fb["hint"]
    assert fb["retry_count"] == 3


def test_transition_routes_opdef_optional_to_schema_retry():
    """F5 transition 接线：def.cpp 输出 OPTIONAL → 定向 retry 回 codegen（不写
    deploy_result → runner 重 spawn coder 带 opdef_optional 反馈）。证明 F5 门从
    warn-only 升级为「拦下并重修」——aclnn 的 fail-closed smoke 无执行探针也防得住
    507057 传播。"""
    from ascendc_devkit.domain.operator import OperatorSpec
    from ascendc_devkit.domain.requirement import Requirement
    from ascendc_devkit.domain.repository import RepositoryProfile, Scaffolding
    from ascendc_devkit.capabilities.agent.backend import AgentResult

    def_file = ('void Register() {\n'
                '  this->Input("x").ParamType(REQUIRED);\n'
                '  this->Output("inverse").ParamType(OPTIONAL);\n'
                '}')
    manifest = {
        "op_name": "unique", "op_pascal": "Unique",
        "inputs": [{"name": "x", "type": "Tensor"}],
        "outputs": [{"name": "y", "type": "Tensor"},
                    {"name": "inverse", "type": "Tensor"}],
        "attrs": [],
        "supported_dtypes": ["int32"],
        "callable_target": {"kind": "torch_op",
                            "symbol": "torch.ops.cann_bench.unique"},
    }
    agent_result = AgentResult(
        agent_name="ascendc-coder", status="ok",
        artifacts={
            "CMakeLists.txt": "# cmake\n",
            "codegen_manifest.json": json.dumps(manifest),
            "op_api/aclnn_unique.cpp": "// api\n",
            "op_host/unique_def.cpp": def_file,
            "op_kernel/unique_kernel.cpp": "// kernel\n",
            "op_plugin/unique_plugin.cpp": (
                'TORCH_LIBRARY_FRAGMENT(cann_bench, m) {\n'
                '    m.def("unique(Tensor x) -> (Tensor, Tensor?)");\n'
                '}\n'),
        })
    stage = CodegenStage()
    state = State(
        mode="new",
        profile=RepositoryProfile(
            name="omni-ops",
            scaffolding=Scaffolding(
                supported=("torch_op",), selected="torch_op")),
        requirement=Requirement(op_spec=OperatorSpec(name="unique")),
        design_target_chip="A2",
        codegen_iterations=0,
        decision_logs={},
    )
    next_state = stage.transition(state, {"agent_result": agent_result})

    # F5 门命中 → 不写 deploy_result（runner 重 spawn）、带 opdef_optional 反馈
    assert next_state.deploy_result is None
    fb = next_state.codegen_build_feedback
    assert fb is not None and fb.get("kind") == "opdef_optional"
    assert fb.get("output_name") == "inverse"
    assert next_state.codegen_build_retries == 1
