#!/bin/bash
# classify_compile_error.sh - Stage 5: 编译错误自动分类
# 用法: bash hooks/classify_compile_error.sh <编译日志路径>
#   或: <编译输出> | bash hooks/classify_compile_error.sh -
# 输出: JSON {errors: [{type, file, line, message}]}
# 退出码: 0=分类完成, 2=脚本错误

set -uo pipefail

LOG_INPUT="${1:-}"

if [ "$LOG_INPUT" = "-" ]; then
    LOG_CONTENT=$(cat)
elif [ -n "$LOG_INPUT" ] && [ -f "$LOG_INPUT" ]; then
    LOG_CONTENT=$(cat "$LOG_INPUT")
else
    echo '{"errors": [], "note": "无输入或文件不存在"}'
    exit 2
fi

errors="[]"
error_count=0

# 分类函数：将匹配结果追加到 errors 数组
add_error() {
    local type="$1" file="$2" line="$3" message="$4"
    if [ "$error_count" -eq 0 ]; then
        errors="[{\"type\": \"${type}\", \"file\": \"${file}\", \"line\": ${line}, \"message\": \"${message}\"}"
    else
        errors="${errors}, {\"type\": \"${type}\", \"file\": \"${file}\", \"line\": ${line}, \"message\": \"${message}\"}"
    fi
    error_count=$((error_count + 1))
}

# C-SYM: 符号未定义 (undefined reference / undeclared identifier / was not declared)
while IFS= read -r match; do
    if [ -n "$match" ]; then
        file=$(echo "$match" | grep -oP '[\w/.-]+\.(h|cpp|cc)' | head -1)
        line=$(echo "$match" | grep -oP ':(\d+):' | head -1 | tr -d ':')
        add_error "C-SYM" "${file:-unknown}" "${line:-0}" "符号未定义"
    fi
done <<< "$(echo "$LOG_CONTENT" | grep -iE "(undefined reference|undeclared identifier|was not declared|use of undeclared)" || true)"

# C-TYP: 类型不匹配 (cannot convert / no viable conversion / invalid conversion)
while IFS= read -r match; do
    if [ -n "$match" ]; then
        file=$(echo "$match" | grep -oP '[\w/.-]+\.(h|cpp|cc)' | head -1)
        line=$(echo "$match" | grep -oP ':(\d+):' | head -1 | tr -d ':')
        add_error "C-TYP" "${file:-unknown}" "${line:-0}" "类型不匹配"
    fi
done <<< "$(echo "$LOG_CONTENT" | grep -iE "(cannot convert|no viable conversion|invalid conversion|incompatible type)" || true)"

# C-DUP: 重复定义 (multiple definition / redefinition)
while IFS= read -r match; do
    if [ -n "$match" ]; then
        file=$(echo "$match" | grep -oP '[\w/.-]+\.(h|cpp|cc)' | head -1)
        line=$(echo "$match" | grep -oP ':(\d+):' | head -1 | tr -d ':')
        add_error "C-DUP" "${file:-unknown}" "${line:-0}" "重复定义"
    fi
done <<< "$(echo "$LOG_CONTENT" | grep -iE "(multiple definition|redefinition of)" || true)"

# C-LNK: 链接错误 (ld returned / undefined symbol / cannot find -l)
while IFS= read -r match; do
    if [ -n "$match" ]; then
        file=$(echo "$match" | grep -oP '[\w/.-]+\.(h|cpp|cc|o|a)' | head -1)
        add_error "C-LNK" "${file:-linker}" "0" "链接错误"
    fi
done <<< "$(echo "$LOG_CONTENT" | grep -iE "(ld returned|cannot find -l|undefined symbol)" || true)"

# C-API: API 不存在 (no matching function / no member named / has no member)
while IFS= read -r match; do
    if [ -n "$match" ]; then
        file=$(echo "$match" | grep -oP '[\w/.-]+\.(h|cpp|cc)' | head -1)
        line=$(echo "$match" | grep -oP ':(\d+):' | head -1 | tr -d ':')
        add_error "C-API" "${file:-unknown}" "${line:-0}" "API不存在或签名不匹配"
    fi
done <<< "$(echo "$LOG_CONTENT" | grep -iE "(no matching function|no member named|has no member|too many arguments|too few arguments)" || true)"

# 关闭 JSON 数组
if [ "$error_count" -gt 0 ]; then
    errors="${errors}]"
else
    errors="[]"
fi

echo "{\"errors\": ${errors}, \"total\": ${error_count}}"
exit 0
