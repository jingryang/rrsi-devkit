# unique 新 run 507035 未定位 + 可选输出契约复发 — L1 问题记录

> 层级：**L1 / 问题记录**。只陈述「哪里坏了、凭什么这么说」（证据 / 现象 / 根因事实 / 产权）。
> **不提方案、不排顺序、不写决策**（§1.8 L1 产权）。方案分析见后续 `02-analysis.md`（L3）。
>
> 记录者：Claude（交互会话内复盘）。日期：2026-08-17。

## 证据来源

- **算子**：`unique`（cann-bench level3，AscendC，self_evolve_op 流水线）
- **运行**：`output/20260816-163138-37a5a9/20260816-163138-e26179/`（单算子 resume 跑，方案 A+C 落地后的首次端到端）
- **最终评分**（cannbench_eval）：`overall=5.00 compile=2.00 func=3.00 perf=0.00 pass_rate=10.00%`
- **评测明细**（`cann-bench-batch/20260817_003121/unique/reports/unique_eval_20260817_202024.json`）：
  2 success（`unique_2`/`unique_4`）、5 failed（`unique_1/3/5/6/7`）、13 cascade（`unique_8~20`）
- **precision_debug 终值**：`control.json` best_commit=`866bd43`、best_passed_count=5、failed_case_queue 12 条
- **kernel 源码**：`cann-bench-batch/20260817_003121/unique/examples/aclnn_launch_example/csrc/ops/unique/`

## 背景事实（供各问题引用，非问题本身）

- **算子语义**：`y, inverse = unique(x, return_inverse)`。`y`（REQUIRED，唯一值），`inverse`（OPTIONAL，`return_inverse=true` 才返回）。
- **本 run 是新 kernel**：方案 A（docgen 独立成段）+ C（定向 respawn）落地后，codegen 重新生成的 kernel 是**向量化 radix 实现**（非旧 run 的单核标量 O(n²)），因而暴露出**新的失败模式**——与旧 RCA（`precision-debug-unique-3of20-rca`、`unique-codegen-scalar-collapse`）的根因（float 中转精度 / O(n²) 超时 / CPU 兜底）**完全不同**。
- **阶段时间线**（events.jsonl，UTC）：codegen ok → run_tests iter-0 0/20 全 507035 → bounds_check 修 SysWorkSpace → diagnose 多轮（DCache 一致性等）→ cannbench_eval。

---

## P1（严重 · 已坐实）：507035 MTE 地址越界在 SysWorkSpace 修复后仍存在，第二根因 = half→int32 Cast 用 CAST_NONE 静默留未初始化 slot

### 哪里坏了

run 初期 20/20 用例全崩 `507035`（vector core exception / MTE invalid GM address）。bounds_check 判定唯一 CRITICAL 为「SysWorkSpace：ws[0] 仅含 userWs 未叠加系统 workspace」，并机械修复（`ws[0] = userWs + 16MB`）。但**最终 cannbench_eval 仍然 507035**（5 failed + 13 cascade），且评测所用的 kernel 已包含该 SysWorkSpace 修复。即：SysWorkSpace 修复**不足以消除 507035**，还存在一个未被 bounds_check / diagnose 定位的第二根因。

### 凭什么这么说（证据）

1. **run 初期全崩**（`run_tests_iter-0/result.json` + debug report iteration 0）：
   「全量 20 case 均报 RuntimeError ACL stream synchronize failed 507035（vector core exception, MTE invalid GM address）」；`outcome: failure_type=runtime, failed_count=20/20`。

2. **bounds_check 判定 + 修复**（`phases/bounds_check/precision_bounds_check.json`，`fixes[0]`）：
   - `approach: "SysWorkSpace 模板修复：op_host/unique_tiling.cpp GetWorkspaceSizes(1) 的 ws[0] = userWs + 16MB 系统 workspace（SYS_WORKSPACE_SIZE=16*1024*1024 写死，rule 7）"`
   - `pre_critical: 20`、`post_critical: 0`、`shadow_recheck_passed: true`、`redeploy_passed: true`、`commit_sha: dd7a755`
   - 即 bounds_check 认为「20 个 CRITICAL 全是 SysWorkSpace，修完归零」。

