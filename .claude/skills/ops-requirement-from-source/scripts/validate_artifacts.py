"""Validate requirement artifacts produced by ops-requirement-from-source.

Checks structure and cross-file consistency. Does not import or execute golden.py,
does not certify operator semantics, precision, or hardware behavior.

Requires Python 3.10+ and PyYAML.
"""

import argparse
import ast
import csv
import json
import re
from pathlib import Path

EXPECTED_CASES = 20
CHIP_ALIASES = {
    "A5": "A5",
    "950": "A5",
    "3510": "A5",
    "A3": "A3",
    "910B": "A3",
    "910C": "A3",
    "910": "A3",
}
FIELDS = ["operator", "case_id", "input_shape", "dtype", "attrs", "value_range", "note"]
DESIGN_SECTIONS = (
    "实现概览",
    "模板设计",
    "分核设计",
    "分块设计",
    "性能调优技巧",
    "模板与测试覆盖映射",
    "源码依据与需求决策",
)
TTK_PASS_VALUES = {"PASS", "FAIL", "SKIP"}
TTK_ATTRIBUTIONS = {"golden", "case", "false_failure", "operator_defect", "environment"}


def read_exact(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return stream.read()


def golden_body(source):
    tree = ast.parse(source)
    imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    if not imports:
        raise ValueError("golden.py 必须有顶层 import/from")
    return "".join(source.splitlines(keepends=True)[imports[0].lineno - 1:])


def canonical(value):
    """Normalize NaN/Inf so YAML and CSV can be compared."""
    if isinstance(value, float):
        if value != value:
            return "nan"
        if value == float("inf"):
            return "inf"
        if value == -float("inf"):
            return "-inf"
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical(item) for item in value]
    return value


def check_notes(cases):
    """Each note must be a one-line natural-language description of the case."""
    errors = []
    for case in cases:
        case_id = case.get("case_id")
        note = case.get("note")
        if not isinstance(note, str) or not note.strip():
            errors.append(f"case {case_id} 的 note 必须是非空字符串")
            continue
        if "\n" in note or "\r" in note:
            errors.append(f"case {case_id} 的 note 必须是单行描述")
        if note.lstrip().startswith("{"):
            errors.append(f"case {case_id} 的 note 不得是 JSON 结构，应为一句话描述")
    return errors


def duplicate_keys(cases):
    keys = []
    for case in cases:
        signature = canonical(
            [
                case.get("input_shape"),
                case.get("dtype"),
                case.get("attrs"),
                case.get("value_range"),
            ]
        )
        keys.append(json.dumps(signature, ensure_ascii=False, sort_keys=True))
    return len(keys) != len(set(keys))


