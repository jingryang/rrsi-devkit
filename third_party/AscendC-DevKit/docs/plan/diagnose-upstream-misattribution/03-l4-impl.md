# L4 — diagnose resume 状态传递实施方案（方案 F）

> 四层方案体系 L4：具体改哪个函数、什么顺序、怎么验证。
> 对应 L3：docs/plan/diagnose-upstream-misattribution/02-l3-analysis.md（方案 F + 前置分析）
> 目标：diagnose 被杀/resume 后，能感知"当前真实状态"（自身进度 + 代码状态 + 失败状态），而非从 round 1 重头认知 + 过时环境结论。

## 一、改动总览

| # | 文件 | 改动 | 工作量 |
|---|---|---|---|
| 1 | `.claude/skills/ascendc-precision-diagnose/SKILL.md` | 增量写 `_summary` 引导 | 小（文本） |
| 2 | `.claude/agents/ascendc-precision-diagnose.md` | 同步增量写纪律 | 小（文本） |
| 3 | `src/ascendc_devkit/orchestration/stages/precision_debug_substages.py` | prompt 构造：resume 注入状态 | 小（逻辑） |
| 4 | `.claude/skills/ascendc-precision-diagnose/schema/precision_diagnose.json` | 不加字段（`_summary` 已自由对象） | 0 |
| 5 | UT | 断言 resume 注入逻辑 | 中 |

**不做**：rollback（丢进度，best_commit 9934d0b 会丢 ShiftF32 修复）、框架检测残留（状态传递即可）。

## 二、改动详情

### 改动 1：SKILL.md 增量写 _summary

**文件**：`.claude/skills/ascendc-precision-diagnose/SKILL.md`
**位置**：「### 写 `precision_diagnose.json`」节（L57-60）

**现文**（L60）：
```
- `_summary`：**必须写**。框架 transition 从此字段生成 history。字段：`symptom` / `case_id` / `root_cause` / `upstream_signal` / `upstream_stage` / `upstream_reason`（上游时）/ 实施时追加 `already_resolved` / `partial_outputs`
```

**改为**（加增量写纪律 + 每修一步写一次）：
```
- `_summary`：**必须写**。框架 transition 从此字段生成 history。字段：`symptom` / `case_id` / `root_cause` / `upstream_signal` / `upstream_stage` / `upstream_reason`（上游时）/ 实施时追加 `already_resolved` / `partial_outputs`
- **增量写**：每完成一步定位/修复/验证后，就**更新** `_summary`（`symptom`/`root_cause` 覆盖为最新结论，`fix_code_log.tried_fixes` 追加本条尝试）——**不要只在收尾才写**。若被中断，resume 后你能从 `_summary`/`fix_code_log` 读到自己的进度。
- **覆盖不追加**：`symptom`/`root_cause` 是覆盖更新（最新结论），不是每步追加；只有 `tried_fixes` 追加。文件保持小（~KB 级）。
```

### 改动 2：agent manifest 同步

**文件**：`.claude/agents/ascendc-precision-diagnose.md`
**位置**：「### Step 4: Write」节

**现文**：
```
- **precision_diagnose.json**：`_summary`（`symptom`/`case_id`/`root_cause`/...）+ `fix_code_log`（...）+ `diagnose_done=true`
```

**改为**（加增量写纪律）：
```
- **precision_diagnose.json**：`_summary`（`symptom`/`case_id`/`root_cause`/...）+ `fix_code_log`（...）+ `diagnose_done=true`
  - **增量写**：每步定位/修复/验证后更新 `_summary`（覆盖 `symptom`/`root_cause` 为最新，追加 `tried_fixes`）。被中断后 resume 能读到进度。
```

### 改动 3：prompt 构造 resume 注入状态

**文件**：`src/ascendc_devkit/orchestration/stages/precision_debug_substages.py`
**位置**：`DiagnoseSubstage._phase_prompt`（约 L2099，diagnose 的 prompt 构造）

**现文**：`_phase_prompt` 是纯字符串拼接，无 resume 感知。

**改为**：在 `_phase_prompt` 开头（Step 0 之前）加一段「**resume 状态感知**」：
- 读 `_read_agent_summary(state)` → 若有非空 `_summary`（说明上次 spawn 已写进度），注入：
  ```
  ## Resume 状态（上次 diagnose 已写进度，你是续跑）
  上次诊断进度：{_summary 的 symptom/root_cause 摘要}
  上次尝试：{tried_fixes 概要}
  当前工作区 git 状态（git status/diff 概要）：{...}
  ```
