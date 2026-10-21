#!/usr/bin/python3
# coding=utf-8

# ----------------------------------------------------------------------------
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# ----------------------------------------------------------------------------

"""前置输入五文件的可执行校验清单（G1~G16）。

下游 ops-direct-invoke 没有任何 cases.yaml / desc.md 的强 schema 校验器
（全仓唯一的程序化读取是 run_eval.py 读 proto.yaml 的 operator.category），
畸形产物不会被拒绝、只会静默拉低成功率。因此校验责任必须由生成侧承担。

用法：
    validate_preinput.py <op_dir>...              # G1~G11、G14~G16 静态门（G14/G15 仅多输入生效）
    validate_preinput.py --run-golden <op_dir>... # 追加 G12/G13：实跑 golden.py 20 例
"""

import argparse
import importlib.util
import inspect
import math
import re
import sys

from preinput_lib import (CASE_KEYS, CATEGORIES, CSV_HEADER, DESC_H3_REQUIRED,
                          DESC_H3_REQUIRED_L4, DESC_SECTIONS, DESC_SECTIONS_L4,
                          DIFFICULTIES, DTYPE_LIMITS, FILES,
                          FLOAT_DTYPES, INT_DTYPES, N_CASES,
                          PROTO_REQUIRED, SUPPORT_TABLE_HEADER, attr_values,
                          desc_h2, desc_h3, desc_prototype, load_cases,
                          all_dim_sizes, coupling_invariants, derivable_bounds,
                          desc_constraint_lines, desc_section,
                          find_string_specials, index_input_positions,
                          int_attr_values, load_desc, load_proto,
                          measured_ranges, note_core, per_input_ranges,
                          parse_ndim_claim, parse_range_cell,
                          parse_support_table, row_input_pos, shapes_of, snake,
                          squash, WRONG_PREFIX)

import os


class Report:
    def __init__(self, op_dir):
        self.op = op_dir
        self.rows = []   # (gate, level, msg)

    def ok(self, gate, msg=""):
        self.rows.append((gate, "PASS", msg))

    def fail(self, gate, msg):
        self.rows.append((gate, "FAIL", msg))

    def warn(self, gate, msg):
        self.rows.append((gate, "WARN", msg))

    @property
    def n_fail(self):
        return sum(1 for _, l, _ in self.rows if l == "FAIL")

    @property
    def n_warn(self):
        return sum(1 for _, l, _ in self.rows if l == "WARN")

    def render(self, verbose=False):
        out = []
        head = f"{'FAIL' if self.n_fail else 'PASS'}  {self.op}"
        out.append(f"{head}   ({self.n_fail} fail, {self.n_warn} warn)")
        for gate, level, msg in self.rows:
            if level == "PASS" and not verbose:
                continue
            out.append(f"    [{level}] {gate}: {msg}")
        return "\n".join(out)


# ══════════════════════════ G1 文件齐备 ══════════════════════════

def g1_files(r):
    missing = [f for f in FILES if not os.path.isfile(os.path.join(r.op, f))]
    if missing:
        r.fail("G1-files", f"缺文件 {missing}（spec 文件名必须是 desc.md，不是 spec.md）")
    else:
        r.ok("G1-files", "5 文件齐备")
    stray = [f for f in os.listdir(r.op)
             if os.path.isfile(os.path.join(r.op, f)) and f not in FILES]
    if stray:
        r.warn("G1-files", f"额外文件 {stray}（五文件之外不应有其它文件）")
    return not missing


# ══════════════════════ G2/G3 cases.yaml 结构 ══════════════════════

def g2_cases_schema(r, cases):
    if len(cases) != N_CASES:
        r.fail("G2-count", f"cases 数 ={len(cases)}，硬约束必须 =20")
    else:
        r.ok("G2-count", "20 例")

    bad_keys = []
    for c in cases:
        if set(c.keys()) != CASE_KEYS:
            bad_keys.append((c.get("case_id"), sorted(set(c.keys()) ^ CASE_KEYS)))
    if bad_keys:
        r.fail("G2-keys", f"case 键集必须恰为 {sorted(CASE_KEYS)}；异常：{bad_keys[:5]}")
    else:
        r.ok("G2-keys", "每例恰 7 键")

    ids = [c.get("case_id") for c in cases]
    if ids != list(range(1, len(cases) + 1)):
        r.fail("G2-ids", f"case_id 必须 1..{len(cases)} 连续递增，实际 {ids}")
    else:
        r.ok("G2-ids", "case_id 连续")


def g3_intra_case(r, cases, proto):
    # is_list / 可选输入算子：一个 dtype 可覆盖整个张量列表，长度无需逐一对应
    ins = proto.get("inputs") or []
    is_list = any(i.get("is_list") for i in ins) or any(i.get("optional") for i in ins)
    errs = []
    for c in cases:
        cid = c.get("case_id")
        ish, dt, vr = c.get("input_shape"), c.get("dtype"), c.get("value_range")
        if not isinstance(ish, list) or not ish:
            errs.append(f"case{cid}: input_shape 必须非空 list")
            continue
        if not isinstance(dt, list):
            errs.append(f"case{cid}: dtype 必须是 list")
        elif len(dt) != len(ish) and not is_list:
            errs.append(f"case{cid}: len(dtype)={len(dt)} != len(input_shape)={len(ish)}")
        for sh in shapes_of(c):
            if not sh:
                continue
            if any((not isinstance(d, int)) or d < 1 for d in sh):
                errs.append(f"case{cid}: shape {sh} 含非正整数维")
        # 逐输入写法：每项是 [lo, hi] 或 None（None = 该可选输入本例缺省，占位保持位置对齐）
        if isinstance(vr, list) and vr and all(x is None or isinstance(x, list) for x in vr) \
                and any(isinstance(x, list) for x in vr):
            if len(vr) != len(ish) and not is_list:
                errs.append(f"case{cid}: 逐输入 value_range 长度 {len(vr)} != len(input_shape) {len(ish)}")
            for one in vr:
                if one is not None and len(one) != 2:
                    errs.append(f"case{cid}: value_range 元素 {one} 不是 [lo, hi]")
        elif isinstance(vr, list):
            if len(vr) != 2:
                errs.append(f"case{cid}: 共享 value_range {vr} 不是 [lo, hi]")
        else:
            errs.append(f"case{cid}: value_range 必须是 list")
    if errs:
        r.fail("G3-intra", f"{len(errs)} 处：{errs[:6]}")
    else:
        r.ok("G3-intra", "shape/dtype/value_range 长度与取值自洽")


