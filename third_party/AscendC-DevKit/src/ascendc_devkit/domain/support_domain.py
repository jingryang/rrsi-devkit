"""Structured input-domain comparison — requirement(golden) 域 ⊆ design.support_domain.

CLAUDE.md §1.12：纯结构信号，不认算子名；§2.10：机器可消费。
词汇表由 requirement.json ``domain`` 与 design_spec ``support_domain`` 共享：

    {
      "inputs": [{"name": "x", "dtypes": ["float16", "float32", ...],
                  "rank": {"min": 2, "max": 8}}],
      "attrs":  [{"name": "perm", "domain": {"kind": "permutation", "constraint": "any"}}]
    }

``rank`` 是**张量属性**，写在 ``inputs[]`` 条目内（同一算子的主输入可以是 2~8 维、
逐维缩放参数 1~7 维、偏置 1 维）。**不存在算子级 rank**——它无法表达张量间差异，
按它比对会把合法的低秩参数判成缺口（见 ``_rank_gaps`` / ``tensor_rank_domain``）。

attr domain kind 经 ``ATTR_DOMAIN_COVERAGE`` 可扩展：kind 下维护
{需求 constraint: set(能覆盖它的设计 constraint)}。新声称类型 → 加一条目，
无需改引擎（§1.2 可扩展）。

方向：``domain_covers(req_domain, design_domain)`` 返回缺口列表；空 = 设计支持域 ⊇ 需求域。
需求侧未声明的轴跳过（不假阳性）；需求侧声明了、设计 support_domain 缺声明 → 保守
flag（design 未声明不构成覆盖证据，rank/dtype/attr 三轴同口径）。引擎是安全网，
不是完备性证明——未声明轴仍由设计自检（support_domain/known_limitations）+ debug/eval 兜底。

schema 健壮性（§1.2 可诊断 + no-halt）：三轴检查对字段形态做 isinstance 守卫——
设计侧字段为不可机器解析形态（如 prose 字符串 rank，skill 曾教设计 LLM 这么写）→
降级为「无法对质」保守 flag（不抛异常、不静默吞掉，缺口可读）；需求侧字段异常 → 跳过。
任何未预见异常仍由 codegen 外层 try/except 兜底（WARN + 继续，绝不 halt）。
"""

from __future__ import annotations

import logging
import re

_log = logging.getLogger(__name__)

# kind -> {requirement constraint: set(design constraints that cover it)}
ATTR_DOMAIN_COVERAGE: dict[str, dict[str, set[str]]] = {
    "permutation": {
        "any": {"any"},                                        # 需求"任意排列"只能被"任意排列"覆盖
        "cyclic_rotation": {"any", "cyclic_rotation"},         # 需求"循环旋转"可被两者覆盖
    },
}


def _rank_gaps(req_domain: dict, design_domain: dict) -> list[str]:
    """逐张量比对 rank 域：需求声称的每张量 rank ⊆ 设计 support_domain 的同张量 rank。

    rank 是**张量属性**，不是算子属性（同一算子的主输入可以是 2~8 维，逐维缩放
    参数是 1~7 维，偏置是 1 维）。算子级 rank 无法表达这种差异，用它比对会把
    合法的低秩参数判成缺口——故判据只看 ``inputs[].rank``。

    未声明的轴跳过（与 dtype/attr 同口径，不假阳性）：需求侧没写 → 不比；设计侧
    没写但需求写了 → 保守 flag（设计未声明不构成覆盖证据）。
    """
    req_inputs = _input_rank_map(req_domain)
    design_inputs = _input_rank_map(design_domain)
    gaps: list[str] = []
    for name, raw in req_inputs.items():
        if "rank" not in raw:
            continue                      # 需求未声明 → 跳过（不假阳性）
        rr = _as_rank(raw["rank"])
        if rr is None:
            continue                      # 需求侧不可解析 → 跳过
        dr_raw = design_inputs.get(name)
        if dr_raw is None:
            gaps.append(f"rank[{name}]: design support_domain 未声明该输入")
            continue
        if "rank" not in dr_raw:
            gaps.append(f"rank[{name}]: design support_domain 未声明 rank")
            continue
        dr = _as_rank(dr_raw["rank"])
        if dr is None:
            gaps.append(f"rank[{name}]: design rank 非 {{min:int, max:int}} 形态"
                        f"（实际 {type(dr_raw['rank']).__name__}），无法对质 — 保守按未覆盖 flag")
            continue
        rmin, rmax = rr.get("min", 1), rr.get("max", 10**9)
        dmin, dmax = dr.get("min", 1), dr.get("max", 10**9)
        if not all(isinstance(v, (int, float)) for v in (dmin, dmax)):
            gaps.append(f"rank[{name}]: design rank.min/max 非数值"
                        f"（实际 {type(dmin).__name__}），无法对质 — 保守按未覆盖 flag")
            continue
        if rmin < dmin or rmax > dmax:
            gaps.append(f"rank[{name}]: requirement [{rmin}..{rmax}] ⊄ design [{dmin}..{dmax}]")
    return gaps


