# AscendC Precision Debug 编排层修复方案

## 一、根因诊断

### 1.1 当前架构

```
PrecisionDebugStage (Python)
  │ SpawnAgent
  ▼
ascendc-precision-debugger (LLM orchestrator agent)
  │
  ├── Agent(ascendc-precision-run-tests)
  ├── Agent(ascendc-precision-diagnose)
  ├── Agent(ascendc-precision-fix)
  └── Agent(ascendc-precision-printf-locate)
```

LOOP 由 LLM agent 的 prompt 驱动（`ascendc-precision-debugger.md:24-33`）：

```
LOOP:
  1. Read checkpoint.json
  2. Bash: stage-transition.py → NEXT_STAGE
  3. Agent(subagent_type=ascendc-precision-{NEXT_STAGE}) → dispatch
  4. Sub-agent returns → verify → loop
```

### 1.2 根因：SDK async dispatch 与 prompt 同步语义失配

**证据**（clipped_swiglu transcript `ascendc-precision-debugger-01.jsonl`）：

1. **SDK 的 Agent 工具是异步的** — 每次 dispatch 返回：
   > "Async agent launched successfully. ... The agent is working in the background. You will be notified automatically when it completes."

2. **编排器 prompt 假定同步执行** — "Sub-agent returns → verify" 期望子 agent 完成后再继续，但 SDK 无法阻塞等待。

3. **编排器通过空转等待** — 每笔 dispatch 后编排器无有效工作可做，在等待通知期间反复读 checkpoint、skill 模板、跑验证脚本。实测数据：
   - Dispatch 1 (diagnose)：空闲 17 turns
   - Dispatch 2 (fix)：空闲 208 turns  
   - Dispatch 3 (run_tests)：空闲 59 turns

4. **空转导致 context 爆炸** — 编排器在 wait 期间把 checkpoint + 模板 + 自写分析全部堆进 context，最终达到 ~251K chars → halt。

5. **空转期间违反职责边界** — 编排器 hard rule 4 声明 "You NEVER execute debugging work"，但实测编排器在空转中自己跑了 Bash 调试命令（因为没其他事可做）。

**这是编排层的系统性问题，与具体算子无关** — clipped_swiglu、dequant_swiglu_quant、ai_infra_moe_init_routing_v3 等所有精度调试都命中同一个编排层缺陷。

### 1.3 次要风险：stale harness（无法从本 repo 验证，但模式合理）

AI 分析还指出另一个根因「stale harness」：批跑前半段用旧版 DevKit 生成 harness.py，后续 resume 不刷新 harness，导致 fix agent 反复遇到同一种不可修的 TypeError。commit `734557f` 和 `multi_add` 的 run 数据在本 repo 不存在，无法确认此问题是否真的发生过。但该风险模式是合理的，在方案中作为独立防范点列出。

---

## 二、修复策略

### 核心思路：把 while 循环从 LLM agent prompt 移到 Python

```
当前：LLM orchestrator → Agent(dispatch) → 空转等通知 → Agent(dispatch) → ...
改为：Python while loop  → SDKBackend.spawn(diagnose) → await → SDKBackend.spawn(fix) → await → ...
```

**什么上升到编排层、什么不变：**

| 阶段 | 当前执行方 | 改为 | 原因 |
|------|-----------|------|------|
| **run_tests** | LLM orchestrator → Agent("ascendc-precision-run-tests") | Python 直接调 `run_precision_cases()` | 确定性逻辑，无 LLM 推理 |
| **stage_transition** | LLM orchestrator → Bash `stage-transition.py` | Python 函数 | 确定性逻辑，已在 Python 模块中 |
| **redeploy** | LLM orchestrator 或子 agent 负责 | Python 直接调 `Deployer` | 确定性逻辑 |
| **diagnose** | LLM orchestrator → Agent("ascendc-precision-diagnose") | Python `await spawn("ascendc-precision-diagnose")` | 仍是 agent（LLM 推理） |
| **fix** | LLM orchestrator → Agent("ascendc-precision-fix") | Python `await spawn("ascendc-precision-fix")` | 仍是 agent（LLM 推理） |
| **printf_location** | LLM orchestrator → Agent("ascendc-precision-printf-locate") | Python `await spawn("ascendc-precision-printf-locate")` | 仍是 agent（LLM 推理） |
| **while 循环** | LLM orchestrator prompt 中的 LOOP | Python `while cp.status == "running"` | 确定性逻辑 |

