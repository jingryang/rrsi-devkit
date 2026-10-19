"""P2+P3 — fail_strategy declarations validation.

Verifies:
  1. Stage base defaults to "continue".
  2. _DesignSubstage overrides to "halt" and all subclasses inherit it.
  3. codegen declares "halt".
  4. RequirementStage inherits base default (continue).
"""

import pytest
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.orchestration.stages.design_substages import (
    _DesignSubstage, GeneralDesignStage,
    TemplateDivisionStage, SynthesizeStage, TilingStage,
)
from ascendc_devkit.orchestration.stages.codegen import CodegenStage


# —— 1. Base defaults ——

def test_stage_base_default_continue():
    assert Stage.fail_strategy == "continue"


# —— 2. _DesignSubstage + generation-class substages ALL halt ——

@pytest.mark.parametrize("cls", [
    _DesignSubstage,
    GeneralDesignStage,
    TemplateDivisionStage,
    SynthesizeStage,
    TilingStage,
])
def test_generation_stages_halt(cls):
    assert cls.fail_strategy == "halt", f"{cls.__name__} must be halt"


# —— 3. Codegen declares halt ——

def test_codegen_halt():
    assert CodegenStage.fail_strategy == "halt"


# —— 4. RequirementStage inherits base default (continue) ——

def test_requirement_stage_continue():
    from ascendc_devkit.orchestration.stages.requirement import RequirementStage
    assert RequirementStage.fail_strategy == "continue"
