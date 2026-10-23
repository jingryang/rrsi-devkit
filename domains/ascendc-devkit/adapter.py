# Copyright 2026 The rrsi Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""AscendC-DevKit domain: evolve the DevKit harness on cann-bench operators.

被测对象是 ``third_party/AscendC-DevKit`` 里的 Python 包 ``ascendc_devkit``。
它驱动一个 agent（opencode/sdk 后端）为 cann-bench 的 ``tasks/<level>/<op>``
任务生成 AscendC 算子，然后编译、跑精度用例、跑性能基线。

一次评测的链路：

    Domain.run   -> <候选 worktree>/domains/ascendc-devkit/bench/run_tasks.py
                    候选 worktree 是 rrsi-devkit 整个仓库在该候选 commit 下的
                    git worktree（不是 ascendc-devkit 的单独副本）；其中只有
                    harness_path 指向的 ascendc_devkit 包会随候选变化。
                    （每轮把所有任务塞进一个 DevKit batch 并发执行）
    Domain.score -> 冻结的 domains/ascendc-devkit/bench/score.py 读取
                    runs/<domain>/jobs/<job>/<op>/t<k>/{meta,verdict}.json

reward 定义（与 ``bench/score.py`` 保持一致）::

    reward(trial) = clamp(overall_score / 100, 0, 1)

``overall_score = compile_score + function_score + performance_score``，
满分 100（20/30/50）。只有 infra 失败（没有 snapshot 或 meta）才算 missing；
编译失败、精度失败、性能为 0 都是 present-zero，候选无法靠“让 trial 失败”提分。

本文件只做 RRSI 与 bench 之间的接线：任务集合、运行、打分、领域 guard 和
冒烟检查。四个角色的领域提示词属于 ``briefs.py``，trace 加载/渲染属于
``render.py``，领域宪法属于 ``SKILL.md`` / ``PATTERNS.md``——这些内容不在
本文件里实现。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE))

from rrsi.domain import Domain
import briefs as _briefs

CFG = json.loads((HERE / "rrsi.json").read_text(encoding="utf-8"))
# 四个角色的领域提示词；``{policy}`` 由配置里的标签替换（briefs.py 只写占位符）。
BRIEFS = {k: v.replace("{policy}", str(CFG.get("policy_label", "the frozen policy")))
          for k, v in {"analyst": _briefs.ANALYST, "digester": _briefs.DIGESTER,
                       "proposer": _briefs.PROPOSER, "critic": _briefs.CRITIC}.items()}

# 领域级 guard 阈值；缺省值写在 adapter 里，rrsi.json 的 "guards" 可覆盖。
# guard 是“非补偿性”准入条件：候选即使总分更高，只要踩到其中任何一条就
# 不予采纳，防止靠牺牲可评测性（少交作业、少出有效结果）换分数。
_G = CFG.get("guards") or {}
# 允许的 missing 率上升幅度：infra 失败占比比 incumbent 高出超过该值即拒绝。
MAX_MISSING_RISE = float(_G.get("max_missing_rate_rise", 0.10))
# 允许的 no-submission 率上升幅度：harness 没产出任何算子/部署产物即拒绝。
MAX_NO_SUBMISSION_RISE = float(_G.get("max_no_submission_rise", 0.20))
# 允许的 valid 率下降幅度：snapshot 里拿不到 eval_result 的比例上升即拒绝。
MAX_VALID_DROP = float(_G.get("max_valid_rate_drop", 0.10))
# 允许的 pass 率下降幅度：cann-bench 用例通过率明显退步即拒绝。
MAX_PASS_DROP = float(_G.get("max_pass_rate_drop", 0.10))

# 冒烟检查使用的训练任务数；冒烟只验证 harness 能跑通，不参与候选选择。
SMOKE_N = int(CFG.get("smoke_n", 1))
# 显式钉住的冒烟算子：与训练集解耦，保证存活检查的成本可预期（固定挑一个简单
# 算子，而不是「训练集的第一个」——后者随数据集和顺序变化，可能又贵又难）。
SMOKE_PINNED = [str(x).strip() for x in (CFG.get("smoke_ids") or []) if str(x).strip()]
# 归因阈值：某任务的平均 reward 比 incumbent 下降超过该值即视为回归。
REGRESSION_THRESHOLD = float(CFG.get("regression_threshold", 0.10))


