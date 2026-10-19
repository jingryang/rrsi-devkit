# L3 方案分析 — 卡租约对称化：配对上移到迭代生命周期持有层

> 状态：**冻结**（2026-08-27）。用户判据入档：**acquire/release 不对称、内聚度
> 不够是最容易造成死锁的形态**——本方案以此为第一性原则。

## 0. 对称性诊断（用户原则的代码坐实）

现状两种持卡纪律并存：

| 形态 | 站点 | 对称性 |
|---|---|---|
| `with card_context(...)` / `acquire_context` | scorer:111、runner:529、deploy:871 | ✅ 同层配对、finally 释放、异常安全 |
| 阶段租约 acquire/release 分离 | precision 两 substage：acquire 在 actions（:1620/:1981）、release 在 transition 首行（:2131/:2667） | ❌ **4 个散点、跨 2 个生命周期阶段、仅靠约定配对** |

分离形态的具体泄漏路径（均在 runner `_run_stage_body` 迭代循环内坐实）：

1. **infra-retry 重入**（runner.py:364-390）：agent 基础设施失败 → 回退重试
   `actions = stage.actions(...)` **再次执行**——前一张租约未释放（transition
   未到），且 sidecar 被覆盖后**旧卡号失联、永久无法释放**。unique 05:49-05:52
   spawn 三连败 = 每轮漏一张；
2. **_check_timeout 抛出**（:330）跳过 transition → 泄漏；
3. actions/_execute_actions 异常 → run_stage except 中止 → 泄漏。

99c4c0 的 8 卡逐张泄漏即上述路径在 5 算子 × 长批上的累积。

## 1. 主修复：配对上移（对称化的唯一正确层次）

**租约的 acquire/release 必须由拥有「actions→agent→transition」完整迭代的
那一层持有**——即 runner `_run_stage_body` 的迭代循环：

```python
with card_iteration_lease(stage, state, owner=...) as lease:   # acquire 在此
    actions = stage.actions(result_state, iteration)           # 原 :352
    ... infra-retry 循环 ...                                    # 原 :364-390
    result_state = stage.transition(result_state, result)      # 原 :397
# finally release 在此——覆盖异常/超时/中止/infra-retry 全部路径
```

- **一处 acquire、一处 release、同一函数、with 语义**——结构对称，泄漏在
  in-process 内**结构性不可能**（finally 覆盖一切；线程不被 kill）；
- stage 用**业务语义声明**迭代级持卡（§1.10）：类属性
  `iteration_card_lease = True`，加载期校验（§1.3）；runner 按声明决定是否
  进入 with；
- precision 两 substage 的 4 个散点（2 acquire + 2 release）与 sidecar
  读写全部删除（§2.5 唯一通路）。

## 2. transport：sidecar 废除，改 State 瞬态字段

- sidecar 消费点仅 `_resolve_card_for_task`（优先级 hard-pin > sidecar > 0）
  ——单消费者，可安全替换；
- 租约卡号经 State 瞬态字段 `card_lease` 传递（快照剥离，同 `_bubble_origin`
  先例）；`_resolve_card_for_task` 优先级改为 hard-pin > `state.card_lease` > 0；
- 租约本就是 in-process 资源（池在内存），进程死池亡——文件 transport 是
  当年配对边界错置的产物，随之消亡。

## 3. owner 记录 + 用户语义的等待纪律

- `pool.acquire` 增 owner 标签（调用方传 execution/op + stage 名）；
  `_acquired` 由 set 变 {card: owner}——等待者日志可归因
  （"waiting, holders=[op/stage…]"，取代现在无主告警）；
- **用户语义保持**：活跃占用 = 正常等待（不 abort）。对称化后 in-process
  「死等」（租约持有者非活跃）已结构性不可能，剩余等待必然是真忙；
- 有界超时（量级 30min）**仅作防未知的最后防线**：触发时 dump 持有者诊断
  + `CardAcquireTimeout` 走既有失败通路——诚实失败而非静默挂死（§1.2），
  且触发即说明存在未知的非对称路径（可诊断信号）；
- cannbench_eval transition 的 `card_context`（99c4c0 阻塞位点）同样获得
  owner 诊断日志；5 算子 ≤5 张并发租约 < 8 卡，结构性不会再耗尽。

## 4. 否决项

- **不动 stage 内 try/finally 包 actions**：租约必须覆盖 agent 会话（跨
  actions/transition），函数内 finally 够不着——这正是当初分离的动因；
  上移到 runner 才是唯一既有完整生命周期的层；
- **不做租约 TTL/心跳自动回收**：对称修复后死租约不存在，TTL 是给「泄漏
  还会发生」留的假设性兜底——机制复杂度买不回正确性（§1.14）；
- **不保留 sidecar 作为并行通道**（§2.5）。

## 5. 原则对照

§1.2 四尺子（可维护=单点 with / 可扩展=新 stage 声明即得 / 可诊断=owner
归因+超时带诊断 / 架构=生命周期层持有配对）、§1.10（业务语义声明持卡需求
+ 等待纪律）、§1.15（唯一配对通路）、§2.5（散点与 sidecar 删除）。
