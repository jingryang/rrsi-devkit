"""L2 Application — batch runner: manifest-driven multi-op dispatch.

See docs/plan/self-evolution/43-subprocess-card-pool-analysis.md (L3) and
44-subprocess-card-pool-impl.md (L4). Stage 2 = subprocess-level card pool: a
shared ``NPUSlotManager`` is threaded into every ``dispatch`` call; cards are
each op takes ONE whole-op lease at the dispatch boundary (``resolve_op_card``
the stages), so a run's LLM-thinking spans (design/codegen) hold no card and
other runs' NPU subprocesses can reuse freed cards. The stage-1 run-level
``card_queue`` is eliminated (§2.5 single path — card allocation lives only in
``NPUSlotManager``).

Layering (§1.1): L2 imports L4 (exceptions) + L3 (runtime_config, for the
probe timeout; ``build_shared_card_pool``, the L3 seam that constructs the
L6 card-pool primitive — L2 → L6 directly is forbidden, so the
``NPUSlotManager`` instance is obtained via the L3 factory) + stdlib only.
Does NOT import L1 (cli) — run_cmd click defaults are not needed because
dispatch reads task_request via .get() with its own fallbacks (equivalent to
the click defaults); build_task_request merges only top_defaults +
task_item (npu_id is the task's hard-pin or None). The bounded NPU count
probe is implemented inline (see _probe_npu_card_count_bounded).
"""

from __future__ import annotations

import logging
import re
import shutil
import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ascendc_devkit.application.dispatcher import dispatch
from ascendc_devkit.application.op_dir_resolver import (
    resolve_op_dir, OpDirResolveError,
)
from ascendc_devkit.orchestration.profile_loader import (
    list_profiles, load_profile,
)
from ascendc_devkit.domain.exceptions import ConfigError
from ascendc_devkit.domain.exit_codes import EX_GENERAL, EX_OK, EX_USAGE
from ascendc_devkit.infra.workspace import new_run_id
from ascendc_devkit.orchestration.card_pool import build_shared_card_pool

_log = logging.getLogger(__name__)

# Top-level manifest keys that are batch-level config (NOT single-op defaults
# propagated into each task_request).
_RESERVED_TOP = {"cards", "design_concurrency", "tasks"}


@dataclass(frozen=True)
class BatchManifest:
    """Parsed batch manifest (wrapper around a list of single-op task_requests).

    - cards / design_concurrency: batch-level knobs (None = unset).
    - top_defaults: non-reserved top-level fields, applied to every task as
      single-op defaults (overridable per task).
    - tasks: list of per-op field dicts; each becomes a task_request after
      merge with top_defaults + the pool-assigned npu_id.
    """
    cards: list[int] | None
    design_concurrency: int | None
    top_defaults: dict
    tasks: list[dict]


