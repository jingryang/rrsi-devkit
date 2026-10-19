#!/usr/bin/env python3
"""策略卡共用库：格式常量、校验、路径解析与工具（仅标准库）。

被选择 skill 的 select_prepare.py / select_finalize.py 与 build_cards.py 共用。

卡片文件格式：
  {"strategies": [{"strategy_id": ..., "text": ..., "text_sha256": ...}, ...]}
  - 每行恰好三键，strategy_id 升序唯一
  - text 为六字段短卡：「动作：…\\n适用：…\\n…」空字段整行省略
  - text_sha256 = sha256(text 的 UTF-8 字节)
  - 序列化：json.dumps(ensure_ascii=False, indent=2) + 结尾换行

与上游卡片库的差异（本 skill 自有的格式契约）：
  - 字段集为六项。上游的「代价」在本策略库的卡元数据中**无来源**，故整字段移除而非
    留空占位——留一个永远填不上的字段只会诱导实现者凭空编造（CLAUDE.md §2.12）。
  - 字段预算按本策略库卡片的实际文本量重新标定（见 FIELD_BUDGETS 注释）。
  - 类别体系为本策略库原生的 `common` + `op-class/<class>`，非上游的算子族×芯片六类。

策略库为**外部数据目录**，本模块不含任何默认根路径：根目录一律由调用方显式传入
（由 CLI/环境变量解析，见 resolve_strategy_root）。策略 md 位于
`<root>/<md_dir>/common/<id>.md` 与 `<root>/<md_dir>/op-class/<class>/<id>.md` 两层。
"""

import hashlib
import json
import os
import re
from pathlib import Path

# ── 类别体系（本策略库原生：common + op-class/<class>） ──────────────────────
COMMON_CATEGORY = "common"
OP_CLASS_DIR = "op-class"
MD_ROOT_DEFAULT = "strategies"

# 类别名与 slug 同构（kebab-case），与上游 _catalog.SLUG 一致
CATEGORY_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
STRATEGY_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

# 六字段短卡：固定顺序、逐字段内容字符预算（不含「字段：」前缀）、整卡上限。
# 预算按本策略库卡片的实测文本量标定：mechanism p50≈261 / 适用条件合计 p50≈137 /
# 排除条件+约束+风险合计 p50≈259。粗筛的最高权重维度正是 动作/适用/限制，把长机制
# 裁成残句会直接诱导粗筛误判，故预算整体放宽而非截断（CLAUDE.md §2.12 宁缺毋滥）。
FIELD_LABELS = ("动作", "适用", "限制", "范围", "检索词", "机会")
FIELD_BUDGETS = {"动作": 160, "适用": 200, "限制": 240,
                 "范围": 80, "检索词": 90, "机会": 90}
REQUIRED_FIELDS = ("动作",)
TOTAL_LIMIT = 900

CARD_ROW_KEYS = ("strategy_id", "text", "text_sha256")
CARD_LINE_RE = re.compile(r"^(动作|适用|限制|范围|检索词|机会)：(.+)$")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


# ── 策略库根与路径解析 ──────────────────────────────────────────────────────

ENV_STRATEGY_ROOT = "ASCENDC_STRATEGY_ROOT"


def resolve_strategy_root(cli_value: str | None) -> Path | None:
    """解析外部策略库根：CLI 显式值 > 环境变量。两者皆无时返回 None。

    解析结果会做基础校验（存在、是目录、含 md 根），失败时抛出 ValueError 并写明
    确切路径与设置方法——调用方据此硬停，**不得**回退到内置副本或空卡片库。
    """
    raw = cli_value or os.environ.get(ENV_STRATEGY_ROOT)
    if not raw:
        return None
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(
            f"策略库根不是目录: {root}\n"
            f"请设置环境变量 {ENV_STRATEGY_ROOT} 指向 ascendc-strategy-opt 检出目录，"
            f"或用 --strategy-root 显式传入。")
    return root


def md_root(strategy_root: Path, md_dir: str = MD_ROOT_DEFAULT) -> Path:
    """策略 md 树根：<strategy_root>/<md_dir>。"""
    root = Path(strategy_root) / md_dir
    if not root.is_dir():
        raise ValueError(
            f"策略 md 根不存在: {root}\n"
            f"期望布局：<strategy_root>/{md_dir}/common/*.md 与 "
            f"<strategy_root>/{md_dir}/{OP_CLASS_DIR}/<class>/*.md")
    return root


