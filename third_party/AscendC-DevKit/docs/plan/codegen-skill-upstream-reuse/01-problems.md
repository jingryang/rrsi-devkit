# codegen skill 上游产物复用缺口 — 问题记录（L1）

> 纯事实快照（哪里坏了 / 凭什么这么说）。不提方案、不排顺序、不写决策。
> 触发：codegen skill 投递修复（见 ../codegen-skill-delivery/）之后，进一步审查 codegen skill
> 内容时发现：即便 skill 被投递，agent 仍缺实现所需的**上游设计内容**，转而 grep CANN。

## P1 — codegen staging 只有 3 个紧凑 JSON，缺实现蓝图
真实 run（`output/20260711-052528-d89426`）的 codegen staging 目录 `ls` 仅有：
`design_spec.json`（2.9KB）/ `tiling_strategy.json`（5.8KB）/ `kernel_architecture.json`（204B）。
`codegen.py` 的 `_materialize_inputs` 也只写这 3 个 + reference_code（ref_ 文件）+ meta.json（刚加）。
**没有**：详细设计说明书、requirement、test_cases。

## P2 — Kernel 实现蓝图的源是 tiling_results（kernel.pseudocode），既未进 codegen 输入、其派生叙述也没进
- **源**：`state.tiling_results = {template: {split, buffer_kernel{kernel.pseudocode}, precision_perf}}`
  （tiling split/buffer-kernel/precision-perf → integrate 聚合），**含每模板 Kernel 伪代码**（Init/Process/
  CopyIn/Compute/CopyOut）。真实 run `artifacts/design/integrate/tiling_results.json` 存在。
- **派生**：`artifacts/design/docgen/moe_re_routing_详细设计说明书.md` §4.1.4 Kernel设计 自述
  「**全量装载自 `tiling_results.json[T1].buffer_kernel.kernel.pseudocode`，无摘要、无省略」」——
  它是源中间产物的**忠实誊抄渲染**（人面向，供评审/留痕），非独立信息源。§2/§3 等章节同理渲染自
  general_design / template_division / design_spec。
- **缺口**：codegen 的 `_materialize_inputs` 与 skill 输入契约都**既未声明源 `tiling_results`，也未声明
  general_design / template_division**。agent 手里只有 design_spec(2.9KB)+tiling_strategy(5.8KB) 紧凑契约，
  缺 Kernel 伪代码/buffer/split 的源细节 → 去 grep CANN 头文件找 API 与实现模式（codegen-skill-delivery
  P1：41/73 Bash 是 grep CANN）。
- **应读源不读派生**（§2.5 + Event Sourcing）：源中间产物在 State 上是 ground truth；详细设计说明书是
  docgen LLM 从源生成的派生叙述，有渲染走样风险。codegen 该沿源链读 `tiling_results` 等，不该在派生
  节点截取详细设计说明书（详见 02 决策2）。

## P3 — moe_re_routing 无参考算子，agent 连代码 pattern 源都没有
该 run staging 无任何 `ref_*` 文件 → `state.reference_code` 为空（moe_re_routing 未注入参考算子）。
`_materialize_inputs` 的 reference_code 分支未触发。agent 既无实现蓝图（P2）又无参考代码，
唯一信息源是 2.9KB 的紧凑 design_spec → 被迫 grep CANN。

## P4 — skill 输入契约未显式声明上游参考集
`ascendc-op-dev-coding` SKILL.md「输入（文件契约）」表只列 4 项：
design_spec / tiling_strategy / kernel_architecture / meta.json（+ op_name 上下文变量）。
**未声明**：详细设计说明书（详设）、requirement（需求分析产物）、reference_code（参考算子）、
test_cases（验收用例）——这些上游 stage 已产出的内容，codegen 该复用却没在 skill 里点名。
即「新的 skill 要明确参考内容」的缺口：skill 没告诉 agent「这些上游产物存在、去读它们」，
agent 不知道该读什么，遂自行 grep 文件系统。

## P5（对照，外部只读参考）— full-pipeline Phase C 用 RECORD_DIR 显式装信息源
`ascendskills/skills/ascendc-op-full-pipeline`（只读参考，不照搬）Phase C 的 skill 逻辑：
C.1.5 把 meta.json / env_snapshot.md / coding_index.md 装进 RECORD_DIR 作为 agent 的**显式有界
信息源**；C.2/C.3 的「参考来源纪律」明令「禁止自行全局搜索参考实现，从详设 + coding_index +
知识库模板生成」。原则相同（有界显式信息源 + 禁自搜），但 full-pipeline 的 S2-analysis
**重新做需求/设计分析**——当前框架的 requirement + design 阶段已产出更丰富产物（P2 的详细设计说明书），
照搬 S2 = 与上游 stage 重复（见 02-analysis 决策 1）。

---

## 状态：已实现（2026-07-11）
P1/P2/P4 已修（决策见 02，实施见 03）：
- **物化层**：`codegen._materialize_inputs` 增物化 `tiling_results`/`general_design`/`template_division`/
  `requirement`/`test_cases` 到 staging（`_json_text` helper 统一处理 dict/dataclass/list[dataclass]）。
- **prompt 层**：`_build_codegen_prompt` 输入清单列源产物（按「翻译为哪层」标注）+ 新增「实现蓝图优先级」段。
- **skill 内容层**：SKILL.md 输入契约表扩为源中间产物集 + 决策5 ①（参考纪律例外条款+Why）/ ②（字段↔源
  逐一对应自检）/ ③（锁定项入口校验 fail-fast）。
- ④（A5 编码硬约束）/ ⑤（多维自检）正交，单独立 follow-up：`codegen-skill-a5-constraints/`、
  `codegen-skill-selfcheck-dims/`。
验证：新 UT 10/10 绿 + UT 全量 1789 passed（+10）+ ST 105 passed / 3 skipped（heavy_llm 按 §3.11
未纳入，待 E2E 重跑确认 codegen 读源产物而非 grep CANN、上下文有界、出分）。
