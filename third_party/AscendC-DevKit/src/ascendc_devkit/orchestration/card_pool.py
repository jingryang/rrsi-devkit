"""L3 Orchestration — card-pool factory for batch dispatch (P69 stage 2).

Layering seam: L2 (``batch_runner`` / ``dispatch``) may import only L3/L4/L7
(see ``tests/ut/test_layer_dependencies.py``). ``NPUSlotManager`` lives in L6
(``adapters/npu/slot.py``). This factory is the L3 touch-point that constructs
the L6 pool from a card-id list and hands it back to L2 as an opaque object.

Single responsibility: turn a resolved card-id list into a shared
``NPUSlotManager``. The four-tier card-source fallback (manifest > cli > probe
> error) stays in ``batch_runner.resolve_card_pool`` (L2); this factory only
packages the already-resolved list.
"""

from __future__ import annotations

from ascendc_devkit.adapters.npu.slot import NPUSlotManager


def build_shared_card_pool(card_ids: list[int]) -> NPUSlotManager:
    """Build a shared ``NPUSlotManager`` over the given card-id set.

    ``max_devices`` is derived from the card set (``max(card_ids)+1``) so no
    redundant NPU count probe runs here — ``resolve_card_pool`` already probed
    (L2 owns the four-tier fallback). The manager is returned to the L2 caller,
    which passes it to ``dispatch(card_pool=...)``: P13/step-116 takes ONE
    whole-op lease per op at the dispatch boundary (op-level granularity —
    the former per-span leases and the State threading are retired).
    """
    return NPUSlotManager(max_devices=max(card_ids) + 1, allowed=list(card_ids))
