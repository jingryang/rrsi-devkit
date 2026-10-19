# Phase C 代码生成逻辑 vs 当前工程 codegen stage — 差异分析（迁移参考）

> **范围**：对比 `ascendskills/skills/ascendc-op-full-pipeline/SKILL.md` 的 **Phase C（代码生成）**
> 与当前工程 `src/ascendc_devkit/orchestration/stages/codegen.py`（+ `codegen_init.py`）所派发的
> `ascendc-coder` agent 及其内部 `stage-codegen:ascendc-op-dev-coding` skill。
> **目的**：为「将 Phase C 迁移到当前工程」提供差异基准与去留判断，不是照搬实现。
>
> **L3 边界自检**：本文只写「有哪些差异、为什么、值不值得迁移」，不写「改哪个函数」（L4），
> 不写客观故障现象（L1）。
>
> **裁决纪律**：每项给出 ① 现状对照 ② 迁移收益（pro，先认真替迁移方说话）③ 迁移代价/风险（con）
> ④ 不迁移的风险 ⑤ 决定因素 + 裁决 ⑥ 重评触发条件。**不出现「待评估/可选」**——每项都要能拍板。

---

## 0. 结论先行（TL;DR）

1. **两套架构是同一目标的两种演进形态，不是同一套东西的两个版本。**
   Phase C = 多 subagent 编排链（env-check → s2-analysis → s4 步进循环 → [vf-test] → s5-compile），
   状态由 `dev_record` 文件状态机承载；当前 codegen = 单 `SpawnAgent` + 单 skill（slash 投递）+
   会话内 `redeploy` 闭环，状态由 immutable `State` + `events.jsonl`（Event Sourcing）承载。
2. **当前工程是从 s2/s4/s5 链有意识演进而来的**（memory：capability-sink-redundant-stages、
   soundness-over-minimal-change）。**8 项差异中 7 项裁定「不迁」、1 项「有条件延后」**，无一项「现在就迁」。
3. **唯一有真实价值的缺口**：A5 Regbase 的 **VF 函数隔离精度预验证**（当前只有静态/编译期门）。
   但经核实 A5 Regbase 是**当前演化的少数路径**（主线是 Membase-on-A5-box，见 P65 跨代矩阵），
   故裁定**延后**，并给出明确的「何时该做」触发条件（§3.4）。
4. **三条硬约束锁死大部分「不迁」**：① Event Sourcing 是权威状态载体（§1.1），dev_record 不得并存；
   ② 设计完整性 + fail-fast 是 codegen 前置不变式（§1.3/§3.7），默认值兜底表与之正面冲突；
   ③ 单一通路不留旧债（§2.5），不重建 s2/s4/s5 编排链。

---

## 1. 两套架构速览

| 维度 | Phase C（外部） | 当前工程 codegen |
|---|---|---|
| 编排骨架 | driver（SKILL.md）逐 subagent 派叶子 agent | L3 `CodegenStage` 单 `SpawnAgent` |
| 派发单位 | 4~5 个叶子 subagent | 1 个 agent（`ascendc-coder` / `incremental-developer`） |
| 方法学注入 | 各 agent 读自身 `.md` + driver 注入 prompt 模板 | slash 投递 `ascendc-op-dev-coding`（§4.3） |
| 状态载体 | `{RECORD_DIR}/`（meta/progress/coding_index/clarification/coding_plan/history/env_snapshot） | immutable `State` + `events.jsonl` + staging/ JSON |
| 步进粒度 | s4 按 coding_index 检查点组步进，每子步独立 subagent + progress.md 留痕 | skill Step4 ①→⑤ 一次性落盘，单 agent，每文件即时写 |
| 编译闭环 | s5 subagent + `classify_compile_error.sh` + driver 回退 s4 | agent 会话内 `ascendc-devkit redeploy`，`transition` 断 `smoke_passed` |
| A5 处理 | `ascendc-vf-test-agent` 逐 VF 函数隔离精度预验证（运行期） | skill Step4 路径三 + Step6 九条静态红线（静态/编译期） |
| 澄清机制 | s3 + C.2.5 默认值表（9 条）自动决断 `[待澄清]` | 无；锁项缺失即 fail-fast |
| Gate 产物 | `codegen_complete.json` 含结构化 `design_inheritance_check` | section 覆盖 + manifest callable_target + smoke_passed；skill 自检不持久化 |

