# P13 修复——NPU 卡治理：span 级租约 → op 级租约 + 子树结构 pin（step-116）

> L1：`01-problems.md` P13。agent 子树开卡对租约体系不可见（撞卡、hdcdrv 死等
> 家族病灶扩大、租约表成虚构账本）。

## L3 方案分析（2026-09-02 冻结）

### 定性与根因

正确性缺陷（资源治理域）。根因两层：

1. **租约粒度与消费主体错配**：NPUSlotManager 的互斥以「span」（框架子进程
   生命周期）为单位，而真实消费主体是 op——op 的 agent 子树（serve→bash→
   python 任意深度）开卡完全绕过池子，裸落默认卡。
2. **卡选择靠行为约定而非结构传播**：「每个开卡进程先问池子」是行为不变式，
   新增 spawn 种类即破洞（agent 的出现就是实证）。

### 核实事实（2026-09-02，全部实测/读码）

| # | 事实 | 证据 |
|---|---|---|
| 1 | backend 是 per-op 的：每 op 一次 `build_agent_backend`（dispatcher.py:932/1449）→ 每 op 独立 `opencode serve` 子进程，serve env 按次组装（`_build_serve_env`） | 读码；per-op env 注入点天然存在 |
| 2 | claude 路径同样有 per-session 注入点：`ClaudeAgentOptions.env` 字段 | 实测 dataclasses fields |
| 3 | **`ASCEND_RT_VISIBLE_DEVICES` 为 remap 语义**：pin=5 时 `device_count()==1` 且 `npu:0` 分配成功（restrict 下 npu:0 应报 invalid ordinal）；dsl-cluster 并行工具（8 worker 各 pin 不同卡、内部全用 device 0）为生产先例 | 子进程实验 ×3 |
| 4 | 批 = 单进程多线程（ThreadPoolExecutor）→ 共享 `os.environ` 不可写；注入必须走各 spawn 的 per-call env dict | 读码 |
| 5 | 运行期逃逸检测两通道全灭：进程只持 `/dev/davinci_manager`（卡无关 fd）；`npu-smi proc-mem` 对本 CANN 代 torch_npu 进程全盲（alive 持 256MB、8 卡查 pid 全 absent） | 实验 |
| 6 | 子树级租约在 agent 侧退化为 op 级（backend per-op、跨 agent 调用复用）；框架 span 侧保留 span 租约则与 op 租约在同一个池**机械死锁**（span acquire 等自己持有的卡） | 读码推理 |

### 选型（原则审计矩阵，仅列差异化条目）

| 原则 | 裁决 | 理由 |
|---|---|---|
| §1.15 统一抽象（漏写一处即出错=缺失抽象） | **op 级，决定性** | 子树级=每个 spawn 点各自记得借还——判据句已用一次真实事故演示（agent 未接租约=P13 本身）。op 级=单点掌握全部信号 |
| §2.5 唯一通路 | **op 级** | op 级收编后卡互斥一条通路（op 租约+env 继承）；子树级保留 span 通路（card_context）+ 新增 backend 生命周期通路 = 同职责两条路径 |
| §2.9/§1.14 构造性保证优先、最小结构 | **op 级** | 执行机制是 OS 语义（env 继承物理传播），框架只留骨架；净删除 span 租约基建。子树级每个异常退出路径挂 release 属「控模型」结构 |
| §1.10 业务语义非机制特征 | **op 级** | op 是框架管理的业务单元（state/events/workspace/失败归属全 per-op）；「spawn 子树」是机制特征 |
| §1.2 四把尺子+活性 | **op 级** | 可扩展/架构/可诊断/可维护全胜；子树级下 1 分钟 harness 可能等别的 op marathon agent 几小时 |
| §1.4 要么彻底改要么不改 | **op 级** | 子树级是补丁形态 |

子树级仅有的赢面（首期工作量小、设计阶段卡利用率）均在原则体系之外；6 ops×8 卡下利用率优势兑现不了。共享机器上 op 全程持卡 6/8 对同事余量收窄——记为已知代价。

### 终态语义

1. **op 边界一借一还**：dispatch 在 op 生命周期起点 `pool.acquire(npu_id=preferred,
   owner="op:{op_name}/{run_id}")`，终局 finally release。卡号写入 `state.npu_id`
   （hint → 权威值），此后 op 内一切消费者读它，不再各自解析。
2. **双变量单真值源**：一切 op 子树进程 env 携带
   `ASCEND_RT_VISIBLE_DEVICES=<物理卡>` + `ASCEND_NPU_ID=0`（remap 后逻辑号，
   事实 3）。物理事实只由 VISIBLE_DEVICES 携带；NPU_ID 恒 0。
