#!/usr/bin/env python3
"""
UB Memory Analyzer - 按时间维度展示

按时间顺序显示所有内存访问，展示并行执行的情况。

Usage:
    python show_by_time.py <dump_file> [options]

Options:
    --unit          过滤执行单元 (MTE_W, MTE_R, VEC_LSU, ALL)
    --buffer, -b    过滤 buffer (如: xQue_0, outQue_)
    --time-range    时间范围过滤 (如: 10000-20000)
    --no-merge      不合并操作
    --time-gap      合并时间间隔阈值 (默认: 10)
    --addr-gap      合并地址间隔阈值 (默认: 32)
    --merge-mte     按 instr_id 合并 MTE 操作（一条指令合并为一条记录）
    --limit         最大显示条数 (默认: 无限制)
    --mte-focus     MTE 聚焦模式: 只显示 MTE 详情，VEC_LSU 聚合为范围
    --output, -o    输出到文件
"""

import sys
import json
import argparse
from ub_analyzer import (
    parse_and_analyze, MEMORY_MAP, UBAnalyzer,
    MergedAccess, init_from_json, find_buffer
)


# 单元分类
UNIT_CATEGORY = {
    'MTE_W': 'MTE_W',
    'MTE_R': 'MTE_R',
    'VEC_LSU_R': 'VEC_LSU',
    'VEC_LSU_W': 'VEC_LSU',
    'AIV_SU_R': 'AIV_SU',
    'AIV_SU_W': 'AIV_SU',
}


def format_addr_range(start: int, end: int) -> str:
    """格式化地址范围"""
    return f"0x{start:05x}-0x{end:05x}"


def format_instr_ids(ids: list) -> str:
    """格式化指令 ID 列表"""
    if not ids:
        return "-"
    if len(ids) == 1:
        return str(ids[0])
    return f"{ids[0]}~{ids[-1]}({len(ids)})"


def print_timeline_header(file=sys.stdout):
    """打印时间线表头"""
    print("=" * 110, file=file)
    print("  时间线视图 (按时间排序)", file=file)
    print("=" * 110, file=file)
    print(f"  {'时间范围':<16} {'Buffer':<15} {'单元':<12} {'类型':<10} "
          f"{'地址范围':<24} {'大小':>8} {'操作数':>6} {'指令ID'}", file=file)
    print("-" * 110, file=file)


def print_merged_access(m: MergedAccess, file=sys.stdout):
    """打印单个合并访问"""
    time_str = f"{m.start_time}-{m.end_time}"
    addr_str = format_addr_range(m.addr_start, m.addr_end)
    instr_str = format_instr_ids(m.instr_ids)

    print(f"  {time_str:<16} {m.buffer_name:<15} {m.unit:<12} {m.op_type:<10} "
          f"{addr_str:<24} {m.size:>8} {m.access_count:>6} {instr_str}", file=file)


