# L1 问题记录 — NPU 探测家族单通路 + 组合根运行时探测的层归属

> 本文件只记录客观事实（哪里坏 / 什么现象 / 有什么信号），**不提方案、不排顺序、不写决策**
> ——方案与理由在 L3（`02-analysis.md`），实施在 L4（`03-impl-*.md`）。
> 现状摄于 v0.2.0 `8179d827` / main `6da0a673`（2026-09-03，探测单通路收口已上两分支）。

## 关联既有记录

- 2026-09-03 review 整改文档（`batch-20260829-49134b-codegen-delivery/19-review-unpushed-remediation.md`）
  「遗留观察」节：main 曾双探测模块并存（`orchestration/npu_probe.py` + `infra/npu_probe.py`）。
  **该条已于同日清偿**——`npu_runtime_available` 并入 L3 卡健康族、`infra/npu_probe.py` 删除，
  双分支功能对齐（8179d827 / 6da0a673）。本 L1 是清偿后对新暴露的「同族探测散点 + 组合根
  直连 L6」的记录。
- P13（`batch-20260829-49134b-codegen-delivery/01-problems.md`「P13」节 + `18-npu-op-card-lease.md`）：
  op 级卡租约 + pin + verify_pin 检测层 A 的产权地。本 L1 涉及的 verify_pin / card_pin 引用以
  该处定义为准。

---

## 事实 A：全仓有 5 处「有界子进程探针」，判据各异、机械重复、超时已漂移

**观测**：全仓 grep `sys.executable, "-c"` 命中 5 处 `torch/torch_npu` 子进程探针：

| 位置 | 判据（回答什么） | 失败形态 | 消费方 |
|---|---|---|---|
| `adapters/npu/probe.py::probe_device` | 这张卡能 open device context 吗（set_device+alloc） | raise | healthy_cards → 卡池/smoke/gate |
| `adapters/npu/card_pin.py::verify_pin` | pin 管道对吗（remap 后恰好可见 1 卡） | raise | dispatch 批 op 起始 / scorer eval 前 |
| `adapters/npu/detect.py::detect_chip_version` | 芯片型号是什么 | 宽容（失败非致命） | dispatch 启动（build 时也用） |
| `orchestration/npu_probe.py::npu_runtime_available` | 有没有任何一张健康卡 | (ok, reason) | dispatch smoke / perf gate |
| `infra/env_contract.py::(探针)` | sitecustomize 被外部 hack 投毒吗 | 宽容 | dispatch 启动 Check 3 |

**重复的事实**：5 处共享同一机械行为——「起一个 `sys.executable -c <脚本>` 子进程、有界超时、
非零退出码/超时 → 诚实诊断（绝不静默折成「可用」）」。但每处各自内联 `subprocess.run` + try/except
+ 诊断拼装，无共享实现。

**漂移的事实（同一行为、不同纪律）**：
- 超时界：`probe_device` 默认 60 / `verify_pin` 默认 90 / 卡级 `hw_probe_sec` 60（外墙 120）
  / `detect`、`env_contract` 各自默认——同一「驱动偶发 hdcdrv 死等（`hdcdrv_connect_wait_reply`
  无超时无异常，memory `npu-driver-hdcdrv-hang`）」要防，每处默认不同。
- 诊断格式：`"全部 NPU 卡不可用（…）"` / `"NPU card pin verify failed … stderr tail"` /
  `"torch_npu_available=False…"` / `"smoke 异常（exit N）…"`——消费方各自 grep 自家文案，
  无统一契约。

## 事实 B：verify_pin 与 probe_device 判据语义相反（正交），但机械同构

**语义相反（B-1，决定判据不得合并）**：
- pin 变量被 CANN 静默忽略时（如拼写/未生效）：`device_count()==8` → **verify_pin 失败**而
  probe_device（对任意健康卡）**通过**。
- 目标卡坏了时：device_count 往往照常报数（set_device/alloc 才失败）→ verify_pin（只数卡）
  **可能通过**而 probe_device **失败**。
- pin 语义下设备号恒 0（remap，P13 实测）——`probe_device(card=N)` 与 pin env 组合本身矛盾。
- 结论：verify_pin 判「pin 管道正确性」，probe_device 判「卡健康」，**同判据合流 = 制造错误归类**。

**机械同构（B-2，决定动作可合）**：两者 spawn 形态、超时防 hang、非零→诚实诊断逐字同构。

## 事实 C：dispatcher 组合根 3 处直连 L6，层守卫 KNOWN 永久挂着

**观测**：`dispatcher.py`（L2 组合根）跨层直连 3 个 L6 探测模块：

| dispatcher 直连 L6 | 用途 | 时机 |
|---|---|---|
| `adapters.npu.detect` | 启动探测芯片型号 → State.chip_version | 组合根启动 |
| `adapters.toolchain.cann` | Check 1 探 CANN 工具链 | 组合根 `_run_runtime_checks` |
| `adapters.npu.card_pin` | op 边界租卡 + verify_pin | op 边界（P13） |

**守卫状态**：`tests/ut/test_layer_dependencies.py` 的矩阵（L2→{L3,L4,L7}）是强制的；这三处进
KNOWN 集合（`"dispatcher.py -> L6 …detect/cann/card_pin"`），各自带「TODO: lift to an L2 DI
container with the other dispatcher runtime probes」注释，长期不兑现。

**守卫损失的观测**：守卫开了 3 个洞 → 「新 L6 探测进 L2」暂无结构性拦截（纯靠 review）。

## 事实 D：verify_pin 已有 UT/ST 守护 + 真机 ST（§3 真链路）

- `test_card_pin.py`：verify_pin 超时 / 非零 / 无子进程覆盖 + dispatch 接入点。
- ST 新增两组真跑绿（P13 记录）：@npu 真机探针正/反向 + @llm dual-backend 子树活体。
- `test_application.py`：dispatcher preflight 用 `mock.patch` 模块内部（`_run_npu_smoke_subprocess`
  / `CANNToolchain`）测 Check 1/2/3 次序——**UT 与组合根内部实现耦合**（若把探测收敛到 seam，
  这些可改注入 stub）。

## 事实 E（诚实边界）：本 L1 未实证「因散点而实际出错的运行事故」

- 5 处漂移目前是「同一行为多份实现 + 纪律不统一」的**结构性债**，不是已观测到的一次性事故。
- 超时界漂移的最坏情形（慢卡冷启 12-44s 被 30s 外墙误杀）**已在 2026-08 实证过一次**——
  那是双模块并存时 infra 版外墙与卡级界不一致所致，正是本 L1 事实 A 的同类根因；本次统一后
  该类错配由「单点同源」构造性消除。
