#!/bin/bash
# ============================================================================
# AscendC DevKit — 端到端真实执行脚本（接真 LLM 跑完整 generate_ascendc）
#
# 目的：把你手敲的 ascendc-devkit run / show / respond / resume 按真实顺序
#       串起来，过程全程打到屏幕，权威日志由 dispatcher 落 output/<run_id>/run.log，方便复盘。
#       —— 不做任何断言，只负责真实执行 + 可见。
#
# 与手敲的等价性：本脚本在你当前 shell、当前 env、当前 TTY 下直接调用
#       ascendc-devkit，命令、参数、环境与你手敲完全一致。
#
# 用法:
#   bash scripts/e2e_run.sh run       # 跑完整管线（默认）
#   bash scripts/e2e_run.sh resume    # 恢复上次 run（用 .last_run_id）
#   bash scripts/e2e_run.sh show <run-id>      # 回放事件
#   bash scripts/e2e_run.sh respond <run-id> <choice>   # 异步应答决策
#
# 安装：默认每次执行先 `pip install -e .` 装当前工程代码（editable，改 .py 即时生效）；
#       已装好不想重复时设 SKIP_INSTALL=1 跳过。
# ============================================================================
set -uo pipefail   # 不加 -e：端到端要看完整过程，非零退出也别中途断

# ───────────────────────────────────────────────────────────────────────────
# 配置区 —— 按你的真实环境填写
# ───────────────────────────────────────────────────────────────────────────
# 仓库根目录（脚本所在目录的上一级），用于解析仓库内固定路径
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

REPO_PROFILE="${REPO_PROFILE:-}"                               # 留空：由 OP_DIR 自解析（改名仓回退时再填）
REPO_ROOT_OVERRIDE="${REPO_ROOT_OVERRIDE:-}"                   # 留空：由 OP_DIR 自解析仓根
# —— 单一驱动：算子目录的绝对路径 ——
# 一条 OP_DIR 自解析出 仓 profile / 仓根 / 编译变体 / 算子全名 / 短名。
# 末段为算子目录名（自定义仓带 ai_infra_ 前缀）。
OP_DIR="${OP_DIR:-/home/x00584171/code/ops-transformer/posembedding/rotary_position_embedding}"
# 可选：跨仓参考检索根（可重复，逗号分隔；留空则用 profile 默认兜底根）
REFERENCES="${REFERENCES:-}"
REQUIREMENT="${REQUIREMENT:-$REPO_ROOT/tests/fixtures/rope_requirements.md}"  # 需求文档路径（.md/.yaml/.txt/.json），留空则不传
GOLDEN="${GOLDEN:-$REPO_ROOT/tests/fixtures/rope_golden.py}"              # 精度基准（golden 参考实现/数据），verify 必需
WORKFLOW="${WORKFLOW:-generate_ascendc}"                       # 完整 9-Stage 管线
NPU_ID="${NPU_ID:-}"                        # 留空不传 → card pool 自动选空闲卡（device 探活保可用）
ON_DECISION="${ON_DECISION:-default}"                          # default 自动选默认 / abort 挂起等 respond
WORKFLOW_TIMEOUT="${WORKFLOW_TIMEOUT:-18000}"                   # 完整管线接真 LLM 较慢，给 30min
STAGE_TIMEOUT="${STAGE_TIMEOUT:-600}"

# —— 可选参数：留空则不传，由 CLI/orchestration-config 用各自默认 ——
MODE="${MODE:-}"                                               # new / incremental，留空用 CLI 默认 new
OUTPUT_ROOT="${OUTPUT_ROOT:-}"                                 # 输出根目录，留空用 CLI 默认 output（detect 也读此变量）
DESIGN_DOC="${DESIGN_DOC:-}"                                   # 概要设计文档路径，留空则不传（CLI flag --general-design，P12 正名）
CHIP_VERSION="${CHIP_VERSION:-}"                               # 设计目标芯片代际码(canonical A2/A3/A5);留空则不传 → CLI probe 本机硬件(CLI flag --design-target-chip,P29 改名;A2=910B/A3=910C/A5=950)
OP_NAME="${OP_NAME:-}"                                         # 算子短名，留空由 OP_DIR 去前缀推导
MAX_ITERATIONS="${MAX_ITERATIONS:-}"                           # 单 Stage 迭代上限
MAX_CORRECTIVE="${MAX_CORRECTIVE:-}"                           # codegen<->verify 纠错回环上限
MAX_ESCALATIONS="${MAX_ESCALATIONS:-}"                         # 设计重写（战略升级）上限
ENABLE_STUBBED="${ENABLE_STUBBED:-0}"                          # 1 → 允许 CANN/NPU 不可用时走 stub 兜底

