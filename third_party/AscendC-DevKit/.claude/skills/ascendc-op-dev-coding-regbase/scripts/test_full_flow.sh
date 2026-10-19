#!/bin/bash
# test_full_flow.sh - 模拟完整 5 Stage 开发记录流程验证
# 验证 dev_record.sh + check_gate.sh 在新 Stage 4 子阶段模型下的协作
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_DIR="/tmp/test_ascendc_flow_$$"
PASS=0
FAIL=0

log_pass() { echo "  ✅ $1"; PASS=$((PASS+1)); }
log_fail() { echo "  ❌ $1"; FAIL=$((FAIL+1)); }

cleanup() { rm -rf "$TEST_DIR"; }
trap cleanup EXIT

mkdir -p "$TEST_DIR"

echo "=== 验证 1: init 创建目录 ==="
RD=$(bash "$SCRIPT_DIR/dev_record.sh" init "$TEST_DIR" "TestMatMul")
[ -d "$RD" ] && log_pass "目录已创建: $RD" || log_fail "目录创建失败"
[ -f "$RD/meta.json" ] && log_pass "meta.json 存在" || log_fail "meta.json 缺失"
[ -f "$RD/progress.md" ] && log_pass "progress.md 存在" || log_fail "progress.md 缺失"
[ -f "$RD/history.log" ] && log_pass "history.log 存在" || log_fail "history.log 缺失"
[ -d "$RD/issues" ] && log_pass "issues/ 目录存在" || log_fail "issues/ 缺失"
grep -q "4\.B1 OpDef" "$RD/progress.md" && log_pass "progress.md 已拆分为 4.B1/4.B2" || log_fail "4.B1/4.B2 未找到"
grep -q "4\.C Kernel 实现" "$RD/progress.md" && log_pass "progress.md 包含 4.C 占位行" || log_fail "4.C 占位行缺失"

echo ""
echo "=== 验证 2: set-meta / get-meta（含数组类型） ==="
bash "$SCRIPT_DIR/dev_record.sh" set-meta "$RD" chip_model "910B3" >/dev/null
bash "$SCRIPT_DIR/dev_record.sh" set-meta "$RD" programming_model "A3 Membase" >/dev/null
bash "$SCRIPT_DIR/dev_record.sh" set-meta "$RD" ub_size 253952 >/dev/null
bash "$SCRIPT_DIR/dev_record.sh" set-meta "$RD" dev_mode "存量改造" >/dev/null
bash "$SCRIPT_DIR/dev_record.sh" set-meta "$RD" kernel_steps '["C.0","C.1","C.2"]' >/dev/null

V=$(bash "$SCRIPT_DIR/dev_record.sh" get-meta "$RD" chip_model)
[ "$V" = "910B3" ] && log_pass "get-meta chip_model = 910B3" || log_fail "chip_model got: $V"

V=$(bash "$SCRIPT_DIR/dev_record.sh" get-meta "$RD" kernel_steps)
[ "$V" = '["C.0", "C.1", "C.2"]' ] && log_pass "kernel_steps 正确存储为 JSON 数组" || log_fail "kernel_steps got: $V"

echo ""
echo "=== 验证 3: expand-kernel 展开与幂等性 ==="
OUT=$(bash "$SCRIPT_DIR/dev_record.sh" expand-kernel "$RD" "C.0:Kernel入口,C.1:类框架,C.2:FP4解包,C.3:类型转换,C.4:Scale计算")
echo "$OUT" | grep -q "展开 5 个 Kernel 步骤" && log_pass "expand-kernel 展开 5 步" || log_fail "expand-kernel: $OUT"
for sub in "4.C.0" "4.C.1" "4.C.2" "4.C.3" "4.C.4"; do
    grep -qE "^\\| ${sub} " "$RD/progress.md" && log_pass "progress.md 包含 ${sub}" || log_fail "${sub} 未找到"
done
V=$(bash "$SCRIPT_DIR/dev_record.sh" get-meta "$RD" kernel_steps)
[ "$V" = '["C.0", "C.1", "C.2", "C.3", "C.4"]' ] && log_pass "kernel_steps 同步为 5 元素数组" || log_fail "kernel_steps got: $V"

