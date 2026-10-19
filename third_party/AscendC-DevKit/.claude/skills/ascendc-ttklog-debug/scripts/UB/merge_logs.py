#!/usr/bin/env python3
"""
MTE + UB 日志合并工具 v2

用 MTE Timeline 的准确数据修正/补充 UB 分析日志中不完整的 MTE_W 记录。
输出格式与 show_by_buffer.py 保持一致。

Usage:
    python merge_logs.py <mte_timeline.txt> <ub_analysis.log> [-o output.log]
"""

import re
import sys
import argparse
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional


@dataclass
class MTERecord:
    """MTE timeline 记录"""
    time: int
    time_end: int           # MTE retire 时间戳（结束时间）
    direction: str      # "GM -> UB" or "UB -> GM"
    ub_start: int
    ub_end: int
    ub_size: int
    gm_info: str        # GM 地址信息（用于显示）

    @property
    def unit(self) -> str:
        return 'MTE_W' if self.direction == "GM -> UB" else 'MTE_R'

    @property
    def op_type(self) -> str:
        return 'WR' if self.direction == "GM -> UB" else 'RD'


@dataclass
class UBRecord:
    """UB 分析记录"""
    time_start: int
    time_end: int
    unit: str
    op_type: str
    addr_start: int
    addr_end: int
    size: int
    count: int
    instr_id: str
    raw_line: str = ""  # 原始行


def _parse_time_field(time_str: str) -> Tuple[int, int]:
    """解析时间字段，支持 'start-end' 和 'start' 两种格式"""
    if '-' in time_str:
        parts = time_str.split('-', 1)
        return int(parts[0]), int(parts[1])
    t = int(time_str)
    return t, t


def parse_mte_timeline(filepath: str) -> List[MTERecord]:
    """解析 MTE timeline 文本文件"""
    records = []

    # GM -> UB: 支持单地址和地址范围两种格式，时间支持 start-end
    re_gm_ub = re.compile(
        r'^(\d+(?:-\d+)?)\s+(GM -> UB)\s+(\S+(?:\s+~\s+\S+)?)\s+\((\d+)B\)\s+'
        r'(0x[0-9a-fA-F]+)\s+\+\s+(\d+)B\s+=\s+(0x[0-9a-fA-F]+)'
    )
    # UB -> GM: 支持单地址和地址范围两种格式
    re_ub_gm = re.compile(
        r'^(\d+(?:-\d+)?)\s+(UB -> GM)\s+(\S+(?:\s+~\s+\S+)?)\s+\((\d+)B\)\s+'
        r'(\S+)\s+\+\s+(\d+)B\s+=\s+(\S+)'
    )

    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()

            # GM -> UB
            m = re_gm_ub.match(line)
            if m:
                time_start, time_end = _parse_time_field(m.group(1))
                ub_start = int(m.group(5), 16)
                ub_end = int(m.group(7), 16)
                # 忽略初始化搬运（地址 0x0，size <= 128）
                if ub_start == 0 and (ub_end - ub_start) <= 128:
                    continue
                records.append(MTERecord(
                    time=time_start,
                    time_end=time_end,
                    direction=m.group(2),
                    ub_start=ub_start,
                    ub_end=ub_end,
                    ub_size=ub_end - ub_start,
                    gm_info=m.group(3)
                ))
                continue

            # UB -> GM
            m = re_ub_gm.match(line)
            if m:
                time_start, time_end = _parse_time_field(m.group(1))
                ub_addr_str = m.group(3)
                # 支持地址范围格式 "0x3bfa0 ~ 0x3c120"
                if '~' in ub_addr_str:
                    ub_addr = int(ub_addr_str.split('~')[0].strip(), 16)
                else:
                    ub_addr = int(ub_addr_str, 16)
                ub_size = int(m.group(4))
                records.append(MTERecord(
                    time=time_start,
                    time_end=time_end,
                    direction=m.group(2),
                    ub_start=ub_addr,
                    ub_end=ub_addr + ub_size,
                    ub_size=ub_size,
                    gm_info=m.group(5)
                ))

    return records


