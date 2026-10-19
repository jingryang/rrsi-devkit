# precision_debug runtime 注释二分定位 — L4 实施方案（2026-07-22）

> 层级：**L4 实施方案**。具体改哪个函数/文件、什么顺序、怎么验证。
> 问题记录见 `01-problems.md`；方案分析见 `02-analysis.md`。

## 改动范围

| 文件 | 改动类型 |
|------|---------|
| `substages` | 新增 `CommentBisectSubstage` 类 + `_PHASE_STEM_MAP`/`_PHASE_DEFAULTS`；`FixSubstage.resolve_condition` runtime 分流改向 |
| `tree` | transition_table 加 `fix.need_comment_bisect` + `comment_bisect` 节点；children 加 `CommentBisectSubstage` |
| `config` | `skills.stages` 加 `comment_bisect`→skill；`skills.tail_calls` 加新 skill 的 tail-call |
| `.claude/agents/ascendc-precision-comment-bisect.md` | 新建 agent manifest |
| `.claude/skills/ascendc-precision-comment-bisect/` | 新建 skill（SKILL.md + references/prompts + schema + _shared-protocol） |
| `fix-skill` SKILL.md / fix.md / `agents/ascendc-precision-fix.md` | 删内嵌消融实验（§2.5） |
| `tests/ut/orchestration/test_precision_debug_stage.py` | TDD：CommentBisectSubstage 路由/transition + fix 改向后回归 |

---

## Step 1：`CommentBisectSubstage` 类（substages.py）

仿 `PrintfLocateSubstage`（substages.py:1597）新增。

| # | 位置 | 改法 |
|---|------|------|
| S1a | 类属性 | `name="comment_bisect"`、`agent_name="ascendc-precision-comment-bisect"`、`_schema_files=["precision_comment_bisect.json"]` |
| S1b | `_phase_prompt` | 注释二分三层方法（区域→行）+ deploy_health 写入 + `located_roots` 跳过已定位区域 |
| S1c | `transition` | 仿 PrintfLocate：读 `deploy_health` 更新 `deploy_fail_streak`（§P8）；dedup candidate_pool；`bisect_progress` 判 case_skipped；bump `corrective_cycles` + `run_iter_counter`；`corrective_cycles` 耗尽 → `_advance_past_failure_type` |
| S1d | `resolve_condition` | 见下路由表 |

`resolve_condition` 路由（仿 printf_location:1713）：
```
corrective_cycles >= max_corrective_cycles → "case_more" if more_cases else "case_done"
case_skipped                                 → "case_more" if more_cases else "case_done"
located（写了 fix_plan 入池）                → "located"
deploy_fail_streak >= 3                      → "deploy_broken"
else                                         → "continue"
```

---

## Step 2：control.json / phase 映射（substages.py）

| # | 位置 | 改法 |
|---|------|------|
| S2a | `_PHASE_STEM_MAP` | 加 `"precision_comment_bisect.json": "comment_bisect"` |
| S2b | `_PHASE_DEFAULTS` | 加 `"precision_comment_bisect.json": {"tried_bisect_paths": []}` |

> comment_bisect **不新增** control.json 顶层字段——退火复用 `corrective_cycles` + `deploy_fail_streak`（§P2/§P8），故 `_CONTROL_REQUIRED_KEYS` / `_CONTROL_DEFAULTS` 不变。

---

## Step 3：路由（tree.py）

| # | 位置 | 改法 |
|---|------|------|
| S3a | `_PRECISION_DEBUG_TRANSITION_TABLE["fix"]` | 加 `"need_comment_bisect": ("comment_bisect", "corrective")` |
| S3b | 新增 `"comment_bisect"` 节点 | `{"located":("fix","corrective"), "continue":("comment_bisect","corrective"), "case_more":("fix","corrective"), "case_done":("run_tests","corrective"), "deploy_broken":("__escalate__:deploy_broken","validation"), "exhausted":("__escalate__:exhausted","validation")}` |
| S3c | `_build_precision_debug_group_a3` children | 在 `PrintfLocateSubstage` 后插 `AtomicStage(CommentBisectSubstage())` |

---

## Step 4：fix 改向 + 删内嵌消融（§2.5）

| # | 位置 | 改法 |
|---|------|------|
| S4a | `FixSubstage.resolve_condition`（substages.py:1498） | runtime pool_exhausted：`return "retry"` → `return "need_comment_bisect"` |
| S4b | fix SKILL.md:22 | 删「runtime→消融实验模式」分流描述，改为「runtime→`FIX_NEED_COMMENT_BISECT`（框架路由去 comment_bisect）」 |
| S4c | fix.md:177-212 | 删「runtime 消融实验模式」伪码段 + 注 2 |
| S4d | fix.md 返回协议（:467-475） | 删 runtime 消融相关；fix 池尽后 `failure_type=="runtime"` → `FIX_NEED_COMMENT_BISECT` |
| S4e | fix SKILL.md:118/139 + fix.md:130/398 + `agents/ascendc-precision-fix.md:45` | 「回退 comment-bisect（见 printf-debug.md）」错引删除（P5） |
| S4f | fix schema | `ablation_log` 非 required key（schema `required_keys=["fix_code_log"]`），**无需改 schema**；仅删 prompt/SKILL.md 逻辑 |

> fix 收到 `source="comment_bisect"` 的 plan 按 A/B 正常分级验证，**不触发** `source=="bisect"` 的知识库前置确认（fix.md:70）——该确认由 comment_bisect skill 内部 tail-call `ascendc-dev-knowledge` 完成。

---

## Step 5：agent manifest

