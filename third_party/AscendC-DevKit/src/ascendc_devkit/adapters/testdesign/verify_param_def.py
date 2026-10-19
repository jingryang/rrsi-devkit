"""03_参数定义.yaml ↔ requirement.json 对质校验（§2.9 构造性保证）。

只查结构，不查语义——语义无唯一正确答案，硬查会造成误报。
E-1（spawn 前，stage ``actions()``）与 E-3（交付前，stage ``transition()``
复验）共用同一入口 ``verify_from_dir``（§1.15 单点），覆盖 03 的两条产出
路径：适配器写 / agent 改。
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from ascendc_devkit.adapters.testdesign.convert_to_param_def import (
    _normalise_dtype,  # 唯一 dtype 归一化点（§1.15）——两侧同源，别名不误报
)


def _canon(d) -> str:
    """dtype 归一化（空安全）：上游 JSON 与 03 的 dtype 表述统一后再比较。"""
    return _normalise_dtype(str(d).lower()) if d else ""


def verify(requirement: dict, design_spec: dict, yaml_data: dict) -> list[str]:
    """对质 03 与上游 JSON，返回违规项列表（空 = 通过）。

    三个维度（只查结构）：
      ① 参数清单：03 的张量集 ⊇ JSON 声明集（只查「缺」方向——ds-attrs 兜底
        可合法产出声明集之外的条目，查「多出」会误报）
      ② dtype 域：03 的 dtype ⊆ requirement.domain.inputs[].dtypes
      ③ rank：03 的 dimensions ∈ requirement.domain.rank.[min,max]
    """
    errors: list[str] = []

    # ① 参数清单：03 的张量集 ⊇ JSON 声明集
    #    dtype 必须经同一归一化点：上游可写别名（fp16/bf16），03 里是
    #    _normalise_dtype 后的规范名（float16/bfloat16）——两侧不同源会误报
    #    「缺参数」（requirement schema 的 example 恰用 "fp16"，必触发）。
    auth: set[tuple[str, str]] = set()
    for src in (requirement, design_spec):
        for e in (src.get("inputs") or []) + (src.get("outputs") or []):
            if isinstance(e, dict) and e.get("name"):
                dt = e.get("dtype")
                for d in (dt if isinstance(dt, list) else [dt] if dt else []):
                    auth.add((e["name"], _canon(d)))
    produced: set[tuple[str, str]] = set()
    for p in (yaml_data.get("parameters") or []):
        if p.get("type") == "aclTensor":
            for de in (p.get("dtype_with_ranges") or []):
                produced.add((p["name"], _canon(de.get("dtype"))))
    for name, dt in sorted(auth - produced):
        errors.append(f"03 缺参数：{name} ({dt})")

    # ② dtype 域：03 的 dtype ⊆ domain.inputs[].dtypes（同经 _canon 归一）
    domain = requirement.get("domain") or {}
    for ent in (domain.get("inputs") or []):
        allowed = {_canon(d) for d in (ent.get("dtypes") or [])}
        if not allowed:
            continue
        for p in (yaml_data.get("parameters") or []):
            if p.get("name") != ent.get("name"):
                continue
            for de in (p.get("dtype_with_ranges") or []):
                got = _canon(de.get("dtype"))
                if got and got not in allowed:
                    errors.append(
                        f"03 dtype 越界：{p['name']}.{got} ∉ {sorted(allowed)}")

    # ③ rank：03 的 dimensions ∈ domain.rank.{min,max}
    rk = domain.get("rank") or {}
    lo, hi = rk.get("min"), rk.get("max")
    if isinstance(lo, int) and isinstance(hi, int):
        for p in (yaml_data.get("parameters") or []):
            dims = p.get("dimensions")
            if not isinstance(dims, list) or p.get("io_type") != "input":
                continue
            bad = [d for d in dims if not (lo <= d <= hi)]
            if bad:
                errors.append(
                    f"03 rank 越界：{p['name']}.dimensions 含 {bad} ∉ [{lo},{hi}]")
    return errors


def verify_from_dir(wd: Path) -> list[str]:
    """从 stage 工作目录加载三份产物并跑对质（E-1 / E-3 共用，§1.15）。"""
    req = json.loads((wd / "requirement.json").read_text(encoding="utf-8"))
    ds_path = wd / "design_spec.json"
    ds = (json.loads(ds_path.read_text(encoding="utf-8"))
          if ds_path.exists() else {})
    yaml_data = (yaml.safe_load(
        (wd / "design" / "03_参数定义.yaml").read_text(encoding="utf-8"))
        or {})
    return verify(req, ds, yaml_data)
