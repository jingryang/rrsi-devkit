# TilingKey 写法统一 — 实施方案（L4）

> 具体改哪段 / 什么顺序 / 怎么验证。as-built 记录（commit `d966c0a` + review 后 minor 修复）。
> 决策见 `02-analysis.md`，问题见 `01-problems.md`。新机制不变式：host `ASCENDC_TPL_SEL_PARAM` ↔ kernel `template<typename...> __global__ __aicore__` + `if constexpr` 编译期路由，host/kernel 同侧同机制。

## 改动 1（层 1）— codegen 引导统一到 ASCENDC_TPL

把引导链从「旧 TILING_KEY_IS / extern C」统一切到「新 ASCENDC_TPL 模板参数化」，覆盖 host/kernel 两侧 + 所有代际（A2/A3/A5）：

- **`codegen.py` CodegenStage**：编码规则段「TilingKey 路由」→ 正向引导 ASCENDC_TPL（host SEL_PARAM ↔ kernel template + if constexpr）；建议默认值表 #7「TilingKey 路由 | 单一模板」→ 标注「统一用 ASCENDC_TPL 参数化」。
- **`ascendc-op-dev-coding/SKILL.md`**：A5 九条红线 #2「禁 TILING_KEY_IS」→「TilingKey 模板参数化」正向约束；Step6 自检项「TILING_KEY_IS 分支覆盖」→「TilingKey 机制一致性（host↔kernel）」并升级 severity warning→fail（见改动 2）；A5 Membase 入侵自检项去 TILING_KEY_IS。
- **`ascendc-op-dev-coding-regbase/references/`**：coding-plan-template（C.0 标准表/A3/A5 三行）/ orchestrator-logic（C.0 示例行）/ phase-c-prompts（默认值表 #7 副本）/ env-and-platform（A2/A3 平台特征 + 路径映射）/ error-handling（CHK 分类原因）/ todo-template（编码后自检项）全部统一到 ASCENDC_TPL。

## 改动 2（层 2）— host/kernel TilingKey 机制一致性交叉自检

softmax run 暴露 selfcheck 各侧通过、合起来错（P3）。新增交叉自检：

- 落 `ascendc-op-dev-coding/SKILL.md` Step6 自检表 + `todo-template.md` todo-9（A3 5 项 / A5 12 项）。
- 判据（正向锚定）：host 用 `ASCENDC_TPL_SEL_PARAM` **且** kernel 入口为 `template` 模板函数 + `if constexpr` 编译期路由；两侧同走 ASCENDC_TPL，任一侧缺正向特征即 `status=fail`。
- 这是「保证不出现旧写法」的确定性承担者（决策 3）——全旧（host 缺 SEL_PARAM）/ 混用（kernel 非 template）都能 catch。

## 改动 3（全链路正向化）— 引导层去 TILING_KEY_IS token

决策 2 落地：引导层（codegen 编码规则 + 全部 skill 文档 + 红线/自检）完全不出现 `TILING_KEY_IS` token。自检靠正向特征缺失 catch（改动 2），不 grep 旧 token。

- `TILING_KEY_IS` 仅保留在知识库 API 参考文档（`ascendc-dev-knowledge/.../基础API/Kernel_Tiling/TILING_KEY_IS.md` 等）——那是 API 参考（知识），不是生成引导，保留。
- grep 验证：`src/ascendc_devkit/orchestration/stages/codegen.py` + `.claude/skills/ascendc-op-dev-coding{,-regbase}/` 内 `TILING_KEY_IS` 命中 = 0（改动后实测）。

## 改动 4（review 后 minor 修复）

PR-d966c0a review（`reviews/PR-d966c0a-review.md`）发现的 minor：

- **m1**：`SKILL.md` 红线 #2「禁止行为」列「host 手动设 key」措辞歧义——`ASCENDC_TPL_SEL_PARAM` 宏内部也调 `context->SetTilingKey`，「手动设 key」易误读为禁 ASCENDC_TPL_SEL_PARAM。改「host 手动拼 TilingKey 数值（非声明式选参）」。
- **m3**：`docs/plan/codegen-skill-a5-constraints/03-impl.md` 回填 as-built——该 L4 仍述 UT 守护「禁 TILING_KEY_IS 关键词」，但 UT（`test_codegen_a5_constraints.py`）已正向化为 ASCENDC_TPL，需回填注明。
- **m4**：`SKILL.md` Kernel 层文件清单「tiling_key.h — TilingKey 枚举」→「ASCENDC_TPL 模板参数声明（ARGS_DECL/SEL）」（新机制下非传统枚举）。

## 验证（TDD）