def print_mte_focus_view(merged_list: list, merge_vec_aiv: bool = False,
                         file=sys.stdout):
    """
    MTE 聚焦视图 - 只显示 MTE 详情，VEC_LSU 聚合为范围
    在两个 MTE 操作之间，将所有 VEC_LSU 操作聚合成一条摘要
    """
    if not merged_list:
        return

    print("=" * 110, file=file)
    print("  MTE 聚焦视图 (VEC_LSU/AIV_SU 聚合显示)", file=file)
    print("=" * 110, file=file)
    print(f"  {'时间范围':<16} {'Buffer':<15} {'单元':<12} {'类型':<10} "
          f"{'地址范围':<24} {'大小':>8} {'操作数':>6}", file=file)
    print("-" * 110, file=file)

    # 按时间排序
    sorted_list = sorted(merged_list, key=lambda m: m.start_time)

    # 分离 MTE 和非 MTE 操作
    mte_ops = []
    vec_ops = []

    for m in sorted_list:
        cat = UNIT_CATEGORY.get(m.unit, m.unit)
        if cat in ('MTE_W', 'MTE_R'):
            mte_ops.append(m)
        else:
            vec_ops.append(m)

    if not mte_ops:
        # 没有 MTE 操作，显示 VEC 摘要
        if vec_ops:
            _print_vec_summary(vec_ops, merge_vec_aiv, file)
        return

    # 按 MTE 操作分段处理
    output_items = []  # (sort_key, is_mte, content)

    # 添加所有 MTE 操作
    for m in mte_ops:
        output_items.append((m.start_time, True, m))

    # 找出每两个相邻 MTE 之间的 VEC 操作
    mte_times = sorted(set(m.start_time for m in mte_ops))

    # 第一个 MTE 之前的 VEC
    before_first = [v for v in vec_ops if v.end_time < mte_times[0]]
    if before_first:
        output_items.append((before_first[0].start_time, False, before_first))

    # 每对 MTE 之间的 VEC
    for i in range(len(mte_times) - 1):
        t1, t2 = mte_times[i], mte_times[i + 1]
        between = [v for v in vec_ops if v.start_time >= t1 and v.end_time <= t2]
        if between:
            # 排序键为中间时间
            sort_key = (t1 + t2) // 2
            output_items.append((sort_key, False, between))

    # 最后一个 MTE 之后的 VEC
    after_last = [v for v in vec_ops if v.start_time > mte_times[-1]]
    if after_last:
        output_items.append((after_last[0].start_time, False, after_last))

    # 按时间排序输出
    output_items.sort(key=lambda x: x[0])

    for sort_key, is_mte, content in output_items:
        if is_mte:
            m = content
            time_str = f"{m.start_time}-{m.end_time}"
            addr_str = format_addr_range(m.addr_start, m.addr_end)
            print(f"  {time_str:<16} {m.buffer_name:<15} {m.unit:<12} {m.op_type:<10} "
                  f"{addr_str:<24} {m.size:>8} {m.access_count:>6}", file=file)
        else:
            # VEC 聚合摘要
            _print_vec_summary(content, merge_vec_aiv, file)

    # 统计
    print("-" * 110, file=file)
    mte_count = len(mte_ops)
    vec_count = sum(m.access_count for m in vec_ops)
    vec_bytes = sum(m.size for m in vec_ops)
    print(f"  统计: MTE 操作 {mte_count} 条, VEC/AIV 操作 {vec_count} 次 ({vec_bytes} 字节)", file=file)


def _print_vec_summary(vec_list: list, merge_vec_aiv: bool = False,
                       file=sys.stdout):
    """打印 VEC 操作的聚合摘要（按 buffer 分组，可选 VEC/AIV 分开）"""
    if not vec_list:
        return

    # 按 buffer 分组
    by_buffer = {}
    for m in vec_list:
        if m.buffer_name not in by_buffer:
            by_buffer[m.buffer_name] = []
        by_buffer[m.buffer_name].append(m)

    # 输出每个 buffer 的摘要
    for buffer_name, ops in sorted(by_buffer.items(),
                                    key=lambda x: min(m.start_time for m in x[1])):
        if merge_vec_aiv:
            _print_one_buffer_vec_line(buffer_name, ops, file)
        else:
            vec_only = [m for m in ops if 'AIV' not in m.unit]
            aiv_only = [m for m in ops if 'AIV' in m.unit]
            if vec_only:
                _print_one_buffer_vec_line(buffer_name, vec_only, file)
            if aiv_only:
                _print_one_buffer_vec_line(buffer_name, aiv_only, file)


def _print_one_buffer_vec_line(buffer_name: str, ops: list, file=sys.stdout):
    """输出单个 buffer 的一行 VEC 或 AIV 摘要"""
    if not ops:
        return

    min_addr = min(m.addr_start for m in ops)
    max_addr = max(m.addr_end for m in ops)
    min_time = min(m.start_time for m in ops)
    max_time = max(m.end_time for m in ops)
    rd_count = sum(m.access_count for m in ops if m.op_type == 'RD')
    wr_count = sum(m.access_count for m in ops if m.op_type == 'WR')
    rd_bytes = sum(m.size for m in ops if m.op_type == 'RD')
    wr_bytes = sum(m.size for m in ops if m.op_type == 'WR')
    total_ops = rd_count + wr_count
    total_bytes = rd_bytes + wr_bytes

    op_parts = []
    if rd_count > 0:
        op_parts.append(f"R{rd_count}")
    if wr_count > 0:
        op_parts.append(f"W{wr_count}")
    op_str = "/".join(op_parts) if op_parts else "-"

    has_aiv = any('AIV' in m.unit for m in ops)
    has_vec = any('VEC_LSU' in m.unit for m in ops)
    if has_aiv and has_vec:
        unit_label = '[VEC/AIV]'
    elif has_aiv:
        unit_label = '[AIV]'
    else:
        unit_label = '[VEC]'

    time_str = f"{min_time}-{max_time}"
    addr_str = format_addr_range(min_addr, max_addr)
    print(f"  {time_str:<16} {buffer_name:<15} {unit_label:<12} {op_str:<10} "
          f"{addr_str:<24} {total_bytes:>8} {total_ops:>6}", file=file)


