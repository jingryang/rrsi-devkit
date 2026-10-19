#!/bin/bash
# ============================================================================
# AscendC-DevKit 单算子 verifier
#
# 读取 batch_self_evolve 工作流产出 + cann-bench 评测报告，据实生成
# verification.md（FINAL_COMPILE/LOAD/ACCURACY_STATUS）。
#
# 验证逻辑（只校验最终是否 pass）：
#   1. 检查 output/ 运行产物存在性（工作流确已跑完）
#   2. 查找并解析 cann-bench 评测报告 JSON（最终结果证据）
#   3. 基于 compilation_score / compile_runtime_fail_cases / passed_cases 判定三态
#   说明：输入件预置于 cann-bench task 目录，不校验 devkit/demands/ 位置；
#         评测报告在阶段检查前即定位并复制，任何阶段失败都不丢失产物。
#
# 退出码：0 全阶段通过，1 任一阶段失败
# ============================================================================
set -uo pipefail

WORKDIR="${WORKDIR:-/app/src}"
DEFAULT_OP_NAME="adaptive_avg_pool_3d"
OP_NAME="${1:-$DEFAULT_OP_NAME}"

DEVKIT_ROOT="${DEVKIT_ROOT:-/app/src/AscendC-DevKit}"
CANN_BENCH_ROOT="${CANN_BENCH_ROOT:-/app/src/cann-bench}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEMANDS_DIR="$DEVKIT_ROOT/demands/$OP_NAME"
OUTPUT_DIR="$DEVKIT_ROOT/output"

ARTIFACT_ROOT="${ARTIFACT_ROOT:-$DEVKIT_ROOT/output}"
VERIFIER_DIR="${VERIFIER_DIR:-/logs/verifier}"
OUT="$ARTIFACT_ROOT/$OP_NAME"

ENABLE_NPU_REVERIFY="${ENABLE_NPU_REVERIFY:-1}"
BUILD_TIMEOUT_SEC="${BUILD_TIMEOUT_SEC:-1800}"
RUN_TIMEOUT_SEC="${RUN_TIMEOUT_SEC:-1800}"
ASCEND_RT_VISIBLE_DEVICES="${ASCEND_RT_VISIBLE_DEVICES:-0}"

# 三态：compile / load / accuracy，据实累积
FINAL_COMPILE="not_run"
FINAL_LOAD="not_run"
FINAL_ACCURACY="not_run"
FINAL_REASON=""

# 镜像默认 python3 无 torch；动态定位带 torch 的 python 并前置（不硬编码版本号）
TORCH_PY="$(ls /usr/local/python*/bin/python3 2>/dev/null | head -1)"
if [ -n "$TORCH_PY" ] && "$TORCH_PY" -c "import torch" >/dev/null 2>&1; then
    export PATH="$(dirname "$TORCH_PY"):$PATH"
fi

mkdir -p "$VERIFIER_DIR" "$OUT"

# ── 需求来源解析：devkit demands/ 或 cann-bench task 目录，二者有一即可 ──
# 本工作流输入件预置于 cann-bench task 目录（$CANN_BENCH_ROOT/tasks/<level>/<op>/），
# agent 不创建 devkit/demands/；两种来源都视为合法输入件位置。
DEMANDS_SRC=""
if [ -d "$DEMANDS_DIR" ]; then
    DEMANDS_SRC="$DEMANDS_DIR"
