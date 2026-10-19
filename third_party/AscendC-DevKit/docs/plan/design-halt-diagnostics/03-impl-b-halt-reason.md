# 详设阶段假性 halt — 实施（L4）：P3 终止消息补 halt_reason

> 改哪 / 顺序 / 怎么验证。决策见 `02-analysis.md` 决策 3，事实见 `01-problems.md` P3。

## 改动 1 — `State` 新增 `halt_reason` 字段

在 `domain/state.py`（或既有 `_stage_failed`/`is_terminal` 所在的同一个 `State` frozen dataclass）
新增字段 `halt_reason: dict | None = None`，结构为 `{"kind": str, "stage": str, "message": str}`：
- `kind` 取值二选一：`"fail_strategy_halt"`（设计类 stage 的硬停）/ `"corrective_exhausted"`
  （codegen/verify 纠正配额耗尽）。
- `stage`：触发终止的 stage 名。
- `message`：具体失败原因（沿用触发点当前已经算出来的那句话，不重新生成新文案）。

该字段的 snapshot 序列化处理对齐 `_stage_failed` 的既定做法（同一 transient 归类，不单独另立规则）。

## 改动 2 — `graph_executor.py` 两处 halt 触发点各自写入

- `fail_strategy=="halt"` 硬停分支：在打印准确 WARN 之后、把 `_stage_failed` 清空为 `None` 之前，
  用同一份 stage 名与失败原因构造 `halt_reason={"kind": "fail_strategy_halt", ...}` 写入返回的
  `state.with_updates(...)`。
- `__halt__` 纠正配额耗尽分支：在设置 `is_terminal=True` 的同一处，用当前已有的上下文
  （耗尽配额的 stage 名、最近一次纠正失败原因）构造 `halt_reason={"kind": "corrective_exhausted", ...}`。

两处只新增字段赋值，不改变各自原有的判定逻辑与既有 WARN 输出。

## 改动 3 — `dispatcher.py` 终止分支消费 `halt_reason`

终止消息构造逻辑改为：若 `state.halt_reason` 非空，按 `kind` 分支拼接对应场景的准确文案（点名
`stage`+`message`）；若为空（防御性兜底，理论上两处触发点都会写入），保留现有通用文案不删除。

## 验证

- TDD：先写失败用例再改代码。
  - `graph_executor.py`：构造一次 `fail_strategy=halt` 硬停场景，断言返回的 `state.halt_reason.kind
    == "fail_strategy_halt"` 且 `stage`/`message` 与触发原因一致；再构造一次 `__halt__` 纠正配额耗尽
    场景，断言 `kind == "corrective_exhausted"`。
  - `dispatcher.py`：分别喂两种 `halt_reason` 的终态 `state`，断言终止消息文本不同、且各自点名正确
    的 stage，不再是同一段写死文案。
- 回归：现有依赖终止消息固定文案的用例（如有）同步更新断言。
- 全量 UT + 非 heavy ST（CLAUDE.md §3.6）。

## 后续（不在本轮）
- P5/P6（entry/context 空转迭代、开局可选输入 WARN）：`02-analysis.md` 决策 6 已明确本轮不处理。
