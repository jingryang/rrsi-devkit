# L1 问题记录 — 需求权威单一通路（design 链 requirement 有损传递）

> 本文件只陈述客观事实与证据（哪里坏、凭什么这么说），不提方案、不排顺序、不写决策。

## P1 设计链「输入路」把需求的多 dtype 域丢在 agent 面前

**现象**（20260818-152906-dde0d9 批，exp 算子）：最终 `design_spec.support_domain.dtypes=["float16"]`，而 `requirement.domain.inputs[0].dtypes=["float16","float32","bfloat16"]`；domain-gap 告警直到 codegen 阶段才出现（run.log L354/L573）。

**证据链**：
- 需求阶段产物 `artifacts/requirement/requirement.json`（108 行）含 `domain`/`math_formula`/`shape_formula`/`golden_alignment` 全量字段，`domain.inputs[0].dtypes` 三值。
- 设计链各阶段 `_upstream_inputs` 物化的 requirement 是 reduced 形态（65 行 `{op_spec:{inputs:[{dtype:"float16"}]}}`，**无 domain**）——`GeneralDesignStage`(design_substages.py:873-876)、`DetailedDesignIntakeStage`(:1065-1068)、`SynthesizeStage`(:1207-1210)、test_design analyze(:109-113) 均返回 `{"requirement": state.requirement}`。
- 基类 `_DesignSubstage._materialize_inputs`(design_substages.py:324-349) 用 `dataclasses.asdict(payload)` 写文件 → reduced `Requirement` 直接序列化。
- `Requirement.from_dict`(src/ascendc_devkit/domain/requirement.py) 只解析 `op`/`constraints`/`test_cases`/`unclear_items`，`domain` 等字段在解析入口被丢弃；`Requirement` dataclass(:56-62) 无 domain 字段。
- 设计链「修正路」已用权威回读：`SynthesizeStage.transition`(:1246-1266) `_load_authoritative_requirement(state)` 用于 scalar 路由/param_type/inplace reconcile——证明权威回读模式是团队既有认可方案，但**输入路未接**。

**影响**：设计 agent 在看不到需求 dtype 域的前提下设计 `support_domain`，收窄成为"无知丢失"而非"知情决策"；错误在设计链内逐级放大，domain-gap 安全网（codegen 末端 no-halt）只能事后告警，靠 debug/eval 兜底，增加整批迭代成本。

## P2 `materialize_authoritative_requirement` 的 last-resort fallback 违反 §3.12

**现象**：权威需求文件缺失时，物化路径静默退回有损序列化继续跑。

**证据**：`design_artifacts.py:57-87` 注释明写 fallback 场景是 "isolated UT"；`codegen.py:988` 在 `materialize_authoritative_requirement` 返回 False 时 `_json_text(state.requirement)`（reduced asdict）兜底。

**影响**：把"权威数据缺失"冒充成"正常输入"，让消费方拿有损需求继续产出——正是 P1 丢字段的温床，违反 §3.12（测试便利不得反向绑架实现）与用户原则（拒绝让一种错误冒充另一种）。

## P3 `validate_support_domain_structure` 定义了但全仓未接线

**证据**：`src/ascendc_devkit/domain/support_domain.py:161` 定义结构校验器（§1.3 加载期校验承诺），全仓 grep 无调用点。

**影响**：support_domain 的结构合法性无加载期校验；且无任何「support_domain ⊆ requirement.domain」语义对质（codegen 末端 domain-gap 是唯一触发点，且 no-halt）。

## P4 既有记录：本问题是 db504b #1 的未收口消费者

**证据**：`docs/plan/db504b-class-consistency-sweep-plan.md` #1 HIGH 已诊断"reduced 丢字段"，M2 修复已覆盖 review gate + codegen（`materialize_authoritative_requirement` 即其产物），**设计链各 stage 是被漏掉的消费者**。
