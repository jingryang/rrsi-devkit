#!/usr/bin/env python3
"""
UB 内存访问可视化工具

解析 merged_report.log，生成自包含 HTML 文件，以交互式甘特图展示各 buffer 的内存访问时间线。

Usage:
    python visualize.py <merged_report.log> [-o visualization.html]
"""

import re
import sys
import json
import argparse
from collections import OrderedDict


def parse_merged_report(filepath: str) -> dict:
    """解析 merged_report.log，返回结构化数据"""
    buffers = OrderedDict()
    current_buffer = None
    in_records = False

    re_buffer = re.compile(
        r'Buffer:\s+(\S+)\s+\((0x[0-9a-fA-F]+)\s+-\s+(0x[0-9a-fA-F]+),\s+(\d+)B\)'
    )
    re_mte = re.compile(
        r'^\s*(\d+)-(\d+)\s+(MTE_[WR])\s+(\S+)\s+'
        r'(0x[0-9a-fA-F]+)\s+-\s+(0x[0-9a-fA-F]+)\s+'
        r'(\d+)\s+(\d+)\s+(\S+)'
    )
    re_vec = re.compile(
        r'^\s*(\d+)-(\d+)\s+\[(VEC(?:/AIV)?|AIV)\]\s+(\S+)\s+'
        r'(0x[0-9a-fA-F]+)\s+-\s+(0x[0-9a-fA-F]+)\s+'
        r'(\d+)\s+(\d+)\s+(\S+)'
    )
    re_separator = re.compile(r'^[-=]+$')

    with open(filepath, 'r') as f:
        lines = f.readlines()

    for i, line in enumerate(lines):
        stripped = line.rstrip()

        m = re_buffer.search(stripped)
        if m:
            current_buffer = m.group(1)
            buffers[current_buffer] = {
                'start': int(m.group(2), 16),
                'end': int(m.group(3), 16),
                'size': int(m.group(4)),
                'records': []
            }
            in_records = False
            continue

        if current_buffer and re_separator.match(stripped):
            if i > 0 and '时间范围' in lines[i - 1]:
                in_records = True
            continue

        if not current_buffer or not in_records:
            continue

        if stripped.startswith('✓') or stripped.startswith('✗') or stripped.startswith('⚠'):
            in_records = False
            continue

        if stripped.startswith('统计:') or stripped.strip() == '':
            continue

        m = re_mte.match(stripped)
        if m:
            buffers[current_buffer]['records'].append({
                'time_start': int(m.group(1)),
                'time_end': int(m.group(2)),
                'unit': m.group(3),
                'op_type': m.group(4),
                'addr_start': m.group(5),
                'addr_end': m.group(6),
                'size': int(m.group(7)),
                'count': int(m.group(8)),
            })
            continue

        m = re_vec.match(stripped)
        if m:
            label = m.group(3)
            buffers[current_buffer]['records'].append({
                'time_start': int(m.group(1)),
                'time_end': int(m.group(2)),
                'unit': label,
                'op_type': m.group(4),
                'addr_start': m.group(5),
                'addr_end': m.group(6),
                'size': int(m.group(7)),
                'count': int(m.group(8)),
            })

    # 过滤无记录的 buffer
    return {k: v for k, v in buffers.items() if v['records']}


