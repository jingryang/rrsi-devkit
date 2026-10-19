#!/usr/bin/env bash
# ============================================================================
# scripts/install_hooks.sh — 一次性安装 git pre-push hook（快速 pytest 硬门）
#
# 安装后，每次 `git push` 前自动跑 pytest --quick（零 token、秒级、无 NPU/LLM
# 依赖）。失败则阻断 push；临时跳过: PRE_PUSH_SKIP=1 git push。
# 这只是「快速兜底」——push 不会跑 review skill（那需要 LLM+分钟级），完整自检
# 请开发者在提 PR 前手动跑: scripts/pre_pr.sh <分支>。
#
# 升级 pre_pr.sh 后无需重装（hook 只是一行调用 scripts/pre_pr.sh）。
# 卸载: rm .git/hooks/pre-push
# ============================================================================
set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "不在 git 仓库内" >&2; exit 2; }
HOOK="$REPO_ROOT/.git/hooks/pre-push"

if [[ -f "$HOOK" ]] && ! grep -q "AscendC-DevKit pre-push" "$HOOK" 2>/dev/null; then
  echo "已存在非本脚本管理的 pre-push hook：$HOOK" >&2
  echo "备份后重装: mv \"$HOOK\" \"$HOOK.bak\" && bash $0" >&2
  exit 1
fi

cat > "$HOOK" <<'HOOK_EOF'
#!/usr/bin/env bash
# AscendC-DevKit pre-push hook — 快速 pytest 硬门（由 scripts/install_hooks.sh 管理）
set -uo pipefail
if [[ "${PRE_PUSH_SKIP:-0}" == "1" ]]; then
  echo "[pre-push] PRE_PUSH_SKIP=1，跳过自检"; exit 0
fi
REPO_ROOT=$(git rev-parse --show-toplevel)
echo "[pre-push] 快速自检 pytest --quick（零 token；完整自检请手动 scripts/pre_pr.sh <分支>）"
PRE_PR_QUICK=1 PRE_PR_SKIP_SKILL=1 bash "$REPO_ROOT/scripts/pre_pr.sh"
rc=$?
if [[ $rc -ne 0 ]]; then
  echo "[pre-push] 自检失败（exit=${rc}）。修到通过再 push，或 PRE_PUSH_SKIP=1 git push 临时跳过。"
  exit 1
fi
exit 0
HOOK_EOF
chmod +x "$HOOK"
echo "已安装 $HOOK"
echo "  - push 前自动跑 pytest --quick（零 token、秒级）"
echo "  - 完整自检（含 review skill）请手动: scripts/pre_pr.sh <分支>"
echo "  - 临时跳过: PRE_PUSH_SKIP=1 git push"
