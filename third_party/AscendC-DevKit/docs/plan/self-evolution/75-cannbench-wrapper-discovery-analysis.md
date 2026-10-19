# 75 — cann_bench/__init__.py wrapper 漏写收口（L3 方案分析）

> 工作线：cann-bench 发现链 D（A=import [[P95]] / B=_C 收录 [[P96]] / C=wrapper 传播 [[P97]] / **D=wrapper 内容 本条**）
> 性质：**L3 方案分析** —— **已拍板（方案 G + 退役 cannbench-adapt agent），冻结；已实施（UT/ST 绿，2026-07-25）**。
> 对应 L1：[[P112]]（`06-problems.md`）。
> 关联：[[P97]]（wrapper 传播缺口，已修 redeploy；本条是它没修的**内容**缺口）、[[P100]]（构造性内容保证，同型教训）、issue.md `/home/x00584171/temp/issue.md`（机理实证）、§4.3（h3-design-resolution，rationale 修订见 §8）。
> 对应 L4：`75-cannbench-wrapper-discovery-impl.md`。

## 1. 问题再陈述

cann-bench 发现算子走 **Python 命名空间扫描**（`scan_interfaces` 的 `dir(cann_bench)` / `inspect.getmembers`），只看 `cann_bench/__init__.py` 里**显式 `def` 的 wrapper**。`TORCH_LIBRARY_FRAGMENT`（`_C.so`）只注册进 C++ Dispatcher（`torch.ops.cann_bench` 投影），**不回写 Python `__dict__`**。故：

- **debugger/harness** 走 `torch.ops.cann_bench.<symbol>`（Dispatcher）→ **不需 wrapper** → 能调（smoke 已验证）。
- **cann-bench** 走 Python 命名空间扫描 → **必须有 wrapper** → wrapper 漏写/错就发现不到/调不起。

wrapper 三维正确性 = {① 存在、② 参数名匹配 golden/proto（cann-bench `func(**golden_params)` 关键字调）、③ 转发目标=`callable_target.symbol` 末段（真实注册名，如 `npu_exp`）}。**三维全交 LLM `cannbench-adapt` agent，无确定性保证**——prompt（cannbench_adapt.py:306-330）只约束 ③（转发目标），不约束 ①②。

间歇性实证：同一 manifold 算子，20260715 run wrapper **在**、issue.md(2026-07-24) run wrapper **不在** → LLM 非确定性。

## 2. 关键事实（影响选项）

- **wrapper 是 manifest 的纯函数，完全可派生**：op_name（`codegen_manifest.op_name`）+ 转发目标（`callable_target.symbol` 末段）+ 参数名（`align_schema_params(op_spec)`，**已存在**，返 proto 参数序：inputs 名 + attrs 名）。真实 wrapper（advance_step_v2/manifold）都是 `def {op}({params}): return torch.ops.cann_bench.{symbol}({params})` 的极简转发——**LLM 在 wrapper 上不提供任何 manifest 之外的信息**。
- **P10 已是确定性后处理的先例**：cannbench_adapt 的 `_rename_mdef_schema_if_needed` 确定性对齐 m.def **C++ schema** 参数名（为关键字调用正确）。wrapper 是同一张契约的 **Python 侧**，P10 没覆盖。方案是对 P10 的自然延伸。
- **P97 方案2（commit `11a5bd73`）已在 eval 期检测 `operators==0`→infra error**：失败已**可见**（非静默 0）。但可见仍=失败（op 无法评测、run 白费）。本条要的是**不让它发生**（构造性保证），而非发生后 loud 报。
- **mdef_parse 原语可复用**：`parse_mdef_params`/`rename_mdef_schema` 已集中 `domain/mdef_parse`（§2.5）。wrapper 签名解析/对齐可复用同源原语，不另立通路。
- **CMake 注册不在本条范围**：P96（commit `4594229c`，clean_build 强制 _C reconfigure）已治 `_C` 不收录新算子；issue.md 的 manifold 是 `_C` 已注册、**只缺 wrapper**。故本条专攻 wrapper，不碰 CMake。

## 3. 选项

### 方案 G（Generate 确定性生成，**推荐**）

不让 LLM 写 wrapper。cannbench_adapt transition 确定性**生成** wrapper 并注入 `cann_bench/__init__.py`：
- 从 manifest 派生：`def {op_name}({align_schema_params(op_spec)}): return torch.ops.cann_bench.{symbol末段}({同参数})`。
- 幂等注入：解析现有 `__init__.py`，已有该 op 的 `def` → 校验/替换；无 → 追加。
- cannbench-adapt agent **保留** CMake/registry（非可派生的仓约定 glue）；wrapper 收归确定性（与 P10 同层）。
- **三维一次修到位**：① 生成必存在；② 参数名取 proto（=golden）→ 关键字调对；③ 转发目标取 symbol末段 → 真。

