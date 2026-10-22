"""cann-bench 任务发现与校验。

任务固定为 cann-bench 的 ``tasks/<level>/<op>`` 目录，至少包含
``proto.yaml``、``golden.py``、``cases.yaml``。task id 取 golden 入口
函数名，同时也是 AscendC-DevKit 使用的算子名。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

try:
    from . import config as cfg
except ImportError:  # 脚本方式直接执行
    import config as cfg


class TaskError(RuntimeError):
    """任务声明无法解析或文件不完整。"""


REQUIRED_FILES = ("proto.yaml", "golden.py", "cases.yaml")


@dataclass(frozen=True)
class Task:
    """一个已解析、已校验的 cann-bench 任务。"""

    id: str
    path: Path
    rel: str
    level: str


def golden_entry(golden_path: Path) -> str:
    """返回 golden.py 中唯一的顶层函数名（排除 get_input）。"""
    try:
        tree = ast.parse(golden_path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        raise TaskError(f"cannot parse {golden_path}: {exc}") from exc
    names = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name != "get_input"
    ]
    if len(names) != 1:
        raise TaskError(
            f"{golden_path}: expected exactly one top-level golden entry "
            f"(excluding get_input), got {names}"
        )
    return names[0]


def _resolve_line(line: str) -> Path:
    """把一行 ``tasks/<level>/<op>`` 解析为绝对路径。"""
    line = line.split("#", 1)[0].strip()
    rel = Path(line)
    if (
        line.startswith("/")
        or len(rel.parts) != 3
        or rel.parts[0] != "tasks"
        or not rel.parts[1].startswith("level")
    ):
        raise TaskError(f"expected tasks/<level>/<op>, got {line!r}")
    return (cfg.CANN_BENCH / rel).resolve()


def _make_task(path: Path) -> Task:
    """校验任务目录与必需文件，构造 Task。"""
    if not path.is_dir():
        raise TaskError(f"task directory does not exist: {path}")
    missing = [name for name in REQUIRED_FILES if not (path / name).is_file()]
    if missing:
        raise TaskError(f"{path}: missing required files {missing}")
    rel = path.relative_to(cfg.CANN_BENCH).as_posix()
    return Task(
        id=golden_entry(path / "golden.py"),
        path=path,
        rel=rel,
        level=Path(rel).parts[1],
    )


def load_split(path: Path) -> list[Task]:
    """读取一个任务清单文件，逐行解析。"""
    if not path.is_file():
        raise TaskError(f"split file not found: {path}")
    tasks: list[Task] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.split("#", 1)[0].strip():
            continue
        try:
            tasks.append(_make_task(_resolve_line(line)))
        except TaskError as exc:
            raise TaskError(f"{path}:{lineno}: {exc}") from exc
    return tasks


def load_all() -> dict[str, list[Task]]:
    """加载训练集与测试集，并保证 task id 全局唯一。"""
    train = load_split(cfg.DATA_DIR / "ops_train.txt")
    heldout = load_split(cfg.DATA_DIR / "ops_heldout.txt")

    seen: dict[str, str] = {}
    for split_name, items in (("train", train), ("heldout", heldout)):
        for task in items:
            if task.id in seen:
                raise TaskError(
                    f"duplicate task id {task.id!r}: "
                    f"{seen[task.id]} and {split_name}"
                )
            seen[task.id] = split_name
    return {"train": train, "heldout": heldout}


def task_map(splits: dict[str, list[Task]] | None = None) -> dict[str, Task]:
    """把两个 split 合并成 ``{task_id: Task}`` 映射。"""
    splits = splits or load_all()
    return {t.id: t for items in splits.values() for t in items}


def select(
    ids_text: str = "",
    which: str = "train",
    limit: int = 0,
    splits: dict[str, list[Task]] | None = None,
) -> list[Task]:
    """按显式算子 id 或 split 名称选择任务。"""
    splits = splits or load_all()
    mapping = task_map(splits)

    if ids_text.strip():
        wanted = [x.strip() for x in ids_text.split(",") if x.strip()]
        missing = [x for x in wanted if x not in mapping]
        if missing:
            raise TaskError(
                f"unknown task id(s) {missing}; known ids: {sorted(mapping)}"
            )
        tasks = [mapping[x] for x in wanted]
    elif which == "train":
        tasks = list(splits["train"])
    elif which == "heldout":
        tasks = list(splits["heldout"])
    elif which == "all":
        tasks = list(splits["train"]) + list(splits["heldout"])
    else:
        raise TaskError(f"unknown split {which!r} (expected train|heldout|all)")

    return tasks[:limit] if limit > 0 else tasks
