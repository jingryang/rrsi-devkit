# L4 实施方案：code-tree 生产者统一孤儿路径反馈（F7 残留闭合）

> 对应问题：F7（主体已由 F3 收口，见 issue 收口记录）。本方案闭合残留：
> code-tree 生产者类内不一致（codegen 有孤儿反馈、perf 没有）。
> 用户决策（2026-08-21）：按统一抽象实施（§1.15）。

## 一、单点抽象

`artifact_recovery.orphan_path_feedback(agent_result, working_dir, stage_name,
locator_name)` —— 证据（`_shared._transcript_orphan_paths`，与小产物搬回恢复
同一证据源）→ 判定 + 标准路径反馈文本 + WARN。返回 `(orphan_paths, feedback)`；
无证据返回 `([], "")`。**判定与文案单点**；熔断豁免/迭代计数等 stage 私有语
义留消费方接线。

## 二、消费方

- **codegen**：删除内联块（§2.5），改调 helper（`locator_name="op_dir"`），
  保留私有语义——不消耗熔断（+0）、走迭代预算重生成、`artifact_misplaced`。
- **perf**：transition 落空分支（agent 跑过、非 infra、零产物）接 helper →
  `user_feedback` + `last_error=artifact_misplaced`；`_build_tuning_prompt` 消费
  `user_feedback`（标准反馈通道）；成功轮清 sticky 反馈（P5）。
  迭代预算照常消耗（perf 无熔断可豁免，反馈换下轮重生成）。
- **smoke**：死代码（P57 后 smoke 归 codegen 会话内），不接。
- **A5 codegen（regbase）**：同事所有权，不动；移交提示在 F7 issue。

## 三、防遗忘边界（诚实披露）

未来新增代码型 stage 仍需"记得调 helper"（纪律残留）。为 2 成员稳定类加
声明-校验机器属过度结构化（§1.14）；触发条件（第 3/4 个成员出现）与升级路径
（`orphan_policy` 声明 + §1.3 加载期校验）记录在 F7 issue。

## 四、验证

- 新增 `test_perf_orphan_feedback.py` ×4：孤儿轮注入反馈+error+预算照常 /
  空跑不注入 / 反馈进下轮 prompt / 成功清反馈。
- codegen 行为不变回归：`test_codegen_orphan_escape.py` ×10 原样通过。
- 全量 UT `--quick`。