def parse_ub_analysis(filepath: str) -> Tuple[Dict[str, List[UBRecord]], Dict[str, dict], List[str]]:
    """
    解析 UB 分析日志文件
    返回: (按buffer分组的记录, buffer信息, 其他行)
    """
    records_by_buffer = {}
    buffer_info = {}
    other_lines = []
    current_buffer = None
    in_record_section = False

    # Buffer 标题: Buffer: xQue_0 (0x00000 - 0x1d3a0, 119840B)
    re_buffer = re.compile(r'Buffer:\s+(\S+)\s+\((0x[0-9a-fA-F]+)\s+-\s+(0x[0-9a-fA-F]+),\s+(\d+)B\)')
    # MTE 记录行: 11325-11349      MTE_W        WR         0x00aa0 - 0x00da0             768     22 43348
    re_record = re.compile(
        r'^\s*(\d+)-(\d+)\s+(MTE_[WR]|MTE_R)\s+(\S+)\s+'
        r'(0x[0-9a-fA-F]+)\s+-\s+(0x[0-9a-fA-F]+)\s+'
        r'(\d+)\s+(\d+)\s+(\S+)'
    )
    # VEC/AIV 聚合行（支持 [VEC/AIV]、[VEC]、[AIV] 三种格式）
    re_vec = re.compile(
        r'^\s*(\d+)-(\d+)\s+\[(VEC(?:/AIV)?|AIV)\]\s+(\S+)\s+'
        r'(0x[0-9a-fA-F]+)\s+-\s+(0x[0-9a-fA-F]+)\s+'
        r'(\d+)\s+(\d+)\s+(-)'
    )
    # 分隔线
    re_separator = re.compile(r'^[-=]+$')

    with open(filepath, 'r') as f:
        lines = f.readlines()

    for i, line in enumerate(lines):
        stripped = line.rstrip()

        # 检查 buffer 标题
        m = re_buffer.search(stripped)
        if m:
            current_buffer = m.group(1)
            buffer_info[current_buffer] = {
                'start': int(m.group(2), 16),
                'end': int(m.group(3), 16),
                'size': int(m.group(4))
            }
            if current_buffer not in records_by_buffer:
                records_by_buffer[current_buffer] = []
            in_record_section = False
            continue

        # 检查是否进入记录区域（在表头分隔线之后）
        if current_buffer and re_separator.match(stripped) and '时间范围' in lines[i-1] if i > 0 else False:
            in_record_section = True
            continue

        if not current_buffer or not in_record_section:
            continue

        # 遇到下一个分隔块或越界检测，结束记录区域
        if stripped.startswith('✓') or stripped.startswith('✗') or stripped.startswith('⚠'):
            in_record_section = False
            continue

        # 匹配 MTE 记录
        m = re_record.match(stripped)
        if m:
            records_by_buffer[current_buffer].append(UBRecord(
                time_start=int(m.group(1)),
                time_end=int(m.group(2)),
                unit=m.group(3),
                op_type=m.group(4),
                addr_start=int(m.group(5), 16),
                addr_end=int(m.group(6), 16),
                size=int(m.group(7)),
                count=int(m.group(8)),
                instr_id=m.group(9),
                raw_line=stripped
            ))
            continue

        # 匹配 VEC/AIV 聚合行
        m = re_vec.match(stripped)
        if m:
            vec_label = f'[{m.group(3)}]'  # [VEC], [AIV], or [VEC/AIV]
            records_by_buffer[current_buffer].append(UBRecord(
                time_start=int(m.group(1)),
                time_end=int(m.group(2)),
                unit=vec_label,
                op_type=m.group(4),
                addr_start=int(m.group(5), 16),
                addr_end=int(m.group(6), 16),
                size=int(m.group(7)),
                count=int(m.group(8)),
                instr_id='-',
                raw_line=stripped
            ))

    return records_by_buffer, buffer_info, other_lines


