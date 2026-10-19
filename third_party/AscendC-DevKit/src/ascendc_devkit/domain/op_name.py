"""L2 Domain — 算子注册名 ↔ 落盘目录名(snake)的 case 派生 + CANN runtime 反推兼容。

背景(P 361001 / 注册名派生源问题):codegen 产物里有两类名——**注册名**(OpDef
``OP_ADD`` / aclnn ``ADD_TO_LAUNCHER_LIST_AICORE`` 首参的 Pascal)与**落盘目录名**
(config json 文件名基底,= ``op_name`` 的 snake,由 golden 入口派生)。CANN runtime 在
kernel launch 时按注册名做 camel→snake **反推**得到若干候选,再去 ``kernel/config/<soc>/``
下找以落盘目录名命名的 config json。注册名若从 proto/requirement 的 Pascal 直抄(数字段
大写,如 ``AdaptiveAvgPool3D``),反推候选与落盘名对不上 → runtime 永不选中 custom
binary → 静默落回内置同名 op(361001)。

本模块是这三条命名事实的**单一来源**(§1.5/§1.15/§2.5):

  - ``snake_to_pascal()`` — 落盘名(snake) → 注册名(Pascal)的**正向派生**规则。
    每 ``_`` 段 capitalize 后拼接:``adaptive_avg_pool_3d`` → ``AdaptiveAvgPool3d``
    (数字段 ``3d`` 的 capitalize 保持小写 d)。
  - ``runtime_camelsnake()`` / ``runtime_snake_lenient()`` — CANN runtime 对注册
    Pascal 名做 camel→snake 反推的**两个候选族**(从实测日志/``AdaptiveAvgPool3D``
    命名推导,见 ``docs/plan/adaptive-opname-snake-mismatch/``)。runtime 依序尝试
    两者,任一命中 config 即选中。
  - ``runtime_config_candidates()`` / ``registration_matches_disk()`` — 判断某个
    注册 Pascal 是否会让 runtime 反推命中某落盘 snake。

判据设计:``registration_matches_disk(reg_pascal, disk_snake)`` 用**成员包含**而非
**相等**——runtime 对含数字段的注册名产生两个不同候选(如 ``AdaptiveAvgPool3d`` →
``adaptive_avg_pool_3d`` 与 ``adaptive_avg_pool3d``),而落盘名可能是任一边界形态
(``adaptive_avg_pool_3d`` 或 ``adaptive_avg_pool3d`` 都是 runtime 认识的);用相等判定
会把边界形态恰好不同的**合法**注册名误拦。成员包含精确复刻 runtime 的候选搜索空间。

与 eval matcher 的关系:cann-bench scorer 的 ``snake_case_candidates`` 是评测侧独立
实现(更高容忍度),不在本模块范围;``CannbenchScorer.snake_to_pascal`` 委托本模块
``snake_to_pascal``(单点实现)。
"""

from __future__ import annotations

import re

# —— 正向派生:落盘 snake → 注册 Pascal ——


def snake_to_pascal(name: str) -> str:
    """snake_case → PascalCase,每 ``_`` 段 capitalize 后拼接。

    ``add`` → ``Add``;``swi_glu`` → ``SwiGlu``;``adaptive_avg_pool_3d`` →
    ``AdaptiveAvgPool3d``(数字段 ``3d`` 的 capitalize 仍为 ``3d``,小写 d)。
    """
    return "".join(part.capitalize() for part in name.split("_"))


# —— runtime 反推:camel→snake 的两个候选族(与 CANN runtime 一致) ——


def runtime_camelsnake(name: str) -> str:
    """CANN runtime 对注册名的**激进** camel→snake 反推候选。

    规则 = 四类边界全切后整体小写:字母+数字、数字+大写、大写+小写、小写+大写。
    ``AdaptiveAvgPool3D`` → ``adaptive_avg_pool_3_d``。实测日志第一个候选
    (``adaptive_avg_pool_3_d.json``)。
    """
    s = re.sub(r"([a-zA-Z])([0-9])", r"\1_\2", name)
    s = re.sub(r"([0-9])([A-Z])", r"\1_\2", s)
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", s)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s).lower()


def runtime_snake_lenient(name: str) -> str:
    """CANN runtime 对注册名的**宽松** camel→snake 反推候选。

    规则 = 只切小写→大写边界后整体小写(数字段不切)。
    ``AdaptiveAvgPool3D`` → ``adaptive_avg_pool3d``。实测日志第二个候选
    (``adaptive_avg_pool3d.json``)。
    """
    return re.sub(r"([a-z])([A-Z])", r"\1_\2", name).lower()


def runtime_config_candidates(reg_pascal: str) -> frozenset[str]:
    """CANN runtime 按注册名反推的全部 config 候选名(去重)。

    与 ``ASCEND_GLOBAL_LOG_LEVEL=1`` 实测的 runtime 依序尝试列表一致:先激进再宽松。
    """
    return frozenset({runtime_camelsnake(reg_pascal), runtime_snake_lenient(reg_pascal)})


def registration_matches_disk(reg_pascal: str, disk_snake: str) -> bool:
    """判断注册 Pascal 是否会让 runtime 反推命中落盘 snake(config 文件名基底)。

    用成员包含:落盘名 ∈ runtime 候选集即视为命中。精确复刻 runtime 搜索空间,
    避免用相等误拦边界形态不同的合法注册名(见模块 docstring)。
    """
    return disk_snake in runtime_config_candidates(reg_pascal)