---

## 2. Phase C 的多 subagent —— 逐一拆解 + 当前工程对应物

| # | Phase C subagent | 职责 | 产物 | 当前工程对应物 |
|---|---|---|---|---|
| C.1 | `ascendc-op-dev-env-check` | 探测硬件 + 定 programming_model | meta.json（含 ub_size/core_num） | `_materialize_inputs` 由 `chip_programming_model()`/`to_soc_version()` 确定性写（仅 prog_model/chip/soc） |
| C.1.5 | driver inline `dev_record.sh init` | 建 dev_record 骨架 | meta/progress/env_snapshot | 无（State + events.jsonl） |
| C.2 | `ascendc-dev-s2-analysis` | 需求分析 + **coding_index 步骤索引表** + clarification + coding_plan | coding_index.md 等 | 拆到 design substages（general_design/template_division/tiling_results）+ staging 文件 |
| C.2.5 | driver inline 默认值表兜底 | `[待澄清]` → `[默认决策]`（9 条规则） | 改写 clarification.md | 无；fail-fast |
| C.3 | `ascendc-dev-s4-coding` 步进循环 | 按 coding_index 分组步进，每组一 subagent | 各 section 源文件 + progress 留痕 | 单 agent 一次性（Step4 ①→⑤） |
| C.3(VF) | `ascendc-vf-test-agent`（仅 A5） | 逐 VF 函数隔离精度预验证 | `vf_verified/kernel_test/` | 无（静态九条红线 + 编译期 + precision_debug 下游） |
| C.4 | `ascendc-dev-s5-compile` | 编译 + 错误分类 + 重试 + 收尾/git | 编译日志 + git commit | agent 会话内 `redeploy` + smoke 门 |

---

## 3. 逐项裁决（pro / con / 风险 / 决定因素 / 重评触发）

### 3.1 多 subagent 编排骨架（env-check + s2 + s4-loop + s5 整条链）

**现状对照**：Phase C driver 派 5 类叶子 agent，靠 dev_record 在 agent 间传状态；当前 1 个 `ascendc-coder` 全包。

- **迁移收益（pro）**：① 职责切分清晰，单 agent 上下文更小；② 每 subagent 可独立调试/替换；③ 步进可断点续跑。
- **迁移代价（con）**：① 重建多 coordinator，直接违反 §2.5「唯一通路」（当前已把 s2/s4/s5 收敛成单 agent + 能力 sink，memory capability-sink-redundant-stages 记录了这次刻意拆除）；② 必须同时引入 dev_record 状态机（与 Event Sourcing 双源，§1.1 冲突，见 §3.7）；③ 4~5× agent spawn 的延迟/token 成本，self-evolution 批跑 N 算子时放大 N 倍；④ driver 编排逻辑（stage4_scheduler.sh / dispatch JSON / RETURN 解析）是新的故障面。
- **不迁移的风险**：单 agent 在超复杂算子上仍可能上下文吃紧——但见 §3.2，根因已修。
- **决定因素**：当前架构是**为消除这条链而演进的**，回灌即倒退。
- **裁决：不迁。**
- **重评触发**：见 §4.5 收紧版——post-fix 环境（skill 投递 + staging 源产物 + 禁 grep 生效）下，
  出现「翻译本身装不下已分解蓝图」型溢出（排除 grep/截断/429 已知可修类）。首选缓解是设计层
  补 focus 导航（§3.3 折进），重建 subagent 是最后选项。

### 3.2 s4 步进式多 subagent（编码粒度）

