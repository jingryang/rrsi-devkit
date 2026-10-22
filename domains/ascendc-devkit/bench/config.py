"""AscendC-DevKit 领域 bench 适配层的配置模块。

所有配置统一从域目录下的 ``rrsi.json`` 读取，不读取任何环境变量。相对路径
一律相对 ``domains/ascendc-devkit/`` 解析，因此候选 worktree 里的副本会
自动指向该 worktree 自己的 ``third_party/AscendC-DevKit`` 和 ``runs``。

模块仅依赖标准库，既供 RRSI 领域 adapter 导入，也供独立 runner 直接执行。
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

# ---------------------------------------------------------------------------
# 仓库目录布局
# ---------------------------------------------------------------------------

# 当前文件位于 <repo>/domains/ascendc-devkit/bench，自下而上推导各层目录。
BENCH_DIR = Path(__file__).resolve().parent
DOMAIN_DIR = BENCH_DIR.parent
REPO_ROOT = DOMAIN_DIR.parent.parent

#: 唯一配置来源。
CONFIG_PATH = DOMAIN_DIR / "rrsi.json"


def _load_bench_config() -> dict:
    """读取 ``rrsi.json`` 中的 ``bench`` 配置段。"""
    if not CONFIG_PATH.is_file():
        raise RuntimeError(f"configuration file not found: {CONFIG_PATH}")
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read {CONFIG_PATH}: {exc}") from exc
    bench = raw.get("bench")
    if not isinstance(bench, dict):
        raise RuntimeError(f"{CONFIG_PATH}: missing object field 'bench'")
    return bench


_CFG = _load_bench_config()


def _get(key: str, default=None):
    """取配置值；显式 ``null`` 视为使用默认值。"""
    value = _CFG.get(key, default)
    return default if value is None else value


def _path(key: str, default: str) -> Path:
    """读取路径配置，相对路径按域目录解析。"""
    value = Path(str(_get(key, default))).expanduser()
    if not value.is_absolute():
        value = DOMAIN_DIR / value
    return value.resolve()


def _int(key: str, default: int) -> int:
    """读取整数配置。"""
    try:
        return int(_get(key, default))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{CONFIG_PATH}: bench.{key} must be an integer") from exc


def _bool(key: str, default: bool) -> bool:
    """读取布尔配置；同时容忍字符串形式。"""
    value = _get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    raise RuntimeError(f"{CONFIG_PATH}: bench.{key} must be a boolean")


def _str(key: str, default: str = "") -> str:
    """读取字符串配置。"""
    value = _get(key, default)
    if not isinstance(value, str):
        raise RuntimeError(f"{CONFIG_PATH}: bench.{key} must be a string")
    return value.strip()


# 训练集 / 测试集清单所在目录。
DATA_DIR = _path("data_dir", "data")

#: 候选 harness 根目录，指向当前 worktree 内的 checkout。
HARNESS = _path("harness", "../../third_party/AscendC-DevKit")

# cann-bench 基仓：每个 trial 都会在它上面创建独立 worktree。
CANN_BENCH = _path("cann_bench", "/home/cann-bench")

# RRSI 的运行目录；trial 产物写到 <RUNS_DIR>/jobs/<job>/<op>/t<k>/。
RUNS_DIR = _path("runs_dir", "../../runs")

# cann-bench 仓库 profile 名称，供 DevKit 做 op_dir 解析。
REPO_PROFILE = _str("repo_profile", "cann-bench")
# 算子生成目录相对 cann-bench worktree 根的子路径。
OP_SUBDIR = _str("op_subdir", "examples/aclnn_launch_example/csrc/ops")

#: 设计目标芯片代际码（A2/A3/A5）。为空表示让 AscendC-DevKit 探测本机芯片。
CHIP = _str("chip", "")

#: 运行候选 harness 的 Python 解释器（必须 >= 3.11）。
PYTHON = _path("python", "/usr/local/python3.12.13/bin/python")
#: 需要 source 的 CANN 环境脚本；配置为空字符串表示沿用当前 shell。
CANN_ENV = _path("cann_env", "") if _str("cann_env", "") else None
#: 显式指定候选卡号；空列表表示运行时用 ``npu-smi`` 探测健康卡。
NPU_IDS = _get("npu_ids", [])
if not isinstance(NPU_IDS, list):
    raise RuntimeError(f"{CONFIG_PATH}: bench.npu_ids must be a list of integers")
NPU_IDS = [int(x) for x in NPU_IDS]

# ---------------------------------------------------------------------------
# 工程参数（超时、清理策略）
# ---------------------------------------------------------------------------

# 单个 trial（一次完整 self_evolve_op）的墙钟超时，单位秒。
TRIAL_TIMEOUT = _int("trial_timeout_sec", 7200)
#: 在 workflow 自身超时之后额外留出的宽限时间，让 DevKit 有机会落盘
#: state_snapshot.json，随后我们再杀掉整个进程组。
HARD_TIMEOUT_GRACE = _int("hard_timeout_grace_sec", 600)
# 单个 stage 的超时；0 表示交给 DevKit 的 orchestration-config 决定。
STAGE_TIMEOUT = _int("stage_timeout_sec", 0)
# 是否保留每个 trial 的 cann-bench worktree（默认清理，调试时可开）。
KEEP_WORKTREES = _bool("keep_worktrees", False)
# 同一 trial 的最大尝试次数；超过后不再自动重试。
MAX_ATTEMPTS = _int("max_attempts", 3)


# ---------------------------------------------------------------------------
# 运行时探测（解释器、CANN、NPU、版本信息）
# ---------------------------------------------------------------------------


def _version_tuple(text: str) -> tuple[int, int]:
    """把 ``(3, 12)`` 形式的版本输出解析成 (3, 12)。"""
    m = re.search(r"\((\d+),\s*(\d+)", text)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def python_bin() -> Path:
    """返回 rrsi.json 配置的 Python 解释器，并校验版本 >= 3.11。"""
    if not PYTHON.is_file():
        raise RuntimeError(
            f"configured python not found: {PYTHON} "
            f"(set bench.python in {CONFIG_PATH})"
        )
    try:
        out = subprocess.check_output(
            [str(PYTHON), "-c", "import sys; print(sys.version_info[:2])"],
            text=True,
            timeout=20,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"cannot execute configured python {PYTHON}: {exc}") from exc
    if _version_tuple(out) < (3, 11):
        raise RuntimeError(
            f"configured python is older than 3.11: {PYTHON} (reported {out.strip()})"
        )
    return PYTHON


def cann_env() -> Path | None:
    """返回配置中需要 source 的 CANN 环境脚本；None 表示沿用当前 shell。"""
    return CANN_ENV


def detect_npu_ids() -> list[int]:
    """返回候选 NPU 卡号。

    配置了 ``bench.npu_ids`` 时直接使用；否则运行时调用 ``npu-smi info``
    探测，并排除状态为 Alarm/Critical 的卡。若一张健康卡都没有，则回退到
    探测到的卡列表，最后兜底 [0]。
    """
    if NPU_IDS:
        return list(NPU_IDS)

    try:
        out = subprocess.check_output(
            ["npu-smi", "info"],
            text=True,
            timeout=30,
            stderr=subprocess.STDOUT,
        )
    except Exception:  # noqa: BLE001
        return [0]

    healthy: list[int] = []
    seen: list[int] = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.strip().strip("|").split("|")]
        if len(parts) < 2:
            continue
        # 卡主行首列为 "<卡号> <型号>"，子行（Chip/Bus）首列是纯数字。
        m = re.match(r"^(\d+)\s+\S", parts[0])
        if not m:
            continue
        idx = int(m.group(1))
        health = parts[1]
        if health not in {"OK", "Alarm", "Warning", "Critical", "Unhealthy"}:
            # 该行不是健康状态行（例如 Bus-Id / 使用率行），跳过。
            continue
        if idx not in seen:
            seen.append(idx)
        if health == "OK" and idx not in healthy:
            healthy.append(idx)
    return sorted(healthy) or sorted(seen) or [0]


def harness_ref() -> dict[str, str]:
    """返回候选 harness 的版本溯源信息（尽力而为，失败时留空）。"""
    ref: dict[str, str] = {"repo_head": "", "harness_tree": ""}
    try:
        ref["repo_head"] = subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            text=True,
            timeout=15,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:  # noqa: BLE001
        pass
    try:
        # 记录 harness 目录树对象哈希，便于区分不同候选改动。
        rel = HARNESS.relative_to(REPO_ROOT).as_posix()
        ref["harness_tree"] = subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "rev-parse", f"HEAD:{rel}"],
            text=True,
            timeout=15,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:  # noqa: BLE001
        pass
    return ref


# ---------------------------------------------------------------------------
# 路径工具与环境自检
# ---------------------------------------------------------------------------


def jobs_dir(runs_dir: Path | str | None = None) -> Path:
    """返回某次 RRSI 运行的所有 job 根目录。"""
    return Path(runs_dir or RUNS_DIR) / "jobs"


def trial_dir(
    runs_dir: Path | str | None, job: str, task_id: str, trial: int
) -> Path:
    """返回单个 (job, task, trial) 的产物目录。"""
    return jobs_dir(runs_dir) / job / task_id / f"t{trial}"


def validate_environment(*, require_git: bool = True) -> list[str]:
    """检查运行前置条件，返回问题列表；空列表表示可以开跑。"""
    problems: list[str] = []
    if not HARNESS.is_dir():
        problems.append(f"candidate harness not found: {HARNESS}")
    if not (HARNESS / "src" / "ascendc_devkit" / "cli" / "main.py").is_file():
        problems.append(f"not an AscendC-DevKit checkout: {HARNESS}")
    if not CANN_BENCH.is_dir():
        problems.append(f"cann-bench not found: {CANN_BENCH}")
    if require_git:
        # 每个 trial 依赖 git worktree 隔离，cann-bench 必须是 git 仓。
        try:
            subprocess.check_output(
                ["git", "-C", str(CANN_BENCH), "rev-parse", "--is-inside-work-tree"],
                text=True,
                timeout=15,
                stderr=subprocess.DEVNULL,
            )
        except Exception:  # noqa: BLE001
            problems.append(f"cann-bench is not a git repository: {CANN_BENCH}")
    env_script = cann_env()
    if env_script is not None and not env_script.is_file():
        problems.append(f"CANN environment script not found: {env_script}")
    try:
        py = python_bin()
        if not py.is_file():
            problems.append(f"Python interpreter not found: {py}")
    except RuntimeError as exc:
        problems.append(str(exc))
    return problems
