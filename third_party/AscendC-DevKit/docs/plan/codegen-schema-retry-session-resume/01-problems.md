# L1 问题记录 — codegen schema-retry 定向重派全新 spawn（不续原会话）

- 立项时间：2026-08-27
- 实证批次：`20260827-132819-41aea1`（moe_re_routing execution `20260827-132819-db3570`）
- 状态：L1 冻结，L3 未启

## P1 — schema-mismatch 定向重派走全新会话，原会话上下文被丢弃

### 现象（客观事实）

1. moe_re_routing codegen 首轮会话 22:40:20 → 23:20:05（152 turns，约 40 min）交付时，
   `codegen_manifest.scalar_access_contract` 不符 step-93 契约。框架处置：
   `codegen.py:1605-1610` 拒写 `deploy_result`、组装 `codegen_build_feedback`
   （`kind='scalar_contract'`，含 violations + 三选一修复 hint）写入 state、
   触发 iteration 2 全新 spawn。
2. 重派会话 `ses_fbc31529bffemZLTJjMgYTI3xK` 为**全新 session**：turn 1 重新计数、
   turn 2 重新 `tool:skill` 加载 coder skill、turn 3 才开始干活。原会话 152 turns 的
   决策上下文（哪个标量点为什么标量化、编译修错历史）不随行。
3. 重派会话 23:20:06 → 23:27:37 done = **7.5 min**（冷启动 + skill/设计产物重读 +
   现场重建）。实际修复动作是改 manifest 一处：代码文件在磁盘未动
   （两次 changed_files.json warning 内容一致可佐证）。
4. 对照组：同批 unique codegen silent-cut（socket 断流）走 backend 层
   `auto-resuming session`（`opencode_backend.py:625` / `sdk_backend.py:531`），
   **续原会话**恢复，上下文保留、推进连续。

### 机制事实

- 两条重拉路径在不同层、未打通：
  - **schema mismatch 重派**（stage 层）：走 stage iteration 循环，spawn 不携带
    上一轮 `session_id`；feedback 只注入新 spawn 的 prompt（反馈本身**有**传递）。
  - **silent-cut auto-resume**（backend 层）：仅存在于**同一次 spawn 调用内部**的
    流断恢复（session_id 在 + sidecar 在 → resume 同 session 继续当前 query）。
  - **跨 iteration 的会话续接能力在框架中不存在**——不存在任何通路把上一轮
    session_id 传给下一轮 spawn。

### 成本影响

- 每轮 schema retry 重付一次冷启动（skill 重载 + 产物重读 + 现场重建 ≈ 7.5 min +
  对应 token）；retry 上限 40 次，反复违约的算子成本按轮线性放大。

## 需求（记录"要什么"，不选实现）

- schema-mismatch 定向重派应**保留原会话上下文**（在反馈渠道不变的前提下续原
  会话），使修复动作限于被指认的那一处，不重付冷启动成本。

## 原则对照（引用，不展开取舍）

- §1.14 原地修改优先于回炉：谁发现谁改、只改那一处、不重填表。
- §2.9 问题发现与解决应在同一 agent 内闭合。

## 边界（非本问题）

- silent-cut 的 auto-resume 行为正常（本批实证有效），不改。
- schema 契约校验本身（step-93 `_validate_scalar_contract`）工作正常，本批实证
  真实拦住违约并定向重派，不改。
- `changed_files.json` 键名误当路径的交叉校验误报是另一独立问题，另行跟踪。