elif [ -d "$CANN_BENCH_ROOT/tasks" ]; then
    for _cand in "$CANN_BENCH_ROOT"/tasks/*/"$OP_NAME"; do
        if [ -d "$_cand" ]; then
            DEMANDS_SRC="$_cand"
            break
        fi
    done
fi

# ── 工具函数 ──
write_json() {
    local reward="$1"; local status="$2"; local reason="$3"; local stage="$4"
    local extra_json="${5:-{}}"
    python3 - "$VERIFIER_DIR/reward.json" "$VERIFIER_DIR/details.json" \
        "$reward" "$status" "$reason" "$stage" "$OP_NAME" \
        "$ARTIFACT_ROOT" "$DEVKIT_ROOT" "$FINAL_COMPILE" "$FINAL_LOAD" "$FINAL_ACCURACY" \
        "$extra_json" <<'PY'
import json, sys
from pathlib import Path
reward_path, details_path = sys.argv[1], sys.argv[2]
reward = int(sys.argv[3])
status, reason, stage, op_name = sys.argv[4], sys.argv[5], sys.argv[6], sys.argv[7]
artifact_root, devkit_root = sys.argv[8], sys.argv[9]
compile_s, load_s, acc_s = sys.argv[10], sys.argv[11], sys.argv[12]
try:
    extra = json.loads(sys.argv[13])
except Exception:
    extra = {}
details = {
    "reward": reward, "status": status, "reason": reason, "stage": stage,
    "op_name": op_name,
    "artifact_root": artifact_root, "devkit_root": devkit_root,
    "final_compile_status": compile_s, "final_load_status": load_s,
    "final_accuracy_status": acc_s,
}
details.update(extra)
Path(reward_path).write_text(json.dumps({"reward": reward}, ensure_ascii=False) + "\n", encoding="utf-8")
Path(details_path).write_text(json.dumps(details, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
}

pass_stage() { local stage="$1"; echo "PASS[$stage]"; }

write_verification_md() {
    mkdir -p "$OUT"
    cat > "$OUT/verification.md" <<EOF
# Verification: ${OP_NAME}

FINAL_COMPILE_STATUS: ${FINAL_COMPILE}
FINAL_LOAD_STATUS: ${FINAL_LOAD}
FINAL_ACCURACY_STATUS: ${FINAL_ACCURACY}
FINAL_REASON: ${FINAL_REASON}
EOF
    cp -f "$OUT/verification.md" "$VERIFIER_DIR/verification.md" 2>/dev/null || true
}

write_trace_md() {
    mkdir -p "$OUT"
    local eval_report="${EVAL_REPORT_JSON:-}"
    local run_id="${RUN_ID:-}"
    {
        echo "# Trace: ${OP_NAME}"
        echo
        echo "- devkit_root: \`${DEVKIT_ROOT}\`"
        echo "- cann_bench_root: \`${CANN_BENCH_ROOT}\`"
        echo "- demands_dir: \`${DEMANDS_DIR}\`"
        echo "- output_dir: \`${OUTPUT_DIR}\`"
        echo "- artifact_dir: \`${OUT}\`"
        echo "- run_id: ${run_id}"
        echo "- eval_report: \`${eval_report}\`"
        echo
        echo "## 最终状态"
        echo "- compile: ${FINAL_COMPILE}"
        echo "- load: ${FINAL_LOAD}"
        echo "- accuracy: ${FINAL_ACCURACY}"
        echo "- reason: ${FINAL_REASON}"
    } > "$OUT/trace.md"
}

# 定位最优 cann-bench 评测报告（前置收集用，不依赖阶段检查是否通过）：
# 候选来源：override 参数 / state_snapshot.eval_result.report_json /
# cann-bench/reports/*_eval_*.json / output/<run>/**/*_eval_*.json，
# 按 (passed_cases, overall_score, mtime) 选最优。
find_best_eval_report() {
    local output_dir="$1" run_id="$2" cann_bench_root="$3" override="${4:-}" op_name="$5"
    python3 - "$output_dir" "$run_id" "$cann_bench_root" "$override" "$op_name" <<'PY'
import json, os, sys, glob
output_dir, run_id, cann_bench_root, override, op_name = sys.argv[1:6]
candidates = []; seen = set()
def add(p):
    if p and os.path.isfile(p) and p not in seen:
        seen.add(p); candidates.append(p)
add(override)
ss = os.path.join(output_dir, run_id, "state_snapshot.json")
if os.path.isfile(ss):
    try:
        d = json.load(open(ss)); add((d.get("eval_result") or {}).get("report_json") or "")
    except Exception:
        pass
rep_dir = os.path.join(cann_bench_root, "reports")
if os.path.isdir(rep_dir):
    for p in glob.glob(os.path.join(rep_dir, "*_eval_*.json")):
        add(p)
run_dir = os.path.join(output_dir, run_id)
if os.path.isdir(run_dir):
    for root, _, files in os.walk(run_dir):
        for f in files:
            if "_eval_" in f and f.endswith(".json"):
                add(os.path.join(root, f))
if not candidates:
    sys.exit(0)
def score(p):
    try:
        d = json.load(open(p))
        ops = d.get("operators") or []
        if ops:
            report_op_name = (ops[0].get("operator") or "").lower().replace(" ", "_")
            if op_name and report_op_name and report_op_name != op_name.lower().replace(" ", "_"):
                return (-1, 0.0, os.path.getmtime(p))
        passed = int(d.get("passed_cases", 0) or 0)
        if passed == 0 and ops:
            passed = int(ops[0].get("passed_cases", 0) or 0)
        overall = float((d.get("summary") or {}).get("overall_score", 0.0) or 0.0)
        return (passed, overall, os.path.getmtime(p))
    except Exception:
        return (-1, 0.0, os.path.getmtime(p))
print(max(candidates, key=score))
PY
}