3. **新 spawn 零动作正确**：env 默认继承传播 pin，新增 spawn 种类自动归位。
4. **检测层**：A=注入时刻自检（op 起、首个 spawn 前，用真实 env 组装跑子进程
   探针断言 `device_count()==1`，失败即报错 fail-fast——守护框架自身管路）；
   B=加载期守护 UT（扫 skill 工具脚本禁止字面量覆写 VISIBLE_DEVICES——历史
   唯一实证逃逸向量）；C=蓄意 unset 无可靠探测器（事实 5 双通道已证死），按
   裁决族二纪律不建不可靠探测器，诚实记录边界。

### 不做 / 边界

- `self_evolution`（training_runner/scheduling）不动：独立消费者，per-subprocess
  租约、无 agent 子树、无盲区问题，NPUSlotManager 保留其服务。
- regbase-vf-test `source_module.py` 的条件覆写与 `precision_debug_a5.py:468`
  的 ctx `"device_id"`（均 A5 域）待同事确认后同型修复——修复前 A5 ctx
  device_id 给出的物理卡号在 pin 子树内是非法逻辑号（`set_device(物理)` 在
  只见 1 卡的进程必败）。
- 批 resume 走 hard-pin 不排队：与持卡兄弟并发或卡集缩小时 EX_CONFIG
  fail-loud（预期行为，非缺陷）。
- TUI run-cases 复用持久化的 state.npu_id（无租约，与今日行为一致）。
- 残留已知缺口（诚实记录）：agent 蓄意 unset env 逃逸不可运行期检测，只能靠
  受害侧争用症状暴露。

### 零感知收敛轮（用户裁定 2026-09-03：agent 对 ASCEND_RT_VISIBLE_DEVICES 无感知）

零卡知识裁定延伸到**变量名**——注入 agent 的一切文本（prompt/命令串/skill）
不得出现卡 env 变量名；记录类（smoke.log 取证、events/state 账本）保留全保真
（被动事实非操作指引，且是人调试的一手现场）。落地三处：

1. codegen smoke 反馈 relay 元组去掉两个卡 env 变量（agent shell 经继承已带
   pin，复现 `python -u script` 默认即落本 op 卡——变量名零复现价值、纯暴露）；
   PYTHONPATH/ASCEND_CUSTOM_OPP_PATH 保留（agent shell 真缺、复现真需）。
2. precision 命令串（build_command/test_command）去掉双变量前缀——agent bash
   继承 serve pin，内层 CLI 经 resolve_op_card 的 pin-env 分支读回同一张卡
   （三重保险：pin env > state.npu_id 权威持久值 > legacy）；`_resolve_round_card`
   随之无调用点删除。
3. **device_id 死链全拆**（step-90 遗产）：ctx device_id → init-checkpoint
   `--device-id` → control.json device_id 字段——grep 全仓证**零消费者**，而
   control.json 正是 diagnose agent 的读物（字段=暴露面）；cannbench_eval
   optional 契约的 stale 条目、`--device-id 0` 防吞零回归测试随通路一并退役。

测试勘误一并落地：subtree-pin ST 断言改锚 tool 输出字段（命令串回显会污染
字符串包含检查）。ST prompt 本身 grep 变量名属测试仪表（单次验证会话），
不属生产注入面。

## L4 实施

### 新增

- `adapters/npu/card_pin.py`（取代 card_context.py 的唯一卡模块）：
  - `card_pin_env(card:int) -> dict`：`{"ASCEND_RT_VISIBLE_DEVICES": str(card),
    "ASCEND_NPU_ID": "0"}`（§1.15 单点）。
  - `resolve_op_card(preferred, pool, owner) -> tuple[int, Callable|None]`：
    pool 非 None → `pool.acquire(npu_id=preferred, owner=owner)` 返回 (card,
    release)；pool None（单 op CLI/内层 CLI）→ pin env（VISIBLE_DEVICES）> 
    preferred > ASCEND_NPU_ID env > 0，(card, None)。hard-pin 语义须含占用
    校验（同池互斥，不能与既有租约撞车——实现时核对 slot.acquire 硬_pin 分支，
    缺则补）。
  - `verify_pin(card, base_env=None) -> None`：子进程
    `python -c "import torch,torch_npu; assert torch.npu.device_count()==1"`，
    env=`{**os.environ, **card_pin_env(card)}`，timeout 90s；失败抛
    `EnvironmentNotAvailableError`（dispatch 既有处理路径）。
