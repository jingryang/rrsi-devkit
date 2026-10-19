# L1 问题记录 — NPU 卡租约生命周期泄漏 → 池耗尽 → 无界死等

> 记录客观事实，不提方案。实证：批 20260826-114823-99c4c0（2026-08-27 05:10
> 起批级死锁 2h40m+，py-spy 取证 + slot.py 代码核勘）。

## P1：租约释放唯一依赖 transition() 执行，跳过 transition 的路径全部泄漏

- step-90 阶段租约设计：`_acquire_card_lease`（precision_debug_substages.py:212，
  actions() 开头调用）→ `_release_card_lease`（:237，transition() **首行**调用）；
  持卡跨度覆盖中间 agent 会话是设计意图（正确）；
- 但 release 只挂在 transition 入口——**deadline 打断、actions 后迭代异常、
  agent spawn 失败重试等一切跳过 transition 的路径都漏一张**；
- 本次实证：8 张卡在 00:38~05:10 CST 间逐张泄漏（审计时 card0 已占 19079s、
  全部超 600s 阈值），无 owner 记录可归因（`_acquired` 是 set，无持有者信息）。

## P2：acquire 无超时 → 池耗尽即批级死锁，无自愈、无诊断出口

- `slot.py:129-130`：`timeout=None` → `self._cond.wait()` **无限等**；
- py-spy 实证死锁形态：moe 的 precision actions（05:10 起）与 unique 的
  cannbench_eval card_context（05:55 起）两线程同时在 acquire 等待；
  MainThread join futures——**没有任何超时/中止/告警路径**；
- 审计函数 `_warn_dead_cards_locked` 已能检测「held > 阈值」并告警
  （"possible dead card from an un-released subprocess"），但**只告警不回收**。

## P3：物理设备与簿记脱节——泄漏卡实际完全空闲

- 死锁时 npu-smi 显示**零真实进程**、8 卡全部物理空闲；
- 泄漏是纯内存簿记（in-memory pool），不涉及设备真死；「等一张实际空闲的卡」
  是本死锁最刺眼的形态。

## 用户语义约束（§1.10，2026-08-27 拍板方向）

acquire 加有界超时**是对的，但退出判据必须区分两种等待**：
- 所有卡被**活跃任务**真实占用（其他算子在跑）→ 等待是**正常现象**，不 abort；
- 只有**死等**（租约持有者已不存在/不活跃）才应退出/回收。
即判据是「租约持有者的存活性」业务语义，不是「等了多久」机制代理。
