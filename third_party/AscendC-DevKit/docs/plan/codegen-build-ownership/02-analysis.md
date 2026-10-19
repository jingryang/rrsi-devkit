# L3 方案分析 — codegen 构建职责归属：agent 会话内受控构建 vs python 侧编译-注入循环

- 层级：**L3 / 方案分析**。记录选项、取舍、理由。调研中演进，拍板后冻结。
- 上游：`01-problems.md` P1/P2（事实产权在 L1，此处只引用）。
- 状态：**已拍板（2026-09-05）**——用户确认选**方案 2**。L4 未写（用户：先落文档，不急着写代码）。

### 拍板决策明细（2026-09-05）

| # | 决策 | 内容 |
|---|---|---|
| D1 | 选方案 2 | agent 只写码；python 编译；错则 resume 注入 |
| D2 | resume 原 session | 不是 fresh；骨架现状已有 |
| D3 | 错误收集全量 | python 侧 `scan_kernel_compile_errors` |
| D4 | 禁轮次纪律 | 绝对禁止限轮换质量 |
| D5 | 禁 build 边界 | 禁整仓 build/install/smoke；**保留读 Bash + ccec 单文件**（保质量），主动引导 agent API 不确定用 ccec 验证 |
| D6 | transition 节奏 | **先 compile 再全链**：compile 过才 install+smoke；compile 错→resume 修 |
| D7 | 工具硬闸 | **不做**命令级硬拦；纯靠 prompt/skill 软引导（保留读+ccec，引导禁整仓 build） |
- 触发：复盘 49134b run `20260829-142941-6f61da`（2026-09-05）。

---

## 一、决策问题

codegen 阶段，agent 的「构建验证」该以什么形态存在，才能同时满足用户三关切：

1. **轨迹短**：agent 不「研究怎么构建」（读 build.sh/cmake/op_build 链自己复刻）——那是
   框架确定性知道的，不该让 agent 重新发明。
2. **不污染**：agent 不能把产物装进系统 vendors / pip / 触发真 smoke（共享环境，影响兄弟算子）。
3. **只用框架提供的工具**：不是要控制模型，是让它按预期工作、有正门可走（用户 2026-09-05：
   「不是想控制模型，只是希望它使用我提供的工具」）。

## 二、候选方案

### 方案 0 — 维持现状（隐含否决）

codegen agent 会话内自由裸 Bash build/install/smoke；框架在会话结束 transition 跑完整
Deployer 链。**否决**：P1 实证 3h15m/805-turn 自研轨迹 + 污染 + 误判编译结果。

### 方案 1 — agent 会话内调框架受控编译工具，自闭环解 bug

拆 Deployer 出独立 `compile()`（只 build 不 install），暴露给 agent 会话内调；agent 写码 →
调 compile → 读结构化错误 → 改 → 再调，自己闭环到编过；install+smoke 留在 python 侧会话外。

- 优点：保留 agent 会话内快速迭代；错误收集天然在会话内闭环。
- 缺点：**仍是会话内 build 循环**——agent 会追着错反复编译到编过，长会话失控的土壤
  （805/974-turn）只是工具受控、循环未破；且若 compile 带运行/smoke 能力，agent 又去追
  kernel 阶段 bug（正是 4h 主体）；要不带，agent 编过也验证不了 runtime。**需额外立"compile
  工具不许跑 NPU、kernel 错不许会话内追"的边界**——而 P1 实证 agent 无视了 skill 里已有的
  同类边界。

### 方案 2 — agent 只写码；python 侧编译，出错 resume 原 session 注入错误（倾向）

agent 只写码/修码 → 退出 → python 侧 `compile()` → 用 `scan_kernel_compile_errors` 收集
**全量去重**错误集 → resume 原 session 注入 → agent 在同一轮充分修（不限轮次/不限工作量）
→ 退出 → python 再编 → 直到门过或交棒。

