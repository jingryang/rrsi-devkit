# 集成质量 — L1 问题记录（2026-06-24）

> 层级：**L1 / 问题记录**。只陈述「哪里坏了、凭什么这么说」（证据/现象/根因/影响）。
> 方案分析见 `02-analysis.md`（L3）；实施方案见 `03-impl-*.md`（L4）。
>
> **状态：已收口 / superseded（2026-07-09）**。本文件 P1–P6 已全部解决——或直接修复、或并入现行权威 track `self-evolution/06-problems.md`。按 §1.8，「修复记录」产权转移至 self-evolution，本文件只保留「事实记录」产权。去向（于当前代码核实）：
> - P1（NPU fallback→stub 产出不可信）→ self-evo **P6/P7**（verify 精度跑真 kernel、deploy 强制）+ P2 preflight 前置拦截缺失 torch_npu
> - P2（无前置环境检测、3h 白费）→ 直接修复：`dispatcher._preflight_runtime`（按 `workflow.requires_npu` 门禁，缺失返 `EX_CONFIG`）
> - P3（codegen 文件平铺根目录、非 op_host/op_kernel）→ self-evo **P2/P3** + `CodegenInitStage` 产出分区目录
> - P4（JSON 中间产物污染算子仓）→ 直接修复：design JSON 落 `artifacts/staging`，prompt 明禁写中间产物进 op_dir
> - P5（docgen 0.0s 空操作）→ self-evo **P13/P36**（docgen 改 LLM 真实组装 md）
> - P6（多 stage schema 不对齐/脆弱/空操作）→ 各子问题均修：P6-a `aclose` 非致命+自适应停滞检测；P6-b dd-intake 设计空操作 / docgen 改 LLM / perf 物化+跑 NPURunner；P6-c tiling 逐模板累加+`merge_forkjoin`；P6-d `_output_boundary()` 只读消费+写己产物；P6-e → self-evo **P46/P51** 统一 `fail_strategy`/`transition_table`

本记录基于最新本地测试：
- **日志文件**：`logs/run_20260624_115927.log`
- **输出目录**：`output/20260624-035927-fc9df6/`
- **算子仓**：`/home/x00584171/code/ops-transformer/posembedding/rotary_position_embedding/`
- **总耗时**：10921.4s（~3h）

---

## P1（严重）：NPU 执行失败后 fallback to stub，产出不可信

### 证据

日志 `run_20260624_115927.log` 第 3219-3220 行：

```
[WARN] NPU execution failed: [Errno 7] Argument list too long: '/root/miniconda3/envs/py311/bin/python3.11', falling back to stub
[WARN] NPU execution STUBBED for 'RotaryPositionEmbedding' — install torch_npu to enable real execution
```

verify 阶段标记为 `✓ done`（第 3221 行），但实际 NPU 执行被 stub 替代，所有验证结果不可信。

### 根因

verify stage 的 error handling 选择了"降级"而非"硬失败"：当 NPU 执行因环境问题（`Argument list too long`，实际是 torch_npu 未安装）失败时，pipeline 回退到 stub 输出，且 stub 的返回被当作正常通过。

### 影响

1. **所有验证结果虚假**：代码在 NPU 上从未真正运行，但 verify 阶段显示 `✓`。
2. **后续 stage 在假通过上继续**：perf、integrate、finalize 都基于 stub 结果执行。
3. **用户被误导**：以为算子已通过验证，实际完全不可用。
4. **问题被延迟发现**：直到实际部署或手动测试才会暴露。

---

## P2（严重）：环境问题缺少前置统一检测/解决，导致全流程 3h 白白浪费

### 证据

1. 启动时仅输出信息性日志，不做有效性验证：
   - 第 3 行：`[INFO] ASCEND_TOOLKIT_HOME: /usr/local/Ascend/cann-9.0.0-beta.2`
   - 第 4 行：`[INFO] CANN compiler found: /usr/local/Ascend/cann-9.0.0-beta.2/bin/ccec`

