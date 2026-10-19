"""CSV → TestCase normalization (anti-corruption layer).

The testdesign skill chain emits 13-column, spec-style CSV (UTF-8-BOM). The
columns describe dtype/shape/format combinations plus precision thresholds —
NOT concrete data arrays (data is generated at runtime), which maps cleanly
onto TestCase's generator model. Parallel tuples are stored as Python repr
strings and need ``ast.literal_eval``.

Column reference (step-4 第二层 §七):
    testcase_name, op_name, stc_input_dtypes, other_compilation_params,
    stc_inputs, output_dtypes, stc_outputs, stc_input_formats, output_formats,
    stc_op_name, input_data_ranges, absolute_precision, error_message

Mapping (TestCase fields → CSV source):
    name             ← testcase_name (fallback: op_name + 1-based row index)
    inputs           ← zip(stc_inputs, stc_input_dtypes, stc_input_formats)
    expected         ← {"max_diff": float(absolute_precision)} or None
    generator        ← "random_uniform" (default)
    generator_params ← {"ranges": <input_data_ranges>} or None

Output-side columns (output_*) have no TestCase home and are dropped in this
version (verify drives precision off inputs + golden). Parse failures (missing
required column / literal_eval error) raise ValueError so the caller (P3 stage
transition) records last_error rather than silently swallowing bad input.
"""

from __future__ import annotations

import ast
import csv
import json
from pathlib import Path

from ascendc_devkit.domain.requirement import TestCase

# Columns the adapter cannot operate without. The CSV may carry more (and may
# leave cells empty), but these headers must exist. Sourced from the
# generate-case skill's own schema (testcase_csv.json) so the column contract a
# skill carries into Claude Code TUI and the contract this adapter parses are
# one and the same (first-principle: schema travels with the skill; no Python
# hardcode that can drift from it). Loaded once at import; a missing/invalid
# schema is a hard error (SchemaNotFoundError) — the contract must exist.
def _load_required_columns() -> tuple[str, ...]:
    from ascendc_devkit.adapters.schema.loader import SchemaLoader
    spec = SchemaLoader.load_spec_from_skill(
        "ascendc-st-design",
        "testcase_csv.json")
    return spec.required_keys


_REQUIRED_COLUMNS = _load_required_columns()


def parse_testcase_csv(csv_path: Path, operator=None) -> list[TestCase]:
    """Parse a testdesign CSV into a list of TestCase.

    Reads with ``utf-8-sig`` to strip the BOM the skill writes. Returns an
    empty list for a header-only CSV. Raises ValueError on a missing required
    column or an unparseable repr-tuple cell.

    ``operator`` (an ``OperatorSpec``) is optional: when it declares tensor
    inputs, the flat per-tensor shapes are regrouped into one entry per logical
    parameter — a ``param_type=DYNAMIC`` (CANN ``Tensor[]``) input absorbs the
    per-side tensor surplus and takes a nested ``list[list[int]]`` shape. With
    no op_spec, or a name-only op_spec that carries no positional info, the
    legacy 1:1 flat mapping is used so the adapter stays usable standalone.
    """
    csv_path = Path(csv_path)
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        missing = [c for c in _REQUIRED_COLUMNS if c not in fieldnames]
        if missing:
            raise ValueError(
                f"CSV '{csv_path}' missing required column(s): "
                f"{', '.join(missing)}. Found: {', '.join(fieldnames) or '(none)'}"
            )
        cases: list[TestCase] = []
        for idx, row in enumerate(reader, start=1):
            cases.append(_row_to_testcase(row, idx, csv_path, operator))
    return cases


