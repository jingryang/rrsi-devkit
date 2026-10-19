"""L4 Domain — Operator specification types."""

import logging
import re
from dataclasses import dataclass, field, fields
from pathlib import Path

from ascendc_devkit.domain.exceptions import HarnessContractError

logger = logging.getLogger(__name__)


def filter_known_fields(cls, d: dict) -> dict:
    """Keep only the keys of ``d`` that map to declared fields of ``cls``.

    LLM- and file-sourced dicts routinely carry extra descriptive metadata
    (``role``, ``note``, ``supported_dtypes``, ...) that these strict frozen
    specs do not model. Dropping unknown keys lets ``Cls(**d)`` construction
    survive that richer input instead of raising ``TypeError`` on the first
    unexpected keyword argument.
    """
    allowed = {f.name for f in fields(cls)}
    return {k: v for k, v in d.items() if k in allowed}


def coerce_precision_thresholds(raw: object) -> dict[str, float] | None:
    """Coerce proto ``precision_thresholds`` (``{dtype: max_diff_or_relative}``)
    into a clean ``dict[str, float]``.

    proto.yaml (cann-bench 产物) 是精度容差的**单一权威源** (P69)。非 dict / 空
    → ``None``（proto 未声明精度规格，下游用默认表 + 显式标记「无精度规格」，**不静默**）。
    逐项 ``float()``；坏值跳过而非整图崩（§1.3 加载期校验优于运行期暴露，§1.4 不留坏值兜底分支）。
    """
    if not isinstance(raw, dict) or not raw:
        return None
    out: dict[str, float] = {}
    for k, v in raw.items():
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError):
            logger.warning(
                "coerce_precision_thresholds: 丢弃不可解析项 %r=%r (期望数值).", k, v,
            )
            continue
    return out or None


# ── Canonical attr-type system (single source of truth, §2.5) ──────────────
# step-105 (docs/plan/op-attr-type-system/): the attr type system is a
# RECURSIVE structure grammar anchored on Python typing spelling (PEP 484/604)
# — NOT a finite enumeration table. Canonical forms are plain strings:
#   base      "int" | "float" | "str" | "bool"
#   list      "list[T]"   (any nesting depth, e.g. "list[list[int]]")
#   union     "T1|T2"     (any arity; "X|None" = nullable)
# The single recursive checker (``check_attr_value``) executes the grammar;
# ``CANON_ATTR_CHECKERS`` remains as the LEAF-plus-common-composite table
# (deploy _SMOKE_ATTR_DEFAULTS keys ⊆ it, load-time asserted). Label
# translation (``_canonical_attr_type``) maps every producer spelling onto
# the grammar: new combinations are free, new spellings cost one alias row,
# untranslatable labels pass through unchanged to be halted loudly by the
# requirement-stage self-check (defence line 2) — never silently re-encoded
# (the 20260829 interpolate incident was exactly that silent channel).

# 文法递归界（防御性，§1.3）：病态标签（超深嵌套/超长）判不可翻译——文法侧
# False、翻译侧 ValueError → 原样透传，走 AttrSpec 构造期既有 WARN 路径——
# 而不是烧穿解释器递归栈。真实语料最深 2 层、标签最长 ~60 字符，16/256 余量充足。
_GRAMMAR_MAX_DEPTH = 16
_GRAMMAR_MAX_LABEL_LEN = 256


