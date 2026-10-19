#!/usr/bin/env python3
"""
MTE Timeline Viewer - Display simplified transfer information for a single core

Usage: python show_timeline.py <timeline_json> [core] [--no-detail]
  core: "veccore0" or "veccore1" (default: veccore0)
  --no-detail: Hide detailed address ranges, show compact view

Display fields: timestamp, direction, source range, destination range,
                 burst_length, burst_count, src_stride, dst_stride
"""

import json
import sys
from pathlib import Path
from typing import Optional


def load_timeline(json_file: str) -> dict:
    """加载 timeline 数据。"""
    with open(json_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_source_range(source_addresses: list, compact: bool = False) -> str:
    """获取源地址范围。"""
    if not source_addresses:
        return "N/A"

    if len(source_addresses) == 1:
        addr = source_addresses[0]['address']
        size = source_addresses[0]['size']
        if compact:
            return f"{addr}"
        return f"{addr} ({size}B)"

    # 多地址：获取范围
    first_addr = source_addresses[0]['address']
    last_addr = source_addresses[-1]['address']
    total_size = sum(s['size'] for s in source_addresses)

    if compact:
        return f"{first_addr}~{last_addr}"
    return f"{first_addr} ~ {last_addr} ({total_size}B)"


def format_for_display(transfer: dict, compact: bool = False) -> dict:
    """格式化用于展示的数据。"""
    src_range = get_source_range(transfer['source_addresses'], compact)
    end_ts = transfer.get('end_timestamp')
    if end_ts is not None:
        time_str = f"{transfer['timestamp']}-{end_ts}"
    else:
        time_str = str(transfer['timestamp'])
    return {
        'timestamp': transfer['timestamp'],
        'end_timestamp': end_ts,
        'time_str': time_str,
        'direction': transfer['direction'],
        'source_range': src_range,
        'dest_range': transfer['destination_range'] if not compact else transfer['destination_range'].split('(')[0].strip(),
        'burst_length': transfer['burst_length'],
        'burst_count': transfer['burst_count'],
        'src_stride': transfer['src_stride'],
        'dst_stride': transfer['dst_stride'],
    }


def print_table(transfers: list, core_name: str, compact: bool = False):
    """以表格形式打印数据。"""
    print("=" * 110)
    print(f"MTE Timeline - {core_name}")
    print("=" * 110)

    if not transfers:
        print(f"No transfers found for {core_name}")
        return

    # 简洁模式：只显示关键信息
    if compact:
        print(f"{'ID':<4} {'Time':<14} {'Dir':<9} {'Src':<18} {'Dst':<35} {'Size':<6} {'Burst':<10}")
        print("-" * 110)

        for i, t in enumerate(transfers, 1):
            formatted = format_for_display(t, compact)
            src = formatted['source_range'][:18]
            dst = formatted['dest_range'][:35]
            total_size = t.get('veccore_total_size_bytes', t.get('total_size_bytes', 0))
            burst = f"L={formatted['burst_length']},C={formatted['burst_count']}"

            print(f"{i:<4} {formatted['time_str']:<14} {formatted['direction']:<9} "
                  f"{src:<18} {dst:<35} {total_size:<6} {burst:<10}")
    else:
        # 详细模式：显示完整信息
        print(f"{'Time':<14} {'Dir':<10} {'Source':<28} {'Dest':<28} {'Burst L':<7} {'Burst C':<7} {'Src Str':<7} {'Dst Str':<7}")
        print("-" * 110)

        for t in transfers:
            formatted = format_for_display(t, compact)
            print(f"{formatted['time_str']:<14} {formatted['direction']:<10} "
                  f"{formatted['source_range']:<28} {formatted['dest_range']:<28} "
                  f"{formatted['burst_length']:<7} {formatted['burst_count']:<7} "
                  f"{formatted['src_stride']:<7} {formatted['dst_stride']:<7}")

    # 统计信息
    print("-" * 110)
    total_size = sum(t.get('veccore_total_size_bytes', t.get('total_size_bytes', 0)) for t in transfers)
    print(f"Total: {len(transfers)} instructions, {total_size} bytes")
    print("=" * 110)


def show_timeline(data: dict = None, json_file: str = None, core: str = 'veccore0',
                  compact: bool = False, output_file: Optional[str] = None):
    """统一入口：接受 dict 或文件路径，输出到 stdout 或文件。"""
    if data is None:
        if json_file is None:
            raise ValueError("Must provide either data or json_file")
        data = load_timeline(json_file)

    by_veccore = data.get('by_veccore', {})
    if core not in by_veccore:
        raise ValueError(f"No data found for core '{core}'. Available: {list(by_veccore.keys())}")

    transfers = by_veccore[core]

    if output_file:
        import io
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            print_table(transfers, core, compact)
        finally:
            sys.stdout = old_stdout
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(buf.getvalue())
    else:
        print_table(transfers, core, compact)


def main():
    if len(sys.argv) < 2:
        print("Usage: python show_timeline.py <timeline_json> [core] [--no-detail]")
        print("  core: veccore0 or veccore1 (default: veccore0)")
        print("  --no-detail: Show compact view (for many entries)")
        sys.exit(1)

    json_file = sys.argv[1]
    core = 'veccore0'
    compact = False

    # 解析参数
    for arg in sys.argv[1:]:
        if arg in ['veccore0', 'veccore1']:
            core = arg
        if arg == '--no-detail':
            compact = True

    # 验证 core 参数
    if core not in ['veccore0', 'veccore1']:
        print(f"Error: core must be 'veccore0' or 'veccore1', got '{core}'")
        sys.exit(1)

    # 加载数据
    print(f"Loading timeline data: {json_file}")
    data = load_timeline(json_file)

    by_veccore = data.get('by_veccore', {})

    if core not in by_veccore:
        print(f"Error: No data found for core '{core}'")
        print(f"Available cores: {list(by_veccore.keys())}")
        sys.exit(1)

    transfers = by_veccore[core]

    # 打印统计摘要
    print(f"Core: {core}")
    print(f"Transfer count: {len(transfers)}")
    if transfers:
        print(f"Timestamp range: {transfers[0]['timestamp']} ~ {transfers[-1]['timestamp']}")
        print(f"Total bytes: {sum(t['total_size_bytes'] for t in transfers)}")
    print()

    # 输出表格
    print_table(transfers, core, compact)


if __name__ == '__main__':
    main()