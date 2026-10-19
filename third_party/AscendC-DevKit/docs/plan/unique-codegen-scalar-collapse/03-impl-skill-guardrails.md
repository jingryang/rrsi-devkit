# unique-codegen-scalar-collapse — 实施方案（L4）：codegen skill 护栏 + fix 防假绿 + P7 假绿洞

> 输入：`docs/plan/unique-codegen-scalar-collapse/02-analysis.md`（L3，已按用户 2026-08-08 冻结）。
> 覆盖决策：**D-A5**（向量化自检强化 + SetValue/GetValue 理由落盘）、**D-A2**（维4 AR-1 措辞）、**D-A6**（维10 plugin 脚手架边界）、**D-B3**（`fallback_masked` 真实性标记）、**D-B1/B4**（fix skill 低性能回退规则扩展）、**D-P7**（harness 输出数量不匹配假绿洞，用户 2026-08-08 拍板"统一解决"）。
> 主体（D-A5/A6/B3/B1/B4）为 **skill + schema 文档级**；D-P7 为 **框架 Python**（harness 模板 + precision_comparer，用户拍板统一解决）。
> 记录者：Claude。日期：2026-08-08。

---

## 改动文件清单

| 文件 | 决策 | 改动 |
|---|---|---|
| `.claude/skills/ascendc-op-dev-coding/SKILL.md` | D-A5 / D-A2 / D-A6 | Step 6 自检表 2 行 + Step 7 写入说明 |
| `.claude/skills/ascendc-op-dev-coding/schema/decision_log.json` | D-A5 | 新增 optional 字段 `scalar_access_points` |
| `.claude/skills/ascendc-precision-fix/SKILL.md` | D-B3 / D-B1/B4 | 验证阶段 host-fallback 检测 + L142 规则扩展 |
| `.claude/skills/ascendc-precision-fix/schema/precision_fix.json` | D-B3 | fix_code_log 新增 optional 字段 |
| `.claude/skills/ascendc-precision-fix/references/prompts/fix.md` | D-B3 | 模板同步（检测 + 标记字段） |

---

## 1. D-A5 + D-A2：codegen 向量化自检强化

### 1.1 维4 AR-1 措辞更新（`SKILL.md` Step 6 自检表，现 L303 行）

**现状**（warning 级，可被 agent 主动绕过——本次 unique 即漏过）：
```
| 【维4】AR-1 主循环禁 GetValue/SetValue 数据搬送 | 主循环内 GetValue/SetValue 做 GM↔scalar 搬送（过滤注释 + TilingData 元数据读取 + 纯索引计算） | warning，改 DataCopy 批量搬送 |
```

**改为**（默认禁 + 理由落盘）：
```
| 【维4】AR-1 主循环禁 GetValue/SetValue 数据搬送（默认禁 + 逐点理由） | 主循环内 GetValue/SetValue 做 GM↔scalar 搬送。**默认禁止**；仅限①设计产物明确声明的标量路径（如 inverse 散写，DR-BK-004 类）②TilingData 元数据读取 ③纯索引计算。使用必须**逐使用点写入 `decision_log.json.scalar_access_points[]`**（每条含 location / 使用场景 / 理由 / 引用的设计产物声明或"无向量化等价物"论证）。命中"主循环数据搬送有 DataCopy/DataCopyPad 等价物 / 排序有 Sort API（fp16/fp32）+ CompareSwap bitonic（int/bf16）/ 归并有向量化实现"→ 不成立，须改向量化；不得以"正确性优先""单核简化"等主观理由豁免（历史反例：D4 把可修索引 bug 误诊为硬件一致性） | warning + 理由必须落盘；理由非法或缺失 → status=fail「scalar_access_points 缺理由/理由不成立：{具体}」 |
```

### 1.2 AR-2/AR-3/AR-4 同步提示（不强改）

AR-2/AR-3/AR-4（嵌套循环单点访问 / 非对齐 DataCopyPad / UB 侧 cast 漏斗）保持现状；AR-1 落盘覆盖已足以让 SetValue/GetValue 使用透明化。**不逐一升级**，避免过度。

### 1.3 `decision_log.json` schema 新增 optional 字段

