#!/bin/bash
# test_dispatch_behavior.sh — stage4_scheduler.sh dispatch 行为 UT
#
# 守护的契约（2026-08-06 起）：COMPLETED 时 dispatch 只信 agent 返回的完成信号，
# 不再做磁盘交付物校验——plan deliverables 命名约定可能与仓库实际产物不一致，
# 磁盘字符串匹配会误判"缺失"造成无谓重试（run add_rms_norm_dynamic_quant：
# 3 个 session 全走 4.E）。s2/s4 完成判定均只信 agent 返回，全链路不做交付物判定。
#   状态权威源 = orchestration_plan.json（s2 产出、s4 消费），progress.md 是派生镜像。
#
# 用法: bash test_dispatch_behavior.sh
set -uo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$TEST_DIR/.." && pwd)"
SCHED="$SKILL_DIR/scripts/stage4_scheduler.sh"
DEV_RECORD="$SKILL_DIR/scripts/dev_record.sh"

PASS=0; FAIL=0
pass(){ echo "  ✅ $1"; PASS=$((PASS+1)); }
fail(){ echo "  ❌ $1"; FAIL=$((FAIL+1)); }

# 从 stdin JSON 取字段（python3 一定可用 —— dispatch 内部也用）
jget(){ python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('$1','<missing>'))"; }
jlen(){ python3 -c "import json,sys; d=json.load(sys.stdin); v=d.get('$1',[]); print(len(v) if isinstance(v,list) else 0)"; }

# 取编排计划中某 sub_stage 的 status
plan_status(){
    python3 -c "
import json,sys
target='$1'
d=json.load(open('$RECORD_DIR/orchestration_plan.json'))
for s in d.get('sub_stages',[]):
    if s.get('id')==target:
        print(s.get('status','ABSENT')); sys.exit(0)
print('ABSENT')
"
}

# ── 公共 fixture 构造 ──────────────────────────────────────────────
# 编排计划：4.0 ✅(已 done) / 4.A pending / 4.B1 pending / ...
# resolve_next('continue') 第一个 pending = 4.A（= 刚完成的 sub-stage）
write_plan(){
    cat > "$RECORD_DIR/orchestration_plan.json" <<'EOF'
{
  "op_name": "gather",
  "programming_model": "A5 Regbase",
  "sub_stages": [
    {"id": "4.0", "desc": "编码前置", "checkpoint_group": "INDEPENDENT", "execution_group": "host_tiling", "kind": "check", "deliverables": [], "status": "done"},
    {"id": "4.A", "desc": "TilingData", "checkpoint_group": "HOST", "execution_group": "host_tiling", "kind": "code", "deliverables": ["op_kernel/gather_tiling_data.h"], "status": "pending"},
    {"id": "4.B1", "desc": "OpDef", "checkpoint_group": "HOST", "execution_group": "host_tiling", "kind": "code", "deliverables": ["op_host/gather_def.cpp", "op_host/gather_infer_shape.cpp"], "status": "pending"},
    {"id": "4.C.1", "desc": "类框架", "checkpoint_group": "KERNEL", "execution_group": "kernel_base", "kind": "code", "deliverables": ["op_kernel/gather.h"], "status": "pending"}
  ]
}
EOF
}

setup_env(){
    TMP=$(mktemp -d)
    RECORD_DIR="$TMP/record"
    CODE_PATH="$TMP/code_path"
    mkdir -p "$RECORD_DIR" "$CODE_PATH/op_host" "$CODE_PATH/op_kernel" "$CODE_PATH/op_api"
    write_plan
    : > "$RECORD_DIR/history.log"   # set-progress 可能 append
}

# 带 code_path 的 meta.json
meta_with_codepath(){
    python3 -c "import json; print(json.dumps({'code_path':'$CODE_PATH','op_name':'gather','kernel_steps':['C.0','C.1','C.2','C.3','C.4']}))" > "$RECORD_DIR/meta.json"
}
# 无 code_path 的 meta.json（兜底场景）
meta_no_codepath(){
    python3 -c "import json; print(json.dumps({'op_name':'gather','kernel_steps':['C.0']}))" > "$RECORD_DIR/meta.json"
}

teardown(){ rm -rf "$TMP"; }

dispatch(){ bash "$SCHED" dispatch "$RECORD_DIR" COMPLETED; }

echo "============================================"
echo " stage4_scheduler.sh dispatch 行为 UT (JSON 编排计划)"
echo "============================================"

