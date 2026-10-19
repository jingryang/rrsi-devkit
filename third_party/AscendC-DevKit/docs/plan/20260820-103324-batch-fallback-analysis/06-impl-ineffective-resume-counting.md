# L4 实施方案：无效 resume 计数——resume 后仍 cut 纳入 resume_fails

> 对应问题：F4（silent-cut 与 resume 计数脱节，cut-resume 循环不触发 fresh 重开）。
> 用户决策背景（2026-08-20 issue 补充）："同一 session resume 符合预期，只要 resume
> 有界"——问题不在 resume 本身，在**"resume 后仍无产出的连续 cut"没有进入任何有界
> 计数**，fresh 重开机制永不触发。

## 一、现状机制（两 backend 对称，已核实）

```
silent-cut（thinking-only terminal，流"正常结束"无 error）
  → sidecar 保留（resume 句柄）+ result.cut=True            (opencode :823 / sdk :818)
  → runner _cut_streak += 1（上限 MAX_CUT_STREAK=5）          (runner.py:509)
下次 spawn：sidecar 存在 → 自动 resume 同一 session            (opencode :573-602 / sdk :505-530)
  → resume 成功、agent 又 thinking 泥潭 silent-cut
  → resume_fails 不涨（只在 resume 会话被硬杀/turn_stall 时 +1）(opencode :866 / sdk :252)
  → 无限 resume 同一 session；fresh 退化（resume_fails >= resume_attempts=3
    → agent_degrade 清 sidecar fresh spawn）永不触发
```

**根因**：`resume_fails` 语义 = "resume **调用**失败"；"resume 成功但**恢复无效**（又
cut）"这个业务事件两套计数（runner cut_streak / backend resume_fails）都不管——F2
"空跑 vs 孤儿"同构的语义中缝问题。

## 二、方案（02-analysis 方案 2 定稿）

**修复语义**：本次 spawn 是 resume 且以 cut 结束 → `resume_fails +1`（"这次恢复尝试
无效"）。既有阈值与退化路径原样接管：

- `resume_fails >= resume_attempts(3)` → 下次 spawn 走既有 `agent_degrade`（清
  sidecar、fresh session、全量 prompt）。
- fresh 正常结束 → 清 sidecar → 计数归零（既有语义，不变）。
- **fresh 首跑的 cut 不计数**（首次 cut 先原地 resume 一次——对齐用户"同一 session
  resume 符合预期"）；只有 resume 过的会话再 cut 才 bump。即退化发生在
  cut→resume→cut→resume→cut→resume→cut（第 3 次无效 resume 后）→ fresh。

### 改动点（每 backend 两处）

**opencode_backend.py**：

1. `_spawn` 内记录本 spawn 是否走了自动 resume：读 sidecar 分支已有
   `resume_session_id = _sid`（:597）——加局部 `_resumed = True` 标记（含显式
   resume_session_id 参数的情形）。
2. cut 判定处（:823 `_cut = ...`）后：`if _cut and _resumed:
   self._bump_session_resume_fails(...)`，WARN 说明"resume 后仍 silent-cut，计无效
   resume（连续 {n} 次，阈值 {resume_attempts}）"。

**sdk_backend.py** 对称：

1. 既有 `self._spawn_was_resume`（:526，供外层硬超时 bump 判断）覆盖 sidecar 自动
   resume——cut 判定处（:818）复用同一标记，不再新增。
2. cut 判定后同样 bump + WARN。

**base_backend.py**：`_bump_session_resume_fails` 不改（read-modify-write 既有）。

### 判据的 §1.10 符合性

横切判据用业务语义显式声明："本次 spawn 是否 resume"（backend 显式记录）+ "结果是否
cut"（既有 cut 判定），非机制特征代理（不猜"有没有调 API"）。

### 不做的事

- 不动 runner `cut_streak`（stage 级放弃界，语义独立保留）。
- 不动 `MAX_CUT_STREAK` / `resume_attempts` 阈值（用户既有决策）。
- 不给 cut 注入 resume_prompt 特化（Part 3 既有机制不动，本方案只修计数中缝）。

## 三、控制流对比

**改前**：
```
cut₁(fresh) → resume → cut₂ → resume → cut₃ → resume → cut₄ → resume → cut₅
  → runner cut_streak=5 → stage 放弃（5 轮 thinking 泥潭 token 全烧）
```

**改后**：
```
cut₁(fresh) → resume → cut₂(bump→1) → resume → cut₃(bump→2) → resume →
cut₄(bump→3≥阈值) → 下次 spawn agent_degrade → fresh 全量 prompt →
  正常结束（sidecar 清，计数归零）或 fresh 也 cut（不计数，resume 重开一轮）
```

thinking 泥潭 session 最多被 resume 3 次即换新，与"resume 有界"的用户要求对齐。

## 四、验证方案（TDD）

### 新增测试（tests/ut/capabilities/ 下就近 backend 测试文件）

1. **resume 后 cut → resume_fails +1**：sidecar 带 session_id（resume_fails=0）→
   spawn resume → 结果 cut → 断言 sidecar resume_fails=1。
2. **fresh cut 不计数**：无 sidecar → fresh spawn → cut → sidecar resume_fails=0。
3. **计数达到阈值 → 下次 spawn 退化 fresh**：sidecar resume_fails=2 → 本次 resume
   又 cut（bump→3）→ 再 spawn 时走 agent_degrade（清 sidecar、新 session、全量
   prompt 非继续 nudge）。既有 degrade 路径的测试若已覆盖"resume_fails>=阈值"分支，
   本方案无需新增（行为不变）——只补 1/2 两条计数路径。
4. **正常结束清零**（回归守护）：resume 后正常结束（非 cut）→ sidecar 被清（既有）。

### 回归

- `tests/ut/capabilities/`（两 backend 的 sidecar/resume 相关用例）
- 全量 UT `--quick`

## 五、风险与边界

- **上下文连续性牺牲**：连续 3 次无效 resume 后 fresh 丢上下文——但泥潭 session 的
  上下文本身就是负资产（thinking 循环），fresh 全量 prompt 重开是更优解（02-analysis
  方案 2 已论证，用户认可方向）。
- **误判面**：cut 判定本身（`_last_turn_actionable`）是既有机制，本方案不改变判据，
  只改变"cut 之后计不计入 resume 无效"。误判代价 = 多一次 fresh spawn（可接受）。
- **两 backend 行为对称**：同一语义两处实现（既有架构即如此——`_bump...` 在
  base_backend 共享，判定点各自），测试覆盖两侧。