def generate_html(data: dict, output_path: str):
    """生成自包含 HTML 文件"""
    json_data = json.dumps(data, ensure_ascii=False)

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>UB Memory Access Visualization</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'Consolas', 'Monaco', monospace; background: #ffffff; color: #1a1a1a; }}
#toolbar {{
  position: fixed; top: 0; left: 0; right: 0; z-index: 100;
  background: #f5f5f5; padding: 8px 16px; display: flex; align-items: center;
  gap: 16px; border-bottom: 1px solid #d0d0d0; height: 44px;
}}
#toolbar button {{
  background: #e0e0e0; color: #1a1a1a; border: 1px solid #b0b0b0;
  padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 13px;
}}
#toolbar button:hover {{ background: #c8c8c8; }}
.filter-group {{ display: flex; gap: 10px; align-items: center; }}
.filter-group label {{ display: flex; align-items: center; gap: 4px; font-size: 13px; cursor: pointer; }}
.color-dot {{ width: 12px; height: 12px; border-radius: 2px; display: inline-block; }}
#container {{ margin-top: 44px; display: flex; }}
#y-axis {{
  width: 260px; min-width: 260px; overflow-y: auto; overflow-x: hidden;
  background: #fafafa; border-right: 1px solid #d0d0d0;
}}
#y-axis::-webkit-scrollbar {{ width: 6px; }}
#y-axis::-webkit-scrollbar-thumb {{ background: #b0b0b0; border-radius: 3px; }}
#canvas-wrap {{ flex: 1; overflow: hidden; position: relative; }}
canvas {{ display: block; }}
.buf-header {{
  padding: 4px 8px; cursor: pointer; user-select: none;
  background: #f0f0f0; border-bottom: 1px solid #d0d0d0;
  font-weight: bold; font-size: 13px; white-space: nowrap;
}}
.buf-header:hover {{ background: #e0e0e0; }}
.buf-header .arrow {{ display: inline-block; width: 14px; text-align: center; }}
.lane {{
  padding: 2px 8px 2px 24px; font-size: 12px; color: #555;
  border-bottom: 1px solid #e8e8e8; height: 28px; line-height: 24px;
}}
#tooltip {{
  position: fixed; display: none; background: #ffffff; border: 1px solid #b0b0b0;
  padding: 8px 12px; border-radius: 6px; font-size: 12px; pointer-events: none;
  z-index: 200; max-width: 320px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);
}}
#tooltip .tt-title {{ font-weight: bold; margin-bottom: 4px; color: #1a1a1a; }}
#tooltip .tt-row {{ color: #444; }}
</style>
</head>
<body>
<div id="toolbar">
  <button id="btn-expand">全部展开</button>
  <button id="btn-collapse">全部折叠</button>
  <button id="btn-fit">适配视图</button>
  <div class="filter-group">
    <label><input type="checkbox" data-unit="MTE_W" checked>
      <span class="color-dot" style="background:#2563EB"></span> MTE_W</label>
    <label><input type="checkbox" data-unit="MTE_R" checked>
      <span class="color-dot" style="background:#16A34A"></span> MTE_R</label>
    <label><input type="checkbox" data-unit="VEC" checked>
      <span class="color-dot" style="background:#DC2626"></span> VEC</label>
    <label><input type="checkbox" data-unit="AIV" checked>
      <span class="color-dot" style="background:#9333EA"></span> AIV</label>
    <label><input type="checkbox" data-unit="VEC/AIV" checked>
      <span class="color-dot" style="background:#EA580C"></span> VEC/AIV</label>
  </div>
</div>
<div id="container">
  <div id="y-axis"></div>
  <div id="canvas-wrap"><canvas id="gantt"></canvas></div>
</div>
<div id="tooltip"></div>
<script>
// PLACEHOLDER_JS_START
const DATA = {json_data};

const COLORS = {{
  'MTE_W': '#2563EB', 'MTE_R': '#16A34A',
  'VEC': '#DC2626', 'AIV': '#9333EA', 'VEC/AIV': '#EA580C'
}};
const ROW_H = 28, HDR_H = 30, TIME_AXIS_H = 32;

function unitKey(u) {{
  if (u === 'MTE_W' || u === 'MTE_R') return u;
  if (u === 'VEC/AIV') return 'VEC/AIV';
  if (u === 'AIV') return 'AIV';
  return 'VEC';
}}

// State
let bufState = {{}};  // bufName -> {{expanded, lanes: [unitKey]}}
let visibleUnits = new Set(['MTE_W','MTE_R','VEC','AIV','VEC/AIV']);
let timeMin, timeMax, viewStart, viewEnd;
let isDragging = false, dragStartX = 0, dragViewStart = 0;
let hoveredRect = null;

