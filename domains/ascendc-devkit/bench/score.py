#!/usr/bin/env python3
"""把 AscendC-DevKit 的 trial 记录聚合为 RRSI 的 ``TaskResult``。

runner 会为每个 trial 写 ``meta.json`` 和 ``verdict.json``。只有两者同时
存在才视为 *present*；基础设施失败不会写 verdict，计为 missing（reward 0
但占用完整分母，符合 ``rrsi.evaluate`` 的语义）。编译失败/精度失败仍然有
verdict，属于 present-zero，这样候选无法通过「让 trial 失败」来提高分数。

用法：

    python3 score.py --job <job> --n 1 --ids exp,softmax
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:  # 以脚本方式导入（adapter 直接执行本文件）
    from . import config as cfg
    from . import tasks as tasklib
except ImportError:  # pragma: no cover - 直接执行
    import config as cfg
    import tasks as tasklib


# 优先使用 RRSI 真实的 TaskResult，方便 adapter 直接交给
# rrsi.evaluate.aggregate；仓库外独立运行时回退到字段完全一致的本地类型。
try:
    sys.path.insert(0, str(cfg.REPO_ROOT))
    from rrsi.evaluate import TaskResult  # type: ignore
except Exception:  # noqa: BLE001

    @dataclass
    class TaskResult:  # type: ignore[no-redef]
        """与 rrsi.evaluate.TaskResult 保持一致的兜底实现。"""

        rewards: list[float]
        weights: list[float] = field(default_factory=list)
        tokens: list = field(default_factory=list)
        missing: int = 0
        extra: dict = field(default_factory=dict)

        def __post_init__(self) -> None:
            # 未显式给权重/token 时补默认值。
            if not self.weights:
                self.weights = [1.0] * len(self.rewards)
            if not self.tokens:
                self.tokens = [None] * len(self.rewards)

        @property
        def mean(self) -> float:
            """加权平均；权重全为 0 时返回 0。"""
            total = sum(self.weights)
            if not total:
                return 0.0
            return sum(r * w for r, w in zip(self.rewards, self.weights)) / total


def read_json(path: Path) -> dict | None:
    """读取 JSON；缺失或损坏返回 None。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _num(value, default: float = 0.0) -> float:
    """转成有限浮点数；NaN/Inf/类型错误都回退默认值。"""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _score(verdict: dict) -> float:
    """读取 verdict 分数，但绝不接受越界 reward。

    交叉校验失败（``scores_consistent is False``）时直接记 0。
    """
    score = _num(verdict.get("score"))
    if verdict.get("scores_consistent") is False:
        return 0.0
    return max(0.0, min(1.0, score))


def read_trial(runs_dir: Path | str, job: str, task_id: str, trial: int) -> dict | None:
    """读取单个 trial；meta/verdict 缺一即返回 None（计为 missing）。"""
    tdir = cfg.trial_dir(runs_dir, job, task_id, trial)
    meta = read_json(tdir / "meta.json")
    verdict = read_json(tdir / "verdict.json")
    if meta is None or verdict is None:
        return None
    return {
        "task_id": task_id,
        "trial": trial,
        "dir": str(tdir),
        "meta": meta,
        "verdict": verdict,
        "score": _score(verdict),
    }


def read_task(runs_dir: Path | str, job: str, task_id: str, k: int) -> list[dict | None]:
    """读取某任务 t0..t(k-1) 的全部 trial。"""
    return [read_trial(runs_dir, job, task_id, trial) for trial in range(k)]


def _trial_flags(record: dict | None) -> dict:
    """把一个 trial 记录展开成用于聚合的数值标志。

    missing trial 的所有标志都是 0；present trial 才贡献 valid/分数/
    pass_rate 等指标。
    """
    if record is None:
        return {
            "present": 0,
            "valid": 0,
            "score": 0.0,
            "pass_rate": 0.0,
            "no_submission": 0,
            "timeout": 0,
            "compile_zero": 0,
            "inconsistent": 0,
            "overall": 0.0,
            "compile": 0.0,
            "function": 0.0,
            "performance": 0.0,
        }
    verdict = record["verdict"]
    meta = record["meta"]
    # valid=1 表示 snapshot 中存在 eval_result。
    valid = 1 if _num(verdict.get("valid")) >= 1.0 else 0
    return {
        "present": 1,
        "valid": valid,
        "score": record["score"],
        "pass_rate": max(0.0, min(1.0, _num(verdict.get("pass_rate")))),
        "no_submission": 1 if _num(verdict.get("no_submission")) >= 1.0 else 0,
        "timeout": 1 if meta.get("status") == "timeout" else 0,
        # 有效但编译分为 0：候选生成了代码但编不过。
        "compile_zero": 1 if valid and _num(verdict.get("compile_score")) <= 0.0 else 0,
        "inconsistent": 0 if verdict.get("scores_consistent") is not False else 1,
        "overall": _num(verdict.get("overall_score")),
        "compile": _num(verdict.get("compile_score")),
        "function": _num(verdict.get("function_score")),
        "performance": _num(verdict.get("performance_score")),
    }


