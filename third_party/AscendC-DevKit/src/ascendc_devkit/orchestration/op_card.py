"""L3 Orchestration — op-level NPU card lifecycle (single point).

dispatcher(L2) 的 op 卡借还壳（P13/step-116）上移本模块（KNOWN 清零 step-2）：
``acquire_op_card`` / ``release_op_card`` 是 dispatcher 主流程 / single-stage rerun
共享的「解析卡 →（可选租约）→ 更新 state」原语。卡级机制（resolve_op_card /
verify_pin / pin_env）留在 L6 ``adapters.npu.card_pin``（设备机制层）；本模块只
承载编排壳。

§1.1 层矩阵：本模块 import L6 合法（3→6）；dispatcher(L2) import 本模块合法（2→3）。

§step-95 对称性（P13 硬仗产出，不可破坏）：借/还紧邻——调用方在**同一个函数体**
内 acquire 后立即进入 body、finally 里 release；release 是唯一归还点，任何
return/异常路径必穿过它。本模块保持该不变式：acquire 失败抛 ``OpCardLeaseError``
（配置错误类，调用方接住转 EX_CONFIG），成功返回 ``(card, state, release)``。
"""
from __future__ import annotations

from ascendc_devkit.adapters.npu.card_pin import resolve_op_card, verify_pin

__all__ = ["acquire_op_card", "release_op_card", "verify_lease", "OpCardLeaseError"]


class OpCardLeaseError(Exception):
    """Op card lease is a task-config error (preferred card held by a sibling op /
    out-of-range / not-in-allowed-set) — the op fails loudly as EX_CONFIG."""


def acquire_op_card(preferred: int | None, pool, state, *, owner: str):
    """Resolve the op's card at the op boundary and pin it on ``state``.

    Batch (pool not None): takes ONE exclusive lease for the whole op lifetime.
    Standalone / inner CLI (pool None): resolves from the inherited pin env /
    preferred / legacy env with no lease.

    Returns ``(card, state_with_card, release)`` — ``release`` is ``None`` when
    nothing was leased (pool is None). Caller runs its body then must call
    ``release_op_card(release)`` in a finally.
    """
    try:
        card, release = resolve_op_card(preferred, pool, owner=owner)
    except (RuntimeError, ValueError) as e:
        # preferred card held by a sibling op — task config reserved one card
        # twice; out-of-range / not-in-allowed-set is the same task-config error
        # class (slot raises ValueError there). Nothing is held yet (resolve
        # raised before assignment), no release needed.
        raise OpCardLeaseError(str(e)) from e
    if card != state.npu_id:
        state = state.with_updates(npu_id=card)
    return card, state, release


def release_op_card(release) -> None:
    """Release the op lease (no-op when nothing was leased). Idempotent. """
    if release is not None:
        release()


def verify_lease(card: int) -> None:
    """Probe the pinned card's pin plumbing (batch op start, L6 verify_pin).

    Raises EnvironmentNotAvailableError when the pin does not yield exactly one
    visible device — the op fails fast instead of hours of wrong-card work.
    """
    verify_pin(card)
