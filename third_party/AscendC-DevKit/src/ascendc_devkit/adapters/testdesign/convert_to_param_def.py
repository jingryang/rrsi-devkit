#!/usr/bin/env python3
"""DevKit → ascendc-st-design input adapter.

Deterministic conversion: ``requirement.json`` + ``design_spec.json``
→ ``03_参数定义.yaml``, skipping the LLM-driven steps 1-2 of
``ascendc-st-design`` so the agent can start from step 3.

Reads from CWD; writes ``03_参数定义.yaml`` to CWD.
No external dependencies (no PyYAML — manual YAML formatting).
"""

from __future__ import annotations

import json
from pathlib import Path

# ── dtype normalisation maps ──────────────────────────────────────────────

# DevKit / OpDef canonical dtype strings → parameter-definition dtype strings
_DTYPE_MAP: dict[str, str] = {
    # float
    "fp16": "float16", "float16": "float16", "half": "float16",
    "fp32": "float32", "float32": "float32", "float": "float32",
    "fp64": "float64", "float64": "float64", "double": "float64",
    "bf16": "bfloat16", "bfloat16": "bfloat16",
    "hf32": "hf32",
    "complex32": "complex32", "complex64": "complex64", "complex128": "complex128",
    # int
    "int4": "int4", "int8": "int8", "int16": "int16",
    "int32": "int32", "int64": "int64",
    # uint
    "uint1": "uint1", "uint8": "uint8", "uint16": "uint16",
    "uint32": "uint32", "uint64": "uint64",
    # other
    "bool": "bool", "char": "char", "string": "string",
    # quant
    "qint8": "qint8", "qint16": "qint16", "qint32": "qint32",
    "quint8": "quint8", "quint16": "quint16",
    # float8 variants
    "float4_e1m2": "float4_e1m2", "float4_e2m1": "float4_e2m1",
    "float8_e4m3fn": "float8_e4m3fn", "float8_e5m2": "float8_e5m2",
    "float8_e8m0": "float8_e8m0", "hifloat8": "hifloat8",
}

# parameter-definition Scalar type ← DevKit attr type
_SCALAR_TYPE_MAP: dict[str, str] = {
    "int": "int64_t", "int8": "int8_t", "int16": "int16_t",
    "int32": "int32_t", "int64": "int64_t",
    "uint8": "uint8_t", "uint16": "uint16_t",
    "uint32": "uint32_t", "uint64": "uint64_t",
    "float": "float", "float16": "float16", "float32": "float32",
    "float64": "double", "double": "double",
    "bfloat16": "bfloat16", "bool": "bool", "char": "char",
    "str": "string", "string": "string",
    "int4": "int4_t", "uint1": "uint1_t",
}


def _normalise_dtype(raw: str) -> str:
    """Map a DevKit dtype string to the parameter-definition canonical form."""
    return _DTYPE_MAP.get(raw.lower(), raw.lower())


def _is_scalar_attr(entry: dict) -> bool:
    """Heuristic: is this entry a scalar attribute rather than a tensor?"""
    # A tensor field carries a list of dtypes (e.g. ["float32", "float16"]).
    # A scalar attr carries a single type string (e.g. "float").
    dtype_field = entry.get("dtype")
    if isinstance(dtype_field, list):
        return False  # multi-dtype → tensor, never scalar
    type_field = entry.get("type", entry.get("dtype"))  # 用户模板用 dtype
    if isinstance(type_field, list):
        return False  # multi-type → tensor
    shape = entry.get("shape")
    if shape is not None and isinstance(shape, list) and len(shape) == 0:
        return True  # empty shape → scalar
    fmt = entry.get("format", "")
    if fmt == "SCALAR":
        return True
    # If no shape AND no format AND type is a scalar type string, treat as scalar.
    if shape is None and not fmt and isinstance(type_field, str):
        return True
    return False