def print_parallel_view(merged_list: list, file=sys.stdout):
    """
    打印并行视图 - 按执行单元分组显示
    展示不同单元在同一时间段内的并行操作
    """
    if not merged_list:
        return

    print("\n" + "=" * 110, file=file)
    print("  并行执行视图 (按执行单元分组)", file=file)
    print("=" * 110, file=file)

    # 按单元类别分组
    by_category = {'MTE_W': [], 'MTE_R': [], 'VEC_LSU': [], 'AIV_SU': []}
    for m in merged_list:
        cat = UNIT_CATEGORY.get(m.unit, m.unit)
        if cat in by_category:
            by_category[cat].append(m)

    for cat_name, items in by_category.items():
        if not items:
            continue

        total_bytes = sum(m.size for m in items)
        total_ops = sum(m.access_count for m in items)

        print(f"\n  [{cat_name}] {len(items)} 个合并块, {total_ops} 次操作, {total_bytes} 字节", file=file)
        print("-" * 80, file=file)

        # 显示前 20 个
        for m in items[:20]:
            time_str = f"{m.start_time}-{m.end_time}"
            addr_str = format_addr_range(m.addr_start, m.addr_end)
            print(f"    {time_str:<16} {m.buffer_name:<15} {m.op_type:<4} "
                  f"{addr_str:<24} {m.size:>8}B", file=file)

        if len(items) > 20:
            print(f"    ... 还有 {len(items) - 20} 个", file=file)


def print_time_statistics(merged_list: list, file=sys.stdout):
    """打印时间统计"""
    if not merged_list:
        return

    min_time = min(m.start_time for m in merged_list)
    max_time = max(m.end_time for m in merged_list)
    total_duration = max_time - min_time

    # 按 buffer 统计
    by_buffer = {}
    for m in merged_list:
        if m.buffer_name not in by_buffer:
            by_buffer[m.buffer_name] = {'count': 0, 'bytes': 0, 'ops': 0}
        by_buffer[m.buffer_name]['count'] += 1
        by_buffer[m.buffer_name]['bytes'] += m.size
        by_buffer[m.buffer_name]['ops'] += m.access_count

    print("\n" + "=" * 110, file=file)
    print("  时间统计", file=file)
    print("=" * 110, file=file)
    print(f"  时间范围: {min_time} - {max_time} (持续 {total_duration} 周期)", file=file)
    print(f"  合并块数: {len(merged_list)}", file=file)
    print(f"  总操作数: {sum(m.access_count for m in merged_list)}", file=file)
    print(f"  总字节数: {sum(m.size for m in merged_list)}", file=file)

    print("\n  按 Buffer 统计:", file=file)
    for name in MEMORY_MAP.keys():
        if name in by_buffer:
            s = by_buffer[name]
            print(f"    {name:<15} {s['count']:>5} 块, {s['ops']:>6} 次操作, {s['bytes']:>10} 字节", file=file)

    # 未知 buffer
    if 'UNKNOWN' in by_buffer:
        s = by_buffer['UNKNOWN']
        print(f"    {'UNKNOWN':<15} {s['count']:>5} 块, {s['ops']:>6} 次操作, {s['bytes']:>10} 字节", file=file)


