# codegen skill 投递缺失 — 问题记录（L1）

> 纯事实快照（哪里坏了 / 凭什么这么说）。不提方案、不排顺序、不写决策。
> 触发：e2e-self-evolve 跑 moe_re_routing（cann-bench L3）时 codegen agent 上下文爆炸死亡。

## P1 — codegen agent 上下文爆炸，死于 exp 同款模式
ascendc-coder agent 跑到 turn 287、上下文 366K 字符、50 分钟仍停 iteration 1/5，未产出可编译代码。
证据：`output/20260711-052528-d89426/agents/ascendc-coder-01.jsonl`（5.7MB transcript）。
73 次 Bash 调用分类：**41 次（56%）grep/cat `/usr/local/Ascend/.../cann-9.1.0-beta.3/` SDK 头文件**；
26 次读工程文件；~3 次「build」实为模板拷贝循环（非真编译）；**0 次 smoke/deploy/pytest**。
grep 的 API：GlobalTensor×6、HardEvent×4、DT_FLOAT16/DT_INT8 dtype 枚举、TILING_KEY×2、Arange×4、DataCopy×2。
上下文轨迹：311K（16:32）→ 366K（16:42），超 exp L1 当年死亡线 331K。

## P2（根因）— CodegenStage 违反 §4.3，skill 加载但未投递
`orchestration/stages/codegen.py` 的 `actions()` 返回 `SpawnAgent(prompt=...)`，prompt 由
`_build_codegen_prompt` 产出，是纯 markdown、**无 `/skill` slash command 首行**。
codegen.py:202-206 注释明说「Skills are loaded as local plugins declared in each agent.md
frontmatter … No runtime skill list」——混淆了加载（§4.2 plugins 加载）与投递
（§4.3 slash command 首行注入 SKILL.md 方法体）。
codegen 专用 skill `stage-codegen:ascendc-op-dev-coding`（含 Step3「编码前查 ascendc-dev-knowledge」
+ line35「禁全局搜索 CANN，知识库查阅 API 签名不受此限」+ Step4 按 programming_model 选编码路径）
虽被加载（ascendc-coder.md 声明 stage-codegen plugin），**从未被投递**，agent 从未按其流程走。

## P3（对照）— 设计侧有 skill 投递机制，故收敛；codegen 没有
设计侧 substages 经 `STAGE_SKILL_MAP`（`orchestration/skill_config.py`，单源
`resources/orchestration-config.json` 的 `skills.stages`）+ `_skill_trigger()`/`_with_trigger()`
（`design_substages.py:312-334`）把 `/stage-design:<skill>` 作为 spawn 首行投递，skill 方法体注入，
agent 按 skill 流程走 → tiling/anchor 收敛。
`STAGE_SKILL_MAP` 现有条目仅 design + testdesign，**无 codegen**。
设计侧能收敛而 codegen 不能：设计侧产物是高层抽象 + 有 ascendc-design-anchor 独立校验 API；
codegen 要落地真实 API 调用，最依赖 skill 的 API 查找纪律，却恰恰没投递。

## P4（契约缝）— skill 要 meta.json，pipeline 无生产者
`ascendc-op-dev-coding` SKILL.md:48/68-69/211 声明输入契约要 `meta.json`
（`programming_model`/`chip_code`/`soc_version`，env-check 产出），缺 `programming_model`
或「编程模型不识别」→ `status=fail`。
`grep -r "meta.json\|programming_model\|chip_code" src/ascendc_devkit/orchestration/stages/*.py`
为空——**整条 pipeline 无 stage 产 meta.json**，印证 skill 契约从未被执行（=从未投递）。
`programming_model` 驱动编码路径（SKILL.md Step4 表：A2/A5 Regbase→路径三 VF+RegTensor；
A3 Membase→路径二传统 AscendC）——即设计侧 anchor loopback 中
「AC1→tiling/T2 claim#5 platform_adaptation unverified（A5/Regbase vs A3/Membase）」的同一未决项。

---

## 状态：已修复（2026-07-11）
P1/P2/P4 已修：STAGE_SKILL_MAP 加 codegen（决策 2）+ CodegenStage 经 `_with_trigger`
投递 `/stage-codegen:ascendc-op-dev-coding`（§4.3，决策 1）+ `_materialize_inputs` 物化
meta.json（programming_model 由 canonical 代际派生，决策 3）。ascendc-coder.md Coding Rules
加 KB/禁 grep CANN 指针双保险。验证：6/6 新 UT 绿 + UT 全量 1779 passed + ST 105 passed
（heavy_llm 按 §3.11 未纳入，待 E2E 重跑）。