OUT2=$(bash "$SCRIPT_DIR/dev_record.sh" expand-kernel "$RD" "C.0:Kernel入口,C.1:类框架")
echo "$OUT2" | grep -q "已展开，跳过" && log_pass "expand-kernel 幂等跳过" || log_fail "幂等失败: $OUT2"

echo ""
echo "=== 验证 4: set-progress 前缀匹配（4.C.1 vs 4.C.10/4.C.11） ==="
RD2=$(bash "$SCRIPT_DIR/dev_record.sh" init "$TEST_DIR" "PrefixTest")
bash "$SCRIPT_DIR/dev_record.sh" expand-kernel "$RD2" "C.1:步骤1,C.10:步骤10,C.11:步骤11" >/dev/null
bash "$SCRIPT_DIR/dev_record.sh" set-progress "$RD2" "4.C.1" "✅" >/dev/null
L10=$(grep "^| 4.C.10 " "$RD2/progress.md" | head -1)
L11=$(grep "^| 4.C.11 " "$RD2/progress.md" | head -1)
echo "$L10" | grep -q "❌" && log_pass "4.C.10 未被误标记" || log_fail "4.C.10 被误标记: $L10"
echo "$L11" | grep -q "❌" && log_pass "4.C.11 未被误标记" || log_fail "4.C.11 被误标记: $L11"

echo ""
echo "=== 验证 5: 模拟 Stage 1→5 流程 ==="

# Stage 1 完成
bash "$SCRIPT_DIR/dev_record.sh" set-progress "$RD" "1" "✅" >/dev/null
bash "$SCRIPT_DIR/dev_record.sh" append-history "$RD" STAGE_COMPLETE "Stage 1 完成" >/dev/null

# check_gate Stage 2 应通过
GATE=$(bash "$SCRIPT_DIR/check_gate.sh" "$RD" 2)
echo "$GATE" | grep -q '"pass": true' && log_pass "gate check: Stage 2 可进入" || log_fail "gate: $GATE"

# Stage 2 完成
bash "$SCRIPT_DIR/dev_record.sh" set-progress "$RD" "2" "✅" >/dev/null
bash "$SCRIPT_DIR/dev_record.sh" append-history "$RD" STAGE_COMPLETE "Stage 2 完成" >/dev/null

# Stage 3 完成
bash "$SCRIPT_DIR/dev_record.sh" set-progress "$RD" "3" "✅" >/dev/null
bash "$SCRIPT_DIR/dev_record.sh" append-history "$RD" STAGE_COMPLETE "Stage 3 完成" >/dev/null

# 新流程强制要求 coding_index.md
cat > "$RD/coding_index.md" <<'EOF'
# Coding Index

## 元信息

- 编程模型: A3 Membase
- 参考算子来源: 测试
- 参考算子路径: —

## 编码步骤索引

| 步骤 | 检查点组 | 详设章节 | 参考代码 | 知识/经验 | 关键 API | 自检关注点 | ~行数 |
|------|---------|---------|---------|----------|---------|-----------|-------|
| A | 1 | §3.1 | — | — | — | — | ~20 |
| B1 | 1 | §3.2 | — | — | — | — | ~40 |
| B2 | 1 | §3.3 | — | — | — | — | ~60 |
| C.0 | 2 | §4.1 | — | — | — | — | ~30 |
| C.1 | 2 | §4.2 | — | — | — | — | ~80 |
| C.2 | 3 | §4.3 | — | — | — | — | ~30 |
| E | Last | §5.1 | — | — | — | — | ~15 |
| F | Last | §5.2 | — | — | — | — | ~15 |

## 字段映射表

## 算法步骤摘要
EOF

# check_gate Stage 4 应通过
GATE=$(bash "$SCRIPT_DIR/check_gate.sh" "$RD" 4)
echo "$GATE" | grep -q '"pass": true' && log_pass "gate check: Stage 4 可进入" || log_fail "gate: $GATE"

