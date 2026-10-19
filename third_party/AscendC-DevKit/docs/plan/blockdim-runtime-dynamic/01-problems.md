# 设计期核数静态化 — 问题记录（L1）

> 纯事实快照（哪里坏了 / 凭什么这么说）。不提方案、不排顺序、不写决策。
> 触发：复盘 foreign run `20260722-022209-e08f46`（self_evolve_op / Exp 算子 / A5），
> 执行方反馈「设计阶段 hw_params.json 核数错误，导致 codegen 硬编码核数」。

---

## P1 — design 阶段把 hw_params 的核数字段当作 block_dim 字面上限钉死，codegen 继承为字面核数

### 现象（run 客观事实）

- run `20260722-022209-e08f46` 生成 Exp 算子（A5 / ascend950 / RegBase）。全 8 份 hw_params.json 一致输出
  `ai_core_cnt=8 / cube_core_cnt=8 / vector_core_cnt=16`，且 hw_params.json 内**无任何 chip / variant / source 标注**。
- tiling 阶段产物 `tiling/T0/tiling_split.json`：`split.block_dim = 8`；claim 明写
  「block_dim 上限 = ai_core_cnt = 8」；`source_pointer` 明指 `hw_params.json: ai_core_cnt=8`；
  anchor **主动否决** `block_dim=16`（vector_core_cnt），理由「以 ai_core_cnt 为界」。
- `integrate/kernel_architecture.json`：ComputeTiling「按 block_dim=8 计算 formerNumber/formerLength/tailLength」。
- codegen（ascendc-dev-s4-coding）会话日志中 `block_dim=8` 字面值出现 40+ 次；其推理文本已写明
  正确做法 `blockDim = min(GetCoreNumAiv(), totalLength)`（运行时动态），却被设计文档「权威 block_dim=8」盖过。

### 凭什么说是「核数被当静态约束」（传递链定位）

block_dim 的合法语义应是 **运行时按 `min(可用核数, ⌈totalLength/tileLength⌉)` 动态计算**（`GetCoreNumAiv()` 运行期取真实核数）。
本次 run 把它降级成「设计期字面常量 = `hw_params.ai_core_cnt`」：

- hw_params 侧：`ai_core_cnt=8` 是 A5 默认入门 variant 的值（见 P2），以「该机器真实核数」身份无标注流向下游。
- tiling 侧：tiling_split 把 `ai_core_cnt` 当 block_dim 上限 / 字面值钉死，`source_pointer` 直接指向 hw_params 核数字段。
- codegen 侧：继承该字面值写进 kernel / tiling；虽有动态 `SetBlockDim(usedCoreNum)` 路径，也存在读 TilingData 字面 blockNum 的路径，
  host 一旦按 design 值写死即失效。

### 为什么静态核数必然失效（根因维度）

- design target 是**代际级**（A5），不是 SKU 级；A5 代际内核数跨 **8 / 28 / 32 / 36** 四档（共 21 个 variant）。
  设计期根本不知最终部署到哪个 SKU，故用任何固定核数钉 block_dim，换 SKU 即失效。
- 跨代际设计（如 A2 机器设计 A5 算子）合法：hw_params 按 design target 代际加载（`build_hardware_target(chip=design_chip)`，非 runtime 机器），
  进一步说明 runtime 探测核数与 design 期 block_dim 无关。

→ 一句话：**block_dim 不该读 hw_params 的任何核数字段，必须运行时 `GetCoreNumAiv()` 动态**。

---

## P2 — hw_params 默认 variant 选入门款，设计期核数系统性偏低

### 现象

- `run_context._DEFAULT_VARIANT` 三代际默认值全为 entry / 入门档：
  - A5 → `910_950z`（注释「entry 8-cube SKU」）= 8/8/16
  - A2 → `910B3`
  - A3 → `910_9362`（注释「entry 20-cube/40-vector SKU」）
- 探测拿不到具体 SKU 时（torch_npu 不可用 / device_name 无子型号 / 探测超时），
  hw_params 静默套用该默认 variant 的核数，**无标注「这是默认占位、非探测真值」**。

### 凭什么说「950z 非典型、默认值偏低」

- A5 spec（ascend_910_95xx.json）variant 按核数归 4 档：
  - 8-core：仅 `910_950z` 一个（入门）
  - 28-core：`910_957x`（10 个）
  - 32-core：`910_958x`（8 个）
  - 36-core：`910_959x`（3 个）
- 实测对照（同项目组环境）：`torch_npu.get_device_name(0)` = `Ascend950DT_9582`，
  对应 spec variant `910_9582` = 32/32/64。hw_params 却给 950z 的 8/8/16 → **低估 4 倍**。
- 即 P1 的字面 `8` 并非探测真值，而是「探测拿不到 SKU → 套入门款默认」的产物。

### P1 与 P2 的关系

P2 供给错误的核数字面值（入门款 8），P1 把它钉进 block_dim。即便 P2 给了「正确」核数，
P1 的静态化机制仍会在代际内换 SKU 时失效——故 **P1 是根因，P2 是放大器**。

---

## 附带观测（非本次范围，记以待查）

- PROVENANCE `detected_chip=null / soc_version=null / driver=null`（env 探测口径）与
  events `chip_decision: runtime_chip=A5, source=probe, mismatch=false`（dispatch 探测口径）**不一致**——
  两套探针各自维护、结果矛盾。非核数硬编码根因，本次不修，留作 follow-up。
