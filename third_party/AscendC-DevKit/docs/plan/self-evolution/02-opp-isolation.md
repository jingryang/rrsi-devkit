# opp + whl 隔离方案 — 多算子并发评测（非侵入 cann-bench）

> **性质**：self-evolution 线工作记录（L3 方案分析），承接 `01-multi-op-isolation.md` §5.6 的 opp 隔离 open 问题。
> **时点声明**：事实基础来自对 cann-bench（外部只读）的代码核实；方案 A/D 未经端到端跑通验证，§6 列待验证项。
> **已定选型（2026-06-29）**：opp 走「A 起步 → D 升级，B 弃」；whl 隔离随 D（`pip --target` + `PYTHONPATH` + 进程隔离）。
> **纪律**：遵守 `plan-doc-discipline`（语义锚点不写行号、不维护现状快照、不照搬外部脚本、外部依赖只读、不引用会话临时文件）。

---

## 0. 问题

多算子并发评测时，cann-bench 的 install 装**两类全局资源**，多份独立提交并发 install 互踩：

- **opp**：run 包经 `install_run_package` → `--install-path=<opp>/vendors/custom_ops`（全局 CANN opp）
- **whl**：cann_bench 包经 `install_whl_package` → `pip install --no-deps`（全局 site-packages）

NPU 卡冲突已由 `--device-id` + 外层 `NPUSlotManager` 解决（见 `01` §3.2）；本文攻 opp + whl。

---

## 1. 事实基础（核实）

### 1.1 cann-bench build+install 绑死单进程 + 全局 opp

- `install_run_package` 用 `_detect_opp_path()` 定 install 目标；`_detect_opp_path()` 优先级 ① `ASCEND_OPP_PATH` ② `$ASCEND_HOME_PATH/opp` ③ `/usr/local/Ascend/opp`。
- **build.sh 编译 kernel 必需 `ASCEND_OPP_PATH`=真实 CANN opp**（找内置头文件）。build 与 install 同进程、`ASCEND_OPP_PATH` 不能中途切 → **单次 cann-bench 调用必然装到全局 CANN opp 的 `vendors/custom_ops/`**。
- 非侵入下无法让 cann-bench「编译用真实 opp、install 到 per-op 目录」——它是单进程绑定模型。

### 1.2 全量 opp 副本不可行；vendors 独立、其余可链接

- CANN opp 根 **7.9G**（`built-in/` 7.8G + `Ascend/` 151M + `lib64/` + 小文件），35 算子全量副本 = 276G，作废。
- 但 **`vendors/` 子目录当前空**（自定义算子才装这），其余子目录（`built-in/`/`Ascend/`/`lib64/`/小文件）全是只读内置 op → 可符号链接。这给「链接视图」留了可能。

### 1.3 cann-bench 原生单位 = 一份提交一批算子

- `csrc/ops/<op1>/<op2>/...` 共享**一次** build+install（aclnn_launch 样例含 add+sqrt 两算子佐证），批内算子**不互踩**；评测时 `OperatorMatcher` 按 snake_case 反查区分。
- **冲突只在「多份独立提交并发 install」时爆发**；一份提交内多算子不冲突。

### 1.4 `--skip-install` 是为外部 PYTHONPATH 暴露而设计

- `--skip-install`（cli.py，注释原话）「ST harness 使用此模式：先构建 golden candidate，**通过 PYTHONPATH 暴露**」→ 调用者负责把 cann_bench 准备在 PYTHONPATH 上，cann-bench 用 `prepare_skip_build()` 扫描已暴露的接口。
- 它跳过**整个** build+install（opp 和 whl 都不装），是 D 方案的原生支点。

### 1.5 whl 内容 = `_C.so`（pybind）

- `cann_bench` whl 含 `_C.so`（编译产物，`build_wheel.sh → setup.py bdist_wheel`）。`cann_bench/__init__.py` 是 `from . import _C`；`import cann_bench` 时 `_C.so` 执行 `TORCH_LIBRARY_FRAGMENT(cann_bench, m) m.def(...)` 注册 `torch.ops.cann_bench.<op>`，并 `dlopen` 对应算子的 opp `.so`（`libcust_opapi.so`，在 `ASCEND_CUSTOM_OPP_PATH`）。

---

## 2. 三方案

| 方案 | opp 隔离 | whl 隔离 | 流水线粒度 | 外层工作量 | cann-bench 复用 |
|---|---|---|---|---|---|
| **A 批量** | ✓（单实例不并发 install） | ✓（同上） | 粗（批内等齐） | 最低 | 全 |
| **B 链接视图** | ✓ | ✗ **whl 全局冲突** | 细 | 造 opp 根链接视图 | 全（但 whl 遗留） |
| **D 外层自管** | ✓ | ✓ | 细 | 调命令 + 设 env（非重写） | 评测（`--skip-install`） |

### 2.1 A 批量（cann-bench 原生，最简避坑）

N 算子打包**一份提交**（`csrc/ops/<op1..N>/`），一次 build+install+评测。单实例 → opp/whl 都不并发冲突。用**分批流水线**兼顾吞吐（每当 K 个算子生成完，打包一份提交评测，同时生成下一批）。K 是可调旋钮：K=1 退化为纯流水线（触发 opp/whl 隔离需求），K=∞ 退化为全批量。

代价：批内等齐（粗粒度）；整批编译是 all-or-nothing（一算子编译失败全批 0 分，cann-bench `build_packages` 设计）。

### 2.2 B 链接视图（per-op opp 视图，whl 遗留 → 不推荐）

