# P57 — 能力下沉 + 删冗余 stage（deploy/verify）— 方案分析（第三层）

> 状态：**方案冻结**（2026-07-09，用户拍板 Q1-Q5）。主导方向 = 两 agent stage（codegen / precision_debug）各自 in-session 闭环，build/deploy/smoke/run-cases 降为 agent 调用的原子能力，**删 deploy/verify 两个确定性 shell stage**，消除跨 stage 错误传递。**本步范围限 self_evolve_op**；generate_ascendc/dev/se 同类问题记 L1 **P58**，作**中优 follow-up，须与本方案一致**（§9.1 / §11）。
> ⚠ **范围修订（2026-07-09 后续，见 §12，权威）**：codegen 的 build 闭环是共享 stage 核心行为，无法只对 self_evolve_op 开（all-or-nothing）。用户获悉此约束 + 真实范围后改拍 **Option II 全局一致**——全 5 workflow、删 deploy/verify **含 `DeployStage`/`VerifyStage` 类**、P58 吸收进本步。§12 覆盖本文件其余 self_evolve_op-only 表述。
> 层级：**第三层 / 方案分析**。选项 + 取舍 + 待定。
> 覆盖问题：P57（deploy build 失败无 loopback + 无具体错误）。
> 输入：run `20260709-094500-b3a241`（self_evolve_op，deploy build 失败直接 halt、stderr 截断无落盘）+ 用户主导的架构探索（build/deploy 封装为原子能力、deploy/verify 是否可删、codegen 是否需产 precision_result、smoke 是否必要）。
> **承接**：P54（in-stage 闭环原则——精度失败 agent 内闭环、不跨 stage loopback 损上下文；本条把该原则**从 precision_debug 边界前移到 codegen/build/deploy 边界**）+ P45/P47（设计侧 in-stage 闭环 + 反馈消费自检，同形先例）+ P53（精度失败反馈死边/失真，被 redesign 绕开的同类现象）。
> 约定：按符号定位（不写 file:line）；外部依赖只读；本文件不写具体改哪个函数（那是 L4）。

---

## 1. 定位：P57 是「deploy 作为独立确定性 stage」的结构缺陷暴露，本条是删该 stage 的整体重设计

P57 的两个现象（halt 抢占 loopback 死边 / stderr 截断无落盘）表面是 bug，结构根因是 **deploy / verify 作为夹在 codegen 与精度调试之间的独立确定性 shell stage**——它们把「编译/部署/验证」做成跨 stage 的厚壳，迫使：

- 错误经 `last_error`（message + 截断 stderr）跨 stage 传回 codegen → 既丢上下文（P54 同款硬伤）又因 halt 抢占变成死边（P57-A）。
- 完整子进程输出无处落盘 → 无具体错误（P57-B）。

本 L3 不在 deploy stage 内打补丁（修 halt 抢占、加落盘），而是**删掉这两个 stage**，把 build/deploy/smoke/run-cases 降为 codegen / precision_debug 各自 in-session 调用的**原子能力**（P54 已建立的 D4 范式），让每个 agent stage 自己闭环、自己看完整 stderr。这同时让 P57-A/B 两现象失效（无 deploy stage → 无 halt 抢占死边；agent 直接读完整 build stderr → 无截断）。

二者的产权边界（§1.8）：
- **P57（L1 事实）**：deploy 失败处理的两处客观缺陷。redesign 后无 deploy stage，**两现象随之失效**（被绕开，非就地修复，同 P54 绕开 P53 模式）。
- **本 L3（架构方案）**：两 agent stage + 原子能力 + 删 deploy/verify 的目标态。

---

## 2. 现状：codegen → deploy → verify 三段式，跨 stage 错误传递（简引 L1 P57 + 结构事实）

当前 self_evolve_op 图：`codegen → deploy → verify → precision_debug → cannbench_*`。

