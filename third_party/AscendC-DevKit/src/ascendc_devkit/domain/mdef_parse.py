"""m.def schema 解析原语（cann-bench op_plugin 注册签名的纯字符串解析）。

集中「从 ``m.def("op(...)")`` 提取信息」的唯一通路（§2.5），供：
- ``codegen`` regbase fallback —— 从 op_plugin 源推导算子真实 C++ 注册名，构造
  ``callable_target.symbol``（注册名可能与 op_name 不同，如避 torch 内置名冲突的
  ``npu_<name>``）；
- ``cannbench_adapt`` P10 —— 把 m.def schema 参数名对齐到 proto（关键字调用正确）。

无业务/op_spec 依赖；依赖 op_spec 的对齐逻辑（``align_schema_params``）留在调用方。
"""

from __future__ import annotations

import re

# `m.def(` 头（吃掉到首个字符串字面量前的空白）。schema 本体可由 C++ 相邻字符串字面量
# 拼接而成（长签名换行书写的惯用法，语义等价单串），故不在此正则内锚定收尾 `)`。
_MDEF_HEAD_RE = re.compile(r'm\.def\(\s*')
# 单个 C++ 字符串字面量（支持转义），group(1) 为去引号内容。
_STRING_LITERAL_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
_INTER_LITERAL_WS_RE = re.compile(r'\s*')
# 单个 schema 参数：<type tokens> <name>(=<default>)?。type 可含 const/&/Tensor[]/Tensor?/
# alias 标注(如 Tensor(a!))/int/float（`?` = optional tensor，如 `Tensor? x=None`）；
# name 是末尾标识符（= 之前）。
_PARAM_RE = re.compile(r'(?:const\s+)?[\w\[\]&?\s()!]+?\s+(\w+)\s*(?:=[^,)]+)?')


def _find_mdef_schema(source: str) -> tuple[str, int, int] | None:
    """定位首个 ``m.def(...)`` 的 schema，返回 ``(schema, start, end)``。

    ``schema`` 为拼接后的去引号逻辑串；``source[start:end]`` 覆盖构成它的全部相邻字符串
    字面量（含引号与串间空白），供 :func:`rename_mdef_schema` 原位改写。

    支持 C++ 相邻字符串字面量拼接——长签名（多形参）常换行写成
    ``m.def("op(" "Tensor x, ..." ") -> ...")``，语义等价单串。旧实现只认单个字面量
    直接跟 ``)``，对拼接形式漏判，导致 torch_op 注册被误判为「缺失」。

    无 ``m.def`` / 头后无字符串字面量时返回 ``None``。只取首个 ``m.def``。
    """
    head = _MDEF_HEAD_RE.search(source)
    if not head:
        return None
    pos = head.end()
    parts: list[str] = []
    span_start: int | None = None
    span_end = pos
    while True:
        lit = _STRING_LITERAL_RE.match(source, pos)
        if not lit:
            break
        if span_start is None:
            span_start = lit.start()
        span_end = lit.end()
        parts.append(lit.group(1))
        pos = _INTER_LITERAL_WS_RE.match(source, lit.end()).end()
    if span_start is None:
        return None
    return "".join(parts), span_start, span_end


def _param_list_span(sig: str) -> tuple[int, int] | None:
    """返回 schema 中参数列表 ``(`` 与其**配对** ``)`` 的索引 ``(lp, rp)``。

    用配对括号定位，而非 ``rfind(")")``——tuple 返回类型
    ``-> (Tensor, Tensor)`` 的收尾 ``)`` 会被 ``rfind`` 误当成参数列表结束，
    污染最后一个参数。无 ``(`` / 括号不配对时返回 ``None``。
    """
    lp = sig.find("(")
    if lp < 0:
        return None
    depth = 0
    for i in range(lp, len(sig)):
        if sig[i] == "(":
            depth += 1
        elif sig[i] == ")":
            depth -= 1
            if depth == 0:
                return lp, i
    return None


def _split_top_level(body: str) -> list[str]:
    """按逗号拆分参数段，但不在嵌套 ``<>``/``[]``/``()`` 内拆。"""
    out: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in body:
        if ch in "<[(":
            depth += 1
        elif ch in ">])":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur))
    return out


