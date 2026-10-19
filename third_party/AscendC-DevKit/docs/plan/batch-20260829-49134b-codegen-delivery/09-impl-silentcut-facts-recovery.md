# P6 thinking 硬切分类恢复 + 事实呈现 — L4 实施方案（2026-09-01 定稿，覆盖 08-31 版）

> 层级：**L4 / 实施方案**。
> 上游：`08-analysis-silentcut-facts-recovery.md`（L3 定稿 2026-09-01）。
> 本版覆盖 08-31 版：删 resume_fails 升级式（前提被证伪），新增硬切分类、
> 兜底提示路由、配置一键（cut_recovery_max 独立预算定稿过程曾设后删——
> 上限由既有 cut_streak + 迭代天花板覆盖，见 L3 件 C）。
> 锚点（2026-09-01 全部实核；**双后端对称——§2.5 复核补正：sdk/claude 侧有
> 同构 cut 判定与 resume 决策，本步所有 backend 改动必须两侧同改**）：
> - 分型累计点：`capabilities/agent/base_backend.py:430` 消费循环
>   `kind in ("text", "thinking")` 分支（两侧 consumer 共享此类，天然单点）；
> - 判切点 ×2：`opencode_backend.py:851` 与 `sdk_backend.py:828`
>   （同构 `_cut = not err/crashed and not _last_turn_actionable`）+
   同构 F4 bump 分支（opencode `:858` 区 / sdk `:833` 区）；
> - resume 消息决策点 ×2：`opencode_backend.py:668`（`first_prompt =
>   (resume_prompt or _RESUME_PROMPT)`）与 `sdk_backend.py:537`
>   （`active_prompt = resume_prompt or _RESUME_PROMPT`）；`_RESUME_PROMPT`
>   单源 `_shared.py:679`；sdk spawn 内层 crash 重试 `:779/:800` 重置裸继续
>   （crash 重试非 cut resume，**保持不动**）；
> - runner：`orchestration/kernel/runner.py:353` 循环守卫、`:662-674` cut 分支、
>   `:688-697` "reached max iterations" 文案（P7 误导游离点）；
> - 校验助手：`runtime_config.py:69 _positive_int / :118 _positive_float`（均在）；
> - 携带通道：`_build_result` 共享（`base_backend.py:269`，metrics dict
>   `:293`）——零 schema 改动，固定键两侧同构。

## 改动 1：consumer 分型累计（base_backend）

`_IRConsumer` 增两字段：`thinking_chars: int = 0`、`last_thinking_ts: float | None
= None`。消费循环 `kind == "thinking"` 时累计 chars 并刷新时间戳
（`time.time()`）。跨 reset 持续累计（与 full_response 同口径）。步长不自建
字段——cut 点用既有 `start_ms` 派生。**无 thinking 到达时 `last_thinking_ts`
保持 None**——这是"无思考流证据"的自然信号，分类据此不成立。

## 改动 2：facts 组装 + 硬切分类（共享单点，两侧判切点调用）

组装与分类收口为 **base_backend 共享方法**（与 consumer 同居，§2.5 单点——
两侧判切点只调用不各自实现）：

```python
def classify_cut(self) -> tuple[dict, bool] | None:
    """cut 判定为 True 后调用：返回 (cut_facts, hard) 或 None（无思考证据）。"""
    _now = time.time()
    _gap_s = (_now - self.last_thinking_ts
              if self.last_thinking_ts is not None else None)
    facts = {
        "thinking_chars": self.thinking_chars,
        "last_delta_to_end_s": round(_gap_s, 2) if _gap_s is not None else None,
    }
    hard = (_gap_s is not None
            and _gap_s <= retry_budgets()["thinking_active_gap_s"])
    return facts, hard
```

（`step_duration_s` 由各判切点用既有 `start_ms` 补入 facts——两侧变量名不同，
不进共享方法。）两侧判切点（opencode `:851` / sdk `:828`）在 `_cut` 为 True
后同构接入：