### 方案 V（Validate + fix，P10 延伸）

LLM 写 wrapper 后，stage 确定性**校验 + 修**：解析 `__init__.py` 的 wrapper，比对 ①存在 ②参数名==proto ③转发目标==symbol，不一致就 add/rename/correct + rebuild。
- 镜像 P10 的 rename 范式。
- 但解析/修一个 Python `def`（含可能的 type annotation/默认值/keyword-only 标记）比 rename m.def schema 字符串复杂；幂等/反复修的边界多。

### 方案 D（Detect + loud-fail，最小）

LLM 写完后确定性**检测** wrapper 三维；不对就标 adapt failed（loud）。
- 比 P97 方案2（eval 期 operators==0 检测）更早报（adapt 期），但**不修**——只把失败提前可见。
- 仍需 rerun 碰运气对齐；属 §2.9 禁止的 discover+regenerate 形态的弱化版。

### 方案 E（External——改 cann-bench）

cann-bench `scan_interfaces` 改扫 `torch.ops.cann_bench`（Dispatcher），不再要 wrapper（issue.md 长期建议）。
- 根治：harness 与 cann-bench 同路，无 wrapper gap。
- 但 cann-bench 是**外部仓**，非 devkit 可控；需跨仓协调。记为长期，非本条 devkit 修复。

## 4. 推荐：方案 G

**判据**：wrapper 是 manifest 的**纯函数**，LLM 在其上零信息增益、纯非确定性来源 → 该删除 LLM 介入、确定性生成（§2.9 构造性保证优先于检查门；§1.2 可维护）。方案 V 留 LLM 在环但只为它"擦屁股"，多此一举；方案 D 只 loud-fail 不修，仍是 discover 形态；方案 E 是真根治但外部。

**四把尺子（§1.2）**：

| 尺 | 方案 G（生成） | 方案 V（校验+修） | 方案 D（检测+fail） |
|---|---|---|---|
| 可维护 | ✅ wrapper 单一形状、manifest 派生；"为何需要 wrapper"（Dispatcher≠__dict__）编码进生成器 | ⚠ 需解析/修 Python def，边界多 | ⚠ 检测逻辑 + 失败处理 |
| 可扩展 | ✅ 新算子自动获 wrapper，零 per-op LLM 依赖 | ⚠ 每种 def 变体要能解析 | ✅ |
| 可诊断 | ✅ 生成失败（manifest 缺 symbol/params）→ loud；不存在"静默漏写" | ✅ | ✅ loud-fail（但不修） |
| 架构合理 | ✅ wrapper=纯函数 → 生成在桥接层（cannbench_adapt，同 P10）是正确归属；LLM 保留非可派生 glue（CMake/registry），干净分工 | ⚠ LLM 写 + 框架擦，两套 | ⚠ discover 形态（§2.9 弱化版） |

**三维覆盖**：G 一次修 ①存在 ②参数名 ③转发目标（V 也覆盖但更繁；D 都不修只报）。

## 5. 反驳与边界

- **"LLM 写的 wrapper 可能有 type annotation / 仓特定风格"**：annotation 对 cann-bench 关键字调用非必需（调 `func(**params)` 不看类型）。极简转发 wrapper（真实 advance_step_v2/manifold 都是这形）完全可派生。仓若需花式 wrapper，是延伸，不阻塞本条的正确性底线。
- **"幂等注入会不会破坏既有 wrapper / 重复"**：生成器解析现有 `__init__.py`，按 op_name 定位 `def`——有则校验+替换、无则追加。复用 mdef_parse 的"定位+替换"范式（P10 已验证幂等 rename）。
- **"G 生成后还要 rebuild 吗"**：要——wrapper 进 example 源 `__init__.py` 后，走既有 `Deployer.deploy(clean_build=True)`（P96/[[P97]] 已建立的 redeploy per-op 通路）传到 per-op 包。G 只管**内容正确**，传输仍用既有通路（P97 已修）。
- **"方案 E（改 cann-bench）不才是根治吗"**：是，但外部。devkit 侧 G 是"在受控范围内把契约构造性保证"（与 P100 同哲学：不依赖外部改对，先在自有层把不变式立住）；E 作长期跨仓建议并行推进。

