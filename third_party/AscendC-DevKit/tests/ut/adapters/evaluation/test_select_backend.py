"""UT — select_backend priority + default registry (step-40 L4 Phase A)."""

from __future__ import annotations

from ascendc_devkit.adapters.evaluation import _default_registry, select_backend
from ascendc_devkit.adapters.evaluation.cannbench import CannbenchBackend
from ascendc_devkit.adapters.evaluation.devkit import DevkitBackend
from ascendc_devkit.domain.evaluation import EvalRequest, OpRef, RunMode
from ascendc_devkit.domain.precision import CompareRule
from ascendc_devkit.domain.verification import DeployResult


def _request(cases_source=None, golden=None):
    return EvalRequest(
        op=OpRef(callable_target={"kind": "torch_op", "symbol": "s"},
                 op_name="op", op_dir="/op", chip="A2"),
        cases=[],
        rule=CompareRule(dtype_thresholds={}),
        deploy_result=DeployResult(),
        golden_contract=golden,
        mode=RunMode.SINGLE_CASE,
        cases_source=cases_source,
    )


_GOLDEN = {"path": "/g.py", "entry": "op", "input_type": "torch"}


class TestDefaultRegistry:
    def test_order_cannbench_before_devkit(self):
        """Standard-alignment priority: CannbenchBackend first, DevkitBackend (always
        available) last as the universal fallback."""
        reg = _default_registry()
        assert isinstance(reg[0], CannbenchBackend)
        assert isinstance(reg[1], DevkitBackend)


class TestSelectBackend:
    def test_cannbench_selected_when_cannbench_source_and_golden(self):
        b = select_backend(_request(cases_source="cannbench", golden=_GOLDEN))
        assert isinstance(b, CannbenchBackend)

    def test_devkit_selected_when_devkit_source(self):
        b = select_backend(_request(cases_source="devkit"))
        assert isinstance(b, DevkitBackend)

    def test_devkit_selected_when_source_unknown(self):
        b = select_backend(_request(cases_source=None))
        assert isinstance(b, DevkitBackend)

    def test_devkit_fallback_when_cannbench_source_lacks_golden(self):
        """CannbenchBackend.available requires a golden; without it the universal
        DevkitBackend is selected (honest fallback — no standard comparison w/o golden)."""
        b = select_backend(_request(cases_source="cannbench", golden=None))
        assert isinstance(b, DevkitBackend)

    def test_devkit_always_available(self):
        """DevkitBackend is the universal fallback — available for any request."""
        assert DevkitBackend().available(_request()) is True
        assert DevkitBackend().available(_request(cases_source="cannbench", golden=_GOLDEN)) is True

    def test_custom_registry_used_when_provided(self):
        """Explicit registry injection (§1.6 DI) — e.g. future ATK/TTK slotting in."""
        dev = DevkitBackend()
        b = select_backend(_request(cases_source="cannbench", golden=_GOLDEN), registry=[dev])
        assert b is dev
