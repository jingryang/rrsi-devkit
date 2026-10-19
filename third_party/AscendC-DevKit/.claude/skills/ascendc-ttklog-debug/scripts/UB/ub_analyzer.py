#!/usr/bin/env python3
"""
UB Memory Analyzer - 核心解析模块

解析 ub.dump 日志，提供内存访问分析、越界检测、同步分析功能。
优化时间复杂度，支持大日志文件（300000+ 行）。
"""

import re
import json
import sys
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Iterator
from collections import defaultdict

# ============================================================
# 内存映射 — 运行时从 memory_map.json 加载
# ============================================================

MEMORY_MAP: Dict[str, dict] = {}
SORTED_BUFFERS: List = []


def load_memory_map(json_path: str) -> dict:
    """从 JSON 文件加载 memory map"""
    with open(json_path, 'r') as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith('_')}


def set_memory_map(memory_map: dict):
    """设置全局 memory map（原地更新，保持 from-import 引用有效）"""
    MEMORY_MAP.clear()
    MEMORY_MAP.update(memory_map)
    SORTED_BUFFERS.clear()
    SORTED_BUFFERS.extend(sorted(MEMORY_MAP.items(), key=lambda x: x[1]['start']))


def init_from_json(json_path: str):
    """从 JSON 文件加载并设置为当前 memory map"""
    set_memory_map(load_memory_map(json_path))

# ============================================================
# 数据结构
# ============================================================
@dataclass
class MemoryAccess:
    """单次内存访问"""
    timestamp: int
    unit: str           # MTE_W, MTE_R, VEC_LSU_R, VEC_LSU_W, AIV_SU_R, AIV_SU_W
    op_type: str        # RD or WR
    addr: int
    size: int
    req_id: int = 0
    instr_name: str = ""
    instr_id: int = 0
    done_timestamp: int = 0
    _addr_set: bool = False  # 内部标志：addr 是否已从日志中解析设置

    @property
    def end_addr(self) -> int:
        return self.addr + self.size


@dataclass
class MergedAccess:
    """合并后的内存访问"""
    start_time: int
    end_time: int
    unit: str
    op_type: str
    addr_start: int
    addr_end: int
    buffer_name: str
    access_count: int = 1
    instr_ids: List[int] = field(default_factory=list)

    @property
    def size(self) -> int:
        return self.addr_end - self.addr_start

    @property
    def duration(self) -> int:
        return self.end_time - self.start_time


@dataclass
class SyncEvent:
    """同步事件"""
    time: int
    buffer_name: str
    prev_unit: str
    prev_op: str
    prev_time: int
    curr_unit: str
    curr_op: str
    addr_start: int
    addr_end: int
    status: str  # OK, WARNING, ERROR


# ============================================================
# 工具函数
# ============================================================
def find_buffer(addr: int) -> Optional[str]:
    """二分查找地址所属的 buffer，O(log n)"""
    left, right = 0, len(SORTED_BUFFERS) - 1
    while left <= right:
        mid = (left + right) // 2
        name, info = SORTED_BUFFERS[mid]
        if addr < info['start']:
            right = mid - 1
        elif addr >= info['end']:
            left = mid + 1
        else:
            return name
    return None


def check_bounds(addr: int, size: int, op_type: str = 'RD') -> Tuple[Optional[str], bool, str, str]:
    """
    检查地址范围是否越界
    返回: (buffer_name, is_valid, message, severity)
    severity: 'ERROR' (写越界) 或 'WARNING' (读越界)
    """
    buffer_name = find_buffer(addr)

    if buffer_name is None:
        severity = 'ERROR' if op_type == 'WR' else 'WARNING'
        return None, False, f"地址 0x{addr:x} 不属于任何已知 buffer", severity

    info = MEMORY_MAP[buffer_name]
    end_addr = addr + size

    if end_addr > info['end']:
        overflow = end_addr - info['end']
        severity = 'ERROR' if op_type == 'WR' else 'WARNING'
        return buffer_name, False, f"上溢 {overflow}B (访问到 0x{end_addr:x}, buffer 结束于 0x{info['end']:x})", severity

    return buffer_name, True, "OK", "OK"


