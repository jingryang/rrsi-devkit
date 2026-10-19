"""Self-evolution — OpScheduler: operator eval queue with subprocess isolation.

Each operator runs as a separate subprocess (self_evolve_op workflow).
NPU slots are acquired before launch and released after completion.
Concurrency is bounded by NPU card count.

Design (05-multi-op-scheduler.md §3):
  - Subprocess isolation preferred — clean CANN/NPU state per operator
  - NPUSlotManager provides slot lifecycle (acquire → use → release)
  - Results parsed from subprocess output dir (state_snapshot.json)
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from ascendc_devkit.domain.evolution import OpEvalResult
from ascendc_devkit.domain.verification import EvalResult
from ascendc_devkit.infra.logger import Logger


class OpScheduler:
    """Manages operator eval queue with NPU slot allocation.

    Each operator eval:
      1. Acquire NPU slot from NPUSlotManager
      2. Launch subprocess: ascendc-devkit run --workflow self_evolve_op ...
      3. Wait for subprocess completion
      4. Release NPU slot
      5. Parse EvalResult from subprocess output directory

    Parameters:
        max_concurrent: max simultaneous subprocesses (bound by NPU card count)
        subprocess_timeout_sec: per-operator timeout (default 30 min)
        ascendc_devkit_cmd: path or command for ascendc-devkit CLI
        run_func: override for testing (callable that returns OpEvalResult)
    """

    def __init__(
        self,
        max_concurrent: int = 2,
        subprocess_timeout_sec: int = 1800,
        ascendc_devkit_cmd: str = "ascendc-devkit",
        run_func: Callable[..., OpEvalResult] | None = None,
    ):
        self._max_concurrent = max_concurrent
        self._timeout = subprocess_timeout_sec
        self._cmd = ascendc_devkit_cmd
        self._run_func = run_func  # test injection point

    def eval_all(
        self,
        operators: list[str],
        op_dir_root: Path | None = None,
        output_root: str | None = None,
        slot_manager: "NPUSlotManager | None" = None,  # noqa: F821
    ) -> list[OpEvalResult]:
        """Run self_evolve_op for all operators, returning per-op results.

        Uses ThreadPoolExecutor for concurrent subprocess management.
        Each worker acquires a slot, launches the subprocess, releases.

        Args:
            operators: operator names (snake_case)
            op_dir_root: root directory containing per-op directories
            output_root: root directory for per-op output
            slot_manager: NPUSlotManager for device allocation (None = no NPU)

        Returns:
            List of OpEvalResult, one per operator (order matches input)
        """
        if not operators:
            return []

        results: dict[str, OpEvalResult] = {}

        with ThreadPoolExecutor(max_workers=self._max_concurrent) as pool:
            futures = {}
            for op_name in operators:
                fut = pool.submit(
                    self._eval_one,
                    op_name=op_name,
                    op_dir_root=op_dir_root,
                    output_root=output_root,
                    slot_manager=slot_manager,
                )
                futures[fut] = op_name

            for fut in as_completed(futures):
                op_name = futures[fut]
                try:
                    results[op_name] = fut.result()
                except Exception as e:
                    Logger.error(f"OpScheduler: {op_name} eval crashed: {e}")
                    results[op_name] = OpEvalResult(
                        op_name=op_name,
                        status="crashed",
                        eval_result=None,
                    )

        # Return in input order
        return [results[name] for name in operators]

    def _eval_one(
        self,
        op_name: str,
        op_dir_root: Path | None,
        output_root: str | None,
        slot_manager: "NPUSlotManager | None" = None,  # noqa: F821
    ) -> OpEvalResult:
        """Run one operator eval — acquires slot, launches subprocess, parses result."""
        t0 = time.monotonic()

        # Test injection: if run_func is set, use it directly
        if self._run_func is not None:
            return self._run_func(
                op_name=op_name,
                op_dir_root=op_dir_root,
                output_root=output_root,
                slot_manager=slot_manager,
            )

        # Allocate NPU slot
        slot: int | None = None
        try:
            if slot_manager is not None:
                slot = slot_manager.acquire()
        except RuntimeError as e:
            Logger.warn(f"OpScheduler: no NPU slot for {op_name}: {e}")
            return OpEvalResult(
                op_name=op_name, status="crashed",
                elapsed_ms=(time.monotonic() - t0) * 1000,
            )

        try:
            result = self._run_subprocess(op_name, op_dir_root, output_root, slot)
        finally:
            if slot is not None and slot_manager is not None:
                try:
                    slot_manager.release(slot)
                except Exception:
                    pass

        result.elapsed_ms = (time.monotonic() - t0) * 1000
        return result

    def _run_subprocess(
        self,
        op_name: str,
        op_dir_root: Path | None,
        output_root: str | None,
        npu_id: int | None,
    ) -> OpEvalResult:
        """Launch ascendc-devkit subprocess for one operator.

        Builds CLI args from parameters, runs the subprocess, and parses
        the resulting state_snapshot.json for EvalResult.
        """
        op_dir = str(op_dir_root / op_name) if op_dir_root else ""
        out_dir = str(Path(output_root or "output") / op_name) if output_root else ""

        cmd = [self._cmd, "run",
               "--workflow", "self_evolve_op",
               "--non-interactive"]

        if op_dir:
            cmd.extend(["--op-dir", op_dir])
        if out_dir:
            cmd.extend(["--output-root", out_dir])
        if npu_id is not None:
            cmd.extend(["--npu-id", str(npu_id)])

        Logger.info(f"OpScheduler: [{op_name}] launching: {' '.join(cmd)}")

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        except subprocess.TimeoutExpired:
            Logger.error(f"OpScheduler: [{op_name}] subprocess timed out ({self._timeout}s)")
            return OpEvalResult(op_name=op_name, status="eval_timeout")
        except FileNotFoundError:
            Logger.error(
                f"OpScheduler: [{op_name}] ascendc-devkit not found. "
                f"Install it or set ascendc_devkit_cmd."
            )
            return OpEvalResult(op_name=op_name, status="crashed")

        if proc.returncode != 0:
            # Determine failure reason from stderr / events
            status = self._classify_exit(proc.stderr, proc.stdout)
            Logger.warn(
                f"OpScheduler: [{op_name}] exited {proc.returncode} "
                f"({status}): {proc.stderr[:200]}"
            )
            return OpEvalResult(op_name=op_name, status=status)

        # Parse state_snapshot.json from output dir
        return self._parse_result(op_name, out_dir)

    @staticmethod
    def _classify_exit(stderr: str, stdout: str) -> str:
        """Classify a non-zero subprocess exit into a failure status."""
        combined = (stderr + stdout).lower()
        if "compile" in combined or "build failed" in combined:
            return "compile_failed"
        if "deploy" in combined or "install" in combined or "smoke" in combined:
            return "deploy_failed"
        return "crashed"

    @staticmethod
    def _parse_result(op_name: str, output_dir: str) -> OpEvalResult:
        """Parse EvalResult from the subprocess's state_snapshot.json."""
        snapshot_path = Path(output_dir) / "state_snapshot.json"
        if not snapshot_path.exists():
            # Find the most recent run directory
            out_root = Path(output_dir)
            if out_root.exists():
                run_dirs = sorted(
                    [d for d in out_root.iterdir() if d.is_dir()],
                    key=lambda p: (p.stat().st_mtime, p.name),
                    reverse=True,
                )
                for run_dir in run_dirs:
                    candidate = run_dir / "state_snapshot.json"
                    if candidate.exists():
                        snapshot_path = candidate
                        break

        if not snapshot_path.exists():
            return OpEvalResult(op_name=op_name, status="crashed",
                               output_dir=output_dir)

        try:
            data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            Logger.error(f"OpScheduler: [{op_name}] bad state_snapshot: {e}")
            return OpEvalResult(op_name=op_name, status="crashed",
                               output_dir=output_dir)

        # Extract EvalResult from snapshot
        eval_data = data.get("eval_result")
        eval_result = None
        if eval_data is not None:
            eval_result = EvalResult(
                overall_score=float(eval_data.get("overall_score", 0)),
                pass_rate=float(eval_data.get("pass_rate", 0)),
                compile_score=float(eval_data.get("compile_score", 0)),
                function_score=float(eval_data.get("function_score", 0)),
                performance_score=float(eval_data.get("performance_score", 0)),
                report_json=str(eval_data.get("report_json", "")),
                baseline_source=str(eval_data.get("baseline_source", "")),
                num_cases=int(eval_data.get("num_cases", 0)),
                num_passed=int(eval_data.get("num_passed", 0)),
            )

        return OpEvalResult(
            op_name=op_name,
            eval_result=eval_result,
            status="ok",
            output_dir=str(snapshot_path.parent),
        )