# ══════════════════════ G4/G5 proto.yaml ══════════════════════

def g4_proto_schema(r, proto, op_dir):
    miss = [k for k in PROTO_REQUIRED if k not in proto]
    if miss:
        r.fail("G4-proto-keys", f"operator 缺必填键 {miss}")
    else:
        r.ok("G4-proto-keys", f"10 必填键齐备")

    cat = proto.get("category")
    if cat not in CATEGORIES:
        r.warn("G4-category", f"category={cat!r} 不在 13 类合法取值中；作为上下文注入下游 prompt，写错会误导算子归类")
    else:
        r.ok("G4-category", cat)

    diff = proto.get("difficulty")
    if diff not in DIFFICULTIES:
        r.fail("G4-difficulty", f"difficulty={diff!r} 必须是 L1/L2/L3/L4")
    else:
        parent = os.path.basename(os.path.dirname(os.path.abspath(op_dir)))
        if parent.startswith("level") and diff != f"L{parent[5:]}":
            r.fail("G4-difficulty", f"difficulty={diff} 与目录 {parent} 不一致（两者必须恒等）")
        else:
            r.ok("G4-difficulty", diff)

    for grp in ("inputs", "outputs"):
        for i, item in enumerate(proto.get(grp) or []):
            for k in ("name", "description", "dtype"):
                if k not in item:
                    r.fail(f"G4-{grp}", f"{grp}[{i}] 缺 {k}")
    for i, a in enumerate(proto.get("attrs") or []):
        for k in ("name", "type", "description"):
            if k not in a:
                r.fail("G4-attrs", f"attrs[{i}] 缺 {k}")


def g5_proto_cases(r, proto, cases):
    pname = proto.get("name")
    bad = {c.get("operator") for c in cases} - {pname}
    if bad:
        r.fail("G5-name", f"cases[].operator 含 {bad}，必须恒等于 proto.operator.name={pname!r}")
    else:
        r.ok("G5-name", f"operator 名一致：{pname}")

    ins = proto.get("inputs") or []
    n_req = sum(1 for i in ins if not i.get("optional"))
    n_all = len(ins)
    is_list = any(i.get("is_list") for i in ins)
    outliers = []
    for c in cases:
        n = len(c["input_shape"])
        if not (n_req <= n <= n_all):
            outliers.append((c["case_id"], n))
    if outliers and not is_list:
        r.fail("G5-arity", f"len(input_shape) 应在 [{n_req},{n_all}]（必选~全部输入），越界：{outliers[:6]}")
    elif outliers:
        r.warn("G5-arity", f"is_list 算子，input_shape 元数可变：{outliers[:4]}")
    else:
        r.ok("G5-arity", f"input_shape 元数 ∈ [{n_req},{n_all}]")

    # 每个位置的 dtype 必须在 proto 声明集合内
    errs = []
    for c in cases:
        for pos, d in enumerate(c["dtype"]):
            if pos >= len(ins) or d is None:   # None = 该可选输入本例缺省
                continue
            allowed = ins[pos].get("dtype") or []
            if isinstance(allowed, list) and allowed and d not in allowed:
                errs.append(f"case{c['case_id']} 输入{pos}({ins[pos].get('name')}) dtype={d} ∉ {allowed}")
    if errs:
        r.fail("G5-dtype", f"{len(errs)} 处 dtype 未在 proto 声明：{errs[:5]}")
    else:
        r.ok("G5-dtype", "每例 dtype 均在 proto 声明集内")

    # attrs：不得发明 proto 未声明的 attr；proto 的必选 attr 应每例出现
    declared = {a["name"] for a in (proto.get("attrs") or []) if "name" in a}
    used = set(attr_values(cases).keys())
    invented = used - declared
    if invented:
        r.fail("G5-attrs", f"cases 出现 proto 未声明的 attr {sorted(invented)}")
    never = declared - used
    if never:
        r.warn("G5-attrs", f"proto 声明但 20 例从未取值的 attr {sorted(never)}（覆盖不足）")
    if not invented and not never:
        r.ok("G5-attrs", f"attr 集一致（{len(declared)} 个）")


# ══════════════════════ G6/G7 desc.md ══════════════════════

