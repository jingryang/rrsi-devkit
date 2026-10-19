"""UT for ``bind_golden_args`` — name-keyed golden argument binding.

Guards the regression where the harness called the golden positionally
(``golden(*tensors, **attrs)``) and broke on goldens that lead with scalars
(``advance_step_v2(num_seqs, num_queries, block_size, input_tokens, ...)`` →
``got multiple values for argument 'num_seqs'``).

All cases are structural-signal driven (Tensor annotation vs scalar); no
operator-name branching (§1.12). ``advance_step_v2`` appears only as a fixture
sample mirroring its real golden signature.

NOTE: this module deliberately does NOT use ``from __future__ import
annotations``. Real cann-bench goldens resolve annotations to real objects
(their modules lack that import), and ``bind_golden_args`` mirrors cann-bench's
str-based annotation check — so fixtures must carry resolved annotations too.
"""

import inspect

import pytest

from ascendc_devkit.adapters.npu.golden_binding import bind_golden_args

try:
    import torch
    _T = torch.Tensor
except Exception:  # torch-free CI: annotation text still carries "Tensor"
    _T = "Tensor"


# —— golden signature fixtures (mirror real shapes) ————————————————————


def _golden_scalars_first(num_seqs: int, num_queries: int, block_size: int,
                          input_tokens: _T, sampled_token_ids: _T,
                          input_positions: _T, seq_lens: _T,
                          slot_mapping: _T, block_tables: _T,
                          spec_token: _T, accepted_num: _T):
    # mirrors bench_lab/kernel_bench/level2/advance_step_v2/golden.py
    return (input_tokens, input_positions, seq_lens, slot_mapping)


def _golden_tensors_first(input_tokens: _T, sampled_token_ids: _T,
                          input_positions: _T, seq_lens: _T,
                          slot_mapping: _T, block_tables: _T,
                          spec_token: _T, accepted_num: _T,
                          num_seqs: int, num_queries: int, block_size: int):
    # mirrors the op-plugin schema order (tensors-first)
    return (input_tokens, input_positions, seq_lens, slot_mapping)


def _golden_interleaved(alpha: float, x: _T, beta: float, y: _T):
    return (x, y)


def _golden_optional_tensor(a: _T, b: _T = None, scale: int = 1):
    return (a, b)


def _golden_optional_scalar(x: _T, eps: float = 1e-6):
    return x


# —— bind correctness ————————————————————————————————————————————


def _tensors(n):
    return [object() for _ in range(n)]


def test_scalars_first_golden_binds_without_duplicate():
    """The bug: scalars-first golden + positional tensors → 'got multiple values
    for num_seqs'. Name-keyed binding must succeed."""
    tensors = _tensors(8)
    attrs = {"num_seqs": 314, "num_queries": 314, "block_size": 8}
    kw = bind_golden_args(_golden_scalars_first, tensors, attrs)
    # scalars come from attrs
    assert kw["num_seqs"] == 314 and kw["num_queries"] == 314 and kw["block_size"] == 8
    # 8 tensors land on the 8 Tensor params in signature order
    tensor_params = [p for p in inspect.signature(_golden_scalars_first).parameters
                     if p not in attrs]
    for tp, t in zip(tensor_params, tensors):
        assert kw[tp] is t
    # actual call must not raise
    _golden_scalars_first(**kw)


def test_tensors_first_golden_still_binds():
    """Common case (tensors-first) must keep working — strict improvement."""
    tensors = _tensors(8)
    attrs = {"num_seqs": 314, "num_queries": 314, "block_size": 8}
    kw = bind_golden_args(_golden_tensors_first, tensors, attrs)
    _golden_tensors_first(**kw)
    assert kw["num_seqs"] == 314 and kw["input_tokens"] is tensors[0]


def test_interleaved_scalars_and_tensors():
    tensors = _tensors(2)
    attrs = {"alpha": 0.1, "beta": 0.2}
    kw = bind_golden_args(_golden_interleaved, tensors, attrs)
    _golden_interleaved(**kw)
    assert kw["alpha"] == 0.1 and kw["beta"] == 0.2
    assert kw["x"] is tensors[0] and kw["y"] is tensors[1]


