# step-62 — claims schema 收口（修B 实质收尾/P82 闭环）+ checkpoint_convention 清理 — 方案分析（第三层）

> P82（修B）标已实施，但 claims 链从未闭环——本步定位 + 收口。L1 见 `06-problems.md` P85。

## 0. 核心判断（用户拍板）

- **claims 机制本身合理，不删**：双层设计——tiling 声明硬件 API 假设清单（claims）+ anchor-per-template 拿 claims 独立对照硬件 API 对质（明文"破自评自证"+"对质的唯一来源"）。claims 是 anchor 的对质输入，非冗余——删 claims = anchor 失核对对象。
- **真问题是 schema 没收口**：tiling 三段 SKILL 文字引导写 verifiable_claims（修B 做了），但 schema `required_keys` 不含 → agent 服从 schema 机器契约不写（[[skill-product-contract-alignment]]）→ claims 不产出 → AC1/AC2 对质空转。
- **落 C 不是大重构**：anchor/validate 核对规则修B 已写，只缺 tiling 这头产出——schema `required_keys` + `example` 收口即可闭环。

## 1. claims 机制合理性（过四把尺子，推翻"删 claims"方向）

曾两轮误判（以为 claims 是产出方自查证了事 + anchor 不依赖 claims → 职责重叠 → 可删）。grep 证据推翻：anchor-per-template SKILL 明文 verifiable_claims 是"对质唯一来源"，AC0/AC1/AC2 都基于 claims；anchor"独立于上游 agent 自检结论（破自评自证）"——anchor 不信 tiling 自评，独立查证。

- 可维护：复杂度服务于 anchor 核对（非多余）。
- 可扩展：claim_type 是核对路由键（hardware_api_capability/repo_convention/numeric_derivation 决定核对方式），合理分类。
- 可诊断：claims 落产物 + anchor AC1/AC2 + validate GV9-a 兜底，UNVERIFIED 有消费者。
- 架构合理：双层防护破自评自证，落点正确。

## 2. 落地方案：schema 收口（非强制 errors）

- tiling 三段 schema `required_keys` 加 `verifiable_claims` + `example` 加字段（`[]` 展示 elementwise 无断言）。
- `to_prompt_block` 渲染 example 给 agent → agent 按 schema 机器契约产 claims（强于 SKILL 文字引导）。
- **tiling segment transition 不强制 errors**（`_TilingSegmentStage.transition` 只校验 spec_name in parsed，不消费 required_keys errors）——这是 §1.2 组合：schema 契约（主引导）+ tiling segment 宽容（不因 claims 缺失卡死 elementwise）+ anchor AC0 兜底（骨架级 API 算子 claims 缺失 → 阻断回 tiling 重产）。
- 不扩展 ArtifactSchema 的 issue 级校验到 verifiable_claims（靠 anchor AC1/AC2 核对字段，不过度工程）。

## 3. 不选删 claims（B）的理由

删 claims → anchor-per-template 失"对质唯一来源" → AC0/AC1/AC2 无对象 → 核对机制半残（anchor 要么全量扫描 tiling 产物找硬件 API 假设[脆弱易漏]，要么废）。且修B 刚做（step-60），删其核心产出反复。

## 4. checkpoint_convention.md 清理（P84 客观事实 5 收尾）

- 删 §manifest.json（planner 生成）段——planner 不存在，工程层不消费。
- 删 §general-design.json 所有权段——错产物名（review 写 general_design_reviewed.json，非 checkpoints/general-design.json；review SKILL 已是权威）。
- §目录结构删 manifest.json 行 + 顶部范围说明（manifest/planner 废弃，工程层走 stage contract）。
- 保留：字段定义/查证规则段（被 tiling schema/knowledge_policy/validate 引用）+ 单步格式段（code-analysis/req-analysis 引用）。
- 不动：code-analysis/req-analysis 的 checkpoints/{step}.json 范式（与工程层 stage 产物契约断裂，独立 follow-up，本次不扩范围）。

## 5. 验证

- 全量 UT 2318 passed/7 skip 零回归（schema required_keys 加 verifiable_claims，example 同步含字段过 test_example_satisfies_own_schema）。
- heavy_llm e2e 未跑（§3.11：跑骨架级 API 算子验证 tiling 产 claims + anchor AC1/AC2 对质闭环 + claims 字段结构合规）。