- `tests/ut/skills/test_card_pin_guard.py`：扫 `.claude/skills/**/*.py`，断言无
  「字面量 RHS 直接覆写 ASCEND_RT_VISIBLE_DEVICES」（`os.environ["X"]="0"` 形；
  `setdefault` 与参数化赋值 `str(npu_id)` 不受限）。

### 修改（注入点，全部 per-spawn env dict，不碰共享 os.environ）

- `application/dispatcher.py`：op 租约（state 定稿后、backend 创建前 acquire +
  `state.with_updates(npu_id=card)`；主 try 的 finally release，覆盖正常/异常/
  SIGINT/超时全部出口）+ `verify_pin` 探针 + `build_agent_backend(card_pin=card)`。
  dispatch docstring 的 card_pool 语义改写（op 级）。1449 的单 stage 路径若涉
  NPU stage 同样处理（实现时核实）。
- `application/agent_backend_factory.py`：union kwargs 增 `card_pin`（既有机制
  自动过滤）。
- `capabilities/agent/opencode_backend.py`：ctor 存 `card_pin`；
  `_build_serve_env` 末尾 `env.update(card_pin_env(self._card_pin))`（None 跳过）。
- `capabilities/agent/sdk_backend.py`：ctor 存；`ClaudeAgentOptions(env=
  card_pin_env(card))`（SDK env 为 CLI 子进程增量 env——语义在 claude 路径 ST
  时核验）。
- `adapters/npu/runner.py`：`execute` 删 `card_context` 与 `card_pool` 形参，
  `npu_id: int` 必填（None 即 ValueError，dispatch 保证已解析）；
  `run_env={**os.environ, **card_pin_env(card), ...}`（原 `"ASCEND_NPU_ID":
  str(card)` 删除）；`_build_test_harness` 的 `$npu_id` 替换值改喂 `"0"`。
- `adapters/npu/_harness_template.py`：模板文本不动（`set_device($npu_id)`/
  setdefault 行由替换值 0 承载语义）。
- `orchestration/stages/deploy.py`：`card_context(state.npu_id, None)` 块删，
  `env.update(card_pin_env(state.npu_id))`；smoke 脚本内 `set_device(npu_id)` 改
  `set_device(0)`；env_summary 增 VISIBLE_DEVICES。
- `orchestration/stages/precision_debug_substages.py`：`build_command`/
  `test_command` 前缀改 `ASCEND_RT_VISIBLE_DEVICES={card} ASCEND_NPU_ID=0`；
  `_resolve_round_card` 删 card_lease 分支（只读 state.npu_id）；`:1490` 删
  `iteration_card_lease = True` 声明。
- `orchestration/stages/codegen.py:1794`：env relay 元组增
  `"ASCEND_RT_VISIBLE_DEVICES"`。
- `orchestration/stages/cannbench_eval.py` + `adapters/evaluation/
  cannbench_scorer.py`：`run_eval` 删 card_pool 形参；`with card_context(...)`
  块删，`card = npu_id`；eval 子进程 `env.update(card_pin_env(card))` 且
  `--device-id 0`（remap 后逻辑号）。
- `orchestration/stages/precision_debug.py` + `adapters/evaluation/_common.py` +
  `application/debug_service.py`：`run_precision_cases`/`EvalRequest`/
  调用点删 `card_pool` 形参（npu_id 权威直达 runner）。
- `.claude/skills/ascendc-custom-op-precision/KernelLaunch/launcher.py`
  `_ensure_camodel_env`：三处 `os.environ["ASCEND_RT_VISIBLE_DEVICES"]="0"` 改
  `setdefault` 语义（有继承 pin 则不覆写；独立 TUI 无 pin 保持历史 "0"）——
  camodel 仿真行为不变，宿主 env 污染向量消除。

### 删除（旧通路，§2.5/§1.4）

- `adapters/npu/card_context.py` 整文件（span 租约 + env 兜底链 → card_pin.py）。
- `orchestration/kernel/runner.py` `card_iteration_lease` 及 runner 循环集成
  （:64/:396）——与 op 租约同池死锁；迭代稳定卡由 op 卡构造性提供。
- `orchestration/kernel/state.py`：`card_pool`、`card_lease` 字段及 snapshot
  两侧 pop 逻辑、注释更新（npu_id 语义 hint→权威 op 卡）。
- `orchestration/card_pool.py`：`build_shared_card_pool` 保留（batch_runner →
  dispatch 的池构造点），docstring 更新（不再入 State）。