def g6_desc_structure(r, desc, proto):
    is_l4 = proto.get("difficulty") == "L4"
    # L4 FA 家族不写 `## 6. 额外信息`（无 .so 直调示例的意义），只有前五节。
    want_sections = DESC_SECTIONS_L4 if is_l4 else DESC_SECTIONS
    want_h3 = DESC_H3_REQUIRED_L4 if is_l4 else DESC_H3_REQUIRED
    n = len(want_sections)

    h2 = desc_h2(desc)
    titles = [t for _, t in h2]
    if titles[:n] != want_sections:
        r.fail("G6-sections", f"前 {n} 节必须严格是 {want_sections}，实际 {titles[:n]}")
    elif is_l4 and len(titles) > n:
        # L4 多出 §6（额外信息）等节 → 违反「FA 类不写额外信息」
        r.fail("G6-sections", f"L4 FA 算子不应有第 {n+1} 节（`## {n+1}. 额外信息`）；实际 {titles[:n+1]}")
    else:
        r.ok("G6-sections", f"{'五' if is_l4 else '六'}节骨架正确")
    nums = [num for num, _ in h2]
    if nums[:n] != list(range(1, n + 1)):
        r.fail("G6-sections", f"节号必须 1..{n} 递增，实际 {nums[:n]}")

    h3 = desc_h3(desc)
    miss = [s for s in want_h3 if s not in h3]
    if miss:
        r.fail("G6-h3", f"缺必备子节 {miss}")
    else:
        r.ok("G6-h3", f"{len(want_h3)} 个必备子节齐备")

    if SUPPORT_TABLE_HEADER not in desc:
        r.fail("G6-support-table", f"§3 必须含表头 {SUPPORT_TABLE_HEADER!r}（固定三列）")
    else:
        r.ok("G6-support-table", "支持范围表头正确")

    tbl = parse_support_table(desc)
    if tbl is not None and len(tbl) < 3:
        r.warn("G6-support-table", f"支持范围仅 {len(tbl)} 行（典型 3~15 行）")


def g7_interface_identity(r, desc, proto, op_dir):
    schema = str(proto.get("schema") or "")
    proto_sig = desc_prototype(desc)
    if not proto_sig:
        r.fail("G7-prototype", "§3 算子原型缺代码块")
        return
    # desc 原型形如 cann_bench.<fn>(...) -> ...；proto.schema 形如 <fn>(...) -> ...
    m = re.match(r"(?:torch\.ops\.npu\.|cann_bench\.)?([A-Za-z_]\w*)\s*\(", proto_sig)
    fn_desc = m.group(1) if m else None
    m2 = re.match(r"([A-Za-z_]\w*)\s*\(", schema)
    fn_proto = m2.group(1) if m2 else None
    if fn_desc != fn_proto:
        r.fail("G7-prototype", f"desc §3 函数名 {fn_desc!r} != proto.schema 函数名 {fn_proto!r}")
    else:
        r.ok("G7-prototype", f"接口名一致：{fn_desc}")

    expect = snake(str(proto.get("name") or ""))
    if fn_proto and squash(fn_proto) != squash(expect):
        r.warn("G7-naming", f"schema 名 {fn_proto} 与 snake(proto.name)={expect} 不同")

    # 参数名序列一致性（desc 原型 vs proto.schema）
    def params(sig):
        inner = sig[sig.find("(") + 1: sig.rfind(")")] if "(" in sig else ""
        out = []
        for tok in re.split(r",(?![^\[\]]*\])", inner):
            tok = tok.strip()
            if not tok:
                continue
            tok = tok.split("=")[0].strip()
            out.append(tok.split()[-1] if " " in tok else tok)
        return out
    pd, pp = params(proto_sig), params(schema)
    if pd != pp:
        r.fail("G7-params", f"参数序列不一致 desc={pd} proto={pp}")
    else:
        r.ok("G7-params", f"参数序列一致 {pd}")

    # golden.py 函数名与签名
    gpath = os.path.join(op_dir, "golden.py")
    if os.path.isfile(gpath):
        src = open(gpath, encoding="utf-8").read()
        fns = re.findall(r"^def (\w+)\(", src, re.M)
        if fn_proto and fn_proto not in fns:
            r.fail("G7-golden-name", f"golden.py 未定义 def {fn_proto}(...)，实际 {fns}")
        else:
            r.ok("G7-golden-name", f"golden.py 定义 {fn_proto}")

    # desc §5 的 golden 代码应与 golden.py 同名同参（允许 golden.py 多做 dtype 提升）
    body = desc_prototype(desc)
    if body and fn_proto:
        gsec = re.search(r"^def " + re.escape(fn_proto) + r"\(", str(desc), re.M)
        if not gsec:
            r.warn("G7-golden-desc", f"desc §5 未见 def {fn_proto}(...)")


# ══════════════════════ G8 支持范围自洽 ══════════════════════

_NUM = r"(\d+(?:\.\d+)?)"


