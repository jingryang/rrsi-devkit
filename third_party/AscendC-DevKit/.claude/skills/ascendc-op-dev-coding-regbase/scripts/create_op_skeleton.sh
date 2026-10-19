#!/bin/bash
# create_op_skeleton.sh - 确保新算子基础目录存在
# 用法: bash create_op_skeleton.sh <新算子目录> [参考算子目录]
#
# 行为:
#   1. 若新算子目录不存在，自动创建空目录
#   2. 若目录已存在且非空，保持现状（不覆盖已有代码）
#   3. 创建 .skeleton 标记文件，记录是否基于参考算子创建
#
# 说明: Stage 1 不生成完整目录结构，仅确保基础目录存在。
#       完整的 op_host / op_kernel / op_api 等子目录由 Stage 4 编码阶段生成。
#
# 退出码: 0=成功, 1=业务错误, 2=用法错误

set -euo pipefail

usage() {
    echo "create_op_skeleton.sh - 确保新算子基础目录存在" >&2
    echo "用法: bash create_op_skeleton.sh <新算子目录> [参考算子目录]" >&2
    exit 2
}

new_dir="${1:-}"
ref_dir="${2:-}"

if [ -z "$new_dir" ]; then
    usage
fi

if [ -e "$new_dir" ] && [ ! -d "$new_dir" ]; then
    echo "错误: 目标路径已存在但不是目录: $new_dir" >&2
    exit 1
fi

# 创建基础目录（幂等）
mkdir -p "$new_dir"

# 写入 .skeleton 标记（如果已存在则覆盖，保持信息最新）
cat > "$new_dir/.skeleton" << EOF
# 本目录由 ascendc-dev Stage 1 自动创建
# 目标目录: $new_dir
# 参考算子: ${ref_dir:-<未提供>}
# 创建时间: $(date '+%Y-%m-%d %H:%M:%S')
# 说明: Stage 1 仅创建基础目录。完整的算子目录结构（op_host/op_kernel/op_api 等）由 Stage 4 生成。
EOF

echo "OK: 已确保算子基础目录存在: $new_dir"
