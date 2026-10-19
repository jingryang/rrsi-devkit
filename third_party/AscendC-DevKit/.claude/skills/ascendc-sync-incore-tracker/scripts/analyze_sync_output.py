#!/usr/bin/env python3
"""
AscendC 核内同步追踪器 - 输出分析脚本 v4

功能：
1. 解析 [SYNC DEBUG] 输出，提取错误信息（支持新的多错误格式）
2. 支持错误计数显示（x N times）
3. 读取 sync_file_map.json，通过 FILE_ID 精确定位源文件
4. 显示错误位置和上一次 SET 位置的代码内容（带上下文）

用法：
    python analyze_sync_output.py <log_file> <operator_dir>

示例：
    python analyze_sync_output.py /tmp/test_output.txt training/ascendc/src/ops-transformer/attention/sparse_flash_attention_grad_enhance
"""

import re
import argparse
import json
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict


@dataclass
class SyncError:
    """同步错误信息"""
    error_index: int      # 错误序号（从1开始）
    error_type: str       # "WAIT on UNSET", "WAIT on NEVER-SET", "SET on SET"
    hard_event: int
    event_id: int
    error_file_id: int    # 出错位置的文件编号
    error_line: int
    prev_set_file_id: Optional[int] = None  # 上一次 SET 的文件编号
    prev_set_line: Optional[int] = None
    count: int = 1        # 错误出现次数
    suggestion: Optional[str] = None  # 来自输出的建议


# HardEvent 索引到名称的映射
HARDEVENT_NAMES = {
    0: "MTE2_MTE1", 1: "MTE1_MTE2", 2: "MTE1_M", 3: "M_MTE1",
    4: "MTE2_V", 5: "V_MTE2", 6: "MTE3_V", 7: "V_MTE3",
    8: "M_V", 9: "V_M", 10: "MTE3_MTE1", 11: "MTE1_MTE3",
    12: "MTE1_V", 13: "MTE2_M", 14: "M_MTE2", 15: "V_MTE1",
    16: "M_FIX", 17: "FIX_M", 18: "MTE3_MTE2", 19: "MTE2_MTE3",
    20: "S_V", 21: "V_S", 22: "S_MTE2", 23: "MTE2_S",
    24: "S_MTE3", 25: "MTE3_S", 26: "MTE2_FIX", 27: "FIX_MTE2",
    28: "FIX_S", 29: "M_S", 30: "FIX_MTE3",
}

