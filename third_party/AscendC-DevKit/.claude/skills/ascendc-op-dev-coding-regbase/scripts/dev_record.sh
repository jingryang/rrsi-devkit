#!/bin/bash
# dev_record.sh - 开发记录目录结构的统一读写接口
# 用法: bash dev_record.sh <子命令> <记录目录> [参数...]
# 子命令: init, get-meta, set-meta, get-progress, set-progress, append-history,
#          expand-kernel, cleanup-kb-cache, update-coding-plan
# 退出码: 0=成功, 1=业务错误, 2=用法错误
#
# 依赖: python3 (JSON 操作), sed, date

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHEMA_PATH="$SCRIPT_DIR/../references/meta-schema.json"

# === JSON 操作工具函数（用 python3 替代 jq）===

# 读取 JSON 字段: json_get <file> [field]
# field 为空时输出整个 JSON；field 支持点分路径如 retries.stage5_compile.used
json_get() {
    local file="$1" field="${2:-}"
    if [ -z "$field" ]; then
        python3 -c "import json,sys; print(json.dumps(json.load(open('$file')),indent=2,ensure_ascii=False))"
    else
        python3 -c "
import json,sys
d=json.load(open('$file'))
keys='$field'.split('.')
for k in keys:
    d=d[k]
if isinstance(d,(dict,list)):
    print(json.dumps(d,ensure_ascii=False))
else:
    print(d)
"
    fi
}

# 设置 JSON 字段: json_set <file> <field> <value>
# 自动检测 value 类型：数字/null/true/false 用原生类型，否则用字符串
json_set() {
    local file="$1" field="$2" value="$3"
    python3 -c "
import json,sys
with open('$file') as f:
    d=json.load(f)
keys='$field'.split('.')
obj=d
for k in keys[:-1]:
    obj=obj[k]
v='$value'
# 类型推断
if v in ('null','None'):
    obj[keys[-1]]=None
elif v in ('true','True'):
    obj[keys[-1]]=True
elif v in ('false','False'):
    obj[keys[-1]]=False
else:
    try:
        parsed=json.loads(v)
        if isinstance(parsed,(list,dict)):
            obj[keys[-1]]=parsed
        else:
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        try:
            obj[keys[-1]]=int(v)
        except ValueError:
            try:
                obj[keys[-1]]=float(v)
            except ValueError:
                obj[keys[-1]]=v
with open('$file','w') as f:
    json.dump(d,f,indent=2,ensure_ascii=False)
    f.write('\n')
"
}

# === 子命令实现 ===

cmd_init() {
    local parent_dir="${1:-}" op_name="${2:-}"
    if [ -z "$parent_dir" ] || [ -z "$op_name" ]; then
        echo "用法: dev_record.sh init <父目录> <算子名>" >&2
        exit 2
    fi
    if [ ! -d "$parent_dir" ]; then
        echo "错误: 父目录不存在: $parent_dir" >&2
        exit 1
    fi

    local timestamp
    timestamp=$(date '+%Y%m%d_%H%M%S')
    local dir_name="${op_name}_dev_${timestamp}"
    local record_dir="$parent_dir/$dir_name"

    mkdir -p "$record_dir/issues"

    # 初始化 meta.json
    cp "$SCHEMA_PATH" "$record_dir/meta.json"
    local now
    now=$(date '+%Y-%m-%d %H:%M:%S')
    json_set "$record_dir/meta.json" "op_name" "$op_name"
    json_set "$record_dir/meta.json" "created_at" "$now"
    json_set "$record_dir/meta.json" "updated_at" "$now"

    # 初始化 progress.md
    cat > "$record_dir/progress.md" << 'PROGRESS_EOF'
| Stage | 状态 | 完成时间 | 备注 |
|-------|------|---------|------|
| 1 环境确认 | ❌ | - | - |
| 2 需求分析 | ❌ | - | - |
| 3 需求澄清 | ❌ | - | - |
| 4.0 编码前置 | ❌ | - | - |
| 4.A 数据结构层（TilingData） | ❌ | - | - |
| 4.B1 OpDef + InferShape | ❌ | - | - |
| 4.B2 Host Tiling | ❌ | - | - |
| 4.C Kernel 实现 | ❌ | - | - |
| 4.E 构建配置（CMakeLists） | ❌ | - | - |
| 4.F 编码后自检 | ❌ | - | - |
| 5 编译出包 | ❌ | - | - |
PROGRESS_EOF

    # 初始化 history.log
    echo "[${now}] [STAGE_START] Stage 1 开始" > "$record_dir/history.log"

    # 初始化空文件
    touch "$record_dir/env_snapshot.md"
    touch "$record_dir/requirements.md"
    touch "$record_dir/clarification.md"
    touch "$record_dir/coding_plan.md"

    echo "$record_dir"
}