def merge_with_mte_timeline(merged_list: list, mte_timeline_json: str,
                            veccore: str) -> list:
    """
    用 MTE timeline 的准确数据替换 UB 日志中不完整的 MTE 记录。
    - MTE timeline 有准确的地址范围和 start/end 时间戳
    - UB 日志的 MTE 记录可能地址不完整（GM→UB 只记录部分）
    - VEC/AIV 记录保留不动
    """
    with open(mte_timeline_json, 'r') as f:
        timeline_data = json.load(f)

    by_veccore = timeline_data.get('by_veccore', {})
    if veccore not in by_veccore:
        print(f"警告: mte_timeline.json 中无 {veccore} 数据", file=sys.stderr)
        return merged_list

    mte_entries = by_veccore[veccore]

    # 将 MTE timeline 转为 MergedAccess
    mte_merged = []
    for entry in mte_entries:
        direction = entry['direction']
        ts = entry['timestamp']
        end_ts = entry.get('end_timestamp') or ts

        if direction == 'GM -> UB':
            # UB 目标地址
            ub_start = int(entry['destination_start_offset'], 16)
            ub_end = int(entry['destination_end_offset'], 16)
            ub_size = entry['veccore_total_size_bytes']
            unit = 'MTE_W'
            op_type = 'WR'
        else:
            # UB -> GM: UB 源地址
            sources = entry.get('source_addresses', [])
            if not sources:
                continue
            ub_start = int(sources[0]['address'], 16)
            ub_end = int(sources[-1]['address'], 16) + sources[-1]['size']
            ub_size = sum(s['size'] for s in sources)
            unit = 'MTE_R'
            op_type = 'RD'

        buf = find_buffer(ub_start) or 'UNKNOWN'
        mte_merged.append(MergedAccess(
            start_time=ts,
            end_time=end_ts,
            unit=unit,
            op_type=op_type,
            addr_start=ub_start,
            addr_end=ub_end,
            buffer_name=buf,
            access_count=1,
            instr_ids=[entry['instr_id']],
        ))

    # 分离 UB 日志中的 MTE 和非 MTE 记录
    ub_non_mte = []
    ub_mte = []
    for m in merged_list:
        cat = UNIT_CATEGORY.get(m.unit, m.unit)
        if cat in ('MTE_W', 'MTE_R'):
            ub_mte.append(m)
        else:
            ub_non_mte.append(m)

    # 标记已被 MTE timeline 替换的 UB MTE 记录
    replaced = set()
    for mte in mte_merged:
        for i, ub in enumerate(ub_mte):
            if i in replaced:
                continue
            # 匹配条件：单元类型一致 + 地址重叠 + 时间接近
            if mte.unit != ub.unit:
                continue
            addr_overlap = (ub.addr_start <= mte.addr_start <= ub.addr_end or
                           mte.addr_start <= ub.addr_start <= mte.addr_end)
            time_close = abs(ub.start_time - mte.start_time) < 1000
            if addr_overlap and time_close:
                replaced.add(i)
                break

    # 保留未被替换的 UB MTE 记录
    remaining_ub_mte = [ub for i, ub in enumerate(ub_mte) if i not in replaced]

    # 合并：MTE timeline + 未替换的 UB MTE + VEC/AIV
    result = mte_merged + remaining_ub_mte + ub_non_mte
    result.sort(key=lambda m: m.start_time)
    return result


