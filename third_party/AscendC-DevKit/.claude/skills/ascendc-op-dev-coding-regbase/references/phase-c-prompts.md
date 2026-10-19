# Phase C Prompt 模板

> 由 `SKILL.md` Phase C 章节引用。Driver 派发 subagent 时按对应模板注入字段。

## C.2 ascendc-dev-s2-analysis

```
【上下文】
- 算子名: {op_name}，开发模式: 新增
- 开发记录目录: {RECORD_DIR}
- SKILL_ROOT: {SKILL_ROOT}
- AGENT_ROOT: {AGENT_S2}

【需求来源 — 直接使用，不收集】
- 若主 Agent 注入了 design_doc（Markdown 详设路径）→ 优先使用
- 否则 → JSON 模式：设计文件位于 $RECORD_DIR 下
  - design_spec.json — IO spec / 公式 / dtype
  - tiling_strategy.json — 切分方案
  - kernel_architecture.json — section 声明

【预置输入 — 已写入 RECORD_DIR/meta.json 或 prompt 注入，S2 直接读取】
- 编程模型 / code_path / dev_mode / ref_op

【已在主 SKILL 收集的项（可选，缺失不影响流程）】
- design_doc: {DESIGN_DOC}（Markdown 详设路径；提供时优先于 $RECORD_DIR 下 JSON 设计文件作为需求来源）
- vf_ref_dir: {VF_REF_DIR}（仅 A5 Regbase；VF 指令参考文档目录路径；用于 coding_index.md 中 vf-instructions: 前缀引用，缺失时 s2 标记 vf-instructions:xxx 供 S4 自行检索）

【零交互纪律】
- 禁止 AskUserQuestion
- 设计文档无法读取 → status=FAILED, error_type=INP
- 设计文档缺少关键字段，且默认决策表无法覆盖 → status=FAILED, error_type=INP（本编排器无 Stage 3，不存在澄清机制；无法自动决策的设计缺口视为输入不完整）
- 设计文档缺少关键字段，但默认决策表可覆盖 → 标记 [默认决策]，来源填"默认§N: {规则名}"

【建议默认值 — 详设未明确时自动采用，标记 [默认决策]】
| # | 决策项 | 默认值 |
|---|--------|--------|
| 1 | 分核方式 | 单核（blockDim=1） |
| 2 | 核内 tile 策略 | 保守单 tile（不拆分） |
| 3 | tail block 处理 | 连续 mask 截断 |
| 4 | 双 buffer | 关闭（BUFFER_NUM=1） |
| 5 | dtype 支持 | 仅详设明确列出的 |
| 6 | 对齐假设 | 32 字节对齐 |
| 7 | TilingKey 路由 | 单一模板，统一用 ASCENDC_TPL 参数化 |
| 8 | 属性默认值 | int→0, float→0.0, bool→false |
| 9 | workspace 空间 | 用户 workspace 按 tiling 推导（host 计 userWs）；host tiling 函数末尾一律 `ws[0] = userWs + GetLibApiWorkSpaceSize()`（工程模式框架偏移系统区，漏 sysWorkspaceSize → GM 越界 507015，历史实证；禁写死 0/16M） |

> 以上默认值来源于 AscendC 工程经验，非硬件强制约束（#6 除外）。
> 有权威来源（ascendc-tips / ascendc-dev-knowledge）时应优先采用。

    用法：
    - 详设已明确 → 标记 [已澄清]，来源填"详设§x.x"
    - 详设未明确 + 上表可覆盖 → 标记 [默认决策]，来源填"默认§N: {规则名}"
    - 两者都无 → 标记 [默认决策#?]，来源填"兜底"，不产生 [待澄清]；若此缺口会导致代码不可生成（如 IO shape 缺失），返回 FAILED(error_type=INP)

【返回约束】本编排器为 3 阶段流水线（s2→s4→s5，无 Stage 3）。COMPLETED 时必须返回 `next_stage=4`，禁止返回 `next_stage=3`。
```

## C.3 循环机制

