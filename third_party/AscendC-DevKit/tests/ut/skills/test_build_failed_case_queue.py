"""Backstop UT for the precision-debug skill's ``build-failed-case-queue.py``
(luckdog111 3c250fd, 262 lines, ~200 of pure logic, zero coverage).

This script decides WHICH failed cases the precision-debug loop re-queues for
retry, and how structural data merges across iterations. A bug here = the loop
retries the wrong cases or silently skips real failures — invisible rot. Pin
the contract.

§2.1: the script imports only stdlib (no devkit coupling), so we import it by
path (spec_from_file_location) exactly as a standalone skill would run it — the
test does not depend on the devkit package. §3.8 pure logic, no marks (§3.5).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# §judgment-ownership (N1): 脚本迁入框架包 src/.../precision_debug_run_tests/scripts/
_SCRIPT = (Path(__file__).resolve().parents[3]
           / "src" / "ascendc_devkit" / "orchestration" / "stages"
           / "precision_debug_run_tests" / "scripts"
           / "build-failed-case-queue.py")


@pytest.fixture(scope="module")
def bfcq():
    spec = importlib.util.spec_from_file_location("bfcq", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["bfcq"] = mod
    spec.loader.exec_module(mod)
    return mod


# —— _is_failed ———————————————————————————————————————————————————————————


class TestIsFailed:
    def test_accuracy_passed_false_is_failed(self, bfcq):
        assert bfcq._is_failed({"accuracy": {"passed": False}}) is True

    def test_accuracy_passed_true_not_failed(self, bfcq):
        assert bfcq._is_failed({"accuracy": {"passed": True}}) is False

    def test_error_field_is_failed(self, bfcq):
        assert bfcq._is_failed({"accuracy": {"passed": True}, "error": "boom"}) is True

    def test_no_accuracy_no_error_not_failed(self, bfcq):
        assert bfcq._is_failed({"case_id": "x"}) is False


# —— _extract_shape ————————————————————————————————————————————————


class TestExtractShape:
    def test_from_input_shapes(self, bfcq):
        cd = {"input_shapes": [[1024, 1024]]}
        assert bfcq._extract_shape(cd) == "1024x1024"

    def test_from_case_name_after_last_colon(self, bfcq):
        cd = {"case": "level2/op_1:3x7x13x1013"}
        assert bfcq._extract_shape(cd) == "3x7x13x1013"

    def test_empty_when_nothing(self, bfcq):
        assert bfcq._extract_shape({}) == ""


# —— _extract_dtype ————————————————————————————————————————————————


class TestExtractDtype:
    def test_from_case_name(self, bfcq):
        assert bfcq._extract_dtype({"case": "case:float16:8x8"}) == "float16"

    def test_lowercased(self, bfcq):
        assert bfcq._extract_dtype({"case": "case:FP32:8x8"}) == "fp32"

    def test_fallback_output_dtype(self, bfcq):
        cd = {"case": "nope", "output_results": [{"dtype": "BF16"}]}
        assert bfcq._extract_dtype(cd) == "bf16"

    def test_empty_when_nothing(self, bfcq):
        assert bfcq._extract_dtype({"case": "nope"}) == ""


# —— _extract_max_err ————————————————————————————————————————————————


class TestExtractMaxErr:
    def test_from_accuracy_max_diff(self, bfcq):
        assert bfcq._extract_max_err({"accuracy": {"max_diff": 0.25}}) == 0.25

    def test_from_top_level_diff(self, bfcq):
        assert bfcq._extract_max_err({"diff": 0.5}) == 0.5

    def test_from_output_results_max(self, bfcq):
        cd = {"output_results": [{"diff": 0.1}, {"diff": 0.9}, {"diff": 0.3}]}
        assert bfcq._extract_max_err(cd) == 0.9

    def test_none_when_absent(self, bfcq):
        assert bfcq._extract_max_err({}) is None


# —— _initial_failure_type ———————————————————————————————————————————


class TestInitialFailureType:
    def test_runtime_when_error(self, bfcq):
        assert bfcq._initial_failure_type({"error": "timeout"}) == "runtime"

    def test_precision_otherwise(self, bfcq):
        assert bfcq._initial_failure_type({"accuracy": {"passed": False}}) == "precision"


# —— build_queue (integration) ————————————————————————————————————————


class TestBuildQueue:
    def _write_result(self, tmp_path: Path, case_details: list) -> Path:
        p = tmp_path / "result.json"
        p.write_text(json.dumps({"case_details": case_details}), encoding="utf-8")
        return p

    def test_only_failed_cases_queued(self, bfcq, tmp_path):
        rjp = self._write_result(tmp_path, [
            {"case_id": "a", "accuracy": {"passed": True}},
            {"case_id": "b", "accuracy": {"passed": False, "max_diff": 0.4}},
            {"case_id": "c", "error": "SIGSEGV"},
        ])
        q, _crash_sentinel, total = bfcq.build_queue(str(rjp))
        case_ids = [e["case_id"] for e in q]
        assert case_ids == ["b", "c"]  # passed 'a' excluded
        assert total == 3  # total_count = len(case_details)

    def test_entry_shape_dtype_err_type(self, bfcq, tmp_path):
        rjp = self._write_result(tmp_path, [{
            "case_id": "b", "case": "case:float16:8x8",
            "input_shapes": [[8, 8]], "accuracy": {"passed": False, "max_diff": 0.4},
        }])
        q, _crash_sentinel, total = bfcq.build_queue(str(rjp))
        e = q[0]
        assert e["shape"] == "8x8"
        assert e["dtype"] == "float16"
        assert e["max_err"] == 0.4
        assert e["failure_type"] == "precision"
        assert e["status"] == "pending"
        assert e["attempt_count"] == 0
        assert total == 1

    def test_runtime_entry_when_error(self, bfcq, tmp_path):
        rjp = self._write_result(tmp_path, [{"case_id": "c", "error": "OOM"}])
        q, _crash_sentinel, total = bfcq.build_queue(str(rjp))
        assert q[0]["failure_type"] == "runtime"
        assert total == 1

    def test_error_entry_queues(self, bfcq, tmp_path):
        """build_queue(result_json_path) — only result.json path, no longer
        a checkpoint path param (migrated from fat skill, 54-*.md §1a)."""
        rjp = self._write_result(tmp_path, [{"case_id": "b", "error": "x"}])
        q, _crash_sentinel, total = bfcq.build_queue(str(rjp))
        assert len(q) == 1
        assert total == 1

    def test_partial_case_details_no_accuracy_fallback_to_tested_cases(self, bfcq, tmp_path):
        """核心 bug 场景：case_details 有结构但无 accuracy/error（harness 部分崩溃），
        fallback 到 tested_cases。total_count 应等于 tested_cases 长度，而非 case_details
        长度，否则 passed_count = 20-1 = 19 虚高导致错误更新 best_commit。"""
        p = tmp_path / "result.json"
        p.write_text(json.dumps({
            "case_details": [{"case_id": f"c{i}"} for i in range(20)],  # 无 accuracy/error
            "tested_cases": [{"case_id": "tc0", "shape": "8x8"}],
        }), encoding="utf-8")
        q, _crash_sentinel, total = bfcq.build_queue(str(p))
        assert len(q) == 1                   # fallback 路径：1 条来自 tested_cases
        assert q[0]["case_id"] == "tc0"
        assert total == 1                    # 与 queue 来源对齐，不是 20
        assert not _crash_sentinel

    def test_sigsegv_case_details_empty_tested_cases_nonempty(self, bfcq, tmp_path):
        """SIGSEGV 场景：case_details 为空，tested_cases 非空。
        harness 崩在输出 case 结果之前，但 tested_cases 里有正在运行的用例信息。
        期望：queue 从 tested_cases 构建，total_count = len(tested_cases)，
        passed_count = total - failed = 0，不触发 crash_sentinel。"""
        p = tmp_path / "result.json"
        p.write_text(json.dumps({
            "case_details": [],
            "tested_cases": [
                {"case_id": "tc0", "shape": "8x8"},
                {"case_id": "tc1", "shape": "16x16"},
            ],
            "failure_type": "runtime_crash",
        }), encoding="utf-8")
        q, crash_sentinel, total = bfcq.build_queue(str(p))
        assert not crash_sentinel           # tested_cases 非空，不走 sentinel
        assert total == 2                   # 与 tested_cases 对齐
        assert len(q) == 2                  # 全部入队（均视为 runtime 失败）
        assert all(e["failure_type"] == "runtime" for e in q)
        assert q[0]["case_id"] == "tc0"
        assert q[1]["case_id"] == "tc1"
        # passed_count = total - len(q) = 2 - 2 = 0，不会虚高触发 best_commit 更新

    def test_crash_sentinel_total_zero(self, bfcq, tmp_path):
        """SIGSEGV 场景：case_details + tested_cases 均为空，total_count = 0。"""
        p = tmp_path / "result.json"
        p.write_text(json.dumps({
            "case_details": [],
            "tested_cases": [],
            "failure_type": "runtime_crash",
        }), encoding="utf-8")
        q, crash_sentinel, total = bfcq.build_queue(str(p))
        assert crash_sentinel is True
        assert len(q) == 1 and q[0].get("crash_sentinel") is True
        assert total == 0

    def test_normal_path_total_count_equals_case_details_len(self, bfcq, tmp_path):
        """正常路径：total_count = len(case_details)，与旧行为一致。"""
        rjp = self._write_result(tmp_path, [
            {"case_id": "a", "accuracy": {"passed": True}},
            {"case_id": "b", "accuracy": {"passed": False, "max_diff": 0.1}},
        ])
        q, _cs, total = bfcq.build_queue(str(rjp))
        assert total == 2  # len(case_details)，不受 queue 长度影响
        assert len(q) == 1


# —— merge_with_existing ————————————————————————————————————————————


class TestMergeWithExisting:
    def test_preserves_subagent_metadata_on_match(self, bfcq):
        """Matching by (shape, dtype): new structural data wins, but subagent-
        written metadata (failure_type / tried_fix_plan_ids / attempt_count /
        status / last_fix_commit) is preserved from the old entry."""
        new_q = [{
            "case_id": "new_id", "shape": "8x8", "dtype": "float16",
            "max_err": 0.5, "status": "pending",
            "failure_type": "precision", "attempt_count": 0,
        }]
        old_q = [{
            "case_id": "old_id", "shape": "8x8", "dtype": "float16",
            "max_err": 0.9, "status": "in_progress",
            "failure_type": "runtime", "attempt_count": 3,
            "tried_fix_plan_ids": ["p1"], "last_fix_commit": "abc",
        }]
        merged = bfcq.merge_with_existing(new_q, old_q)
        e = merged[0]
        # new structural data wins
        assert e["case_id"] == "new_id"
        assert e["max_err"] == 0.5
        # old subagent metadata preserved
        assert e["status"] == "in_progress"
        assert e["failure_type"] == "runtime"
        assert e["attempt_count"] == 3
        assert e["tried_fix_plan_ids"] == ["p1"]
        assert e["last_fix_commit"] == "abc"

    def test_no_match_keeps_new_as_is(self, bfcq):
        new_q = [{"shape": "16x16", "dtype": "fp32", "status": "pending"}]
        old_q = [{"shape": "8x8", "dtype": "float16", "status": "in_progress"}]
        merged = bfcq.merge_with_existing(new_q, old_q)
        assert merged == new_q  # no match → new entry untouched

    def test_empty_old_returns_new(self, bfcq):
        new_q = [{"shape": "8x8", "dtype": "float16"}]
        assert bfcq.merge_with_existing(new_q, []) == new_q


# —— amplify_timeout_if_large_shape（确定性超时放大）——————————————
#
# unique d61245 教训：harness 120s 看门狗超时 + 大 shape（百万级元素，golden 本身
# 就可能数十秒）时，放大超时是机械决策，依赖 run_tests agent 的 LLM 判断会误判
# 「环境/死锁」而跳过放大 → 整轮 run_tests 假阴性白跑。本函数是确定性兜底：
# timeout + ≥1M 元素 case → 写回 control.harness_timeout_sec（×4，上限 1200）。
# 放大值 debug_service.run_cases 自动消费；agent 只负责看到 AMPLIFIED 后重跑。


class TestAmplifyTimeoutIfLargeShape:
    def _result(self, failure_type="timeout", error="", elems=1048576):
        r = {"failure_type": failure_type,
             "tested_cases": [{"case_id": "c1", "max_input_elements": elems}]}
        if error:
            r["error"] = error
        return r

    def test_timeout_large_shape_amplifies_x4(self, bfcq):
        ctrl = {"harness_timeout_sec": 120.0}
        amplified, reason = bfcq.amplify_timeout_if_large_shape(
            self._result(), ctrl)
        assert amplified is True
        assert reason == "large_shape_amplified"
        assert ctrl["harness_timeout_sec"] == 480.0

    def test_amplify_respects_cap(self, bfcq):
        ctrl = {"harness_timeout_sec": 120.0, "harness_timeout_max_sec": 200.0}
        amplified, _ = bfcq.amplify_timeout_if_large_shape(self._result(), ctrl)
        assert amplified is True
        assert ctrl["harness_timeout_sec"] == 200.0

    def test_at_cap_no_amplify_over_cap(self, bfcq):
        ctrl = {"harness_timeout_sec": 1200.0}
        amplified, reason = bfcq.amplify_timeout_if_large_shape(
            self._result(), ctrl)
        assert amplified is False
        assert reason == "large_shape_over_cap"
        assert ctrl["harness_timeout_sec"] == 1200.0  # 不变

    def test_non_large_shape_no_amplify(self, bfcq):
        ctrl = {"harness_timeout_sec": 120.0}
        amplified, reason = bfcq.amplify_timeout_if_large_shape(
            self._result(elems=65536), ctrl)
        assert amplified is False
        assert reason == "non_large_shape"
        assert ctrl["harness_timeout_sec"] == 120.0

    def test_custom_threshold_from_control(self, bfcq):
        ctrl = {"harness_timeout_sec": 120.0,
                "harness_large_shape_elements": 500000}
        amplified, reason = bfcq.amplify_timeout_if_large_shape(
            self._result(elems=600000), ctrl)
        assert amplified is True
        assert reason == "large_shape_amplified"

    def test_not_timeout_no_amplify(self, bfcq):
        ctrl = {"harness_timeout_sec": 120.0}
        amplified, reason = bfcq.amplify_timeout_if_large_shape(
            self._result(failure_type="precision"), ctrl)
        assert amplified is False
        assert reason == ""
        assert ctrl["harness_timeout_sec"] == 120.0

    def test_timeout_via_error_string(self, bfcq):
        ctrl = {"harness_timeout_sec": 120.0}
        r = self._result(failure_type="runtime",
                         error="Command '[...]' timed out after 120.0 seconds")
        amplified, reason = bfcq.amplify_timeout_if_large_shape(r, ctrl)
        assert amplified is True
        assert reason == "large_shape_amplified"

    def test_empty_tested_cases_is_non_large_shape(self, bfcq):
        ctrl = {"harness_timeout_sec": 120.0}
        r = {"failure_type": "timeout", "tested_cases": []}
        amplified, reason = bfcq.amplify_timeout_if_large_shape(r, ctrl)
        assert amplified is False
        assert reason == "non_large_shape"


# —— 框架自有 sidecar（§2.9）：main() 放大超时后写 harness_timeout.fw.json ——


class TestMainWritesFrameworkSidecar:
    def test_amplified_timeout_writes_sidecar(self, bfcq, tmp_path):
        """放大超时 → 除 control.json 外，写框架自有 sidecar（debug_service 读它
        恢复放大值，不靠 agent 在 control.json 保留——20260810 批 6+ 次 PD-CONTRACT
        WARN 根因）。"""
        control_path = tmp_path / "control.json"
        result_path = tmp_path / "result.json"
        control_path.write_text(json.dumps({
            "harness_timeout_sec": 120.0,
            "failed_case_queue": [],
        }), encoding="utf-8")
        result_path.write_text(json.dumps({
            "failure_type": "timeout",
            "error": "subprocess timed out after 120s",
            "total_ms": 999.0, "max_diff": 999.0,
            "case_details": [],
            "tested_cases": [{"case_id": "c1", "max_input_elements": 1048576}],
        }), encoding="utf-8")
        sys.argv = ["bfcq", "--result-json", str(result_path),
                    "--control", str(control_path)]
        bfcq.main()
        # control.json 放大写回（既有行为）
        cp = json.loads(control_path.read_text(encoding="utf-8"))
        assert cp["harness_timeout_sec"] == 480.0
        # 框架自有 sidecar 同步持久化
        sidecar = tmp_path / "harness_timeout.fw.json"
        assert sidecar.exists()
        assert json.loads(sidecar.read_text(encoding="utf-8")) == {
            "harness_timeout_sec": 480.0}

    def test_sidecar_mirrors_current_value_without_amplification(self, bfcq, tmp_path):
        """非超时（精度失败）→ 不放大，但 sidecar 镜像 control.json 当前值
        （框架自有持久化 = 字段的可靠副本，不依赖放大才写——保证任何时刻
        debug_service 读 sidecar 都能拿到最新值）。"""
        control_path = tmp_path / "control.json"
        result_path = tmp_path / "result.json"
        control_path.write_text(json.dumps({
            "harness_timeout_sec": 120.0,
            "failed_case_queue": [],
        }), encoding="utf-8")
        result_path.write_text(json.dumps({
            "failure_type": "precision",
            "total_ms": 10.0, "max_diff": 0.1,
            "case_details": [{"case_id": "c1", "status": "failed",
                              "accuracy": {"passed": False}}],
            "tested_cases": [],
        }), encoding="utf-8")
        sys.argv = ["bfcq", "--result-json", str(result_path),
                    "--control", str(control_path)]
        bfcq.main()
        sidecar = tmp_path / "harness_timeout.fw.json"
        assert sidecar.exists()
        assert json.loads(sidecar.read_text(encoding="utf-8")) == {
            "harness_timeout_sec": 120.0}


# —— F4（review 坐实）：sidecar 文件名双处声明漂移守卫 ————————————————————
# skill 脚本（stdlib-only，§2.1 自闭环）与 runtime_config.HARNESS_TIMEOUT_SIDECAR_NAME
# 各声明 harness_timeout.fw.json，靠注释对齐；漂移会静默断链（debug_service 读不到
# sidecar → 放大值丢 → 退默认 120）。此测试把两处钉在同一断言里，漂移即红。


def test_sidecar_filename_matches_framework_constant():
    """脚本写的 sidecar 文件名必须 == runtime_config.HARNESS_TIMEOUT_SIDECAR_NAME。"""
    from ascendc_devkit.orchestration.runtime_config import HARNESS_TIMEOUT_SIDECAR_NAME
    src = _SCRIPT.read_text(encoding="utf-8")
    assert f'"{HARNESS_TIMEOUT_SIDECAR_NAME}"' in src, (
        f"build-failed-case-queue.py 的 sidecar 文件名与框架常量 "
        f"{HARNESS_TIMEOUT_SIDECAR_NAME!r} 不一致——漂移会导致 debug_service 读不到放大值")
