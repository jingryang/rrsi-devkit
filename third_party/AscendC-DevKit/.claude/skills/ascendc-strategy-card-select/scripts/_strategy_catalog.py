#!/usr/bin/env python3
"""策略库元数据解析的适配层（跨仓单源引用，仅标准库）。

策略卡的权威源是外部策略库自带的 curator skill：

    <strategy_root>/.claude/skills/ascendc-strategy-curator/scripts/_catalog.py

该脚本负责解析卡片顶部的 `<!-- strategy-metadata ... -->` 元数据块、渲染正文、校验
条目。本 skill **不 vendor** 它的副本（CLAUDE.md §2.5 唯一通路），而是按路径 import。

本模块存在的唯一理由是**隔离其失败模式**：`_catalog.fail()` 在元数据损坏时抛
SystemExit，一张坏卡会直接把生成器打死。这里逐卡 try/except，把错误收进 card_errors
返回给调用方，让生成器能报告"哪几张卡坏了"而不是整体崩溃（§1.3 错误非静默，
§1.2 宽容兜底）。

跨仓引用的已知脆弱点（调用方应在 run_inputs.json 记录 strategy_root 以便追溯）：
`_catalog.py` 所在的目录属于策略库的内部约定，可能被其产权方改名。
"""

import sys
from pathlib import Path

CURATOR_REL = Path(".claude/skills/ascendc-strategy-curator/scripts")
CATALOG_MODULE = "_catalog.py"


def resolve_curator_scripts(strategy_root: Path, override: str | None = None) -> Path:
    """定位 _catalog.py 所在目录：显式 override > <strategy_root>/<CURATOR_REL>。"""
    base = Path(override).expanduser().resolve() if override \
        else Path(strategy_root).expanduser().resolve() / CURATOR_REL
    target = base / CATALOG_MODULE
    if not target.is_file():
        raise ValueError(
            f"策略库元数据解析器不存在: {target}\n"
            f"期望在 <strategy_root>/{CURATOR_REL}/{CATALOG_MODULE}。\n"
            f"若策略库布局已变更，用 --curator-scripts 显式指定其所在目录。")
    return base


def _import_catalog(curator_scripts: Path):
    """按路径 import _catalog（单源，不落副本）。"""
    key = str(curator_scripts)
    if key not in sys.path:
        sys.path.insert(0, key)
    try:
        import _catalog  # type: ignore
    except Exception as e:  # noqa: BLE001 — 任何 import 期失败都要转成可读错误
        raise ValueError(
            f"无法 import {CATALOG_MODULE}（{curator_scripts}）: {e}") from e
    return _catalog


class StrategyCatalog:
    """外部策略库的只读句柄。"""

    def __init__(self, strategy_root: Path, curator_scripts: str | None = None):
        self.strategy_root = Path(strategy_root).expanduser().resolve()
        self.curator_scripts = resolve_curator_scripts(self.strategy_root, curator_scripts)
        self._cat = _import_catalog(self.curator_scripts)

    def paths(self) -> list:
        """全库策略 md 路径（由策略库自身的枚举规则产出）。"""
        return self._cat.strategy_paths(self.strategy_root)

    def load_all(self) -> tuple:
        """加载全库条目。返回 (entries, errors)。

        entries: [{path, entry}...]；单个卡片解析失败只记入 errors，不中断整体加载。
        errors:  [{path, error}...]
        """
        entries, errors = [], []
        for path in self.paths():
            try:
                entry = self._cat.load_entry(path)
            except SystemExit as e:  # _catalog.fail() 的退出信号
                errors.append({"path": str(path), "error": f"SystemExit: {e}"})
                continue
            except Exception as e:  # noqa: BLE001
                errors.append({"path": str(path), "error": f"{type(e).__name__}: {e}"})
                continue
            entries.append({"path": path, "entry": entry})
        return entries, errors

    @property
    def classifications(self) -> set:
        return set(self._cat.CLASSIFICATIONS)

    @property
    def generalities(self) -> set:
        return set(self._cat.GENERALITIES)