def g8_support_selfconsistency(r, desc, cases, proto):
    tbl = parse_support_table(desc)
    if not tbl:
        r.warn("G8-support", "无法解析支持范围表，跳过自洽校验")
        return
    checked = skipped = 0
    for name, rng, note in tbl:
        low = name.lower()
        is_dimsize = any(k in low for k in ("各维大小", "各维度大小", "shape[i]", "dim_size")) \
            or "各维" in name
        is_ndim = "维度数" in name or "ndim" in low
        if not (is_dimsize or is_ndim):
            continue
        pos, qualified = row_input_pos(name, proto)
        if qualified:
            skipped += 1
            continue
        # 单输入算子时行名即该输入；多输入且无法归因则跳过（不误判）
        n_in = len(proto.get("inputs") or [])
        if pos is None:
            if n_in != 1:
                skipped += 1
                continue
            pos = 0
        m = measured_ranges(cases, input_pos=pos)
        if m["dim_min"] is None:
            continue

        if is_dimsize:
            a, b = parse_range_cell(note)
            if a is not None and b is not None:
                checked += 1
                # 备注常以括号补注 1D 超长维（如「2 ~ 8192（含 1D 长度 1000003）」），
                # 故上界只要求「不低于实测」或「实测最大维在备注中被显式提及」。
                if b < m["dim_max"] and str(m["dim_max"]) not in str(note):
                    r.fail("G8-support", f"「{name}」备注声称实测上界 {b:g}，"
                                         f"但 cases 实际最大维 {m['dim_max']}")
                if a > m["dim_min"]:
                    r.fail("G8-support", f"「{name}」备注声称实测下界 {a:g}，"
                                         f"但 cases 实际最小维 {m['dim_min']}")
            lo, hi = parse_range_cell(rng)
            if hi is not None and m["dim_max"] > hi:
                r.fail("G8-support", f"「{name}」声明范围上界 {hi:g} < 实测最大维 {m['dim_max']}")

        if is_ndim:
            claim = parse_ndim_claim(note)
            if claim:
                checked += 1
                if claim != set(m["ndim"]):
                    r.fail("G8-support", f"「{name}」备注声称实测 {sorted(claim)}D，"
                                         f"但 cases 实际 {m['ndim']}D")
            lo, hi = parse_range_cell(rng)
            if hi is not None and max(m["ndim"]) > hi:
                r.fail("G8-support", f"「{name}」声明维度上界 {hi:g} < 实测最大维度数 {max(m['ndim'])}")
    if checked:
        r.ok("G8-support", f"支持范围备注列已比对 {checked} 行"
                           f"（实测值来自 cases.yaml{f'，{skipped} 行含限定语已跳过' if skipped else ''}）")
    elif proto.get("difficulty") == "L4":
        # L4 FA 支持范围表用符号维度（B/S/S_kv/N/D）做行名、备注写场景化实测，不走
        # 「各维大小 / 实测 A~B」的 L1 句式 —— 无可机械比对不是缺陷，降级为 ok。
        r.ok("G8-support", "L4 FA 符号维度支持范围表，无 L1『各维大小/实测 A~B』句式可机械比对（正常）")
    else:
        r.warn("G8-support", f"支持范围备注列无可机械比对的「实测 A ~ B」表述"
                             f"{f'（{skipped} 行含限定语）' if skipped else ''}")


# ══════════════════════ G9/G10 用例设计覆盖 ══════════════════════

def g9_value_range_sanity(r, cases, op_dir):
    strs = find_string_specials(op_dir)
    if strs:
        r.warn("G9-inf-form", f"case {strs} 的 value_range 用字符串写 inf/nan；"
                              f"规范写法是 YAML 原生 `.inf` / `-.inf` / `.nan`")
    errs = []
    for c in cases:
        vr, dts = c["value_range"], c["dtype"]
        per = vr if (vr and all(x is None or isinstance(x, list) for x in vr)
                     and any(isinstance(x, list) for x in vr)) else [vr] * len(dts)
        for pos, (one, dt) in enumerate(zip(per, dts)):
            if one is None or dt is None or len(one) != 2:
                continue
            lo, hi = one
            if not isinstance(lo, (int, float)) or not isinstance(hi, (int, float)):
                errs.append(f"case{c['case_id']} 输入{pos}: value_range {one} 含非数值项")
                continue
            if math.isnan(lo) or math.isnan(hi):
                continue
            if math.isinf(lo) or math.isinf(hi):
                continue
            if lo > hi:
                errs.append(f"case{c['case_id']} 输入{pos}: lo>hi {one}")
            lim = DTYPE_LIMITS.get(dt)
            if lim and (lo < lim[0] or hi > lim[1]):
                errs.append(f"case{c['case_id']} 输入{pos}: {one} 超出 {dt} 可表示范围 "
                            f"[{lim[0]:g}, {lim[1]:g}]")
            if dt in INT_DTYPES and any(isinstance(v, float) and not float(v).is_integer()
                                        for v in (lo, hi)):
                errs.append(f"case{c['case_id']} 输入{pos}: 整型 {dt} 的值域 {one} 含小数")
    if errs:
        r.fail("G9-value-range", f"{len(errs)} 处：{errs[:6]}")
    else:
        r.ok("G9-value-range", "值域与 dtype 可表示范围自洽")


# L4 FA 场景 slug —— note 里应出现的注意力场景与 head-dim 覆盖信号。
# 与 L1 的对齐/特殊值配额不同：注意力算子的覆盖面是「计算模式 × 真实 head 维」。
_FA_SCENARIOS = ("prefill", "decode", "cross", "mtp", "causal")


def _g10_scenario_coverage(r, cases, blob):
    """L4 FA 家族的覆盖检查：场景 slug + head-dim 档位（替代 L1 的对齐/特殊值/维度数）。

    note 用 `prefill-causal` / `decode` / `cross` / `MTP` 这类场景 slug 标注计算模式，
    head dim 通常取 64 / 128 / 256。这两条是注意力算子真正需要覆盖的维度，
    L1 的「对齐档 / inf-nan-零值 / 1D~5D」在此语义上无意义。
    """
    low = blob.lower()
    hit = [s for s in _FA_SCENARIOS if s in low]
    miss = [s for s in _FA_SCENARIOS if s not in low]
    # head dim：从 note 里的 `D64` / `D128` / `D256` 或 `-64` 后缀识别不可靠，
    # 直接从用例最后一维统计更稳。
    dims = sorted({sh[-1] for c in cases for sh in shapes_of(c) if sh})
    head_dims = sorted(d for d in dims if d in (64, 128, 256))
    if len(hit) < 3:
        r.warn("G10-scenario",
               f"FA 场景覆盖偏弱：命中 {hit or '无'}，缺 {miss}"
               f"（应覆盖 prefill/decode/cross/MTP/causal 中至少 3 类）")
    elif len(head_dims) < 2:
        r.warn("G10-scenario",
               f"head dim 覆盖偏弱：仅 {head_dims or dims}（典型应覆盖 64/128/256 中至少 2 档）")
    else:
        r.ok("G10-scenario",
             f"FA 场景覆盖 {hit}，head dim {head_dims}（L4 场景驱动，L1 骨架启发式不适用）")