# HardEvent 类型的详细说明
HARDEVENT_INFO = {
    "MTE2_MTE1": {"from": "MTE2", "to": "MTE1", "desc": "数据搬运完成，通知 L1 搬运"},
    "MTE1_MTE2": {"from": "MTE1", "to": "MTE2", "desc": "L1 搬运完成，通知 MTE2"},
    "MTE1_M": {"from": "MTE1", "to": "M", "desc": "L1 数据就绪，通知 Cube 计算"},
    "M_MTE1": {"from": "M", "to": "MTE1", "desc": "Cube 计算完成，通知 L1"},
    "MTE2_V": {"from": "MTE2", "to": "V", "desc": "数据搬运完成，通知 Vector 计算"},
    "V_MTE2": {"from": "V", "to": "MTE2", "desc": "Vector 计算完成，通知 MTE2"},
    "MTE3_V": {"from": "MTE3", "to": "V", "desc": "数据搬出完成，通知 Vector"},
    "V_MTE3": {"from": "V", "to": "MTE3", "desc": "Vector 计算完成，通知数据搬出"},
    "M_V": {"from": "M", "to": "V", "desc": "Cube 计算完成，通知 Vector"},
    "V_M": {"from": "V", "to": "M", "desc": "Vector 计算完成，通知 Cube"},
    "MTE3_MTE1": {"from": "MTE3", "to": "MTE1", "desc": "数据搬出完成，通知 L1"},
    "MTE1_MTE3": {"from": "MTE1", "to": "MTE3", "desc": "L1 就绪，通知数据搬出"},
    "MTE1_V": {"from": "MTE1", "to": "V", "desc": "L1 数据就绪，通知 Vector"},
    "MTE2_M": {"from": "MTE2", "to": "M", "desc": "数据搬运完成，通知 Cube"},
    "M_MTE2": {"from": "M", "to": "MTE2", "desc": "Cube 计算完成，通知 MTE2"},
    "V_MTE1": {"from": "V", "to": "MTE1", "desc": "Vector 计算完成，通知 L1"},
    "M_FIX": {"from": "M", "to": "FIX", "desc": "Cube 计算完成，通知 Fixpipe"},
    "FIX_M": {"from": "FIX", "to": "M", "desc": "Fixpipe 完成，通知 Cube"},
    "MTE3_MTE2": {"from": "MTE3", "to": "MTE2", "desc": "数据搬出完成，通知下一轮搬运"},
    "MTE2_MTE3": {"from": "MTE2", "to": "MTE3", "desc": "数据搬运完成，通知数据搬出"},
    "S_V": {"from": "S", "to": "V", "desc": "Scalar 操作完成，通知 Vector"},
    "V_S": {"from": "V", "to": "S", "desc": "Vector 计算完成，通知 Scalar"},
    "S_MTE2": {"from": "S", "to": "MTE2", "desc": "Scalar 操作完成，通知 MTE2"},
    "MTE2_S": {"from": "MTE2", "to": "S", "desc": "数据搬运完成，通知 Scalar"},
    "S_MTE3": {"from": "S", "to": "MTE3", "desc": "Scalar 操作完成，通知 MTE3"},
    "MTE3_S": {"from": "MTE3", "to": "S", "desc": "数据搬出完成，通知 Scalar"},
    "MTE2_FIX": {"from": "MTE2", "to": "FIX", "desc": "数据搬运完成，通知 Fixpipe"},
    "FIX_MTE2": {"from": "FIX", "to": "MTE2", "desc": "Fixpipe 完成，通知 MTE2"},
    "FIX_S": {"from": "FIX", "to": "S", "desc": "Fixpipe 完成，通知 Scalar"},
    "M_S": {"from": "M", "to": "S", "desc": "Cube 计算完成，通知 Scalar"},
    "FIX_MTE3": {"from": "FIX", "to": "MTE3", "desc": "Fixpipe 完成，通知 MTE3"},
}