`schema/decision_log.json`——`required_keys` 不变（`key_decisions`/`known_issues`/`assumptions`），**追加 optional**：
```json
{
  "scalar_access_points": [
    {
      "location": "op_kernel/unique.h:291 (Stage1LocalSort)",
      "usage": "主循环 GM GetValue/SetValue 数据搬送",
      "reason": "设计产物声明的标量路径 / 无向量化等价物论证",
      "reference": "tiling_results.json DR-BK-004（inverse 散写无向量 API）或空"
    }
  ]
}
```
- optional 字段不触发 `required_keys` 校验失败（框架按既有 contract 校验逻辑，只查 required_keys）。
- 语义：**codegen 有任一 SetValue/GetValue 数据搬送即须填充**；纯向量化实现可留空数组或省略。

### 1.4 Step 7 写入说明（`SKILL.md` Step 7）

在 Step 7「写入 decision_log.json」后追加一句：
> kernel 中凡含 GetValue/SetValue 做数据搬送（非 TilingData 元数据/纯索引计算），必须逐使用点写入 `decision_log.json.scalar_access_points[]`（location / usage / reason / reference）。**reference 必须指向设计产物声明的标量路径，或给出"无向量化等价物"的论证**；仅写"正确性优先/单核简化"类主观理由视为缺失，返回重写。

---

## 2. D-A6：维10 plugin 脚手架边界自检

### 2.1 `SKILL.md` Step 6 自检表追加一行（仿维8/维9 结构）

```
| 【维10】plugin 脚手架边界（codegen 本职自检） | **codegen 产权**：op_plugin 是脚手架层，只做「接口适配 + 调 aclnn kernel」。自检 plugin 文件——**命中任一即违规**：①调用 golden 同源参考实现替代 kernel（`at::_unique2`/`torch::unique`/`torch::sort`/`at::unique` 等 torch CPU 算子）②host 实现算子逻辑（重算算子结果如 `max(inverse)+1` 归约定 numUnique、变长输出 slice 决策、去重/排序逻辑）③含 CPU 兜底路径（`.cpu()` 往返 + torch 算子 + `.npu()` 绕过 aclnn）。**允许**：Tensor 转换（contiguous/reshape 展平输入）、调 aclnn kernel、dtype/device 检查、输出封装（含按 torch 语义还原 shape，如 inverse reshape 回 x.sizes()——接口适配 ≠ 算子逻辑）。判据凭结构信号（文件内容模式），不认算子名、不耦合具体 plugin | 命中①/②/③ → status=fail「plugin 越界：{具体}」，就地改回脚手架形态（只保留接口适配 + aclnn kernel 调用）；算子逻辑回归 kernel/tiling 实现（如 numUnique 应由 kernel 写回 workspace，由 host tiling 决定 y 长度） |
```

### 2.2 Step 7 写入说明

在 Step 7 追加：plugin 自检结论（越界项 / 修正记录）写入 `decision_log.json.key_decisions`（decision="plugin 脚手架边界自检"）。

---

## 3. D-B3：fix 通过判定的 `fallback_masked` 真实性标记

### 3.1 检测时机与判据（`ascendc-precision-fix/SKILL.md` 验证阶段）

在 fix_plan 应用并单用例验证**通过后、commit 前**，增加一步「host fallback 检测」：

> **host fallback 检测（§D-B3，commit 前必做）**：检查本次 fix_plan 改动是否在 op_plugin 层引入了「绕过 kernel 的执行路径」——判据（结构信号，不认算子名）：改动含 torch CPU 参考算子调用（`at::_unique2` / `torch::unique` / `torch::sort` / `at::unique` 等）+ `.cpu()`/`.npu()` 往返 + 绕过 aclnn kernel 执行，或 host 重算算子结果。命中 → **本次通过标记为 `fallback_masked = true`**，写 `fix_code_log.fallback_masked` 与 `_summary.fallback_masked`，并在 `side_effect_cases` 注明「该 case 经 host fallback 通过，kernel 路径未验证」——**不得记为 kernel 验证通过**。

### 3.2 `precision_fix.json` schema 追加 optional 字段

`fix_code_log` 追加 optional：
```json
"fallback_masked": true
```
语义：true = 该 case 通过但经 host fallback（绕过 kernel），不构成 kernel 可用性证据。

### 3.3 `references/prompts/fix.md` 模板同步

在 fix 模板的验证→commit 段加入 3.1 检测步骤 + `fallback_masked` 字段写入骨架（与 `fix_code_log` 既有字段并列）。

### 3.4 report 层面（框架侧，暂不实施）

