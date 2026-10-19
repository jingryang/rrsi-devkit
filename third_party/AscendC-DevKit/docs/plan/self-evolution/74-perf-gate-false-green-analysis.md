# 74 — perf PerformanceGate 静默 no-op false-green 收口（L3 方案分析）

> 工作线：self-evolution / perf 门 false-green
> 性质：**L3 方案分析** —— 有哪些选项、选哪个、为什么。**调研中**（待用户拍板范围）。
> 对应 L1：[[P102]]（`06-problems.md`）。前序/关联：[[P109]]（finalize 用内联 gate 正常，**非同 bug**，另查）。
> 对应 L4：`74-perf-gate-false-green-impl.md`（拍板后写）。
>
> 硬约束：perf 量测跑真实 NPU（NPURunner）→ 实施验证需 NPU 环境（§3.6/§3.11）。

## 1. 问题再陈述（四层）

perf 门的 false-green 不是单点，是四层叠加：

| 层 | 事实 | 后果 |
|---|---|---|
| L1 通用 | `runner.py:_execute_run_gate`(:652-664) 解析 gate 失败（`action.gate` None 且 registry 空）→ **默认 `passed=True`**（:663 "defaulting to passed"） | 任何未接线的 RunGate 都静默 false-green（违 §3.7/§1.2 可诊断） |
| L2 perf 专属 | `perf.py:215` `RunGate(gate_name="performance", evidence=...)` **漏内联 `gate=`**（对照 finalize.py:84 带内联 `gate=BuildInRepoGate()`） | PerformanceGate（perf.py:54-143，整段写好）从未被解析 → 死代码 |
| L3 量测缺口 | `PerformanceGate.evaluate`(:123) 调 `NPURunner.execute(op_spec, test_cases, npu_id, card_pool=...)` **不传 `deploy_result` 也不传 `callable_target`**；NPURunner 两者皆必需（runner.py:279 无 deploy_result→抛 EnvironmentNotAvailableError；:286 无 callable_target→同） | 即便 wire，量测也起不来 |
| L4 redeploy 缺口 | perf-tuner 改 code 后 transition 更新 generated_sources，但 perf 全程无 rebuild+redeploy（deploy 由 codegen agent 在 session 内经 Deployer 做，runner 无 Deploy action） | tuning 轮量 stale .so → 改进无法验证 → false-redesign |

**当前实况**：L1+L2 使 `performance_result.passed` 恒 True → perf.py:220 `if perf_result and not perf_result.passed` **永不进** → **perf-tuner 从未被 spawn**。故 perf **量测与调优双死**（非"会丢"，是本就没生效）。多数算子无 perf constraint → PerfStage skip_reason 跳过；仅声明 perf constraint 的算子才进这条死路。

## 2. 关键事实（影响选项）

- **finalize 是正面对照**：`finalize.py:84` `RunGate(gate_name="build_in_repo", gate=BuildInRepoGate(), evidence=...)` 带内联 gate → runner.py:652 `action.gate` 非 None → 真执行。**RunGate+内联 gate 通路本身是 live 的**，死的是 registry 通路（全仓无注册调用）+ perf 漏写内联 gate。
- **deploy_result / callable_target 在 perf 时点可用**：`state.deploy_result`（state.py:256，codegen agent 经 Deployer 写）+ codegen_manifest 的 callable_target，codegen 阶段已产出，perf 在其后跑 → 状态里本就有，只需 plumb 进 evidence。
- **deploy 是 agent侧行为**：codegen agent 在 session 内跑 Deployer（build+smoke），返 deploy_result。runner/action.py **无 Deploy action 类型**。故 perf 内 redeploy 不是"复用既有 action"，要么 perf-tuner agent 自带 build+deploy、要么 PerfStage 直接调 Deployer、要么新增 Deploy action。
- **`stage.gate()` 是另一条 live 通路**：runner.py:198 `gate = stage.gate()` → PerfStage.gate()=PrecisionPassedGate（精度前置检查，debug_result.passed）→ 真跑。本问题**专在 RunGate+registry 通路**，不动 stage.gate()。
- **PerformanceGate 已含 try/except stub 回退**（perf.py:124-128）：`enable_stubbed=True` 时 NPURunner 异常→stub；否则 raise。故 wire 后缺 deploy_result 会 raise（非静默），除非显式 stub。

## 3. 选项

