---
name: ascendc-dev
description: AscendC 算子开发（5 阶段流程：环境确认 → 需求分析 → 需求澄清 → 编码实现 → 编译出包）。支持存量算子改造和新增算子开发两种模式。Use when (1) 用户提到增量开发、存量算子改造、需求变更、新增需求、算子改造、新增算子、创建算子 (2) 用户提供详设文档 + 算子代码路径，要求进行算子开发 (3) 涉及新增 TilingData 字段、Tiling 策略、kernel 文件等结构性变更 (4) 用户提供xxx算子开发记录.md要求恢复上次进度继续开发。触发关键词：增量开发, 存量算子, 新增算子, 创建算子, 需求变更, 新增需求, 算子改造, 开发记录, 多变更点。Do NOT use for 单点 bug fix 或简单一两行修改。
---

# AscendC 算子开发

面向完整算子开发场景的工作流，支持**存量算子改造**和**新增算子开发**两种模式。

## 初始化任务清单（session 首次触发必须执行）

本 skill 是多阶段强制流程，跨 Stage 容易遗漏步骤。**进入本 skill 的第一个动作必须是调用 `TaskCreate`，按 [references/todo-template.md](references/todo-template.md) 批量建立 10 条 todo**，再开始 Stage 1。

- 模板里每条 todo 的 `subject` / `description` / `activeForm` 直接照抄，不要改写字段
- 10 条 todo 对应 5 个 Stage（每个 Stage 1~2 条）
- 创建完把 todo-1 置为 `in_progress`，然后开始 Stage 1
- 每完成一个 Stage，将对应 todo 标 `completed`；进入下一 Stage 前先把下一条置 `in_progress`
- 如果 `TaskList` 显示本 session 已经存在 ascendc-dev 的 todo，跳过重建，直接沿用

详细模板与批量创建建议：[references/todo-template.md](references/todo-template.md)

## 流程总览

```
Stage 1        Stage 2         Stage 3        Stage 4       Stage 5
环境与输入确认 → 需求分析与报告 → 需求澄清 ────→ 编码实现 ──→ 编译出包
 [必须]         [必须]          [必须]        [必须]        [必须]
     │                                                          │
     │    ┌──────────── 精度/性能问题反馈 ◄──── 后续测试/调试 skill
     │    ▼
     └→ 跨 session 恢复入口（提供已有开发记录 → 跳转 Stage 4）
```

**全局规则：**
- 禁止跳过 Stage 1-3 直接编码（唯一例外：用户提供了已完成 Stage 1-3 的开发记录）
- 所有阶段的关键信息、决策、变更都必须写回开发记录
- 开发记录是跨 session 的唯一状态恢复载体
- 本 skill 职责到**编译出包**为止，不负责测试
- 每次状态转换必须记录到开发记录"迭代记录"
- 如果检测到前文丢失或上下文被压缩，立即重读开发记录，从当前 Stage 前置检查继续

---

## 工作流保障机制

完整规格见 [workflow-spec.md](references/workflow-spec.md)。

- **反馈**：每个 Stage 结束时验收，不达标则重试/回退/升级
- **稳定性**：重试有预算，超限升级处理，单 session 累计错误 > 10 则流程暂停
- **状态恢复**：开发记录是唯一状态载体，任何 session 可从记录恢复
- **进度**：由 `scripts/update_progress.sh` 自动计算并写入开发记录
- **错误处理**：详见 [error-handling.md](references/error-handling.md)，梯度递进：同策略修复 → 换策略修复 → 升级处理 → 流程暂停

---

## Memory 指针同步规范（贯穿所有 Stage）

auto memory 是**两文件结构**，任何 Stage 切换都必须同时更新 **两个文件**，缺一即造成索引陈旧：

| 文件 | 更新内容 |
|------|---------|
| `dev_{OpName}.md` body | "当前 Stage"字段改为 `Stage N ✅` |
| `dev_{OpName}.md` frontmatter | 如 `description` 反映了 Stage 状态则同步 |
| `MEMORY.md` 索引行 | 用 Edit 把该行末尾 `(Stage X ✅)` 替换为 `(Stage N ✅)` |

**Stage 5 收尾清理**：删除 `dev_{OpName}.md` 文件 **且** 从 `MEMORY.md` 移除该索引行（两处都要清，否则留下断链索引）。

