# L4 实施方案 — 卡租约对称化（TDD）

> 对应 L3 冻结方案。改动 1-4；UT 先红后绿。

## 改动 1：pool owner 记录 + 等待纪律（slot.py）

- `_acquired: set` → `{card: owner_label}`（dict），`acquire(..., owner="")`
  增参；`release`/`list_acquired`/`_warn_dead_cards_locked` 适配；
- 等待分支日志含 holders 归因：`waiting for NPU card; holders=[gelu/diagnose,
  unique/cannbench_eval]`（替代无主告警；audit 阈值保留）；
- `acquire(timeout=...)` 既有语义保留：timeout 到 → `CardAcquireTimeout`
  （异常消息带 holders——诊断随失败走）。

## 改动 2：runner 迭代级对称租约（runner.py）

- 新增 contextmanager `card_iteration_lease(stage, state, owner)`：
  - `stage` 未声明 `iteration_card_lease` → no-op（零行为变化）；
  - `state.npu_id` 非空（hard-pin）→ no-op（对齐既有语义：hard-pin 不碰池）；
  - 否则 `pool = state.card_pool`；pool None（redeploy 子进程等）→ no-op；
    pool 存在 → `with pool.acquire_context(owner=owner)`，卡号经
    `state.with_updates(card_lease=card)` 注入；
- `_run_stage_body` 迭代循环：`actions = stage.actions(...)`（:352）到
  `result_state = stage.transition(...)`（:397）整段包进 `with`；
  **infra-retry 重入（:390）的二次 actions 在 with 内**——对称后重入不再
  重复 acquire（lease 在迭代头取得一次）；
- owner 标签 = `f"{execution/op 名}/{stage.name}"`（batch 线程上下文可取；
  取不到退化 stage 名）。

### 实施检查项（2026-08-27 反面质疑补，两项必须以 UT 坐实）

1. **card_lease 清零目标 = 出块后的最终 result_state**：State 不可变且循环内
   不断重绑——with 的 finally 里恢复"进块时捕获的旧 state"是无效操作；必须在
   with 块之后对最终 `result_state` 做
   `result_state = result_state.with_updates(card_lease=None)`，否则 transition
   返回的 state 携带指向已释放卡号的悬挂值；
2. **transition 路径零嵌套池获取**：新租约窗口 [actions 起, transition 完]
   比现状 [actions 起, transition 首行] 大——若 transition 内存在嵌套
   pool.acquire，5 算子并发下（租约 5 + 嵌套 N）可能 >8 卡形成池耗尽假死。
   现状"transition 首行即 release"暗示无嵌套，但必须以 UT/静态检查坐实
   （声明租约的两 substage 的 transition 全路径无 pool 获取）。

## 改动 3：声明 + 散点删除（precision_debug_substages.py）

- 两个持卡 substage 类增 `iteration_card_lease = True`（§1.10 业务语义声明）；
- 删除：`_acquire_card_lease`/`_release_card_lease` 及 4 个调用点
  （:1620/:1981/:2131/:2667）、`_CARD_LEASE_SIDECAR`/`_card_lease_path`/
  `_read_card_lease`（§2.5）；
- `_resolve_card_for_task` 优先级：hard-pin > `state.card_lease` > 0
  （读 State 瞬态字段，读文件变读内存）。

## 改动 4：State 瞬态字段（kernel/state.py）

- `card_lease: int | None` 瞬态（`_transient_fields`，snapshot/恢复两侧剥离
  ——对齐 `_bubble_origin` 先例；resume 新进程池为空，剥离正确）。

## 验证

1. UT（先红后绿）：
   - slot：owner 记录/释放清除/等待日志含 holders/超时消息含 holders；
   - card_iteration_lease：未声明 no-op；hard-pin no-op；pool None no-op；
     声明+池 → acquire 注入 state.card_lease + finally 释放恢复 None；
   - **对称性主用例**：声明租约的 stage，actions 抛异常 / infra-retry 重入
     actions 二次执行 / _check_timeout 抛出 / transition 抛出——四路径
     断言 `pool.list_acquired() == []`（99c4c0 泄漏形态回归门）；
   - `_resolve_card_for_task`：state.card_lease 传递；transient 快照剥离；
   - 既有 precision substage UT 适配（散点删除后行为等价：卡仍可达命令行）；
2. 全量 `tests/ut --quick` + 非 heavy ST；
3. 重放验证：模拟 unique 05:49 形态（actions→agent infra abort→重试 actions→
   再 abort→耗尽），断言全程租约数 ≤1、结束归零。

## 不做清单

1. 不做租约 TTL/心跳自动回收（L3 否决）；
2. 不在 stage 内 try/finally 包 actions（生命周期够不着，L3 否决）；
3. 不保留 sidecar（§2.5）；
4. 不动 `card_context` 三个既有对称位点（它们本来就对）。

## as-built（2026-08-27）

- 改动 1-4 全部落地；两个实施检查项均坐实：
  ① card_lease 清零在 with 块 finally 对**最终** result_state 执行
  （`test_outgoing_state_card_lease_cleared`）；② precision 模块内零嵌套池
  获取（deploy 的 card_context 传 pool=None 走 env 兜底、scorer 属别的
  stage；代码审查 + 四路径对称 UT 双重覆盖）；
- `card_context` 增 owner 透传（scorer/deploy 既有调用零改动）；
- UT：`test_npu_slot_owner.py` 10 + `test_card_iteration_lease.py` 12 +
  `test_precision_card_lease.py` 重写 11；全量 UT 3736 绿。
- 下批观测点：批内租约数 ≤5、结束归零、等待日志 holders 归因。
