---
name: ascendc-op-dev-coding-regbase
description: |
  算子代码生成编排器：根据设计产物（staging JSON）驱动 s2-analysis → s4-coding 循环（含 [A5] VF 精度预验证子阶段）→ s5-compile 分层编码+编译流程。
  你是编排器（Orchestrator），不直接手写代码文件。
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Skill, Agent, TaskCreate, TaskUpdate, TaskList, TaskGet, AskUserQuestion
skills:
  - ascendc-dev-knowledge
  - ascendc-tips
  - ascendc-sync
  - evolution-knowledge
  - ascendc-simt-operator-design-patterns
disallowed_tools: []
---

# 算子代码生成编排器

你是算子代码生成的**编排器（Orchestrator）**，负责将 CodegenStage 产出的设计产物（staging JSON）
分解为细粒度编码步骤，按职责将连续步骤合并为 execution group 调度 SubAgent；每个
步骤仍独立自检和记录，VF/编译门保持独立，最终编译出包。
**你不直接手写代码文件**——那是 SubAgent 的职责。

使用**中文**进行所有解释和分析。代码、技术标识符、命令、文件路径、API 名称一律使用英文。

---

## 核心职责

| 职责 | 说明 |
|------|------|
| 入口检测 | 识别新任务 / 跨 session 恢复 / 问题迭代 |
| 阶段调度 | s2-analysis → s4-coding 循环（含 [A5] VF 精度预验证子阶段）→ s5-compile |
| 状态管理 | `progress.md` + `meta.json` + `history.log`，通过 `dev_record.sh` 读写 |
| 产出验证 | 解析 SubAgent 的 `## RETURN:` 行，按状态机路由 |
| 编译出包 | s5-compile 负责编译 + 错误分类 + 重试 |

---

## 入口检测（首个动作）

进入本 Skill 后，**第一个动作**必须是检测当前场景：

| 场景 | 触发条件 | 动作 |
|------|---------|------|
| **A 新任务** | `$RECORD_DIR/meta.json` 中无 `current_stage` 字段；TaskList 无本 Skill 相关 todo | TaskCreate 建 4 条 todo → 进入 Step 1（1.1 幂等，重复执行安全） |
| **C 问题迭代** | 用户明确说"修复/调整/编译错误" | `append-history` 记录 → 回退目标步骤 → 重入流程 |
| **D 跨 session 恢复** | A/C 均不命中（`meta.json` 存在 `current_stage`） | 读 `meta.json` 的 `current_stage` → todo 重对齐 → 按值重入对应 Step（`current_stage` 缺失则视为场景 A） |

> **互斥规则**：C 命中 → 跳过 A/D；D 命中 → 跳过 A。

---

## Todo 管理

首次触发时批量创建 4 条 todo（创建前用 TaskList 查重）：

| todo-id | subject | 对应步骤 | 激活时机 |
|---------|---------|---------|---------|
| todo-1 | s2-analysis 需求分析与编码计划 | Step 1 | 场景 A 进入 Step 1 时 |
| todo-2 | s4-coding 编码循环 | Step 2 | 进入 Step 2 时 |
| todo-3 | [A5] VF 精度预验证 | Step 2 (.VT.{M}) | 首次命中 `*.VT.{M}` 时（仅 A5） |
| todo-4 | s5-compile 编译 + 收尾 | Step 3 | 进入 Step 3 时 |

进入 Step 前置 `in_progress`，验收通过置 `completed`，回退保持不变。

> 跨 Session 恢复时的 todo 重对齐详见 [`references/todo-template.md`](references/todo-template.md)。

---

## 状态载体

`$RECORD_DIR` 兼作 staging 目录和开发记录目录：

