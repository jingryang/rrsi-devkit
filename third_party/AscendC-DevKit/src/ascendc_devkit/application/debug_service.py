"""L2 Application — debug service: ``redeploy`` + ``run-cases`` (P54 D11).

The precision-debug agent drives its closed loop through the CLI; this service
is the CLI's L2 delegate so L1 never imports orchestration internals or L6
adapters directly (§1.1 layering: L1 → L2 → L3; L3 owns the NPURunner). It owns:

  - loading a run's ``state_snapshot.json`` read-only — Event Sourcing (§1.1)
    stays authoritative (the snapshot/events are never mutated here); the
    per-deploy handoff between the two commands is a file (``last_deploy.json``,
    §2.3),
  - ``redeploy``: ``Deployer.deploy(state)`` (L3) → per-op install + smoke,
    writes ``last_deploy.json`` for ``run-cases`` to consume,
  - ``run_cases``: ``run_precision_cases`` (L3, the single runner-assembly
    path — §2.5; now lives in the precision_debug stage module after the
    verify stage was deleted) → max_diff + per-case diff + the dumptensor log
    on disk (D7).

The CLI is a thin click wrapper over this service (see ``cli/commands/debug.py``).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from ascendc_devkit.domain.verification import DeployResult
from ascendc_devkit.infra.workspace import Workspace
from ascendc_devkit.orchestration.kernel.state import ErrorFeedback, State
from ascendc_devkit.orchestration.runtime_config import (
    harness_timeout_sec,
    read_harness_timeout_sidecar,
)
from ascendc_devkit.orchestration.stages.deploy import Deployer
from ascendc_devkit.orchestration.stages.precision_debug import (
    run_precision_cases,
)


class DebugService:
    """L2 delegate for the debug CLI (redeploy + run-cases)."""

    def load_state(self, run_dir: Path) -> State:
        """Load ``state_snapshot.json`` read-only; re-attach ``_workspace``.

        ``_workspace`` is transient (not serialized), so it must be re-attached
        after every snapshot load so ``Deployer``'s per-op install lands in the
        run's artifacts dir (consistent with the in-session redeploy the codegen
        agent performs), not the ``~/.cache`` fallback.
        """
        snapshot = run_dir / "state_snapshot.json"
        if not snapshot.exists():
            raise FileNotFoundError(f"state_snapshot.json not found in {run_dir}")
        with snapshot.open("r", encoding="utf-8") as f:
            data = json.load(f)
        state = State.from_snapshot(data)
        ws = Workspace(run_dir.parent, run_dir.name)
        return state.with_updates(_workspace=ws)

    def debug_dir(self, run_dir: Path, op_name: str) -> Path:
        d = run_dir / "artifacts" / "debug" / (op_name or "op")
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def _op_name(state: State) -> str:
        return (state.op_name
                or (state.op_identity.spec.name if state.op_identity else "op"))

    def redeploy(
        self, run_dir: Path,
    ) -> tuple[str, DeployResult, "ErrorFeedback | None", Path]:
        """``Deployer.deploy(state)`` → per-op install + smoke; persist ``last_deploy.json``.

        Returns ``(op_name, deploy_result, err, last_deploy_path)``.
        """
        state = self.load_state(run_dir)
        op_name = self._op_name(state)
        debug_dir = self.debug_dir(run_dir, op_name)

        deploy_result, err = Deployer().deploy(state)
        last_deploy = debug_dir / "last_deploy.json"
        last_deploy.write_text(
            json.dumps(dataclasses.asdict(deploy_result), ensure_ascii=False),
            encoding="utf-8")
        return op_name, deploy_result, err, last_deploy

    def read_last_deploy(self, debug_dir: Path) -> DeployResult:
        """File handoff (§2.3): read the ``DeployResult`` written by ``redeploy``."""
        p = debug_dir / "last_deploy.json"
        if not p.exists():
            raise FileNotFoundError(
                f"no last_deploy.json in {debug_dir} — run `redeploy` first")
        with p.open("r", encoding="utf-8") as f:
            return DeployResult(**json.load(f))

    def run_cases(
        self, run_dir: Path, case_names: tuple[str, ...] = (), iter_n: int = 0,
        label: str = "",
    ) -> tuple[str, dict, Path, Path]:
        """``run_precision_cases(...)`` → result dict + log path + result.json path (D7).

        step-40 (test-execution decoupling): cases + golden no longer come from a
        runtime ``task_loader`` directory sniff. Cases are ``state.test_cases``
        (loaded upstream by ``test_design`` — ``cann_bench_cases_loader`` for
        cann-bench ops, which handles per-input value_range correctly, killing the
        scatter bug); the golden contract is the CLI-supplied ``--golden``
        (``state.golden_path/entry/input_type``); backend selection is driven by
        ``state.cases_source`` (set by test_design) — ``run_precision_cases`` builds
        the ``EvalRequest`` and ``select_backend`` picks CannbenchBackend or
        DevkitBackend.

        Returns ``(op_name, result, run_log_path, result_json_path)``. Raises on
        NPU/env failure (the CLI surfaces it honestly — §3.4/§3.7; no stub here).
        """
        state = self.load_state(run_dir)
        op_name = self._op_name(state)
        debug_dir = self.debug_dir(run_dir, op_name)

        deploy_result = self.read_last_deploy(debug_dir)

        # P69: prefer requirement.op_spec (carries proto precision_thresholds) over
        # the bare op_identity.spec shell — without it the runner cannot tolerance-
        # gate precision (the DQ 冤杀 path: int8 ±1 needs proto's {int8: 1.0}).
        if state.requirement and state.requirement.op_spec:
            op_spec = state.requirement.op_spec
        elif state.op_identity:
            op_spec = state.op_identity.spec
        else:
            op_spec = None
        if op_spec is None:
            raise ValueError("no op_identity in run state — cannot run cases")

        # Stale-state defense (precision_thresholds drift): the snapshot's
        # op_spec.precision_thresholds is captured once at the requirement stage.
        # Agents that edit proto.yaml mid-session (adding a dtype tolerance after
        # observing a legitimate hardware reduce-order divergence) would otherwise
        # see their new tolerance ignored — the runner still judges against the
        # stale snapshot. Re-read proto.yaml here (the single source of precision
        # tolerance per P69) and patch op_spec with the fresh thresholds + per-output
        # compare flags so run_precision_cases picks up the current proto truth.
        # Graceful: proto missing/unreadable/undeclared → op_spec unchanged.
        proto_path = getattr(state, "requirement_path", None)
        if proto_path:
            try:
                from ascendc_devkit.domain.requirement import read_proto_precision
                from dataclasses import replace as _dc_replace
                _thresholds, _compares, _index_gathers = read_proto_precision(proto_path)
                _has_meta = any(
                    _c is not None or _g is not None
                    for _c, _g in zip(_compares, _index_gathers)
                )
                if _thresholds is not None or _has_meta:
                    _new_outputs = list(op_spec.outputs)
                    for _i, (_cmp, _ig) in enumerate(zip(_compares, _index_gathers)):
                        if (_cmp is not None or _ig is not None) and _i < len(_new_outputs):
                            _kw = {}
                            if _cmp is not None:
                                _kw["compare"] = _cmp
                            if _ig is not None:
                                _kw["index_gather"] = _ig
                            _new_outputs[_i] = _dc_replace(_new_outputs[_i], **_kw)
                    op_spec = _dc_replace(
                        op_spec,
                        precision_thresholds=_thresholds if _thresholds is not None
                        else op_spec.precision_thresholds,
                        outputs=_new_outputs if _has_meta else op_spec.outputs,
                    )
            except Exception:
                # Non-fatal: degrade to snapshot thresholds (never abort a run
                # because of a proto re-read failure — the snapshot is still a
                # valid, if possibly stale, source).
                pass

        # step-40: cases flow from upstream test_design (state.test_cases). No
        # task_loader directory sniff — per-input value_range correctness is the
        # upstream loader's job (cann_bench_cases_loader), not a judgement-time
        # concern (L3 §0.2/§6).
        test_cases = state.test_cases or []

        # Golden contract from the CLI-supplied --golden (state scalars). cann-bench
        # ops ship a golden; hand-written fixtures use the user's reference. Absent
        # → None (CannbenchBackend then declines; DevkitBackend runs without a golden).
        golden_contract: dict | None = None
        if state.golden_path:
            golden_contract = {
                "path": str(state.golden_path),
                "entry": state.golden_entry or "",
                "input_type": state.golden_input_type or "",
                # golden 参考计算精度：默认 fp64_cpu（对齐 cann-bench 评测标准）。
                # 空值落默认——harness 与 eval 必须用同一参考，否则 debug 判
                # 20/20 而 eval 判 13/20 的假收敛分裂（golden_precision 对齐）。
                "precision": state.golden_precision or "fp64_cpu",
                # eval seed：harness 与 eval（kernel_eval config.eval_seed）必须
                # 同种子生成用例输入，否则两侧输入分裂（默认 0，scorer 显式对齐）。
                "eval_seed": state.eval_seed or 0,
            }

        # Apply case filter AFTER loading (single-case iteration: --case <CASE_ID>).
        # Match against name, case_id, or numeric suffix.  The numeric-suffix
        # fallback mirrors ``runner._resolve_case_id`` — when ``case_id`` is empty
        # (test_design was skipped or the snapshot pre-dates the loader upgrade),
        # the name's trailing ``_N`` still pinpoints the right case:
        #   --case "level2/op_5"  +  name "Op_5"  →  suffix "5" == "5"  → match ✅
        # The old ``endswith("_" + w)`` was too loose ("_5" would match "_15").
        if case_names:
            wanted = set(case_names)
            test_cases = [
                tc for tc in test_cases
                if getattr(tc, "name", "") in wanted
                or getattr(tc, "case_id", "") in wanted
                or any(
                    getattr(tc, "name", "") == w
                    or getattr(tc, "case_id", "") == w
                    or getattr(tc, "name", "").endswith("_" + w)
                    or getattr(tc, "case_id", "").endswith("_" + w)
                    # Numeric-suffix fallback: extract trailing _N from both
                    # sides and compare.  Handles cann-bench task paths
                    # ("level2/op_5") where the full path isn't in name/case_id.
                    or (
                        "_" in w
                        and (w_sfx := w.rsplit("_", 1)[-1]).isdigit()
                        and getattr(tc, "name", "").rsplit("_", 1)[-1] == w_sfx
                    )
                    for w in wanted
                )
            ]
        if not test_cases:
            raise ValueError(
                "no test cases to run — state.test_cases is empty "
                "(test_design must run before run-cases; --case filter matched nothing)")

        callable_target = (state.codegen_manifest or {}).get("callable_target")

        iter_dir = debug_dir / (f"{label}_iter-{iter_n}" if label else f"iter-{iter_n}")
        iter_dir.mkdir(parents=True, exist_ok=True)

        # 解析 harness 看门狗超时，优先级：control.json per-run override（人工 hand-edit /
        # 显式设置专用，**phase agent 禁写该字段**——见 run-tests SKILL 与
        # _FRAMEWORK_OWNED_KEYS）→ 框架自有 sidecar（build-failed-case-queue.py 写的
        # 放大值）→ config 默认（timeouts.harness_sec）。三阶段（run_tests/fix/
        # printf_location）都走本入口，因此放大值自动共享。注意：override 优先级高于
        # sidecar 是有意设计（人工干预 win），这也意味着 agent 若违规写 control.json
        # 该字段会压过框架值——防线是写入纪律 + prompt 契约，不是本函数的解析顺序。
        # control.json 不存在/读失败 → 用 sidecar/默认，不阻断运行。
        harness_timeout = harness_timeout_sec()
        control_path = debug_dir / "control.json"
        _override: float | None = None
        if control_path.exists():
            try:
                _ctrl = json.loads(control_path.read_text(encoding="utf-8"))
                _t = _ctrl.get("harness_timeout_sec")
                if isinstance(_t, (int, float)) and _t > 0:
                    _override = float(_t)
            except (json.JSONDecodeError, OSError):
                pass  # 读失败用默认，绝不因 control.json 解析错误阻断测试
        if _override is not None:
            harness_timeout = _override
        else:
            _side = read_harness_timeout_sidecar(debug_dir)
            if _side is not None:
                harness_timeout = _side

        result = run_precision_cases(
            op_spec, test_cases, state.npu_id,
            golden_contract=golden_contract,
            deploy_result=deploy_result,
            callable_target=callable_target,
            chip_version=state.design_target_chip,
            cases_source=state.cases_source,
            op_dir=str(state.op_dir) if state.op_dir else None,
            log_dir=iter_dir,
            test_timeout_sec=harness_timeout,
        )

        # Persist the structured result alongside the raw log (agent reads either).
        result_path = iter_dir / "result.json"
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return op_name, result, iter_dir / "run.log", result_path
