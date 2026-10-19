#!/usr/bin/env python3
"""
AscendC 核内同步追踪器 - 注入脚本

功能：
1. 将 SetFlag<HardEvent::XXX>(eid) 替换为 TrackerSet(HE_XXX, eid, __LINE__)
2. 将 WaitFlag<HardEvent::XXX>(eid) 替换为 TrackerWait(HE_XXX, eid, __LINE__)
3. 将 SET_FLAG(A, B, eid) 替换为 TrackerSet(HE_A_B, eid, __LINE__)
4. 将 WAIT_FLAG(A, B, eid) 替换为 TrackerWait(HE_A_B, eid, __LINE__)
5. 复制 sync_tracker.h 到合适目录（优先 basic_modules，否则 op_kernel）
6. 添加 #include（路径根据文件位置自动调整）
7. 在 op.Process() 后添加 TrackerPrint()

用法：
    python inject_sync_tracker.py /path/to/operator
"""

import re
import argparse
import json
from pathlib import Path
from collections import defaultdict
import shutil

# HardEvent 名称到索引的映射
HARDEVENT_MAP = {
    "MTE2_MTE1": 0, "MTE1_MTE2": 1, "MTE1_M": 2, "M_MTE1": 3,
    "MTE2_V": 4, "V_MTE2": 5, "MTE3_V": 6, "V_MTE3": 7,
    "M_V": 8, "V_M": 9, "MTE3_MTE1": 10, "MTE1_MTE3": 11,
    "MTE1_V": 12, "MTE2_M": 13, "M_MTE2": 14, "V_MTE1": 15,
    "M_FIX": 16, "FIX_M": 17, "MTE3_MTE2": 18, "MTE2_MTE3": 19,
    "S_V": 20, "V_S": 21, "S_MTE2": 22, "MTE2_S": 23,
    "S_MTE3": 24, "MTE3_S": 25, "MTE2_FIX": 26, "FIX_MTE2": 27,
    "FIX_S": 28, "M_S": 29, "FIX_MTE3": 30,
}

# 只替换 MTE1/2/3 和 V 之间的同步（常见软件同步）
# 不替换 MTE_M, M_V, FIX_*, S_* 等（关键硬件同步，替换会导致硬件错误）
FILTER_HARDEVENTS = {
    "MTE2_MTE1", "MTE1_MTE2",  # MTE 之间
    "MTE2_V", "V_MTE2", "MTE3_V", "V_MTE3",  # MTE 和 V 之间
    "MTE3_MTE1", "MTE1_MTE3",  # MTE 之间
    "MTE1_V", "V_MTE1",  # MTE1 和 V 之间
    "MTE3_MTE2", "MTE2_MTE3",  # MTE 之间
}

SCAN_EXTENSIONS = {".h", ".cpp", ".hpp"}
TRACKER_HEADER = "sync_tracker.h"
FILE_MAP_JSON = "sync_file_map.json"
SCRIPT_DIR = Path(__file__).parent


def extract_balanced_paren(content: str, start_pos: int) -> str:
    """
    从 start_pos 位置开始提取平衡的括号内容。
    正确处理嵌套括号，如 (a + (b + c)) 或 ((a + ((b + d) + c)))。

    Args:
        content: 字符串内容
        start_pos: 左括号 '(' 的位置

    Returns:
        括号内的内容（不含外层括号），如果括号不匹配返回 None
    """
    if start_pos >= len(content) or content[start_pos] != '(':
        return None

    depth = 0
    i = start_pos

    while i < len(content):
        ch = content[i]
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0:
                # 找到匹配的右括号
                return content[start_pos + 1:i]
        i += 1

    # 括号不匹配
    return None


