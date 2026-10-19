"""L4 Domain — cann-bench cases loader (P10/D4/D5; B5 14 L4; P34 正名).

Bridges an external cann-bench cases.csv into the framework's ``TestCase``
list. B5 (13 E1/E2): cases source is an explicit CLI path (--cann-bench-cases);
the param name encodes the format, so this loader no longer dispatches by
format nor substitutes {op}/{N}. Deterministic parse — no LLM, no repo-specific
branching (CLAUDE.md 1.5/2.7).

P34 正名:此 loader 为 cann-bench 专属(列名 / dtype map / value_range→generator
均按 cann-bench 约定),对外 API 用 ``load_cann_bench_cases`` 自注释 —— 不再用通用名
``load_cases`` 误导维护者以为它支持多种 cases 格式(当前只有 cann-bench 一种,
泛化属过度设计,YAGNI)。
"""

from __future__ import annotations

import ast
import csv
import json
import logging
from pathlib import Path

from ascendc_devkit.domain.requirement import TestCase

logger = logging.getLogger(__name__)

# cann-bench dtype names → the framework vocabulary the harness _NP dict
# understands (fp16/fp32/bf16/int8/...). Unknown names pass through lowercased
# so a new dtype is visible rather than silently coerced.
_DTYPE_MAP = {
    "float16": "fp16",
    "float32": "fp32",
    "bfloat16": "bf16",
    "fp16": "fp16",
    "fp32": "fp32",
    "bf16": "bf16",
    "int8": "int8",
    "int32": "int32",
    "int64": "int64",
    "bool": "bool",
}


def load_cann_bench_cases(cases_path: Path) -> list[TestCase]:
    """Load an external cann-bench cases.csv → list[TestCase].

    13 E1/E2: cases source is an explicit CLI path (--cann-bench-cases); the
    parameter name encodes the format, so there is no in-loader format dispatch
    and no ``{op}``/``{N}`` substitution. Accepts str or Path.
    """
    return parse_cann_bench_csv(Path(cases_path))


def load_cann_bench_case_meta(cases_path: Path) -> dict[str, dict]:
    """cann-bench cases.csv → ``{str(case_id): {"shape": [...], "dtype": "..."}}``.

    Only the **primary (first non-null) input's** shape/dtype per case. This is
    the authoritative per-case metadata the baseline stage uses to enrich
    ``failed_case_queue`` entries: the baseline agent's ``cross_compare``
    contract carries only comparison results (rc/kl pass, max_diff, error_layer),
    not case metadata — shape/dtype live in cases.csv (§1.13 golden 权威,
    constructive guarantee: the framework reads the authoritative file instead
    of relying on the agent to echo back what it already read).
    """
    meta: dict[str, dict] = {}
    path = Path(cases_path)
    if not path.is_file():
        return meta
    with path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cid = (row.get("case_id") or "").strip()
            if not cid:
                continue
            shapes = _loads_or(row.get("input_shape"), [])
            dtypes = _loads_or(row.get("dtype"), [])
            if isinstance(dtypes, str):
                dtypes = [dtypes]
            # cann-bench 约定：len==1 的 dtype 广播到所有 tensor 输入（与
            # parse_cann_bench_csv 同一广播规则，避免取到空 dtype）。
            num_shapes = sum(1 for s in shapes if s is not None)
            if len(dtypes) == 1 and num_shapes > 1:
                dtypes = dtypes * num_shapes
            primary = None
            for i, shape in enumerate(shapes):
                if shape is None:
                    continue
                raw_dtype = (dtypes[i] if i < len(dtypes) else "") or ""
                primary = {
                    "shape": list(shape) if isinstance(shape, list) else [shape],
                    "dtype": raw_dtype.strip(),
                }
                break
            if primary is not None:
                meta[str(cid)] = primary
    return meta