def load_manifest(path) -> BatchManifest:
    """Parse + loading-time validate a batch manifest (§1.3 fail-fast).

    Validates: top-level is a mapping; cards is an int list if present;
    design_concurrency is an int if present; tasks is a non-empty list; each
    task is a mapping with a non-empty op_dir. Unknown task fields are NOT
    rejected (would need the run_cmd dest set, but L2 cannot import L1 —
    layering); dispatch's .get() defaults mean a typo'd field is silently
    skipped rather than crashing, acceptable for stage 1 (see L4 §2).
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(str(path), "manifest must be a YAML mapping")

    cards = raw.get("cards")
    if cards is not None:
        if not isinstance(cards, list) or not all(isinstance(c, int) for c in cards):
            raise ConfigError(str(path), "cards must be a list of ints")
        cards = list(cards)

    design_concurrency = raw.get("design_concurrency")
    if design_concurrency is not None and not isinstance(design_concurrency, int):
        raise ConfigError(str(path), "design_concurrency must be an int")

    tasks = raw.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ConfigError(str(path), "tasks must be a non-empty list")

    top_defaults = {k: v for k, v in raw.items() if k not in _RESERVED_TOP}

    validated: list[dict] = []
    for i, t in enumerate(tasks):
        if not isinstance(t, dict):
            raise ConfigError(str(path), f"task[{i}] must be a mapping")
        if not t:
            raise ConfigError(
                str(path),
                f"task[{i}] is empty — provide op_dir or target_repo/op_name")
        validated.append(dict(t))

    return BatchManifest(
        cards=cards,
        design_concurrency=design_concurrency,
        top_defaults=top_defaults,
        tasks=validated,
    )


def _filter_healthy_cards(pool: list[int], timeout_sec: float) -> list[int]:
    """Return the subset of *pool* whose cards can actually open a device context.

    Dead-card filtering is the batch runner's own responsibility (it owns the
    resolved pool before ``build_shared_card_pool``): a card may be "free" in
    Python bookkeeping yet unopenable on the driver side after subprocess-zombie
    context leaks. The probe policy is a single point — ``orchestration/npu_probe.py
    ::healthy_cards`` (L3), shared with the dispatcher NPU smoke (L2 cannot import
    L6 probe_device directly — layer matrix L2->L3,L4,L7): serial per-card bounded
    subprocess (P113 — parallel NPU init races the driver and can fail even healthy
    cards). Unhealthy cards are logged at WARNING (observable, §1.2) and dropped;
    an all-dead pool is a ConfigError, never a silent 0-card run.
    """
    from ascendc_devkit.orchestration.npu_probe import healthy_cards

    healthy = healthy_cards(list(pool), timeout_sec)
    for card in pool:
        if card not in healthy:
            _log.warning(
                "NPU card %d probe failed — dropped from batch card pool %s",
                card, pool,
            )
    return healthy


def resolve_card_pool(manifest: BatchManifest, cli_cards=None) -> list[int]:
    """Resolve the card pool via four-tier fallback (L4 §3):
    manifest.cards (authority) > cli --cards > bounded NPU probe > ConfigError.

    Then validates every per-task npu_id (if declared) is inside the pool — a
    hard pin to a card outside the pool is a config error, not a runtime
    surprise. Then drops unhealthy cards (driver-side open-device probe), so a
    half-broken box (one card with leaked context) still runs on the healthy
    cards instead of aborting the whole batch. Returns the pool as a list of
    int device ids.
    """
    if manifest.cards is not None:
        pool = list(manifest.cards)
    elif cli_cards is not None:
        pool = list(cli_cards)
    else:
        n = _probe_npu_card_count_bounded()
        if n is None:
            raise ConfigError(
                "batch",
                "NPU card probe failed or timed out; declare 'cards' in the "
                "manifest or pass --cards explicitly",
            )
        pool = list(range(n))

    if not pool:
        raise ConfigError(
            "batch",
            "card pool resolved empty — declare non-empty 'cards' in the "
            "manifest or pass --cards explicitly",
        )

    for i, t in enumerate(manifest.tasks):
        if "npu_id" in t and t["npu_id"] not in pool:
            raise ConfigError(
                "batch",
                f"task[{i}] npu_id={t['npu_id']} is outside the card pool {pool}",
            )

    from ascendc_devkit.orchestration.runtime_config import hw_probe_timeout_sec

    healthy = _filter_healthy_cards(pool, hw_probe_timeout_sec())
    if not healthy:
        raise ConfigError(
            "batch",
            "all resolved cards failed the open-device probe; every card in the "
            f"pool {pool} is unavailable (driver context-pool exhaustion? check "
            "zombie processes or restart the container)",
        )
    if healthy != pool:
        _log.info("card pool %s -> healthy subset %s", pool, healthy)
        # m5: 硬 pin 复核须在健康过滤之后——pin 到"池内但被探针过滤掉"的卡会在运行期
        # 才炸（507033 / TsdOpen），早报 ConfigError 与"outside the card pool"同界
        # （§3.7 诚实失败，不静默运行期炸）。healthy==pool 时此复核对 healthy 恒成立，
        # 但保留无条件复核更稳。
        for i, t in enumerate(manifest.tasks):
            if "npu_id" in t and t["npu_id"] not in healthy:
                raise ConfigError(
                    "batch",
                    f"task[{i}] npu_id={t['npu_id']} is pinned to a card dropped "
                    f"by the open-device health probe (healthy subset {healthy}) — "
                    "re-pin or remove the hard pin",
                )
    return healthy


def _probe_npu_card_count_bounded():
    """Best-effort bounded NPU device-count probe. Returns int (>0) or None.

    Last-resort fallback for resolve_card_pool when neither manifest nor CLI
    declare cards. The NPU driver may hang on hdcdrv_connect_wait_reply (a
    kernel ioctl with NO timeout and NO Python-visible exception — see
    adapters/npu/detect.py for the field record: 7.4s degraded, 13min+ stuck),
    so torch_npu.npu.device_count() is run in a daemon thread bounded by
    hw_probe_timeout_sec(); an overrunning thread is abandoned. npu-smi info -l
    (its "Total Count" line) is the fallback when torch_npu is unavailable.
    None on any failure/timeout so resolve_card_pool raises ConfigError asking
    for explicit 'cards' (§3.7: no silent 0-card degradation).

    NOT a §2.5 duplicate of verify_env / detect.py: this probes for a card
    COUNT (card-pool decision), whereas verify_env._check_* are diagnostic
    panel entries and detect.py probes the chip GENERATION. Different
    responsibilities; torch_npu.npu.device_count() is the single underlying
    API (the physical source), called from multiple sites like any low-level
    API — not two implementations of one responsibility (L4 §2).
    """
    from ascendc_devkit.orchestration.runtime_config import hw_probe_timeout_sec
    timeout = hw_probe_timeout_sec()

    n = _probe_via_torch_npu(timeout)
    if n and n > 0:
        return n
    n = _probe_via_npu_smi(timeout)
    if n and n > 0:
        return n
    return None


def _probe_via_torch_npu(timeout_sec: float):
    holder: dict[str, int] = {}

    def _run() -> None:
        try:
            import torch_npu  # optional at import time
            holder["n"] = int(torch_npu.npu.device_count())
        except Exception:
            holder["n"] = -1

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout_sec)
    if t.is_alive():
        _log.warning(
            "torch_npu device_count() probe timed out after %ss (driver hang?)",
            timeout_sec,
        )
        return None  # abandon the daemon thread (cleaned up at process exit)
    n = holder.get("n", -1)
    return n if n >= 0 else None


def _probe_via_npu_smi(timeout_sec: float):
    npu_smi = shutil.which("npu-smi")
    if not npu_smi:
        return None
    try:
        result = subprocess.run(
            [npu_smi, "info", "-l"],
            capture_output=True, text=True, timeout=timeout_sec, check=False,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    m = re.search(r"Total\s+Count\s*:\s*(\d+)", result.stdout)
    return int(m.group(1)) if m else None


def build_task_request(
    manifest: BatchManifest, task_item: dict,
) -> dict:
    """Merge into a single-op task_request:
    top_defaults (low) < task_item (high), then set npu_id.

    ``npu_id`` is the task's HARD-PIN card (``--npu-id`` equivalent) or ``None``
    (no preference → the op lease auto-picks from the shared
    pool). Stage 2 no longer assigns a run-level card here: card acquisition
    moved to the dispatch op boundary (op-level lease, P13/step-116).
    Fields absent from both top_defaults and task_item are NOT filled here —
    dispatch reads task_request via .get() with its own fallbacks (equivalent
    to run_cmd click defaults), so this stays L2-clean (no L1 import, §1.1).
    """
    tr = {**manifest.top_defaults, **task_item}
    tr["npu_id"] = task_item.get("npu_id")
    return tr


# ---------------------------------------------------------------------------
# run_batch — concurrent dispatch over a shared card pool (stage 2: subprocess-level)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunOutcome:
    """One task's outcome in a batch run."""
    op_name: str
    exit_code: int
    run_id: str | None
    # Q6: eval score read from state_snapshot.json (None if cannbench_eval wasn't
    # reached or the snapshot is unreadable). workflow-done (exit_code==0) ≠
    # eval-passed — summary surfaces this so "X/Y succeeded" isn't misleading.
    eval_score: float | None = None
    eval_pass_rate: float | None = None