def test_attrs_keys_not_in_signature_are_ignored():
    """Extra attrs (no matching param) are silently dropped, matching cann-bench
    build_call_params (iterates signature params only)."""
    tensors = _tensors(2)  # interleaved needs x, y
    attrs = {"alpha": 0.1, "beta": 0.2, "stray_key": 999}  # interleaved has no stray_key
    kw = bind_golden_args(_golden_interleaved, tensors, attrs)
    assert "stray_key" not in kw
    _golden_interleaved(**kw)


def test_optional_tensor_missing_uses_default():
    tensors = _tensors(1)  # only `a`; `b` left to default
    attrs = {"scale": 4}
    kw = bind_golden_args(_golden_optional_tensor, tensors, attrs)
    assert kw["a"] is tensors[0]
    assert kw["b"] is None  # default
    assert kw["scale"] == 4
    _golden_optional_tensor(**kw)


def test_optional_scalar_absent_from_attrs_uses_default():
    tensors = _tensors(1)  # eps not in attrs
    kw = bind_golden_args(_golden_optional_scalar, tensors, {})
    assert kw["x"] is tensors[0]
    assert kw["eps"] == pytest.approx(1e-6)
    _golden_optional_scalar(**kw)


def test_required_tensor_exhausted_is_omitted_not_masked():
    """A required Tensor param with no tensor must NOT be set to None (would mask
    a proto/golden tensor-count mismatch). Omit → fn(**kw) raises a clear error."""
    tensors = _tensors(7)  # scalars_first needs 8
    attrs = {"num_seqs": 1, "num_queries": 1, "block_size": 1}
    kw = bind_golden_args(_golden_scalars_first, tensors, attrs)
    # exactly one Tensor param omitted
    tensor_params = [p for p in inspect.signature(_golden_scalars_first).parameters
                     if p not in attrs]
    bound = [p for p in tensor_params if p in kw]
    assert len(bound) == 7
    with pytest.raises(TypeError):  # missing required argument, not silent None
        _golden_scalars_first(**kw)


def test_required_scalar_absent_and_no_default_is_omitted():
    """A required scalar not in attrs must surface as a clear missing-arg error."""
    def g(x: _T, mode: int):
        return x
    tensors = _tensors(1)
    kw = bind_golden_args(g, tensors, {})  # mode missing
    assert kw["x"] is tensors[0]
    with pytest.raises(TypeError):
        g(**kw)


# —— regression contrast: naive positional binding fails where name-keyed works —


def test_naive_positional_would_fail_on_scalars_first():
    """Documents the pre-fix failure mode: ``golden(*tensors, **attrs)`` raises
    'got multiple values' on a scalars-first golden. The name-keyed helper does
    not. Kept as an explicit contrast so the regression cannot silently return."""
    tensors = _tensors(8)
    attrs = {"num_seqs": 314, "num_queries": 314, "block_size": 8}
    with pytest.raises(TypeError, match="multiple values"):
        _golden_scalars_first(*tensors, **attrs)
    # name-keyed path is clean
    _golden_scalars_first(**bind_golden_args(_golden_scalars_first, tensors, attrs))


# —— portability + edge annotations —————————————————————————————————


def test_getsource_is_portable_into_harness_namespace():
    """The harness inlines ``bind_golden_args`` via ``inspect.getsource`` into
    the generated ``harness.py``, whose namespace offers only ``inspect`` (no
    ``typing`` import). So the function must carry **no typing annotations** — a
    def-time annotation like ``Callable`` / ``List[Any]`` would NameError when
    the inlined def is evaluated in the harness (I hit this exact failure during
    development: typing annotations broke the inlined copy at def-time).

    This test execs the getsource'd source in a bare ``{inspect}`` namespace —
    the minimal contract the generated harness guarantees — and confirms the
    inlined copy still binds a scalars-first golden. Guards the portability
    invariant documented in ``golden_binding.py``."""
    import inspect as _inspect
    from ascendc_devkit.adapters.npu.golden_binding import bind_golden_args

    src = _inspect.getsource(bind_golden_args)
    ns = {"inspect": _inspect}  # exactly what the generated harness offers here
    exec(src, ns)  # must not raise — no typing-annotation NameError

    inlined = ns["bind_golden_args"]
    # the inlined copy works on the bug shape (scalars-first); tensors annotated
    def g(num_seqs: int, block_size: int, x: "Tensor"):
        return (num_seqs, block_size, x)
    assert inlined(g, ["T0"], {"num_seqs": 5, "block_size": 8}) == \
        {"num_seqs": 5, "block_size": 8, "x": "T0"}


