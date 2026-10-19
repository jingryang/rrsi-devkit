"""Structured input-domain comparison — requirement(golden) 域 ⊆ design.support_domain.

CLAUDE.md §1.12：纯结构信号，不认算子名；§2.10：机器可消费。
词汇表由 requirement.json ``domain`` 与 design_spec ``support_domain`` 共享：

    {
      "rank":   {"min": 1, "max": 8},
      "inputs": [{"name": "x", "dtypes": ["float16", "float32", ...]}],
      "attrs":  [{"name": "perm", "domain": {"kind": "permutation", "constraint": "any"}}]
    }

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

# kind -> {requirement constraint: set(design constraints that cover it)}
ATTR_DOMAIN_COVERAGE: dict[str, dict[str, set[str]]] = {
    "permutation": {
        "any": {"any"},                                        # 需求"任意排列"只能被"任意排列"覆盖
        "cyclic_rotation": {"any", "cyclic_rotation"},         # 需求"循环旋转"可被两者覆盖
    },
}


def _rank_gaps(req_domain: dict, design_domain: dict) -> list[str]:
    rr = req_domain.get("rank")
    if not isinstance(rr, dict) or not rr:
        return []  # 需求未声明/不可解析 → 跳过（不假阳性）
    dr = design_domain.get("rank")
    if dr is None:
        # 与 dtype/attr 同口径：需求声明了 rank 但 design.support_domain 缺声明 → 保守 flag
        return ["rank: design support_domain 未声明 rank"]
    if not isinstance(dr, dict):
        # design 写了 rank 但非 {min,max} dict（如 prose 字符串）→ 不构成可机器消费的覆盖
        # 证据，显式报「格式异常」保守 flag，避免裸 AttributeError 被外层吞成泛化 WARN
        # （§1.2 可诊断）。
        return [f"rank: design support_domain.rank 非 {{min,max}} dict（实际 {type(dr).__name__}），无法对质 — 保守按未覆盖 flag"]
    rmin, rmax = rr.get("min", 1), rr.get("max", 10**9)
    dmin, dmax = dr.get("min", 1), dr.get("max", 10**9)
    # min/max 值类型守卫（§1.2 可诊断）：rank 是 dict 但 min/max 是字符串（如
    # {"min":"1"}）时，`int < str` 会抛 TypeError 被外层吞成泛化 WARN——显式报「无法对质」。
    # 需求侧不可解析 → 跳过（同 rr 非 dict 口径，不假阳性）；设计侧不可解析 → 保守 flag。
    if not all(isinstance(v, (int, float)) for v in (rmin, rmax)):
        return []
    if not all(isinstance(v, (int, float)) for v in (dmin, dmax)):
        return [f"rank: design support_domain.rank.min/max 非数值（实际 {type(dmin).__name__}），无法对质 — 保守按未覆盖 flag"]
    if rmin < dmin or rmax > dmax:
        return [f"rank: requirement [{rmin}..{rmax}] ⊄ design [{dmin}..{dmax}]"]
    return []


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
    """从 requirement.json 提取结构化域。优先新 ``domain`` 字段，否则容错回退到既有字段。"""
    if isinstance(req.get("domain"), dict):
        return req["domain"]
    out: dict = {}
    # rank: 从 shape_constraints.symbolic_rules 解析 "1 <= x.dim() <= 8" 类（容错）
    rank = _parse_rank(req.get("shape_constraints") or {})
    if rank:
        out["rank"] = rank
    # dtypes: data_type_support.input_combinations 按输入位展平
    dtypes = _parse_dtypes(req)
    if dtypes:
        out["inputs"] = dtypes
    return out


def design_support_domain(ds: dict) -> dict:
    """从 design_spec 提取 support_domain（结构化；缺失返回 {} → 引擎跳过/调用方裁决）。"""
    sd = ds.get("support_domain")
    return sd if isinstance(sd, dict) else {}


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
    rank = sd.get("rank")
    if rank is not None and not (
            isinstance(rank, dict)
            and isinstance(rank.get("min"), int)
            and isinstance(rank.get("max"), int)):
        errors.append(f"support_domain.rank 应为 {{min:int, max:int}} dict，实际 {type(rank).__name__}")
    inputs = sd.get("inputs")
    if inputs is not None:
        if not isinstance(inputs, list):
            errors.append(f"support_domain.inputs 应为 list，实际 {type(inputs).__name__}")
        else:
            for i, it in enumerate(inputs):
                if not isinstance(it, dict) or not isinstance(it.get("name"), str):
                    errors.append(f"support_domain.inputs[{i}] 应为 {{name:str, dtypes:list}} dict")
                elif not isinstance(it.get("dtypes"), list):
                    errors.append(f"support_domain.inputs[{i}].dtypes 应为 list，"
                                  f"实际 {type(it.get('dtypes')).__name__}")
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


def _parse_rank(sc: dict) -> dict | None:
    """从 shape_constraints 解析 rank 界。优先动态维描述，其次 symbolic_rules。"""
    rules = [str(r) for r in (sc.get("symbolic_rules") or [])]
    rules += [str(r) for r in (sc.get("dynamic_dims") or [])]
    for rule in rules:
        m = _RANK_RE.search(rule)
        if m:
            lo = int(m.group(1))
            hi = int(m.group(2)) if m.group(2) else 10**9
            return {"min": lo, "max": hi}
    return None


_RANK_RE = __import__("re").compile(r"(\d+)\s*<=\s*[A-Za-z_]\w*\s*\.?\s*dim\s*\(\s*\)\s*<=\s*(\d+)")


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
