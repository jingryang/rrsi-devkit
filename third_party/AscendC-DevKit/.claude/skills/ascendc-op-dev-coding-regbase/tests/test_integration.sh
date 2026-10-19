#!/bin/bash
# test_integration.sh — ascendc-op-dev-coding-regbase 集成验证
# 验证脚本/参考文档/Agent/Skill 依赖完整性 + 格式契约兼容性
set -o pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(bash "$SKILL_DIR/scripts/get_repo_root.sh" "$SKILL_DIR")"
PASS=0
FAIL=0

log_pass() { echo "  ✅ $1"; PASS=$((PASS+1)); }
log_fail() { echo "  ❌ $1"; FAIL=$((FAIL+1)); }

echo "============================================"
echo " ascendc-op-dev-coding-regbase 集成验证"
echo " SKILL_DIR: $SKILL_DIR"
echo " REPO_ROOT: $REPO_ROOT"
echo "============================================"

# ── 1. 脚本完整性 ──
echo ""
echo "── 1. 脚本完整性 ──"
for s in dev_record.sh stage4_scheduler.sh check_gate.sh; do
    f="$SKILL_DIR/scripts/$s"
    [ -f "$f" ] && [ -x "$f" ] && log_pass "scripts/$s" || log_fail "scripts/$s 缺失或不可执行"
done

# 验证关键子命令存在
echo ""
echo "── 1.1 dev_record.sh 子命令 ──"
for cmd in append-history set-progress expand-kernel init get-meta; do
    grep -q "    $cmd) " "$SKILL_DIR/scripts/dev_record.sh" 2>/dev/null \
        && log_pass "dev_record.sh $cmd" \
        || log_fail "dev_record.sh $cmd 缺失"
done

echo ""
echo "── 1.2 stage4_scheduler.sh 子命令（薄壳 → 编排层 CLI）──"
for cmd in resolve-sub-stage get-group check-gate dispatch; do
    # 薄壳转发到编排层 codegen_s4.py CLI；命令存在性由编排层 main() 保证
    bash "$SKILL_DIR/scripts/stage4_scheduler.sh" "$cmd" 2>/dev/null
    rc=$?
    # 用法错误退出码 = 2（有命令但缺参数）说明命令被 main() 识别
    [ "$rc" = "2" ] && log_pass "stage4_scheduler.sh $cmd 可识别" \
        || log_fail "stage4_scheduler.sh $cmd 不可识别 (rc=$rc)"
done

# ── 2. 参考文档完整性 ──
echo ""
echo "── 2. 参考文档完整性 ──"
for f in orchestrator-logic.md workflow-spec.md error-handling.md \
         subagent-common-protocol.md todo-template.md phase-c-prompts.md \
         coding-plan-template.md dev-record-template.md meta-schema.json; do
    [ -f "$SKILL_DIR/references/$f" ] && log_pass "references/$f" || log_fail "references/$f 缺失"
done

# ── 3. SKILL.md 本身 ──
echo ""
echo "── 3. SKILL.md ──"
[ -f "$SKILL_DIR/SKILL.md" ] && log_pass "SKILL.md 存在" || log_fail "SKILL.md 缺失"
head -1 "$SKILL_DIR/SKILL.md" | grep -q '^---$' && log_pass "SKILL.md frontmatter 格式" || log_fail "SKILL.md frontmatter 格式异常"

# ── 4. Agent 文件 ──
echo ""
echo "── 4. Agent 文件完整性 ──"
for a in ascendc-dev-s2-analysis.md ascendc-dev-s4-coding.md \
         ascendc-dev-s5-compile.md ascendc-vf-test-agent.md; do
    f="$REPO_ROOT/.claude/agents/$a"
    [ -f "$f" ] && log_pass "agents/$a" || log_fail "agents/$a 缺失"
done

# ── 5. Skill 依赖 ──
echo ""
echo "── 5. Skill 依赖 ──"
check_skill() {
    local name="$1"
    local found
    found=$(find "$REPO_ROOT/.claude" -maxdepth 5 -name "$name" -type d 2>/dev/null | head -1)
    [ -n "$found" ] && log_pass "$name → ${found#$REPO_ROOT/}" || log_fail "$name 未找到"
}
check_skill "ascendc-dev-knowledge"
check_skill "ascendc-tips"
check_skill "ascendc-sync"
check_skill "evolution-knowledge"
check_skill "regbase-vf-test"

# ── 6. Python 语法 ──
echo ""
echo "── 6. SKILL.md 内嵌代码语法 ──"
# 提取 Step 1.1 的 python3 代码块
python3 -c "
import re, sys
with open('$SKILL_DIR/SKILL.md') as f:
    content = f.read()
# 找到 python3 -c \"...\" 块
m = re.search(r'python3 -c \"(.*?)\"', content, re.DOTALL)
if m:
    code = m.group(1)
    code = code.replace('\\\\', '\\\\')  # unescape
    compile(code, '<SKILL.md>', 'exec')
    print('SKILL.md Python code OK')
else:
    print('WARNING: no python3 -c block found')
" 2>&1
[ $? -eq 0 ] && log_pass "SKILL.md 内嵌 Python 语法正确" || log_fail "SKILL.md 内嵌 Python 语法错误"

# ── 7. progress.md 格式兼容性 ──
echo ""
echo "── 7. progress.md 格式兼容性 ──"
python3 -c "
import re

# 从 SKILL.md 提取的模板行
lines = [
    ('4.0 编码前置', 'SKILL.md template'),
    ('4.A TilingData 定义', 'SKILL.md template'),
    ('4.B1 OpDef 注册', 'SKILL.md template'),
    ('4.B2 Tiling 实现', 'SKILL.md template'),
    ('4.C Kernel 实现', 'SKILL.md template'),
    ('4.E CMakeLists', 'SKILL.md template'),
    ('4.F 收尾', 'SKILL.md template'),
    ('5 编译出包', 'SKILL.md template'),
]

# stage4_scheduler.sh 正则
pattern = r'^\|\s*(4\.[0-9A-Z]+(?:\.[0-9A-Z]+)*)\s+(.*?)\s*\|\s*([⏳❌✅])\s*\|'

regex_ok = 0
regex_fail = 0
parts_ok = 0
parts_fail = 0

for desc, source in lines:
    line = f'| {desc} | ❌ | - | - |'
    # regex test (skip Stage 5 row)
    m = re.match(pattern, line)
    if m or desc.startswith('5 '):
        regex_ok += 1
    else:
        regex_fail += 1
        print(f'  REGEX FAIL: {line[:50]}')
    # set-progress parts test
    parts = line.split('|')
    if len(parts) >= 5:
        parts_ok += 1
    else:
        parts_fail += 1
        print(f'  PARTS FAIL (n={len(parts)}): {line[:50]}')

