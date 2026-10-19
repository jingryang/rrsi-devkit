#!/bin/bash
# ============================================================================
# rerun_from_stage.sh — 从指定 stage 恢复运行，重跑该 stage 及其因果下游。
#
# 原理：基于 ascendc-devkit run 内置的 --rerun-from 机制（P68）：
#       1. 将目标节点 + 因果下游在 node_status 中标记为未完成
#       2. 删除 session sidecar，强制 fresh agent spawn
#       3. 重置 gate 计数器
#       GraphExecutor 遍历 workflow 树时自动跳过已完成的节点。
#
# 用法:
#   # 列出可用的 stage 节点
#   bash scripts/rerun_from_stage.sh --list-stages <RUN_ID>
#
#   # 从 codegen 开始重跑（默认）
#   bash scripts/rerun_from_stage.sh <RUN_ID>
#
#   # 指定起跑 stage（裸名，唯一时可用）
#   RERUN_FROM=precision_debug bash scripts/rerun_from_stage.sh <RUN_ID>
#
#   # 指定完整路径（子阶段，重名时必须用完整路径）
#   RERUN_FROM='self_evolve_op/detailed-design/tiling' \
#     bash scripts/rerun_from_stage.sh <RUN_ID>
#
# 环境变量:
#   RERUN_FROM          起始 stage 名或路径（默认 codegen）
#   SKIP_INSTALL        1=跳过 pip install
#   WORKFLOW_TIMEOUT    全局 workflow 超时秒（默认 20000；0=禁用）
#   STAGE_TIMEOUT       单 stage 超时秒（默认 4800；0=禁用）
#   RESUME_OPTS         额外 ascendc-devkit run 参数
#   NO_BACKUP           1=跳过自动备份
# ============================================================================
set -uo pipefail

# ── 环境配置（同 e2e_self_evolve.sh）──────────────────────────────────────
export TORCH_DEVICE_BACKEND_AUTOLOAD="${TORCH_DEVICE_BACKEND_AUTOLOAD:-0}"

_CANN_HOME="${ASCEND_HOME_PATH:-/usr/local/Ascend/cann-9.1.0}"
export LD_LIBRARY_PATH="${_CANN_HOME}/aarch64-linux/lib64:${_CANN_HOME}/lib64:${LD_LIBRARY_PATH}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ── 参数解析 ──────────────────────────────────────────────────────────────
LIST_MODE=0
ARG_RUN_ID=""

for _arg in "$@"; do
    case "$_arg" in
        --list-stages) LIST_MODE=1 ;;
        --help|-h)
            sed -n '2,26p' "$0"
            exit 0
            ;;
        *) ARG_RUN_ID="$_arg" ;;
    esac
done

RUN_ID="${ARG_RUN_ID:-${RUN_ID:-}}"
SNAPSHOT="output/${RUN_ID}/state_snapshot.json"

# ── RUN_ID 校验 ───────────────────────────────────────────────────────────
if [[ -z "$RUN_ID" ]]; then
    echo "Usage: bash scripts/rerun_from_stage.sh [--list-stages] <RUN_ID>"
    echo "       bash scripts/rerun_from_stage.sh --help"
    echo ""
    echo "  RUN_ID  output/<run_id>/ 下的目录名"
    echo ""
    echo "  示例:"
    echo "    bash scripts/rerun_from_stage.sh --list-stages <RUN_ID>"
    echo "    RERUN_FROM=codegen bash scripts/rerun_from_stage.sh <RUN_ID>"
    exit 1
fi

