"""UT — AttributionEngine rule-based tests."""

from ascendc_devkit.domain.evolution import OpEvalResult
from ascendc_devkit.domain.verification import EvalResult
from ascendc_devkit.self_evolution.attribution import AttributionEngine


class TestAttributionEngine:
    def test_empty_results(self):
        attrs = AttributionEngine.attribute([])
        assert attrs == []

    def test_all_passed_no_attributions(self):
        results = [
            OpEvalResult(
                op_name="add", status="ok",
                eval_result=EvalResult(overall_score=85.0),
            ),
            OpEvalResult(
                op_name="exp", status="ok",
                eval_result=EvalResult(overall_score=40.0),
            ),
        ]
        attrs = AttributionEngine.attribute(results)
        assert attrs == []  # all passed → nothing to attribute

    def test_compile_failure_maps_to_skill_codegen(self):
        results = [
            OpEvalResult(op_name="exp", status="compile_failed"),
        ]
        attrs = AttributionEngine.attribute(results)
        assert len(attrs) == 1
        assert attrs[0].failure_type == "compile_failed"
        assert attrs[0].target_component == "skill/codegen"
        assert attrs[0].severity == "low"
        assert attrs[0].op_count == 1

    def test_deploy_failure_maps_to_framework_high_risk(self):
        results = [
            OpEvalResult(op_name="exp", status="deploy_failed"),
        ]
        attrs = AttributionEngine.attribute(results)
        assert len(attrs) == 1
        assert attrs[0].failure_type == "deploy_failed"
        assert attrs[0].target_component == "framework/deploy"
        assert attrs[0].severity == "high"

    def test_multiple_same_failure_deduplicated(self):
        """Three ops with same failure → one AttributionItem, not three."""
        results = [
            OpEvalResult(op_name="a", status="compile_failed"),
            OpEvalResult(op_name="b", status="compile_failed"),
            OpEvalResult(op_name="c", status="compile_failed"),
        ]
        attrs = AttributionEngine.attribute(results)
        assert len(attrs) == 1
        assert attrs[0].op_count == 3
        assert "a" in attrs[0].evidence and "b" in attrs[0].evidence

    def test_mixed_failures_produce_multiple_attributions(self):
        results = [
            OpEvalResult(op_name="a", status="compile_failed"),
            OpEvalResult(op_name="b", status="deploy_failed"),
            OpEvalResult(op_name="c", status="compile_failed"),
        ]
        attrs = AttributionEngine.attribute(results)
        # Two distinct failure types → two attributions
        assert len(attrs) == 2
        types = {a.failure_type for a in attrs}
        assert types == {"compile_failed", "deploy_failed"}

    def test_precision_failure_from_zero_function_score(self):
        """Non-zero compile + zero function → precision failure."""
        results = [
            OpEvalResult(
                op_name="exp", status="ok",
                eval_result=EvalResult(
                    overall_score=0.0,
                    compile_score=10.0,    # compile passed
                    function_score=0.0,    # function = precision fail
                    performance_score=0.0,
                ),
            ),
        ]
        attrs = AttributionEngine.attribute(results)
        assert len(attrs) == 1
        assert attrs[0].failure_type == "precision_failed"
        assert attrs[0].target_component == "skill/codegen"

    def test_eval_timeout_maps_to_deploy_framework(self):
        results = [
            OpEvalResult(op_name="exp", status="eval_timeout"),
        ]
        attrs = AttributionEngine.attribute(results)
        assert len(attrs) == 1
        assert attrs[0].failure_type == "deploy_failed"
        assert attrs[0].severity == "high"