export_artifacts() {
    mkdir -p "$OUT"
    # 复制需求文档（devkit demands/ 或 cann-bench task 目录）
    local dsrc="${DEMANDS_SRC:-$DEMANDS_DIR}"
    if [ -n "$dsrc" ] && [ -d "$dsrc" ]; then
        mkdir -p "$OUT/demands/$(basename "$dsrc")"
        cp -rf "$dsrc"/* "$OUT/demands/$(basename "$dsrc")/" 2>/dev/null || true
    fi
    # 复制部署产物（per-op 目录下的 python/ 和 opp/）
    if [ -n "${RUN_ID:-}" ] && [ -d "$OUTPUT_DIR/$RUN_ID/artifacts/per-op/$OP_NAME" ]; then
        local per_op="$OUTPUT_DIR/$RUN_ID/artifacts/per-op/$OP_NAME"
        local dst="$OUT/per-op/$OP_NAME"
        mkdir -p "$dst"
        for sub in python opp; do
            [ -d "$per_op/$sub" ] && cp -rf "$per_op/$sub" "$dst/" 2>/dev/null || true
        done
    fi
    # 复制评测报告
    if [ -n "${EVAL_REPORT_JSON:-}" ] && [ -f "$EVAL_REPORT_JSON" ]; then
        mkdir -p "$OUT/reports"
        cp -f "$EVAL_REPORT_JSON" "$OUT/reports/" 2>/dev/null || true
        local md_report="${EVAL_REPORT_JSON%.json}.md"
        [ -f "$md_report" ] && cp -f "$md_report" "$OUT/reports/" 2>/dev/null || true
    fi
    # 清除可能混入的中间产物
    find "$OUT" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
    find "$OUT" -type f \( -name "*.pyc" -o -name "*.o" \) -delete 2>/dev/null || true
    # 所有 cp 完成后再打包快照（$OUT 位于 output 下，快照包含上述全部产物）
    if [ -d "$DEVKIT_ROOT/output" ]; then
        tar czf /logs/verifier/app_artifacts.tar.gz -C "$DEVKIT_ROOT/output" . 2>/dev/null || true
    fi
}

# ── 前置定位评测报告：在阶段检查之前先定位，供后续阶段与 export_artifacts 使用；
#    产物收集不在此处执行，只在 fail()/收尾路径调用一次 export_artifacts ──
# batch 流程产物为 output/<batch_id>/<execution_id>/（两层），旧 e2e 为 output/<run_id>/（一层）；
# 统一按「含 run.log 的最新目录」定位 run 根，两种布局都兼容。
find_latest_run() {
    find "$OUTPUT_DIR" -name run.log -printf '%T@ %h\n' 2>/dev/null \
        | sort -rn | head -1 | awk '{print $2}' \
        | sed "s|^$OUTPUT_DIR/||" || true
}
RUN_ID="$(find_latest_run)"
EVAL_REPORT_JSON="$(find_best_eval_report "$OUTPUT_DIR" "$RUN_ID" "$CANN_BENCH_ROOT" "${EVAL_REPORT_JSON_OVERRIDE:-}" "$OP_NAME")"
if [ -n "$EVAL_REPORT_JSON" ] && [ -f "$EVAL_REPORT_JSON" ]; then
    echo "early eval_report: $EVAL_REPORT_JSON"
fi

# ── 前置复制最终执行源码：batch 流程 codegen 写入 worktree
#    （$DEVKIT_ROOT/../cann-bench-batch/<ts>/<op>/，含 precision_debug 的原位修复），
#    cann-bench 基仓内没有最终代码；按 mtime 取最新 worktree，找不到则回退基仓路径。
#    在脚本开头即备份，任何后续阶段失败（含异常退出）都不会丢失。
#    注意 output/artifacts/codegen/ 是生成期快照，不含 precision_debug 的原位修复。
SRC_DIR="$(ls -dt "$DEVKIT_ROOT"/../cann-bench-batch/*/"$OP_NAME"/examples/aclnn_launch_example/csrc/ops/"$OP_NAME" 2>/dev/null | head -1)"
[ -n "$SRC_DIR" ] || SRC_DIR="$CANN_BENCH_ROOT/examples/aclnn_launch_example/csrc/ops/$OP_NAME"
if [ -d "$SRC_DIR" ]; then
    mkdir -p "$OUT/src"
    cp -rf "$SRC_DIR/." "$OUT/src/" 2>/dev/null || true
    echo "early src saved: $SRC_DIR"