def summarize(records_by_task: dict[str, list[dict | None]]) -> dict:
    """计算 guards 与报告使用的领域级聚合指标。

    以 ``slots = n_tasks * k`` 为分母的 rate 会把 missing 计入（偏保守）；
    ``*_present`` 指标只在 present trial 上取均值。
    """
    n_tasks = len(records_by_task)
    k = len(next(iter(records_by_task.values()))) if records_by_task else 0
    slots = n_tasks * k
    totals = {
        "present": 0,
        "valid": 0,
        "score": 0.0,
        "pass_rate": 0.0,
        "no_submission": 0,
        "timeout": 0,
        "compile_zero": 0,
        "inconsistent": 0,
        "overall": 0.0,
        "compile": 0.0,
        "function": 0.0,
        "performance": 0.0,
    }
    present = 0
    for records in records_by_task.values():
        for record in records:
            flags = _trial_flags(record)
            present += flags["present"]
            for key in totals:
                totals[key] += flags[key]

    def rate(key: str) -> float:
        """按全部 slots 求比例（missing 计入分母）。"""
        return totals[key] / slots if slots else 0.0

    def mean_present(key: str) -> float:
        """只在 present trial 上求均值。"""
        return totals[key] / present if present else 0.0

    return {
        "n_tasks": n_tasks,
        "k": k,
        "slots": slots,
        "present": present,
        "missing": slots - present,
        "eval_missing_rate": (slots - present) / slots if slots else 0.0,
        "mean_score": totals["score"] / slots if slots else 0.0,
        "mean_present_score": mean_present("score"),
        "valid_rate": rate("valid"),
        "pass_rate": rate("pass_rate"),
        "pass_rate_present": mean_present("pass_rate"),
        "no_submission_rate": rate("no_submission"),
        "timeout_rate": rate("timeout"),
        "compile_zero_rate": rate("compile_zero"),
        "scores_inconsistent_rate": rate("inconsistent"),
        "mean_overall": mean_present("overall"),
        "mean_compile": mean_present("compile"),
        "mean_function": mean_present("function"),
        "mean_performance": mean_present("performance"),
    }


def build_task_result(records: list[dict | None], task_id: str) -> TaskResult:
    """把一个任务的 k 个 trial 转成 RRSI TaskResult。

    missing trial 的 reward 补 0，但保留在 rewards 中——分母仍是完整的 k。
    """
    k = len(records)
    rewards = [record["score"] if record is not None else 0.0 for record in records]
    missing = sum(1 for record in records if record is None)
    extra = summarize({task_id: records})
    return TaskResult(rewards=rewards, tokens=[None] * k, missing=missing, extra=extra)


def score_job(
    runs_dir: Path | str,
    job: str,
    ids: list[str],
    k: int,
    *,
    which: str = "all",
) -> tuple[dict[str, TaskResult], dict]:
    """返回 ``({task_id: TaskResult}, extra)``，供 RRSI Domain adapter 使用。"""
    # ids 为空时按 which 选择 split；否则按给定 id 顺序评测。
    selected = tasklib.select(",".join(ids), which=which)
    task_ids = [task.id for task in selected]

    records_by_task = {
        task_id: read_task(runs_dir, job, task_id, k) for task_id in task_ids
    }
    per_task = {
        task_id: build_task_result(records, task_id)
        for task_id, records in records_by_task.items()
    }
    extra = summarize(records_by_task)
    extra["tasks"] = task_ids
    return per_task, extra


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析独立运行时的命令行参数。"""
    parser = argparse.ArgumentParser(
        description="Aggregate AscendC-DevKit trial verdicts for RRSI."
    )
    parser.add_argument("--job", required=True)
    parser.add_argument("--ids", default="", help="comma-separated operator ids")
    parser.add_argument(
        "--which", default="train", choices=["train", "heldout", "all"],
        help="task split when --ids is empty (default: train)",
    )
    parser.add_argument("--n", "--k", dest="k", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--runs-dir", default=str(cfg.RUNS_DIR))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """独立打分入口：打印 S、missing、聚合指标与每任务明细。"""
    args = parse_args(argv)
    if args.k < 1:
        print("error: --n must be >= 1", file=sys.stderr)
        return 2

    try:
        selected = tasklib.select(args.ids, which=args.which, limit=args.limit)
    except tasklib.TaskError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    runs_dir = Path(args.runs_dir).expanduser().resolve()
    task_ids = [task.id for task in selected]
    records_by_task = {
        task_id: read_task(runs_dir, args.job, task_id, args.k)
        for task_id in task_ids
    }
    per_task = {
        task_id: build_task_result(records, task_id)
        for task_id, records in records_by_task.items()
    }
    extra = summarize(records_by_task)
    extra["tasks"] = task_ids

    # S = Σ reward·weight / Σ weight；missing trial 的 reward 已补 0。
    weights_total = sum(sum(result.weights) for result in per_task.values())
    weighted = sum(
        reward * weight
        for result in per_task.values()
        for reward, weight in zip(result.rewards, result.weights)
    )
    payload = {
        "job": args.job,
        "k": args.k,
        "S": weighted / weights_total if weights_total else 0.0,
        "missing": sum(result.missing for result in per_task.values()),
        "extra": extra,
        "per_task": {
            task_id: {
                "rewards": result.rewards,
                "weights": result.weights,
                "tokens": result.tokens,
                "missing": result.missing,
                "mean": result.mean,
                "extra": result.extra,
            }
            for task_id, result in per_task.items()
        },
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
