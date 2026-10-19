# Codegen Stage 流程介绍

## 概览

`src/ascendc_devkit/orchestration/stages/codegen.py` — 从设计规约生成 AscendC 算子代码的编排 Stage，属 L3 编排层。

职责：接收上游设计产物（`design_spec`、`tiling_strategy`、`kernel_architecture` 等），驱动 AI agent 生成完整的算子代码（host、kernel、API、plugin），并闭环编译验证。

---

## 双路径架构

根据芯片编程模型（`chip_programming_model`）路由为两条互斥路径：

| 路径 | 芯片模型 | 模式 | 架构 |
|------|---------|------|------|
| **Membase** | A2/A3 | `new` / `incremental` | 单 agent 一次生成 |
| **Regbase** | A5 | 仅 `new` | 三阶段状态机（s2→s4→s5） |

---

## Membase 路径（传统模式）

### 流程

```
actions() ──→ SpawnAgent (ascendc-coder / incremental-developer)
                  │
                  ▼
             agent 生成代码 + codegen_manifest.json
                  │
                  ▼
          agent 在会话内闭环 redeploy (ascendc-devkit redeploy)
                  │
                  ▼
transition() ──→ 校验产出 → 更新状态
```

- **单 agent 模式**：`ascendc-coder`（新增）或 `incremental-developer`（存量改造）
- prompt 包含设计产物路径、编码规则、仓库调用协议、build 闭环指令
- agent 须自行在会话内完成 `ascendc-devkit redeploy` --workspace 闭环
- `transition` 读取 `last_deploy.json`，检查 `smoke_passed`

---

## Regbase 路径（多步编排状态机）

### 完整状态机

