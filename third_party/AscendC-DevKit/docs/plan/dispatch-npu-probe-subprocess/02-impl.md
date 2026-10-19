# L4 实施方案 — dispatch 主进程 NPU 探测子进程化

**上游**: `01-analysis.md`（方案 a 已选定）
**状态**: ✅ 已实施（2026-08-29）——UT/maps 验收记录见文末「实施结果」

## 实施偏差（与上文的差异，均记录于此）

1. **守卫安装点从 run CLI 入口迁至 `dispatch()` 顶部**：分层依赖检查器拒绝
   L1→L7（`cli/commands/run.py → infra.import_guard`）；且 dispatch() 是
   batch/resume/单算子三条编排路径的唯一漏斗，装在此处覆盖更全、归属编排层
   （L2→L7 既有先例）。幂等，批内 N 线程重复安装 no-op。
2. **`batch_runner` 的 `[integrity] dispatch-enter` 行删除而非换 Logger**：它与
   dispatcher 入口的 dispatch-enter 行数据重复（§2.5 唯一通路），且打印于
   bind_run_log 之前、无论如何进不了 run.log。
3. **tests/conftest.py 增加 `DEVKIT_ALLOW_INPROC_TORCH=1` 宿主豁免**（仅测试侧）：
   本仓 pytest 会话有插件在启动期预载 torch_npu，真跑 dispatch 的用例会误触
   守卫的「已预载→抛」分支；守卫自身双分支由 test_import_guard.py 显式覆盖
   （该文件摘除此 env）。生产语义不变。

## 实施结果（2026-08-29）

- **UT**：新增 test_detect_subprocess_routing（12）、test_npu_smi（9）、
  test_import_guard（8）、遗言/卡数/provenance 语义用例若干；既有
  test_detect_sentinel / test_adapters(TestChipDetection) 补缓存隔离 fixture
  （fake 硬件每例不同，进程级缓存须用例间隔离）、test_adapters 两处零参 probe
  stub 适配新签名。
- **maps 验收（dispatch 窗口 + 早期 stage）**：真跑 `run --batch`（芯片未指定，
  agent 派发前主动终止，零 LLM 成本）全程 10 采样点 **0** 个 Ascend|torch 映射区
  （修复前 418-460）、线程 7→4（修复前 73）、无段错误；新批 3 exec 全部
  `constructed fields=124 ok`、零塌缩行、无孤儿进程。
- **stage 期向量清点（收尾项提前完成静态部分）**：`toolchain/pta.py:45` 与
  `adapters/npu/precision_compare.py:29` 为顶层 torch import，但当前无任何主进程
  引用者（仅注释提及）；未来误引由守卫响亮兜底。cannbench_scorer/
  _harness_template 的 torch_npu 引用均为子进程脚本内容（合法）。
  **修正（20260829 批实证）**：「precision_compare 无主进程引用者」只对**模块级**
  成立——三处**函数级 lazy import**（`runner.py` execute / `_build_test_harness`
  ×2、`precision_debug.py:66`）仅需要其中的 torch-free 阈值核心，却在调用时把
  顶层 torch 整个加载进主进程。静态清点只扫了导入面，漏了调用面；守卫按设计
  把它变成确定性拦截（见下条）——机器强制优于静态清点的直接实证。
- **第四向量收口（2026-08-29，验证批 20260829-024316-f0252f 实证）**：upsample_custom
  codegen 尾段 deploy → smoke harness 生成（主进程）经 `_build_test_harness(rule=None)`
  lazy import precision_compare → 守卫拦下、stage halt（fail_strategy=halt 可 resume）。
  修复：torch-free 阈值核心（`DEFAULT_THRESHOLDS`/`merge_thresholds`/
  `threshold_for_dtype` + 小值域/相消表与 `_lookup` 族）上移
  `domain/precision.py`（CompareRule 语义归位，§1.15 单点；domain 纯数据不
  反向依赖）；precision_compare 反向引用；三处 lazy import 改模块级域层 import
  （懒导入的 torch 理由消失）。回归网：test_import_guard 增功能性子进程用例
  （装守卫重放 smoke harness 生成全路径，零 torch 泄漏）——补上「调用面纯度」
  这个静态导入面 UT 覆盖不到的维度。