- **deploy**（确定性 shell）：build → install → smoke。`fail_strategy="halt"`，`resolve_condition` 返回 `deploy_failed`，transition_table 写了 `deploy_failed: ("codegen","corrective")`——但 halt 抢占使其为死边（P57-A）。
- **verify**（确定性 shell）：build gate（BuildInRepoGate）+ 跑 cases 量精度。`fail_strategy` 默认 continue，`build_failed→codegen` / `precision_failed→precision_debug`（P54 改）/ `exhausted→__halt__`。verify 产 `build_result` + `precision_result`。
- **跨 stage 错误载体**：deploy/verify 失败经 `last_error`（message + stderr 截断 2000 字符）传回 codegen；子进程完整输出不落盘（P57-B）。

**问题**：build/deploy/smoke 本是 codegen「让代码跑起来」的职责延伸，却被拆成独立 stage + 跨 stage 传递，既割裂上下文（P54 同款）又制造 halt 抢占死边（P57-A）。

---

## 3. 认知校正（用户主导）：in-stage 闭环原则应从 precision_debug 前移到 codegen/build/deploy

> **本 L3 的理论基石，由用户在讨论中提出。**

### 3.1 P54 已立「精度失败 agent 内闭环」原则

P54 论证：精度调试属 inference-time 单算子自我修正，应 stage 内闭环（改码→commit→redeploy→run-cases→读日志→再改），不跨 stage loopback 回 codegen——理由是 loopback 上下文损失 + 频繁启 agent + debug workflow 不可复用三硬伤。据此立了 `PrecisionDebugStage`，其 agent 经 `redeploy` / `run-cases` 两个 CLI 原子能力闭环。

### 3.2 同一原则应前移到 codegen：build/deploy 也是 codegen 的职责延伸

build 失败回 codegen 的信息需求 = codegen 重生成所需信息（哪行编译错、stderr）——但**经跨 stage 传递会损失/抢断**（P57-A 死边、P57-B 截断）。而 P54 已经证明：**让 agent 自己调原子能力闭环**（直接读完整 stderr、in-session 自修）远优于跨 stage loopback。

既然精度调试能 agent 内闭环，build/部署调试为何不能？codegen 写完代码后「让它编译通过、可调用」本就是 codegen 的收尾职责，不该外包给独立 deploy stage 再用截断 stderr 传回来。**把 build/deploy/smoke 降为 codegen agent 调用的原子能力**，codegen 自己读完整 build stderr、in-session 自修编译错——与 P54 的 `redeploy`/`run-cases` 完全同形（且 `redeploy` 本就是 build+install+smoke 的封装，可直接复用）。

### 3.3 这不是新架构——P54 的原子能力 + in-session 闭环已是现成范式

P54 已建：`Deployer` 服务（build+install+smoke 单一通路，§2.5）+ CLI `redeploy`（build+install+smoke）+ CLI `run-cases`（量精度+落盘日志）。precision_debug 的 agent 经这两个 CLI 闭环。本条**让 codegen 的 agent 也经 `redeploy` 闭环 build/部署**——同一套原子能力、同一种 in-session 闭环，只是调用方从 precision_debug 扩到 codegen。deploy/verify 作为独立 stage 自然失去存在理由（其逻辑全在 `Deployer`/`run-cases` 里，被 agent 直接调用）。

---

## 4. 目标态：两 agent stage + 原子能力 + 删 deploy/verify

```
codegen（agent 内闭环：写码 → redeploy[build+install+smoke] → 读完整 build stderr → 自修编译错 → 再 redeploy）
   原子能力：redeploy（P54 已建）
   产出：generated_sources / codegen_manifest / build_result(编译过) / deploy_result(可调用/smoke 过)
   stop-loss：max_rounds 编译自修上限 → exhausted → __halt__
        ↓ 只交「编译 OK + 可调用」的代码
precision_debug（agent 内闭环：run-cases → 读 max_diff/日志 → 改码 → redeploy → 再 run-cases）  [P54 已落地]
   原子能力：redeploy + run-cases（P54 已建）
   产出：debug_result(功能 OK + 精度 max_diff)
        ↓ passed
cannbench_adapt / cannbench_eval / perf / integrate / finalize
```

- **删 deploy stage**：build+install+smoke 全在 `Deployer`，被 codegen 的 agent 经 `redeploy` CLI 直接调用。
- **删 verify stage**：build gate 角色 → codegen（编译自修闭环）；精度首量角色 → precision_debug（首轮 run-cases 即首量门）。
- **无跨 stage 错误传递**：每个 agent stage 自己读完整子进程输出、自己修，不经 `last_error` 截断传递。