cmd_get_meta() {
    local record_dir="${1:-}" field="${2:-}"
    if [ -z "$record_dir" ]; then
        echo "用法: dev_record.sh get-meta <记录目录> [字段]" >&2
        exit 2
    fi
    local meta="$record_dir/meta.json"
    if [ ! -f "$meta" ]; then
        echo "错误: meta.json 不存在: $meta" >&2
        exit 1
    fi
    json_get "$meta" "$field"
}

cmd_set_meta() {
    local record_dir="${1:-}" field="${2:-}" value="${3:-}"
    if [ -z "$record_dir" ] || [ -z "$field" ]; then
        echo "用法: dev_record.sh set-meta <记录目录> <字段> <值>" >&2
        exit 2
    fi
    local meta="$record_dir/meta.json"
    if [ ! -f "$meta" ]; then
        echo "错误: meta.json 不存在: $meta" >&2
        exit 1
    fi
    local now
    now=$(date '+%Y-%m-%d %H:%M:%S')

    # 一次性设置字段并同步 updated_at，减少一次 JSON 读写
    python3 -c "
import json
with open('$meta') as f:
    d = json.load(f)

def set_path(obj, keys, value):
    for k in keys[:-1]:
        obj = obj[k]
    if value in ('null','None'):
        obj[keys[-1]] = None
    elif value in ('true','True'):
        obj[keys[-1]] = True
    elif value in ('false','False'):
        obj[keys[-1]] = False
    else:
        try:
            parsed = json.loads(value)
            if isinstance(parsed, (list, dict)):
                obj[keys[-1]] = parsed
            else:
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            try:
                obj[keys[-1]] = int(value)
            except ValueError:
                try:
                    obj[keys[-1]] = float(value)
                except ValueError:
                    obj[keys[-1]] = value

set_path(d, '$field'.split('.'), '$value')
d['updated_at'] = '$now'
with open('$meta', 'w') as f:
    json.dump(d, f, indent=2, ensure_ascii=False)
    f.write('\n')
print('OK: ${field} = ${value}')
"
}