def _row_to_testcase(row: dict, idx: int, csv_path: Path,
                     operator=None) -> TestCase:
    op_name = (row.get("op_name") or "").strip()
    name = (row.get("testcase_name") or "").strip() or f"{op_name}_{idx}"

    shapes = _parse_repr_field(row.get("stc_inputs"), "stc_inputs", idx, csv_path)
    dtypes = _parse_repr_field(
        row.get("stc_input_dtypes"), "stc_input_dtypes", idx, csv_path)
    formats = _parse_repr_field(
        row.get("stc_input_formats"), "stc_input_formats", idx, csv_path)

    shapes = _as_shape_list(shapes)
    dtypes = _as_scalar_list(dtypes)
    formats = _as_scalar_list(formats)

    # 契约校验（§1.3 加载期校验优于运行期暴露）：testcase_csv.json 要求
    # stc_input_dtypes 逐输入声明（并行数组，merge_test_cases 对每个 tensor 产出
    # 一个 dtype 项）。声明不足 = producer 违约（输入错误），显式报错让 LLM/skill
    # 修正，而非静默截断（旧 n=min）或静默降级 fp16。空 dtype 列不报（走 runner
    # 既有 fp16 默认 / 存量继承）。此处统一校验 flat shapes 数，op_spec 分组
    # （_build_inputs，DYNAMIC 吸收 surplus）与 legacy 1:1 映射（_flat_inputs）
    # 两条路径共享同一契约——dtype 数对应 flat tensor 数，不随逻辑分组变化。
    num_tensor_inputs = len(shapes)
    if dtypes and len(dtypes) != num_tensor_inputs:
        _direction = "少于" if len(dtypes) < num_tensor_inputs else "多于"
        raise ValueError(
            f"CSV '{csv_path}' row {idx}: stc_input_dtypes 声明 {len(dtypes)} 个 dtype，"
            f"但 stc_inputs 有 {num_tensor_inputs} 个输入槽位（含 None 占位；"
            f"契约要求逐输入声明且可选缺省处三列同位 None，"
            f"数量必须一致；当前{_direction}槽位数）"
        )

    op_inputs = getattr(operator, "inputs", None) if operator is not None else None
    # input_data_ranges → 逐槽位可执行值域（与 stc_inputs 同位对齐）。这是
    # 值域进入 runner/harness 世界的唯一通路（§2.5）：消费侧只读 per-input
    # value_range，ranges 装箱进 case 级字段无人能读（历史缺陷，已删）。
    flat_ranges = _normalize_range_slots(
        _as_scalar_list(_parse_repr_field(
            row.get("input_data_ranges"), "input_data_ranges", idx, csv_path)),
        num_tensor_inputs, idx, csv_path)
    if op_inputs:
        # op_spec declares tensor inputs → regroup flat per-tensor shapes into
        # one entry per logical parameter (DYNAMIC/Tensor[] absorbs surplus).
        inputs = _build_inputs(op_inputs, shapes, dtypes, formats, flat_ranges)
    else:
        # No positional info (no op_spec, or name-only op_spec) → legacy flat.
        inputs = _flat_inputs(shapes, dtypes, formats, flat_ranges)

    expected = _parse_precision(row.get("absolute_precision"))
    attrs = _parse_attrs(row.get("other_compilation_params"))

    return TestCase(
        name=name,
        inputs=inputs,
        expected=expected,
        generator="random_uniform",
        generator_params=None,
        attrs=attrs,
        # 来源标记：本 adapter 只解析 test_design / st-design 生成的 CSV，供 baseline
        # 报告把 st-design 生成用例与 cann-bench 原有用例分开统计（§1.12）。
        source="devkit",
    )


