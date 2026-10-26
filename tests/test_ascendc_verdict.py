# Copyright 2026 The rrsi Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""ascendc-devkit verdict：兼容 cann-bench 1.x / 2.x 的评分口径。

    python3 -m pytest -q tests/test_ascendc_verdict.py
"""

import json
import sys
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent.parent / "domains/ascendc-devkit/bench"
sys.path.insert(0, str(BENCH_DIR))
try:
    import run_tasks
finally:
    sys.path.remove(str(BENCH_DIR))


def _snapshot(tmp_path: Path, report: dict | None, **eval_result) -> Path:
    """写一份最小 snapshot（可选附带 cann-bench 报告）并返回路径。"""
    eval_result.setdefault("num_cases", 20)
    eval_result.setdefault("pass_rate", 1.0)
    eval_result.setdefault("compile_score", 5.0)
    eval_result.setdefault("function_score", 20.0)
    eval_result.setdefault("performance_score", 0.0)
    if report is not None:
        path = tmp_path / "report.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        eval_result["report_json"] = str(path)
    snap = tmp_path / "state_snapshot.json"
    snap.write_text(
        json.dumps(
            {
                "eval_result": eval_result,
                "generated_sources": ["kernel.cpp"],
                "deploy_result": {"ok": True},
            }
        ),
        encoding="utf-8",
    )
    return snap


def _report(score: float, profile: str = "2", **op_extra) -> dict:
    """单算子报告；score 是 cann-bench 的权威总分。"""
    op = {
        "operator": "SwiGlu",
        "score": score,
        "pass_rate": 1.0,
        "compilation_score": 5.0,
        "compile_runtime_score": 5.0,
        "function_score": 20.0,
        "performance_score": 0.0,
        **op_extra,
    }
    payload = {"operators": [op]}
    if profile:
        payload["score_weight_profile"] = profile
    return payload


def _verdict(snap: Path, **kw) -> dict:
    return run_tasks.verdict_from_snapshot(
        json.loads(snap.read_text()), 1.0, snap, **kw
    )


def test_profile2_full_pass_with_bonus(tmp_path):
    """2.x：30 = 5 + 20 + 5(bonus) + 0，替身分项和不得把有效结果判 0。"""
    v = _verdict(_snapshot(tmp_path, _report(30.0), overall_score=30.0, num_passed=20))
    assert v["status"] == "ok"
    assert v["scores_consistent"] is True
    assert v["score"] == 0.3
    assert v["implied_bonus"] == 5.0
    assert v["score_weight_profile"] == "2"
    assert v["checks"] == []


def test_profile2_partial_pass_has_no_bonus(tmp_path):
    """19/20：报告 24 = 5 + 19 + 0 + 0，隐含 bonus 为 0。"""
    rep = _report(
        24.0, pass_rate=0.95, function_score=19.0
    )
    v = _verdict(
        _snapshot(
            tmp_path,
            rep,
            overall_score=24.0,
            function_score=19.0,
            num_passed=19,
            pass_rate=0.95,
        )
    )
    assert v["status"] == "ok"
    assert v["score"] == 0.24
    assert v["implied_bonus"] == 0.0


def test_profile1_legacy_report(tmp_path):
    """1.x：没有 bonus 和 profile 字段，三项之和就是总分。"""
    rep = {
        "operators": [
            {
                "operator": "SwiGlu",
                "score": 50.0,
                "compilation_score": 20.0,
                "function_score": 30.0,
                "performance_score": 0.0,
            }
        ]
    }
    v = _verdict(
        _snapshot(
            tmp_path,
            rep,
            overall_score=50.0,
            compile_score=20.0,
            function_score=30.0,
        )
    )
    assert v["status"] == "ok"
    assert v["score"] == 0.5
    assert v["implied_bonus"] == 0.0
    assert v["score_weight_profile"] == ""


def test_overall_disagrees_with_report(tmp_path):
    """eval_result 的总分被改写 → 与报告权威分不符，记 0。"""
    v = _verdict(_snapshot(tmp_path, _report(30.0), overall_score=90.0, num_passed=20))
    assert v["status"] == "score_inconsistent"
    assert v["score"] == 0.0
    assert any("report operator score" in c for c in v["checks"])


def test_components_exceed_total(tmp_path):
    """bonus 不可能为负：分项和大于总分即为篡改。"""
    rep = _report(25.0, function_score=30.0)
    v = _verdict(
        _snapshot(
            tmp_path, rep, overall_score=25.0, function_score=30.0, num_passed=20
        )
    )
    assert v["status"] == "score_inconsistent"
    assert v["score"] == 0.0
    assert any("exceeds overall_score" in c for c in v["checks"])


def test_multiple_operator_entries(tmp_path):
    """单算子 trial 的报告里出现 2 个算子 → 不可信。"""
    rep = {"operators": [_report(30.0)["operators"][0]] * 2, "score_weight_profile": "2"}
    v = _verdict(_snapshot(tmp_path, rep, overall_score=30.0, num_passed=20))
    assert v["status"] == "score_inconsistent"
    assert v["score"] == 0.0
    assert any("2 operator entries" in c for c in v["checks"])


def test_missing_report_keeps_soft_check_only(tmp_path):
    """报告不可读时不能把有效分数判 0，只校验分项和不超过总分。"""
    v = _verdict(_snapshot(tmp_path, None, overall_score=30.0, num_passed=20))
    assert v["status"] == "ok"
    assert v["score"] == 0.3
    assert any("report total unavailable" in c for c in v["checks"])


def test_missing_report_ignores_bonus_score_key(tmp_path):
    """报告缺失时不读 bonus_score：1.x/2.x 的报告都不输出该字段。

    显式 bonus 的严格加法曾作为兜底，但没有任何版本真的产出过该键；
    留着只会误导读者以为它受支持。缺报告时统一走不变式校验。
    """
    v = _verdict(
        _snapshot(
            tmp_path, None, overall_score=30.0, num_passed=20, bonus_score=5.0
        )
    )
    assert v["status"] == "ok"
    assert v["score"] == 0.3
    assert v["implied_bonus"] == 5.0
    assert any("report total unavailable" in c for c in v["checks"])

    # 分项和超过总分仍要被抓住（不依赖 bonus_score）。
    bad = _verdict(
        _snapshot(
            tmp_path, None, overall_score=20.0, num_passed=20, bonus_score=5.0
        )
    )
    assert bad["status"] == "score_inconsistent"


def test_hap_score_above_100_allowed(tmp_path):
    """HAP 奖励可让单算子总分超过 100，封顶 120。"""
    rep = _report(115.0, performance_score=85.0)
    v = _verdict(
        _snapshot(tmp_path, rep, overall_score=115.0, performance_score=85.0, num_passed=20)
    )
    assert v["status"] == "ok"
    assert v["score"] == 1.0
    assert v["implied_bonus"] == 5.0


def test_capped_score_allows_component_sum_above_total(tmp_path):
    """封顶时报告记的是 120，分项和 125 高于它属正常，不能判不一致。"""
    rep = _report(120.0, performance_score=100.0)
    v = _verdict(
        _snapshot(
            tmp_path, rep, overall_score=120.0,
            function_score=20.0, performance_score=100.0, num_passed=20,
        )
    )
    assert v["status"] == "ok"
    assert v["score"] == 1.0
    assert v["implied_bonus"] == -5.0


def test_report_cap_raise_does_not_drift(tmp_path):
    """封顶常量在 cann-bench 侧可调；报告说了算，不能因 120 硬编码误杀。"""
    rep = _report(130.0, performance_score=100.0)
    v = _verdict(
        _snapshot(tmp_path, rep, overall_score=130.0, performance_score=100.0, num_passed=20)
    )
    assert v["status"] == "ok"
    assert v["score"] == 1.0


def test_non_finite_component_rejected(tmp_path):
    """NaN/Inf 分项不可信；verdict 仍要能写进严格 JSON。"""
    v = _verdict(
        _snapshot(
            tmp_path, _report(30.0), overall_score=30.0, num_passed=20,
            performance_score=float("nan"),
        )
    )
    assert v["status"] == "score_inconsistent"
    assert v["score"] == 0.0
    assert any("not a finite number" in c for c in v["checks"])
    json.dumps(v, allow_nan=False)


def test_no_eval_result_is_harness_error(tmp_path):
    snap = tmp_path / "state_snapshot.json"
    snap.write_text("{}", encoding="utf-8")
    v = run_tasks.verdict_from_snapshot({}, 1.0, snap)
    assert v["status"] == "harness_error"
    assert v["score"] == 0.0
    assert v["implied_bonus"] == 0.0