def parse_cann_bench_csv(path: Path) -> list[TestCase]:
    """Parse a cann-bench ``cases.csv`` into TestCase list.

    cann-bench columns: operator, case_id, input_shape, dtype, attrs,
    value_range, note. ``input_shape``/``dtype`` are JSON arrays (one entry per
    input tensor); ``attrs`` is a JSON object of operator attribute values (the
    non-default-branch coverage P10 needs); ``value_range`` is a flat
    ``[low, high]`` (single input) or nested ``[[low, high], ...]`` (multi-input,
    ``null`` for non-random inputs) → generator_params.
    """
    cases: list[TestCase] = []
    # rel_path = task 目录相对 tasks/ 的路径，即 cann-bench case_id_str 前缀
    # （如 'level1/clipped_swiglu'）。csv 位于 tasks/<rel_path>/cases.csv，
    # 向上走到 'tasks' 祖先再反向拼接，兼容 level1/<op> 与多级 levelN/a/b 布局。
    # evaluator.get_case_id_str() 真值 = f'{rel_path}_{case_num}'；种子公式
    # SHA256(case_id_str) 需此串才能与 cann-bench eval 对齐。
    _rel_parts: list[str] = []
    _cur = Path(path).resolve().parent
    while _cur.name != "tasks" and _cur != _cur.parent:
        _rel_parts.append(_cur.name)
        _cur = _cur.parent
    rel_path = "/".join(reversed(_rel_parts))
    # utf-8-sig transparently strips a BOM if present (cann-bench CSVs vary).
    with Path(path).open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            operator = (row.get("operator") or "").strip()
            case_id = (row.get("case_id") or "").strip()
            shapes = _loads_or(row.get("input_shape"), [])
            dtypes = _loads_or(row.get("dtype"), [])
            attrs = _loads_or(row.get("attrs"), {}) or {}
            value_range = _loads_or(row.get("value_range"), None)

            # cann-bench 约定：dtype 列允许裸串（isinstance str），也允许单元素数组
            # 「所有 tensor 输入共享该 dtype」（foreach 类多输入算子）。复刻 cann-bench
            # 自家 loader（cann_loader._parse_case: len==1 && 多输入 → dtypes*输入数）。
            # 本 loader 是 cann-bench 格式产权层（docstring 自证列名/dtype map/value_range
            # 均按 cann-bench 约定），在此忠实转写上游约定（§1.13），非修正、非报错。
            # 裸串归一：防 `dtypes[0]` 取到字符串首字符（'float32'[0]=='f'）。
            if isinstance(dtypes, str):
                dtypes = [dtypes]
            _num_shapes = sum(1 for s in shapes if s is not None)
            if len(dtypes) == 1 and _num_shapes > 1:
                dtypes = dtypes * _num_shapes
            elif len(dtypes) > 1 and len(dtypes) != _num_shapes:
                # 结构不齐（少填或多填）都算 producer 违约信号：少填的输入留空由 runner
                # 存量兜底继承，多填被静默截断（raw_dtype 只取前 N 个）——两种情况都必须
                # 可观测（§1.3），不静默。len==0（空 dtype 列）是「无信息」非违约，由
                # runner 兜底 + WARN 覆盖，不在 loader 报。
                logger.warning(
                    "cann-bench case %s: dtype len=%d ≠ 非空输入数=%d（仅广播单 dtype "
                    "约定；少填的输入留空由 runner 存量兜底继承，多填被忽略）",
                    case_id, len(dtypes), _num_shapes,
                )

            inputs = []
            for i, shape in enumerate(shapes):
                if shape is None:
                    # optional input absent (cann-bench null shape entry) — dropped;
                    # the harness relies on the param's default at the call site
                    # (e.g. moe_re_routing per_token_scales=null → 2 inputs, the
                    # kernel/golden default per_token_scales=None).
                    continue
                raw_dtype = (dtypes[i] if i < len(dtypes) else "") or ""
                inputs.append({
                    "name": f"input_{i}",
                    "shape": list(shape) if isinstance(shape, list) else [shape],
                    "dtype": _map_dtype(raw_dtype),
                    # explicit original proto position (§1.15 single point):
                    # every input producer writes it, runner only reads it —
                    # never inferred from the input_{i} name.
                    "proto_idx": i,
                    # per-input value_range (Fix E): multi-input ops with
                    # dissimilar ranges need their OWN range, not a single
                    # collapsed one (moe_re_routing tokens [-1,1] vs
                    # expert_token_num [1,128]). Absent when this input has none.
                    **_per_input_value_range(value_range, i),
                })
            generator, generator_params = _value_range_to_gen(value_range)
            cases.append(TestCase(
                name=f"{operator}_{case_id}" if operator and case_id else (case_id or f"case_{len(cases)}"),
                inputs=inputs,
                attrs=dict(attrs) if isinstance(attrs, dict) else {},
                generator=generator,
                generator_params=generator_params,
                # cann-bench case_id_str = f'{rel_path}_{case_num}'（evaluator
                # get_case_id_str 真值）。种子 SHA256(case_id_str) 据此与 cann-bench
                # eval 对齐；单用例 _idx=0 不再把它压成 1。rel_path 缺失时回退空串，
                # 由 runner 的 name 反解兜底（仍保持单/全量一致）。
                case_id=f"{rel_path}_{case_id}" if rel_path and case_id else "",
                # 来源标记：本 loader 只产 cann-bench 用例（P34 正名），供 baseline
                # 报告把 st-design 生成用例与 cann-bench 原有用例分开统计（§1.12）。
                source="cannbench",
            ))
    return cases