// Init state
(function init() {{
  timeMin = Infinity; timeMax = -Infinity;
  for (const [name, buf] of Object.entries(DATA)) {{
    const lanes = new Set();
    for (const r of buf.records) {{
      const uk = unitKey(r.unit);
      lanes.add(uk);
      if (r.time_start < timeMin) timeMin = r.time_start;
      if (r.time_end > timeMax) timeMax = r.time_end;
    }}
    const sorted = [];
    for (const k of ['MTE_W','MTE_R','VEC','AIV','VEC/AIV']) {{
      if (lanes.has(k)) sorted.push(k);
    }}
    bufState[name] = {{ expanded: true, lanes: sorted }};
  }}
  const pad = Math.max(1, (timeMax - timeMin) * 0.05);
  timeMin -= pad; timeMax += pad;
  viewStart = timeMin; viewEnd = timeMax;
}})();

const yAxis = document.getElementById('y-axis');
const canvasWrap = document.getElementById('canvas-wrap');
const canvas = document.getElementById('gantt');
const ctx = canvas.getContext('2d');
const tooltip = document.getElementById('tooltip');

function buildYAxis() {{
  yAxis.innerHTML = '';
  // Time axis spacer
  const spacer = document.createElement('div');
  spacer.style.height = TIME_AXIS_H + 'px';
  spacer.style.borderBottom = '1px solid #d0d0d0';
  yAxis.appendChild(spacer);

  for (const [name, buf] of Object.entries(DATA)) {{
    const st = bufState[name];
    const hdr = document.createElement('div');
    hdr.className = 'buf-header';
    hdr.style.height = HDR_H + 'px';
    hdr.style.lineHeight = (HDR_H - 4) + 'px';
    const arrow = st.expanded ? '▼' : '▶';
    const info = buf;
    hdr.innerHTML = `<span class="arrow">${{arrow}}</span> ${{name}} (0x${{info.start.toString(16).padStart(5,'0')}}, ${{info.size}}B)`;
    hdr.onclick = () => {{ st.expanded = !st.expanded; buildYAxis(); draw(); }};
    yAxis.appendChild(hdr);

    if (st.expanded) {{
      for (const lane of st.lanes) {{
        const div = document.createElement('div');
        div.className = 'lane';
        const dot = `<span class="color-dot" style="background:${{COLORS[lane] || '#888'}}"></span>`;
        div.innerHTML = dot + ' ' + lane;
        yAxis.appendChild(div);
      }}
    }}
  }}
}}

function getRowLayout() {{
  // Returns array of {{bufName, lane (or null for header), y, h}}
  const rows = [];
  let y = TIME_AXIS_H;
  for (const [name] of Object.entries(DATA)) {{
    const st = bufState[name];
    rows.push({{ bufName: name, lane: null, y, h: HDR_H }});
    y += HDR_H;
    if (st.expanded) {{
      for (const lane of st.lanes) {{
        rows.push({{ bufName: name, lane, y, h: ROW_H }});
        y += ROW_H;
      }}
    }}
  }}
  return rows;
}}

function timeToX(t) {{
  const w = canvas.width;
  return (t - viewStart) / (viewEnd - viewStart) * w;
}}

function xToTime(x) {{
  return viewStart + x / canvas.width * (viewEnd - viewStart);
}}

