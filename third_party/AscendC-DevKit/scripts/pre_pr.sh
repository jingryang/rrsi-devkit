#!/usr/bin/env bash
# ============================================================================
# scripts/pre_pr.sh — AscendC-DevKit 提 PR 前自检门（两段式）
#
# 把「提 PR 前自检」规则化成一条命令。两段：
#   ① pytest -m "not heavy_llm"                 硬门（零 token；pre-push hook 复用同一条）
#      └─ 不过 → 直接退出 1，不浪费 token 跑 skill
#   ② ascendc-devkit skill run ascendc-devkit-code-reviewer   全面 review
#      双后端：ASCENDC_AGENT_BACKEND=opencode(默认)|claude
#      skill 内部已跑 UT + 非 heavy_llm ST，并产出 reviews/PR-*-review.{md,json}
#   ③ parse 本次产出的 reviews/*-review.json 的 verdict → approve* 退出 0，否则 1
#
# 为什么是两段、且 skill 走 DevKit 的 `skill run`：
#   - 测试是二元 pass/fail，作硬门；skill 是 Advisory（给结论不阻断）。两层职责不同。
#   - skill 经 DevKit 的 skill run，双后端 + skill 方法论注入由 DevKit 在 backend
#     边界统一解决（claude 加 /<skill>、opencode 加 system steer —— opencode 不展开
#     slash）。脚本只做薄编排，绝不在 bash 里重造后端编排（§2.5 唯一通路）。
#   - heavy_llm 不在默认范围（§3.11）；如需跑由人决策后单独执行，本脚本不自动纳入。
#
# 用法:
#   scripts/pre_pr.sh [<分支>]                       # 分支默认=当前分支
#   PRE_PR_QUICK=1 scripts/pre_pr.sh                 # ①用 --quick（排除 llm/npu/cann，秒级、无环境依赖）
#   PRE_PR_SKIP_PYTEST=1 scripts/pre_pr.sh [<分支>]  # 跳过①（应急）
#   PRE_PR_SKIP_SKILL=1  scripts/pre_pr.sh           # 跳过②（LLM 不可达时）
#   ASCENDC_AGENT_BACKEND=claude scripts/pre_pr.sh   # 强制 claude 后端（默认 opencode）
# ============================================================================
set -uo pipefail

# —— 颜色（非 tty 自动关闭，CI 友好）———————————————————————————————————
if [[ -t 1 ]]; then
  C_RED=$'\033[0;31m'; C_GRN=$'\033[0;32m'; C_YEL=$'\033[1;33m'; C_DIM=$'\033[2m'; C_N=$'\033[0m'
else
  C_RED=""; C_GRN=""; C_YEL=""; C_DIM=""; C_N=""
fi
say()  { printf '%s\n' "$*"; }
ok()   { say "  ${C_GRN}✓${C_N} $*"; }
bad()  { say "  ${C_RED}✗${C_N} $*"; }
sec()  { say ""; say "${C_YEL}── $* ──${C_N}"; }

# —— 定位仓根（脚本可能在子目录被调用）————————————————————————————————
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  bad "不在 git 仓库内"; exit 2; }
cd "$REPO_ROOT"

BRANCH="${1:-$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")}"
[[ -z "$BRANCH" || "$BRANCH" == "HEAD" ]] && {
  bad "无法确定分支（detached HEAD？）请显式传：scripts/pre_pr.sh <分支名>"; exit 2; }

BACKEND="${ASCENDC_AGENT_BACKEND:-opencode}"

say "${C_YEL}═══ AscendC-DevKit pre-PR 自检 ═══${C_N}"
say "分支: ${C_DIM}${BRANCH}${C_N}   后端: ${C_DIM}${BACKEND}${C_N}（ASCENDC_AGENT_BACKEND）"
say "  选项: QUICK=${PRE_PR_QUICK:-0} SKIP_PYTEST=${PRE_PR_SKIP_PYTEST:-0} SKIP_SKILL=${PRE_PR_SKIP_SKILL:-0}"

EXIT_CODE=0

# —— ① pytest 硬门 ————————————————————————————————————————————————————————
if [[ "${PRE_PR_SKIP_PYTEST:-0}" == "1" ]]; then
  sec "① pytest 硬门（已跳过 PRE_PR_SKIP_PYTEST=1）"
  ok "跳过"