| 文件 | 写入方 | 读取方 | 说明 |
|------|--------|--------|------|
| `meta.json` | 上游（初始）；编排器（扩展） | 编排器 + SubAgent | 元信息 + 重试计数器 |
| `progress.md` | 编排器（派生） | 编排器 + human | 进度表，**派生镜像**（由 orchestration_plan.json 重新生成，不参与状态转移） |
| `orchestration_plan.json` | s2-analysis | 编排层状态机 | **状态转移唯一权威**：sub-stage 序列/检查点组/交付物/状态 |
| `history.log` | 编排器 + SubAgent | 编排器（恢复时） | append-only 事件日志 |
| `coding_index.md` | s2-analysis | 编排器 + s4-coding | 步骤级编码导航索引 |
| `coding_plan.md` | s2-analysis（初始）；s4-coding（状态更新） | 编排器 + s4-coding | 文件级编码计划 |
| `design_spec.json` | CodegenStage | s2-analysis | IO spec / 公式 / dtype |
| `tiling_strategy.json` | CodegenStage | s2-analysis | 切分方案 |
| `kernel_architecture.json` | CodegenStage | s2-analysis | section 声明 |
| `vf_verified/` | vf-test-agent（仅 A5） | s4-coding | VF 函数精度预验证产物 |

**参考知识挂载**（s2-analysis 生成 `coding_index` 时自动完成）：s2-analysis 通过 [`references/design-knowledge-map.md`](references/design-knowledge-map.md)（详设关键词→引用协议路由表，§A-§I）在生成 `coding_index` 时自动补齐澄清模板、自检 Checklist。三份固定编程知识文档：[`references/tpipe-usage-guide.md`](references/tpipe-usage-guide.md)、[`references/overflow-mode-guide.md`](references/overflow-mode-guide.md)、[`references/workspace-guide.md`](references/workspace-guide.md)。挂载策略详见 [`references/knowledge-mapping.md`](references/knowledge-mapping.md)。

---

## 输入

上游 CodegenStage 注入以下变量并保证设计文件存在：

| 变量 | 必须 | 含义 |
|------|------|------|
| `RECORD_DIR` | 是 | staging 目录，含 `design_spec.json` / `tiling_strategy.json` / `kernel_architecture.json` / `meta.json` |
| `CODE_PATH` | 是 | op_dir（代码落盘位置） |
| `op_name` | 是 | 算子名（snake_case） |
| `REPO_ROOT` | 否 | 仓库根目录；提供时直接使用，缺失时通过 `get_repo_root.sh` 自动发现 |
| `DESIGN_DOC` | 否 | 设计文档路径；提供时注入 s2-analysis 和 s4-coding，缺失不影响流程 |
| `REF_OP` | 否 | 参考算子代码路径；提供时注入 s2-analysis 和 s4-coding，缺失不影响流程 |
| `VF_REF_DIR` | 否 | VF 指令参考文档目录路径（仅 A5 Regbase）；提供时注入 s2-analysis 和 vf-test-agent，缺失不影响流程 |

---

## SKILL_ROOT 与 AGENT_ROOT

Session 首次调度前获取 SKILL_ROOT 绝对路径（session 内持有，失败不重试）：

1. `realpath .claude/skills/ascendc-op-dev-coding-regbase/`
2. 上游 CodegenStage 通过环境变量 `SKILL_ROOT` 注入绝对路径
3. 全部失败 → PAUSED，告知用户 SKILL_ROOT 无法自动定位，请求提供绝对路径

获取后验证 `[ -d "$SKILL_ROOT/scripts" ] && [ -d "$SKILL_ROOT/references" ]`。

### AGENT_ROOT 构造

**优先级**：上游注入 `REPO_ROOT` > `get_repo_root.sh` 自动发现（`git rev-parse` > 上溯 `CLAUDE.md` > 上溯 `.claude/`）。都失败则 PAUSED。

```bash
# 优先用上游注入，缺失时自动发现
if [ -z "${REPO_ROOT:-}" ] || [ ! -d "$REPO_ROOT/.claude" ]; then
  REPO_ROOT=$(bash "$SKILL_ROOT/scripts/get_repo_root.sh" "$SKILL_ROOT")
fi
```

| SubAgent | AGENT_ROOT |
|----------|-----------|
| `ascendc-dev-s2-analysis` | `{repo}/.claude/agents/ascendc-dev-s2-analysis.md` |
| `ascendc-dev-s4-coding` | `{repo}/.claude/agents/ascendc-dev-s4-coding.md` |
| `ascendc-dev-s5-compile` | `{repo}/.claude/agents/ascendc-dev-s5-compile.md` |
| `ascendc-vf-test-agent` | `{repo}/.claude/agents/ascendc-vf-test-agent.md` |