def test_rendered_harness_inlines_a_working_bind_golden_args():
    """End-to-end at the binding layer: ``_build_test_harness`` must render a
    harness whose inlined ``bind_golden_args`` is present AND callable — not just
    textually present (drift-guard) but actually executable against a
    scalars-first golden. Catches a substitution/wiring break that source-grep
    would miss. No NPU needed: golden binding is pure Python."""
    import ast as _ast
    import inspect as _inspect
    from ascendc_devkit.adapters.npu.precision_comparer import DevkitComparer
    from ascendc_devkit.adapters.npu.runner import NPURunner
    from ascendc_devkit.domain.operator import OperatorSpec
    from ascendc_devkit.domain.precision import CompareRule
    from ascendc_devkit.domain.requirement import TestCase
    from types import SimpleNamespace

    r = NPURunner.__new__(NPURunner); r._chip_version = "A2"; r._torch_npu_available = True
    op = OperatorSpec(name="add")
    tc = [TestCase(name="basic",
            inputs=[{"name": "a", "shape": [8], "dtype": "fp16"},
                    {"name": "b", "shape": [8], "dtype": "fp16"}])]
    src = r._build_test_harness(
        op, tc,
        golden_contract={"path": "/tmp/g.py", "entry": "reference", "input_type": "numpy"},
        deploy_result=SimpleNamespace(python_path="/p", install_path="/i", ld_library_path_add=""),
        callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.add"},
        rule=CompareRule(dtype_thresholds={"*": 1e-2}), comparer=DevkitComparer())

    # extract the inlined bind_golden_args FunctionDef from the rendered harness
    tree = _ast.parse(src)
    fn = next((n for n in tree.body if isinstance(n, _ast.FunctionDef)
               and n.name == "bind_golden_args"), None)
    assert fn is not None, "rendered harness does not inline bind_golden_args"
    inlined_src = _ast.get_source_segment(src, fn)
    ns = {"inspect": _inspect}
    exec(compile(_ast.Module(body=[fn], type_ignores=[]), "<harness>", "exec"), ns)
    inlined = ns["bind_golden_args"]

    # the rendered-and-exec'd copy resolves a scalars-first golden correctly
    def g(num_seqs: int, num_queries: int, block_size: int, x: "Tensor", y: "Tensor"):
        return (num_seqs, x, y)
    kw = inlined(g, ["T0", "T1"], {"num_seqs": 7, "num_queries": 7, "block_size": 8})
    assert kw == {"num_seqs": 7, "num_queries": 7, "block_size": 8, "x": "T0", "y": "T1"}
    g(**kw)  # no 'got multiple values'


def test_tensorlist_annotation_consumes_one_grouped_input():
    """A ``List[Tensor]`` param (TensorList) is detected as a tensor param and
    consumes ONE entry from ``tensors`` — the grouped list the harness builds
    (one element per TensorList input), not one per element. Mirrors cann-bench
    ``build_call_params`` List[Tensor] handling; the harness has explicit
    TensorList grouping (``_flatten_shape``), so this annotation shape is real."""
    def g(x: "List[Tensor]", scale: int):
        return (x, scale)
    grouped = [["t0", "t1", "t2"]]  # one TensorList input = 3 elements grouped as 1
    kw = bind_golden_args(g, grouped, {"scale": 3})
    assert kw["x"] == ["t0", "t1", "t2"]  # whole list → the single List[Tensor] param
    assert kw["scale"] == 3
    g(**kw)


# ─── golden_precision: harness golden 参考精度对齐 cann-bench eval ────────────
# 背景：eval 默认 fp64_cpu（升 fp64 算参考，比较时截断回 kernel dtype），harness
# 曾直接用原生 dtype 算参考 → debug 判过而 eval 判挂。harness 必须烘焙同一精度。
# 用例见 docs/plan（golden_precision harness-eval 分裂）。