def _load_json(filename: str, base_dir: Path | None = None) -> dict:
    """Read JSON from ``base_dir`` (default: CWD) — supports both the standalone
    skill usage (relative paths from CWD) and the orchestration adapter usage
    (absolute paths under a stage working dir)."""
    path = Path(filename)
    if not path.is_absolute():
        path = (base_dir or Path.cwd()) / path
    if not path.exists():
        raise FileNotFoundError(f"Required input file not found: {path}")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _yaml_str(val) -> str:
    """Minimal YAML string escaping."""
    s = str(val)
    if any(ch in s for ch in ('"', "'", ":", "#", "{", "}", "[", "]", ",",
                               "&", "*", "?", "|", "-", "<", ">", "=", "!",
                               "%", "@", "`")):
        return f'"{s}"'
    if s in ("true", "false", "yes", "no", "on", "off", "null", "True",
             "False", "None"):
        return f'"{s}"'
    return s


def _yaml_list(items: list, indent: int = 0) -> str:
    """Format a Python list as YAML list."""
    if not items:
        return "[]"
    prefix = "  " * indent
    lines = []
    for item in items:
        if isinstance(item, dict):
            lines.append(_yaml_dict(item, indent))
        elif isinstance(item, list):
            lines.append(_yaml_list(item, indent))
        elif isinstance(item, bool):
            lines.append(f"{prefix}- {'true' if item else 'false'}")
        elif isinstance(item, str) and not item.startswith('"'):
            lines.append(f"{prefix}- {_yaml_str(item)}")
        else:
            lines.append(f"{prefix}- {item}")
    return "\n".join(lines)


def _yaml_inline(value, indent: int = 0) -> str:
    """Render a Python value as a single-line YAML literal.

    Used for value_range, format, dimensions, length_ranges — anything where a
    compact inline representation is preferred. Scalars, lists, and lists of
    lists are supported.
    """
    if isinstance(value, list):
        parts = []
        for v in value:
            if isinstance(v, list):
                parts.append("[" + ", ".join(_yaml_inline_scalar(x) for x in v) + "]")
            elif isinstance(v, str):
                parts.append(_yaml_str(v))
            elif isinstance(v, bool):
                parts.append("true" if v else "false")
            else:
                parts.append(str(v))
        return "[" + ", ".join(parts) + "]"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return _yaml_str(value)
    return str(value)


def _yaml_inline_scalar(value) -> str:
    """Render a single scalar as YAML literal."""
    if isinstance(value, str):
        # bare inf/-inf/nan stay unquoted — that's what the examples use.
        if value in ("inf", "-inf", "+inf", "nan", "+0", "-0"):
            return f'"{value}"'
        return _yaml_str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _yaml_dict(d: dict, indent: int = 0) -> str:
    """Format a Python dict as YAML mapping."""
    prefix = "  " * indent
    lines = []
    for key, value in d.items():
        if value is None:
            lines.append(f"{prefix}{key}:")
        elif isinstance(value, dict):
            lines.append(f"{prefix}{key}:")
            lines.append(_yaml_dict(value, indent + 1))
        elif isinstance(value, list):
            if not value:
                lines.append(f"{prefix}{key}: []")
            elif key in ("value_range", "value", "format", "dimensions",
                         "length_ranges"):
                # Always inline these keys (compact representation).
                lines.append(f"{prefix}{key}: {_yaml_inline(value)}")
            elif key in ("dtype_with_ranges", "dtype_with_values"):
                # list of dicts — render each as a "- " list item.
                # Items sit at the same column as the key (indent), with
                # "- " consuming 2 of the indent; nested attrs at indent+1.
                lines.append(f"{prefix}{key}:")
                item_indent = indent  # "- " at same column as key
                attr_indent = indent + 1
                for entry in value:
                    body = _yaml_dict(entry, attr_indent)
                    first_line, _, rest = body.partition("\n")
                    item_prefix = "  " * item_indent
                    lines.append(f"{item_prefix}- {first_line.lstrip()}")
                    if rest:
                        lines.append(rest)
            else:
                # Heuristic: all scalars and short → inline; else multi-line.
                all_scalar = all(
                    not isinstance(v, (dict, list)) for v in value)
                if all_scalar and len(value) <= 5:
                    items = ", ".join(str(v) if not isinstance(v, str)
                                      else _yaml_str(v) for v in value)
                    lines.append(f"{prefix}{key}: [{items}]")
                else:
                    lines.append(f"{prefix}{key}:")
                    lines.append(_yaml_list(value, indent + 1))
        elif isinstance(value, bool):
            lines.append(f"{prefix}{key}: {'true' if value else 'false'}")
        elif isinstance(value, str):
            lines.append(f"{prefix}{key}: {_yaml_str(value)}")
        else:
            lines.append(f"{prefix}{key}: {value}")
    return "\n".join(lines)


