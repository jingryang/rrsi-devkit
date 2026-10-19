# step-63 — SKILL 文档与工程层产物契约漂移收敛 — 方案分析（第三层）

> L1 见 `06-problems.md` P86。已实施。

## 0. 核心判断（Explore 推翻"断裂"措辞）

- **非代码断裂，是单向文档陈旧债**：工程层完全自洽（requirement.json 三者合一：schema 名 == 产物名 == 工程读写），真实 run agent 实际写对 requirement.json（工程 prompt override SKILL 文字引导），pipeline 端到端跑通。问题是 6 个 SKILL.md 文字漂移（仍教 op_spec.json/md）。
- **收敛方向**：只改 SKILL.md，不动工程层（工程自洽，改工程层反引风险）。

## 1. 收敛决策（用户拍板）

- `op_spec.json` → `requirement.json`（工程权威单一源）。
- `op_spec.md` 删（agent 不产 + 工程不读；人类可读已有入口 `requirement_doc.md`）。
- `checkpoints/{step}.json` 降级（"必须写" → "可选，工程不消费"）—— 不删 `checkpoint_convention.md`（自我承认工程不消费，定位字段定义/查证规则，被 tiling schema/knowledge_policy 引用）。
- `op_spec_schema.md` 字典化（字段语义保留，头部改 requirement.json）。
- `precision-debug/rules/checkpoint-spec.md` 独立不改（precision-debug 内部规则）。
- code-analysis 是孤立工具 skill（不在 pipeline），checkpoints 降级即可，不造工程 stage。

## 2. 不做的（避免误伤）

- 不改工程层（requirement.py / design_substages.py / loader.py / artifact.py 自洽，schema travels with skill）。
- 不把 op_spec.json 加进工程层（逆向收敛，让已收敛的 requirement.json 链路重新分裂）。
- 不新增 manifest 动态发现（checkpoint_convention 已决议"下游硬编码上游产物路径，不走 manifest"）。