def _render_harness_with_golden_contract(golden_contract):
    """渲染 harness 源码（golden_contract 可带 precision 键），返回源码字符串。"""
    from ascendc_devkit.adapters.npu.precision_comparer import DevkitComparer
    from ascendc_devkit.adapters.npu.runner import NPURunner
    from ascendc_devkit.domain.operator import OperatorSpec
    from ascendc_devkit.domain.precision import CompareRule
    from ascendc_devkit.domain.requirement import TestCase
    from types import SimpleNamespace
    r = NPURunner.__new__(NPURunner); r._chip_version = "A2"; r._torch_npu_available = True
    op = OperatorSpec(name="add")
    tc = [TestCase(name="basic",
            inputs=[{"name": "a", "shape": [8], "dtype": "fp16"},
                    {"name": "b", "shape": [8], "dtype": "fp16"}])]
    gc = dict(golden_contract)
    gc.setdefault("path", "/tmp/g.py")
    gc.setdefault("entry", "reference")
    gc.setdefault("input_type", "torch")
    return r._build_test_harness(
        op, tc,
        golden_contract=gc,
        deploy_result=SimpleNamespace(python_path="/p", install_path="/i",
                                      ld_library_path_add=""),
        callable_target={"kind": "torch_op", "symbol": "torch.ops.cann_bench.add"},
        rule=CompareRule(dtype_thresholds={"*": 1e-2}), comparer=DevkitComparer())


def test_rendered_harness_bakes_golden_precision_fp64_upcast():
    """fp64_cpu（eval 权威参考）必须烘焙进 harness：golden 调用前把浮点输入升
    fp64（``_upcast_fp64`` + ``golden_precision == 'fp64_cpu'`` 分支）。
    否则 debug 参考 ≠ eval 参考 → 假收敛（20/20 vs 13/20）。"""
    src = _render_harness_with_golden_contract({"precision": "fp64_cpu"})
    assert "golden_precision = 'fp64_cpu'" in src
    assert "def _upcast_fp64" in src
    # CANN 路径 golden 调用点上抛 fp64（不是拿原生 dtype 直喂 golden）
    assert "_upcast_fp64(_torch_inputs)" in src
    assert "golden_precision == 'fp64_cpu'" in src


def test_rendered_harness_fallback_golden_path_upcasts_fp64():
    """fallback 路径（golden_input_type != torch 的 numpy golden + 独立 fallback）
    在 fp64_cpu 时同样把浮点输入升 float64——任意 golden 调用路径参考一致，否则
    fallback 用原生参考仍会与 eval（fp64）分裂。比较器两侧都按 kernel dtype 截断
    golden（.to(target_dtype).double()），语义已对齐。"""
    src = _render_harness_with_golden_contract({"precision": "fp64_cpu"})
    # 独立 fallback 路径：_np_inputs 原地 astype(np.float64)（golden_fn(*_np_inputs)）
    assert "a.astype(np.float64)" in src
    assert "np.issubdtype(a.dtype, np.floating)" in src
    # CANN 路径 numpy golden（golden_input_type != torch 分支）同样上抛
    assert src.count("astype(np.float64)") >= 2  # 两条 golden 调用路径都升 fp64


def test_rendered_harness_defaults_golden_precision_fp64():
    """golden_contract 未带 precision 时，runner 落默认 fp64_cpu（对齐 cann-bench
    BenchConfig 默认）——老 contract（path/entry/input_type 三键）不被遗忘。"""
    src = _render_harness_with_golden_contract({})
    assert "golden_precision = 'fp64_cpu'" in src


def test_rendered_harness_native_precision_keeps_native_golden():
    """native_cpu 明确声明时保持原生 dtype 参考（不升精度）。烘焙的 golden_precision
    变量必须是 'native_cpu'（运行时条件表达式取 else 分支，不走 fp64 上抛）。"""
    src = _render_harness_with_golden_contract({"precision": "native_cpu"})
    assert "golden_precision = 'native_cpu'" in src
    assert "golden_precision = 'fp64_cpu'" not in src


