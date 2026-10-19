# VF 经验库类别化重构 — 实施方案（L4）

> 改哪些文件、什么顺序、怎么验证。对应 `01-problems.md` / `02-analysis.md`。

## 改动清单

1. **经验库重构**（`regbase-vf-test/references/vf_experiences/`）：
   - 建 8 类目录（cast / dequant-quant / elementwise / reduce / gather-scatter / layout / sort-select / stateful-accumulator），各含 `INDEX.md`（判据/指令链选型/结构模板/陷阱/条目索引）
   - 29 份旧 `{op}/` lesson 提炼归约为 17 份 `experience-*.md`（各含实证来源指向算子 record dir），**删除** 9 个旧 per-op 目录
2. **归档/检索指令**：
   - `regbase-vf-test/SKILL.md`：§3 step 3 检索（按类别）、step 9 归档（提炼归约，必须）、§5.3 全部重写（过程资产 vs 终态类别库）
   - `ascendc-vf-test-agent.md` §2.2b：检索定位类别 + 归档提炼归约
   - `ascendc-precision-vf-debug/SKILL.md` + agent：Step 3 检索、经验归档改类别化
   - `precision_debug_a5/vf_test.py:117,121`：prompt 文本同步
3. **硬编码引用修复**：`vf-instructions/mask-model.md`（3 处）、`multi-dtype-numpy.md`（1 处）、`overflow-mode-guide.md`（2 处）、`design-knowledge-map.md`（C4 分流：跨算子走类别库 / 同算子续作走 vf_lesson）
4. **docs/plan**：`vf-experience-categorization/` 工作目录（01 L1 / 02 L3 / 本文件 L4）

## 验证

- `grep -rn "vf_experiences/{op_name}\|vf_experiences/quant\|_lesson.md" .claude/ src/` → 仅剩待删文件内部引用，删除后无残留
- `find vf_experiences -name INDEX.md | wc -l` = 8；`find vf_experiences -name 'experience-*.md' | wc -l` = 17
- SKILL.md §3 步骤 1-9 连贯、§5.3 两资产边界清晰；frontmatter 未动
- 过程资产（`{record_dir}/vf_verified/kernel_test/`）未迁移，`lesson:{op}:{vf}` 兄弟目录机制保留

## 未做（后续可做）

- 类别粒度演进：出现第 9 类按相同判据新增目录即可，不破坏既有条目。