fi

fail() {
    local stage="$1"; local reason="$2"; local log_file="${3:-}"
    [ -n "$reason" ] && FINAL_REASON="$reason"
    echo "FAIL[$stage]: $FINAL_REASON"
    echo "0" > "$VERIFIER_DIR/reward.txt"
    printf '%s\n' "$FINAL_REASON" > "$VERIFIER_DIR/reason.txt"
    local extra="{}"
    if [ -n "$log_file" ]; then
        extra="$(printf '%s' "$log_file" | python3 -c 'import json,sys; print(json.dumps({"log_file": sys.stdin.read()}))' 2>/dev/null || echo '{}')"
    fi
    write_verification_md
    write_trace_md
    export_artifacts
    write_json 0 "fail" "$FINAL_REASON" "$stage" "$extra"
    exit 1
}

echo "=== AscendC-DevKit verifier: $OP_NAME ==="
echo "devkit_root=$DEVKIT_ROOT"
echo "cann_bench_root=$CANN_BENCH_ROOT"
echo "demands_dir=$DEMANDS_DIR"

# ── s0 调用参数 ──
STAGE="s0_invocation"
[ -n "$OP_NAME" ] || fail "$STAGE" "bad_invocation"
PLACEHOLDER_OP="__""OP_NAME__"
if [ "$DEFAULT_OP_NAME" = "$PLACEHOLDER_OP" ] && [ -z "${1:-}" ]; then
    fail "$STAGE" "bad_invocation"
fi
pass_stage "$STAGE"

# ── s1 环境与输入件 ──
STAGE="s1_environment"
[ -d "$DEVKIT_ROOT" ] || fail "$STAGE" "devkit_root_not_found"
[ -d "$CANN_BENCH_ROOT" ] || fail "$STAGE" "cann_bench_root_not_found"
[ -f "$DEVKIT_ROOT/scripts/batch_self_evolve.sh" ] || fail "$STAGE" "batch_self_evolve_script_missing"
pass_stage "$STAGE"

# ── s2 需求来源（信息性，不参与最终校验）──
# 输入件预置于 cann-bench task 目录（或 devkit demands/），位置不决定最终结果；
# 最终 pass 与否完全由 s4 评测报告字段决定。
STAGE="s2_demand_presence"
if [ -n "$DEMANDS_SRC" ]; then
    echo "demands_src: $DEMANDS_SRC"
else
    echo "demands_src: <none>（未找到输入件目录，不影响最终校验）"
fi
pass_stage "$STAGE"

# ── s3 运行产物存在性（工作流确已跑完的证据）──
STAGE="s3_output_presence"
# 查找最新的 run 目录（排除 $OUT 产物目录名 $OP_NAME）
RUN_ID="$(find_latest_run)"
[ -n "$RUN_ID" ] || fail "$STAGE" "no_output_run_found"
[ -d "$OUTPUT_DIR/$RUN_ID" ] || fail "$STAGE" "output_run_dir_not_found"
# 检查运行日志存在
[ -f "$OUTPUT_DIR/$RUN_ID/run.log" ] || fail "$STAGE" "run_log_missing"
# 检查 state_snapshot.json 存在（工作流完成标志）
[ -f "$OUTPUT_DIR/$RUN_ID/state_snapshot.json" ] || fail "$STAGE" "state_snapshot_missing"
pass_stage "$STAGE"