def replace_sync_calls(content: str, file_id: int) -> tuple:
    """
    替换所有核内同步调用。
    返回 (替换后的内容, 替换次数)

    Args:
        content: 文件内容
        file_id: 文件编号（用于精确定位错误位置）
    """
    lines = content.split('\n')
    result_lines = []
    replace_count = 0

    for line in lines:
        new_line = line
        replaced = False

        # 1. SetFlag<HardEvent::XXX>(eid)
        # 使用括号匹配算法提取 eid，支持嵌套括号
        m = re.search(
            r'SetFlag\s*<\s*(?:AscendC\s*::\s*)?HardEvent\s*::\s*(\w+)\s*>\s*\(',
            line
        )
        if m:
            he_name = m.group(1)
            paren_start = m.end() - 1  # 左括号的位置
            eid = extract_balanced_paren(line, paren_start)
            if eid is not None and he_name in FILTER_HARDEVENTS:
                indent = line[:len(line) - len(line.lstrip())]
                new_line = f'{indent}TrackerSet(HE_{he_name}, {eid.strip()}, {file_id}, __LINE__);'
                replaced = True

        # 2. WaitFlag<HardEvent::XXX>(eid)
        if not replaced:
            m = re.search(
                r'WaitFlag\s*<\s*(?:AscendC\s*::\s*)?HardEvent\s*::\s*(\w+)\s*>\s*\(',
                line
            )
            if m:
                he_name = m.group(1)
                paren_start = m.end() - 1
                eid = extract_balanced_paren(line, paren_start)
                if eid is not None and he_name in FILTER_HARDEVENTS:
                    indent = line[:len(line) - len(line.lstrip())]
                    new_line = f'{indent}TrackerWait(HE_{he_name}, {eid.strip()}, {file_id}, __LINE__);'
                    replaced = True

        # 3. SET_FLAG(A, B, eid) - 同样需要处理嵌套括号
        if not replaced:
            m = re.search(r'SET_FLAG\s*\(\s*(\w+)\s*,\s*(\w+)\s*,', line)
            if m:
                he_name = f"{m.group(1)}_{m.group(2)}"
                # 找到第二个逗号后的内容
                comma_end = m.end()
                # 跳过空白找到左括号或表达式的开始
                rest = line[comma_end:].lstrip()
                if rest.startswith('('):
                    # eid 是括号表达式
                    paren_start = line.index('(', comma_end)
                    eid = extract_balanced_paren(line, paren_start)
                else:
                    # eid 是简单标识符或表达式，找到右括号
                    end_pos = line.find(')', comma_end)
                    if end_pos != -1:
                        eid = line[comma_end:end_pos].strip()
                    else:
                        eid = None

                if eid is not None and he_name in FILTER_HARDEVENTS:
                    indent = line[:len(line) - len(line.lstrip())]
                    new_line = f'{indent}TrackerSet(HE_{he_name}, {eid.strip()}, {file_id}, __LINE__);'
                    replaced = True

        # 4. WAIT_FLAG(A, B, eid) - 同样需要处理嵌套括号
        if not replaced:
            m = re.search(r'WAIT_FLAG\s*\(\s*(\w+)\s*,\s*(\w+)\s*,', line)
            if m:
                he_name = f"{m.group(1)}_{m.group(2)}"
                comma_end = m.end()
                rest = line[comma_end:].lstrip()
                if rest.startswith('('):
                    paren_start = line.index('(', comma_end)
                    eid = extract_balanced_paren(line, paren_start)
                else:
                    end_pos = line.find(')', comma_end)
                    if end_pos != -1:
                        eid = line[comma_end:end_pos].strip()
                    else:
                        eid = None

                if eid is not None and he_name in FILTER_HARDEVENTS:
                    indent = line[:len(line) - len(line.lstrip())]
                    new_line = f'{indent}TrackerWait(HE_{he_name}, {eid.strip()}, {file_id}, __LINE__);'
                    replaced = True

        if replaced:
            replace_count += 1
        result_lines.append(new_line)

    return '\n'.join(result_lines), replace_count


def get_tracker_header_dir(operator_dir: Path) -> Path:
    """
    确定sync_tracker.h的放置位置。
    优先使用 basic_modules 目录（如果存在），否则使用 op_kernel 目录。
    """
    basic_modules = operator_dir / "basic_modules"
    if basic_modules.exists():
        return basic_modules
    return operator_dir / "op_kernel"


def get_include_path(file_path: Path, operator_dir: Path, tracker_dir: Path) -> str:
    """
    返回 include 路径，根据文件位置和 tracker 位置计算。

    规则：
    1. 如果文件在 tracker_dir 或其子目录下，使用相对路径
       - 同一目录: "sync_tracker.h"
       - 子目录: "../sync_tracker.h" 或 "../../sync_tracker.h" 等
    2. 否则使用从算子根目录开始的路径，如 "basic_modules/sync_tracker.h"
    """
    file_dir = file_path.parent

    # 检查文件是否在 tracker_dir 或其子目录下
    try:
        rel_path = file_dir.relative_to(tracker_dir)
        # 文件在 tracker_dir 下（包括同一目录和子目录）
        # 计算从文件目录到 tracker_dir 的相对路径
        depth = len(rel_path.parts) if str(rel_path) != '.' else 0
        if depth == 0:
            # 同一目录
            return TRACKER_HEADER
        else:
            # 子目录，需要 ../ 返回
            return '../' * depth + TRACKER_HEADER
    except ValueError:
        # 文件不在 tracker_dir 下
        pass

    # 使用从算子根目录开始的路径
    rel_tracker = tracker_dir.relative_to(operator_dir)
    return str(rel_tracker / TRACKER_HEADER)


