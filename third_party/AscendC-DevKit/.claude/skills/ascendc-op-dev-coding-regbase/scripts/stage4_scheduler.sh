#!/bin/bash
# stage4_scheduler.sh - Stage 4 sub-stage orchestration helpers (thin wrapper)
# 真实实现已迁入编排层 = ascendc_devkit.orchestration.stages.codegen_s4。
# 本脚本仅为向后兼容保留（shell 测试 / 独立调用），转发到编排层 CLI 入口。
# 用法: bash stage4_scheduler.sh <命令> <记录目录> [参数...]
#
# 状态权威源 = orchestration_plan.json（s2-analysis 产出的机器可读编排计划，
# 框架校验后作为唯一输入）。progress.md 是派生镜像，不做状态转移依据。
#
# 定位 codegen_s4.py 的方式与编排层运行时一致——优先用已安装的
# ascendc_devkit 包（codegen.py 就是这么 import 的）；包未安装时 fallback
# 到本仓源码相对路径（仅供仓内开发）。不假定 skill 一定在 DevKit 仓内，
# 这样 skill 取出后只要 ascendc_devkit 已安装即可独立运行。

# 1) 优先：已安装的 ascendc_devkit 包内的 codegen_s4.py
SCHED_PY="$(python3 - <<'PY' 2>/dev/null
try:
    from ascendc_devkit.orchestration.stages import codegen_s4
    print(codegen_s4.__file__)
except Exception:
    pass
PY
)"

# 2) Fallback：仓内源码相对路径（skill 位于 <root>/.claude/skills/...）
if [ -z "$SCHED_PY" ] || [ ! -f "$SCHED_PY" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    DEVKIT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
    CANDIDATE="$DEVKIT_ROOT/src/ascendc_devkit/orchestration/stages/codegen_s4.py"
    if [ -f "$CANDIDATE" ]; then
        SCHED_PY="$CANDIDATE"
    fi
fi

if [ -z "$SCHED_PY" ] || [ ! -f "$SCHED_PY" ]; then
    echo "错误: 编排层 scheduler (ascendc_devkit.orchestration.stages.codegen_s4) 未找到。" >&2
    echo "       请先安装 ascendc_devkit（pip install -e .），或在本仓内运行。" >&2
    exit 1
fi

exec python3 "$SCHED_PY" "$@"