**常见失误**：只改了 `dev_{OpName}.md` 本体、漏改 `MEMORY.md` 索引行。Edit 时以固定后缀 `(Stage X ✅)` 为锚点原子替换，可避免漏同步。

---

## Stage 1: 环境与输入确认 [必须]

> **Todo**: 开始前将 todo-1 置 `in_progress`；本 Stage 结束时把 todo-1/-2/-3 置 `completed`

### 1.1 环境就绪确认

执行 `bash scripts/check_env.sh` 验证 CANN 环境，然后完成以下断言：

```bash
# 断言 1: CANN 环境变量（由 check_env.sh 覆盖）
# 断言 2: 硬件参数 — 若本 session 尚未获取 UB_SIZE / core_num → 调用 ascend-hardware skill
# 断言 3: 知识库索引 — 若本 session 尚未读取核心 INDEX.md → 读取:
#   skills/ascendc-dev-knowledge/references/basic_knowledge_docs/INDEX.md
#   skills/ascendc-dev-knowledge/references/api_reference_docs/INDEX.md
```

任一断言失败则修复后再继续。

### 1.2 信息收集

通过 AskUserQuestion 依次收集：

| # | 确认项 | 必选/可选 | 说明 |
|---|--------|----------|------|
| 1 | 开发模式 | 必选 | 存量算子改造 / 新增算子开发 |
| 2 | 算子代码路径 | 必选 | 存量：现有代码目录；新增：要创建的目标目录路径 |
| 3 | 参考算子 | 条件必选 | 存量：可选；**新增：必选**（用于确定目录结构和代码模板） |
| 4 | 需求来源 | 必选 | 正式详设文档路径 / 简易文档+参考实现路径 / 已有开发记录路径（恢复进度） |
| 5 | 编译指令 | 可选 | 完整编译命令，可延迟到 Stage 5 |

各项收集后的处理：

**#1 开发模式 + #2 算子代码路径**：
- **存量模式**：`ls` 扫描目录结构，记录所有子目录和源文件布局。识别算子名（从 `*_def.cpp` 或目录名推断）。
- **新增模式**：确认目标目录路径。目录可能尚不存在，在 #3 确定参考算子后再创建目录骨架。

**#3 参考算子**：
- **存量模式（可选）**：如果用户提供了参考算子，收集代码路径、参考的特性点/模块/功能、文件和代码片段位置。将映射关系记录到开发记录"参考算子映射"章节。
- **新增模式（必选）**：参考算子承担双重角色——**目录结构参考** + **代码逻辑参考**。如果用户未提供，自动搜索最近的算子（同级目录 → 上一层），找到后向用户确认，基于参考算子创建新算子目录骨架。

**#4 需求来源**：选择已有开发记录 → 读取记录，检查进度表：Stage 1-3 均已完成 → **跳转 Stage 4**；部分未完成 → 从未完成的 Stage 继续。

### 1.3 创建开发记录

按 [dev-record-template.md](references/dev-record-template.md) 模板初始化开发记录。

**文件命名**：`{OpName}算子开发记录_{YYYYMMDD_HHmmss}.md`
**保存位置**：算子代码目录同级或用户指定的工作路径

**写入 Memory 指针**（auto memory 两文件结构，两处都要写）：

**① `dev_{OpName}.md`（memory 本体）：**

```markdown
---
name: dev-{OpName}
description: {OpName}算子开发进行中，开发记录路径指针
type: project
---

{OpName} 算子开发进行中。
- **开发模式**：{存量改造 / 新增开发}
- **开发记录路径**：{record_file_path}
- **算子代码路径**：{code_path}
- **当前 Stage**：Stage 1 ✅
**How to apply:** 新 session 读取开发记录，从上次中断处继续。开发完成（Stage 5 ✅）后删除此 memory。
```

**② `MEMORY.md`（索引行，末尾固定后缀 `(Stage N ✅)`，后续 Stage 用 Edit 原子替换）：**

```markdown
- [dev-{OpName}](dev_{OpName}.md) — {一句话简述} (Stage 1 ✅)
```

### 验收检查
- [ ] 开发记录已创建且必选字段已填充
- [ ] `dev_{OpName}.md` memory 本体已写入（含"当前 Stage：Stage 1 ✅"）
- [ ] `MEMORY.md` 索引行已追加（末尾 `(Stage 1 ✅)`）
- [ ] 执行 `bash scripts/update_progress.sh "$RECORD_PATH"`

