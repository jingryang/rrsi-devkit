# L1 问题记录 — codegen 反馈注入死通道：feedback 组装了但从未到达 coder

- 立项时间：2026-08-28
- 发现契机：step-100 实施的反向质疑（用户要求的自我审查）实证查证
- 状态：L1 冻结；L3 已拍板（方案 a 精化版）

> **勘误（2026-08-28 实施期查证）**：原论断「prompt 侧反馈分支被 B5 删除、
> 反馈从未到达 coder」**部分错误**——`_build_codegen_prompt` 函数体后半
> （提取前 `:2417-2561`）一直有方案 Z 时代建的 **kind 专属反馈段**
> （opdef_optional / scalar_contract / schema_mismatch / smoke_host /
> smoke_owner_judge / else 编译失败 + artifact_feedback 段），fresh 路径的
> 反馈投递是通的。误判源于调查时 grep/sed 范围截断了函数体。真实缺口修正为：
> **(a)** `context[...]` 注入是死通道（backend 零消费——该实证不变）；
> **(b)** step-100 引入的 resume_prompt 通用摘要**丢失 kind 专属上下文与
> 修复指引**（resume 路径反馈质量低于 fresh 路径）。本批「盲改」实证仍成立：
> fresh 重派轮反馈虽进 prompt，但 resume 轮（unique silent-cut 恢复后的多轮
> smoke 迭代）当时尚无 step-100/103 的通路。


## P1 — build/artifact/smoke 反馈经 `context` 注入，而 context 无任何消费方

### 证据链（代码事实）

1. **生产端存在**：`codegen.py:883-890`（`_actions_membase`）把
   `state.codegen_build_feedback` / `state.codegen_artifact_feedback` 注入
   `context["build_feedback"]` / `context["artifact_feedback"]`，注释声称
   「build-retry 反馈（上轮编译错误）注入下轮 coder」（方案 Z 文案）。
2. **消费端不存在**：
   - `sdk_backend.py`：`spawn(..., context, ...)` → `_spawn(..., context, ...)`
     仅签名传递，函数体内**零引用**；
   - `opencode_backend.py`：同（spawn 签名后零引用，仅注释提及）；
   - `runner.py:1064` 透传、`:1114` 仅把 `context_keys` 记进 spawn_context
     事件（可观测用途，非注入）。
3. **prompt 侧通道已断**：`_build_codegen_prompt`（`codegen.py:2283-2286`）的
   build/precision 反馈分支被 B5 删除，注释依据是「codegen self-closes build
   via the in-session redeploy loop (B1)」——该前提已被方案 Z 推翻（框架驱动
   build-retry，coder 不自建 build 循环），但反馈分支未随方案 Z 恢复。

### 历史脉络（两头断接）

方案 Z（框架驱动 build-retry）建了反馈的**生产端**（`_collect_build_feedback`/
`_collect_schema_feedback` 组装 → State 字段 → actions 注入 context），但
**消费端从未接通**（context 无人读、prompt 分支被 B5 删）。即自方案 Z 起，
「带反馈重派」的反馈从未到达 coder。

### 后果（行为事实）

- smoke/build/artifact/schema 反馈重派轮的 coder（**fresh spawn 路径**）从未
  收到结构化反馈，只能看 op_dir 磁盘现状冷干。
- 本批（20260827-132819-41aea1）佐证：unique smoke 循环 retry 4→6 每轮
  changed_files warning 重复出现（coder 每轮盲改）；moe schema 重派 7.5min
  重写 manifest 碰巧过契约（它并不知晓具体 violations 清单）。
- 与 step-100 的边界：step-100 的 `resume_prompt` 经 `first_prompt`
  （opencode `:668` / sdk 同构）是**活通道**——resume 路径反馈已通；本问题
  的暴露面是 **fresh spawn 兜底路径**（首跑失败即重派、旧 snapshot 恢复、
  rerun 后）与历史所有批的 fresh 重派轮。

## 需求

- 反馈的生产端（既有组装逻辑）与消费端（进入 coder 会话的载体）接通：
  fresh spawn 路径的 coder 必须能收到与 resume 路径同等的结构化反馈。
- 死通道（`context` 注入）按 §2.5 删除，不留「看似注入实为死代码」的误导。

## 边界

- resume 路径（step-100）已通，不重做。
- 反馈内容与字段的组装逻辑（step-93/94 产物）正常，本问题只在「最后一公里
  投递」。