# run-id 记忆文件（权威日志由 dispatcher 落 output/<run_id>/run.log，不再 tee 副本）
LOG_DIR="${LOG_DIR:-$REPO_ROOT/logs}"
LAST_RUN_FILE="$LOG_DIR/.last_run_id"
mkdir -p "$LOG_DIR"

YELLOW='\033[1;33m'; GREEN='\033[0;32m'; NC='\033[0m'
banner() { echo -e "\n${YELLOW}═══ $1 ═══${NC}"; }

# ───────────────────────────────────────────────────────────────────────────
# 安装 —— 以 editable 模式装当前工程代码
# 跑脚本前通常刚改过工程代码；editable 安装能让改动即时生效（改 .py 不必重装），
# 同时首次能补齐 CLI 与依赖。设 SKIP_INSTALL=1 可跳过（如改了 deps 后想强装则别跳）。
# ───────────────────────────────────────────────────────────────────────────
ensure_installed() {
    if [[ "${SKIP_INSTALL:-0}" == "1" ]]; then
        echo "SKIP_INSTALL=1 → 跳过安装步骤"
        return 0
    fi
    banner "INSTALL — pip install -e (editable) @ $REPO_ROOT"
    echo -e "${GREEN}\$ pip install -e \"$REPO_ROOT\"${NC}\n"
    if ! pip install -e "$REPO_ROOT"; then
        echo -e "${YELLOW}安装失败：请检查 Python 环境后重试，或设 SKIP_INSTALL=1 跳过${NC}"
        exit 1
    fi
}

