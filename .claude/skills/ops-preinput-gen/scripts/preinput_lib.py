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

"""ops-preinput-gen 共享库：前置输入五文件的加载、序列化与派生。

被 gen_cases_csv.py / validate_preinput.py / run_golden_selftest.py 共用。
本模块只依赖 stdlib + pyyaml；torch 仅在 golden 自测路径按需 import。
"""

import csv
import json
import math
import re
import sys

import yaml

FILES = ("desc.md", "cases.yaml", "cases.csv", "proto.yaml", "golden.py")

CSV_HEADER = ["operator", "case_id", "input_shape", "dtype", "attrs", "value_range", "note"]
CASE_KEYS = set(CSV_HEADER)
N_CASES = 20

# proto.yaml operator.* —— 必填键
PROTO_REQUIRED = (
    "name", "category", "difficulty", "formula",
    "description", "shape_support", "attrs", "inputs", "outputs", "schema",
)
# category 合法取值全集（13 类）。作为上下文注入下游 prompt，不得新造（保持归类一致）。
CATEGORIES = {
    "Elementwise", "Broadcast", "Reduction", "Normalization", "Contraction",
    "LayoutTransform", "SortSelect", "ScatterUpdate", "IndexGather",
    "MaskPredicate", "NumericalStable", "VVFusion", "FusedComposite",
}
DIFFICULTIES = {"L1", "L2", "L3", "L4"}

# desc.md 节骨架 —— 顺序固定，不可增删。
# L1/L2/L3 是六节；L4 FA 注意力家族**不写 `## 6. 额外信息`**（无 .so 直调示例的意义），
# 只有前五节。校验器按 difficulty 取对应切片（见 g6_desc_structure）。
DESC_SECTIONS = ["算子简介", "算子定义", "接口规范", "精度要求", "标准 Golden 代码", "额外信息"]
DESC_SECTIONS_L4 = DESC_SECTIONS[:5]  # 不含「额外信息」
# H3 子节：必备。L4 无 §6，故不要求「算子调用示例」。
DESC_H3_REQUIRED = ["数学公式", "算子原型", "输出", "数据类型", "规则与约束", "支持范围", "算子调用示例"]
DESC_H3_REQUIRED_L4 = ["数学公式", "算子原型", "输出", "数据类型", "规则与约束", "支持范围"]

SUPPORT_TABLE_HEADER = "| 维度 / 参数 | 范围 | 备注 |"

# 算子原型/调用示例的合法前缀。ops-direct-invoke 直调流程把算子编译成
# `build/lib<op>_ops.so`，经 TORCH_LIBRARY 注册到 `npu` 命名空间，
# 以 `torch.ops.npu.<op>(x.npu())` 调用，.so 名为 lib<op>_ops.so。
# `cann_bench.` 是 cann-bench 基准仓的约定，本仓不适用。
PROTO_PREFIXES = ("torch.ops.npu.", "cann_bench.")
WRONG_PREFIX = "cann_bench"

FLOAT_DTYPES = {"float16", "float32", "bfloat16", "float64", "hifloat32"}
INT_DTYPES = {"int8", "uint8", "int16", "uint16", "int32", "uint32", "int64", "uint64", "bool"}

DTYPE_LIMITS = {  # (min, max) 可表示范围；整型是非对称的，不能用 abs 比
    "float16": (-65504.0, 65504.0),
    "bfloat16": (-3.39e38, 3.39e38),
    "float32": (-3.40e38, 3.40e38),
    "int8": (-128, 127),
    "uint8": (0, 255),
    "int16": (-32768, 32767),
    "uint16": (0, 65535),
    "int32": (-2147483648, 2147483647),
    "uint32": (0, 4294967295),
    "int64": (-(2**63), 2**63 - 1),
    "bool": (0, 1),
}


# ─────────────────────────── 序列化 ───────────────────────────

def to_csv_scalar(v):
    """把 YAML 侧的 inf/nan 浮点还原为 CSV/JSON 侧的字符串形式。

    约定：YAML 写 `.inf` / `-.inf` / `.nan`，CSV 内嵌 JSON 写 "inf" / "-inf" / "nan"。
    """
    if isinstance(v, float):
        if math.isinf(v):
            return "inf" if v > 0 else "-inf"
        if math.isnan(v):
            return "nan"
    return v