@dataclass(frozen=True)
class BatchResult:
    """Aggregate outcome of a batch run (first-run or resume).

    ``batch_id`` is the batch identity; ``RunOutcome.run_id`` is each op's
    ``execution_id`` (= run_id), whose run dir lives at
    ``output/<batch_id>/<execution_id>/``. On resume the execution_ids are the
    pre-assigned ones read back from the directory listing (no index file).
    """
    batch_id: str
    results: list[RunOutcome]

    def summary(self) -> str:
        if not self.results:
            return f"batch {self.batch_id}: no tasks"
        ok = sum(1 for r in self.results if r.exit_code == EX_OK)
        # Q6: eval-passed count (overall_score > 0, mirrors loss_aggregator L48).
        # workflow-done ≠ eval-passed — surface both so a 0-eval batch doesn't
        # read as "succeeded" (batch 20260727_225324 was 2/5 done, 0/5 eval-passed).
        eval_passed = sum(1 for r in self.results
                          if r.eval_score is not None and r.eval_score > 0)
        lines = [f"batch {self.batch_id}: {ok}/{len(self.results)} "
                 f"workflow-done, {eval_passed}/{len(self.results)} eval-passed"]
        for r in self.results:
            tag = "OK  " if r.exit_code == EX_OK else f"FAIL(exit {r.exit_code})"
            if r.eval_score is not None:
                eval_str = f"eval={r.eval_score:.2f}/{r.eval_pass_rate:.0f}%"
            else:
                eval_str = "eval=-"
            lines.append(f"  [{tag}] {r.op_name}  exec={r.run_id or '-'}  {eval_str}")
        return "\n".join(lines)


