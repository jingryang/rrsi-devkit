# L3 方案分析 — dispatch 主进程 NPU 探测子进程化（F1/F3 根因修复）

**工作目录**: `docs/plan/dispatch-npu-probe-subprocess/`
**覆盖问题（L1，产权在彼处，此处仅引用）**: `docs/issue-analysis/20260810-state-to-snapshot-reference-roots-startup-crash.md`（2026-08-28 深夜复发记录段：埋点判别假设②成立 + `/proc/pid/maps` 主进程原生暴露面实证）
**状态**: 调研完成，方案 a 选定，待拍板 → 实施（L4 见 `02-impl.md`）

## 1. 要恢复的不变式

**编排主进程（`ascendc-devkit run`）是纯 Python 进程**：一切设备/原生库访问（torch/torch_npu/CANN 运行时）只发生在子进程。这不是新发明——仓内已有两处同一哲学的既有决策：

- **M1**（`dispatcher._run_npu_smoke_subprocess`）：NPU smoke 放子进程 + timeout，注释明言"主进程同步 smoke 在 driver hang 时永久阻塞…子进程隔离把 hang 限定在 timeout 内"、Check 1 注释"毫秒级，进程本安全"；
- **P69 stage 2 / 卡隔离**：NPU 子进程按 spawn 边界 acquire 卡 + `set_device` 硬绑定——设备访问边界=子进程。

F1（0810 起概率性 `AttributeError: reference_roots` / "preflight 报缺已提供输入"）与 F3（0828 起整进程 SIGSEGV exit 139）是**同一条不变式被三处违反**的后果：`adapters/npu/detect.py:75`（`_probe_chip_blocking` 在 dispatch 进程的探测子线程内 `import torch_npu`，`dispatcher.py:781→588` 调用，**runtime probe 无条件执行**——design_target_chip 仅携带 CLI 值，runtime 侧 "probe authority" 恒探测，设 CHIP 也绕不开；2026-07-01 85308e70 引入）、`adapters/npu/slot.py:79`（`NPUSlotManager._detect_device_count` 的 torch_npu 兜底，env 未设 `ASCEND_NPU_COUNT` 时触发，2026-05-28 引入）、`infra/provenance.py:283/326`（`_npu_device_count`/`_probe_torch_npu_version` 主进程 import，经 `dispatcher.py:982/1007 build_provenance` 调用，恰在 preflight→snapshot 的 F1 崩溃窗口内）。三处任一残留都会把 torch 灌回主进程——修复必须**枚举收口全部三处**，不能只修首个加载者。实测主进程 t=3s 即 418-460 个 Ascend|torch 映射区、73 线程；torch 2.10.0+cpu + torch_npu 2.10.0.post4 + CANN 9.1.0-beta.3 混载下原生层间歇写坏堆，轻则 `State.__dict__` 124 项塌缩为 2/20 项（F1），重则段错误（F3）。本机既往病史见 `/root/.local/.../sitecustomize.py`（0821）自述"CANN library loading triggers SIGSEGV (-11)"。

## 2. 选项与取舍

| 选项 | 内容 | 判定 |
|---|---|---|
| **a. 探测子进程化 + 加载期守卫（选定）** | `detect.py` 条件路由（torch_npu 已在 sys.modules → 进程内直查，覆盖子进程调用方；未加载 → subprocess 探测，M1 同款 + 缓存双检锁）；`slot.py` 卡数兜底改 env → npu-smi 子进程 → 默认；`provenance.py` 两探针改 `importlib.metadata` + env/npu-smi；`run` 入口装 import 守卫（主进程 import torch/torch_npu 即 fail-fast，§1.3 不变式机器强制，逃生门 env）；调用方（dispatcher/runner）零改动 | ✅ 见下 |
| b. 环境旁路 | 显式传 `CHIP_VERSION` + `ASCEND_NPU_COUNT` 绕开 import 路径 | ❌ **根本不可行 + 不作终态**：runtime probe 无条件执行（设 CHIP 绕不开 detect 向量），env 只能旁路 slot 一处；且 probe 的存在意义就是"用户不传则探测"的默认路径=主路径，纯度取决于每个调用方是否记得设 env 属机制特征代理（§1.10 精神违反），漏写一处即回退（§1.15） |
| b′. stub-PYTHONPATH A/B（仅实验） | 临时 stub 模块遮蔽 torch_npu（import 即 raise ImportError）跑批对照崩率 | ⚠️ 仅作修复前根因反向实证的**一次性实验手段**（detect/provenance 走 except 路径、行为退化为 UNKNOWN，可接受）；不进主干 |
| c. torch_npu/CANN 版本配对修复 | 把 torch 2.10.0+cpu / torch_npu 2.10.0.post4 / CANN 9.1.0-beta.3 配齐 | ❌ 治标：主进程原生暴露面仍在，版本由平台侧漂移即复发（机器病史已证 CANN 加载本身有 SIGSEGV 风险）；可与 a 并行但不替代 a |
| d. dispatch 整体下沉子进程 | 每 task 一个子进程跑 dispatch | ❌ 改动面大：吞掉 ThreadPoolExecutor 并发模型与 events.jsonl 实时物化，违反最小改动与既有架构 |