标记 Stage 1 ✅，迭代记录追加：`STAGE_COMPLETE | Stage 1 完成`。

---

## Stage 2: 需求分析与开发记录 [必须]

> **Todo**: 开始前将 todo-4 置 `in_progress`；本 Stage 结束时把 todo-4/-5 置 `completed`

### 前置检查
- [ ] `bash scripts/check_gate.sh "$RECORD_PATH" 2` — Stage 1 已完成
- [ ] 算子代码路径可访问（存量）或参考算子路径可访问（新增）
- [ ] 需求文档路径可读

### 2.1 分析流程

按详设文档的**实际章节结构**逐章分析，同时交叉阅读存量代码和参考算子代码。不预设固定分析顺序——以下是需要关注的维度。

**输入材料：**
1. **详设文档/简易文档** — 提取：数学公式、接口变更、新增数据类型、输入输出约束、Tiling设计及变更、Kernel设计及变更、Pytorch/Numpy的Golden实现。
2. **存量代码**（存量模式）/ **参考算子代码 + 目录骨架**（新增模式）— 基于实际目录结构遍历读取所有源文件。推荐优先级：`*_tiling.h` → `*_tiling.cpp` → `*_def.cpp` → kernel `.h` → kernel `.cpp` → `CMakeLists.txt`。
3. **参考算子代码**（如有）— 读取用户指定的文件，将每个变更点与参考算子对应部分建立映射。

**分析关注点：**

| 关注维度 | 说明 |
|----------|------|
| 变更点识别 | 每个需求变更映射到具体影响文件、变更类型、设计决策、实现要点 |
| 不明确项收集 | 条件分支、边界情况、回退行为、并行策略、默认值——详设中未明确的点记入 ⚠️ 不明确项清单 |
| Tiling 策略审查 | 如涉及 Tiling 变更，调用 `ascendc-tiling-strategy` skill 分析 |
| 用例数据流 | 分析变更前后的 TilingKey 路由、Kernel 路径变化 |
| 参考算子映射 | 每个变更点与参考算子实现的对应关系 |

### 2.2 生成开发记录

按 [dev-record-template.md](references/dev-record-template.md) 填写所有章节。

**关键要求：**
- **⚠️ 不明确项清单**必须放在报告最开头，每项标注维度和问题描述，状态标为"待澄清"
- 不明确项要覆盖：条件分支、边界情况、回退行为、并行策略、默认值

### 验收检查
- [ ] 开发记录所有章节已填写（非空）
- [ ] 变更点列表非空
- [ ] 编码计划已生成
- [ ] 不明确项清单已收集（可为空）
- [ ] `bash scripts/update_progress.sh "$RECORD_PATH"`

标记 Stage 2 ✅，按上方"Memory 指针同步规范"**同时更新 `dev_{OpName}.md` 和 `MEMORY.md`**（MEMORY.md 索引行末尾 `(Stage 1 ✅)` → `(Stage 2 ✅)`）。迭代记录追加：`STAGE_COMPLETE | Stage 2 完成`。

---

## Stage 3: 需求澄清 [必须]

> **Todo**: 开始前将 todo-6 置 `in_progress`；本 Stage 结束时把 todo-6 置 `completed`

### 前置检查
- [ ] `bash scripts/check_gate.sh "$RECORD_PATH" 3` — Stage 2 已完成
- [ ] 不明确项清单存在（即使为空也算通过）

### 3.1 逐项澄清不明确项

遍历 ⚠️ 不明确项清单中状态为"待澄清"的每一项，使用 AskUserQuestion 进行结构化提问。

提问原则：
- 说明背景上下文——为什么需要澄清这个点
- 提供可选方案并解释各方案的影响
- 引导用户意识到可能遗漏的需求
- 用具体场景提问，而非抽象维度

### 3.2 确认参考算子映射

如果收集了参考算子信息，逐项与用户确认：每个变更点对应的参考算子部分是否准确、哪些可直接复用、哪些需调整。确认后写入开发记录。

### 3.3 回写报告

每项澄清完成后：
1. 在 ⚠️ 不明确项清单中将状态改为 `[已澄清]`
2. 填写澄清结论
3. 在"9.1 澄清记录"中追加详细记录
4. 如果澄清结果导致变更点需要调整，同步更新

