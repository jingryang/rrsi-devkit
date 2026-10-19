#!/bin/bash
# ============================================================================
# AscendC DevKit — 测试环境验证 & 场景覆盖脚本
# 用法: bash tests/run_checks.sh [all|llm|npu|markers|full]
# ============================================================================
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0

ok()   { echo -e "  ${GREEN}OK${NC}  $1"; PASS=$((PASS+1)); }
fail() { echo -e "  ${RED}FAIL${NC} $1"; FAIL=$((FAIL+1)); }

_run() {
    # 执行命令，输出暂存到临时文件，返回 grep 匹配结果
    local tmp="/tmp/ascendc_check_$$.log"
    eval "$1" > "$tmp" 2>&1
    local rc=$?
    if grep -q "$2" "$tmp"; then
        rm -f "$tmp"
        return 0
    else
        rm -f "$tmp"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# 场景 1：快速开发模式（不连 LLM/NPU/CANN）
# ---------------------------------------------------------------------------
check_default() {
    echo ""
    echo -e "${YELLOW}═══ 快速开发模式 --quick（不连 LLM/NPU/CANN）═══${NC}"
    _run "python -m pytest --co -q --quick" "deselected" && \
        ok "--quick 排除 llm/slow/npu/cann 标记用例" || \
        fail "--quick 收集结果不符预期"
    _run "python -m pytest -q --quick tests/ut/test_layer_dependencies.py -x" "2 passed" && \
        ok "--quick 运行 UT 通过（无预检触发）" || \
        fail "--quick 运行 UT 失败"
}

# ---------------------------------------------------------------------------
# 场景 2：LLM 连通性检查
# ---------------------------------------------------------------------------
check_llm() {
    echo ""
    echo -e "${YELLOW}═══ LLM 连通性检查 ═══${NC}"
    _run "python -m pytest -q -m llm tests/st/test_llm.py::TestLLMRealAPI::test_anthropic_returns_llm_response -x" "LLM: OK" && \
        ok "LLM 预检通过（endpoint reachable, model responded）" || \
        fail "LLM 预检失败"
    _run "python -m pytest -q -m llm tests/st/test_llm.py::TestLLMRealAPI::test_anthropic_returns_llm_response -x" "1 passed" && \
        ok "LLM 测试用例通过" || \
        fail "LLM 测试用例失败"
}

# ---------------------------------------------------------------------------
# 场景 3：NPU 环境检查
# ---------------------------------------------------------------------------
check_npu() {
    echo ""
    echo -e "${YELLOW}═══ NPU 环境检查 ═══${NC}"
    _run "python -m pytest -q -m npu tests/st/test_npu.py -x" "NPU: OK" && \
        ok "NPU 预检通过（torch.npu.device_count > 0）" || \
        fail "NPU 预检失败"
    _run "python -m pytest -q -m npu tests/st/test_npu.py -x" "3 passed" && \
        ok "NPU 测试用例全部通过" || \
        fail "NPU 测试用例未全部通过"
}

# ---------------------------------------------------------------------------
# 场景 4：标记筛选
# ---------------------------------------------------------------------------
check_markers() {
    echo ""
    echo -e "${YELLOW}═══ 标记筛选 ═══${NC}"
    _run "python -m pytest --co -q --no-env-check"  "947 tests collected" && \
        ok "默认全量收集 947 用例" || fail "默认全量收集失败"
    _run "python -m pytest --co -q --ut"        "880 tests collected" && \
        ok "--ut 收集 880 用例" || fail "--ut 失败"
    _run "python -m pytest --co -q --st --no-env-check" "67 tests collected" && \
        ok "--st 收集 67 用例" || fail "--st 失败"
    _run "python -m pytest --co -q -m llm --no-env-check"  "8/947 tests collected" && \
        ok "-m llm 收集 8 用例" || fail "-m llm 失败"
    _run "python -m pytest --co -q -m npu --no-env-check"  "3/947 tests collected" && \
        ok "-m npu 收集 3 用例" || fail "-m npu 失败"
    _run "python -m pytest --co -q --quick"     "16 deselected" && \
        ok "--quick 剔除 16 个 llm/slow/npu/cann 用例" || fail "--quick 失败"
}

# ---------------------------------------------------------------------------
# 场景 5：全量运行
# ---------------------------------------------------------------------------
check_full() {
    echo ""
    echo -e "${YELLOW}═══ 全量运行（UT + ST，含 LLM/NPU/CANN）═══${NC}"
    python -m pytest -q -x 2>&1 | tail -5
}

# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
case "${1:-all}" in
    all)
        check_default
        check_llm
        check_npu
        check_markers
        ;;
    llm)     check_llm ;;
    npu)     check_npu ;;
    markers) check_markers ;;
    full)    check_full ;;
    *)
        echo "用法: bash tests/run_checks.sh [all|llm|npu|markers|full]"
        exit 1
        ;;
esac

echo ""
echo -e "${GREEN}通过: $PASS${NC}  ${RED}失败: $FAIL${NC}"
[[ $FAIL -eq 0 ]] && exit 0 || exit 1