def deep_csv(v):
    if isinstance(v, list):
        return [deep_csv(x) for x in v]
    if isinstance(v, dict):
        return {k: deep_csv(x) for k, x in v.items()}
    return to_csv_scalar(v)


def from_csv_scalar(v):
    """CSV/JSON 侧字符串形式还原为浮点，用于回读比对。"""
    if isinstance(v, str):
        low = v.lower()
        if low == "inf":
            return math.inf
        if low == "-inf":
            return -math.inf
        if low == "nan":
            return math.nan
    return v


def deep_from_csv(v):
    if isinstance(v, list):
        return [deep_from_csv(x) for x in v]
    if isinstance(v, dict):
        return {k: deep_from_csv(x) for k, x in v.items()}
    return from_csv_scalar(v)


def eq_nan(a, b):
    """结构化比较，NaN == NaN 视为相等（NaN 是合法用例值，不是错误）。"""
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(eq_nan(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(eq_nan(a[k], b[k]) for k in a)
    if isinstance(a, float) and isinstance(b, float):
        if math.isnan(a) and math.isnan(b):
            return True
    return a == b


def cases_to_csv_rows(cases):
    """cases.yaml 的 cases 列表 → cases.csv 的行（含表头）。纯机械派生。"""
    rows = [list(CSV_HEADER)]
    for c in cases:
        rows.append([
            str(c["operator"]),
            str(c["case_id"]),
            json.dumps(deep_csv(c["input_shape"]), ensure_ascii=False),
            json.dumps(deep_csv(c["dtype"]), ensure_ascii=False),
            json.dumps(deep_csv(c["attrs"]), ensure_ascii=False),
            json.dumps(deep_csv(c["value_range"]), ensure_ascii=False),
            str(c["note"]),
        ])
    return rows


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f, lineterminator="\n").writerows(rows)


# ─────────────────────────── 加载 ───────────────────────────

def load_cases(op_dir, normalize=True):
    """加载 cases.yaml。

    normalize=True 时把 value_range 里被写成字符串的 'inf'/'-inf'/'nan' 归一为浮点。
    规范写法是 YAML 原生 `.inf` / `-.inf` / `.nan`；字符串形式归一后
    下游比对/建 tensor 才有单一表示。
    """
    with open(f"{op_dir}/cases.yaml", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    if not isinstance(doc, dict) or "cases" not in doc:
        raise ValueError("cases.yaml 缺少顶层 `cases:` 键")
    cases = doc["cases"]
    if normalize:
        for c in cases:
            if "value_range" in c:
                c["value_range"] = deep_from_csv(c["value_range"])
    return cases


def find_string_specials(op_dir):
    """返回 value_range 里用字符串写 inf/nan 的 case_id 列表（非规范写法）。"""
    with open(f"{op_dir}/cases.yaml", encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    out = []
    for c in doc.get("cases") or []:
        def walk(x):
            if isinstance(x, list):
                for i in x:
                    yield from walk(i)
            else:
                yield x
        if any(isinstance(v, str) and v.lower() in ("inf", "-inf", "nan")
               for v in walk(c.get("value_range"))):
            out.append(c.get("case_id"))
    return out



def load_proto(op_dir):
    with open(f"{op_dir}/proto.yaml", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    if not isinstance(doc, dict) or "operator" not in doc:
        raise ValueError("proto.yaml 缺少顶层 `operator:` 键")
    return doc["operator"]


def load_desc(op_dir):
    with open(f"{op_dir}/desc.md", encoding="utf-8") as f:
        return f.read()


# ─────────────────────────── desc.md 解析 ───────────────────────────

def desc_h2(text):
    """返回 [(序号, 标题)]，按出现顺序。"""
    return [(int(m.group(1)), m.group(2).strip())
            for m in re.finditer(r"^## (\d+)\.\s*(.+?)\s*$", text, re.M)]


def desc_h3(text):
    return [m.group(1).strip() for m in re.finditer(r"^### (.+?)\s*$", text, re.M)]


def desc_section(text, title):
    """取出某个 H2/H3 小节正文（到下一个同级或更高级标题为止）。"""
    m = re.search(r"^(#{2,3}) (?:\d+\.\s*)?" + re.escape(title) + r"\s*$", text, re.M)
    if not m:
        return None
    level = len(m.group(1))
    rest = text[m.end():]
    nxt = re.search(r"^#{2," + str(level) + r"} ", rest, re.M)
    return rest[:nxt.start()] if nxt else rest


def parse_support_table(text):
    """解析 §3「支持范围」表 → [(维度/参数, 范围, 备注)]。"""
    body = desc_section(text, "支持范围")
    if body is None:
        return None
    lines = [l.strip() for l in body.split("\n") if l.strip().startswith("|")]
    if len(lines) < 3:
        return []
    out = []
    for l in lines[2:]:
        cells = [c.strip() for c in l.strip().strip("|").split("|")]
        if len(cells) >= 3:
            out.append((cells[0], cells[1], cells[2]))
    return out


def desc_prototype(text):
    """从 §3「算子原型」代码块提取签名文本。"""
    body = desc_section(text, "算子原型")
    if body is None:
        return None
    m = re.search(r"```(?:python)?\n(.*?)```", body, re.S)
    return m.group(1).strip() if m else None


def desc_golden_code(text):
    body = desc_section(text, "标准 Golden 代码")
    if body is None:
        return None
    m = re.search(r"```(?:python)?\n(.*?)```", body, re.S)
    return m.group(1).strip() if m else None


# ─────────────────────────── 派生量 ───────────────────────────

def shapes_of(case):
    """把 input_shape 摊平成 [shape, ...]，兼容 is_list 算子的嵌套写法。"""
    out = []

    def rec(x):
        if isinstance(x, list):
            if x and all(isinstance(i, int) for i in x):
                out.append(x)
            else:
                for i in x:
                    rec(i)
    rec(case["input_shape"])
    return out


def measured_ranges(cases, input_pos=None):
    """从 cases 反推实测覆盖面 —— 用于校验 desc.md「支持范围」备注列自洽。

    input_pos=None 统计全部输入；给定整数则只统计该位置的输入（逐输入归因，
    避免把 `index` 行的声明拿去和全体输入的极值比）。
    """
    dims, numels, ndims, dtypes = [], [], set(), set()
    for c in cases:
        if input_pos is None:
            shs = shapes_of(c)
        else:
            raw = c["input_shape"]
            shs = [raw[input_pos]] if input_pos < len(raw) else []
            shs = [s for s in shs if isinstance(s, list) and all(isinstance(i, int) for i in s)]
        for sh in shs:
            dims += sh
            ndims.add(len(sh))
            numels.append(math.prod(sh) if sh else 1)
        dl = c["dtype"] if isinstance(c["dtype"], list) else [c["dtype"]]
        if input_pos is not None:
            dl = [dl[input_pos]] if input_pos < len(dl) else []
        for d in dl:
            if d is not None:
                dtypes.add(str(d))
    return {
        "ndim": sorted(ndims),
        "dim_min": min(dims) if dims else None,
        "dim_max": max(dims) if dims else None,
        "numel_min": min(numels) if numels else None,
        "numel_max": max(numels) if numels else None,
        "dtypes": sorted(dtypes),
    }


def row_input_pos(row_name, proto):
    """把「支持范围」行名归因到某个 proto 输入位置。

    返回 (pos, qualified)：pos 为输入下标或 None；qualified=True 表示行名带
    限定语（如 `i ≠ dim`、`除 dim 外`），此时不做机械比对以免误判。

    L2/L3 惯用符号维度名做行名，真正的输入名往往出现在括注里，
    形如 ``​`D_i`（`x` 各维大小）``。故扫描**所有**反引号标识符，
    取第一个能对上 proto 输入名的，而不是只看第一个标识符。
    """
    name = str(row_name)
    if re.search(r"[≠≥≤]|除|不含|除外|其余", name):
        return (None, True)
    idents = re.findall(r"`([A-Za-z_]\w*)", name)
    names = [inp.get("name") for inp in (proto.get("inputs") or [])]
    for ident in idents:
        if ident in names:
            return (names.index(ident), False)
    return (None, False)


# ══════════════════ L2/L3 多输入专用 ══════════════════

# 索引类输入的命名特征（如 gather.index / scatter.indices /
# unsorted_segment_sum.segment_ids / moe_finalize_routing.expanded_src_to_dst_row）
INDEX_NAME = re.compile(
    r"ind(ex|ices)|segment_ids?|src_to_dst|row_idx|expert_idx|_ids?$|^ids?$|offsets?$",
    re.I)

# 「按角色定值域」中的权重/缩放类输入（bias 值域通常约为主体输入的 1/10）
SCALE_NAME = re.compile(r"bias|scale|offset|zero_point|gamma|beta|weight_scale", re.I)


def index_input_positions(proto):
    """返回被判定为「索引类」的输入下标列表。"""
    out = []
    for i, inp in enumerate(proto.get("inputs") or []):
        nm = str(inp.get("name") or "")
        dts = [str(d) for d in (inp.get("dtype") or [])]
        # 名字像索引，且 dtype 全为整型 —— 两个条件都满足才算，避免误伤 int8 量化输入
        if INDEX_NAME.search(nm) and dts and all(d in INT_DTYPES for d in dts):
            out.append(i)
    return out


def per_input_ranges(case, n_inputs=None):
    """把 case 的 value_range 规整成「逐输入」列表；共享写法则广播。

    返回 list，元素为 [lo, hi] 或 None（该位置可选输入缺省）。
    """
    vr = case.get("value_range")
    n = n_inputs if n_inputs is not None else len(case.get("input_shape") or [])
    if isinstance(vr, list) and vr and all(x is None or isinstance(x, list) for x in vr) \
            and any(isinstance(x, list) for x in vr):
        return list(vr)
    return [vr] * n


def all_dim_sizes(case):
    """该 case 里出现过的所有维度大小（用于校验索引上界是否指向某个真实维）。"""
    out = set()
    for sh in shapes_of(case):
        out |= set(sh)
    return out


def derivable_bounds(case):
    """索引上界的所有合法来源：单维、维的两两乘积、维的前缀积、整数 attr。

    上界可以是多个维的乘积而非单一维（如 MoE 路由类算子的 `E * C - 1`），
    只认单维会把这类合法设计误报成越界。
    """
    dims = sorted(all_dim_sizes(case))
    out = set(dims) | int_attr_values(case)
    for i, a in enumerate(dims):
        for b in dims[i:]:
            out.add(a * b)
    for sh in shapes_of(case):
        acc = 1
        for d in sh:                      # 前缀积：覆盖 (E,C,H) 里 E*C、E*C*H
            acc *= d
            out.add(acc)
    return out



def int_attr_values(case):
    """case 的 attrs 里所有整数取值（num_segments 这类会决定索引上界）。"""
    out = set()
    for v in (case.get("attrs") or {}).values():
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            out.add(v)
        elif isinstance(v, list):
            out |= {x for x in v if isinstance(x, int) and not isinstance(x, bool)}
    return out


def coupling_invariants(cases, proto):
    """挖出「在全部用例都成立」的跨输入维度相等关系。

    返回 [(i, ia, j, ib, 名字i, 名字j)]，表示 input[i].shape[ia] == input[j].shape[ib]
    在 20 例中恒成立。**注意**：恒成立 ≠ 语义必然 —— 若 20 例恰好都取
    C_out == C_in，统计就会额外推出 `x[1]==filter[0]` 这种假耦合。
    故本函数只用于「提示应在 desc.md 写明」，不作为 FAIL 依据。
    """
    names = [str(i.get("name") or f"in{k}")
             for k, i in enumerate(proto.get("inputs") or [])]

    def norm(c):
        return [s if (isinstance(s, list) and all(isinstance(x, int) for x in s)) else None
                for s in (c.get("input_shape") or [])]

    if not cases:
        return []
    base = norm(cases[0])
    cand = set()
    for i, si in enumerate(base):
        if not si:
            continue
        for j in range(i + 1, len(base)):
            sj = base[j]
            if not sj:
                continue
            for ia, va in enumerate(si):
                for ib, vb in enumerate(sj):
                    if va == vb and va > 1:
                        cand.add((i, ia, j, ib))
    for c in cases[1:]:
        s = norm(c)
        cand = {(i, ia, j, ib) for (i, ia, j, ib) in cand
                if i < len(s) and j < len(s) and s[i] and s[j]
                and ia < len(s[i]) and ib < len(s[j]) and s[i][ia] == s[j][ib]}
    nm = lambda k: names[k] if k < len(names) else f"in{k}"
    return [(i, ia, j, ib, nm(i), nm(j)) for (i, ia, j, ib) in sorted(cand)]


def desc_constraint_lines(text):
    """取出 desc.md 里承载跨输入约束的文字：§3「规则与约束」+ 支持范围表后的「约束：」行。

    跨输入约束按惯例写在「规则与约束」与「支持范围」两处，
    多输入算子还应在支持范围表后有独立的 `约束：` 行。
    """
    out = []
    body = desc_section(text, "规则与约束")
    if body:
        out.append(body)
    sup = desc_section(text, "支持范围")
    if sup:
        out.append(sup)
    return "\n".join(out)



def attr_values(cases):
    """收集每个 attr 在 20 例中的取值集合。"""
    out = {}
    for c in cases:
        for k, v in (c.get("attrs") or {}).items():
            out.setdefault(k, []).append(v)
    return out


def note_core(note):
    """去掉 ` | baseline_kernels: ...` 尾巴，只留设计维度 slug。"""
    return str(note).split("|")[0].strip()


def snake(name):
    """PascalCase → snake_case（proto.operator.name → golden 函数名）。

    注意：含数字的名字本质歧义（Conv2D 既可 conv_2d 也可 conv2_d），
    故比对时应用 squash() 归一后再判等，不要直接字符串相等。
    """
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower()


def squash(name):
    """去掉下划线并小写，用于消除 conv_2d / conv2_d 这类分词歧义。"""
    return str(name).replace("_", "").lower()


def parse_bound(text):
    """解析「支持范围」里的数值上下界写法 → float。

    支持：普通数字、`2^23` 幂次、`64M` / `2M` / `1K`（M=2^20, K=2^10）。
    解析不出来返回 None（调用方据此降级为 WARN，不误判 FAIL）。
    """
    t = str(text).strip().replace(",", "")
    m = re.fullmatch(r"(\d+)\s*\^\s*(\d+)", t)
    if m:
        return float(int(m.group(1)) ** int(m.group(2)))
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*([MKGmkg])", t)
    if m:
        mul = {"k": 1 << 10, "m": 1 << 20, "g": 1 << 30}[m.group(2).lower()]
        return float(m.group(1)) * mul
    m = re.fullmatch(r"-?\d+(?:\.\d+)?", t)
    if m:
        return float(t)
    return None


def parse_range_cell(cell):
    """从「范围」/「备注」单元格里抽出 (lo, hi)；抽不出返回 (None, None)。"""
    # 先剥掉 ~ 两侧的 token，token 可以是 2^23 / 64M / 1048576
    m = re.search(r"([\w^.]+)\s*[~—－-]\s*([\w^.]+)", str(cell))
    if not m:
        return (None, None)
    return (parse_bound(m.group(1)), parse_bound(m.group(2)))


def parse_ndim_claim(note):
    """解析备注里的维度覆盖声明 → set[int]。

    支持 `实测 1D ~ 5D`（区间展开）与 `实测 1D / 2D / 3D`（枚举）两种写法。
    """
    toks = re.findall(r"(\d+)\s*D", str(note))
    if not toks:
        return set()
    nums = [int(t) for t in toks]
    if len(nums) == 2 and re.search(r"(\d+)\s*D\s*[~—－-]\s*(\d+)\s*D", str(note)):
        return set(range(min(nums), max(nums) + 1))
    return set(nums)



def human_numel(n):
    """67108864 → '64M'（M = 2^20，与 note 的元素数口径一致）。"""
    if n >= 1 << 20:
        return f"{round(n / (1 << 20))}M"
    if n >= 1 << 10:
        return f"{round(n / (1 << 10))}K"
    return str(n)


def eprint(*a):
    print(*a, file=sys.stderr)