```
                                    ┌── 首次进入 ──┐
                                    │              │
                                    ▼              │
 ┌───────────────────────────────────────────────────────┐
 │  s2: 分析阶段 (ascendc-dev-s2-analysis)               │
 │                                                        │
 │  成功 ──────────────────────────────────────────────→ s4 │
 │  (coding_index.md + progress.md expand-kernel 验证通过)  │
 │                                                        │
 │  失败 ─→ 重试 (stage4_selfcheck 计数器 ≤8) ──→ 仍为 s2 │
 │          ↓ 计数器耗尽                                   │
 │          exhausted, halt ──→ ✘ 终止（人工介入）         │
 └───────────────────────┬───────────────────────────────┘
                         │ s2 成功
                         ▼
 ┌───────────────────────────────────────────────────────┐
 │  s4: 编码阶段 (stage4_scheduler.sh 驱动 sub-stage)    │
 │                                                        │
 │  dispatch 返回值:                                       │
 │   finish ──────────────────────────────────────────→ s5 │
 │   call_s4 / call_vf_test ──→ 派发 agent ──→ 仍为 s4   │
 │   retry_s4 ──→ 推进下一 sub-stage（计数器未耗尽）       │
 │   rollback_s4 ──→ 计数器耗尽/设计错误 ──→ 回退 s2      │
 │   paused ──→ 挂起报错（env 错误恒 pause）──→ ✘ 终止    │
 │   call_agent ──→ NEEDS_AGENT (外部 agent) → 完成后回 s4│
 │   rollback_stage ──→ 回退到指定 sub-stage, 仍为 s4     │
 │   vf_exhausted ──→ VF 预验证耗尽, 标记⚠️继续, 仍为 s4  │
 └───────────────────────┬───────────────────────────────┘
                         │ s4 完成 (所有 sub-stage DONE)
                         ▼
 ┌───────────────────────────────────────────────────────┐
 │  s5: 编译阶段 (ascendc-dev-s5-compile)                 │
 │                                                        │
 │  编译前检查:                                            │
 │   ├─ 源文件不存在 ──→ 设 phase=done + error ──→ ■ 终止│
 │   └─ 源文件存在 ──→ 派发 s5-compile agent              │
 │                                                        │
 │  agent 返回 ok + artifacts:                            │
 │   ├─ CMakeLists.txt 缺失 ──→ _handle_regbase_failure   │
 │   │    (error_type=INP) ──→ 进入 retry/rollback 链路   │
 │   ├─ manifest 缺失/无效 ──→ done + error ──→ ■ 终止   │
 │   ├─ torch_op 契约违规  ──→ done + error ──→ ■ 终止   │
 │   ├─ symbol 冲突       ──→ done + error ──→ ■ 终止   │
 │   ├─ 缺 last_deploy.json─→ _handle_regbase_failure     │
 │   │    (error_type=ENV) ──→ 进入 retry/rollback 链路   │
 │   ├─ smoke_passed ──→ done + 成功 ──→ ✓ 完成           │
 │   └─ smoke 失败 ──→ _handle_regbase_failure            │
 │        (error_type=CK) ──→ 进入 retry/rollback 链路     │
 │                                                        │
 │  agent 返回非 ok / 无 artifacts:                       │
 │   ├─ NEEDS_AGENT ──→ 派发外部 agent → 完成后回 s5      │
 │   └─ 其他失败 ──→ _handle_regbase_failure(s5):         │
 │         重试 (stage5_compile 计数器 ≤24次) ──→ 仍为 s5 │
 │          ↓ 计数器耗尽                                   │
 │         回退 s4（受 s5_rollback 预算 ≤2 约束防乒乓，    │
 │           s5 成功后预算重置；预算耗尽 → halt ──→ ✘ 终止）│
 └───────────────────────┬───────────────────────────────┘
                         │ s5 成功 (smoke_passed)
                         ▼
 ┌───────────────────────────────────────────────────────┐
 │  phase=done (codegen 完成)                              │
 │                                                        │
 │  ├─ ✓ 成功: deploy.smoke_passed=true                    │
 │  ├─ ■ 有产出但失败: 校验不通过 (manifest/missing/deploy)│
 │  └─ ✘ exhausted/halt: 重试耗尽, error_type=exhausted   │
 │                                                        │
 │  所有 done 状态 actions() 返回 [] (空), stage 终止      │
 └───────────────────────────────────────────────────────┘

 错误处理（per-type 计数器，无全局加权累计）:
   Layer 0: 读取 meta.json retries 计数器
   Layer 1: 单类重试（计数器未耗尽即同 phase 重试）
     stage5_compile ≤24 / stage4_selfcheck ≤8 /
     vf_test ≤4 / stage3_ambiguity ≤3
   Layer 2: 计数器耗尽后按阶段确定性升级:
     s2 耗尽 → exhausted, halt（人工介入）
     s4 耗尽 → rollback_s4 → 回退 s2（设计可能是根因）
     s5 耗尽 → 回退 s4（s5_rollback 预算 ≤2，成功后重置；
               预算耗尽 → halt）
   类别特判: ENV* 恒 pause；DSG/DS-ALG/KBD 恒回退 s2；
             CK-VF 耗尽 → vf_exhausted 标⚠️继续
```

### Phase 详解

#### s2（分析阶段）

**agent**: `ascendc-dev-s2-analysis`

- 读取设计 JSON 与 Markdown 详设
- 产出 `coding_index.md`（步骤索引）、`coding_plan.md`（编码计划）
- 验证 `expand-kernel` 生效（`progress.md` 中 "4.C Kernel 实现" 被展开为子步骤）
- **正常** → phase 切到 `s4`；**失败** → 重试（stage4_selfcheck 计数器 ≤8）→ 耗尽 halt

#### s4（编码阶段）

**调度器**: `stage4_scheduler.sh` 驱动 sub-stage 推进

sub-stage 分类：

| 类型 | 示例 | agent |
|------|------|-------|
| 普通编码步骤 | `4.A`, `4.B1`, `4.B2`, `4.C.*`, `4.E`, `4.F` | `ascendc-dev-s4-coding` |
| VF 步骤 | `4.C.3.VT.0` | `ascendc-vf-test-agent` |

sub-stage 调度状态机：