2. 环境问题直到 verify 阶段才暴露（第 3219 行），此时前面所有阶段已完成：
   - entry（0.0s）
   - context（0.0s）
   - requirement（132.3s）
   - general-design-generator（120.4s）
   - general-design-review（120.3s）
   - dd-intake（0.0s）
   - template-division（209.7s）
   - split × 4 模板（~1200s total）
   - buffer-kernel × 4 模板（~700s total）
   - precision-perf × 4 模板（~500s total）
   - anchor-check × 3 iterations（~656s）
   - loopback corrective × 1（~1000s）
   - integrate（skipped）
   - docgen（0.0s）
   - validate（~700s）
   - test_design × 3 substages（~1000s）
   - codegen（~423s）
   - **累计 ~7000s 白跑**

3. `Argument list too long` 错误提示 torch_npu 未安装——这是可在 5 秒内判断的静态环境条件。

### 根因

1. 缺少**前置环境健康检查（pre-flight check）**机制。
2. 环境依赖没有声明文件（pip requirements.txt、conda env yaml），也没有自动安装/提示逻辑。
3. 各阶段互相独立，不知道彼此对环境的依赖——verify 需要 torch_npu，但前面没有一个阶段会检查它是否存在。

### 影响

1. 研发效率极低：3h 等待后得到不可信结果。
2. 新环境/新开发者无法快速上手。
3. 重复性浪费：每次改代码后重跑都会遇到相同问题。

---

## P3（严重）：codegen 生成的文件全部平铺在算子仓根目录，不符合 op_host/op_kernel 目录组织

### 证据

算子仓 `rotary_position_embedding/` 下现有目录结构（良好的参考）：
```
op_host/
  rotary_position_embedding_tiling.cpp
  rotary_position_embedding_tiling.h
  ...
op_kernel/
  rotary_position_embedding.cpp
  rotate_half.h
  ...
```

但 codegen 生成的代码全部平铺在根目录：
```
rotary_position_embedding/
  rotary_position_embedding_tiling.cpp      ← 应在 op_host/
  rotary_position_embedding_tiling.h        ← 应在 op_host/
  rotary_position_embedding_op_host.cpp     ← 应在 op_host/
  rotary_position_embedding_op_host.h       ← 应在 op_host/
  rotary_position_embedding_kernel.cpp      ← 应在 op_kernel/
  rotary_position_embedding_kernel.h        ← 应在 op_kernel/
  rotary_position_embedding_kernel_half.h   ← 应在 op_kernel/
  ...
```

### 根因

1. codegen stage 的 agent（`ascendc-coder`）的 cwd 直接设置为算子根目录：
   ```
   • agent_spawn ascendc-coder starting, cwd=/home/x00584171/code/ops-transformer/posembedding/rotary_position_embedding
   ```
   （第 3110 行）

2. agent skill（`ascendc-coder.md`）中没有关于目录组织的指令——它不知道应该把 host 代码放 `op_host/`，kernel 代码放 `op_kernel/`。

3. 设计阶段产出的 `kernel_architecture.json` / `tiling_strategy.json` 不包含目标文件路径信息。

### 影响

1. 生成的代码与已有代码结构不一致，破坏项目组织。
2. CMakeLists.txt 中 `add_subdirectory` 引用的是 `op_host` / `op_kernel` 子目录，平铺的文件可能不被编译。
3. 后续维护困难——不知道新文件和旧文件的对应关系。

---

## P4（严重）：工程中间产物（JSON）被直接输出到算子仓，污染代码仓库

### 证据

codegen 完成后（第 3198 行）：
```
[WARN] git diff found changes the agent didn't report: ['changed_files.json', 'decision_log.json', 'design_spec.json', 'kernel_architecture.json', 'tiling_strategy.json']
```

算子仓根目录下出现以下中间产物文件：
```
rotary_position_embedding/
  changed_files.json        ← 工程中间产物
  decision_log.json         ← 工程中间产物
  design_spec.json          ← 工程中间产物
  kernel_architecture.json  ← 工程中间产物
  tiling_strategy.json      ← 工程中间产物
```

对比输出目录中正确的存放位置：
```
output/20260624-035927-fc9df6/artifacts/
  codegen/design_spec.json            ← 正确应在此
  design/integrate/design_spec.json   ← 正确应在此
```

### 根因

1. codegen agent 的 cwd 被设为算子仓库目录而非输出目录，agent 在算子仓直接 `Write` 文件。
2. integrate stage 也把工作目录设为算子仓（第 3225 行：`integrate validated 59 files in /home/x00584171/code/ops-transformer/posembedding/rotary_position_embedding`）。
3. 中间产物和最终代码没有写入隔离——agent 不知道哪些是"产出代码"（应入仓），哪些是"中间记录"（应入 artifacts）。