def _resolve_max_workers(design_concurrency, n_tasks) -> int:
    """Thread-pool size: design_concurrency if set, else n_tasks (full-parallel).

    When design_concurrency is None we pass n_tasks explicitly — Python's
    ThreadPoolExecutor(max_workers=None) decays to min(32, cpu+4), which would
    silently cap a large batch; an explicit task count gives true full-parallel
    (L3 §2.2b). design_concurrency is a LOCAL-resource valve (CPU/memory/
    handles), orthogonal to the card pool (NPU critical resource). Stage 2
    subprocess-level pinning makes concurrency > cards pay off: extra runs hold
    no card during LLM thinking and queue only at their NPU subprocess (L4 §8).
    """
    if design_concurrency is not None:
        return design_concurrency
    return n_tasks


def _should_degrade(n_tasks) -> bool:
    """A single task skips the thread pool (L3 §2.3): direct synchronous
    dispatch with the shared pool — no batch overhead, still through dispatch
    (the single path, §2.5)."""
    return n_tasks == 1


def run_batch(
    manifest: BatchManifest,
    card_pool: list[int],
    progress_callback=None,
) -> BatchResult:
    """First-run batch: assign a fresh ``batch_id``, delegate to ``_run_batch``
    which scopes each task's ``output_root`` to ``<root>/<batch_id>`` (so each
    op's run lands at ``output/<batch_id>/<exec>/``) and pre-assigns each task
    an execution_id (run_id). The returned ``BatchResult.batch_id`` is the
    resume handle (``run --resume <batch_id>``).
    """
    return _run_batch(manifest, card_pool, new_run_id(), progress_callback)


def resume_batch(
    batch_id: str,
    output_root: str = "output",
    cli_cards: list[int] | None = None,
    progress_callback=None,
) -> BatchResult:
    """Resume a batch by id — the directory listing IS the batch→ops map (no
    index file, §2.5 single source). Lists ``output/<batch_id>/<exec>/`` dirs
    (each with a ``state_snapshot.json`` = a real run), rebuilds a resume
    manifest (``resume_from=exec`` per task), resolves the card pool
    (``cli_cards`` or bounded probe), and reuses ``_run_batch`` with the SAME
    ``batch_id`` so resumed runs stay under ``output/<batch_id>/``. Reuses
    single-op resume end-to-end (dispatch's ``resume_from`` path). Raises
    ``ConfigError`` if the batch dir is absent or has no executions.
    """
    batch_dir = Path(output_root).resolve() / batch_id
    if not batch_dir.is_dir():
        raise ConfigError(
            str(batch_dir),
            f"batch '{batch_id}' not found under {output_root}/ "
            f"(to resume a single run use its run_id; to resume a batch in a "
            f"non-default output pass the matching --output-root)")
    exec_dirs = sorted(
        d for d in batch_dir.iterdir()
        if d.is_dir() and (d / "state_snapshot.json").exists())
    if not exec_dirs:
        raise ConfigError(
            str(batch_dir),
            f"batch '{batch_id}' has no executions to resume")
    tasks = [{"resume_from": d.name} for d in exec_dirs]
    manifest = BatchManifest(
        cards=None, design_concurrency=None,
        top_defaults={"output_root": output_root}, tasks=tasks)
    pool = resolve_card_pool(manifest, cli_cards=cli_cards)
    return _run_batch(manifest, pool, batch_id, progress_callback)