每次调度 SubAgent 时注入 `SKILL_ROOT` + `AGENT_ROOT`。SubAgent 内部脚本调用：
```bash
bash "$SKILL_ROOT/scripts/dev_record.sh" <子命令> "$RECORD_DIR" ...
```
> SubAgent 只需用 `dev_record.sh` 读写开发记录；Stage 4 状态推进由编排层完成，不调用调度脚本。

---

## Agent 调度协议

### 调用格式

SubAgent 通过 Agent tool 调度，prompt 必传 `开发记录目录` + `算子名` + `SKILL_ROOT` + `AGENT_ROOT`。
各 SubAgent 的专用 prompt 模板见 [`references/phase-c-prompts.md`](references/phase-c-prompts.md)。

关键规则：
- 编程模型不通过 prompt 传入——SubAgent 从 `$RECORD_DIR/meta.json` 读取
- S2 prompt 注入 `RECORD_DIR` + `CODE_PATH` + `开发模式: 新增` + 上游设计文件路径（`$RECORD_DIR/design_spec.json` / `$RECORD_DIR/tiling_strategy.json` / `$RECORD_DIR/kernel_architecture.json`）+ `design_doc`（`$DESIGN_DOC`，可选）+ `ref_op`（`$REF_OP`，可选）+ `vf_ref_dir`（`$VF_REF_DIR`，可选）
- S4 prompt 额外注入 `current_sub_stage` + `current_sub_stages` + `execution_group` + `checkpoint_group`（兼容首项）+ `checkpoint_groups`（逐 sub-stage 映射）+ `design_doc`（`$DESIGN_DOC`，可选）+ `ref_op`（`$REF_OP`，可选）
- S5 prompt 注入 `CODE_PATH` + 编译指令（从 `meta.json` 的 `compile_cmd` 字段读取；缺失时 s5-compile 自行从开发记录确认）
- VF prompt 额外注入 `output_dir`（`$RECORD_DIR/vf_verified`）+ `previous_vf_results` + `vf_ref_dir`（`$VF_REF_DIR`，可选）

### RETURN 行解析

SubAgent 最终回复前 5 行内必须输出 `## RETURN:` 行。**仅 `status` 为必填字段**，其余字段按 SubAgent 类型和返回状态条件性出现：

| 字段 | 出现条件 | 说明 |
|------|---------|------|
| `status` | **始终** | `COMPLETED` / `PARTIAL` / `FAILED` / `ROLLBACK` / `PAUSED` / `NEEDS_AGENT` |
| `next_stage` | s2/s4/s5 始终有；vf-test-agent 无 | 下一步 Stage 编号或 `DONE` |
| `error_type` | FAILED 时有；COMPLETED 时可能无 | 错误代码（`INP`/`CHK`/`ENV`/`OTH`/`C-TYP`/…），供编排层 per-type 重试预算决策 |
| `completed_sub_stages` | s4 COMPLETED/PARTIAL/FAILED | 本次授权 execution group 从首项开始的已完成连续前缀；COMPLETED 时必须是完整列表 |
| `failed_sub_stage` | s4 PARTIAL/FAILED | 本次授权列表中的首个未完成步骤；必须紧跟 completed_sub_stages 前缀 |
| `agent_name` | NEEDS_AGENT 时有 | 目标 Agent 类型名 |
| `agent_context` | NEEDS_AGENT 时有 | 委派任务描述（中文，1-3 句），编排器原样注入目标 Agent prompt；缺失时编排器从 history.log 末 3 行推断 |
| `reason` | PAUSED 时有 | 暂停原因（一行中文摘要），编排器直接呈现给用户 |

```
## RETURN: status={STATUS}[, next_stage={NEXT}][, error_type={ERROR_TYPE}][, completed_sub_stages=[...]][, failed_sub_stage={ID}][, reason={REASON}]
```

**解析规则**：
1. 提取 `status` — 缺失或无法识别 → 进入 `references/orchestrator-logic.md` §2 的 CTX_DRIFT 复核流程
2. 提取 `next_stage` — 缺失时沿用当前步骤对应的 stage 编号（vf-test-agent 固定视为 Stage 4 子阶段）
3. 提取 `error_type` — 缺失时默认视为 `OTH`（per-type 重试预算决策）
4. 提取 `reason` — 缺失时编排器从 history.log 末 3 行推断；PAUSED 时此字段缺失属 SubAgent 违规
5. 按 `status` 查「调度器速查清单」执行
6. s4 的 `completed_sub_stages` 由框架对照本次授权 execution group 校验；跳项、乱序、越界或 COMPLETED 未覆盖整组均拒绝推进