---

## 5. 角色定义（核心决策）：smoke = codegen 接线门，run-cases = precision_debug 功能+精度门

> **本节是本次讨论的焦点收敛。两个 gate 正交、无重叠，是守住两 stage 职责边界的关键。**

### 5.1 smoke 不跑算子——它只查「符号可解析」

`Deployer` 的 smoke（经 `redeploy` CLI 暴露）：
- `torch_op`：`import torch` → `__import__(ns)` → `getattr(torch.ops, ns)` → `getattr(ns, op)` → `assert fn is not None`。**全程只查符号能不能解析到，从不拿真实 tensor 调它。**
- `aclnn`/其它：近乎 no-op（插 sys.path + print）。

所以 smoke 的**失败域是确定的、极窄的**：`.so` 加载不起来、`callable_target` 符号写错、`TORCH_LIBRARY` 注册没触发、`__init__.py` import 炸。全是**接线/注册问题**——不喂真实输入，**不可能**触发算子逻辑错或精度错。

### 5.2 smoke 归 codegen（接线是 codegen 产出物）

接线的产出物（注册胶水、符号、打包、`__init__.py`）全是 codegen 写的。smoke 抓的失败 = codegen 的接线输出有缺陷 → 让 codegen 修完全在职责内，**不越界到 precision_debug**（precision_debug 管的是「真跑起来对不对」，接线是「能不能跑起来」）。

### 5.3 smoke 必要——它是守 precision_debug 边界的门

设想**删掉 smoke**：接线坏的算子直接流进 precision_debug，首轮 `run-cases` 报 "symbol not resolvable" 或 "import failed"。此时只有两条路，**两条都坏**：

1. precision_debug 自己去修接线 → **职责越界**（被迫懂注册胶水，那是 codegen 的活）。
2. precision_debug 判定「这是接线失败不是精度失败」回路给 codegen → **重新引入跨 stage 错误传递**，正是本条要消灭的东西。

所以 smoke 留在 codegen 内闭环：**用一次确定性检查把所有接线失败吸收进 codegen 自修圈**，保证交到 precision_debug 的代码一定是「可调用」的，precision_debug 就能干净地只管「调用得对不对」。

### 5.4 run-cases 归 precision_debug（功能 + 精度）

run-cases 拿真实 tensor 调算子、量 max_diff、抓功能崩溃 + 精度错。precision_debug 的定义 = **调试 stage = 功能 + 精度**（用户定调）——run-cases 完整覆盖这条线。smoke 不碰这条线（它不跑算子）。

### 5.5 角色对照表

| 检查 | 跑真数据？ | 抓什么 | 失败属谁 | 归属 stage |
|---|---|---|---|---|
| **smoke**（`redeploy` 内） | 否，只解析符号 | 接线/注册/`.so` 加载 | codegen（接线产出方） | codegen |
| **run-cases** | 是，真 tensor | 功能崩溃 + 精度 max_diff | precision_debug（功能+精度） | precision_debug |

**结论**：smoke 与 run-cases 正交、都必要。smoke 不是在干 precision_debug 的活——它干的恰是 precision_debug **不该碰**的接线校验，是守边界的门。用户「功能崩溃归 precision_debug」的直觉正确，但那崩溃在 run-cases 发生、不在 smoke（smoke 不跑算子）。

---

## 6. 状态字段搬迁（消消费者核查驱动）

### 6.1 codegen 产什么

- `generated_sources` / `codegen_manifest`（原有，不变）。
- `build_result`（编译过）：**保留**——finalize 读 `final_build_result` 做终态报告（硬依赖）。
- `deploy_result`（可调用/smoke 过）：**保留**——cannbench_eval 读它（硬依赖）；codegen 经 `redeploy` 产出。
- **不产 `precision_result`**（见 6.2）。

### 6.2 `precision_result` 字段：删除（无硬依赖消费者）

全仓 `precision_result` 消费者核查：