# ── s4 查找并选出最优 cann-bench 评测报告 ──
# 说明：工作流 cann-bench_eval 可能失败（如 cann_bench_warmup ImportError），
# 随后 agent 手动重跑 kernel_eval 会产出更新的成功报告，但 state_snapshot 的
# eval_result.report_json 仍可能指向旧失败报告。因此这里收集全部候选报告，
# 按 (passed_cases, overall_score, mtime) 选最优，避免误用旧的失败报告。
STAGE="s4_eval_report"
if [ -z "${EVAL_REPORT_JSON:-}" ]; then
    EVAL_REPORT_JSON="$(find_best_eval_report "$OUTPUT_DIR" "$RUN_ID" "$CANN_BENCH_ROOT" "${EVAL_REPORT_JSON_OVERRIDE:-}" "$OP_NAME")"
fi
if [ -z "$EVAL_REPORT_JSON" ] || [ ! -f "$EVAL_REPORT_JSON" ]; then
    fail "$STAGE" "eval_report_not_found"
fi
echo "eval_report: $EVAL_REPORT_JSON"
pass_stage "$STAGE"

# ── NPU reverify 开关 ──
if [ "$ENABLE_NPU_REVERIFY" != "1" ]; then
    echo "NPU reverify skipped by ENABLE_NPU_REVERIFY=$ENABLE_NPU_REVERIFY"
    FINAL_REASON="npu_reverify_skipped"
    echo "1" > "$VERIFIER_DIR/reward.txt"
    write_verification_md; write_trace_md; export_artifacts
    write_json 1 "pass" "npu_reverify_skipped" "s4_eval_report" '{"npu_reverify":"skipped"}'
    exit 0
fi

# ── s5 解析评测报告 ──
STAGE="s5_parse_eval"
EVAL_DATA="$(python3 - "$EVAL_REPORT_JSON" <<'PY'
import json, sys
from pathlib import Path

report_path = sys.argv[1]
with open(report_path) as f:
    d = json.load(f)

summary = d.get("summary", {})
operators = d.get("operators", [])

result = {
    "overall_score": float(summary.get("overall_score", 0.0)),
    "pass_rate": float(summary.get("pass_rate", 0.0)),
    "total_cases": int(d.get("total_cases", 0)),
    "passed_cases": int(d.get("passed_cases", 0)),
    "failed_cases": int(d.get("failed_cases", 0)),
}

if operators:
    first = operators[0]
    result["compilation_score"] = float(first.get("compilation_score", 0.0))
    result["function_score"] = float(first.get("function_score", 0.0))
    result["performance_score"] = float(first.get("performance_score", 0.0))
    result["operator_score"] = float(first.get("score", 0.0))
    result["compile_runtime_fail_cases"] = int(first.get("compile_runtime_fail_cases", 0))
    result["op_total_cases"] = int(first.get("total_cases", 0))
    result["op_passed_cases"] = int(first.get("passed_cases", 0))
    result["score_error_code"] = first.get("score_error_code", "")

print(json.dumps(result))
PY
)"

if [ -z "$EVAL_DATA" ]; then
    fail "$STAGE" "eval_report_parse_failed"
fi

# 提取关键字段
OVERALL_SCORE="$(echo "$EVAL_DATA" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("overall_score",0))')"
PASS_RATE="$(echo "$EVAL_DATA" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("pass_rate",0))')"
COMPILATION_SCORE="$(echo "$EVAL_DATA" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("compilation_score",0))')"
FUNCTION_SCORE="$(echo "$EVAL_DATA" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("function_score",0))')"
PERFORMANCE_SCORE="$(echo "$EVAL_DATA" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("performance_score",0))')"
COMPILE_RUNTIME_FAIL="$(echo "$EVAL_DATA" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("compile_runtime_fail_cases",0))')"
OP_TOTAL_CASES="$(echo "$EVAL_DATA" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("op_total_cases",0))')"
OP_PASSED_CASES="$(echo "$EVAL_DATA" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("op_passed_cases",0))')"
SCORE_ERROR_CODE="$(echo "$EVAL_DATA" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("score_error_code",""))')"

echo "overall_score=$OVERALL_SCORE"
echo "pass_rate=$PASS_RATE"
echo "compilation_score=$COMPILATION_SCORE"
echo "function_score=$FUNCTION_SCORE"
echo "performance_score=$PERFORMANCE_SCORE"
echo "compile_runtime_fail=$COMPILE_RUNTIME_FAIL / $OP_TOTAL_CASES"
echo "passed_cases=$OP_PASSED_CASES / $OP_TOTAL_CASES"
echo "score_error_code=$SCORE_ERROR_CODE"