框架 report 区分「kernel 验证通过」vs「host 兜底通过」需要框架 Python 读取 `fallback_masked` 并渲染——**本轮 skill/schema 先行**（字段落盘即有信号），框架渲染列为后续（避免本轮触及框架代码 + 并发 session 约束）。

---

## 4. D-B1/B4：fix skill 低性能回退规则扩展

### 4.1 `ascendc-precision-fix/SKILL.md` L142 扩展

**现状**：
> 命中「用 for-loop 替换 Vector API」「用更低效算法换取正确性」类回退 → 标 refuted（`refuted_reason = "low-performance fallback rejected"`），不应用。

**改为**（覆盖 host 侧兜底）：
> 命中「用 for-loop 替换 Vector API」「用更低效算法换取正确性」类回退，**或 plugin/host 侧用 golden 同源参考实现（torch CPU 算子 `at::_unique2`/`torch::unique`/`at::sort` 等）替代 kernel 调用、含 CPU 兜底路径（`.cpu()` 往返绕过 aclnn）** → 标 refuted（`refuted_reason = "low-performance fallback rejected"`），不应用。判据凭结构信号（plugin 调 torch CPU 参考算子替代 aclnn kernel），不认算子名。

---

## 5. 验证

### 5.1 机械可验证项

| 项 | 方法 | 期望 |
|---|---|---|
| decision_log schema 合法 | `python3 -c "import json; json.load(open('.../decision_log.json'))"`（仅 schema 文件语法，非实际校验器） | 无异常 |
| precision_fix schema 合法 | 同上 | 无异常 |
| 既有 UT 不回归 | `pytest tests/ -k "skill or schema or contract" --quick`（若存在 schema/contract UT） | 0 回归（新增字段为 optional，不破坏 required_keys 校验） |
| scalar_access_points 语义示例 | 用本次 unique 的 `decision_log.json` 验证新字段能承载 D4 证据（location/usage/reason/reference 四元组） | 可承载 |

### 5.2 行为验证（需真实 codegen 一轮，属 heavy_llm，§3.11 需用户决策）

- 跑一个向量化算子的 codegen，确认 `scalar_access_points` 为空数组（纯向量化）且自检 pass。
- 构造「设计要求向量化但 kernel 标量」场景，确认 AR-1 触发理由落盘要求。
- 构造 plugin 越界场景（调 torch::unique），确认维10 命中 status=fail。

### 5.3 不验证项（诚实记录）

- D-B3 框架 report 渲染（未实施，见 3.4）。
- unique kernel 重做（D-P4 只护栏不重做，非本轮）。

---

## 6. 实施顺序

1. `.claude/skills/ascendc-op-dev-coding/schema/decision_log.json`（加 optional 字段，风险最小）
2. `.claude/skills/ascendc-op-dev-coding/SKILL.md`（1.1 维4 AR-1 + 2.1 维10 + 1.4/2.2 Step 7）
3. `.claude/skills/ascendc-precision-fix/schema/precision_fix.json`（加 optional 字段）
4. `.claude/skills/ascendc-precision-fix/SKILL.md`（3.1 host fallback 检测 + 4.1 L142 扩展）
5. `.claude/skills/ascendc-precision-fix/references/prompts/fix.md`（模板同步）
6. 5.1 机械验证

## 7. 影响面与风险

- 全部改动为 skill 文档 + schema（optional 字段），**不触框架 Python、不破坏既有 required_keys 校验**。
- AR-1 升级为「理由落盘 + 非法理由 fail」：对纯向量化算子无影响（无 GetValue/SetValue 搬送则无需填写）；对含合法标量路径算子（inverse 散写）要求写理由（多一步落盘，收益是透明化）。
- 维10 对合法接口适配（reshape 还原等）不误报——判据已区分接口适配 vs 算子逻辑。
- 按并发 session 约定，实际编辑 `.claude/skill/` 共享文件前与用户确认时机。

---

## 8. D-P7：harness 输出数量不匹配假绿洞（框架 Python，用户拍板统一解决）

### 8.1 改动文件

| 文件 | 改动 |
|---|---|
| `src/ascendc_devkit/adapters/npu/_harness_template.py` | golden 分支加「空 verdicts → raise」守卫（P7-1） |
| `src/ascendc_devkit/adapters/npu/precision_comparer.py` | `judge_case_details` 查 case 级 error → fail（P7-2） |
| `tests/ut/adapters/test_precision_compare.py` | +2 UT：count mismatch → passed=False+error_msg+空 verdicts；数量匹配必非空 verdicts |
| `tests/ut/adapters/test_precision_comparer.py` | +2 UT：judge 查 error → fail（含 error+空 output_results 不空过） |
| `tests/ut/adapters/test_runner_execute.py` | +1 UT：模板守卫断言（`if not _verdict.output_verdicts` + `P7`）；**golden fixture 重新生成** |
| `tests/ut/adapters/fixtures/harness_devkit_golden.txt` | 重生成（含 P7 守卫） |