print(f'  regex: {regex_ok}/{len(lines)} OK, {regex_fail} FAIL')
print(f'  set-progress parts: {parts_ok}/{len(lines)} OK, {parts_fail} FAIL')
" 2>&1
[ "$(python3 -c "
import re
lines = ['4.0 编码前置','4.A TilingData 定义','4.B1 OpDef 注册','4.B2 Tiling 实现','4.C Kernel 实现','4.E CMakeLists','4.F 收尾','5 编译出包']
pattern = r'^\|\s*(4\.[0-9A-Z]+(?:\.[0-9A-Z]+)*)\s+(.*?)\s*\|\s*([⏳❌✅])\s*\|'
ok=sum(1 for d in lines if re.match(pattern, f'| {d} | ❌ | - | - |') or d.startswith('5 '))
print(ok)
")" -eq 8 ] && log_pass "progress.md 格式兼容 (8/8)" || log_fail "progress.md 格式不兼容"

# ── 8. expand-kernel 占位行 ──
echo ""
echo "── 8. expand-kernel 占位行检测 ──"
echo '| 4.C Kernel 实现 | ❌ | - | - |' | grep -qF "| 4.C Kernel" \
    && log_pass "expand-kernel 占位行可检测" \
    || log_fail "expand-kernel 占位行不可检测"

# ── 9. dev_record.sh 端到端冒烟 ──
echo ""
echo "── 9. dev_record.sh 冒烟测试 ──"
TEST_DIR=$(mktemp -d)
trap "rm -rf $TEST_DIR" EXIT

# init
RD=$(bash "$SKILL_DIR/scripts/dev_record.sh" init "$TEST_DIR" "TestOp" 2>&1)
[ -d "$RD" ] && log_pass "dev_record.sh init 成功" || log_fail "dev_record.sh init 失败: $RD"

# set-meta
bash "$SKILL_DIR/scripts/dev_record.sh" set-meta "$RD" "current_stage" "1" 2>/dev/null \
    && log_pass "dev_record.sh set-meta" || log_fail "dev_record.sh set-meta"

# get-meta
VAL=$(bash "$SKILL_DIR/scripts/dev_record.sh" get-meta "$RD" "current_stage" 2>/dev/null)
[ "$VAL" = "1" ] && log_pass "dev_record.sh get-meta → $VAL" || log_fail "dev_record.sh get-meta → $VAL (expected 1)"

# append-history
bash "$SKILL_DIR/scripts/dev_record.sh" append-history "$RD" "STAGE_COMPLETE" "test" 2>/dev/null \
    && log_pass "dev_record.sh append-history" || log_fail "dev_record.sh append-history"
grep -q "test" "$RD/history.log" 2>/dev/null \
    && log_pass "history.log 内容正确" || log_fail "history.log 内容缺失"

# expand-kernel
bash "$SKILL_DIR/scripts/dev_record.sh" expand-kernel "$RD" "C.0:Kernel入口,C.1:类框架,C.2:CopyIn,C.3:Compute,C.4:CopyOut" 2>/dev/null \
    && log_pass "dev_record.sh expand-kernel" || log_fail "dev_record.sh expand-kernel"
grep -q "4.C.0" "$RD/progress.md" 2>/dev/null \
    && log_pass "expand-kernel 展开正确" || log_fail "expand-kernel 未展开"

# set-progress
bash "$SKILL_DIR/scripts/dev_record.sh" set-progress "$RD" "4.0" "✅" 2>/dev/null \
    && log_pass "dev_record.sh set-progress 4.0" || log_fail "dev_record.sh set-progress 4.0"

# ── 10. stage4_scheduler.sh 冒烟 ──
echo ""
echo "── 10. stage4_scheduler.sh 冒烟测试 ──"
TEST_DIR2=$(mktemp -d)
trap "rm -rf $TEST_DIR2 $TEST_DIR" EXIT
RD2="$TEST_DIR2"
mkdir -p "$RD2"

# 创建 orchestration_plan.json（唯一权威；progress.md 由其派生）
cat > "$RD2/orchestration_plan.json" << 'EOF'
{
  "op_name": "TestOp",
  "programming_model": "A5 Regbase",
  "sub_stages": [
    {"id": "4.0", "desc": "编码前置", "checkpoint_group": "INDEPENDENT", "kind": "check", "deliverables": [], "status": "pending"},
    {"id": "4.A", "desc": "TilingData", "checkpoint_group": "HOST", "kind": "code", "deliverables": ["op_kernel/TestOp_tiling_data.h"], "status": "pending"},
    {"id": "4.B1", "desc": "OpDef", "checkpoint_group": "HOST", "kind": "code", "deliverables": ["op_host/TestOp_def.cpp"], "status": "pending"},
    {"id": "4.B2", "desc": "Tiling", "checkpoint_group": "HOST", "kind": "code", "deliverables": ["op_host/TestOp_tiling.cpp"], "status": "pending"},
    {"id": "4.C.0", "desc": "Kernel入口", "checkpoint_group": "KERNEL", "kind": "code", "deliverables": ["op_kernel/TestOp.cpp"], "status": "pending"},
    {"id": "4.C.1", "desc": "类框架", "checkpoint_group": "KERNEL", "kind": "code", "deliverables": ["op_kernel/TestOp.h"], "status": "pending"},
    {"id": "4.C.2", "desc": "CopyIn", "checkpoint_group": "KERNEL", "kind": "code", "deliverables": ["op_kernel/TestOp.h"], "status": "pending"},
    {"id": "4.C.3", "desc": "Compute", "checkpoint_group": "KERNEL", "kind": "code", "deliverables": ["op_kernel/TestOp.h"], "status": "pending"},
    {"id": "4.C.4", "desc": "CopyOut", "checkpoint_group": "KERNEL", "kind": "code", "deliverables": ["op_kernel/TestOp.h"], "status": "pending"},
    {"id": "4.E", "desc": "CMakeLists", "checkpoint_group": "LAST", "kind": "code", "deliverables": ["CMakeLists.txt"], "status": "pending"},
    {"id": "4.F", "desc": "综合自检", "checkpoint_group": "LAST", "kind": "check", "deliverables": [], "status": "pending"}
  ]
}
EOF

# resolve-sub-stage first_enter
S=$(bash "$SKILL_DIR/scripts/stage4_scheduler.sh" resolve-sub-stage "$RD2" first_enter 2>/dev/null)
[ "$S" = "4.0" ] && log_pass "resolve-sub-stage first_enter → $S" || log_fail "resolve-sub-stage first_enter → $S (expected 4.0)"

