#!/bin/bash
# salvage_rebuild_eval.sh — 修 P10 schema 后 rebuild + 重装 + 重评（不经 LLM）。
# 用法: salvage_rebuild_eval.sh <op> <device_id>
# 性质：一次性运维抢救工具（RID_MAP 硬编码 20260710-140056 批次）——跳过 LLM，对已构建
#       opp rebuild + 重装 + 重评。Python 链路需经 dispatch 不能跳 LLM，无等价。非通用入口。
set -uo pipefail
source /usr/local/Ascend/ascend-toolkit/cann-9.1.0-beta.3/set_env.sh

OP="${1:?usage: salvage_rebuild_eval.sh <op> <device_id>}"
DEV="${2:?device id}"
declare -A RID_MAP=(
  [swi_glu]=20260710-140056-24b312 [rms_norm]=20260710-140056-ba16cd
  [foreach_norm]=20260710-140056-1c2fce [cross_entropy_loss]=20260710-140056-0ce45e
  [dynamic_quant]=20260710-140056-94616a [moe_re_routing]=20260710-140056-b1b8ec
)
RID="${RID_MAP[$OP]}"
RUN_DIR="/home/x00584171/code/AscendC-DevKit/output/$RID"
PER_OPP="$RUN_DIR/artifacts/per-op/$OP/opp"
PER_PY="$RUN_DIR/artifacts/per-op/$OP/python"
WT="/home/x00584171/code/cann-bench-batch/20260710_220043/$OP"
BUILD_DIR="$WT/examples/aclnn_launch_example"

echo "═══ rebuild+eval: $OP (run=$RID dev=$DEV) ═══"
echo "─── 1) build (bash build.sh --soc=ascend910b) ───"
cd "$BUILD_DIR"
rm -rf dist build 2>/dev/null
bash build.sh --soc=ascend910b
BUILD_RC=$?
if [[ $BUILD_RC -ne 0 ]]; then echo "[FAIL] build rc=$BUILD_RC"; exit $BUILD_RC; fi
echo "dist 产物:"; ls -la dist/ 2>/dev/null

RUN_PKG=$(ls dist/*.run 2>/dev/null | head -1)
WHL_PKG=$(ls dist/*.whl 2>/dev/null | head -1)
[[ -n "$RUN_PKG" ]] || { echo "[FAIL] 无 .run 产物"; exit 2; }
[[ -n "$WHL_PKG" ]] || { echo "[FAIL] 无 .whl 产物"; exit 2; }

echo ""; echo "─── 2) install opp → $PER_OPP ───"
rm -rf "$PER_OPP"/* 2>/dev/null
bash "$RUN_PKG" --quiet --install-path="$PER_OPP"
echo ""; echo "─── 3) install python → $PER_PY ───"
rm -rf "$PER_PY"/* 2>/dev/null
pip install --target "$PER_PY" --force-reinstall --no-deps "$WHL_PKG" 2>&1 | tail -3

echo ""; echo "─── 4) re-eval ───"
cd /home/x00584171/code/AscendC-DevKit
exec bash scripts/salvage_eval.sh "$OP" "$DEV" "$RID"