### 测试（TDD 先行）

- 新 `tests/ut/adapters/test_card_pin.py`：pin_env 两变量、resolve 三态
  （pool/env-pin/standalone）、lease release 全出口、verify_pin 成功/失败
  （monkeypatch subprocess）。
- 新 `tests/ut/capabilities/test_backend_card_pin.py`：serve env 含 pin 对、
  sdk options.env 含 pin 对、factory union kwarg 透传。
- 新 `tests/ut/skills/test_card_pin_guard.py`（守护 B）。
- 改造：`test_card_iteration_lease.py` 删（机制亡，op 租约测试取代）；
  `test_precision_card_lease.py`、`test_adapters.py`（card_context 部分）、
  `test_cannbench_scorer.py`、`test_deploy.py`（env 断言改 pin 对+device 0）、
  `test_state_snapshot_rebuild.py`、`test_batch_runner/test_application/
  test_cli/test_run_batch`（card_pool 引用清理）、`test_stages.py`、
  `test_codegen_smoke_feedback_facts.py`、`test_harness_timeout_adaptive.py`。

### 验证

- 全量 UT 绿（改造后，4060）。
- **对称性复检轮（用户指令 2026-09-02，锁操作逐点证明）**：
  - 发现并修复 ①探针失败路径漏 release（首版 except 直接 return EX_CONFIG，
    批内共享池下该卡锁死到批结束——正是 step-95 家族）；②acquire 与主 try 间
    ~140 行 stretch 异常绕过 finally 的盲区；③with_updates 误入
    except-RuntimeError 罩内的误报风险。
  - **按用户裁定重构为「借还紧邻 + 中间封装」终态**：dispatch 尾部
    acquire→`_dispatch_leased(...)`→finally release 相邻 6 行；中间一切（探针
    →backend→executor→主循环）提取为 `_dispatch_leased`，其任何 return/异常
    必然穿过唯一 finally——未来修改不可能在借还之间插入逃逸路径；顺带消除
    acquire-RuntimeError 与 body-RuntimeError 同点捕获歧义。
  - 对称性四路径回归门（`TestDispatchLeaseSymmetry`）：探针失败/段异常穿透
    /探针段 KeyboardInterrupt/acquire 撞兄弟租约——全部断言池清空+正确退出。
  - 死代码随通路退役：dispatch 的 CardAcquireTimeout 处理器 +
    graph_executor 传播清单条目（span 级带超时 acquire 全拆后无产生点；op
    租约 timeout=None 阻塞排队不抛）；其 dispatch 映射测试一并退役。
  - scorer `npu_id=None` 由静默落 0 改为与 runner 同款确定性 ValueError
    （§1.15 单一解析点纪律，两侧一致）。
- ST（新增，均已真跑绿）：
  - `tests/st/test_npu.py::TestOpCardPinRealChain`（@npu）：真实机器探针正向
    （非 0 卡 device_count==1）+ 破坏注入负向（证明探针非常绿）。
  - `tests/st/test_agent_subtree_card_pin.py`（@llm dual-backend）：真实
    spawn 的 agent 在 bash 里 `env` 打出双变量 pin——opencode（serve env→
    bash 继承）与 claude（`ClaudeAgentOptions.env` 增量语义，L4 挂着的待核验
    项就此关闭）双侧活体证据；断言锚定 tool 输出字段（命令串回显会污染
    字符串包含检查——首版即翻车于此）。
- 全量测试终态（2026-09-03，用户裁定 ST 全跑含 heavy_llm）：
  - UT 4059 全绿。
  - 非 heavy ST 129/129（`test_self_evolution_stages` 的 device_id 契约断言
    随死链退役同步一条）。
  - heavy_llm 29 例串行 2:09:23：28 直接过；1 例（precision reject-hint
    闭环）失败，取证定位为**测试断言过严、非框架缺陷**——agent 完整闭环
    （修复+commit+验证 err=0.0+case resolved_pending）后写了提及旧值的解释
    性注释，撞上 `_BUG_MARK not in kernel` 裸子串断言；该裸子串在修复信号
    方向本可被种子注释 `// BUG: 应 CAST_RINT` 骗过（双向都失准）。修法=三处
    断言收紧为代码形锚定 `RoundMode::CAST_RINT / RoundMode::CAST_NONE`（与
    文件内 stub_test 判定同一形，无漂移），单例重跑绿（88.75s）。
- 下批真实跑观测：op→卡映射唯一性（events）、verify_pin 打点、无「device 0 挤压」
  症状、hdcdrv 家族无新增。
