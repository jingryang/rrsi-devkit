# L3 方案分析 — 快照排除表对构建清单的误杀(拍板后冻结)

> 对应 L1:`01-problems.md` P1–P4。用户裁决(2026-10-12):根修 + 补现场(推荐方案)。

## 1. 修复原则

根因在「快照提交不完整」——快照完整则回滚 `checkout` 能恢复构建清单,`clean` 才是安全的;回滚端 `git clean` 本身不改(改 clean 属症状端兜底,§1.2 症状修复)。

## 2. 候选方案

### 方案 A(采纳):排除表按精确文件名豁免构建清单
- `_DEBUG_EXCLUDES` 判定前,`CMakeLists.txt` 这一精确 basename 直通。构建清单是 cmake 机制级常量名(与算子/仓无关,§1.12 不耦合);误报空间为零(调试文本不会叫 CMakeLists.txt);改动单点(git_safety.py 一处条件)。
- veto 语义不变:它仍然拦截一切 `*.txt` 调试文本(`stderr_case.txt` 等既有测试继续绿)。

### 方案 B(拒):profile include 的显式精确名优先于框架排除表
- 语义听起来通(profile 作者显式点名 → 意图优先),但 include 里的宽 glob(`op_kernel/**`)也会让 `op_kernel/foo.txt` 绕过 veto——排除表对真实调试文本失效,veto 被架空。

### 方案 C(拒):把 `*.txt` 收窄为更具体的调试文本模式
- 调试文本文件名无界(notes/caseN/verify 输出……),枚举不可靠,漏一类就静默进提交——把误杀换成漏放,同样不可判定。

## 3. 关键子决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 修快照还是修回滚 | 修快照 | 快照完整 ⇒ checkout 天然恢复 ⇒ clean 安全;回滚端兜底属症状修复 |
| 豁免形式 | 精确 basename 集合(`CMakeLists.txt`) | 机制常量、零误报、不耦合算子(§1.12);豁免发生在 include/exclude 过滤**之后**,profile 未声明的文件本来就不进候选,不产生新暴露面 |
| 现场 worktree 是否提交该文件 | 不提交 | 批次 worktree 瞬态(「批毕自动 reset」);提交会改已完结 run 的提交史。根治靠快照修复,下一批次入口快照自然携带 |
| 本次 run 的 converge_mismatch 标记 | 保留不抹 | 如实记录历史事实;物理复验以旁路重建+smoke 补齐(见 L4) |
| 950 侧 | 不同步(沿用既有裁决口径) | 本缺陷为 1903 侧快照/回滚组合首次真实触发;950 侧演进文件分叉清单照 P8 口径追加 |

## 4. 验证方案(结果见 L4)

- TDD:入口快照端到端用例(profile include 显式声明 CMakeLists.txt + 调试 `stderr_case.txt` 并存)——红(复现事故:提交为空、op_dir 仍脏)→ 绿(CMakeLists 入提交、调试文本留在外)。既有调试排除行为回归(`test_entry_snapshot_commits_only_profile_allowed_production_files`)不得破坏。
- 现场:在 dfa6242 工作树重建 CMakeLists.txt → `build.sh --soc=ascend910b` → 旁路安装(run 的 artifacts 不动)→ NPU smoke。