function draw() {{
  const dpr = window.devicePixelRatio || 1;
  const rect = canvasWrap.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  const rows = getRowLayout();
  const totalH = rows.length > 0 ? rows[rows.length - 1].y + rows[rows.length - 1].h : TIME_AXIS_H + 100;
  canvas.height = Math.max(totalH, rect.height) * dpr;
  canvas.style.width = rect.width + 'px';
  canvas.style.height = Math.max(totalH, rect.height) + 'px';
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const W = rect.width, H = canvas.height / dpr;
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, W, H);

  // Time axis
  drawTimeAxis(W);

  // Row backgrounds
  for (const row of rows) {{
    if (row.lane === null) {{
      ctx.fillStyle = '#f0f0f0';
      ctx.fillRect(0, row.y, W, row.h);
      ctx.strokeStyle = '#d0d0d0';
      ctx.beginPath(); ctx.moveTo(0, row.y + row.h); ctx.lineTo(W, row.y + row.h); ctx.stroke();
    }} else {{
      ctx.fillStyle = '#fafafa';
      ctx.fillRect(0, row.y, W, row.h);
      ctx.strokeStyle = '#e8e8e8';
      ctx.beginPath(); ctx.moveTo(0, row.y + row.h); ctx.lineTo(W, row.y + row.h); ctx.stroke();
    }}
  }}

  // Draw records
  rectCache = [];
  for (const row of rows) {{
    if (row.lane === null) continue;
    if (!visibleUnits.has(row.lane)) continue;
    const buf = DATA[row.bufName];
    for (const r of buf.records) {{
      const uk = unitKey(r.unit);
      if (uk !== row.lane) continue;
      const x1 = timeToX(r.time_start);
      const x2 = timeToX(r.time_end);
      const barW = Math.max(x2 - x1, 3);
      if (x1 + barW < 0 || x1 > W) continue;
      const color = COLORS[uk] || '#888';
      ctx.fillStyle = color;
      const barY = row.y + 3;
      const barH = row.h - 6;
      ctx.fillRect(x1, barY, barW, barH);
      // Lighter border
      ctx.strokeStyle = color.replace(/[0-9a-f]{{2}}$/i, 'ff');
      ctx.strokeRect(x1, barY, barW, barH);
      rectCache.push({{ x: x1, y: barY, w: barW, h: barH, record: r, bufName: row.bufName }});
    }}
  }}

  // Sync y-axis scroll
  yAxis.style.height = canvas.style.height;
}}

let rectCache = [];

function drawTimeAxis(W) {{
  ctx.fillStyle = '#f5f5f5';
  ctx.fillRect(0, 0, W, TIME_AXIS_H);
  ctx.strokeStyle = '#d0d0d0';
  ctx.beginPath(); ctx.moveTo(0, TIME_AXIS_H); ctx.lineTo(W, TIME_AXIS_H); ctx.stroke();

  const range = viewEnd - viewStart;
  const tickTarget = W / 100;
  const rawStep = range / tickTarget;
  const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
  let step = mag;
  if (rawStep / mag > 5) step = mag * 10;
  else if (rawStep / mag > 2) step = mag * 5;
  else if (rawStep / mag > 1) step = mag * 2;

  const start = Math.ceil(viewStart / step) * step;
  ctx.fillStyle = '#555';
  ctx.font = '11px Consolas, monospace';
  ctx.textAlign = 'center';
  for (let t = start; t <= viewEnd; t += step) {{
    const x = timeToX(t);
    ctx.strokeStyle = '#999';
    ctx.beginPath(); ctx.moveTo(x, TIME_AXIS_H - 8); ctx.lineTo(x, TIME_AXIS_H); ctx.stroke();
    // Grid line
    ctx.strokeStyle = '#ececec';
    ctx.beginPath(); ctx.moveTo(x, TIME_AXIS_H); ctx.lineTo(x, canvas.height); ctx.stroke();
    ctx.fillStyle = '#555';
    ctx.fillText(Math.round(t).toString(), x, TIME_AXIS_H - 12);
  }}
}}

// Interactions
canvas.addEventListener('wheel', (e) => {{
  e.preventDefault();
  const rect = canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const t = xToTime(mx);
  const factor = e.deltaY > 0 ? 1.2 : 1 / 1.2;
  const newStart = t - (t - viewStart) * factor;
  const newEnd = t + (viewEnd - t) * factor;
  if (newEnd - newStart > 10 && newEnd - newStart < (timeMax - timeMin) * 10) {{
    viewStart = newStart;
    viewEnd = newEnd;
    draw();
  }}
}});