def _loads_or(raw, default):
    """Parse a CSV cell as JSON, falling back to ast.literal_eval for single-quote lists.

    JSON requires double quotes, but cann-bench CSVs sometimes use Python-style
    single quotes (e.g. ``['-inf', 'inf']``) which fail ``json.loads``. We try
    ``ast.literal_eval`` as a safe fallback — it accepts single-quote strings but
    rejects arbitrary expressions, so it won't accidentally execute code.
    """
    if raw is None:
        return default
    raw = raw.strip()
    if raw == "" or raw.lower() == "null":
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        try:
            return ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            return default


def _map_dtype(raw) -> str:
    # TensorList 输入的 dtype 可能是嵌套数组（lstm/gru 权重列表逐 tensor 一个
    # dtype 条目，如 ["float32"]）——取首元素映射，与 cann-bench DataGenerator
    # 的 ``d[0]`` 约定一致；空列表视为无声明。
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    key = (raw or "").strip().lower()
    return _DTYPE_MAP.get(key, key)


def _coerce_float(x):
    """Coerce a value_range element to float, accepting JSON string specials.

    JSON has no Infinity/NaN literals, so cann-bench CSVs encode them as
    strings ("-inf"/"inf"/"nan"). Python float() accepts all of these.
    int/float pass through. Unparseable → None (treated as absent).
    """
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        try:
            return float(x)
        except (ValueError, TypeError):
            return None
    return None


def _value_range_to_gen(value_range):
    """cann-bench value_range → (generator, generator_params).

    Flat ``[low, high]`` (single input) or nested ``[[low, high], ...]``
    (multi-input, entries may be null) → the case-level generator + params.
    The first non-null range wins; these become the harness ``GEN_LOW``/
    ``GEN_HIGH`` FALLBACK for inputs without their own range (per-input ranges
    are attached separately by ``_per_input_value_range``).
    None/empty/null → (None, None) and the harness falls back to its default
    random_uniform.
    """
    if not value_range or not isinstance(value_range, list):
        return None, None
    pair = None
    lo = _coerce_float(value_range[0]) if value_range else None
    if value_range and lo is not None:
        # flat [low, high] — elements may be int, float, or JSON string specials.
        if len(value_range) >= 2:
            hi = _coerce_float(value_range[1])
            if hi is not None:
                pair = [lo, hi]
    if pair is None:
        # nested; first non-null [low, high]
        for entry in value_range:
            if isinstance(entry, list) and len(entry) >= 2:
                lo2 = _coerce_float(entry[0])
                hi2 = _coerce_float(entry[1])
                if lo2 is not None and hi2 is not None:
                    pair = [lo2, hi2]
                    break
    if not pair or pair[0] is None or pair[1] is None:
        return None, None
    return "random_uniform", {"low": pair[0], "high": pair[1], "seed": 42}


def _per_input_value_range(value_range, i: int) -> dict:
    """Return ``{"value_range": [low, high]}`` for input *i*, or ``{}``.

    cann-bench value_range is flat ``[low, high]`` (single input — applies to the
    sole input) or nested ``[[low, high] | null, ...]`` (multi-input, one entry
    per input, null = non-random). Each input carries its OWN range so multi-input
    ops with dissimilar ranges (moe_re_routing: tokens [-1,1] vs expert_token_num
    [1,128]) are generated correctly — collapsing to a single range would feed
    expert_token_num a fractional [-1,1] and break the sum==A invariant.
    """
    if not value_range or not isinstance(value_range, list):
        return {}
    lo = _coerce_float(value_range[0])
    if lo is not None:
        # flat [low, high] — applies to the single input (i==0)
        if i == 0 and len(value_range) >= 2:
            hi = _coerce_float(value_range[1])
            if hi is not None:
                return {"value_range": [lo, hi]}
        return {}
    # nested [[low,high]|null, ...] — entry i, if present and non-null
    if i < len(value_range) and isinstance(value_range[i], list) and len(value_range[i]) >= 2:
        lo2 = _coerce_float(value_range[i][0])
        hi2 = _coerce_float(value_range[i][1])
        if lo2 is not None and hi2 is not None:
            return {"value_range": [lo2, hi2]}
    return {}