if [[ ! -f "$SNAPSHOT" ]]; then
    echo "ERROR: state snapshot not found: $SNAPSHOT"
    echo "  可用的 run 见 output/ 目录："
    ls -d output/*/ 2>/dev/null | head -10 | while read -r d; do
        echo "    $(basename "$d")"
    done
    exit 2
fi

# ── list-stages：展示完整 node_status 树 ─────────────────────────────────
_run_python() {
    python3 -c "$1" 2>/dev/null
}

if [[ "$LIST_MODE" == "1" ]]; then
    # 用临时 Python 脚本文件，避免 shell 变量转义问题（set -u 下 $wf 等会报错）
    _TMP_PY=$(mktemp /tmp/rerun_list_stages.XXXXXX.py)
    trap "rm -f $_TMP_PY" EXIT

    cat > "$_TMP_PY" << 'PYEOF'
import json, sys

snapshot = sys.argv[1]
run_id   = sys.argv[2]

d  = json.load(open(snapshot))
ns = d.get("node_status", {})
wf = d.get("workflow_name", "unknown")

print(f"\n  workflow: {wf}  —  run: {run_id}")
print("  " + "─" * 44)

paths = sorted(ns.keys())
if not paths:
    print("  (empty — no stages recorded)")
    sys.exit(0)

# 去掉根前缀，构建层级结构
root_prefix = wf + "/" if wf else ""

# 构建树结构：按路径段分组
# tree_nodes[()] = ["entry", "context", ...]  (根级的子节点列表)
# tree_nodes[("entry",)] = []  叶子节点没有子节点
children = {}   # parent_tuple -> sorted list of child_names
all_keys = set()

for p in paths:
    display = p
    if root_prefix and p.startswith(root_prefix):
        display = p[len(root_prefix):]
    parts = tuple(display.split("/")) if display else ()
    all_keys.add(parts)
    parent = parts[:-1]
    child_name = parts[-1] if parts else display
    children.setdefault(parent, []).append((child_name, ns.get(p, "unknown"), p))
    # 确保中间节点也被注册（即使没有独立 entry）
    for i in range(1, len(parts)):
        mid = parts[:i]
        children.setdefault(mid, [])

# 去重并排序每个父节点的子节点
for parent in list(children.keys()):
    seen = set()
    unique = []
    for name, st, full_path in children[parent]:
        if name not in seen:
            seen.add(name)
            unique.append((name, st, full_path))
    children[parent] = sorted(unique, key=lambda x: x[0])

# 递归打印树
def print_tree(parent, prefix=""):
    kids = children.get(parent, [])
    for i, (name, status, full_path) in enumerate(kids):
        is_last = (i == len(kids) - 1)
        # 本级连接线
        connector = "└─ " if is_last else "├─ "
        # 下级前缀延续
        extension = "   " if is_last else "│  "

        icon = {"completed": "✅", "failed": "❌"}.get(status, "⏳")
        line = f"  {icon} {prefix}{connector}{name}"
        # 填充对齐状态标签
        pad = max(2, 30 - len(prefix) - len(name))
        line += " " * pad + f"({status})"

        # 如果这是默认起跑点，标记一下
        if name == "codegen" and parent == ():
            line += "  ← 默认"

        print(line)

        # 递归子节点
        child_key = parent + (name,)
        if child_key in children:
            print_tree(child_key, prefix + extension)

# 从根开始打印
print_tree(())

# 收集所有裸名，标记重名
from collections import Counter
name_counts = Counter()
for parts in all_keys:
    if parts:
        name_counts[parts[-1]] += 1
duplicates = {n for n, c in name_counts.items() if c > 1}

print("")
print("  ⚠ 重名节点必须用完整路径：")
for n in sorted(duplicates):
    paths_with = [p for p in sorted(paths) if p.endswith("/" + n) or p == n]
    print(f"    {n}  ({len(paths_with)} 个)")
    for p in paths_with[:5]:
        print(f"      → {p}")
print(f"\n  用法：RERUN_FROM=<stage> bash scripts/rerun_from_stage.sh {run_id}")
print(f"        stage 可以是裸名（唯一时）或完整路径（如 {wf}/codegen）")
PYEOF

    python3 "$_TMP_PY" "$SNAPSHOT" "$RUN_ID"
    rm -f "$_TMP_PY"
    trap - EXIT
    exit 0
fi

# ── 起跑 stage ────────────────────────────────────────────────────────────
RERUN_FROM="${RERUN_FROM:-codegen}"

# ── 自动备份 ──────────────────────────────────────────────────────────────
# 如果目标 stage 已完成 → 这是「重跑」而非「续跑」→ 备份当前结果
# 如果目标 stage 不存在或未完成 → 中断恢复 → 不备份（没必要）
BACKUP_DIR="output/${RUN_ID}/rerun_backups"
_NEED_BACKUP=0
if [[ "${NO_BACKUP:-0}" != "1" ]] && command -v python3 &>/dev/null; then
    _TMP_BKP=$(mktemp /tmp/rerun_backup_check.XXXXXX.py)
    cat > "$_TMP_BKP" << 'PYEOF_BKP'
import json, sys
snapshot, target = sys.argv[1], sys.argv[2]
d = json.load(open(snapshot))
ns = d.get("node_status", {})
# 裸名匹配任意路径后缀，完整路径精确匹配
keys = [k for k in ns if k == target or k.endswith("/" + target)]
done = any(ns.get(k) == "completed" for k in keys)
print("1" if done else "0")
PYEOF_BKP
    _NEED_BACKUP=$(python3 "$_TMP_BKP" "$SNAPSHOT" "$RERUN_FROM" 2>/dev/null)
    rm -f "$_TMP_BKP"
fi

if [[ "${_NEED_BACKUP:-0}" == "1" ]]; then
    _SEQ=1
    for _d in "$BACKUP_DIR"/*/; do
        _bn=$(basename "$_d")
        if [[ "$_bn" =~ ^[0-9]{3}$ ]] && (( _bn >= _SEQ )); then
            _SEQ=$((_bn + 1))
        fi
    done
    _DST=$(printf "%s/%03d" "$BACKUP_DIR" "$_SEQ")
    mkdir -p "$_DST"
    cp "$SNAPSHOT" "$_DST/state_snapshot.json"
    for _r in output/"$RUN_ID"/report.md output/"$RUN_ID"/report.json; do
        [[ -f "$_r" ]] && cp "$_r" "$_DST/"
    done
    echo "[backup]  #$_SEQ → rerun_backups/$(printf "%03d" "$_SEQ")/"
    echo "          (NO_BACKUP=1 可跳过备份)"
fi

echo "═══════════════════════════════════════════════════════════════"
echo "  rerun from '$RERUN_FROM': run=$RUN_ID"
echo "  snapshot:     $SNAPSHOT"
echo "═══════════════════════════════════════════════════════════════"

# ── 安装 ─────────────────────────────────────────────────────────────────
if [[ "${SKIP_INSTALL:-0}" != "1" ]]; then
    echo "[install] pip install -e $REPO_ROOT"
    pip install -e "$REPO_ROOT" || { echo "安装失败"; exit 1; }
fi

# ── 执行 ─────────────────────────────────────────────────────────────────
WORKFLOW_TIMEOUT="${WORKFLOW_TIMEOUT:-20000}"
STAGE_TIMEOUT="${STAGE_TIMEOUT:-4800}"
CONTROL_OPTS=(--non-interactive --on-decision default
  --workflow-timeout "$WORKFLOW_TIMEOUT" --stage-timeout "$STAGE_TIMEOUT")

# shellcheck disable=SC2086
ascendc-devkit run \
  --resume "$RUN_ID" \
  --rerun-from "$RERUN_FROM" \
  "${CONTROL_OPTS[@]}" \
  ${RESUME_OPTS:-}
RC=$?

echo ""
echo "exit code: $RC"
echo "[log]    → output/$RUN_ID/run.log"
exit $RC