| 消费处 | 用途 | redesign 下 |
|---|---|---|
| codegen 反馈（max_diff） | 反馈给 coder | **消除**——codegen 不再修精度 |
| precision_debug 启动 guard | 判断要不要启动 | **消除**——precision_debug 总接 codegen 之后、自己首轮 run-cases 即门，不需预存结果判断 |
| dispatcher / runner 报告 | 展示 "Precision max_diff=" / 进度事件 | **换源**——改读 precision_debug 产出的 `debug_result`（P54 已 `provides=["debug_result"]`，带 passed/max_diff） |

**关键：没有任何 eval/perf/finalize 硬依赖 `precision_result`**（对比 `build_result`→finalize、`deploy_result`→eval 是真硬依赖）。故 codegen **不必产 precision_result**——精度由 precision_debug 端到端负责，报告读 `debug_result`。

### 6.3 verify 产物的去向

verify 产 `build_result` + `precision_result` + `verify_iterations`：
- `build_result` → 改由 codegen 产（codegen 编译闭环产出）。
- `precision_result` → 删除（6.2），报告读 `debug_result`。
- `verify_iterations` → 删除（verify 不存在，无 stage loopback 计数）。

---

## 7. transition_table 简化

| | 现状 | redesign 后 |
|---|---|---|
| deploy | `deploy_failed → codegen`（死边，halt 抢占） | **删**（无 deploy stage） |
| verify build | `build_failed → codegen` | **删**（codegen 内闭环编译自修） |
| verify precision | `precision_failed → precision_debug` | **删**（precision_debug 内闭环精度自修，首轮 run-cases 即门） |
| codegen | — | 新增：`exhausted → __halt__`（编译自修 max_rounds 耗尽） |
| precision_debug | `exhausted → __halt__`（P54 已建） | 不变 |

新图（self_evolve_op）：`codegen → precision_debug → cannbench_adapt → cannbench_eval → ...`。原 deploy/verify 两段 + 三条 loopback 边全消失，codegen/precision_debug 各自 in-session 闭环 + `exhausted→__halt__` 止损（复用 P51/P54 既有出口）。

---

## 8. 决策冻结（D1–D8，草案待审）

### D1 — 删 deploy stage，build+install+smoke 经 `redeploy` CLI 由 codegen agent 调用

deploy 的逻辑全在 `Deployer`（P54 D3 已抽），`redeploy` CLI（P54 D11）已是 build+install+smoke 封装。codegen 的 agent 写完码后调 `redeploy` 自闭环。删 `DeployStage`（删 stage 类 + workflow 图中的 deploy 节点 + transition_table deploy 分支）。§2.5 不留两套：deploy 唯一通路 = `Deployer` 经 `redeploy` CLI。

### D2 — 删 verify stage，build gate 归 codegen、精度首量归 precision_debug

verify 的 build gate（BuildInRepoGate）→ codegen 编译闭环（`redeploy` build 步骤失败即编译错，codegen 自修）；verify 的精度首量 → precision_debug 首轮 `run-cases`（即首量门，已过则短路退出）。删 `VerifyStage` + 图中 verify 节点 + transition_table verify 分支。

### D3 — codegen 产 build_result + deploy_result，不产 precision_result（§6）

codegen transition 经 `redeploy` 产出 `build_result`（编译过）+ `deploy_result`（smoke 过/可调用）。precision 归 precision_debug（产 `debug_result`）。`precision_result` 字段删除，报告换源读 `debug_result`（dispatcher / runner 改读点）。

### D4 — smoke 是 codegen 的接线门（§5），守 precision_debug 边界

smoke 保留在 `redeploy` 内（codegen 调），作为「可调用/可解析」的确定性接线门。其失败域（接线/注册/`.so`）属 codegen 产出物，codegen 自修。**不删 smoke**——它是防接线坏算子流入 precision_debug 的门（删则职责越界或重引入跨 stage 路由，§5.3）。

### D5 — codegen 加 max_rounds 编译自修上限（stop-loss 镜像 precision_debug）

codegen 的编译自修循环需上限（照搬 precision_debug 的 `max_rounds`：user > config > default）。耗尽 → `exhausted → __halt__`（复用 P51/P54 既有止损出口，不新增出口）。codegen transition 断言 `build_result.passed` + `deploy_result.smoke_passed`（确定性保证 + 止损触发点，agent 不能空声称成功）。