def parse_sync_output(log_content: str) -> List[SyncError]:
    """解析同步调试输出，提取所有错误信息

    支持格式：
    - v4 多错误格式:
      [SYNC DEBUG] Found N error(s):
      [SYNC DEBUG] ERROR 1: WAIT on UNSET (HE=4 eid=0) x 10 times
        WAIT at F1:L100, prev SET at F2:L50
    - v3 单错误格式:
      [SYNC DEBUG] ERROR: WAIT on UNSET (HE=4 eid=0)
        WAIT at F1:L100, prev SET at F2:L50

    Returns:
        List[SyncError]: 错误列表，空列表表示无错误或解析失败
    """
    errors = []

    # 检查是否是 OK
    if "[SYNC DEBUG] OK: all sync calls are correct" in log_content:
        return errors

    # v4 多错误格式
    # [SYNC DEBUG] ERROR 1: WAIT on UNSET (HE=4 eid=0) x 10 times
    v4_pattern = re.compile(
        r'\[SYNC DEBUG\] ERROR (\d+): (WAIT on UNSET|WAIT on NEVER-SET|SET on SET)\s*\(HE=(\d+)\s+eid=(\d+)\)(?:\s+x\s+(\d+)\s+times)?'
    )

    v4_matches = v4_pattern.findall(log_content)
    if v4_matches:
        for match in v4_matches:
            error_index = int(match[0])
            error_type = match[1]
            hard_event = int(match[2])
            event_id = int(match[3])
            count = int(match[4]) if match[4] else 1

            # 查找对应的行号信息（在错误行之后）
            # 找到这个错误在文本中的位置
            error_str = f'[SYNC DEBUG] ERROR {error_index}:'
            error_pos = log_content.find(error_str)
            if error_pos != -1:
                # 提取从这个位置到下一个 ERROR 或文本结束的内容
                next_error_pos = log_content.find('[SYNC DEBUG] ERROR', error_pos + 1)
                if next_error_pos == -1:
                    error_block = log_content[error_pos:]
                else:
                    error_block = log_content[error_pos:next_error_pos]

                # 解析行号信息
                line_match = re.search(
                    r'(WAIT|SET) at F(\d+):L(\d+)(?:,\s*prev SET at F(\d+):L(\d+))?',
                    error_block
                )

                if line_match:
                    error_file_id = int(line_match.group(2))
                    error_line = int(line_match.group(3))
                    prev_set_file_id = int(line_match.group(4)) if line_match.group(4) else None
                    prev_set_line = int(line_match.group(5)) if line_match.group(5) else None
                else:
                    error_file_id = 0
                    error_line = 0
                    prev_set_file_id = None
                    prev_set_line = None

                # 解析建议
                suggestion_match = re.search(r'=> (.+)', error_block)
                suggestion = suggestion_match.group(1) if suggestion_match else None

                errors.append(SyncError(
                    error_index=error_index,
                    error_type=error_type,
                    hard_event=hard_event,
                    event_id=event_id,
                    error_file_id=error_file_id,
                    error_line=error_line,
                    prev_set_file_id=prev_set_file_id,
                    prev_set_line=prev_set_line,
                    count=count,
                    suggestion=suggestion
                ))

        return errors

    # v3 单错误格式（向后兼容）
    # [SYNC DEBUG] ERROR: WAIT on UNSET (HE=4 eid=0)
    v3_match = re.search(
        r'\[SYNC DEBUG\] ERROR: (WAIT on UNSET|WAIT on NEVER-SET|SET on SET)\s*\(HE=(\d+)\s+eid=(\d+)\)',
        log_content
    )
    if v3_match:
        error_type = v3_match.group(1)
        hard_event = int(v3_match.group(2))
        event_id = int(v3_match.group(3))

        # 匹配位置信息
        line_match = re.search(
            r'(WAIT|SET) at F(\d+):L(\d+)(?:,\s*prev SET at F(\d+):L(\d+))?',
            log_content
        )

        if line_match:
            error_file_id = int(line_match.group(2))
            error_line = int(line_match.group(3))
            prev_set_file_id = int(line_match.group(4)) if line_match.group(4) else None
            prev_set_line = int(line_match.group(5)) if line_match.group(5) else None
        else:
            error_file_id = 0
            error_line = 0
            prev_set_file_id = None
            prev_set_line = None

        # 匹配建议
        suggestion_match = re.search(r'=> (.+)', log_content)
        suggestion = suggestion_match.group(1) if suggestion_match else None

        errors.append(SyncError(
            error_index=1,
            error_type=error_type,
            hard_event=hard_event,
            event_id=event_id,
            error_file_id=error_file_id,
            error_line=error_line,
            prev_set_file_id=prev_set_file_id,
            prev_set_line=prev_set_line,
            count=1,
            suggestion=suggestion
        ))

    return errors


