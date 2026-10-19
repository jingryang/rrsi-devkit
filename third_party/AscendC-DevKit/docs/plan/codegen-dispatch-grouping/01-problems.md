# Codegen 连续子阶段重复调度问题

## P1：同一职责内的连续子阶段被拆成独立 Agent 会话

Regbase codegen 的 Stage 4 将 `4.0/A/B1/B2/C.*/E/F` 保存为细粒度
`sub_stages`。当前调度器每轮只选择第一个 pending 子阶段，S4 Agent 契约也要求
一次只执行一个子阶段。因此 Host/Tiling、Kernel 骨架、Kernel 收尾、API/Plugin
等连续工作会重复启动 Agent。

每次新会话都会重新读取 `coding_index.md`、`meta.json`、设计产物、参考代码缓存和
工作区。实际运行中，非失败重试也会产生多个 `ascendc-dev-s4-coding-*.jsonl`
会话。

## P2：Agent 已返回完成列表，但框架只推进一个子阶段

S4 Agent 的 RETURN 契约包含 `completed_sub_stages=[...]`，但
`parse_return_signal()` 不解析该字段；`dispatch(COMPLETED)` 固定只将第一个
pending 子阶段标记为 done。

因此仅修改 prompt 让 Agent 连续执行多个子阶段，会造成代码已完成多个步骤、计划
只推进一个步骤的状态漂移。

## P3：现有检查点组不能直接作为调度单元

`checkpoint_group` 当前表示知识/编码上下文类别。目标调度边界会跨越部分现有类别：
`4.0(INDEPENDENT)` 需要和 Host/Tiling 合并，API 与 LAST 需要合并；Kernel 又必须
在 VF 独立验证点以及基础实现/收尾职责之间切开。

## P4：组内失败缺少已完成前缀的确定性提交协议

当前 PARTIAL 不推进任何步骤，FAILED 也不消费 `completed_sub_stages`。若一次 Agent
执行多个子阶段后在中间失败，框架无法区分已完成前缀和失败点，只能整组重做或冒险
将整组标记完成。