- 用户裁定（2026-09-05）：
  - **resume 原 session**（不是每次 fresh）；骨架现状已有（`resume_session_id` +
    `_render_retry_resume_prompt`）。
  - **错误收集全量**（跟方案 1 同级），python 侧 `scan_kernel_compile_errors` 已具备。
  - **绝对禁止轮次限制**换机制便利；compaction 不空谈，真遇到再说。
  - **精化（2026-09-05 拍板）**：方案 2「禁 agent 会话内 build」的边界精确到——
    - **禁**：整仓 build（`bash build.sh` / `cmake` 全量）、install、smoke、pip、写系统
      （装 vendors / `/root/opencode_smoke` 类）——越权+污染本体。
    - **保留**：agent 会话内**读 Bash**（ls/cat/grep/find/git diff）——知识搜索/仓探索
      （实测约 76% 合法用途），写码查 API 依赖。
    - **保留 + 主动引导**：**ccec 单文件编译到临时目录**（验 API 签名能不能编，不装系统
      不 smoke）。理由：最重要目标永远是**写出高质量算子**；agent 写码时若 API 签名不确定，
      ccec 单文件验证是秒级反馈，禁掉会迫使其等整仓编译（分钟级）才暴露 API 错，往返变慢、
      可能损算子质量。故**不禁 ccec**，并在 skill/prompt **主动提醒 agent**「API 签名不确定
      时用 ccec 单文件编译验证」。
    - 这条把「治污染/轨迹」与「保质量」分开：整仓 build 链归 python，单文件 API 验证留 agent。
- 优点（逐条对照用户三关切）：
  - **轨迹短**：agent 无 build 能力，不可能"研究怎么构建"，只消费注入的错误 → 改对应处。
  - **不污染**：install/smoke 在 python 侧，agent 物理上装不进系统。
  - **kernel 错天然交棒**：agent 无法会话内验证 runtime → kernel 错落 known_issues →
    precision（现状路由）。
  - **上下文成本低于方案 1**：build 原始输出/试错轨迹由 python 消化，只注入去重错误集；
    方案 1 这些在 agent 会话内自我累积。见「四、上下文成本对比」。
  - **质量判定归 python**：P1 铁证——agent 自报 build 成功而 binary 未出；python 判
    "编过"不会误判，质量天花板在确定性门，不依赖 agent 自觉。

### 方案 3 — 命令级硬约束（命令墙/禁 Bash）——用户评估后否决

用 opencode 原生命令级 deny / 禁 Bash 工具 / 白名单等，硬挡 agent 构建命令。用户评估：
- 注入 prompt 是软约束、兜底；硬约束难做且有副作用（用户 2026-09-05）。
- 命令白名单会限制 agent 能力（合法搜索命令形态无穷，枚举不全就误伤解题力）；黑名单仍要
  枚举"哪些是构建"，agent 变体绕，漏一个破墙。
- **否决为方案主体**；不作为独立方案推进。

## 三、取舍分析

| 维度 | 方案 1 | 方案 2 |
|---|---|---|
| 轨迹（不研究构建） | 部分——工具受控但仍会话内试错 | **完全**——agent 无 build 能力 |
| 污染（不装系统） | 依赖"compile 不带 install"边界 | **结构上不可能**（install 在 python 侧） |
| kernel 错归属 | 需额外边界防 agent 追 | **天然交棒** precision |
| 上下文成本 | 会话内自积 build 日志/轨迹 | python 消化，注入精简错误集 |
| "编过"判定 | agent 自判（P1 铁证会误判） | **python 判**（确定性） |
| resume 复用 | 长会话自闭环 | 复用现状 resume 骨架 |

方案 1 在不限轮次（用户刚硬的约束）下反而暴露最大弱点：会话内 build 循环 + 不限轮次 =
给了 agent 无限自修的闭环。方案 2 中"是否编过"由 python 判、不由 agent 判，循环由 python
驱动，天然不需要"轮次纪律"去兜质量——质量由 agent 每轮充分解决 + python 确定性门共同保证。

## 四、上下文成本对比（方案 1 vs 方案 2，用户 2026-09-05 提问）

| | 每轮新增进 agent 上下文 | 累积性 |
|---|---|---|
| 方案 1 | build 原始输出 + 试错轨迹（大、杂） | **强累积**（会话内自积） |
| 方案 2 | 去重错误集 `KernelCompileError[]` + 改动文件（小、结构化） | **弱累积**（python 挡掉 build 日志） |