def test_rendered_harness_authority_golden_gated_by_precision():
    """review M3：权威 golden 选择抽公共决策函数 _select_authority_golden，三处
    golden 路径（CANN torch / CANN numpy / 独立 fallback）统一调用（§2.5 单一通路）。
    native_cpu 时 fp64 计算必须被 golden_precision 门控（cann-bench 语义：不升
    fp64、直接复用 Golden 输出）；fp64_cpu 时仍走 fp64 权威。"""
    import re
    native = _render_harness_with_golden_contract({"precision": "native_cpu"})
    fp64 = _render_harness_with_golden_contract({"precision": "fp64_cpu"})

    # 公共决策函数内联
    assert "def _select_authority_golden(" in native
    assert "def _select_authority_golden(" in fp64

    def _calls(src):
        return len(re.findall(r"(?<!def )_select_authority_golden\(", src))
    assert _calls(native) == 3, "三处 golden 路径都必须走单一决策点"
    assert _calls(fp64) == 3

    # 三处 fp64 计算行在 native_cpu 渲染下必须被 golden_precision 门控包裹
    for src, prec in ((native, "native_cpu"), (fp64, "fp64_cpu")):
        lines = src.split("\n")
        fp64_sites = [i for i, l in enumerate(lines)
                      if "_upcast_fp64(_torch_inputs)" in l
                      or "golden_fn(*_upcast_fp64" in l]
        assert len(fp64_sites) == 3, f"{prec}: 期望 3 处 fp64 计算，实际 {len(fp64_sites)}"
        for i in fp64_sites:
            ctx = lines[max(0, i - 6):i]
            gated = any("golden_precision == 'fp64_cpu'" in c for c in ctx)
            # native_cpu 渲染下 fp64 计算必须被门控（不升 fp64）；fp64_cpu 渲染下
            # 同样被门控（条件恒真分支，语法一致）。
            assert gated, f"{prec}: fp64 计算未按 golden_precision 门控 (line {i + 1})"

    # native_cpu 时权威选择 = native：_select_authority_golden 在
    # golden_precision != 'fp64_cpu' 时返回 native 作权威（cann-bench 语义）。
    assert "return _native_out, True" in native  # native_cpu 权威 = native


def test_select_authority_golden_behavior():
    """review M3（函数级）: 提取渲染出的 ``_select_authority_golden`` 独立执行，
    验证三种输入路径的权威选择（单一决策点，§2.5）：

    - golden_precision=fp64_cpu 且 fp64 可用 → fp64 作权威（native_as_authority=False）；
    - golden_precision=native_cpu → native 作权威（True），即使 fp64 已算好也不取；
    - fp64_cpu 但 fp64 不可用（F1 宽容兜底）→ 回退 native 作权威（True）。
    """
    import ast as _ast, textwrap
    src = _render_harness_with_golden_contract({"precision": "fp64_cpu"})
    tree = _ast.parse(src)
    fn = next((n for n in tree.body if isinstance(n, _ast.FunctionDef)
               and n.name == "_select_authority_golden"), None)
    assert fn is not None, "rendered harness does not inline _select_authority_golden"
    # 取函数 def 文本，把模板级全局 golden_precision 替换为注入变量后独立 exec。
    fn_src = textwrap.dedent(_ast.get_source_segment(src, fn))
    fn_src = fn_src.replace(
        "golden_precision != 'fp64_cpu'", "__gp != 'fp64_cpu'")
    ns = {"__gp": "fp64_cpu"}
    exec(compile(fn_src, "<select_authority_golden>", "exec"), ns)
    sel = ns["_select_authority_golden"]

    # fp64_cpu + fp64 可用 → fp64 权威
    got, is_native = sel("NATIVE", "FP64")
    assert got == "FP64" and is_native is False
    # native_cpu → native 权威（fp64 已算好也不取）
    ns["__gp"] = "native_cpu"
    got, is_native = sel("NATIVE", "FP64")
    assert got == "NATIVE" and is_native is True
    # fp64_cpu 但 fp64 不可用 → 回退 native 权威
    ns["__gp"] = "fp64_cpu"
    got, is_native = sel("NATIVE", None)
    assert got == "NATIVE" and is_native is True