def _input_rank_map(dom: dict) -> dict:
    """``{name: 该输入的条目 dict}``——原样返回，由调用点判读 rank 形态与缺失。"""
    out: dict = {}
    for item in dom.get("inputs") or []:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            out[item["name"]] = item
    return out


def _inputs_map(dom: dict) -> dict:
    """容错提取 {name: dtypes-set}：容忍非 dict 条目 / dtypes 非 list / 缺 name。

    结构化正常路径与旧实现逐字段等价；异常条目跳过不抛异常（安全网绝不因 schema
    形态崩，§1.2/§1.13）。"""
    out: dict[str, set] = {}
    for item in dom.get("inputs") or []:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            dts = item.get("dtypes")
            out[item["name"]] = set(dts) if isinstance(dts, list) else set()
    return out


def _dtype_gaps(req_domain: dict, design_domain: dict) -> list[str]:
    req_inputs = _inputs_map(req_domain)
    design_inputs = _inputs_map(design_domain)
    gaps = []
    for name, rdt in req_inputs.items():
        if not rdt:
            continue
        ddt = design_inputs.get(name)
        if ddt is None:
            gaps.append(f"input[{name}]: design support_domain 未声明 dtypes")
        elif not rdt <= ddt:
            gaps.append(f"input[{name}] dtypes: 需求含 {sorted(rdt - ddt)} ⊄ 设计 {sorted(ddt)}")
    return gaps


def _attr_gaps(req_domain: dict, design_domain: dict) -> list[str]:
    req_attrs: dict = {}
    for a in req_domain.get("attrs") or []:
        if isinstance(a, dict) and isinstance(a.get("name"), str):
            req_attrs[a["name"]] = a
    design_attrs: dict = {}
    for a in design_domain.get("attrs") or []:
        if isinstance(a, dict) and isinstance(a.get("name"), str):
            design_attrs[a["name"]] = a
    gaps = []
    for name, ra in req_attrs.items():
        rdom = ra.get("domain")
        if not isinstance(rdom, dict):
            continue  # 需求侧未结构化声明该 attr 域 → 跳过，不假阳性
        rk, rc = rdom.get("kind"), rdom.get("constraint")
        if not rk:
            continue
        da = design_attrs.get(name)
        ddom = da.get("domain") if isinstance(da, dict) else None
        if not isinstance(ddom, dict):
            ddom = {}  # 设计未声明/不可解析 → 走「未声明」保守 flag（同口径）
        dk, dc = ddom.get("kind"), ddom.get("constraint")
        if not dk:
            gaps.append(f"attr[{name}]: design 未声明 {rk} 约束")
            continue
        if rk != dk:
            gaps.append(f"attr[{name}] domain kind: 需求 {rk} ≠ 设计 {dk}")
            continue
        cover = ATTR_DOMAIN_COVERAGE.get(rk, {})
        if rc and cover and dc not in cover.get(rc, set()):
            gaps.append(f"attr[{name}] domain: 需求 {rk}:{rc} ⊄ 设计 {dk}:{dc}")
    return gaps


def domain_covers(req_domain: dict, design_domain: dict) -> list[str]:
    """设计 support_domain 是否覆盖需求(golden) 域。返回缺口描述列表，空 = 覆盖。"""
    gaps: list[str] = []
    for fn in (_rank_gaps, _dtype_gaps, _attr_gaps):
        gaps.extend(fn(req_domain, design_domain))
    return gaps


# --------------------------------------------------------------------------
# 提取器：从 requirement.json / design_spec 提取结构化域（容错回退）
# --------------------------------------------------------------------------