# get-group
G=$(bash "$SKILL_DIR/scripts/stage4_scheduler.sh" get-group "$RD2" "4.0" 2>/dev/null)
[ "$G" = "INDEPENDENT" ] && log_pass "get-group 4.0 → $G" || log_fail "get-group 4.0 → $G (expected INDEPENDENT)"

# 4.0 + 4.A 标 done 后 continue → 4.B1
python3 -c "
import json
p='$RD2/orchestration_plan.json'
d=json.load(open(p))
d['sub_stages'][0]['status']='done'
d['sub_stages'][1]['status']='done'
json.dump(d, open(p,'w'), ensure_ascii=False, indent=2)
"
S2=$(bash "$SKILL_DIR/scripts/stage4_scheduler.sh" resolve-sub-stage "$RD2" continue 2>/dev/null)
[ "$S2" = "4.B1" ] && log_pass "resolve-sub-stage continue → $S2" || log_fail "resolve-sub-stage continue → $S2 (expected 4.B1)"

# ── 11. dispatch 命令冒烟 ──
echo ""
echo "── 11. dispatch 命令冒烟 ──"
for status in COMPLETED PARTIAL FAILED ROLLBACK PAUSED; do
    R=$(bash "$SKILL_DIR/scripts/stage4_scheduler.sh" dispatch "$RD2" "$status" 2>/dev/null)
    echo "$R" | python3 -c "import json,sys; d=json.load(sys.stdin); assert 'action' in d" 2>/dev/null \
        && log_pass "dispatch $status → JSON with action" \
        || log_fail "dispatch $status 返回无效 JSON"
done

# ── 12. SKILL.md YAML frontmatter 校验 ──
echo ""
echo "── 12. SKILL.md YAML frontmatter 校验 ──"
python3 -c "
import yaml, sys
with open('$SKILL_DIR/SKILL.md') as f:
    content = f.read()
parts = content.split('---', 2)
if len(parts) < 3:
    print('FAIL: no frontmatter')
    sys.exit(1)
fm = yaml.safe_load(parts[1])
required = ['name', 'description', 'allowed-tools']
for k in required:
    assert k in fm, f'missing key: {k}'
# check AskUserQuestion is allowed
assert 'AskUserQuestion' in fm.get('allowed-tools',''), 'AskUserQuestion not in allowed-tools'
# check TaskCreate/TaskUpdate are allowed
for t in ['TaskCreate','TaskUpdate','TaskList','TaskGet']:
    assert t in fm.get('allowed-tools',''), f'{t} not in allowed-tools'
print('OK')
" 2>&1
[ $? -eq 0 ] && log_pass "SKILL.md YAML frontmatter 合法" || log_fail "SKILL.md YAML frontmatter 校验失败"

# ── 13. meta-schema.json 有效性 ──
echo ""
echo "── 13. meta-schema.json 有效性 ──"
python3 -c "import json; json.load(open('$SKILL_DIR/references/meta-schema.json'))" 2>/dev/null \
    && log_pass "meta-schema.json 合法 JSON" || log_fail "meta-schema.json 非法 JSON"

# ── 14. SKILL.md 引用完整性 ──
echo ""
echo "── 14. SKILL.md 引用文件可达性 ──"
# 提取 SKILL.md 中所有 `references/xxx.md` 引用
refs=$(grep -oP 'references/[a-zA-Z0-9_-]+\.(md|json)' "$SKILL_DIR/SKILL.md" | sort -u)
for ref in $refs; do
    [ -f "$SKILL_DIR/$ref" ] && log_pass "$ref" || log_fail "$ref 缺失"
done

# ── 15. VF 路径解析 ──
echo ""
echo "── 15. VF 指令参考路径解析 ──"
AGENT_VF="$REPO_ROOT/.claude/agents/ascendc-vf-test-agent.md"
# AGENT_ROOT={repo}/.claude/agents/x.md → ../ → .claude/ → plugins/...
VF_INSTR_DIR="$(dirname "$AGENT_VF")/../skills/regbase-vf-test/references/vf-instructions"
[ -d "$VF_INSTR_DIR" ] && log_pass "vf-instructions 目录存在: ${VF_INSTR_DIR#$REPO_ROOT/}" \
    || log_fail "vf-instructions 目录缺失: $VF_INSTR_DIR"

# ── 16. VT 子阶段模式匹配 ──
echo ""
echo "── 16. VT 子阶段模式匹配 ──"
python3 -c "
import re
cases = [
    ('4.C.2.VT.0', True),
    ('4.C.3.VT.1', True),
    ('4.C.0', False),
    ('4.C.2', False),
    ('4.A', False),
    ('C.2.VT.0', True),
]
pattern = r'.*\.VT\.[0-9]+$'
for s, expected in cases:
    m = re.match(pattern, s, re.IGNORECASE)
    ok = (m is not None) == expected
    if not ok:
        print(f'FAIL: {s} → expected={expected}, got={m is not None}')
        sys.exit(1)
print('All VT patterns OK')
" 2>&1
[ $? -eq 0 ] && log_pass "VT 子阶段模式匹配正确" || log_fail "VT 子阶段模式匹配错误"

# ── 17. Agent 适配一致性 ──
echo ""
echo "── 17. Agent 适配一致性 ──"
for agent in ascendc-dev-s2-analysis ascendc-dev-s4-coding ascendc-dev-s5-compile ascendc-vf-test-agent; do
    f="$REPO_ROOT/.claude/agents/${agent}.md"
    # 检查是否使用 $SKILL_ROOT 引用（非相对路径）
    if grep -q '$SKILL_ROOT/references/' "$f" 2>/dev/null; then
        log_pass "$agent 使用 SKILL_ROOT 引用"
    else
        log_fail "$agent 未使用 SKILL_ROOT 引用"
    fi
    # 检查是否有 PATH 设置
    if grep -q 'export PATH.*SKILL_ROOT/scripts' "$f" 2>/dev/null; then
        log_pass "$agent 已设置 PATH"
    else
        log_fail "$agent 缺少 PATH 设置"
    fi
done

# ── 18. RETURN 格式灵活解析 ──
echo ""
echo "── 18. RETURN 格式灵活解析 ──"

# 18.1 SKILL.md RETURN 节内容验证
python3 -c "
with open('$SKILL_DIR/SKILL.md') as f:
    content = f.read()