def _matching_rparen(s: str, lp: int) -> int:
    """返回与 ``s[lp] == '('`` 配对的 ``)`` 索引（括号深度匹配）；不配对返回 -1。

    必须用深度匹配而非 ``rfind(')')``：多输出 schema 形如
    ``op(Tensor x) -> (Tensor y, Tensor scale)`` —— 最后一个 ``)`` 属于**返回类型
    元组**，不是参数体右界。``rfind`` 会把返回类型括进参数体，污染参数解析
    （run 20260803-143122-30031b dynamic_quant 根因）。
    """
    depth = 0
    for i in range(lp, len(s)):
        if s[i] == "(":
            depth += 1
        elif s[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _extract_schema_sig(source: str) -> str | None:
    """提取 schema sig 字符串。

    - plugin source（含 ``m.def("sig")``）→ 提取 ``m.def`` 内的 sig；
    - 裸 schema 字符串（proto.yaml ``operator.schema``，如 ``gather(Tensor x, int dim=0)
      -> Tensor y``）→ source 本身。两者同构，复用同一 parser，无需 agent 重新表达。
    无 m.def 且无括号 → ``None``。
    """
    found = _find_mdef_schema(source)
    if found:
        return found[0]
    s = source.strip()
    if "(" in s and ")" in s:
        return s
    return None


def parse_mdef_op_name(source: str) -> str | None:
    """提取首个 ``m.def("<op_name>(...")`` 的算子注册名（``(`` 前的末尾标识符）。

    如 ``'m.def("npu_exp(Tensor x, ...) -> Tensor")'`` → ``'npu_exp'``。
    注册名可能与 op_name 不同（codegen 为避 torch 内置名冲突常注册成 ``npu_<name>``），
    故构造 ``callable_target.symbol`` 必须取此处真值，而非 op_name 盲拼。

    无 m.def / 无 ``(`` / 名为空时返回 ``None``。只取首个 m.def（一个 plugin 只注册一个算子）。
    """
    found = _find_mdef_schema(source)
    if not found:
        return None
    sig = found[0]
    lp = sig.find("(")
    if lp <= 0:
        return None
    tokens = sig[:lp].strip().split()
    return tokens[-1] if tokens else None


def parse_mdef_params(source: str) -> list[str]:
    """提取参数名序列（按位置有序）——接受 plugin source（``m.def("op(...)")``）或裸
    proto.yaml schema 字符串（如 ``gather(Tensor x, int dim=0) -> Tensor y``）。

    如 ``"swi_glu(Tensor x, int dim=-1)"`` → ``["x","dim"]``。无 schema / 无参数时返回
    ``[]``。只解析首个 schema（一个 plugin 只注册一个算子）。
    """
    sig = _extract_schema_sig(source)
    if sig is None:
        return []
    lp = sig.find("(")
    rp = _matching_rparen(sig, lp)
    if lp < 0 or rp < 0 or rp <= lp:
        return []
    body = sig[lp + 1:rp].strip()
    if not body:
        return []
    names: list[str] = []
    for part in _split_top_level(body):
        part = part.strip()
        if not part:
            continue
        pm = _PARAM_RE.fullmatch(part)
        names.append(pm.group(1) if pm else part)
    return names


def _replace_param_name(part: str, old: str, new: str) -> str:
    """把 ``"Tensor x"`` / ``"float p=2.0"`` 中的形参名 old 换成 new，保留 type/default。

    在未 strip 的 head 上用 ``\\b{old}\\b\\s*$`` 匹配末尾标识符（索引与切点一致），
    避免 strip/未 strip 索引错位。
    """
    eq = part.find("=")
    head = part[:eq] if eq >= 0 else part
    tail = part[eq:] if eq >= 0 else ""
    nm = re.search(rf"\b{re.escape(old)}\b\s*$", head)
    if not nm:
        return part
    return head[:nm.start()] + new + head[nm.end():] + tail


def rename_mdef_schema(source: str, old_names: list[str],
                       new_names: list[str]) -> str:
    """把 source 中首个 m.def schema 参数名按位置从 old_names 改为 new_names。

    数量不一致时不改动（返回原 source）——位置对齐的前提是参数数相同，错位 rename 会把
    名绑到错误参数（多同类型参数场景），不如不改 + 上游记 error 暴露。
    """
    if len(old_names) != len(new_names) or not old_names:
        return source
    found = _find_mdef_schema(source)
    if not found:
        return source
    sig, span_start, span_end = found
    span = _param_list_span(sig)
    if span is None:
        return source
    lp, rp = span
    body = sig[lp + 1:rp]
    parts = _split_top_level(body)
    new_parts: list[str] = []
    for i, part in enumerate(parts):
        if i < len(old_names) and old_names[i] != new_names[i]:
            new_parts.append(_replace_param_name(part, old_names[i], new_names[i]))
        else:
            new_parts.append(part)
    new_sig = sig[:lp + 1] + ",".join(new_parts) + sig[rp:]
    # 拼接形式的多字面量整段替换为单个规范化字面量（schema 内无引号/反斜杠）。
    return source[:span_start] + '"' + new_sig + '"' + source[span_end:]


# —— schema 参数序校验（加载期兜底，§1.3）——————————————————————
#
# cann-bench eval harness 按 ``func(*tensor_inputs, **attrs)`` 调用部署算子：所有
# Tensor 输入作位参、scalar attrs 作关键字。故 ``m.def`` schema 必须「所有 Tensor 在前、
# scalar attrs 在后」。若 codegen 镜像了 torch 内置算子规范签名（如
# ``gather(Tensor input, int dim, Tensor index)`` —— dim 夹在两 Tensor 中间），位参
# binding 会把 index Tensor 强转 ``int dim`` → pybind cast 失败、kernel 从未执行
# （run 20260727-144633-2a1db8 gather 全 0 分根因）。
#
# 顺序正确性须在 producer（codegen）保证（重排需同步改 C++ 实现函数签名，确定性后处理
# 层无法兜）—— 由 codegen skill 契约 + s4-coding C.{plugin} 自检引导。本函数是**加载期
# 校验兜底**：cannbench_adapt 在 P10 rename 后调用，违例 → 报 last_error + loopback
# codegen（确定性诊断），不静默（§1.3 / §3.4）。


def _split_param_type_name(part: str) -> tuple[str, str]:
    """从单个 schema 参数段拆出 ``(type_token, name)``。

    ``"Tensor x"`` → ``("Tensor", "x")``；``"int dim=-1"`` → ``("int", "dim")``；
    ``"const Tensor& x"`` → ``("const Tensor&", "x")``；``"Tensor[] xs"`` →
    ``("Tensor[]", "xs")``。去掉 ``=default`` 后取声明部末尾标识符为 name，其余为 type。
    """
    eq = part.find("=")
    decl = part[:eq] if eq >= 0 else part
    m = re.search(r"(\w+)\s*$", decl)
    if not m:
        return part.strip(), part.strip()
    return decl[: m.start()].strip(), m.group(1)


def _is_tensor_type(type_token: str) -> bool:
    """``Tensor`` / ``Tensor[]`` / ``const Tensor&`` / ``Tensor?``（optional）→ True；
    ``int`` / ``int64`` / ``float`` / ``bool`` / ``str`` 等 scalar → False。"""
    return "tensor" in type_token.lower()


def parse_mdef_param_types(source: str) -> list[tuple[str, str]]:
    """提取 ``(type_token, name)`` 序（按位置有序）——接受 plugin source（``m.def``）或裸
    proto.yaml schema 字符串。

    如 ``"gather(Tensor input, int dim, Tensor index)"`` →
    ``[("Tensor","input"), ("int","dim"), ("Tensor","index")]``。无 schema / 无参数 → ``[]``。
    """
    sig = _extract_schema_sig(source)
    if sig is None:
        return []
    lp = sig.find("(")
    rp = _matching_rparen(sig, lp)
    if lp < 0 or rp < 0 or rp <= lp:
        return []
    body = sig[lp + 1 : rp].strip()
    if not body:
        return []
    out: list[tuple[str, str]] = []
    for part in _split_top_level(body):
        part = part.strip()
        if not part:
            continue
        out.append(_split_param_type_name(part))
    return out


def validate_schema_param_order(source: str) -> tuple[bool, str | None]:
    """校验 ``m.def`` schema 参数序：所有 Tensor 连续在前、scalar attrs 在后。

    纯结构约束（不依赖 proto/manifest）：一旦出现 scalar 参数，其后不得再有 Tensor。
    违例（如 ``gather(Tensor input, int dim, Tensor index)``）→ harness 位参 binding
    把 Tensor 强转 scalar → pybind cast 失败、kernel 从未执行。

    返回 ``(ok, detail)``：``ok=True`` 序合法（含无参数/无 m.def 的平凡情形）；
    ``ok=False`` 时 ``detail`` 为确定性诊断（实际 type 序 + 违例位置 + 约束 + 修复方向），
    供 cannbench_adapt 报 ``last_error`` 并 loopback codegen（§2.9 ② 明确反馈消费渠道）。
    """
    params = parse_mdef_param_types(source)
    if not params:
        return True, None
    kinds = ["Tensor" if _is_tensor_type(t) else "scalar" for t, _ in params]
    seen_scalar = False
    violation_idx: int | None = None
    for i, kind in enumerate(kinds):
        if kind == "scalar":
            seen_scalar = True
        elif kind == "Tensor" and seen_scalar:
            violation_idx = i
            break
    if violation_idx is None:
        return True, None
    detail = (
        "m.def schema 参数序违例：scalar attr 夹在 Tensor 输入中间。"
        f" 实际 type 序={kinds}；位置 {violation_idx}（0-indexed）的 Tensor 出现在"
        " scalar 之后。cann-bench eval harness 按 func(*inputs, **attrs) 调用，要求"
        " 所有 Tensor 输入在前、scalar attrs 在后；否则位参 binding 把 Tensor 强转"
        " scalar → pybind cast 失败、kernel 从未执行。需重排 m.def schema 与对应"
        " C++ 实现函数（<op>_meta/<op>_npu）签名为：Tensor... 在前、scalar... 在后。"
    )
    return False, detail


def validate_schema_against_proto(
    plugin_source: str, proto_schema: str | None
) -> tuple[bool, str | None]:
    """比对 plugin ``m.def`` schema vs proto.yaml schema 的 type+name+order 全等。

    proto.yaml ``operator.schema`` 是 plugin 接口 + cann-bench eval harness 调用契约的
    **共同权威**。codegen 生成的 ``m.def`` 必须 == proto schema（type+name+order 全等）。任何
    偏离（顺序错 scalar 夹 Tensor 中间、名字错 ``input`` vs proto 的 ``x``、type 错）都是接口
    对齐 bug —— proto.yaml 才是权威，不是 codegen 套的 torch 标准签名，也不是 codegen_manifest。

    返回 ``(ok, detail)``：全等 → ``(True, None)``；偏离 → ``(False, 确定性诊断)``。
    ``proto_schema`` 缺失/不可 parse → 退化为 :func:`validate_schema_param_order` 结构校验
    （无 proto 时的兜底：只抓 scalar 夹 Tensor 中间，抓不了名字错）。
    """
    proto_params = parse_mdef_param_types(proto_schema) if proto_schema else []
    if not proto_params:
        return validate_schema_param_order(plugin_source)
    plugin_params = parse_mdef_param_types(plugin_source)
    if plugin_params == proto_params:
        return True, None
    proto_repr = ", ".join(f"{t} {n}" for t, n in proto_params)
    plugin_repr = ", ".join(f"{t} {n}" for t, n in plugin_params)
    detail = (
        "plugin m.def schema 偏离 proto.yaml 权威 schema（type+name+order 必须全等）。"
        f" proto.yaml operator.schema: [{proto_repr}]；plugin m.def: [{plugin_repr}]。"
        " proto.yaml 是 plugin 接口 + cann-bench eval harness 调用契约的共同权威；需令"
        " plugin m.def 与对应 C++ 实现函数签名（<op>_meta/<op>_npu）完全对齐 proto.yaml schema"
        "（禁止套 torch 标准签名）。"
    )
    return False, detail


# ——————————————————————————————————————————————————————————————————————————
# 返回签名对质原语（方案 A）：m.def 声明返回 ↔ C++ 实现返回类型的一致性校验。
#
# 只做**高置信**判定，任一侧解析不确定 → 返回 None（fail-open，运行期 smoke 的
# checkSchema 才是兜底）。不拦合法形态（`-> Tensor`+torch::Tensor、`-> Tensor[]`+
# std::vector、`-> (Tensor, Tensor?)`+std::tuple<..., optional<...>> 等）。
# ——————————————————————————————————————————————————————————————————————————

# ``m.impl("op", fn)`` —— fn 是实际注册的实现函数（meta/npu），其返回类型即真实契约。
_IMPL_RE = re.compile(r'm\.impl\(\s*"([^"]+)"\s*,\s*([A-Za-z_]\w*)\s*\)')


def _normalize_return_type(t: str) -> str | None:
    """归一单个 schema 返回类型 token → 保留 Tensor-family 的 ?/[] 标记，其余原样。

    ``" Tensor? "`` → ``"Tensor?"``；``"Tensor[]"`` → ``"Tensor[]"``；``"int"`` →
    ``"int"``。无法归一（空/脏 token）→ ``None``。
    """
    t = t.strip()
    if not t:
        return None
    # alias 标注（Tensor(a) / Tensor(a!)）只影响输入别名，返回侧剥掉括号标注。
    if t.startswith("Tensor"):
        core = re.match(r'Tensor(\??)((\[\])?)(\??)', t)
        if core:
            return "Tensor" + (core.group(1) or core.group(4) or "") + (core.group(2) or "")
        return "Tensor"
    return t


def _split_return_tuple(ret: str) -> list[str] | None:
    """切分 ``(A, B, ...)`` 返回元组为逐项列表；``(A)`` 单元素按单返回处理。

    用配对括号定位（复用 ``_split_top_level`` 的深度逻辑），无法配对 → ``None``。
    """
    if not ret.startswith("("):
        return None
    depth = 0
    end = -1
    for i, ch in enumerate(ret):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end < 0:
        return None
    inner = ret[1:end].strip()
    if not inner:
        return []  # `-> ()` → 无返回
    parts = _split_top_level(inner)
    return [p.strip() for p in parts if p.strip()]


def parse_mdef_return_signature(source: str) -> list[str] | None:
    """提取首个 ``m.def("op(...) -> <RET>")`` 的**返回签名**（规范化逐项列表）。

    - ``-> Tensor`` → ``["Tensor"]``；``-> Tensor?`` → ``["Tensor?"]``；
    - ``-> Tensor[]`` → ``["Tensor[]"]``；
    - ``-> (Tensor, Tensor?)`` → ``["Tensor", "Tensor?"]``；``-> (Tensor)`` → ``["Tensor"]``；
    - ``-> ()`` / ``-> None`` → ``[]``；
    - 无 ``->`` / 无法解析 → ``None``（fail-open）。

    长度即返回 arity；首项含 ``[]`` 表示变长单返回（``Tensor[]``）。
    """
    found = _find_mdef_schema(source)
    if not found:
        return None
    sig = found[0]
    span = _param_list_span(sig)
    if span is None:
        return None
    lp, rp = span
    rest = sig[rp + 1:].strip()
    if not rest.startswith("->"):
        return None
    ret = rest[2:].strip()
    if not ret:
        return None
    if ret in ("None", "()"):
        return []
    parts = _split_return_tuple(ret)
    if parts is not None:
        norm = [_normalize_return_type(p) for p in parts]
        return [p for p in norm if p is not None] if norm else []
    single = _normalize_return_type(ret)
    return [single] if single is not None else None


def _classify_impl_return(ret: str) -> str | None:
    """把 C++ 实现返回类型分类为可比较 token。

    - ``std::tuple<A, B, ...>`` / ``std::pair<...>`` → ``"tuple<N>"``；
    - ``std::vector<...>`` → ``"vector"``（→ schema ``Tensor[]``，1 个变长返回）；
    - ``at::Tensor``/``torch::Tensor``/``c10::Tensor``/裸 ``Tensor`` → ``"tensor"``；
    - ``c10::optional<...>``/``std::optional<...>`` → ``"optional"``；
    - ``void`` → ``"void"``；无法分类 → ``None``（fail-open）。
    """
    ret = ret.strip()
    if not ret:
        return None
    if ret == "void":
        return "void"
    m = re.match(r'(?:std::tuple|std::pair)\s*<(.*)>\s*', ret, re.DOTALL)
    if m:
        inner = m.group(1).strip()
        arity = len(_split_top_level(inner)) if inner else 0
        return f"tuple{arity}"
    if re.match(r'std::vector\s*<', ret):
        return "vector"
    if re.match(r'(?:c10::optional|std::optional)\s*<', ret):
        return "optional"
    if re.match(r'(?:const\s+)?(?:at::|torch::|c10::)?Tensor(?:\s*&)?$', ret):
        return "tensor"
    return None


def _find_impl_return_kind(source: str, fn_name: str) -> str | None:
    """从 ``static <RET> <fn_name>(`` 提取实现函数返回类型并分类；找不到 → None。

    返回类型含嵌套模板（``std::tuple<at::Tensor, std::optional<at::Tensor>>``），
    用非贪婪匹配到函数名为止。只认 ``static`` 声明（codegen 产物惯例）。
    """
    m = re.search(
        r'\bstatic\s+([\w:<>,\s]+?)\s+' + re.escape(fn_name) + r'\s*\(',
        source, re.DOTALL)
    if not m:
        return None
    return _classify_impl_return(m.group(1))


def plugin_impl_return_kinds(source: str) -> list[str] | None:
    """返回所有 ``m.impl`` 注册实现函数的返回类型分类列表；无 m.impl/无法分类 → None。

    unique 20260808 根因即此可检出：``m.def("... -> (Tensor, Tensor?)")``（arity 2）
    但 ``unique_npu`` 返回 ``std::vector<torch::Tensor>`` → 分类 ``["vector"]``，与
    声明 arity 2 矛盾（vector → schema ``Tensor[]`` 1 变长，checkSchema 运行时拒注册）。
    """
    impls = _IMPL_RE.findall(source)
    if not impls:
        return None
    kinds: list[str] = []
    for _, fn_name in impls:
        kind = _find_impl_return_kind(source, fn_name)
        if kind is None:
            continue
        kinds.append(kind)
    return kinds if kinds else None