def add_include_header(content: str, include_path: str) -> tuple:
    """添加 #include "sync_tracker.h" """
    if TRACKER_HEADER in content:
        return content, 0

    lines = content.split('\n')
    for i, line in enumerate(lines):
        if line.strip().startswith('#include'):
            j = i + 1
            while j < len(lines) and lines[j].strip().startswith('#include'):
                j += 1
            lines.insert(j, f'#include "{include_path}"')
            return '\n'.join(lines), 1

    # 如果没有找到 include，在开头添加
    lines.insert(0, f'#include "{include_path}"')
    return '\n'.join(lines), 1


def add_tracker_print_to_process(content: str) -> tuple:
    """
    在 op.Process(...) 后添加 TrackerPrint()
    支持跨多行的 Process 调用（在宏定义中常见）
    """
    lines = content.split('\n')
    modified = False
    i = 0

    while i < len(lines):
        line = lines[i]

        # 检查是否是 op.Process 的开始（可能在宏定义中）
        if re.search(r'op\.Process\s*\(', line):
            # 检查这一行是否已经以分号结尾
            if ';' in line:
                # 单行调用
                if i + 1 < len(lines) and 'TrackerPrint' in lines[i + 1]:
                    i += 1
                    continue
                indent = line[:len(line) - len(line.lstrip())]
                # 检查是否在宏定义中（行末有反斜杠）
                if line.rstrip().endswith('\\'):
                    lines.insert(i + 1, f'{indent}TrackerPrint(); \\')
                else:
                    lines.insert(i + 1, f'{indent}TrackerPrint();')
                modified = True
            else:
                # 跨多行调用，找到结束的分号
                j = i + 1
                while j < len(lines) and ';' not in lines[j]:
                    j += 1

                if j < len(lines):
                    # 检查下一行是否已有 TrackerPrint
                    if j + 1 < len(lines) and 'TrackerPrint' in lines[j + 1]:
                        i = j + 1
                        continue
                    indent = lines[j][:len(lines[j]) - len(lines[j].lstrip())]
                    # 检查是否在宏定义中（行末有反斜杠）
                    if lines[j].rstrip().endswith('\\'):
                        lines.insert(j + 1, f'{indent}TrackerPrint(); \\')
                    else:
                        lines.insert(j + 1, f'{indent}TrackerPrint();')
                    modified = True
                    i = j + 1

        i += 1

    return '\n'.join(lines), 1 if modified else 0


def add_tracker_print_to_kernel_entry(content: str) -> tuple:
    """
    在 kernel 入口函数 (extern "C" __global__ __aicore__ void xxx(...)) 的 return 语句前添加 TrackerPrint()
    用于处理 Process 调用在宏定义中的情况
    只在紧跟 INVOKE_XXX 宏后面的 return 前添加，避免冗余
    """
    # 查找 kernel 入口函数
    if 'extern "C" __global__ __aicore__' not in content:
        return content, 0

    lines = content.split('\n')
    modified_count = 0

    # 查找所有 return 语句之前添加 TrackerPrint
    # 但要检查前面是否已经有 TrackerPrint
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('return'):
            # 检查前一行是否已有 TrackerPrint
            if i > 0 and 'TrackerPrint' in lines[i - 1]:
                continue
            indent = line[:len(line) - len(line.lstrip())]
            lines.insert(i, f'{indent}TrackerPrint();')
            modified_count += 1

    return '\n'.join(lines), modified_count


def add_tracker_print_to_macro(content: str) -> tuple:
    """
    在 op.Process() 后添加 TrackerPrint()
    保留此函数以兼容旧逻辑
    """
    return add_tracker_print_to_process(content)


