# opencode 后端产物落点取证失效 — 问题记录（L1）

> 纯事实快照（哪里坏了 / 凭什么这么说）。不提方案、不排顺序、不写决策。
> 来源：分析真实 run `20260716-121432-97ea5a`（fork-join 分支 halt 复盘，见 `forkjoin-branch-halt/`）
> 时追查「T1 split 为什么没在 cwd 产出 `tiling_split.json`」，发现 step 51
> （`artifact-location-provenance`）的确定性取证 `_harvest_relocation_evidence` 对该 run 实际使用的
> **opencode 后端完全空转**——本该区分「agent 没写」与「写到别处」的证据从未被采集，故真实落点不可复原。

## 背景：step 51 取证机制与它的隐含前提

step 51 的 `_harvest_relocation_evidence`（`orchestration/stages/design_substages.py:128`）扫描
agent transcript jsonl，从中找 Write/Edit 调用的 `file_path`，判断产物是否落在了 cwd 之外，
用来把「agent 没写文件」与「agent 写到了 op_dir/别处」两种同信号的失败区分开。它读取的字段结构是：
- block 判据：`block.get("kind") == "tool_use"`；
- 工具名：`block.get("tool_name") in ("Write", "Edit")`；
- 路径：`block.get("tool_input", {}).get("file_path")`。

该结构对应 **SDK 后端**（`sdk_backend.py` 的 `_serialize_block` 记 `{"tool_name","tool_input"}`）。
step 51 的落地时间是 2026-07-15 15:55（commit `79b2ea0e`），本 run 是 2026-07-16，代码在位——
**不是「修复未上线」问题**。

## P1 — transcript block schema 不兼容：opencode 用 `type`/`name`/`input`，取证读 `kind`/`tool_name`/`tool_input`

opencode 后端 `_parts_to_records`（`capabilities/agent/opencode_backend.py:621-648`）把返回消息的
`parts` 映射为 block 时，对工具调用产出的是：
```
{"type": "tool_use", "name": <工具名>, "input": <参数>}
```
（line 638-643，键为 `type`/`name`/`input`）。而 `_harvest_relocation_evidence` 找的是
`block["kind"]=="tool_use"` + `block["tool_name"]` + `block["tool_input"]["file_path"]`。
**两套字段名完全不交叉**：即便 opencode transcript 里写入了 tool_use block，harvest 的
`block.get("kind")` 恒为 None、`tool_name`/`tool_input` 恒缺失，扫描必然 0 命中、返回 None，
落到「无证据」分支给统一错误文案。取证对 opencode 结构上不可用。

## P2 — 采集不完整：backend 只落 POST 返回的收尾消息，未取会话历史，turn 恒为 1

逐个核对本 run `agents/*.jsonl`（对 `tool_use`/`file_path` 全体 grep）：**0 命中**。
每份 transcript 仅 1 行、`turn=1`，block 只有 `type` 为 `step-start`/`thinking`/`text`/`step-finish`
的收尾消息内容（agent 最后一条总结），**不含本轮中间的 Write/Edit 工具调用**。

**根因已定位**（`opencode_backend.py:207-263`）：opencode 后端是**单次阻塞 POST**
`/session/{id}/message`，返回值只是**最终组装好的那一条消息** `{info, parts}`（代码注释原话
"opencode is single-shot"）。`_parts_to_records`（line 621-648）把这条消息的 parts 映射为 blocks、
且把 `turn` **硬编码为 1**。中间轮次的 Write/Edit 工具调用在会话的**更早消息**里，不在这条返回值内，
因此从未进入 transcript。backend 从不调用 `GET /session/{id}/message` 取整段会话历史（该 REST
端点存在，`_http_json` 通用 helper 已具备调用能力，只是未用）。

**同根的用户可观测症状**：opencode 后端**打不出 turn**（不像 claude SDK 逐 turn 流式返回、可标 turn N）——
正因返回的是单条最终消息、无 turn 维度，`_parts_to_records` 只能硬编码 `turn=1`。turn 缺失与
tool_use 缺采是**同一个根**（只取末条消息、未取会话历史）的两个表现。

## P3 — 两面叠加的后果：opencode 链路上「未写 vs 写错目录」始终不可判定

P1（schema 不兼容）与 P2（采集不完整）任一成立即足以让 step 51 取证失效，二者同时成立。
后果：**在实际生产运行所用的 opencode 后端上**，`artifact-location-provenance` 想解决的核心歧义
——「agent 没写」还是「写到了别处」——依然无法区分，产物落点无确定性证据。step 51 的 L2 状态标为
「✅ 已实施」，该结论对 SDK 后端成立，但对 opencode 后端不成立（覆盖缺口）。

## 影响

- 本 run（`forkjoin-branch-halt` 触发根因）的真实落点已不可复原，只能确定「产物没到 cwd」。
- 更一般地：只要 self_evolve 流水用 opencode 后端跑，任何设计子阶段的 `missing_artifact` 都拿不到
  落点证据，落点误判的确定性排障能力在这条链路上缺席——与 step 51 的目标相悖。