```
dispatch 返回值:
  finish         → phase 切到 s5
  call_s4        → 派发 s4-coding agent
  call_vf_test   → 派发 vf-test-agent
  retry_s4       → 推进到下一 sub-stage（per-type 计数器未耗尽）
  rollback_s4    → 计数器耗尽/设计错误 → 回退 s2 重做设计
  paused         → 挂起并报错（env 错误恒 pause）
  call_agent     → NEEDS_AGENT 暂存（派发外部 agent）
  rollback_stage → 回退到指定 sub-stage
  vf_exhausted   → VF 预验证耗尽，标记⚠️继续
```

#### s5（编译阶段）

**agent**: `ascendc-dev-s5-compile`

- 编译前检查源文件是否存在
- agent 编译出包 + 会话内 redeploy
- 校验 `codegen_manifest.json`（含 `callable_target`）
- 校验 `last_deploy.json`（`smoke_passed`）
- 通过 → `phase=done`；失败 → 重试（stage5_compile ≤24）→ 耗尽回退 s4
  （s5_rollback 预算 ≤2，s5 成功后重置）

### 错误处理（per-type 计数器）

```
错误 → Layer 0: 读 meta.json retries 计数器
     → Layer 1: 单类重试（计数器未耗尽即同 phase 重试）
         stage5_compile ≤24 / stage4_selfcheck ≤8 /
         vf_test ≤4 / stage3_ambiguity ≤3
     → Layer 2: 计数器耗尽后按阶段确定性升级
         ├─ s2 耗尽: exhausted, halt（人工介入）
         ├─ s4 耗尽: rollback_s4 → 回退 s2（设计可能是根因）
         └─ s5 耗尽: 回退 s4（s5_rollback 预算 ≤2，
                    成功后重置；预算耗尽 → halt）
类别特判:
  ENV* 恒 pause（人工修复环境，不回退）
  DSG/DS-ALG/KBD 恒回退 s2（设计错误不重试编码）
  CK-VF 耗尽 → vf_exhausted 标⚠️继续
```

---

## Agent 返回信号与编排层决策映射

下表说明各 agent 返回的语义信号，以及 `codegen.py` 如何据此完成阶段跳转。

| 当前阶段 | Agent | 关键返回信号 | 编排层处理 |
|----------|-------|--------------|-----------|
| Membase | `ascendc-coder` / `incremental-developer` | 会话内完成 `ascendc-devkit redeploy` | `_transition_membase()` 读取 `last_deploy.json.smoke_passed` + 校验 `codegen_manifest.json` |
| s2 | `ascendc-dev-s2-analysis` | `status=COMPLETED, next_stage=4` | `_transition_regbase_s2()` 校验 `coding_index.md` + `expand-kernel` 后设 `codegen_phase="s4"` |
| s4 | `ascendc-dev-s4-coding` | `status=COMPLETED, next_sub_stage={下一个子步骤}` | `_transition_regbase_s4()` 调用 `stage4_scheduler.sh dispatch` 决定下一子步骤 |
| s4 | `ascendc-dev-s4-coding` | `next_sub_stage=DONE` | `_complete_regbase_s4()` 校验仓库调用协议后设 `codegen_phase="s5"` |
| s4 (VF) | `ascendc-vf-test-agent` | `status=COMPLETED` | 父编排器继续 s4 下一子步骤（下一个 `.VT.{M}` 或回到 s4-coding） |
| s5 | `ascendc-dev-s5-compile` | `status=ok` + 产物 + redeploy 通过 | `_transition_regbase_s5()` 校验后设 `codegen_phase="done"` |

**注意**：
- 除 Membase 单 agent 路径外，Regbase 各 agent 的 `next_stage` 仅作为参考信号，**实际阶段跳转由编排层根据文件产物、per-type 重试计数器和调度脚本决策**。
- 复杂回退（s4 计数器耗尽回退 s2、s5 计数器耗尽回退 s4）由 `_handle_regbase_failure()` / dispatch 的 `rollback_s4` 统一维护，**不依赖 agent 返回的 `rollback_target`**。

---

## 公共机制

### Circuit Breaker（熔断器）

- `max_consecutive_failures = 3`
- 连续硬 agent 失败（非 `ok` 状态）触发 → 返回空 actions，stage 终止
- `rerun` 重置

