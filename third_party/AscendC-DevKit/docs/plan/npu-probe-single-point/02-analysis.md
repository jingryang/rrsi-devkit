# L3 方案分析 — dispatcher 层归属收口：KNOWN 清零，无遗留

> L1 事实源：`docs/plan/npu-probe-single-point/01-problems.md`。
> 关联产权：P13 的 card_pin/verify_pin 语义以 `18-npu-op-card-lease.md` 为准。
> 状态：**方案已锁定（2026-09-03）**——反复复盘后收敛的终态，无待拍板项。实施见 `03-impl-draft.md`。

## 0. 结论（锁死，不再有第二版）

- **矩阵不豁免**。`test_layer_dependencies` 的层矩阵是 §1.1 的机械化身；本仓 L2 到不了 L6 是刻意设计，
  无「组合根接线」例外（用户裁定：豁免 = 开特殊通道，不合理）。
- **终态**：`dispatcher.py` 只依赖 {L3, L4, L7}；它需要的每个 L5/L6 能力都经一个 **L3 编排单元**获得；
  **KNOWN 表清零**（真上移/真归位，非豁免、非删守卫）。
- **分层不变式（四条原则一致指向，非选择）**：
  - **L6 = 设备机制层**：probe_device / verify_pin / pin_env / detect / CANNToolchain ——「怎么跟设备说话」。
  - **L3 = 编排决策层**：healthy_cards / npu_runtime_available / runtime env 门 / op 租约 / backend 装配 / 恢复分类 ——「编排该知道的资源与决策」。
  - dispatcher(L2) 只调度，经 L3 要事实。
- **验证**：每步全绿分步收口；KNOWN==∅ 有测试断言（防回潮）；dispatcher import 面断言 ⊆ {L3,L4,L7}。

## 1. 为什么不是别的几个方案（否决记录）

| 否决项 | 理由 |
|---|---|
| (a) 豁免组合根 | 用户裁定豁免=特殊通道不合理；L2 到不了 L6 是刻意架构，无全能接线者概念 |
| (c) 维持现状（KNOWN 挂着） | §2.5 反「新旧并存长期态」；KNOWN 带 TODO-lift 永不兑现=债换皮 |
| P1「建 subprocess helper 收 5 处」 | 5 处判据/消费/生命周期低内聚，按 subprocess 归类是伪收敛；真重复（双整探针）2026-09-03 已删；剩余各自有界、各诚实，是正常管道。改用一个共享 helper 提高耦合，非 §1.15 的「同一行为重复」 |
| P3b「造 L3 seam 只抬 preflight」 | 代码实况：CANN 是 6 行单调用内联、chip 在另一函数——trio 非内聚单元；seam 是「为守规则造壳」 |
| 「整体搬 dispatcher 到 L3」 | 搬层只解决 import 合法，不解决模块太胖（1900 行 god-object 放 L3 仍是 god-object）；且 L1 够不到 L3，还得再造 L2 shell |
| verify_pin 并入卡健康族 / 并入 preflight | 判据语义相反（pin 被忽略→verify 败而 probe 过）；op 级 per-op 生命周期非启动探测 |

**主线**：dispatcher 是越界 god-object → 修 dispatcher，不修矩阵、不豁免。按职责拆成单一用途 L3 单元，每个单元承载真实编排决策（非转手壳），KNOWN 随真上移而清零。

## 2. 逐能力终态归属（KNOWN 全表 14 条的归位）

### 2.1 dispatcher 的三个 L5/L6 import 簇 → 拆给 L3 单元

| dispatcher 越界 | 真职责 | L3 单元（新家） | L6 留下的机制 |
|---|---|---|---|
| `npu.detect`（chip）| 跑前解析本机 chip → State | `runtime_probe.resolve_chip()` | detect_chip_version（机制）|
| `toolchain.cann`（Check1）| 跑前环境门 | `runtime_probe`（CANN→NPU→env 门 + 进程级缓存）| CANNToolchain.is_available（机制）|
| `npu_probe` NPU 可用性 | 同上（**已在 L3**，先例）| 同上 | probe_device（机制，healthy_cards 串行调用）|
| `card_pin` resolve_op_card + verify（:937/:976/:1504）| op 卡生命周期（acquire→verify→release）| `op_card`（L3：per-op 租约 + 内部 verify）| card_pin.py 保留 verify_pin / pin_env（机制）|
| `capabilities.agent.{backend,sdk,opencode}`（经 agent_backend_factory）+ `stub_backend` fallback | backend 装配（config→实例）| agent_backend_factory **移 L3**（含 stub fallback）| —（装配是编排，无机制留 L6）|
| `_shared.is_infra_error_type` | infra 错误分类（瞬态/永久→resume/halt）| 分类器移 **L4 domain**（纯分类无 SDK 依赖）| — |
| `mcp_tools._render_ask_user_ui` | loopback 决策 UI | L3 loopback 策略（内部→L5 合法）| — |

### 2.2 邻居（非 dispatcher，一并清零）

| KNOWN | 归位 |
|---|---|
| `application/agent_backend_factory.py → L5 ×3` | 随 2.1 移 L3（factory 是 L2 模块却装配 L5 = 违背 L2→L5）|
| `application/profile_loader.py → L6` | L3 薄委派（L3→L6 合法）|
| `cli/commands/show.py → L7 event_log`（L1 只能 {L2,L4}）| L2 提供读历史入口，show 调 L2 |

### 2.3 不动（本就在合法边 / 既定产权）

- `env_contract`（L7）：`L2→L7` 本就合法（矩阵 2→7）；为 preflight 内聚可随 runtime_probe 收（L3→L7 合法），非必须。
- L6 `card_pin.py` 的 verify_pin / pin_env：**留 L6**（设备机制 + L6 scorer 同层直用）。
- 探测策略 healthy_cards / npu_runtime_available：**留 L3**（npu_probe，2026-09-03 收口产物，不动）。

## 3. 为什么这次经受得住最严厉质疑

- **verify_pin 矛盾已解**：verify 留 L6、但 dispatcher 不直调——L3 `op_card` 的 acquire 路径内部调 verify（L3→L6 合法）。dispatcher 只碰 L3。终态「dispatcher 只依赖 {L3,L4,L7}」可达。
- **非搬层**：每个 L3 单元承载真实编排决策 + 真实多调用方（runtime_probe 服务 batch/single/resume/rerun 多入口；op_card 双 stage 复用），非假 seam。
- **KNOWN 清零是断言而非口号**：层守卫测试收尾改为 `assert KNOWN == ∅`（防回潮），dispatcher import 面另设断言 ⊆ {L3,L4,L7}。
- **无遗留判据**：KNOWN==∅ / dispatcher 合规 / L6 只留机制 / 新增设备子进程必有界超时（§1.3 源级守卫）。

## 4. 验证

- 分步收口（L4），每步 UT 绿。
- 末尾全量 UT 双分支 + 非 heavy ST + P13 两组真机 ST（@npu 探针正/反向、@llm dual-backend 子树）当回归安全网。
- 端到端判据：卡池 / smoke / gate 共用探针路径；KNOWN==∅；dispatcher import ⊆ {L3,L4,L7}。
