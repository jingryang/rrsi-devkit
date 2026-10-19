"""Name-keyed golden argument binding for the ST harness.

Why this exists
---------------
The generated harness calls the golden reference function with positional input
tensors plus per-case attrs as keyword arguments::

    golden(*tensors, **attrs)

A naive positional call only works when the golden lists **every tensor before
every scalar**. Goldens that lead with scalars break it — e.g.
``advance_step_v2(num_seqs, num_queries, block_size, input_tokens, ...)``:
``tensors[0]`` binds the first scalar parameter (``num_seqs``) positionally,
then ``attrs['num_seqs']`` rebinds it →
``TypeError: advance_step_v2() got multiple values for argument 'num_seqs'``.
The kernel side (op-plugin schema, tensors-first) binds fine; only the golden
call is wrong.

Convention
----------
cann-bench's own evaluator does NOT call the golden positionally. It walks the
golden's real signature (``kernel_eval/utils/param_builder.py::build_call_params``),
classifies each parameter by annotation (``Tensor`` → next positional tensor in
signature order; scalar → attr by name, else default), builds a **name-keyed**
kwarg dict, and calls ``golden(**params)`` — order-independent. This module is
the DevKit harness's faithful port of that convention.

Self-containment
----------------
Stdlib-only (``inspect``) and **annotation-free on the function itself** so its
source is portable: the harness inlines this function's source via
``inspect.getsource`` (see ``runner.py::_build_test_harness``) into the generated
``harness.py``. A function carrying typing annotations (``Callable`` /
``List[Any]`` / ...) would fail at def-time in the harness, which does not import
``typing`` — so the inlined source must reference only names the harness already
has (``inspect``). Golden binding is on the critical path for every operator and
must not gain a runtime dependency on ``ascendc_devkit`` being importable in the
subprocess.
"""
from __future__ import annotations

import inspect


def bind_golden_args(fn, tensors, attrs):
    """Build name-keyed call kwargs for ``fn`` from positional tensors + attrs.

    Walks ``fn``'s signature; for each parameter:

    * annotation mentions ``Tensor`` → consume the next positional tensor (in
      signature order). Exhausted tensors fall back to the param's default;
      a *required* tensor param with no tensor is **omitted** so ``fn(**kw)``
      raises a clear ``missing required argument`` instead of being masked by
      ``None`` (§1.2 可诊断).
    * name present in ``attrs`` → use that attr value.
    * otherwise → use the param's default if it has one; else omit (surfaces as
      a clear missing-argument error rather than a silent ``None``).

    Classification is by **objective structural signal** (the ``Tensor``
    annotation), never by parameter/op name (§1.12) — any golden with annotated
    Tensor / scalar params is handled uniformly regardless of how they interleave.

    Args:
        fn: golden callable whose parameters carry ``Tensor`` / scalar annotations.
        tensors: positional input tensors, in proto.yaml ``inputs`` order
            (TensorList inputs already grouped as one list element each).
        attrs: per-case scalar attrs, e.g. ``{'num_seqs': 314, ...}``.

    Returns:
        ``{param_name: value}`` dict; call as ``fn(**bind_golden_args(fn, tensors, attrs))``.

    Note: annotations are intentionally omitted from this def — see module
    docstring (source is inlined into the generated harness via getsource).
    """
    sig = inspect.signature(fn)
    kw = {}
    ti = 0
    n = len(tensors)
    for name, param in sig.parameters.items():
        ann = "" if param.annotation is inspect.Parameter.empty else str(param.annotation)
        has_default = param.default is not inspect.Parameter.empty
        if "Tensor" in ann:
            if ti < n:
                kw[name] = tensors[ti]
                ti += 1
            elif has_default:
                kw[name] = param.default
            # required tensor with no input → omit (clear missing-arg error)
        elif name in attrs:
            kw[name] = attrs[name]
        elif has_default:
            kw[name] = param.default
        # required scalar absent from attrs, no default → omit (clear error)
    return kw