### 输入物化（Materialize Inputs）

在 `actions()` 中将上游设计产物写入 staging 目录（`artifacts/staging/`）：

```
design_spec.json
tiling_strategy.json
kernel_architecture.json
tiling_results.json
general_design.json
template_division.json
requirement.json
test_cases.json
known_issues.json
meta.json          ← 编程模型/芯片型号/soc_version
ref_*.cpp          ← 参考代码
```

### Prompts 构造

- Membase: `_build_codegen_prompt()` — 单 prompt 含全部上下文
- Regbase: 按 phase 分别构造（`_build_s2_prompt` / `_build_s4_prompt` / `_build_vf_prompt` / `_build_s5_prompt`）

### 产出校验

- `generated_sources`: 完整源代码
- `codegen_manifest.json`: 算子签名（含 `callable_target.kind` + `.symbol`）
- `build_result`: 编译结果
- `deploy_result`: 部署烟雾测试结果
- `codegen_iterations`: 迭代次数

### 仓库调用协议

`profile.scaffolding.selected` 是调用协议的唯一权威源：

- `torch_op`: 必须生成 `op_plugin/*.cpp` + `TORCH_LIBRARY_FRAGMENT` + `m.def`
- agent 不得覆盖 `callable_target.kind`，`transition` 强制注入 profile 值

---

## 文件组织结构

```
codegen.py
├── Stage 定义（CodegenStage）
│   ├── name / description / default_max_iterations
│   ├── input_contract / output_contract / artifact_contract
│   ├── validate_inputs
│   ├── actions             ← 入口：路由到 Membase / Regbase
│   ├── transition          ← 入口：路由到 Membase / Regbase
│   └── rerun_reset_fields / rerun_reset_files
│
├── 公共辅助方法
│   ├── _json_text / _bash / _profile_scaffolding_kind
│   ├── _expected_code_files / _required_codegen_sections
│   ├── _plugin_sources / _resolve_torch_registration
│   ├── _torch_plugin_contract_error
│   ├── _materialize_inputs
│   ├── _persist_sources / _read_deploy_result
│   ├── _warn_manifest_name_drift / _check_plugin_schema_consistency
│   └── _inject_scaffolding_kind
│
├── Membase 路径
│   ├── _actions_membase
│   ├── _transition_membase
│   └── _build_codegen_prompt
│
├── Regbase 路径
│   ├── Regbase 辅助
│   │   ├── _regbase_record_dir
│   │   ├── _regbase_skill_root / _regbase_agent_root
│   │   ├── _regbase_scripts_dir / _regbase_vf_ref_dir
│   │   ├── _regbase_ensure_init
│   │   ├── _is_vf_step / _first_vt_in_group
│   │   └── _update_meta_retries
│   │
│   ├── actions 子路由
│   │   ├── _actions_regbase        ← 主入口
│   │   ├── _actions_regbase_s2     ← s2: 分析
│   │   ├── _actions_regbase_s4     ← s4: 编码（含 sub-stage 调度）
│   │   │   ├── _actions_regbase_s4_step  ← 普通编码
│   │   │   └── _actions_regbase_vf       ← VF 验证
│   │   ├── _actions_regbase_s5     ← s5: 编译
│   │   └── _actions_regbase_needs_agent  ← 外部 agent 派发
│   │
│   ├── transition 子路由
│   │   ├── _transition_regbase          ← 主入口
│   │   ├── _transition_regbase_s2
│   │   ├── _transition_regbase_s4       ← dispatch 驱动的复杂逻辑
│   │   ├── _transition_regbase_s5       ← 编译结果校验
│   │   └── _transition_regbase_needs_agent_done
│   │
│   ├── 错误处理
│   │   └── _handle_regbase_failure   ← per-type 计数器重试 + 确定性升级
│   │
│   └── Prompt 构造
│       ├── _build_s2_prompt
│       ├── _build_s4_prompt
│       ├── _build_vf_prompt
│       └── _build_s5_prompt
│
└── 常量
    ├── RETRY_LIMITS
    └── S5_ROLLBACK_LIMIT
```