# Stage 4 sub-stages（含 B1/B2 拆分和 C.0~C.n 动态行）
for sub in "4.0" "4.A" "4.B1" "4.B2" "4.C.0" "4.C.1" "4.C.2" "4.C.3" "4.C.4" "4.E" "4.F"; do
    bash "$SCRIPT_DIR/dev_record.sh" set-progress "$RD" "$sub" "✅" >/dev/null
done
bash "$SCRIPT_DIR/dev_record.sh" append-history "$RD" STAGE_COMPLETE "Stage 4 完成" >/dev/null

# check_gate Stage 5 应通过（所有 4.x 都 ✅）
GATE=$(bash "$SCRIPT_DIR/check_gate.sh" "$RD" 5)
echo "$GATE" | grep -q '"pass": true' && log_pass "gate check: Stage 5 可进入（所有4.x ✅）" || log_fail "gate: $GATE"

# Stage 5 完成
bash "$SCRIPT_DIR/dev_record.sh" set-progress "$RD" "5" "✅" >/dev/null
bash "$SCRIPT_DIR/dev_record.sh" append-history "$RD" STAGE_COMPLETE "Stage 5 完成" >/dev/null

echo ""
echo "=== 验证 6: 编译失败重试模拟 ==="
bash "$SCRIPT_DIR/dev_record.sh" set-meta "$RD" retries.stage5_compile.used 0 >/dev/null
bash "$SCRIPT_DIR/dev_record.sh" append-history "$RD" ERROR "C-SYM: undefined symbol blockSize" >/dev/null
bash "$SCRIPT_DIR/dev_record.sh" set-meta "$RD" retries.stage5_compile.used 1 >/dev/null
V=$(bash "$SCRIPT_DIR/dev_record.sh" get-meta "$RD" retries.stage5_compile.used)
[ "$V" = "1" ] && log_pass "重试计数器递增: 1" || log_fail "retry got: $V"

bash "$SCRIPT_DIR/dev_record.sh" append-history "$RD" ERROR "C-TYP: type mismatch in tiling.cpp" >/dev/null
bash "$SCRIPT_DIR/dev_record.sh" set-meta "$RD" retries.stage5_compile.used 2 >/dev/null
V=$(bash "$SCRIPT_DIR/dev_record.sh" get-meta "$RD" retries.stage5_compile.used)
[ "$V" = "2" ] && log_pass "重试计数器递增: 2" || log_fail "retry got: $V"

echo ""
echo "=== 验证 7: cleanup-kb-cache 幂等性 ==="
CACHE="$RD/coding_index_kb_cache.md"
echo "# cache" > "$CACHE"
bash "$SCRIPT_DIR/dev_record.sh" cleanup-kb-cache "$RD" >/dev/null
[ ! -f "$CACHE" ] && log_pass "cleanup-kb-cache 删除缓存" || log_fail "缓存仍存在"
OUT=$(bash "$SCRIPT_DIR/dev_record.sh" cleanup-kb-cache "$RD")
echo "$OUT" | grep -q "无需清理" && log_pass "cleanup-kb-cache 幂等" || log_fail "幂等失败: $OUT"

echo ""
echo "=== 验证 8: update-coding-plan 文件状态同步 ==="
# 构造标准 coding_plan.md
cat > "$RD/coding_plan.md" <<'EOF'
# Coding Plan

| 文件 | Sub-stage | 状态 | 备注 |
|------|-----------|------|------|
| *_tilingdata.h | A | ❌ | TilingData 结构体 |
| *_def.cpp | B1 | ❌ | OpDef + InferShape |
| *_tiling.h | B2 | ❌ | Tiling 策略声明 |
| *_tiling.cpp | B2 | ❌ | Tiling 策略实现 |
| *.cpp (kernel入口) | C.0 | ❌ | extern "C" 入口 |
| *.h (kernel类) | C.1~C.n | ❌ | 类框架+各计算单元 |
| CMakeLists.txt | E | ❌ | 构建配置 |
EOF
bash "$SCRIPT_DIR/dev_record.sh" update-coding-plan "$RD" "A" "✅" >/dev/null
bash "$SCRIPT_DIR/dev_record.sh" update-coding-plan "$RD" "C.3" "⏳" >/dev/null
grep "^| \*_tilingdata.h" "$RD/coding_plan.md" | grep -q "✅" && log_pass "update-coding-plan A → ✅" || log_fail "A 未更新"
grep "^| \*.h (kernel类)" "$RD/coding_plan.md" | grep -q "⏳" && log_pass "update-coding-plan C.3 → C.1~C.n ⏳" || log_fail "C.1~C.n 未更新"