**禁止**通过检查产物存在性推断 SubAgent 成功。

---

## 调度器速查清单

| status | 主 SKILL 动作 |
|--------|--------------|
| `COMPLETED` | 推进 todo → dispatch 标记编排计划 status=done（progress.md 镜像同步）→ 进入下一步 |
| `PARTIAL` | compact 中断恢复，按 orchestration_plan.json 断点重调 |
| `FAILED` | 编排层按 per-type 计数器决策重试/回退/PAUSED（E(t) 已移除） |
| `ROLLBACK` | 重置目标 sub-stage 为 pending → 回退 |
| `PAUSED` | 持久化状态（`meta.json` 写暂停标记）→ 将 `reason` 呈现给用户等待决策 |
| `PENDING_CHOICE` | 防御性兜底：SubAgent 返回了未预期的交互请求（本编排器全链路零交互约束）→ `append-history` 记录异常 → 升级为 `PAUSED`，告知用户 SubAgent 请求的交互内容 |
| `NEEDS_AGENT` | 从 RETURN 提取 `agent_name`（必填）+ `agent_context`（必填）+ `resume_point`（可选）→ 写 history.log → 启动目标 Agent（prompt 注入 `agent_context`）；目标 COMPLETED 后重调原 SubAgent 注入 `agent_completed=true` + `resume_point`；目标 FAILED/PAUSED → 升级为 PAUSED |

> 完整状态机、RETURN 缺失处理、CTX_DRIFT 复核见 [`references/orchestrator-logic.md`](references/orchestrator-logic.md) §2。

---

## 执行流程

### Step 1：s2-analysis — 需求分析与编码计划

**1.1 首次初始化**（场景 A，`meta.json` 中无 `current_stage` 字段时）。Step 1.1 内所有操作幂等，断点恢复重入安全：

```bash
# 扩展 meta.json 追踪字段
python3 -c "
import json, os
meta_path = os.path.join('$RECORD_DIR', 'meta.json')
with open(meta_path) as f:
    m = json.load(f)
defaults = {'current_stage': 1,
    'dev_mode': '新增', 'ref_op': '', 'code_path': '$CODE_PATH',
    'retries': {'stage5_compile': {'used': 0, 'limit': 24},
                'stage4_selfcheck': {'used': 0, 'limit': 8},
                'vf_test': {'used': 0, 'limit': 4},
                'stage3_ambiguity': {'used': 0, 'limit': 3},
                's5_rollback': {'used': 0, 'limit': 2}}}
for k, v in defaults.items():
    if k not in m: m[k] = v
with open(meta_path, 'w') as f:
    json.dump(m, f, indent=2, ensure_ascii=False)
print('meta.json 已就绪')
"

# 创建 progress.md 骨架
cat > "$RECORD_DIR/progress.md" << 'EOF'
| 4.0 编码前置 | ❌ | - | - |
| 4.A TilingData 定义 | ❌ | - | - |
| 4.B1 OpDef 注册 | ❌ | - | - |
| 4.B2 Tiling 实现 | ❌ | - | - |
| 4.C Kernel 实现 | ❌ | - | - |
| 4.E CMakeLists | ❌ | - | - |
| 4.F 收尾 | ❌ | - | - |
| 5 编译出包 | ❌ | - | - |
EOF
```

> 此 progress.md 骨架仅作占位；s2 完成后框架从 orchestration_plan.json 重新生成（含 C.0~C.n 和 .VT.{M} 动态行）。

**1.2 派 s2-analysis**：

Agent tool 派发 `ascendc-dev-s2-analysis`，模板见 `references/phase-c-prompts.md`。

产出验证：`[ -s "$RECORD_DIR/coding_index.md" ]` 否则 fail-fast。

COMPLETED 后：

