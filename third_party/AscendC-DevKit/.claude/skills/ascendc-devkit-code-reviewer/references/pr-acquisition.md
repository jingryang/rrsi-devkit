# 取 PR 的方法

## 情况 1：已在本地（最常见）
PR 已 fetch 为本地分支（如 `pr-<N>-review`），直接用：

```bash
git rev-parse pr-<N>-review                       # head SHA
git merge-base main pr-<N>-review                 # 基线 SHA
git diff $(git merge-base main pr-<N>-review)...pr-<N>-review
```

## 情况 2：从 gitcode 拉（给 merge-request 号）
gitcode（AtomGit/Gitea 系）的 PR ref 是 **`refs/merge-requests/<N>/head`**，**不是** GitHub 的 `pull/<N>/head`：

```bash
git fetch origin refs/merge-requests/<N>/head:pr-<N>-review
```

- **认证**：gitcode 已**禁用账号密码**，必须用 **PAT（访问令牌）** 当密码，经 credential helper 输入。
- 拉不下来先 `git ls-remote origin` 确认 ref 存在 + 认证通（`GIT_TERMINAL_PROMPT=0` 可让它缺凭证时**立即报错**而非卡住）。
- 若该 ref 不存在（少数配置），去 PR 页拿贡献者源分支，`git fetch <fork-url> <branch>:pr-<N>-review`。

## 情况 3：显式 commit 区间

```bash
git diff <base-sha>...<head-sha>
```

## diff 语义（重要）
始终用**三点点** `...`（相对 merge-base），对齐 PR「相对目标分支的净变更」语义；
两点点 `..` 会带入目标分支自己的演进历史，**不是** PR 的改动。
