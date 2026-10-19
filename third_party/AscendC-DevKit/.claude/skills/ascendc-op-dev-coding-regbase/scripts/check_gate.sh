#!/bin/bash
# check_gate.sh - 通用门控检查：验证前置 Stage 是否已完成
# 用法: bash check_gate.sh <开发记录路径> <目标Stage编号>
# 输出: JSON {pass: bool, blocking_stage: string, reason: string}
# 退出码: 0=通过, 1=检查失败, 2=脚本错误

set -euo pipefail

RECORD_INPUT="${1:-}"
TARGET_STAGE="${2:-}"

if [ -z "$RECORD_INPUT" ] || [ -z "$TARGET_STAGE" ]; then
    echo '{"pass": false, "blocking_stage": "", "reason": "用法: check_gate.sh <记录路径或目录> <目标Stage编号>"}'
    exit 2
fi

# 兼容目录模式和文件模式
if [ -d "$RECORD_INPUT" ]; then
    RECORD_PATH="$RECORD_INPUT/progress.md"
elif [ -f "$RECORD_INPUT" ]; then
    RECORD_PATH="$RECORD_INPUT"
else
    echo "{\"pass\": false, \"blocking_stage\": \"\", \"reason\": \"开发记录不存在: ${RECORD_INPUT}\"}"
    exit 1
fi

if [ ! -f "$RECORD_PATH" ]; then
    echo "{\"pass\": false, \"blocking_stage\": \"\", \"reason\": \"进度文件不存在: ${RECORD_PATH}\"}"
    exit 1
fi

# 校验 TARGET_STAGE 为纯数字
if ! echo "$TARGET_STAGE" | grep -qE '^[0-9]+$'; then
    echo "{\"pass\": false, \"blocking_stage\": \"\", \"reason\": \"目标 Stage 编号必须是纯数字: ${TARGET_STAGE}\"}"
    exit 2
fi

# Stage 1 没有前置依赖
if [ "$TARGET_STAGE" -eq 1 ]; then
    echo '{"pass": true, "blocking_stage": "", "reason": "Stage 1 无前置依赖"}'
    exit 0
fi

PREV_STAGE=$((TARGET_STAGE - 1))

# === Stage 4 相关前置：新流程强制要求 coding_index.md ===
if [ "$TARGET_STAGE" -eq 4 ] || [ "$PREV_STAGE" -eq 4 ]; then
    if [ ! -f "$(dirname "$RECORD_PATH")/coding_index.md" ]; then
        echo '{"pass": false, "blocking_stage": "Stage 4", "reason": "coding_index.md 不存在，必须按新流程生成编码索引后才能进入 Stage 4"}'
        exit 1
    fi
fi

# === Stage 4 特殊处理：需要所有子阶段 (4.0, 4.A~4.F, 4.C.N) 都完成 ===
if [ "$PREV_STAGE" -eq 4 ]; then
    # 进度表格式: | 4.0 xxx | 状态 | ... | 或 | 4.A xxx | 状态 | ... | 或 | 4.C.N xxx | 状态 | ... | 或 | 4.C.N.M xxx | 状态 | ... |
    STAGE4_LINES=$(grep -E '^\| 4\.([0-9]|[A-F][0-9]?|C\.[0-9]+(\.[0-9]+)*) ' "$RECORD_PATH" || true)

    if [ -z "$STAGE4_LINES" ]; then
        echo '{"pass": false, "blocking_stage": "Stage 4", "reason": "进度表中未找到 Stage 4 子阶段记录"}'
        exit 1
    fi

    # 遍历每个子阶段，检查是否全部完成
    while IFS= read -r line; do
        if echo "$line" | grep -qv "✅"; then
            SUB_STAGE=$(echo "$line" | sed -n 's/| *\([0-9A-Z.]*\) .*/\1/p')
            CURRENT_STATUS="未完成"
            if echo "$line" | grep -q "⏳"; then
                CURRENT_STATUS="进行中"
            elif echo "$line" | grep -q "❌"; then
                CURRENT_STATUS="未开始"
            elif echo "$line" | grep -q "🔄"; then
                CURRENT_STATUS="需重做"
            fi
            echo "{\"pass\": false, \"blocking_stage\": \"Stage 4\", \"reason\": \"Stage 4 子阶段 ${SUB_STAGE} 当前状态: ${CURRENT_STATUS}，需所有子阶段完成后才能进入 Stage ${TARGET_STAGE}\"}"
            exit 1
        fi
    done <<< "$STAGE4_LINES"

    echo '{"pass": true, "blocking_stage": "", "reason": "Stage 4 所有子阶段已完成"}'
    exit 0
fi
# === Stage 4 特殊处理结束 ===

# Stage 1-3, 5：在进度表中查找前置 Stage 的状态
# 进度表格式: | 1 环境确认 | 状态 | ... |
# 匹配模式: 行首为 "| N "（N 为 Stage 编号，空格分隔）
STAGE_LINE=$(grep -E "^\| ${PREV_STAGE} " "$RECORD_PATH" | head -1)

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
