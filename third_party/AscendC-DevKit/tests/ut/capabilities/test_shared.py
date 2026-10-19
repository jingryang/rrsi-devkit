"""UT for capabilities.agent._shared's backend-neutral helpers.

``format_attribution`` is shared by ``SDKBackend``/``OpenCodeBackend`` (§1.6 DI
/ §2.5 single implementation path) for the ``[op_name/stage/branch] `` prefix
on log/transcript lines (D8/§P2, AU-7). Covered directly here since neither
backend's own test file binds ``op_name`` when exercising ``spawn()``'s
attribution construction.
"""

from __future__ import annotations

import pytest

from ascendc_devkit.capabilities.agent._shared import format_attribution
from ascendc_devkit.infra.log_capture import bind_op_name


@pytest.fixture(autouse=True)
def _reset_op_name():
    yield
    bind_op_name("")


def test_empty_stage_name_uses_op_name():
    """Q7 layer-2: empty ``stage_name`` no longer drops attribution when
    ``op_name`` is bound — ``[op/branch]`` keeps batch-log op attribution
    (defence-in-depth: even if a stage forgets stage_name AND the runner
    fallback misses). Pre-Q7 this returned ``""``."""
    bind_op_name("MyOp")
    assert format_attribution("", "T1") == "[MyOp/T1] "
    assert format_attribution("", "") == "[MyOp] "


def test_empty_stage_and_no_op_is_empty():
    """Nothing to attribute (no stage, no op) → ``""`` (no stray ``[]``)."""
    assert format_attribution("", "T1") == ""
    assert format_attribution("", "") == ""


def test_stage_only():
    assert format_attribution("split", "") == "[split] "


def test_stage_and_branch():
    assert format_attribution("split", "T1") == "[split/T1] "


def test_stage_and_op_no_branch():
    bind_op_name("MyOp")
    assert format_attribution("split", "") == "[MyOp/split] "


def test_stage_branch_and_op():
    bind_op_name("MyOp")
    assert format_attribution("split", "T1") == "[MyOp/split/T1] "


def test_op_name_unbound_degrades_to_original_format():
    # Nothing bound (default "") — must be byte-identical to the pre-AU-7 format.
    assert format_attribution("split", "T1") == "[split/T1] "
    assert format_attribution("split", "") == "[split] "