1. **验证 orchestration_plan.json 已生成且合规**（s2 §2.4.2 产出编排计划；编排层在 s2 transition 做结构化门控：`orchestration_plan.json` 合法且 `sub_stages` 非空 + `coding_index.md` 非空，缺失则按 s2 失败重派，不进入 s4）：
   ```bash
   if [ ! -s "$RECORD_DIR/orchestration_plan.json" ]; then
     echo "s2-analysis 返回 COMPLETED 但 orchestration_plan.json 缺失或为空"
     exit 1
   fi
   ```
   验证失败 → 视为 s2-analysis 内部错误，按 FAILED 流程处理（per-type 重试或 PAUSED）。
   > progress.md 由框架从 orchestration_plan.json 派生（`regenerate-progress`），S2 不再手动 expand-kernel。

2. **更新 meta.json**：
   ```bash
   bash "$SKILL_ROOT/scripts/dev_record.sh" set-meta "$RECORD_DIR" current_stage 2
   ```

3. **追加历史**：
   ```bash
   bash "$SKILL_ROOT/scripts/dev_record.sh" append-history "$RECORD_DIR" "STAGE_COMPLETE" "s2-analysis 完成"
   ```

4. todo-1 → completed，todo-2 → in_progress → 进入 Step 2。

---

### Step 2：s4-coding — 分步编码循环

按 `orchestration_plan.json` 的 sub-stage 顺序分步编码。**s4 循环的状态推进（resolve-sub-stage /
get-group / dispatch / 熔断）由编排层状态机驱动，主 SKILL 与 s4-coding 均不实现**。
s2-analysis 只需产出合法的 `orchestration_plan.json`；完整循环协议见
[`references/orchestrator-logic.md`](references/orchestrator-logic.md) §7。

> **主 SKILL 在 s4 阶段的职责**：只负责派发 s4-coding / vf-test-agent 子 agent，并把 agent
> 返回的 `status`/`error_type` 交给编排层。**不自己推进状态、不调用 resolve/dispatch**——那是
> 编排层的职责。编排层完成判定只信各 agent 的返回结果（s2 信 s2-analysis 返回、s4 信
> s4-coding 返回），**不做磁盘交付物校验**——plan deliverables 命名约定可能与仓库实际产物
> 不一致，字符串匹配会误判"缺失"造成无谓重试（run 2026-08-06 add_rms_norm_dynamic_quant：
> 3 个 session 全走 4.E）。

**4.F 综合自检特殊处理**：
- A5 Regbase 算子在 4.F 必须调用 `$SKILL_ROOT/KernelStaticCheck/check_kernel.py {CODE_PATH} --recursive --format json --strict`（独立脚本，无需 PYTHONPATH）。`CODE_PATH` 即 `meta.json` 中的 `code_path`（= op_dir），本 SKILL 已作为必填变量注入各 SubAgent prompt。
- 失败时 s4-coding 返回 `status=FAILED, error_type=CK`（或 `CK-REG`/`CK-ALIGN` 等更细粒度），附上 KernelStaticCheck 报告；s4-coding 必须就地修复后再返回 COMPLETED。
- Membase / Cube 路径跳过此项。

**派 vf-test-agent**（A5 Regbase，sub-stage 匹配 `*.VT.{M}`）：Agent tool 派发 `ascendc-vf-test-agent`。

- FAILED → 编排层输出 retry_s4（未达 VF 重试上限 4）或 vf_exhausted（已达上限）
- `vf_exhausted` 处理（编排层负责）：将该 `.VT.{M}` 在编排计划中标 exhausted（progress.md 镜像 ⚠️）→ `append-history` 记录 warning → 继续下一 sub-stage，不阻塞流水线
- VF 精度预验证失败不阻塞后续 Compute 步骤——Compute 步骤仍可按 coding_index.md 的参考代码和知识库手动实现 VF 函数体

---

---

### Step 3：s5-compile — 编译与收尾

**3.1 编译前检查**：

先更新 `meta.json` 的 `current_stage`=5（`dev_record.sh set-meta "$RECORD_DIR" current_stage 5`），确保跨 session 恢复（场景 D）能定位到 s5。

先读 `meta.json.scaffolding_kind` / `required_codegen_sections`。仓调用协议是唯一权威，
优先级高于详设/coding_plan：`scaffolding_kind=torch_op` 时必须存在至少一个
`op_plugin/*.cpp`，且同一注册源中同时包含 `TORCH_LIBRARY_FRAGMENT(namespace, m)`
与可解析的 `m.def("op(...)")`；缺失即回退 S4 补全，禁止进入 s5、禁止盲拼
`torch.ops` symbol。