canvas.addEventListener('mousedown', (e) => {{
  isDragging = true;
  dragStartX = e.clientX;
  dragViewStart = viewStart;
  canvas.style.cursor = 'grabbing';
}});

window.addEventListener('mousemove', (e) => {{
  if (isDragging) {{
    const dx = e.clientX - dragStartX;
    const dt = -dx / canvas.getBoundingClientRect().width * (viewEnd - viewStart);
    const range = viewEnd - viewStart;
    viewStart = dragViewStart + dt;
    viewEnd = viewStart + range;
    draw();
  }}
  // Tooltip
  const rect = canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;
  let found = null;
  for (const r of rectCache) {{
    if (mx >= r.x && mx <= r.x + r.w && my >= r.y && my <= r.y + r.h) {{
      found = r; break;
    }}
  }}
  if (found) {{
    const rec = found.record;
    tooltip.style.display = 'block';
    tooltip.style.left = (e.clientX + 12) + 'px';
    tooltip.style.top = (e.clientY + 12) + 'px';
    tooltip.innerHTML = `
      <div class="tt-title">${{found.bufName}} — ${{rec.unit}}</div>
      <div class="tt-row">时间: ${{rec.time_start}} - ${{rec.time_end}}</div>
      <div class="tt-row">操作: ${{rec.op_type}}</div>
      <div class="tt-row">地址: ${{rec.addr_start}} - ${{rec.addr_end}}</div>
      <div class="tt-row">大小: ${{rec.size}}B, 操作数: ${{rec.count}}</div>`;
  }} else {{
    tooltip.style.display = 'none';
  }}
}});

window.addEventListener('mouseup', () => {{
  isDragging = false;
  canvas.style.cursor = 'default';
}});

// Toolbar
document.getElementById('btn-expand').onclick = () => {{
  for (const st of Object.values(bufState)) st.expanded = true;
  buildYAxis(); draw();
}};
document.getElementById('btn-collapse').onclick = () => {{
  for (const st of Object.values(bufState)) st.expanded = false;
  buildYAxis(); draw();
}};
document.getElementById('btn-fit').onclick = () => {{
  viewStart = timeMin; viewEnd = timeMax; draw();
}};

document.querySelectorAll('.filter-group input').forEach(cb => {{
  cb.addEventListener('change', () => {{
    const u = cb.dataset.unit;
    if (cb.checked) visibleUnits.add(u); else visibleUnits.delete(u);
    draw();
  }});
}});

// Sync scroll
const canvasContainer = document.getElementById('canvas-wrap');
canvasContainer.addEventListener('scroll', () => {{
  yAxis.scrollTop = canvasContainer.scrollTop;
}});
yAxis.addEventListener('scroll', () => {{
  canvasContainer.scrollTop = yAxis.scrollTop;
}});

// Resize
window.addEventListener('resize', () => {{ buildYAxis(); draw(); }});

// Init
buildYAxis();
draw();
</script>
</body>
</html>'''

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)


def main():
    parser = argparse.ArgumentParser(description='UB 内存访问可视化工具')
    parser.add_argument('report', help='merged_report.log 路径')
    parser.add_argument('-o', '--output', default='visualization.html',
                        help='输出 HTML 文件路径')
    args = parser.parse_args()

    print(f"解析: {args.report}", file=sys.stderr)
    data = parse_merged_report(args.report)
    print(f"  找到 {len(data)} 个有访问记录的 buffer", file=sys.stderr)

    for name, buf in data.items():
        print(f"  {name}: {len(buf['records'])} 条记录", file=sys.stderr)

    generate_html(data, args.output)
    print(f"已生成: {args.output}", file=sys.stderr)


if __name__ == '__main__':
    main()
