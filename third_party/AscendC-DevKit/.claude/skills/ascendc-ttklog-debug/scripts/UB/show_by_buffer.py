#!/usr/bin/env python3
"""
UB Memory Analyzer - 按内存区域展示

按 buffer 分组显示内存访问，包含越界检测和同步分析。

Usage:
    python show_by_buffer.py <dump_file> [options]

Options:
    --buffer, -b    只显示指定 buffer (如: xQue_0, outQue_)
    --no-merge      不合并操作
    --time-gap      合并时间间隔阈值 (默认: 10)
    --addr-gap      合并地址间隔阈值 (默认: 32)
    --merge-mte     按 instr_id 合并 MTE 操作（一条指令合并为一条记录）
    --mte-focus     MTE 聚焦模式: 只显示 MTE 详情，VEC_LSU/AIV_SU 聚合为范围
    --output, -o    输出到文件
"""

import sys
import argparse
from ub_analyzer import (
    parse_and_analyze, MEMORY_MAP, UBAnalyzer,
    MergedAccess, SyncEvent, init_from_json
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
    return f"0x{start:05x} - 0x{end:05x}"


def format_instr_ids(ids: list) -> str:
    """格式化指令 ID 列表"""
    if not ids:
        return "-"
    if len(ids) == 1:
        return str(ids[0])
    return f"{ids[0]}~{ids[-1]}({len(ids)})"


def print_buffer_section(buffer_name: str, merged: list, info: dict,
                         bound_errors: list, mte_focus: bool = False,
                         merge_vec_aiv: bool = False, file=sys.stdout):
    """打印单个 buffer 的信息"""
    print("=" * 90, file=file)
    print(f"  Buffer: {buffer_name} (0x{info['start']:05x} - 0x{info['end']:05x}, {info['size']}B)", file=file)
    print("=" * 90, file=file)

    if not merged:
        print("  无访问记录", file=file)
        print(file=file)
        return

    # 统计
    reads = [m for m in merged if m.op_type == 'RD']
    writes = [m for m in merged if m.op_type == 'WR']
    total_ops = sum(m.access_count for m in merged)
    total_bytes_rd = sum(m.size for m in reads)
    total_bytes_wr = sum(m.size for m in writes)

    print(f"  统计: {len(merged)} 个合并块, {total_ops} 次操作, "
          f"读 {total_bytes_rd}B, 写 {total_bytes_wr}B", file=file)
    print("-" * 90, file=file)

    # 表头
    print(f"  {'时间范围':<16} {'单元':<12} {'类型':<10} {'地址范围':<24} "
          f"{'大小':>8} {'操作数':>6} {'指令ID'}", file=file)
    print("-" * 90, file=file)

    if mte_focus:
        # MTE 聚焦模式：MTE 详情显示，VEC/AIV 按轮次聚合 + 内联越界检测
        buffer_errors = [(a, msg, sev) for a, msg, sev in bound_errors
                         if a.addr >= info['start'] and a.addr < info['end']]
        _print_buffer_mte_focus(merged, buffer_errors, merge_vec_aiv, file)
    else:
        # 普通模式：显示所有
        for m in merged:
            time_str = f"{m.start_time}-{m.end_time}"
            addr_str = format_addr_range(m.addr_start, m.addr_end)
            instr_str = format_instr_ids(m.instr_ids)

            print(f"  {time_str:<16} {m.unit:<12} {m.op_type:<10} {addr_str:<24} "
                  f"{m.size:>8} {m.access_count:>6} {instr_str}", file=file)

    # 越界检测（mte-focus 模式已内联显示，此处仅用于非 mte-focus 和汇总）
    buffer_errors = [(a, msg, sev) for a, msg, sev in bound_errors
                     if a.addr >= info['start'] and a.addr < info['end']]
    if buffer_errors:
        errors = [(a, msg, sev) for a, msg, sev in buffer_errors if sev == 'ERROR']
        warnings = [(a, msg, sev) for a, msg, sev in buffer_errors if sev == 'WARNING']

        if not mte_focus:
            # 非 mte-focus 模式：详细列出越界
            print(file=file)
            if errors:
                print(f"  ✗ 越界错误: 发现 {len(errors)} 个写越界 (ERROR)", file=file)
                for access, msg, sev in errors[:5]:
                    print(f"    [{sev}] Time {access.timestamp}: {access.op_type} 0x{access.addr:x} + {access.size}B - {msg}", file=file)
                if len(errors) > 5:
                    print(f"    ... 还有 {len(errors) - 5} 个错误", file=file)

            if warnings:
                print(f"  ⚠ 越界警告: 发现 {len(warnings)} 个读越界 (WARNING)", file=file)
                for access, msg, sev in warnings[:5]:
                    print(f"    [{sev}] Time {access.timestamp}: {access.op_type} 0x{access.addr:x} + {access.size}B - {msg}", file=file)
                if len(warnings) > 5:
                    print(f"    ... 还有 {len(warnings) - 5} 个警告", file=file)
        else:
            # mte-focus 模式：仅打印汇总计数（详情已内联）
            err_cnt = len(errors)
            warn_cnt = len(warnings)
            if err_cnt or warn_cnt:
                parts = []
                if err_cnt:
                    parts.append(f"{err_cnt} 个写越界")
                if warn_cnt:
                    parts.append(f"{warn_cnt} 个读越界")
                print(f"\n  ✗ 越界汇总: {', '.join(parts)} (详情见上方内联标注)", file=file)
    else:
        print(f"\n  ✓ 越界检测: 无越界访问", file=file)

    print(file=file)


def _unit_display_cat(unit: str) -> str:
    """返回显示用的单元大类"""
    cat = UNIT_CATEGORY.get(unit, unit)
    if cat in ('AIV_SU',):
        return 'AIV'
    if cat in ('VEC_LSU',):
        return 'VEC'
    return cat


def _split_vec_segments(ops: list, gap_threshold: int = 200) -> list:
    """将 VEC/AIV 操作列表按连续段拆分

    拆分条件：
    - AIV 操作：每条独立成段（AIV 是标量操作，基本都是独立的）
    - VEC 操作：按以下条件合并
      1. 不同单元大类（VEC vs AIV）交替出现 → 断开
      2. 时间间隔超过 gap_threshold → 断开
    """
    if not ops:
        return []

    sorted_ops = sorted(ops, key=lambda m: m.start_time)
    segments = [[sorted_ops[0]]]

    for m in sorted_ops[1:]:
        prev = segments[-1][-1]
        prev_cat = _unit_display_cat(prev.unit)
        curr_cat = _unit_display_cat(m.unit)

        # AIV 操作每条独立成段
        if curr_cat == 'AIV' or prev_cat == 'AIV':
            segments.append([m])
            continue

        # VEC 操作：不同类别或时间间隔过大 → 新段
        if prev_cat != curr_cat or m.start_time - prev.end_time > gap_threshold:
            segments.append([m])
        else:
            segments[-1].append(m)

    return segments


def _print_buffer_mte_focus(merged: list, bound_errors: list,
                            merge_vec_aiv: bool = False, file=sys.stdout):
    """
    Buffer 内的 MTE 聚焦视图
    MTE 详细显示，VEC/AIV 在相邻 MTE 之间按连续段聚合为摘要 + 越界内联
    不同单元类别（VEC vs AIV）互为分段屏障，时间间隔过大也分段。
    """
    sorted_list = sorted(merged, key=lambda m: m.start_time)

    mte_ops = []
    vec_ops = []
    for m in sorted_list:
        cat = UNIT_CATEGORY.get(m.unit, m.unit)
        if cat in ('MTE_W', 'MTE_R'):
            mte_ops.append(m)
        else:
            vec_ops.append(m)

    if not mte_ops:
        if vec_ops:
            for seg in _split_vec_segments(vec_ops):
                _print_vec_summary_line(seg, bound_errors, merge_vec_aiv, file)
        return

    # 构建输出列表：(sort_key, is_mte, content)
    output_items = []
    for m in mte_ops:
        output_items.append((m.start_time, True, m))

    mte_times = sorted(set(m.start_time for m in mte_ops))

    # 第一个 MTE 之前的 VEC/AIV
    before_first = [v for v in vec_ops if v.end_time < mte_times[0]]
    for seg in _split_vec_segments(before_first):
        output_items.append((seg[0].start_time, False, seg))

    # 每对 MTE 之间的 VEC/AIV
    for i in range(len(mte_times) - 1):
        t1, t2 = mte_times[i], mte_times[i + 1]
        between = [v for v in vec_ops if v.start_time >= t1 and v.end_time <= t2]
        for seg in _split_vec_segments(between):
            output_items.append((seg[0].start_time, False, seg))

    # 最后一个 MTE 之后的 VEC/AIV
    after_last = [v for v in vec_ops if v.start_time > mte_times[-1]]
    for seg in _split_vec_segments(after_last):
        output_items.append((seg[0].start_time, False, seg))

    output_items.sort(key=lambda x: x[0])

    for sort_key, is_mte, content in output_items:
        if is_mte:
            m = content
            time_str = f"{m.start_time}-{m.end_time}"
            addr_str = format_addr_range(m.addr_start, m.addr_end)
            instr_str = format_instr_ids(m.instr_ids)
            print(f"  {time_str:<16} {m.unit:<12} {m.op_type:<10} {addr_str:<24} "
                  f"{m.size:>8} {m.access_count:>6} {instr_str}", file=file)
        else:
            _print_vec_summary_line(content, bound_errors, merge_vec_aiv, file)


def _print_vec_summary_line(vec_list: list, bound_errors: list,
                            merge_vec_aiv: bool = False, file=sys.stdout):
    """VEC/AIV 摘要 + 越界内联
    merge_vec_aiv=False: VEC 和 AIV 分开各一行
    merge_vec_aiv=True:  合并为一行
    """
    if not vec_list:
        return

    if merge_vec_aiv:
        _print_one_vec_summary(vec_list, bound_errors, file)
    else:
        # 按 VEC / AIV 分组
        vec_only = [m for m in vec_list if 'AIV' not in m.unit]
        aiv_only = [m for m in vec_list if 'AIV' in m.unit]
        if vec_only:
            _print_one_vec_summary(vec_only, bound_errors, file)
        if aiv_only:
            _print_one_vec_summary(aiv_only, bound_errors, file)


def _print_one_vec_summary(vec_list: list, bound_errors: list, file=sys.stdout):
    """输出一行摘要 + 内联越界"""
    if not vec_list:
        return

    min_addr = min(m.addr_start for m in vec_list)
    max_addr = max(m.addr_end for m in vec_list)
    min_time = min(m.start_time for m in vec_list)
    max_time = max(m.end_time for m in vec_list)
    total_bytes = sum(m.size for m in vec_list)

    rd_count = sum(m.access_count for m in vec_list if m.op_type == 'RD')
    wr_count = sum(m.access_count for m in vec_list if m.op_type == 'WR')
    total_ops = rd_count + wr_count

    op_parts = []
    if rd_count > 0:
        op_parts.append(f"R{rd_count}")
    if wr_count > 0:
        op_parts.append(f"W{wr_count}")
    op_str = "/".join(op_parts) if op_parts else "-"

    has_aiv = any('AIV' in m.unit for m in vec_list)
    has_vec = any('VEC_LSU' in m.unit for m in vec_list)
    if has_aiv and has_vec:
        unit_label = '[VEC/AIV]'
    elif has_aiv:
        unit_label = '[AIV]'
    else:
        unit_label = '[VEC]'

    time_str = f"{min_time}-{max_time}"
    addr_str = format_addr_range(min_addr, max_addr)
    print(f"  {time_str:<16} {unit_label:<12} {op_str:<10} {addr_str:<24} "
          f"{total_bytes:>8} {total_ops:>6} -", file=file)

    # 内联越界
    if bound_errors:
        hits = [(a, msg, sev) for a, msg, sev in bound_errors
                if min_time <= a.timestamp <= max_time]
        for a, msg, sev in hits:
            print(f"    [{sev}] t={a.timestamp} {a.unit} {a.op_type} "
                  f"0x{a.addr:x}+{a.size}B - {msg}", file=file)


def _print_vec_range_summary(vec_list: list, file=sys.stdout):
    """打印 VEC/AIV 操作的聚合摘要（单行）"""
    if not vec_list:
        return

    min_addr = min(m.addr_start for m in vec_list)
    max_addr = max(m.addr_end for m in vec_list)
    min_time = min(m.start_time for m in vec_list)
    max_time = max(m.end_time for m in vec_list)
    total_bytes = sum(m.size for m in vec_list)

    rd_count = sum(m.access_count for m in vec_list if m.op_type == 'RD')
    wr_count = sum(m.access_count for m in vec_list if m.op_type == 'WR')
    total_ops = rd_count + wr_count

    # 操作类型摘要
    op_parts = []
    if rd_count > 0:
        op_parts.append(f"R{rd_count}")
    if wr_count > 0:
        op_parts.append(f"W{wr_count}")
    op_str = "/".join(op_parts) if op_parts else "-"

    time_str = f"{min_time}-{max_time}"
    addr_str = format_addr_range(min_addr, max_addr)

    print(f"  {time_str:<16} {'[VEC/AIV]':<12} {op_str:<10} {addr_str:<24} "
          f"{total_bytes:>8} {total_ops:>6} -", file=file)


def print_sync_analysis(sync_events: list, file=sys.stdout):
    """打印同步分析结果"""
    print("=" * 90, file=file)
    print("  同步分析", file=file)
    print("=" * 90, file=file)

    if not sync_events:
        print("  ✓ 未检测到跨单元访问冲突", file=file)
        print(file=file)
        return

    warnings = [e for e in sync_events if e.status == 'WARNING']
    print(f"  检测到 {len(sync_events)} 个跨单元访问, 其中 {len(warnings)} 个潜在警告", file=file)
    print("-" * 90, file=file)

    # 只显示警告
    if warnings:
        print(f"  {'时间':<10} {'Buffer':<15} {'写入单元':<12} → {'读取单元':<12} {'地址范围':<26} 状态", file=file)
        print("-" * 90, file=file)
        for e in warnings[:20]:
            addr_str = format_addr_range(e.addr_start, e.addr_end)
            print(f"  {e.time:<10} {e.buffer_name:<15} {e.prev_unit:<12} → {e.curr_unit:<12} "
                  f"{addr_str:<26} {e.status}", file=file)
        if len(warnings) > 20:
            print(f"  ... 还有 {len(warnings) - 20} 个警告", file=file)
    else:
        print("  ✓ 所有跨单元访问时序正常", file=file)

    print(file=file)


def print_statistics(stats: dict, file=sys.stdout):
    """打印统计摘要"""
    print("=" * 90, file=file)
    print("  统计摘要", file=file)
    print("=" * 90, file=file)

    print(f"  总访问次数: {stats['total_accesses']}", file=file)
    print(f"  未知地址访问: {stats['unknown_accesses']}", file=file)
    print(f"  越界错误 (写): {stats['bound_errors']}", file=file)
    print(f"  越界警告 (读): {stats['bound_warnings']}", file=file)
    print(file=file)

    print("  按 Buffer 统计:", file=file)
    for name, info in MEMORY_MAP.items():
        if name in stats['by_buffer']:
            s = stats['by_buffer'][name]
            print(f"    {name:<15} 读 {s['reads']:>5} 次 ({s['bytes_read']:>10}B), "
                  f"写 {s['writes']:>5} 次 ({s['bytes_written']:>10}B)", file=file)

    print(file=file)
    print("  按执行单元统计:", file=file)
    for unit, s in sorted(stats['by_unit'].items()):
        print(f"    {unit:<12} 读 {s['RD']:>5} 次 ({s['bytes_rd']:>10}B), "
              f"写 {s['WR']:>5} 次 ({s['bytes_wr']:>10}B)", file=file)

    print(file=file)


def main():
    parser = argparse.ArgumentParser(description='UB Memory Analyzer - 按内存区域展示')
    parser.add_argument('dump_file', help='日志文件路径')
    parser.add_argument('-b', '--buffer', help='只显示指定 buffer')
    parser.add_argument('--no-merge', action='store_true', help='不合并操作')
    parser.add_argument('--time-gap', type=int, default=10, help='合并时间间隔阈值')
    parser.add_argument('--addr-gap', type=int, default=32, help='合并地址间隔阈值')
    parser.add_argument('--merge-mte', action='store_true',
                        help='按 instr_id 合并 MTE 操作（一条指令合并为一条记录）')
    parser.add_argument('--mte-focus', action='store_true',
                        help='MTE 聚焦模式: 只显示 MTE 详情，VEC_LSU/AIV_SU 聚合为范围')
    parser.add_argument('--merge-vec-aiv', action='store_true',
                        help='mte-focus 模式下将 VEC 和 AIV 合并为一行（默认分开）')
    parser.add_argument('-m', '--memory-map', required=True,
                        help='memory_map.json 路径 (由 gen_memory_map.py 生成)')
    parser.add_argument('-o', '--output', help='输出到文件')

    args = parser.parse_args()

    # 加载内存映射
    init_from_json(args.memory_map)

    # 进度回调
    def progress(count):
        print(f"\r解析进度: {count} 行...", end='', file=sys.stderr)

    # 解析和分析
    print(f"正在解析: {args.dump_file}", file=sys.stderr)
    analyzer = parse_and_analyze(args.dump_file, progress)
    print(f"\n解析完成: {len(analyzer.accesses)} 条访问记录", file=sys.stderr)

    # 合并
    if not args.no_merge:
        analyzer.merge_accesses_by_buffer(args.time_gap, args.addr_gap,
                                          merge_mte_by_instr=args.merge_mte)
        print(f"合并完成", file=sys.stderr)

    # 同步分析
    sync_events = analyzer.analyze_sync()

    # 输出
    output_file = open(args.output, 'w') if args.output else sys.stdout

    try:
        # 统计摘要
        stats = analyzer.get_statistics()
        print_statistics(stats, output_file)

        # 按 buffer 显示
        buffers_to_show = [args.buffer] if args.buffer else MEMORY_MAP.keys()

        for buffer_name in buffers_to_show:
            if buffer_name not in MEMORY_MAP:
                print(f"警告: 未知 buffer '{buffer_name}'", file=sys.stderr)
                continue

            info = MEMORY_MAP[buffer_name]
            merged = analyzer.merged_by_buffer.get(buffer_name, [])
            print_buffer_section(buffer_name, merged, info, analyzer.bound_errors,
                                 mte_focus=args.mte_focus,
                                 merge_vec_aiv=args.merge_vec_aiv,
                                 file=output_file)

        # 同步分析
        print_sync_analysis(sync_events, output_file)

        # 未知地址访问
        if analyzer.unknown_accesses:
            print("=" * 90, file=output_file)
            print(f"  未知地址访问 ({len(analyzer.unknown_accesses)} 个)", file=output_file)
            print("=" * 90, file=output_file)
            for access in analyzer.unknown_accesses[:10]:
                print(f"  Time {access.timestamp}: {access.unit} {access.op_type} "
                      f"0x{access.addr:x} + {access.size}B", file=output_file)
            if len(analyzer.unknown_accesses) > 10:
                print(f"  ... 还有 {len(analyzer.unknown_accesses) - 10} 个", file=output_file)

    finally:
        if args.output:
            output_file.close()
            print(f"结果已保存到: {args.output}", file=sys.stderr)


if __name__ == '__main__':
    main()
