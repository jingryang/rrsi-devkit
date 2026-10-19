# P5: A3/A5 双实现重复——同职责写两遍，且 A5 有功能缺口

**状态**: 待修
**层归**: L1 问题记录（只述事实，方案在 L3）

## 哪里坏了？

A3（`precision_debug_substages.py`，3253 行）与 A5（`precision_debug_a5.py`，1279 行）实现同一份"precision_debug 复合组"职责，但**代码级重复 + 结构级重复 + A5 功能缺口**并存。同一逻辑写两遍（违反 §1.15 统一抽象），且 A5 缺失 A3 已有的关键机制。

## 凭什么这么说？（证据，来自 A5 深度审计）

### 事实 1：代码级重复（同一逻辑写两遍）

| 逻辑 | A3 | A5 | 重复度 |
|---|---|---|---|
| `_operator_dir` | substages.py 同名 | a5.py L45-51 | 完全相同（注释自认"对齐 A3"） |
| `_sync_debug_result` | substages.py L1301 | a5.py L367-404 | 几乎逐行相同（terminal status 集、iterations_used、last_error 清空） |
| `_common_context` | substages.py L1490-1534 | a5.py L440-475 | 80% 同构 |
| transition 模板体 | 每 substage 写 | 5 个 transition 4 个同模板 | 35-45 行 × 4 连拷贝 |

### 事实 2：A5 功能缺口（非重复，是缺失）

A5 基类 `_A5PrecisionDebugSubstage`（L409-510）是 A3 `_PrecisionDebugSubstage`（L1384）的**瘦身版，缺 3 个关键机制**：
- **无 teardown rollback**（A3 L1422-1469 RepoGuard 回滚）——A5 硬超时中断时不回滚到 best_commit
- **无 `_entry_commit_codegen`**（A3 L1537-1539）——A5 入口不 commit codegen，best_commit 不可靠
- **无 schema 校验**（A3 `_schema_files`/SchemaLoader）——A5 对 skill 产物无契约校验

### 事实 3：结构级重复

- checkpoint relay 双轨并存：A3 用 control.json，A5 用 checkpoint.json（同模式写两遍）
- 注释体系整段复制（§P2/§1.3/§2.3/§4.3 交叉引用一致）

## 影响

- **§1.15 违背**：同职责（precision_debug 复合组）双实现，改一处不同步。
- **A5 功能缺口**：中断无回滚、无契约校验——A5 算子在硬超时下可能残留脏 op_dir。
- **维护成本双倍**：任何机制改动（如 R1 artifact-retry）要改两处。

## 与既有问题边界

- **P7**（A5 is_vf_issue）：A5 特有路由委托问题。
- **P8**（A5 best_snapshot）：A5 特有精度权威委托。
- **P5 是结构性重复**，P7/P8 是 A5 特有的语义问题，正交。