### 改什么、不改什么

**改：**
- `precision_debug.py:_actions_legacy()` — 不再 spawn `ascendc-precision-debugger` orchestrator agent，改为在 stage 内部用 Python while 循环直接执行 debug workflow
- 子 agent (diagnose/fix/printf_location) 的输出解析 — 从 `RESULT:` 文本协议改为 JSON Schema 校验（低风险附带改进）
- 兜底 `debug_result.json` — 异常终止时 Python 循环写 partial result（含 best_commit/max_diff/failing_cases），不让 transition 读到空文件就 halt

**不改：**
- 子 agent 的 agent definition（`ascendc-precision-diagnose/fix/printf-locate`）— 它们的能力不变
- `checkpoint.json` 文件接力机制 — 当前机制工作正常（子 agent 正确读写 checkpoint），只是在 orchestrator 层有读取频率过高的问题
- `stage-transition.py` 的过渡逻辑 — 保留为 Python 代码后可直接内联
- SDK 层的 Agent 异步语义 — 不改变 SDK，Python `await spawn()` 本身就是正确的异步等待模式

---

## 三、实现方案

### 3.1 改动范围

所有改动集中在 `src/ascendc_devkit/orchestration/stages/precision_debug.py`，不新增类 / 文件 / Workflow 引擎。

### 3.2 核心流程

```python
# precision_debug.py 中的新逻辑（伪代码，核心路径）

async def _run_debug_workflow(state, working_dir, repo_root, max_rounds, ct):
    """Python while 循环替代 LLM orchestrator agent 的 LOOP。"""
    checkpoint = _init_checkpoint(state, working_dir)
    had_progress = False

    while checkpoint.status == "running":
        next_stage = _stage_transition(checkpoint, max_rounds)

        if next_stage == "run_tests":
            result = run_precision_cases(
                state.op_spec, state.test_cases, state.npu_id,
                state.golden_contract, state.deploy_result, ct,
            )
            _update_checkpoint_from_test_result(checkpoint, result)
            had_progress = True

        elif next_stage == "diagnose":
            result = await _spawn_and_wait(
                agent_type="ascendc-precision-diagnose",
                prompt=_build_diagnose_prompt(checkpoint),
                schema=DIAGNOSE_SCHEMA,
            )
            _update_checkpoint_from_diagnose(checkpoint, result)

        elif next_stage == "fix":
            result = await _spawn_and_wait(
                agent_type="ascendc-precision-fix",
                prompt=_build_fix_prompt(checkpoint),
                schema=FIX_SCHEMA,
            )
            _update_checkpoint_from_fix(checkpoint, result)

        elif next_stage == "printf_location":
            result = await _spawn_and_wait(
                agent_type="ascendc-precision-printf-locate",
                prompt=_build_printf_prompt(checkpoint),
                schema=PRINTF_SCHEMA,
            )
            _update_checkpoint_from_printf(checkpoint, result)

        elif next_stage == "finalize":
            break

    return _build_debug_result(checkpoint, had_progress)
```

### 3.3 关键新增函数

**`_spawn_and_wait(agent_type, prompt, schema) -> dict`**

```python
async def _spawn_and_wait(agent_type: str, prompt: str, schema: dict) -> dict:
    """派发子 agent 并真正阻塞等待完成，返回 schema-validated 结构。

    与当前 LLM orchestrator 的关键区别：Python 的 async/await 是真正阻塞的
    ——不产生空转 turn，不积累上下文。SDKBackend._spawn 返回 AgentResult，
    含完整 output text。从 output 中提取 JSON（fallback: 从 RESULT: 行提取），
    并校验 schema。校验失败时自动重试（追加格式提示）。
    """
    for attempt in range(MAX_RETRIES):
        result = await sdk_backend.spawn(agent_type, prompt, ...)
        try:
            return _extract_and_validate(result.output, schema)
        except ValidationError:
            prompt = prompt + _format_hint(schema)  # 追加格式提示重试
    raise AgentOutputError(...)
```