def test_fp64_cpu_authority_contract_preserved():
    """fp64_cpu（默认路径，同事验证）行为不变式守护（review M3 回归门）:

    M3 前 fp64_cpu 是"无条件算 fp64 权威 + native 作 native_output/兜底"；M3 后
    抽 _select_authority_golden 后，fp64_cpu 的**渲染语义必须与改动前逐字节等价**
    （git worktree 对照实证 diff=0）。本条把 fp64_cpu 的关键契约固化为断言，防
    未来改动把默认路径改坏：

    - 三个 golden 调用点的权威选择都走 _select_authority_golden(native, fp64)——
      第一实参是 native 结果、第二实参是 fp64 结果（顺序不能反，反了权威会错）；
    - 比较器 golden 实参来自权威选择结果（fp64_cpu 下即 fp64）；
    - native_output/native_refs 仅在 fp64 作权威时传 native（M3 前 _fp64_ok 语义）。

    若未来有人把 fp64_cpu 误改为 native 权威 / 传参顺序调反 / native_output 恒
    None，本条立刻红。
    """
    src = _render_harness_with_golden_contract({"precision": "fp64_cpu"})
    # 三个调用点都是 (native 结果, fp64 结果) 顺序——native 在前
    import re
    # 排除函数定义行（def _select_authority_golden(...)）——只匹配调用点
    calls = re.findall(
        r"(?<!def )_select_authority_golden\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)",
        src)
    assert len(calls) == 3, f"fp64_cpu 应有 3 处权威选择调用，实际 {len(calls)}"
    for native_arg, fp64_arg in calls:
        # 第一参（native 结果）名含 n（_n_raw_out/_n_tensors/_gnp/golden_np_list/native）
        # 第二参（fp64 结果）名含 fp64 或 _raw_out（_fp64_raw_out/_gnp_fp64）
        assert native_arg != fp64_arg, "权威选择两参相同——传参错误"
        assert "fp64" not in native_arg.lower(), \
            f"第一参应是 native 结果，实际是 {native_arg}（传参顺序反了）"
        assert ("fp64" in fp64_arg.lower() or "raw" in fp64_arg.lower()), \
            f"第二参应是 fp64 结果，实际是 {fp64_arg}"

    # fp64_cpu 下 _select_authority_golden 的 else 分支不生效：golden_precision=='fp64_cpu'
    # 时 _is_native=False → 返回 fp64 作权威（native_as_authority=False）。
    assert "golden_precision = 'fp64_cpu'" in src

    # 比较器 golden 实参来自权威选择（M3 前 _g_tensors 同理）——不直接引用 fp64 计算
    # 结果绕过决策函数（绕过了就等于把 M3 门控架空，native_cpu 也会误用 fp64）。
    assert "_compare_tensors(" in src or "compare_outputs(" in src
    # native_output/native_refs 语义：仅当 native 非权威时才传 native（fp64_cpu 成功
    # 时 native 是兜底 → 传；native_cpu 时 native 即权威 → None）。
    assert "None if _native_as_auth else" in src or "if _fp64_ok else None" in src


def test_upcast_fp64_behavior():
    """渲染出的 ``_upcast_fp64`` 可执行：fp16/bf16→fp64、int/None 不变、
    TensorList（list of tensors）逐元素升。镜像 cann-bench tensors_to_fp64_cpu。"""
    import ast as _ast
    src = _render_harness_with_golden_contract({"precision": "fp64_cpu"})
    tree = _ast.parse(src)
    fn = next((n for n in tree.body if isinstance(n, _ast.FunctionDef)
               and n.name == "_upcast_fp64"), None)
    assert fn is not None, "rendered harness does not inline _upcast_fp64"
    ns = {"torch": __import__("torch")} if _T is not str else {}
    exec(compile(_ast.Module(body=[fn], type_ignores=[]), "<harness>", "exec"), ns)
    up = ns["_upcast_fp64"]
    if _T is not str:  # torch 可用才断言 dtype；torch-free CI 只验结构
        import torch as _torch
        t16 = _torch.randn(4, dtype=_torch.float16)
        t32 = _torch.randn(4, dtype=_torch.float32)
        ti = _torch.randint(0, 4, (4,))
        out = up([t16, ti, None, [t16, t32]])
        assert out[0].dtype == _torch.float64 and (out[0].float().half() == t16).all()
        assert out[1].dtype == _torch.int64  # 非浮点不升
        assert out[2] is None
        assert [x.dtype for x in out[3]] == [_torch.float64, _torch.float64]  # TensorList
    else:  # torch-free CI：至少结构上无异常（跳过 dtype 断言）
        assert callable(up)