- **随结果携带**：`_build_result(..., cut=_cut)` 处补 metrics 固定键
  `cut_facts` + `cut_hard`（共享 `_build_result`，单点生效两侧）；
- **随 sidecar 持久化**（下一次 spawn 的 resume 路由依据）：sidecar JSON 增
  `cut_facts` + `cut_hard` 两键，两侧同构写入；自然结束清 sidecar 既有语义
  不变（恢复成功即自愈清除）；fresh 首跑写 sidecar 不带这两键。**stale 防护**：
  非 cut 的 crash 轮（sidecar 保留作 resume 句柄）若沿用上一次 cut 的旧键，
  会把本次未知中断错误路由进兜底提示——故 sidecar 写入以**当次分类为准**：
  cut 轮写实测值；crash 轮写 `cut_hard=False` 覆写旧键（消息路由回到裸
  「继续」，与 crash 性质一致）。
- **F4 计数分流（语义错配修正，两侧同构）**：hard 为 True 时**不**走
  `_bump_session_resume_fails`（resume_attempts=3 是未知中断试探语义，管
  确定性事件是错配；且达阈退化 fresh 会丢上下文、重放同一深推理再撞墙）；
  hard 为 False 维持既有 bump 行为不变。侧车读侧退化判定无需改动——硬切
  不 bump，计数恒不因此达阈。

## 改动 3：resume 消息路由（两侧决策点同构三态）

`_HARD_CUT_RESUME_PROMPT` 常量进 `_shared.py`（与 `_RESUME_PROMPT` 同居
单源）。两侧 sidecar 读侧增读 `cut_hard`（缺键=False，旧 sidecar 自然走
原路）。两侧决策点（opencode `:668` / sdk `:537`）同构三态：

```python
if resume_session_id:
    if resume_prompt:                    # 显式深修反馈，恒优先（不变）
        prompt = resume_prompt
    elif _sidecar_cut_hard:              # 硬切分类：兜底提示（仅此注入）
        prompt = _HARD_CUT_RESUME_PROMPT
    else:                                # 未知中断 / 首次：裸「继续」（不变）
        prompt = _RESUME_PROMPT
```

`_HARD_CUT_RESUME_PROMPT`（通用文案无编号 §2.11，L3 冻结）：

```
上一步思考在输出中被截断。请先把已得出的结论落成草稿，再边落边思考继续——
已落盘的推导不会被截断丢失。
```

首次执行（fresh spawn）零注入不变；sdk spawn 内层 crash 重试（`:779/:800`）
保持裸继续——那是 crash 重试非 cut resume，硬切分类不适用。

## 改动 4：runner 文案事实化 + P7 诚实化（硬切计数纯观测，零控制流）

`kernel/runner.py`（stage 作用域，与 _cut_streak 同生命周期；**循环守卫
:353 零改动**）：

- 新计数 `_hard_cut_total = 0`（**纯观测**，不进任何控制流判定）、
  `_cut_chars: list[int] = []`；
- `_acut` 分支：读 `_ares.metrics.get("cut_facts")`；hard（`cut_hard` 为
  True）→ `_hard_cut_total += 1`；每 cut 追加 `cut_facts["thinking_chars"]`；
- cut WARN 文案：facts 在（metrics 有 `cut_facts`）→ 事实化
  「agent 终止：thinking 流被硬切（thinking {N} chars / 步长 {T}s / 末增量距
  结束 {X}s；无模型结束原因）；auto-resume next iteration（cut_streak={k}/
  {阈值}，硬切累计 {h}，iteration 保持 …）」；facts 缺失（旧 backend）→
  降级现文案；
- P7：循环退出后契约未满足 WARN（:688 区）按退出原因分流——cut_streak 耗尽
  导致的退出，前置真实原因 + 各次 thinking chars 清单；真迭代耗尽
  （`_iteration > iteration_ceiling`）保留 "reached max iterations" 原文
  （该路径文案与事实相符）。退出原因判定用既有变量
  （`_cut_streak >= cut_streak_threshold()` / 其余=迭代耗尽），零新状态。

## 改动 5：配置一键（§1.15 统一组）