**现状对照**：Phase C 把编码拆 `4.0→A→B1→B2→C.0~C.n→E→F`，按检查点组分 subagent，progress.md 逐步留痕，compact 后续跑；当前单 agent 按 skill Step4 ①TilingData→②Host→③Kernel→④ACLNN→⑤Plugin 一次性落盘。

- **迁移收益（pro）**：① 步级断点续跑，compact 不丢已完成步骤；② 每步绑「自检关注点」，定向查坑；③ 单步上下文更小。
- **迁移代价（con）**：① **历史溢出根因已修**——codegen-skill-delivery/01-problems.md P1 记录 ascendc-coder 在 moe_re_routing 跑到 366K/turn287/50min 死亡，但 P2 根因是**skill 未投递**（agent 41 次 grep SDK 头文件），现已由 `_with_trigger` slash 投递修复。用「步进 subagent」去解一个「skill 投递 bug」是错配；② 引入 stage4_scheduler.sh + progress.md 步表 + RETURN 解析三套确定性脚本，维护面陡增；③ 步间回 driver 重派 = 反复重建 agent 上下文（每步都要重读 coding_index + 详设），总 token 反而更高。
- **不迁移的风险**：复杂算子仍可能溢出。**但当前已有三道缓解**：(a) skill 投递（禁 CANN grep，P2 已修）；(b) staging 文件化输入（design_spec 等不进 prompt context，靠路径引用）；(c) 每文件即时落盘 + session resume 侧车（codegen.py:202-222，跨 run 续跑）。
- **决定因素**：步进 subagent 的主卖点（防溢出）针对的根因已被更轻的手段（skill 投递 + staging）解决；剩下的步级续跑被 Event Sourcing + session resume 覆盖。
- **裁决：不迁。** 若要吸收其「每步自检关注点」的价值，正确形态是把它折进 design 产物或 skill（见 §3.3），而非重建步进编排。
- **重评触发**：同 §3.1（§4.5 收紧版）。

### 3.3 coding_index 步骤导航表（步→详设章节/参考代码/关键API/自检关注点/~行数）

**现状对照**：Phase C s2 产出 coding_index.md 把「每个编码步」与「详设章节 / 参考代码行范围 / 关键 API / **预判自检关注点** / ~行数」显式绑定；当前最接近的等价物是 staging 的 `tiling_results.json`（`buffer_kernel.kernel.pseudocode` 实现蓝图主源）+ `general_design.json`（sections 骨架）+ `template_division.json`（锁定决策如 BUFFER_NUM）。

- **迁移收益（pro）**：① **「步→自检关注点」是真有价值的导航信号**——当前 tiling_results 是伪代码（告诉你算什么），不是导航表（告诉你按什么序写、每步盯什么坑），agent 要自己从伪代码推断；② ~行数预判可防过度工程化。
- **迁移代价（con）**：① **与 tiling_results 职责重叠**——两者都是「实现蓝图」，并存即双份表示，违反 §2.5 单一表示；② 要么新增 design subagent 产 coding_index（codegen 上游膨胀 + 新 skill 投递链），要么 codegen 内派分析 subagent（违反单 agent，§3.1）；③ coding_index 的「参考代码行范围」列依赖参考算子存在——当前 `reference_code` 由调用方显式注入、可能为空，该列大量落空，导航价值打折。
- **不迁移的风险**：复杂算子上 agent 可能漏掉某步的特定坑（如 mask 边界、dtype cast），靠 Step6 统一自检兜底——但 Step6 是事后检查，非事前导航，定位偏晚。
- **决定因素**：**有真实价值但形态必须改**——不能作为独立 artifact/独立 subagent 迁；应把「每步自检关注点」增量折进**已有** design 产物（让 general_design/template_division 的 section 描述带上 focus 提示）或 skill Step4 各 section 段，保持单一通路。
- **裁决：不迁（作为独立 artifact/subagent）；价值以「折进既有产物」吸收。** 这是唯一一项「价值真、但迁移形态要改」的——区别于纯不迁。
- **重评触发**：Step6 事后自检在 ≥2 个算子上反复漏同一类坑（如 dtype cast），证明事前导航确有必要时，再考虑折进。

