"""L4 Domain — Requirement types (parsed specification DSL)."""

from dataclasses import dataclass, field
from pathlib import Path
from .operator import (
    OperatorSpec, OperatorIdentity, filter_known_fields, coerce_precision_thresholds,
)


@dataclass(frozen=True)
class Constraint:
    kind: str                      # "precision" | "performance" | "hardware"
    threshold: float | None = None  # precision threshold or perf upper bound (ms)
    comparison: str | None = None   # "abs_diff" | "cosine" | "relative"
    baseline_ms: float | None = None  # performance baseline
    shapes: list[list[int]] | None = None  # perf test shapes


@dataclass(frozen=True)
class TestCase:
    __test__ = False  # Prevent pytest from collecting this as a test class
    name: str
    inputs: list[dict] = field(default_factory=list)
    # [{"name": "input", "shape": [N], "data": [...]}, ...]
    expected: dict | None = None   # {"max_diff": 1e-5}
    generator: str | None = None   # "random_uniform" | "arange"
    generator_params: dict | None = None  # {"seed": 42, "low": -1.0, "high": 1.0}
    # Cann-bench case identifier (e.g. "level2/dynamic_quant_1"). Used for
    # deterministic seed computation matching cann-bench eval's format.
    case_id: str = ""
    # Operator attribute values bound to this case, e.g.
    # {"base": -1.0, "scale": 1.5, "shift": 0.0}. P8: carrying attrs at the
    # case level aligns the test-case model with OperatorSpec.attrs so kernels
    # and goldens can be exercised on non-default branches (see A2 — the
    # harness forwards attrs as kwargs). Empty by default so attr-less
    # operators regress to pure positional calls.
    attrs: dict = field(default_factory=dict)
    # Provenance of the case: "cannbench" (external cann-bench cases.csv) or
    # "devkit" (LLM test_design / st-design generated CSV). Set once at the
    # producing loader so downstream consumers (precision baseline reporting the
    # st-design subset separately from the cann-bench originals) read a
    # structural signal instead of guessing from names (§1.12). Empty string =
    # unknown/legacy (e.g. a hand-written requirement file that predates this).
    source: str = ""


@dataclass(frozen=True)
class UnclearItem:
    question: str
    context: str = ""
    resolution: str | None = None  # None = pending clarification
    severity: str = "choice"
    # ^ "blocking" = requirement is fundamentally underspecified (missing
    #   inputs/outputs, undeterminable op semantics). Non-interactive mode must
    #   error out rather than guess.
    #   "choice" = a route selection (e.g. half vs interleave, default dtype).
    #   Non-interactive mode may auto-pick a default and record it as the
    #   resolution. Default is the conservative "choice" so an unlabeled item
    #   never hard-blocks the pipeline.


@dataclass(frozen=True)
class Requirement:
    op_spec: OperatorSpec
    design_doc_path: Path | None = None
    constraints: list[Constraint] = field(default_factory=list)
    test_cases: list[TestCase] = field(default_factory=list)
    reference_op: OperatorIdentity | None = None
    unclear_items: list[UnclearItem] = field(default_factory=list)

    @staticmethod
    def from_file(path: Path) -> "Requirement":
        """Parse a machine-readable requirement file into a Requirement.

        Supports JSON (.json) and YAML (.yaml/.yml) by extension; an unknown
        extension is probed as JSON first, then YAML. This path deserializes
        directly into test_cases/constraints with no agent, so prose formats
        (.md/.txt) are not accepted here — use the full workflow's
        ``--requirement`` for those, where the agent interprets free text.
        """
        import json
        text = path.read_text()
        suffix = path.suffix.lower()

        if suffix in (".yaml", ".yml"):
            import yaml
            data = yaml.safe_load(text)
        elif suffix == ".json":
            data = json.loads(text)
        else:
            # Unknown extension: try JSON, fall back to YAML.
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                import yaml
                data = yaml.safe_load(text)

        if not isinstance(data, dict):
            raise ValueError(
                f"Requirement file '{path}' must contain a mapping at the top "
                f"level, got {type(data).__name__}."
            )
        return Requirement.from_dict(data)

    @staticmethod
    def from_dict(d: dict) -> "Requirement":
        # Accept devkit requirement.json (top-level ``op:``) and cann-bench
        # proto.yaml (top-level ``operator:`` block). proto's operator block also
        # carries ``precision_thresholds`` (P69 single source of precision
        # tolerance); OperatorSpec.from_dict reads it directly.
        op_block = d.get("op") if "op" in d else d.get("operator")
        if op_block is None:
            op_block = {"name": "unknown"}
        op_spec = OperatorSpec.from_dict(op_block)
        constraints = [Constraint(**filter_known_fields(Constraint, c))
                       for c in d.get("constraints", [])]
        test_cases = [TestCase(**filter_known_fields(TestCase, tc))
                      for tc in d.get("test_cases", [])]
        unclear = [UnclearItem(**filter_known_fields(UnclearItem, u))
                   for u in d.get("unclear_items", [])]
        return Requirement(
            op_spec=op_spec,
            constraints=constraints,
            test_cases=test_cases,
            unclear_items=unclear,
        )


