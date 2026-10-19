#!/usr/bin/env python3
"""
MTE Transfer Analysis - Extract transfer information with deduplication

Key design decisions:
1. UBWIF operations: Keep both send_req and recv_rsp to show full transfer lifecycle
2. Group by req_id to understand actual independent transfers
3. Calculate unique transfer addresses to avoid confusion from duplicate phase logs

Output Format (AI-friendly):
{
  "transfers": [
    {
      "instr_id": 7,
      "direction": "GM -> UB",
      "summary": {
        "total_gm_bytes": 200,
        "total_ub_bytes": 200,
        "unique_gm_addresses": 1,
        "unique_ub_addresses": 2
      },
      "gm_sources": [
        {"address": "0x9003b7d400", "size": 200}
      ],
      "ub_destinations": [
        {"veccore": "veccore0", "offset": "0x3ce80", "size": 128},
        {"veccore": "veccore0", "offset": "0x3cf00", "size": 96}
      ]
    }
  ]
}
"""

import re
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


class MTETransferAnalyzer:
    """Analyze MTE transfers with complete address and size information."""

    def __init__(self, log_file: str):
        self.log_file = Path(log_file)
        self.lines = self._read_log()
        self.transfers: List[Dict[str, Any]] = []

    def _read_log(self) -> List[str]:
        """读取日志文件内容。"""
        with open(self.log_file, 'r', encoding='utf-8') as f:
            return f.readlines()

    def analyze(self) -> Dict[str, Any]:
        """分析 MTE 日志，提取完整的搬运信息。"""
        # 1. 提取 MTE 指令信息
        mte_instructions = self._extract_mte_instructions()

        # 2. 提取 BRIF 请求（包含 GM 地址）
        brif_requests = self._extract_brif_requests()

        # 3. 提取 UBWIF 操作（包含 UB 偏移）
        ubwif_operations = self._extract_ubwif_operations()

        # 4. 提取 UBRIF 操作（包含 UB 源地址，用于 UB->GM）
        ubrif_operations = self._extract_ubrif_operations()

        # 5. 提取 BWIF 操作（包含搬出信息）
        bwif_operations = self._extract_bwif_operations()

        # 6. 提取 MTE retire 事件（包含结束时间戳）
        mte_retire_map = self._extract_mte_retire_events()

        # 7. 组织完整的搬运信息
        for mte_instr in mte_instructions:
            instr_id = mte_instr.get('instr_id')
            if instr_id is None:
                continue

            # 获取相关的 BRIF 请求
            related_brifs = [b for b in brif_requests if b.get('instr_id') == instr_id]

            # 获取相关的 UBWIF 操作
            related_ubwifs = [u for u in ubwif_operations if u.get('instr_id') == instr_id]

            # 获取相关的 UBRIF 操作（UB源地址）
            related_ubrifs = [u for u in ubrif_operations if u.get('instr_id') == instr_id]

            # 获取相关的 BWIF 操作
            related_bwifs = [b for b in bwif_operations if b.get('instr_id') == instr_id]

            # 构建搬运信息
            end_timestamp = mte_retire_map.get(instr_id)
            transfer_info = self._build_transfer_info(mte_instr, related_brifs, related_ubwifs, related_ubrifs, related_bwifs, end_timestamp)
            self.transfers.append(transfer_info)

        # 生成统计信息
        summary = self._generate_summary()

        return {
            'metadata': {
                'source_file': str(self.log_file),
                'total_transfers': len(self.transfers),
                'notes': [
                    "UBWIF operations are grouped by req_id to avoid duplicate phase records.",
                    "Each req_id represents one actual memory transfer operation.",
                    "Multiple UBWIF entries with the same req_id (send_req/recv_rsp/record_map_3)",
                    "represent different phases of the same transfer."
                ]
            },
            'summary': summary,
            'transfers': self.transfers,
        }

    def _build_transfer_info(self, mte_instr: Dict, brifs: List[Dict], ubwifs: List[Dict], ubrifs: List[Dict], bwifs: List[Dict], end_timestamp: Optional[int] = None) -> Dict[str, Any]:
        """构建单个搬运信息，处理重复和去重。"""
        instr_id = mte_instr.get('instr_id')

        # 获取方向字符串
        direction = self._get_direction_str(mte_instr.get('direction', {}))

        # 处理 BRIF GM 源地址（去重）
        gm_sources = self._deduplicate_brif_addresses(brifs)

        # 处理 UBWIF UB 目标地址（按 req_id 去重）
        ub_destinations = self._process_ubwif_addresses(ubwifs)
        ub_sources = []  # UB -> GM 的情况

        # 处理 BWIF GM 目标地址
        gm_destinations = self._deduplicate_bwif_addresses(bwifs)

        # 根据方向修正 ub_sources：UB -> GM 时使用 UBRIF 提取的 UB 源地址
        if direction == 'UB -> GM':
            # 使用 UBRIF 记录构建 ub_sources
            ub_sources = self._process_ubrif_addresses(ubrifs)
            ub_destinations = []

        # 统计摘要
        summary = {
            'total_gm_bytes': sum(b.get('size_bytes', 0) for b in gm_sources) + sum(b.get('size_bytes', 0) for b in gm_destinations),
            'total_ub_bytes': sum(u.get('size_bytes', 0) for u in ub_destinations) + sum(u.get('size_bytes', 0) for u in ub_sources),
            'unique_brif_requests': len(set(b.get('req_id') for b in brifs)),
            'unique_ubwif_requests': len(set(u.get('req_id') for u in ubwifs)),
        }

        if gm_sources:
            summary['unique_gm_source_addresses'] = len(set(s['address'] for s in gm_sources))
        if ub_destinations:
            summary['unique_ub_dest_addresses'] = len(set(d['offset'] for d in ub_destinations))

        return {
            'instr_id': instr_id,
            'timestamp': mte_instr.get('timestamp'),
            'end_timestamp': end_timestamp,
            'mte_unit': mte_instr.get('mte_unit'),
            'direction': direction,
            'summary': summary,
            'gm_sources': gm_sources,
            'ub_destinations': ub_destinations,
            'gm_destinations': gm_destinations,
            'ub_sources': ub_sources,
            'parameters': {
                'burst_len': mte_instr.get('burst_len'),
                'burst_num': mte_instr.get('burst_num'),
                'loop4_size': mte_instr.get('loop4_size'),
                'loop3_size': mte_instr.get('loop3_size'),
                'src_stride': mte_instr.get('src_stride'),
                'dst_stride': mte_instr.get('dst_stride'),
                'pad': [mte_instr.get('pad_left', 0), mte_instr.get('pad_right', 0)],
                'data_type': mte_instr.get('data_type'),
                'element_bytes': mte_instr.get('element_bytes'),
            },
        }

    def _deduplicate_brif_addresses(self, brifs: List[Dict]) -> List[Dict]:
        """对 BRIF 地址去重（按 req_id）。"""
        seen = set()
        unique = []
        for b in brifs:
            if b.get('operation_type') == 'send_cmd':
                key = (b.get('port'), b.get('address'), b.get('size_bytes'))
                if key not in seen:
                    seen.add(key)
                    unique.append({
                        'address': b.get('address'),
                        'size_bytes': b.get('size_bytes'),
                        'port': b.get('port'),
                        'req_id': b.get('req_id'),
                    })
        return unique

    def _deduplicate_bwif_addresses(self, bwifs: List[Dict]) -> List[Dict]:
        """对 BWIF 地址去重。"""
        seen = set()
        unique = []
        for b in bwifs:
            key = b.get('address')
            if key not in seen:
                seen.add(key)
                unique.append({
                    'address': b.get('address'),
                    'size_bytes': b.get('size_bytes'),
                })
        return unique

    def _process_ubwif_addresses(self, ubwifs: List[Dict]) -> List[Dict]:
        """处理 UBWIF 地址，按 req_id 去重，保留唯一的搬运操作。"""
        # 按 req_id 分组
        by_req_id = defaultdict(list)
        for u in ubwifs:
            if u.get('operation') == 'send_req':  # 只保留 send_req 作为实际搬运
                by_req_id[u.get('req_id')].append(u)

        unique_entries = []
        seen = set()

        # 每个 req_id 只保留一个记录（代表一次独立搬运）
        for req_id, entries in sorted(by_req_id.items()):
            for entry in entries:
                key = (entry.get('veccore_id'), entry.get('address'), entry.get('size_bytes'))
                if key not in seen:
                    seen.add(key)
                    unique_entries.append({
                        'veccore': entry.get('veccore_id'),
                        'offset': entry.get('address'),
                        'size_bytes': entry.get('size_bytes'),
                        'req_id': req_id,
                    })

        return unique_entries

    def _process_ubrif_addresses(self, ubrifs: List[Dict]) -> List[Dict]:
        """处理 UBRIF 地址，按 req_id 去重，保留唯一的搬运操作（UB->GM 源地址）。"""
        # 按 req_id 分组
        by_req_id = defaultdict(list)
        for u in ubrifs:
            by_req_id[u.get('req_id')].append(u)

        unique_entries = []
        seen = set()

        # 每个 req_id 只保留一个记录（代表一次独立搬运）
        for req_id, entries in sorted(by_req_id.items()):
            for entry in entries:
                key = (entry.get('veccore_id'), entry.get('address'), entry.get('size_bytes'))
                if key not in seen:
                    seen.add(key)
                    unique_entries.append({
                        'veccore': entry.get('veccore_id'),
                        'offset': entry.get('address'),
                        'size_bytes': entry.get('size_bytes'),
                        'req_id': req_id,
                    })

        return unique_entries

    def _extract_mte_instructions(self) -> List[Dict[str, Any]]:
        """提取所有 MTE 指令信息。"""
        instructions = []
        i = 0

        while i < len(self.lines):
            line = self.lines[i]

            if ('MTE2 instr_id:' in line or 'MTE3 instr_id:' in line) and 'MOV_SRC_TO_DST_ALIGNv2' not in line:
                instr = self._parse_mte_instruction_block(i)
                if instr:
                    instructions.append(instr)

            i += 1

        return instructions

    def _parse_mte_instruction_block(self, start_idx: int) -> Optional[Dict[str, Any]]:
        """解析一个 MTE 指令块。"""
        instruction = {}

        line1 = self.lines[start_idx]
        timestamp_match = re.search(r'\[info\]\s+(\d+):', line1)
        if not timestamp_match:
            return None

        instruction['timestamp'] = int(timestamp_match.group(1))

        params = self._extract_params(line1)
        if params:
            instruction.update(params)
        else:
            return None

        if start_idx + 1 < len(self.lines):
            line2 = self.lines[start_idx + 1]
            if 'MOV_SRC_TO_DST_ALIGNv2' in line2:
                uop_match = re.search(r'rd_uop_cnt\s*=\s*(\d+),\s*wr_uop_cnt:\s*(\d+)', line2)
                if uop_match:
                    instruction['read_uop_count'] = int(uop_match.group(1))
                    instruction['write_uop_count'] = int(uop_match.group(2))

        if start_idx + 2 < len(self.lines):
            line3 = self.lines[start_idx + 2]
            if 'MOV_SRC_TO_DST_ALIGNv2' in line3:
                detail = self._parse_detail_line(line3)
                if detail:
                    instruction.update(detail)

        return instruction

    def _extract_params(self, line: str) -> Optional[Dict[str, Any]]:
        """从一行中提取 MTE 参数。"""
        params = {}

        patterns = {
            'loop4_size': r'loop4_size:\s*(\d+)',
            'loop3_size': r'loop3_size:\s*(\d+)',
            'burst_num': r'isa_para->burst_num:\s*(\d+)',
            'burst_len': r'burst\s*=\s*(\d+)',
            'src_stride': r'src_stride:\s*(\d+)',
            'dst_stride': r'dst_stride:\s*(\d+)',
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, line)
            if match:
                params[key] = int(match.group(1))
            else:
                return None

        pad_match = re.search(r'pad:\s*\((\d+),(\d+)\)', line)
        if pad_match:
            params['pad_left'] = int(pad_match.group(1))
            params['pad_right'] = int(pad_match.group(2))
        else:
            params['pad_left'] = 0
            params['pad_right'] = 0

        instr_id_match = re.search(r' instr_id:\s*(\d+)', line)
        if instr_id_match:
            params['instr_id'] = int(instr_id_match.group(1))

        mte_type_match = re.search(r'MTE(2|3)', line)
        if mte_type_match:
            params['mte_unit'] = int(mte_type_match.group(1))

        return params

    def _parse_detail_line(self, line: str) -> Dict[str, Any]:
        """解析详细的 MTE 信息行。"""
        detail = {}

        pc_match = re.search(r'PC:\s*0x([0-9a-fA-F]+)', line)
        if pc_match:
            detail['pc_address'] = pc_match.group(1)

        id_match = re.search(r'\(ID:\s*(\d+)\)', line)
        if id_match:
            detail['hardware_instruction_id'] = int(id_match.group(1))

        src_match = re.search(r'Src:(\w+)', line)
        dst_match = re.search(r'Dst:(\w+)', line)

        if src_match or dst_match:
            detail['direction'] = {}
            if src_match:
                detail['direction']['src'] = src_match.group(1)
            if dst_match:
                detail['direction']['dst'] = dst_match.group(1)

        addresses = {}
        xd_match = re.search(r'XD:(X?\d+)=0x([0-9a-fA-F]+)', line)
        xn_match = re.search(r'XN:(X?\d+)=0x([0-9a-fA-F]+)', line)

        if xn_match:
            addr_hex = '0x' + xn_match.group(2)
            addresses['src'] = {
                'register': xn_match.group(1),
                'address': addr_hex,
                'is_gm': self._is_gm_address(addr_hex)
            }

        if xd_match:
            addr_hex = '0x' + xd_match.group(2)
            addresses['dst'] = {
                'register': xd_match.group(1),
                'address': addr_hex,
                'is_gm': self._is_gm_address(addr_hex)
            }

        if addresses:
            detail['addresses'] = addresses

        # 对于 UB -> GM 的情况，提取 UB 源地址
        if src_match and dst_match and src_match.group(1) == 'UB' and dst_match.group(1) == 'OUT':
            if xn_match:
                addr_hex = '0x' + xn_match.group(2)
                detail['ub_source_address'] = addr_hex

        dtype_match = re.search(r'Dtype:(B\d+)', line)
        if dtype_match:
            dtype = dtype_match.group(1)
            detail['data_type'] = dtype
            detail['element_bits'] = int(dtype[1:])
            detail['element_bytes'] = int(dtype[1:]) // 8

        return detail

    def _is_gm_address(self, addr: str) -> bool:
        """判断是否为 GM 地址。"""
        try:
            addr_int = int(addr, 16)
            return addr_int >= 0x90000000
        except:
            return False

    def _get_direction_str(self, direction: Dict[str, str]) -> str:
        """获取方向字符串。"""
        src = direction.get('src', '')
        dst = direction.get('dst', '')
        if src == 'OUT' and dst == 'UB':
            return 'GM -> UB'
        elif src == 'UB' and dst == 'OUT':
            return 'UB -> GM'
        else:
            return f"{src} -> {dst}"

    def _extract_brif_requests(self) -> List[Dict[str, Any]]:
        """提取 BRIF 请求（包含 GM 地址）。"""
        requests = []

        for line in self.lines:
            # 匹配 BRIF send_cmd，字段顺序可能不同，分别提取
            if 'BRIF' in line and 'send_cmd' in line:
                port_match = re.search(r'port:\s*(\d+)', line)
                addr_match = re.search(r'addr:\s*(0x[0-9a-fA-F]+)', line)
                size_match = re.search(r'size:\s*(\d+)', line)
                gid_match = re.search(r'gid:\s*(\d+)', line)
                instr_id_match = re.search(r'instr_id:\s*(\d+)', line)
                req_id_match = re.search(r'req_id:\s*(\d+)', line)

                if port_match and addr_match and size_match and instr_id_match and req_id_match:
                    requests.append({
                        'port': int(port_match.group(1)),
                        'address': addr_match.group(1),
                        'size_bytes': int(size_match.group(1)),
                        'gid': int(gid_match.group(1)) if gid_match else None,
                        'instr_id': int(instr_id_match.group(1)),
                        'req_id': int(req_id_match.group(1)),
                        'operation_type': 'send_cmd',
                    })

        return requests

    def _extract_ubwif_operations(self) -> List[Dict[str, Any]]:
        """提取 UBWIF 操作（包含 UB 偏移）。"""
        operations = []

        for line in self.lines:
            # 更宽松的匹配：先找到 UBWIF 行，然后分别提取字段
            if '.mte.UBWIF.' in line:
                veccore_match = re.search(r'core(\d+)\.mte\.UBWIF\.(\w+)', line)
                operation_match = re.search(r'UBWIF\.\w+\s+(\w+),', line)
                addr_match = re.search(r'addr:\s*(0x[0-9a-fA-F]+)', line)
                size_match = re.search(r'size:\s*(\d+)', line)
                instr_id_match = re.search(r'instr_id:\s*(\d+)', line)
                req_id_match = re.search(r'req_id:\s*(\d+)', line)

                if veccore_match and operation_match and addr_match and size_match and instr_id_match and req_id_match:
                    operations.append({
                        'core_id': int(veccore_match.group(1)),
                        'veccore_id': veccore_match.group(2),
                        'operation': operation_match.group(1),
                        'address': addr_match.group(1),
                        'size_bytes': int(size_match.group(1)),
                        'instr_id': int(instr_id_match.group(1)),
                        'req_id': int(req_id_match.group(1)),
                    })

        return operations

    def _extract_ubrif_operations(self) -> List[Dict[str, Any]]:
        """提取 UBRIF 操作（UB 源地址）。"""
        operations = []

        for line in self.lines:
            if '.mte.UBRIF.' in line and 'record_map_3' in line:
                veccore_match = re.search(r'core(\d+)\.mte\.UBRIF\.(\w+)', line)
                addr_match = re.search(r'addr:\s*(0x[0-9a-fA-F]+)', line)
                size_match = re.search(r'size:\s*(\d+)', line)
                instr_id_match = re.search(r'instr_id:\s*(\d+)', line)
                req_id_match = re.search(r'req_id:\s*(\d+)', line)

                if veccore_match and addr_match and size_match and instr_id_match and req_id_match:
                    operations.append({
                        'core_id': int(veccore_match.group(1)),
                        'veccore_id': veccore_match.group(2),
                        'address': addr_match.group(1),
                        'size_bytes': int(size_match.group(1)),
                        'instr_id': int(instr_id_match.group(1)),
                        'req_id': int(req_id_match.group(1)),
                    })

        return operations

    def _extract_bwif_operations(self) -> List[Dict[str, Any]]:
        """提取 BWIF 操作（搬出到 GM）。"""
        operations = []

        for line in self.lines:
            # 更宽松的匹配：先找到 BWIF send_data 行，然后分别提取字段
            if 'BWIF' in line and 'send_data' in line:
                addr_match = re.search(r'addr:\s*(0x[0-9a-fA-F]+)', line)
                size_match = re.search(r'size:\s*(\d+)', line)
                instr_id_match = re.search(r'instr_id:\s*(\d+)', line)

                if addr_match and size_match and instr_id_match:
                    operations.append({
                        'address': addr_match.group(1),
                        'size_bytes': int(size_match.group(1)),
                        'instr_id': int(instr_id_match.group(1)),
                    })

        return operations

    def _extract_mte_retire_events(self) -> Dict[int, int]:
        """提取 MTE retire 事件，返回 {instr_id: end_timestamp} 映射。

        格式: [info] 14292: mte retire: instr_id: 12
        """
        retire_map = {}
        re_retire = re.compile(r'\[info\]\s+(\d+):\s+mte retire:\s+instr_id:\s+(\d+)')
        for line in self.lines:
            m = re_retire.search(line)
            if m:
                timestamp = int(m.group(1))
                instr_id = int(m.group(2))
                retire_map[instr_id] = timestamp
        return retire_map

    def _generate_summary(self) -> Dict[str, Any]:
        """生成统计信息。"""
        stats = {
            'total_transfers': len(self.transfers),
            'direction_counts': {'GM -> UB': 0, 'UB -> GM': 0, 'Other': 0},
            'total_bytes': {'GM -> UB': 0, 'UB -> GM': 0},
            'data_type_counts': defaultdict(int),
        }

        for t in self.transfers:
            direction = t.get('direction', 'Other')
            stats['direction_counts'][direction] = stats['direction_counts'].get(direction, 0) + 1

            # 使用 summary 中的字节数统计
            summary = t.get('summary', {})
            if direction == 'GM -> UB':
                stats['total_bytes']['GM -> UB'] += summary.get('total_gm_bytes', 0)
            elif direction == 'UB -> GM':
                stats['total_bytes']['UB -> GM'] += summary.get('total_ub_bytes', 0)

            # 统计数据类型
            params = t.get('parameters', {})
            dtype = params.get('data_type')
            if dtype:
                stats['data_type_counts'][dtype] += 1

        stats['data_type_counts'] = dict(stats['data_type_counts'])
        return stats