```
s4 循环由编排层状态机驱动，主 SKILL 与 s4-coding 均不实现循环、不推进状态：
  - 编排层按 orchestration_plan.json 的 sub_stage 顺序逐个派发 s4-coding / vf-test-agent
  - 每个 sub-stage 完成后，编排层只信 agent 返回的完成信号推进下一（不再校验磁盘交付物）
  - 你只需完成当前 sub-stage 并返回 status / error_type
状态权威源 = orchestration_plan.json（s2-analysis 产出、s4 消费）。
```

## C.3 ascendc-dev-s4-coding

```
【上下文】
- 算子名: {op_name}
- 开发记录目录: {RECORD_DIR}
- SKILL_ROOT: {SKILL_ROOT}
- AGENT_ROOT: {AGENT_S4}
- current_sub_stage: {sub_stage}
- current_sub_stages: [{execution_group_sub_stages}]
- execution_group: {execution_group}
- checkpoint_group: {checkpoint_group}
- checkpoint_groups: [{sub_stage=checkpoint_group, ...}]（逐步骤权威映射；checkpoint_group 仅兼容首项）

【已在主 SKILL 收集的项】
- code_path: {CODE_PATH}（也写入 meta.json.code_path）
- design_doc: {DESIGN_DOC}（可选；Markdown 详设路径，缺失不影响流程）
- ref_op: {REF_OP}（可选；参考算子代码路径，缺失不影响流程）

【零交互约束 — 最高优先级】
- 禁止 AskUserQuestion
- 交互模式固定为 auto（每步不确认，直接完成）

【调度边界 — 每次处理一个 execution group】
- 本次只按顺序处理 `current_sub_stages` 列出的子阶段，禁止越界或处理 `.VT.{M}`
- 每个子阶段仍分别执行编码、自检、写 `selfcheck_<id>.md`；合并会话不合并质量门
- 全部完成后 RETURN `completed_sub_stages=[current_sub_stages 的完整列表]`
- 中途失败时只提交从首项开始的已完成连续前缀，并返回 `failed_sub_stage={首个未完成步骤}`
- `next_sub_stage` 只作审计，实际推进由编排层根据 orchestration_plan.json 决定

【参考来源纪律】
- 从 coding_index.md 参考代码列 + 详设章节（JSON 或 Markdown）+ 知识库模板生成
- 禁止自行全局搜索参考实现
- （仅 A5）进入 C 系列及 VT 步骤前，按 coding_index.md 的 vf-instructions 引用
  查阅 VF 指令参考文档（$SKILL_ROOT/../regbase-vf-test/references/vf-instructions/）
- sub-stage 为 ACLNN API / Plugin 步骤时，参考目标仓现有算子的 aclnn_*.cpp /
  *_plugin.cpp 文件模式生成，遵循仓特定的注册宏与 include 路径

【4.F 综合自检（A5 Regbase 必做）】
- 当 current_sub_stage == "4.F" 时，在返回前调用：
  `python3 "$SKILL_ROOT/KernelStaticCheck/check_kernel.py" "$CODE_PATH" --recursive --format json --strict`（独立脚本，无需 PYTHONPATH）
- 若失败，解析 JSON 报告定位到具体文件/行号，就地修复 `__simd_vf__` / `__simd_callee__` 违规项（inline / ubuf 直接访问 / GM 访问 / hardware-loop 变量类型 / 循环内运行时分支 / UpdateMask 参数 mutation / 函数级运行时分支）。
- 修复后重新运行直到通过；无法修复则返回 FAILED(error_type=CK)。
- Membase / Cube 路径跳过此项。
```

## C.3 ascendc-vf-test-agent（仅 A5 Regbase，sub-stage 匹配 `*.VT.*` 时）

```
【上下文】
- 开发记录目录: {RECORD_DIR}
- 算子名: {op_name}
- current_sub_stage: {sub_stage}
- SKILL_ROOT: {SKILL_ROOT}
- AGENT_ROOT: {AGENT_VF}
- output_dir: {RECORD_DIR}/vf_verified
- previous_vf_results: {列出已完成的 VF 函数路径，首次为空}

【已在主 SKILL 收集的项】
- code_path: {CODE_PATH}
- design_doc: {DESIGN_DOC}（可选；Markdown 详设路径，缺失不影响流程）
- ref_op: {REF_OP}（可选；参考算子代码路径，缺失不影响流程）
- vf_ref_dir: {VF_REF_DIR}（可选；仅 A5 Regbase；VF 指令参考文档目录路径，缺失不影响流程）

【零交互约束】禁止 AskUserQuestion
```

