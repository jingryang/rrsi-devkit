"""L6 Adapters — cann-bench glue adapter (wrapper gen + m.def schema align).

Moved from orchestration/stages/cannbench_adapt.py (step-82 决策2=A 收口): the
cann-bench-specific glue — generating the ``cann_bench/__init__.py`` Python
wrapper (so cann-bench's ``scan_interfaces`` discovers the operator) and
aligning the op_plugin m.def schema param names to proto (P10) — is repo-specific
(a per-repo adapter, §1.6) and belongs at the adapter boundary, not the stage
layer. The stage now only orchestrates (resolve state → call these → Deployer
rebuild → write AdaptResult).

Both are deterministic (no LLM): the wrapper is a manifest pure function; the
rename is pure string post-processing. ``cann_bench`` pkg-root resolution reuses
``cannbench_env.resolve_cann_bench_pkg_root`` (single path, §2.5 — was duplicated
in the old stage).

Hard scope constraints (unchanged from the stage):
  - READ: codegen_manifest (operator signatures — NEVER design_spec), op_spec
  - WRITE: cann_bench/__init__.py wrapper, op_plugin m.def schema string
  - PROHIBITED: touching op_host/, op_kernel/, op_api/ sources beyond m.def rename
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ascendc_devkit.adapters.evaluation.cannbench_env import resolve_cann_bench_pkg_root
from ascendc_devkit.domain.mdef_parse import (
    parse_mdef_params,
    rename_mdef_schema,
    validate_schema_against_proto,
)
from ascendc_devkit.infra.logger import Logger


def align_schema_params(op_spec) -> list[str]:
    """Fallback 参数名序列（inputs 名在前、attrs 名在后）。

    ``proto.yaml operator.schema`` is authoritative. This op_spec-derived
    sequence is used only when that first-hand schema is absent or unparseable.
    """
    names = [t.name for t in (op_spec.inputs or [])]
    if op_spec.attrs:
        names.extend(op_spec.attrs.keys())
    return names


def schema_param_names(
    proto_schema: str | None, op_spec
) -> tuple[list[str] | None, list[str]]:
    """Resolve parameter names from proto schema, falling back to ``op_spec``."""
    messages: list[str] = []
    if proto_schema:
        names = parse_mdef_params(proto_schema)
        if names:
            return names, messages
        messages.append(
            "CannbenchAdapter: proto_schema exists but is unparseable; "
            "fallback to op_spec"
        )
    if op_spec is None:
        messages.append(
            "CannbenchAdapter: cannot derive parameter names — "
            "no proto_schema nor op_spec"
        )
        return None, messages
    return align_schema_params(op_spec), messages


def _build_wrapper(op_name: str, symbol_last: str, params: list[str]) -> str:
    """确定性派生 cann_bench wrapper（manifest 纯函数，方案 G / [[P112]]）。

    三维构造性保证：① ``def {op_name}`` 必存在；② 参数名取 proto（=golden，cann-bench
    ``func(**params)`` 关键字调用对）；③ 转发目标取 ``callable_target.symbol`` 末段（真实
    C++ 注册名，[[P98]]）。
    """
    sig = ", ".join(params)
    return (
        f"def {op_name}({sig}):\n"
        f"    return torch.ops.cann_bench.{symbol_last}({sig})\n"
    )


def _inject_wrapper_block(existing: str, op_name: str, block: str) -> str:
    """幂等注入 wrapper 块（AST 定位，robust to 类型注解 / 多行签名）。

    返回新文本；与 ``existing`` 相等表示幂等无变化（调用方据此决定是否 rebuild）。

    - 既有顶层 ``def {op_name}`` → 替换其行段（含可选前置 deterministic 注释）为 canonical
      ``block``（覆盖注解签名 / 多行签名 / 旧 LLM wrapper 等所有形态，不留重复 def）；
    - 无 AST 命中 → 追加（与上文空行分隔）；
    - AST 不可用（syntax error 文件）→ 退回正则 best-effort 定位（仍命中则替换，否则追加）。
    """
    lines = existing.splitlines(keepends=True)
    start_idx: int | None = None
    end_idx: int | None = None
    try:
        tree = ast.parse(existing)
    except SyntaxError:
        tree = None
    if tree is not None:
        for node in tree.body:
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == op_name
            ):
                start_idx = node.lineno - 1
                end_idx = node.end_lineno
                break
    if start_idx is not None and end_idx is not None:
        if start_idx - 1 >= 0 and lines[start_idx - 1].lstrip().startswith(
            f"# {op_name} wrapper (deterministic"
        ):
            start_idx -= 1
        if "".join(lines[start_idx:end_idx]).rstrip() == block.rstrip():
            return existing  # 幂等：已是 canonical
        return "".join(lines[:start_idx]) + block + "".join(lines[end_idx:])

    pattern = re.compile(
        r"(?:^[ \t]*# " + re.escape(op_name) + r" wrapper \(deterministic[^\n]*\n)?"
        r"^def " + re.escape(op_name) + r"\b[^\n]*(?:\n[ \t]+[^\n]*)*",
        re.MULTILINE,
    )
    match = pattern.search(existing)
    if match:
        return existing[: match.start()] + block + existing[match.end():]
    if existing == "":
        return block
    base = existing if existing.endswith("\n") else existing + "\n"
    return base + "\n" + block


def generate_and_inject_wrapper(
    codegen_manifest,
    op_spec,
    op_name_fallback,
    repo_root,
    source_dir,
    proto_schema: str | None = None,
) -> tuple[bool, list[str], list[str]]:
    """方案 G：确定性派生并幂等注入 ``cann_bench/__init__.py`` wrapper。

    Args are destructured from state by the stage (this adapter stays L3-state-free,
    §1.1 layering). Returns ``(injected, errors, files_modified)``:
      - injected: True iff a wrapper was actually written/corrected (→ stage triggers
        a clean rebuild); False on idempotent no-change (no spurious rebuild).
      - errors: non-blocking precondition problems (missing manifest/op_spec/path).
      - files_modified: e.g. ``["cann_bench/__init__.py"]``.
    """
    errors: list[str] = []
    files_modified: list[str] = []
    if not codegen_manifest:
        return False, errors, files_modified

    op_name = codegen_manifest.get("op_name") or op_name_fallback or ""
    symbol = (codegen_manifest.get("callable_target") or {}).get("symbol") or ""
    if not op_name or not symbol:
        errors.append(
            "CannbenchAdapter: cannot derive wrapper — "
            f"missing op_name ({op_name!r}) or callable_target.symbol ({symbol!r})"
        )
        return False, errors, files_modified
    symbol_last = symbol.split(".")[-1]

    params, name_messages = schema_param_names(proto_schema, op_spec)
    errors.extend(name_messages)
    if params is None:
        errors.append(
            "CannbenchAdapter: cannot derive wrapper params — "
            "no proto_schema nor op_spec"
        )
        return False, errors, files_modified
    if not params:
        errors.append(
            f"CannbenchAdapter: no schema params derived "
            f"for {op_name} — skipping wrapper injection"
        )
        return False, errors, files_modified

    wrapper = _build_wrapper(op_name, symbol_last, params)

    if not repo_root:
        errors.append("CannbenchAdapter: cannot locate cann_bench package — no repo_root")
        return False, errors, files_modified
    if source_dir is None:
        source_dir = repo_root
    pkg_root = resolve_cann_bench_pkg_root(source_dir, repo_root)
    if pkg_root is None:
        errors.append(
            f"CannbenchAdapter: cannot locate cann_bench/ package walking up "
            f"from {source_dir} within {repo_root}"
        )
        return False, errors, files_modified
    init_path = pkg_root / "cann_bench" / "__init__.py"

    try:
        existing = init_path.read_text(encoding="utf-8") if init_path.exists() else ""
    except OSError as exc:
        errors.append(f"CannbenchAdapter: failed to read {init_path}: {exc}")
        return False, errors, files_modified

    block = f"# {op_name} wrapper (deterministic, cannbench_adapt)\n{wrapper}"
    new_content = _inject_wrapper_block(existing, op_name, block)
    if new_content == existing:
        return False, errors, files_modified  # idempotent no-change

    try:
        init_path.parent.mkdir(parents=True, exist_ok=True)
        init_path.write_text(new_content, encoding="utf-8")
    except OSError as exc:
        errors.append(f"CannbenchAdapter: failed to write wrapper to {init_path}: {exc}")
        return False, errors, files_modified

    Logger.info(
        f"CannbenchAdapter: injected deterministic wrapper for {op_name} "
        f"(symbol_last={symbol_last}, params={params}) into {init_path.name}"
    )
    files_modified.append("cann_bench/__init__.py")
    return True, errors, files_modified


def rename_mdef_schema_if_needed(
    op_spec, op_dir, op_name, proto_schema: str | None = None,
) -> tuple[list[dict], list[str]]:
    """P10 后处理：对齐 m.def schema 参数名 → proto（纯 rename，不 rebuild）。

    Destructured args (stage resolves op_spec/op_dir/op_name from state). Returns
    ``(schema_renamed, errors)``. Rebuild is the stage's call (merged with the
    wrapper injection into one clean rebuild). No proto / no m.def file / no
    m.def / count mismatch / already aligned → safe skip.
    """
    schema_renamed: list[dict] = []
    errors: list[str] = []

    proto_names, name_messages = schema_param_names(proto_schema, op_spec)
    errors.extend(name_messages)
    if proto_names is None:
        return schema_renamed, errors

    if not op_dir or not op_name:
        return schema_renamed, errors
    plugin_path = op_dir / "op_plugin" / f"{op_name}_plugin.cpp"
    if not plugin_path.exists():
        return schema_renamed, errors

    source = plugin_path.read_text(encoding="utf-8")
    schema_names = parse_mdef_params(source)
    if not schema_names:
        return schema_renamed, errors

    if len(schema_names) != len(proto_names):
        errors.append(
            f"P10 schema param count mismatch: m.def has {len(schema_names)} "
            f"{schema_names} but proto has {len(proto_names)} {proto_names} — "
            f"cannot align by position; skipping rename"
        )
        return schema_renamed, errors

    renamed = [(o, n) for o, n in zip(schema_names, proto_names) if o != n]
    if not renamed:
        return schema_renamed, errors  # already aligned
    schema_renamed = [{"from": o, "to": n} for o, n in renamed]
    new_source = rename_mdef_schema(source, schema_names, proto_names)
    plugin_path.write_text(new_source, encoding="utf-8")
    Logger.info(
        f"CannbenchAdapter: P10 renamed m.def schema params "
        f"{[r['from'] for r in schema_renamed]} → "
        f"{[r['to'] for r in schema_renamed]} in {plugin_path.name}"
    )
    return schema_renamed, errors


def validate_plugin_schema(
    op_dir: Path | None, op_name: str, proto_schema: str | None
) -> str | None:
    """Validate plugin ``m.def`` against the authoritative proto schema.

    With no usable proto schema, validation degrades to the structural
    Tensor-before-scalar check implemented by ``validate_schema_against_proto``.
    """
    if not op_dir or not op_name:
        return None
    plugin_path = op_dir / "op_plugin" / f"{op_name}_plugin.cpp"
    if not plugin_path.exists():
        return None
    try:
        source = plugin_path.read_text(encoding="utf-8")
    except OSError:
        return None
    ok, detail = validate_schema_against_proto(source, proto_schema)
    return None if ok else detail
