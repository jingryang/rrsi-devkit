#!/usr/bin/env python3
"""
gen_memory_map.py — 从 buffer_config.json 自动计算 UB 地址映射

Usage:
    python gen_memory_map.py <buffer_config.json> [-o <output.json>]

输入格式 (buffer_config.json):
    {
      "buffers": [
        {"name": "groupIdxQue_", "num": 1, "size": 32},
        {"name": "xQue_", "num": 4, "size": 55776}
      ]
    }

输出格式 (memory_map.json):
    {
      "groupIdxQue_": {"start": 0, "end": 32, "size": 32},
      "xQue_0": {"start": 32, "end": 55808, "size": 55776},
      ...
    }
"""

import json
import sys
import argparse
from pathlib import Path

UB_MAX_BYTES = 0x3E000  # 248KB


def compute_memory_map(config: dict) -> dict:
    """从 buffer 配置计算地址映射"""
    memory_map = {}
    current_addr = 0

    for buf in config['buffers']:
        name = buf['name']
        num = buf.get('num', 1)
        size = buf['size']

        if num < 1:
            raise ValueError(f"Buffer '{name}': num must be >= 1, got {num}")
        if size <= 0:
            raise ValueError(f"Buffer '{name}': size must be > 0, got {size}")

        if num == 1:
            memory_map[name] = {
                'start': current_addr,
                'end': current_addr + size,
                'size': size,
            }
            current_addr += size
        else:
            for i in range(num):
                entry_name = f"{name}{i}"
                memory_map[entry_name] = {
                    'start': current_addr,
                    'end': current_addr + size,
                    'size': size,
                }
                current_addr += size

    return memory_map


def print_summary(memory_map: dict, file=sys.stderr):
    """打印人类可读的地址摘要"""
    if not memory_map:
        print("  (empty)", file=file)
        return

    print("=" * 70, file=file)
    print(f"  {'Buffer':<20} {'Start':>10} {'End':>10} {'Size':>10}", file=file)
    print("-" * 70, file=file)
    for name, info in memory_map.items():
        print(f"  {name:<20} 0x{info['start']:05x}   0x{info['end']:05x}   {info['size']:>8}B",
              file=file)

    total = max(info['end'] for info in memory_map.values())
    print("-" * 70, file=file)
    print(f"  Total UB: {total}B (0x{total:x}) / {UB_MAX_BYTES}B (0x{UB_MAX_BYTES:x})"
          f"  [{total * 100 // UB_MAX_BYTES}%]", file=file)
    if total > UB_MAX_BYTES:
        print(f"  ⚠ WARNING: 超过 UB 上限 {total - UB_MAX_BYTES}B!", file=file)
    print("=" * 70, file=file)


def main():
    parser = argparse.ArgumentParser(description='从 buffer_config.json 计算 UB 地址映射')
    parser.add_argument('config', help='buffer_config.json 路径')
    parser.add_argument('-o', '--output', help='输出 memory_map.json 路径 (默认: 同目录下 memory_map.json)')
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Error: {config_path} not found", file=sys.stderr)
        sys.exit(1)

    with open(config_path, 'r') as f:
        config = json.load(f)

    if 'buffers' not in config or not config['buffers']:
        print("Error: config must contain non-empty 'buffers' list", file=sys.stderr)
        sys.exit(1)

    memory_map = compute_memory_map(config)

    # 输出路径
    output_path = Path(args.output) if args.output else config_path.parent / 'memory_map.json'

    with open(output_path, 'w') as f:
        json.dump(memory_map, f, indent=2)

    print_summary(memory_map)
    print(f"\n  已写入: {output_path}", file=sys.stderr)


if __name__ == '__main__':
    main()