echo ""
echo "=== 验证 9: history.log 内容完整性 ==="
LINES=$(wc -l < "$RD/history.log")
[ "$LINES" -ge 7 ] && log_pass "history.log 有 $LINES 行记录" || log_fail "仅 $LINES 行"

echo ""
echo "=== 验证 10: stage4_scheduler.sh 编排辅助（orchestration_plan.json 驱动）==="
cat > "$RD/orchestration_plan.json" <<'EOF'
{
  "op_name": "TestMatMul",
  "programming_model": "A5 Regbase",
  "sub_stages": [
    {"id": "4.0", "desc": "编码前置", "checkpoint_group": "INDEPENDENT", "kind": "check", "deliverables": [], "status": "pending"},
    {"id": "4.A", "desc": "TilingData", "checkpoint_group": "HOST", "kind": "code", "deliverables": ["op_kernel/TestMatMul_tiling_data.h"], "status": "pending"},
    {"id": "4.B1", "desc": "OpDef", "checkpoint_group": "HOST", "kind": "code", "deliverables": ["op_host/TestMatMul_def.cpp"], "status": "pending"},
    {"id": "4.B2", "desc": "Tiling", "checkpoint_group": "HOST", "kind": "code", "deliverables": ["op_host/TestMatMul_tiling.cpp"], "status": "pending"},
    {"id": "4.C.0", "desc": "Kernel入口", "checkpoint_group": "KERNEL", "kind": "code", "deliverables": ["op_kernel/TestMatMul.cpp"], "status": "pending"},
    {"id": "4.C.1", "desc": "类框架", "checkpoint_group": "KERNEL", "kind": "code", "deliverables": ["op_kernel/TestMatMul.h"], "status": "pending"},
    {"id": "4.C.2", "desc": "CopyIn", "checkpoint_group": "KERNEL", "kind": "code", "deliverables": ["op_kernel/TestMatMul.h"], "status": "pending"},
    {"id": "4.C.3", "desc": "Compute", "checkpoint_group": "KERNEL", "kind": "code", "deliverables": ["op_kernel/TestMatMul.h"], "status": "pending"},
    {"id": "4.C.4", "desc": "CopyOut", "checkpoint_group": "KERNEL", "kind": "code", "deliverables": ["op_kernel/TestMatMul.h"], "status": "pending"},
    {"id": "4.E", "desc": "CMakeLists", "checkpoint_group": "LAST", "kind": "code", "deliverables": ["CMakeLists.txt"], "status": "pending"},
    {"id": "4.F", "desc": "综合自检", "checkpoint_group": "LAST", "kind": "check", "deliverables": [], "status": "pending"}
  ]
}
EOF

V=$(bash "$SCRIPT_DIR/stage4_scheduler.sh" resolve-sub-stage "$RD" first_enter)
[ "$V" = "4.0" ] && log_pass "resolve-sub-stage first_enter = 4.0" || log_fail "first_enter got: $V"

# continue 测试：4.0 done，4.A pending → 返回 4.A
python3 -c "
import json
d=json.load(open('$RD/orchestration_plan.json'))
d['sub_stages'][0]['status']='done'
json.dump(d, open('$RD/orchestration_plan.json','w'), ensure_ascii=False, indent=2)
"
V=$(bash "$SCRIPT_DIR/stage4_scheduler.sh" resolve-sub-stage "$RD" continue)
[ "$V" = "4.A" ] && log_pass "resolve-sub-stage continue = 4.A" || log_fail "continue got: $V"

# retry 测试：全部置为 done，仅 4.B2 保持 pending → 最后一个 pending = 4.B2
python3 -c "
import json
d=json.load(open('$RD/orchestration_plan.json'))
for s in d['sub_stages']:
    if s['id'] != '4.B2':
        s['status']='done'