### 方案 M（Minimal honest-fail）—— 只修 L1

`runner.py:_execute_run_gate`：gate 解析失败时 **不再默认 passed**，改 raise 配置错误（"RunGate gate_name=X 不可解析：既无内联 gate 也未注册"）。
- 效果：任何未接线 RunGate **loud-fail** 而非 false-green（§3.7）。perf 遇 perf constraint 时会报错（而非假过）。
- 不做 L2/L3/L4：perf **不量测**，只是把"假过"变"真错"。
- 代价：声明 perf constraint 的算子会在 perf stage 报错（honest break），perf 功能仍不可用。

### 方案 W（Wire + measure，**推荐**）—— 修 L1+L2+L3，tuning 诚实降级

1. **L1**（同方案 M）：runner unresolved RunGate → raise（通用 §3.7 修复，perf+finalize+未来通用）。
2. **L2**：`perf.py:215` 加内联 `gate=PerformanceGate()`（对齐 finalize 范式，§2.5 单一通路；registry 死路不再依赖）。
3. **L3**：evidence 加 `deploy_result=state.deploy_result` + `callable_target`（从 codegen_manifest）；`PerformanceGate.evaluate` 把两者透传给 `NPURunner.execute`。
- 效果：perf **真量测 codegen 部署的 .so**（单次：达标→forward，未达标→ redesign/loud）。
- **tuning 诚实降级**：tuning 本就死（见 §1），本方案不假装激活它——perf 成为**真实单次量测门**（量→过/不过），tuning loop 待 L4（redeploy 架构）另开。resolve_condition 相应收敛（去掉基于 dead tuning 的 "tuned" 路由，或保留但标注待 redeploy）。
- 代价：未达标算子无 tuning 缓冲、直走 redesign（honest：设计确不达标）。比 false-green 正确，比 false-red（stale 量测）也正确。

### 方案 F（Full）—— L1+L2+L3+L4，激活 tuning

方案 W 全部 + **L4 redeploy**：perf-tuner 改 code 后，量测前 rebuild+deploy。redeploy 机制三选一（L4 定）：
- (a) perf-tuner agent 自带 build+deploy（像 codegen agent 那样 session 内 Deployer）；
- (b) PerfStage transition 直接调 Deployer（Python，确定性）；
- (c) 新增 `Deploy` action + runner executor。
- 效果：perf 完整可用（量测 + 调优循环 + 复量）。
- 代价：最大；触及 deploy 架构（runner 无 Deploy action，要新增机制或让 agent 扛 build）；perf-tuner agent 契约变（要产 .so 不只改源）。

## 4. 推荐：方案 W

**判据**：P102 的**缺陷是 false-green**（perf 假过）。方案 W 把它变成**真量测**（L1-3）+ **诚实降级 tuning**（不假装激活一个本就死、且无 redeploy 支撑的功能）。方案 F 的 tuning 虽好，但 tuning **当前根本没生效**（gate no-op→从不 spawn perf-tuner），所以"激活 tuning"是**新增功能**而非"修 bug"——不该塞进 P102 这个 false-green 修复里（§1.2 方案合理性：修复落在缺陷正确的层）。方案 M 太小（只 loud-fail，perf 仍不可用）。

**方案 W 的四把尺子**：

| 尺 | 方案 W | 方案 M | 方案 F |
|---|---|---|---|
| 可维护 | ✅ perf 对齐 finalize 内联 gate 范式；registry 死路不再被依赖（单一通路 §2.5） | ✅ 通用 | ⚠ 引入 redeploy 新机制/agent 契约变 |
| 可扩展 | ✅ L1 通用：未来任何 RunGate 未接线都 loud-fail 非 false-green | ✅ 最通用 | ⚠ 新机制要维护 |
| 可诊断 | ✅ L1 把静默 false-green 变 loud error；perf 真量测或真报错 | ✅ loud-fail | ✅ |
| 架构合理 | ✅ 修在 gate 契约层（L1）+ perf 接线层（L2-3）；tuning 诚实降级非越层假装 | ✅ 但半截 | ⚠ tuning+redeploy 是新功能，混进 bug 修复 |

## 5. 反驳与边界