**结论**：方案 2 相对方案 1 是**减少**上下文，不是增加。方案 1 把"看 build 日志找错"这件
上下文最贵的事留在 agent 会话内（每编一次灌一屏原始输出、试错轨迹自积）；方案 2 把它挪到
python 确定性处理（`scan_kernel_compile_errors` 去重后只注入结论），agent 只消费精简错误集。
"注入原 session 使 session 随轮变长"与方案 1 的会话内累积同源（都是长 session 问题），
非方案 2 特有；方案 2 净优势是 build 日志/探索轨迹两大膨胀源被 python 挡掉。

## 五、现状基建盘点（方案 2 落地依赖，非新增）

1. **`resume_session_id` + `_render_retry_resume_prompt`**：`codegen.py:940-941`（_actions_membase
   构造 `SpawnAgent(resume_session_id, resume_prompt)`）——但现状只服务"轮末反馈"
   （build/artifact），**不服务"逐次编译错误注入"**，需把编译错误接成逐次 resume 注入源。
2. **错误收集**：`domain/build_log_scanner.py::scan_kernel_compile_errors` 返回全量去重
   `KernelCompileError[]`（按 file:line+msg 去重，带 op_name/source/message）——方案 2 的
   "全量收集"已具备，不用发明。`classify_build_error` + retry gradient 已有。
3. **Deployer 拆分**：需把 `_run_build_install` 里的 build 段拆出独立 `compile()`（只 build
   不 install）。现状颗粒到 `build_install`（含 install），无只编译入口。
4. **skill/prompt 误导描述**：P1 证据 3/4——fresh prompt 无"构建归框架"、skill 授权会话内
   自检编译到好，需随方案改（若选方案 2：删/改为"codegen 只写码，不 build；runtime/kernel
   错 known_issues 交棒"）。

## 六、待拍板点

1. **方案 1 vs 2 最终选型**：**已拍板方案 2**（用户 2026-09-05「选择方案 2」）。
2. **方案 2 的 session 策略**：已定 resume 原 session；但"session 膨胀/compaction"不空谈
   （用户裁定），真遇实际问题再处理，不在本方案预设计。
3. **「每轮充分修」的质量语义**：python 编译一次收集全量错误注入后，agent 在一轮里改到
   它认为解决（不限轮次），python 再编——循环由 python 驱动，非由轮次上限驱动（用户
   2026-09-05 绝对禁止轮次纪律）。
4. **环境层（与选型正交）**：本批 smoke_host 连败根因非 codegen 代码，是环境（agent 历史
   污染 + sitecustomize 剥路径 + GE 缓存）。2026-09-05 实查：污染源中系统 vendors 已空、
   剥路径 sitecustomize 不存在、`/root/opencode_smoke` 残留已删（L1 环境清除证据）；各批
   算子仓内 sitecustomize 为修复性 hook、保留。框架 smoke 区分"代码错 vs 环境错"能力是否
   需补，另行跟踪。

## 七、逐条质疑后的收敛（2026-09-05 质疑轮后定稿）

对方案 1/2/3 及 L4 逐条质疑，用户裁决后收敛如下。本节是 L3 的最终取舍记录，
取代第五节"待拍板点"中已被覆盖的表述。

### 裁决（用户 2026-09-05）

1. **P1 是"真空缺口"而非"软约束被无视"**：coder-01 fresh prompt **根本没提 build 归属**，
   agent 在真空里只能自己探索。skill 里"别污染系统/kernel 交棒"的软约束被无视，**不是因为
   模型无视软约束，而是那些不是针对 build 归属的明确引导**。补上"构建归框架、别自己整仓
   build"的明确句 = 堵真空，不是重复一条已被无视的禁令。**→ 撤回质疑 1（软约束与 P1 矛盾）。**
2. **明确引导下模型仍不遵守 = 模型能力问题，方案 1 同样救不了**：方案 1 的会话内受控 build
   也依赖模型遵守"只用受控工具"。所以"会话内那部分"是所有方案共同依赖，非方案 2 独有弱点。
   **→ 撤回质疑 2/6（方案 2 空心/两头不靠）。**
3. **build 必须复用**：无码改动时不得做两次 build（compile 过 → 再 deploy 重编 = 浪费）。
   **→ L4 改动 2 改成 compile 产物复用 install+smoke。**

### 方案 2 的真实构成（质疑后厘清）