**`_stage_transition(checkpoint, max_rounds) -> str`**

```python
def _stage_transition(checkpoint: dict, max_rounds: int) -> str:
    """Python 内联状态机，替代 stage-transition.py + LLM orchestrator 解读。

    逻辑与当前 stage-transition.py 完全一致（读 checkpoint fields →
    判定下一阶段），不改变状态机语义，仅改执行方。
    """
    ...
```

### 3.4 入口守卫：AI 分析 run_tests 结果，判定是否属于本阶段职责

首轮 `run_tests` + `redeploy` 执行后，用一个轻量 AI 调用分析结果，判定失败的根因类别。判定为"上游产物缺陷"则直接 halt 并写 `debug_result.json`=failed，**不进入 diagnose → fix 循环**。

```python
async def _guard_scope_analysis(
    compile_result: str | None,   # None = 编译通过；非 None = 编译错误
    run_result: dict,             # run_tests 产出的 result.json
) -> str | None:
    """AI 分析首轮 run_tests 结果，判定失败是否在本阶段职责内。
    
    返回 None → 通过守卫，进入 debug 循环。
    返回非 None → 上游问题摘要，halt 并写入 debug_result.json。
    """
    result = await _spawn_and_wait(
        agent_type="ascendc-scope-guard",
        prompt=f"""分析以下 run_tests 结果，判断失败是否属于「精度调试阶段」的职责范围。

## 编译结果
{compile_result or "编译通过，无错误"}

## run_tests 结果（共 {run_result.get('total_count', 0)} 个用例，{run_result.get('failed_count', 0)} 个失败）
{json.dumps(run_result.get('case_details', []), indent=2, ensure_ascii=False)[:8000]}

## 判定规则

**属于本阶段职责**（返回 PASS）：
- 运行时错误（如 507035 vector core exception、UB out of bounds、nullptr 等）→ 很可能是 kernel 代码缺陷
- 精度误差超标 → 数值计算逻辑需要修复
- 输出全 0 / NaN / Inf → 计算路径缺陷

**不属于本阶段职责**（返回 FAIL + 原因 + 该回哪修复）：
- 编译失败 → 源代码语法错误、缺失头文件等，属于 codegen 阶段
- schema 不匹配（Unknown keyword argument / expected at most N but received M）→ op_plugin 的 m.def 或 aclnn L2 API 签名与 golden.py 不一致，属于 codegen 阶段
- golden.py 缺 get_input 致 optional tensor 为空 → golden.py 不完整，属于 codegen 阶段
- 算子注册失败 → CMakeLists.txt 或 def 文件问题，属于 codegen 阶段

## 输出格式
{{
  "verdict": "PASS" | "FAIL",
  "summary": "一句话摘要",
  "upstream_stage": "codegen" | "general_design" | null,
  "detail": "详细原因和修复建议（仅 FAIL 时）"
}}
""",
        schema=SCOPE_GUARD_SCHEMA,
    )
    if result["verdict"] == "FAIL":
        return f"upstream({result['upstream_stage']}): {result['summary']}"
    return None

# 调用：
halt_reason = await _guard_scope_analysis(compile_error, run_result)
if halt_reason:
    _write_debug_result_failed(halt_reason)
    return  # ← halt，不进 debug 循环
```

**为什么用 AI 而非正则匹配：**

| 方式 | 问题 |
|------|------|
| 正则 `"Unknown keyword argument"` | 只能匹配已知错误模板；新错误类型（如 torch 版本差异、不同 cann 版本的报错措辞变化）会漏过 |
| 正则 `"expected at most"` | 组合型错误（部分用例 schema 错 + 部分用例精度错）无法正确判定比例 |
| AI 语义分析 | 读整体 error 分布 + 错误语义，能区分「全是上游问题→halt」vs「混有上游问题和本阶段问题→只标记上游 case、本阶段 case 继续调」vs「全是本阶段问题→正常进入」 |


这些问题的修复不在 precision_debug 范围内（要改 op_plugin.cpp、aclnn API 文件、或 golden.py），precision_debug stage 的职责是**精度/运行时问题定位**。AI 守卫把上游问题挡在循环外，不浪费 agent 预算和时间。

### 3.5 独立防范：harness freshness 检测