def requirement_domain(req: dict) -> dict:
    """从 requirement.json 提取结构化域。优先新 ``domain`` 字段，否则容错回退到既有字段。

    两条路径都遵守「rank 属于张量」：算子级 ``rank`` 一律不参与对质（它无法归属到
    某个张量），存在时留一条可观测告警而不是静默丢弃（§1.2 可诊断）。
    """
    if isinstance(req.get("domain"), dict):
        domain = req["domain"]
        if "rank" in domain:
            _log.warning(
                "requirement.domain.rank 已被忽略：rank 是逐张量属性，"
                "请改写到 inputs[].rank = {min:int, max:int}（原值 %r）",
                domain.get("rank"))
        return domain
    out: dict = {}
    by_name: dict[str, dict] = {}
    # dtypes: data_type_support.input_combinations 按输入位展平
    for e in (_parse_dtypes(req) or []):
        by_name[e["name"]] = dict(e)
    # rank: 从 shape_constraints.symbolic_rules 解析 "1 <= x.dim() <= 8" 类（容错）
    for name, rk in _parse_ranks(req.get("shape_constraints") or {}).items():
        by_name.setdefault(name, {"name": name, "dtypes": []})["rank"] = rk
    if by_name:
        out["inputs"] = list(by_name.values())
    return out


def design_support_domain(ds: dict) -> dict:
    """从 design_spec 提取 support_domain（结构化；缺失返回 {} → 引擎跳过/调用方裁决）。"""
    sd = ds.get("support_domain")
    return sd if isinstance(sd, dict) else {}


# --------------------------------------------------------------------------
# per-tensor rank 域：单一权威点（§1.15）
# --------------------------------------------------------------------------
#
# 03_参数定义.yaml 的 ``dimensions`` 语义是「该张量允许的 rank 集合」
# （ascendc-st-design/SKILL.md：文档写"3 维"取 [3]，写"不超过 8 维"取 [1..8]）。
# 它必须由**该张量自己的**结构信号派生，不能用 op 级 ``domain.rank``
# （requirement.json 的 domain.notes：那是主输入的域）套所有张量——
# 后者会把合法的 1 维参数（缩放/偏置）判死，并诱导修复者写错值过门。
#
# 符号 shape 的**占位符个数不是 rank**：``["N_0", "...", "N_{m-1}"]`` 的长度
# 与真实 rank 无对应关系（省略号代表任意个维度）。

# 形状中代表「任意个维度」的通配符：不构成具体 rank 证据
_WILDCARD_TOKENS = frozenset({"...", "…", "*"})

# "rank(x) = m + k ∈ [2, 8]" / "rank(x) ∈ [2, 8]"（∈ 之前的表述任意，不跨行）
_RANK_RANGE_RE = re.compile(
    r"rank\(\s*([A-Za-z_]\w*)\s*\)[^∈\n]{0,24}∈\s*\[\s*(\d+)\s*,\s*(\d+)\s*\]")
# 固定 rank 表述：「1 维，numel == C」（张量名可不出现在句中）
_FIXED_RANK_LEAD_RE = re.compile(r"^\s*(\d+)\s*维")
# 「gamma 为 1 维」这类带名固定 rank 表述
_FIXED_RANK_NAME_RE = re.compile(r"([A-Za-z_]\w*)[^\n,，;；]{0,12}?(\d+)\s*维")


def _op_block(requirement: dict) -> dict:
    """requirement.json 的算子块：平铺 / ``op`` / ``operator`` 嵌套三种形态。"""
    for key in ("op", "operator"):
        blk = requirement.get(key)
        if isinstance(blk, dict):
            return blk
    return requirement


def merged_input_entries(requirement: dict,
                         design_spec: dict | None = None) -> dict[str, dict]:
    """``{name: 合并后的 input 条目}``：design_spec 非空值覆盖 requirement。

    与 convert_to_param_def 的合并口径一致（唯一通路，§1.15）；空值
    （``""`` / ``[]`` / ``None``）不覆盖上游声明。
    """
    ds_inputs: dict[str, dict] = {}
    for e in ((design_spec or {}).get("inputs") or []):
        if isinstance(e, dict) and isinstance(e.get("name"), str):
            ds_inputs[e["name"]] = e
    out: dict[str, dict] = {}
    for e in (_op_block(requirement).get("inputs") or []):
        if isinstance(e, dict) and isinstance(e.get("name"), str):
            ds_e = ds_inputs.get(e["name"]) or {}
            out[e["name"]] = {**e, **{k: v for k, v in ds_e.items() if v}}
    return out


def _as_rank(rk) -> dict | None:
    """``{min,max}`` 形态校验：两个值都是 int 才成立。"""
    if isinstance(rk, dict):
        lo, hi = rk.get("min"), rk.get("max")
        if isinstance(lo, int) and isinstance(hi, int):
            return {"min": lo, "max": hi}
    return None