每算子建独立 opp 根（per-op-dir）：`built-in/`/`Ascend/`/`lib64/`/小文件符号链接到真实 CANN opp，`vendors/` 独立。`ASCEND_OPP_PATH=per-op-dir` 让 cann-bench **完整跑**（build+install+评测），install 装 opp 到 per-op-dir/vendors/custom_ops。

**致命遗留**：cann-bench 完整流程仍 `install_whl_package`（全局 `pip install`）→ 多实例 whl 互踩。B 只隔离 opp 不隔离 whl。要补 whl 隔离就靠近 D，不如直接 D。

### 2.3 D 外层自管（opp + whl 全隔离，细粒度流水线，推荐升级目标）

cann-bench 只评测（`--skip-install`），build + install **外层接管**到 per-op：

```
① 外层 build:    ASCEND_OPP_PATH=真实CANN  bash <source-dir>/build.sh
                  → dist/cann_bench*.run（opp）+ dist/cann_bench*.whl（whl）
② 外层 install opp:  dist/cann_bench*.run --install-path=<per-op-opp-dir-X>
                  → 装 <per-op-opp-dir-X>/vendors/custom_ops（不碰全局 opp）
③ 外层 install whl:  pip install --target=<per-op-python-dir-X> dist/cann_bench*.whl
                  → _C.so 解到 per-op-python-dir-X（不碰全局 site-packages）
④ 评测:  PYTHONPATH=<per-op-python-dir-X>
         ASCEND_CUSTOM_OPP_PATH=<per-op-opp-dir-X>/vendors/custom_ops
         ASCEND_OPP_PATH=真实CANN
         run_evaluation.sh --skip-install --source-dir <source-dir> --device-id <slot>
```

外层是**调命令 + 设三阶段环境变量**，不重写 cann-bench 的编译/install 逻辑（build 用 source-dir 自带 build.sh，install 用 run 包自带 makeself，评测用 cann-bench `--skip-install`）。

---

## 3. D 的 whl 多算子隔离机制（三层）

冲突根源：`cann_bench` whl 同名，全局 `pip install` 互相覆盖；`_C.so` import 时注册 `torch.ops.cann_bench.<op>`。

隔离靠三层叠加：

1. **per-op 装载位置**：`pip install --target=<per-op-python-dir-X>`（解到独立目录，不全局）→ 算子 X 的 `_C.so` 在 `per-op-python-dir-X/cann_bench/`。
2. **per-op PYTHONPATH**：评测算子 X 的 cann-bench 进程（含其 ProcessPool 子进程）`PYTHONPATH=per-op-python-dir-X` → `import cann_bench` 只加载算子 X 的 `_C.so`。
3. **进程隔离（根本）**：`torch.ops.cann_bench` 命名空间是**进程私有**，不跨进程共享。每算子一个独立评测进程，各自注册到本进程的 `torch.ops.cann_bench` → 天然不冲突。

**关键**：不在 PYTHONPATH 本身，而在**每算子一个评测进程 + 该进程 PYTHONPATH 只指该算子**。`pip --target + PYTHONPATH` 只保证每个进程加载正确的 `_C.so`。

**成对约束**：`_C.so` import 时 `dlopen` 对应算子的 opp `.so`（`ASCEND_CUSTOM_OPP_PATH`）。故 per-op 的 `PYTHONPATH`（`_C.so`）必须与 per-op 的 `ASCEND_CUSTOM_OPP_PATH`（opp `.so`）**成对同属一算子**。D 的隔离单元 = `{per-op-python-dir, per-op-opp-dir, ASCEND_OPP_PATH=真实CANN, device-id}`。

---

## 4. 推荐：A 起步 → D 升级，B 弃

- **A 起步**：baseline 先证 loss 有信号，单实例批量最简、零隔离难题。分批流水线（K 可调）兼顾吞吐。
- **D 升级**：要细粒度流水线（K=1）时上 D，opp+whl 全隔离，外层调命令非重写，且 `--skip-install` + `pip --target` 是 cann-bench 原生支持路径。
- **B 弃**：whl 全局 install 遗留使其不如 D 干净；补 whl 即趋同 D。

---

## 5. 与 `01` 的关系

- NPU 卡隔离（`--device-id` + `NPUSlotManager`）见 `01` §3.2，已定。
- opp + whl 隔离见本文（A/D）。
- D 的隔离单元 = `01` §3.1 隔离单元的细化：`source-dir` + `per-op-opp-dir` + `per-op-python-dir` + `device-id` + 共享 `ASCEND_OPP_PATH=真实CANN`。
- python 侧选型（`pip --target` + `PYTHONPATH`，`01` §3.3）在 D 下由外层 `pip install --target` 落地，cann-bench 不碰全局 site-packages。

---

## 6. 待验证

1. **D 端到端**：`--skip-install` + 外层 `pip install --target` + `ASCEND_CUSTOM_OPP_PATH` 能否让 cann-bench 正确加载 per-op 算子（精度/性能跑通）。`--skip-install` 有 ST harness 先例，但 self-evolution 的 per-op 多实例并发场景未跑通。
2. **`_C.so` ↔ opp `.so` 配对**：`_C.so` import 时 dlopen opp `.so`，per-op 的 PYTHONPATH 与 ASCEND_CUSTOM_OPP_PATH 必须严格同算子配对，跨算子错配会 dlopen 失败。
3. **A 的批编译 all-or-nothing**：一份提交内一算子编译失败 → 全批 0 分（cann-bench `build_packages` 设计）。分批流水线的批大小 K 要权衡（大批省 install 次数但失败波及广）。
4. **`build.sh` 的 `--install-path` 可定制性**：D 步骤 ② 要求 run 包 `--install-path` 可指向任意 per-op-dir（makeself 标准支持，但 DevKit aclnn 产出的 build.sh 是否产出标准 run 包待布局适配阶段验证）。