### 3.4 A5 Regbase 的 VF 函数隔离精度预验证 ← **唯一真缺口（延后）**

**现状对照**：Phase C 在 A5 时由 s2 在 Compute 步前插 `.VT.{M}` 子步，driver 派 `ascendc-vf-test-agent`，用 regbase-vf-test 工具链对**每个 VF 函数**做独立 kernel + Python 脚本，隔离编译运行验证精度，通过后才集成进 Compute；当前 A5 只靠 skill Step4 路径三（VF 入口 + RegTensor + 九条强制约束）+ Step6 静态自检（VF 签名/RegTensor≤32/MaskReg≤8/SIMD-SIMT 隔离/GetPhyAddr/Membase API 入侵），全是**静态/编译期门**；VF 组合的**运行期精度**只能等下游 `precision_debug` 在整 kernel 级暴露（且 precision_debug 是通用环，不按 VF 函数隔离）。

- **迁移收益（pro）**：① **真盲区**——VF 函数组合的精度错（如反量化 scale 预处理顺序、Interleave 参数序、Cast trait 选错）静态规则查不出，整 kernel 跑精度时才爆，定位成本高；② 隔离验证把「整 kernel 错」降维成「单 VF 函数错」，二分定位更快；③ 这是 Phase C 唯一没有等价物的能力。
- **迁移代价（con）**：① **依赖 regbase-vf-test 工具链**（external 独立 skill），引入重依赖；② **heavy_llm 级成本**（每 VF 函数一次 kernel 编译 + NPU 运行 + Python 验证，分钟级起，§3.11 须用户确认）；③ A5 专属分支逻辑（codegen 内按 programming_model 路由），增加条件路径；④ 仅对 A5 Regbase 有效——而 **A5 Regbase 是当前演化的少数路径**（P65 跨代矩阵：主线是 Membase-on-A5-box；self-evolution 用例里 A5 多指 cases-loader 步骤标签，非 Regbase codegen）。
- **不迁移的风险**：A5 Regbase 算子的 VF 精度错要到 precision_debug 暴露，且不隔离到函数级，调试更慢、更易在多 VF 函数间误判。
- **决定因素**：**价值真，但当前 ROI 低**——少数路径 × heavy 成本。延后到 A5 Regbase 成为主线目标时再做。
- **裁决：延后（不现在迁），形态预定为「A5 专属 capability sink」（codegen 后/precision 前，loopback codegen），不照搬 vf-test-agent 编排链。** 作为更廉价的过渡：强化 skill 的静态 VF 检查 + 确保 precision_debug 的 dumptensor 定位对 VF 函数可用。
- **重评触发（任一即启动评估）**：① A5 Regbase 算子在演化目标中占比上升（如 ≥20%）；② 出现 ≥1 例「整 kernel 精度错、根因是单 VF 函数、静态规则未拦、precision_debug 定位耗时显著」的实证。

### 3.5 编译错误结构化分类（classify_compile_error.sh，C-SYM/C-TYP/C-DUP/C-LNK/C-API）

**现状对照**：Phase C s5 用脚本分 5 类，据此回退 s4 的对应 sub-stage；当前 build 闭环由 agent 会话内 `redeploy`（build→install→smoke）自驱，agent 直接读 `subprocess/*.log` 自修，`transition` 只断 `smoke_passed`。

- **迁移收益（pro）**：① 结构化分类可做统计/告警（哪类错最多）；② 路由更精细（C-LNK 回链接段、C-API 回 API 段）。
- **迁移代价（con）**：① 当前 `smoke_passed` 是**严格更强**的门（编译通过 + 符号可解析 + 算子可调用），分类只是 smoke 失败时的归因，agent 读 stderr 已能归因；② 外置分类脚本 vs agent 隐式分类 = 两套错误 taxonomy，违反 §2.5；③ 分类脚本依赖正则匹配编译器输出，CANN 版本一变就脆。
- **不迁移的风险**：无——smoke 门 + 断路器（`max_consecutive_failures`/infra halt）已覆盖闭环与止损。
- **决定因素**：smoke 门是更强收敛点，分类是冗余归因层。
- **裁决：不迁。**
- **重评触发**：需对编译错误做跨算子统计分析（运营/质量度量需求）时，再考虑——但那是观测层需求，非 codegen 闭环需求。