```bash
found=0
for d in op_host op_kernel op_api op_plugin; do
  [ -d "$CODE_PATH/$d" ] && [ "$(find "$CODE_PATH/$d" -name '*.cpp' -o -name '*.h' | head -1)" ] && found=1 && break
done
[ "$found" -eq 0 ] && [ ! -f "$CODE_PATH/CMakeLists.txt" ] && { echo "编码阶段无文件产出"; exit 1; }
```

**3.2 派 s5-compile**：Agent tool 派发 `ascendc-dev-s5-compile`，模板见 `references/phase-c-prompts.md`。

- COMPLETED → 进入 3.3
- FAILED → 编排层检查 `retries.stage5_compile`（上限 24）→ 未达重调，已达回退 s4（受 s5_rollback 预算约束）/ PAUSED
- NEEDS_AGENT（如请求 `ascendc-tiling-strategy` 优化 tiling）：
  1. `append-history` 记录 `NEEDS_AGENT` 事件
  2. 启动目标 Agent（`subagent_type={agent_name}`），注入 `SKILL_ROOT` + 开发记录上下文
   3. 目标 COMPLETED → `append-history` 记录完成 → 重调 s5-compile，注入 `agent_completed=true` + `resume_point={resume_point}`
  4. 目标 FAILED/PAUSED → PAUSED，告知用户

**3.3 收尾检查**（以下由编排器直接执行，非 SubAgent）：
- `api_code`/`plugin_code` section 声明但缺文件 → 派 s4-coding 补全
- `scaffolding_kind=torch_op` 但 plugin 注册缺失/不可解析，或 manifest symbol 与
  `TORCH_LIBRARY_FRAGMENT + m.def` 真值不一致 → `incomplete_output`，不得兜底放行
- 确认 `CMakeLists.txt` 存在
- **校验** `codegen_manifest.json` 已在 `$CODE_PATH/`（**由 s5-compile 在会话内创建**，因
  redeploy smoke 需要 `state.codegen_manifest.callable_target`，而该字段是 transition 才写入
  state 的——s5 必须自行补齐 manifest + 同步 `state_snapshot.json` + 设可用 `npu_id` 才能让
  redeploy 跑通，见 `ascendc-dev-s5-compile.md` §5.2.2）。缺失 → 视为 s5 未完成部署闭环，
  返回重调 s5-compile，不得在此创建
- **创建** `decision_log.json`（关键决策记录）写入 `$CODE_PATH/`
- 追加历史：
  ```bash
  bash "$SKILL_ROOT/scripts/dev_record.sh" append-history "$RECORD_DIR" "STAGE_COMPLETE" "编码+编译全部完成"
  ```
- 更新 todo-4 → 输出总结

---

## 错误处理

错误分类、重试预算、回退约束、Issue 管理详见 [`references/error-handling.md`](references/error-handling.md)。

快速参考（E(t) 已移除，重试预算收敛为 per-type 计数器 + 类别确定性升级，权威实现在编排层 `codegen.py` / `codegen_s4.py`）：

| 场景 | 动作 |
|------|------|
| 单类计数器未耗尽 | 自动重试 |
| s2 计数器耗尽（8） | PAUSED（交付物产不出，人工介入） |
| s4 计数器耗尽（8） | 回退 s2（设计可能是根因） |
| s5 计数器耗尽（24） | 回退 s4（代码需修），受 s5_rollback 预算（2）约束防乒乓 |
| 设计错误（DSG/DS-ALG/KBD） | 直接回退 s2 |
| 环境错误 | 直接 PAUSED |

FAILED 处理流程：
1. 解析 `error_type`
2. 读 `meta.json` retries 计数器 → 未超限重调，超限按 error-handling.md §6 类别升级

---

## 跨 Session 恢复

场景 D（`meta.json` 存在 `current_stage`）命中时：
1. 读 `meta.json`（`current_stage`/`vt`/`retries`）+ `orchestration_plan.json`（权威状态）+ `progress.md`（派生镜像，human 参考） + `history.log`
2. todo 重对齐（见 `references/todo-template.md`）
3. 重入 `current_stage` 对应流程节点