# ──────────────────────────────────────────────────────────────────
echo ""
echo "── Test 1: 交付物齐全 → call_s4 推进 + status=done ──"
setup_env
meta_with_codepath
# 4.A 的交付物落盘（resolve_next('continue') 第一个 pending = 4.A）
: > "$CODE_PATH/op_kernel/gather_tiling_data.h"
OUT=$(dispatch)
ACT=$(echo "$OUT" | jget action)
NEXT=$(echo "$OUT" | jget next_sub_stage)
ST=$(plan_status 4.A)
[ "$ACT" = "call_s4" ] && pass "action=call_s4 (got: $ACT)" || fail "action 应为 call_s4 (got: $ACT)"
[ "$NEXT" = "4.B1" ] && pass "next_sub_stage=4.B1" || fail "next 应为 4.B1 (got: $NEXT)"
[ "$ST" = "done" ] && pass "plan 4.A status=done" || fail "plan 4.A 应 done (got: $ST)"
teardown

# ──────────────────────────────────────────────────────────────────
echo ""
echo "── Test 2: 交付物未落盘 → 仍按 COMPLETED 标 done + 推进（核心）──"
setup_env
meta_with_codepath
# code_path 空 —— 4.A 交付物没落盘。COMPLETED 只信 agent 返回，不做磁盘校验，
# 直接标 done 推进下一 pending（避免命名约定不一致时的误判重试）。
OUT=$(dispatch)
ACT=$(echo "$OUT" | jget action)
NEXT=$(echo "$OUT" | jget next_sub_stage)
ST=$(plan_status 4.A)
[ "$ACT" = "call_s4" ] && pass "action=call_s4（COMPLETED 直接推进，got: $ACT）" || fail "action 应为 call_s4 (got: $ACT)"
[ "$NEXT" = "4.B1" ] && pass "next_sub_stage=4.B1（推进下一 pending）" || fail "next 应为 4.B1 (got: $NEXT)"
[ "$ST" = "done" ] && pass "plan 4.A status=done（agent COMPLETED 即放行）" || fail "plan 4.A 应 done (got: $ST)"
teardown

# ──────────────────────────────────────────────────────────────────
echo ""
echo "── Test 3: 无 code_path → 降级放行不阻塞（兜底）──"
setup_env
meta_no_codepath
: > "$CODE_PATH/op_kernel/gather_tiling_data.h"
OUT=$(dispatch)
ACT=$(echo "$OUT" | jget action)
ST=$(plan_status 4.A)
[ "$ACT" = "call_s4" ] && pass "无 code_path 降级 call_s4 推进（不阻塞）" || fail "应降级 call_s4 (got: $ACT)"
[ "$ST" = "done" ] && pass "降级路径标 done" || fail "降级应标 done (got: $ST)"
teardown

# ──────────────────────────────────────────────────────────────────
echo ""
echo "── Test 4: VF 步骤（kind=vf, deliverables=[]）→ call_vf_test ──"
setup_env
meta_with_codepath
# 重写计划：4.C.2 为当前 pending，之后是 4.C.3.VT.1（kind=vf）
cat > "$RECORD_DIR/orchestration_plan.json" <<'EOF'
{
  "op_name": "gather",
  "programming_model": "A5 Regbase",
  "sub_stages": [
    {"id": "4.0", "desc": "编码前置", "checkpoint_group": "INDEPENDENT", "execution_group": "host_tiling", "kind": "check", "deliverables": [], "status": "done"},
    {"id": "4.C.2", "desc": "CopyIn", "checkpoint_group": "KERNEL", "execution_group": "kernel_base", "kind": "code", "deliverables": ["op_kernel/gather.h"], "status": "pending"},
    {"id": "4.C.3.VT.1", "desc": "VF预验证", "checkpoint_group": "KERNEL", "execution_group": "vf_1", "kind": "vf", "deliverables": [], "status": "pending"},
    {"id": "4.C.3", "desc": "Compute", "checkpoint_group": "KERNEL", "execution_group": "kernel_finalize", "kind": "code", "deliverables": ["op_kernel/gather.h"], "status": "pending"}
  ]
}
EOF
# 4.C.2 交付物落盘 → 推进到 VT 步骤应 call_vf_test
: > "$CODE_PATH/op_kernel/gather.h"
OUT=$(dispatch)
ACT=$(echo "$OUT" | jget action)
NEXT=$(echo "$OUT" | jget next_sub_stage)
ST=$(plan_status 4.C.2)
[ "$ACT" = "call_vf_test" ] && pass "推进到 VF 步骤 → call_vf_test（got: $ACT）" || fail "应 call_vf_test (got: $ACT)"
[ "$NEXT" = "4.C.3.VT.1" ] && pass "next_sub_stage=4.C.3.VT.1" || fail "next 应为 4.C.3.VT.1 (got: $NEXT)"
[ "$ST" = "done" ] && pass "plan 4.C.2 status=done" || fail "plan 4.C.2 应 done (got: $ST)"
teardown