else
  sec "① pytest 硬门"
  if [[ "${PRE_PR_QUICK:-0}" == "1" ]]; then
    PYTEST_ARGS=(python -m pytest --quick)
    say "  ${C_DIM}范围: --quick（排除 llm/npu/cann，秒级、无环境依赖）${C_N}"
  else
    # 默认范围 = 全量 - heavy_llm（§3.6/§3.11）。conftest 会对 LLM/NPU/CANN 做预检，
    # 缺失时诚实报错（§3.7）；本脚本不绕过、不打桩。cann-bench parity 用例由 conftest
    # 启动时自动解析 + 挂 <cann-bench>/src 进 sys.path（tests/conftest.py
    # _mount_cannbench_src）→ 兄弟目录/配置里有 cann-bench 就默认真跑，无需手动 PYTHONPATH。
    PYTEST_ARGS=(python -m pytest -m "not heavy_llm")
    say "  ${C_DIM}范围: -m \"not heavy_llm\"（UT 全量 + 非 heavy_llm ST，需真实环境；cann-bench parity 自动挂载）${C_N}"
  fi
  if "${PYTEST_ARGS[@]}"; then
    ok "① pytest 通过"
  else
    rc=$?
    bad "① pytest 失败（exit=${rc}）—— 修到全绿再提 PR（§3.4 禁止 skip/except 掩盖）"
    EXIT_CODE=1
  fi
fi

# pytest 没过就没必要烧 token 跑 skill。
if [[ $EXIT_CODE -ne 0 ]]; then
  sec "结果"
  bad "自检未通过（① pytest 硬门失败），跳过 ② skill review"
  exit 1
fi

# —— ② review skill ——————————————————————————————————————————————————————
if [[ "${PRE_PR_SKIP_SKILL:-0}" == "1" ]]; then
  sec "② review skill（已跳过 PRE_PR_SKIP_SKILL=1）"
  ok "跳过"
  sec "结果"
  ok "自检通过（仅 pytest 硬门；skill review 已跳过）"
  exit 0
fi

if ! command -v ascendc-devkit >/dev/null 2>&1; then
  bad "未找到 ascendc-devkit CLI（pip install -e . 安装本仓后重试）"
  exit 2
fi

sec "② review skill（ascendc-devkit-code-reviewer via skill run）"
say "  ${C_DIM}后端=${BACKEND}；skill 内部会跑 UT+非 heavy_llm ST 并产出 reviews/PR-*-review.{md,json}${C_N}"

# 记录跑 skill 前的时刻，用于定位「本次产出」的 review json（同名文件可能被覆盖）。
SKILL_START=$(date +%s)

ASCENDC_AGENT_BACKEND="$BACKEND" \
  ascendc-devkit skill run \
    --name ascendc-devkit-code-reviewer \
    --prompt "review 本地分支 ${BRANCH}" \
    --output-root output \
  && SKILL_RC=0 || SKILL_RC=$?

# —— ③ 定位本次产出的 review json + parse verdict ———————————————————————
sec "③ verdict"
# 找 mtime >= SKILL_START 的最新 review json（本次产出）；找不到则回退到全局最新。
LATEST=""
while IFS= read -r f; do
  mt=$(stat -c %Y "$f" 2>/dev/null || echo 0)
  if (( mt >= SKILL_START )); then LATEST="$f"; break; fi
done < <(ls -1t reviews/*-review.json 2>/dev/null)
[[ -z "$LATEST" ]] && LATEST=$(ls -1t reviews/*-review.json 2>/dev/null | head -1)

if [[ -z "$LATEST" ]]; then
  bad "未找到 reviews/*-review.json（skill 可能未完成产出）；skill run exit=${SKILL_RC}"
  exit 1
fi
say "  ${C_DIM}报告: ${LATEST}${C_N}"

VERDICT=$(ASCENDC_DEVKIT_PRE_PR=1 python - "$LATEST" <<'PY' || echo "__PARSE_FAIL__"
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception as e:
    sys.stderr.write(f"verdict 解析失败: {e}\n"); sys.exit(2)
print(str(d.get("verdict", "")).strip() or "__NO_VERDICT__")
PY
)

case "$VERDICT" in
  approve|approve_with_minor)
    ok "③ verdict=${VERDICT} —— 自检通过，可提 PR（minor 可选改）"
    ;;
  request_changes|reject)
    bad "③ verdict=${VERDICT} —— review 建议修改，请看 ${LATEST%.json}.md 的 findings 后再提"
    EXIT_CODE=1
    ;;
  *)
    bad "③ verdict 未知（${VERDICT}），skill run exit=${SKILL_RC}；请人工查看 ${LATEST%.json}.md"
    EXIT_CODE=1
    ;;
esac

# —— 汇总 ————————————————————————————————————————————————————————————————
sec "结果"
if [[ $EXIT_CODE -eq 0 ]]; then
  say "${C_GRN}═══ 全部通过，可提 PR ═══${C_N}"
else
  say "${C_RED}═══ 自检未通过，请按上面 ✗ 修改 ═══${C_N}"
fi
exit $EXIT_CODE