### 3.6 Gate C 的结构化 design_inheritance_check 持久化（维2 四字段 + 维5 dtype）

**现状对照**：Phase C 把 coding 自检结论结构化落进 `codegen_complete.json`，Driver 只记录不 grep；当前 skill Step6 已做维2/维3/维4/维5 自检（warning/fail），但结论不持久化为结构化门产物，`transition` 只校验 section 覆盖 + manifest callable_target + smoke_passed。

- **迁移收益（pro）**：① 跨 stage 可追溯「codegen 是否对齐了 tiling/buffer/dtype」；② 下游可据此决策（如 dtype 不一致 → 跳过某些用例）。
- **迁移代价（con）**：① **当前无消费者**——核实：precision_debug 读自己的 `debug_result.json`，cannbench_adapt 读 `codegen_manifest` 的签名，**都不读** tilingdata_fields_aligned 等。持久化 = 死数据（违反 §1.8「每个事实只在一层有产权」，无人消费的字段是债）；② 增 codegen_complete.json 的 schema + 校验维护。
- **不迁移的风险**：skill 自检结论只在当轮 agent context，不跨 stage——但既然无人跨 stage 消费，无损失。
- **决定因素**：**无消费者 = 不该持久化**。skill 自检的 warning/fail 已驱动当轮 loopback，足够。
- **裁决：不迁。** 若未来某 stage 真需消费，再加（写进 `codegen_manifest.json` 扩展字段，零新载体）。
- **重评触发**：出现明确的新下游消费者（某 stage 需读「tilingdata 字段是否对齐」做决策）。

### 3.7 dev_record 状态机（meta/progress/coding_index/clarification/coding_plan/history/env_snapshot）

**现状对照**：Phase C 用 dev_record 目录在 subagent 间传状态；当前用 immutable frozen `State` + `events.jsonl`（Event Sourcing，§1.1 权威）+ staging/ 文件。

- **迁移收益（pro）**：① 文件系统状态机直观可读；② agent 间松耦合。
- **迁移代价（con）**：① **与 Event Sourcing 双源**——最严重反模式，状态权威分叉，重放/审计/恢复三套语义打架，直接违反 §1.1「events.jsonl 是运行历史的权威记录」；② dev_record 落 workdir（仓外），违反 §1.7 代码仓自闭环；③ 已有 session resume 侧车覆盖跨 run 续跑，dev_record 的 progress.md 续跑能力冗余。
- **不迁移的风险**：无——Event Sourcing 是更严格的状态载体（可重放、有 schema）。
- **决定因素**：双状态源是架构性红线，不可碰。
- **裁决：坚决不迁。** 这是所有「不迁」里最硬的一条。
- **重评触发**：无（除非放弃 Event Sourcing 架构，那是另一场大改）。

---

## 4. 上下文经济性专论：单 agent 真不需要 subagent 吗？

> 本节直回应一条质疑：**Phase C 起多 subagent 的初衷就是治「上下文过长→失焦」**，
> 当前单 agent codegen 有没有这问题、怎么治、复杂算子下够不够。不绕「根因已修」，
> 把账算清。本节是对 §3.1 / §3.2 裁决的**纵深补强**，不改裁决，只把「为什么够」讲透。

### 4.1 先校准前提：subagent 当初为何而设（两件事别混）

- **能力下沉（主因）**：当前工程拆掉 codegen 期 s2/s4/s5 链，首要驱动是
  capability-sink-redundant-stages——把 build/deploy/smoke/run-cases 从独立 stage 降为
  codegen 会话内原子能力，消灭冗余 stage。这与「上下文」无关，是**职责收敛**。