### D6 — precision_debug 职责明确为「功能 + 精度」（run-cases 为其门）

precision_debug 经 `run-cases` 拿真实 tensor 测功能 + 精度，in-session 闭环自修。输入契约去掉对 `precision_result` 的依赖（D3 删该字段）；保持 code+cases+golden（P54 D5，debug workflow 可复用）。首轮 run-cases 即「功能首量 + 精度首量」门，已过则短路。

### D7 — 无跨 stage 错误传递（agent 自读完整子进程输出）

codegen / precision_debug 各自 agent 经 CLI 原子能力读**完整** build/run-cases stderr（不截断、落盘），in-session 自修。不经 `last_error` 截断传递——P57-B（无具体错误）随之失效（agent 直接看完整 stderr）。`Deployer` 的 `_run_command` 截断逻辑（stderr[:1500]）改为落盘完整输出 + 返回路径（agent 读文件）。

### D8 — 作者/校验者分离的软保留：客观性由确定性测量保

precision_debug 既测又修（P54 已先例突破）。pass/fail 判据是**确定性测量**（`run-cases` 的 max_diff vs threshold，agent 无法伪造）——客观性由测量保、不由 stage 分离保。codegen 同理：编译过/不过 + smoke 过/不过 是确定性事实，agent 无法空声称。两个 stage 的 transition 都做确定性断言（D5/D6）兜底。

---

## 9. 决策拍板（Q1-Q5，用户 2026-07-09 确认）

1. **Q1 范围 = 仅 self_evolve_op**（本步落地）。generate_ascendc / generate_ascendc_dev / generate_ascendc_se 同类问题（deploy/verify 死边/截断 + `precision_failed→codegen` 无 in-stage precision_debug 闭环）记 **L1 P58**，作**中优 follow-up，须与本方案一致**（§9.1）。本步 `DeployStage`/`VerifyStage` 类**保留**（generate_* 仍依赖），仅 self_evolve_op 图摘除 deploy/verify 节点。
   > ⚠ **已被 §12 覆盖（2026-07-09）**：范围改为 **Option II 全局一致**（全 5 workflow、删 `DeployStage`/`VerifyStage` 类、P58 吸收）。下文 Q2-Q5 仍有效。
2. **Q2 复用 `redeploy`**：codegen 编译自修每轮复用 `redeploy`（build+install+smoke，P54 已建），**不新增** `build` 能力（单一通路 §2.5）。
3. **Q3 报告换源**：`final_build_result`（finalize）读 codegen 产 `build_result`；dispatcher 精度报告读 precision_debug 产 `debug_result`（替代 `precision_result`）。L4 实施 grep 核对所有消费者。
4. **Q4 verify 完全吸收**：build gate 归 codegen 编译闭环、精度首量归 precision_debug 首轮 run-cases，verify 无残余角色。
5. **Q5 full_test 随 P58**：full_test 的 verify 删除归 P58 follow-up（与 generate_* 一并），本步不动。

### 9.1 generate_ascendc/dev/se 一致性约束（P58 follow-up，中优）

generate_* 三个 workflow 目前仍走 `codegen → deploy → verify` 旧路：`deploy_failed→codegen` 死边 + stderr 截断（P57 适用）、`precision_failed→codegen`（无 in-stage precision_debug 闭环）。**同类问题已记 L1 P58，作中优 follow-up**。收口原则：

- **须与 self_evolve_op 本方案一致**：P58 收口时 generate_* 同样删 deploy/verify、codegen 内闭环 build、precision 失败进 precision_debug（或等价 in-stage 闭环），**不另立第二套架构**。
- **`DeployStage`/`VerifyStage` 类本步保留仅因 generate_* 仍依赖**——P58 收口后随 generate_* 切换而删（§2.5 过渡期并存限时手段，P58 为其收口步；不允许无限期存续）。
- **Deployer 单一通路不破**：generate_*（stage 调 `Deployer.deploy`）与 self_evolve_op（agent 调 `redeploy` CLI → `Deployer.deploy`）共用同一 `Deployer`，差异仅在编排方（stage vs agent），非两套实现——故本步不构成 §2.5 双通路债。

---

## 10. 与现有工作的关系