### 影响

1. **算子仓被污染**：非代码文件混入版本管理。
2. **git status 混乱**：中间产物被视为代码变更的一部分。
3. **安全性风险**：decision_log 可能包含敏感的设计决策信息混入开源仓。
4. **diff 噪声**：真正的代码变更被中间产物淹没。

---

## P5（严重）：详细设计文档缺失，docgen 是空操作

### 证据

docgen stage 执行结果（第 2475-2476 行）：
```
• stage_iteration generate_ascendc/detailed-design/docgen/docgen iteration 1/1
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ✓ generate_ascendc/detailed-design/docgen/docgen done (0.0s)
```

- 耗时 0.0s —— 明显是空操作。
- 没有任何产物输出。
- design 阶段的产物全部是 JSON schema（`general_design.json`、`tiling_split.json` 等），没有一份人类可读的详细设计文档（markdown）。

验证：遍历 design 阶段所有产物目录，没有任何 `.md` 设计文档：
```
$ find artifacts/design -name "*.md"
# 空
```

对比 test_design 阶段，有大量 markdown 设计文档产出：
```
RotaryPositionEmbedding算子测试设计方案.md (767 lines)
RotaryPositionEmbedding算子测试设计方案_测试分析_合并版.md (830 lines)
```

### 根因

1. docgen stage 被配置为跳过或空操作（report.json 中 status=unknown, 0ms）。
2. 之前的重构可能移除了 docgen 的 skill 或 agent 配置，但 pipeline DAG 中仍保留了这个 stage 节点。
3. 替代方案（JSON schema 聚合）并不能替代人类可读的详细设计文档。

### 影响

1. **无完整详细设计文档**：开发者无法从设计产物理解算子设计。
2. **评审困难**：评审者需要读多个 JSON 文件才能理解设计意图。
3. **知识丢失**：设计决策和 trade-off 只存在于 agent 对话中，无法传承。

---

## P6（严重）：多 stage 存在 schema 不对齐 / 执行脆弱 / 空操作问题

### 子问题 P6-a：tiling 阶段 agent 频繁 stall 并崩溃

#### 证据

第 391-395 行（InterleaveRotation buffer-kernel）：
```
[WARN] Agent ascendc-design-generator stalled: 3 consecutive turns with no new text and no effective tool use (repeated/erroring calls). Stopping early and collecting existing output.
RuntimeError: aclose(): asynchronous generator is already running
✗ generate_ascendc/detailed-design/tiling/InterleaveRotation/buffer-kernel/buffer-kernel done (10.2s) [failed]
→ missing_artifact: tiling_buffer_kernel.json: required artifact not produced
```

第 565-577 行（HalfRotation precision-perf）：
```
[WARN] Agent ascendc-design-generator stalled: 3 consecutive turns with no new text ...
✗ generate_ascendc/detailed-design/tiling/HalfRotation/precision-perf/precision-perf done (9.7s) [failed]
→ missing_artifact: tiling_precision_perf.json: required artifact not produced
```

同一模板在 loopback 重跑后成功（InterleaveRotation buffer-kernel loopback 成功于第 1220 行，HalfRotation precision-perf 成功于第 1402 行），但首次执行的不稳定性说明 agent skill 提示词不够鲁棒。

#### 根因

1. `ascendc-design-generator` 的 skill prompt 在 buffer-kernel 和 precision-perf 阶段过于简略，agent 无法独立产出有效结果。
2. agent 无输出时 trigger stall 检测（3 轮 continuous no output），但 stall 恢复机制（loopback）仅在 anchor-check 后触发，导致依赖这些产物的管道断裂。

### 子问题 P6-b：多个 stage 是 0.0s 空操作

#### 证据

以下 stage 耗时 0.0s，无 agent 启动，无产物：

| Stage | 耗时 | 日志行 |
|-------|------|--------|
| dd-intake | 0.0s | 第 151-152 行 |
| docgen | 0.0s | 第 2475-2476 行 |
| perf | 0.0s | 第 3222-3223 行 |

#### 影响

- dd-intake 不做输入验证，后续 tiling 阶段接收到的 schema 可能不对齐。
- docgen 不做文档生成（见 P5）。
- perf 不做性能测试——这与其 stage 名称矛盾。