- **上下文经济（次因，但真实存在）**：Phase C 的 s2/s4 分离确实带上下文红利——s2 在大上下文里
  做需求分析并产出 **compact coding_index**，s4 每子步**只读 compact index**（详设只被 s2 消费一次）。
  这是「先压缩、再小上下文翻译」的设计。

质疑成立的部分：**当前 codegen 没有「压缩」这一步**——它直接读全量源产物（见 4.3）。
所以不能笼统说「subagent 解决的问题已被解决」，得分清解决的是**哪一类**。

### 4.2 当前框架有没有「上下文过长→失焦」问题？——历史、根因、实证

**历史上有，且正是 moe_re_routing**（`codegen-skill-delivery/01-problems.md` P1）：
ascendc-coder 跑到 **366K 字符 / turn 287 / 50min** 后死亡。但根因诊断（P2）是
**skill 未投递**——agent 没拿到 `ascendc-op-dev-coding`，于是 **41/73 次 Bash 是 grep SDK 头文件**
撑爆上下文。**这是 grep 爆炸，不是「设计复杂到装不下」。**

**修复手段（非 subagent）**：① `_with_trigger` slash 投递 skill；② skill 明令禁 grep CANN；
③ `codegen-skill-upstream-reuse` 把上游源产物物化进 staging（显式有界信息源，**明确替代** Phase C 的
RECORD_DIR——该 doc P5 对照原文：「Phase C 用 RECORD_DIR 显式装信息源……当前用 staging 源产物」）。

**修复后实证（同一复杂算子 moe_re_routing，run `20260711-052528-d89426`）**：
- 转录 2.18MB / **170 assistant turns**（非 287 死亡螺旋）；
- **grep-CANN = 0 回归**（6 处 `/usr/local/Ascend` 命中**全是合法的编译报错栈 / CMake 日志 / traceback**，
  非主动搜 SDK 头文件——禁 grep 纪律在该复杂算子上**守住**）；
- 命中真实编译错误（CMake），在会话内 redeploy 环里 **productive** 迭代，最终经 task notification 收口。
- **结论：P1 的 grep 病理在同一个复杂算子上未复现。** 修复有效。

### 4.3 当前框架怎么治上下文——机制清单（非「没有策略」）

**最关键的一条，质疑里漏了**：当前工程**没有放弃 subagent——把它前移到了设计期**。
设计组是一条 ~12 子阶段、各起独立 agent（generator / anchor / reviewer）的链（`design_substages.py`）：

```
general-design → general-design-review(锚)
 → dd-intake → template-division → anchor-per-template → anchor-consistency
 → tiling: split → buffer-kernel → precision-perf（各带锚）
 → integrate → docgen → validate(门)
```

每个子阶段产出**有界、经锚点校验**的产物（general_design / template_division /
tiling_results{split,buffer-kernel,precision-perf} / integrate…）。**到 codegen 时，蓝图已被
~12 个上游 agent 分解完毕。** codegen 是**翻译者**，不是分解者——翻译的认知载荷远低于分解。
Phase C 的 s2/s4 是「分解+翻译揉在一起」，当前是「设计期 12 agent 分解（带锚）+ codegen 期 1 agent 翻译」。

**加上 codegen 自身的 8 道上下文卫生**：

| # | 机制 | 作用 |
|---|------|------|
| 1 | skill slash 投递 + 禁 grep | 杜绝 P1 的 grep 爆炸（4.2 实证 0 回归） |
| 2 | staging 源产物化 | design_spec/tiling_results 等不进 prompt，靠路径引用 |
| 3 | 每文件即时 Write/Edit 落盘 | 不攒到最后，上下文不积压中间态 |
| 4 | session resume 侧车（codegen.py:202-222） | 跨 run 续跑，compact 不丢已完成文件 |
| 5 | `max_turns=10000` | e2e-stability P1 修旧值 15→10000，杜绝截断 |
| 6 | 断路器 `max_consecutive_failures` | 连续失败止损 |
| 7 | 会话内 redeploy 环 | build→install→smoke 不回 driver 重派，免重建上下文 |
| 8 | Event Sourcing（无 dev_record 双源） | 状态权威单一，不臃肿、可重放 |