def _flat_inputs(shapes, dtypes, formats, ranges=None) -> list[dict]:
    """Legacy 1:1 flat mapping — one ``input_i`` entry per parsed tensor shape.

    Used when no op_spec is available (skill standalone / name-only op_spec).
    dtype 数量已在 _row_to_testcase 的契约校验（§1.3）保证等于 shapes 数；format
    是弱契约元数据（harness 不消费），缺省允许。此处只做防御性 bounds 检查，
    不做任何静默截断——声明不足的行在入口就被拒。

    A ``None`` slot is an omitted OPTIONAL input: no entry is produced (the
    in-memory list stays compact) and surviving entries carry an explicit
    ``proto_idx`` so positional restoration never infers from names (§1.15).
    """
    inputs: list[dict] = []
    n = len(shapes)
    if ranges and len(ranges) != n:
        raise ValueError(
            f"input_data_ranges 声明 {len(ranges)} 个值域，但 stc_inputs 有 "
            f"{n} 个输入槽位——legacy flat 路径按槽位逐一对齐，数量必须一致。")
    for i in range(n):
        if shapes[i] is None:
            continue                                 # omitted slot: no entry
        entry = {"name": f"input_{i}", "shape": list(shapes[i]),
                 "proto_idx": i}
        if i < len(dtypes) and dtypes[i] is not None:
            entry["dtype"] = dtypes[i]
        if i < len(formats) and formats[i] is not None:
            entry["format"] = formats[i]
        if ranges and i < len(ranges) and ranges[i] is not None:
            entry["value_range"] = ranges[i]
        inputs.append(entry)
    return inputs


# inf/nan 以字符串字面量落盘（_format_number），转换回 float 后由 runner 的
# _norm_vr 归一为 __INF__/__NAN__ 哨兵——与 cann-bench loader 路径同一条链。
_RANGE_SPECIAL_BOUNDS = {"inf": float("inf"), "+inf": float("inf"),
                         "-inf": float("-inf"), "nan": float("nan")}


def _is_range_bound(v) -> bool:
    """值域端点合法性：数值，或 inf/nan 字符串字面量。"""
    if isinstance(v, (int, float)):
        return True
    return isinstance(v, str) and v.lower() in _RANGE_SPECIAL_BOUNDS


def _as_range_bound(v):
    """端点归一：inf/nan 字符串 → float；数值原样（int 保持 int）。"""
    if isinstance(v, str):
        return _RANGE_SPECIAL_BOUNDS[v.lower()]
    return v


def _normalize_range_slots(ranges, num_slots, idx: int, csv_path) -> list:
    """input_data_ranges 值 → 逐槽位对齐列表（每槽 ``None`` 或 ``[lo, hi]``）。

    挂载语义与 cann_bench_cases_loader 的 per-input value_range（Fix E）一致：
    值域是逐输入事实，case 级单一区间表达不了多输入异值域。槽位语义与
    stc_inputs 完全同构——``None`` = 缺省可选占位（跳过），字面数值对原样保留
    （``[0, 0]`` 是因子候选选中的真实区间，如全零输入边界用例，不是"无约束"）。

    符号串（未实例化的维度表达式，如 ``C-1``）在本层不可执行也不可猜测——
    诚实报错（§1.3/§3.7），绝不静默回退默认值域制造非法输入。

    长度对齐由消费路径校验：proto 路径（_build_inputs）按**逻辑参数**对齐
    （生成器逐 param 产出，DYNAMIC 参数一个值域），legacy flat 路径
    （_flat_inputs）按扁平张量槽对齐——无 TensorList 时二者重合。
    """
    if not ranges:
        return []
    # 单输入行的扁平单对形式（"[-1.0, 1.0]"，非嵌套）→ 包装为单槽。
    if (num_slots == 1 and len(ranges) == 2
            and all(_is_range_bound(v) for v in ranges)):
        ranges = [ranges]
    slots: list = []
    for slot in ranges:
        if slot is None:
            slots.append(None)
            continue
        if (isinstance(slot, (tuple, list)) and len(slot) == 2
                and all(_is_range_bound(v) for v in slot)):
            slots.append([_as_range_bound(v) for v in slot])
            continue
        # 非法槽位：符号表达式（维度名，如 C-1）或结构错。这是上游设计产物
        # 违约——符号必须在设计/求解层实例化为具体数值，本层不猜、不回退。
        token = slot if isinstance(slot, str) else repr(slot)
        raise ValueError(
            f"CSV '{csv_path}' row {idx}: input_data_ranges 含不可执行的值域声明 "
            f"{token!r} —— 值域槽位只能是数值对 [lo, hi] 或 None 占位；维度符号"
            f"表达式属设计层未实例化产物，须先在因子求解层落成具体数值。")
    return slots