def ranges_overlap(start1: int, end1: int, start2: int, end2: int) -> bool:
    """检查两个地址范围是否重叠"""
    return not (end1 <= start2 or end2 <= start1)


# ============================================================
# 解析器
# ============================================================
class UBLogParser:
    """UB 日志解析器 - 流式处理，O(n) 时间复杂度"""

    # 正则表达式 - 预编译提高性能
    RE_LOG_LINE = re.compile(r'\[info\]\s+\[(\d+)\]\s+\[([^\]]+)\]\s+(.+)')
    RE_REQ = re.compile(r'\[(\w+)\]\s+req_id\s+(\d+)(?:\s+instr_name\s+(\S+)\s+instr_id\s+(\d+))?')
    RE_ARB_ADDR = re.compile(r'size=(\d+).*?addr=(\S+?)(?:\(|$)')
    RE_VP_RECV = re.compile(r'size=(\d+).*?scat_num=(\d+)\s+addr=(\S+?)(?:\(|$)')
    RE_GRANT_STATS = re.compile(r'(WR|RD)\s+\S+\s+\S+\s+req_id\s+(\d+).*?total\s+(\d+)')
    RE_DONE = re.compile(r'req_id\s+(\d+)')

    def __init__(self):
        self.pending: Dict[int, MemoryAccess] = {}
        self.accesses: List[MemoryAccess] = []
        self._line_count = 0
        self._last_timestamp = 0

    def parse_file(self, filepath: str, progress_callback=None) -> List[MemoryAccess]:
        """解析日志文件，返回所有内存访问"""
        self.pending.clear()
        self.accesses.clear()
        self._line_count = 0

        with open(filepath, 'r') as f:
            for line in f:
                self._line_count += 1
                self._parse_line(line)

                if progress_callback and self._line_count % 50000 == 0:
                    progress_callback(self._line_count)

        # 处理未完成的请求
        for access in self.pending.values():
            if access._addr_set and access.size > 0:
                self.accesses.append(access)

        # 过滤 TilingData 初始化阶段的 AIV_SU_R（第一个 MTE/VEC 事件之前的标量读）
        self._filter_tiling_init_reads()

        return self.accesses

    def _filter_tiling_init_reads(self) -> None:
        """
        移除 TilingData 初始化阶段的访问：
        - 找到第一个 AIV_SU_R 之后的第一个 MTE_W 作为分界点 (cutoff)
        - cutoff 之前的所有 AIV_SU_R → 过滤（标量读 TilingData）
        - 第一个 AIV_SU_R 之前的 MTE_W → 过滤（搬运 TilingData 到 UB）
        """
        sorted_acc = sorted(self.accesses, key=lambda a: a.timestamp)

        # 找第一个 AIV_SU_R
        first_aiv_time = None
        for a in sorted_acc:
            if a.unit == 'AIV_SU_R':
                first_aiv_time = a.timestamp
                break

        if first_aiv_time is None:
            return

        # 找第一个 AIV_SU_R 之后的第一个 MTE_W → cutoff
        cutoff_time = None
        for a in sorted_acc:
            if a.timestamp > first_aiv_time and a.unit == 'MTE_W':
                cutoff_time = a.timestamp
                break

        if cutoff_time is None:
            return

        before = len(self.accesses)
        self.accesses = [
            a for a in self.accesses
            if not (
                # 过滤 cutoff 之前的 AIV_SU_R（TilingData 读取）
                (a.unit == 'AIV_SU_R' and a.timestamp < cutoff_time)
                or
                # 过滤第一个 AIV_SU_R 之前的 MTE_W（TilingData 搬运）
                (a.unit == 'MTE_W' and a.timestamp < first_aiv_time)
            )
        ]
        removed = before - len(self.accesses)
        if removed > 0:
            print(f"已过滤 {removed} 条 TilingData 初始化访问 "
                  f"(AIV_SU_R t<{cutoff_time}, MTE_W t<{first_aiv_time})",
                  file=sys.stderr)

    def _parse_line(self, line: str) -> None:
        match = self.RE_LOG_LINE.match(line)
        if not match:
            return

        timestamp = int(match.group(1))
        self._last_timestamp = timestamp
        event_type = match.group(2)
        content = match.group(3)

        if event_type in ('UB_WR_REQ', 'UB_RD_REQ'):
            self._handle_request(timestamp, event_type, content)
        elif event_type in ('ARB0', 'ARB1'):
            self._handle_arb(content)
        elif event_type == 'VP_RECV':
            self._handle_vp_recv(content)
        elif event_type == 'UB_GRANT_STATS':
            self._handle_grant_stats(content)
        elif event_type in ('UB_WR_DONE', 'UB_RD_DONE'):
            self._handle_done(timestamp, content)

    def _handle_request(self, timestamp: int, event_type: str, content: str) -> None:
        match = self.RE_REQ.search(content)
        if not match:
            return

        unit = match.group(1)
        req_id = int(match.group(2))
        instr_name = match.group(3) or ""
        instr_id = int(match.group(4)) if match.group(4) else 0
        op_type = 'WR' if 'WR' in event_type else 'RD'

        self.pending[req_id] = MemoryAccess(
            timestamp=timestamp,
            unit=unit,
            op_type=op_type,
            addr=0,
            size=0,
            req_id=req_id,
            instr_name=instr_name,
            instr_id=instr_id
        )

    # AIV_SU 单元识别正则 — 从 ARB 内容中提取 [AIV_SU_R] 或 [AIV_SU_W]
    RE_AIV_UNIT = re.compile(r'\[(AIV_SU_[RW])\]')

    def _handle_arb(self, content: str) -> None:
        match = self.RE_ARB_ADDR.search(content)
        if not match:
            return

        # 提取 req_id
        req_match = re.search(r'req_id\s+(\d+)', content)
        if not req_match:
            return

        req_id = int(req_match.group(1))
        if req_id not in self.pending:
            # AIV_SU 没有 UB_WR_REQ/UB_RD_REQ，直接从 ARB0 开始
            aiv_match = self.RE_AIV_UNIT.search(content)
            if not aiv_match:
                return
            unit = aiv_match.group(1)  # AIV_SU_R 或 AIV_SU_W
            op_type = 'RD' if unit.endswith('_R') else 'WR'
            self.pending[req_id] = MemoryAccess(
                timestamp=self._last_timestamp,
                unit=unit,
                op_type=op_type,
                addr=0,
                size=0,
                req_id=req_id,
            )

        size = int(match.group(1))
        addr_str = match.group(2)

        access = self.pending[req_id]
        if not access._addr_set:  # 只记录第一次
            try:
                access.addr = int(addr_str, 16) if addr_str.startswith('0x') else int(addr_str)
            except ValueError:
                pass
            access.size = size
            access._addr_set = True

    def _handle_vp_recv(self, content: str) -> None:
        match = self.RE_VP_RECV.search(content)
        if not match:
            return

        req_match = re.search(r'req_id\s+(\d+)', content)
        if not req_match:
            return

        req_id = int(req_match.group(1))
        if req_id not in self.pending:
            return

        size = int(match.group(1))
        scat_num = int(match.group(2))
        addr_str = match.group(3)

        access = self.pending[req_id]
        if not access._addr_set:
            try:
                access.addr = int(addr_str, 16) if addr_str.startswith('0x') else int(addr_str)
            except ValueError:
                pass
            access.size = size * scat_num
            access._addr_set = True

    def _handle_grant_stats(self, content: str) -> None:
        match = self.RE_GRANT_STATS.search(content)
        if not match:
            return

        req_id = int(match.group(2))
        total_bytes = int(match.group(3))

        if req_id in self.pending:
            access = self.pending[req_id]
            if total_bytes > 0:
                access.size = total_bytes

    def _handle_done(self, timestamp: int, content: str) -> None:
        match = self.RE_DONE.search(content)
        if not match:
            return

        req_id = int(match.group(1))
        if req_id in self.pending:
            access = self.pending[req_id]
            access.done_timestamp = timestamp
            if access._addr_set and access.size > 0:
                self.accesses.append(access)
            del self.pending[req_id]