- **P54（precision_debug in-stage 闭环，已落地）**：本条是其原则的前移——同一套原子能力（`redeploy`/`run-cases`）+ in-session 闭环，调用方从 precision_debug 扩到 codegen。P54 是本条的直接先例与地基（`Deployer`/CLI 已建，直接复用）。
- **P57（deploy 失败无 loopback + 无错误，L1）**：本条的触发与覆盖。redesign 删 deploy stage → P57-A/B 两现象随之失效（被绕开，非就地修，同 P54 绕开 P53）。
- **P53（精度反馈死边/失真，被 P54 绕开）**：同类「transition_table 死边 + 错误信息丢失」现象。本条 redesign 是 P54 思路的进一步推广（不只精度，build/deploy 也 agent 内闭环）。
- **P45/P47（设计侧 in-stage 闭环 + 反馈消费自检）**：in-session 闭环的同形先例。本条让 codegen/precision_debug 都遵循。
- **P51/P46（`exhausted→__halt__` 止损 + halt 控制流）**：本条 codegen 的编译自修 stop-loss 复用同一止损出口（D5），不新增出口。
- **CLAUDE.md §2.5（唯一通路）**：D1 删 deploy stage 后，build/deploy/smoke 唯一通路 = `Deployer` 经 `redeploy` CLI，不留 stage + CLI 两套。
- **CLAUDE.md §2.7（核心归 skill、脚手架外移）**：build/install/smoke/run-cases 是确定性脚手架，封装 CLI（P54 D10/D11 已建）；codegen/precision_debug 的核心调试/编码引导归 skill。
- **CLAUDE.md §1.2（四把尺子）**：可维护（删两冗余 stage，消跨 stage 传递）/ 可扩展（同类「agent 内闭环」自动归位）/ 可诊断（agent 读完整 stderr，无截断丢失）/ 架构合理（build/deploy 职责落回 codegen，不外包给独立 shell stage）。

---

## 11. 四把尺子自检（§1.2）

| 尺子 | 评估 |
|---|---|
| 可维护 | ✅ 删 deploy/verify 两个夹层 stage，消除跨 stage `last_error` 传递；两 agent stage 各自单一职责闭环 |
| 可扩展 | ✅ 同形「agent 内闭环 + 原子能力」模式：未来新调试维度（如性能调试）自动归位为「新 agent stage + 复用/新增原子能力」，不再夹独立 shell stage |
| 可诊断 | ✅ agent 直读完整子进程输出并落盘（D7），P57-B 截断丢失失效；失败留完整可观测信号 |
| 架构合理 | ✅ build/deploy 是 codegen「让代码跑起来」的职责延伸，落回 codegen；功能+精度是 precision_debug 的职责，不外包给 verify shell；stop-loss 复用既有出口不越层兜底 |

---

## 12. 范围修订：self_evolve_op-only → Option II 全局一致（2026-07-09 后续决策，权威覆盖本文件其余 self_evolve_op-only 表述）

### 12.1 触发：共享 codegen stage 使「self_evolve_op-only」与「codegen 拥有 build 闭环」不可兼得

§4 目标态要求 codegen 的 agent 在会话内调 `redeploy` 自闭环 build/编译。但 `CodegenStage` 是 5 个 workflow **共享** stage——其 build 闭环行为无法只对 self_evolve_op 生效：

- 全局开（所有 workflow 的 codegen 都 build 闭环）+ generate_* 仍挂独立 deploy stage → **重复 build**（codegen 已 build+smoke、deploy 再 build+smoke），冗余且 codegen 的 build_result 被 deploy 覆盖。
- 只对 self_evolve_op 开 → 需 codegen 按 workflow/flag 分支决定是否 build，stage 核心行为条件化（等效两套 codegen 行为，违背 §2.5 精神）。

故 codegen 拥有 build 是 **all-or-nothing**。用户在获悉此约束 + §12.2 真实范围后，于 2026-07-09 改拍 **Option II：全局一致**，覆盖原 Q1 的 self_evolve_op-only。

### 12.2 真实范围（实施前 grep 取证，大于原 L3/L4 框定）

`precision_result` 消费者比 §6.2 列的全，删 deploy/verify 两 stage 类的 blast radius 更大：