json.dump(d, open('$RD/orchestration_plan.json','w'), ensure_ascii=False, indent=2)
"
V=$(bash "$SCRIPT_DIR/stage4_scheduler.sh" resolve-sub-stage "$RD" retry)
[ "$V" = "4.B2" ] && log_pass "resolve-sub-stage retry = 4.B2" || log_fail "retry got: $V"

# 检查点组查询
V=$(bash "$SCRIPT_DIR/stage4_scheduler.sh" get-group "$RD" "4.B2")
[ "$V" = "HOST" ] && log_pass "get-group 4.B2 = HOST" || log_fail "get-group got: $V"

V=$(bash "$SCRIPT_DIR/stage4_scheduler.sh" get-group "$RD" "4.E")
[ "$V" = "LAST" ] && log_pass "get-group 4.E = LAST" || log_fail "get-group E got: $V"

# check-gate 应识别未就绪（4.B2 仍为 pending）
V=$(bash "$SCRIPT_DIR/stage4_scheduler.sh" check-gate "$RD")
echo "$V" | grep -q "NOT_READY" && log_pass "check-gate 正确识别未就绪" || log_fail "check-gate: $V"

# 全部完成后再测 gate
python3 -c "
import json
d=json.load(open('$RD/orchestration_plan.json'))
for s in d['sub_stages']:
    s['status']='done'
json.dump(d, open('$RD/orchestration_plan.json','w'), ensure_ascii=False, indent=2)
"
V=$(bash "$SCRIPT_DIR/stage4_scheduler.sh" check-gate "$RD")
[ "$V" = "READY" ] && log_pass "check-gate 最终返回 READY" || log_fail "check-gate final: $V"

bash "$SCRIPT_DIR/stage4_scheduler.sh" finish-stage4 "$RD" >/dev/null && log_pass "finish-stage4 输出动作清单" || log_fail "finish-stage4 失败"

echo ""
echo "=== 验证 11: Agent RETURN 解析 ==="
RD4=$(bash "$SCRIPT_DIR/dev_record.sh" init "$TEST_DIR" "EtTest")
cat > "$RD4/last_return.md" <<'EOF'
## RETURN: status=NEEDS_AGENT, next_stage=5, agent_name=ascendc-tiling-strategy, resume_point=5.3.2-recompile

状态: NEEDS_AGENT
原因: Tiling 策略需优化
目标 Agent: ascendc-tiling-strategy
EOF
RET=$(bash "$SCRIPT_DIR/dev_record.sh" parse-return "$RD4")
echo "$RET" | grep -q '"status": "NEEDS_AGENT"' && log_pass "RETURN status = NEEDS_AGENT" || log_fail "RETURN status: $RET"
echo "$RET" | grep -q '"next_stage": "5"' && log_pass "RETURN next_stage = 5" || log_fail "RETURN next_stage: $RET"
echo "$RET" | grep -q '"agent_name": "ascendc-tiling-strategy"' && log_pass "RETURN agent_name 正确" || log_fail "RETURN agent_name: $RET"

echo ""
echo "=== 验证 12: PAUSED 恢复 ==="
bash "$SCRIPT_DIR/dev_record.sh" set-progress "$RD4" "5" "🔄" >/dev/null
bash "$SCRIPT_DIR/dev_record.sh" append-history "$RD4" PAUSED "Stage 5: 环境 - CANN 未配置" 0.60 >/dev/null
bash "$SCRIPT_DIR/dev_record.sh" resume "$RD4" >/dev/null
L5=$(grep "^| 5 " "$RD4/progress.md" | head -1)
echo "$L5" | grep -q "⏳" && log_pass "Stage 5 恢复为 ⏳" || log_fail "Stage 5 状态: $L5"
grep -q "RESUME.*从 Stage 5 恢复" "$RD4/history.log" && log_pass "history.log 追加 RESUME 事件" || log_fail "RESUME 事件未写入"
CS=$(bash "$SCRIPT_DIR/dev_record.sh" get-meta "$RD4" current_stage)
[ "$CS" = "5" ] && log_pass "current_stage 恢复为 5" || log_fail "current_stage got: $CS"