def _is_int_value(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_float_value(v: object) -> bool:
    # ints are assignable to float; bool excluded (bool is an int subclass).
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_str_value(v: object) -> bool:
    return isinstance(v, str)


def _is_bool_value(v: object) -> bool:
    return isinstance(v, bool)


def check_attr_value(value: object, canon_type: str, depth: int = 0) -> bool:
    """Recursive structural check of an attr value against a canonical type
    expression — the single checker (§1.15; consumed by ``validate_case_attrs``
    — the runner pre-flight and the test_design self-check). Semantics align
    with JSON Schema structure rules: array+items / anyOf=union / None=null.

    Grammar: base | "list[T]" | "T1|T2" (nesting bounded by
    ``_GRAMMAR_MAX_DEPTH``/``_GRAMMAR_MAX_LABEL_LEN`` — over-bound labels are
    judged non-grammar, never a recursion blow-up). Non-grammar labels
    (passthrough like ``Tensor``/enums) return False — callers fall back to
    the generic scalar check (legacy behaviour; the load-time WARN already
    fired at AttrSpec construction).
    """
    t = (canon_type or "").strip()
    if not t or len(t) > _GRAMMAR_MAX_LABEL_LEN or depth > _GRAMMAR_MAX_DEPTH:
        return False
    if value is None:
        # null passes only as an explicit union member ("X|None" — the
        # grammar's nullable form); JSON Schema null-semantics.
        return t == "None" or any(p.strip() == "None" for p in t.split("|"))
    if "|" in t:  # union: any branch passing suffices ("X|None" included)
        return any(check_attr_value(value, part, depth + 1) for part in t.split("|"))
    if t in ("int", "float", "str", "bool"):
        return _CANON_LEAF[t](value)
    if t.startswith("list[") and t.endswith("]"):
        if not isinstance(value, (list, tuple)):
            return False
        return all(check_attr_value(x, t[5:-1].strip(), depth + 1) for x in value)
    return False


_CANON_LEAF = {
    "int": _is_int_value,
    "float": _is_float_value,
    "str": _is_str_value,
    "bool": _is_bool_value,
}


def is_grammar_type(canon_type: str) -> bool:
    """True iff the string parses on the type grammar (base | list[T] | T1|T2,
    nesting bounded by ``_GRAMMAR_MAX_DEPTH``/``_GRAMMAR_MAX_LABEL_LEN``,
    ``None`` literal allowed in unions). Structural — mirrors
    check_attr_value's dispatch without a value."""
    t = (canon_type or "").strip()
    if not t:
        return False
    return all(_grammar_one(p) for p in t.split("|"))


def _grammar_one(t: str, depth: int = 0) -> bool:
    t = t.strip()
    if not t or len(t) > _GRAMMAR_MAX_LABEL_LEN or depth > _GRAMMAR_MAX_DEPTH:
        return False
    if t in _CANON_LEAF or t == "None":
        return True
    if t.startswith("list[") and t.endswith("]"):
        return _grammar_one(t[5:-1].strip(), depth + 1)
    return False


def _canon_check(canon_type: str):
    """Partial application of check_attr_value — table-friendly form."""
    return lambda v: check_attr_value(v, canon_type)


# Leaf + common-composite table. Deploy's _SMOKE_ATTR_DEFAULTS keys must be a
# subset (load-time assert in deploy.py). Container logic lives in
# check_attr_value — this table is for legacy key-based lookup only.
CANON_ATTR_CHECKERS = {
    "int": _is_int_value,
    "float": _is_float_value,
    "str": _is_str_value,
    "bool": _is_bool_value,
    "list[int]": _canon_check("list[int]"),
    "list[float]": _canon_check("list[float]"),
    "list[str]": _canon_check("list[str]"),
    "list[bool]": _canon_check("list[bool]"),
    "list[list[int]]": _canon_check("list[list[int]]"),
    "int|float": _canon_check("int|float"),
}


# ── Case-attr validation (single point, §1.15/§2.5) ─────────────────────────
# 提自 adapters/npu/runner 的私有 ``_validate_attrs``：同一校验被 runner
# （执行前 pre-flight）与 orchestration/test_design 自检（产出当下防线 3）两个
# 消费者使用，属域规则——编排层不再 import adapter 私有符号（G1 F9）。


def validate_case_attrs(attrs, idx: int, operator=None) -> None:
    """Validate one test case's ``attrs`` dict against the operator contract.

    Raises :exc:`HarnessContractError` on violation. When ``operator`` carries
    an ``attrs`` spec (``OperatorSpec.attrs`` / duck-typed), each attr value is
    checked against the declared type via the recursive grammar checker;
    without a spec, only dict-structure is enforced.

    SIDE EFFECT (numeric-string coerce): numeric strings are coerced against
    the DECLARED numeric spec **in place** (``attrs[k]`` is rewritten) so the
    corrected value flows downstream to the harness. cann-bench fixtures store
    numbers as quoted strings (cases.csv attrs JSON ``{"epsilon":"1e-6"}``;
    cases.yaml ``1e-6`` → YAML safe_load str); the subprocess harness already
    coerces (``_cast_attr``), but this pre-flight ran first and rejected
    str-typed numerics before that coercion. A UNION spec counts when ANY
    branch is numeric (``"int|float"`` — the ATen ``Scalar`` canonical form):
    branches are tried in declaration order, first parse wins (``"1e-6"``
    fails ``int`` but parses ``float``); a non-numeric string falls through to
    the type check and raises there.
    """
    if not isinstance(attrs, dict):
        raise HarnessContractError(
            f"test_cases[{idx}].attrs must be dict "
            f"(got {type(attrs).__name__})"
        )

    spec = getattr(operator, "attrs", None) or {}
    for k, v in attrs.items():
        attr_spec = spec.get(k)
        expected = attr_spec.type if attr_spec and hasattr(attr_spec, "type") else None
        # Optional/nullable attr: a value of None means "not provided / use the
        # declared default". golden encodes optionality as ``default=null`` (e.g.
        # resize_bilinear ``output_size``/``scale_factor`` are ``Optional``,
        # mutually exclusive — a scale_factor-path case legitimately passes
        # output_size=None). Accept None only when the spec declares default=None
        # (§1.13 faithful consumption of golden Optional semantics; §1.12
        # structural signal via the default field). Attrs with a concrete default
        # (false/0/[]) still reject None below — None is not their declared type.
        if v is None and attr_spec is not None and getattr(attr_spec, "default", None) is None:
            continue
        # Coerce numeric-string attrs against the DECLARED numeric spec before
        # type-checking (see docstring: union branches count, in-place rewrite).
        if isinstance(v, str):
            numeric_branches = [b.strip() for b in (expected or "").split("|")
                                if b.strip() in ("int", "float")]
            if numeric_branches:
                for branch in numeric_branches:
                    try:
                        v = int(v) if branch == "int" else float(v)
                        attrs[k] = v
                        break
                    except (ValueError, TypeError):
                        continue
                # not a numeric string → fall through to type-check → raise
        # step-105: dispatch to the recursive grammar checker (single source:
        # domain check_attr_value — base | list[T] | T1|T2 at any depth). No
        # per-type branch list (§2.5): new combinations are free.
        if expected and is_grammar_type(expected):
            if not check_attr_value(v, expected):
                raise HarnessContractError(
                    f"test_cases[{idx}].attrs[{k!r}] expected {expected}, "
                    f"got {type(v).__name__}={v!r}"
                )
            # Fixed-length is the DECLARED contract (L4 红线 1): only checked
            # when the spec carries a length; semantic-variadic params declare
            # list[T] without one.
            fixed_len = getattr(attr_spec, "length", None) if attr_spec else None
            if fixed_len is not None and isinstance(v, (list, tuple)) and len(v) != fixed_len:
                raise HarnessContractError(
                    f"test_cases[{idx}].attrs[{k!r}] expected fixed length "
                    f"{fixed_len} (declared), got {len(v)}: {v!r}"
                )
        else:
            # Fallback: no spec, or unrecognized/passthrough type (already
            # load-time WARN'd in AttrSpec.__post_init__). Generic scalar /
            # list-element check — legacy behaviour for non-grammar labels.
            if isinstance(v, bool):
                pass  # acceptable as generic scalar
            elif isinstance(v, (list, tuple)):
                if not all(isinstance(x, (int, float, str, bool)) for x in v):
                    raise HarnessContractError(
                        f"test_cases[{idx}].attrs[{k!r}] list elements "
                        f"must be scalar"
                    )
            elif not isinstance(v, (int, float, str)):
                raise HarnessContractError(
                    f"test_cases[{idx}].attrs[{k!r}] has unsupported "
                    f"type {type(v).__name__}"
                )


# ── Label → canonical-type translation (single translation point, §1.9) ────
# Producers emit many spellings (ATen schema, C++ types, proto.yaml, Python
# typing). The translator maps them onto the grammar above. Anchored on
# existing standards — no invented notation (step-105 L3 标准对齐表).

_INT_TYPE_RE = re.compile(r"^(u?int)(\d+)?$")
_FLOAT_TYPE_RE = re.compile(r"^(float|double|half)(\d+)?$")
_SCALAR_BASE_CANON = {"str": "str", "string": "str", "bool": "bool"}

# Whole-word aliases (lowercased). ATen schema vocabulary + generic synonyms.
_ALIAS_WORDS = {
    "intlist": "list[int]",        # ATen IntList
    "floatlist": "list[float]",    # ATen FloatList
    "strlist": "list[str]",        # ATen StrList(罕见)
    "boollist": "list[bool]",
    "listlistint": "list[list[int]]",  # CANN ListListInt
    "scalar": "int|float",       # ATen Scalar
    "symint": "int",             # ATen SymInt
    "scalartype": "str",         # ATen ScalarType (dtype label)
    "dimname": "str",            # ATen Dimname
    "memoryformat": "str",       # ATen MemoryFormat
    "number": "int|float",
    "double": "float",
    "string": "str",
    "long": "int",
    "integer": "int",
    "boolean": "bool",
}


def _base_word(elem: str) -> str | None:
    """Single element word → grammar base / union (None = not base-typed)."""
    e = re.sub(r"_t$", "", elem.strip().lower())
    if not e:
        return None
    if e in _ALIAS_WORDS:
        return _ALIAS_WORDS[e]
    if _INT_TYPE_RE.match(e):
        return "int"
    if _FLOAT_TYPE_RE.match(e):
        return "float"
    if e in _SCALAR_BASE_CANON:
        return _SCALAR_BASE_CANON[e]
    return None


def _strip_pascal_list(elem: str) -> tuple[str, int]:
    """Strip leading list markers: ListInt→(int,1), ListListInt→(int,2),
    ListFloat→(float,1), camelCase listInt→(Int,1). Returns (rest, depth)."""
    rest = elem
    depth = 0
    while True:
        m = re.match(r"^[Ll]ist(?=[A-Za-z_])", rest)
        if not m:
            break
        rest = rest[4:]
        depth += 1
    return rest, depth


def _translate_spec(spec: str, depth: int = 0) -> tuple[str, int, int | None]:
    """Translate ONE union-free, bracket-tail-free spec onto the grammar.

    Returns (canon, list_depth, fixed_length). ``spec`` may still contain
    bracket nesting (``int[][]``), comma-tuples (``int, int``) or parenthesized
    unions (``(int|None)``) — handled here. Raises ValueError when
    untranslatable (incl. over-bound depth/length — caller passthrough).
    """
    spec = spec.strip()
    if not spec or len(spec) > _GRAMMAR_MAX_LABEL_LEN or depth > _GRAMMAR_MAX_DEPTH:
        raise ValueError(f"untranslatable spec (grammar bound): {spec!r}")
    # parenthesized group: strip ONE outer layer of brackets (the inner may be
    # a union — "(int|None)[2]" → translate "int|None" with fixed length 2).
    if spec.startswith("(") and spec.endswith(")"):
        spec = spec[1:-1].strip()
    # comma-tuple (tuple[int, int, int] arrives here after wrapper strip):
    # value semantics = list whose element type is the UNION of members.
    if "," in spec:
        parts = [p.strip() for p in spec.split(",") if p.strip()]
        translated = [_translate_spec(p, depth + 1) for p in parts]
        union = sorted({t for t, _, _ in translated})
        inner_depth = max(d for _, d, _ in translated)
        # the wrapper loop already counted the tuple[...] layer as depth 1;
        # bare comma-forms (no wrapper) don't occur in the corpus.
        return "|".join(union), inner_depth, None
    # trailing [] nesting: int[] / int[][]
    m = re.match(r"^(.*?)((?:\[\])+)$", spec)
    if m and m.group(1).strip():
        base, d, n = _translate_spec(m.group(1).strip(), depth + 1)
        return base, d + m.group(2).count("[]"), n
    # trailing [N] fixed length: int[2] / int64[5] / (int|None)[2]
    m = re.match(r"^(.*?)\[(\d+)\]$", spec)
    if m and m.group(1).strip():
        base, d, _ = _translate_spec(m.group(1).strip(), depth + 1)
        return base, d + 1, int(m.group(2))
    # PascalCase list markers: ListInt / ListListInt / ListFloat
    rest, depth = _strip_pascal_list(spec)
    base = _base_word(rest)
    if base is None:
        raise ValueError(f"untranslatable spec: {spec!r}")
    return base, depth, None


def _canonical_attr_type(raw: str) -> str:
    """Translate an attr type LABEL to the canonical grammar string (single
    translation point, §1.9 — the ``to_soc_version`` pattern). Legacy string
    form; fixed-length info is not representable here — use
    :func:`canonical_attr_type` (tuple form) when length matters.

    Covers the producer spelling space observed in the corpus (~50 forms, L1
    issue doc §4): case variants, C++ suffixes, ATen schema (int[]/int[][]/
    List[int]/ListListInt/Scalar/SymInt), Python typing (list[list[int]]/
    tuple[int,int]/Optional[int]/X | None), optional suffix (int?), unions,
    fixed-length (int[2]). Untranslatable labels pass through UNCHANGED —
    surfaced loudly downstream (requirement self-check), never re-encoded.
    """
    s = (raw or "").strip()
    # 空标签/超长标签 = 不可翻译 → 原样透传（AttrSpec 构造期既有 WARN 路径接管）。
    # 长度界同时兜住本函数 union/paren 分支的递归深度（每层至少消耗 1 字符）。
    if not s or len(s) > _GRAMMAR_MAX_LABEL_LEN:
        return s
    nullable = False
    # int? / float? — suffix optional; tolerate trailing parenthetical prose.
    m = re.match(r"^([A-Za-z_][\w\[\],. ]*?)\s*\?\s*(?:[(（].*)?$", s)
    if m:
        nullable = True
        s = m.group(1).strip()
    if re.search(r"\|\s*(?:None|none|null)\s*$", s):
        nullable = True
        s = re.sub(r"\s*\|\s*(?:None|none|null)\s*$", "", s)
    # parenthesized-union-with-tail "(int|None)[2]": hoist the tail BEFORE
    # the union split (each branch inherits it), e.g. → int[2]|None[2]-free.
    if s.startswith("(") and "]" in s and s.endswith("]"):
        m = re.match(r"^\((.*)\)\[(\d+)\]$", s)
        if m:
            inner, n = m.group(1), m.group(2)
            branches = []
            for part in inner.split("|"):
                if part.strip().lower() in ("none", "null"):
                    branches.append("None")  # None 分支不吃定长尾
                    continue
                canon = _canonical_attr_type(f"{part.strip()}[{n}]")
                if not canon:
                    return raw.strip()
                canon = re.sub(r"@\d+$", "", canon)
                branches.append(canon)
            out = "|".join(branches)
            return out + "|None" if nullable else out
    # union: translate each branch independently, keep as union string.
    # Fixed-length markers on branches are dropped (length applies to the
    # whole attr only in the single-branch case; union members of differing
    # lengths make a single N meaningless — declare list[T] instead).
    # Parenthesis-aware split: a branch may itself be a parenthesized union
    # with a tail — "(int|None)[2]" — whose inner "|" is NOT a top-level union.
    if "|" in s:
        parts, buf, depth = [], [], 0
        for ch in s:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            if ch == "|" and depth == 0:
                parts.append("".join(buf)); buf = []
            else:
                buf.append(ch)
        parts.append("".join(buf))
        branches = []
        for part in parts:
            part = part.strip()
            if not part:
                return raw.strip()
            canon = _canonical_attr_type(part)
            if not canon:
                return raw.strip()
            canon = re.sub(r"@\d+$", "", canon)
            branches.append(canon)
        out = "|".join(branches)
        return out + "|None" if nullable else out
    # Optional[...] wrapper.
    m = re.match(r"^Optional\[(.*)\]$", s)
    if m:
        nullable = True
        s = m.group(1).strip()
    # strip outer list[...] / List[...] / tuple[...] wrappers iteratively
    # (list[list[int]], List[List[int]], tuple[int, int, int]).
    depth = 0
    while True:
        m = re.match(r"^(?:List|list|Tuple|tuple)\[(.*)\]$", s)
        if not m:
            break
        inner = m.group(1).strip()
        if not inner:
            break
        s = inner
        depth += 1
    try:
        base, d, n = _translate_spec(s)
    except ValueError:
        return raw.strip()  # passthrough (halted loudly downstream)
    total_depth = depth + d
    canon = base
    for _ in range(total_depth):
        canon = f"list[{canon}]"
    if n is not None:
        canon += f"@{n}"  # internal length marker; AttrSpec unwraps via tuple form
    return canon + "|None" if nullable else canon


def canonical_attr_type(raw: str) -> tuple[str, int | None]:
    """(canonical_type, fixed_length) — the tuple form consumers use.

    The canonical type string itself NEVER carries the length (JSON-
    serializable; smoke-default-table keys unaffected). Fixed-length applies
    to the OUTERMOST list only (``int[2]`` = list[int] of length 2).
    """
    canon = _canonical_attr_type(raw)
    if canon and canon.endswith("]") is False and "@" in canon:
        base, _, n = canon.rpartition("@")
        if n.isdigit():
            return base, int(n)
    # "@N" may also sit before a "|None" suffix.
    m = re.match(r"^(.*)@(\d+)(\|None)?$", canon)
    if m:
        return m.group(1) + (m.group(3) or ""), int(m.group(2))
    return canon, None

@dataclass(frozen=True)
class AttrSpec:
    name: str
    # canonical grammar form — translated in ``__post_init__`` via
    # ``_canonical_attr_type`` onto the recursive type grammar (step-105:
    # base | list[T] | T1|T2). The canonical form IS the faithful semantics;
    # raw spelling variants are equivalent labels, so carrying canonical is
    # faithful (§1.13), not a correction of golden facts. Untranslatable
    # labels pass through unchanged (halted loudly downstream, never
    # silently re-encoded — the 20260829 interpolate incident).
    type: str
    default: object | None = None
    description: str = ""
    # fixed-length of the OUTERMOST list (from labels like ``int[2]``) —
    # declared-contract constraint (L4 过严防护红线 1: 定长是声明的约束，
    # 语义可变参数应声明 list[int] 不带 length).
    length: int | None = None

    def __post_init__(self):
        canon, fixed_len = canonical_attr_type(self.type)
        if canon != self.type:
            object.__setattr__(self, "type", canon)
        if fixed_len is not None and self.length is None:
            object.__setattr__(self, "length", fixed_len)
        if not is_grammar_type(canon):
            # §1.3: surface producer contract violations / misclassifications
            # at load time (e.g. a Tensor/enum label here likely means a tensor
            # wrongly declared as a scalar attr) rather than silent fallback.
            logger.warning(
                "AttrSpec(%r): attr type %r is not a recognized type-grammar "
                "form (grammar: base | list[T] | T1|T2; leaf+composite table: "
                "%s); validator will use generic fallback. If this is a "
                "tensor/enum, it may be misclassified as an attr.",
                self.name, canon, sorted(CANON_ATTR_CHECKERS),
            )




@dataclass(frozen=True)
class TensorSpec:
    name: str
    dtype: str | list[str] = ""  # "fp16" 或 ["fp16","fp32","bf16"]
    # str for dynamic dims, e.g. [128, "N"]. Defaults to [] so an external
    # source that omits shape degrades to an unshaped tensor (last-resort
    # safety net) instead of crashing OperatorSpec.from_dict. Semantic
    # routing in OperatorSpec.from_dict handles the common case (attrs
    # mistakenly listed under inputs) before this net is ever needed.
    shape: list[int | str] = field(default_factory=list)
    # OpDef ParamType (REQUIRED/OPTIONAL/DYNAMIC) — 对齐 CANN
    # ``OpParamDef::ParamType`` 三值。默认 REQUIRED（绝大多数 aclnn IO 必选）；
    # OPTIONAL 经 design_spec→recipe 渲染 ``.ParamType(OPTIONAL)``。authority 源
    # 是 requirement（需求级契约事实），integrate 按 name 对齐进 design_spec。
    param_type: str = "REQUIRED"
    # proto output ``compare: false`` → 精度比较时跳过该输出（cann-bench
    # ignore_output_indices）。``None`` = 正常比较（默认）。
    compare: bool | None = None
    # proto output ``index_gather``: {"input", "dim_attr", "value_output"} —
    # tie 顺序无关的"指向值"自洽校验规格（TopK idx 输出：逐元素比较跳过，
    # 改为 ``x.gather(dim, idx) == values`` 校验）。``None`` = 无声明。
    index_gather: dict | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "TensorSpec":
        kwargs = filter_known_fields(cls, d)
        # P2 (precision-tensorlist-harness-contract): a TensorList entry
        # (``is_list: true``) is a CANN variadic — ParamType(DYNAMIC) is the only
        # coherent declaration. ``REQUIRED``/``OPTIONAL`` on a TensorList is a
        # semantic contradiction (requirement once declared ``Tensor[] x``
        # REQUIRED, which the runner's DYNAMIC gate then rejected for
        # list-of-lists case shapes → PD-CONTRACT abort → upstream halt).
        # Derive DYNAMIC deterministically from the structural signal
        # ``is_list`` (§1.12 — never operator identity), WARN on the rewrite
        # (§1.3 — never silent). ``is_list`` itself is not a TensorSpec field
        # (dropped by filter_known_fields); only the derived param_type survives.
        # M1 (PR-42 review): judge is_list on the NORMALIZED boolean, not truthy
        # — a quoted string ``"false"`` (LLM-written YAML/JSON is legal) is truthy
        # and would wrongly derive DYNAMIC on a non-TensorList input; and a quoted
        # ``"true"`` must still derive (so bare ``is True`` is not enough).
        _is_list_flag = d.get("is_list")
        _is_list = (_is_list_flag is True
                    or (isinstance(_is_list_flag, str)
                        and _is_list_flag.strip().lower() in ("1", "true", "yes")))
        if _is_list and kwargs.get("param_type", "REQUIRED") != "DYNAMIC":
            old = kwargs.get("param_type", "REQUIRED")
            kwargs["param_type"] = "DYNAMIC"
            logger.warning(
                "TensorSpec %r: is_list=true 但 param_type=%r — TensorList 在 CANN 必须 "
                "DYNAMIC，派生为 DYNAMIC。", d.get("name", "?"), old)
        return cls(**kwargs)


# §2.5 single pathway: the authoritative scalar/tensor classifier, shared by
# OperatorSpec._route (object build), design_substages._route_scalar_params
# (in-place design_spec rewrite) and _opdef_missing_canonical_anchors (OpDef
# Attr/Input render check). Business-semantics precedence (§1.10) — never proxies
# via a mechanism feature like ``shape == []`` (which mis-routes shapeless-but-real
# tensors: an elementwise op's ``shape: []`` broadcasting tensor → the
# 20260805-152456 Maximum RCA, where _is_scalar_param's ``shape==[]`` emptied
# inputs/outputs and halted codegen).
_SCALAR_TYPES = {"int", "int8", "int16", "int32", "int64", "uint",
                 "uint8", "uint16", "uint32", "uint64",
                 "float", "float16", "float32", "double", "bool",
                 "str", "string"}


def is_scalar_entry(entry: dict, *, group: str = "",
                    input_names: set[str] | frozenset[str] = frozenset()) -> bool:
    """True iff *entry* is a scalar attr (→ ``Attr``), False iff a wire tensor
    (→ ``Input``/``Output``). The single authoritative predicate (§2.5).

    Judges by BUSINESS SEMANTICS (§1.10) — what the entry **declares about
    itself**, never the value-emptiness of ``shape``:
      1. explicit ``role``: ``attr``→attr, ``tensor``→tensor (author's intent).
      2. ``param_type`` present (REQUIRED/OPTIONAL/DYNAMIC) → tensor (tensor-only
         concept; a DYNAMIC variadic keeps its place even with no shape).
      3. an output aliasing an input by name → tensor (in-place; shape carried by
         ``shape_formula``).
      4. an explicit ``format:"SCALAR"`` (design_spec's declared scalar format) →
         attr — a STRONGER declaration than a bare shape key, so an entry carrying
         both ``shape:[]`` and ``format:SCALAR`` (a true scalar like epsilon) is
         classified as scalar. (op_spec/requirement entries carry no ``format``.)
      5. a real shape signal (``shape`` / ``shape_formula`` / ``shape_constraints``
         **key present**) → tensor. NOTE: key *presence*, not value — ``shape: []``
         WITHOUT ``format:SCALAR`` is a shapeless-but-real broadcasting tensor
         (elementwise ops), not scalar.
      6. a scalar ``type`` (int/float/str/bool…) or a scalar ``dtype`` (single
         scalar string, no shape) → attr.
      7. otherwise undecidable → kept as tensor + a loud warning (§1.3: surface
         the ambiguity, never silently drop a possible tensor).
    """
    role = entry.get("role")
    if role == "attr":
        return True                       # 1
    if role == "tensor":
        return False                      # 1
    if "param_type" in entry:
        return False                      # 2
    name = entry.get("name", "")
    if group == "outputs" and name in input_names:
        return False                      # 3
    if (entry.get("format") or "").upper() == "SCALAR":
        return True                       # 4 — explicit scalar format (stronger than a shape key)
    if ("shape" in entry or "shape_formula" in entry
            or "shape_constraints" in entry):
        return False                      # 5 — real shape signal (key presence, not value)
    stype = entry.get("type")
    if isinstance(stype, str) and stype.lower() in _SCALAR_TYPES:
        return True                       # 6
    dtype = entry.get("dtype")
    if isinstance(dtype, str) and dtype.lower() in _SCALAR_TYPES:
        return True                       # 6
    logger.warning(
        "is_scalar_entry: %s entry %r declares neither a tensor signal "
        "(role/param_type/shape) nor a scalar type; keeping it as a tensor — "
        "declare its kind explicitly to remove this ambiguity.", group, name)
    return False                          # 6


def classify_golden_params(fn) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Classify golden callable *fn*'s parameters into ``(tensor_names,
    scalar_names)`` by the ``Tensor`` annotation (§1.12 structural signal, not
    name). The golden function signature is the §1.13 single authoritative
    source for the operator's IO contract; this is the deterministic parser that
    extracts the tensor input names from it — used by design_substages'
    ``_route_scalar_params`` D-reconcile to align design_spec IO to **golden**
    (not to the LLM-derived requirement).

    Outputs (golden return values) are NOT in a function signature's parameters,
    so only **inputs** are deterministic here; outputs/shape/dtype still need the
    requirement as auxiliary (§1.13). A golden whose params lack ``Tensor``
    annotations → empty tensor_names → caller falls back to requirement.

    NOTE: ``adapters/npu/golden_binding.bind_golden_args`` carries its own copy of
    the ``"Tensor" in annotation`` judgment — it CANNOT call this function because
    its source is inlined (``inspect.getsource``) into the generated harness
    subprocess, which must stay self-contained (no ``ascendc_devkit`` import).
    That shared judgment is a design constraint, not duplication debt (§2.5).
    """
    import inspect
    tensor_names, scalar_names, seen = [], [], set()
    for name, param in inspect.signature(fn).parameters.items():
        ann = "" if param.annotation is inspect.Parameter.empty else str(param.annotation)
        if name in seen:
            continue
        seen.add(name)
        (tensor_names if "Tensor" in ann else scalar_names).append(name)
    return tuple(tensor_names), tuple(scalar_names)


@dataclass(frozen=True)
class OperatorSpec:
    name: str
    inputs: list[TensorSpec] = field(default_factory=list)
    outputs: list[TensorSpec] = field(default_factory=list)
    attrs: dict[str, AttrSpec] = field(default_factory=dict)
    # proto.yaml ``precision_thresholds`` (``{dtype: tolerance}``)，精度容差
    # 单一权威源 (P69)。``None`` = proto 未声明 → 下游用默认表 + 显式标记，不静默。
    precision_thresholds: dict[str, float] | None = None

    @staticmethod
    def from_dict(d: dict) -> "OperatorSpec":
        attrs: dict[str, "AttrSpec"] = {}

        # Names on the input side — an output that aliases an input by name is an
        # in-place mutation target, hence a genuine tensor even without a shape
        # (its shape mirrors the aliased input). Precomputed so ``_route`` can
        # consult it for the ``outputs`` pass.
        _input_names = {
            e.get("name") for e in d.get("inputs", [])
            if isinstance(e, dict) and e.get("name")
        }

        def _route(entries: list, group: str) -> list["TensorSpec"]:
            """Split a raw input/output list into real tensors vs. attrs by
            **business semantics**, not by a mechanism proxy (§1.10).

            The old判据 was "no ``shape`` key ⇒ attr". That mechanism feature is
            shared by two semantically OPPOSITE kinds of entry — a genuine scalar
            attr (epsilon) AND a shapeless-but-real tensor (a ``DYNAMIC``
            ``Tensor[]`` variadic input, or an in-place alias output whose shape
            is carried by ``shape_formula``). So it silently mis-routed real
            tensors into attrs, emptying ``op_spec.inputs`` and breaking every
            downstream consumer that maps test-case inputs to it by position
            (the precision harness's DYNAMIC check, cannbench schema alignment).

            The judature now reads what the entry **declares about itself**, in
            precedence order:
              1. an explicit ``role`` wins — the author's stated intent
                 (``attr`` → attr, ``tensor`` → tensor). Agents rarely emit it,
                 so it can't be the ONLY signal, but when present it is decisive.
              2. ``param_type`` (REQUIRED/OPTIONAL/DYNAMIC) is a tensor-only
                 concept ⇒ tensor — a ``DYNAMIC`` variadic keeps its place even
                 with no shape.
              3. an output that aliases an input by name ⇒ in-place tensor
                 (its shape mirrors the aliased input; carried as
                 ``shape_formula``).
              4. a real shape signal (``shape`` / ``shape_formula`` /
                 ``shape_constraints``) ⇒ tensor.
              5. a scalar ``type`` (int/float/str/bool), or a scalar-ish
                 ``dtype`` with NO shape, ⇒ attr (the epsilon/axis-listed-under-
                 inputs case the old code was really written for).
              6. anything left undecidable ⇒ kept as a tensor + a loud warning
                 (§1.3: surface the ambiguity, never silently drop a possible
                 tensor).

            Why this replaces "no ``shape`` ⇒ attr" (§1.10): that mechanism
            feature is shared by two semantically OPPOSITE kinds — a genuine
            scalar attr (epsilon) AND a shapeless-but-real tensor (a ``DYNAMIC``
            ``Tensor[]`` variadic, or an in-place alias output). The old proxy
            silently mis-routed the latter into attrs, emptying ``op_spec.inputs``
            and breaking every consumer that maps test-case inputs to it by
            position (the precision harness DYNAMIC check, cannbench alignment).
            """
            tensors: list[TensorSpec] = []
            for e in entries:
                name = e.get("name", "")
                # §2.5 single pathway: classify via the shared is_scalar_entry
                # predicate (business-semantics precedence, §1.10) — not inlined.
                is_attr = is_scalar_entry(e, group=group, input_names=_input_names)
                if is_attr:
                    attrs[name] = AttrSpec(
                        name=name,
                        type=e.get("type") or e.get("dtype", ""),
                        default=e.get("default"),
                        description=e.get("note", "") or e.get("description", ""),
                    )
                else:
                    tensors.append(TensorSpec.from_dict(e))
            return tensors

        inputs = _route(d.get("inputs", []), "inputs")
        outputs = _route(d.get("outputs", []), "outputs")

        # ``attrs`` may arrive as a dict ({name: {...}}) or — because LLM output
        # tends to mirror the list-of-objects style of inputs/outputs — as a
        # list ([{name, ...}]). Normalize both to (key, value) pairs so a list
        # form no longer crashes with "'list' object has no attribute 'items'".
        # None (proto ``attrs:`` 空键 → YAML None，weight_quant_batch_matmul 真实
        # 场景) 视为无 attrs。
        raw_attrs = d.get("attrs", {}) or {}
        if isinstance(raw_attrs, list):
            attr_items = [(e.get("name", ""), e) for e in raw_attrs]
        else:
            attr_items = list(raw_attrs.items())
        for k, v in attr_items:
            if isinstance(v, dict):
                # Bridge common LLM key aliases to AttrSpec field names before
                # filtering, so the dtype/description carried by list-style
                # entries (dtype/desc) survives instead of being dropped.
                v = dict(v)
                if "type" not in v and "dtype" in v:
                    v["type"] = v["dtype"]
                if "description" not in v and "desc" in v:
                    v["description"] = v["desc"]
                attrs[k] = AttrSpec(name=k, **{
                    fk: fv for fk, fv in filter_known_fields(AttrSpec, v).items()
                    if fk != "name"
                })
            else:
                attrs[k] = v
        return OperatorSpec(
            name=d["name"],
            inputs=inputs,
            outputs=outputs,
            attrs=attrs,
            precision_thresholds=coerce_precision_thresholds(
                d.get("precision_thresholds")
            ),
        )


@dataclass(frozen=True)
class OperatorIdentity:
    spec: OperatorSpec
    repo_root: Path
    op_dir: Path
    files: dict[str, Path] = field(default_factory=dict)
    # e.g. {"tiling_h": Path(".../gelu_tiling.h"), "kernel_cpp": Path(".../gelu.cpp")}