- **第五向量收口（step-106，2026-08-29 静态清点发现，与 step-105 同批实施——用户
  拍板"一次验证批覆盖纯度家族"）**：`NPURunner.__init__→_check_environment`
  （`runner.py:400/406`）进程内 `import torch`。全仓构造点三处：`_common.py:139`
  （run-cases 子进程，合法不动）；**`perf.py:123`**（PerfGate 测量，主进程构造且在
  try 外——触发即 stage 报错）；**`perf.py:179`**（`_check_npu_available`，主进程构造
  且包在 `except Exception` 内——守卫错误被吞、**静默判 NPU 不可用**，最恶劣形态）。
  self_evolve_op 无 perf stage 故验证批未触发；属 devkit 单算子工作流潜伏向量。
  **修法**：
  - `perf.py:179` 改子进程探测——`dispatcher.py:470` 已有同款子进程代码串
    （subprocess 内 `NPURunner()._torch_npu_available`），按 review m4 预案（第 5 处
    subprocess 模式出现）**顺手收敛为 infra 单点**（如 `infra/npu_probe.py`），
    dispatcher 与 perf 共用（§1.15）。
  - `perf.py:123` 走 probe-free 构造：把 deploy `_build_smoke_harness` 既有的
    `NPURunner.__new__` + 显式置字段惯用法**正式化为构造通路**（类方法或
    `probe=False` 参数），需先核对 `execute()` 依赖的实例字段清单（_chip_version/
    _torch_npu_available/_device_count/_env_info），probe-free 默认值语义要明确。
  - **UT**：主进程（子进程纯度用例模式）构造+execute 编排路径零 torch；179 的探测
    走子进程单点；`except Exception` 不再可能吞守卫错（探测失败语义=诚实返回不可用
    +原因，非静默）。
- **待办**：批实测（heavy_llm，用户已授权验证批 20260829-024316-f0252f，3 算子）——
  第四向量修复后 `RESUME=1` 续跑 halted exec 终判；达标后删除 state-integrity
  埋点（import 守卫永久保留）。

## 改动配方（按实施顺序）

### 1. `src/ascendc_devkit/adapters/npu/detect.py` — chip 探测子进程化

- 现函数 `_probe_chip_blocking()`（L62）**原地拆两半**：
  - 当前"进程内 `import torch_npu` 探测"的函数体 → 重命名为 `_probe_chip_inproc()`（保留原实现）；
  - `_probe_chip_blocking()` 变为**条件路由 + 子进程包装**：
    1. **短路**：`"torch_npu" in sys.modules` → 直接调 `_probe_chip_inproc()`（**已加载=零新增暴露**；覆盖 smoke/run-cases 等**子进程**调用方如 `runner.py:366`——那里 torch 本就加载，避免子进程再 spawn 孙进程多付 ~7s，行为与今天完全一致）；
    2. 未加载（主进程恒此态，见守卫）→ `subprocess.run([sys.executable, "-c", "from ascendc_devkit.adapters.npu.detect import _probe_chip_inproc; print(_probe_chip_inproc())"], capture_output=True, text=True, timeout=...)`，stdout 解析为 chip；超时/非零退出/解析失败 → 与现行一致的 UNKNOWN 语义（L35 注释"probe cannot produce a truth, so it returns UNKNOWN"）。模式对齐 `_run_npu_smoke_subprocess`（`dispatcher.py:454`，M1）。
- `detect_chip_version()`（L92，线程 + holder + `EnvironmentProbeTimeout` 骨架）**不动**。
- **进程级缓存 + 双检锁**：模块级 `_PROBE_CACHE`，锁复用 registry 双检锁模式（§1.15；防三 dispatch 线程并发首探同时 spawn 三个子进程）。**只缓存 chip 型号**（静态硬件属性；与今天 sys.modules 事实上只 import 一次的时效语义等价），失败不缓存（下个 dispatch 可重试）。

### 2. `src/ascendc_devkit/adapters/npu/slot.py` — 卡数兜底去 torch_npu

- `NPUSlotManager._detect_device_count()`（L67-83）删 `import torch_npu` 兜底分支，优先序改为：
  1. `ASCEND_NPU_COUNT` / `ASCEND_DEVICE_NUM` env（现行为保留）；
  2. `npu-smi info` 子进程解析卡数（`shutil.which("npu-smi")` 定位，输出解析与 `batch_self_evolve.sh:147` 同款；失败静默跳过）；
  3. 默认 8（现行为保留）。