def g10_design_coverage(r, cases, proto):
    notes = [note_core(c["note"]) for c in cases]
    blob = " ".join(notes)

    # L4 FA 注意力家族按「场景」设计用例（prefill/decode/cross/MTP/causal + 真实 head dim），
    # 而非 L1 的 shape/dtype/对齐/特殊值 20 行骨架。对齐档 / inf-nan-零值 / 1D~5D 这三条
    # L1 覆盖启发式对固定 4D、只有 fp16/bf16 的注意力算子在语义上不适用 —— 换成 G10-scenario。
    if proto.get("difficulty") == "L4":
        _g10_scenario_coverage(r, cases, blob)
    else:
        align = {k: sum(1 for n in notes if k in n) for k in ("对齐", "非对齐", "质数非对齐")}
        n_aligned = align["对齐"] - align["非对齐"]  # 「非对齐」串内含「对齐」
        if align["非对齐"] == 0 or n_aligned <= 0:
            r.warn("G10-align", f"对齐性维度覆盖偏弱 {align}（基准配额 5 对齐 / 9 非对齐 / 6 质数非对齐）")
        else:
            r.ok("G10-align", f"对齐性覆盖 {align}")

        specials = {k: (k in blob) for k in ("inf特殊值", "nan特殊值", "零值")}
        miss = [k for k, v in specials.items() if not v]
        out_dtypes = set()
        for o in (proto.get("outputs") or []):
            out_dtypes |= set(o.get("dtype") or [])
        float_out = bool(out_dtypes & FLOAT_DTYPES)
        if miss and float_out:
            r.warn("G10-special", f"缺特殊值用例 {miss}（浮点算子应三者齐备）")
        else:
            r.ok("G10-special", f"特殊值覆盖 {[k for k,v in specials.items() if v]}")

        nd = sorted({len(sh) for c in cases for sh in shapes_of(c)})
        if len(nd) < 3:
            r.warn("G10-ndim", f"仅覆盖 {nd} 维（典型应覆盖 1D~5D 共 5 档）")
        else:
            r.ok("G10-ndim", f"维度档位覆盖 {nd}")

    dts = measured_ranges(cases)["dtypes"]
    declared = set((proto.get("inputs") or [{}])[0].get("dtype") or [])
    uncovered = declared - set(dts)
    if uncovered:
        r.warn("G10-dtype-cov", f"proto 声明但未覆盖的 dtype {sorted(uncovered)}")
    else:
        r.ok("G10-dtype-cov", f"首输入 dtype 全覆盖 {dts}")


# ══════════════════════ G11 CSV 一致 ══════════════════════

def g11_csv(r, op_dir):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from gen_cases_csv import check_one
    try:
        bad = check_one(op_dir)
    except (OSError, ValueError, KeyError) as e:
        r.fail("G11-csv", f"{type(e).__name__}: {e}")
        return
    if bad:
        r.fail("G11-csv", f"cases.csv 与 cases.yaml 不一致 {len(bad)} 处：{bad[:6]}"
                          f"（应由 gen_cases_csv.py 机械生成）")
    else:
        r.ok("G11-csv", "cases.csv == cases.yaml 机械派生结果")


# ══════════════════════ G12/G13 golden 实跑 ══════════════════════

def _load_golden(op_dir, fn_name):
    spec = importlib.util.spec_from_file_location(
        f"golden_{os.path.basename(op_dir)}", os.path.join(op_dir, "golden.py"))
    mod = importlib.util.module_from_spec(spec)
    # 不要在算子目录里落 __pycache__ —— 那会让「五文件齐备」的 G1 门看到第 6 个条目，
    # 并把编译缓存带进交付产物。
    prev, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = prev
    return getattr(mod, fn_name)