3. **评测 kernel 已含该修复，但仍 507035**：
   - 评测 source_dir（`run.log:6091`）= `cann-bench-batch/20260817_003121/unique/examples/aclnn_launch_example/csrc/ops/unique`，其 `op_host/unique_tiling.cpp:174-175` 现为：
     ```cpp
     static constexpr size_t SYS_WORKSPACE_SIZE = 16 * 1024 * 1024;   // 系统 workspace 预占（A2 写死 16MB）
     currentWorkspace[0] = static_cast<size_t>(userWs) + SYS_WORKSPACE_SIZE;
     ```
   - 最终 eval 结果（`run.log:6112` + eval report）：`overall=5.00 func=3.00 pass_rate=10%`；`unique_1/3/5/6/7` status=failed，stderr 明确 `runtime result = 507035`（`subprocess/cannbench_eval_unique.stderr.log`）。

4. **diagnose 的根因判定指向「数据错」而非「地址错」，未覆盖 507035**：
   - 最终 `phases/diagnose/precision_diagnose.json` root_cause：「GlobalTensor::SetValue 标量 GM 写只落各核私有 DCache … 跨核 GetValue 与 host DMA 读到旧值 → 排序键全零 → K=0 → y 空」；残留 `H6-scatter-cacheline-pad`（散射 dest 段跨核 64B CacheLine 边界覆盖丢 pair）。
   - 这些修复（commit `27823ae`/`866bd43`：WsFlush + 64B 段隔离 + 主序遍历）把 best_passed_count 抬到 5，但 **diagnose 关注的症状是「数据错」（K=0/y 空），不是 507035 的「地址错」（MTE 越界）**——二者性质不同。

### 根因（事实陈述）

507035 = MTE（Memory Transfer Engine）访问非法 GM 地址，属**地址越界**类崩溃，与 DCache 一致性导致的**数据错**（K=0/y 空，不崩溃）是两类性质。现有证据只坐实了一个 507035 来源（SysWorkSpace 未叠加，已修），但修复后 507035 仍在 5 个 case 上出现，说明存在**第二个 MTE 地址越界来源**（如某 tiling offset 算错 / 散射段 strided 写越界 / 某 shape 下 workspace 仍不足），该来源未被 bounds_check 的 shadow 检查（判 post_critical=0）和 diagnose 的静态诊断（转向 DCache 数据错）定位到。

### 根因（已定位 · 待评测坐实）：`half→int32` Cast 用 `CAST_NONE` 在 A2 是 unsupported，静默留未初始化 slot → 数据错 K=1 与 507035 同源

**关键事实（编译期硬证据，dav_c220 / ascend910b）**：

1. **8bit→32bit 无直连 Cast**：`dav_c220/kernel_operator_vec_vconv_impl.h` 的 `CastIntrinsicsImpl` 重载全集里，`int8_t`/`uint8_t` 作 src 的仅 `half* dst`（第 37/53 行），`int32_t* dst` 的仅 `half* src`/`float* src`/`bfloat16_t* src`/`int64_t* src`（第 124/280/546/711 行）——**不存在 `int8_t/uint8_t → int32_t/uint32_t` 重载**。codegen 生成的 `Cast(slotI32, xLocal, CAST_NONE)`（int8→int32）编译即报 `no matching function for call to 'CastIntrinsicsImpl'`（`unique_build11.log`）。→ 必须 **half 中转**。

2. **half→int32 的 `CAST_NONE` 是 unsupported，release 下静默留垃圾**：同一头文件第 124-162 行，`CastIntrinsicsImpl(int32_t* dst, half* src, roundMode, ...)` 的 switch 里 `CAST_NONE` / `CAST_ODD` 分支是 `ASCENDC_DEBUG_ASSERT(false, ...)`；而 `kernel_log.h` 在 **无 `ASCENDC_DEBUG` 的 release 构建下 `ASCENDC_DEBUG_ASSERT(...)` 展开为空**（第 425 行）→ 该方向啥也不写，`dst`（slotI32 / invI32）**保持未初始化**。支持的是 `CAST_RINT`（`vconv_f162s32r`，round-to-nearest）。

3. **未初始化 slot 的内容随 UB 历史状态/时序变** → 同一 bug 两种表象：
   - UB 恰好为 0 → `slot=0` → `grp=slot>>5=0`、`bit=0` → 所有元素打 `presence[0]` 的同一 bit → **K=1**（数据错，不崩）。
   - UB 为垃圾 → `grp=slot>>5` 巨大 → `presence.SetValue(grp, ...)` / `presence.GetValue(grp)` 越界读写 → 下游 K/rankTable 污染 → **GM MTE 越界（507035）**。printf 改变时序 → UB 历史状态变 → 崩溃消失，正好解释此前「printf 让 507035 消失」的 Heisenbug 现象。

