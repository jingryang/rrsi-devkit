"""Local conftest for tests/ut/skills/ — overrides the root conftest's
_unbind_run_log_after_each_test fixture which requires ascendc_devkit to be
installed. The template invariant tests are pure static analysis with no
run-log binding, so the teardown is a safe no-op here."""

import pytest


@pytest.fixture(autouse=True)
def _unbind_run_log_after_each_test():
    """Override root conftest's fixture: no-op when ascendc_devkit is not importable."""
    yield
    try:
        from ascendc_devkit.infra.log_capture import unbind_run_log
        unbind_run_log()
    except ModuleNotFoundError:
        pass