```python
def _check_harness_freshness(op_dir: Path, current_devkit_version: str) -> bool:
    """检查 iter-1/harness.py 的生成时间 vs 当前 DevKit 版本时间。"""
    harness = op_dir / ".precision-fix" / "original_backup" / "harness.py"
    if harness.exists() and harness.stat().st_mtime < DEVKIT_BUILD_TIME:
        return False  # harness 由旧版 DevKit 生成，需要刷新
    return True

# 在 _init_checkpoint 中检查，不新鲜 → 强制 redeploy 刷新 harness
```

---

## 四、解决的问题

| 问题 | 是否解决 | 机制 |
|------|:---:|------|
| SDK async dispatch → LLM 空转 + context 爆炸 | ✅ | Python `await spawn()` 真正阻塞，无 LLM 空转 turn，不积累 context |
| 编排器漂移自己做调试 | ✅ | Python 代码不存在 "漂移" — 每个 stage 只执行它被编程的内容 |
| API 401/429 → context 耗尽后全损 | ✅ | Python 循环被中断时 checkpoint.json 保留最后状态，resume 可续跑；不依赖 LLM finalize |
| 子 agent schema 违规（如 `status="fixed"`） | ✅ | Python 校验后自动纠正 / retry |
| stale harness 致不可修 | ✅ | 独立防范点（3.5），不影响主流程 |
| diagnose 诊断能力 | — 不变 | 仍是 LLM agent，能力边界不变 |
| fix 修复能力 | — 不变 | 仍是 LLM agent，能力边界不变 |
| 上游产物缺陷（编译失败、schema 不匹配） | ✅ | 入口守卫（§3.4）在进入 debug 循环前检查编译 + schema 一致性，命中则 halt + 写明原因 |

---

## 五、不改的部分及其原因

以下是原方案中不做的事情，以及原因：

| 不做的 | 原因 |
|--------|------|
| **新建 `PrecisionDebugWorkflow` 类** | 改动只在 `precision_debug.py` 单文件内，不需要新抽象层 |
| **`DebugCheckpoint` dataclass 替换 checkpoint.json** | 当前 JSON 文件接力机制工作正常（子 agent 正确读写），问题仅在 orchestrator 层读取频率过高。Python while 循环不反复读取，不需要改变 I/O 模型 |
| **四阶段迁移计划** | 核心改动是 `_actions_legacy()` 内的 ~100 行，不需要多月迁移。保留 `ascendc-precision-debugger` 的旧路径作为 feature flag 开关即可 |
| **Gate 1 + Gate 2 并行** | 这是 diagnose agent 的内部优化，与编排层无关。可在子 agent 内部独立实现 |
| **内存态 checkpoint** | 增加了跨 run 恢复的复杂度（进程崩溃丢状态），当前文件 checkpoint 配合 JSON 已足够可靠 |

---

## 六、改动量估算

| 改动 | 文件 | 行数 |
|------|------|------|
| `_actions_legacy` 改 `_actions_legacy_v2` + feature flag | `precision_debug.py` | ~30 行 |
| `_run_debug_workflow` async while 循环 | `precision_debug.py` | ~60 行 |
| `_spawn_and_wait` + schema 校验 + retry | `precision_debug.py` | ~40 行 |
| `_stage_transition` Python 内联 | `precision_debug.py` | ~30 行 |
| `_init_checkpoint` + harness freshness 检测 | `precision_debug.py` | ~20 行 |
| 入口守卫：AI 分析 run_tests 结果判定职责范围 | `precision_debug.py` | ~40 行 |
| SCOPE_GUARD_SCHEMA 常量 | `precision_debug.py` | ~15 行 |
| DIAGNOSE_SCHEMA / FIX_SCHEMA / PRINTF_SCHEMA 常量 | `precision_debug.py` | ~40 行 |
| 子 agent prompt 加入 "输出 JSON" 指令 | 各 agent `.md` | ~5 行/个 |
| 删除旧路径（收口步） | `ascendc-precision-debugger.md` | 删除或标记 deprecated |

**总计**：`precision_debug.py` 约 +240 行，子 agent prompt 约 +15 行，新增 1 个 scope-guard 子 agent。单文件改动，无新类/新文件。
