# L4 实施配方 — dispatcher 层归属收口（KNOWN 清零）

> 上游：`02-analysis.md`（终态已锁死）。本文件是**分步实施配方**，每步 UT 绿，终态无遗留。
> 状态：**✅ 已实施（2026-09-03，双分支同构）**。
> 双分支：main + v0.2.0 同构（功能一致）。

## 目标终态（可断言）

1. `test_layer_dependencies.py` 的 `KNOWN == ∅`（改守卫为断言 KNOWN 空，防回潮）。
2. `dispatcher.py` 顶层 import 面 ⊆ {ascendc_devkit.domain, orchestration, infra}。
3. L6 只剩设备机制；L3 拥有全部编排决策（探测门 / op 卡 / backend 装配 / chip 记录）。
4. 新增设备子进程探针必有界超时（§1.3 源级守卫）。

## 分步（按依赖序，每步一个 commit，双分支同构后各自全量 UT）

### Step 1 — L3 `runtime_probe`（CANN + chip + NPU env 门）

- 新建 `orchestration/runtime_probe.py`：
  - `resolve_chip(probe_timeout_sec) -> str`：包 `detect.detect_chip_version`（L3→L6 合法）
  - `check_env() -> int | None`：CANN `CANNToolchain().is_available`（失败→EX_CONFIG）→ NPU
    `npu_probe.npu_runtime_available`（失败→EX_CONFIG）→ env_contract（L7，L3→L7 合法）
  - 进程级缓存（照搬 dispatcher `_RUNTIME_CHECK_CACHE` + Lock，迁来）
- dispatcher：`_run_runtime_checks` / `_resolve_chip_fields` 改调 runtime_probe，删内联 CANN/chip 代码
- 删 KNOWN：dispatcher→npu.detect、dispatcher→toolchain.cann
- 测试：preflight 测试改注入 runtime_probe stub（原 mock dispatcher 内部改干净）；runtime_probe 自身 UT（次序/缓存/EX_CONFIG）
- 验证：全量 UT 绿

### Step 2 — L3 `op_card`（op 卡生命周期：acquire→verify→release）

- 新建 `orchestration/op_card.py`：
  - `lease_and_run(state, pool, body)`：`resolve_op_card` → verify（batch 模式）→ `body(card)` → release
  - 从 dispatcher `_dispatch`（:937 前 acquire → `_dispatch_leased` → finally release）**原样搬**真逻辑，
    借还紧邻 + 唯一 finally 不变式保留（P13 §step-95 对称性硬仗的产出，不可破坏）
- dispatcher：`_dispatch` / 单 stage rerun 路径（:1504）改调 op_card.lease_and_run，删内联
- 删 KNOWN：dispatcher→card_pin
- 测试：P13 既有的对称性四路径测试 + 真机 ST 当安全网；跑 test_card_pin.py / P13 ST
- 验证：全量 UT + P13 ST 绿

### Step 3 — L3 `agent_backend_factory`（backend 装配上移）

- `application/agent_backend_factory.py` **整个移** `orchestration/agent_backend_factory.py`（包 stub fallback）
  - dispatcher import 改 L3 路径；application 下删旧文件
- 删 KNOWN：agent_backend_factory→backend/sdk/opencode ×3、dispatcher→stub_backend ×1
- 测试：factory 测试文件迁移路径；dispatcher 三装配点 stub
- 验证：全量 UT 绿

### Step 4 — infra 错误分类下沉 L4 domain

- `capabilities/agent/_shared.is_infra_error_type` → 移到 L4 `domain/`（纯分类，无 SDK 依赖，_shared 本身不 import SDK）
  - `_shared` re-export 或 dispatcher/其它消费方改 import L4
- 删 KNOWN：dispatcher→_shared
- 测试：分类 UT 迁移
- 验证：全量 UT 绿

### Step 5 — 邻居清零

