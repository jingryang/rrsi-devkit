"""convert_to_param_def adapter guard tests.

Covers the historical incident failure mode: the adapter read a never-existing
nested ``op_spec`` block, silently dropped all declared tensors, and wrote a
residual ``03_参数定义.yaml`` without any error. Also guards the follow-up
contracts: aclnn_name is user-provided (verbatim copy, raise on missing) and
value_range is declaration-first (verbatim copy, dtype-table fallback).

All fixtures are operator-agnostic inline structures (§1.12 — fixtures may
use concrete samples but the code path must not branch on operator names).
The ``full_structure`` fixture (conftest.py, shared with the verify-side
calibration) mirrors the structural shape of a historical incident run's
real product (8 tensors + 2 scalar attrs + domain nesting, identifiers
genericized) — the multi-tensor scale no small synthetic case reaches.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from ascendc_devkit.adapters.testdesign.convert_to_param_def import convert


def _flat_req(**extra) -> dict:
    """Flat-form requirement.json (DevKit requirement stage output shape)."""
    req = {
        "op_name": "sample_op",
        "aclnn_name": "aclnnSampleOp",
        "mutation_mode": "out_of_place",
        "inputs": [
            {"name": "x", "dtype": ["float16", "float32"], "shape": ["N"]},
            {"name": "idx", "dtype": "int32", "shape": ["N"]},
        ],
        "outputs": [
            {"name": "y", "dtype": "float32"},
        ],
        "attrs": [
            {"name": "mode", "type": "int", "default": 0},
        ],
        "golden_alignment": {"status": "pass", "differences": [], "notes": ""},
    }
    req.update(extra)
    return req


def _write(base: Path, req: dict, ds: dict | None = None) -> None:
    (base / "requirement.json").write_text(
        json.dumps(req, ensure_ascii=False), encoding="utf-8")
    (base / "design_spec.json").write_text(
        json.dumps(ds if ds is not None else {}, ensure_ascii=False),
        encoding="utf-8")


def _run(tmp_path: Path) -> str:
    return convert("requirement.json", "design_spec.json",
                   "design/03_参数定义.yaml", base_dir=tmp_path)


def _load(out_path: str) -> dict:
    return yaml.safe_load(Path(out_path).read_text(encoding="utf-8"))


def _tensors(data: dict) -> list[dict]:
    return [p for p in data["parameters"] if p.get("type") == "aclTensor"]


# ── P1 regression: flat / nested forms must keep every declared tensor ─────


def test_flat_requirement_all_tensors(tmp_path):
    """历史事故回归：平铺形态下声明张量一个不丢（事故形态：8 全丢只活 2 标量）。"""
    _write(tmp_path, _flat_req())
    data = _load(_run(tmp_path))
    assert len(_tensors(data)) == 3  # 2 inputs + 1 output（标量不计入张量）
    assert len(data["parameters"]) == 4  # 3 张量 + 1 标量 attr


def test_nested_requirement_all_tensors(tmp_path):
    """嵌套 op 形态（用户原始模板 / proto 包装）同样不丢。"""
    req = {
        "aclnn_name": "aclnnSampleOp",
        "op": {
            "name": "sample_op",
            "inputs": [{"name": "x", "dtype": "float32", "shape": ["N"]}],
            "outputs": [{"name": "y", "dtype": "float32"}],
        },
    }
    _write(tmp_path, req)
    data = _load(_run(tmp_path))
    assert len(_tensors(data)) == 2


# ── assertions: incomplete products raise BEFORE writing to disk ───────────


def test_empty_sources_raises(tmp_path):
    """三源皆空 → 校验 1（参数定义为空）。"""
    _write(tmp_path, {"aclnn_name": "aclnnSampleOp"})
    with pytest.raises(ValueError, match="参数定义为空"):
        _run(tmp_path)


def test_tensor_count_mismatch_raises(tmp_path):
    """结构不匹配（声明 2 张量、产出 0）→ 校验 2。"""
    req = {"op_name": "sample_op", "aclnn_name": "aclnnSampleOp",
           "attrs": [{"name": "mode", "type": "int", "default": 0}]}
    ds = {"inputs": [{"name": "x", "dtype": "float32"}],
          "outputs": [{"name": "y", "dtype": "float32"}]}
    _write(tmp_path, req, ds)
    with pytest.raises(ValueError, match="参数定义不完整"):
        _run(tmp_path)


def test_no_yaml_on_failure(tmp_path):
    """断言失败时残缺产物不落盘（写盘前 raise）。"""
    req = {"op_name": "sample_op", "aclnn_name": "aclnnSampleOp",
           "attrs": [{"name": "mode", "type": "int", "default": 0}]}
    ds = {"inputs": [{"name": "x", "dtype": "float32"}],
          "outputs": [{"name": "y", "dtype": "float32"}]}
    _write(tmp_path, req, ds)
    with pytest.raises(ValueError):
        _run(tmp_path)
    assert not (tmp_path / "design" / "03_参数定义.yaml").exists()


# ── aclnn_name: user-provided, verbatim copy, raise on missing ─────────────


def test_aclnn_name_from_input(tmp_path):
    """req 提供 aclnn_name → 03 逐字照抄（无拼接）。"""
    _write(tmp_path, _flat_req(aclnn_name="aclnnExactName"))
    data = _load(_run(tmp_path))
    assert data["aclnn_name"] == "aclnnExactName"


def test_aclnn_name_missing_raises(tmp_path):
    """req 缺 aclnn_name → raise（不静默拼接错误接口名）。"""
    req = _flat_req()
    del req["aclnn_name"]
    _write(tmp_path, req)
    with pytest.raises(ValueError, match="aclnn_name"):
        _run(tmp_path)


# ── _is_scalar_attr: dtype key on user-template scalars ────────────────────


def test_scalar_dtype_key(tmp_path):
    """用户模板标量用 dtype 键 → 不误判为张量。"""
    req = {"op_name": "sample_op", "aclnn_name": "aclnnSampleOp",
           "inputs": [{"name": "x", "dtype": "float32", "shape": ["N"]}],
           "outputs": [],
           "attrs": [{"name": "vocab_start", "dtype": "int32"}]}
    _write(tmp_path, req)
    data = _load(_run(tmp_path))
    by_name = {p["name"]: p for p in data["parameters"]}
    assert by_name["vocab_start"]["type"] != "aclTensor"


# ── value_range: declaration-first (verbatim) with dtype-table fallback ────


def test_upstream_value_range_verbatim(tmp_path):
    """上游声明了 → 逐字照抄（不并、不加）。"""
    declared = [[0, 0], [1, 16], [16, 100]]
    req = _flat_req()
    req["inputs"][0]["value_range"] = declared
    _write(tmp_path, req)
    data = _load(_run(tmp_path))
    x = next(p for p in data["parameters"] if p["name"] == "x")
    for de in x["dtype_with_ranges"]:
        ranges = {tuple(r) for r in de["value_range"]}
        for r in declared:
            assert tuple(r) in ranges
        assert (-1, 1) not in ranges  # 通用表区间不得混入


def test_no_upstream_value_range_fallback(tmp_path):
    """上游没声明 → 适配器 dtype 通用表兜底（现状行为不变）。"""
    _write(tmp_path, _flat_req())
    data = _load(_run(tmp_path))
    x = next(p for p in data["parameters"] if p["name"] == "x")
    f16 = next(de for de in x["dtype_with_ranges"]
               if de["dtype"] == "float16")
    assert ["inf", "inf"] in f16["value_range"]  # float16 通用表含极端值条目


def test_scalar_declared_range_verbatim(tmp_path):
    """标量（非枚举分支）声明照抄。"""
    req = _flat_req()
    req["attrs"][0]["value_range"] = [[0, 5]]
    _write(tmp_path, req)
    data = _load(_run(tmp_path))
    mode = next(p for p in data["parameters"] if p["name"] == "mode")
    assert mode["dtype_with_values"][0]["value_range"] == [[0, 5]]


def test_output_no_value_range(tmp_path):
    """输出张量不携带 value_range（现状守护——即使误给也不写入）。"""
    req = _flat_req()
    req["outputs"][0]["value_range"] = [[9, 9]]
    _write(tmp_path, req)
    data = _load(_run(tmp_path))
    y = next(p for p in data["parameters"] if p["name"] == "y")
    assert all("value_range" not in de for de in y["dtype_with_ranges"])


# ── real-artifact calibration (key check: no false-negative, no regression) ─


def test_full_structure_regression(tmp_path, full_structure):
    """完整结构标定：8 张量 + 2 标量 → 10 参数一个不丢，aclnn_name 照抄
    （历史事故形态：同规模输入曾整批丢张量只剩 2 标量）。

    结构由 `conftest.full_structure` fixture 提供（与对质标定共用同一份）。"""
    req, ds = full_structure
    _write(tmp_path, req, ds)
    data = _load(_run(tmp_path))
    tensors = _tensors(data)
    scalars = [p for p in data["parameters"] if p.get("type") != "aclTensor"]
    assert len(tensors) == 8
    assert len(scalars) == 2
    assert data["aclnn_name"] == req["aclnn_name"]


# ── dimensions：必须由该张量自己的 rank 域派生（不得用占位符个数）──────────


def _dims(tmp_path: Path) -> dict:
    data = _load(_run(tmp_path))
    return {p["name"]: p.get("dimensions") for p in _tensors(data)}


_SYMBOLIC_REQ = {
    "op_name": "sample_reduce_norm",
    "aclnn_name": "aclnnSampleReduceNorm",
    "mutation_mode": "out_of_place",
    "inputs": [
        # 6 个占位符（含省略号），真实 rank 由约束给出 [2,8]
        {"name": "main", "dtype": ["float16"],
         "shape": ["N_0", "...", "N_{m-1}", "D_0", "...", "D_{k-1}"],
         "shape_constraints": "rank(main) = m + k ∈ [2, 8]；所有维度 > 0"},
        # 同为符号 shape；与 main 完全同形 → 结构化别名继承 [2,8]
        {"name": "residual", "dtype": ["float16"],
         "shape": ["N_0", "...", "N_{m-1}", "D_0", "...", "D_{k-1}"]},
        # 3 个占位符，真实 rank 是其自己的 [1,7]
        {"name": "scale", "dtype": ["float16"], "shape": ["D_0", "...", "D_{k-1}"],
         "shape_constraints": "rank(scale) ∈ [1, 7] 且严格小于 rank(main)"},
        # 固定 1 维（句中不含张量名）
        {"name": "bias", "dtype": ["float16"], "shape": ["C"],
         "shape_constraints": "1 维，numel == C"},
        # 结构化备选形状
        {"name": "pool_idx", "dtype": ["int32"], "shape": ["N", "C", "D", "H", "W"],
         "shape_variants": [["N", "C", "D", "H", "W"], ["C", "D", "H", "W"]]},
        # 通配、无任何证据
        {"name": "wild", "dtype": ["float16"], "shape": ["*"]},
    ],
    "outputs": [{"name": "out", "dtype": ["float16"], "shape": ["N", "C", "D"]}],
}


def test_dimensions_from_prose_rank_range(tmp_path):
    """符号 shape 的占位符个数不得当 rank：按该张量自己的 rank 域生成。"""
    _write(tmp_path, _SYMBOLIC_REQ)
    dims = _dims(tmp_path)
    assert dims["main"] == [2, 3, 4, 5, 6, 7, 8]
    assert dims["scale"] == [1, 2, 3, 4, 5, 6, 7]


def test_dimensions_from_fixed_rank_phrase(tmp_path):
    _write(tmp_path, _SYMBOLIC_REQ)
    assert _dims(tmp_path)["bias"] == [1]


def test_dimensions_from_shape_variants(tmp_path):
    _write(tmp_path, _SYMBOLIC_REQ)
    assert _dims(tmp_path)["pool_idx"] == [4, 5]


def test_dimensions_inherit_identical_symbolic_shape(tmp_path):
    _write(tmp_path, _SYMBOLIC_REQ)
    assert _dims(tmp_path)["residual"] == [2, 3, 4, 5, 6, 7, 8]


def test_dimensions_unknown_rank_falls_back_to_generic_band(tmp_path):
    """无证据 → 通用 [1..8]（skill 文档约定），不得伪造占位符个数。"""
    _write(tmp_path, _SYMBOLIC_REQ)
    assert _dims(tmp_path)["wild"] == [1, 2, 3, 4, 5, 6, 7, 8]


def test_dimensions_concrete_shape_exact(tmp_path):
    _write(tmp_path, _SYMBOLIC_REQ)
    assert _dims(tmp_path)["out"] == [3]


def test_dimensions_structured_domain_rank_wins(tmp_path):
    """domain.inputs[].rank 结构化声明优先于措辞。"""
    req = {
        "op_name": "sample_op", "aclnn_name": "aclnnSampleOp",
        "inputs": [{"name": "main", "dtype": ["float16"], "shape": ["A", "..."],
                    "shape_constraints": "rank(main) ∈ [2, 8]"}],
        "outputs": [{"name": "out", "dtype": ["float16"], "shape": ["A", "B"]}],
        "domain": {"inputs": [{"name": "main", "dtypes": ["float16"],
                               "rank": {"min": 3, "max": 6}}]},
    }
    _write(tmp_path, req)
    assert _dims(tmp_path)["main"] == [3, 4, 5, 6]
