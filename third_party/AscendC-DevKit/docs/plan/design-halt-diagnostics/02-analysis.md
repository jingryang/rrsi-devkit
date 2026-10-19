# 详设阶段假性 halt 与终止诊断信息缺失 — 方案分析（L3）

> 选项 / 选择 / 理由。决策拍板后冻结。问题事实见 `01-problems.md`。

## 决策 1（P1）— stale last_error 修法：三处各自补一行 vs 共享清理入口 → **选共享清理入口**

- **选项 A 三处各补 `last_error=None`**：改动最小，但同一遗漏已独立发生 3 次，说明「记得清」这条
  隐性约定不可靠，选 A 只是把第 4 次遗漏的概率留在原地。
- **选项 B 在 `_DesignSubstage` 上加一个共享方法，三处自定义 `transition` 的成功路径统一调用它清
  `last_error`**：把「成功即清本 stage 的 sticky error」从「每个作者要记得写」变成「结构上不可能漏」。
- **选 B 的理由**（四把尺子）：可维护（消除 3 处重复实现、与 `_parse_single` 已有约定统一）；
  可扩展（未来新增自定义 `transition` 的设计 stage 天然继承该行为，不必再单独记）；可诊断（不改变
  `last_error` 本身的语义，只修正清理时机，不掩盖真实错误）；架构合理（修复落在产生该状态的
  `transition` 层，不在 runner 层加兜底——runner 层无法安全兜底，因为 `IntegrateStage` 存在「产物字段
  齐全但 schema 校验仍报错」的合法场景，此时必须保留 `last_error`）。

## 决策 2（P2）— `stage_enter` 事件缺 scope 前缀：单点直接对齐 → **直接改**

现有代码在 `stage_aborted`/`iteration_start`/`stage_complete` 三处都用了
`f"{scope_prefix}/{stage.name}" if scope_prefix else stage.name` 这条规则，唯独 `stage_enter` 一处
遗漏、仍用裸 `stage.name`。修法是让 `stage_enter` 补上同一条规则，四处事件的 stage 命名口径归一，
`Report._from_events` 的字典查找即可命中。不存在需要权衡的选项——这是对既有约定的补齐，不是新决策。

## 决策 3（P3）— 终止消息缺场景信息：State 新增字段 vs 沿用现状仅补日志 → **选新增 State 字段**

- **选项 A 只在触发点把 WARN 打得更详细**：触发点（`graph_executor.py`）本身已经打印了准确信息，
  问题是这条信息传不到 `dispatcher.py` 的终止分支——A 不解决传递问题。
  ​
- **选项 B 在 `State` 上新增一个字段，在两处 halt 触发点（`fail_strategy=halt` 硬停 / `__halt__`
  纠正配额耗尽）各自写入 stage 名与失败原因，`dispatcher.py` 终止分支据此拼接消息**：让 `dispatcher`
  能区分两类 halt 并给出准确文案，而不是套用一段只适配其中一类场景的固定文案。
- **选 B 的理由**：可诊断性直接对应本次事故的教训——终止文案本身带偏了排查方向；两处触发点当前
  已经拿到了准确信息，只是没有随 `State` 传递出去，B 是补最短的传递路径，不引入新的判定逻辑。
- **落点细节**：该字段与既有的 `_stage_failed`/`is_terminal` 一样属于「本次运行的终态描述」，
  参照 `_stage_failed` 现有的 transient 处理方式（snapshot 序列化时按需保留/剔除，具体在实现时对齐
  `_stage_failed` 的既定做法，不单独另立一套序列化规则）。

## 决策 4（P4）— op_dir 与 cwd 语义混淆：prompt 文案增强 → **直接改**

在 `_operator_section` 或 `_output_boundary` 补一句明确说明：`op_dir` 是只读参考（外部算子源目录），
当前工作目录（cwd）才是唯一产出位置。这是预防性提示，`_missing_artifact_error` 里已有的事后纠正提示
不变；不存在需要权衡的选项——只是把已经在事后错误信息里存在的说法提前到首轮 prompt。

## 决策 5 — 早前排查中的「missing_artifact 反馈不进 loopback」猜测：核实后不成立，不作为问题登记

排查过程中一度怀疑 `_missing_artifact_error` 写入的 `user_feedback` 没有被下一轮 prompt 消费。
核对 `_DesignSubstage` 基类的 `_build_prompt` 后确认：`user_feedback` 确实会被拼进下一轮 prompt
（与 gate stage 的 `_loopback_feedback`/`_feedback_section` 是两条独立但都生效的反馈通道）。
不存在缺陷，未列入 `01-problems.md`。

## 决策 6（P5/P6）— 开局 WARN 与空转迭代：本轮不处理

`01-problems.md` P5（entry/context 空转 5 轮无 agent_spawn）与 P6（可选输入未提供的 WARN）均未观察到
与本次 halt 事故的因果关系，本轮不安排修复，仅作为事实记录留存。
