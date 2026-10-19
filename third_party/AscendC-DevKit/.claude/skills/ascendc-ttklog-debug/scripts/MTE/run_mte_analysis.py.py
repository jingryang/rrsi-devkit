#!/usr/bin/env python3
"""
MTE 一键分析 — 原子化执行三阶段 MTE 日志分析流程。

Usage:
    python run_mte_analysis.py <mte_log.dump> <veccore> [--output-dir <dir>] [--no-detail]

Arguments:
    mte_log.dump    MTE 日志文件路径
    veccore         veccore0 或 veccore1

Options:
    --output-dir    输出目录（默认当前目录）
    --no-detail     紧凑模式输出

中间产物（保留在 output-dir）：
    mte_analysis.json           Stage 1 解析结果
    mte_timeline.json           Stage 2 时间线
    mte_timeline_<veccore>.txt  Stage 3 可读报告（最终输出）
"""

import argparse
import json
import sys
from pathlib import Path

from analyze_mte_transfers import MTETransferAnalyzer
from process_mte_timeline import MTETimelineProcessor
from show_timeline import show_timeline


def main():
    parser = argparse.ArgumentParser(description='MTE 一键分析')
    parser.add_argument('mte_log', help='MTE 日志文件路径')
    parser.add_argument('veccore', choices=['veccore0', 'veccore1'], help='目标 veccore')
    parser.add_argument('--output-dir', default='.', help='输出目录（默认当前目录）')
    parser.add_argument('--no-detail', action='store_true', help='紧凑模式')
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    analysis_json = output_dir / 'mte_analysis.json'
    timeline_json = output_dir / 'mte_timeline.json'
    timeline_txt = output_dir / f'mte_timeline_{args.veccore}.txt'

    # Stage 1: 解析 MTE 日志
    print(f"[1/3] Analyzing MTE log: {args.mte_log}")
    analyzer = MTETransferAnalyzer(args.mte_log)
    analysis_data = analyzer.analyze()
    with open(analysis_json, 'w', encoding='utf-8') as f:
        json.dump(analysis_data, f, indent=2, ensure_ascii=False)
    print(f"      -> {analysis_json} ({analysis_data['summary']['total_transfers']} transfers)")

    # Stage 2: 生成时间线
    print(f"[2/3] Processing timeline...")
    processor = MTETimelineProcessor(data=analysis_data)
    timeline_data = processor.process()
    with open(timeline_json, 'w', encoding='utf-8') as f:
        json.dump(timeline_data, f, indent=2, ensure_ascii=False)
    print(f"      -> {timeline_json}")

    # Stage 3: 输出可读报告
    print(f"[3/3] Generating report for {args.veccore}...")
    show_timeline(data=timeline_data, core=args.veccore,
                  compact=args.no_detail, output_file=str(timeline_txt))
    print(f"      -> {timeline_txt}")

    print(f"\nDone. Final report: {timeline_txt}")


if __name__ == '__main__':
    main()