def _default_value_range(dtype: str) -> list:
    """Return a minimal default value_range for the given parameter-definition
    dtype.  Full ranges are large (see parameter-definition.md table); we ship a
    representative subset so the solver has useful anchors without exploding
    combinatorial space.  Real operators that need wider / narrower ranges
    should get them from the design_spec or an LLM-crafted 03_参数定义.yaml."""
    dtype = dtype.lower()
    ranges: dict[str, list] = {
        "float16": [[-1, 1], [0, 0], [1, 10], [-10, -1], ["inf", "inf"],
                     ["-inf", "-inf"], ["nan", "nan"]],
        "float32": [[-1, 1], [0, 0], [1, 100], [-100, -1], ["inf", "inf"],
                     ["-inf", "-inf"], ["nan", "nan"]],
        "float64": [[-1, 1], [0, 0], [1, 100], [-100, -1]],
        "bfloat16": [[-1, 1], [0, 0], [1, 10], [-10, -1]],
        "int8": [[-1, 1], [0, 10], [-10, -1], [-128, 127]],
        "uint8": [[0, 1], [1, 10], [0, 255]],
        "int16": [[-1, 1], [0, 10], [-32768, 32767]],
        "uint16": [[0, 1], [1, 100], [0, 65535]],
        "int32": [[-1, 1], [0, 100], [-100, -1]],
        "uint32": [[0, 1], [1, 100]],
        "int64": [[-1, 1], [0, 100], [-100, -1]],
        "uint64": [[0, 1], [1, 100]],
        "bool": [[0, 1]],
        "int4": [[-8, 7], [0, 1]],
        "uint1": [[0, 1]],
        "char": [[-128, 127]],
        "hf32": [[-1, 1], [0, 0]],
    }
    return ranges.get(dtype, [[-1, 1], [0, 0], [1, 100]])


def _build_tensor_param(name: str, entry: dict, io_type: str) -> dict:
    """Build a parameter-definition dict for a tensor input/output."""
    dtype_raw = entry.get("dtype", "float16")
    if isinstance(dtype_raw, list):
        dtypes = [_normalise_dtype(d) for d in dtype_raw]
    else:
        dtypes = [_normalise_dtype(dtype_raw)]

    shape = entry.get("shape", ["N"])
    if not isinstance(shape, list):
        shape = ["N"]
    dimensions = list(range(1, len(shape) + 1)) if shape else [1]

    fmt = entry.get("format", "ND")
    if isinstance(fmt, str):
        formats = [fmt] if fmt else ["ND"]
    elif isinstance(fmt, list):
        formats = fmt if fmt else ["ND"]
    else:
        formats = ["ND"]

    param: dict = {
        "name": name,
        "type": "aclTensor",
        "required": entry.get("param_type", "REQUIRED") != "OPTIONAL",
        "io_type": io_type,
        "format": formats,
        "dimensions": dimensions,
    }

    dtype_entries: list[dict] = []
    for dt in dtypes:
        de: dict = {"dtype": dt}
        if io_type == "input":
            # 声明优先（§1.13 忠实传递）：用户声明照抄，未声明才按 dtype 查通用表
            de["value_range"] = (entry.get("value_range")
                                 or _default_value_range(dt))
        dtype_entries.append(de)
    param["dtype_with_ranges"] = dtype_entries
    return param