echo ""
echo "=== 验证 13: 多级子步骤 C.N.M（如 C.3.1/C.3.2）==="

RD5=$(bash "$SCRIPT_DIR/dev_record.sh" init "$TEST_DIR" "MultiLevel")

# coding_index.md 含 C.3.1/C.3.2 步骤
cat > "$RD5/coding_index.md" <<'EOF'
# Coding Index

## 元信息

- 编程模型: A5 Regbase
- 参考算子来源: 测试
- 参考算子路径: —

## 编码步骤索引

| 步骤 | 检查点组 | 详设章节 | 参考代码 | 知识/经验 | 关键 API | 自检关注点 | ~行数 |
|------|---------|---------|---------|----------|---------|-----------|-------|
| A | 1 | §3.1 | — | — | — | — | ~20 |
| B1 | 1 | §3.2 | — | — | — | — | ~40 |
| B2 | 1 | §3.3 | — | — | — | — | ~60 |
| C.0 | 2 | §4.1 | — | — | — | — | ~30 |
| C.1 | 2 | §4.2 | — | — | — | — | ~80 |
| C.2 | 3 | §4.3 | — | — | — | — | ~30 |
| C.3.1 | 3 | §4.4.1 | — | — | — | — | ~60 |
| C.3.2 | 3 | §4.4.2 | — | — | — | — | ~60 |
| C.4 | 3 | §4.5 | — | — | — | — | ~30 |
| E | Last | §5.1 | — | — | — | — | ~15 |
| F | Last | §5.2 | — | — | — | — | ~15 |

## 字段映射表

## 算法步骤摘要
EOF

# expand-kernel 展开多级步骤
OUT=$(bash "$SCRIPT_DIR/dev_record.sh" expand-kernel "$RD5" "C.0:入口,C.1:类框架,C.2:CopyIn,C.3.1:VF_A,C.3.2:VF_B,C.4:CopyOut")
echo "$OUT" | grep -q "展开 6 个 Kernel 步骤" && log_pass "expand-kernel 支持 C.3.1/C.3.2" || log_fail "expand-kernel 多级: $OUT"

for sub in "4.C.0" "4.C.1" "4.C.2" "4.C.3.1" "4.C.3.2" "4.C.4"; do
    grep -qE "^\\| ${sub} " "$RD5/progress.md" && log_pass "progress.md 包含 ${sub}" || log_fail "${sub} 未找到"
done

V=$(bash "$SCRIPT_DIR/dev_record.sh" get-meta "$RD5" kernel_steps)
[ "$V" = '["C.0", "C.1", "C.2", "C.3.1", "C.3.2", "C.4"]' ] && log_pass "kernel_steps 含多级子步骤" || log_fail "kernel_steps got: $V"

# stage4_scheduler 应能解析多级步骤的检查点组（读 orchestration_plan.json）
cat > "$RD5/orchestration_plan.json" <<'EOF'
{
  "op_name": "MultiLevel",
  "programming_model": "A5 Regbase",
  "sub_stages": [
    {"id": "4.0", "desc": "编码前置", "checkpoint_group": "INDEPENDENT", "kind": "check", "deliverables": [], "status": "done"},
    {"id": "4.A", "desc": "TilingData", "checkpoint_group": "HOST", "kind": "code", "deliverables": ["op_kernel/MultiLevel_tiling_data.h"], "status": "done"},
    {"id": "4.B1", "desc": "OpDef", "checkpoint_group": "HOST", "kind": "code", "deliverables": ["op_host/MultiLevel_def.cpp"], "status": "done"},
    {"id": "4.B2", "desc": "Tiling", "checkpoint_group": "HOST", "kind": "code", "deliverables": ["op_host/MultiLevel_tiling.cpp"], "status": "done"},
    {"id": "4.C.0", "desc": "入口", "checkpoint_group": "KERNEL", "kind": "code", "deliverables": ["op_kernel/MultiLevel.cpp"], "status": "done"},
    {"id": "4.C.1", "desc": "类框架", "checkpoint_group": "KERNEL", "kind": "code", "deliverables": ["op_kernel/MultiLevel.h"], "status": "done"},
    {"id": "4.C.2", "desc": "CopyIn", "checkpoint_group": "KERNEL", "kind": "code", "deliverables": ["op_kernel/MultiLevel.h"], "status": "done"},
    {"id": "4.C.3.1", "desc": "VF_A", "checkpoint_group": "KERNEL", "kind": "code", "deliverables": ["op_kernel/MultiLevel.h"], "status": "done"},
    {"id": "4.C.3.2", "desc": "VF_B", "checkpoint_group": "KERNEL", "kind": "code", "deliverables": ["op_kernel/MultiLevel.h"], "status": "pending"},
    {"id": "4.C.4", "desc": "CopyOut", "checkpoint_group": "KERNEL", "kind": "code", "deliverables": ["op_kernel/MultiLevel.h"], "status": "pending"},
    {"id": "4.E", "desc": "CMakeLists", "checkpoint_group": "LAST", "kind": "code", "deliverables": ["CMakeLists.txt"], "status": "pending"},
    {"id": "4.F", "desc": "综合自检", "checkpoint_group": "LAST", "kind": "check", "deliverables": [], "status": "pending"}
  ]
}
EOF