- **"方案 W 让未达标算子直走 redesign，太重"**：未达标是客观事实（量测为证）；tuning 是给"差一点"的缓冲，但它本就死、且需 redeploy 才有意义。诚实报未达标→redesign（或 human）比 false-green（假过）和 false-red（stale 量测误判）都正确。tuning 作 follow-up（方案 F）按价值再排期。
- **"L1 通用 raise 会误伤 finalize 吗"**：不会。finalize 带内联 gate（BuildInRepoGate）→ `action.gate` 非 None → 不进 unresolved 分支。L1 只命中"既无内联 gate 又未注册"的 RunGate（当前仅 perf）。
- **"L3 plumb callable_target 哪来"**：codegen_manifest 已声明（codegen 阶段产出，runner.py:286-293 校验过）。perf 在 codegen 后跑，state.codegen_manifest 可读。落地时核对字段路径。
- **"enable_stubbed 路径"**：保留 PerformanceGate 既有的 try/except stub 回退——NPU 不可用且 enable_stubbed 时 stub 量测（honest stub，标 stubbed=True），不破坏现有 stub 语义。

## 6. §2.9 合规

- **L1（runner honest-fail）= §1.3/§3.7 框架职责**：契约/配置校验（RunGate 可解析性）权威在框架，确定性可判；unresolved→raise 是"加载期校验优于运行期暴露"的运行期对应（动作执行期即拒，不静默向前）。非 §2.9 违反（契约形状归框架）。
- **L2-3（wire + plumb）= 接线修复**：把已写好但没接线的 PerformanceGate 接上，非新逻辑。
- **tuning 降级 = §2.9 诚实**：不假装激活一个无 redeploy 支撑的 loop（那会是 discover+regenerate 病态：量 stale .so→误判→重调→再量 stale）。诚实标"tuning 待 redeploy 架构"。

## 7. 决策（待用户拍板范围）

**推荐方案 W**（L1+L2+L3，tuning 诚实降级为 follow-up 方案 F）。

待用户定：
1. **范围**：方案 M / **W（推荐）** / F？
2. 若 W：未达标算子的路由（redesign / human / 新增 perf_not_met 终态）？
3. tuning（方案 F）排期：本次 follow-up 留档，还是一并做？

拍板后出 L4（`74-perf-gate-false-green-impl.md`）。

## 8. 实际决策：**deferred（休眠功能，不做）**——2026-07-24

用户质询"性能调优没正式上线、skill 可能不可用，还有必要改吗"+ "做了 L1 workflow 会不会必然失败"。核实后判定 **P102 整体 defer，什么都不做**：

**关键事实（核实）**：
- perf-tuner agent 存在（`.claude/agents/perf-tuner.md`），perf 在默认 graph（workflow.py:333/517），**但真实 requirement 无一声明 perf constraint**（只 UT fixture 声明 `Constraint(kind="performance")`）。
- → PerfStage 永远 skip_reason 跳过 → false-green 路径**真实 run 从不执行**。P102 是**潜伏缺陷**，非活跃 blocker。

**L1 不会让 workflow 必然失败（但仍不做）**：
- 全仓唯一 unresolved RunGate 是 perf 的 `RunGate(gate_name="performance")`（finalize:84 带内联 `gate=BuildInRepoGate()`，总解析，不受 L1 影响）。
- PerfStage 只在 `has_perf_target`（声明 perf constraint）时才 emit 该 RunGate（perf.py:182-190）；真实 run 无声明 → 从不 emit → L1 raise 从不触发 → **L1 对真实 run 是 no-op**。
- 即便如此不做：零价值（改没人走的路径）+ 徒增"谁声明 perf constraint 就炸"的陷阱。

**为什么不选 W**：方案 W（让 perf 真量测）= 在没上线、skill 可能不可用的功能上盖楼，违 §1.2 方案合理性（修复不该为未上线功能添砖加瓦）。

**去向**：
- L2-L4（perf 量测+调优）：**归 perf 功能正式上线工作**（那时 skill 可用、真有人声明 perf constraint，作为上线的一部分做 W/F）。
- L1（runner §1.3/§3.7）：**攒到真有人动 runner 或上线 perf 时一并做**（不单独为休眠路径动 runner 契约）。
- **本 L3 不出 L4**（无可实施内容）。

**复盘**：P102 教训——loopback/iteration 专项里，**先判"缺陷在活跃路径还是潜伏路径"**再决定投入。潜伏缺陷（如 perf false-green）按 P100 节奏投入是浪费；应 defer 到其功能激活时。这条判据应用到 P103-P111 的逐条取舍。