def _run_batch(
    manifest: BatchManifest,
    card_pool: list[int],
    batch_id: str,
    progress_callback=None,
) -> BatchResult:
    """Shared body for ``run_batch`` (fresh ``batch_id``) and ``resume_batch``
    (existing ``batch_id``).

    Stage-2 subprocess-level pinning: builds a shared ``NPUSlotManager`` from
    ``card_pool`` and threads it into every ``dispatch(card_pool=...)`` call.
    Cards are acquired/released at each NPU subprocess boundary (via
    the dispatch op lease), NOT at run entry — a run's
    LLM-thinking spans (design/codegen) hold no card, so other runs' NPU
    subprocesses can reuse freed cards. A per-task ``npu_id`` hard-pins that
    card (skips the pool). One task's failure never aborts the others.

    Batch-id scoping (layered ids, L4 §54): every task's ``output_root`` is
    set to ``<root>/<batch_id>`` so runs land at ``output/<batch_id>/<exec>/``;
    first-run tasks are pre-assigned an ``execution_id`` (``run_id``) BEFORE
    dispatch, so the exec dir is deterministic with zero concurrency race.
    Resume tasks carry ``resume_from`` and reuse the exec dir already on disk.
    """
    root = manifest.top_defaults.get("output_root", "output")
    nested_root = f"{root}/{batch_id}"
    for t in manifest.tasks:
        if not t.get("resume_from"):
            t.setdefault("run_id", new_run_id())
        t["output_root"] = nested_root

    pool = build_shared_card_pool(card_pool)
    tasks = manifest.tasks
    if _should_degrade(len(tasks)):
        return BatchResult(
            batch_id=batch_id,
            results=[_dispatch_one(manifest, tasks[0], pool, progress_callback)])
    max_workers = _resolve_max_workers(manifest.design_concurrency, len(tasks))
    results: dict[int, RunOutcome] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(_dispatch_one, manifest, task, pool, progress_callback): i
            for i, task in enumerate(tasks)
        }
        for fut, i in futures.items():
            results[i] = fut.result()
    return BatchResult(batch_id=batch_id,
                       results=[results[i] for i in range(len(tasks))])


def _read_eval_score(tr, exec_id) -> tuple[float | None, float | None]:
    """Q6: read ``eval_result`` from ``<output_root>/<exec_id>/state_snapshot.json``.

    Returns ``(overall_score, pass_rate)``; ``(None, None)`` when the snapshot is
    missing or unreadable (resume mid-flight / exited before cannbench_eval /
    write failure). dict直读 — no ``State.from_snapshot`` coupling (batch only
    needs two numbers). Never raises.
    """
    if not exec_id:
        return None, None
    output_root = tr.get("output_root")
    if not output_root:
        return None, None
    snap = Path(output_root) / exec_id / "state_snapshot.json"
    try:
        data = json.loads(snap.read_text())
        ev = data.get("eval_result") or {}
        return ev.get("overall_score"), ev.get("pass_rate")
    except Exception as e:
        # Distinguish "missing" from "present-but-corrupt" for debugging — a bare
        # except made a malformed snapshot indistinguishable from no snapshot (m3).
        _log.debug("eval score read failed for %s: %s", snap, e)
        return None, None