### 子问题 P6-c：loopback 中存在 schema 不对齐

#### 证据

第 928-931 行 loopback 触发条件：
```
[AC2→tiling/QuarterRotation] QuarterRotation 模板的 hardware_api_capability 类 claims（UB=253952B/248KB、DDR=17G...）
[AC2→tiling/InterleaveRotation] InterleaveRotation 模板在聚合产物 tiling_results.json 中仅含 split 段，缺失 buffer_kernel 和...
```

说明：
1. anchor-check 发现了 schema 不一致（hardware API capability 数值不匹配）。
2. tiling_results.json 聚合逻辑有 bug：buffer-kernel 和 precision-perf 的产物未正确合并到聚合产物中。
3. 需要 loopback 才能修复——增加了约 1000s 的额外时间。

### 子问题 P6-d：test_design 和 codegen 阶段输入 schema 传递混乱

#### 证据

test-casedesign 产出了不属于它阶段的 schema 文件（第 2862-2869 行）：
```
design_spec.json (107 lines, 2074 bytes)       ← 不属于 test_design
kernel_architecture.json (338 lines, 10271 bytes) ← 不属于 test_design
tiling_results.json (2742 lines, 139830 bytes)  ← 不属于 test_design
tiling_strategy.json (189 lines, 5219 bytes)    ← 不属于 test_design
```

codegen 阶段的产物既有代码文件，又有 schema 文件（第 3200-3213 行）：
```
decision_log.json             ← 中间产物
design_spec.json              ← 上游 schema
kernel_architecture.json      ← 上游 schema
tiling_strategy.json          ← 上游 schema
+ 10 个 .cpp/.h 文件          ← 最终代码
```

这些 schema JSON 在多个 stage 中重复产出且内容随时间漂移——说明 stage 之间没有清晰的"只读消费 schema + 写入自己产物"的契约。

### 子问题 P6-e：pipeline 在 stage 失败后行为不一致

#### 证据

1. buffer-kernel/InterleaveRotation 失败（第 395 行）→ `fail_strategy=halt` → pipeline 停止该模板分支的后续，但其他 3 个模板继续。
2. precision-perf/HalfRotation 失败（第 569 行）→ 同样 halt。
3. 但 loopback 阶段（第 928-931 行）重新触发了这些失败模板的 tiling。
4. 最终所有模板都通过了（第 3221 行 verify `✓ done`），说明内部重试机制在起作用，但控制台/用户感知不透明。

### 综合影响

这些子问题共同表明：**design→codegen 的 stage 链存在系统性的 schema 对齐和执行可靠性问题**，表现为 agent stall、空操作 stage、产物重复产出、loopback 自救——整个链路不如一条清晰的线性流水线。

---

## 问题汇总矩阵

| 问题 | 严重度 | 影响范围 | 证据密度 | 是否可自动检测 |
|------|--------|----------|----------|----------------|
| P1 fallback to stub | 严重 | verify 可信性 | 日志 2 行 | ✅ 可前置 |
| P2 环境问题晚发现 | 严重 | 全流程效率 | ~7000s 浪费 | ✅ 可前置 |
| P3 代码目录组织 | 严重 | 代码可用性 | 算子仓 10+ 文件 | ✅ 静态检查 |
| P4 中间产物污染 | 严重 | 仓库洁净度 | 5 个 JSON 文件 | ✅ 静态检查 |
| P5 设计文档缺失 | 严重 | 知识传承 | docgen 0.0s | ✅ 产物检查 |
| P6-a agent stall | 严重 | 管道稳定性 + 时间损失 | 2 stall+crash → +2000s loopback | 部分 |
| P6-b 空操作 stage | 低 | 用户感知 | 3 个 0.0s stage (设计意图) | ✅ 日志分级 |
| P6-c schema 不对齐 | 严重 | 设计产物质量 + 时间 | 3 loopback × ~1000s = ~3000s | 部分 |
| P6-d schema 传递混乱 | 中 | 产物清晰度 | ~150KB 重复 schema 产出 | ✅ diff 检查 |
| P6-e 失败行为透明度 | 中 | 用户信任 | halt→loopback→success 链路不可见 | ✅ 日志增强 |

> **P6 源码级根因分析详见：[`04-p6-root-cause-analysis.md`](./04-p6-root-cause-analysis.md)**