def load_file_map(operator_dir: Path) -> Dict[int, Path]:
    """加载文件编号映射

    查找 sync_file_map.json 的位置（可能在 basic_modules 或 op_kernel）

    Returns:
        Dict[int, Path]: {file_id: 文件绝对路径}
    """
    file_map = {}

    # 查找 file_map.json 的可能位置
    possible_paths = [
        operator_dir / "basic_modules" / "sync_file_map.json",
        operator_dir / "op_kernel" / "sync_file_map.json",
    ]

    file_map_path = None
    for p in possible_paths:
        if p.exists():
            file_map_path = p
            break

    if not file_map_path:
        return file_map

    try:
        with open(file_map_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # JSON 的 key 是字符串，转换为 int
            for file_id_str, rel_path in data.items():
                file_id = int(file_id_str)
                file_map[file_id] = operator_dir / rel_path
    except Exception as e:
        print(f"警告: 加载 file_map.json 失败: {e}")

    return file_map


def restore_original_code(tracker_line: str) -> str:
    """
    将 TrackerSet/TrackerWait 还原为原始的 SetFlag/WaitFlag 代码

    例如：
    TrackerSet(HE_MTE2_V, event_id, 1, __LINE__) → SetFlag<HardEvent::MTE2_V>(event_id)
    TrackerWait(HE_MTE3_MTE2, 0, 2, __LINE__) → WaitFlag<HardEvent::MTE3_MTE2>(0)
    """
    # 匹配 TrackerSet/TrackerWait（带 file_id 参数）
    set_match = re.match(r'^\s*TrackerSet\s*\(\s*HE_(\w+)\s*,\s*([^,]+)\s*,\s*\d+\s*,\s*__LINE__\s*\)', tracker_line)
    wait_match = re.match(r'^\s*TrackerWait\s*\(\s*HE_(\w+)\s*,\s*([^,]+)\s*,\s*\d+\s*,\s*__LINE__\s*\)', tracker_line)

    indent = tracker_line[:len(tracker_line) - len(tracker_line.lstrip())]

    if set_match:
        he_name = set_match.group(1)
        eid = set_match.group(2).strip()
        return f'{indent}SetFlag<HardEvent::{he_name}>({eid});'

    if wait_match:
        he_name = wait_match.group(1)
        eid = wait_match.group(2).strip()
        return f'{indent}WaitFlag<HardEvent::{he_name}>({eid});'

    # 如果不是 Tracker 调用，返回原行
    return tracker_line


def find_line_in_file(file_path: Path, line_number: int) -> Optional[Tuple[str, str]]:
    """在指定文件中查找指定行号的代码行

    返回: (替换后的代码行, 还原后的原始代码行)
    """
    try:
        lines = file_path.read_text().split('\n')
        if 1 <= line_number <= len(lines):
            line_content = lines[line_number - 1]
            original_code = restore_original_code(line_content)
            return (line_content, original_code)
    except Exception:
        pass
    return None


def get_context_lines(file_path: Path, line_number: int, context: int = 3) -> List[Tuple[int, str]]:
    """获取指定行及其上下文"""
    try:
        lines = file_path.read_text().split('\n')
        start = max(0, line_number - context - 1)
        end = min(len(lines), line_number + context)
        return [(i + 1, lines[i]) for i in range(start, end)]
    except Exception:
        return []


def format_code_snippet(file_path: Path, line_number: int, label: str, highlight: bool = True) -> str:
    """格式化代码片段输出（显示还原后的原始代码）"""
    context_lines = get_context_lines(file_path, line_number)
    if not context_lines:
        return f"  {label}: 无法读取文件内容"

    result = [f"  {label}: {file_path.name}:{line_number}"]
    result.append("  " + "-" * 60)

    for ln, content in context_lines:
        marker = ">>> " if ln == line_number and highlight else "    "
        # 所有包含 Tracker API 的行都还原为原始代码
        if 'TrackerSet' in content or 'TrackerWait' in content:
            restored = restore_original_code(content)
        else:
            restored = content
        result.append(f"  {marker}{ln:4d} | {restored}")

    return "\n".join(result)


def analyze_error(error: SyncError, operator_dir: Path, file_map: Dict[int, Path] = None) -> str:
    """分析单个错误并生成报告

    Args:
        error: 同步错误信息
        operator_dir: 算子目录
        file_map: 文件编号映射 {file_id: 文件路径}
    """
    he_name = HARDEVENT_NAMES.get(error.hard_event, f"UNKNOWN({error.hard_event})")
    he_info = HARDEVENT_INFO.get(he_name, {})

    report = []
    report.append(f"错误 #{error.error_index}: {error.error_type}")
    if error.count > 1:
        report.append(f"  出现次数: {error.count} 次")
    report.append(f"  HardEvent: {he_name} (索引={error.hard_event})")

    if he_info:
        report.append(f"    - 触发方: {he_info.get('from', '?')}")
        report.append(f"    - 等待方: {he_info.get('to', '?')}")
        report.append(f"    - 语义: {he_info.get('desc', '?')}")

    report.append(f"  Event ID: {error.event_id}")

    # 查找错误位置的代码
    error_file = None
    if file_map and error.error_file_id in file_map:
        error_file = file_map[error.error_file_id]

    if error_file and error_file.exists():
        result = find_line_in_file(error_file, error.error_line)
        if result:
            report.append(format_code_snippet(error_file, error.error_line, "  错误位置"))
            report.append(f"      原始代码: {result[1].strip()}")
        else:
            report.append(f"  错误位置: {error_file.name}:{error.error_line}")
    else:
        report.append(f"  错误位置: F{error.error_file_id}:L{error.error_line}")
        if not file_map:
            report.append("  (未找到 sync_file_map.json，请确认注入脚本是否正确执行)")

    # 查找上一次 SET 的位置
    if error.prev_set_line:
        prev_file = None
        if file_map and error.prev_set_file_id in file_map:
            prev_file = file_map[error.prev_set_file_id]

        if prev_file and prev_file.exists():
            result = find_line_in_file(prev_file, error.prev_set_line)
            if result:
                report.append(format_code_snippet(prev_file, error.prev_set_line, "  上一次 SET"))
                report.append(f"      原始代码: {result[1].strip()}")
            else:
                report.append(f"  上一次 SET: {prev_file.name}:{error.prev_set_line}")
        else:
            report.append(f"  上一次 SET: F{error.prev_set_file_id}:L{error.prev_set_line}")
    else:
        report.append("  上一次 SET: 从未 SET 过")

    # 输出建议
    if error.suggestion:
        report.append(f"  调试器建议: {error.suggestion}")

    # 根据错误类型给出修复建议
    report.append("")
    if error.error_type == "WAIT on UNSET":
        report.append("  【修复建议】")
        report.append("  1. 检查上一次 SET 和本次 WAIT 之间的逻辑")
        report.append("  2. 如果是 PingPong 模式，检查初始化的 SET 数量是否与循环匹配")
        report.append("  3. 确保每条执行路径都有正确的 SET→WAIT 顺序")
    elif error.error_type == "WAIT on NEVER-SET":
        report.append("  【修复建议】")
        report.append("  1. 在本次 WAIT 之前添加对应的 SET")
        report.append("  2. 如果是 PingPong 模式，确保初始化时预 SET 所有需要的 event")
        report.append("  3. 检查条件分支，确保所有路径都有 SET")
    elif error.error_type == "SET on SET":
        report.append("  【修复建议】")
        report.append("  1. 检查上一次 SET 和本次 SET 之间是否缺少 WAIT")
        report.append("  2. 确保 SET→WAIT→SET 的循环顺序正确")
        report.append("  3. 检查分支逻辑，避免重复 SET")

    return "\n".join(report)


def analyze_errors(errors: List[SyncError], operator_dir: Path, file_map: Dict[int, Path] = None) -> str:
    """分析所有错误并生成完整报告

    Args:
        errors: 错误列表
        operator_dir: 算子目录
        file_map: 文件编号映射
    """
    report = []
    report.append("=" * 70)
    report.append("同步错误分析报告")
    report.append("=" * 70)
    report.append(f"发现 {len(errors)} 个错误")
    report.append("")

    for i, error in enumerate(errors):
        if i > 0:
            report.append("-" * 70)
            report.append("")
        report.append(analyze_error(error, operator_dir, file_map))

    report.append("")
    report.append("=" * 70)

    return "\n".join(report)


def main():
    parser = argparse.ArgumentParser(
        description="AscendC 核内同步追踪器 - 输出分析脚本 v4"
    )
    parser.add_argument("log_file", help="测试输出日志文件路径")
    parser.add_argument("operator_dir", help="算子目录路径")

    args = parser.parse_args()

    log_path = Path(args.log_file)
    operator_path = Path(args.operator_dir).resolve()

    if not log_path.exists():
        print(f"错误: 日志文件不存在 {log_path}")
        return

    if not operator_path.exists():
        print(f"错误: 算子目录不存在 {operator_path}")
        return

    log_content = log_path.read_text()
    errors = parse_sync_output(log_content)

    if not errors:
        if "[SYNC DEBUG] OK: all sync calls are correct" in log_content:
            print("=" * 70)
            print("同步检查结果: OK")
            print("=" * 70)
            print("所有同步调用都是正确的，没有发现问题。")
        else:
            print("未找到 [SYNC DEBUG] 输出，请确认测试是否正确运行。")
        return

    # 加载文件映射
    file_map = load_file_map(operator_path)
    if file_map:
        print(f"已加载文件映射: {len(file_map)} 个文件")
    else:
        print("提示: 未找到 sync_file_map.json，将使用搜索方式定位文件")

    report = analyze_errors(errors, operator_path, file_map)
    print(report)


if __name__ == "__main__":
    main()