# ───────────────────────────────────────────────────────────────────────────
# 抓取最近一次 run 的 run-id（从 output/ 下按 mtime 取最新目录）
# ───────────────────────────────────────────────────────────────────────────
detect_latest_run_id() {
    local out_root="${OUTPUT_ROOT:-output}"
    [[ -d "$out_root" ]] || return 1
    local latest
    latest=$(ls -1dt "$out_root"/*/ 2>/dev/null | head -1)
    [[ -n "$latest" ]] && basename "$latest"
}

# ───────────────────────────────────────────────────────────────────────────
# run —— 完整管线
# ───────────────────────────────────────────────────────────────────────────
do_run() {
    banner "RUN — workflow=$WORKFLOW op-dir=$OP_DIR on-decision=$ON_DECISION"

    # 组装命令：OP_DIR 为单一驱动，自解析 profile/仓根/变体/算子名。
    local -a cmd=(ascendc-devkit run
        --workflow "$WORKFLOW"
        --op-dir "$OP_DIR"
        --non-interactive
        --on-decision "$ON_DECISION"
        --workflow-timeout "$WORKFLOW_TIMEOUT"
        --stage-timeout "$STAGE_TIMEOUT")
    [[ -n "${NPU_ID:-}" ]] && cmd+=(--npu-id "$NPU_ID")  # 未指定 → card pool 自动选卡
    # 改名仓回退：显式 profile / 仓根
    [[ -n "$REPO_PROFILE" ]] && cmd+=(--repo-profile "$REPO_PROFILE")
    [[ -n "$REPO_ROOT_OVERRIDE" ]] && cmd+=(--repo-root "$REPO_ROOT_OVERRIDE")
    # 参考检索根（逗号分隔 → 多个 --reference）
    if [[ -n "$REFERENCES" ]]; then
        IFS=',' read -ra _refs <<< "$REFERENCES"
        for r in "${_refs[@]}"; do
            [[ -n "$r" ]] && cmd+=(--reference "$r")
        done
    fi
    [[ -n "$REQUIREMENT" ]] && cmd+=(--requirement "$REQUIREMENT")
    cmd+=(--golden "$GOLDEN")                                       # verify 阶段必需
    # 可选参数：非空才追加，留空交给 CLI/orchestration-config 默认
    [[ -n "$MODE" ]]            && cmd+=(--mode "$MODE")
    [[ -n "$OUTPUT_ROOT" ]]     && cmd+=(--output-root "$OUTPUT_ROOT")
    [[ -n "$DESIGN_DOC" ]]      && cmd+=(--general-design "$DESIGN_DOC")
    [[ -n "$CHIP_VERSION" ]]    && cmd+=(--design-target-chip "$CHIP_VERSION")
    [[ -n "$OP_NAME" ]]         && cmd+=(--op-name "$OP_NAME")
    [[ -n "$MAX_ITERATIONS" ]]  && cmd+=(--max-iterations "$MAX_ITERATIONS")
    [[ -n "$MAX_CORRECTIVE" ]]  && cmd+=(--max-corrective "$MAX_CORRECTIVE")
    [[ -n "$MAX_ESCALATIONS" ]] && cmd+=(--max-escalations "$MAX_ESCALATIONS")
    [[ "$ENABLE_STUBBED" == "1" ]] && cmd+=(--enable-stubbed)

    echo -e "${GREEN}\$ ${cmd[*]}${NC}\n"
    "${cmd[@]}"
    local rc=$?
    echo -e "\n${YELLOW}exit code: $rc${NC}"

    # 记录 run-id 便于后续 resume/show（权威日志 dispatcher 已落 output/$rid/run.log）
    local rid; rid=$(detect_latest_run_id)
    if [[ -n "$rid" ]]; then
        echo "$rid" > "$LAST_RUN_FILE"
        echo "run-id: $rid (已记录到 $LAST_RUN_FILE)；权威日志 → output/$rid/run.log"
        echo -e "\n后续可用：bash scripts/e2e_run.sh show $rid"
    fi
    return $rc
}

# ───────────────────────────────────────────────────────────────────────────
# resume —— 恢复上次 run
# ───────────────────────────────────────────────────────────────────────────
do_resume() {
    local rid="${1:-}"
    [[ -z "$rid" && -f "$LAST_RUN_FILE" ]] && rid=$(cat "$LAST_RUN_FILE")
    if [[ -z "$rid" ]]; then echo "用法: e2e_run.sh resume <run-id>（或先跑过 run）"; exit 1; fi
    banner "RESUME — run-id=$rid"
    echo -e "${GREEN}\$ ascendc-devkit run --resume $rid${NC}\n"
    ascendc-devkit run --resume "$rid"
    echo -e "\n${YELLOW}exit code: $?${NC}"
}

# ───────────────────────────────────────────────────────────────────────────
# respond —— 异步应答挂起的决策（配合 --on-decision abort）
# ───────────────────────────────────────────────────────────────────────────
do_respond() {
    local rid="${1:-}"; local choice="${2:-}"
    [[ -z "$rid" && -f "$LAST_RUN_FILE" ]] && rid=$(cat "$LAST_RUN_FILE")
    if [[ -z "$rid" || -z "$choice" ]]; then echo "用法: e2e_run.sh respond <run-id> <choice>"; exit 1; fi
    banner "RESPOND — run-id=$rid choice=$choice"
    echo -e "${GREEN}\$ ascendc-devkit respond --run $rid --choice $choice${NC}\n"
    ascendc-devkit respond --run "$rid" --choice "$choice"
    echo -e "\n${YELLOW}exit code: $?${NC}"
}

# ───────────────────────────────────────────────────────────────────────────
# show —— 回放事件
# ───────────────────────────────────────────────────────────────────────────
do_show() {
    local rid="${1:-}"
    [[ -z "$rid" && -f "$LAST_RUN_FILE" ]] && rid=$(cat "$LAST_RUN_FILE")
    if [[ -z "$rid" ]]; then echo "用法: e2e_run.sh show <run-id>"; exit 1; fi
    banner "SHOW — run-id=$rid"
    echo -e "${GREEN}\$ ascendc-devkit show --run $rid${NC}\n"
    ascendc-devkit show --run "$rid"
}

# ───────────────────────────────────────────────────────────────────────────
# 入口
# ───────────────────────────────────────────────────────────────────────────
case "${1:-run}" in
    run)     ensure_installed; do_run ;;
    resume)  ensure_installed; do_resume "${2:-}" ;;
    respond) ensure_installed; do_respond "${2:-}" "${3:-}" ;;
    show)    ensure_installed; do_show "${2:-}" ;;
    *) echo "用法: bash scripts/e2e_run.sh [run|resume|respond <id> <choice>|show <id>]"; exit 1 ;;
esac