def _build_scalar_param(name: str, entry: dict) -> dict:
    """Build a parameter-definition dict for a scalar attribute."""
    raw_type = entry.get("type", entry.get("dtype", "float"))
    # Defensive: only accept scalar raw_type (string). If a list slips through
    # (e.g. a tensor entry misclassified), fall back to "float".
    if isinstance(raw_type, list):
        scalar_type = "aclScalar"
        param_dtype = _normalise_dtype(str(raw_type[0]) if raw_type else "float")
    else:
        scalar_type = _SCALAR_TYPE_MAP.get(raw_type.lower(), "aclScalar")
        param_dtype = _normalise_dtype(raw_type)

    default_val = entry.get("default")
    is_enum = default_val is not None and not isinstance(default_val, (int, float))

    param: dict = {
        "name": name,
        "type": scalar_type,
        "required": False,  # attrs are optional by default in OpDef semantics
        "io_type": "input",
        "is_enum": is_enum,
    }

    dtype_values: list[dict] = []
    de: dict = {"dtype": param_dtype}
    if is_enum:
        de["value"] = [default_val] if default_val else [0]
    else:
        # 声明优先（§1.13 忠实传递）：用户声明照抄，未声明才按 dtype 查通用表
        de["value_range"] = (entry.get("value_range")
                             or _default_value_range(param_dtype))
    dtype_values.append(de)
    param["dtype_with_values"] = dtype_values
    return param