### 验收检查
- [ ] 所有不明确项状态 = "已澄清"
- [ ] 参考算子映射已确认（如有）
- [ ] `bash scripts/update_progress.sh "$RECORD_PATH"`

标记 Stage 3 ✅，按上方"Memory 指针同步规范"**同时更新 `dev_{OpName}.md` 和 `MEMORY.md`**（MEMORY.md 索引行末尾 `(Stage 2 ✅)` → `(Stage 3 ✅)`）。迭代记录追加：`STAGE_COMPLETE | Stage 3 完成`。提示用户可进入 Stage 4。

---

## Stage 4: 编码实现 [必须]

> **Todo**: 开始前将 todo-7 置 `in_progress`；本 Stage 结束时把 todo-7/-8 置 `completed`

### 前置检查
- [ ] `bash scripts/check_gate.sh "$RECORD_PATH" 4` — Stage 3 已完成（或有效恢复记录）
- [ ] 确认零"待澄清"项（读取不明确项清单）
- [ ] 存量模式：基线编译通过（或用户已确认跳过）

### 4.1 前置校验

1. **检查不明确项**：确认所有项状态均为 `[已澄清]`。如有未澄清项 → 回退 Stage 3。
2. **跨 session 恢复入口**：如果用户提供已有开发记录 → 读取全部内容 → 从"6. 编码计划"中上次中断处继续。

### 4.2 编译预检查

**存量模式**：先编译当前存量代码建立基线。编译通过 → 继续；编译失败 → 告知用户，由用户决定修复或跳过。

**新增模式**：跳过基线编译。

### 4.3 分层编码

按数据流方向编码。**每个 sub-stage 完成后展示变更摘要，等待用户确认后再进入下一步。**

```
Sub-stage A: 数据结构层 — TilingData 结构体定义
Sub-stage B: Host Tiling 层 — Tiling 策略 + OpDef 定义
Sub-stage C: Kernel 层 — Kernel 类实现 + 入口分支
Sub-stage D: 构建配置 — CMakeLists.txt
```

#### 变更摘要格式

```
── Sub-stage X 变更摘要 ──
【What】[文件名:行号范围] 变更类型 + 关键代码片段（≤3行）
【Why】对应详设/需求：[章节名/变更点编号]
【Risk】[无 / 描述潜在风险]
```

### 4.4 编码规则

- **保持现有风格**：遵循存量代码的命名规范、缩进风格
- **最小改动**：不全量重写，新功能加条件分支
- **不动无关代码**
- **禁止硬编码硬件参数**：通过 `ascend-hardware` 获取
- **同步机制**：涉及多 pipeline 交互 → 调用 `ascendc-sync` skill
- **不走捷径通过编译**：不得绕过关键校验或填充无语义默认值

### 4.5 编码后自检

| 检查项 | 说明 |
|--------|------|
| TilingData 字段对齐 | Host 和 Device 的字段名、类型、顺序必须一致 |
| TILING_KEY_IS 分支覆盖 | 每个 TilingKey 值都有对应分支，禁止裸 `else` |
| 32 字节对齐 | DataCopy、Vector ops 等 API 的基地址需 32 字节对齐 |
| 新增输入/属性声明 | OpDef 中声明的新增输入/属性，在 Tiling 和 Kernel 中都有对应读取 |
| 功能关闭退化路径 | flag=false 时代码路径与修改前等价 |
| 变量初始化 | scalar变量需要初始化为合适的值大小 |

自检失败：重试上限 2 次，超过则创建 Issue + 请求用户。

### 验收检查
- [ ] 自检表全部通过
- [ ] 用户已确认各 sub-stage 变更摘要
- [ ] 编码计划中所有文件状态已更新
- [ ] `bash scripts/update_progress.sh "$RECORD_PATH"`

标记 Stage 4 ✅，按上方"Memory 指针同步规范"**同时更新 `dev_{OpName}.md` 和 `MEMORY.md`**（MEMORY.md 索引行末尾 `(Stage 3 ✅)` → `(Stage 4 ✅)`）。

---

## Stage 5: 编译与收尾 [必须]

> **Todo**: 开始前将 todo-9 置 `in_progress`；本 Stage 结束时把 todo-9/-10 置 `completed`