def test_golden_core_isolates_inplace_golden_inputs():
    """in-place golden（``mutation_mode=in_place``：golden 内 ``copy_`` 写回入参
    并返回它）下，native / fp64 两次参考调用必须各自基于**原始输入**。

    harness 在同一批输入对象上连调两次 golden（native 参考 + fp64 权威），
    ``_golden_core`` 只做 ``list(_inputs)`` 浅拷贝，golden 的原地写回会污染这批
    对象 → 第二次拿到的输入已是第一次的结果（``g(g(x))``）。参考真值失真，且
    污染同时传导到 native 与权威两侧，令小值域/相消兜底判据被平凡满足（
    ``small_value_cpu_error_count == small_value_error_count`` → 比值 1 ≤ 2）而
    **假通过**（实测：in-place 元素激活算子 debug 全绿 vs eval 有真实精度失败）。

    ``_golden_core`` 调用前经 ``_golden_inputs_copy`` 克隆输入即切断该耦合。
    本测试用真实 in-place golden 形态复现：无隔离时第二次结果 = 复合函数，
    有隔离时两次都 = 单次函数且原张量不被改写。
    """
    import ast as _ast
    src = _render_harness_with_golden_contract({"precision": "fp64_cpu"})
    tree = _ast.parse(src)
    fns = {n.name: n for n in tree.body if isinstance(n, _ast.FunctionDef)}
    assert "_golden_inputs_copy" in fns, \
        "rendered harness does not inline _golden_inputs_copy"
    assert "_golden_core" in fns

    if _T is str:  # torch-free CI：仅结构在位检查（执行需真实张量）
        return

    import numpy as _np
    ns = {"torch": torch, "np": _np, "bind_golden_args": bind_golden_args}

    def _inplace_golden(x: "torch.Tensor") -> "torch.Tensor":
        # 原地算子形态：写回入参并返回它（对齐 requirement.json mutation_mode=in_place）
        x.copy_(x * 2.0)
        return x

    ns["_golden_raw"] = _inplace_golden
    for name in ("_golden_inputs_copy", "_golden_core"):
        exec(compile(_ast.Module(body=[fns[name]], type_ignores=[]),
                     "<harness>", "exec"), ns)

    orig = torch.tensor([1.0, 2.0, 3.0])
    x = orig.clone()
    r1 = ns["_golden_core"]([x], {})
    r2 = ns["_golden_core"]([x], {})

    # ① 输入对象不被 golden 写回污染（隔离生效）
    assert torch.equal(x, orig), "in-place golden 污染了 harness 输入对象"
    # ② 两次参考一致：无隔离时第二次 = 4,8,12（复合），有隔离时都是 2,4,6
    assert torch.equal(r1, torch.tensor([2.0, 4.0, 6.0]))
    assert torch.equal(r2, r1), \
        f"第二次参考基于被污染的输入（g(g(x))）: r1={r1.tolist()} r2={r2.tolist()}"


def test_rendered_harness_bakes_eval_seed_default_zero():
    """eval_seed 缺省 → 烘焙 `_eval_seed = 0`（与 kernel_eval config.eval_seed 默认
    对齐），公式 `(eval_seed + SHA256(case_id)) % 2^31` 在 harness 内。"""
    src = _render_harness_with_golden_contract({})
    assert "_eval_seed = 0" in src
    assert "(_eval_seed + int.from_bytes(_digest[:8], byteorder='big')) % (2**31)" in src


def test_rendered_harness_threads_eval_seed_from_contract():
    """eval_seed 由契约显式传（state.eval_seed）——不再模板内硬编码 0。两侧种子
    漂移会静默分裂输入判定，故取值必须来自契约（F3 review 坐实）。"""
    src = _render_harness_with_golden_contract({"eval_seed": 5})
    assert "_eval_seed = 5" in src
    assert "_eval_seed = 0" not in src
