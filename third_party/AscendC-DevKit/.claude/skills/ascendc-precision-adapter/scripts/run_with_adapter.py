#!/usr/bin/env python3
"""run_with_adapter.py — 用户自定义测试/编译命令的适配层(standalone)。

把用户的 ``build_command`` / ``test_command`` 和任意格式的测试产出,适配成
precision_debug 闭环需要的标准 ``result.json``(``case_details[]`` 结构),让
``build-failed-case-queue.py`` 能直接消费。无 ``ascendc_devkit`` 依赖。

三种 result 适配模式(由 ``adapter_config.yaml`` 的 ``result_adapter.mode`` 选):
  - ``builtin_preset``:内置预设解析器(py_numpy / atk / ttk),把常见格式转标准结构
  - ``mapping``:按 ``result_adapter.mapping`` 的 JSONPath-ish 字段映射抽取
  - ``hook``:调用用户提供的 ``hook_script``,任意格式都能转(万能兜底)

标准 result.json 契约(喂给 build-failed-case-queue.py)::

    {"case_details": [
        {"case_id": "...", "case": "...", "input_shapes": [[..]],
         "output_results": [{"index":0,"dtype":"float32","diff":0.01,
                             "max_diff_location": {...}}],
         "accuracy": {"passed": false, "max_diff": 0.01}, "error": null}
    ]}

子命令:
  build      —— 执行 build_command(编译/部署算子)
  run-test   —— 执行 test_command(支持 {case_id}/{iter}/{label} 占位符),
                 产出 raw_output → adapt → 写标准 result.json
  adapt      —— 只做 raw_output → result.json 转换(单独验证适配层)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any

try:  # PyYAML 可选;缺失时只支持 JSON 配置
    import yaml  # type: ignore
except ImportError:
    yaml = None


# ── 配置加载 ──────────────────────────────────────────────────────────────────
def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if path.endswith((".yaml", ".yml")):
        if yaml is None:
            sys.exit("ERROR: 配置是 YAML 但未装 PyYAML(pip install pyyaml),或改用 .json")
        return yaml.safe_load(text)
    return json.loads(text)


def _cfg(config: dict, *keys: str, default: Any = None) -> Any:
    cur: Any = config
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur if cur is not None else default


# ── 标准结构构造 ──────────────────────────────────────────────────────────────
def _make_case_detail(case_id: str, *, case: str = "", shape: Any = None,
                      dtype: str = "", diff: float | None = None,
                      passed: bool | None = None, error: str | None = None) -> dict:
    """构造一个标准 case_detail。diff/passed 任一非空即视为有用例结果。"""
    out_results: list[dict] = []
    if diff is not None or dtype:
        entry: dict = {"index": 0}
        if dtype:
            entry["dtype"] = dtype
        if diff is not None:
            entry["diff"] = float(diff)
        out_results.append(entry)
    accuracy = None
    if passed is not None or diff is not None:
        accuracy = {"passed": bool(passed) if passed is not None else (diff == 0),
                    **({"max_diff": float(diff)} if diff is not None else {})}
    return {
        "case_id": case_id,
        "case": case or case_id,
        "input_shapes": [shape] if shape is not None else [],
        "output_results": out_results,
        "accuracy": accuracy,
        "error": error,
    }


def _finalize(case_details: list[dict]) -> dict:
    """统一兜底:无 accuracy 且无 error 的条目视为失败(error 字段缺失会让
    build-failed-case-queue.py 漏判,这里显式标 error 防漏)。"""
    for cd in case_details:
        acc = cd.get("accuracy")
        if (acc is None or acc.get("passed") is None) and not cd.get("error"):
            cd["error"] = "adapter: indeterminate(无 passed/diff/error)"
    return {"case_details": case_details}


# ── 适配模式 1:builtin_preset ─────────────────────────────────────────────────
def _parse_py_numpy(raw: Any) -> list[dict]:
    """预设:纯 py 脚本(numpy 比对)常见产出。

    契约(任一字段名变体)::
        {"cases": [{"name"|"id", "ok"|"passed", "max_abs_err"|"diff",
                    "shape", "dtype", "error"}]}
    """
    cases = raw.get("cases") or raw.get("results") or []
    if not isinstance(cases, list):
        raise ValueError("py_numpy 预设:顶层缺 cases/results 列表")
    out = []
    for c in cases:
        cid = c.get("name") or c.get("id") or c.get("case_id")
        if cid is None:
            raise ValueError("py_numpy 预设:用例缺 name/id 字段")
        out.append(_make_case_detail(
            str(cid), case=c.get("case", ""),
            shape=c.get("shape"), dtype=c.get("dtype", ""),
            diff=c.get("max_abs_err", c.get("diff")),
            passed=c.get("ok", c.get("passed")),
            error=c.get("error")))
    return out


def _parse_atk(raw: Any) -> list[dict]:
    """预设:ATK(ApiToolkits)report 常见结构。ATK 各版本字段略有差异,
    解析失败请改用 mapping 或 hook。"""
    # ATK 常见:{results:[{case_name, pass, max_abs_error, ...}]} 或 {test_cases:[...]}
    cases = (raw.get("results") or raw.get("test_cases")
             or raw.get("case_results") or [])
    if not isinstance(cases, list):
        raise ValueError("atk 预设:未识别的 ATK 结构(改用 mapping/hook)")
    out = []
    for c in cases:
        cid = c.get("case_name") or c.get("name") or c.get("case_id")
        if cid is None:
            continue
        out.append(_make_case_detail(
            str(cid), case=c.get("case", cid),
            shape=c.get("input_shape") or c.get("shape"),
            dtype=c.get("dtype", ""),
            diff=c.get("max_abs_error", c.get("max_diff", c.get("diff"))),
            passed=c.get("pass", c.get("passed", c.get("success"))),
            error=c.get("error_msg") or c.get("error")))
    return out


def _parse_ttk(raw: Any) -> list[dict]:
    """预设:TTK(TBEToolkits)输出。TTK 常以行文本+JSON 混合呈现,此处期望
    已抽成 JSON:{cases:[{case, expect_ok, max_diff,...}]}。复杂日志请用 hook。"""
    cases = raw.get("cases") or raw.get("items") or []
    if not isinstance(cases, list):
        raise ValueError("ttk 预设:未识别结构(改用 mapping/hook)")
    out = []
    for c in cases:
        cid = c.get("case") or c.get("name") or c.get("id")
        if cid is None:
            continue
        out.append(_make_case_detail(
            str(cid), case=str(cid),
            shape=c.get("shape"), dtype=c.get("dtype", ""),
            diff=c.get("max_diff", c.get("diff")),
            passed=c.get("expect_ok", c.get("passed")),
            error=c.get("error")))
    return out


_PRESETS = {"py_numpy": _parse_py_numpy, "atk": _parse_atk, "ttk": _parse_ttk}


# ── 适配模式 2:mapping(迷你 JSONPath)─────────────────────────────────────────
def _query(data: Any, expr: str) -> Any:
    """迷你 JSONPath:支持 ``$.a.b`` 与 ``$.list[*].field`` 两类。复杂路径用 hook。"""
    if expr.startswith("$."):
        expr = expr[2:]
    elif expr.startswith("$"):
        expr = expr[1:]
    cur = data
    spread = False
    for seg in expr.split("."):
        if not seg:
            continue
        if seg.endswith("[*]"):
            key = seg[:-3]
            if key:
                cur = cur.get(key) if isinstance(cur, dict) else None
            if not isinstance(cur, list):
                return None
            spread = True
            nested = seg[len(seg):]  # remainder after [*] (here always "")
            cur = [c.get(nested) if isinstance(c, dict) else None for c in cur] \
                if nested else cur
        else:
            if spread and isinstance(cur, list):
                cur = [c.get(seg) if isinstance(c, dict) else None for c in cur]
            elif isinstance(cur, dict):
                cur = cur.get(seg)
            else:
                return None
    return cur


def _parse_mapping(raw: Any, mapping: dict) -> list[dict]:
    """按 mapping 把任意结构抽成 case_details[]。

    mapping 键 → 标准字段,值 → JSONPath(指向【用例列表元素的字段】):
        case_id:   "$.cases[*].name"
        passed:    "$.cases[*].ok"
        diff:      "$.cases[*].max_abs_err"
        shape / dtype / error: ...
    """
    # 先定位用例列表:取 case_id 映射的列表根
    cid_expr = mapping.get("case_id", "")
    list_root_expr = cid_expr.split("[*]")[0] if "[*]" in cid_expr else ""
    cases = _query(raw, list_root_expr) if list_root_expr else raw
    if not isinstance(cases, list):
        raise ValueError(f"mapping: 用例列表根 {list_root_expr!r} 不是 list")
    # 每个映射字段取 leaf 名([*] 之后的部分)
    def leaf(expr: str) -> str:
        return expr.split("[*]", 1)[1].lstrip(".").split(".")[0] if "[*]" in expr else expr

    out = []
    for c in cases:
        if not isinstance(c, dict):
            continue
        g = lambda key: c.get(leaf(mapping[key])) if key in mapping else None
        cid = g("case_id")
        if cid is None:
            continue
        out.append(_make_case_detail(
            str(cid), case=str(cid),
            shape=g("shape"), dtype=str(g("dtype") or ""),
            diff=g("diff"), passed=g("passed"), error=g("error")))
    return out


# ── 适配模式 3:hook(用户脚本兜底)──────────────────────────────────────────────
def _parse_hook(raw_path: str, hook_script: str) -> list[dict]:
    """调用用户 hook 脚本:``python3 <hook> <raw_output>`` stdout 须为标准
    {case_details:[...]} 或裸 [...](case 列表)。"""
    proc = subprocess.run(
        [sys.executable, hook_script, raw_path],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise ValueError(f"hook {hook_script} 退出码 {proc.returncode}: {proc.stderr.strip()}")
    payload = json.loads(proc.stdout)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("case_details"), list):
        return payload["case_details"]
    raise ValueError("hook 输出既不是 case 列表也不是 {case_details:[...]}")


# ── 适配总入口 ────────────────────────────────────────────────────────────────
def adapt_raw(raw_path: str, adapter_cfg: dict) -> dict:
    if not os.path.exists(raw_path):
        # 硬错误:harness 没跑起来,产出一个硬错误单条 queue(run_tests 硬错误路径)
        return {"case_details": [_make_case_detail(
            "hard_error", error=f"raw output not found: {raw_path}")]}
    with open(raw_path, encoding="utf-8") as f:
        raw = json.load(f)

    mode = adapter_cfg.get("mode", "builtin_preset")
    if mode == "builtin_preset":
        preset = adapter_cfg.get("preset", "py_numpy")
        parser = _PRESETS.get(preset)
        if parser is None:
            raise ValueError(f"未知 preset {preset!r}(可选: {list(_PRESETS)})")
        cds = parser(raw)
    elif mode == "mapping":
        cds = _parse_mapping(raw, adapter_cfg.get("mapping", {}))
    elif mode == "hook":
        hook = adapter_cfg.get("hook_script")
        if not hook:
            raise ValueError("hook 模式缺 hook_script")
        cds = _parse_hook(raw_path, hook)
    else:
        raise ValueError(f"未知 result_adapter.mode {mode!r}")
    return _finalize(cds)


# ── 命令包装(占位符替换)──────────────────────────────────────────────────────
def _subst(cmd_tpl: str, **vals: Any) -> str:
    out = cmd_tpl
    for k, v in vals.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def _run_shell(cmd: str, log_path: str) -> int:
    """执行命令,stdout+stderr 同步落盘到 log_path,返回退出码。"""
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"$ {cmd}\n")
        f.flush()
        proc = subprocess.run(cmd, shell=True, stdout=f, stderr=subprocess.STDOUT)
    return proc.returncode


# ── 子命令实现 ────────────────────────────────────────────────────────────────
def cmd_build(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    cmd = cfg.get("build_command", "")
    if not cmd:
        sys.exit("ERROR: adapter_config 缺 build_command")
    work = cfg.get("compile_work_dir") or cfg.get("operator_dir") or "."
    log = _cfg(cfg, "paths", "build_log", default="build.log")
    print(f"[adapter] build: {cmd} (cwd={work})", flush=True)
    rc = _run_shell(f"cd {work} && {cmd}", log)
    print(f"[adapter] build rc={rc} log={log}", flush=True)
    return rc


def cmd_run_test(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    adapter = cfg.get("result_adapter", {})
    raw_out = adapter.get("raw_output") or _cfg(cfg, "paths", "raw_output",
                                                default="raw_output.json")
    result_json = adapter.get("result_json") or _cfg(cfg, "paths", "result_json",
                                                    default="result.json")
    run_log = _cfg(cfg, "paths", "run_log", default="run.log")

    # 全量用 test_command,单用例用 test_command_case(支持 {case_id} 占位符)
    if args.case:
        tpl = cfg.get("test_command_case") or (cfg.get("test_command", "") + " --case {case_id}")
        cmd = _subst(tpl, case_id=args.case, iter=args.iter, label=args.label or "verify")
    else:
        cmd = _subst(cfg.get("test_command", ""),
                     iter=args.iter, label=args.label or "regression")
    if not cmd:
        sys.exit("ERROR: adapter_config 缺 test_command")

    work = cfg.get("operator_dir", ".")
    print(f"[adapter] run-test: {cmd} (cwd={work})", flush=True)
    rc = _run_shell(f"cd {work} && {{ {cmd} ; }}", raw_out)
    with open(run_log, "w", encoding="utf-8") as f:
        f.write(f"$ {cmd}\nrc={rc}\nraw_output={raw_out}\n")
    print(f"[adapter] run-test rc={rc} raw={raw_out} log={run_log}", flush=True)

    # 适配:raw_out → 标准 result.json
    try:
        result = adapt_raw(raw_out, adapter)
    except (ValueError, json.JSONDecodeError) as exc:
        # 适配失败也算硬错误:产出单条 queue,scope_guard 可据此判定
        result = {"case_details": [_make_case_detail(
            "hard_error", error=f"adapter parse failed: {exc}")]}
    os.makedirs(os.path.dirname(result_json) or ".", exist_ok=True)
    with open(result_json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[adapter] result.json → {result_json} "
          f"({len(result['case_details'])} cases)", flush=True)
    return rc


def cmd_adapt(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    adapter = cfg.get("result_adapter", {})
    raw = args.raw or adapter.get("raw_output")
    out = args.out or adapter.get("result_json", "result.json")
    if not raw:
        sys.exit("ERROR: 需 --raw 或 config.result_adapter.raw_output")
    result = adapt_raw(raw, adapter)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[adapter] {raw} → {out} ({len(result['case_details'])} cases)", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_with_adapter.py",
        description="用户自定义测试/编译命令的适配层(precision_debug TUI adapter)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="执行 build_command")
    b.add_argument("--config", required=True)
    b.set_defaults(func=cmd_build)

    r = sub.add_parser("run-test", help="执行 test_command 并适配出 result.json")
    r.add_argument("--config", required=True)
    r.add_argument("--case", default="", help="单用例 case_id(填 {case_id} 占位符)")
    r.add_argument("--iter", default="", help="迭代号(填 {iter} 占位符)")
    r.add_argument("--label", default="", help="标签(填 {label} 占位符)")
    r.set_defaults(func=cmd_run_test)

    a = sub.add_parser("adapt", help="只做 raw_output → result.json 转换")
    a.add_argument("--config", required=True)
    a.add_argument("--raw", default="", help="覆盖 config.result_adapter.raw_output")
    a.add_argument("--out", default="", help="覆盖 config.result_adapter.result_json")
    a.set_defaults(func=cmd_adapt)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
