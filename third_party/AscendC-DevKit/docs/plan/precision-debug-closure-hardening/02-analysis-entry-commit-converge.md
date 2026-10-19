# L3 — 方案分析：precision_debug 入口 commit + converge 双通道一致化

> 层级：L3（有哪些选项、选了哪个、为什么）。覆盖 L1 P5-P8（见 `01-problems.md`）。
> 实施见 `04-impl-entry-commit-converge.md`。本工作是 step-73（best-commit-budget）的延续——
> step-73 的 `_converge_to_best_commit` 只在 `_sync_debug_result` terminal 路径调用，本工作补全
> escalation/except 通道 + 修 rollback 安全性根因（codegen 不 commit）。

## 背景：为什么入口 commit 是根因

step-73 加的 `_converge_to_best_commit` / `teardown` 都用 `RepoGuard.rollback` =
`git checkout <ref> -- op_dir` + `git clean -fd -- op_dir`。其安全性隐含假设：
**best_commit / HEAD 含全部 codegen 产物**。但实际：

- codegen 成功路径**不 commit**（产物停留 op_dir 工作区 untracked，另镜像到 artifacts/）；
- fix agent 只选择性 `git add <修改的文件>`（不收编 op_plugin/op_api 等注册文件）；
- 故 best_commit（= fix commit HEAD）**不含未被 fix 收编的 untracked codegen 文件**。

→ `clean -fd` 会删这些 codegen 文件 → 工作区残缺 → redeploy 残缺。这是 P5（根因），
也是 P3（退出收敛）安全性在 step-73 未触及的隐患。同时 escalation/except 通道压根没调
converge（P6），best_commit 缺失时 converge 直接 return（P7），teardown 还在用
`git reset --hard`（P8）。

## 核心决策：commit 模型（入口 commit 正确性的前提）

**决策**：precision_debug 期间 op_dir 的变更**仅来自三个来源**，各自独立 commit，**无用户手动修改**：

1. **codegen 产物** → 入口 commit（`_entry_commit_codegen`，首轮框架确定性提交）；
2. **fix 修改** → fix agent 自己 commit（每个 fix 一个 commit，best_commit = 最优 fix）；
3. **printf 探针** → printf commit。

**为什么这是入口 commit 的前提**：入口处 `git add -- <op_dir>`（全量 stage op_dir）只在
"op_dir 变更 = 纯 codegen"时精确等价于"commit codegen 产物"。入口时刻 fix/printf 尚未跑、
无手动修改，故 op_dir 变更只有 codegen。违反此前提（如有人在 precision_debug 期间手动改
tracked 文件）会把手动修改一并 commit，破坏 fix/printf 的 commit 边界。

**否决"支持手动修改"**：precision_debug 是框架驱动的自动化调试闭环，op_dir 变更由
codegen/fix/printf agent 产生，用户不在此期间手动改 op_dir。支持手动修改会破坏三源 commit
边界（fix commit 不再纯净），且让入口 commit 语义模糊。用户若需手动改，应在 precision_debug
之外（独立 commit）。

> 此前提曾导致 code review 第一轮误判（把"git add -- op_dir 会 commit 手动修改"列为 major）——
> 正是前提未成文所致。显式声明于此，防未来重蹈。

## 选项取舍

### D1 — 入口 commit 的方式
- **选：框架入口确定性 `git add -- <op_dir>` + commit**（op_dir scoped）。
  - 全量 add 在 commit 模型前提下（核心决策）== codegen-only，简洁且不依赖 codegen 产物路径枚举。
  - op_dir scoped（非 `git add -A`）避免扫入 repo 无关 untracked（遵 bounds_check 告诫）。
- 否：显式列 codegen 产物文件 —— codegen 产物路径随算子/skill 版本变化，枚举易漏且耦合 codegen 内部。
- 否：让 codegen 自己 commit —— 跨层（codegen 是能力层，不应承担编排层的 commit 调度），违 §1.6/分层。

### D2 — commit 由谁触发、何时
- **选：`RunTestsSubstage.actions` 入口（spawn agent 前的确定性 Python 段），首轮一次**。
  - RunTestsSubstage 是 precision_debug 组第一个 child（CompositeGroup 无 on_enter 钩子），
    其 actions 入口等价组入口。
  - spawn 前 commit → agent 跑 init-checkpoint.py 读到的 `git rev-parse HEAD` = 入口 commit →
    `best_commit`/`initial_commit` 自动含 codegen（零额外协调）。