def convert(requirement_path: str = "requirement.json",
            design_spec_path: str = "design_spec.json",
            output_path: str = "design/03_参数定义.yaml",
            base_dir: Path | None = None) -> str:
    """Main entry point.

    Writes ``03_参数定义.yaml`` under ``base_dir`` (default: CWD), matching the
    skill's DESIGN_DIR convention (SKILL.md §1.1) so step 3+ scripts find it at
    the documented relative location. The ``design/`` subdir is created if
    absent. Returns the absolute path of the written YAML file.

    ``base_dir`` lets the orchestration adapter run this under a stage working
    dir while the standalone skill usage keeps CWD-relative paths.
    """
    base = base_dir or Path.cwd()
    req = _load_json(requirement_path, base)
    ds = _load_json(design_spec_path, base) if (base / design_spec_path).exists() else {}

    # ── aclnn_name：用户输入提供（必填），需求阶段照抄进产物；适配器只读 ──
    # requirement.json 有两条真实形态（非新旧版本，二者并存）：
    #   平铺 —— DevKit requirement stage 产出，顶层直接是 op_name/inputs/outputs/attrs
    #   嵌套 —— 用户原始模板与 cann-bench proto.yaml，算子块在 op / operator 下
    # 故逐级探测后回退到 req 本身。必须用 `or` 串联：dict.get(key, default) 在
    # key 存在但值为 None 时返回 None，嵌套写法取不到兜底（op_spec 是不存在的
    # 字段——仅 domain 层属性名，死支已删，§2.5）。
    op_block = req.get("op") or req.get("operator") or req
    aclnn_name = req.get("aclnn_name")
    if not aclnn_name:
        raise ValueError(
            "requirement.json 缺必填字段 aclnn_name（ACLNN 接口名，由用户输入"
            "提供、需求阶段照抄进产物）。requirement.json 顶层键 = "
            f"{sorted(req.keys())}")

    # ── parameters ──
    parameters: list[dict] = []

    # Inputs — from design_spec first (richer format info), fall back to req
    ds_inputs = {e.get("name", ""): e for e in ds.get("inputs", [])}
    req_inputs = op_block.get("inputs", [])

    for entry in req_inputs:
        name = entry.get("name", "")
        ds_entry = ds_inputs.get(name, {})
        merged = {**entry, **{k: v for k, v in ds_entry.items() if v}}

        if _is_scalar_attr(merged):
            parameters.append(_build_scalar_param(name, merged))
        else:
            parameters.append(_build_tensor_param(name, merged, "input"))

    # Outputs
    ds_outputs = {e.get("name", ""): e for e in ds.get("outputs", [])}
    req_outputs = op_block.get("outputs", [])

    for entry in req_outputs:
        name = entry.get("name", "")
        ds_entry = ds_outputs.get(name, {})
        merged = {**entry, **{k: v for k, v in ds_entry.items() if v}}
        parameters.append(_build_tensor_param(name, merged, "output"))

    # Attrs — from requirement attrs dict or design_spec attrs list
    raw_attrs = op_block.get("attrs", {})
    if isinstance(raw_attrs, dict):
        for attr_name, attr_val in raw_attrs.items():
            if isinstance(attr_val, dict):
                entry = {"name": attr_name, **attr_val}
            else:
                entry = {"name": attr_name, "default": attr_val}
            if _is_scalar_attr(entry):
                parameters.append(_build_scalar_param(attr_name, entry))
            else:
                parameters.append(_build_tensor_param(attr_name, entry, "input"))
    elif isinstance(raw_attrs, list):
        for entry in raw_attrs:
            name = entry.get("name", "")
            if name:
                if _is_scalar_attr(entry):
                    parameters.append(_build_scalar_param(name, entry))
                else:
                    parameters.append(_build_tensor_param(name, entry, "input"))

    # Also process ds attrs
    ds_attrs = ds.get("attrs", [])
    seen_names = {p["name"] for p in parameters}
    if isinstance(ds_attrs, list):
        for entry in ds_attrs:
            name = entry.get("name", "")
            if name and name not in seen_names:
                if _is_scalar_attr(entry):
                    parameters.append(_build_scalar_param(name, entry))
                else:
                    parameters.append(_build_tensor_param(name, entry, "output"))
                seen_names.add(name)

    # ── Assemble YAML ──
    yaml_lines: list[str] = [
        f"# Generated by convert_to_param_def.py",
        f"# Sources: {requirement_path}, {design_spec_path}",
        f"aclnn_name: {_yaml_str(aclnn_name)}",
        "",
        "parameters:",
    ]

    for param in parameters:
        # Each parameter is a list item. The list item is at column 0 ("- "),
        # and all properties align at column 2 (indent=1). Render the dict at
        # indent=1, then promote the first line onto the "- " marker.
        body = _yaml_dict(param, indent=1)
        first_line, _, rest = body.partition("\n")
        # first_line is "  key: value" (2 spaces) → replace with "- key: value".
        if first_line.startswith("  "):
            first_line = "- " + first_line[2:]
        else:
            first_line = "- " + first_line.lstrip()
        yaml_lines.append(first_line)
        if rest:
            yaml_lines.append(rest)
        yaml_lines.append("")

    yaml_text = "\n".join(yaml_lines)

    # ── 自检（§2.9 producer 自检 / §1.3 加载期校验 / §1.2 可诊断）──
    # 放在写盘之前：残缺产物不落盘（§3.12）；且 actions() 每次重试都会重跑本
    # 适配器——断言在写盘前，失败就不会覆盖 agent 上一轮手工修复的 03。
    declared_tensors = max(
        len(req.get("inputs") or []) + len(req.get("outputs") or []),
        len(ds.get("inputs") or []) + len(ds.get("outputs") or []),
        len(op_block.get("inputs") or []) + len(op_block.get("outputs") or []),
    )
    produced_tensors = sum(1 for p in parameters if p.get("type") == "aclTensor")

    # 校验 1：一个参数都没提取到（三源皆空 / 结构完全不匹配）
    if not parameters:
        raise ValueError(
            "参数定义为空：未能从 requirement.json / design_spec.json 提取到任何"
            f"参数。requirement.json 顶层键 = {sorted(req.keys())}")
    # 校验 2：张量数与上游声明不符（历史事故形态：0 < 8）
    if declared_tensors and produced_tensors < declared_tensors:
        raise ValueError(
            f"参数定义不完整：上游声明 {declared_tensors} 个张量，"
            f"实际转换出 {produced_tensors} 个。"
            f"requirement.json 顶层键 = {sorted(req.keys())}")

    out_path = base / output_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yaml_text, encoding="utf-8")
    print(f"[convert_to_param_def] Wrote {len(parameters)} parameters → {out_path}")
    return str(out_path)


if __name__ == "__main__":
    import sys
    req_path = sys.argv[1] if len(sys.argv) > 1 else "requirement.json"
    ds_path = sys.argv[2] if len(sys.argv) > 2 else "design_spec.json"
    out_path = sys.argv[3] if len(sys.argv) > 3 else "design/03_参数定义.yaml"
    convert(req_path, ds_path, out_path)