# KP-2/KP-3 诊断提示：评测无算子或全 case 加载失败时给出修复指引
if [ "$OP_TOTAL_CASES" = "0" ]; then
    echo "[HINT] kernel_eval 未匹配到算子用例（total_cases=0）。常见原因："
    echo "[HINT]   - KP-2: cann_bench/__init__.py 缺算子 wrapper（补 def mhc_sinkhorn(...) 后重跑 kernel_eval）"
    echo "[HINT]   - KP-4: cann-bench/tasks/level<N>/ 目录 level 与 proto.yaml difficulty 不一致"
elif [ "$OP_PASSED_CASES" = "0" ] && [ "$OP_TOTAL_CASES" -gt 0 ] 2>/dev/null; then
    echo "[HINT] 评测有算子但全 case 失败。如日志出现 ImportError: cann_bench_warmup → KP-3（装 cann_bench_utils wheel）"
fi
pass_stage "$STAGE"

# ── s6 判定三态 ──
STAGE="s6_verdict"

# FINAL_COMPILE: compilation_score > 0 表示至少有 case 编译+运行通过
if python3 -c "exit(0 if float('$COMPILATION_SCORE') > 0 else 1)" 2>/dev/null; then
    FINAL_COMPILE="pass"
else
    FINAL_COMPILE="fail"
fi

# FINAL_LOAD: compile_runtime_fail_cases < total_cases 表示不是所有 case 都加载失败
if python3 -c "exit(0 if int('$COMPILE_RUNTIME_FAIL') < int('$OP_TOTAL_CASES') else 1)" 2>/dev/null; then
    FINAL_LOAD="pass"
else
    FINAL_LOAD="fail"
fi

# FINAL_ACCURACY: passed_cases > 0 表示至少有 case 精度通过
if python3 -c "exit(0 if int('$OP_PASSED_CASES') > 0 else 1)" 2>/dev/null; then
    FINAL_ACCURACY="pass"
else
    FINAL_ACCURACY="fail"
fi

echo "verdict: compile=$FINAL_COMPILE load=$FINAL_LOAD accuracy=$FINAL_ACCURACY"

# ── 收尾 ──
if [ "$FINAL_COMPILE" = "pass" ] && [ "$FINAL_LOAD" = "pass" ] && [ "$FINAL_ACCURACY" = "pass" ]; then
    FINAL_REASON="verified: compile+load+accuracy passed (score=${OVERALL_SCORE})"
    echo "PASS: compile+load+accuracy verified, overall_score=${OVERALL_SCORE}"
    echo "1" > "$VERIFIER_DIR/reward.txt"
    write_verification_md
    write_trace_md
    export_artifacts
    write_json 1 "pass" "verified" "s6_verdict" "{\"overall_score\":${OVERALL_SCORE},\"compilation_score\":${COMPILATION_SCORE},\"function_score\":${FUNCTION_SCORE},\"performance_score\":${PERFORMANCE_SCORE},\"pass_rate\":${PASS_RATE},\"passed_cases\":${OP_PASSED_CASES},\"total_cases\":${OP_TOTAL_CASES}}"
else
    FINAL_REASON="compile=${FINAL_COMPILE} load=${FINAL_LOAD} accuracy=${FINAL_ACCURACY} (score=${OVERALL_SCORE})"
    echo "FAIL: $FINAL_REASON"
    echo "0" > "$VERIFIER_DIR/reward.txt"
    printf '%s\n' "$FINAL_REASON" > "$VERIFIER_DIR/reason.txt"
    write_verification_md
    write_trace_md
    export_artifacts
    write_json 0 "fail" "$FINAL_REASON" "s6_verdict" "{\"overall_score\":${OVERALL_SCORE},\"compilation_score\":${COMPILATION_SCORE},\"function_score\":${FUNCTION_SCORE},\"performance_score\":${PERFORMANCE_SCORE},\"pass_rate\":${PASS_RATE},\"passed_cases\":${OP_PASSED_CASES},\"total_cases\":${OP_TOTAL_CASES}}"
    exit 1
fi