def _build_inputs(op_inputs, flat_shapes, flat_dtypes, flat_formats,
                  flat_ranges=None) -> list[dict]:
    """Regroup flat per-tensor shapes into one entry per logical parameter.

    The CSV lists every input-side tensor as a flat shape (TensorList boundary
    lost). op_spec restores it: a ``param_type=DYNAMIC`` (CANN ``Tensor[]``)
    parameter absorbs the per-side tensor surplus — its members are contiguous
    in declaration order — and takes a nested ``list[list[int]]`` shape; every
    other tensor parameter consumes one flat ``list[int]``. The judature is the
    business-semantic ``param_type`` (§1.10/§1.12), never the operator name.

    Positional semantics (§1.15): a ``None`` slot in the flat columns is an
    omitted OPTIONAL input — the placeholder keeps the declared position while
    the in-memory list stays compact (no entry produced), and every surviving
    entry carries an explicit ``proto_idx`` (its declared position). Position
    is never inferred from names; restoration downstream consumes ``proto_idx``
    only. An OPTIONAL may sit at ANY position (middle included), not just the
    tail. Out-of-range slots (a flat list shorter than the declared params,
    legacy under-count) degrade to absent the same way.

    Single DYNAMIC per side is the unambiguous, supported case (the dominant
    aclnn pattern). Surfaced honestly (§3.7) rather than guessed: multiple
    DYNAMIC inputs, a tensor surplus with no DYNAMIC input to absorb it
    (EXCEPT the single-input degenerate foreach upgrade below), and a DYNAMIC
    input sharing a case with an omitted OPTIONAL — the flat list has no
    TensorList boundary, so the surplus cannot be attributed unambiguously;
    split into separate case rows instead.
    """
    import logging
    _log = logging.getLogger(__name__)

    dyn_idx = [
        i for i, p in enumerate(op_inputs)
        if str(getattr(p, "param_type", "")).upper() == "DYNAMIC"
    ]
    # 值域按逻辑参数对齐（生成器逐 param 产出；DYNAMIC 参数一个值域管全部成员），
    # 与扁平形状槽不同构——TensorList 场景二者数量天然不等。
    if flat_ranges and len(flat_ranges) != len(op_inputs):
        raise ValueError(
            f"input_data_ranges 声明 {len(flat_ranges)} 个值域，但 op_spec 声明 "
            f"{len(op_inputs)} 个输入参数——proto 路径按逻辑参数逐一对齐，"
            f"数量必须一致。")
    absent = [i for i, s in enumerate(flat_shapes) if s is None]
    n_total = len(flat_shapes) - len(absent)   # placeholders are not tensors
    n_fixed = len(op_inputs) - len(dyn_idx)
    names = [getattr(p, "name", "") or f"input_{i}"
             for i, p in enumerate(op_inputs)]

    if len(dyn_idx) > 1:
        raise ValueError(
            f"cannot group test-case shapes: multiple DYNAMIC (Tensor[]) "
            f"inputs {names} — the CSV carries no per-param TensorList length, "
            f"so the flat shape list cannot be split unambiguously.")
    if dyn_idx and absent:
        raise ValueError(
            f"cannot group test-case shapes: DYNAMIC (Tensor[]) input(s) "
            f"{[names[i] for i in dyn_idx]} cannot share a case with omitted "
            f"OPTIONAL input(s) {[names[i] for i in absent if i < len(names)]} "
            f"— the CSV flat list carries no TensorList boundary, so the "
            f"tensor surplus cannot be attributed unambiguously. Split into "
            f"separate case rows (all-present row / omitted-optional row).")
    if not dyn_idx and n_total > n_fixed:
        # Defense-in-depth: a single-input op with a tensor surplus is the
        # degenerate foreach/TensorList pattern — the input should have been
        # declared DYNAMIC. Upgrade it rather than halting the pipeline (the
        # primary fix in TensorSpec.from_dict infers DYNAMIC from is_list/
        # tensor_list; this fallback catches any remaining gap).
        if n_fixed == 1 and n_total > 1:
            _log.warning(
                "inferring DYNAMIC (Tensor[]) for input %r: %d flat tensors "
                "with a single non-variadic input — the input likely carries "
                "is_list/tensor_list but param_type was not set to DYNAMIC. "
                "TensorSpec.from_dict should have inferred this; this fallback "
                "indicates a gap upstream.", names[0], n_total)
            dyn_idx = [0]  # upgrade the sole input
            n_fixed = len(op_inputs) - len(dyn_idx)  # recalc after upgrade
        else:
            raise ValueError(
                f"cannot group test-case shapes: {n_total} flat tensors exceed "
                f"{n_fixed} non-variadic input(s) {names} and no DYNAMIC "
                f"(Tensor[]) input is declared to absorb the surplus.")

    inputs: list[dict] = []
    if dyn_idx:
        # All params present (absent is empty here — rejected above), so the
        # cursor walk equals declaration order; DYNAMIC absorbs the surplus.
        n_dyn = max(0, n_total - n_fixed)
        cursor = 0
        for i in range(len(op_inputs)):
            if i in dyn_idx:
                members = flat_shapes[cursor:cursor + n_dyn]
                m_dtypes = flat_dtypes[cursor:cursor + n_dyn]
                m_formats = flat_formats[cursor:cursor + n_dyn]
                cursor += n_dyn
                entry = {"name": names[i],
                         "shape": [list(m) for m in members],
                         "proto_idx": i}
                # aclnn Tensor[] members are homogeneous dtype/format; take the
                # declared member's (lossless for the only case Tensor[]
                # expresses). value_range 同构：该参数自己的单值域管全部成员。
                if m_dtypes and m_dtypes[0] is not None:
                    entry["dtype"] = m_dtypes[0]
                if m_formats and m_formats[0] is not None:
                    entry["format"] = m_formats[0]
                if flat_ranges and flat_ranges[i] is not None:
                    entry["value_range"] = flat_ranges[i]
            else:
                j = cursor
                cursor += 1
                shape = flat_shapes[j] if j < len(flat_shapes) else []
                entry = {"name": names[i], "shape": list(shape),
                         "proto_idx": i}
                if j < len(flat_dtypes):
                    entry["dtype"] = flat_dtypes[j]
                if j < len(flat_formats):
                    entry["format"] = flat_formats[j]
                # flat_ranges 按逻辑参数对齐（与 proto 路径同一约定），此处
                # 声明序即游标序，i 即该参数自己的值域槽位。
                if flat_ranges and i < len(flat_ranges) \
                        and flat_ranges[i] is not None:
                    entry["value_range"] = flat_ranges[i]
            inputs.append(entry)
        return inputs

    # Non-DYNAMIC: positional take — the i-th declared param reads flat slot i;
    # a None (or out-of-range) slot is an omitted OPTIONAL and yields no entry.
    for i in range(len(op_inputs)):
        shape = flat_shapes[i] if i < len(flat_shapes) else None
        if shape is None:
            # An explicit None (in-range) means that proto slot was declared
            # absent — legal only for an OPTIONAL/DYNAMIC param. An out-of-range
            # slot (flat list shorter than declared) is the legacy under-count and
            # degrades silently (tail-omitted OPTIONAL). So the required-input
            # guard fires only on an in-range placeholder (§1.3 load-time honest
            # failure, not a silent data drop).
            if i < len(flat_shapes):
                ptype = str(getattr(op_inputs[i], "param_type", "")).upper()
                if ptype not in ("OPTIONAL", "DYNAMIC"):
                    raise ValueError(
                        f"input {names[i]!r} (param_type={ptype or 'REQUIRED'}) "
                        f"is absent (None) in the test case, but it is not "
                        f"declared OPTIONAL/DYNAMIC.")
            continue
        entry = {"name": names[i], "shape": list(shape), "proto_idx": i}
        if i < len(flat_dtypes) and flat_dtypes[i] is not None:
            entry["dtype"] = flat_dtypes[i]
        if i < len(flat_formats) and flat_formats[i] is not None:
            entry["format"] = flat_formats[i]
        if flat_ranges and i < len(flat_ranges) and flat_ranges[i] is not None:
            entry["value_range"] = flat_ranges[i]
        inputs.append(entry)
    return inputs