## C.4 ascendc-dev-s5-compile

```
【上下文】
- 算子名: {op_name}
- 开发记录目录: {RECORD_DIR}
- SKILL_ROOT: {SKILL_ROOT}
- AGENT_ROOT: {AGENT_S5}

【编译指令】
- code_path: {CODE_PATH}（也写入 meta.json.code_path）
- 编译指令: {compile_cmd}（从 meta.json 读取；缺失时 s5-compile 自行确认）

【编译前置检查】
- A5 Regbase 算子在每次调用 ccec 前，先执行：
  `python3 "$SKILL_ROOT/KernelStaticCheck/check_kernel.py" "$CODE_PATH" --recursive --format json --strict`（独立脚本，无需 PYTHONPATH）
- 若失败，定位并修复后再进入编译；修复后必须重新跑 KernelStaticCheck 通过才能再次调 ccec。
- 重试循环中每次修改 kernel 代码后都应重新跑 KernelStaticCheck。
- 无法修复则返回 FAILED(error_type=CK)。

【部署闭环（编译通过后必经，禁止跳过）】
- 编译通过后必须在会话内执行 `ascendc-devkit redeploy --workspace <run_dir>`（build → install → smoke）。
  `<run_dir>` 即开发记录目录的上级上级（RECORD_DIR 形如 `<run_dir>/artifacts/staging`）；prompt 注入的
  run_dir 优先。结果写入 `<run_dir>/artifacts/debug/<op>/last_deploy.json`。
- redeploy 的 smoke 依赖 state.codegen_manifest.callable_target，而该字段是 s5 返回后 transition
  才写入 state 的——因此 s5-compile 必须自行补齐部署契约：
  1. 创建 codegen_manifest.json（含 callable_target{kind, symbol}，symbol 与 op_plugin 的
     TORCH_LIBRARY_FRAGMENT + m.def 注册一致）写入 $CODE_PATH/
  2. 同步 <run_dir>/state_snapshot.json 的 codegen_manifest 字段
  3. 调用 `$SKILL_ROOT/scripts/pick_available_card.py` 获取当前可用卡，设置 state_snapshot.json 的
     npu_id（避免 507033）；禁止现场写探测循环，卡问题用脚本 --max-wait 时间窗口内持续重试
     （默认 500s，窗口耗尽仍无卡则返回 FAILED(ENV)；Bash 超时须大于 585s 防误杀）
  4. 执行 redeploy，确认 last_deploy.json 的 smoke_passed=true
- **smoke 失败分流**：redeploy smoke 对 torch_op/pybind 是真实 fn() 调用。若 smoke_passed=false，
  读 `<run_dir>/subprocess/smoke.log` 判断失败阶段：
  - **kernel 已执行（507035/507057/AICORE/aivec/越界文本）**：kernel 已被 launch 并执行，
    vector error 类运行期缺陷**不是 codegen 可修的**——禁止继续重试编译，正常收尾返回完成，
    编排层会分类出 kernel 阶段并带 deploy_result(smoke_passed=False) 前进交 precision_debug
    （scope_guard / vector_error_debug）。
  - **host 阶段（EZ1008/561001/561002/Failed to execute tiling/inferShape）**：接线/注册/launch
    缺陷，按重试协议修复后重跑 redeploy。
  - **无法判断** → 按 host 阶段保守重试。
- install 后、smoke 前必须确认 kernel binary 已打包（<opp>/vendors/custom_ops/kernel/ascend950/<op_file>/ 下有
  <OpName>_*.o/.json）。若 build 成功但缺 kernel binary，根因是 build_run.sh 的 --target binary || WARNING
  吞掉了 kernel 编译失败，须修复后重跑完整 build。
- smoke 失败 `BinaryGetFunctionByEntry failed, funcEntry=N`：先查 kernel config json 别名是否缺失
  （runtime 按 opInterface 名含下划线查 json，编译只按 opFile.value 不含下划线生成），修复 def.cpp 的
  ExtendCfgInfo("opFile.value", "<opInterface 名含下划线>")。详见 ascendc-dev-s5-compile.md §5.2.2。
【零交互约束】
- 禁止 AskUserQuestion
```