新建 `.claude/agents/ascendc-precision-comment-bisect.md`（仿 `ascendc-precision-printf-locate.md`）：
- role = 注释二分定位 runtime crash
- hard rules：纯 crash/no-crash 二分、不依赖 printf 输出；每 experiment 必须 redeploy + 单用例；`located_roots` 跳过已定位区域；≤4 experiment/spawn；**区域二分先验优先 DataCopy/TQue 定向消融（参数降级，禁止裸注释），全不命中才 fallback 盲区域二分**

---

## Step 6：skill

新建 `.claude/skills/ascendc-precision-comment-bisect/`：

| 文件 | 内容 |
|------|------|
| `SKILL.md` | workflow：区域二分（阶段→区块）→ 行级确认 → located 写 `fix_plan(source=comment_bisect)` 入池；读写契约；返回协议 |
| `references/prompts/comment_bisect.md` | 占位符 / 内部循环伪码 / JSON 写入骨架（仿 fix.md 结构） |
| `references/_shared-protocol.md` | 通用子 agent 协议（接力布局/JSON 安全写入/精简策略）——自包含（§2.1） |
| `schema/precision_comment_bisect.json` | 见下 |

`schema/precision_comment_bisect.json`（仿 printf schema）：
```json
{
  "required": true,
  "required_keys": ["tried_bisect_paths"],
  "description": "comment_bisect phase 的 owner 产物：注释二分定位进度（粒度/怀疑区域/已定位根因）+ 实验记录 + 归档已试路径。bisect_progress 在 fresh 态为 null（不进 required_keys），仅 bisecting 时有值。",
  "example": {
    "bisect_progress": {
      "granularity": "stage | block | line",
      "suspect_region": {"file": "...", "start": 0, "end": 0},
      "located_roots": [
        {"file": "...", "line": 0, "evidence": "...", "errcode_before": "...", "errcode_after": "..."}
      ]
    },
    "experiments": [
      {"what_commented": "...", "result": "crash|no_crash|compile_fail", "errcode": "..."}
    ],
    "tried_bisect_paths": []
  }
}
```

核心方法（SKILL.md）——注释二分四层（先验优先加速收敛）：
0. **DataCopy/TQue 定向消融（先验快筛，D4-O2）**：枚举 kernel 内所有 `DataCopy`/`DataCopyPad` 调用 + `TQue` 使用点（Alloc/Free/EnQue/DeQue/Get 等），逐个**参数降级消融**（DataCopy: `blockLen`/`element`→安全常量，禁止裸注释；TQue: 最小安全配对）→ redeploy → 单用例 → crash 消失即定位到该调用点（直达行级，跳过区域二分）。理由：runtime crash 根因高度集中于此。
1. **区域二分（fallback）**：DataCopy/TQue 全不命中才进入。注释 `CopyIn/Compute/CopyOut/Tail` 整段 → redeploy → 单用例 → crash 消失则病灶在被注释段；段内二分（注释后半 → run → 还 crash 则病灶在后半）收敛到区块。
2. **行级确认**：区块内逐行注释 → run → 锁定触发行。
3. **多根因（增量）**：定位一处 → 写 `fix_plan(source=comment_bisect)` 入 `candidate_pool` → 返回 `located`；同 case 再入时读 `located_roots` 跳过已定位区域，从剩余继续。

判定信号：errcode 变化 / `max_err` 是否脱出 999.0（crash 哨兵），纯 crash/no-crash。

---

## Step 7：skill 注册（config）

| # | 位置 | 改法 |
|---|------|------|
| S7a | `config` `skills.stages` | 加 `"comment_bisect": "ascendc-precision-comment-bisect"` |
| S7b | `config` `skills.tail_calls` | 加 `"ascendc-precision-comment-bisect": ["ascendc-dev-knowledge", "ascendc-runtime-debug"]` |

---

## 退火行为矩阵

| 阶段 | 计数器 | 耗尽后 |
|------|--------|--------|
| comment_bisect | `corrective_cycles`（≥8）+ `deploy_fail_streak`（≥3） | case_more/case_done 或 deploy_broken → escalate |
| fix（改向后） | `corrective_cycles` + `consecutive_aborts`（abort 改造后） | runtime 池空 → `need_comment_bisect`（不再 retry 空转） |

---

## 验证（TDD，§3.1）

### UT（`tests/ut/orchestration/test_precision_debug_stage.py`）
- `CommentBisectSubstage.resolve_condition` 各分支：located / continue / case_more / case_done / deploy_broken
- `transition`：写 `bisect_progress`/`located_roots` 正确；`deploy_health`→`deploy_fail_streak`；`corrective_cycles` bump
- `FixSubstage.resolve_condition`：runtime pool_exhausted → `need_comment_bisect`（不再 `retry`）
- 删消融后 fix 相关 UT 回归（`ablation_log` 引用清理）

### ST（npu）
- 模拟 runtime crash case（`max_err=999.0`）→ fix 池空 → 验证进 comment_bisect 而非 retry 空转
- 多根因场景：同 case 修一处后仍 crash → comment_bisect 读 `located_roots` 继续二分剩余区域

### 回归
- 现有 precision_debug UT 全量通过
- 非 heavy ST 全量通过

---

## 风险
- comment_bisect 每 experiment 都要 redeploy + 单用例（比 printf 重）→ 靠 `corrective_cycles` + `deploy_health` 严格退火防空转
- 行级确认实验多 → ≤4 experiment/spawn 上限，跨 spawn 读 `experiments` 续跑
- 删 fix 消融是破坏性改动（§2.5）→ 必须与 comment_bisect 落地同批，禁止新旧并存

## 变更记录

| 日期 | 内容 |
|------|------|
| 2026-07-22 | 初版：7 步实施计划，覆盖 7 文件 |