def read_proto_precision(proto_path: Path | str | None) -> tuple[dict[str, float] | None, list[bool | None], list[dict | None]]:
    """Read ``precision_thresholds`` + per-output ``compare``/``index_gather``
    from a cann-bench proto file (yaml/json).

    proto.yaml is the single source of precision tolerance (P69). The
    requirement agent's output drops it (schema is op_name/inputs/outputs only),
    so callers deterministically re-read the proto to recover it.

    Returns ``(thresholds, output_compares, output_index_gathers)``:
      - ``thresholds``: coerced ``{dtype: float}`` or ``None`` if undeclared.
      - ``output_compares[i]``: the i-th output's ``compare`` flag (``None`` if
        unset → compare normally). Empty if no outputs declared.
      - ``output_index_gathers[i]``: the i-th output's ``index_gather`` dict
        (``{"input", "dim_attr", "value_output"}``, TopK idx 输出) or ``None``.

    Graceful: ``None``/missing/unreadable/non-mapping path → ``(None, [], [])``;
    never raises (called from stage transitions, §1.3 加载期校验 but degrade
    rather than abort on a malformed proto).
    """
    if proto_path is None:
        return None, [], []
    path = Path(proto_path)
    if not path.exists():
        return None, [], []
    import json
    import yaml
    try:
        text = path.read_text()
        suffix = path.suffix.lower()
        if suffix in (".yaml", ".yml"):
            data = yaml.safe_load(text)
        elif suffix == ".json":
            data = json.loads(text)
        else:
            try:
                data = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                data = yaml.safe_load(text)
    except (OSError, ValueError, yaml.YAMLError):
        return None, [], []
    if not isinstance(data, dict):
        return None, [], []
    # proto.yaml nests under top-level ``operator:``; a flat mapping (devkit
    # requirement.json ``op:`` already consumed by from_dict) is also accepted.
    op_block = data.get("operator")
    if not isinstance(op_block, dict):
        op_block = data
    pt = coerce_precision_thresholds(op_block.get("precision_thresholds"))
    compares: list[bool | None] = []
    index_gathers: list[dict | None] = []
    outs = op_block.get("outputs")
    if isinstance(outs, list):
        for out_def in outs:
            if isinstance(out_def, dict):
                c = out_def.get("compare")
                compares.append(bool(c) if c is not None else None)
                ig = out_def.get("index_gather")
                if ig is not None and not isinstance(ig, dict):
                    # §1.3 加载期暴露配置问题：index_gather 类型错误静默置 None
                    # 会让 idx 校验无声消失（退回逐元素比较/"乱填索引也过"缺口
                    # 重现）——warn 留痕，不静默吞（§1.2 可诊断）。
                    import warnings
                    warnings.warn(
                        f"proto output index_gather 类型错误（期望 dict，实际 "
                        f"{type(ig).__name__}），已忽略——idx 校验不会生效")
                    ig = None
                index_gathers.append(ig)
            else:
                compares.append(None)
                index_gathers.append(None)
    return pt, compares, index_gathers


