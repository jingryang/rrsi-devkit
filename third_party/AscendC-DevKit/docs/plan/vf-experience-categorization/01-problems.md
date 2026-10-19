# VF 经验库按算子组织 + 含源码答案 — 问题记录（L1）

> 观测事实与证据，不提方案、不排顺序、不写决策。方案见 `02-analysis.md`，实施见 `03-impl.md`。

## P1 经验库按算子目录组织，检索退化为"按算子名找答案抄"

- **事实**：`regbase-vf-test/references/vf_experiences/` 以 `{op_name}/{vf_func}_lesson.md` 组织（9 算子 29 份）。
- **证据**：
  - `ascendc-vf-test-agent.md` §2.2b 检索指令 = "扫描 `vf_experiences/*_lesson.md` 或 `{op_name}/{vf_func_snake}_lesson.md`"，按 `vf_function_name` + dtype + 关键词语义匹配——检索锚点是算子名/函数名。
  - 库内 lesson 互相引用成"母本链"（top_k 的 VT.0→VT.7 逐级引直接母本；adaptive_avg_pool_3d 直接"复用 gather 8KB 窗口"），知识搬运靠人肉识别而非类别命中。
  - 同一算子内含异构 VF 模式（softmax 3 种、top_k 9 种），按算子归档粒度失配。

## P2 lesson 含整段源码答案，归档=复制实例而非沉淀抽象经验

- **事实**：多份 lesson 的「可复用代码模式」节含完整可编译 VF 函数体 / kernel 入口 / 算子专属指令链。
- **证据**：`transpose2_d_tile_vf_lesson.md` §4 三份完整函数骨架；`compute_partial_sum_vf_lesson.md` §6 完整 r×j×t 三层循环代码；`local_top_k_merge_vf_lesson.md` 载入整段调度伪码。归档规则（`SKILL.md` §5.3）要求"复制 vf_lesson.md"、"必要时复制 _custom.cpp 关键片段"——把上一个算子的实现（含其特有 bug 与特判）整体搬入经验库。
- **影响**：LLM 检索后倾向直接照抄源码而非理解类别范式；上一算子缺陷/特判随源码扩散。

## P3 归档/检索指令口径不一

- **事实**：`SKILL.md` §3 step 8 归档标"（推荐）"、§5.3 标"必须"；agent §2.2b 与 skill §3 step 3 两处重复的检索指令；算子结束后的"批量同步"（`SKILL.md` §5.3）纯靠 LLM 自觉、无兜底。
- **证据**：见两文件对应行（grep `vf_experiences`）。

## P4 参考文档硬编码引用具体 lesson 路径

- **事实**：`vf-instructions/mask-model.md:51,645,800`、`multi-dtype-numpy.md:182`、`ascendc-op-dev-coding-regbase/references/overflow-mode-guide.md:72,300,301` 直接引 `vf_experiences/{op}/{file}.md`。经验库一旦重构，这些指针断裂。
