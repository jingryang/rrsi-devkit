# opencode 硬切分类修复 — L4 实施方案（2026-09-14）

> 层级：**L4 / 实施方案**。改哪个函数、什么顺序、怎么验证。
> 证据见 `01-problems.md`；选型见 `02-analysis.md`（A：partID→类型关联）。

## 改动（全部在 `src/ascendc_devkit/capabilities/agent/opencode_backend.py`）

1. `_new_sse_log_state()`：新增 `"part_kinds": {}`（partID → IR kind，生命周期对齐
   `step_reasoning_chars`）。
2. `_handle_sse_event()` 的 `message.part.delta` 分支：
   - 删除 `field == "reasoning"` 死分支（§1.4）；
   - delta（`field` 恒 `"text"`，L1 F3）改按 `partID` 查 `part_kinds`，
     `kind == "thinking"` 才累计 `step_reasoning_chars` + 打点
     `last_reasoning_delta_ts`；
   - `state["chars"]`（text+reasoning 合计）原样保留。
3. `_handle_sse_event()` 的 `message.part.updated` 分支：在既有 kind 分派前记
   `state["part_kinds"][part.id] = kind`（`_part_to_block` 归一，与 IR 同源）。
4. step-start 分支与换轮（role=user）分支：随 `step_reasoning_chars = 0` 一并
   `state["part_kinds"] = {}`（内存有界 + 生命周期同源）。

## 测试（tests/ut/capabilities/test_opencode_backend.py，TDD：先红后绿）

- 改 `test_sse_reasoning_delta_stamps_classification_evidence`：真实协议形态
  （part.updated 标记 `type:"reasoning"` + delta `field:"text"` 带 partID）→ 累计/打点；
  text part 同形态 delta → 不累计、ts 不动。
- 改 `test_sse_step_start_resets_step_reasoning_chars`：fixture 换真实形态。
- 新增：未标记 partID 的 delta 不累计（订阅中途启动，诚实无证据）。
- 新增：step-start / 换轮清空 `part_kinds`（跨步/跨轮 partID 不串）。

## 验证

1. 受影响文件 UT 前台全绿（`PYTHONPATH=src pytest tests/ut/capabilities/test_opencode_backend.py`）。
2. 全量 UT 绿（受影响面：capabilities / orchestration）。
3. 端到端（非本步内）：下批真实跑出现 cut 时，日志应出现详细版文案与非空
   `各次 thinking chars：[…]` 清单——留观察项，不阻塞合入。

## 评审整改（2026-09-14，`reviews/unpushed-v020-ahead1-opencode-cut-classification-review`）

首版提交（`89e8aa90` / main `eadfa1dc`）评审发现同源第二通路未同步，整改如下：

1. **F1（blocker，§2.5）删除方案 A 残留死通路**：`opencode_sse.py` 的
   `sse_event_to_ir_records` + `_DELTA_FIELD_KIND` —— 与本体同源的 `field=="reasoning"`
   分型假设，且属被否决方案 A 的残留（`opencode-streaming-transport/03-impl` 明载
   「A 收敛时用；B 仅用前两个」，实际走 B）。生产零调用（仅测试自证），按 §2.5
   **整删**而非同步修。同批删除同类死的 `is_idle_completion` / `event_error`
   （生产零引用）、随之失效的 `_EVT_SESSION_IDLE`/`_EVT_SESSION_STATUS`/
   `_EVT_SESSION_ERROR` 常量与 `time` 导入。
2. **F4（minor）**：清 `opencode_backend.py` 的死 import `sse_event_to_ir_records`。
3. **F2（major，§3.9）协议守护**：新增
   `test_opencode_backend.py::test_sse_part_kinds_tracked_from_real_wire_frames`
   ——真实 wire 帧序列经 `parse_sse_frames` → `_handle_sse_event`，守护
   「delta 按 partID 关联类型」的不变式；`test_opencode_sse.py` 的
   `test_spike_slice_end_to_end` 改写为 `test_wire_frames_parse_end_to_end`
   （帧形态守护，显式断言 delta 的 `field` 恒 `"text"`）。
4. **F3（minor）**：L2 step-122 行补端到端待验限定。

模块 docstring 补「field 恒 text、分型须经 partID→part.type」协议注意（§2.12：
防后人重蹈）。