### 8.2 判据可靠性（UT 证实）

`compare_outputs` 数量匹配时**永不返回空 verdicts**——None 对 / ignore_indices / 真实对比三路必 append verdict；空 verdicts ⇔ 数量不匹配 early-return（`passed=False + error_msg`）。故「空 verdicts → raise」不会误伤合法场景（含全 ignore 输出）。

### 8.3 端到端闭环

- P7-1：数量不匹配 → harness per-case except → 记 `error` + diff=999（不再空对比假绿）。
- 消费端 A：`build-failed-case-queue._is_failed`（已查 case 级 error）→ precision_debug 循环判失败。
- 消费端 B：`judge_case_details`（P7-2 新增查 error）→ comparer 聚合同样判失败。

### 8.4 验证

- schema/adapters/orchestration 相关 UT **599 passed / 0 回归**。
- P7 新增 4 UT（count mismatch / 空 verdicts 不可达 / judge error / 模板守卫）+ golden 快照更新。
- 全量 quick UT 后台回归确认中。

---

## 9. D-P7 根治：可选输出契约三层对齐（用户拍板"彻底根治"，2026-08-08）

### 9.1 改动文件（A/B/C 三层，2026-08-08 融合后定版）

> **融合说明**：A（harness）层最终以**同事方案**为准（`_normalize_outputs` 按 proto 输出数右补 None + `compare_outputs` 原生处理双边 None/单边 fail/数量不匹配 fail），我的 golden-arity 方案在对比后让位（同事方案更优：结构基准更稳、严格暴露 placeholder hack、复用比较器 §2.5）。见 L3 §B.6 方案对比。

| 层 | 文件 | 改动 |
|---|---|---|
| A harness | `src/ascendc_devkit/adapters/npu/runner.py` | **同事方案**：传 `output_names`（proto 输出名，含 optional 位）+ attr 过滤 |
| A harness | `src/ascendc_devkit/adapters/npu/_harness_template.py` | **同事方案**：`_normalize_outputs` 右补 None 对齐 + 比较器原生处理；`_run_kernel`/`first_n` 透传 None |
| A 聚合 | `src/ascendc_devkit/adapters/npu/precision_comparer.py` | **同事方案**：`judge_case_details` 查 case 级 error + 空输出数据 → fail（我初版 P7-2 error→fail 与同事相同，融合后删我的、用同事版） |
| B 契约 | `src/ascendc_devkit/adapters/evaluation/cannbench_adapt.py` | **我的独有（保留）**：`_existing_contract_wrapper`（AST 检测转发到本算子 symbol 的非直通 wrapper）+ `_is_pure_pass_through` + `_calls_forward_target`；命中 → 保留 codegen 裁剪 wrapper、跳过直通注入 |
| C codegen | `.claude/skills/ascendc-op-dev-coding/SKILL.md` | **我的独有（保留，与同事的同步选型/维7b 合并）**：维11 条件输出契约自检 + "条件输出/可选输出建模"节（通用描述：可选输出→调用入口层裁剪、禁空占位冒充、脚手架不实现算子内部逻辑）；维4 AR-1 升级；维10 plugin 脚手架边界；两套消费路径并存说明（raw op 返回 None vs 裁剪 wrapper 返回单张量，placeholder hack 均不符） |
| 测试 | `tests/ut/adapters/test_runner_execute.py` | **同事测试保留**（`_normalize_outputs`/output_names）；**删除我的 golden-arity 测试**（断言已废弃逻辑） |
| 测试 | `tests/ut/orchestration/test_cannbench_adapt_schema.py` | **我的独有（保留）**：`_existing_contract_wrapper` 检测 + 保留/注入测试 |

### 9.2 关键设计