**已评测坐实**（2026-08-18 重跑，`reports/cann_correctness_eval_20260818_143031.json`）：修复 `CAST_NONE→CAST_RINT` + `-> Tensor[]`（P2）后，**507035 全部消失**（`cascade_cases: 0`，此前 13）、**y 全部 exact match**（含 int8/uint8）、**无「输出数量不匹配」**、`passed 18/20`（此前 2/20，`pass_rate 0.1→0.9`）。第 3 点「K=1 与 507035 同源」成立：同一 `CAST_NONE` 根因，UB 残留态为 0 → K=1，为垃圾 → presence 越界 → 507035。残留 2 例失败为**新的独立缺陷**（见 P3：int8/uint8 的 inverse 稀疏 mismatch，非本根因）。

**附带发现（同源缺陷）**：`PhaseInverse` 内 `Cast(invI32, invF16, CAST_NONE)`（原第 330 行）是同一 `half→int32 CAST_NONE` 缺陷；另有 `MarkPresenceImpl` 的 bit 提取 `(slot<<27)>>27` 依赖 int32 向量**算术右移**（`ShiftRight.md` 功能说明：有符号类型执行算术右移），slot bit4=1 时符号扩展出错——均已随本修复一并改为标量位移。

### 连带暴露（事实，非本文 P，供后续引用）

- bounds_check 的 `shadow_recheck_passed=true` 与真实评测 507035 **相矛盾**——shadow 影子脚本的「越界检查」覆盖不了真实 kernel 的全部 MTE 访问路径，存在**假阴性**（判无越界实则有越界）。
- diagnose 把「地址错（507035）」与「数据错（DCache）」混在同一 case 的诊断里，未显式区分「崩溃 vs 数值错误」两类失败模式，导致地址越界根因被 DCache 修复的进展**掩盖**。

### 产权

507035 第二根因的定位职责：precision_debug 的 bounds_check（shadow 越界检查覆盖度）+ diagnose（症状分类是否区分「崩溃 vs 数值错」）。根因本身属 codegen 产物（kernel 某处 MTE 越界访问）。

---

## P2（中等 · 复发）：return_inverse 可选输出在「生产层」恒二元组未消除，旧修复只兜在「消费层」，新 codegen 复发

### 哪里坏了

`unique` 是条件输出算子：`return_inverse=false` 时 golden 返回单张量 `y`，`true` 时返回 `(y, inverse)`。但 codegen 生成的 plugin 把签名固定为二元组（`return_inverse=false` 时返回空占位 tensor 而非 None）。旧 run（20260807）已记录此缺陷（`unique-codegen-scalar-collapse` P5/P7），且当时的修复全部落在**消费层**（harness 检测/对齐），**没有消除生产层（plugin 生成）的恒二元组**。本 run codegen 重新生成 plugin，恒二元组复发；因 P1 的 507035 崩溃在前，输出数量不匹配**尚未显式暴露**，属被掩盖的潜在缺陷。

### 凭什么这么说（证据）

1. **旧修复落在消费层、未动生产层**（`unique-codegen-scalar-collapse/01-problems.md` P7 已记录）：
   - P7-1 `_harness_template.py` 空 verdicts → raise（数量不匹配 → case error）；P7-2 `judge_case_details` 查 case 级 error。
   - `_normalize_outputs`（devkit harness）golden/kernel 输出右补/裁剪对齐。
   - 上述都在 devkit harness / 适配层**兜住**，plugin 恒二元组这一生产层根因（P5）未被改。

2. **本 run plugin 仍恒二元组**（smoke_probe 证据，`run.log:6079`）：
   - `output_comparisons` 含 `output_index: 0`（dtype float16，kernel 有值）+ `output_index: 1`（dtype 空，kernel_first10=[]）—— kernel 恒返回 2 个输出，inverse 为空占位。
   - 同条记录 `golden_used: false`、`bottleneck: smoke_callable_only`、`smoke_probe: true` —— 探测阶段未跑 golden，故数量不匹配未比对。

3. **本 run 未显式暴露（被 507035 掩盖）**：
   - 最终 eval failed 的 `unique_1/3/5/6/7` 是 507035 崩溃（stderr 实证），崩溃发生在输出对比之前；`unique_8~20` 全部 cascade。
   - 即「输出数量不匹配」这条缺陷在真实评测里**还没走到**，被 507035 先行阻断。