def _num(value, default: float = 0.0) -> float:
    """转成有限浮点数；NaN/Inf/类型错误回退默认值。"""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if out == out and out not in (float("inf"), float("-inf")) else default


def _scorer():
    """惰性导入冻结的打分器（主仓 domains/ascendc-devkit/bench/score.py）。

    这里有意使用主仓的 bench，而不是候选 worktree 里的副本：评测逻辑
    属于 RRSI 的冻结部分，候选只允许改 harness（ascendc_devkit 包）。
    """
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    from bench import score as scorelib

    return scorelib


def _tasklib():
    """惰性导入任务发现模块（读取 data/ops_train.txt / ops_heldout.txt）。"""
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    from bench import tasks as tasklib

    return tasklib


class AscendCDevKitDomain(Domain):
    """AscendC-DevKit 的 RRSI Domain 实现。"""

    name = "ascendc-devkit"

    # 声明harness路径和可进化的文件后缀，diff / commit / proposer 编辑都限制
    # 当前只把 Python 包本身纳入可进化范围，resources/、scripts/、docs/ 暂不参与进化。
    harness_path = "../../third_party/AscendC-DevKit/src/ascendc_devkit"
    source_exts = {".py"}

    # 四个角色的领域提示词（analyst / digester / proposer / critic）。
    briefs = BRIEFS

    # proposer 的附加资产区：平台技能树。运行中的 agent 对它只读（经验写入
    # run 产物目录），经验库的并入由出策环节承担（见 briefs._SKILL_TREE_INTEGRITY）。
    # 以 skills/ 前缀寻址；不进 list_files/dump 初始视图，不受 harness exts 约束。
    aux_roots = {"skills": ("../../third_party/AscendC-DevKit/.claude/skills",
                            {".md"})}

    # 被禁止的模式，rsi修改harness的文件段包含以下正则表达式就被打回。
    # 当前主要禁止rsi修改打分组件。
    critic_patterns = [
        (r"domains/ascendc-devkit/bench/(?:score|tasks|config|run_tasks)\.py",
         "edits the frozen evaluation/plumbing layer"),
        (r"/home/cann-bench|/home/rrsi-devkit|\.\./\.\./\.\.",
         "absolute or upward path escape out of the harness"),
        (r"(?:overall_score|pass_rate|compile_score|function_score|performance_score)"
         r"\s*=\s*(?:100(?:\.0)?|50(?:\.0)?|30(?:\.0)?|20(?:\.0)?|1(?:\.0)?)\b",
         "writes a constant grader score instead of computing it"),
        (r"runs/ascendc-devkit/jobs|jobs/[^ \n]*/t\d+/|verdict\.json",
         "targets RRSI run artifacts rather than the harness"),
    ]

    # 把 diff 映射回固定的 K 词汇（rrsi/components.py）。
    # RRSI 会把修改归因到某个组件上，匹配优先级按列表的顺序。
    component_signals = [
        ("output_plumbing",
         [r"report\.py", r"report\b", r"snapshot", r"artifacts?/", r"write_json",
          r"serializ", r"workspace\.py"]),
        ("control_flow",
         [r"dispatcher", r"graph_executor", r"stages?/", r"workflow", r"retry",
          r"max_attempts", r"feedback", r"node_status"]),
        ("context_mgmt",
         [r"compact", r"summar", r"context", r"history", r"transcript",
          r"truncat"]),
        ("config",
         [r"runtime_config", r"orchestration-config", r"threshold", r"timeout",
          r"defaults?\b"]),
        ("client_tool",
         [r"backend", r"opencode", r"sdk", r"tool", r"mcp", r"capabilit"]),
        ("prompt",
         [r"prompt", r"requirement", r"template", r"design_substage",
          r"codegen"]),
        ("skill", [r"skills?/", r"skill_"]),
        ("subagent", [r"subagent", r"sub_agent", r"worker"]),
        ("memory", [r"memory", r"state_store", r"cache"]),
    ]

    def __init__(self):
        self._task_cache: dict | None = None

    # ---- 任务集合 --------------------------------------------------------
    def _tasks(self) -> dict:
        if self._task_cache is None:
            self._task_cache = _tasklib().load_all()
        return self._task_cache

    def evolve_ids(self) -> list[str]:
        """训练集：每轮候选 harness 在完整训练集上评测。"""
        return [task.id for task in self._tasks()["train"]]

    def heldout_ids(self) -> list[str]:
        """测试集：只用于准入，不参与候选提案。"""
        return [task.id for task in self._tasks()["heldout"]]

    def smoke_ids(self, incumbent_per_task=None) -> list[str]:
        """冒烟任务：``smoke_ids`` 显式配置时直接用（与训练集无关）；
        否则退回「incumbent 全部 trial 都有效的训练任务」中取 ``smoke_n`` 个。"""
        if SMOKE_PINNED:
            known = {task.id for task in self._tasks()["train"]
                     + self._tasks()["heldout"]}
            unknown = [tid for tid in SMOKE_PINNED if tid not in known]
            if unknown:
                raise ValueError(
                    f"rrsi.json smoke_ids {unknown} 不在当前任务清单里；"
                    f"已配置的算子: {sorted(known)}")
            return list(SMOKE_PINNED)
        ids = self.evolve_ids()
        n = max(1, SMOKE_N)
        if incumbent_per_task:
            solid = [
                tid for tid in ids
                if tid in incumbent_per_task
                and incumbent_per_task[tid].rewards
                and min(incumbent_per_task[tid].rewards) > 0.0
            ]
            if len(solid) >= n:
                return solid[:n]
        return ids[:n]

    def regression_threshold(self, k: int) -> float:
        """逐任务均值下降超过该值即视为回归（0-1 连续分，默认 0.10）。"""
        return REGRESSION_THRESHOLD

    # ---- 评测 ------------------------------------------------------------
    def run(self, root, runs_dir, job, ids, k, log_prefix=""):
        """在候选 worktree 上跑 ``bench/run_tasks.py``。
        
        ``run_tasks.py`` 自己负责 CANN 环境、NPU 卡探测、cann-bench
        worktree 和 DevKit batch manifest；这里只负责定位脚本和日志。
        评测是 resume-safe 的：已有 meta+verdict 的 trial 会被跳过。
        """
        root, runs_dir = Path(root), Path(runs_dir)
        bench = root / "domains" / "ascendc-devkit" / "bench" / "run_tasks.py"
        if not bench.is_file():
            raise RuntimeError(
                f"candidate worktree has no {bench}; commit domains/ascendc-devkit "
                "before running the evolve loop"
            )
        log = runs_dir / "logs" / f"{log_prefix or job}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            sys.executable, str(bench),
            "--job", job,
            "--n", str(k),
            "--ids", ",".join(ids),
            "--runs-dir", str(runs_dir),
        ]
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"\n$ {' '.join(cmd)}\n")
            fh.flush()
            rc = subprocess.run(
                cmd, cwd=str(bench.parent), stdout=fh, stderr=subprocess.STDOUT
            ).returncode
        if rc != 0:
            # 非零退出可能只是个别任务 infra 失败；产物仍然可打分。
            print(f"[ascendc-devkit] WARNING run rc={rc} (see {log})", flush=True)

    def score(self, runs_dir, job, ids, k):
        """把 trial 产物聚合成 ``{task_id: TaskResult}``。"""
        return _scorer().score_job(Path(runs_dir), job, list(ids), k)

    # ---- 证据（analyst / digester / proposer 读取） -----------------------
    #
    # trial 产物由 freeze 的 ``bench/run_tasks.py`` 写在
    # ``jobs/<job>/<op>/t<k>/{meta,verdict}.json`` 与 ``op_src/``；DevKit 的
    # 原始产物（state_snapshot.json / report.md / report.json）在
    # ``meta["snapshot"]`` 的父目录。render.py 只依赖这些路径，所以这里把两者
    # 拼成一个 rec 再交给它渲染。
    def _run_dir(self, tdir: Path, meta: dict) -> Path | None:
        snap = meta.get("snapshot") or ""
        if snap:
            p = Path(snap)
            if p.is_file():
                return p.parent
        return None

    @staticmethod
    def _prompt(task_id: str) -> str:
        """需求描述（desc.md），analyst 判断机制时需要看到算子语义。"""
        try:
            splits = _tasklib().load_all()
            for task in splits["train"] + splits["heldout"]:
                if task.id == task_id:
                    desc = task.path / "desc.md"
                    if desc.is_file():
                        return desc.read_text(errors="replace")
        except Exception:  # noqa: BLE001 - 证据渲染不得打断 round
            pass
        return ""

    @staticmethod
    def _read_tree(root: Path) -> dict:
        """把一个算子目录读成 ``{相对路径: 内容}``（有上限）。"""
        out: dict = {}
        if not root.is_dir():
            return out
        exts = {".cpp", ".h", ".cc", ".cce", ".py", ".txt"}
        budget = 200_000
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p.suffix not in exts or "__pycache__" in p.parts:
                continue
            try:
                body = p.read_text(errors="replace")
            except Exception:  # noqa: BLE001
                continue
            out[str(p.relative_to(root))] = body
            budget -= len(body)
            if budget <= 0 or len(out) >= 60:
                out["...[more files omitted]"] = ""
                break
        return out

    @classmethod
    def _sources(cls, tdir: Path, task_id: str, run_dir: Path | None) -> dict:
        """提交的算子源码：优先 cann-bench worktree，其次 op_src 副本。"""
        from bench import config as bench_cfg

        if run_dir is not None:
            # <batches>/<stamp>/devkit/<batch>/<exec> -> <batches>/<stamp>/repos/<exec>
            batch_root = run_dir.parents[2]
            repo = batch_root / "repos" / run_dir.name
            found = cls._read_tree(repo / bench_cfg.OP_SUBDIR / task_id)
            if found:
                return found
        return cls._read_tree(tdir / "op_src")

    def product_experiences(self, runs_dir) -> str:
        """收集各 trial run 产物目录里的经验文件，渲染给 proposer 审阅并入。

        只认 ``jobs/**/artifacts`` 下的产物经验目录（skill 内置库在
        ``.claude/`` 下、工作树在 ``wt/`` 下，都不在 artifacts 内，天然排除）。
        预算封顶；渲染失败不打断 round。
        """
        runs = Path(runs_dir)
        if not runs.is_dir():
            return ""
        parts: list[str] = []
        budget = 60_000
        try:
            for art in sorted(runs.glob("jobs/**/artifacts")):
                for d in sorted(art.rglob("vf_experiences")):
                    for f in sorted(d.rglob("*.md")):
                        if budget <= 0:
                            parts.append("...[budget capped]")
                            return "\n\n".join(parts)
                        body = f.read_text(errors="replace")
                        parts.append(f"===== FILE: {f.relative_to(runs)} =====\n{body}")
                        budget -= len(body)
        except Exception:  # noqa: BLE001 - 证据渲染不得打断 round
            pass
        return "\n\n".join(parts)

    def load_trial(self, runs_dir, job, task_id, trial):
        """一次 trial 的全部证据；从未跑过（或 infra 失败）返回 None。"""
        from render import load_verdict, run_reports

        runs_dir = Path(runs_dir)
        from bench import config as bench_cfg

        tdir = bench_cfg.trial_dir(runs_dir, job, task_id, trial)
        meta_path, verdict_path = tdir / "meta.json", tdir / "verdict.json"
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            meta = None
        try:
            stored = json.loads(verdict_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            stored = None
        if meta is None and stored is None:
            return None

        run_dir = self._run_dir(tdir, meta or {})
        rel_parts = str((meta or {}).get("task_rel", "")).split("/")
        op = {"name": task_id,
              "k": rel_parts[1] if len(rel_parts) > 1 else "", "category": ""}
        if run_dir is not None:
            verdict = load_verdict(run_dir)
            report = run_reports(run_dir)
        else:
            verdict, report = dict(stored or {}), {}
        # 冻结的 verdict 是权威分数；render 只是把同一份事实展开成证据。
        for key in ("overall_score", "compile_score", "function_score",
                    "performance_score", "pass_rate", "num_cases", "num_passed"):
            if verdict.get(key) is None and stored is not None:
                verdict[key] = stored.get(key)
        return {
            "task_id": task_id,
            "op": op,
            "trial": trial,
            "run_dir": str(run_dir) if run_dir is not None else "",
            "meta": meta or {},
            "report": report,
            "verdict": verdict,
            "prompt": self._prompt(task_id),
            "sources": self._sources(tdir, task_id, run_dir),
            "compile_log": verdict.get("compile_log") or "",
            "rubric": None,
        }

    def render_trace(self, rec, detail: bool = False) -> str:
        from render import render_full

        return render_full(rec, detail=detail)

    def task_row(self, task_id, rec, tr) -> str:
        from render import stats

        s = stats(rec or {}) if rec else {}
        return (f"{task_id} | rewards={getattr(tr, 'rewards', '?')} | "
                f"class={s.get('class')} | overall={s.get('overall')} | "
                f"cases={s.get('cases')} | function={s.get('function')} | "
                f"perf={s.get('perf')}")

    def guards(self, incumbent, candidate) -> list[str]:
        """非补偿性领域检查：候选不能靠牺牲可评测性换取分数。"""
        out: list[str] = []

        def delta(cand_key: str, inc_key: str) -> float:
            return (_num(candidate.extra.get(cand_key))
                    - _num(incumbent.extra.get(inc_key)))

        rise = delta("eval_missing_rate", "eval_missing_rate")
        if rise > MAX_MISSING_RISE:
            out.append(f"missing-trial rate rose {rise:+.3f} "
                       f"(limit {MAX_MISSING_RISE})")

        rise = delta("no_submission_rate", "no_submission_rate")
        if rise > MAX_NO_SUBMISSION_RISE:
            out.append(f"no-submission rate rose {rise:+.3f} "
                       f"(limit {MAX_NO_SUBMISSION_RISE})")

        drop = _num(incumbent.extra.get("valid_rate")) - _num(
            candidate.extra.get("valid_rate"))
        if drop > MAX_VALID_DROP:
            out.append(f"valid rate fell {drop:+.3f} (limit {MAX_VALID_DROP})")

        drop = _num(incumbent.extra.get("pass_rate")) - _num(
            candidate.extra.get("pass_rate"))
        if drop > MAX_PASS_DROP:
            out.append(f"pass rate fell {drop:+.3f} (limit {MAX_PASS_DROP})")

        return out

    # ---- 门禁 ------------------------------------------------------------
    def smoke(self, root, runs_dir, job, ids):
        """候选 harness 的存活检查：能编译、能 import、能端到端跑完一个 trial。"""
        root, runs_dir = Path(root), Path(runs_dir)
        hdir = self.harness_dir(root)

        comp = subprocess.run(
            [sys.executable, "-m", "compileall", "-q", str(hdir)],
            capture_output=True, text=True,
        )
        if comp.returncode != 0:
            return False, {"stage": "compile",
                           "err": (comp.stdout + comp.stderr)[-1500:]}

        # PYTHONPATH 指向 src/，确保 import 的是候选 worktree 里的包。
        code = (
            "import ascendc_devkit\n"
            "from ascendc_devkit.application.batch_runner import "
            "load_manifest, build_task_request\n"
            "from ascendc_devkit.application.dispatcher import dispatch\n"
            "from ascendc_devkit.domain.verification import EvalResult\n"
            "from ascendc_devkit.cli.main import main\n"
            "assert callable(main) and callable(dispatch) and callable(build_task_request)\n"
            "assert EvalResult is not None\n"
            "print('CTOR OK')\n"
        )
        env = {**os.environ, "PYTHONPATH": str(hdir.parent)}
        ctor = subprocess.run(
            [sys.executable, "-c", code], cwd=str(root), env=env,
            capture_output=True, text=True,
        )
        if ctor.returncode != 0 or "CTOR OK" not in ctor.stdout:
            return False, {"stage": "ctor",
                           "err": (ctor.stderr or ctor.stdout)[-1500:]}

        # 冒烟 job 每次重跑，避免上一次残留的 verdict 让 runner 直接跳过。
        shutil.rmtree(runs_dir / "jobs" / job, ignore_errors=True)
        self.run(root, runs_dir, job, ids, 1, log_prefix=job)
        per, extra = self.score(runs_dir, job, ids, 1)
        missing = sum(result.missing for result in per.values())
        ok = (
            missing == 0
            and _num(extra.get("valid_rate")) > 0.0
            and _num(extra.get("no_submission_rate")) < 1.0
        )
        return ok, {"stage": "run", "smoke_ids": list(ids),
                    "missing": missing, **extra}


DOMAIN = AscendCDevKitDomain()
