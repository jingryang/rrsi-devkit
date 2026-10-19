---
name: ascendc-devkit-code-reviewer
description: "对本仓（AscendC-DevKit 框架）所有 PR 做统一 review：设计原则符合性（CLAUDE.md §1/§2/§4）、必要 UT/ST 且真实通过（§3）、方案根因合理且尽量最优（§1.2 四把尺子）、软件架构与经典软件工程方法论（散弹式修改/内聚耦合/架构/设计模式）。产出结构化报告（verdict + 分级 findings，人读 md + 机读 json）。默认前台自动跑 UT + 非 heavy_llm ST，heavy_llm 列清单待确认；Advisory 模式给结论不阻断；全 8 维一次到位。触发词：review PR, PR review, 代码评审, devkit review, 审查提交, review 这个 PR。"
---

# ascendc-devkit-code-reviewer

本仓 PR 的统一 review 入口。把 CLAUDE.md 的设计原则蒸馏成可逐条勾选的 review 清单，对每个 PR 给出结构化结论。

## 定位与边界

**审查对象**（本仓框架自身）：
- `src/ascendc_devkit/**` — Python 编排 / 领域 / 适配器 / CLI
- `.claude/skills/**`、`.claude/agents/**`、`.claude/rules/**`
- `tests/**`、`resources/**`、`docs/plan/**`

**不审查**（走别的 skill，两者互补不重叠）：
- AscendC 算子 kernel/host 编码红线 → `ascendc-code-review`

**权威源**：CLAUDE.md 是设计原则唯一源；本 skill 的 `references/checklist.md` 是其 review 视角的蒸馏（自带、自包含，§2.1）。命名疑问先查 `src/ascendc_devkit/domain/chip.py`（§1.9）。

## 输入

PR 三选一：
1. **本地分支名**（如 `pr-<N>-review`）—— 最常见，已 fetch 到本地。
2. **gitcode merge-request 号**（如 `#<N>`）—— 按 `references/pr-acquisition.md` 取。
3. **显式 `base..head`**（commit 区间）。

## 工作流

1. **取 PR** — 拿到 head，算 `git diff $(merge-base)...head`（**三点点**，对齐 PR「相对目标分支的净变更」语义）。
2. **分类变更** — 标注每个文件属于 framework / skill / agent / test / doc / resource；据此启用维度（D1/D3/D5/D6/D7/D8 常驻；D2 触及 skill、D4 触及 agent/编排时启用）。
3. **逐维审查** — 按 `references/checklist.md` 逐条过，记录 finding（severity × dimension × file:line × evidence × suggestion）。**每条必须有 evidence，不得空泛。**
4. **跑测试** — 前台执行 UT 全量 + 非 heavy_llm ST（§3.3 前台、§3.6 默认全量真实）；heavy_llm 列清单 + 预估耗时/token，**待用户确认**才跑（§3.11）；环境缺失诚实报错不静默（§3.7）。
5. **出报告** — 按 `references/report-template.md` 写 `reviews/PR-<N>-review.{md,json}`。

## 审查维度（详见 references/checklist.md）

| 维度 | 映射 | 启用条件 |
|---|---|---|
| D1 设计原则符合性 | CLAUDE.md §1 | 常驻 |
| D2 Skill 原则 | §2 | PR 触及 `.claude/skills` |
| D3 测试必要性与真实性 | §3 | 常驻 |
| D4 Agent/编排 | §4 | PR 触及 `.claude/agents` 或 `orchestration/` |
| D5 方案合理性与最优性 | §1.2 | 常驻 |
| D6 通用代码质量 | — | 常驻 |
| D7 文档与跟踪一致性 | §1.8 | 常驻 |
| D8 软件架构与经典软件工程 | — | 常驻 |

> **审查视角分层**：D1/D2/D4 执行本仓 CLAUDE.md 自定义硬约束（层矩阵 / 唯一通路 / 结构信号驱动等）；D8 从软件开发专家视角检实现健康度（散弹式修改 / 高内聚低耦合 / 上帝对象 / 依赖方向 / 设计模式恰当性 / 开闭扩展点）。两者互补，改动可同时命中。权威源是 CLAUDE.md；checklist 是其 review 视角的蒸馏。

## 输出契约

- **人读**：`reviews/PR-<N>-review.md` — verdict + findings 表 + 测试结果 + 整改建议。
- **机读**：`reviews/PR-<N>-review.json` — 同结构，供未来 gitcode 自动 review 消费。
- **verdict**：`approve` / `approve_with_minor` / `request_changes` / `reject`。
- **severity**：`blocker`（违反硬不变式 / 测试不过 / §3.4 掩盖失败 / §1.7 外部路径）→ `major` → `minor` → `nit`。

## 审核原则（recall > precision）

- **宁可错报，不可漏报**：发现疑似问题就提（在 finding 里标注不确定性），由人裁决；**不得因「不确定」「可能没问题」而放过**。误报可接受，漏报是失职。所有问题从严审核。
- **通用化边界**：通用流程代码（`orchestration/`/`application/`/adapter 基类）不得写死绑定**具体仓 / 具体算子 / 具体路径**的机制或约定（调用方式、目录布局、命名、接口形态）——应外移到适配器 / 配置 / skill。例：cann-bench 仓可用 torch 接口调算子，但不是所有算子都这么调，通用流程不能假设它。判别：**换一个仓/算子，这段通用代码还能跑吗？**

## 已锁定的行为默认值

- **测试**：自动前台跑 UT + 非 heavy ST；heavy_llm 待确认（§3.11）。
- **约束力**：Advisory —— 给结论与分级 findings，是否修复由人定，不阻断流程。
- **维度**：全 8 维一次到位（按启用条件动态选）。

## 使用示例

```
用 ascendc-devkit-code-reviewer review 本地分支 pr-<N>-review
review gitcode MR #<N>
对本仓这个 PR 做代码评审
```
