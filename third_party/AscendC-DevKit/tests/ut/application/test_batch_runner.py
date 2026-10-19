"""UT for L2 batch_runner (batch fusion, stage 1).

See docs/plan/self-evolution/42-batch-fusion-impl.md §7 Phase 1.
Covers: manifest wrapper parsing + loading-time validation, card-pool
four-tier fallback, manifest→task_request mapping. Pure logic, no backend.
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from ascendc_devkit.domain.exceptions import ConfigError
from ascendc_devkit.adapters.npu.slot import NPUSlotManager
from ascendc_devkit.application.batch_runner import (
    BatchManifest,
    load_manifest,
    resolve_card_pool,
    build_task_request,
    run_batch,
    resume_batch,
    BatchResult,
    RunOutcome,
    _resolve_max_workers,
    _should_degrade,
    _read_eval_score,
)
from ascendc_devkit.infra.workspace import new_run_id


def _write_manifest(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "batch.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# load_manifest — wrapper shape + loading-time validation (§1.3)
# ---------------------------------------------------------------------------


class TestLoadManifest:
    def test_wrapper_shape(self, tmp_path):
        p = _write_manifest(tmp_path, {
            "cards": [0, 1, 2],
            "design_concurrency": 4,
            "output_root": "out",
            "tasks": [
                {"op_dir": "/a/opA", "requirement_path": "/r.md"},
                {"op_dir": "/a/opB"},
            ],
        })
        m = load_manifest(p)
        assert m.cards == [0, 1, 2]
        assert m.design_concurrency == 4
        assert m.top_defaults["output_root"] == "out"
        assert len(m.tasks) == 2
        assert m.tasks[0]["op_dir"] == "/a/opA"

    def test_top_defaults_collected(self, tmp_path):
        """Non-reserved top-level fields become single-op defaults."""
        p = _write_manifest(tmp_path, {
            "output_root": "outX",
            "design_target_chip": "A2",
            "tasks": [{"op_dir": "/a/opA"}],
        })
        m = load_manifest(p)
        assert m.top_defaults == {"output_root": "outX", "design_target_chip": "A2"}

    def test_cards_and_design_concurrency_optional(self, tmp_path):
        p = _write_manifest(tmp_path, {"tasks": [{"op_dir": "/a/opA"}]})
        m = load_manifest(p)
        assert m.cards is None
        assert m.design_concurrency is None

    def test_tasks_empty_rejected(self, tmp_path):
        p = _write_manifest(tmp_path, {"tasks": []})
        with pytest.raises(ConfigError):
            load_manifest(p)

    def test_task_empty_dict_rejected(self, tmp_path):
        """An empty task dict can locate no operator — reject at load (§1.3).
        op_dir itself is NOT required (matches run_cmd: target_repo/repo_profile/
        op_name is an equivalent locator; _dispatch_one skips resolve_op_dir
        when op_dir is absent)."""
        p = _write_manifest(tmp_path, {"tasks": [{}]})
        with pytest.raises(ConfigError):
            load_manifest(p)

    # NOTE: unknown-field typo warning deferred to follow-up — it needs the
    # run_cmd dest set, but L2 may not import L1 (layering L2->L3,L4,L7 only);
    # a hand-maintained constant would drift (§1.2). dispatch's .get() defaults
    # mean a typo'd field is silently skipped (no KeyError), acceptable for now.


# ---------------------------------------------------------------------------
# resolve_card_pool — four-tier fallback (manifest > cli > probe > error)
# ---------------------------------------------------------------------------


class TestResolveCardPool:
    """Pure-logic card-pool tests: probe/health-check subprocesses are mocked,
    so no real NPU dependency (UT semantics, §3.5)."""

    @staticmethod
    def _healthy_identity(pool, timeout):
        return pool

    def test_manifest_authoritative_over_cli_and_probe(self, tmp_path, monkeypatch):
        m = load_manifest(_write_manifest(tmp_path, {
            "cards": [0, 1, 2], "tasks": [{"op_dir": "/a"}],
        }))
        # probe must NOT be called when manifest declares cards
        monkeypatch.setattr(
            "ascendc_devkit.application.batch_runner._probe_npu_card_count_bounded",
            lambda: 99,
        )
        monkeypatch.setattr(
            "ascendc_devkit.application.batch_runner._filter_healthy_cards",
            self._healthy_identity,
        )
        assert resolve_card_pool(m, cli_cards=[9]) == [0, 1, 2]

    def test_cli_override_when_no_manifest_cards(self, tmp_path, monkeypatch):
        m = load_manifest(_write_manifest(tmp_path, {"tasks": [{"op_dir": "/a"}]}))
        monkeypatch.setattr(
            "ascendc_devkit.application.batch_runner._probe_npu_card_count_bounded",
            lambda: 99,
        )
        monkeypatch.setattr(
            "ascendc_devkit.application.batch_runner._filter_healthy_cards",
            self._healthy_identity,
        )
        assert resolve_card_pool(m, cli_cards=[3, 4]) == [3, 4]

    def test_probe_fallback(self, tmp_path, monkeypatch):
        m = load_manifest(_write_manifest(tmp_path, {"tasks": [{"op_dir": "/a"}]}))
        monkeypatch.setattr(
            "ascendc_devkit.application.batch_runner._probe_npu_card_count_bounded",
            lambda: 3,
        )
        monkeypatch.setattr(
            "ascendc_devkit.application.batch_runner._filter_healthy_cards",
            self._healthy_identity,
        )
        assert resolve_card_pool(m) == [0, 1, 2]

    def test_probe_failure_raises(self, tmp_path, monkeypatch):
        """Probe returning None (timeout/failure) → ConfigError, no silent 0."""
        m = load_manifest(_write_manifest(tmp_path, {"tasks": [{"op_dir": "/a"}]}))
        monkeypatch.setattr(
            "ascendc_devkit.application.batch_runner._probe_npu_card_count_bounded",
            lambda: None,
        )
        with pytest.raises(ConfigError):
            resolve_card_pool(m)

    def test_per_task_npu_id_outside_pool_rejected(self, tmp_path, monkeypatch):
        m = load_manifest(_write_manifest(tmp_path, {
            "cards": [0, 1], "tasks": [{"op_dir": "/a", "npu_id": 5}],
        }))
        monkeypatch.setattr(
            "ascendc_devkit.application.batch_runner._filter_healthy_cards",
            self._healthy_identity,
        )
        with pytest.raises(ConfigError):
            resolve_card_pool(m)

    def test_per_task_npu_id_inside_pool_ok(self, tmp_path, monkeypatch):
        m = load_manifest(_write_manifest(tmp_path, {
            "cards": [0, 1, 2], "tasks": [{"op_dir": "/a", "npu_id": 1}],
        }))
        monkeypatch.setattr(
            "ascendc_devkit.application.batch_runner._filter_healthy_cards",
            self._healthy_identity,
        )
        assert resolve_card_pool(m) == [0, 1, 2]

    def test_unhealthy_cards_dropped_from_pool(self, tmp_path, monkeypatch):
        """Bad cards (driver context-pool exhaustion) are filtered out; the batch
        proceeds on the healthy subset instead of aborting (§3.7: honest signal —
        the drop is logged, not silent)."""
        m = load_manifest(_write_manifest(tmp_path, {
            "cards": [0, 1, 2], "tasks": [{"op_dir": "/a"}],
        }))
        monkeypatch.setattr(
            "ascendc_devkit.application.batch_runner._filter_healthy_cards",
            lambda pool, timeout: [card for card in pool if card != 0],
        )
        assert resolve_card_pool(m) == [1, 2]

    def test_per_task_npu_id_pinned_to_dropped_card_rejected(self, tmp_path, monkeypatch):
        """m5: a task hard-pinning npu_id to a card that the health probe DROPPED
        must be rejected at config time (honest ConfigError), not left to fail
        silently at runtime on a dead card."""
        m = load_manifest(_write_manifest(tmp_path, {
            "cards": [0, 1, 2], "tasks": [{"op_dir": "/a", "npu_id": 0}],
        }))
        monkeypatch.setattr(
            "ascendc_devkit.application.batch_runner._filter_healthy_cards",
            lambda pool, timeout: [card for card in pool if card != 0],
        )
        with pytest.raises(ConfigError) as ei:
            resolve_card_pool(m)
        assert "dropped by the open-device health probe" in str(ei.value)
        assert "npu_id=0" in str(ei.value)

    def test_all_cards_unhealthy_raises(self, tmp_path, monkeypatch):
        """Every resolved card failing the open-device probe → ConfigError, never
        a silent 0-card run."""
        m = load_manifest(_write_manifest(tmp_path, {
            "cards": [0, 1], "tasks": [{"op_dir": "/a"}],
        }))
        monkeypatch.setattr(
            "ascendc_devkit.application.batch_runner._filter_healthy_cards",
            lambda pool, timeout: [],
        )
        with pytest.raises(ConfigError) as ei:
            resolve_card_pool(m)
        assert "open-device probe" in str(ei.value)


# ---------------------------------------------------------------------------
# build_task_request — merge priority: run_cmd default < top < task; npu_id
# ---------------------------------------------------------------------------


class TestBuildTaskRequest:
    def test_top_defaults_applied(self, tmp_path):
        m = load_manifest(_write_manifest(tmp_path, {
            "output_root": "outTop", "design_target_chip": "A2",
            "tasks": [{"op_dir": "/a/opA"}],
        }))
        tr = build_task_request(m, m.tasks[0])
        assert tr["output_root"] == "outTop"
        assert tr["design_target_chip"] == "A2"

    def test_task_overrides_top(self, tmp_path):
        m = load_manifest(_write_manifest(tmp_path, {
            "output_root": "outTop",
            "tasks": [{"op_dir": "/a/opA", "output_root": "outTask"}],
        }))
        tr = build_task_request(m, m.tasks[0])
        assert tr["output_root"] == "outTask"

    def test_npu_id_none_when_task_has_none(self, tmp_path):
        """Stage 2: no task npu_id → tr['npu_id'] is None (card acquired per
        subprocess from the shared pool, NOT assigned at run level)."""
        m = load_manifest(_write_manifest(tmp_path, {
            "tasks": [{"op_dir": "/a/opA"}],
        }))
        tr = build_task_request(m, m.tasks[0])
        assert tr["npu_id"] is None

    def test_task_npu_id_hard_pin(self, tmp_path):
        """Per-task npu_id is a hard-pin (carried straight into task_request)."""
        m = load_manifest(_write_manifest(tmp_path, {
            "tasks": [{"op_dir": "/a/opA", "npu_id": 5}],
        }))
        tr = build_task_request(m, m.tasks[0])
        assert tr["npu_id"] == 5

    def test_op_dir_carried(self, tmp_path):
        m = load_manifest(_write_manifest(tmp_path, {
            "tasks": [{"op_dir": "/a/opA"}],
        }))
        tr = build_task_request(m, m.tasks[0])
        assert tr["op_dir"] == "/a/opA"


# ---------------------------------------------------------------------------
# helpers — max_workers / degrade decision (pure functions)
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_resolve_max_workers_uses_design_concurrency(self):
        assert _resolve_max_workers(4, 10) == 4

    def test_resolve_max_workers_none_uses_task_count(self):
        # None must NOT decay to Python's min(32, cpu+4) — explicit task count
        # gives true full-parallel (L3 §2.2b).
        assert _resolve_max_workers(None, 10) == 10

    def test_should_degrade_single(self):
        assert _should_degrade(1) is True

    def test_should_degrade_multi(self):
        assert _should_degrade(2) is False


# ---------------------------------------------------------------------------
# run_batch — concurrent dispatch + card pool + 1-task degradation
# ---------------------------------------------------------------------------


def _fake_resolve_op_dir(op_dir, **kwargs):
    """Minimal resolved object — only the fields run_batch forwards. op_name
    derives from the op_dir tail so distinct ops get distinct labels."""
    name = Path(op_dir).name
    return SimpleNamespace(
        confidence="high",
        profile_name="profile",
        repo_root="/repo",
        rel_op_dir=name,
        full_op_name=name,
        op_name=name,
        variant_name="",
    )


class TestRunBatch:
    def test_shared_pool_threaded_to_dispatch(self, tmp_path, monkeypatch):
        """Both dispatches receive the SAME shared NPUSlotManager over the card
        set; each op takes ONE whole-op lease at the dispatch boundary (via
        resolve_op_card). run_batch only threads the pool."""
        m = load_manifest(_write_manifest(tmp_path, {
            "cards": [0, 1],
            "tasks": [{"op_dir": "/a/opA"}, {"op_dir": "/a/opB"}],
        }))
        seen_pools: list = []
        lock = threading.Lock()

        def fake_dispatch(tr, progress_callback=None, card_pool=None):
            with lock:
                seen_pools.append(card_pool)
            time.sleep(0.05)  # both workers run concurrently
            return 0

        monkeypatch.setattr("ascendc_devkit.application.batch_runner.dispatch", fake_dispatch)
        monkeypatch.setattr(
            "ascendc_devkit.application.batch_runner.resolve_op_dir", _fake_resolve_op_dir)
        result = run_batch(m, [0, 1])
        assert len(seen_pools) == 2
        # same shared instance, an NPUSlotManager over {0,1}
        assert seen_pools[0] is seen_pools[1]
        assert isinstance(seen_pools[0], NPUSlotManager)
        assert set(seen_pools[0].list_available()) == {0, 1}
        assert all(r.exit_code == 0 for r in result.results)

    def test_one_dispatch_exception_doesnt_abort_others(self, tmp_path, monkeypatch):
        """One task's dispatch raising → that task gets a non-zero RunOutcome,
        but the other still runs. (Card lease release on exception is the
        dispatch op-lease's job, covered in test_card_pin's dispatch lease
        symmetry; run_batch only guarantees one failure doesn't abort the
        batch.)"""
        m = load_manifest(_write_manifest(tmp_path, {
            "cards": [0],
            "tasks": [{"op_dir": "/a/opA"}, {"op_dir": "/a/opB"}],
        }))
        ran: list[str] = []
        lock = threading.Lock()

        def fake_dispatch(tr, progress_callback=None, card_pool=None):
            with lock:
                ran.append(tr["op_dir"])
            if tr["op_dir"] == "/a/opA":
                raise RuntimeError("boom")
            return 0

        monkeypatch.setattr("ascendc_devkit.application.batch_runner.dispatch", fake_dispatch)
        monkeypatch.setattr(
            "ascendc_devkit.application.batch_runner.resolve_op_dir", _fake_resolve_op_dir)
        result = run_batch(m, [0])
        assert set(ran) == {"/a/opA", "/a/opB"}  # both ran
        codes = {r.op_name: r.exit_code for r in result.results}
        assert any(c != 0 for c in codes.values())  # opA failed
        assert any(c == 0 for c in codes.values())  # opB succeeded

    def test_results_collected_with_summary(self, tmp_path, monkeypatch):
        m = load_manifest(_write_manifest(tmp_path, {
            "cards": [0, 1],
            "tasks": [{"op_dir": "/a/opA"}, {"op_dir": "/a/opB"}],
        }))
        codes = {"/a/opA": 0, "/a/opB": 2}

        def fake_dispatch(tr, progress_callback=None, card_pool=None):
            return codes[tr["op_dir"]]

        monkeypatch.setattr("ascendc_devkit.application.batch_runner.dispatch", fake_dispatch)
        monkeypatch.setattr(
            "ascendc_devkit.application.batch_runner.resolve_op_dir", _fake_resolve_op_dir)
        result = run_batch(m, [0, 1])
        assert isinstance(result, BatchResult)
        assert len(result.results) == 2
        assert {r.exit_code for r in result.results} == {0, 2}
        assert result.summary()  # non-empty summary

    def test_single_task_degrades_to_sync(self, tmp_path, monkeypatch):
        """1 task → no threadpool; direct dispatch with npu_id=None + shared pool."""
        m = load_manifest(_write_manifest(tmp_path, {
            "cards": [0],
            "tasks": [{"op_dir": "/a/opA"}],
        }))
        captured: list = []

        def fake_dispatch(tr, progress_callback=None, card_pool=None):
            captured.append((tr["npu_id"], card_pool))
            return 0

        monkeypatch.setattr("ascendc_devkit.application.batch_runner.dispatch", fake_dispatch)
        monkeypatch.setattr(
            "ascendc_devkit.application.batch_runner.resolve_op_dir", _fake_resolve_op_dir)
        run_batch(m, [0])
        assert len(captured) == 1  # dispatched exactly once (sync)
        npu_id, pool = captured[0]
        assert npu_id is None  # no hard-pin → None
        assert isinstance(pool, NPUSlotManager)

    def test_per_task_npu_id_hard_pin_respected(self, tmp_path, monkeypatch):
        """A per-task npu_id is a hard-pin → flows into task_request."""
        m = load_manifest(_write_manifest(tmp_path, {
            "cards": [0, 1, 2],
            "tasks": [{"op_dir": "/a/opA", "npu_id": 2}],
        }))
        seen: list[int] = []

        def fake_dispatch(tr, progress_callback=None, card_pool=None):
            seen.append(tr["npu_id"])
            return 0

        monkeypatch.setattr("ascendc_devkit.application.batch_runner.dispatch", fake_dispatch)
        monkeypatch.setattr(
            "ascendc_devkit.application.batch_runner.resolve_op_dir", _fake_resolve_op_dir)
        run_batch(m, [0, 1, 2])
        assert seen == [2]

    def test_design_concurrency_caps_workers(self, tmp_path, monkeypatch):
        """design_concurrency=2 + 4 tasks → at most 2 dispatches concurrent."""
        m = load_manifest(_write_manifest(tmp_path, {
            "cards": [0, 1, 2, 3],
            "design_concurrency": 2,
            "tasks": [{"op_dir": f"/a/op{i}"} for i in range(4)],
        }))
        active = 0
        peak = 0
        lock = threading.Lock()

        def fake_dispatch(tr, progress_callback=None, card_pool=None):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return 0

        monkeypatch.setattr("ascendc_devkit.application.batch_runner.dispatch", fake_dispatch)
        monkeypatch.setattr(
            "ascendc_devkit.application.batch_runner.resolve_op_dir", _fake_resolve_op_dir)
        run_batch(m, [0, 1, 2, 3])
        assert peak <= 2  # never exceeded design_concurrency


# ---------------------------------------------------------------------------
# batch_id hierarchy (L4 §54): layered ids + nested output_root + resume_batch
# ---------------------------------------------------------------------------

_RUN_ID_RE = re.compile(r"\d{8}-\d{6}-[0-9a-f]{6}")


class TestBatchIdHierarchy:
    """batch_id 分层：execution_id=run_id；output/<batch_id>/<exec>/ nested；
    filesystem IS the batch→ops map (no index file); resume_batch reuses
    single-op resume per execution."""

    def test_new_run_id_format_and_uniqueness(self):
        rid = new_run_id()
        assert _RUN_ID_RE.fullmatch(rid)
        assert new_run_id() != rid

    def test_run_batch_assigns_batch_id(self, tmp_path, monkeypatch):
        m = load_manifest(_write_manifest(tmp_path, {
            "cards": [0, 1],
            "tasks": [{"op_dir": "/a/opA"}, {"op_dir": "/a/opB"}],
        }))
        monkeypatch.setattr(
            "ascendc_devkit.application.batch_runner.dispatch",
            lambda tr, progress_callback=None, card_pool=None: 0)
        monkeypatch.setattr(
            "ascendc_devkit.application.batch_runner.resolve_op_dir",
            _fake_resolve_op_dir)
        result = run_batch(m, [0, 1])
        assert _RUN_ID_RE.fullmatch(result.batch_id)

    def test_output_root_scoped_to_batch_and_exec_id_injected(
            self, tmp_path, monkeypatch):
        """Each task's output_root → <root>/<batch_id> and run_id (exec_id) is
        pre-assigned BEFORE dispatch (deterministic, zero concurrency race)."""
        out = str(tmp_path / "out")
        m = load_manifest(_write_manifest(tmp_path, {
            "cards": [0, 1], "output_root": out,
            "tasks": [{"op_dir": "/a/opA"}, {"op_dir": "/a/opB"}],
        }))
        seen: dict[str, tuple] = {}

        def fake_dispatch(tr, progress_callback=None, card_pool=None):
            seen[tr["op_dir"]] = (tr["output_root"], tr.get("run_id"))
            return 0

        monkeypatch.setattr("ascendc_devkit.application.batch_runner.dispatch", fake_dispatch)
        monkeypatch.setattr(
            "ascendc_devkit.application.batch_runner.resolve_op_dir",
            _fake_resolve_op_dir)
        result = run_batch(m, [0, 1])
        for op_dir, (ort, rid) in seen.items():
            assert ort == f"{out}/{result.batch_id}"      # scoped nesting
            assert rid and _RUN_ID_RE.fullmatch(rid)      # exec_id injected
            op = Path(op_dir).name
            outcome = next(r for r in result.results if r.op_name == op)
            assert outcome.run_id == rid                   # RunOutcome carries exec_id

    def test_resume_batch_lists_dir_and_reuses_batch_id(self, tmp_path, monkeypatch):
        """resume_batch: directory listing IS the batch→ops map; reuses the
        SAME batch_id (no new id); each dispatch gets resume_from=exec_id +
        output_root=<root>/<batch_id> (stays nested under the batch)."""
        bid = "20260717-120000-bbbbbb"
        e1, e2 = "20260717-120000-cccccc", "20260717-120000-dddddd"
        out = tmp_path / "out"
        for e in (e1, e2):
            d = out / bid / e
            d.mkdir(parents=True)
            (d / "state_snapshot.json").write_text("{}", encoding="utf-8")
        seen: list = []

        def fake_dispatch(tr, progress_callback=None, card_pool=None):
            seen.append((tr.get("resume_from"), tr["output_root"]))
            return 0

        monkeypatch.setattr("ascendc_devkit.application.batch_runner.dispatch", fake_dispatch)
        monkeypatch.setattr(
            "ascendc_devkit.application.batch_runner._filter_healthy_cards",
            lambda pool, timeout: pool,
        )
        result = resume_batch(bid, output_root=str(out), cli_cards=[0])
        assert result.batch_id == bid                       # reused, not regenerated
        assert {r.run_id for r in result.results} == {e1, e2}
        for rf, ort in seen:
            assert rf in (e1, e2)
            assert ort == str(out / bid)                    # stays under output/<batch_id>/

    def test_resume_batch_missing_raises(self, tmp_path):
        with pytest.raises(ConfigError):
            resume_batch("20260717-120000-nope",
                         output_root=str(tmp_path / "out"), cli_cards=[0])

    def test_resume_batch_empty_batch_raises(self, tmp_path):
        bid = "20260717-120000-empty"
        (tmp_path / "out" / bid).mkdir(parents=True)        # exists, no executions
        with pytest.raises(ConfigError):
            resume_batch(bid, output_root=str(tmp_path / "out"), cli_cards=[0])


class TestBatchSummaryEvalVisibility:
    """Q6: summary surfaces eval score + eval-passed count (done ≠ passed).

    batch 20260727_225324 reported "2/5 succeeded" but both OK ops eval'd 0
    (discovery broken) — workflow-done masqueraded as success. ``ok`` semantics
    stay (exit_code==0); the summary adds an eval column + eval-passed count so
    a 0-eval batch reads honestly.
    """

    def test_read_eval_score_from_snapshot(self, tmp_path):
        exec_id = "exec123"
        (tmp_path / exec_id).mkdir()
        (tmp_path / exec_id / "state_snapshot.json").write_text(
            '{"eval_result": {"overall_score": 72.5, "pass_rate": 80.0}}')
        assert _read_eval_score({"output_root": str(tmp_path)}, exec_id) == (72.5, 80.0)

    def test_read_eval_score_missing_snapshot(self, tmp_path):
        assert _read_eval_score({"output_root": str(tmp_path)}, "ghost") == (None, None)

    def test_read_eval_score_no_output_root(self):
        assert _read_eval_score({}, "x") == (None, None)

    def test_summary_shows_eval_column_and_passed_count(self):
        results = [
            RunOutcome("op_a", 0, "e1", eval_score=72.5, eval_pass_rate=80.0),
            RunOutcome("op_b", 0, "e2", eval_score=0.0, eval_pass_rate=0.0),
            RunOutcome("op_c", 65, "e3"),  # failed, no eval
        ]
        s = BatchResult(batch_id="b1", results=results).summary()
        assert "2/3 workflow-done" in s
        assert "1/3 eval-passed" in s  # only op_a (score>0)
        assert "eval=72.50/80%" in s
        assert "eval=0.00/0%" in s
        assert "eval=-" in s  # op_c (no snapshot / didn't reach eval)

    def test_summary_zero_eval_not_counted_as_passed(self):
        """done but eval=0 is NOT eval-passed (the 20260727_225324 case)."""
        results = [
            RunOutcome("op_a", 0, "e1", eval_score=0.0, eval_pass_rate=0.0),
            RunOutcome("op_b", 0, "e2", eval_score=0.0, eval_pass_rate=0.0),
        ]
        s = BatchResult(batch_id="b1", results=results).summary()
        assert "2/2 workflow-done" in s
        assert "0/2 eval-passed" in s


# ---------------------------------------------------------------------------
# step 104 — dispatch 失败遗言进 run.log（可诊断：死 exec 不再只剩一行）
# ---------------------------------------------------------------------------

class TestDispatchFailureLastWords:
    def test_last_words_land_in_run_log(self, tmp_path, monkeypatch):
        """dispatch 抛异常时，遗言（消息+traceback）必须双写该 exec 的 run.log。

        生产形态：真实 dispatch 内部 bind_run_log 后才可能抛——伪 dispatch 复刻
        该形态（先 bind 再 raise），断言 except 分支的 Logger.error 落进 run.log。
        """
        from ascendc_devkit.application import batch_runner as br
        from ascendc_devkit.infra.log_capture import bind_run_log, unbind_run_log

        m = load_manifest(_write_manifest(tmp_path, {
            "tasks": [{"op_name": "opX", "target_repo": "/tmp/never-used"}],
        }))

        run_log = tmp_path / "run.log"

        def fake_dispatch(tr, progress_callback, card_pool=None):
            bind_run_log(run_log)
            raise RuntimeError("boom: simulated dispatch crash")

        monkeypatch.setattr(br, "dispatch", fake_dispatch)
        try:
            outcome = br._dispatch_one(m, m.tasks[0], pool=None,
                                       progress_callback=lambda *a, **k: None)
        finally:
            unbind_run_log()

        from ascendc_devkit.cli.exit_codes import EX_GENERAL
        assert outcome.exit_code == EX_GENERAL
        content = run_log.read_text(encoding="utf-8")
        assert "dispatch failed for" in content, "遗言主行必须进 run.log"
        assert "boom: simulated dispatch crash" in content
        assert "Traceback" in content, "完整 traceback 必须进 run.log（非仅控制台）"
