"""L6 Adapters — op-level NPU card pin (P13 / step-116).

Single point for the op's card identity and its structural propagation,
replacing the former per-span ``card_context`` leases (whose agent-subtree
blind spot was P13's root cause — the lease ledger only covered framework
subprocesses while op agents opened cards invisibly):

- ``card_pin_env(card)`` — the two-variable pin every op subprocess carries.
  Physical truth lives in exactly one variable; the logical id is always 0:

  * ``ASCEND_RT_VISIBLE_DEVICES=<physical card>`` — the CANN runtime restricts
    visibility to the pinned card with **remap** semantics (verified live:
    under ``=5`` a process sees ``device_count()==1`` and ``npu:0`` is the
    physical card 5; restrict semantics would raise invalid-ordinal on
    ``npu:0``). Default env inheritance propagates it to every descendant —
    new spawn kinds are correct with zero action (§2.9 constructive).
  * ``ASCEND_NPU_ID=0`` — the logical device id under remap. The legacy
    meaning (physical id) survives only OUTSIDE pinned subtrees.

- ``resolve_op_card(preferred, pool, owner)`` — the ONE resolution point, at
  the op boundary (``dispatch``). Batch: one exclusive lease held for the
  whole op lifetime (``state.npu_id`` turns from hint into the authoritative
  op card). Standalone / inner CLI (pool is None): resolve from the inherited
  pin env, the preferred id, or the legacy env — nothing to lease against.

- ``verify_pin(card)`` — batch op-start probe: a real subprocess under the
  exact spawn env asserting ``device_count() == 1``. Broken pin plumbing
  fails the op fast instead of silently landing everything on device 0
  (§1.10 — evidence, not assumption). Deliberate env tampering is NOT
  detectable at runtime on this stack (processes hold only the card-agnostic
  ``/dev/davinci_manager`` fd; ``npu-smi proc-mem`` is blind to torch_npu
  processes) — recorded as an honest boundary, no unreliable detector built.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from typing import Callable

from ascendc_devkit.domain.exceptions import EnvironmentNotAvailableError
from ascendc_devkit.infra.logger import Logger

# Subprocess assertion under the pin env: exactly one visible device.
_PROBE_CODE = (
    "import torch, torch_npu; "
    "n = torch.npu.device_count(); "
    "assert n == 1, f'device_count={n}'"
)

# 继承 pin env 的合法卡号 = 纯十进制数字（``^\d+$``），与 ``card_pin_env`` 的
# 非负 int 校验同语义：负值/畸形（"-3"/"3.0"/"0x3"）视为无 pin env，落到下一
# 优先级——绝不把 ``"-3"`` 经 lstrip("-") 误读成 3，也不让负卡号流入 CANN env。
_PIN_ENV_ID = re.compile(r"^\d+$")


def card_pin_env(card: int) -> dict[str, str]:
    """The two-variable pin for one op card (single source, §1.15).

    ``ASCEND_RT_VISIBLE_DEVICES`` carries the physical card (remap: it becomes
    device 0 inside the subtree); ``ASCEND_NPU_ID`` is always the logical 0.
    """
    if not isinstance(card, int) or isinstance(card, bool) or card < 0:
        raise ValueError(f"invalid NPU card id: {card!r}")
    return {"ASCEND_RT_VISIBLE_DEVICES": str(card), "ASCEND_NPU_ID": "0"}


def resolve_op_card(
    preferred: int | None,
    pool,
    owner: str = "",
) -> tuple[int, Callable[[], None] | None]:
    """Resolve the op's card once, at the op boundary.

    Returns ``(card, release)``; ``release`` is ``None`` when nothing was
    leased (standalone / inner-CLI mode).

    - ``pool`` not None (batch): an exclusive whole-op lease —
      ``pool.acquire(npu_id=preferred, owner=owner)``. A preferred card held
      by a sibling op raises (config error: two tasks reserved one card);
      no preferred card → auto-pick, blocking while peers hold all cards
      (admission queuing — explicit, not hidden latency coupling).
    - ``pool`` None (standalone / inner CLI subprocess): inherited pin env
      (``ASCEND_RT_VISIBLE_DEVICES``, first entry of a list; legal card id =
      ``^\d+$`` — negative/malformed entries count as NO pin env and fall to
      the next priority) > ``preferred``
      > legacy ``ASCEND_NPU_ID`` env (physical-id semantics, unpinned
      contexts only; same ``^\d+$`` validity) > 0.
    """
    if pool is not None:
        card = pool.acquire(npu_id=preferred, owner=owner or "op")

        def _release() -> None:
            try:
                pool.release(card)
            except Exception as e:  # noqa: BLE001 — release must never mask
                Logger.warn(f"op card lease release failed (card={card}): {e}")

        return card, _release

    vis = os.environ.get("ASCEND_RT_VISIBLE_DEVICES", "").strip()
    first = vis.split(",")[0].strip() if vis else ""
    if _PIN_ENV_ID.match(first):
        return int(first), None
    if preferred is not None:
        return int(preferred), None
    legacy = os.environ.get("ASCEND_NPU_ID", "").strip()
    return (int(legacy) if _PIN_ENV_ID.match(legacy) else 0), None


def verify_pin(card: int, base_env: dict | None = None,
               timeout_s: float = 90.0) -> None:
    """Probe the pin with a real subprocess; raise on any doubt.

    Runs ``device_count() == 1`` under ``{base_env | os.environ} + pin`` —
    the same env shape every op spawn gets — so a broken pin (var ignored by
    this CANN, env not reaching subprocesses, wrong spelling) fails the op
    at start with the probe's stderr, not hours later as a mystery wrong-card
    symptom (§3.7 honest env failure; §1.10 real evidence).
    """
    env = {**(base_env if base_env is not None else os.environ),
           **card_pin_env(card)}
    try:
        result = subprocess.run(
            [sys.executable, "-c", _PROBE_CODE],
            env=env, capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as e:
        raise EnvironmentNotAvailableError(
            "dispatch", f"NPU card pin verify timed out on card {card} "
                        f"({timeout_s:.0f}s)") from e
    if result.returncode != 0:
        stderr_tail = (result.stderr or result.stdout or "").strip()[-2000:]
        raise EnvironmentNotAvailableError(
            "dispatch",
            f"NPU card pin verify failed on card {card} "
            f"(rc={result.returncode}); pin env did not yield exactly one "
            f"visible device — stderr tail: {stderr_tail!r}")