def _make_tensor(torch, shape, dtype, vr):
    td = getattr(torch, dtype, None)
    if td is None:
        raise ValueError(f"未知 dtype {dtype}")
    lo, hi = vr
    is_nan = isinstance(lo, float) and math.isnan(lo)
    has_inf = any(isinstance(v, float) and math.isinf(v) for v in (lo, hi))
    if is_nan:
        return torch.full(shape, float("nan"), dtype=td)
    if has_inf:
        t = torch.empty(shape, dtype=torch.float32).uniform_(-10, 10)
        flat = t.view(-1)
        n = flat.numel()
        flat[0:max(1, n // 100)] = float("inf")
        flat[max(1, n // 100):max(2, n // 50)] = float("-inf")
        return t.to(td)
    if dtype in INT_DTYPES:
        if dtype == "bool":
            return torch.randint(0, 2, shape).bool()
        return torch.randint(int(lo), int(hi) + 1 if hi >= lo else int(lo) + 1,
                             shape, dtype=td)
    if lo == hi:
        return torch.full(shape, float(lo), dtype=td)
    # 先在 float32 取样再降型：fp16 的 uniform_ 不接受跨度超过 fp16 max 的区间
    # （如边界值用例 [-65504, 65504]），float32 取样后 cast 语义等价且不溢出。
    # 但 float32 自身也受此限制（跨度须 <= float32 max），故满量程区间改用
    # 「[0,1) 均匀采样后线性映射」，数学上等价且不触发 uniform_ 的跨度断言。
    lo_f, hi_f = float(lo), float(hi)
    if hi_f - lo_f > 3.4e38:
        t = torch.rand(shape, dtype=torch.float32)
        return (t * (hi_f / 2 - lo_f / 2) * 2 + lo_f).to(td)
    return torch.empty(shape, dtype=torch.float32).uniform_(lo_f, hi_f).to(td)


# golden 报出的这些错，说明用例带有「跨输入语义不变量」（如 indices 必须是合法下标、
# 各 expert token 数之和必须等于 batch），通用随机合成器无从推断。这类失败是
# **本校验器的能力边界**，不是产物缺陷 —— 记为 UNSYNTH（WARN）而非 FAIL，
# 并要求生成侧在 desc.md 里把该不变量写清楚，供下游造数时遵守。
_UNSYNTHESIZABLE = (
    "must equal",           # 和/计数类不变量
    "must match the size",  # 跨输入 shape 耦合
    "index out of range", "out of bounds", "must be within",
    "Boolean value of Tensor",   # attr 期望标量、用例给了张量
    "必须为 None", "must be None",
)


def _is_unsynthesizable(msg):
    return any(k in msg for k in _UNSYNTHESIZABLE)


def _scale_shape(shape, attrs, max_numel):

    """把超过 max_numel 的 shape 缩到内存可承受范围，且不破坏用例语义。

    缩最大的那一维，并保证不低于任何整数 attr 的取值 —— 否则像 top_k 的 `k=1024`
    会因为把 dim 从 8192 缩到 512 而变成非法用例（k > shape[dim]），
    产生「golden 跑挂」的假告警。缩不下来就不缩，交给内存去承受。
    """
    if not shape or math.prod(shape) <= max_numel:
        return shape, False
    floor = 1
    for v in (attrs or {}).values():
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            floor = max(floor, abs(v))
        elif isinstance(v, list):
            floor = max([floor] + [abs(x) for x in v
                                   if isinstance(x, int) and not isinstance(x, bool)])
    out = list(shape)
    i = max(range(len(out)), key=lambda j: out[j])
    rest = math.prod(out) // out[i]
    target = max(floor, max_numel // max(rest, 1), 1)
    if target >= out[i]:
        return shape, False
    out[i] = target
    return out, True



def g12_g13_golden(r, op_dir, proto, cases, max_numel, verbose):
    try:
        import torch
    except ImportError:
        r.warn("G12-golden", "torch 不可用，跳过 golden 实跑")
        return
    schema = str(proto.get("schema") or "")
    m = re.match(r"([A-Za-z_]\w*)\s*\(", schema)
    fn_name = m.group(1) if m else snake(str(proto.get("name")))
    try:
        fn = _load_golden(op_dir, fn_name)
    except Exception as e:                                   # noqa: BLE001
        r.fail("G12-golden", f"无法从 golden.py 取得 {fn_name}: {type(e).__name__}: {e}")
        return
    sig = inspect.signature(fn)
    r.ok("G12-golden", f"golden.py 可导入，{fn_name}{sig}")

    torch.manual_seed(0)
    n_ok = n_scaled = n_skip = 0
    fails, unsynth = [], []
    for c in cases:
        cid = c["case_id"]
        shapes = [list(s) for s in shapes_of(c)]
        dts = c["dtype"]
        vr = c["value_range"]
        per = vr if (vr and all(x is None or isinstance(x, list) for x in vr)
                     and any(isinstance(x, list) for x in vr)) else [vr] * len(shapes)
        per = [x for x in per if x is not None]
        dts = [d for d in dts if d is not None]
        scaled = False
        # 多输入算子的 shape 之间通常互相耦合（conv 的 C_in 必须等于 filter 的 C_in），
        # 单独缩某一个输入会造出非法用例。故只对单输入算子缩放；
        # 多输入且确实过大的用例记为 skip，而不是伪造成 FAIL。
        may_scale = len(shapes) == 1
        if not may_scale and sum(math.prod(s) for s in shapes if s) > 4 * max_numel:
            n_skip += 1
            continue
        try:
            args = []
            for i, sh in enumerate(shapes):
                if may_scale:
                    sh, did = _scale_shape(sh, c.get("attrs"), max_numel)
                    scaled = scaled or did
                dt = dts[i] if i < len(dts) else dts[-1]
                one = per[i] if i < len(per) else per[-1]
                args.append(_make_tensor(torch, sh, dt, one))
            # 按 golden 的**形参顺序**绑定，而不是假定「张量在前、attr 在后」：
            # 有的 golden 把 attr 夹在张量之间（scatter 的 (x, dim, indices, updates)），
            # 有的把张量列表当单个参数收（foreach_*）。形参名命中 attrs 就填 attr，
            # 否则按顺序取下一个张量；张量用尽后剩余形参交给默认值。
            attrs_map = dict(c.get("attrs") or {})
            params = list(sig.parameters.values())
            call, ti = [], 0
            for p in params:
                if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                    continue
                if p.name in attrs_map:
                    call.append(attrs_map.pop(p.name))
                elif ti < len(args):
                    call.append(args[ti])
                    ti += 1
                elif p.default is not p.empty:
                    call.append(p.default)
            if ti < len(args):
                # 形参比张量少：foreach_* 这类把「整个张量列表」当一个形参收。
                # 把多出来的张量按形参顺序均分给各张量形参（每个形参收一个列表）。
                pos = [p for p in params
                       if p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)]
                tensor_slots = [p for p in pos if p.name not in (c.get("attrs") or {})]
                k = len(tensor_slots)
                call = []
                if k:
                    per = max(1, len(args) // k)
                    chunks = [args[i * per:(i + 1) * per] for i in range(k)]
                    chunks[-1] = args[(k - 1) * per:]        # 余数并入最后一组
                it = iter(chunks) if k else iter(())
                for p in pos:
                    if p.name in (c.get("attrs") or {}):
                        call.append((c.get("attrs") or {})[p.name])
                    else:
                        call.append(next(it, []))
            args, kwargs = call, {}
            with torch.no_grad():
                out = fn(*args, **kwargs)
            outs = out if isinstance(out, (tuple, list)) else (out,)
            for o in outs:
                if not hasattr(o, "shape"):
                    raise TypeError(f"golden 返回非 tensor：{type(o)}")
            n_ok += 1
            n_scaled += int(scaled)
        except Exception as e:                               # noqa: BLE001
            msg = f"case{cid}: {type(e).__name__}: {str(e)[:120]}"
            (unsynth if _is_unsynthesizable(str(e)) else fails).append(msg)
    if fails:
        r.fail("G13-golden-run", f"{len(fails)}/{len(cases)} 例跑挂：{fails[:5]}")
    else:
        detail = []
        if n_scaled:
            detail.append(f"{n_scaled} 例为控内存缩放了最大维")
        if n_skip:
            detail.append(f"{n_skip} 例因多输入 shape 耦合且过大而跳过")
        r.ok("G13-golden-run",
             f"{n_ok}/{len(cases)} 例复算通过" + (f"（{'，'.join(detail)}）" if detail else ""))
    if unsynth:
        r.warn("G13-unsynth",
               f"{len(unsynth)} 例含跨输入语义不变量（合法下标 / 计数和 / 标量 attr），"
               f"通用随机造数无从满足，非产物缺陷；"
               f"请确认 desc.md 已写明该约束供下游造数：{unsynth[:3]}")


# ══════════════ G14/G15 L2/L3 多输入专用 ══════════════

def g14_index_bounds(r, cases, proto):
    """索引类输入的值域必须指向真实存在的维度（否则 golden 一定越界）。

    规律：索引输入的上界应满足 `hi + 1 ∈ {某输入维大小}`；
    unsorted_segment_sum 16/20、moe_finalize_routing 17/20，偏离的那几例都**语义合法**
    —— 上界由 attr（num_segments）决定，或用 `-1` 表示「无效索引」哨兵。
    故本门对「上界能被某维或某整数 attr 解释」判 PASS，否则 WARN 并要求给出依据。
    """
    idx = index_input_positions(proto)
    if not idx:
        return
    names = [str(i.get("name") or "") for i in (proto.get("inputs") or [])]
    bad, sentinel = [], []
    for c in cases:
        per = per_input_ranges(c, len(c.get("input_shape") or []))
        dims = derivable_bounds(c)        # 单维 / 维乘积 / 前缀积 / 整数 attr
        attrs = int_attr_values(c)
        for p in idx:
            if p >= len(per) or per[p] is None or len(per[p]) != 2:
                continue
            lo, hi = per[p]
            if not isinstance(lo, int) or not isinstance(hi, int):
                continue
            if lo < -1:
                bad.append(f"case{c['case_id']} {names[p]} 下界 {lo} < -1")
            elif lo == -1:
                sentinel.append(c["case_id"])
            # hi+1 应等于某个真实维度大小，或等于/小于某个整数 attr（num_segments 等）
            if (hi + 1) not in dims and hi not in attrs:
                bad.append(f"case{c['case_id']} {names[p]}=[{lo},{hi}] 的上界+1={hi+1} "
                           f"无法由「维大小 / 维乘积 / 整数 attr」解释")
    if bad:
        r.warn("G14-index-bounds",
               f"{len(bad)} 处索引值域无法由「维大小 / 整数 attr」解释，"
               f"下游按此造数会越界；若确为有意设计请在 desc.md 写明：{bad[:4]}")
    else:
        extra = f"（{len(set(sentinel))} 例用 -1 作无效索引哨兵）" if sentinel else ""
        r.ok("G14-index-bounds", f"{len(idx)} 个索引输入的值域均指向真实维度{extra}")


def g15_constraints_documented(r, cases, proto, desc):
    """跨输入耦合与语义不变量**必须写进 desc.md**，否则下游造数无从遵守。

    这是 L2/L3 成功率的关键：G13 用通用随机造数复算时，凡是撞上
    「indices 必须合法」「各组 token 数之和必须等于 M」这类不变量就会失败；
    下游 developer 同样需要照着 desc.md 造数。程序无法判断不变量*是否正确*，
    但可以判断*有没有被写下来*。
    """
    ins = proto.get("inputs") or []
    if len(ins) < 2:
        return
    text = desc_constraint_lines(desc)
    if not text.strip():
        r.fail("G15-constraints", "多输入算子的 desc.md 缺「规则与约束」/「支持范围」正文，"
                                 "跨输入约束无处承载")
        return

    inv = coupling_invariants(cases, proto)
    # 只挑「跨不同输入」的耦合做提示，并按输入对去重（同一对输入报一次即可）
    pairs = {}
    for i, ia, j, ib, ni, nj in inv:
        pairs.setdefault((ni, nj), []).append(f"{ni}[{ia}]=={nj}[{ib}]")
    undocumented = []
    for (ni, nj), items in pairs.items():
        # desc 中同时提到这两个输入名，就算已描述（不强求写成公式）
        if not (ni and nj and ni in text and nj in text):
            undocumented.append(f"{ni}↔{nj}（如 {items[0]}）")
    if undocumented:
        r.warn("G15-constraints",
               f"{len(undocumented)} 组跨输入耦合在 20 例中恒成立，但 desc.md 的"
               f"「规则与约束」/「支持范围」未同时提及这两个输入：{undocumented[:4]}"
               f"；下游据此造数会造出不合法输入")
    else:
        r.ok("G15-constraints",
             f"{len(pairs)} 组跨输入耦合均已在 desc.md 描述"
             if pairs else "无跨输入维度耦合")

    # 支持范围表后的「约束：」行 —— 多输入算子的通行写法
    sup = desc_section(desc, "支持范围") or ""
    if len(ins) >= 3 and not re.search(r"^\s*约束[：:]", sup, re.M):
        r.warn("G15-constraints",
               "3 个以上输入的算子建议在「支持范围」表后补一行 `约束：…` "
               "集中声明跨输入关系（多输入算子的通行写法）")


def g16_invocation_convention(r, desc, proto, target):
    """§3 算子原型（及非 FA 类的 §6 调用示例）必须用本仓真实的直调约定。

    ops-direct-invoke 把算子编译成 `build/lib<op>_ops.so`，经 TORCH_LIBRARY 注册到
    `npu` 命名空间，以 `torch.ops.npu.<op>(x.npu())` 调用。`cann_bench.<op>` /
    `import cann_bench` 是 **cann-bench 基准仓**的约定，本仓没有这个包，照抄会给下游
    跑不通的示例。

    调用示例里**不写** `torch.ops.load_library("build/lib<op>_ops.so")` 及其加载注释，
    也**不写**「> 算子编译为 … 注册到 npu … 接口契约」的收尾 blockquote —— 这些是接入
    背景说明，不属于需求前置输入的内容，出现即判 FAIL。

    L4 FA 注意力家族**不写 `## 6. 额外信息`**（无 §6 调用示例），只校 §3 原型。

    target='cann-bench' 时反向校验，仅用于审计 cann-bench 原生素材。
    """
    has_cb = WRONG_PREFIX in desc
    has_direct = "torch.ops.npu." in desc
    if target == "cann-bench":
        if not has_cb:
            r.warn("G16-invocation", "target=cann-bench 但 desc.md 未见 cann_bench 调用约定")
        else:
            r.ok("G16-invocation", "cann-bench 约定（原生素材）")
        return

    if has_cb:
        lines = [f"L{i+1}" for i, l in enumerate(desc.split("\n")) if WRONG_PREFIX in l]
        r.fail("G16-invocation",
               f"desc.md 出现 `{WRONG_PREFIX}`（{', '.join(lines[:6])}）—— 那是 cann-bench "
               f"基准仓的约定，本仓没有该包。§3 算子原型应写 `torch.ops.npu.<op>(...)`")
        return
    if not has_direct:
        r.warn("G16-invocation",
               "desc.md 未见 `torch.ops.npu.<op>` 直调约定；§3 原型"
               "应体现本仓真实调用形态")
        return

    # load_library / 接口契约收尾 blockquote 一律不写（无论 FA 与否）
    bad = []
    for i, l in enumerate(desc.split("\n")):
        if "load_library" in l:
            bad.append(f"L{i+1}(load_library)")
        elif "接口契约" in l:
            bad.append(f"L{i+1}(接口契约收尾说明)")
    if bad:
        r.fail("G16-invocation",
               f"desc.md 不应出现 {'/'.join(bad[:6])} —— §6 调用示例不写 "
               f"`torch.ops.load_library(...)` 及其加载注释，也不写「注册到 npu…接口契约」"
               f"收尾 blockquote（这些是接入背景，非前置输入内容）")
    else:
        r.ok("G16-invocation", "torch.ops.npu 直调约定（§3 原型，无 load_library/接口契约收尾）")


# ══════════════════════ 主流程 ══════════════════════

def validate(op_dir, run_golden=False, max_numel=1 << 22, verbose=False,
             target="direct-invoke"):
    r = Report(op_dir)
    if not g1_files(r):
        return r
    try:
        cases = load_cases(op_dir)
        proto = load_proto(op_dir)
        desc = load_desc(op_dir)
    except (OSError, ValueError) as e:
        r.fail("G1-parse", f"{type(e).__name__}: {e}")
        return r

    g2_cases_schema(r, cases)
    g3_intra_case(r, cases, proto)
    g4_proto_schema(r, proto, op_dir)
    g5_proto_cases(r, proto, cases)
    g6_desc_structure(r, desc, proto)
    g7_interface_identity(r, desc, proto, op_dir)
    g8_support_selfconsistency(r, desc, cases, proto)
    g9_value_range_sanity(r, cases, op_dir)
    g10_design_coverage(r, cases, proto)
    g11_csv(r, op_dir)
    g14_index_bounds(r, cases, proto)
    g15_constraints_documented(r, cases, proto, desc)
    g16_invocation_convention(r, desc, proto, target)
    if run_golden:
        g12_g13_golden(r, op_dir, proto, cases, max_numel, verbose)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("op_dirs", nargs="+")
    ap.add_argument("--run-golden", action="store_true", help="追加 G12/G13：实跑 golden.py")
    ap.add_argument("--max-numel", type=int, default=1 << 22,
                    help="golden 实跑单输入元素上限，超出按首维缩放（默认 4M）")
    ap.add_argument("-v", "--verbose", action="store_true", help="打印 PASS 明细")
    ap.add_argument("--target", choices=("direct-invoke", "cann-bench"),
                    default="direct-invoke",
                    help="调用约定目标：本仓算子用 direct-invoke（torch.ops.npu）；"
                         "审计 cann-bench 原生素材时用 cann-bench")
    args = ap.parse_args()

    n_fail = 0
    for d in args.op_dirs:
        d = d.rstrip("/")
        if not os.path.isdir(d):
            print(f"SKIP {d}: 不是目录")
            continue
        rep = validate(d, args.run_golden, args.max_numel, args.verbose, args.target)
        print(rep.render(args.verbose))
        n_fail += bool(rep.n_fail)
    if len(args.op_dirs) > 1:
        print(f"\n合计：{len(args.op_dirs)} 个算子，{n_fail} 个存在 FAIL")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