- **C++ op 恒返回全输出**（schema 固定 `-> (Tensor, Tensor)`，torch 底层合法模式 `at::unique` 恒 3 元组）。
- **Python 裁剪 wrapper**（调用入口层）：按控制参数裁剪返回，对齐 golden（`return_opt=false` → 单张量）。权威载体，收尾适配层保留不覆盖（B）。
- **harness 右补 None 对齐**（A，同事方案）：golden 省略尾部 optional → 右补 None；kernel 按 proto 固定返回 → 右补 None；比较器原生处理双边 None（跳过）/单边 None（fail）/数量不匹配（fail）。**raw op 对 optional absent 必须返回 None（非空 placeholder）**——placeholder hack 会被单边 None fail 暴露。

### 9.3 验证

- 融合后受影响 UT **172 passed / 11 skipped**（harness/precision/cannbench/codegen/schema）。
- 保留测试：同事 `_normalize_outputs`/output_names、我的 cannbench_adapt 保留/注入、judge error、schema optional 字段。
- 删除测试：我的 golden-arity 渲染断言（断言已废弃逻辑）。
- 全量 quick UT 待确认。

### 9.4 补强（2026-08-08，用户确认）：schema `?` 声明是 raw op 返回 None 的构造性前提

**坐实证据**：融合后复核 codegen↔harness 契约时，本次 unique 批的 `unique_plugin.cpp:120-122` 注册 schema 为
`unique(Tensor x, bool return_inverse=False) -> (Tensor, Tensor)`——**无 `Tensor?` optional 标记**，实现只能返回
`torch::Tensor()`（undefined/空占位，`:86`）而非 None。与 golden union 返回（`return_inverse=false` → 单张量）右补
None 对齐后，比较器**单边 None → FAIL**。该 FAIL 正确暴露契约违反（P7 意图），但 root cause 是 schema 声明错位——
**C++ 层要返回 None 的唯一合法前提是 schema 声明 `Tensor?`（返回 `c10::optional<Tensor>` + `c10::nullopt`）**。

**补强内容**（`.claude/skills/ascendc-op-dev-coding/SKILL.md` 维11，三处）：
- 表格行判据/命中：判据加「schema `?`」信号；命中加「schema 可选输出未声明 `?`」→ fail，整改含「schema 输出签名补 `?`」。
- 「内核/宿主层」契约：schema 中可选输出必须显式声明 `?`，对应返回位 Python 层表现为 None（C++ 返回 `c10::optional<Tensor>` + `c10::nullopt`）；无 `?` 则只能退化空占位（契约 bug）。
- 两套消费路径 + 自检：raw op 返回 None 的实现前提 = schema 已声明 `Tensor?`；自检新增（d）schema 输出签名中可选输出显式带 `?`。

**效果**：codegen 生成时 schema 声明与返回类型配套，harness 单边 fail 只命中真正的空占位 hack，不再命中「schema 没 `?` 导致实现无法满足契约」的声明错位。机制层（harness）无需改动——补强是 codegen 契约生产侧的构造性保证（§2.9）。

### 9.5 §2.11 新原则（2026-08-08，用户提出）：skill 内容禁止耦合问题/需求编号

**背景**：本次补强 SKILL.md 维11 时写入多处「P7 实证 / P7 根治」引用；用户指出 **skill 内容禁止与问题编号耦合**。

**原则落地**（CLAUDE.md 新增 §2.11）：
- skill 内容（SKILL.md / schema / references）禁止引用本仓跟踪体系编号：docs/plan 问题编号（P7/P12 类）、阶段/会话步骤号（step-84 类）、历史实例决策编号（D4 类）。
- 理由：skill 即插即用（§2.1），取出后编号无法索引、对读者是噪音；编号是「实例数据/内部上下文」，与 §1.12 算子名、§2.6 仓布局、§2.7 仓内容同源。
- 写法：佐证用**通用语义描述**（如「空占位冒充省略导致与 golden 对比失败的历史实证」）；编号只留 docs/plan 各层供追溯。
- 判据：删编号是否改变 skill 判据/流程结论——改变=依赖内部上下文须改写；不改变=冗余引用删。

**同步改动**：
- `.claude/skills/ascendc-devkit-code-reviewer/references/checklist.md` D2-B 新增审查项（grep `P[0-9]{1,3}/step-[0-9]+/问题[0-9]+/D[0-9]+` → 引用编号 → major）。
- `.claude/skills/ascendc-op-dev-coding/SKILL.md` 清理 8 处编号引用（P1×2、P7×5、step-84）+ 2 处实例锚点（DR-BK-004、D4）→ 全部改通用语义描述。
- 编号本身合法保留在 docs/plan 本 L4 文档 + L1/L3（§2.11 明确「编号只保留在 docs/plan」）。
