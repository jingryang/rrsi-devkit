"""L6 Adapters — CannbenchScorer: cann-bench kernel_eval CLI → EvalResult.

The cann-bench **整箱评分** adapter (② in the three-tier eval model): runs
``python -m kernel_eval.cli eval`` and parses the weighted
(compile 0.2 + function 0.3 + performance 0.5) report into ``EvalResult``.

Deliberately NOT an ``EvaluationBackend`` (that Protocol is the ① local
precision-precheck service: ``run(EvalRequest) -> TestReport``, v3 frozen).
Scoring is a different job returning a different type (``EvalResult``), so it
lives at the adapter boundary but outside the Protocol — selected by
``CannbenchEvalStage`` directly, not via ``select_backend`` (no ``available()``
guard; the stage is scheduled unconditionally by the workflow graph).

Env assembly is delegated to ``cannbench_env`` (single source — the stage no
longer assembles cann-bench env itself; §1.6/§2.5). This class owns: the
kernel_eval subprocess, the usercustomize torch_npu-preload lifecycle, the
cann_bench_utils reachability precheck, and report parsing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from ascendc_devkit.adapters.evaluation.cannbench_env import build_kernel_eval_env
from ascendc_devkit.domain.verification import EvalResult
from ascendc_devkit.infra.logger import Logger


class CannbenchScorer:
    """cann-bench kernel_eval CLI scorer (cann-bench adapter boundary).

    Owns the cann-bench scoring mechanism + its env; the stage owns orchestration
    (smoke gate, state write-back, LOSS semantics). Invariants (autoload=0,
    card→--device-id, PYTHONPATH, --task-dir, infra/LOSS split) are preserved
    from the pre-refactor stage — guarded by tests/ut/adapters/evaluation/.
    """

    # kernel_eval subprocess budget (matches the stage's prior 30 min cap).
    _EVAL_TIMEOUT = 1800
    # cann_bench_utils reachability precheck budget (import + _C load only).
    _PRECHECK_TIMEOUT = 120
    # eval_prepare build/install step budget (compile cann_bench_utils _C + pip).
    _PREPARE_TIMEOUT = 1200

    def run_eval(
        self,
        source_dir: Path,
        repo_root: Path,
        op_pascal: str,
        op_name: str,
        deploy,
        npu_id: int | None = None,
        ws=None,
    ) -> tuple[EvalResult, str | None]:
        """Run cann-bench kernel_eval and parse the report → (EvalResult, reason).

        Returns a primitive (EvalResult, reason_str | None) so this L6 adapter
        stays free of L3 types (§1.1 layering): the stage wraps a non-None reason
        into an infra ErrorFeedback. reason is non-empty for infra-class breakages
        (cann_bench_utils unreachable / discovery chain broken / eval crash) —
        surfaced for attribution only, never a corrective loopback (cann-bench is
        the one-shot LOSS signal). Precision failures (operators non-empty,
        pass_rate==0) stay a plain LOSS (None).
        """
        per_op_python = getattr(deploy, "python_path", "") or ""
        per_op_opp = getattr(deploy, "install_path", "") or ""
        deploy_ld = getattr(deploy, "ld_library_path_add", "") or ""

        # usercustomize: force torch_npu import at Python startup so the first
        # `import torch` (in cann_bench) finds it loaded and does NOT re-register
        # the npu backend (double-register crash, 20260709-094500). Lifecycle owned
        # here (env assembly only takes the dir, never touches the filesystem).
        usercustomize_dir = tempfile.mkdtemp(prefix="tn_usercustomize_")
        try:
            with open(os.path.join(usercustomize_dir, "usercustomize.py"), "w") as f:
                f.write("import torch_npu\n")

            env = build_kernel_eval_env(
                repo_root, source_dir,
                per_op_python=per_op_python,
                per_op_opp=per_op_opp,
                deploy_ld=deploy_ld,
                usercustomize_dir=usercustomize_dir,
            )

            # Reachability: ensure cann_bench_utils (kernel_eval perf warmup/cache
            # anti-cheat ops + _C) is importable in THIS env. On failure, run the
            # cann-bench profile's eval_prepare (build+install) then re-check (step-82
            # 决策1=C 主修复). If still unreachable, surface an honest infra error
            # instead of a silent all-zero (§3.7, §1.11 env fidelity).
            unreachable = self._ensure_eval_prepare(env, repo_root)
            if unreachable:
                return (
                    EvalResult(overall_score=0.0),
                    self._infra_error(op_name, unreachable),
                )

            Logger.info(
                f"CannbenchScorer: eval {op_pascal} "
                f"npu_id={npu_id} source_dir={source_dir}"
            )

            try:
                # P13 (step-116)：npu_id 即 dispatch 解析的权威 op 卡（原 span 级
                # card_context 租约已随 op 级租约退役）。双变量 pin 进 eval 子进程
                # env——remap 后子进程内设备号恒 0，故 --device-id 传逻辑 0。
                if npu_id is None:
                    raise ValueError(
                        "npu_id must be the op-resolved card "
                        "(dispatch/resolve_op_card) — None means the caller "
                        "skipped the single resolution point")
                card = int(npu_id)
                from ascendc_devkit.adapters.npu.card_pin import card_pin_env
                env.update(card_pin_env(card))
                Logger.info(
                    f"CannbenchScorer: eval {op_pascal} "
                    f"device_id={card} source_dir={source_dir}"
                )
                task_dir = self._resolve_task_dir(repo_root, op_name)
                # main 侧先例织入（P13 形态）：提交 30 分钟级 kernel_eval 前对
                # 解析卡做真实环境探针——zombie 子进程遗留的驱动侧 context
                # 耗尽是进程内租约表看不见的；探针 env 形态与 eval 子进程一致
                # （base_env+pin）。infra 故障经 EnvironmentNotAvailableError
                # 传播，绝不冒充 LOSS=0。
                from ascendc_devkit.adapters.npu.card_pin import verify_pin
                verify_pin(card, env)
                Logger.info(
                    f"CannbenchScorer: eval {op_pascal} task_dir={task_dir} "
                    f"(task-level scoping — filter_prefix limits cases to the "
                    f"target task)"
                )
                proc = subprocess.run(
                    [
                        "python", "-m", "kernel_eval.cli", "eval",
                        "--source-dir", str(source_dir),
                        "--operator", op_pascal,
                        "--device-id", "0",  # P13: remap 后逻辑号
                        "--skip-install",
                        "--task-dir", task_dir,
                        # eval_seed 显式 0（默认值显式化）：kernel_eval 的
                        # config.eval_seed 若未来变默认，DevKit harness 的
                        # (eval_seed + SHA256(case_id)) % 2^31 与之分裂 →
                        # 输入不同 → debug/eval 判定分裂。显式传值对齐 harness。
                        "--eval-seed", "0",
                        # §step-91 P3/P4 方向：把 --output 指到我们自己的已知路径。
                        # kernel_eval 的 evaluator 增量写它（incremental_output_path），
                        # 超时/崩溃时该路径已有「已完成 case 的完整 perf/accuracy 报告」——
                        # 性能问题不再被超时墙读成纯 infra 0 分（20260826 unique 实证：
                        # 20 case 只跑完 9 个即超时，完整性能分布之前只能从随机 /tmp 考古）。
                        # ws 不可用（单测）→ None，不传该参数。
                        *((["--output",
                            str(partial_path)]
                           if (partial_path := self._eval_partial_path(ws, op_name))
                           else [])),
                    ],
                    cwd=str(repo_root),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=self._EVAL_TIMEOUT,
                )
            except subprocess.TimeoutExpired as te:
                _mins = self._EVAL_TIMEOUT // 60
                Logger.error(f"CannbenchScorer: eval timed out ({_mins} min)")
                # §1.11 留可诊断信号：超时前捕获的 partial stdout/stderr 是定位
                # kernel hang 前在跑哪个 case 的唯一线索，必须落盘（对齐
                # _log_eval_failure 同款模式，§1.15 单一通路）——不应像 incident
                # 20260825-153847-ccad38 那样 subprocess/ 为空、线索全丢。
                # dump 是尽力而为的可观测性，自身失败绝不把「干净 return infra」
                # 变成 stage crash（20260826 回放实证 bytes 写文件炸出 uncaught）——
                # 报 WARN 留痕、超时仍按 infra 走。
                try:
                    self._dump_partial_output(op_name, te, ws)
                except Exception as e:  # noqa: BLE001 — observability never breaks routing
                    Logger.warn(
                        f"CannbenchScorer: failed to dump timeout partial output "
                        f"({e}) — eval still scored 0 as infra")
                # §P3 方向：把 kernel_eval 增量写的 partial 报告（已完成 case 的完整
                # perf/accuracy）拷贝到 subprocess_log —— 性能分布不再只能考古。
                try:
                    self._archive_eval_partial(op_name, ws)
                except Exception as e:  # noqa: BLE001 — observability never breaks routing
                    Logger.warn(
                        f"CannbenchScorer: failed to archive partial eval report "
                        f"({e}) — eval still scored 0 as infra")
                # §1.10 错误不冒充：超时 ≠ 前置环境缺失——两个不同的外部故障
                # 类（环境缺依赖 vs eval 进程挂死），文案分流，error_type 仍 infra。
                return (
                    EvalResult(overall_score=0.0),
                    f"cann-bench eval 超时 (op '{op_name}'): "
                    f"eval subprocess exceeded {_mins} min without exiting "
                    "(kernel/driver hang class — check the NPU device state and "
                    "the op worktree eval logs before retrying)",
                )

            if proc.returncode != 0:
                self._log_eval_failure(op_name, proc, ws)
                # Non-zero exit = some cases failed, but report may still exist.

            return self._parse_report(
                repo_root, proc.stdout, proc.stderr, op_name, ws=ws)
        finally:
            shutil.rmtree(usercustomize_dir, ignore_errors=True)

    # —— env-internal precheck ——

    def _precheck_cannbench_utils(self, env: dict, repo_root: Path) -> str:
        """Return ``""`` if cann_bench_utils (+ cann_bench_warmup/_C) imports in env,
        else a human-readable reason. Runs in the SAME env kernel_eval will use
        (cwd=repo_root) so the probe faithfully reflects the real subprocess (§1.11).
        """
        try:
            proc = subprocess.run(
                [
                    "python", "-c",
                    "import cann_bench_utils; "
                    "from cann_bench_utils import cann_bench_warmup, cann_bench_cache_clean",
                ],
                cwd=str(repo_root),
                env=env,
                capture_output=True,
                text=True,
                timeout=self._PRECHECK_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return "cann_bench_utils 预检超时（import 挂起）"
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "")[-800:].strip()
            cbu = repo_root / "src" / "cann_bench_utils"
            return (
                "cann_bench_utils 不可达（kernel_eval 性能预热的反作弊工具算子 "
                "cann_bench_warmup/cann_bench_cache_clean 的 _C 未编译/未安装）。"
                f"请预装：cd {cbu} && bash build.sh && "
                "pip install dist/cann_bench_utils-*.whl --force-reinstall --no-deps。"
                f" 预检 stderr: {tail}"
            )
        return ""

    def _ensure_eval_prepare(self, env: dict, repo_root: Path) -> str:
        """Ensure cann_bench_utils is reachable, building it via the profile's
        eval_prepare if the precheck fails (step-82 决策1=C 主修复).

        Precheck → on failure run the cann-bench profile's eval_prepare steps
        (build+install cann_bench_utils) → re-precheck. Returns "" when reachable
        (possibly after a build), else a reason. Build steps run with the base
        os.environ (build.sh/pip need no kernel_eval env); the precheck runs in
        the kernel_eval env (§1.11 fidelity). Profile/step absence degrades to a
        pure precheck (reason tells the user to pre-install).
        """
        reason = self._precheck_cannbench_utils(env, repo_root)
        if not reason:
            return ""
        steps = self._load_eval_prepare_steps()
        if not steps:
            return reason  # no eval_prepare declared → keep the precheck reason
        Logger.info(
            "CannbenchScorer: cann_bench_utils is not prebuilt in this fresh per-op "
            "worktree (build artifacts are not checked into git); building on-demand "
            f"via eval_prepare ({len(steps)} steps). This is expected for every fresh "
            "worktree — not a failure; eval proceeds once the build succeeds."
        )
        for step in steps:
            if not step.command_template or not step.enabled:
                continue
            try:
                # command_template comes from the cann-bench profile — an in-repo
                # trusted resource (§1.5, NOT user input) — so shell=True is safe
                # here; the shell is needed to expand globs like dist/*.whl.
                proc = subprocess.run(
                    step.command_template,
                    cwd=str(repo_root / step.cwd) if step.cwd else str(repo_root),
                    env=os.environ.copy(),
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=self._PREPARE_TIMEOUT,
                )
            except subprocess.TimeoutExpired:
                return f"eval_prepare step '{step.name}' timed out"
            if proc.returncode != 0:
                Logger.warn(
                    f"CannbenchScorer: eval_prepare step '{step.name}' exited "
                    f"{proc.returncode}: {(proc.stderr or proc.stdout or '')[-600:]}"
                )
        return self._precheck_cannbench_utils(env, repo_root)  # "" = build fixed it

    def _load_eval_prepare_steps(self) -> list:
        """cann-bench profile's eval_prepare steps ([] on any failure — the scorer
        is cann-bench-specific so the profile name is fixed; lazy import keeps
        module load decoupled from the repository adapter)."""
        try:
            from ascendc_devkit.adapters.repository.profile_loader import ProfileLoader
            return list(ProfileLoader.load("cann-bench").eval_prepare)
        except Exception as e:
            Logger.warn(
                f"CannbenchScorer: cann-bench profile eval_prepare unavailable ({e}); "
                "falling back to precheck-only")
            return []

    # —— report parsing (moved from the stage, unchanged logic) ——

    def _resolve_task_dir(self, repo_root: Path, op_name: str) -> str:
        """Discover the **task directory** holding <op>'s cases.yaml (not the
        bench-set root).

        --task-dir 传任务目录激活 kernel_eval 的 filter_prefix 通路（其
        resolve_task_dir 拆成 bench_root=评测集根 + filter_prefix=<level>/<op>）：
        bench_root 归位根目录使 match_operators/golden/baseline 照常工作，
        filter_prefix 把用例集**构造性限定到目标任务**。传根则只剩名字过滤兜
        范围——kernel_eval 的 --operator 过滤大小写不敏感，任务集中仅差大小
        写的重名算子（孪生任务）会一并入选：overall 变跨任务求和的错数据，
        且孪生任务的 4D/NaN/极值用例污染执行环境。任务身份 = rel_path（唯
        一），不是算子名。

        Falls back to the tasks/ root when no task dir is found (that path
        already yields operators=[] → the discovery-broken infra error).
        """
        candidates = [
            repo_root / "bench_lab" / "kernel_bench",
            repo_root / "tasks",
        ]
        for root in candidates:
            if not root.is_dir():
                continue
            for level in sorted(root.glob("level*")):
                task_dir = level / op_name
                if (task_dir / "cases.yaml").is_file():
                    return str(task_dir)
        return str(repo_root / "tasks")

    def _log_eval_failure(self, op_name: str, proc, ws) -> None:
        """Surface the FULL kernel_eval stderr (traceback lives at the END)."""
        stderr = proc.stderr or ""
        self._write_stream(ws, op_name, "stderr", stderr)
        preview = stderr[-1200:] if len(stderr) > 1200 else stderr
        if ws is not None:
            log_path = ws.subprocess_log / f"cannbench_eval_{op_name}.stderr.log"
            Logger.warn(
                f"CannbenchScorer: kernel_eval exited {proc.returncode}. "
                f"Full stderr → {log_path}\n--- stderr tail ---\n{preview}"
            )
        else:
            Logger.warn(
                f"CannbenchScorer: kernel_eval exited {proc.returncode}; "
                f"stderr (tail; full log unavailable — no workspace):\n{preview}"
            )

    def _dump_partial_output(self, op_name: str, exc, ws) -> None:
        """Persist the partial stdout/stderr captured by TimeoutExpired — the only
        clue to what case was running when the eval hung (§1.11). Same write
        pattern as _log_eval_failure (single pathway, §1.15)."""
        stdout = getattr(exc, "stdout", None) or getattr(exc, "output", None) or ""
        stderr = getattr(exc, "stderr", None) or ""
        self._write_stream(ws, op_name, "stdout", stdout)
        self._write_stream(ws, op_name, "stderr", stderr)

    @staticmethod
    def _eval_partial_path(ws, op_name: str) -> str | None:
        """kernel_eval 的 --output 路径——scorer 已知、incrementally written。ws
        不可用（单元测试无 workspace）→ None（不传 --output，回退 kernel_eval
        默认随机路径）。"""
        if ws is None:
            return None
        return str(ws.subprocess_log / f"cannbench_eval_{op_name}.partial.json")

    @staticmethod
    def _archive_eval_partial(op_name: str, ws) -> None:
        """超时/崩溃时把 kernel_eval 增量写的 partial 报告（已完成 case 的完整
        perf/accuracy）归档到 subprocess_log —— 性能分布可查，不被超时墙读成纯
        infra 0 分（§P3 方向）。

        kernel_eval 的 --output 语义是**报告目录**（内写 <op>_eval_<ts>.json），
        按目录发现报告（与 _parse_report 同款发现，§1.15 同族单点）；报告的
        total_cases = 增量已完成的 case 数。"""
        p = CannbenchScorer._eval_partial_path(ws, op_name)
        if p is None:
            return
        report_json = CannbenchScorer._find_latest_report(Path(p))
        if not report_json:
            return  # 目录未成形（首个 case 都没写完）→ 无可归档
        try:
            data = json.loads(Path(report_json).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return  # 报告写了一半（增量写中途被超时杀）→ 无可归档
        n = data.get("total_cases", 0) if isinstance(data, dict) else 0
        Logger.warn(
            f"CannbenchScorer: eval timed out — {n} case(s) completed and archived "
            f"→ {report_json} (full perf/accuracy; score stays 0 as infra)")


    @staticmethod
    def _write_stream(ws, op_name: str, stream: str, content) -> None:
        if ws is None:
            return
        # TimeoutExpired.output/stderr 在部分路径是 bytes（即使 text=True）——
        # 统一解码再落盘，避免超时分支被 bytes 写文件炸掉（20260826 回放实证
        # 'data must be str, not bytes'：把该干净 return infra 的路径变成 stage failed）。
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")
        log_dir = ws.subprocess_log
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / f"cannbench_eval_{op_name}.{stream}.log").write_text(
            content, encoding="utf-8")

    def _parse_report(
        self, repo_root: Path, stdout: str, stderr: str, op_name: str = "",
        ws=None,
    ) -> tuple[EvalResult, str | None]:
        """Locate and parse the latest cann-bench eval report JSON.

        Discovery order (step-102): the ``--output`` dir handed to kernel_eval
        (``_eval_partial_path`` — the location WE told it to write to) comes
        first; ``repo_root/reports`` glob is the fallback when ws is absent or
        its dir holds no report. Returns a non-None reason string when the
        discovery chain is broken (operators == []), so the failure is
        visible/attributable instead of a silent all-zero. Precision failures
        (operators non-empty, pass_rate==0) stay LOSS (None).
        """
        # step-102: 在自己指定给 kernel_eval 的产出位置找，别处（repo reports/）
        # 只作回退——发现位置与产出位置错位曾把整批跑完的 eval 误报成 0 分
        # （20260827 批，L1 cannbench-eval-report-discovery）。
        search_dirs: list[Path] = []
        partial_dir = self._eval_partial_path(ws, op_name) if ws else None
        if partial_dir:
            search_dirs.append(Path(partial_dir))
        search_dirs.append(repo_root / "reports")
        report_json = ""
        for d in search_dirs:
            report_json = self._find_latest_report(d)
            if report_json:
                break
        if not report_json:
            Logger.error(
                f"CannbenchScorer: no eval report found under "
                f"{[str(d) for d in search_dirs]}")
            return (
                EvalResult(overall_score=0.0),
                self._no_report_error(op_name, search_dirs),
            )

        try:
            data = json.loads(Path(report_json).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            Logger.error(f"CannbenchScorer: failed to parse report: {e}")
            return (
                EvalResult(overall_score=0.0, report_json=report_json),
                self._discovery_broken_error(
                    op_name, report_json, f"failed to parse eval report: {e}"),
            )

        summary = data.get("summary", {}) if isinstance(data, dict) else {}
        overall_score = float(summary.get("overall_score", 0.0))
        pass_rate = float(summary.get("pass_rate", 0.0))

        operators = data.get("operators", []) if isinstance(data, dict) else []
        # 结构校验单点：operators 必须是 dict 列表——其后的多 operator 守卫
        # （op.get）与 per-dimension 读取（first.get）都直接消费元素，畸形
        # 报告（非 dict 元素 / 非 list）若不在解析点拦下会以 AttributeError
        # 炸穿 stage 而非 infra reason 终止（同暴露面一起收，§1.15）。
        if not isinstance(operators, list) or not all(
                isinstance(op, dict) for op in operators):
            Logger.error(
                "CannbenchScorer: eval report operators malformed "
                f"(type={type(operators).__name__}) — {report_json}")
            return (
                EvalResult(overall_score=0.0, report_json=report_json),
                f"cann-bench eval 报告畸形：operators 不是 dict 列表 "
                f"(type={type(operators).__name__})，无法解析算子条目 "
                f"({report_json})",
            )
        # scope 守卫：单 op 评测的报告必须恰好一个 operator。>1 = 任务级
        # scoping 失效（如 cann-bench 行为漂移重新按名字吸入仅差大小写的孪生
        # 任务）——overall 是跨任务求和的错数据，静默流入 converge 会翻转决策
        # （拒绝错误冒充）；按 infra reason 暴露，列出全部 rel_path 供归因。
        if len(operators) > 1:
            rel_paths = [str(op.get("rel_path", "?")) for op in operators]
            Logger.error(
                f"CannbenchScorer: eval report holds {len(operators)} operators "
                f"({rel_paths}) — expected exactly the target task "
                f"(task-level --task-dir scoping broken?)")
            return (
                EvalResult(overall_score=0.0, report_json=report_json),
                f"cann-bench eval 报告含 {len(operators)} 个算子条目 "
                f"({rel_paths})，任务级 scoping 失效——overall 为跨任务求和的"
                f"错数据，按 infra 处理不参与计分",
            )
        # Per-dimension scores ARE exposed on ``operators[0]``
        # (``compilation_score`` / ``function_score`` / ``performance_score``);
        # read them so the log faithfully transcribes what the eval reported.
        # Hardcoding 0 here produced a long-standing false signal — a passing
        # eval (func=30) looked identical in the log to one that never ran, and
        # a legitimately-0 perf (missing cann-bench baseline anchor) could not
        # be told apart from a wholesale failure. Fall back to 0 only when a
        # field is genuinely absent (older report schema).
        compile_score = 0.0
        function_score = 0.0
        performance_score = 0.0
        num_cases = int(data.get("total_cases", 0))
        num_passed = int(data.get("passed_cases", 0))
        baseline_source = "fallback"

        if operators:
            first = operators[0]
            compile_score = float(first.get("compilation_score", 0.0) or 0.0)
            function_score = float(first.get("function_score", 0.0) or 0.0)
            performance_score = float(first.get("performance_score", 0.0) or 0.0)
            op_num_cases = int(first.get("total_cases", 0))
            op_num_passed = int(first.get("passed_cases", 0))
            if op_num_cases:
                num_cases = op_num_cases
                num_passed = op_num_passed
            cases = first.get("cases", [])
            if cases:
                has_baseline = any(
                    c.get("baseline_perf_us") for c in cases
                    if isinstance(c, dict)
                )
                if has_baseline:
                    baseline_source = "inherited"

        Logger.info(
            f"CannbenchScorer: overall={overall_score:.2f} "
            f"compile={compile_score:.2f} func={function_score:.2f} "
            f"perf={performance_score:.2f} pass_rate={pass_rate:.2%} "
            f"report={report_json}"
        )

        eval_result = EvalResult(
            overall_score=overall_score,
            pass_rate=pass_rate,
            compile_score=compile_score,
            function_score=function_score,
            performance_score=performance_score,
            report_json=report_json,
            baseline_source=baseline_source,
            num_cases=num_cases,
            num_passed=num_passed,
        )
        discovery_err = (
            self._discovery_broken_error(op_name, report_json)
            if self._is_discovery_broken(data)
            else None
        )
        return eval_result, discovery_err

    @staticmethod
    def _is_discovery_broken(data) -> bool:
        """True iff scan_interfaces found no operator (operators list empty)."""
        operators = data.get("operators", []) if isinstance(data, dict) else []
        return isinstance(operators, list) and len(operators) == 0

    @staticmethod
    def _discovery_broken_error(
        op_name: str, report_json: str, reason: str = "",
    ) -> str:
        """Reason string for a discovery-chain breakage (operators == []). The
        stage wraps it into an infra ErrorFeedback (scorer stays L3-type-free).
        §1.10: fact (operators==[] in the report) and suspicion (stale .so)
        are stated as such — the suspicion is NOT asserted as fact."""
        msg = (
            f"fact: eval report exists but target op '{op_name}' not found by "
            f"scan_interfaces (report operators=[], total_cases=0). "
        )
        if reason:
            msg += f"{reason}. "
        msg += (
            "suspected (not verified): _C.abi3.so stale (CMake GLOB cache) or "
            f"per-op package not redeployed after adapt. Report: {report_json or '<none>'}"
        )
        return msg

    @staticmethod
    def _no_report_error(op_name: str, search_dirs: list[Path]) -> str:
        """Reason string when NO report was found anywhere (step-102). Fact
        (searched where, found nothing) and suspicion (kernel_eval crashed
        early) are separated — the old文案 asserted "likely crashed" as if
        measured (§1.10 错误不冒充)."""
        searched = "; ".join(str(d) for d in search_dirs)
        return (
            f"fact: no eval report (*_eval_*.json) found for op '{op_name}' — "
            f"searched: {searched}. "
            "suspected (not verified): kernel_eval exited before writing its "
            "report, or crashed mid-run — check subprocess log for its exit "
            "status and stderr before attributing."
        )

    def _infra_error(self, op_name: str, reason: str) -> str:
        """Reason string for a pre-eval environment breakage (e.g. cann_bench_utils
        unreachable). The stage wraps it into an infra ErrorFeedback."""
        return f"cann-bench eval 前置环境缺失 (op '{op_name}'): {reason}"

    @staticmethod
    def _find_latest_report(reports_dir: Path) -> str:
        """Find the most recent eval_*.json under reports/."""
        if not reports_dir.exists():
            return ""
        candidates = sorted(
            reports_dir.glob("**/*_eval_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return str(candidates[0]) if candidates else ""

    @staticmethod
    def snake_to_pascal(name: str) -> str:
        """Convert snake_case to PascalCase: 'swi_glu' → 'SwiGlu'.

        单点实现委托 domain/op_name(§1.15/§2.5)——注册名↔落盘名 case 规则只允许
        一处定义,codegen 机械校验与 eval 共享同一派生,避免两端漂移。
        """
        from ascendc_devkit.domain.op_name import snake_to_pascal as _snake_to_pascal
        return _snake_to_pascal(name)