## 6. §2.9 合规

- **G = §2.9 偏好的构造性保证**：wrapper 存在性/正确性由生成构造性兜住（不可能漏写），而非放任 LLM 漏写再由 cannbench_eval 的 `operators==0` 检查"发现"（那恰是 §2.9 禁止的 discover+regenerate：发现漏了→rerun producer→LLM 再碰运气写对）。**用构造性预防替代了潜在 discover 门**——比"加门去查"更 §2.9（同 [[P100]] 论证）。
- **wrapper 是确定性可派生**（manifest 纯函数），不是语义/质量问题 → 归框架/桥接层确定性生成，不归 LLM 自闭（与 L3-73 §8"契约形状归框架"同判）。
- **CMake/registry 留 LLM**：那些含仓约定（非纯派生），是 LLM 通用能力的正当用途（§2.7 核心引导归 skill、脚手架外移）。G 不越界替 LLM 做非可派生部分。

## 7. 决策（已拍板 2026-07-25）

**选定方案 G + 退役 cannbench-adapt agent**。冻结，出 L4。

不仅生成 wrapper，且把 CannbenchAdaptStage 收敛为**确定性适配**（退役 LLM agent）：
- wrapper → 确定性生成（manifest 派生）。
- CMake → codegen 强制产 per-op CMakeLists（codegen.py:1564-1569 缺失即报错）+ P96 `file(GLOB)` + `clean_build=True` 覆盖 _C 收录；agent 的 CMake 活冗余。
- registry → cann-bench 用 `__init__.py` wrapper 发现（`dir(cann_bench)`），无 registry.py 要适配。

**为何可退役 agent（§4.3 rationale 修订）**：见 §8。

## 8. §4.3 rationale 修订 + per-repo adapter 生命周期

**§4.3 当初"为什么需要 LLM"（h3-design-resolution.md:395）**："不同仓的发现/注册机制不同……枚举所有仓用 Python 确定性覆盖不现实——会随仓版本膨胀，违反'不进 Python 代码'原则。"

**修订**：该理由把"**通用多仓适配器**"的担忧，套在了一个**实际是单仓专用**的 stage 上。
- `CannbenchAdaptStage` 顾名思义、且实际就是 **cann-bench 专用**（名/prompt/agent 名全 cann-bench 特定），不是通用适配器。
- 它只服务**一个仓**（cann-bench），不存在"枚举所有仓"的膨胀。
- 架构是 **per-repo adapter 模式**：每仓一个适配 stage，互相独立。改 cann-bench 的确定性化、未来仓用 agent，零冲突（§2.5 单一通路在每仓内成立）。

**per-repo adapter 的健康生命周期**：每仓适配器自然演化 = **机制未知时 agent-driven → 机制摸清后确定性化**。
- cann-bench：2026-07-01 引入 agent（机制未知）→ 2026-07-22 P95-P99 把机制彻底摸清并确定性化（scan_interfaces/dir(cann_bench)/TORCH_LIBRARY_FRAGMENT/GLOB/clean rebuild 全已知）→ 现在到了"确定性化"阶段。
- 未来新仓：其适配器从 agent-driven 重新起步（机制未知），摸清后再确定性化——同轨迹，互不干扰。
- 故 §4.3 rationale 修订为：**per-repo adapter 在其仓机制摸清后应收敛确定性**；agent 只服务于"机制未知"的初生期，或真正通用多仓适配器（本 stage 非）。

**对 §1.5/§2.7 的一致性**：§2.7"脚手架/构建文件交 LLM、不固化 Python"约束的是 **skill** 不硬编码仓布局；本改动在 **bridge stage**（cannbench_adapt，本就仓感知、P10 已在此做确定性 m.def rename），确定性生成 **通用** forwarding wrapper（非仓特定脚手架），不冲突。CMake/registry 若确有仓特定变体才留 LLM——但 cann-bench 的 CMake 由 codegen+GLOB 覆盖、无 registry，故全确定性。

**与 [[P100]] 同型**：内容正确性（wrapper 存在/参数名/转发目标）由构造性生成保证，不靠 LLM + 下游 discover（cannbench_eval `operators==0` 检查恰是 discover 门）。§2.9 构造性保证优先于检查门。

拍板后出 L4（`75-cannbench-wrapper-discovery-impl.md`）：确定性 wrapper 生成器 + 退役 agent（删 SpawnAgent + agent.md，§2.5）+ CMake 退役验证步 + UT（三维+幂等+manifest 驱动）+ 全量 UT + heavy_llm ST（用户决策）。
