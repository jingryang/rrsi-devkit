"""step-108 harness 生成侧 env 契约断言（05-impl 改动 4 的渲染级红测）。

被测：``NPURunner._build_test_harness`` 渲染产物含 env 契约断言块，期望值从
``deploy_result.install_path`` 活值单源派生（stale 防护：换 install_path 重渲染，
期望值必须跟随）；值形态单源守卫（§1.15：三处 env 构造点全部经
``expected_ascend_custom_opp``，仓内不得再出现裸 f-string 拼接形态）。
"""
import inspect
from types import SimpleNamespace


def _render(install_path: str) -> str:
    """按 deploy smoke 的真实调用形态渲染 harness（smoke_probe=True、无 golden）。"""
    from ascendc_devkit.adapters.npu.runner import NPURunner
    from ascendc_devkit.domain.operator import OperatorSpec
    from ascendc_devkit.domain.requirement import TestCase

    r = NPURunner.__new__(NPURunner)
    r._chip_version = "A2"
    r._torch_npu_available = True
    op = OperatorSpec(name="add")
    tc = [TestCase(name="basic",
                   inputs=[{"name": "a", "shape": [8], "dtype": "fp16"}])]
    return r._build_test_harness(
        op, tc,
        golden_contract=None,
        deploy_result=SimpleNamespace(
            python_path="/p", install_path=install_path, ld_library_path_add=""),
        callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.add"},
        smoke_probe=True,
    )


def test_rendered_harness_contains_env_contract_assert():
    src = _render("/i1")
    assert "[ENV_CONTRACT]" in src, (
        "渲染产物缺少 env 契约断言块——harness 消费点失去地面真值守卫")
    assert "/i1/vendors/custom_ops" in src, (
        "断言块期望值必须从 install_path 派生的 vendor 级形态烘入")


def test_rendered_expected_follows_install_path_stale_guard():
    """stale 防护：换 install_path 重渲染，期望值必须跟随（resume 换 exec 目录
    后旧烘入值必假红——期望值只能来自渲染时的活值单源）。"""
    src1 = _render("/i1")
    src2 = _render("/i2")
    assert "/i1/vendors/custom_ops" in src1
    assert "/i2/vendors/custom_ops" in src2
    assert "/i1/vendors/custom_ops" not in src2


def test_env_value_form_single_source_grep_guard():
    """§1.15 源级守卫：值形态唯一实现点=infra/env_contract.expected_ascend_custom_opp；
    runner / cannbench_env / deploy 三处构造点不得再出现裸 `/vendors/custom_ops`
    f-string 拼接（第二形态源=drift 温床）。"""
    import re

    from ascendc_devkit.adapters.npu import runner as runner_mod
    from ascendc_devkit.adapters.evaluation import cannbench_env as cann_env_mod
    from ascendc_devkit.orchestration.stages import deploy as deploy_mod

    # M6（review 整改）：匹配任意「引号内含该路径段」的字面量——历史偏差
    # 形态是 f-string 拼接 f"{x}/vendors/custom_ops"（路径段前是 `}` 非引号），
    # 首版只查引号紧贴的独立字面量，恰好放行了它自称要拦的形态。
    _second_form = re.compile(r"""["'][^"'\n]*/vendors/custom_ops["']""")

    for mod in (runner_mod, cann_env_mod, deploy_mod):
        src = inspect.getsource(mod)
        assert "expected_ascend_custom_opp" in src, (
            f"{mod.__name__} 未走值形态单源 expected_ascend_custom_opp")
        assert not _second_form.search(src), (
            f"{mod.__name__} 残留裸值形态拼接（含 f-string 内嵌段——第二形态源）")


def test_env_value_form_guard_actually_catches_fstring_form():
    """M6 防腐：守护正则必须命中历史偏差形态（f-string 拼接），不得只拦
    引号紧贴的独立字面量——证明守护非常绿。"""
    import re

    _second_form = re.compile(r"""["'][^"'\n]*/vendors/custom_ops["']""")
    bad = 'env["ASCEND_CUSTOM_OPP_PATH"] = f"{per_op_opp}/vendors/custom_ops"'
    assert _second_form.search(bad), "guard misses the f-string drift form"
    assert _second_form.search('env["X"] = "/a/vendors/custom_ops"')
    ok = "value = expected_ascend_custom_opp(install_path)"
    assert not _second_form.search(ok)
