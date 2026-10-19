#!/bin/bash
# check_gate.sh - 通用门控检查：验证前置 Stage 是否已完成
# 用法: bash hooks/check_gate.sh <开发记录路径> <目标Stage编号>
# 输出: JSON {pass: bool, blocking_stage: string, reason: string}
# 退出码: 0=通过, 1=检查失败, 2=脚本错误

set -euo pipefail

RECORD_PATH="${1:-}"
TARGET_STAGE="${2:-}"

if [ -z "$RECORD_PATH" ] || [ -z "$TARGET_STAGE" ]; then
    echo '{"pass": false, "blocking_stage": "", "reason": "用法: check_gate.sh <记录路径> <目标Stage编号>"}'
    exit 2
fi

if [ ! -f "$RECORD_PATH" ]; then
    echo "{\"pass\": false, \"blocking_stage\": \"\", \"reason\": \"开发记录文件不存在: ${RECORD_PATH}\"}"
    exit 1
fi

# Stage 1 没有前置依赖
if [ "$TARGET_STAGE" -eq 1 ]; then
    echo '{"pass": true, "blocking_stage": "", "reason": "Stage 1 无前置依赖"}'
    exit 0
fi

# 检查前置 Stage 是否标记为 ✅
PREV_STAGE=$((TARGET_STAGE - 1))

# 在进度表中查找前置 Stage 的状态
# 进度表格式: | Stage N: xxx | 状态 | 门控 | 完成时间 | 备注 |
STAGE_LINE=$(grep -E "Stage ${PREV_STAGE}" "$RECORD_PATH" | head -1)

if [ -z "$STAGE_LINE" ]; then
    echo "{\"pass\": false, \"blocking_stage\": \"Stage ${PREV_STAGE}\", \"reason\": \"进度表中未找到 Stage ${PREV_STAGE} 记录\"}"
    exit 1
fi

# 检查是否包含 ✅ 标记
if echo "$STAGE_LINE" | grep -q "✅"; then
    echo "{\"pass\": true, \"blocking_stage\": \"\", \"reason\": \"Stage ${PREV_STAGE} 已完成\"}"
    exit 0
else
    # 获取当前状态
    CURRENT_STATUS="未完成"
    if echo "$STAGE_LINE" | grep -q "⏳"; then
        CURRENT_STATUS="进行中"
    elif echo "$STAGE_LINE" | grep -q "❌"; then
        CURRENT_STATUS="未开始"
    elif echo "$STAGE_LINE" | grep -q "🔄"; then
        CURRENT_STATUS="需重做"
    fi
    echo "{\"pass\": false, \"blocking_stage\": \"Stage ${PREV_STAGE}\", \"reason\": \"Stage ${PREV_STAGE} 当前状态: ${CURRENT_STATUS}，需完成后才能进入 Stage ${TARGET_STAGE}\"}"
    exit 1
fi
