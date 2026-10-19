#!/bin/bash
# check_env.sh - Stage 1: 验证 AscendC 开发环境
# 用法: bash scripts/check_env.sh
# 输出: JSON {pass: bool, missing: [string], details: string}
# 退出码: 0=通过, 1=检查失败, 2=脚本错误

set -euo pipefail

missing=()
details=""

# 检查驱动库路径
DRIVER_DIR="/usr/local/Ascend/driver/lib64/driver"
if [ ! -d "$DRIVER_DIR" ]; then
    missing+=("DRIVER_DIR")
    details="${details}驱动目录 ${DRIVER_DIR} 不存在; "
elif ! echo "${LD_LIBRARY_PATH:-}" | grep -q "$DRIVER_DIR"; then
    missing+=("LD_LIBRARY_PATH")
    details="${details}LD_LIBRARY_PATH 未包含 ${DRIVER_DIR}，请执行 export LD_LIBRARY_PATH=${DRIVER_DIR}:\$LD_LIBRARY_PATH; "
fi

# 检查 ASCEND_TOOLKIT_HOME
if [ -z "${ASCEND_TOOLKIT_HOME:-}" ]; then
    missing+=("ASCEND_TOOLKIT_HOME")
    details="${details}ASCEND_TOOLKIT_HOME 未设置，请执行 source /path/to/cann-x.x.x/set_env.sh; "
fi

# 检查 ASCEND_HOME_PATH (备选环境变量)
if [ -z "${ASCEND_TOOLKIT_HOME:-}" ] && [ -z "${ASCEND_HOME_PATH:-}" ]; then
    missing+=("ASCEND_HOME_PATH")
    details="${details}ASCEND_TOOLKIT_HOME 和 ASCEND_HOME_PATH 均未设置; "
fi

# 检查 ASCEND_OPP_PATH (算子包部署路径)
if [ -z "${ASCEND_OPP_PATH:-}" ]; then
    missing+=("ASCEND_OPP_PATH")
    details="${details}ASCEND_OPP_PATH 未设置，算子包部署将失败; "
fi

# 检查编译工具链
if ! command -v cmake &>/dev/null; then
    missing+=("cmake")
    details="${details}cmake 未找到; "
fi

# 检查 CANN 头文件目录是否存在
if [ -n "${ASCEND_TOOLKIT_HOME:-}" ]; then
    if [ ! -d "${ASCEND_TOOLKIT_HOME}/include" ]; then
        missing+=("CANN_INCLUDE_DIR")
        details="${details}${ASCEND_TOOLKIT_HOME}/include 目录不存在; "
    fi
fi

# 输出 JSON 结果
if [ ${#missing[@]} -eq 0 ]; then
    echo '{"pass": true, "missing": [], "details": "环境检查通过"}'
    exit 0
else
    missing_json=$(printf '"%s",' "${missing[@]}")
    missing_json="[${missing_json%,}]"
    details="${details:-环境检查失败}"
    echo "{\"pass\": false, \"missing\": ${missing_json}, \"details\": \"${details}\"}"
    exit 1
fi
