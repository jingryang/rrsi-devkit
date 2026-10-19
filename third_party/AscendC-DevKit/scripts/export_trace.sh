#!/usr/bin/env bash
# ============================================================================
# export_trace.sh — 一键导出算子生成轨迹（canonical + 2.0 SFT JSONL + 终版代码）
#
# 用法：编辑下方「导出配置」后直接执行，不接受命令行参数：
#   bash scripts/export_trace.sh
#
# 导出内容（每个 run 一个目录，镜像 runs-root 下的相对结构）:
#   canonical/NNN_<ses_id>.json   每个原生会话一条 canonical 记录（时间序）
#   slow_thinking.jsonl           轨迹语料·有思考（含 reasoning）
#   fast_thinking.jsonl           轨迹语料·全空思考
#   code/                         终版算子代码（artifacts/codegen 快照）
#
# 逻辑单源在 scripts/trace_export/export_trace.py，本脚本只做配置转发。
# ============================================================================

# ── 导出配置（按需修改）────────────────────────────────────────────────────
# 导出目标：run id（单次运行）与 batch id（整批）二选一填写，另一个留空。
RUN_ID=""
BATCH_ID=""

# 运行数据根：含 run/batch 目录。留空 = <仓根>/output
RUNS_ROOT=""

# 语料输出根。留空 = <仓根>/trace_export
OUT_ROOT=""

# 只导匹配的原生会话（对会话 id/agent/标题做子串匹配）。留空 = 全部导出
SESSION_FILTER=""

# meta_info 元数据（2.0 SFT schema）：
#   TEACHER       留空 = 取各会话日志中的实际模型 id
#   OWNER         数据责任人；代码侧缺省 unknown，按需在此临时填写
#   QUERY_SOURCE / CATEGORY  语料来源与类目；留空 = operator / code
TEACHER=""
OWNER="unknown"
QUERY_SOURCE=""
CATEGORY=""

# 是否带出终版算子代码 artifacts/codegen → code/（1=带出 0=不带）
WITH_CODE=1
# ───────────────────────────────────────────────────────────────────────────

set -euo pipefail

if [[ $# -gt 0 ]]; then
    echo "ERROR: 本脚本不接受命令行参数，请编辑脚本头部「导出配置」后执行" >&2
    exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENTRY="$REPO_ROOT/scripts/trace_export/export_trace.py"

if [[ ! -f "$ENTRY" ]]; then
    echo "ERROR: entry not found: $ENTRY" >&2
    exit 2
fi

# ── 配置校验（加载期 fail-fast）────────────────────────────────────────────
if [[ -n "$RUN_ID" && -n "$BATCH_ID" ]]; then
    echo "ERROR: RUN_ID 与 BATCH_ID 二选一，不可同时填写" >&2
    exit 2
fi
if [[ -z "$RUN_ID" && -z "$BATCH_ID" ]]; then
    echo "ERROR: 请编辑脚本头部配置：RUN_ID（单次运行）或 BATCH_ID（整批）至少填一个" >&2
    exit 2
fi

# ── 组装参数并转发 ──────────────────────────────────────────────────────────
TARGET="${RUN_ID:-$BATCH_ID}"
ARGS=("$TARGET")
ARGS+=(--runs-root "${RUNS_ROOT:-$REPO_ROOT/output}")
ARGS+=(--out "${OUT_ROOT:-$REPO_ROOT/trace_export}")
[[ -n "$SESSION_FILTER" ]] && ARGS+=(--session "$SESSION_FILTER")
ARGS+=(--teacher "${TEACHER:-}")
ARGS+=(--owner "${OWNER:-}")
ARGS+=(--query-source "${QUERY_SOURCE:-}")
ARGS+=(--category "${CATEGORY:-}")
[[ "$WITH_CODE" != "1" ]] && ARGS+=(--no-code)

echo ">>> export_trace: target=$TARGET"
exec python3 "$ENTRY" "${ARGS[@]}"