- **语义声明（UT 钉住）**：`npu-smi` 数**物理卡**，原 `torch_npu.device_count()` 数 `ASCEND_RT_VISIBLE_DEVICES` 过滤后的**可见卡**——受限可见性场景下结果可能不同。缓解：env 优先级不变（受限场景本就应显式声明 env），兜底仅覆盖"无 env 无过滤"的默认场景，语义差异不触达。

### 2b. `src/ascendc_devkit/infra/provenance.py` — 两探针去主进程 import（第三向量，勿漏）

- `_probe_torch_npu_version()`（L326）：`import torch_npu` → `importlib.metadata.version("torch_npu")`（纯 Python 读发行版元数据，零原生加载；`PackageNotFoundError` → None）。
- `_npu_device_count()`（L283）：`import torch_npu` → env（`ASCEND_NPU_COUNT`/`ASCEND_DEVICE_NUM`）→ `npu-smi info` 子进程卡数（与 slot 同款 helper，**抽单点共用**，§1.15）→ None（**不**给默认值，None 本就表示未知，语义不变）。
- `build_provenance`（L365 调用点）与调用方 `dispatcher.py:982/1007` 零改动。
- **语义声明（UT 钉住）**：版本从"可 import 的版本"变为"已安装的版本"——torch_npu 装了但 import 坏时，旧 None → 新返回版本串。provenance 记录环境而言新语义更诚实（import 坏也是环境事实），但属显式变更。
- 注意：此向量位于 preflight→snapshot 的 F1 崩溃窗口内——只修 detect/slot 不修此处，主进程仍会被灌入 torch，maps 验收必失败。

### 3. 加载期 import 守卫（§1.3：不变式从文档变机器强制）

- `run` CLI 入口（单算子与 `--batch`/`--resume` 共用入口）安装 meta-path 守卫：主进程内 `import torch`/`import torch_npu` 即 **fail-fast**，报错文案指向本方案文档与"主进程纯 Python"不变式 + 逃生门 `DEVKIT_ALLOW_INPROC_TORCH=1`（应急用，报错文案提示该路径不受不变式保护）。
- 守卫只装在编排主进程入口；探测/smoke/run-cases 等**子进程**是全新解释器，不受影响（其内 import 合法且必要）。
- 目的：本修复收口三向量后，未来新增进程内 import（如本次 provenance 的漏网形态）由静默概率性崩溃（不可诊断）变为启动期确定性报错（§1.2 可诊断 + §1.3 加载期校验）。

### 4. `src/ascendc_devkit/application/batch_runner.py` — 遗言进 run.log

- L508-509：`_log.exception("dispatch failed for %s", ...)` → 引擎 `Logger.error(f"dispatch failed for {tr.get('op_dir')}", exc_info=True)`（`Logger._emit_traceback` 已支持 exc_info 形态，进 run.log + 控制台双写）。
- L502-503：`_log.info("[integrity] dispatch-enter tr keys=...")` 同理换 `Logger.info`（同一观测缺口）。

### 5. `src/ascendc_devkit/application/dispatcher.py` — 探针升级（验证期弹药）

- `_log_state_integrity`（L197-215）缺失分支补 `keys={sorted(d.keys())}`——修复后如仍复发，直接点名塌缩后字典的键归属。

### 6. 收尾（验证达标后，单列）

- 删除 state-integrity 四点位 + `[integrity] dispatch-enter` 埋点（0827/0828 注释承诺）。**import 守卫保留**（它是长期不变式强制，不是诊断埋点）。
- stage 执行期 in-process import 向量清点（见验证 2 的全程采样结果处置）。

## 验证

1. **UT**（TDD，先写用例）：
   - detect：短路路径（torch_npu 已在 sys.modules → 进程内直查）/ 子进程路径成功/超时/非零退出 / 缓存命中+双检锁防并发重复 spawn（mock `subprocess.run`）；`detect_chip_version` 超时仍抛 `EnvironmentProbeTimeout`（语义回归）；主进程路径断言 torch_npu 始终未进 `sys.modules`。
   - slot/provenance：env → npu-smi 子进程 →（slot 默认 8 / provenance None）优先序 + npu-smi 物理卡 vs device_count 可见卡的**语义声明断言**（mock 子进程输出）；provenance 版本走 `importlib.metadata`（mock 元数据，含"已装但 import 坏"场景）。
   - 守卫：主进程 import torch/torch_npu → 启动期确定性报错（含逃生门 env 生效路径）。
   - batch_runner：dispatch 抛异常时 run.log 内出现 traceback（临时 bind_run_log 捕获）。
