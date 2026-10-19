#!/usr/bin/env python3
"""
MTE Timeline Processor - Simplified MOV_SRC_TO_DST_ALIGNv2 Instruction View

Extracts MOV_SRC_TO_DST_ALIGNv2 instruction information separated by veccore:
- Source address (GM)
- Destination address (UB start offset)
- Destination address range (start + total_size)
- Timestamp
- Transfer size
- Stride info
"""

import json
import sys
from pathlib import Path
from typing import List, Dict, Any


class MTETimelineProcessor:
    """Process MTE transfer data into simplified instruction view by veccore."""

    def __init__(self, json_file: str = None, *, data: Dict[str, Any] = None):
        if data is not None:
            self.json_file = None
            self.data = data
        elif json_file is not None:
            self.json_file = Path(json_file)
            self.data = self._load_data()
        else:
            raise ValueError("Must provide either json_file or data")

    def _load_data(self) -> Dict[str, Any]:
        """加载 JSON 数据。"""
        with open(self.json_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def process(self) -> Dict[str, Any]:
        """处理数据，按 veccore 分离 MOV_SRC_TO_DST_ALIGNv2 指令信息。"""
        transfers = self.data.get('transfers', [])

        # 按 veccore 分组
        by_veccore = {
            'veccore0': [],
            'veccore1': [],
            'shared': [],  # 两个核心都参与的搬运
        }

        for transfer in transfers:
            veccore_info = self._classify_by_veccore(transfer)
            if veccore_info:
                for veccore, items in veccore_info.items():
                    if veccore in by_veccore:
                        by_veccore[veccore].extend(items)
                    else:
                        # 如果是新的 veccore 名称，添加到字典
                        by_veccore[veccore] = items

        # 按时间戳排序每个 veccore 的数据
        for veccore_name, transfers in by_veccore.items():
            if isinstance(transfers, list):
                by_veccore[veccore_name] = sorted(transfers, key=lambda x: x['timestamp'])

        # 计算统计信息
        stats = self._generate_statistics(by_veccore)

        return {
            'metadata': {
                'source_file': str(self.json_file),
                'description': 'MOV_SRC_TO_DST_ALIGNv2 instructions separated by veccore',
            },
            'statistics': stats,
            'by_veccore': by_veccore,
        }

    def _classify_by_veccore(self, transfer: Dict) -> Dict[str, List]:
        """根据 veccore 分类搬运信息。"""
        result = {}
        instr_id = transfer['instr_id']
        direction = transfer['direction']
        params = transfer.get('parameters', {})

        # 总搬运大小
        total_size = params.get('burst_len', 0) * params.get('burst_num', 0)

        # 判断涉及的 veccore
        ub_destinations = transfer.get('ub_destinations', [])
        ub_sources = transfer.get('ub_sources', [])

        # GM -> UB 情况
        if direction == 'GM -> UB':
            # 获取 GM 源地址
            source_addresses = []
            gm_sources = transfer.get('gm_sources', [])
            for gm in gm_sources:
                source_addresses.append({
                    'address': gm['address'],
                    'size': gm['size_bytes'],
                })

            veccores_involved = set(ub['veccore'] for ub in ub_destinations)

            # 为每个参与的 veccore 生成记录
            if veccores_involved:
                for veccore in sorted(veccores_involved):
                    # 找到该 veccore 的 UB 目标地址
                    veccore_dests = [ub for ub in ub_destinations if ub['veccore'] == veccore]
                    if veccore_dests:
                        # 取第一个 UB 地址
                        start_offset = veccore_dests[0]['offset']
                        # 计算范围：起始 + 总大小
                        total_veccore_size = sum(ub['size_bytes'] for ub in veccore_dests)
                        end_offset = int(start_offset, 16) + total_veccore_size

                        result[veccore] = [{
                            'instr_id': instr_id,
                            'timestamp': transfer.get('timestamp', 0),
                            'end_timestamp': transfer.get('end_timestamp'),
                            'direction': direction,
                            'data_type': params.get('data_type'),
                            'burst_length': params.get('burst_len', 0),
                            'burst_count': params.get('burst_num', 0),
                            'src_stride': params.get('src_stride', 0),
                            'dst_stride': params.get('dst_stride', 0),
                            'source_addresses': source_addresses,
                            'destination_start_offset': start_offset,
                            'destination_end_offset': f"0x{end_offset:x}",
                            'destination_range': f"{start_offset} + {total_veccore_size}B = 0x{end_offset:x}",
                            'veccore_total_size_bytes': total_veccore_size,
                            'total_size_bytes': total_size,
                        }]

        # UB -> GM 情况
        elif direction == 'UB -> GM':
            # 获取 GM 目标地址
            gm_destinations = transfer.get('gm_destinations', [])
            if gm_destinations:
                # 取第一个和最后一个 GM 地址计算范围
                start_addr = gm_destinations[0]['address']
                total_gm_size = sum(gm['size_bytes'] for gm in gm_destinations)
                end_addr_int = int(start_addr, 16) + total_gm_size

                # 按 veccore 分组 ub_sources
                ub_sources_by_veccore = {}
                for ub in ub_sources:
                    veccore = ub.get('veccore')
                    if veccore not in ub_sources_by_veccore:
                        ub_sources_by_veccore[veccore] = []
                    ub_sources_by_veccore[veccore].append(ub)

                # 为每个有 ub_sources 的 veccore 生成记录
                for veccore in sorted(ub_sources_by_veccore.keys()):
                    veccore_sources = ub_sources_by_veccore[veccore]
                    # 构建 source_addresses
                    source_addresses = []
                    for ub in veccore_sources:
                        source_addresses.append({
                            'address': ub['offset'],
                            'size': ub['size_bytes'],
                        })

                    # 计算该 veccore 的 UB 源范围
                    start_offset = veccore_sources[0]['offset']
                    total_veccore_size = sum(ub['size_bytes'] for ub in veccore_sources)

                    result[veccore] = [{
                        'instr_id': instr_id,
                        'timestamp': transfer.get('timestamp', 0),
                        'end_timestamp': transfer.get('end_timestamp'),
                        'direction': direction,
                        'data_type': params.get('data_type'),
                        'burst_length': params.get('burst_len', 0),
                        'burst_count': params.get('burst_num', 0),
                        'src_stride': params.get('src_stride', 0),
                        'dst_stride': params.get('dst_stride', 0),
                        'source_addresses': source_addresses,
                        'destination_start_offset': start_addr,
                        'destination_end_offset': f"0x{end_addr_int:x}",
                        'destination_range': f"{start_addr} + {total_gm_size}B = 0x{end_addr_int:x}",
                        'veccore_total_size_bytes': total_veccore_size,
                        'total_size_bytes': total_size,
                    }]

        return result

    def _generate_statistics(self, by_veccore: Dict) -> Dict[str, Any]:
        """生成统计信息。"""
        stats = {
            'by_veccore': {},
            'total': {
                'total_instructions': 0,
                'total_bytes': 0,
            }
        }

        for veccore, transfers in by_veccore.items():
            if not transfers:
                continue

            stats['by_veccore'][veccore] = {
                'instruction_count': len(transfers),
                'total_bytes': sum(t.get('total_size_bytes', 0) for t in transfers),
                'veccore_total_bytes': sum(t.get('veccore_total_size_bytes', 0) for t in transfers),
                'timestamp_range': {
                    'min': min(t['timestamp'] for t in transfers),
                    'max': max(t['timestamp'] for t in transfers),
                },
            }

            stats['total']['total_instructions'] += len(transfers)
            stats['total']['total_bytes'] += stats['by_veccore'][veccore]['veccore_total_bytes']

        return stats

    def save(self, output_file: str):
        """保存处理结果。"""
        result = self.process()
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        return result


def main():
    if len(sys.argv) < 2:
        print("Usage: python process_mte_timeline.py <input_json> [output_json]")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"Processing MTE data: {input_file}")
    processor = MTETimelineProcessor(input_file)

    if output_file:
        result = processor.save(output_file)
        print(f"Result saved to: {output_file}")

    result = processor.process()

    print("\n" + "=" * 80)
    print("Statistics")
    print("=" * 80)
    print(json.dumps(result['statistics'], indent=2, ensure_ascii=False))

    # 按各个 veccore 显示
    print("\n" + "=" * 80)
    print("By VecCore")
    print("=" * 80)

    for veccore, transfers in result['by_veccore'].items():
        if not transfers:
            continue

        print(f"\n--- {veccore} ({len(transfers)} transfers) ---")
        print(f"\n{'ID':<6} {'Time':<8} {'Dir':<10} {'Src':<16} {'Dst Start':<12} {'Dst End':<12} {'Size':<10} {'Burst':<15} {'Stride':<20} {'Type'}")
        print("-" * 120)

        for t in transfers:
            src_info = t.get('source_addresses', [])
            src = src_info[0]['address'][:16] if src_info else 'N/A (UB)'
            dst_start = t.get('destination_start_offset', 'N/A')
            dst_end = t.get('destination_end_offset', 'N/A')
            size = t.get('total_size_bytes', 0)
            burst = f"L={t.get('burst_length', 0)}, C={t.get('burst_count', 0)}"
            stride = f"src={t.get('src_stride', 0)}, dst={t.get('dst_stride', 0)}"
            dtype = t.get('data_type', 'N/A')

            print(f"{t['instr_id']:<6} {t['timestamp']:<8} {t['direction']:<10} "
                  f"{src:<16} {dst_start:<12} {dst_end:<12} {size:<10} {burst:<15} {stride:<20} {dtype}")


if __name__ == '__main__':
    main()