### 根因（事实陈述）

条件输出算子的「生产层（plugin 注册/返回）」与「消费层（harness 对比）」之间，缺少一个**从 schema/proto 的 OPTIONAL 语义到 plugin 返回值数量的构造性对齐**。旧修复（P7-1/P7-2 + `_normalize_outputs`）只在消费层做运行时兜底/对齐，每次 codegen 重新生成 plugin 时恒二元组复发——生产层根因未消除，消费层兜底是治标。

### 产权

plugin 生成路径（codegen + `ascendc-op-dev-coding` skill op_plugin 部分）：应让 plugin 按 schema OPTIONAL 语义返回（false 时单张量或真 None），而非恒二元组 + 空占位。消费层兜底（harness `_normalize_outputs`）是防御性补偿，非根治。

---

## P3（中等 · 已定位已修复）：int8/uint8 的 inverse 稀疏 mismatch（max_diff=255），根因 = count 型 Compare/Select 的 256B 对齐要求被尾块违反

### 哪里坏了

P1/P2 修复重跑后（`cann_correctness_eval_20260818_143031.json`），20 例中 18 过、2 例失败，均为 **int8/uint8 且 return_inverse=true** 的稀疏 inverse mismatch：

- `unique_10`（int8）：`int8[y] ✅ exact match`，`int64[inverse] ❌ mismatch=1825/49691433 (0.00%) max_diff=255`。
- `unique_6`（uint8）：`uint8[y] ✅ exact match`，`int64[inverse] ❌ mismatch=4081/268435456 (0.00%) max_diff=255`。

即 y（唯一值）与 K 全对（P1 修复见效），但 **inverse（每个元素的秩）在极少数元素上错**，误差幅度恒为 255。

### 凭什么这么说（证据）

- 两例都是**大 N**（int8 N≈4.97e7、uint8 N≈2.68e8），错元素占比 0.00%（千/亿级），`max_diff=255` 恒定。
- y 精确 → presence 位图、K、rankTable（PhaseMergeScan 标量构建）都正确；inverse 走 **PhaseInverse 的向量 Compare+Select 路径**（逐存在槽 s：`Compare(cmpMask, slotF16, s, EQ)` + `Select(invF16, cmpMask, rankF16, invF16)`），与 y 的标量路径不同。
- `max_diff=255` 且稀疏：疑似 Compare/Select 向量路径对**特定槽/特定 mask 边界**的偶发误选（rank ∈ [0,255]，错 255 = 秩 0↔255 互换量级）。

### 根因（事实陈述 · 已定位坐实）

**count 型 `Compare`/`Select`（`VSEL_TENSOR_TENSOR_MODE`）的 256 字节对齐要求被尾块违反**：

1. **硬证据（知识库 `Compare.md`）**：Compare 的 dst 是**打包 mask**（"将 uint8_t 数据按 bit 位展开，由左至右依次表征比较结果"——1 bit/元素、8 元素/字节）；`count` 参数约束 "**设置 count 时，需要保证 count 个元素所占空间 256 字节对齐**"。
2. **失效点**：`PhaseInverse` 的 `Compare`/`Select`/`Duplicate` 用 `count = len`；尾块 `len = tailLen_`（如 perCoreElems=6667 时）**非 128 的整数倍**（half：128 元素=256B），末段部分 chunk（`len % 128`，如 11 元素）的打包 mask 被 `set_cmpmask` 消费时错位/丢弃 → 该段元素的 `invF16` 从未被任何槽 Select 命中，残留初始 `Duplicate(..., 0)` 的 0。
3. **实锤（本地复现，`torch.ops.cann_bench.unique` 直调）**：错元素是**连续块**、每块恰为 `perCoreElems % 128` 个（N=100000 → perCoreElems=6667 → 11 元素/核，14 核×11 + 尾核×6 = 160 = 实测 mismatch）、块内 `inv_got=0`、`inv_ref` 为各自真实 slot（含 255 → 解释 `max_diff=255`）；且 `mismatch` 随 N 变化、与 `sum(perCoreElems % 128)` 精确吻合。y 走标量路径（PhaseEmitY）不受影响，故 y exact、inverse 才错。
4. **修复**：`PhaseInverse` 内 `lenAligned = ((len+127)/128)*128`，所有向量 op（Cast/Adds/Duplicate/Compare/Select/Cast）改用 `lenAligned`，`CopyOutInv` 仍按 `len` 短写（填充段不写回）。修复后重跑 20/20（`pass_rate 1.0`，`unique_6` uint8 / `unique_10` int8 的 `int64[inverse]` 均 exact match）。