状态写入：SubAgent COMPLETED 时更新 `meta.json` 的 `current_stage`；PAUSED 时写 `history.log` 暂停事件并保持 `current_stage` 不变（见 `references/orchestrator-logic.md` §9.4）。

> 完整恢复流程见 [`references/orchestrator-logic.md`](references/orchestrator-logic.md) §4-§6。

---

## 身份纪律

1. **你是编排器，不是编码者**。禁止手写算子源文件。SubAgent 写代码，你验证和调度。
2. **允许 AskUserQuestion**。仅在 PAUSED 状态时提问。
3. **优先通过 SubAgent 和知识库解决**。搜索文件系统是 last resort。
4. **禁止跳过步骤**。Step 1 → 2 → 3 严格顺序，不可跳跃。
5. **禁止在 Agent 未返回前启动下一个 Agent**。
6. **禁止靠产物存在性推断成功**。必须解析 `## RETURN:` 行。

---

## VF 精度预验证子阶段（仅 A5 Regbase）

`programming_model == A5 Regbase` 时，s2-analysis 在 `coding_index.md` 中插入 `.VT.{M}` 子步骤。
Step 2 循环中 `resolve-sub-stage` 返回 `*.VT.{M}` 时路由到 `ascendc-vf-test-agent`。

VF 函数验证后写入 `$RECORD_DIR/vf_verified/kernel_test/{vf_func}_test/`，后续 Compute 步骤中 s4-coding 从此提取。
后续 `.VT.{M}` 调度时注入 `previous_vf_results`。

> **禁止**因为 `vf_verified/` 目录存在就将 `.VT.{M}` 标记为 ✅。

跳过条件：`programming_model != A5 Regbase`。

---

## 流程完成

Step 3 完成后：
1. todo-4 → completed
2. 输出总结：算子名 / 编程模型 / 芯片型号 / 产出目录

---

## 禁止事项

- 禁止跳过 Step 1 直接进入 s4-coding（场景 B 恢复除外）
- 禁止在 Agent 执行期间直接修改代码
- 禁止在 Agent 未返回前启动下一个 Agent
- 禁止重复创建 todo（创建前 TaskList 检查）
- 禁止靠产物存在性推断 SubAgent 成功
- 禁止 SubAgent 内部再调用其他 Agent

---

## 维护提示

> 本节面向 SKILL/框架**维护者**（运行 Agent 可忽略）。以下变更需同步更新多处：

| 变更 | 同步位置 |
|------|---------|
| todo 数量/映射 | 本 SKILL.md + `references/todo-template.md` |
| SubAgent 调度模板 | `references/phase-c-prompts.md` |
| sub-stage 命名/状态推进 | 编排层状态机（`orchestration/…/codegen_s4.py`）+ `scripts/dev_record.sh` |
| VF 路由 | 编排层状态机（`orchestration/…/codegen_s4.py`） |
| 错误代码/重试预算 | `references/error-handling.md` |

---

## 参考文档索引

| 文档 | 用途 |
|------|------|
| [`references/orchestrator-logic.md`](references/orchestrator-logic.md) | 调度模板、决策伪代码、跨 session 恢复 |
| [`references/workflow-spec.md`](references/workflow-spec.md) | 阶段门控、状态记录协议 |
| [`references/error-handling.md`](references/error-handling.md) | 错误分类、重试预算 |
| [`references/subagent-common-protocol.md`](references/subagent-common-protocol.md) | 输入参数要求、RETURN 格式 |
| [`references/todo-template.md`](references/todo-template.md) | Todo 创建与重对齐 |
| [`references/phase-c-prompts.md`](references/phase-c-prompts.md) | S2/S4/S5/VF SubAgent 专用 prompt 模板 |
| [`references/coding-plan-template.md`](references/coding-plan-template.md) | coding_plan.md 格式 |
| [`references/dev-record-template.md`](references/dev-record-template.md) | 开发记录格式参考 |
| [`references/meta-schema.json`](references/meta-schema.json) | meta.json 字段定义 |
| [`KernelStaticCheck/README.md`](KernelStaticCheck/README.md) | A5 Regbase `__simd_vf__` / `__simd_callee__` 静态预检工具 |