def main():
    if len(sys.argv) < 2:
        print("Usage: python analyze_mte_transfers.py <mte_log_file> [output_json]")
        sys.exit(1)

    log_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"Analyzing MTE log file: {log_file}")
    analyzer = MTETransferAnalyzer(log_file)
    report = analyzer.analyze()

    print(f"\nFound {report['summary']['total_transfers']} transfer instructions.")

    # 输出统计摘要
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(json.dumps(report['summary'], indent=2, ensure_ascii=False))

    # 输出详细搬运信息
    print("\n" + "=" * 80)
    print("DETAILED TRANSFERS (Deduplicated)")
    print("=" * 80)

    for i, transfer in enumerate(report['transfers'], 1):
        print(f"\n[{i}] instr_id={transfer['instr_id']}, direction={transfer['direction']}")
        summary = transfer['summary']
        print(f"    {summary.get('unique_brif_requests', 0)} BRIF requests, {summary.get('unique_ubwif_requests', 0)} UBWIF requests")
        print(f"    Total: {summary.get('total_gm_bytes', 0)}B GM ↔ {summary.get('total_ub_bytes', 0)}B UB")

        if transfer['gm_sources']:
            print(f"    GM sources:")
            for gm in transfer['gm_sources']:
                print(f"        addr={gm['address']}, size={gm['size_bytes']}B (req_id={gm.get('req_id')})")

        if transfer['ub_destinations']:
            print(f"    UB destinations:")
            for ub in transfer['ub_destinations']:
                print(f"        {ub['veccore']}: offset={ub['offset']}, size={ub['size_bytes']}B (req_id={ub.get('req_id')})")

        if transfer['gm_destinations']:
            print(f"    GM destinations:")
            for gm in transfer['gm_destinations']:
                print(f"        addr={gm['address']}, size={gm['size_bytes']}B")

        if transfer['ub_sources']:
            print(f"    UB sources:")
            for ub in transfer['ub_sources']:
                print(f"        {ub['veccore']}: offset={ub['offset']}, size={ub['size_bytes']}B")

    # 保存到文件
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\n\nFull report saved to: {output_file}")


if __name__ == '__main__':
    main()