2. **不变量硬验收（全程采样，非仅 dispatch 早期）**：真跑 `ascendc-devkit run --batch <manifest>`（芯片不显式指定），**整个运行期**周期采样 `/proc/<pid>/maps`：`grep -c 'Ascend|torch'` == 0、线程数 Python 侧规模。若**晚期**（stage 执行期）出现映射 → 即为 stage 期漏网向量（如 perf/integrate 主进程路径），按同模式补收口后重验——这是方案边界内显式的一步，不是验收失败。
3. **实测批判据（heavy_llm，执行前需用户确认成本）**：`bash scripts/batch_self_evolve.sh`（默认 CHIP 未设）连跑 ≥2 批，全程零 exit 139、零 `state-integrity` 缺失行（探针退役前由它做守护）、exec run.log 不再出现"只剩一行 constructed"的 dispatch 期死亡。
4. **前置根因实证（可先做，一次性实验）**：stub-PYTHONPATH 遮蔽 torch_npu（临时 stub 模块 import 即 raise ImportError，prepend PYTHONPATH）跑批对照崩率——detect/provenance 走 except 退化为 UNKNOWN，行为可接受。**注意 `CHIP_VERSION` 旁路无效**：runtime probe 无条件执行（`dispatcher.py:583-588`，runtime 侧 probe authority），设 CHIP 只影响 design 字段。

## 归因置信边界（诚实声明）

根因链为**强证据 + 排除法**归因（maps 实证暴露面 + 时序吻合 + 机器既往病史 + 全静态排除 + 合成压测阴性），未直接捕获 CANN/torch_npu 写坏堆的那一次写（无可用 core dump）。方案的可证伪性是真实的：三向量收口 + 守卫 + 全程 maps 归零 + 崩率 2/3→0 实测对照；**若收口后批实测仍崩，则归因错误**，接棒定位弹药 = 探针 keys 升级（条目 5）+ 重新归因（sqlite/解释器等剩余候选）。

## 风险与边界

- 子进程探测耗时（torch_npu import ~数秒）：与现状持平（现在主进程同样要 import 7s），且缓存后整批只付一次；不阻塞 GIL；**子进程调用方零新增开销**（短路路径直查）。
- `--runtime_target_chip` 显式传入时 probe **仍会执行**（仅作超时兜底，`dispatcher.py:564-566` probe authority）——子进程化后该语义不变，只是探测成本移入子进程；`--design_target_chip` 只影响 design 字段，不触发/绕开探测。
- smoke/评测/精度等子进程链路本就子进程化，不受影响；本改动回收 dispatch 主进程的**三处**违规 import。
- 守卫误伤未来合法的主进程 torch 使用：报错文案直接指向本方案文档与逃生门 `DEVKIT_ALLOW_INPROC_TORCH=1`——若真出现合法场景，应先改方案再放行，逃生门只作应急（§1.3 精神：显式豁免优于静默例外）。
- npu-smi 物理卡 vs device_count 可见卡、provenance"已装 vs 可 import"两处语义变更：见各条目内声明，UT 钉住。

## 第五向量 As-built（step-106，2026-08-29）

- `infra/npu_probe.py` 单点落地：`npu_runtime_available()` 子进程 smoke 探测
  （语义与 dispatcher 原实现逐字一致）；dispatcher `_run_npu_smoke_subprocess`
  改为委托（调用点零变化）。
- perf.py:179 `_check_npu_available` → 子进程单点；不可用时 reason 进 WARN 日志
  （不再 except Exception 静默折 False）。
- perf.py:123 → `NPURunner.probe_free()`（类方法正式化 deploy 的 `__new__` 惯用法；
  探测字段 None=未知）。**实施期发现并修正语义缺口**：`execute()` 的可用性闸门
  消费 `_torch_npu_available` 真值——probe-free 缺省 False 会误报"NPU 缺失"；
  修正为三值语义（False=探测实证不可用→报缺；None=probe-free→跳过闸门，
  设备真值源=子进程 harness）。
- deploy `_build_smoke_harness` 手写 `__new__` 惯用法 → `probe_free()` 单点
  （§1.15）。
- UT：test_perf_probe_free（11：probe-free 构造/闸门三值语义/委托单点/超时与
  traceback 可诊断）+ test_import_guard 增 perf 面子进程纯度用例（含 execute
  编排入口零 torch）。