def categories(strategy_root: Path, md_dir: str = MD_ROOT_DEFAULT) -> list:
    """本策略库的合法类别清单：["common", <class>...]（升序，仅含有卡目录）。

    由外部目录树派生，是类别合法性的唯一事实源——不在此内维护第二份类名表
    （CLAUDE.md §2.5 唯一通路）。目录树缺失/为空时抛出 ValueError。
    """
    root = md_root(strategy_root, md_dir)
    if not (root / COMMON_CATEGORY).is_dir():
        raise ValueError(f"策略库缺少 common 目录: {root / COMMON_CATEGORY}")
    classes = sorted(
        d.name for d in (root / OP_CLASS_DIR).iterdir()
        if d.is_dir() and any(d.glob("*.md"))
    ) if (root / OP_CLASS_DIR).is_dir() else []
    return [COMMON_CATEGORY, *classes]


def pool_categories(strategy_root: Path, md_dir: str = MD_ROOT_DEFAULT) -> list:
    """可作筛选池的类别清单（= categories()；保留此别名以表达调用点语义）。"""
    return categories(strategy_root, md_dir)


def pool_members(strategy_root: Path, category: str,
                 md_dir: str = MD_ROOT_DEFAULT) -> list:
    """某类别的筛选池成员 id：common 池即 common 自身；其余类为 common ∪ 该类。

    合并的原因是薄类（如 normalization 仅 3 张、layout-transform 4 张）单独成池会让
    Top10 粗筛失去意义；合并后 18–34 张。此语义与策略库自身的选择语义一致
    （选某 op-class 时同时返回 common）。
    """
    root = md_root(strategy_root, md_dir)
    valid = categories(strategy_root, md_dir)
    if category not in valid:
        raise ValueError(
            f"非法类别 {category!r}。可选类别（{len(valid)} 个）: {'、'.join(valid)}")
    ids = {p.stem for p in (root / COMMON_CATEGORY).glob("*.md") if p.is_file()}
    if category != COMMON_CATEGORY:
        ids |= {p.stem for p in (root / OP_CLASS_DIR / category).glob("*.md") if p.is_file()}
    return sorted(ids)


def source_md_path(strategy_root: Path, strategy_id: str,
                   md_dir: str = MD_ROOT_DEFAULT) -> Path:
    """按 strategy_id 跨两层解析源策略 md 的绝对路径。

    两层布局：<md_root>/common/<id>.md 与 <md_root>/op-class/<class>/<id>.md。
    两层都扫描并合并候选，因为池合并后「tier 是 category 的函数」这一前提不成立。

    命中恰好 1 个才返回；0 个或 ≥2 个都抛 ValueError——≥2 的分支必须保留：本函数
    依赖「slug 全局唯一」这一**外部**不变式（由策略库侧 validate_catalog.py 保证），
    一旦该不变式被放宽，必须响亮报错而不是静默选一个。
    """
    root = md_root(strategy_root, md_dir)
    candidates = []
    direct = root / COMMON_CATEGORY / f"{strategy_id}.md"
    if direct.is_file():
        candidates.append(direct)
    if (root / OP_CLASS_DIR).is_dir():
        candidates.extend(sorted((root / OP_CLASS_DIR).glob(f"*/{strategy_id}.md")))
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError(
            f"策略 md 不存在: {strategy_id}\n"
            f"已探测：{direct} 与 {root / OP_CLASS_DIR}/*/{strategy_id}.md")
    raise ValueError(
        f"策略 md 命中 {len(candidates)} 处（slug 应全局唯一）: {strategy_id}\n"
        + "\n".join(f"  {p}" for p in candidates))