`resources/orchestration-config.json` `retry_budgets` 增：

```json
"thinking_active_gap_s": 0.6
```

`runtime_config.py`：默认常量 `_DEFAULT_THINKING_ACTIVE_GAP_S = 0.6`
（实证：批 49134b 34/34 硬切 gap ≤0.58s、中位 0.12s；网关 flush 粒度影响
观测值故可调）；`retry_budgets()` loader 增该键（`_positive_float`，助手
已在）+ docstring 补 members 一行。

## 实施顺序（TDD）

1. 红测 consumer：thinking 增量累计、text 不计入、无 thinking 保持 None；
2. 红测判切点（**两侧 backend 各一组**，同构断言防单侧漂移）：facts 组装
   （实测值）、hard 分类（gap 命中/不命中/无 thinking）、metrics 两固定键、
   sidecar 两键持久化、自然结束清除、crash 轮覆写 cut_hard=False（stale
   防护）、hard 不 bump resume_fails / 非 hard 照 bump；分类实现单点断言
   （grep 级：classify 仅 base_backend 一处定义，两侧只调用）；
3. 红测消息路由（两侧决策点各一组）：三态优先级（resume_prompt > cut_hard
   兜底 > 裸继续）+ 旧 sidecar 缺键走裸继续 + fresh 零注入 + sdk 内层 crash
   重试保持裸继续；
4. 红测 runner：hard 计数仅观测（guard 行为零变化）、cut WARN 事实化含
   硬切累计、streak 耗尽退出 WARN 含真实原因与 chars 清单且不再
   max-iterations（P7）、真迭代耗尽路径文案不变、非 hard cut 文案降级；
5. 红测配置：默认 0.6、覆盖生效、非法值 ConfigError；
6. 实施 1→2→3→4→5；回归既有 cut/sidecar/退化/resume 用例。

## 验证

```bash
PYTHONPATH=src pytest tests/ut/capabilities -k "cut or sidecar or resume or consumer" -q
PYTHONPATH=src pytest tests/ut/orchestration -k "cut or runner or iteration or retry_budgets" -q
PYTHONPATH=src pytest tests/ut --quick -q
PYTHONPATH=src pytest tests/st -m "not heavy_llm" -q
```

端到端判据（下批）：任一硬切事件日志含三实测数字；恢复消息含截断事实与
落草稿引导（transcript 首条 user 可见）；硬切链不再出现 agent_degrade fresh
退化；streak/迭代耗尽的退出文案与真实原因一致。

## 判据（完成的定义）

- 零模型阈值：grep 改动集新增判定数字只来自配置（gap）与实测变量；
- facts/分类单点（grep：`classify_cut` 定义仅 base_backend 一处，两侧判切点
  只调用；`_HARD_CUT_RESUME_PROMPT` 仅 `_shared.py` 一处）；
- **控制流变化恰一处**：hard 不 bump resume_fails；其余（cut_streak=5、
  resume_attempts=3、迭代预算、resume_prompt 优先级、循环守卫）零变化；
- P7 误导文案在 streak 耗尽路径消失（UT 断言），真迭代耗尽路径保留。

## 风险清单

| 风险 | 缓解 |
|---|---|
| 兜底提示被模型误解为框架指挥打法 | 文案只有事实+落盘建议（§1.14）；下批 transcript 抽查模型响应 |
| hard 分类假阳性（非墙切被判墙切）→ 多余兜底提示 | 提示本身无害（建议非门）；gap 判据 34/34 实证无假阳性；可配置收紧 |
| 穿插型 chronic 撞墙（每次进展后撞一次）空烧时长 | 受迭代天花板约束且属真进展（质量优先放行）；硬切累计进 WARN 可观测；下批若实证空烧数小时，届时加总量预算方为有据 |
| consumer 累计口径跨 resume 混入上轮 | 与 full_response 同口径先例；sidecar cut_facts 每次 cut 覆写为当轮实测；UT 钉住 |
| 旧 sidecar 无新键 | 缺键=False 走原路径，不假设（§1.2 可诊断） |