V=$(bash "$SCRIPT_DIR/stage4_scheduler.sh" get-group "$RD5" "4.C.3.1")
[ "$V" = "KERNEL" ] && log_pass "get-group 4.C.3.1 = KERNEL" || log_fail "get-group C.3.1 got: $V"

# check-gate 应识别 4.C.3.2 未完成
V=$(bash "$SCRIPT_DIR/stage4_scheduler.sh" check-gate "$RD5")
echo "$V" | grep -q "NOT_READY: 4.C.3.2" && log_pass "check-gate 识别未完成的 4.C.3.2" || log_fail "check-gate: $V"

# resolve-sub-stage continue 应返回 4.C.3.2
V=$(bash "$SCRIPT_DIR/stage4_scheduler.sh" resolve-sub-stage "$RD5" continue)
[ "$V" = "4.C.3.2" ] && log_pass "resolve-sub-stage continue = 4.C.3.2" || log_fail "continue got: $V"

# 标记 4.C.3.2 完成后 gate 通过
python3 -c "
import json
p='$RD5/orchestration_plan.json'
d=json.load(open(p))
for s in d['sub_stages']:
    s['status']='done'
json.dump(d, open(p,'w'), ensure_ascii=False, indent=2)
"
V=$(bash "$SCRIPT_DIR/stage4_scheduler.sh" check-gate "$RD5")
[ "$V" = "READY" ] && log_pass "check-gate 多级步骤全部完成返回 READY" || log_fail "check-gate final: $V"

# set-progress 前缀匹配：4.C.3.1 不应误标 4.C.3 或 4.C.3.10
RD6=$(bash "$SCRIPT_DIR/dev_record.sh" init "$TEST_DIR" "PrefixMulti")
bash "$SCRIPT_DIR/dev_record.sh" expand-kernel "$RD6" "C.3:Compute,C.3.1:VF_A,C.3.2:VF_B,C.3.10:VF_C" >/dev/null
bash "$SCRIPT_DIR/dev_record.sh" set-progress "$RD6" "4.C.3.1" "✅" >/dev/null
L3=$(grep "^| 4.C.3 " "$RD6/progress.md" | head -1)
L31=$(grep "^| 4.C.3.1 " "$RD6/progress.md" | head -1)
L310=$(grep "^| 4.C.3.10 " "$RD6/progress.md" | head -1)
echo "$L3" | grep -q "❌" && log_pass "4.C.3 未被 4.C.3.1 误标记" || log_fail "4.C.3 被误标记: $L3"
echo "$L31" | grep -q "✅" && log_pass "4.C.3.1 正确标记" || log_fail "4.C.3.1 未标记: $L31"
echo "$L310" | grep -q "❌" && log_pass "4.C.3.10 未被 4.C.3.1 误标记" || log_fail "4.C.3.10 被误标记: $L310"

echo ""
echo "========================================"
echo "  结果: $PASS 通过, $FAIL 失败"
echo "========================================"

[ "$FAIL" -eq 0 ] && exit 0 || exit 1