def find_buffer_for_addr(addr: int, buffer_info: Dict) -> Optional[str]:
    """根据地址找到对应的 buffer"""
    for name, info in buffer_info.items():
        if info['start'] <= addr < info['end']:
            return name
    return None


def merge_records(mte_records: List[MTERecord],
                  ub_records: Dict[str, List[UBRecord]],
                  buffer_info: Dict) -> Dict[str, List]:
    """
    合并 MTE 和 UB 记录
    - MTE_W/MTE_R 记录以 MTE 为准
    - VEC/AIV 保留
    """
    merged = {}

    for buffer_name, info in buffer_info.items():
        merged[buffer_name] = []

        # 获取该 buffer 的 MTE 记录
        buffer_mte = [m for m in mte_records
                      if info['start'] <= m.ub_start < info['end']]

        # 获取该 buffer 的 UB 记录
        buffer_ub = ub_records.get(buffer_name, [])

        # 分离 VEC/AIV 和 MTE 记录
        vec_records = [u for u in buffer_ub if u.unit in ('[VEC/AIV]', '[VEC]', '[AIV]')]
        ub_mte_records = [u for u in buffer_ub if u.unit in ('MTE_W', 'MTE_R')]

        # 用 MTE 记录替换 UB 中的 MTE 记录
        # 策略：对于每个 MTE 记录，找到时间和地址重叠的 UB MTE 记录并替换
        used_ub_indices = set()

        for mte in buffer_mte:
            # 查找可以被替换的 UB 记录
            for i, ub in enumerate(ub_mte_records):
                if i in used_ub_indices:
                    continue
                # 检查地址重叠
                addr_overlap = (ub.addr_start <= mte.ub_start <= ub.addr_end or
                               mte.ub_start <= ub.addr_start <= mte.ub_end)
                # 检查单元类型匹配
                unit_match = (mte.unit == ub.unit)
                # 检查时间接近（500 时间单位内）
                time_close = abs(ub.time_start - mte.time) < 1000

                if addr_overlap and unit_match and time_close:
                    used_ub_indices.add(i)
                    break

            # 添加 MTE 记录（转换为统一格式）
            merged[buffer_name].append({
                'type': 'MTE',
                'time': mte.time,
                'time_end': mte.time_end,
                'unit': mte.unit,
                'op_type': mte.op_type,
                'addr_start': mte.ub_start,
                'addr_end': mte.ub_end,
                'size': mte.ub_size,
                'count': 1,
                'instr_id': '-'
            })

        # 添加未被替换的 UB MTE 记录
        for i, ub in enumerate(ub_mte_records):
            if i not in used_ub_indices:
                merged[buffer_name].append({
                    'type': 'UB',
                    'time': ub.time_start,
                    'time_end': ub.time_end,
                    'unit': ub.unit,
                    'op_type': ub.op_type,
                    'addr_start': ub.addr_start,
                    'addr_end': ub.addr_end,
                    'size': ub.size,
                    'count': ub.count,
                    'instr_id': ub.instr_id
                })

        # 添加 VEC/AIV 记录
        for ub in vec_records:
            merged[buffer_name].append({
                'type': 'UB',
                'time': ub.time_start,
                'time_end': ub.time_end,
                'unit': ub.unit,
                'op_type': ub.op_type,
                'addr_start': ub.addr_start,
                'addr_end': ub.addr_end,
                'size': ub.size,
                'count': ub.count,
                'instr_id': ub.instr_id
            })

        # 按时间排序
        merged[buffer_name].sort(key=lambda x: x['time'])

    return merged