def _dispatch_one(manifest, task_item, pool, progress_callback) -> RunOutcome:
    """Build task_request, resolve op_dir (L1->L2 boundary, mirrors run_cmd),
    dispatch with the shared card pool. Never raises — failures become non-zero
    RunOutcomes so the batch continues (one task's failure must not abort the
    others)."""
    tr = build_task_request(manifest, task_item)
    # execution_id for RunOutcome: first-run task carries run_id (pre-assigned
    # in _run_batch); resume task carries resume_from (= the exec dir name).
    exec_id = tr.get("run_id") or tr.get("resume_from")
    if tr.get("op_dir") and not tr.get("resume_from"):
        try:
            res = resolve_op_dir(
                tr["op_dir"],
                profile_override=tr.get("repo_profile"),
                repo_root_override=tr.get("repo_root"),
                op_name_override=tr.get("op_name") or None,
            )
            tr.update({
                "repo_profile": res.profile_name,
                "repo_root": res.repo_root,
                "rel_op_dir": res.rel_op_dir,
                "full_op_name": res.full_op_name,
                "op_name": res.op_name,
                "variant_name": res.variant_name,
                "target_repo": tr.get("target_repo") or res.repo_root,
            })
            # P0: profile auto-detection fallback — when op_dir path segments
            # don't match any known profile (e.g. cann-bench-batch working
            # dirs whose parent dir is named "cann-bench-batch" rather than
            # "cann-bench"), scan known profiles against target_repo structure.
            if not tr.get("repo_profile") and tr.get("target_repo"):
                _target = Path(tr["target_repo"])
                for _pn in list_profiles():
                    try:
                        _prof = load_profile(_pn)
                        for _v in _prof.build_variants:
                            if (_target / _v.match_prefix).exists():
                                tr["repo_profile"] = _pn
                                tr["repo_root"] = str(_target)
                                _log.info(
                                    "auto-detected profile=%s for op_dir=%s "
                                    "(target_repo matched %s)",
                                    _pn, tr.get("op_dir"), _v.match_prefix)
                                break
                    except Exception as exc:
                        _log.warning(
                            "auto-detect profile for op_dir=%s failed: %s",
                            tr.get("op_dir"), exc, exc_info=True)
                        continue
                    if tr.get("repo_profile"):
                        break
        except OpDirResolveError as e:
            _log.error("op_dir resolve failed for %s: %s", tr.get("op_dir"), e)
            return RunOutcome(_label(tr, task_item), EX_USAGE, exec_id)
    try:
        # [integrity 20260827] tr 键集快照原在此处经 stdlib logging 打（仅控制台）；
        # step 104 删除——dispatcher 入口已有同数据的 dispatch-enter 行（Logger，
        # 双写 run.log + 控制台），此处重复且发生在 bind_run_log 之前进不了
        # run.log（§2.5 唯一通路）。
        exit_code = dispatch(tr, progress_callback, card_pool=pool)
    except Exception as exc:
        # step 104 可诊断：死亡 exec 的遗言必须进它自己的 run.log。此前走 stdlib
        # logging（无 handler → lastResort 裸 stderr），run.log 只残留 constructed
        # 一行、真因只在共享控制台。bind_run_log 在 dispatch 内已绑定且 dispatch
        # 返回/抛出后不解绑（线程生命周期内保持），此处 Logger 双写 run.log+控制台。
        from ascendc_devkit.infra.logger import Logger
        Logger.error(f"dispatch failed for {tr.get('op_dir')}: {exc!r}", exc_info=True)
        return RunOutcome(_label(tr, task_item), EX_GENERAL, exec_id)
    # Q6: best-effort read eval score from state_snapshot.json. done ≠ passed.
    eval_score, eval_pass_rate = _read_eval_score(tr, exec_id)
    return RunOutcome(_label(tr, task_item), exit_code, exec_id,
                      eval_score=eval_score, eval_pass_rate=eval_pass_rate)


def _label(tr, task_item) -> str:
    """Human-readable task label for RunOutcome (resolved op_name preferred)."""
    return (
        tr.get("op_name")
        or tr.get("full_op_name")
        or Path(task_item.get("op_dir", "")).name
        or "?"
    )