### 4.4 复杂算子下，单 translator 真的够吗？——诚实回答

**对已观测复杂度（moe_re_routing，level-3）**：够。4.2 实证——post-fix 同一算子 170 turn、
0 grep 回归、productive 收口。单 translator + 已分解蓝图**撑住了**。

**对更复杂算子（比 moe_re_routing 更甚）**：**未验证**。没有比 moe_re_routing 更复杂的算子在
post-fix 跑过。这是诚实的空白，不粉饰。

**真正的压力点在哪**：当前 codegen **没有「压缩」步**（4.1 次因），它读全量源产物——
post-fix staging 从 ~20K 涨到 **~180K**（4.2 修复的代价：用大信息源换不 grep）。
对 moe_re_routing，180K + skill 体 + 知识库 + redeploy 日志尚在安全区；若算子模板数 / section 数 /
pseudocode 体量再上一个台阶，**单上下文装全量蓝图**就是下一次压力的来源——这是 §3.3 已裁定
「价值折进」要盯的点。

**若真触发，正解不是重建 codegen 期 subagent 链**（那会违反 §2.5 唯一通路、与设计期 12-agent 分解
职责重叠），而是**在设计层补一道轻压缩**——即 §3.3 已裁定的「把『每步自检关注点』折进 design 产物」，
让 codegen 读「带 focus 导航的源产物」而非「裸源产物」。这是 Phase C coding_index 价值的
**正确吸收形态**，不是新起 subagent。

### 4.5 修订 §3.1 / §3.2 的重评触发（更精确，不笼统）

- **§3.1 / §3.2 裁决不变（不迁）**，但重评触发从「重复溢出实证 ≥2 算子」**收紧**为：
  **post-fix 环境（skill 已投递 + staging 源产物已物化 + 禁 grep 生效）下，出现 ≥1 例
  codegen 上下文膨胀，且膨胀源是「装不下已分解蓝图」而非「grep / 截断 / 429」**——
  即排除已知可修类（skill 投递、max_turns、429），只认「翻译本身装不下」这一类。
- 同时把 §3.3 的「折进」方案**前置为该触发一旦出现的首选缓解**（设计层补 focus 导航），
  而非直接跳到重建 codegen 期 subagent——后者是最后选项，需先证明轻压缩无效。

---

## 5. 裁决汇总表

| # | 差异项 | 性质 | 裁决 | 决定因素（一句话） | 重评触发 |
|---|---|---|---|---|---|
| 3.1 | 多 subagent 编排骨架 | 架构形态 | **不迁** | 当前是为消除这条链演进的，回灌即倒退（§2.5） | post-fix 下「翻译装不下蓝图」型溢出（§4.5） |
| 3.2 | s4 步进多 subagent | 编码粒度 | **不迁** | 溢出根因（skill 未投递）已修，步进是错配方案 | 同 3.1（§4.5） |
| 3.3 | coding_index 步骤导航 | 部分缺口 | **不迁为独立 artifact；价值折进既有产物** | 与 tiling_results 双表示冲突；价值在「自检关注点」可折进 design/skill | Step6 反复漏同类坑 ≥2 算子 |
| 3.4 | **A5 VF 隔离精度预验证** | **真缺口** | **延后**（形态预定 capability sink） | 价值真但 A5 Regbase 是少数路径 × heavy 成本，ROI 低 | A5 Regbase 占比升 / 出现 VF 精度漏拦实证 |
| 3.5 | 编译错误分类脚本 | 等价吸收 | **不迁** | smoke 门严格更强，分类是冗余归因层 | 跨算子统计分析需求出现 |
| 3.6 | inheritance_check 持久化 | 无消费者 | **不迁** | 无下游消费者 = 死数据（§1.8） | 新下游消费者出现 |
| 3.7 | dev_record 状态机 | 不变式冲突 | **坚决不迁** | 与 Event Sourcing 双源，§1.1 红线 | 无（除非弃 Event Sourcing） |