### 前置检查
- [ ] `bash scripts/check_gate.sh "$RECORD_PATH" 5` — Stage 4 已完成
- [ ] 编译指令可用

### 5.1 确认编译指令

如果已有 → 向用户确认是否仍有效。如果尚未获取 → 向用户确认并写入开发记录。

### 5.2 执行编译（重试协议）

```
┌→ 执行编译命令
│  ├─ 编译成功 → 5.3
│  └─ 编译失败：
│       1. `bash scripts/classify_compile_error.sh <日志路径>` → 分类错误
│       2. 根据分类定位文件/行号，应用校正策略
│       3. 记录到报告 + 迭代记录追加 ERROR 事件
└────── 重新编译
```

**重试协议**（详见 [error-handling.md](references/error-handling.md)）：

| 重试次数 | 策略 |
|---------|------|
| 第 1 次 | 同策略修复：定位错误 → 修改 → 重编译 |
| 第 2 次 | 换策略修复：重新审视设计决策 |
| 第 3 次 | 升级处理：创建 Issue → 请求用户协助 |
| 超过 3 次 | 流程暂停，输出诊断报告 |

**稳定性约束**：单 session 累计错误 E(t) > 10 → 流程强制暂停。

### 5.3 编译通过后

1. **Tiling 策略优化**：如涉及 Tiling 代码 → 调用 `ascendc-tiling-strategy` skill
2. **更新开发记录**：编译记录追加成功记录

### 验收检查
- [ ] 编译成功（exit 0）
- [ ] 开发记录已更新
- [ ] `dev_{OpName}.md` 文件已删除
- [ ] `MEMORY.md` 中对应索引行已移除（避免断链索引）
- [ ] `bash scripts/update_progress.sh "$RECORD_PATH"` → V(t) = 1.00

标记 Stage 5 ✅，**按上方"Memory 指针同步规范"执行收尾清理：删除 `dev_{OpName}.md` 并移除 `MEMORY.md` 中该行**。迭代记录追加：`STAGE_COMPLETE | Stage 5 完成 | V(t)=1.00`。

### 5.4 后续路由

| 后续需求 | 调用资源 |
|----------|---------|
| 精度验证 / 跑测试 | `ascendc-testing` agent |
| 精度问题排查 | `ascendc-dumptensor` skill |
| 性能分析 / 优化 | `ascendc-profiling` skill |
| PTA 接口适配 | `ascendc-pta` skill |

### 5.5 问题迭代循环

后续测试发现问题需要回到本 skill 修改代码时：
1. 将问题现象记录到"9.3 迭代记录"
2. 分析问题原因 → 回退 Stage 3（需求偏差）或直接进入 Stage 4（原因明确）
3. 修复后重新执行 Stage 5
4. 迭代记录追加：`REGRESSION | 从 Stage 5 回退到 Stage {N} | 原因: {描述}`

---

## Issue 管理

当错误重试 ≥ 2 次仍未解决，或 API 行为与文档不符时，创建独立 Issue 文件。

**位置**：开发记录同目录下 `issues/` 子目录
**命名**：`issue_{YYYYMMDD}_{关键词}.md`
**注册**：在开发记录"8. Issue 注册表"中追加一行

详细模板见 [error-handling.md](references/error-handling.md) 第 4 节。

---

## 开发记录

模板详见 [dev-record-template.md](references/dev-record-template.md)。

核心设计：
- **⚠️ 不明确项清单**置于记录最开头
- **Header 状态字段**（V(t)、E(t)、重试预算、门控结果）快速评估系统状态
- **当前进度表**让新 session 立即知道从哪个 Stage 继续
- **Issue 注册表**追踪复杂问题
- **迭代记录**提供完整状态观测链
- 跨 session 恢复通过 auto memory 指针自动感知

---

## 与其他 Skill 的交互

| Stage | 调用资源 | 场景 |
|-------|---------|------|
| 1 | `ascend-hardware` | 获取硬件参数 |
| 2 | `ascendc-dev-knowledge` | 按需查 API 文档 |
| 4 | `ascendc-sync` | 涉及同步机制时 |
| 4/5 | `ascendc-tips` | 编码/编译遇到问题时 |
| 5 | `ascendc-tiling-strategy` | 编译通过后优化 Tiling |
