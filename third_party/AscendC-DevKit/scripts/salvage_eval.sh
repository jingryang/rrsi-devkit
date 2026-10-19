#!/bin/bash
# salvage_eval.sh — 对已构建但未过 stage 的 opp 直接跑 cann-bench kernel_eval（不经 LLM）。
# 复刻 cannbench_eval.py 的 env 与命令，只换 per-op 路径 + source-dir。
# 性质：一次性运维抢救工具（RID 默认值硬编码 20260710-140056 批次，见下方 case；可用
#       第 3 参数覆盖）——跳过 LLM，对已 deploy 的 opp 直接重评。Python cannbench_eval
#       stage 需经 dispatch 入口、不能跳 LLM，故无 Python 等价。非通用入口，按需改 RID 手动跑。
set -uo pipefail
source /usr/local/Ascend/ascend-toolkit/cann-9.1.0-beta.3/set_env.sh

OP="${1:?usage: salvage_eval.sh <op> [device_id]}"
DEV="${2:-1}"
RUN_DIR="/home/x00584171/code/AscendC-DevKit/output/20260710-140056-24b312"
# 按 run_id 解析；每个算子 run_id 不同，支持第二参数覆盖
RID="${3:-}"
if [[ -z "$RID" ]]; then
  case "$OP" in
    swi_glu) RID=20260710-140056-24b312 ;;
    rms_norm) RID=20260710-140056-ba16cd ;;
    foreach_norm) RID=20260710-140056-1c2fce ;;
    cross_entropy_loss) RID=20260710-140056-0ce45e ;;
    dynamic_quant) RID=20260710-140056-94616a ;;
    moe_re_routing) RID=20260710-140056-b1b8ec ;;
    *) echo "[FATAL] 未知算子 $OP，请显式传 run_id"; exit 2 ;;
  esac
fi
RUN_DIR="/home/x00584171/code/AscendC-DevKit/output/$RID"
PER_OPP="$RUN_DIR/artifacts/per-op/$OP/opp"
PER_PY="$RUN_DIR/artifacts/per-op/$OP/python"
WT="/home/x00584171/code/cann-bench-batch/20260710_220043/$OP"

OP_PASCAL="$(python3 -c "print(''.join(p.capitalize() for p in '$OP'.split('_')))")"
echo "═══ salvage eval: $OP → $OP_PASCAL  (run=$RID device=$DEV) ═══"
echo "  per_op_opp : $PER_OPP"
echo "  per_op_py  : $PER_PY"
echo "  worktree   : $WT"

[[ -d "$PER_OPP/vendors/custom_ops" ]] || { echo "[FATAL] opp 不存在: $PER_OPP"; exit 2; }
[[ -f "$PER_PY/cann_bench/_C.abi3.so" ]] || { echo "[FATAL] _C.abi3.so 不存在: $PER_PY"; exit 2; }

LD_PATH="$PER_OPP/vendors/custom_ops/op_api/lib"
CANN_HOME="${ASCEND_HOME_PATH:-/usr/local/Ascend/ascend-toolkit/cann-9.1.0-beta.3}"
CANN_LIBS="$CANN_HOME/aarch64-linux/lib64:$CANN_HOME/aarch64-linux/asc/lib64"

export TORCH_DEVICE_BACKEND_AUTOLOAD=0
export ASCEND_CUSTOM_OPP_PATH="$PER_OPP/vendors/custom_ops"
export ASCEND_OPP_PATH="${ASCEND_OPP_PATH:-$CANN_HOME/opp}"
export PYTHONPATH="$PER_PY:$WT/src:${PYTHONPATH:-}"
export LD_LIBRARY_PATH="$LD_PATH:$CANN_LIBS:${LD_LIBRARY_PATH:-}"
export ASCEND_DEVICE_ID="$DEV"

echo ""; echo "─── 1) load smoke (import cann_bench + resolve torch.ops) ───"
python3 - <<'PY'
import torch
try:
    import cann_bench
    from cann_bench import _C  # noqa
except Exception as e:
    print(f"[smoke FAIL] import cann_bench: {e!r}"); raise
ns = getattr(torch.ops, "cann_bench", None)
print("torch.ops.cann_bench attrs:", [a for a in dir(ns) if not a.startswith('_')])
import cann_bench as cb
for fn in ("swi_glu","sqrt","add"):
    if hasattr(cb, fn):
        print(f"  smoke OK: cann_bench.{fn} exists")
print("[smoke OK] opp loaded, _C resolved")
PY
SMOKE_RC=$?
if [[ $SMOKE_RC -ne 0 ]]; then echo "[ABORT] smoke 失败，opp 无法加载，跳过 eval"; exit $SMOKE_RC; fi

echo ""; echo "─── 2) cann-bench kernel_eval eval (--skip-install) ───"
cd "$WT"
timeout 1800 python3 -m kernel_eval.cli eval \
  --source-dir "$WT/examples/aclnn_launch_example/csrc/ops/$OP" \
  --operator "$OP_PASCAL" \
  --device-id "$DEV" \
  --skip-install
EVAL_RC=$?
echo ""; echo "═══ eval exit=$EVAL_RC ═══"
echo "─── latest report ───"
LATEST=$(ls -t "$WT"/reports/**/*_eval_*.json 2>/dev/null | head -1)
[[ -z "$LATEST" ]] && LATEST=$(find "$WT/reports" -name '*_eval_*.json' 2>/dev/null | xargs ls -t 2>/dev/null | head -1)
if [[ -n "$LATEST" ]]; then
  echo "report: $LATEST"
  python3 -c "import json,sys; d=json.load(open('$LATEST')); s=d.get('summary',{}); print('overall_score=', s.get('overall_score'), 'pass_rate=', s.get('pass_rate')); [print('  op',o.get('operator'),'score=',o.get('score'),'cases=',o.get('total_cases'),'passed=',o.get('passed_cases')) for o in d.get('operators',[])]"
else
  echo "[WARN] 未找到 report json under $WT/reports"
fi