def check_bound_errors(records: List[Dict], buffer_info: dict) -> Tuple[List, List]:
    """检查越界错误"""
    errors = []   # 写越界 (ERROR)
    warnings = [] # 读越界 (WARNING)

    start = buffer_info['start']
    end = buffer_info['end']

    for r in records:
        # 只检查 MTE 记录
        if r['unit'] not in ('MTE_W', 'MTE_R'):
            continue

        addr_start = r['addr_start']
        addr_end = r['addr_end']

        # 检查下溢
        if addr_start < start:
            overflow = start - addr_start
            msg = f"下溢 {overflow}B (访问从 0x{addr_start:x}, buffer 起始于 0x{start:x})"
            if r['op_type'] == 'WR':
                errors.append((r, msg))
            else:
                warnings.append((r, msg))

        # 检查上溢
        if addr_end > end:
            overflow = addr_end - end
            msg = f"上溢 {overflow}B (访问到 0x{addr_end:x}, buffer 结束于 0x{end:x})"
            if r['op_type'] == 'WR':
                errors.append((r, msg))
            else:
                warnings.append((r, msg))

    return errors, warnings


def parse_ub_bound_checks(filepath: str) -> Dict[str, Tuple[List[str], List[str]]]:
    """从 UB 分析日志中提取越界检查结果"""
    bound_checks = {}
    current_buffer = None
    current_errors = []
    current_warnings = []

    re_buffer = re.compile(r'Buffer:\s+(\S+)\s+\(')
    re_error = re.compile(r'^\s*\[ERROR\](.+)$')
    re_warning = re.compile(r'^\s*\[WARNING\](.+)$')
    re_check_header = re.compile(r'^\s*[✗✓⚠]')

    with open(filepath, 'r') as f:
        lines = f.readlines()

    in_check_section = False

    for line in lines:
        stripped = line.rstrip()

        # 检查 buffer 标题
        m = re_buffer.search(stripped)
        if m:
            # 保存上一个 buffer 的结果
            if current_buffer:
                bound_checks[current_buffer] = (current_errors, current_warnings)
            current_buffer = m.group(1)
            current_errors = []
            current_warnings = []
            in_check_section = False
            continue

        # 检查是否进入越界检查区域
        if re_check_header.match(stripped):
            in_check_section = True

        if not in_check_section:
            continue

        # 提取错误和警告
        m = re_error.match(stripped)
        if m:
            current_errors.append(stripped)
            continue

        m = re_warning.match(stripped)
        if m:
            current_warnings.append(stripped)

    # 保存最后一个 buffer
    if current_buffer:
        bound_checks[current_buffer] = (current_errors, current_warnings)

    return bound_checks