- 若无 `_summary`（上次没写进度，可能被杀太早），注入：
  ```
  ## Resume 状态（上次 diagnose 被杀，未写进度）
  你上次可能正在定位。请从当前失败证据（result.json 的 error_msg）重新确认失败状态，再继续。
  ```
- **实现**：`_phase_prompt` 签名不变（纯函数），但通过 `state` 读 `_read_agent_summary` 注入。注意 `_phase_prompt` 当前是 `(ctx, op_dir, ctrl, phase_path, skill_dir, iteration)` 纯函数——需传 state 或提前在调用处把 resume 状态拼进 ctx。

**关键实现决策**：`_phase_prompt` 是纯函数（无 state）。两个方案：
- **方案 i**：调用处（`_build_param_prompt`，约 L1320）读 `_read_agent_summary(state)`，把 resume 状态作为 `ctx["resume_status"]` 传入，`_phase_prompt` 拼接。**推荐**——保持 `_phase_prompt` 纯函数，改调用处。
- **方案 ii**：`_phase_prompt` 加 state 参数。改动大，不推荐。

**方案 i 实现**：
```python
# _build_param_prompt 里（约 L1339 ctx 构造处）
resume_status = self._format_resume_status(state)
ctx["resume_status"] = resume_status
```
```python
# 新增 helper（DiagnoseSubstage 内）
def _format_resume_status(self, state) -> str:
    """Resume 感知：读上次 _summary + git 状态，格式化为 prompt 注入段。"""
    summary = self._read_agent_summary(state) or {}
    if not summary:
        return ("## Resume 状态（上次被杀未写进度）\n"
                "你可能在定位中途被杀。请先读 result.json 的 error_msg 确认当前失败状态，再继续。")
    rc = str(summary.get("root_cause") or "")[:200]
    fixes = summary.get("fix_code_log", {}).get("tried_fixes") or []
    tried = "; ".join(str(f.get("fix_desc") or f.get("result") or "")[:80] for f in fixes[-3:])
    return (f"## Resume 状态（上次 diagnose 已写进度，续跑）\n"
            f"上次 root_cause: {rc or '(未定)'}\n"
            f"上次尝试: {tried or '(无)'}")
```
然后 `_phase_prompt` 里在 Step 0 前加 `f"{ctx.get('resume_status', '')}"`。

### 改动 4：schema

**不需要加字段**：`_summary` 已是自由对象（schema `fields` 有 `_summary`，子字段不强制）。增量写 `symptom`/`root_cause`/`tried_fixes` 不新增字段。**0 改动**。

## 三、验证（TDD）

### UT

新增 `tests/ut/orchestration/test_precision_debug_resume_status.py`：
- `test_format_resume_status_no_summary`：无 `_summary` → 输出"被杀未写进度"提示。
- `test_format_resume_status_with_summary`：有 `_summary`（root_cause + tried_fixes）→ 输出续跑提示含 root_cause 摘要。
- `test_prompt_includes_resume_status`：`_phase_prompt` 输出包含 resume_status 段。
- `test_resume_status_pure_function`：`_format_resume_status` 不改 state（纯读）。

### ST 非 heavy

- `test_precision_debug_stage.py` 现有诊断路由测试保持绿（resume_status 是附加段，不影响路由）。

### heavy_llm（可选，§3.11 用户确认）

- 复用 `test_precision_diagnose_inplace_loop.py`：seed 一个已写 `_summary` 的 diagnose 产物 → spawn diagnose → 断言它读到 root_cause 继续（而非重头）。

## 四、实施顺序

1. 改动 1+2（SKILL.md + agent manifest）——纯文本，先做。
2. 改动 3（prompt 构造 + `_format_resume_status` helper + ctx 注入）——逻辑，后做。
3. UT（改动 5）——TDD，与 2 同步。
4. 全量 UT + 相关 ST。

## 五、回退与边界

- 每个改动独立 commit 可回退（1+2 是文本，3 是逻辑）。
- 不动框架路由/transition（只改 prompt 构造）。
- 不动 §1.14（不枚举）、§1.13（比对 golden）——resume 状态是帮模型的起点，不控模型。
- 不改 `_phase_prompt` 纯函数签名（改调用处传 ctx）。

## 六、不做清单（明确排除）

- **不做 rollback**：丢进度（best_commit 9934d0b 会丢 ShiftF32 修复），非通用。
- **不做框架检测残留**：状态传递即可（diagnose 增量写后 resume 能读到）。
- **不做 SIGKILL 进程级守护**：改动大，为硬件错误兜底不值（用户决策）。
- **不加 schema 字段**：`_summary` 已自由对象。