### 产权

codegen 产物（bitmap kernel 的 PhaseInverse 向量路径）。属 P1 修复后新暴露的独立缺陷，不否定 P1 根因定位。

---

## 问题汇总矩阵

| 问题 | 严重度 | 性质 | 核心锚点 | 产权 |
|------|-------|------|---------|------|
| P1 507035 在 SysWorkSpace 修复后仍存在，第二根因 = half→int32 Cast 用 CAST_NONE 静默留未初始化 slot | 严重 | GM 地址越界（MTE）第二来源 = `MarkPresenceImpl`/`PhaseInverse` 的 `Cast(int32,half,CAST_NONE)` unsupported → slot 未初始化 → presence 越界 | `unique_tiling.cpp:174-175` 已含 SysWorkSpace 修复，eval 仍 507035；`unique.h` Cast 头文件硬证据 | codegen 产物（kernel Cast round-mode 选错） |
| P2 return_inverse 可选输出生产层恒二元组未消除，复发 | 中等 | 消费层兜底、生产层根因未改，新 codegen 复发 | smoke_probe `output_index:1` 空占位；旧 P5/P7 消费层修复 | codegen plugin 生成路径 |
| P3 int8/uint8 inverse 稀疏 mismatch（max_diff=255） | 中等 | P1 修复后新暴露，根因 = count 型 Compare/Select 256B 对齐被尾块违反（len%128 部分 chunk mask 错位） | `unique_10` int8、`unique_6` uint8，错块恰 = perCoreElems%128；已修（lenAligned 对齐）20/20 | codegen bitmap kernel PhaseInverse 向量 Compare+Select 路径 |

## 与既有工作的关系（避免重复产权）

- **`unique-codegen-scalar-collapse` P5/P7**：旧 run（20260807）的 optional 输出契约 + harness 假绿洞。本 P2 是其**生产层根因未消除的复发**——旧 P7 修消费层检测/对齐，本 P2 指出生产层（plugin 生成）恒二元组未改、新 codegen 复发。
- **`precision-debug-unique-3of20-rca`**：旧 run（20260805）的 float 中转精度 + printf 假 abort。与本 P1/P2 根因**无关**（旧 kernel 已废弃）。
- **`gm-workspace-sysworkspace-contract`（memory）**：ws[0] 必须含 GetLibApiWorkSpaceSize() 的铁律 + 507015 实证。本 P1 是其**新变体**：SysWorkSpace 修复（写死 16MB）后 507035 仍在，说明 SysWorkSpace 不是充分根因，另有一个 MTE 越界来源。
- **`cannbench-eval-crash-cascade-zero-score`（memory）**：单 case 崩 → 后续 cascade。本 P1 的 13 cascade 是同一机制的表现。

## 变更记录

| 日期 | 内容 |
|------|------|
| 2026-08-17 | 初版：基于 `20260816-163138-e26179`（unique）记录 P1（507035 未定位）+ P2（可选输出复发）。 |
| 2026-08-18 | P1 第二根因定位：`MarkPresenceImpl`/`PhaseInverse` 的 `Cast(int32,half,CAST_NONE)` 在 A2 unsupported（release 下静默留未初始化 slot），编译期硬证据（dav_c220 CastIntrinsicsImpl 重载全集 + ASCENDC_DEBUG_ASSERT 空展开）；统一解释 K=1（UB 为 0）与 507035（UB 为垃圾 → presence 越界），并修附带的 int32 算术右移符号扩展缺陷。待评测坐实。 |
| 2026-08-18 | 评测坐实 P1 + 记录 P3：重跑 `cann_correctness_eval_20260818_143031`，507035 全消（cascade 13→0）、y 全 exact、无输出数量不匹配、passed 2/20→18/20；新暴露 P3（int8/uint8 inverse 稀疏 mismatch max_diff=255）。 |
| 2026-08-18 | P3 定位坐实 + 修复：根因 = count 型 Compare/Select 的 256B 对齐要求被尾块违反（len%128 部分 chunk mask 错位 → inverse 残留 0），本地复现错块恰 = perCoreElems%128 实锤；修 `lenAligned` 对齐后重跑 `cann_correctness_eval_20260818_182429` 20/20（pass_rate 1.0）。 |