def validate_ttk(workdir, expected_cases):
    """Light check of the optional TTK verification artifacts under TTK_WORKDIR."""
    if not workdir.is_dir():
        return [f"TTK 产物目录不存在：{workdir}"]
    handoff_path = workdir / "debug" / "handoff.json"
    if not handoff_path.is_file():
        return [f"缺少 TTK 交接文件：{handoff_path}"]
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    status = handoff.get("status")
    if status == "skipped":
        return [] if handoff.get("skip_reason") else ["handoff.json 的 status=skipped 时需写 skip_reason"]
    if status != "executed":
        return ["handoff.json 的 status 必须为 executed 或 skipped"]

    errors = []
    if not (workdir / "cases.csv").is_file():
        return [f"TTK 产物缺少 cases.csv：{workdir / 'cases.csv'}"]

    with (workdir / "cases.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != expected_cases:
        errors.append(f"TTK cases.csv 行数应为 {expected_cases}，当前为 {len(rows)}")
    bad_pass = [row.get("testcase_name") for row in rows if row.get("pass") not in TTK_PASS_VALUES]
    if bad_pass:
        errors.append(f"TTK cases.csv 的 pass 必须为 PASS/FAIL/SKIP：{bad_pass[:5]}")

    bad = [
        entry.get("case_id") for entry in (handoff.get("failures") or [])
        if entry.get("attribution") not in TTK_ATTRIBUTIONS
    ]
    if bad:
        errors.append(f"handoff.json 的 FAIL 用例 attribution 非法：{bad[:5]}")
    return errors
def parse_chips(text):
    chips = []
    for item in text.split(","):
        item = item.strip().upper()
        if not item:
            continue
        if item not in CHIP_ALIASES:
            raise ValueError(f"无法识别的芯片种类：{item}；支持 A5、A3、A3,A5 及其 SoC 别名")
        chip = CHIP_ALIASES[item]
        if chip not in chips:
            chips.append(chip)
    if not chips:
        raise ValueError("芯片种类不能为空")
    return chips


def validate(folder, yaml, expected_cases=EXPECTED_CASES, chips=("A5",)):
    errors = []
    warnings = []

    def check(condition, message):
        if not condition:
            errors.append(message)

    required = ("desc.md", "golden.py", "proto.yaml", "cases.yaml", "cases.csv", "design.md")
    for name in required:
        check((folder / name).is_file(), f"缺少文件：{name}")
    if errors:
        return errors, warnings

    snake = folder.name
    check(bool(re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", snake)), "文件夹名必须为 snake_case")

    source = read_exact(folder / "golden.py")
    tree = ast.parse(source)
    functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    public = [node for node in functions if not node.name.startswith("_")]
    check(len(public) == 1 and public[0].name == snake, "golden.py 必须只有一个公开模块级函数，且名称等于文件夹名")
    if len(public) == 1:
        args = public[0].args
        params = args.posonlyargs + args.args + args.kwonlyargs
        params += [arg for arg in (args.vararg, args.kwarg) if arg is not None]
        check(all(arg.arg != "self" for arg in params), "golden 入口不能有 self 参数")

    desc = read_exact(folder / "desc.md")
    section = re.search(r"^## 5\. 标准 Golden 代码\r?\n(.*?)(?=^## |\Z)", desc, re.M | re.S)
    block = re.search(r"^```python\r?\n(.*?)^```[ \t]*\r?$", section[1], re.M | re.S) if section else None
    check(block is not None, "缺少标准 Golden 代码章节或 python fenced block")
    if block:
        check(block[1] == golden_body(source), "desc.md 标准 Golden 代码与 golden.py 正文不逐字符一致（包括换行）")
    check("### 用例执行与数据构造约定" in desc, "desc.md 第 6 节缺少“用例执行与数据构造约定”")

    proto = yaml.safe_load(read_exact(folder / "proto.yaml"))
    operator = proto["operator"]
    pascal = operator["name"]
    check(bool(re.fullmatch(r"[A-Z][A-Za-z0-9]*", pascal)), "operator.name 必须为 PascalCase")
    check(desc.splitlines()[0] == f"# {pascal} 算子 API 描述", "desc.md 一级标题与 operator.name 不一致")
    check(str(operator["schema"]).startswith(snake + "("), "proto schema 入口名不一致")
    check(f"cann_bench.{snake}(" in desc, "desc.md 缺少 cann_bench 调用原型")

    cases = yaml.safe_load(read_exact(folder / "cases.yaml"))["cases"]
    check(isinstance(cases, list) and bool(cases), "cases.yaml 的 cases 必须为非空列表")
    if not isinstance(cases, list):
        return errors, warnings

    check(len(cases) == expected_cases, f"用例数必须固定为 {expected_cases}，当前为 {len(cases)}")
    check(all(list(case.keys()) == FIELDS for case in cases), f"cases.yaml 每个 case 的字段必须为 {FIELDS}")
    ids = [case.get("case_id") for case in cases]
    check(len(set(ids)) == len(ids), "case_id 重复")
    check(all(case.get("operator") == pascal for case in cases), "case operator 与 proto.yaml 不一致")

    errors.extend(check_notes(cases))
    if duplicate_keys(cases):
        errors.append("存在重复用例：input_shape/dtype/attrs/value_range 完全相同")

    with (folder / "cases.csv").open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        check(fields == FIELDS, f"CSV 列必须为 {FIELDS}")
        rows = list(reader)
    check(len(rows) == expected_cases, f"cases.csv 行数必须为 {expected_cases}，当前为 {len(rows)}")

    normalized = []
    for row in rows:
        converted = dict(row)
        converted["case_id"] = int(row["case_id"])
        for field in ("input_shape", "dtype", "attrs", "value_range"):
            converted[field] = json.loads(row[field])
        normalized.append(converted)
    check(canonical(cases) == canonical(normalized), "cases.yaml 与 cases.csv 内容或顺序不一致")

    design = read_exact(folder / "design.md")
    missing_sections = [name for name in DESIGN_SECTIONS if name not in design]
    check(not missing_sections, f"design.md 缺少章节：{missing_sections}")
    check(all(chip in design for chip in chips), f"design.md 未标注所选芯片：{list(chips)}")

    warnings.append("语义、数值精度、覆盖充分性和硬件行为仍需单独验证。")
    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--expected-cases", type=int, default=EXPECTED_CASES)
    parser.add_argument("--chip", default="A5",
                        help="芯片种类：A5（默认）、A3 或 A3,A5；也接受 950/3510/910b/910c 别名")
    parser.add_argument("--with-ttk", action="store_true",
                        help="同时校验 TTK 验证产物（TTK_WORKDIR 下的 cases.csv 与 debug/handoff.json）")
    parser.add_argument("--ttk-workdir", type=Path, default=None,
                        help="TTK 产物目录；默认 <folder>/ttk")
    args = parser.parse_args()
    try:
        import yaml
    except ImportError:
        parser.exit(2, "缺少 PyYAML；请在工作环境中安装 PyYAML 后重试。未执行校验。\n")
    try:
        chips = parse_chips(args.chip)
        errors, warnings = validate(args.folder, yaml, args.expected_cases, chips)
        if args.with_ttk:
            workdir = args.ttk_workdir or (args.folder / "ttk")
            errors.extend(validate_ttk(workdir, args.expected_cases))
    except (OSError, ValueError, SyntaxError, KeyError, TypeError, IndexError, AttributeError, yaml.YAMLError) as exc:
        parser.exit(1, f"FAIL: 无法解析产物：{exc}\n")
    for warning in warnings:
        print(f"WARN: {warning}")
    if errors:
        parser.exit(1, "\n".join(f"FAIL: {error}" for error in errors) + "\n")
    suffix = "，TTK 产物已校验" if args.with_ttk else ""
    print(f"PASS: 结构与跨文件一致性检查通过（{args.expected_cases} 个用例，芯片 {'/'.join(chips)}{suffix}）；"
          "语义、精度、覆盖和硬件执行仍需单独验证。")


if __name__ == "__main__":
    main()