def process_operator(operator_dir: Path):
    """处理整个算子目录。"""
    print(f"扫描目录: {operator_dir}")

    # 0. 确定 sync_tracker.h 的放置位置
    tracker_dir = get_tracker_header_dir(operator_dir)
    tracker_dest = tracker_dir / TRACKER_HEADER

    print(f"头文件位置: {tracker_dest}")

    tracker_dir.mkdir(parents=True, exist_ok=True)
    src_tracker = SCRIPT_DIR / TRACKER_HEADER
    if src_tracker.exists():
        shutil.copy(src_tracker, tracker_dest)
        print(f"复制 sync_tracker.h -> {tracker_dest}")
    else:
        print(f"警告: 找不到 {src_tracker}")

    # 1. 收集所有文件
    files = []
    for ext in SCAN_EXTENSIONS:
        files.extend(operator_dir.rglob(f"*{ext}"))

    # 只处理 op_kernel 和 basic_modules 目录下的文件
    files = [f for f in files if "op_kernel" in str(f) or "basic_modules" in str(f)]
    print(f"找到 {len(files)} 个文件")

    # 2. 处理每个文件
    stats = defaultdict(lambda: {'sync_replaced': 0, 'includes_added': 0, 'prints_added': 0, 'file_id': 0})
    file_contents = {}
    file_id_map = {}  # file_id -> relative_path
    next_file_id = 1

    for fp in files:
        content = fp.read_text()
        lines = content.split('\n')

        # 先检查是否有同步调用需要替换，分配 file_id
        temp_content, sync_count = replace_sync_calls(content, 0)  # 临时用 0 测试
        if sync_count > 0:
            # 分配文件编号
            file_id = next_file_id
            next_file_id += 1
            stats[fp]['file_id'] = file_id
            # 记录相对路径
            rel_path = str(fp.relative_to(operator_dir))
            file_id_map[file_id] = rel_path

            # 用正确的 file_id 重新替换
            new_content, sync_count = replace_sync_calls(content, file_id)
            stats[fp]['sync_replaced'] = sync_count
            lines = new_content.split('\n')
            content = new_content

        # 在 op.Process 后添加 TrackerPrint
        new_content, print_count = add_tracker_print_to_macro(content)
        if print_count > 0:
            stats[fp]['prints_added'] += print_count
            lines = new_content.split('\n')
            content = new_content

        # 添加 include
        if stats[fp]['sync_replaced'] > 0 or stats[fp]['prints_added'] > 0:
            include_path = get_include_path(fp, operator_dir, tracker_dir)
            new_content = '\n'.join(lines)
            new_content, include_count = add_include_header(new_content, include_path)
            if include_count > 0:
                stats[fp]['includes_added'] = include_count
                lines = new_content.split('\n')

        file_contents[fp] = lines

    # 3. 输出统计
    total = defaultdict(int)
    modified_files = []
    for fp, s in stats.items():
        if any(v > 0 for v in s.values() if isinstance(v, int)):
            modified_files.append((fp, s))
            for k, v in s.items():
                if isinstance(v, int):
                    total[k] += v

    # 4. 写入文件
    for fp, lines in file_contents.items():
        if any(v > 0 for v in stats[fp].values() if isinstance(v, int)):
            fp.write_text('\n'.join(lines))

    # 5. 生成 file_map.json
    if file_id_map:
        file_map_path = tracker_dir / FILE_MAP_JSON
        with open(file_map_path, 'w', encoding='utf-8') as f:
            json.dump(file_id_map, f, indent=2, ensure_ascii=False)
        print(f"生成文件映射: {file_map_path}")
        print(f"  包含 {len(file_id_map)} 个文件的编号映射")

    # 输出结果
    print("\n" + "=" * 60)
    print("修改统计:")
    print(f"  同步替换: {total['sync_replaced']}")
    print(f"  Include添加: {total['includes_added']}")
    print(f"  Print添加: {total['prints_added']}")
    print(f"\n修改文件: {len(modified_files)} 个")

    for fp, s in modified_files:
        rel = fp.relative_to(operator_dir)
        file_id_str = f" [ID:{s['file_id']}]" if s['file_id'] > 0 else ""
        details = [f"{k}:{v}" for k, v in s.items() if isinstance(v, int) and v > 0 and k != 'file_id']
        print(f"  {rel}{file_id_str}: {', '.join(details)}")


def main():
    parser = argparse.ArgumentParser(
        description="AscendC 核内同步追踪器 - 注入脚本"
    )
    parser.add_argument("operator_dir", help="算子目录路径")

    args = parser.parse_args()
    operator_path = Path(args.operator_dir).resolve()

    if not operator_path.exists():
        print(f"错误: 目录不存在 {operator_path}")
        return

    process_operator(operator_path)


if __name__ == "__main__":
    main()