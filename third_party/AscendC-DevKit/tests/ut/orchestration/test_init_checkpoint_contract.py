"""Q4: ``init-checkpoint.py`` seeds ``consecutive_aborts`` (step-55 P9 fourth part).

``_CONTROL_REQUIRED_KEYS`` (substages) lists ``consecutive_aborts`` and
``_CONTROL_DEFAULTS`` has it (0), but ``init-checkpoint.py`` — which writes the
first-round ``control.json`` — missed it → the first ``_load_control``'s contract
check auto-init'd and WARNed ``[PD-CONTRACT] control.json missing ... consecutive_aborts``.
step-55 P9 synced ``phase_counter``/``run_iter_counter`` (required + default +
init-write + doc); this completes the same pattern for ``consecutive_aborts``.
"""
import json
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

# §judgment-ownership (N1): 脚本迁入框架包 src/.../precision_debug_run_tests/scripts/
INIT_PATH = (Path(__file__).resolve().parents[3]
             / "src/ascendc_devkit/orchestration/stages/"
             "precision_debug_run_tests/scripts/init-checkpoint.py")


def _load_init_module():
    spec = spec_from_file_location("_init_checkpoint", INIT_PATH)
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _init(tmp_path):
    mod = _load_init_module()
    op_dir = tmp_path / "op"
    op_dir.mkdir()
    (op_dir / "kernel.cpp").write_text("// stub")  # copytree needs a file
    out_dir = tmp_path / "out"
    mod.init_control(str(op_dir), str(out_dir), "tcmd", "bcmd", op_name="add")
    control_files = list(out_dir.rglob("control.json"))
    assert control_files, "init_control should write control.json"
    return json.loads(control_files[0].read_text())


def test_init_control_seeds_consecutive_aborts(tmp_path):
    """init_control() must seed ``consecutive_aborts=0`` — no auto-init WARN."""
    control = _init(tmp_path)
    assert "consecutive_aborts" in control, (
        "init-checkpoint must seed consecutive_aborts — else first _load_control "
        "auto-init WARNs (step-55 P9 pattern, fourth sync part)")
    assert control["consecutive_aborts"] == 0


def test_init_control_still_seeds_p9_counters(tmp_path):
    """regression guard: the existing P9-synced counters stay seeded."""
    control = _init(tmp_path)
    assert control["phase_counter"] == 0
    assert control["run_iter_counter"] == 0
    # P3 减法: corrective_cycles 已删; upstream_signal 是新的诊断入口判据字段
    assert control["upstream_signal"] is False
    assert control["upstream_stage"] is None