def _parse_repr_field(raw, col: str, idx: int, csv_path: Path):
    """``ast.literal_eval`` a repr-tuple cell. Empty → None. Bad → ValueError."""
    s = (raw or "").strip()
    if not s:
        return None
    try:
        return ast.literal_eval(s)
    except (ValueError, SyntaxError) as exc:
        raise ValueError(
            f"CSV '{csv_path}' row {idx}: cannot parse column '{col}' "
            f"value {s!r}: {exc}"
        ) from exc


def _as_shape_list(value):
    """Normalize a parsed stc_inputs value into a list of shape tuples.

    Handles the single-input collapse quirk: ``ast.literal_eval("((1,2,3))")``
    yields a flat int tuple ``(1, 2, 3)``, which is ONE shape, not three. A
    tuple of tuples/lists is already the multi-input form.

    A ``None`` element is a position placeholder (omitted OPTIONAL input) —
    it must stay in place (positional semantics), never be dropped and never
    make the all()-guard misgroup the column as one collapsed shape.
    """
    if value is None:
        return []
    if not isinstance(value, (tuple, list)):
        return []
    if value and all(isinstance(e, (tuple, list)) or e is None
                     for e in value):
        return [None if e is None else list(e) for e in value]
    # Flat sequence of scalars → a single collapsed shape.
    return [list(value)]