- **会话外（结构性，不依赖模型，真硬）**：编译判定归 python、install/smoke 物理在框架侧、
  kernel 错交棒 precision、build 产物复用。这些是方案 2 相对方案 1 的净优势所在，且正是治
  "污染"和"编译误判"（P1 铁证）的关键。
- **会话内（依赖模型遵守，软引导）**：禁整仓 build、引导用 ccec 验 API。**这部分方案 1 一样
  依赖模型**，不是方案 2 独有。

### 风险假设（实施后观测，不预设计）

方案 2 会话内防"805-turn 自研土壤"依赖软引导有效性。**风险前提**：在"构建归框架"的明确引导下，
agent 应不再会话内整仓 build（低上下文时模型能遵守；若连明确引导都频繁违反，是模型能力问题，
方案 1 同样失效）。**处置**：不作为缺陷预修，实施后观测——若真实跑仍频繁出现 agent 会话内整仓
build，说明软引导不足，再升级（不预设手段，届时按实证定）。

### ccec 保留的边界（质疑 3/7 展开后收敛）

- ccec 单文件编译到 /tmp 的合法价值：① 验 API 签名（质量保障）；② **减少纯 API 错误的整仓
  往返**——有些错单文件就暴露，不必每轮等整仓 compile。
- 它不能替代整仓集成验证（注册/tiling/多文件 link），那是框架 compile 的活——分工：ccec 管
  单文件，整仓归框架。
- ccec 不是越权台阶：transcript 里 agent 有 ccec 仍滑向整仓 build，是因为它要"整仓能否集成"
  的反馈，ccec 给不了；防越权靠把 ccec 边界讲清（到 /tmp、别跨到整仓 build），而非禁它。

#### ccec 措辞收敛（2026-09-05 实施后风险复盘）

**风险（用户提出）**：ccec 引导在弱模型下可能诱发「一遇 API 就 ccec」的过度验证，甚至被
误解成「agent 需要自己编译来感知错误」——后者与方案 2「agent 不自己编译」**直接矛盾**。

**收敛**：ccec 的触发源**严格限定为「框架注入的编译错误明确指认某 API 签名」**这一个——
agent 会话内**不主动编译、不预验证、不逐 API 试编**（整仓 build 由框架跑，编译错误经框架
注入）。措辞明示「你不主动编译」消除「自己编译」歧义。实施中已将 SKILL.md 与 fresh prompt
两处改为该表述，fresh-prompt UT 断言同步（`你不主动编译` / `不预验证` / `注入的编译错误`）。

#### ccec 最终形态（2026-09-05 用户裁决：知识化，非提示词）

**用户指出**：ccec 不该写成提示词（逐轮指令会诱导模型当常规手段反复用），而应**沉淀为 skill
的知识**，只在「API 用法不确定」时按需查；且**不写死 /tmp**（路径耦合，违反 §1.5 资源路径规范）。

**最终收敛（覆盖前几版反复收紧）**：
- **prompt 零 ccec 指令**——fresh 首轮与编译反馈段都不展开方法；编译反馈段仅在签名错
  （C-API + no matching function）时给一句**判据指针**（"方法见 skill references"），不展开。
- **SKILL.md 只留判据**——"某 API 用法存疑时先查知识库/ascendc-tips，仍存疑可做最小单文件
  编译验证（方法见 references/verify-api-signature.md）"；是**仅存疑时的定向动作**，非常规流程。
- **方法沉淀为新知识文件** `ascendc-op-dev-coding/references/verify-api-signature.md`：临时
  目录抽象（mktemp/工作区临时子目录，**不写死 /tmp**）、最小 .cpp 构造、只编不装不 smoke、
  边界（不验证整仓集成/runtime）。
- **§2.8 符合**：知识归 references 资源按需 Read，不内联 workflow 正文；§2.2 references 在
  skill 目录内，单独取出不缺失。
- UT：feedback_delivery 三测试断言改判据指针形态（含 references 指针、不含 /tmp）；upstream_reuse
  断言 fresh 无 ccec。

### 质疑后新增的修正（落进 L4）

1. **L4 改动 2 改 build 复用**：compile 产物被 install+smoke 复用，不重复 build。
2. **L4 改动 1 DeployResult 留空 install_path/python_path**：compile() 没 install，返回的
   DeployResult 不得带 install_path/python_path（防误导下游以为装好了），只带 run_package/
   wheel_package。