def print_merged_analysis(merged: Dict, buffer_info: Dict,
                          ub_bound_checks: Dict[str, Tuple[List[str], List[str]]],
                          file=sys.stdout):
    """按 ub_analysis 格式输出合并结果"""

    # 统计
    total_records = sum(len(v) for v in merged.values())
    print("=" * 90, file=file)
    print("  MTE + UB 合并后分析结果", file=file)
    print("=" * 90, file=file)
    print(file=file)

    for buffer_name, info in buffer_info.items():
        records = merged.get(buffer_name, [])

        print("=" * 90, file=file)
        print(f"  Buffer: {buffer_name} (0x{info['start']:05x} - 0x{info['end']:05x}, {info['size']}B)", file=file)
        print("=" * 90, file=file)

        if not records:
            print("  无访问记录", file=file)
            print(file=file)
            continue

        # 统计
        reads = [r for r in records if r['op_type'] in ('RD', 'R') or 'R' in str(r['op_type'])]
        writes = [r for r in records if r['op_type'] in ('WR', 'W') or 'W' in str(r['op_type'])]
        total_ops = sum(r['count'] for r in records)

        print(f"  统计: {len(records)} 个合并块, {total_ops} 次操作", file=file)
        print("-" * 90, file=file)

        # 表头
        print(f"  {'时间范围':<16} {'单元':<12} {'类型':<10} {'地址范围':<24} "
              f"{'大小':>8} {'操作数':>6} {'指令ID'}", file=file)
        print("-" * 90, file=file)

        # 记录
        for r in records:
            if r['time'] == r['time_end']:
                time_str = str(r['time'])
            else:
                time_str = f"{r['time']}-{r['time_end']}"

            addr_str = f"0x{r['addr_start']:05x} - 0x{r['addr_end']:05x}"

            print(f"  {time_str:<16} {r['unit']:<12} {r['op_type']:<10} {addr_str:<24} "
                  f"{r['size']:>8} {r['count']:>6} {r['instr_id']}", file=file)

        # 越界检查
        print(file=file)

        # MTE 越界检查
        mte_errors, mte_warnings = check_bound_errors(records, info)

        # UB (VEC) 越界检查 - 从原日志复用
        ub_errors, ub_warnings = ub_bound_checks.get(buffer_name, ([], []))

        # 合并输出
        all_errors = mte_errors + [(None, e) for e in ub_errors]
        all_warnings = mte_warnings + [(None, w) for w in ub_warnings]

        if all_errors:
            print(f"  ✗ 越界错误: 发现 {len(all_errors)} 个写越界 (ERROR)", file=file)
            for item in all_errors:
                if item[0] is None:
                    # 来自 UB 日志的原始错误
                    print(f"  {item[1]}", file=file)
                else:
                    # MTE 越界
                    r, msg = item
                    print(f"    [ERROR] Time {r['time']}: {r['op_type']} 0x{r['addr_start']:x} + {r['size']}B - {msg}", file=file)

        if all_warnings:
            print(f"  ⚠ 越界警告: 发现 {len(all_warnings)} 个读越界 (WARNING)", file=file)
            for item in all_warnings:
                if item[0] is None:
                    # 来自 UB 日志的原始警告
                    print(f"  {item[1]}", file=file)
                else:
                    # MTE 越界
                    r, msg = item
                    print(f"    [WARNING] Time {r['time']}: {r['op_type']} 0x{r['addr_start']:x} + {r['size']}B - {msg}", file=file)

        if not all_errors and not all_warnings:
            print(f"  ✓ 越界检测: 无越界访问", file=file)

        print(file=file)


def main():
    parser = argparse.ArgumentParser(description='MTE + UB 日志合并工具')
    parser.add_argument('mte_timeline', help='MTE timeline 文本文件 (show_timeline.py 输出)')
    parser.add_argument('ub_analysis', help='UB 分析日志文件 (show_by_buffer.py 输出)')
    parser.add_argument('-o', '--output', help='输出文件路径')

    args = parser.parse_args()

    # 解析文件
    print(f"解析 MTE timeline: {args.mte_timeline}", file=sys.stderr)
    mte_records = parse_mte_timeline(args.mte_timeline)
    print(f"  找到 {len(mte_records)} 条 MTE 记录（已忽略初始化搬运）", file=sys.stderr)

    print(f"解析 UB 分析日志: {args.ub_analysis}", file=sys.stderr)
    ub_records, buffer_info, _ = parse_ub_analysis(args.ub_analysis)
    total_ub = sum(len(v) for v in ub_records.values())
    print(f"  找到 {total_ub} 条 UB 记录", file=sys.stderr)

    # 合并
    print("合并记录...", file=sys.stderr)
    merged = merge_records(mte_records, ub_records, buffer_info)

    # 输出
    output_file = open(args.output, 'w') if args.output else sys.stdout

    # 解析 UB 日志中的越界检查结果（VEC 部分）
    print("解析 UB 越界检查结果...", file=sys.stderr)
    ub_bound_checks = parse_ub_bound_checks(args.ub_analysis)

    try:
        print_merged_analysis(merged, buffer_info, ub_bound_checks, output_file)
    finally:
        if args.output:
            output_file.close()
            print(f"结果已保存到: {args.output}", file=sys.stderr)


if __name__ == '__main__':
    main()