def _structured_rank(requirement: dict, name: str, entry: dict | None) -> dict | None:
    """结构化 rank 声明，最高优先。两处可写，语义相同（该张量自己的域）：

      * 张量条目内 —— ``inputs[].rank``（requirement 顶层 / design_spec 均可）
      * 支持域内 —— ``domain.inputs[].rank``

    张量条目内优先：它描述的是这个张量本身；``domain.inputs[]`` 描述支持域。
    """
    rk = _as_rank((entry or {}).get("rank"))
    if rk:
        return rk
    for ent in ((requirement.get("domain") or {}).get("inputs") or []):
        if isinstance(ent, dict) and ent.get("name") == name:
            rk = _as_rank(ent.get("rank"))
            if rk:
                return rk
    return None


def _rank_from_variants(entry: dict) -> dict | None:
    """``shape_variants``（结构化备选 shape 列表）→ 由各变体的维数得出 rank 集合。"""
    variants = entry.get("shape_variants")
    if not isinstance(variants, list):
        return None
    ranks = sorted({len(v) for v in variants if isinstance(v, list) and v})
    if not ranks:
        return None
    return {"min": ranks[0], "max": ranks[-1]}


def _rank_from_constraints(name: str, sc) -> dict | None:
    """逐张量 ``shape_constraints`` 措辞（过渡兜底；已知措辞形态才解析）。"""
    if not isinstance(sc, str) or not sc.strip():
        return None
    for var, lo, hi in _RANK_RANGE_RE.findall(sc):
        if var == name:
            return {"min": int(lo), "max": int(hi)}
    m = _FIXED_RANK_LEAD_RE.match(sc)
    if m:
        r = int(m.group(1))
        return {"min": r, "max": r}
    for var, r in _FIXED_RANK_NAME_RE.findall(sc):
        if var == name:
            r = int(r)
            return {"min": r, "max": r}
    return None


def _shape_is_concrete(shape) -> bool:
    """非空且不含通配符（省略号 / 星号）的 shape → 其长度即精确 rank。"""
    return (isinstance(shape, list) and bool(shape)
            and not any(isinstance(t, str) and t.strip() in _WILDCARD_TOKENS
                        for t in shape))


def tensor_rank_domain(requirement: dict, name: str, *,
                       design_spec: dict | None = None,
                       entry: dict | None = None,
                       _seen: frozenset[str] = frozenset()) -> dict | None:
    """单张量的合法 rank 域 ``{min,max}``；无足够证据返回 ``None``。

    优先级（先结构化后措辞，§2.10；没有证据就不臆造，§2.12）：
      ① 该张量条目内的 ``rank``（``inputs[].rank``，亦认 ``domain.inputs[].rank``）
      ② ``shape_variants`` 结构化备选 shape
      ③ 逐张量 ``shape_constraints`` 措辞（``rank(x) ∈ [2,8]`` / 「1 维」）
      ④ 具体 shape（无通配符）→ 精确 rank
      ⑤ 与其它输入符号 shape 完全相同 → 继承（结构信号，不解析措辞）

    ``entry`` 可传入已合并（design_spec 覆盖后）的条目；缺省从 requirement 查。
    """
    if not name or name in _seen:
        return None
    entries = merged_input_entries(requirement, design_spec)
    ent = entry if isinstance(entry, dict) else entries.get(name, {})
    if not isinstance(ent, dict):
        ent = {}

    rk = _structured_rank(requirement, name, ent)
    if rk:
        return rk
    rk = _rank_from_variants(ent)
    if rk:
        return rk
    rk = _rank_from_constraints(name, ent.get("shape_constraints"))
    if rk:
        return rk
    shape = ent.get("shape")
    if _shape_is_concrete(shape):
        return {"min": len(shape), "max": len(shape)}

    # ⑤ 结构别名：同形张量共享 rank 域（如「残差项 shape 必须与主输入完全一致」）
    if isinstance(shape, list) and shape:
        seen = _seen | {name}
        for other, other_ent in entries.items():
            if other == name or other in seen:
                continue
            if other_ent.get("shape") == shape:
                rk = tensor_rank_domain(requirement, other, design_spec=design_spec,
                                        entry=other_ent, _seen=seen)
                if rk:
                    return rk
    return None