# 提取 RETURN 行解析节：从 '### RETURN 行解析' 到 '## 调度器速查清单'
import re
start = content.find('### RETURN 行解析')
end = content.find('## 调度器速查清单', start)
section = content[start:end] if end > start else content[start:]

checks = {
    '仅 status 为必填字段': 'status' in section and '必填' in section,
    '方括号可选标记存在': '[,' in section and 'next_stage' in section,
    '字段表有 status 行': '| \`status\` |' in section,
    'next_stage 条件性出现': 'vf-test-agent' in section,
    'error_type 条件性出现': 'COMPLETED' in section and '可能无' in section,
    'agent_name 字段': 'NEEDS_AGENT' in section and 'agent_name' in section,
    '解析规则 1 (status 缺失)': '缺失或无法识别' in section,
    '解析规则 2 (next_stage 缺失)': '沿用当前步骤' in section,
    '解析规则 3 (error_type 缺失)': 'OTH' in section and '默认' in section,
    '解析规则 4 (查调度器)': '调度器速查清单' in section,
    '禁止产物推断': '产物存在性' in section,
}

all_ok = True
for label, ok in checks.items():
    if not ok:
        print(f'  CHECK FAIL: {label}')
        all_ok = False
if all_ok:
    print('  All RETURN section checks passed')
else:
    import sys; sys.exit(1)
" 2>&1
[ $? -eq 0 ] && log_pass "SKILL.md RETURN 节灵活格式声明" || log_fail "SKILL.md RETURN 节格式声明异常"

# 18.2 parse-return 命令冒烟 — 各 SubAgent 典型 RETURN 格式
echo ""
echo "── 18.2 parse-return 多格式兼容性 ──"
TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR $TEST_DIR $TEST_DIR2" EXIT

