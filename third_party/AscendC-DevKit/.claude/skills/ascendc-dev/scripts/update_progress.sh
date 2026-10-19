#!/bin/bash
# update_progress.sh - 进度度量 V(t) 自动计算并回写开发记录
# 用法: bash hooks/update_progress.sh <开发记录路径>
# 行为: 读取记录中各 Stage 状态，按权重公式计算 V(t)，sed 原地更新 header
# 退出码: 0=更新成功, 1=计算失败, 2=脚本错误

set -euo pipefail

RECORD_PATH="${1:-}"

if [ -z "$RECORD_PATH" ] || [ ! -f "$RECORD_PATH" ]; then
    echo "错误: 开发记录文件不存在: ${RECORD_PATH}" >&2
    exit 2
fi

# 权重定义: Stage 1-5
W1=10  # 0.10 * 100
W2=25  # 0.25 * 100
W3=15  # 0.15 * 100
W4=35  # 0.35 * 100
W5=15  # 0.15 * 100

# 读取各 Stage 状态并转换为分数 (0/50/100)
get_stage_score() {
    local stage_num=$1
    local line
    line=$(grep -E "Stage ${stage_num}" "$RECORD_PATH" | grep -E "\|.*\|" | head -1)

    if echo "$line" | grep -q "✅"; then
        echo 100
    elif echo "$line" | grep -q "⏳"; then
        echo 50
    else
        echo 0
    fi
}

S1=$(get_stage_score 1)
S2=$(get_stage_score 2)
S3=$(get_stage_score 3)
S4=$(get_stage_score 4)
S5=$(get_stage_score 5)

# 计算 V(t) = Σ(w_i * S_i) / 10000
# 使用整数运算避免浮点依赖
NUMERATOR=$(( W1*S1 + W2*S2 + W3*S3 + W4*S4 + W5*S5 ))
# NUMERATOR 范围: 0 ~ 1000000, 除以 10000 得到 0.00 ~ 1.00
VT_INT=$((NUMERATOR / 10000))
VT_FRAC=$(( (NUMERATOR % 10000) / 100 ))

# 格式化为 X.XX
VT=$(printf "%d.%02d" $VT_INT $VT_FRAC)

# 原地更新开发记录中的 V(t) 值
sed -i "s/> \*\*进度度量 V(t)\*\*: .*/> **进度度量 V(t)**: ${VT}/" "$RECORD_PATH"

# 更新最后更新时间
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
sed -i "s/> \*\*最后更新\*\*: .*/> **最后更新**: ${TIMESTAMP}/" "$RECORD_PATH"

echo "V(t) = ${VT} (S1=${S1}, S2=${S2}, S3=${S3}, S4=${S4}, S5=${S5})"
exit 0