- **perf 硬依赖 precision_result**：`PerfStage.input_contract().requires` 含 `precision_result`；`PrecisionPassedGate`（perf 门槛）读 `precision_result.passed`（精度不过不测性能）。→ Option II 下 precision_debug 排 perf 前、产 `debug_result`，perf 门槛换源 `debug_result`。
- **integrate 读 precision_result 为死代码**：`VerifyCompleteGate` 读 `precision_result` 进局部变量后未用（只判 `build_result`）。→ 删该死读。
- **VerifyStage 被 full_test 复用**（test_suite 占位）+ **~10 个测试文件直接 import VerifyStage**（test_stages 的 `TestVerifyStage`/`TestVerifyStageStubbed` 整类、test_verify_precision_feedback[P53]、test_loopback、test_plan_a_inrepo、test_verify_testcase_source、test_verify_golden_contract、test_stage_failure_status verify 部分、test_test_design_e2e）。删 `VerifyStage` 类 = 这些测试删除/重写。`DeployStage` 同理（test_npu、test_self_evolution_stages `TestDeployStageContracts`）。
- **generate_ascendc/dev 现无 precision_debug**（走 `precision_failed→codegen`）。Option II 给二者加 precision_debug = **语义变更**：精度失败从「回 codegen」变「precision_debug agent 自修」；perf `tuned→verify` 改 `tuned→precision_debug`（perf 改码后重验精度）。
- **generate_ascendc_se 无需改**：design-only（entry→context→requirement→design→finalize），无 codegen/deploy/verify/perf。

### 12.3 决策覆盖（原 §9 Q1 / §9.1 / §6.2 / §7 的 self_evolve_op-only 表述以下列为准）

- **范围**：覆盖为**全 5 workflow 全局一致**（generate_ascendc/dev/se、full_test、self_evolve_op）。`DeployStage`/`VerifyStage` 类**本步删除**（无消费者后留死类违背 §1.4；不再「保留」）。
- **§9.1 / P58**：generate_* 一致性约束**吸收进本步**——P58 与 self_evolve_op 同步收口，不再中优 follow-up。L1 P58 状态改「吸收进 step-31」。
- **§6.2 precision_result 消费者**：补全 perf（换源 debug_result）+ integrate（删死读）；其余（codegen 反馈随 B5 删、precision_debug guard 随 C 删、dispatcher/runner 报告换源 debug_result）不变。
- **§7 transition_table**：generate_ascendc/dev 同 self_evolve_op——删 deploy/verify 分支、加 codegen/precision_debug `exhausted→__halt__`、perf `tuned→precision_debug`。
- **smoke 归属（§5）不变**：Option II 下 codegen 全局拥有 build，smoke 在 codegen 调的 `redeploy` 内、仍守 codegen 接线门，§5 前提成立、无需修订。

### 12.4 四把尺子复核

全局一致优于 self_evolve_op-only：可维护（无 flag 分支、无双 codegen 行为）/ 可扩展（新 workflow 自动归位两 agent stage 模式）/ 可诊断（全链路 agent 读完整 stderr）/ 架构合理（build 归 codegen、功能+精度归 precision_debug，全 workflow 一致、无残留 verify shell）。代价是本步范围大（删两类 + 测试 churn），但无共存债、无 §2.5 双通路。

---

状态：**方案冻结 → §12 范围修订（Option II 全局一致，2026-07-09）**。主导方向 = 两 agent stage（codegen / precision_debug）各自 in-session 闭环 + build/deploy/smoke/run-cases 降为 `redeploy`/`run-cases` 原子能力（P54 已建，复用）+ 删 deploy/verify（**全 5 workflow，含 `DeployStage`/`VerifyStage` 类**）；smoke 守 codegen 接线门、run-cases 守 precision_debug 功能+精度门（§5，正交都必要）；codegen 产 build_result+deploy_result 不产 precision_result（§6 + §12.3 补 perf/integrate）；transition_table 简化（§7 + §12.3 全 workflow）。**范围 = 全 5 workflow 全局一致**（P58 吸收，§12）。L4 已按 Option II 修订（`34-capability-sink-redundant-stages-impl.md`）。L2 step 31 跟踪本条。