def main():
    parser = argparse.ArgumentParser(description='UB Memory Analyzer - 按时间维度展示')
    parser.add_argument('dump_file', help='日志文件路径')
    parser.add_argument('--unit', choices=['MTE_W', 'MTE_R', 'VEC_LSU', 'AIV_SU', 'ALL'],
                        default='ALL', help='过滤执行单元')
    parser.add_argument('-b', '--buffer', help='过滤 buffer')
    parser.add_argument('--time-range', help='时间范围过滤 (如: 10000-20000)')
    parser.add_argument('--no-merge', action='store_true', help='不合并操作')
    parser.add_argument('--time-gap', type=int, default=10, help='合并时间间隔阈值')
    parser.add_argument('--addr-gap', type=int, default=32, help='合并地址间隔阈值')
    parser.add_argument('--merge-mte', action='store_true',
                        help='按 instr_id 合并 MTE 操作（一条指令合并为一条记录）')
    parser.add_argument('--limit', type=int, help='最大显示条数')
    parser.add_argument('--mte-focus', action='store_true',
                        help='MTE 聚焦模式: 只显示 MTE 详情，VEC_LSU/AIV_SU 聚合为范围')
    parser.add_argument('--merge-vec-aiv', action='store_true',
                        help='mte-focus 模式下将 VEC 和 AIV 合并为一行（默认分开）')
    parser.add_argument('-m', '--memory-map', required=True,
                        help='memory_map.json 路径 (由 gen_memory_map.py 生成)')
    parser.add_argument('-t', '--mte-timeline',
                        help='mte_timeline.json 路径 (由 run_mte_analysis.py 生成)')
    parser.add_argument('--veccore', default='veccore0',
                        help='目标 veccore (默认: veccore0)')
    parser.add_argument('-o', '--output', help='输出到文件')

    args = parser.parse_args()

    # 加载内存映射
    init_from_json(args.memory_map)

    # 解析时间范围
    time_range = None
    if args.time_range:
        try:
            start, end = args.time_range.split('-')
            time_range = (int(start), int(end))
        except ValueError:
            print(f"错误: 无效的时间范围格式 '{args.time_range}'", file=sys.stderr)
            sys.exit(1)

    # 进度回调
    def progress(count):
        print(f"\r解析进度: {count} 行...", end='', file=sys.stderr)

    # 解析和分析
    print(f"正在解析: {args.dump_file}", file=sys.stderr)
    analyzer = parse_and_analyze(args.dump_file, progress)
    print(f"\n解析完成: {len(analyzer.accesses)} 条访问记录", file=sys.stderr)

    # 合并
    if not args.no_merge:
        merged_list = analyzer.merge_accesses_by_time(args.time_gap, args.addr_gap,
                                                       merge_mte_by_instr=args.merge_mte)
        print(f"合并完成: {len(merged_list)} 个合并块", file=sys.stderr)
    else:
        # 不合并，将每个访问转换为 MergedAccess
        merged_list = []
        for access in analyzer.accesses:
            buffer_name = find_buffer(access.addr) or "UNKNOWN"
            merged_list.append(MergedAccess(
                start_time=access.timestamp,
                end_time=access.done_timestamp or access.timestamp,
                unit=access.unit,
                op_type=access.op_type,
                addr_start=access.addr,
                addr_end=access.end_addr,
                buffer_name=buffer_name,
                access_count=1,
                instr_ids=[access.instr_id] if access.instr_id else []
            ))
        merged_list.sort(key=lambda m: m.start_time)

    # MTE timeline 合并
    if args.mte_timeline:
        before_count = len(merged_list)
        merged_list = merge_with_mte_timeline(merged_list, args.mte_timeline, args.veccore)
        print(f"MTE 合并完成: {before_count} -> {len(merged_list)} 条记录", file=sys.stderr)

    # 应用过滤器
    filtered = merged_list

    # 单元过滤
    if args.unit != 'ALL':
        filtered = [m for m in filtered
                    if UNIT_CATEGORY.get(m.unit, m.unit) == args.unit]

    # Buffer 过滤
    if args.buffer:
        filtered = [m for m in filtered if m.buffer_name == args.buffer]

    # 时间范围过滤
    if time_range:
        filtered = [m for m in filtered
                    if not (m.end_time < time_range[0] or m.start_time > time_range[1])]

    print(f"过滤后: {len(filtered)} 条记录", file=sys.stderr)

    # 输出
    output_file = open(args.output, 'w') if args.output else sys.stdout

    try:
        # 时间统计
        print_time_statistics(filtered, output_file)

        if args.mte_focus:
            # MTE 聚焦模式
            print("\n", file=output_file)
            print_mte_focus_view(filtered, output_file)
        else:
            # 普通时间线视图
            print("\n", file=output_file)
            print_timeline_header(output_file)

            display_list = filtered[:args.limit] if args.limit else filtered
            for m in display_list:
                print_merged_access(m, output_file)

            if args.limit and len(filtered) > args.limit:
                print(f"\n  ... 还有 {len(filtered) - args.limit} 条记录 (使用 --limit 调整)", file=output_file)

            # 并行视图
            print_parallel_view(filtered, output_file)

    finally:
        if args.output:
            output_file.close()
            print(f"结果已保存到: {args.output}", file=sys.stderr)


if __name__ == '__main__':
    main()