def _as_scalar_list(value):
    """Normalize a parsed dtypes/formats value into a flat list of scalars.

    Handles the single-element collapse quirk: ``ast.literal_eval("('ND')")``
    yields the bare string ``'ND'`` (must wrap), while ``"('ND',)"`` is already
    a 1-tuple. A ``None`` element is an omitted-slot placeholder kept in place
    (parallel-array alignment with stc_inputs, L1 P7); consumers skip it.
    """
    if value is None:
        return []
    if isinstance(value, (tuple, list)):
        return list(value)
    return [value]


def _parse_precision(raw):
    """absolute_precision → {"max_diff": float} or None.

    Perf CSVs put prose (e.g. '相比小算子拼接性能提升10倍以上') here; a
    non-numeric value is treated as 'no precision threshold' rather than an
    error so the adapter stays robust across CSV flavors.
    """
    s = (raw or "").strip()
    if not s:
        return None
    try:
        return {"max_diff": float(s)}
    except ValueError:
        return None


def _parse_attrs(raw):
    """other_compilation_params → dict of operator attrs.

    The cell carries the operator's scalar attributes as a dict literal (e.g.
    ``{"scalar": 3.0}``, ``{"axis": -1, "epsilon": 1e-6}``). The harness
    forwards ``TestCase.attrs`` as ``**kwargs`` to BOTH kernel and golden, so an
    unparsed cell starves the operator of required scalars at runtime. An empty
    cell (attr-less op) → ``{}``. JSON is tried first (it accepts scientific
    notation like ``1e-6`` that ``ast.literal_eval`` rejects); ``ast`` is the
    fallback for Python-literal variants (single-quoted keys, ``None``/``True``).
    A non-empty cell that is neither a dict nor parseable is a data error —
    surface it (§3.7) rather than silently dropping attrs.
    """
    s = (raw or "").strip()
    if not s:
        return {}
    try:
        v = json.loads(s)
    except (ValueError, SyntaxError):
        try:
            v = ast.literal_eval(s)
        except (ValueError, SyntaxError) as exc:
            raise ValueError(
                f"cannot parse other_compilation_params attrs {s!r}: {exc}"
            ) from exc
    if not isinstance(v, dict):
        raise ValueError(
            f"other_compilation_params must be a dict literal, got "
            f"{type(v).__name__}: {v!r}")
    return v