# 批量设置 meta 字段，减少多次独立调用的 shell 开销
# 用法: dev_record.sh set-meta-batch <记录目录> key1=val1 [key2=val2 ...]
cmd_set_meta_batch() {
    local record_dir="${1:-}"
    if [ -z "$record_dir" ]; then
        echo "用法: dev_record.sh set-meta-batch <记录目录> <字段1>=<值1> [<字段2>=<值2> ...]" >&2
        exit 2
    fi
    shift
    local meta="$record_dir/meta.json"
    if [ ! -f "$meta" ]; then
        echo "错误: meta.json 不存在: $meta" >&2
        exit 1
    fi
    if [ $# -eq 0 ]; then
        echo "用法: dev_record.sh set-meta-batch <记录目录> <字段1>=<值1> [<字段2>=<值2> ...]" >&2
        exit 2
    fi

    local now
    now=$(date '+%Y-%m-%d %H:%M:%S')

    # 构建 key=value 列表传给 python
    local pairs_json="["
    for pair in "$@"; do
        if [[ "$pair" != *"="* ]]; then
            echo "错误: 参数必须是 key=value 格式: $pair" >&2
            exit 2
        fi
        local k="${pair%%=*}"
        local v="${pair#*=}"
        pairs_json+="[\"$k\",\"$v\"],"
    done
    pairs_json="${pairs_json%,}]"

    python3 -c "
import json
pairs = $pairs_json
with open('$meta') as f:
    d = json.load(f)
for k, v in pairs:
    # 复用 json_set 的类型推断逻辑
    if v in ('null','None'):
        d[k] = None
    elif v in ('true','True'):
        d[k] = True
    elif v in ('false','False'):
        d[k] = False
    else:
        try:
            parsed = json.loads(v)
            if isinstance(parsed, (list, dict)):
                d[k] = parsed
            else:
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            try:
                d[k] = int(v)
            except ValueError:
                try:
                    d[k] = float(v)
                except ValueError:
                    d[k] = v
d['updated_at'] = '$now'
with open('$meta', 'w') as f:
    json.dump(d, f, indent=2, ensure_ascii=False)
    f.write('\n')
for k, v in pairs:
    print(f'OK: {k} = {v}')
"
}

cmd_get_progress() {
    local record_dir="${1:-}" stage="${2:-}"
    if [ -z "$record_dir" ]; then
        echo "用法: dev_record.sh get-progress <记录目录> [stage标识]" >&2
        exit 2
    fi
    local progress="$record_dir/progress.md"
    if [ ! -f "$progress" ]; then
        echo "错误: progress.md 不存在: $progress" >&2
        exit 1
    fi
    if [ -z "$stage" ]; then
        cat "$progress"
    else
        grep -F "| ${stage} " "$progress" | head -1
    fi
}

cmd_set_progress() {
    local record_dir="${1:-}" stage="${2:-}" status="${3:-}"
    if [ -z "$record_dir" ] || [ -z "$stage" ] || [ -z "$status" ]; then
        echo "用法: dev_record.sh set-progress <记录目录> <stage标识> <状态符号>" >&2
        echo "  状态符号: ✅ ⏳ ❌ 🔄" >&2
        exit 2
    fi
    local progress="$record_dir/progress.md"
    if [ ! -f "$progress" ]; then
        echo "错误: progress.md 不存在: $progress" >&2
        exit 1
    fi

    local now
    now=$(date '+%Y-%m-%d %H:%M')
    local time_field="$now"
    if [ "$status" != "✅" ]; then
        time_field="-"
    fi

    # 用 python3 做精确行匹配和替换（彻底消除正则/转义/兼容性问题）
    python3 -c "
import sys
stage = '$stage'
status_sym = '$status'
time_field = '$time_field'

with open('$progress', 'r') as f:
    lines = f.readlines()

found = False
for i, line in enumerate(lines):
    # 精确匹配：'| {stage} ' 且 stage 后紧跟非数字非点字符（排除前缀子串）
    marker = f'| {stage} '
    if marker in line:
        # 进一步验证：marker 后的字符不是数字或点（排除 4.C.1 匹配 4.C.10，或 4.C.3.1 匹配 4.C.3.10）
        idx = line.index(marker) + len(marker)
        if idx < len(line) and line[idx] in '0123456789.':
            continue
        # 替换状态和时间字段
        parts = line.split('|')
        if len(parts) >= 5:
            parts[2] = f' {status_sym} '
            parts[3] = f' {time_field} '
            lines[i] = '|'.join(parts)
            found = True
            break

if not found:
    print(f'错误: 未找到匹配行: {stage}', file=sys.stderr)
    sys.exit(1)

with open('$progress', 'w') as f:
    f.writelines(lines)
print(f'OK: {stage} → {status_sym}')
"
}

cmd_append_history() {
    local record_dir="${1:-}" event_type="${2:-}" msg="${3:-}"
    if [ -z "$record_dir" ] || [ -z "$event_type" ] || [ -z "$msg" ]; then
        echo "用法: dev_record.sh append-history <记录目录> <事件类型> <描述>" >&2
        echo "  事件类型: STAGE_START, STAGE_COMPLETE, GATE_PASS, GATE_FAIL, ERROR, REGRESSION, RESUME, CLARIFY, COMPILE, TILING, NEEDS_AGENT, AGENT_COMPLETE, CTX_DRIFT" >&2
        exit 2
    fi
    local history="$record_dir/history.log"
    local now
    now=$(date '+%Y-%m-%d %H:%M')

    echo "[${now}] [${event_type}] ${msg}" >> "$history"
    echo "OK: [${event_type}] ${msg}"
}

# 展开 4.C 占位行为 C.0~C.n 动态行（S2 调用）
cmd_expand_kernel() {
    local record_dir="${1:-}" steps_csv="${2:-}"
    if [ -z "$record_dir" ] || [ -z "$steps_csv" ]; then
        echo "用法: dev_record.sh expand-kernel <记录目录> <步骤列表>" >&2
        echo "  步骤列表格式: C.0:Kernel入口,C.1:类框架,C.2:FP4解包,..." >&2
        exit 2
    fi
    local progress="$record_dir/progress.md"
    if [ ! -f "$progress" ]; then
        echo "错误: progress.md 不存在: $progress" >&2
        exit 1
    fi

    # 幂等检查：如果已经展开过（存在 4.C.0 行），跳过
    if grep -qF "| 4.C.0 " "$progress"; then
        echo "OK: 4.C 已展开，跳过（幂等）"
        return 0
    fi

    # 检查占位行是否存在
    if ! grep -qF "| 4.C Kernel" "$progress"; then
        echo "错误: 未找到 4.C 占位行，无法展开" >&2
        exit 1
    fi

    # 使用 python3 做多行替换（避免 sed 跨平台问题）
    python3 -c "
import sys
steps_csv = '''$steps_csv'''
steps = [s.strip() for s in steps_csv.split(',') if s.strip()]
expanded = []
for step in steps:
    parts = step.split(':', 1)
    sid = parts[0].strip()
    desc = parts[1].strip() if len(parts) > 1 else sid
    expanded.append(f'| 4.{sid} {desc} | ❌ | - | - |')

with open('$progress', 'r') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if '| 4.C Kernel' in line:
        for el in expanded:
            new_lines.append(el + '\n')
    else:
        new_lines.append(line)

with open('$progress', 'w') as f:
    f.writelines(new_lines)
print(f'OK: 展开 {len(expanded)} 个 Kernel 步骤')
"

    # 同步写入 meta.json kernel_steps
    local steps_json="["
    IFS=',' read -ra step_arr <<< "$steps_csv"
    for step in "${step_arr[@]}"; do
        local id="${step%%:*}"
        id="${id// /}"  # trim spaces
        steps_json+="\"${id}\","
    done
    steps_json="${steps_json%,}]"
    json_set "$record_dir/meta.json" "kernel_steps" "$steps_json"
}

# 从 orchestration_plan.json 重新生成 progress.md（派生镜像，不做状态转移依据）
# 状态映射：pending→⏳, done→✅, exhausted→⚠️
cmd_regenerate_progress() {
    local record_dir="${1:-}"
    if [ -z "$record_dir" ]; then
        echo "用法: dev_record.sh regenerate-progress <记录目录>" >&2
        exit 2
    fi
    local plan="$record_dir/orchestration_plan.json"
    if [ ! -f "$plan" ]; then
        echo "INFO: orchestration_plan.json 不存在，跳过" >&2
        exit 0
    fi

    python3 -c "
import json, os, sys
plan_path = '$plan'
try:
    with open(plan_path) as f:
        d = json.load(f)
except Exception as e:
    print(f'错误: orchestration_plan.json 不可解析: {e}', file=sys.stderr)
    sys.exit(1)
steps = d.get('sub_stages') or []
sym = {'pending': '⏳', 'done': '✅', 'exhausted': '⚠️'}
lines = ['| Stage | 状态 | 完成时间 | 备注 |', '|-------|------|---------|------|']
for s in steps:
    sid = s.get('id', '?')
    desc = s.get('desc', '')
    st = sym.get(s.get('status', 'pending'), '⏳')
    lines.append(f'| {sid} {desc} | {st} | - | - |')
with open(os.path.join('$record_dir', 'progress.md'), 'w') as f:
    f.write('\n'.join(lines) + '\n')
print(f'OK: progress.md 已由 orchestration_plan.json 重新生成（{len(steps)} 行）')
"
}

# 删除 coding_index_kb_cache.md 临时缓存（Stage 5 成功后调用）
cmd_cleanup_kb_cache() {
    local record_dir="${1:-}"
    if [ -z "$record_dir" ]; then
        echo "用法: dev_record.sh cleanup-kb-cache <记录目录>" >&2
        exit 2
    fi
    local cache_file="$record_dir/coding_index_kb_cache.md"
    if [ -f "$cache_file" ]; then
        rm -f "$cache_file"
        echo "OK: 已删除 $cache_file"
    else
        echo "OK: 缓存文件不存在，无需清理"
    fi
}

# 按 sub-stage 更新 coding_plan.md 文件状态列
cmd_update_coding_plan() {
    local record_dir="${1:-}"
    local sub_stage="${2:-}"
    local status="${3:-✅}"

    if [ -z "$record_dir" ] || [ -z "$sub_stage" ]; then
        echo "用法: dev_record.sh update-coding-plan <记录目录> <sub_stage> [状态]" >&2
        exit 2
    fi

    local coding_plan="$record_dir/coding_plan.md"
    if [ ! -f "$coding_plan" ]; then
        echo "错误: coding_plan.md 不存在: $coding_plan" >&2
        exit 1
    fi

    # sub_stage 支持 progress.md 完整 ID（4.A/4.B1/4.C.0/4.C.1）或 coding_index 步骤 ID（A/B1/C.0/C.1）
    python3 -c "
import sys
sub_stage = '$sub_stage'
status = '$status'

# 统一去掉 4. 前缀
if sub_stage.startswith('4.'):
    sub_stage = sub_stage[2:]

# 直接映射表：key=步骤 ID，value=coding_plan 的 Sub-stage 列值；None 表示无对应文件行
stage_to_file_stage = {
    '0': None,           # 4.0 编码前置，无产出文件
    'A': 'A',
    'B1': 'B1',
    'B2': 'B2',
    'C.0': 'C.0',
    'C.1~C.n': 'C.1~C.n',
    'E': 'E',
    'F': None,           # 4.F 编码后自检，无产出文件
}

# C.1~C.n 聚合到同一行（兼容 C.1/C.2/.../C.n 以及聚合写法 C.1~C.n）
if sub_stage.startswith('C.') and sub_stage != 'C.0':
    sub_stage = 'C.1~C.n'

target = stage_to_file_stage.get(sub_stage)
if target is None:
    print(f'INFO: {sub_stage} 无对应 coding_plan 文件行，跳过')
    sys.exit(0)

with open('$coding_plan', 'r') as f:
    lines = f.readlines()

found = False
for i, line in enumerate(lines):
    parts = [p.strip() for p in line.split('|')]
    if len(parts) >= 4 and parts[2] == target:
        parts[3] = status
        lines[i] = '| ' + ' | '.join(parts[1:]) + '\n'
        found = True
        break

if not found:
    print(f'错误: 未找到 Sub-stage 为 {target} 的行', file=sys.stderr)
    sys.exit(1)

with open('$coding_plan', 'w') as f:
    f.writelines(lines)
print(f'OK: coding_plan {target} → {status}')
"
}

# 解析 Agent/SubAgent 返回文本中的 ## RETURN: 机器可读标记
# 用法: dev_record.sh parse-return <记录目录> [return文本文件，默认 record_dir/last_return.md]
cmd_parse_return() {
    local record_dir="${1:-}"
    local text_file="${2:-}"
    if [ -z "$record_dir" ]; then
        echo "用法: dev_record.sh parse-return <记录目录> [return文本文件]" >&2
        exit 2
    fi
    if [ -z "$text_file" ]; then
        text_file="$record_dir/last_return.md"
    fi
    if [ ! -f "$text_file" ]; then
        echo "错误: 返回文本文件不存在: $text_file" >&2
        exit 1
    fi

    python3 -c "
import re, sys
with open('$text_file') as f:
    text = f.read()
# 匹配 ## RETURN: status=..., next_stage=... 以及后续 key=value 对
m = re.search(r'^##\\s*RETURN:\\s*([^\\n]+)', text, re.MULTILINE)
if not m:
    print('{\"status\": \"\", \"next_stage\": \"\", \"agent_name\": \"\", \"raw\": \"\"}', file=sys.stderr)
    sys.exit(1)
raw = m.group(1).strip()
result = {'raw': raw}
for key, val in re.findall(r'([a-zA-Z0-9_]+)=([^,\\s]+)', raw):
    result[key] = val
print(__import__('json').dumps(result, ensure_ascii=False))
"
}

# 恢复 PAUSED 流程：将指定 Stage 或当前 🔄 状态置为 ⏳，追加 RESUME 事件
cmd_resume() {
    local record_dir="${1:-}"
    local target_stage="${2:-}"
    if [ -z "$record_dir" ]; then
        echo "用法: dev_record.sh resume <记录目录> [stage标识]" >&2
        exit 2
    fi
    local progress="$record_dir/progress.md"
    local meta="$record_dir/meta.json"
    if [ ! -f "$progress" ] || [ ! -f "$meta" ]; then
        echo "错误: progress.md 或 meta.json 不存在" >&2
        exit 1
    fi

    # 若未指定 stage，查找第一个 🔄 行
    if [ -z "$target_stage" ]; then
        target_stage=$(python3 -c "
import sys
with open('$progress') as f:
    for line in f:
        if '🔄' in line:
            parts = line.split('|')
            if len(parts) >= 2:
                sid = parts[1].strip().split()[0]
                print(sid)
                sys.exit(0)
print('')
")
        if [ -z "$target_stage" ]; then
            echo "错误: 未找到 PAUSED/🔄 状态的 Stage，无法自动恢复" >&2
            exit 1
        fi
    fi

    # 将目标 stage 置为 ⏳
    bash "$SCRIPT_DIR/dev_record.sh" set-progress "$record_dir" "$target_stage" "⏳" >/dev/null

    # 追加 RESUME 事件
    cmd_append_history "$record_dir" RESUME "从 Stage ${target_stage} 恢复"

    # 更新 current_stage：schema 要求为数字 Stage 编号；若 target_stage 是子阶段（如 4.B2），只取主 Stage 编号
    local stage_num
    if [[ "$target_stage" =~ ^([0-9]+) ]]; then
        stage_num="${BASH_REMATCH[1]}"
    else
        stage_num="$target_stage"
    fi
    json_set "$meta" "current_stage" "$stage_num"

    echo "OK: Stage ${target_stage} 已恢复"
}

# === 主入口 ===

CMD="${1:-}"
shift || true

case "$CMD" in
    init)               cmd_init "$@" ;;
    get-meta)           cmd_get_meta "$@" ;;
    set-meta)           cmd_set_meta "$@" ;;
    set-meta-batch)     cmd_set_meta_batch "$@" ;;
    get-progress)       cmd_get_progress "$@" ;;
    set-progress)       cmd_set_progress "$@" ;;
    append-history)     cmd_append_history "$@" ;;
    expand-kernel)      cmd_expand_kernel "$@" ;;
    regenerate-progress) cmd_regenerate_progress "$@" ;;
    cleanup-kb-cache)   cmd_cleanup_kb_cache "$@" ;;
    update-coding-plan) cmd_update_coding_plan "$@" ;;
    parse-return)       cmd_parse_return "$@" ;;
    resume)             cmd_resume "$@" ;;
    *)
        echo "dev_record.sh - 开发记录目录结构读写接口" >&2
        echo "用法: bash dev_record.sh <子命令> <记录目录> [参数...]" >&2
        echo "" >&2
        echo "子命令:" >&2
        echo "  init <父目录> <算子名>             创建开发记录目录" >&2
        echo "  get-meta <目录> [字段]             读取 meta.json" >&2
        echo "  set-meta <目录> <字段> <值>        更新 meta.json" >&2
        echo "  set-meta-batch <目录> <字段1>=<值1> [<字段2>=<值2> ...]  批量更新 meta.json" >&2
        echo "  get-progress <目录> [stage]        读取进度表" >&2
        echo "  set-progress <目录> <stage> <状态>    更新进度行" >&2
        echo "  append-history <目录> <类型> <描述>    追加历史" >&2
        echo "  parse-return <目录> [文本文件]      解析 Agent RETURN 标记" >&2
        echo "  resume <目录> [stage]              恢复 PAUSED 流程" >&2
        echo "  expand-kernel <目录> <步骤列表>     展开 4.C 占位行为 C.0~C.n（历史命令，新流程由 orchestration_plan.json 驱动）" >&2
        echo "  regenerate-progress <目录>           由 orchestration_plan.json 重新生成 progress.md（派生镜像）" >&2
        echo "  cleanup-kb-cache <目录>            删除 coding_index_kb_cache.md 临时缓存（幂等）" >&2
        echo "  update-coding-plan <目录> <sub_stage> [状态]  更新 coding_plan.md 文件状态列" >&2
        exit 2
        ;;
esac