- 否：CompositeGroup on_enter —— 该抽象无此钩子。
- 否：init-checkpoint.py 内 commit —— 那是 agent 跑的脚本，框架不可控其执行/成败。

### D3 — best_commit 缺失时 converge 的兜底
- **选：`best = dc.get("best_commit") or _current_head(repo_root)`（HEAD fallback）**。
  - 入口 commit 后 best_commit 不会空（init-checkpoint 写 best_commit=initial_commit=入口 commit HEAD）；
    本兜底覆盖 init-checkpoint 失败 / 非 git 转 git 等边缘。此时 HEAD 含 codegen（入口 commit），rollback 安全。
- 否：直接 `return state`（step-73 原状）—— 边缘场景 deploy_result 失真，评测错误 commit。

### D4 — teardown 的 best_commit 缺失处理（与 converge 不一致，故意）
- **选：`if not best or not op_dir: return state`（no-op，不 fallback HEAD）**。
  - teardown 是硬超时收尾路径，可能在首轮入口 commit **之前**触发（hard-kill 早于 commit 完成），
    此时 HEAD 不含 codegen，fallback HEAD + `clean -fd` 会删 codegen。
  - converge 安全 fallback HEAD 是因为它只在入口 commit **之后**运行（best_commit/HEAD 都含 codegen）。
  - 两路径取舍不同是故意的防御性设计（teardown 注释已澄清，见 L4 改动 6）。

### D5 — teardown 的 rollback 机制
- **选：`RepoGuard().rollback(repo_root, op_dir, best)`**（scoped `checkout best -- op_dir` + `clean -fd`，
  不动 HEAD）。
  - 与 converge 同语义（§2.5 唯一通路），消除 `git reset --hard`（无 pathspec、动 HEAD）的 RepoGuard
    D4/R1 违规。
- 否：`git reset --hard best`（step-73 原状）—— 违 RepoGuard D4/R1（whole-repo reset、动 HEAD）。

### D6 — escalation 通道接 converge 的条件
- **选：`node.name == "precision_debug" and escalation_cond != "upstream"`**。
  - `exhausted`/`abort_exhausted`/`deploy_broken` → converge（deploy_result 须指向 best_commit）；
  - `upstream` → 排除（首轮上游 halt，无 best_commit 可收敛，与 `_sync_debug_result if not is_upstream` 一致）；
  - `passed` → converge 内 `status=="passed"` 自带短路，接入亦安全。
- 与 except 通道（架构超时）共用 `_converge_precision_debug` helper（D7）。

### D7 — converge 调用的复用
- **选：提取模块级 `_converge_precision_debug(state, node) -> State` helper**，except 通道 + escalation
  通道共用（函数内 import 打破 graph_executor ↔ precision_debug_substages 循环依赖）。
- 否：两处各写 6 行（import + dc 提取 + 调用）—— 同构重复，未来 converge 签名/dc 提取变更要改两处，易漂移（§2.5）。
- `node.name == "precision_debug"` 判定保留在调用方（外围条件不同：except 无条件、escalation 排除 upstream）。

## 与 step-73 的边界

step-73（best-commit-budget）解决 P1-P4：best_commit 选对（passed_count 严格大于）+ 墙钟预算 + 退出收敛
（`_sync_debug_result` terminal 路径）+ 配置化。本工作是其延续：
- 补 P3 收敛的**根因**（P5：codegen 不 commit → clean -fd 误删）—— step-73 的 rollback 安全性隐含假设
  "best_commit 含 codegen"，本工作用入口 commit 让假设成立；
- 扩 P3 收敛的**覆盖**（P6：escalation + except 通道）—— step-73 只覆盖 terminal 路径；
- 补 P7（best_commit 缺失 HEAD fallback）+ P8（teardown reset --hard → rollback）。

## 不在范围

- A5 流程（`precision_debug_a5.py` 的 `InitBaselineSubstage`）独立于 A3 的 8-substage 流程，入口 commit 需另行处理。
- cannbench_adapt 未声明 `uninterruptible`（独立问题，`cannbench-adapt-uninterruptible/`）。
- heavy_llm 端到端验证（§3.11，特性交付节点由用户决策）。
