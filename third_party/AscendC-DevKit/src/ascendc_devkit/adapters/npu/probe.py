"""L6 Adapters — per-card NPU open-device probe.

Runtime health check distinct from load-time detection (detect.py): before a
stage commits a long subprocess (kernel_eval / precision run) to a card, verify
that card can actually open a device context (set_device + alloc). This catches
driver-level device-context pool exhaustion (507033 / TsdOpen failed / device
retain error) that the in-memory card pool (slot.py) structurally cannot see —
a card may be "free" in Python bookkeeping yet unopenable on the driver side
after subprocess-zombie context leaks (run 20260727-144633-2a1db8: cannbench_eval
hit 507033 with the slot pool showing all 8 cards free; the fault was mistaken
for an operator precision loss and silently swallowed).

Failure raises EnvironmentNotAvailableError — a control-flow exception the
dispatcher halts on (preserving the generated operator code for inspection) —
never a swallowed RuntimeError. Device unavailability is an environment
precondition, not an operator defect (§3.7 honest reporting).
"""

from __future__ import annotations

import subprocess
import sys

from ascendc_devkit.domain.exceptions import EnvironmentNotAvailableError

# set_device + alloc a 1-element tensor is the minimal "can this card open a
# device context" signal — matches the 507033 diagnostic. The probe reuses the
# caller's env so it walks the same open-device path the real subprocess will.
_PROBE_SCRIPT = (
    "import torch,torch_npu;"
    "torch.npu.set_device({card});"
    "torch.zeros(1, device='npu')"
)
# open-device can HANG on context-pool exhaustion (npu-smi info hangs in that
# state too), so the probe MUST be bounded — a hung unbounded probe would stall
# the stage instead of reporting the fault.
_DEFAULT_TIMEOUT = 60.0


def probe_device(
    card: int,
    env: dict | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
    stage_name: str = "npu_probe",
) -> None:
    """Probe that NPU device ``card`` can be opened (set_device + alloc tensor).

    Raises :class:`EnvironmentNotAvailableError` on non-zero exit or timeout — a
    control-flow exception the dispatcher halts on (preserving the generated
    operator code), so a device fault is reported honestly instead of being
    mistaken for an operator precision loss.

    ``env`` should be the caller's subprocess env (autoload=0, usercustomize
    torch_npu import, PYTHONPATH/LD) so the probe exercises the same open-device
    path the real eval will — not a bare ``os.environ`` that might hide the fault.
    """
    script = _PROBE_SCRIPT.format(card=card)
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            env=env, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise EnvironmentNotAvailableError(
            stage_name=stage_name,
            missing=f"NPU device {card} (probe timed out after {timeout}s)",
            help_hint=(
                "open-device hung — likely driver device-context pool exhausted "
                "(zombie subprocess leak); check zombie count or restart the container"
            ),
        ) from e
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-400:]
        raise EnvironmentNotAvailableError(
            stage_name=stage_name,
            missing=f"NPU device {card} (probe exited {proc.returncode})",
            help_hint=(
                "open-device failed — 507033/device-retain/TsdOpen usually means "
                "driver context-pool exhaustion; check zombie processes or restart "
                f"the container. probe stderr tail: {tail}"
            ),
        )
