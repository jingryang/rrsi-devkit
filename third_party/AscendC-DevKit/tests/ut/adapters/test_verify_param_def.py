"""verify_param_def (03 ↔ 上游 JSON 对质) guard tests.

Guards the cross-check used at two trigger points in the test-design stage
(E-1 before spawn / E-3 at transition). Cases 1-3 assert each dimension
fires; case 4 is the key calibration (a full 8-tensor structure passes —
no false positives); case 5 guards the dtype-alias normalisation (upstream
may write fp16 while 03 carries the canonical float16); case 6 exercises
the working-dir entry used by the stage on a corrupted 03 (the E-3
mechanism: violations carry the cause).
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from ascendc_devkit.adapters.testdesign.convert_to_param_def import convert
from ascendc_devkit.adapters.testdesign.verify_param_def import (
    verify,
    verify_from_dir,
)


def _req() -> dict:
    return {
        "op_name": "sample_op",
        "aclnn_name": "aclnnSampleOp",
        "inputs": [{"name": "x", "dtype": "float16", "shape": ["N"],
                    "rank": {"min": 1, "max": 4}}],
        "outputs": [{"name": "y", "dtype": "float16"}],
        "domain": {"inputs": [{"name": "x", "dtypes": ["float16", "float32"]}]},
    }


def _yaml_data(params: list[dict]) -> dict:
    return {"aclnn_name": "aclnnSampleOp", "parameters": params}


def _tensor(dtype: str = "float16", dims: list | None = None) -> dict:
    return {"name": "x", "type": "aclTensor", "io_type": "input",
            "dimensions": dims or [1], "dtype_with_ranges": [{"dtype": dtype}]}


# ── dimension ① tensor manifest ────────────────────────────────────────────


def test_missing_tensor_reported():
    errs = verify(_req(), {}, _yaml_data([]))
    assert any("03 缺参数" in e and "x" in e for e in errs)


# ── dimension ② dtype domain ───────────────────────────────────────────────


def test_dtype_out_of_domain_reported():
    errs = verify(_req(), {}, _yaml_data([_tensor(dtype="int32")]))
    assert any("dtype 越界" in e for e in errs)


# ── dimension ③ rank bounds ────────────────────────────────────────────────


def test_rank_out_of_domain_reported():
    errs = verify(_req(), {}, _yaml_data([_tensor(dims=[1, 9])]))
    assert any("rank 越界" in e for e in errs)


# ── key calibration: real successful artifacts must pass ───────────────────


def test_full_structure_pass(tmp_path, full_structure):
    """完整结构标定：8 张量 + 2 标量经适配器生成 03 后对质放行——无误报。

    结构由 `conftest.full_structure` fixture 提供（与 convert 标定共用同一份）。"""
    req, ds = full_structure
    (tmp_path / "requirement.json").write_text(
        json.dumps(req, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "design_spec.json").write_text(
        json.dumps(ds, ensure_ascii=False), encoding="utf-8")
    convert("requirement.json", "design_spec.json",
            "design/03_参数定义.yaml", base_dir=tmp_path)
    assert verify_from_dir(tmp_path) == []


# ── dtype-alias normalisation guard ────────────────────────────────────────


def test_dtype_alias_no_false_positive():
    """上游声明别名（fp16）/ 03 产出规范名（float16）→ 不得误报缺参数。"""
    req = _req()
    req["inputs"][0]["dtype"] = "fp16"
    params = [
        _tensor(dtype="float16"),
        {"name": "y", "type": "aclTensor", "io_type": "output",
         "dimensions": [1], "dtype_with_ranges": [{"dtype": "float16"}]},
    ]
    errs = verify(req, {}, _yaml_data(params))
    assert errs == []


# ── E-1/E-3 mechanism via the working-dir entry (corrupted 03) ─────────────


def test_corrupted_03_in_wd_reported_with_cause(tmp_path):
    """E-3 机制：stage 工作目录里 03 被改坏（删一个张量）→ 违规带病因。

    合成 fixture 版（机制用例不依赖完整结构——完整结构的标定守护由
    `test_full_structure_pass` 承担）：就地构造小型 requirement → 适配器产 03
    → 模拟 agent 漂移删掉一个张量 → `verify_from_dir` 报缺参且带参数名，
    而非只报下游症状（历史事故 4 轮重试均只见 "no merged test-case CSV"）。
    """
    req = {
        "op_name": "sample_op",
        "aclnn_name": "aclnnSampleOp",
        "mutation_mode": "out_of_place",
        "inputs": [
            {"name": "x", "dtype": "float16", "shape": ["N"]},
            {"name": "idx", "dtype": "int32", "shape": ["N"]},
        ],
        "outputs": [{"name": "y", "dtype": "float16"}],
        "domain": {"inputs": [{"name": "x", "dtypes": ["float16", "float32"]}]},
    }
    (tmp_path / "requirement.json").write_text(
        json.dumps(req, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "design_spec.json").write_text("{}", encoding="utf-8")
    convert("requirement.json", "design_spec.json",
            "design/03_参数定义.yaml", base_dir=tmp_path)

    # agent 漂移场景：删掉 03 里的 idx 张量（确定性 victim，按名选取）
    pd_path = tmp_path / "design" / "03_参数定义.yaml"
    data = yaml.safe_load(pd_path.read_text(encoding="utf-8"))
    victim = "idx"
    assert any(p.get("name") == victim for p in data["parameters"])
    data["parameters"] = [p for p in data["parameters"]
                          if p.get("name") != victim]
    pd_path.write_text(yaml.safe_dump(data, allow_unicode=True),
                       encoding="utf-8")

    violations = verify_from_dir(tmp_path)
    assert violations, "corrupted 03 must be reported"
    assert any("03 缺参数" in v and victim in v for v in violations)


# ── dimension ③ 的 per-tensor 语义 ─────────────────────────────────────────
#
# `domain.rank` 语义上是**主输入**的域（见 requirement.json 的 domain.notes）；
# 用它审判所有输入张量会把合法的低秩参数（如 1 维缩放/偏置）判死，并诱导
# 修复者写出语义错误的值来绕过门。门的判据必须是「每个张量各自的合法 rank 域」。


def _per_tensor_req() -> dict:
    return {
        "op_name": "sample_reduce_norm",
        "aclnn_name": "aclnnSampleReduceNorm",
        "inputs": [
            {"name": "main", "dtype": "float16", "shape": ["N_0", "...", "D_0", "..."],
             "rank": {"min": 2, "max": 8}},
            {"name": "scale", "dtype": "float16", "shape": ["D_0", "..."],
             "rank": {"min": 1, "max": 7}},
            {"name": "bias", "dtype": "float16", "shape": ["C"],
             "rank": {"min": 1, "max": 1}},
            {"name": "wild", "dtype": "float16", "shape": ["*"]},
        ],
        "outputs": [{"name": "out", "dtype": "float16", "shape": ["N"]}],
        "domain": {"inputs": [{"name": "main", "dtypes": ["float16"]},
                              {"name": "scale", "dtypes": ["float16"]},
                              {"name": "bias", "dtypes": ["float16"]},
                              {"name": "wild", "dtypes": ["float16"]}]},
    }


def _t(name: str, dims: list) -> dict:
    return {"name": name, "type": "aclTensor", "io_type": "input",
            "dimensions": dims, "dtype_with_ranges": [{"dtype": "float16"}]}


def _params(**overrides) -> list[dict]:
    """_per_tensor_req 的完整 03 参数集（含输出），按名覆盖 dimensions。"""
    dims = {"main": [2, 3, 4, 5, 6, 7, 8],
            "scale": [1, 2, 3, 4, 5, 6, 7],
            "bias": [1],
            "wild": [1]}
    dims.update(overrides)
    out = [_t(name, d) for name, d in dims.items()]
    out.append({"name": "out", "type": "aclTensor", "io_type": "output",
                "dimensions": [1], "dtype_with_ranges": [{"dtype": "float16"}]})
    return out


def test_rank_low_rank_params_not_flagged_by_main_input_domain():
    """1 维 scale/bias 在自己域内合法——不得被 main 的 [2,8] 误判。"""
    assert verify(_per_tensor_req(), {}, _yaml_data(_params())) == []


def test_rank_violation_against_own_domain_reported():
    errs = verify(_per_tensor_req(), {}, _yaml_data(_params(main=[1, 9])))
    assert any("rank 越界" in e and "main" in e for e in errs)
    # 违规信息带该张量自己的域（不是 op 级全局域）
    assert any("[2,8]" in e for e in errs)


def test_rank_scale_exceeding_own_domain_reported():
    """scale 写 8（超出自己的 [1,7]）→ 必须被抓住。"""
    errs = verify(_per_tensor_req(), {}, _yaml_data(_params(scale=[8])))
    assert any("rank 越界" in e and "scale" in e for e in errs)
    assert any("[1,7]" in e for e in errs)


def test_rank_unknown_domain_not_fabricated():
    """无 rank 证据的张量 → 跳过（不臆造判据，§2.12）。"""
    assert verify(_per_tensor_req(), {}, _yaml_data(_params(wild=[1, 2, 3]))) == []


def test_rank_output_tensors_still_skipped():
    y = _yaml_data([
        _t("main", [2, 3, 4, 5, 6, 7, 8]),
        _t("scale", [1, 2, 3, 4, 5, 6, 7]),
        _t("bias", [1]),
        _t("wild", [1]),
        {"name": "out", "type": "aclTensor", "io_type": "output",
         "dimensions": [1, 2, 3, 4, 5, 6, 7, 8],
         "dtype_with_ranges": [{"dtype": "float16"}]},
    ])
    assert verify(_per_tensor_req(), {}, y) == []