- `application/profile_loader.py` → `orchestration/profile_loader.py`（L3→L6 合法），dispatcher/消费方改路径
- `cli/commands/show.py` 读 event_log：L2 提供读入口，show 调 L2（或 L1→L2 合法新增）
- 删 KNOWN：profile_loader→L6、show→L7
- 验证：全量 UT 绿

### Step 6 — dispatcher 瘦身 + 守卫断言 + §1.3 守卫

- 复查 dispatcher 无残留 L5/L6 import（顶层/函数内全扫）
- `mcp_tools._render_ask_user_ui`（loopback 决策 UI）若仍在 dispatcher：随 loopback 归 L3 策略（L3→L5 合法）
  - 若单点且小，最简归位：经 L3 loopback 单元，或评估 dispatcher 该处是否可真删
- `test_layer_dependencies.py`：KNOWN 设 `set()` + 断言；加「dispatcher import 面 ⊆ {L3,L4,L7}」断言
- 加 §1.3 源级守卫：AST 扫 src，任何 `sys.executable -c`（或 subprocess 设备脚本）必须有界 timeout
- 验证：全量 UT + 非 heavy ST + P13 两组真机/LLM ST

## 风险护栏

- 分步每步一个 commit + 全量 UT，不在一步里跨多个 KNOWN
- dispatcher 主流程（batch/single/resume/rerun/loopback 必经）大拆：租约 finally / 缓存 key / verify 时机
  靠 P13 既有的对称性四路径测试 + 真机 ST 当安全网（那是 P13 防死锁打的硬仗）
- 双分支同构：先 main（worktree）全绿，再 v0.2.0 同构全绿
- 端到端判据记录：卡池/smoke/gate 共用探针路径；KNOWN==∅；dispatcher 合规

## 实施结果（as-built，2026-09-03）

- **v0.2.0**：Step1-6 六 commit（81f18d68..c364b655），全量 UT 4261 绿（430s）。
- **main**：cherry-pick 六步 + 收口（e7f60148..5b93f83d），全量 UT 4623 绿（451s）。
- 全部 KNOWN 清零、dispatcher 终态只依赖 {L3,L4,L7}、L6 留设备机制、L3 持编排决策。
- 实施中发现并修：verify 经 op_card 绑定引用故 mock 须打调用处；route 决策簇从未
  生产调用故 default_idx→default_index 传参 bug 首次暴露；_render_ask_user_ui mock 用
  模块引用（绑定引用 mock 无效）；input mock 迁 builtins.input。

## Review 整改（2026-09-03，step-118 review reject 后）

review 发现 1 blocker + 4 major + 8 minor（reviews/step118-known-zero-review.md），
坐实即修：

- **B1**（blocker）：ST 13+2 处 mock dispatcher.build_agent_backend 抛 Exception 漏改
  （dispatcher 不再 catch）→ return_value=StubBackend()。
- **M1**：工厂 fallback 补 Logger.warn + 3 条 fallback UT（构造抛→Stub / 不 fallback
  传播 / ConfigError 不吞）。
- **M2**：探针超时守卫改纯形态检查（sys.executable+-c 须 timeout，不限字面量脚本）——
  旧守卫对全仓变量脚本形态空转。
- **M3**：main 侧改动在 known-zero-main 分支——用户裁定该推即推，docs 措辞成立。
- **M4**：route_decision 无生产接线（graph_executor 自带 loopback/escalation 决策），
  模块 docstring 诚实标注状态（非「归位清理」）。
- **m1-m8**：死 import / 假 re-export / docstring 层错 / State 注解 / 返回注解 /
  import 分组清理。

**整改后验证**：全量 UT 4264 绿（含 perf_probe_free 改测 runtime_probe——m1 删死 import
暴露的测试隐藏依赖收敛）；非 heavy ST 全跑绿（B1 修复后 test_integration 30 /
test_batch_e2e 2 过）。