def catalog_digest(strategy_root: Path, ids=None,
                   md_dir: str = MD_ROOT_DEFAULT) -> str:
    """池内 md 的目录摘要：sha256(排序后的 "<相对路径>:<文件sha256>" 行拼接)。

    用于在运行目录内记录本轮所见策略正文的版本，供 finalize 复核 md 是否在运行中途
    被改写（Phase 3 直读外部 md，卡侧 sha 冻结保护不到正文）。ids 为 None 时取全库。
    """
    root = md_root(strategy_root, md_dir)
    if ids is None:
        targets = sorted(root.rglob("*.md"))
    else:
        targets = sorted(source_md_path(strategy_root, i, md_dir) for i in ids)
    lines = [f"{p.relative_to(root)}:{sha256_file(p)}" for p in targets]
    return sha256_text("\n".join(lines))


# ── 卡片格式校验 ────────────────────────────────────────────────────────────

def parse_card_text(text) -> tuple:
    """校验六字段短卡正文。返回 (fields: {label: content}, errors: [str])。"""
    errors = []
    if not isinstance(text, str) or not text:
        return {}, ["text 为空"]
    if text != text.strip():
        errors.append("text 首尾含空白")
    if "\r" in text:
        errors.append("text 含回车符 \\r")
    fields = {}
    prev_idx = -1
    for i, line in enumerate(text.split("\n"), 1):
        m = CARD_LINE_RE.match(line)
        if not m:
            errors.append(f"第{i}行格式非法（须为「字段：内容」，字段∈{FIELD_LABELS}，空字段省略）: {line[:40]!r}")
            continue
        label, content = m.group(1), m.group(2)
        idx = FIELD_LABELS.index(label)
        if idx <= prev_idx:
            errors.append(f"字段 {label} 顺序非法（按 {'、'.join(FIELD_LABELS)} 递增，空字段整行省略）")
        prev_idx = idx
        budget = FIELD_BUDGETS[label]
        if len(content) > budget:
            errors.append(f"字段 {label} 超预算: {len(content)}>{budget}")
        fields[label] = content
    for label in REQUIRED_FIELDS:
        if label not in fields:
            errors.append(f"缺少必填字段 {label}")
    if len(text) > TOTAL_LIMIT:
        errors.append(f"整卡超上限: {len(text)}>{TOTAL_LIMIT}")
    return fields, errors


def validate_card_rows(rows, source: str = "cards") -> list:
    """校验已加载的卡片行列表，返回 errors。

    行键**恰好**为 CARD_ROW_KEYS：这是与 select_finalize 的门禁共同依赖的契约，
    新增键会同时破坏两侧校验。需要每卡的额外溯源信息时，放到运行目录的兄弟文件里
    （见 run_inputs.json 的 catalog_digest），**不要**扩行合约。
    """
    errors = []
    ids = set()
    for i, row in enumerate(rows):
        where = f"{source}[{i}]"
        if not isinstance(row, dict) or set(row) != set(CARD_ROW_KEYS):
            errors.append(f"{where}: 键须恰好为 {list(CARD_ROW_KEYS)}")
            continue
        sid, text, sha = row["strategy_id"], row["text"], row["text_sha256"]
        if not isinstance(sid, str) or not STRATEGY_ID_RE.match(sid):
            errors.append(f"{where}: strategy_id 非法: {sid!r}")
            continue
        if sid in ids:
            errors.append(f"{where}: strategy_id 重复: {sid}")
        ids.add(sid)
        _, text_errors = parse_card_text(text)
        for e in text_errors:
            errors.append(f"{where} {sid}: {e}")
        if sha256_text(text) != sha:
            errors.append(f"{where} {sid}: text_sha256 与 text 不符")
    return errors


def load_cards_file(path: Path) -> tuple:
    """读取并校验卡片文件。返回 (rows, errors)；文件不存在时 (None, [信息])。"""
    path = Path(path)
    if not path.is_file():
        return None, [f"卡片文件不存在: {path}"]
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return None, [f"JSON 解析失败 {path}: {e}"]
    if not isinstance(obj, dict) or set(obj) != {"strategies"}:
        return None, [f"{path}: 顶层须仅含 strategies 键"]
    rows = obj["strategies"]
    if not isinstance(rows, list):
        return None, [f"{path}: strategies 须为数组"]
    return rows, validate_card_rows(rows, source=str(path.name))


def render_cards_doc(rows: list) -> str:
    return json.dumps({"strategies": rows}, ensure_ascii=False, indent=2) + "\n"


def write_text_atomic(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