**四把尺子（§1.2）过方案 a**：
- **可维护**：把"主进程纯 Python"从隐式假设变为显式结构（探测即子进程），与 M1/P69 注释里的设计意图闭合；
- **可扩展**：修在 adapter 层内部、接口不变，`dispatcher.py:588`、`runner.py:366` 等所有调用方自动受益；未来新增探测需求有同款模式可循；
- **可诊断**：子进程崩溃/超时留独立 exit code + stderr（M1 已验证的形态），不再以"主进程随机字典塌缩"这种最难定位的方式暴露；
- **架构合理**：设备访问边界=子进程，正是既有分层；反向方案 d 才是越层。

## 3. 同工作项附带项（一次收口，避免二次进场）

1. **死亡 exec 的遗言进 run.log**：`batch_runner.py:508-509` `except Exception: _log.exception("dispatch failed for %s", ...)` 走 stdlib logging，只到共享控制台、不进该 exec 的 run.log（run.log 只镜像引擎 `Logger`）——这就是"死掉的算子 run.log 只剩一行 `constructed`"观测缺口的直接原因（§1.2 可诊断）。改为引擎 `Logger.error(..., exc_info=True)`。同函数 L502-503 的 `[integrity] dispatch-enter tr keys` 埋点同理换 Logger（同一理由）。
2. **state-integrity 探针升级**：`dispatcher._log_state_integrity` 缺失分支补打 `keys=sorted(d.keys())`——若修复后仍复发，可直接点名 2/20 个键的归属对象，一次定位。
3. **埋点退役计划**：上列探针（含 0827 四点位）在修复经批实测验证后整段删除（0827 注释承诺"机制定位后整段删除"），单独收尾步，不与本体修复混提。

## 4. 验证策略（详见 L4）

- 不变量硬验收：真跑 `run --batch` **全程**采样 `/proc/<pid>/maps` **零** Ascend|torch 映射区、线程数为 Python 侧规模；晚期出现映射 = stage 期漏网向量，按同模式补收口（显式边界步，非验收失败）；
- 语义回归：probe 超时 → `EnvironmentProbeTimeout` → `--runtime_target_chip` 兜底路径行为不变；卡数 env 优先序不变；npu-smi 物理卡 vs 可见卡、provenance"已装 vs 可 import"两处语义变更 UT 显式钉住；
- 实测（heavy_llm，执行前用户确认成本）：芯片未显式指定的批连跑（历史段错误率 2/3），零 SIGSEGV、零字典塌缩、埋点全程 `fields=124 ok`；
- 根因独立实证（可先于实施，一次性实验）：stub-PYTHONPATH 遮蔽 torch_npu（import 即 ImportError）跑批对照崩率（见选项 b′；注意 **`CHIP_VERSION` 旁路无效**——runtime probe 无条件执行）。

## 5. 归因置信边界

根因链为强证据 + 排除法归因（maps 实证 + 时序吻合 + 机器病史 + 全静态排除 + 合成压测阴性），未直接捕获原生层写坏堆的那一次写。方案可证伪：三向量收口 + 守卫 + 全程 maps 归零 + 崩率实测对照；若仍崩则归因错误，探针 keys 升级接棒重新归因（sqlite/解释器等剩余候选）。