def read_proto_schema(proto_path: Path | str | None) -> str | None:
    """Read the authoritative ``schema:`` field from a cann-bench proto file.

    proto.yaml ``operator.schema`` 是 plugin 注册 schema + cann-bench eval harness
    调用契约的**共同权威**（54/54 proto.yaml 均声明）。该字符串与 ``m.def`` schema 同构
    （如 ``gather(Tensor x, Tensor index, int dim=0) -> Tensor y``），下游
    ``parse_mdef_params`` / ``parse_mdef_param_types`` 直接 parse，无需 agent 重新表达。

    codegen 生成的 op_plugin m.def schema **必须等于** proto.yaml schema（type+name+order）；
    套 torch 标准签名（如 ``gather(Tensor input, int dim, Tensor index)``）是接口对齐 bug ——
    proto.yaml 才是权威，不是 codegen 产出的 codegen_manifest（二手）。

    Graceful: ``None``/missing/unreadable/non-mapping/无 schema → ``None``（调用方 fallback
    op_spec；§1.3 加载期校验但畸形/缺 schema 的 proto 不阻断）。
    """
    if proto_path is None:
        return None
    path = Path(proto_path)
    if not path.exists():
        return None
    import json
    import yaml
    try:
        text = path.read_text()
        suffix = path.suffix.lower()
        if suffix in (".yaml", ".yml"):
            data = yaml.safe_load(text)
        elif suffix == ".json":
            data = json.loads(text)
        else:
            try:
                data = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                data = yaml.safe_load(text)
    except (OSError, ValueError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None
    op_block = data.get("operator")
    if not isinstance(op_block, dict):
        op_block = data
    schema = op_block.get("schema")
    if isinstance(schema, str) and schema.strip():
        return schema.strip()
    return None


def read_proto_tensorlist_inputs(
    proto_path: Path | str | None,
) -> list[str]:
    """Read authoritative TensorList (variadic tensor list) input names from a
    cann-bench proto file.

    A CANN TensorList input (``Tensor[] x``) is a variadic — its only coherent
    ``param_type`` is DYNAMIC. The proto declares the list-ness via **two
    structural signals** (§1.12 — never operator identity):
      1. ``operator.inputs[].is_list: true`` — explicit field (proto.yaml 常显式
         声明，如 ``is_list: true``).
      2. ``operator.schema`` signature — ``Tensor[] <name>`` 参数（如
         ``foreach_norm(Tensor[] x, float scalar) -> Tensor[] y``），按位置有序。

    Requirement 阶段据此确定性派生 ``is_list`` → ``param_type=DYNAMIC``
    （TensorList 在 CANN 必须 DYNAMIC），修 requirement 把 Tensor[] 误标
    REQUIRED/OPTIONAL 的源头缺陷。proto 是权威（§1.13 接口契约），不是 agent 手写
    requirement.json 的二手表达。

    Returns the sorted list of input names that are TensorList (deduplicated);
    ``[]`` on any absence/unreadable/non-mapping proto (Graceful, §1.3 加载期校验
    but never aborts).

    注：schema 签名解析是**内联轻量实现**（正则 ``Tensor[] <name>``），不依赖
    ``parse_mdef_param_types``（该函数在不同分支/版本存在性不一）——保持本函数
    跨分支一致可用（§1.12 结构信号驱动）。
    """
    if proto_path is None:
        return []
    path = Path(proto_path)
    if not path.exists():
        return []
    import json
    import re
    import yaml
    try:
        text = path.read_text()
        suffix = path.suffix.lower()
        if suffix in (".yaml", ".yml"):
            data = yaml.safe_load(text)
        elif suffix == ".json":
            data = json.loads(text)
        else:
            try:
                data = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                data = yaml.safe_load(text)
    except (OSError, ValueError, yaml.YAMLError):
        return []
    if not isinstance(data, dict):
        return []
    op_block = data.get("operator")
    if not isinstance(op_block, dict):
        op_block = data

    names: set[str] = set()
    # Signal 1: explicit ``is_list: true`` on the input entry.
    for inp in (op_block.get("inputs") or []):
        if isinstance(inp, dict) and inp.get("is_list") is True:
            name = inp.get("name")
            if isinstance(name, str) and name:
                names.add(name)
    # Signal 2: ``Tensor[] <name>`` in the authoritative schema signature
    # (parameter list only — everything between the first "(" and its ")").
    schema = op_block.get("schema")
    if isinstance(schema, str) and schema.strip():
        lp = schema.find("(")
        if lp >= 0:
            rp = schema.find(")", lp)
            if rp > lp:
                body = schema[lp + 1:rp]
                for m in re.finditer(r"Tensor\[\]\s+(\w+)", body):
                    names.add(m.group(1))
    return sorted(names)