run_parse_test() {
    local label="$1" return_line="$2" expected_status="$3" expected_next="${4:-}" expected_error="${5:-}" expected_agent="${6:-}"
    local tmpfile="$TMPDIR/return_$$.md"
    echo "blah blah" > "$tmpfile"
    echo "" >> "$tmpfile"
    echo "$return_line" >> "$tmpfile"
    echo "some more text" >> "$tmpfile"

    local json
    json=$(bash "$SKILL_DIR/scripts/dev_record.sh" parse-return "$TMPDIR" "$tmpfile" 2>/dev/null)
    local rc=$?

    if [ "$rc" -ne 0 ]; then
        log_fail "parse-return [$label]: 命令失败 (rc=$rc)"
        return
    fi

    local status
    status=$(echo "$json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null)
    if [ "$status" != "$expected_status" ]; then
        log_fail "parse-return [$label]: status=$status (expected $expected_status)"
        return
    fi

    if [ -n "$expected_next" ]; then
        local next
        next=$(echo "$json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('next_stage',''))" 2>/dev/null)
        if [ "$next" != "$expected_next" ]; then
            log_fail "parse-return [$label]: next_stage=$next (expected $expected_next)"
            return
        fi
    fi

    if [ -n "$expected_error" ]; then
        local err
        err=$(echo "$json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('error_type',''))" 2>/dev/null)
        if [ "$err" != "$expected_error" ]; then
            log_fail "parse-return [$label]: error_type=$err (expected $expected_error)"
            return
        fi
    fi

    if [ -n "$expected_agent" ]; then
        local aname
        aname=$(echo "$json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('agent_name',''))" 2>/dev/null)
        if [ "$aname" != "$expected_agent" ]; then
            log_fail "parse-return [$label]: agent_name=$aname (expected $expected_agent)"
            return
        fi
    fi

    log_pass "parse-return [$label]"
}

# Case 1: s4-coding COMPLETED — status + next_stage, 无 error_type
run_parse_test \
    "s4-coding COMPLETED" \
    "## RETURN: status=COMPLETED, next_stage=4" \
    "COMPLETED" "4" "" ""

# Case 2: s4-coding FAILED — status + next_stage + error_type
run_parse_test \
    "s4-coding FAILED" \
    "## RETURN: status=FAILED, next_stage=4, error_type=CHK" \
    "FAILED" "4" "CHK" ""

# Case 3: vf-test-agent COMPLETED — status + error_type, 无 next_stage
run_parse_test \
    "vf-test-agent COMPLETED" \
    "## RETURN: status=COMPLETED, error_type=VF-PREC" \
    "COMPLETED" "" "VF-PREC" ""

# Case 4: vf-test-agent FAILED — status + error_type, 无 next_stage
run_parse_test \
    "vf-test-agent FAILED" \
    "## RETURN: status=FAILED, error_type=CK" \
    "FAILED" "" "CK" ""

# Case 5: s5-compile COMPLETED — status only (minimal)
run_parse_test \
    "s5-compile minimal" \
    "## RETURN: status=COMPLETED" \
    "COMPLETED" "" "" ""

# Case 6: s5-compile NEEDS_AGENT — status + next_stage + agent_name
run_parse_test \
    "s5-compile NEEDS_AGENT" \
    "## RETURN: status=NEEDS_AGENT, next_stage=5, agent_name=ascendc-tiling-strategy" \
    "NEEDS_AGENT" "5" "" "ascendc-tiling-strategy"

# Case 7: s2-analysis COMPLETED — status + next_stage, 无 error_type
run_parse_test \
    "s2-analysis COMPLETED" \
    "## RETURN: status=COMPLETED, next_stage=4" \
    "COMPLETED" "4" "" ""

# Case 8: PAUSED — status + next_stage
run_parse_test \
    "PAUSED" \
    "## RETURN: status=PAUSED, next_stage=4" \
    "PAUSED" "4" "" ""

# Case 9: 带多余空白和中文说明的 RETURN 行
run_parse_test \
    "带空格和中文" \
    "## RETURN: status=FAILED, next_stage=4, error_type=INP   (设计文件缺失)" \
    "FAILED" "4" "INP" ""

# 18.3 parse-return — status 缺失：命令成功但 status 字段为空 (CTX_DRIFT 触发条件)
echo ""
echo "── 18.3 parse-return status 缺失检测 ──"
NO_STATUS_FILE="$TMPDIR/return_no_status.md"
echo "## RETURN: next_stage=4, error_type=CHK" > "$NO_STATUS_FILE"
JSON=$(bash "$SKILL_DIR/scripts/dev_record.sh" parse-return "$TMPDIR" "$NO_STATUS_FILE" 2>/dev/null)
RC=$?
NO_STATUS=$(echo "$JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status','MISSING'))" 2>/dev/null)
if [ "$RC" -eq 0 ] && { [ "$NO_STATUS" = "" ] || [ "$NO_STATUS" = "MISSING" ]; }; then
    log_pass "parse-return 缺 status → status 为空 (编排器据此触发 CTX_DRIFT)"
else
    log_fail "parse-return 缺 status → rc=$RC, status=$NO_STATUS (expected empty)"
fi

# 18.4 parse-return — 完全无 RETURN 行应失败
echo ""
echo "── 18.4 parse-return 无 RETURN 行检测 ──"
NO_RETURN_FILE="$TMPDIR/return_missing.md"
echo "some text without return line" > "$NO_RETURN_FILE"
echo "more text" >> "$NO_RETURN_FILE"
if bash "$SKILL_DIR/scripts/dev_record.sh" parse-return "$TMPDIR" "$NO_RETURN_FILE" 2>/dev/null; then
    log_fail "parse-return 无 RETURN 行应返回非 0"
else
    log_pass "parse-return 无 RETURN 行 → 非 0 (CTX_DRIFT)"
fi

# 18.5 parse-return — 未知 status 值仍应成功解析 (编排器自行判断)
echo ""
echo "── 18.5 parse-return 未知 status 值 ──"
UNKNOWN_STATUS_FILE="$TMPDIR/return_unknown.md"
echo "## RETURN: status=UNKNOWN_STATUS, next_stage=3" > "$UNKNOWN_STATUS_FILE"
JSON=$(bash "$SKILL_DIR/scripts/dev_record.sh" parse-return "$TMPDIR" "$UNKNOWN_STATUS_FILE" 2>/dev/null)
RC=$?
S=$(echo "$JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)
if [ "$RC" -eq 0 ] && [ "$S" = "UNKNOWN_STATUS" ]; then
    log_pass "parse-return 未知 status → 成功解析 (编排器自行判断)"
else
    log_fail "parse-return 未知 status → rc=$RC, status=$S"
fi

# ── 19. NEEDS_AGENT 处理验证 ──
echo ""
echo "── 19. NEEDS_AGENT 处理验证 ──"

# 19.1 SKILL.md 调度器速查清单含 NEEDS_AGENT
python3 -c "
with open('$SKILL_DIR/SKILL.md') as f:
    content = f.read()

# 提取调度器速查清单
start = content.find('## 调度器速查清单')
end = content.find('## 执行流程', start)
dispatch_section = content[start:end] if end > start else content[start:]

checks = {
    'NEEDS_AGENT 行存在': 'NEEDS_AGENT' in dispatch_section,
    'agent_name 提取': 'agent_name' in dispatch_section,
    'resume_point 可选': 'resume_point' in dispatch_section,
    'history.log 记录': 'history.log' in dispatch_section or 'append-history' in dispatch_section,
    '启动目标 Agent': '启动目标 Agent' in dispatch_section,
    '目标 COMPLETED 处理': 'COMPLETED' in dispatch_section and '重调' in dispatch_section,
}

all_ok = True
for label, ok in checks.items():
    if not ok:
        print(f'  CHECK FAIL: {label}')
        all_ok = False
if all_ok:
    print('  调度器速查清单 NEEDS_AGENT 声明完整')
else:
    import sys; sys.exit(1)
" 2>&1
[ $? -eq 0 ] && log_pass "调度器速查清单含 NEEDS_AGENT" || log_fail "调度器速查清单 NEEDS_AGENT 声明不完整"

# 19.2 Step 3.2 含 NEEDS_AGENT 处理分支
python3 -c "
with open('$SKILL_DIR/SKILL.md') as f:
    content = f.read()

# 提取 Step 3.2 区域
start = content.find('**3.2 派 s5-compile**')
end = content.find('**3.3 收尾检查**', start)
step32 = content[start:end] if end > start else content[start:start+1500]

checks = {
    'NEEDS_AGENT 分支存在': 'NEEDS_AGENT' in step32,
    'ascendc-tiling-strategy 引用': 'tiling-strategy' in step32,
    'append-history 记录': 'append-history' in step32,
    '重调 s5-compile': '重调 s5-compile' in step32,
    'agent_completed 注入': 'agent_completed' in step32,
    '目标 FAILED → PAUSED': 'PAUSED' in step32,
}

all_ok = True
for label, ok in checks.items():
    if not ok:
        print(f'  CHECK FAIL: {label}')
        all_ok = False
if all_ok:
    print('  Step 3.2 NEEDS_AGENT 处理分支完整')
else:
    import sys; sys.exit(1)
" 2>&1
[ $? -eq 0 ] && log_pass "Step 3.2 含 NEEDS_AGENT 处理" || log_fail "Step 3.2 NEEDS_AGENT 处理不完整"

# 19.3 parse-return — NEEDS_AGENT 完整字段（含 resume_point）
run_parse_test \
    "NEEDS_AGENT with resume_point" \
    "## RETURN: status=NEEDS_AGENT, next_stage=5, agent_name=ascendc-tiling-strategy, resume_point=5.3.2-recompile" \
    "NEEDS_AGENT" "5" "" "ascendc-tiling-strategy"

# Verify resume_point was also captured
TMPFILE="$TMPDIR/return_needs_agent_resume.md"
echo "## RETURN: status=NEEDS_AGENT, next_stage=5, agent_name=ascendc-tiling-strategy, resume_point=5.3.2-recompile" > "$TMPFILE"
NEEDS_JSON=$(bash "$SKILL_DIR/scripts/dev_record.sh" parse-return "$TMPDIR" "$TMPFILE" 2>/dev/null)
RESUME_PT=$(echo "$NEEDS_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('resume_point',''))" 2>/dev/null)
if [ "$RESUME_PT" = "5.3.2-recompile" ]; then
    log_pass "parse-return NEEDS_AGENT resume_point 正确提取"
else
    log_fail "parse-return NEEDS_AGENT resume_point=$RESUME_PT (expected 5.3.2-recompile)"
fi

# 19.4 parse-return — NEEDS_AGENT 缺 agent_name（编排器应检测并报错）
NO_AGENT_FILE="$TMPDIR/return_needs_no_agent.md"
echo "## RETURN: status=NEEDS_AGENT, next_stage=5" > "$NO_AGENT_FILE"
NO_AGENT_JSON=$(bash "$SKILL_DIR/scripts/dev_record.sh" parse-return "$TMPDIR" "$NO_AGENT_FILE" 2>/dev/null)
NO_AGENT_NAME=$(echo "$NO_AGENT_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('agent_name','MISSING'))" 2>/dev/null)
if [ "$NO_AGENT_NAME" = "" ] || [ "$NO_AGENT_NAME" = "MISSING" ]; then
    log_pass "parse-return NEEDS_AGENT 缺 agent_name → 为空 (编排器据此报错)"
else
    log_fail "parse-return NEEDS_AGENT 缺 agent_name → agent_name=$NO_AGENT_NAME (expected empty)"
fi

# ── 20. PENDING_CHOICE 防御性兜底 ──
echo ""
echo "── 20. PENDING_CHOICE 防御性兜底 ──"

# 20.1 SKILL.md 调度器速查清单含 PENDING_CHOICE 防御性兜底
python3 -c "
with open('$SKILL_DIR/SKILL.md') as f:
    content = f.read()
start = content.find('## 调度器速查清单')
end = content.find('## 执行流程', start)
dispatch_section = content[start:end] if end > start else content[start:]

checks = {
    'PENDING_CHOICE 行存在': 'PENDING_CHOICE' in dispatch_section,
    '防御性兜底': '防御性兜底' in dispatch_section or '未预期' in dispatch_section,
    '升级为 PAUSED': 'PAUSED' in dispatch_section.split('PENDING_CHOICE')[1].split('NEEDS_AGENT')[0] if 'PENDING_CHOICE' in dispatch_section and 'NEEDS_AGENT' in dispatch_section else False,
    'append-history 记录': 'append-history' in dispatch_section.split('PENDING_CHOICE')[1].split('NEEDS_AGENT')[0] if 'PENDING_CHOICE' in dispatch_section and 'NEEDS_AGENT' in dispatch_section else False,
    '零交互约束提及': '零交互' in dispatch_section or '全链路' in dispatch_section,
}

all_ok = True
for label, ok in checks.items():
    if not ok:
        print(f'  CHECK FAIL: {label}')
        all_ok = False
if all_ok:
    print('  调度器速查清单 PENDING_CHOICE 防御性兜底声明完整')
else:
    import sys; sys.exit(1)
" 2>&1
[ $? -eq 0 ] && log_pass "调度器速查清单含 PENDING_CHOICE 防御性兜底" || log_fail "调度器速查清单 PENDING_CHOICE 声明不完整"

# 20.2 parse-return — PENDING_CHOICE 格式兼容
run_parse_test \
    "PENDING_CHOICE" \
    "## RETURN: status=PENDING_CHOICE, next_stage=3" \
    "PENDING_CHOICE" "3" "" ""

# 20.3 parse-return — PENDING_CHOICE with questions_file/batches_file (ascendc-dev 格式)
run_parse_test \
    "PENDING_CHOICE with question refs" \
    "## RETURN: status=PENDING_CHOICE, next_stage=3, questions_file=questions.json, batches_file=batches.json" \
    "PENDING_CHOICE" "3" "" ""

# ── 21. VF prompt 字段完整性 ──
echo ""
echo "── 21. VF prompt 字段完整性 ──"

# 21.1 phase-c-prompts.md VF 模板含必要字段且不含 previous_error
python3 -c "
with open('$SKILL_DIR/references/phase-c-prompts.md') as f:
    content = f.read()

# 提取 VF 模板区域：从 '## C.3 ascendc-vf-test-agent' 标题到文件末尾（最后一段）
start = content.find('## C.3 ascendc-vf-test-agent')
# C.3 编号重复，确认定位到含 '仅 A5 Regbase' 的正确标题
if '仅 A5 Regbase' not in content[start:start+80]:
    # 可能匹配到 s4-coding 的 C.3，找下一个
    start = content.find('## C.3 ascendc-vf-test-agent', start + 40)
vf_section = content[start:] if start >= 0 else ''

checks = {
    'previous_error 已移除': 'previous_error' not in vf_section,
    'previous_vf_results 字段存在': 'previous_vf_results' in vf_section,
    'output_dir 字段存在': 'output_dir' in vf_section,
    'current_sub_stage 字段存在': 'current_sub_stage' in vf_section,
    '零交互约束存在': '零交互约束' in vf_section or '禁止 AskUserQuestion' in vf_section,
}

all_ok = True
for label, ok in checks.items():
    if not ok:
        print(f'  CHECK FAIL: {label}')
        all_ok = False
if all_ok:
    print('  VF 模板字段完整（无 previous_error）')
else:
    import sys; sys.exit(1)
" 2>&1
[ $? -eq 0 ] && log_pass "phase-c-prompts.md VF 模板字段完整" || log_fail "phase-c-prompts.md VF 模板字段缺失"

# 21.2 SKILL.md VF prompt 注入摘要含必要字段且不含 previous_error
python3 -c "
with open('$SKILL_DIR/SKILL.md') as f:
    content = f.read()

# 找 VF prompt 额外注入那一行
import re
m = re.search(r'VF prompt 额外注入.*', content)
if not m:
    print('  CHECK FAIL: 未找到 VF prompt 额外注入行')
    import sys; sys.exit(1)

line = m.group(0)
checks = {
    'output_dir 提及': 'output_dir' in line,
    'previous_vf_results 提及': 'previous_vf_results' in line,
    'previous_error 已移除': 'previous_error' not in line,
}

all_ok = True
for label, ok in checks.items():
    if not ok:
        print(f'  CHECK FAIL: {label} → line={line.strip()}')
        all_ok = False
if all_ok:
    print(f'  SKILL.md VF 注入摘要完整: {line.strip()}')
else:
    import sys; sys.exit(1)
" 2>&1
[ $? -eq 0 ] && log_pass "SKILL.md VF prompt 注入摘要完整" || log_fail "SKILL.md VF prompt 注入摘要不完整"

# ── 22. AGENT_ROOT 去硬编码 ──
echo ""
echo "── 22. AGENT_ROOT 去硬编码 ──"

# 22.1 get_repo_root.sh 可执行且存在
[ -x "$SKILL_DIR/scripts/get_repo_root.sh" ] \
    && log_pass "get_repo_root.sh 存在且可执行" \
    || log_fail "get_repo_root.sh 缺失或不可执行"

# 22.2 get_repo_root.sh 从 SKILL_DIR 正确推到 repo 根
REPO_FOUND=$(bash "$SKILL_DIR/scripts/get_repo_root.sh" "$SKILL_DIR" 2>/dev/null)
if [ -n "$REPO_FOUND" ] && [ -d "$REPO_FOUND/.claude" ] && [ -f "$REPO_FOUND/CLAUDE.md" ]; then
    log_pass "get_repo_root → $REPO_FOUND (与 REPO_ROOT=$REPO_ROOT 一致)"
else
    log_fail "get_repo_root 返回异常: $REPO_FOUND"
fi

# 22.3 SKILL.md 已移除硬编码上溯
python3 -c "
with open('$SKILL_DIR/SKILL.md') as f:
    content = f.read()
if '上溯 5 级' in content or '../../../../..' in content:
    print('FAIL: 仍含硬编码上溯')
    import sys; sys.exit(1)
if 'get_repo_root.sh' not in content:
    print('FAIL: 未引用 get_repo_root.sh')
    import sys; sys.exit(1)
print('SKILL.md AGENT_ROOT 构造已改为 get_repo_root.sh')
" 2>&1
[ $? -eq 0 ] && log_pass "SKILL.md AGENT_ROOT 已去硬编码" || log_fail "SKILL.md AGENT_ROOT 仍含硬编码"

# 22.4 get_repo_root.sh 无 git 场景兜底（临时模拟：unset git 后走 CLAUDE.md 上溯）
GIT_SAVED=$(command -v git 2>/dev/null || echo "")
# 在临时目录创建 fake repo 结构测试上溯逻辑
FAKE_REPO="$TMPDIR/fake_repo/sub/deep"
mkdir -p "$FAKE_REPO"
touch "$FAKE_REPO/../../../CLAUDE.md"  # repo 根标识在 fake_repo 上级
ROOT_BY_CLAUDE=$(bash "$SKILL_DIR/scripts/get_repo_root.sh" "$FAKE_REPO" 2>/dev/null || echo "")
# 清理
rm -rf "$TMPDIR/fake_repo"
if [ -n "$ROOT_BY_CLAUDE" ] && [ -f "$ROOT_BY_CLAUDE/CLAUDE.md" ]; then
    log_pass "get_repo_root 上溯 CLAUDE.md 兜底正常 → $ROOT_BY_CLAUDE"
else
    log_fail "get_repo_root 上溯 CLAUDE.md 失败 → '$ROOT_BY_CLAUDE'"
fi

# 22.5 get_repo_root.sh --inject 外部注入（有效路径）
INJECTED=$(bash "$SKILL_DIR/scripts/get_repo_root.sh" --inject "$REPO_ROOT" "$SKILL_DIR" 2>/dev/null)
if [ "$INJECTED" = "$REPO_ROOT" ]; then
    log_pass "get_repo_root --inject 有效路径 → 直接使用注入值"
else
    log_fail "get_repo_root --inject 有效路径 → $INJECTED (expected $REPO_ROOT)"
fi

# 22.6 get_repo_root.sh --inject 无效路径 → 回退自动发现
INJECTED_BAD=$(bash "$SKILL_DIR/scripts/get_repo_root.sh" --inject "/nonexistent/path" "$SKILL_DIR" 2>/dev/null)
if [ "$INJECTED_BAD" = "$REPO_ROOT" ]; then
    log_pass "get_repo_root --inject 无效路径 → 回退自动发现成功"
else
    log_fail "get_repo_root --inject 无效路径 → $INJECTED_BAD (expected fallback to $REPO_ROOT)"
fi

# 22.7 SKILL.md 输入变量表含 REPO_ROOT（可选注入）
python3 -c "
with open('$SKILL_DIR/SKILL.md') as f:
    content = f.read()
# 提取输入表
start = content.find('## 输入')
end = content.find('## SKILL_ROOT', start)
input_section = content[start:end] if end > start else ''

checks = {
    'REPO_ROOT 字段存在': 'REPO_ROOT' in input_section,
    '标记为可选（否）': '否' in input_section.split('REPO_ROOT')[0][-50:] + input_section.split('REPO_ROOT')[1][:50] if 'REPO_ROOT' in input_section else False,
    'get_repo_root.sh 自动发现提及': 'get_repo_root.sh' in input_section,
}

all_ok = True
for label, ok in checks.items():
    if not ok:
        print(f'  CHECK FAIL: {label}')
        all_ok = False
if all_ok:
    print('  输入变量表 REPO_ROOT 注入声明完整')
else:
    import sys; sys.exit(1)
" 2>&1
[ $? -eq 0 ] && log_pass "SKILL.md 输入变量表含 REPO_ROOT 注入" || log_fail "SKILL.md 输入变量表 REPO_ROOT 声明不完整"

# 22.8 SKILL.md AGENT_ROOT 节含注入优先级
python3 -c "
with open('$SKILL_DIR/SKILL.md') as f:
    content = f.read()
start = content.find('### AGENT_ROOT 构造')
end = content.find('## Agent 调度协议', start)
ag_section = content[start:end] if end > start else ''

checks = {
    '上游注入 REPO_ROOT 优先': 'REPO_ROOT' in ag_section and ('注入' in ag_section or '优先' in ag_section),
    'get_repo_root.sh 自动发现兜底': 'get_repo_root.sh' in ag_section,
    '都失败则 PAUSED': 'PAUSED' in ag_section,
}

all_ok = True
for label, ok in checks.items():
    if not ok:
        print(f'  CHECK FAIL: {label}')
        all_ok = False
if all_ok:
    print('  AGENT_ROOT 构造注入优先级声明完整')
else:
    import sys; sys.exit(1)
" 2>&1
[ $? -eq 0 ] && log_pass "SKILL.md AGENT_ROOT 含注入优先级" || log_fail "SKILL.md AGENT_ROOT 注入声明不完整"

# ── 22. diff-analysis 守护: phase-c-prompts.md fast_start 协议已移除 ──
echo ""
echo "── 22. diff-analysis fast_start 已移除校验 ──"

# 22.1 phase-c-prompts.md 不得含 【fast_start】字段（门控收敛到 Python 编排层）
if grep -q "【fast_start】" "$SKILL_DIR/references/phase-c-prompts.md"; then
    log_fail "phase-c-prompts.md 残留 【fast_start】字段（协议已移除，门控收敛到 Python 编排层）"
else
    log_pass "phase-c-prompts.md 无 fast_start 字段"
fi

# 22.2 SKILL.md 不得引用 fast_start 协议
if grep -q "fast_start" "$SKILL_DIR/SKILL.md"; then
    log_fail "SKILL.md 残留 fast_start 引用（协议已移除）"
else
    log_pass "SKILL.md 无 fast_start 引用"
fi

# ── 23. diff-analysis 守护: phase-c-prompts.md 字段完整性 ──
echo ""
echo "── 23. diff-analysis 字段完整性 ──"

# 23.1 C.2 must have 【已在主 SKILL 收集的项】 with design_doc + vf_ref_dir (guard #19)
C2_COLLECTED=$(sed -n '/## C.2 ascendc-dev-s2-analysis/,/## C.3 循环机制/p' \
    "$SKILL_DIR/references/phase-c-prompts.md")
echo "$C2_COLLECTED" | grep -q "design_doc: {DESIGN_DOC}" \
    && log_pass "#19 C.2 design_doc" \
    || log_fail "#19 C.2 missing design_doc placeholder"
echo "$C2_COLLECTED" | grep -q "vf_ref_dir: {VF_REF_DIR}" \
    && log_pass "#19 C.2 vf_ref_dir" \
    || log_fail "#19 C.2 missing vf_ref_dir placeholder"

# 23.2 C.3 S4 must have design_doc + ref_op (guard #21)
C3S4_COLLECTED=$(sed -n '/## C.3 ascendc-dev-s4-coding/,/## C.3 ascendc-vf-test-agent/p' \
    "$SKILL_DIR/references/phase-c-prompts.md")
echo "$C3S4_COLLECTED" | grep -q "design_doc: {DESIGN_DOC}" \
    && log_pass "#21 C.3 S4 design_doc" \
    || log_fail "#21 C.3 S4 missing design_doc placeholder"
echo "$C3S4_COLLECTED" | grep -q "ref_op: {REF_OP}" \
    && log_pass "#21 C.3 S4 ref_op" \
    || log_fail "#21 C.3 S4 missing ref_op placeholder"

# 23.3 C.3 VF must have design_doc + ref_op + vf_ref_dir (guard #20)
C3VF_COLLECTED=$(sed -n '/## C.3 ascendc-vf-test-agent.*仅 A5 Regbase/,/## C.4 ascendc-dev-s5-compile/p' \
    "$SKILL_DIR/references/phase-c-prompts.md")
echo "$C3VF_COLLECTED" | grep -q "design_doc: {DESIGN_DOC}" \
    && log_pass "#20 C.3 VF design_doc" \
    || log_fail "#20 C.3 VF missing design_doc placeholder"
echo "$C3VF_COLLECTED" | grep -q "ref_op: {REF_OP}" \
    && log_pass "#20 C.3 VF ref_op" \
    || log_fail "#20 C.3 VF missing ref_op placeholder"
echo "$C3VF_COLLECTED" | grep -q "vf_ref_dir: {VF_REF_DIR}" \
    && log_pass "#20 C.3 VF vf_ref_dir" \
    || log_fail "#20 C.3 VF missing vf_ref_dir placeholder"

# ── 24. diff-analysis 守护: orchestrator-logic.md 无 ascendc-dev 残留 (#10) ──
echo ""
echo "── 24. orchestrator-logic.md ascendc-dev 残留检测 ──"

# 排除 §3 "不适用" 声明行后检查
CLEANED=$(grep -v "不存在 Stage 3" "$SKILL_DIR/references/orchestrator-logic.md" \
    | grep -v "不适用")

echo "$CLEANED" | grep -q "Stage 3 快速通道" \
    && log_fail "#10 'Stage 3 快速通道' 残留" \
    || log_pass "#10 无 Stage 3 快速通道"

echo "$CLEANED" | grep -q "todo-7" \
    && log_fail "#10 'todo-7' 残留" \
    || log_pass "#10 无 todo-7"

echo "$CLEANED" | grep -q "todo-8\|todo-9\|todo-10\|todo-11" \
    && log_fail "#10 ascendc-dev todo 编号残留" \
    || log_pass "#10 无 ascendc-dev todo 编号"

# ── 25. diff-analysis 守护: SKILL.md Step 1.1 vf_test retries (#11) ──
echo ""
echo "── 25. SKILL.md Step 1.1 vf_test retries ──"
grep -q "'vf_test':" "$SKILL_DIR/SKILL.md" \
    && log_pass "#11 vf_test retries 存在" \
    || log_fail "#11 vf_test retries 缺失"

grep -q "'used': 0, 'limit': 4" "$SKILL_DIR/SKILL.md" \
    && log_pass "#11 vf_test used=0, limit=4" \
    || log_fail "#11 vf_test counter 格式异常"

# ── 26. diff-analysis 守护: SKILL.md Step 1.2 orchestration_plan.json 验证 ──
echo ""
echo "── 26. SKILL.md Step 1.2 orchestration_plan.json 验证 ──"
grep -q 'orchestration_plan.json 缺失或为空' "$SKILL_DIR/SKILL.md" \
    && log_pass "#12 orchestration_plan.json 产出验证" \
    || log_fail "#12 orchestration_plan.json 验证缺失"

# ── 27. diff-analysis 守护: SKILL.md Step 1.2 set-meta current_stage 2 (#13) ──
echo ""
echo "── 27. SKILL.md Step 1.2 current_stage 更新 ──"
grep -q "set-meta.*current_stage 2" "$SKILL_DIR/SKILL.md" \
    && log_pass "#13 current_stage 更新" \
    || log_fail "#13 current_stage 更新缺失"

# ── 28. diff-analysis 守护: C.2 next_stage=4 约束 (#17) ──
echo ""
echo "── 28. C.2 next_stage=4 约束 ──"
C2_NEXT=$(sed -n '/## C.2 ascendc-dev-s2-analysis/,/## C.3 循环机制/p' \
    "$SKILL_DIR/references/phase-c-prompts.md")
echo "$C2_NEXT" | grep -q "next_stage=4" \
    && log_pass "#17 next_stage=4 存在" \
    || log_fail "#17 next_stage=4 缺失"
echo "$C2_NEXT" | grep -q "禁止返回.*next_stage.*3" \
    && log_pass "#17 禁止 next_stage=3" \
    || log_fail "#17 禁止 next_stage=3 缺失"

# ── 29. diff-analysis 守护: progress.md 骨架无 Stage 1/3 行 (#16) ──
echo ""
echo "── 29. progress.md 骨架无 Stage 1/3 行 ──"
# Extract the heredoc from SKILL.md Step 1.1
PROGRESS_SKEL=$(sed -n "/cat >.*progress.md.*<< 'EOF'/,/^EOF$/p" "$SKILL_DIR/SKILL.md")
echo "$PROGRESS_SKEL" | grep -q "| 1 " \
    && log_fail "#16 progress.md 骨架含 Stage 1 行" \
    || log_pass "#16 无 Stage 1 行"
echo "$PROGRESS_SKEL" | grep -q "| 3 " \
    && log_fail "#16 progress.md 骨架含 Stage 3 行" \
    || log_pass "#16 无 Stage 3 行"

# ── 结果 ──
echo ""
echo "============================================"
echo " 结果: $PASS 通过, $FAIL 失败"
echo "============================================"
[ "$FAIL" -eq 0 ] && echo "✅ 全部通过" || echo "❌ 存在失败项"
exit $FAIL