- **UT 断言同步正向化**：`test_stages.py::test_prompt_contains_encoding_rules`（prompt 含 ASCENDC_TPL）+ `test_codegen_a5_constraints.py::test_step4_has_nine_mandatory_constraints`（SKILL.md 含 ASCENDC_TPL，原 TILING_KEY_IS 断言替换）。
- **全量 UT**：`pytest tests/ut -m "not heavy_llm"` → 2891 passed / 7 skipped / 0 failed（含正向化断言）。
- **静态 grep**：引导层 `TILING_KEY_IS` 命中 = 0（知识库 API 参考保留）。
- **heavy_llm 端到端**（§3.11，待用户确认）：重跑 softmax 或最小 A5 算子，确认改后 codegen 产出 host/kernel 一致用 ASCENDC_TPL、`get_code_channel_v220` 错消失。

## 后续（不在本轮）

- **m2（机械自检加固，follow-up）**：当前自检靠 agent 读描述判断（softmax 当年 selfcheck 各自通过合起来错的薄弱点）。可加固为机械 grep 自检脚本（host tiling.cpp 含 `ASCENDC_TPL_SEL_PARAM` 且 kernel 入口含 `template<typename` + `if constexpr`），确定性 catch。§2.9 agent 自检已够，机械加固是更优备选，非必须。
- **env-and-platform.md A2/A3 命名漂移（另案）**：该文件把 910B 归 A3，与 CLAUDE.md §1.9 canonical（910B=A2）冲突。本次只换 TILING_KEY_IS→ASCENDC_TPL，不动代际标签，命名一致性另案。

## 改动 5（rebase 后 force-A 收口：在 wenman 72fec4a 基础上覆盖 A/B 选型）

`d966c0a` 之后 wenman 的 `72fec4a`（"TilingKey 两种模式必须二选一"）合入 origin/main，在 3 处加了 A/B 二选一选型引导。用户决策：force-A（ASCENDC_TPL 模板参数化）是以后唯一标准，不给 codegen 多种选择（消除 softmax bug 的 A/B 判定点，§2.5 唯一通路）；在 72fec4a 的产物结构上**再改一次**改成 force-A，不破坏 wenman 的提交（rebase 把本系列 commit 重放在含 72fec4a 的 origin/main 之上，72fec4a 作为 base 完整保留）。

rebase 冲突点（SKILL.md Step6 自检）按 force-A 解——保留 wenman 的「Step6 表里有 TilingKey 自检行」结构，内容换 force-A 机制一致性。另把 72fec4a 的 A/B 引导残留统一改 force-A（单机制、正向描述、不残留 A/B 与 TILING_KEY_IS token）：

- `ascendc-op-dev-coding/SKILL.md`：「#### TilingKey 路由方案」A/B 整段 →「#### TilingKey 路由（ASCENDC_TPL 模板参数化）」单机制正向描述（host `ASCENDC_TPL_SEL_PARAM` ↔ kernel `template<...> __global__ __aicore__` + `if constexpr`；多模板算子用 `ASCENDC_TPL_UINT_DECL`）。
- `agents/ascendc-dev-s4-coding.md`：「#### TilingKey 路由方案选型」A/B 段 → force-A + C.0 自检必须项（机制一致性 + 模板参数维度与设计产物一致）。
- `ascendc-op-dev-coding-regbase/references/per-substage-selfcheck.md`：C.0 自检 item 4/5/6（wenman 的 A/B）合并为单一 force-A 机制一致性项；同表 item 3「`extern "C"` 包裹」校正为「kernel 入口为 `template<...> __global__ __aicore__`」（force-A 入口无 extern C，由 add 参考 kernel `template <typename D_T_X, int BUFFER_MODE> __global__ __aicore__` 坐实，与 d966c0a 的 coding-plan-template 一致）；B2 item 2「统计 TILING_KEY_IS 出现次数」→ force-A「ASCENDC_TPL 参数组合完整」（原项会引导 host 侧写 TILING_KEY_IS，即 softmax bug 模式，必须收口）。

**保留 2 处 TILING_KEY_IS 诊断探测器**（非引导，与 force-A 一致——出现即缺陷）：`per-substage-selfcheck.md` C.x「VF 域 Membase 入侵 grep」、`s4-coding.md` MEM 风险分类。知识库（ascendc-dev-knowledge）的 TILING_KEY_IS/SetTilingKey 是 CANN API 事实文档，不动。

**边界（本轮不动，另案）**：`ascendc-dev` / `ascendc-dev-interactive` / `ascendc-migration` / `ascendc-tiling-strategy` 等 skill 仍有预存 TILING_KEY_IS 引导（非 wenman 72fec4a 引入、非本轮 codegen 主链路），force-A 全仓收口另案。

## as-built

- commit `d966c0a`（层 1 + 层 2 + 正向化 + UT 断言）。
- review 后 minor 修复（m1/m3/m4 + 本 L1/L3/L4 补文档）。
- rebase 到 origin/main（7b43e33）+ force-A 收口覆盖 wenman 72fec4a 的 A/B（改动 5）：见本次提交。
- UT：26 项靶向（a5-constraints / selfcheck-dims / regbase-template-invariants / codegen prompt）全绿 + orchestration+skills 子集 1718 passed / 0 failed。