# ──────────────────────────────────────────────────────────────────
echo ""
echo "── Test 5: VF 步骤 dispatch COMPLETED → 不查交付物直接推进 ──"
setup_env
meta_with_codepath
cat > "$RECORD_DIR/orchestration_plan.json" <<'EOF'
{
  "op_name": "gather",
  "programming_model": "A5 Regbase",
  "sub_stages": [
    {"id": "4.0", "desc": "编码前置", "checkpoint_group": "INDEPENDENT", "execution_group": "host_tiling", "kind": "check", "deliverables": [], "status": "done"},
    {"id": "4.C.3.VT.1", "desc": "VF预验证", "checkpoint_group": "KERNEL", "execution_group": "vf_1", "kind": "vf", "deliverables": [], "status": "pending"},
    {"id": "4.C.3", "desc": "Compute", "checkpoint_group": "KERNEL", "execution_group": "kernel_finalize", "kind": "code", "deliverables": ["op_kernel/gather.h"], "status": "pending"}
  ]
}
EOF
# 无任何磁盘文件，但 VF 步骤 deliverables=[] → 直接 done + 推进
OUT=$(dispatch)
ACT=$(echo "$OUT" | jget action)
NEXT=$(echo "$OUT" | jget next_sub_stage)
ML=$(echo "$OUT" | jlen missing_files)
ST=$(plan_status 4.C.3.VT.1)
[ "$ACT" = "call_s4" ] && pass "VF 步骤无交付物要求 → 推进（got: $ACT）" || fail "VF 应推进 (got: $ACT)"
[ "$NEXT" = "4.C.3" ] && pass "next_sub_stage=4.C.3" || fail "next 应为 4.C.3 (got: $NEXT)"
[ "$ML" = "0" ] && pass "missing_files=0（VF 文件不计入）" || fail "missing 应为 0 (got: $ML)"
[ "$ST" = "done" ] && pass "VF 步骤 status=done" || fail "VF 应 done (got: $ST)"
teardown

# ──────────────────────────────────────────────────────────────────
echo ""
echo "── Test 6: 概念占位符交付物 → COMPLETED 同样放行（全链路均不做交付物判定）──"
setup_env
meta_with_codepath
# 模拟 s2 产出 (CopyIn 实现) 占位符。s2 gate 与 dispatch 层均不做交付物判定——
# s2 完成只看 agent 返回，s4 完成只看 s4-coding 返回，COMPLETED 一律放行推进。
cat > "$RECORD_DIR/orchestration_plan.json" <<'EOF'
{
  "op_name": "gather",
  "programming_model": "A5 Regbase",
  "sub_stages": [
    {"id": "4.0", "desc": "编码前置", "checkpoint_group": "INDEPENDENT", "execution_group": "host_tiling", "kind": "check", "deliverables": [], "status": "done"},
    {"id": "4.C.2", "desc": "CopyIn", "checkpoint_group": "KERNEL", "execution_group": "kernel_base", "kind": "code", "deliverables": ["(CopyIn 实现)"], "status": "pending"}
  ]
}
EOF
OUT=$(dispatch)
ACT=$(echo "$OUT" | jget action)
# 4.C.2 是最后 pending → 标 done 后无后继 → finish（同样验证：dispatch 不做交付物判定）
[ "$ACT" = "finish" ] && pass "COMPLETED 放行推进 → finish（dispatch 不做交付物判定）" || fail "应 finish (got: $ACT)"
teardown

# ──────────────────────────────────────────────────────────────────
echo ""
echo "── Test 7: regenerate-progress 派生 progress.md ──"
setup_env
meta_with_codepath
bash "$DEV_RECORD" regenerate-progress "$RECORD_DIR" >/dev/null 2>&1
P=$(cat "$RECORD_DIR/progress.md")
echo "$P" | grep -q "4.A TilingData | ⏳" && pass "progress.md 含 4.A 行（pending→⏳）" || fail "progress.md 缺 4.A 行: $P"
echo "$P" | grep -q "4.0 编码前置 | ✅" && pass "progress.md 4.0 映射 done→✅" || fail "progress.md 4.0 应为 ✅"
teardown

# ──────────────────────────────────────────────────────────────────
echo ""
echo "============================================"
echo " 结果: PASS=$PASS  FAIL=$FAIL"
echo "============================================"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