def validate_support_domain_structure(sd) -> list[str]:
    """设计 support_domain 结构校验（§1.3 加载期校验优于运行期暴露；设计 validate 阶段调用）。

    返回结构错误列表（空 = 合规）。与 ``schema/support_domain.json`` 契约一致：
    ``rank={min,max}`` / ``inputs=[{name,dtypes}]`` / ``attrs=[{name,domain{kind,constraint}}]``。
    只查**结构形态**（dict/list/字段类型），不查覆盖语义（那是 ``domain_covers`` 的活）。
    校验器是加载期门，引擎 ``_rank_gaps`` 等的 isinstance 守卫是运行期 last-resort 兜底——
    两者同源一致（§2.5 单一通路：schema 契约 → 校验器 → 引擎守卫，无第二套词汇表）。
    """
    if not isinstance(sd, dict):
        return [f"support_domain 应为 dict，实际 {type(sd).__name__}"]
    errors: list[str] = []
    # rank 是张量属性，写在 inputs[] 条目内。算子级 rank 无法表达张量间差异，
    # 下游会误当成「所有张量的域」——结构校验直接拒绝（§1.3 加载期暴露）。
    if "rank" in sd:
        errors.append(
            "support_domain 不应有算子级 rank：rank 是逐张量属性，"
            "请写到 inputs[].rank = {min:int, max:int}（不同张量可不同）")
    inputs = sd.get("inputs")
    if inputs is not None:
        if not isinstance(inputs, list):
            errors.append(f"support_domain.inputs 应为 list，实际 {type(inputs).__name__}")
        else:
            for i, it in enumerate(inputs):
                if not isinstance(it, dict) or not isinstance(it.get("name"), str):
                    errors.append(f"support_domain.inputs[{i}] 应为 "
                                  f"{{name:str, dtypes:list, rank?:{{min,max}}}} dict")
                    continue
                if not isinstance(it.get("dtypes"), list):
                    errors.append(f"support_domain.inputs[{i}].dtypes 应为 list，"
                                  f"实际 {type(it.get('dtypes')).__name__}")
                if "rank" in it and _as_rank(it.get("rank")) is None:
                    errors.append(
                        f"support_domain.inputs[{i}].rank 应为 {{min:int, max:int}} dict，"
                        f"实际 {type(it.get('rank')).__name__}")
    attrs = sd.get("attrs")
    if attrs is not None:
        if not isinstance(attrs, list):
            errors.append(f"support_domain.attrs 应为 list，实际 {type(attrs).__name__}")
        else:
            for i, at in enumerate(attrs):
                if not isinstance(at, dict) or not isinstance(at.get("name"), str):
                    errors.append(f"support_domain.attrs[{i}] 应为 {{name:str, domain:{{kind,constraint}}}} dict")
                else:
                    dom = at.get("domain")
                    if not (isinstance(dom, dict) and isinstance(dom.get("kind"), str)):
                        errors.append(f"support_domain.attrs[{i}].domain 应为 {{kind:str, constraint:str}} dict，"
                                      f"实际 {type(dom).__name__}")
    return errors


def _parse_ranks(sc: dict) -> dict[str, dict]:
    """从 shape_constraints 解析 ``{张量名: {min,max}}``。优先动态维描述，其次 symbolic_rules。

    规则形态形如 ``"1 <= x.dim() <= 8"``；解析出的区间只归给该规则点名的张量，
    因为 rank 是张量属性（不存在算子级 rank）。
    """
    rules = [str(r) for r in (sc.get("symbolic_rules") or [])]
    rules += [str(r) for r in (sc.get("dynamic_dims") or [])]
    out: dict[str, dict] = {}
    for rule in rules:
        for lo, name, hi in _RANK_RE.findall(rule):
            out.setdefault(name, {"min": int(lo),
                                  "max": int(hi) if hi else 10**9})
    return out


_RANK_RE = __import__("re").compile(
    r"(\d+)\s*<=\s*([A-Za-z_]\w*)\s*\.?\s*dim\s*\(\s*\)\s*<=\s*(\d+)")


def _parse_dtypes(req: dict) -> list[dict] | None:
    dts = req.get("data_type_support") or {}
    combos = dts.get("input_combinations") or []
    if not combos or not all(isinstance(c, list) and c for c in combos):
        return None
    width = len(combos[0])
    if not all(len(c) == width for c in combos):
        return None
    names = [i.get("name") for i in (req.get("inputs") or [])]
    if len(names) != width:
        names = [f"input_{k}" for k in range(width)]
    return [
        {"name": names[k], "dtypes": sorted({c[k] for c in combos})}
        for k in range(width)
    ]
