"""cannbench_adapt UT：P10 m.def schema 对齐 + 方案 G ([[P112]]) 确定性 wrapper 生成。

两条确定性后处理（均不需 LLM，agent 已退役，方案75）：
1. **P10**：cann-bench kernel_eval 按 golden 名**关键字调用** ``func(**params)``，故
   codegen m.def schema 名（``x``/``p``）≠ proto/golden 名（``input``/``scalar``）时
   ``missing value for argument`` → 全 case 0 分。transition 末尾比对 proto 名 vs m.def
   schema 名，不一致则 rename m.def + rebuild。
2. **方案 G ([[P112]])**：cann-bench ``scan_interfaces`` 扫 ``dir(cann_bench)``（Python
   命名空间）发现算子，``TORCH_LIBRARY_FRAGMENT`` 只注册 C++ Dispatcher、不回写
   ``__dict__``，故 ``cann_bench/__init__.py`` 必须有显式 ``def <op>`` wrapper。wrapper
   三维{存在/参数名/转发目标}是 manifest 纯函数 → 确定性生成 + 幂等注入。

m.def 解析原语集中于 ``domain.mdef_parse``（§2.5 唯一通路）；注册名推导（codegen
fallback symbol）由 ``tests/ut/domain/test_mdef_parse.py`` + ``test_codegen_regbase_phases.py``
守护。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from ascendc_devkit.domain.operator import (
    AttrSpec,
    OperatorIdentity,
    OperatorSpec,
    TensorSpec,
)
from ascendc_devkit.domain.verification import DeployResult
from ascendc_devkit.domain.requirement import Requirement
from ascendc_devkit.orchestration.kernel.state import ErrorFeedback, State
from ascendc_devkit.domain.mdef_parse import (
    parse_mdef_params,
    rename_mdef_schema,
)
from ascendc_devkit.adapters.evaluation.cannbench_adapt import (
    _build_wrapper,
    _inject_wrapper_block,
    align_schema_params,
    generate_and_inject_wrapper,
)
from ascendc_devkit.orchestration.stages.cannbench_adapt import CannbenchAdaptStage


REPO_ROOT = Path(__file__).resolve().parents[3]


# —— 纯函数：parse_mdef_params ————————————————————————————————

class TestParseMdef:
    def test_basic_tensor_int(self):
        assert parse_mdef_params('m.def("swi_glu(Tensor x, int dim=-1) -> Tensor");') == ["x", "dim"]

    def test_tensor_list_float_default(self):
        assert parse_mdef_params(
            'm.def("foreach_norm(Tensor[] x, float p=2.0) -> Tensor[]");'
        ) == ["x", "p"]

    def test_const_ref(self):
        assert parse_mdef_params(
            'm.def("op(const Tensor& x, int dim) -> Tensor");'
        ) == ["x", "dim"]

    def test_no_params(self):
        assert parse_mdef_params('m.def("foo() -> Tensor");') == []

    def test_no_mdef(self):
        assert parse_mdef_params("// no m.def here") == []

    def test_multiple_tensors(self):
        assert parse_mdef_params(
            'm.def("op(Tensor a, Tensor b, float eps=1e-6) -> Tensor");'
        ) == ["a", "b", "eps"]


# —— 纯函数：rename_mdef_schema ———————————————————————————————

class TestRenameMdef:
    def test_rename_input(self):
        s = 'm.def("swi_glu(Tensor x, int dim=-1) -> Tensor");'
        assert rename_mdef_schema(s, ["x", "dim"], ["input", "dim"]) == \
            'm.def("swi_glu(Tensor input, int dim=-1) -> Tensor");'

    def test_rename_scalar(self):
        s = 'm.def("foreach_norm(Tensor[] x, float p=2.0) -> Tensor[]");'
        assert rename_mdef_schema(s, ["x", "p"], ["input", "scalar"]) == \
            'm.def("foreach_norm(Tensor[] input, float scalar=2.0) -> Tensor[]");'

    def test_no_change_when_aligned(self):
        s = 'm.def("swi_glu(Tensor input, int dim=-1) -> Tensor");'
        assert rename_mdef_schema(s, ["input", "dim"], ["input", "dim"]) == s

    def test_count_mismatch_no_rename(self):
        s = 'm.def("op(Tensor x) -> Tensor");'
        # schema 1 个参数，proto 给 2 个名 → 数量不一致，不 rename（返回原串）
        assert rename_mdef_schema(s, ["x"], ["input", "dim"]) == s


# —— 纯函数：align_schema_params（proto 名序列）——————————————

class TestAlignSchema:
    def test_inputs_then_attrs(self):
        spec = OperatorSpec(
            name="swi_glu",
            inputs=[TensorSpec(name="input")],
            attrs={"dim": AttrSpec(name="dim", type="int")},
        )
        assert align_schema_params(spec) == ["input", "dim"]

    def test_multi_inputs_multi_attrs(self):
        spec = OperatorSpec(
            name="op",
            inputs=[TensorSpec(name="a"), TensorSpec(name="b")],
            attrs={
                "eps": AttrSpec(name="eps", type="float"),
                "dim": AttrSpec(name="dim", type="int"),
            },
        )
        assert align_schema_params(spec) == ["a", "b", "eps", "dim"]

    def test_no_attrs(self):
        spec = OperatorSpec(name="op", inputs=[TensorSpec(name="x")])
        assert align_schema_params(spec) == ["x"]


# —— W1：_build_wrapper 三维（纯函数）——————————————————————————

class TestBuildWrapper:
    """W1：wrapper 三维构造性保证（存在 / 参数名 / 转发目标）。"""

    def test_three_dims_basic(self):
        w = _build_wrapper("swi_glu", "swi_glu", ["input", "dim"])
        # ① 存在 def {op_name}
        assert "def swi_glu(input, dim):" in w
        # ② 参数名 = proto
        assert "input" in w and "dim" in w
        # ③ 转发目标 = symbol_last
        assert "torch.ops.cann_bench.swi_glu(input, dim)" in w

    def test_symbol_last_decouples_from_op_name(self):
        """op_name=exp 但真实注册名 npu_exp（codegen 避内置名冲突）→ 转发到 npu_exp。"""
        w = _build_wrapper("exp", "npu_exp", ["x"])
        assert "def exp(x):" in w
        assert "torch.ops.cann_bench.npu_exp(x)" in w
        # 对外名(exp)与转发目标(npu_exp)解耦——三维③的关键
        assert "torch.ops.cann_bench.exp(" not in w

    def test_full_symbol_dotted_form(self):
        """_generate_and_inject_wrapper 对 'torch.ops.cann_bench.npu_exp' 取末段。"""
        assert "torch.ops.cann_bench.npu_exp".split(".")[-1] == "npu_exp"


class TestGenerateInjectWrapper:
    """cannbench_adapt 确定性直通 wrapper 注入（非条件输出算子的正常路径）。"""

    def test_generate_inject_append_pass_through_when_no_contract(self, tmp_path):
        """无既有 wrapper → 注入确定性直通（正常路径不回归）。"""
        repo_root = tmp_path / "cann-bench"
        repo_root.mkdir(parents=True, exist_ok=True)
        pkg = repo_root / "cann_bench"
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")

        op_spec = OperatorSpec(name="exp", inputs=[TensorSpec(name="x")])
        injected, errors, files = generate_and_inject_wrapper(
            codegen_manifest={
                "op_name": "exp",
                "callable_target": {"kind": "torch_op", "symbol": "torch.ops.cann_bench.exp"},
            },
            op_spec=op_spec,
            op_name_fallback="exp",
            repo_root=repo_root,
            source_dir=repo_root,
        )
        assert injected is True
        content = (pkg / "__init__.py").read_text(encoding="utf-8")
        assert "def exp(x):" in content
        assert "torch.ops.cann_bench.exp(x)" in content


# —— fixture：_make_state（cann_bench 包 + op_plugin m.def）————————

def _write_plugin(op_dir: Path, op_name: str, mdef_line: str) -> Path:
    plugin_dir = op_dir / "op_plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    p = plugin_dir / f"{op_name}_plugin.cpp"
    p.write_text(
        f'#include <torch/library.h>\nnamespace cann_bench {{\n    {mdef_line}\n}}\n',
        encoding="utf-8",
    )
    return p


def _canonical_block(op_name: str, symbol: str, op_spec: OperatorSpec) -> str:
    """与 _generate_and_inject_wrapper 写入的 canonical 块逐字一致（用于幂等种子）。"""
    params = align_schema_params(op_spec)
    symbol_last = symbol.split(".")[-1]
    return f"# {op_name} wrapper (deterministic, cannbench_adapt)\n" + _build_wrapper(
        op_name, symbol_last, params
    )


def _make_state(
    tmp_path: Path,
    mdef_line: str,
    op_spec: OperatorSpec,
    op_name: str = "swi_glu",
    symbol: str | None = None,
    seed_wrapper: bool = False,
) -> State:
    """建带 op_plugin m.def + cann_bench/ 包 fixture 的 State。

    - ``symbol``：manifest callable_target.symbol（默认 = op_name）。
    - ``seed_wrapper=True``：预写 canonical wrapper 到 cann_bench/__init__.py，使
      ``_generate_and_inject_wrapper`` 幂等 no-op（injected=False）——用于把 P10/rebuild
      行为与 wrapper 注入路径隔离。
    """
    op_dir = tmp_path / "op_dir"
    _write_plugin(op_dir, op_name, mdef_line)
    ident = OperatorIdentity(spec=op_spec, repo_root=tmp_path, op_dir=op_dir, files={})
    sym = symbol or op_name
    manifest = {
        "op_name": op_name,
        "callable_target": {"kind": "torch_op", "symbol": sym},
    }
    # cann_bench 包放 repo_root 下：_resolve_cann_bench_pkg_root 从 op_dir 向上走到
    # tmp_path（含 cann_bench/）即命中。
    cb_init = tmp_path / "cann_bench" / "__init__.py"
    cb_init.parent.mkdir(parents=True, exist_ok=True)
    if seed_wrapper:
        cb_init.write_text(_canonical_block(op_name, sym, op_spec), encoding="utf-8")
    else:
        cb_init.write_text("", encoding="utf-8")
    return State.empty().with_updates(
        op_name=op_name,
        requirement=Requirement(op_spec=op_spec),
        op_identity=ident,
        codegen_manifest=manifest,
        deploy_result=DeployResult(
            smoke_passed=True,
            install_path=str(tmp_path / "opp"),
            python_path=str(tmp_path / "py"),
        ),
        design_target_chip="A2",
        runtime_target_chip="A2",
    )


def _gen(state):
    """Decode state → adapter.generate_and_inject_wrapper (mirrors the stage's
    transition decoding); returns (injected, errors) for compat with the
    pre-refactor stage-method tests."""
    repo_root = CannbenchAdaptStage._resolve_repo_root(state)
    source_dir = CannbenchAdaptStage._resolve_source_dir(state, repo_root) if repo_root else None
    op_spec = state.requirement.op_spec if state.requirement else None
    injected, errors, _files = generate_and_inject_wrapper(
        state.codegen_manifest,
        op_spec,
        state.op_name or "",
        repo_root,
        source_dir,
        state.proto_schema,
    )
    return injected, errors


# —— W2/W3：_generate_and_inject_wrapper 幂等注入 ————————————————

class TestGenerateWrapper:
    """W2（错版→替换）/ W3（无→追加，保既有）/ 幂等（已对→跳过）。"""

    def test_append_when_absent_preserves_existing(self, tmp_path):
        """W3：__init__.py 不含本 op wrapper → 追加；既有 wrapper（add）不动。"""
        spec = OperatorSpec(name="swi_glu", inputs=[TensorSpec(name="input")],
                            attrs={"dim": AttrSpec(name="dim", type="int")})
        state = _make_state(tmp_path, 'm.def("swi_glu(Tensor x, int dim=-1) -> Tensor");',
                            spec, seed_wrapper=False)
        init_path = tmp_path / "cann_bench" / "__init__.py"
        init_path.write_text(
            "def add(a, b):\n    return torch.ops.cann_bench.add(a, b)\n",
            encoding="utf-8",
        )
        injected, errors = _gen(state)
        assert injected is True
        assert errors == []
        content = init_path.read_text(encoding="utf-8")
        # 既有 add wrapper 仍在
        assert "def add(a, b):" in content
        # 新 swi_glu wrapper 三维正确
        assert "def swi_glu(input, dim):" in content
        assert "torch.ops.cann_bench.swi_glu(input, dim)" in content
        # 不重复 def
        assert content.count("def swi_glu(") == 1

    def test_replace_when_wrong(self, tmp_path):
        """W2：__init__.py 有错版 wrapper（错参数名 + 错转发目标）→ 替换为 canonical。"""
        spec = OperatorSpec(name="swi_glu", inputs=[TensorSpec(name="input")],
                            attrs={"dim": AttrSpec(name="dim", type="int")})
        state = _make_state(tmp_path, 'm.def("swi_glu(Tensor x, int dim=-1) -> Tensor");',
                            spec, symbol="npu_swi_glu", seed_wrapper=False)
        init_path = tmp_path / "cann_bench" / "__init__.py"
        init_path.write_text(
            "# swi_glu wrapper (deterministic, cannbench_adapt)\n"
            "def swi_glu(wrong_a, wrong_b):\n"
            "    return torch.ops.cann_bench.npu_wrong(wrong_a, wrong_b)\n",
            encoding="utf-8",
        )
        injected, errors = _gen(state)
        assert injected is True
        assert errors == []
        content = init_path.read_text(encoding="utf-8")
        # 旧错版痕迹清除
        assert "wrong_a" not in content and "npu_wrong" not in content
        # 新 canonical：参数名=proto、转发目标=symbol_last(npu_swi_glu)
        assert "def swi_glu(input, dim):" in content
        assert "torch.ops.cann_bench.npu_swi_glu(input, dim)" in content
        assert content.count("def swi_glu(") == 1

    def test_idempotent_when_already_correct(self, tmp_path):
        """幂等：__init__.py 已是 canonical → injected=False，内容不变。"""
        spec = OperatorSpec(name="swi_glu", inputs=[TensorSpec(name="input")],
                            attrs={"dim": AttrSpec(name="dim", type="int")})
        state = _make_state(tmp_path, 'm.def("swi_glu(Tensor x, int dim=-1) -> Tensor");',
                            spec, seed_wrapper=True)
        init_path = tmp_path / "cann_bench" / "__init__.py"
        before = init_path.read_text(encoding="utf-8")
        injected, errors = _gen(state)
        assert injected is False
        assert errors == []
        assert init_path.read_text(encoding="utf-8") == before

    def test_no_symbol_records_error(self, tmp_path):
        """manifest 缺 callable_target.symbol → injected=False + error（可诊断）。"""
        spec = OperatorSpec(name="op", inputs=[TensorSpec(name="x")])
        state = _make_state(tmp_path, 'm.def("op(Tensor x) -> Tensor");', spec, op_name="op")
        state = state.with_updates(
            codegen_manifest={"op_name": "op"}  # 无 callable_target
        )
        injected, errors = _gen(state)
        assert injected is False
        assert errors and "callable_target.symbol" in errors[0]

    def test_no_cann_bench_pkg_records_error(self, tmp_path):
        """repo 内无 cann_bench/ 包 → injected=False + error（可诊断）。"""
        spec = OperatorSpec(name="op", inputs=[TensorSpec(name="x")])
        state = _make_state(tmp_path, 'm.def("op(Tensor x) -> Tensor");', spec, op_name="op")
        # 删掉 cann_bench 包 → 路径解析落空
        import shutil
        shutil.rmtree(tmp_path / "cann_bench")
        injected, errors = _gen(state)
        assert injected is False
        assert errors and "cann_bench/" in errors[0]


    def test_replace_commentless_wrong_wrapper(self, tmp_path):
        """真实 P112 输入：LLM 写的 wrapper **无 deterministic 注释**且错（错转发目标）
        → 仍被定位+替换（不因缺注释而漏匹配→追加重复 def）。验证 regex 可选注释组。"""
        spec = OperatorSpec(name="swi_glu", inputs=[TensorSpec(name="input")],
                            attrs={"dim": AttrSpec(name="dim", type="int")})
        state = _make_state(tmp_path, 'm.def("swi_glu(Tensor x, int dim=-1) -> Tensor");',
                            spec, symbol="npu_swi_glu", seed_wrapper=False)
        init_path = tmp_path / "cann_bench" / "__init__.py"
        # 注意：无前置注释（LLM 常见产出形态）
        init_path.write_text(
            "def swi_glu(input, dim):\n"
            "    return torch.ops.cann_bench.npu_wrong(input, dim)\n",
            encoding="utf-8",
        )
        injected, errors = _gen(state)
        assert injected is True
        assert errors == []
        content = init_path.read_text(encoding="utf-8")
        # 旧错转发目标清除，新 canonical（含我们的注释）落地
        assert "npu_wrong" not in content
        assert "torch.ops.cann_bench.npu_swi_glu(input, dim)" in content
        # 关键：未重复 def（替换而非追加）
        assert content.count("def swi_glu(") == 1

    def test_op_name_falls_back_to_state_when_manifest_lacks_it(self, tmp_path):
        """manifest 无 op_name 键时，兜底取 state.op_name（codegen 真实 manifest 带 op_name，
        此为防御分支）。"""
        spec = OperatorSpec(name="op", inputs=[TensorSpec(name="x")])
        state = _make_state(tmp_path, 'm.def("op(Tensor x) -> Tensor");', spec, op_name="op")
        # 抹掉 manifest 的 op_name 键，仅留 callable_target；state.op_name 仍在
        state = state.with_updates(
            codegen_manifest={"callable_target": {"kind": "torch_op", "symbol": "op"}}
        )
        injected, errors = _gen(state)
        assert injected is True
        assert errors == []
        content = (tmp_path / "cann_bench" / "__init__.py").read_text(encoding="utf-8")
        assert "def op(x):" in content

    def test_replace_annotated_existing_wrapper(self, tmp_path):
        """m2：既有 wrapper 带**返回注解**（``def op(...) -> Tensor:``，签名里的 ``)``
        在 ``->`` 之前）→ AST 仍定位+替换，不因旧正则 ``[^)]*`` 截断签名而漏匹配 → 重复 def。"""
        spec = OperatorSpec(name="swi_glu", inputs=[TensorSpec(name="input")],
                            attrs={"dim": AttrSpec(name="dim", type="int")})
        state = _make_state(tmp_path, 'm.def("swi_glu(Tensor x, int dim=-1) -> Tensor");',
                            spec, symbol="npu_swi_glu", seed_wrapper=False)
        init_path = tmp_path / "cann_bench" / "__init__.py"
        # 返回注解：签名 `def swi_glu(input, dim) -> torch.Tensor:` —— `)` 后还有 ` -> torch.Tensor`
        # 旧正则 `def op\([^)]*\):` 会因首个 `)` 后非 `:` 而漏匹配 → 走追加 → 重复 def
        init_path.write_text(
            "def swi_glu(input, dim) -> torch.Tensor:\n"
            "    return torch.ops.cann_bench.npu_wrong(input, dim)\n",
            encoding="utf-8",
        )
        injected, errors = _gen(state)
        assert injected is True
        assert errors == []
        content = init_path.read_text(encoding="utf-8")
        # 关键：替换非追加——只有 1 个 def swi_glu
        assert content.count("def swi_glu(") == 1
        assert "npu_wrong" not in content
        assert "torch.ops.cann_bench.npu_swi_glu(input, dim)" in content


# —— m2：_inject_wrapper_block AST 定位（注解 / 多行签名 robustness）——————

class TestInjectWrapperBlock:
    """m2：``_inject_wrapper_block`` 用 AST 定位既有 ``def {op}``，robust to 类型注解 /
    多行签名（旧正则 ``def op\\([^)]*\\)`` 遇签名含 ``)`` 会截断 → 漏匹配 → 重复 def）。
    AST 为准（python 语法权威），正则仅 syntax-error 文件兜底。"""

    BLOCK = (
        "# swi_glu wrapper (deterministic, cannbench_adapt)\n"
        "def swi_glu(input, dim):\n"
        "    return torch.ops.cann_bench.swi_glu(input, dim)\n"
    )

    def test_replace_return_annotation(self):
        """返回注解签名（``) -> torch.Tensor``）→ 替换不重复。"""
        existing = (
            "import torch\n\n"
            "def swi_glu(input, dim) -> torch.Tensor:\n"
            "    return torch.ops.cann_bench.npu_wrong(input, dim)\n"
        )
        result = _inject_wrapper_block(existing, "swi_glu", self.BLOCK)
        assert result.count("def swi_glu(") == 1
        assert "npu_wrong" not in result
        assert "torch.ops.cann_bench.swi_glu(input, dim)" in result
        assert "import torch" in result  # 前导内容保留

    def test_replace_paren_in_default(self):
        """签名默认值含 ``)``（``dim: int = (1,)``）→ AST 仍精确覆盖整 def，不截断。"""
        existing = (
            "def swi_glu(input: torch.Tensor, dim: int = (1,)):\n"
            "    return torch.ops.cann_bench.npu_wrong(input, dim)\n"
        )
        result = _inject_wrapper_block(existing, "swi_glu", self.BLOCK)
        assert result.count("def swi_glu(") == 1
        assert "npu_wrong" not in result
        assert "def swi_glu(input, dim):" in result

    def test_replace_multiline_signature(self):
        """多行签名（issue.md LLM 风格：``def op(\\n  x,\\n):``）→ 整 def 被替换为单行 canonical。"""
        existing = (
            "def swi_glu(\n"
            "    input,\n"
            "    dim,\n"
            ") -> torch.Tensor:\n"
            "    return torch.ops.cann_bench.npu_wrong(input, dim)\n"
        )
        result = _inject_wrapper_block(existing, "swi_glu", self.BLOCK)
        assert result.count("def swi_glu(") == 1
        assert "npu_wrong" not in result
        assert "def swi_glu(input, dim):" in result

    def test_idempotent_when_already_canonical(self):
        """已是 canonical block → 返回原文（幂等）。"""
        assert _inject_wrapper_block(self.BLOCK, "swi_glu", self.BLOCK) == self.BLOCK

    def test_append_when_absent_preserves_siblings(self):
        """无既有 def → 追加；兄弟函数（add）保留。"""
        existing = "def add(a, b):\n    return torch.ops.cann_bench.add(a, b)\n"
        result = _inject_wrapper_block(existing, "swi_glu", self.BLOCK)
        assert "def add(a, b):" in result
        assert "def swi_glu(input, dim):" in result
        assert result.count("def add(") == 1
        assert result.count("def swi_glu(") == 1

    def test_replaces_with_preceding_comment_block(self):
        """既有 def 带 deterministic 注释 → 注释行一并替换（不留孤儿注释）。"""
        existing = (
            "# swi_glu wrapper (deterministic, cannbench_adapt)\n"
            "def swi_glu(wrong_a, wrong_b):\n"
            "    return torch.ops.cann_bench.npu_wrong(wrong_a, wrong_b)\n"
        )
        result = _inject_wrapper_block(existing, "swi_glu", self.BLOCK)
        assert result == self.BLOCK  # 注释+def 整段被 canonical 覆盖
        assert result.count("# swi_glu wrapper") == 1
        assert "wrong_a" not in result


# —— P10：transition m.def schema 对齐（seed_wrapper 隔离 wrapper 路径）————

class TestTransitionSchemaAlign:
    """P10 m.def rename。seed_wrapper=True 隔离掉 wrapper 注入（injected=False），
    让 rebuild 仅由 schema_renamed 驱动，聚焦 P10 行为。"""

    def test_rename_triggers_rebuild(self, tmp_path):
        spec = OperatorSpec(
            name="swi_glu",
            inputs=[TensorSpec(name="input")],
            attrs={"dim": AttrSpec(name="dim", type="int")},
        )
        state = _make_state(
            tmp_path, 'm.def("swi_glu(Tensor x, int dim=-1) -> Tensor");', spec,
            seed_wrapper=True,
        )
        with patch("ascendc_devkit.orchestration.stages.deploy.Deployer") as MockDep:
            MockDep.return_value.build_install.return_value = (DeployResult(), None)
            new_state = CannbenchAdaptStage().transition(state, {})
        assert new_state.adapt_result.schema_renamed == [{"from": "x", "to": "input"}]
        plugin = (state.op_identity.op_dir / "op_plugin" / "swi_glu_plugin.cpp").read_text()
        assert "Tensor input" in plugin and "Tensor x" not in plugin
        MockDep.return_value.build_install.assert_called_once()

    def test_no_mismatch_no_rebuild(self, tmp_path):
        spec = OperatorSpec(
            name="swi_glu",
            inputs=[TensorSpec(name="input")],
            attrs={"dim": AttrSpec(name="dim", type="int")},
        )
        state = _make_state(
            tmp_path, 'm.def("swi_glu(Tensor input, int dim=-1) -> Tensor");', spec,
            seed_wrapper=True,
        )
        with patch("ascendc_devkit.orchestration.stages.deploy.Deployer") as MockDep:
            MockDep.return_value.build_install.return_value = (DeployResult(), None)
            new_state = CannbenchAdaptStage().transition(state, {})
        assert new_state.adapt_result.schema_renamed == []
        MockDep.return_value.build_install.assert_not_called()

    def test_rebuild_failure_blocks_eval(self, tmp_path):
        spec = OperatorSpec(
            name="swi_glu",
            inputs=[TensorSpec(name="input")],
            attrs={"dim": AttrSpec(name="dim", type="int")},
        )
        state = _make_state(
            tmp_path, 'm.def("swi_glu(Tensor x, int dim=-1) -> Tensor");', spec,
            seed_wrapper=True,
        )
        with patch("ascendc_devkit.orchestration.stages.deploy.Deployer") as MockDep:
            MockDep.return_value.build_install.return_value = (
                DeployResult(smoke_passed=False),
                ErrorFeedback(stage_name="deploy", error_type="deploy_failed",
                              message="build fail"),
            )
            new_state = CannbenchAdaptStage().transition(state, {})
        # rebuild 失败 → last_error(deploy_failed)；fail_strategy=continue，由
        # cannbench_eval 加载期校验兜 infra-0（方案 2 防御纵深）
        assert new_state.last_error is not None
        assert new_state.last_error.error_type == "deploy_failed"

    def test_param_count_mismatch_records_error_no_rename(self, tmp_path):
        # proto 1 个参数，schema 2 个 → 数量不一致，不 rename、不 rebuild，记 error
        spec = OperatorSpec(name="op", inputs=[TensorSpec(name="input")], attrs={})
        state = _make_state(
            tmp_path, 'm.def("op(Tensor x, int dim) -> Tensor");', spec, op_name="op",
            seed_wrapper=True,
        )
        with patch("ascendc_devkit.orchestration.stages.deploy.Deployer") as MockDep:
            MockDep.return_value.build_install.return_value = (DeployResult(), None)
            new_state = CannbenchAdaptStage().transition(state, {})
        assert new_state.adapt_result.schema_renamed == []
        MockDep.return_value.build_install.assert_not_called()
        assert new_state.adapt_result.errors  # 非空：记录了数量不一致

    def test_no_op_spec_skips_align(self, tmp_path):
        # 无 proto 基准 → 跳过对齐（不 crash）
        state = _make_state(
            tmp_path, 'm.def("swi_glu(Tensor x, int dim=-1) -> Tensor");',
            OperatorSpec(name="swi_glu", inputs=[TensorSpec(name="input")],
                         attrs={"dim": AttrSpec(name="dim", type="int")}),
        ).with_updates(requirement=None)
        with patch("ascendc_devkit.orchestration.stages.deploy.Deployer") as MockDep:
            MockDep.return_value.build_install.return_value = (DeployResult(), None)
            new_state = CannbenchAdaptStage().transition(state, {})
        assert new_state.adapt_result.schema_renamed == []
        MockDep.return_value.build_install.assert_not_called()


# —— W4：stage 集成（确定性 wrapper 注入驱动 rebuild）———————————

class TestDiscoveryRebuild:
    """发现就绪根治（P96/P97）+ 方案 G：wrapper 注入 → 统一一次 clean rebuild
    （clean_build=True，让新 wrapper 进 _C + per-op 包同步）。rebuild 失败 →
    last_error(deploy_failed)，由 cannbench_eval 加载期校验兜底（方案 2）。"""

    def test_wrapper_injection_triggers_clean_rebuild(self, tmp_path):
        """W4：空 __init__ → wrapper 注入 → clean rebuild（clean_build=True，单次）。"""
        spec = OperatorSpec(name="op", inputs=[TensorSpec(name="x")], attrs={})
        state = _make_state(
            tmp_path, 'm.def("op(Tensor x) -> Tensor");', spec, op_name="op",
            seed_wrapper=False)
        with patch("ascendc_devkit.orchestration.stages.deploy.Deployer") as MockDep:
            MockDep.return_value.build_install.return_value = (DeployResult(), None)
            new_state = CannbenchAdaptStage().transition(state, {})
        MockDep.return_value.build_install.assert_called_once()
        assert MockDep.return_value.build_install.call_args.kwargs["clean_build"] is True
        assert new_state.adapt_result.rebuilt is True
        assert new_state.adapt_result.files_modified == ["cann_bench/__init__.py"]
        # wrapper 三维落地
        content = (tmp_path / "cann_bench" / "__init__.py").read_text(encoding="utf-8")
        assert "def op(x):" in content
        assert "torch.ops.cann_bench.op(x)" in content

    def test_wrapper_idempotent_skips_rebuild(self, tmp_path):
        """canonical wrapper 已在 → injected=False + schema 对齐 → 零 rebuild。"""
        spec = OperatorSpec(name="op", inputs=[TensorSpec(name="x")], attrs={})
        state = _make_state(
            tmp_path, 'm.def("op(Tensor x) -> Tensor");', spec, op_name="op",
            seed_wrapper=True)
        with patch("ascendc_devkit.orchestration.stages.deploy.Deployer") as MockDep:
            new_state = CannbenchAdaptStage().transition(state, {})
        MockDep.return_value.build_install.assert_not_called()
        assert new_state.adapt_result.rebuilt is False
        assert new_state.adapt_result.files_modified == []

    def test_clean_rebuild_failure_sets_deploy_failed(self, tmp_path):
        spec = OperatorSpec(name="op", inputs=[TensorSpec(name="x")], attrs={})
        state = _make_state(
            tmp_path, 'm.def("op(Tensor x) -> Tensor");', spec, op_name="op",
            seed_wrapper=False)
        with patch("ascendc_devkit.orchestration.stages.deploy.Deployer") as MockDep:
            MockDep.return_value.build_install.return_value = (
                DeployResult(smoke_passed=False),
                ErrorFeedback(stage_name="deploy", error_type="deploy_failed", message="fail"),
            )
            new_state = CannbenchAdaptStage().transition(state, {})
        # rebuild 失败 → deploy_failed（continue，方案 2 兜 infra-0）
        assert new_state.last_error is not None
        assert new_state.last_error.error_type == "deploy_failed"

    def test_actions_is_empty_deterministic(self, tmp_path):
        """W4：确定性 stage 不再 spawn agent —— actions() 恒空。"""
        spec = OperatorSpec(name="op", inputs=[TensorSpec(name="x")])
        state = _make_state(
            tmp_path, 'm.def("op(Tensor x) -> Tensor");', spec, op_name="op")
        assert CannbenchAdaptStage().actions(state, 1) == []


# —— W5：cannbench-adapt agent 退役确认（§2.5 单一通路）——————————

class TestAgentRetired:
    """W5：守护 cannbench-adapt LLM agent 已彻底退役（无残留 spawn / agent.md）。"""

    def test_no_cannbench_adapt_agent_manifest(self):
        agent_path = REPO_ROOT / ".claude" / "agents" / "cannbench-adapt.md"
        assert not agent_path.exists(), (
            f"cannbench-adapt agent must be retired (方案75 §2.5); found {agent_path}"
        )

    def test_stage_module_has_no_spawnagent_reference(self):
        """stage 模块不再引用 SpawnAgent（AST 扫描，不受 docstring/注释干扰）。"""
        import ast
        src_path = (REPO_ROOT / "src" / "ascendc_devkit" / "orchestration" / "stages"
                    / "cannbench_adapt.py")
        tree = ast.parse(src_path.read_text(encoding="utf-8"))
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.alias) and node.name == "SpawnAgent":
                found.append("import " + node.name)
            if isinstance(node, ast.Name) and node.id == "SpawnAgent":
                found.append(f"name@{node.lineno}")
            if isinstance(node, ast.Attribute) and node.attr == "SpawnAgent":
                found.append(f"attr@{node.lineno}")
        assert not found, f"cannbench_adapt still references SpawnAgent: {found}"

    def test_no_cannbench_adapt_spawn_anywhere_in_src(self):
        """全仓 src/ 不再有 ``agent_name="cannbench-adapt"`` 的 spawn（§2.5 单一通路）。"""
        import re
        spawn_re = re.compile(r'agent_name\s*=\s*["\']cannbench-adapt["\']')
        hits = []
        for p in (REPO_ROOT / "src").rglob("*.py"):
            try:
                txt = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if spawn_re.search(txt):
                hits.append(str(p.relative_to(REPO_ROOT)))
        assert not hits, f"cannbench-adapt agent still spawned in: {hits}"


# —— proto.yaml schema 作 plugin 接口权威源 + 全等校验 ————————————

class TestProtoSchemaSource:
    """proto.yaml ``operator.schema``（``State.proto_schema``）是 plugin 接口 + harness 调用
    契约的共同权威（54/54 proto.yaml 均声明）。cannbench_adapt 参数名序优先取它，规避 op_spec
    畸形（outputs 被路由进 attrs，run 20260727-144633-2a1db8 gather 的 ``y`` 进了 wrapper）。"""

    def test_wrapper_uses_proto_schema_not_malformed_op_spec(self, tmp_path):
        """op_spec 畸形（inputs=[], attrs={x,index,y,dim}）但 proto.yaml schema 正确 →
        wrapper 取 proto 序 [x,index,dim]、**不含 y**。复现 2a1db8 gather 的真实数据通路。"""
        malformed_spec = OperatorSpec(
            name="gather", inputs=[], outputs=[],
            attrs={
                "x": AttrSpec(name="x", type=""),
                "index": AttrSpec(name="index", type=""),
                "y": AttrSpec(name="y", type=""),
                "dim": AttrSpec(name="dim", type="int64"),
            },
        )
        state = _make_state(
            tmp_path,
            'm.def("gather(Tensor x, Tensor index, int dim) -> Tensor");',
            malformed_spec, op_name="gather",
        ).with_updates(proto_schema="gather(Tensor x, Tensor index, int dim=0) -> Tensor y")
        injected, errors = _gen(state)
        assert injected is True
        content = (tmp_path / "cann_bench" / "__init__.py").read_text(encoding="utf-8")
        # wrapper 参数 = proto schema 序 [x, index, dim]，无 y
        assert "def gather(x, index, dim):" in content
        assert "(x, index, y" not in content and ", y," not in content

    def test_proto_schema_unparseable_falls_back_to_op_spec(self, tmp_path):
        """proto_schema 存在但不可 parse → fallback op_spec（记 WARN，§1.3）。"""
        spec = OperatorSpec(name="op", inputs=[TensorSpec(name="x")],
                            attrs={"dim": AttrSpec(name="dim", type="int")})
        state = _make_state(
            tmp_path, 'm.def("op(Tensor x, int dim) -> Tensor");', spec, op_name="op",
        ).with_updates(proto_schema="not a schema")
        injected, errors = _gen(state)
        assert injected is True
        assert any("proto_schema" in e and "fallback" in e for e in errors)

    def test_no_proto_schema_falls_back_to_op_spec(self, tmp_path):
        """无 proto_schema → 静默 fallback op_spec（非异常）。"""
        spec = OperatorSpec(name="op", inputs=[TensorSpec(name="x")])
        state = _make_state(
            tmp_path, 'm.def("op(Tensor x) -> Tensor");', spec, op_name="op",
        )
        injected, errors = _gen(state)
        assert injected is True


class TestSchemaAgainstProto:
    """加载期校验 plugin m.def schema vs proto.yaml schema 全等（§1.3）。"""

    def test_proto_mismatch_sets_last_error(self, tmp_path):
        """plugin gather(Tensor input, int dim, Tensor index) ≠ proto gather(x,index,dim)
        → schema_param_order_violation（同时抓顺序错 + 名字错 input vs x）。"""
        spec = OperatorSpec(
            name="gather",
            inputs=[TensorSpec(name="x"), TensorSpec(name="index")],
            attrs={"dim": AttrSpec(name="dim", type="int")},
        )
        state = _make_state(
            tmp_path,
            'm.def("gather(Tensor input, int dim, Tensor index) -> Tensor");',
            spec, op_name="gather", seed_wrapper=True,
        ).with_updates(proto_schema="gather(Tensor x, Tensor index, int dim=0) -> Tensor y")
        with patch("ascendc_devkit.orchestration.stages.deploy.Deployer") as MockDep:
            MockDep.return_value.build_install.return_value = (DeployResult(smoke_passed=True), None)
            new_state = CannbenchAdaptStage().transition(state, {})
        assert new_state.last_error is not None
        assert new_state.last_error.error_type == "schema_param_order_violation"
        assert "proto.yaml" in new_state.last_error.message

    def test_proto_equal_no_violation(self, tmp_path):
        """plugin == proto schema（type+name+order 全等）→ 无违例。"""
        spec = OperatorSpec(
            name="gather",
            inputs=[TensorSpec(name="x"), TensorSpec(name="index")],
            attrs={"dim": AttrSpec(name="dim", type="int")},
        )
        state = _make_state(
            tmp_path,
            'm.def("gather(Tensor x, Tensor index, int dim) -> Tensor");',
            spec, op_name="gather", seed_wrapper=True,
        ).with_updates(proto_schema="gather(Tensor x, Tensor index, int dim=0) -> Tensor y")
        with patch("ascendc_devkit.orchestration.stages.deploy.Deployer") as MockDep:
            MockDep.return_value.build_install.return_value = (DeployResult(smoke_passed=True), None)
            new_state = CannbenchAdaptStage().transition(state, {})
        assert not (new_state.last_error is not None
                    and new_state.last_error.error_type == "schema_param_order_violation")

    def test_no_plugin_no_violation(self, tmp_path):
        """无 op_plugin 文件 → 校验跳过（不 crash、不报违例）。"""
        spec = OperatorSpec(name="op", inputs=[TensorSpec(name="x")])
        state = _make_state(
            tmp_path, 'm.def("op(Tensor x) -> Tensor");', spec, op_name="op",
            seed_wrapper=True,
        ).with_updates(proto_schema="op(Tensor x) -> Tensor y")
        (state.op_identity.op_dir / "op_plugin" / "op_plugin.cpp").unlink()
        with patch("ascendc_devkit.orchestration.stages.deploy.Deployer") as MockDep:
            MockDep.return_value.build_install.return_value = (DeployResult(smoke_passed=True), None)
            new_state = CannbenchAdaptStage().transition(state, {})
        assert not (new_state.last_error is not None
                    and new_state.last_error.error_type == "schema_param_order_violation")

    def test_no_proto_degrades_to_structural(self, tmp_path):
        """无 proto_schema → 退化结构校验（抓 scalar 夹中间；名字错抓不了，已知取舍）。"""
        spec = OperatorSpec(
            name="gather",
            inputs=[TensorSpec(name="x"), TensorSpec(name="index")],
            attrs={"dim": AttrSpec(name="dim", type="int")},
        )
        state = _make_state(
            tmp_path,
            'm.def("gather(Tensor input, int dim, Tensor index) -> Tensor");',
            spec, op_name="gather", seed_wrapper=True,
        )
        with patch("ascendc_devkit.orchestration.stages.deploy.Deployer") as MockDep:
            MockDep.return_value.build_install.return_value = (DeployResult(smoke_passed=True), None)
            new_state = CannbenchAdaptStage().transition(state, {})
        assert new_state.last_error is not None
        assert new_state.last_error.error_type == "schema_param_order_violation"