**净结论**：8 项 → 7 项不迁（其中 3.3 价值折进、不另起炉灶）、1 项延后（A5 VF，等触发）。
**没有任何一项现在就该迁。** Phase C 的质量机制要么已被当前 design 产物链 / redeploy 闭环 / 静态自检等价吸收，
要么与已确立纪律（单通路、Event Sourcing、设计完整性 + fail-fast）冲突。迁移的正道是**能力下沉**，不重建编排链。

---

## 6. 附录：文件/实体映射表

| Phase C 实体 | 路径（ascendskills） | 当前工程对应 | 路径（AscendC-DevKit） |
|---|---|---|---|
| 流水线 driver | `skills/ascendc-op-full-pipeline/SKILL.md` | L3 Stage 编排 | `stages/codegen.py` |
| env-check meta.json | 派 `ascendc-op-dev-env-check` | `_materialize_inputs` 确定性写 | codegen.py:344-354 |
| s2 analysis | `skills/ascendc-dev/SKILL.md` + `agents/s2-analysis.md` | design substages（拆分吸收） | `stages/design_substages.py` |
| s4 coding | `agents/s4-coding.md` + `scripts/stage4_scheduler.sh` | 单 skill `ascendc-op-dev-coding` Step4 | `.claude/plugins/stage-codegen/skills/ascendc-op-dev-coding/SKILL.md` |
| s5 compile | `agents/s5-compile.md` + `scripts/classify_compile_error.sh` | 会话内 `ascendc-devkit redeploy` | codegen.py:627-645 + transition:811-860 |
| vf-test | `agents/ascendc-vf-test-agent.md` + regbase-vf-test | 无（静态红线） | skill Step4/Step6 A5 节 |
| dev_record 状态机 | `skills/ascendc-dev/scripts/dev_record.sh` | immutable State + events.jsonl | `orchestration/kernel/state.py` |
| 触发 agent | driver 派 ascendc-dev-* | `ascendc-coder`/`incremental-developer` | `.claude/agents/ascendc-coder.md` |
| 方法学投递 | 各 agent 读自身 .md | slash 投递 `/stage-codegen:ascendc-op-dev-coding` | codegen.py:240-241,371-397 |
| section 声明 | s2/s4 推导 | 确定性 `CodegenInitStage`（无 agent） | `stages/codegen_init.py` |
| design 产物链 | Phase A planner + step subagents | design substages（general-design/template-division/split/buffer-kernel/precision-perf/anchor/integrate/docgen/validate） | `resources/orchestration-config.json` stages map |

---

## 7. 给决策者的三句话

1. **「多 subagent」没被放弃，是前移了**——设计期 ~12 个 agent（带锚）已把蓝图分解完毕，
   codegen 是翻译者不是分解者；codegen 期不再起 subagent 是职责收敛（capability-sink），
   不是上下文偷懒。历史溢出（P1）根因是 skill 未投递（P2，已修），同一复杂算子 post-fix 实证
   170 turn、0 grep 回归、productive 收口（§4.2）。
2. **真正值得记一笔的只有 A5 VF 预验证**（§3.4），但它绑在 A5 Regbase 这条少数路径上，
   heavy 且当前无实证漏拦——记下触发条件，等信号出现再做，别现在为假设问题建重设施。
3. **三条红线锁死大部分不迁**：Event Sourcing 权威（拒 dev_record）、设计完整性 + fail-fast
   （拒默认值兜底）、单一通路（拒 s2/s4/s5 链回灌）。任何「迁」的提案先过这三关；
   唯一可能松动的上下文压力点（§4.4）正解是设计层补 focus 导航（§3.3 折进），不是重建 subagent。
