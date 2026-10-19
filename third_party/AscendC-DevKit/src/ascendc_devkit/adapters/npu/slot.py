"""L6 Adapters — NPU Slot Manager: multi-NPU device allocation.

Prevents concurrent conflicts by tracking which NPU devices are in use.
Card granularity is subprocess-level (P69 stage 2): ``acquire`` blocks until a
card is free so concurrent NPU subprocesses queue rather than fail, with
optional timeout, context-managed release, and best-effort dead-card warnings.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Iterator

from ascendc_devkit.domain.exceptions import CardAcquireTimeout

_logger = logging.getLogger(__name__)


class NPUSlotManager:
    """Manage multi-NPU card allocation for concurrent workloads.

    Each NPU device is identified by an integer ID (0-indexed). The manager
    tracks which IDs are currently acquired and provides acquire/release
    operations with thread safety.

    Acquisition semantics (subprocess-level granularity):

    - ``acquire(npu_id=N)`` — hard-pin card N. If already held, raises
      ``RuntimeError`` immediately (hard-pin never queues; it is the path for
      ``--npu-id`` / task-level ``npu_id`` reservations).
    - ``acquire()`` — take the lowest free card in ``allowed``; if the pool is
      exhausted, block until one is released (default), bounded by ``timeout``.
    - ``acquire(timeout=0)`` — non-blocking probe: raise ``CardAcquireTimeout``
      immediately if empty (the legacy fail-fast escape hatch).
    - ``acquire(timeout=T)`` — block at most ``T`` seconds, then raise.
    - ``acquire_context(timeout=T)`` — context manager that releases on exit
      (including the exception path, covering subprocess crash/timeout).

    ``allowed`` restricts the pool to a subset of ``max_devices`` (e.g. the
    batch card-pool four-level fallback result); ``None`` uses the full
    detected range. Dead-card detection is best-effort: when a waiter finds the
    pool empty, any held card whose lease exceeds ``lease_warn_threshold`` is
    logged at WARNING — never force-reclaimed (forced reclaim needs a lease;
    subprocess ``timeout`` + ``acquire_context`` covers the common crash path).
    """

    def __init__(self, max_devices: int | None = None,
                 allowed: list[int] | None = None,
                 lease_warn_threshold: float = 600.0):
        self._cond = threading.Condition()
        # §step-95: card → owner label（归因）。99c4c0 批 8 卡泄漏时是无主 set——
        # 等待者只知「池空」不知「谁持有」，死等无法诊断。owner 由 acquire 调用方
        # 传入（execution/op 名 + stage 名）；空串 = 未标注（行为不变）。
        self._acquired: dict[int, str] = {}
        self._acquired_at: dict[int, float] = {}
        detected = max_devices or self._detect_device_count()
        self._max_devices = detected
        if allowed is None:
            self._allowed: list[int] = list(range(detected))
        else:
            self._allowed = sorted({i for i in allowed if 0 <= i < detected})
        self._lease_warn_threshold = lease_warn_threshold

    @staticmethod
    def _detect_device_count() -> int:
        """Detect available NPU devices via env or npu-smi subprocess.

        step 104: the in-process ``import torch_npu`` fallback is GONE — the
        orchestrator main process must stay pure Python (in-process torch_npu/
        CANN loading corrupts its heap; docs/plan/dispatch-npu-probe-subprocess/).
        Priority: env (ASCEND_NPU_COUNT/ASCEND_DEVICE_NUM) → npu-smi physical
        count → default 8. npu-smi counts PHYSICAL cards — restricted-visibility
        (ASCEND_RT_VISIBLE_DEVICES) setups must declare the env explicitly.
        """
        from ascendc_devkit.infra.npu_smi import env_device_count, npu_smi_device_count

        count = env_device_count()
        if count is not None:
            return count
        smi = npu_smi_device_count()
        if smi is not None:
            return smi
        return 8  # default for 910B

    def _holders_locked(self) -> list[str]:
        """``["0:owner", ...]`` snapshot for logs/exceptions. Caller holds cond."""
        return [f"{card}:{owner or '?'}"
                for card, owner in sorted(self._acquired.items())]

    def _warn_dead_cards_locked(self) -> None:
        """Best-effort dead-card diagnostic. Caller holds ``self._cond``."""
        now = time.monotonic()
        for card, acquired_at in self._acquired_at.items():
            lease = now - acquired_at
            if lease > self._lease_warn_threshold:
                _logger.warning(
                    "NPU card %d held for %.1fs by %r (exceeds lease threshold "
                    "%.1fs); possible dead card from an un-released holder",
                    card, lease, self._acquired.get(card, "?"),
                    self._lease_warn_threshold)

    def acquire(self, npu_id: int | None = None,
                timeout: float | None = None, owner: str = "") -> int:
        """Acquire an NPU device. Returns the acquired device ID.

        See class docstring for npu_id / timeout semantics. ``owner`` is a
        best-effort attribution label (e.g. ``"unique/precision_debug"``)
        surfaced in wait logs / timeout errors / dead-card warnings (§step-95).
        """
        deadline = None if timeout is None else time.monotonic() + max(timeout, 0.0)
        _logged_wait = False
        with self._cond:
            while True:
                # Hard-pin path: validate, never queue.
                if npu_id is not None:
                    if npu_id < 0 or npu_id >= self._max_devices:
                        raise ValueError(
                            f"NPU device {npu_id} out of range [0, {self._max_devices})")
                    if npu_id not in self._allowed:
                        raise ValueError(
                            f"NPU device {npu_id} not in allowed set {self._allowed}")
                    if npu_id in self._acquired:
                        raise RuntimeError(
                            f"NPU device {npu_id} is already acquired "
                            f"(holder: {self._acquired[npu_id] or '?'})")
                    self._acquired[npu_id] = owner
                    self._acquired_at[npu_id] = time.monotonic()
                    return npu_id

                # Auto path: lowest free card in allowed.
                free = [i for i in self._allowed if i not in self._acquired]
                if free:
                    card = free[0]
                    self._acquired[card] = owner
                    self._acquired_at[card] = time.monotonic()
                    return card

                # Pool exhausted — attribute holders once, diagnose, then block
                # or time out. §step-95 用户语义：活跃占用 = 正常等待（不 abort）；
                # 归因让「死等」可诊断（谁持有、持了多久）。
                if not _logged_wait:
                    _logged_wait = True
                    _logger.info(
                        "waiting for NPU card; holders=%s",
                        self._holders_locked())
                self._warn_dead_cards_locked()
                pool_size = len(self._allowed)
                if timeout is None:
                    self._cond.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CardAcquireTimeout(
                        f"All {pool_size} NPU devices are currently acquired "
                        f"(waited {timeout}s); holders={self._holders_locked()}",
                        pool_size=pool_size, waited_sec=timeout)
                self._cond.wait(timeout=remaining)

    @contextmanager
    def acquire_context(self, timeout: float | None = None,
                        owner: str = "") -> Iterator[int]:
        """Context-managed acquire: yield a card, release on exit (incl. exceptions)."""
        card = self.acquire(timeout=timeout, owner=owner)
        try:
            yield card
        finally:
            self.release(card)

    def release(self, npu_id: int) -> None:
        """Release a previously acquired NPU device and wake any waiters."""
        with self._cond:
            self._acquired.pop(npu_id, None)
            self._acquired_at.pop(npu_id, None)
            self._cond.notify_all()

    def list_available(self) -> list[int]:
        """Return list of currently available NPU device IDs."""
        with self._cond:
            return [i for i in self._allowed if i not in self._acquired]

    def list_acquired(self) -> list[int]:
        """Return list of currently acquired NPU device IDs."""
        with self._cond:
            return sorted(self._acquired)

    def acquired_holders(self) -> dict[int, str]:
        """Return ``{card: owner}`` snapshot (§step-95 attribution)."""
        with self._cond:
            return dict(self._acquired)

    @property
    def total_devices(self) -> int:
        return len(self._allowed)

    @property
    def available_count(self) -> int:
        with self._cond:
            return len(self._allowed) - len(self._acquired)