# ============================================================
# 分析器
# ============================================================
class UBAnalyzer:
    """UB 内存分析器"""

    def __init__(self, accesses: List[MemoryAccess]):
        self.accesses = accesses
        self.by_buffer: Dict[str, List[MemoryAccess]] = defaultdict(list)
        self.unknown_accesses: List[MemoryAccess] = []
        self.bound_errors: List[Tuple[MemoryAccess, str]] = []
        self.merged_by_buffer: Dict[str, List[MergedAccess]] = {}
        self.merged_by_time: List[MergedAccess] = []

        self._classify_accesses()

    def _classify_accesses(self) -> None:
        """将访问按 buffer 分类，O(n log m)，m 是 buffer 数量"""
        for access in self.accesses:
            # AIV_SU 只看起点地址归属，不做越界检查
            if access.unit in ('AIV_SU_R', 'AIV_SU_W'):
                buffer_name = find_buffer(access.addr)
                if buffer_name is None:
                    self.unknown_accesses.append(access)
                else:
                    self.by_buffer[buffer_name].append(access)
                continue

            buffer_name, is_valid, msg, severity = check_bounds(access.addr, access.size, access.op_type)

            if buffer_name is None:
                self.unknown_accesses.append(access)
            elif not is_valid:
                self.bound_errors.append((access, msg, severity))
                self.by_buffer[buffer_name].append(access)
            else:
                self.by_buffer[buffer_name].append(access)

    def merge_accesses_by_buffer(self, time_gap: int = 10, addr_gap: int = 32,
                                    merge_mte_by_instr: bool = False) -> Dict[str, List[MergedAccess]]:
        """
        按 buffer 合并连续访问
        时间复杂度: O(n log n) 排序 + O(n) 合并

        merge_mte_by_instr: 是否按 instr_id 合并 MTE 操作
        """
        self.merged_by_buffer.clear()

        for buffer_name, accesses in self.by_buffer.items():
            if not accesses:
                continue

            # 如果启用 MTE 按指令合并，先处理 MTE 操作
            if merge_mte_by_instr:
                mte_accesses = [a for a in accesses if a.unit in ('MTE_W', 'MTE_R')]
                other_accesses = [a for a in accesses if a.unit not in ('MTE_W', 'MTE_R')]

                # 按 instr_id 合并 MTE
                mte_merged = self._merge_mte_by_instr_id(mte_accesses, buffer_name)

                # VEC/AIV 按原来方式合并
                other_merged = self._merge_access_list(other_accesses, buffer_name, time_gap, addr_gap)

                # 合并结果并按时间排序
                merged = mte_merged + other_merged
                merged.sort(key=lambda m: m.start_time)
            else:
                merged = self._merge_access_list(accesses, buffer_name, time_gap, addr_gap)

            self.merged_by_buffer[buffer_name] = merged

        return self.merged_by_buffer

    def _merge_vec_by_round(self, accesses: List[MemoryAccess], buffer_name: str,
                             round_gap: int = 100) -> List[MergedAccess]:
        """按轮次合并 VEC/AIV 操作

        同一轮次内的访问按 op_type 分别聚合为一条 MergedAccess。
        轮次之间按时间间隔 (round_gap) 切分。
        """
        if not accesses:
            return []

        sorted_acc = sorted(accesses, key=lambda a: a.timestamp)

        # 按时间间隔切分轮次
        rounds = [[sorted_acc[0]]]
        for a in sorted_acc[1:]:
            if a.timestamp - rounds[-1][-1].timestamp > round_gap:
                rounds.append([a])
            else:
                rounds[-1].append(a)

        # 每轮次按 (unit, op_type) 分别聚合，保持 VEC/AIV 分离
        merged = []
        for round_accesses in rounds:
            by_key = defaultdict(list)
            for a in round_accesses:
                by_key[(a.unit, a.op_type)].append(a)

            for (unit, op_type), group in by_key.items():
                start_time = min(a.timestamp for a in group)
                end_time = max(a.done_timestamp or a.timestamp for a in group)
                addr_start = min(a.addr for a in group)
                addr_end = max(a.end_addr for a in group)

                merged.append(MergedAccess(
                    start_time=start_time,
                    end_time=end_time,
                    unit=unit,
                    op_type=op_type,
                    addr_start=addr_start,
                    addr_end=addr_end,
                    buffer_name=buffer_name,
                    access_count=len(group),
                    instr_ids=sorted(set(a.instr_id for a in group if a.instr_id))
                ))

        merged.sort(key=lambda m: m.start_time)
        return merged

    def _merge_mte_by_instr_id(self, accesses: List[MemoryAccess], buffer_name: str) -> List[MergedAccess]:
        """按 instr_id 合并 MTE 操作"""
        if not accesses:
            return []

        # 按 (unit, op_type, instr_id) 分组
        by_instr = {}
        for access in accesses:
            key = (access.unit, access.op_type, access.instr_id)
            if key not in by_instr:
                by_instr[key] = []
            by_instr[key].append(access)

        merged = []
        for (unit, op_type, instr_id), group in by_instr.items():
            if not group:
                continue

            # 合并同一指令的所有访问
            start_time = min(a.timestamp for a in group)
            end_time = max(a.done_timestamp or a.timestamp for a in group)
            addr_start = min(a.addr for a in group)
            addr_end = max(a.end_addr for a in group)
            total_size = sum(a.size for a in group)

            merged.append(MergedAccess(
                start_time=start_time,
                end_time=end_time,
                unit=unit,
                op_type=op_type,
                addr_start=addr_start,
                addr_end=addr_end,
                buffer_name=buffer_name,
                access_count=len(group),
                instr_ids=[instr_id] if instr_id else []
            ))

        return merged

    @staticmethod
    def _unit_category(unit: str) -> str:
        """返回单元大类，用于判断合并屏障"""
        if unit in ('MTE_W', 'MTE_R'):
            return 'MTE'
        if unit.startswith('AIV'):
            return 'AIV'
        return 'VEC'

    def _merge_access_list(self, accesses: List[MemoryAccess], buffer_name: str,
                           time_gap: int, addr_gap: int) -> List[MergedAccess]:
        """合并访问列表

        按时间排序，同 (unit, op_type) 可合并，但不同单元类别
        （VEC_LSU vs AIV_SU）互为屏障——中间出现了另一类操作则断开。
        """
        if not accesses:
            return []

        # 按时间排序，保留真实执行顺序
        sorted_accesses = sorted(accesses, key=lambda a: (a.timestamp, a.addr))

        # 每个 (unit, op_type) 维护一个活跃合并块
        active: Dict[Tuple[str, str], MergedAccess] = {}
        # 记录每个单元大类最后出现的时间戳，用于屏障检测
        last_seen_cat: Dict[str, int] = {}
        merged = []

        for access in sorted_accesses:
            key = (access.unit, access.op_type)
            cat = self._unit_category(access.unit)

            can_merge = False
            if key in active:
                current = active[key]
                # 基本合并条件
                if (access.timestamp - current.end_time <= time_gap and
                    access.addr - current.addr_end <= addr_gap and
                    access.addr >= current.addr_start):
                    # 屏障检测：检查自上次合并以来是否有不同类别的操作介入
                    barrier = False
                    for other_cat, other_ts in last_seen_cat.items():
                        if other_cat != cat and other_ts > current.end_time:
                            barrier = True
                            break
                    can_merge = not barrier

            if can_merge:
                current = active[key]
                current.end_time = max(current.end_time, access.done_timestamp or access.timestamp)
                current.addr_end = max(current.addr_end, access.end_addr)
                current.access_count += 1
                if access.instr_id and access.instr_id not in current.instr_ids:
                    current.instr_ids.append(access.instr_id)
            else:
                # 保存旧的活跃块（如果有）
                if key in active:
                    merged.append(active[key])
                # 开始新块
                active[key] = MergedAccess(
                    start_time=access.timestamp,
                    end_time=access.done_timestamp or access.timestamp,
                    unit=access.unit,
                    op_type=access.op_type,
                    addr_start=access.addr,
                    addr_end=access.end_addr,
                    buffer_name=buffer_name,
                    access_count=1,
                    instr_ids=[access.instr_id] if access.instr_id else []
                )

            last_seen_cat[cat] = access.timestamp

        # 收尾
        for block in active.values():
            merged.append(block)

        merged.sort(key=lambda m: m.start_time)
        return merged

    def merge_accesses_by_time(self, time_gap: int = 10, addr_gap: int = 32,
                                  merge_mte_by_instr: bool = False) -> List[MergedAccess]:
        """
        全局按时间合并，保持时间顺序
        时间复杂度: O(n log n)

        merge_mte_by_instr: 是否按 instr_id 合并 MTE 操作
        """
        if not self.accesses:
            return []

        if merge_mte_by_instr:
            # 分离 MTE 和非 MTE 操作
            mte_accesses = [a for a in self.accesses if a.unit in ('MTE_W', 'MTE_R')]
            other_accesses = [a for a in self.accesses if a.unit not in ('MTE_W', 'MTE_R')]

            # MTE 按 instr_id 合并
            mte_merged = []
            by_instr = {}
            for access in mte_accesses:
                buffer_name = find_buffer(access.addr) or "UNKNOWN"
                key = (buffer_name, access.unit, access.op_type, access.instr_id)
                if key not in by_instr:
                    by_instr[key] = []
                by_instr[key].append(access)

            for (buffer_name, unit, op_type, instr_id), group in by_instr.items():
                start_time = min(a.timestamp for a in group)
                end_time = max(a.done_timestamp or a.timestamp for a in group)
                addr_start = min(a.addr for a in group)
                addr_end = max(a.end_addr for a in group)

                mte_merged.append(MergedAccess(
                    start_time=start_time,
                    end_time=end_time,
                    unit=unit,
                    op_type=op_type,
                    addr_start=addr_start,
                    addr_end=addr_end,
                    buffer_name=buffer_name,
                    access_count=len(group),
                    instr_ids=[instr_id] if instr_id else []
                ))

            # 非 MTE 按 buffer 分组后轮次合并
            by_buffer = defaultdict(list)
            for access in other_accesses:
                buf = find_buffer(access.addr) or "UNKNOWN"
                by_buffer[buf].append(access)

            other_merged = []
            for buf_name, buf_accesses in by_buffer.items():
                other_merged.extend(self._merge_vec_by_round(buf_accesses, buf_name))

            # 合并并按时间排序
            result = mte_merged + other_merged
            result.sort(key=lambda m: m.start_time)
            self.merged_by_time = result
            return result
        else:
            result = self._merge_by_time_internal(self.accesses, time_gap, addr_gap)
            self.merged_by_time = result
            return result

    def _merge_by_time_internal(self, accesses: List[MemoryAccess],
                                 time_gap: int, addr_gap: int) -> List[MergedAccess]:
        """内部时间合并方法，不同单元类别互为屏障"""
        if not accesses:
            return []

        sorted_accesses = sorted(accesses, key=lambda a: (a.timestamp, a.unit, a.addr))

        # 每个 (buffer, unit, op_type) 维护一个活跃的合并块
        active: Dict[Tuple[str, str, str], MergedAccess] = {}
        # 每个 buffer 内记录各单元大类最后出现时间
        last_seen_cat: Dict[Tuple[str, str], int] = {}  # (buffer, cat) -> timestamp
        result: List[MergedAccess] = []

        for access in sorted_accesses:
            buffer_name = find_buffer(access.addr)
            if buffer_name is None:
                buffer_name = "UNKNOWN"

            key = (buffer_name, access.unit, access.op_type)
            cat = self._unit_category(access.unit)

            can_merge = False
            if key in active:
                current = active[key]
                if (access.timestamp - current.end_time <= time_gap and
                    access.addr - current.addr_end <= addr_gap and
                    access.addr >= current.addr_start):
                    # 屏障检测
                    barrier = False
                    for (buf, other_cat), other_ts in last_seen_cat.items():
                        if buf == buffer_name and other_cat != cat and other_ts > current.end_time:
                            barrier = True
                            break
                    can_merge = not barrier

            if can_merge:
                current = active[key]
                current.end_time = max(current.end_time, access.done_timestamp or access.timestamp)
                current.addr_end = max(current.addr_end, access.end_addr)
                current.access_count += 1
                if access.instr_id and access.instr_id not in current.instr_ids:
                    current.instr_ids.append(access.instr_id)
            else:
                if key in active:
                    result.append(active[key])
                active[key] = MergedAccess(
                    start_time=access.timestamp,
                    end_time=access.done_timestamp or access.timestamp,
                    unit=access.unit,
                    op_type=access.op_type,
                    addr_start=access.addr,
                    addr_end=access.end_addr,
                    buffer_name=buffer_name,
                    access_count=1,
                    instr_ids=[access.instr_id] if access.instr_id else []
                )

            last_seen_cat[(buffer_name, cat)] = access.timestamp

        # 添加所有活跃块
        result.extend(active.values())

        # 按开始时间排序
        result.sort(key=lambda m: m.start_time)

        return result

    def analyze_sync(self) -> List[SyncEvent]:
        """
        分析同步问题
        检查不同执行单元对同一 buffer 同一地址范围的读写冲突
        """
        if not self.merged_by_buffer:
            self.merge_accesses_by_buffer()

        sync_events = []

        for buffer_name, merged_list in self.merged_by_buffer.items():
            # 按时间排序
            sorted_merged = sorted(merged_list, key=lambda m: m.start_time)

            # 跟踪每个地址范围的最后写入
            # 简化：只跟踪整个 buffer 的最后写入
            last_write: Optional[MergedAccess] = None

            for access in sorted_merged:
                if access.op_type == 'WR':
                    last_write = access
                elif access.op_type == 'RD' and last_write is not None:
                    # 检查读操作是否与之前的写操作有地址重叠
                    if ranges_overlap(last_write.addr_start, last_write.addr_end,
                                     access.addr_start, access.addr_end):
                        # 检查是否需要同步
                        if last_write.unit != access.unit:
                            # 不同执行单元，需要同步
                            status = "OK"  # 假设代码已处理同步
                            if access.start_time < last_write.end_time:
                                status = "WARNING"  # 可能的竞争

                            sync_events.append(SyncEvent(
                                time=access.start_time,
                                buffer_name=buffer_name,
                                prev_unit=last_write.unit,
                                prev_op='WR',
                                prev_time=last_write.start_time,
                                curr_unit=access.unit,
                                curr_op='RD',
                                addr_start=max(last_write.addr_start, access.addr_start),
                                addr_end=min(last_write.addr_end, access.addr_end),
                                status=status
                            ))

        return sync_events

    def get_statistics(self) -> Dict:
        """获取统计信息"""
        # 统计越界错误和警告
        bound_errors_count = sum(1 for _, _, sev in self.bound_errors if sev == 'ERROR')
        bound_warnings_count = sum(1 for _, _, sev in self.bound_errors if sev == 'WARNING')

        stats = {
            'total_accesses': len(self.accesses),
            'by_buffer': {},
            'by_unit': defaultdict(lambda: {'RD': 0, 'WR': 0, 'bytes_rd': 0, 'bytes_wr': 0}),
            'unknown_accesses': len(self.unknown_accesses),
            'bound_errors': bound_errors_count,
            'bound_warnings': bound_warnings_count,
        }

        for buffer_name, accesses in self.by_buffer.items():
            reads = [a for a in accesses if a.op_type == 'RD']
            writes = [a for a in accesses if a.op_type == 'WR']
            stats['by_buffer'][buffer_name] = {
                'total': len(accesses),
                'reads': len(reads),
                'writes': len(writes),
                'bytes_read': sum(a.size for a in reads),
                'bytes_written': sum(a.size for a in writes),
            }

        for access in self.accesses:
            unit_stats = stats['by_unit'][access.unit]
            unit_stats[access.op_type] += 1
            if access.op_type == 'RD':
                unit_stats['bytes_rd'] += access.size
            else:
                unit_stats['bytes_wr'] += access.size

        stats['by_unit'] = dict(stats['by_unit'])
        return stats


# ============================================================
# 便捷函数
# ============================================================
def parse_and_analyze(filepath: str, progress_callback=None) -> UBAnalyzer:
    """解析日志并返回分析器"""
    if not MEMORY_MAP:
        print("WARNING: MEMORY_MAP 为空，请先通过 init_from_json() 加载 memory_map.json",
              file=sys.stderr)
    parser = UBLogParser()
    accesses = parser.parse_file(filepath, progress_callback)
    return UBAnalyzer(accesses)
