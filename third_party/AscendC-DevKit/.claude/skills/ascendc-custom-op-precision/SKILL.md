---
name: ascendc-custom-op-precision
description: >
  对已编译出包的自定义算子进行 Kernel 级精度验证与调试。
  使用 KernelLaunch 工具在 NPU 上启动二进制 kernel，与 CPU Golden 对比定位精度问题。
  触发关键词：验证算子精度、精度调试、custom op precision、binary kernel、NPU 验证。
  适用条件：(1) 算子已完成编译出包；(2) 需要直接对 .o binary kernel 做 NPU 级验证；
  (3) 需要快速构造输入、调用 kernel、对比 NPU 输出与 CPU Golden；
  (4) 精度失败后需要系统化定位根因（流水同步 / Cast优化 / 数值错误 / OOB）。
---

# 自定义算子精度验证与调试

本 Skill 用于对**已编译出包**的自定义算子进行 Kernel 级精度验证。核心工具为 `skills/ascendc-custom-op-precision/KernelLaunch/`，它复用 TTK 内部模块（`binary_kernel_match`、`dyn_do_tiling`、`RTSInterface`），可直接从 Python 启动 NPU 上的二进制 kernel。

**精度调试的整体流程**：假设 `__simd_vf__` 和计算逻辑正确，简化流水和 VF 融合问题 → 排除流水问题 → 再逐步确认数据搬入、搬出和计算的问题 → 循环迭代。严格按照该流程进行，详见第 3 节。

**相关参考文档**：
- `skills/regbase-vf-test/references/ascend950_hardware_and_pipeline_control.md` — 流水线同步与 PipeBarrier
- `skills/regbase-vf-test/references/multi-dtype-numpy.md` — 多 dtype numpy 支持（dtype 构造、4-bit 打包、golden 比较）

---

## 1. 适用场景

- 算子已完成编译出包（如 `build.sh --pkg --soc=ascend950 --ops={op_name}`）。
- 需要跳过 PTA/ACL 层，直接验证 binary kernel 的 NPU 输出。
- 需要与 CPU Golden / PyTorch 标杆做精度对比。
- 需要定位越界、数据未写、数值偏差等问题。

## 2. 前置条件

### 2.1 编译并安装自定义算子包

#### ops-nn 仓
```bash
# 示例：ops-nn / ops-math 仓库
bash build.sh --pkg --soc=ascend950 --ops={op_name} -j40
```
编译完成后确保 `build/binary/` 路径下包含算子的 `.o` / `.json` 文件。

出包后使用如下指令进行安装
```bash
./build_out/cann-ops-nn-custom_linux-aarch64.run --install-path=${ASCEND_OPP_PATH}
```
### cannbench 仓
```bash
bash build.sh --soc=Ascend950
```

编译完成后安装自定义算子包：
```bash
./dist/cann_bench_*.run --install-path=${ASCEND_OPP_PATH}
```

### 2.2 环境变量

执行前必须设置：

```bash
source ${ASCEND_HOME_PATH}/bin/setenv.bash
source ${ASCEND_HOME_PATH}/opp/vendors/custom_nn/bin/set_env.bash
```

> `ASCEND_OPP_PATH` 指向 OPP 目录，KernelLaunch 通过 `binary_kernel_match` 在该路径下查找合法的 `.o` 文件。

### 2.3 检查 `ttk` 并确保 `KernelLaunch` 可用

`KernelLaunch` 依赖 `ttk`，先检查 `ttk` 是否存在，禁止主动安装。

```bash
python3 -m ttk info
```

`KernelLaunch` 在 `skills/ascendc-custom-op-precision/KernelLaunch` 中，确保可用：

```bash
python3 -c "from KernelLaunch import KernelLauncher; print('KernelLaunch OK')"
```

---

## 3. 精度失败调试流程（重点）

> **⚠ 本节流程为强制工作流，必须严格按步骤顺序执行，禁止跳步。**

整体思路：**简化问题 → 排除流水问题 → 逐步确认数值情况 → 循环迭代**。

```
精度失败
  │
  ├─ 第 0 步：流水简化关闭 double buffer，降低问题复杂度
  ├─ 第 1 步：上板精度测试 （不要定位具体原因，在后续步骤中分析具体原因）
  ├─ 第 2 步：camodel 仿真 + trace 分析，排除/修复流水问题
  │     └─ dynamic 编译自动关闭 VF 融合并生成简化 trace 与 VF 函数名标注；流水问题修复后回到第 1 步重新验证
  ├─ 第 3 步：DumpTensor / printf 逐步校验各阶段 LocalTensor 数值（不允许修改 VF 函数代码）
  │     └─ 定位到具体阶段后回到第 1 步重新验证
  ├─ 第 4 步：考虑其他错误可能（OOB / 分核 / tiling / VF 逻辑）
  └─ 第 5 步：重新开启 double buffer，进行精度测试
```

### 工作流规则（必读）

1. **禁止跳步**：必须从第 0 步开始，依次执行到当前问题对应的步骤。**必须先走完第 0~2 步**，用 camodel 的 trace 证据确认后再修改代码。
2. **每步必须实际执行**：不能仅凭代码审查就跳到修复，必须逐步确认问题。
3. **流水问题优先**：在第 2 步排除流水问题之前，不要插入 DumpTensor —— DumpTensor 的 PipeBarrier 效应会掩盖同步问题，导致误判。
4. **每次只改一个变量**：修复流水问题时不要同时改计算逻辑，反之亦然。


| 步骤 | 输入 | 动作 | 输出 / 进入下一步的条件 |
|------|------|------|------------------------|
| 第 0 步 | 原始 kernel 代码 | 改单 buffer → 编译安装 | 单 buffer 版本就绪 |
| 第 1 步 | 单 buffer 版本 | 上板精度测试 → 现象分类 | 初步判断精度状态 |
| 第 2 步 | 精度失败现象 | dynamic camodel 仿真 → 自动关闭 VF 融合 + 自动简化 trace + VF 标注 → 时序分析 | 流水正常 → 进入第 3 步；流水异常 → 修复 → 回第 2 步 |
| 第 3 步 | 流水已确认正常 | DumpTensor 二分定位 | 定位到出错阶段 → 修复 → 回第 1 步 |
| 第 4 步 | 以上均未定位 | 排查 OOB / 分核 / tiling / VF 逻辑 | 定位根因 → 修复 → 回第 1 步 |
| 第 5 步 | 精度全部正常 | 重新开启 double buffer | 重新进行精度测试 |

---

### 第 0 步：流水简化 —— 排除 double buffer

#### 0.0 为什么

- double buffer 会让两轮数据在流水上重叠，trace 里面会交叉出现数据搬入、计算和数据搬出，难以分辨数据搬入和计算的对应关系，以及计算与数据搬出的对应关系。**调试精度问题时，必须先用单 buffer 让每一轮的数据流在 trace 里清晰可辨**。

#### 关闭 double buffer

把所有 `TQue` 的 `pipe.InitBuffer(que, num, len)` 的第二个参数（buffer 数量）改成 1：

```cpp
// 修改前（double buffer）
pipe.InitBuffer(xQueue, BUFFER_NUM, size);

// 修改后（单 buffer，仅用于调试）
pipe.InitBuffer(xQueue, 1, size);
```

> **注意**：改的是 `InitBuffer` 的第二个实参，不是 `TQue<Pos, N>` 的模板参数 `N`。`InitBuffer` 的第二个参数才是控制实际分配 buffer 数量的参数。
>
> **仅针对 TQue**：`TBuf` 的 `InitBuffer(buf, size)` 没有 buffer 数量参数，无需修改。
>
> **仅需要修改 kernel 代码即可关闭 double buffer，无需关心 Tiling 侧代码**

修改后重新编译出包 + 安装。

> **调试完成后的恢复**：精度问题修复并通过验证后，应将 `InitBuffer` 的 buffer 数量恢复为原始值（如 `BUFFER_NUM`），重新编译出包 + 安装，以恢复 double buffer 的流水性能。

> **注意**：该修改不能在安装自定义算子包之前，必须在其之后。安装自定义算子包时会自动覆盖该文件导致配置失效。

---

### 第 1 步：上板精度测试

使用 `KernelLaunch` 在 NPU 上运行精度测试脚本，如果精度无误则直接返回。测试脚本的生成方法见第 4.2 节。

```bash
python3 {op_name}_precision_test.py --device_id 0
```

同时关注 OOB 检测结果：
- `OK`：正常。
- `FAIL`：发生越界或 output 数据未变，应优先排查地址/长度/偏移（跳到第 4 步）。

---

### 第 2 步：camodel 仿真 + trace 分析 —— 排除流水问题

#### 2.1 准备 camodel 测试

准备一份新的 `{op_name}_precision_test_camodel.py`，准备合适的 shape 和 dtype 的测试样例（**用小 shape**，camodel 仿真慢，小 shape 足以暴露流水问题）。脚本写法可参考第 4.2 节的模板，并加上 `--camodel` 参数。

**关键：使用 dynamic 编译模式**。在构造 `KernelLauncher` 时传入 `compile_mode="dynamic"`。dynamic 编译模式会**自动关闭 VF 融合**，且 camodel 仿真完成后 `generate_report()` 会**自动生成已简化的 trace**（`trace_core0_simplified.json`）并对 VF 事件标注函数名，**无需再手动调用 `simplify_cannsim_trace.py`**：

```python
launcher = KernelLauncher(
    "{op_name}",
    device_id=0,
    compile_mode="dynamic",
    camodel="CAMODEL",
)
```

| 参数 | 说明 |
|------|------|
| `compile_mode="dynamic"` | 通过 TBE 编译器动态编译算子（而非使用预编译 binary），可在运行时生成 kernel；dynamic 编译模式会自动关闭 VF 融合 |

通过 camodel 进行仿真：

```bash
python3 {op_name}_precision_test_camodel.py --camodel
```

camodel 仿真完成后，脚本中的 `generate_report()` + `annotate_camodel_trace()` 会自动在 `./kernel_meta/{op_name}/cannsim_report/` 目录生成：
- **`trace_core0_simplified.json`** —— 已简化的 Chrome Tracing 格式 trace，VF 事件已标注对应函数名（`vf_function` 字段）。

> **注意**：多次 camodel 仿真会覆盖同一目录下的 trace 文件。如需对比不同 dtype 的 trace，请先备份或重命名 `cannsim_report` 目录。

#### 2.2 分析简化后的 trace

简化版 trace 只保留四类关键流水事件（`pid` 标识流水线），为 Chrome Tracing JSON 格式：

| pid | 流水线 | 典型事件名 | 含义 | 对应代码 |
|-----|--------|-----------|------|---------|
| 4 | MTE2 | `MOV_SRC_TO_DST_ALIGNv2` | GM → UB 搬入 | `AscendC::DataCopyPad` / `AscendC::DataCopy`（搬入） |
| 10 | PUSHQ/VF | `VF` | Vector 计算 | `__simd_vf__` 调用；AscendC Vector API 也会编译为 VF （例如: `AscendC::Cast`、`AscendC::Duplicate`、`AscendC::Add`、`AscendC::ReduceSum`、`AscendC::SoftMax` 等） |
| 7 | MTE3 | `MOV_SRC_TO_DST_ALIGNv2` | UB → GM 搬出 | `AscendC::DataCopyPad` / `AscendC::DataCopy`（搬出） |
| 1 | SCALAR | `WAIT_FLAG_*` / `BAR` | Scalar 发射同步指令 | `AscendC::SetFlag / AscendC::WaitFlag`、`AscendC::PipeBarrier<>`（参考意义不大） |

> **注意：VF 本身是同步的，无需考虑 VF 之间的重叠。**
>
> **VF 函数名标注**：使用 `dynamic` 编译模式时，每个 `VF` 事件的 `args` 中会自动附带 `vf_function` 字段，标注该 VF 对应的源码函数名（如 `AddRmsNormCustomAddVF`、`Cast` 等），省去手动对照 PC 的步骤。

按以下流程分析 trace：

1. **确认目标 kernel**：trace 中可能有多个 `kernel_N`（B/E 对），对应测试脚本的不同 case。先确认当前分析的 kernel 与要调试的 shape/dtype 对应。

2. **统计各流水事件数量并与代码对照**：
   - MTE2 数量 = 实际执行的 GM→UB `AscendC::DataCopyPad`/`AscendC::DataCopy` 次数（**注意第一个 `MOV_SRC_TO_DST_ALIGNv2` 为搬运 `TilingData` 时触发，若没有 `TilingData` 则没有对应事件**）。
   - MTE3 数量 = 实际执行的 UB→GM `AscendC::DataCopyPad`/`AscendC::DataCopy` 次数。
   - VF 数量 = `__simd_vf__` 调用次数（完全符合）+ AscendC Vector API 调用（`AscendC::Cast`/`AscendC::Duplicate`/`AscendC::Add`/`AscendC::ReduceSum` 等，实际可能不完全匹配，取决于底层设计），可以参考 VF 事件注释的函数名称来推断。
   - 数量偏少：某段代码被编译器优化、条件分支未进入、或循环次数为 0。

3. **从代码建立数据依赖图**：trace 本身不标注「这条 VF 读了哪个 LocalTensor」，需结合代码——列出 CopyIn 每个 MTE2 搬入的 LocalTensor、Compute 每个 VF 的输入/输出 LocalTensor、CopyOut 每个 MTE3 搬出的 LocalTensor，标出生产者-消费者对（MTE2→VF、VF→MTE3）。

4. **验证时序约束**：对每一对有数据依赖的生产者-消费者，检查 `producer.end ≤ consumer.start`：
   - 读取某 LocalTensor 的 `VF.start` ≥ 搬入该 LocalTensor 的 `MTE2.end`。
   - 搬出某 LocalTensor 的 `MTE3.start` ≥ 产生该 LocalTensor 的 `VF.end`。
   - 无依赖的流水可以重叠，不要要求「所有 MTE2 结束后才开始 VF」。

5. **对比不同 dtype**：`AscendC::Cast(T→T)` 同类型转换会被编译器当作 no-op 优化掉，trace 里不会出现对应 VF（注意不是 `AscendC::Reg::Cast`）。若 fp32 算子的 VF 明显少于 bf16/fp16（少了 Cast 对应的 VF），数据可能停留在错误队列。建议结合多数据类型 trace 对比。

6. **检查循环轮数**：若代码有多轮 `LoopProcess`，trace 中应看到多组 MTE2→VF→MTE3。trace 只含 core0 数据，需结合 tiling/kernel 代码与 TilingData 实际内容分析核内情况。

**分析快速检查清单**：

- [ ] 已确认当前分析的 `kernel_N` 与目标 case 对应。
- [ ] MTE2 / MTE3 / VF 数量与代码预期一致。
- [ ] 每个有数据依赖的 MTE2→VF、VF→MTE3 满足 `producer.end ≤ consumer.start`。
- [ ] 已研究不同数据类型 trace 的差别。

#### 2.3 发现流水问题后修复

根据 trace 分析定位的异常，按下表确定根因与修复方向。
核心原则：**搬运与 Cast 不要混在同一阶段**——CopyIn 只做搬入并 EnQue，Cast 放到 Compute；CopyOut 先 DeQue 再搬出，全程走完整的 AllocTensor/EnQue/DeQue/FreeTensor 同步链。

**注意：VF 天生就是相互同步，不需要考虑 VF 之间的重叠**

| trace 异常 | 可能根因 | 修复方向 |
|-----------|---------|---------|
| `VF.start < 依赖的 MTE2.end` | MTE2→V 同步缺失；有依赖关系的数据搬入和数据使用处缺失同步，未走完整 AllocTensor/EnQue/DeQue/FreeTensor | 用 `TQue` 确保同步 |
| `MTE3.start < 依赖的 VF.end` | V→MTE3 同步缺失；有依赖关系的计算输出和数据搬出间缺少同步，未走完整 AllocTensor/EnQue/DeQue/FreeTensor | 用 `TQue` 确保同步 |
| Scalar 读到 VF 归约的旧值 | 缺少 V→S 同步 | 手动插入 `SetFlag<HardEvent::V_S>` / `WaitFlag<HardEvent::V_S>` |
| kernel hang 或只跑一轮 | AllocTensor/EnQue/DeQue/FreeTensor 没有完整实现，或匹配有误 | 检查每轮 AllocTensor/EnQue/DeQue/FreeTensor 是否配对 |
| MTE2/MTE3 数量与代码预期不符 | 某次搬运被优化、分支未走到或循环未执行 | 对照代码路径与 trace 逐一核对 |

> 参考 `skills/regbase-vf-test/references/ascend950_hardware_and_pipeline_control.md` 理解流水同步机制。

**修复后重新编译出包 + 安装，回到第 1 步重新验证**。确保流水不存在问题后，再进行后续代码分析。

#### 2.4 camodel 仿真严禁使用 `AscendC::DumpTensor` / `AscendC::printf`

`AscendC::DumpTensor` / `AscendC::printf` 本身会影响流水，并引入其他逻辑，干扰对当前 kernel 流水的分析。

---

### 第 3 步：DumpTensor / printf 逐步校验数值

在排除流水问题后（trace 确认时序正确），如果精度仍然失败，需要在 kernel 内部逐步校验各阶段 `LocalTensor` 的数值，但是不能修改 `__simd_vf__` 函数。

#### 前提

进入本 skill 调试时，`__simd_vf__` 函数已经经过 VF 单元测试，可以认为其大概率没有错误。因此调试的重点应关注**计算流程（搬入 → 计算 → 搬出）中各部分 LocalTensor 数据是否符合预期**，而非 VF 内部逻辑。

#### 方法：在 kernel 内插入 DumpTensor / printf

在算子源码中插入 `AscendC::DumpTensor` 或 `AscendC::printf`，逐步定位数据在哪一步出错：

```cpp
// 1. 数据搬入后：检查数据被正确搬入
LocalTensor<float> xLocal = inQueueX.DeQue<float>();
AscendC::DumpTensor(xLocal, 100, 32);   // desc=100 表示输入阶段

// 2. 计算逻辑前后：检查给计算逻辑的输入和计算结果
AscendC::DumpTensor(x1Fp32Local, 200, 32);  // 计算前
AddRmsNormCustomAddVF(xUb, x1Ub, x2Ub, ...);
AscendC::DumpTensor(xLocal, 210, 32);        // 计算后

// 3. 数据搬出之前：检查数据是否被正确搬出
AscendC::DumpTensor(yLocal, 300, 32);   // desc=300 表示输出阶段
```

#### desc 编号规范

| 范围 | 阶段 |
|------|------|
| 100-199 | 搬入后（CopyIn 输出） |
| 200-299 | 计算中间值（Compute 各步骤） |
| 300-399 | 搬出前（CopyOut 输入） |

#### 配合测试脚本定位

可以在测试脚本中控制输入内容（如使用固定值而非随机值），或打印输入内容，与 kernel 中的 DumpTensor 输出对比：

```python
# 测试脚本中打印输入
print(f"[INPUT] x1[0:8] = {x1.flatten()[:8]}")

# kernel 中 printf 对应位置
AscendC::printf("[DUMP-100] xLocal[0] = %f\n", xLocal.GetValue(0));
```

#### 重要注意事项

- 插入 DumpTensor / printf 后需要**重新编译出包**（`bash build.sh --pkg --soc=ascend950 --ops={op_name}`）。
- **DumpTensor 本身会产生 `PipeBarrier<PIPE_ALL>` 的效果**——它会强制等待所有流水完成。因此插入 DumpTensor 可能让精度"假性恢复"（因为屏蔽了同步问题）。如果插入 DumpTensor 后精度变好了，**不要急着认为问题解决了**，先确认是数值问题还是同步问题被 DumpTensor 的屏障效应掩盖了。
- 采用**二分法**逐步缩小范围：先在搬入后和搬出前各加一个 DumpTensor，确认问题在前半段还是后半段，再逐步细化。

**定位到具体阶段后，修复代码，重新编译出包 + 安装，回到第 1 步重新验证**。

---

### 第 4 步：考虑其他错误可能

如果流水和数值都确认正常，但精度仍然失败，考虑以下方向：

#### 4.1 OOB（越界）

OOB check 报 FAIL 时，优先排查：
- output / workspace 的地址、长度、偏移是否计算正确
- GM 偏移公式是否与 tiling 的分核逻辑一致
- UB buffer 大小是否小于实际写入量

#### 4.2 分核 / tiling 问题

- 检查 `GetBlockIdx()` 分核后 GM 偏移是否正确，各核处理的数据范围是否重叠或遗漏
- 检查 tiling 的 `rowsPerCore` / `tailRows` / `batchRows` 计算是否正确
- 多核不一致时，检查尾核（`blockIdx == coreNum_ - 1`）的处理行数

#### 4.3 同步问题（用 PipeBarrier 临时验证）

在可疑位置插入 `PipeBarrier<PIPE_ALL>`，如果精度恢复，说明是同步问题：

```cpp
// 在搬入和计算之间、或计算和搬出之间插入
PipeBarrier<PIPE_ALL>();
```

确认是同步问题后，再用精确的 `SetFlag/WaitFlag` 或 TQue 的 EnQue/DeQue 替换 PipeBarrier。

> 参考 `skills/regbase-vf-test/references/ascend950_hardware_and_pipeline_control.md` 理解流水同步机制。

#### 4.4 VF 函数逻辑问题

如果以上都排除，回归检查 `__simd_vf__` 函数的内部逻辑：
- mask 处理（UpdateMask / StoreAlign 的 mask 是否正确）
- dtype 与 mask merge mode 选择
- 非对齐数据的尾块处理
- StoreDist 选择（如归约结果的 `DIST_FIRST_ELEMENT_B32`）


### 第 5 步：恢复 double buffer，重新进行精度测试

在单 buffer 的基础上确保精度完全正确后，需要恢复 double buffer 配置。

只需将 `InitBuffer` 的 buffer 数量恢复为原始值（如 `BUFFER_NUM`），重新编译出包 + 安装，即可恢复 double buffer 的流水性能。

---

## 4. KernelLaunch 使用方法

### 4.1 确认算子注册信息

首次调用前，建议先打印算子签名，确认输入、输出、属性的数量与类型：

```python
from KernelLaunch import KernelLauncher
launcher = KernelLauncher("add", device_id=0)
launcher.show_op_info()
launcher.close()
```

输出示例：

```text
Operator: add  (type: add)
  Inputs:
    [0] x  dtype=float16  format=ND  paramType=required
    [1] y  dtype=float16  format=ND  paramType=required
  Outputs:
    [0] z  dtype=float16  format=ND
```

### 4.2 生成测试脚本

生成测试脚本时，**直接参考 `skills/ascendc-custom-op-precision/KernelLaunch/examples/run_add_camodel.py` 的写法**，保持与示例一致的风格：

- 使用 `sys.path.insert(0, ".")` 或脚本所在目录作为 `PYTHONPATH` 入口。
- 从 `KernelLaunch` 导入 `KernelLauncher, setup_log_separation`。
- 调用 `setup_log_separation(log_file="log_{op_name}.log", result_file="result_{op_name}.log")` 分离日志。
- 一个测试函数负责一组 shape / dtype：`np.random.randn` 构造输入 → `launcher.set_input` → `set_output` → `launcher.set_attr`（如有属性） → `launcher.run()` → 与 golden 对比。
- 使用 `np.allclose` 判定，返回 `is_pass, max_diff`。
- `main()` 中构造 `KernelLauncher`（非上下文管理器），调用 `show_op_info()`，循环多组配置，最后 `launcher.close()`。
- 如需使用 camodel 模式，使用 **dynamic 编译模式**：在构造 `KernelLauncher` 时传入 `compile_mode="dynamic"`、`camodel="CAMODEL"` 参数，并添加 `--camodel` 命令行参数控制。dynamic 编译模式会自动关闭 VF 融合。

#### 多 dtype 支持

`KernelLauncher` 支持 numpy 原生 dtype（`float32/float16/int8/...`），也支持通过 `ttk.utilities.dtypes` 构造的 `bfloat16 / int4 / float8 / float4` 等低精度 dtype。测试脚本中涉及这些非原生 dtype 时，必须使用 `ttk.utilities.dtypes` 提供的构造器和转换函数；具体写法（dtype 构造、width 计算、4-bit 打包、golden 比较、FP8 E8M0 编码等）参见：

- `skills/regbase-vf-test/references/multi-dtype-numpy.md`

#### KernelLauncher 核心 API

| 方法 / 属性 | 签名 | 说明 |
|------|------|------|
| `KernelLauncher` 构造参数 | `KernelLauncher(op_name, device_id=0, compile_mode="auto", camodel=None, kernel_meta=None)` | `compile_mode="dynamic"` 使用 TBE 动态编译，会自动关闭 VF 融合；`camodel="CAMODEL"` 启用 camodel 仿真 |
| `set_input` | `set_input(index, tensor)` | 设置第 `index` 个输入，`tensor` 为 `np.ndarray` |
| `set_output` | `set_output(index, shape, dtype)` | 声明第 `index` 个输出的 shape 和 dtype |
| `set_attr` | `set_attr(index, value)` | 设置第 `index` 个属性（按 `show_op_info()` 显示的 Attributes 顺序），`value` 为 `int`/`float`/`bool`/`str` |
| `run` | `run() -> List[np.ndarray]` | 执行 kernel，返回各输出 tensor 列表 |
| `show_op_info` | `show_op_info()` | 打印算子签名（输入/输出/属性），首次调用时建议先执行以确认索引和类型 |
| `generate_report` | `generate_report(core_ids="0")` | camodel 模式下生成 trace 报告，**dynamic 模式会自动调用 `simplify_traces_in_dir` 生成 `trace_core0_simplified.json`** |
| `close` | `close()` | 释放资源 |
| `kernel_o_path` | 属性 | 当前 case 编译出的 `.o` 文件路径，用于 VF 函数名标注 |
| `_kernel_meta` | 属性 | 当前算子的 `kernel_meta` 目录（`./kernel_meta/{op_name}`） |
| `_last_compile_result.tiling_key` | 属性 | 当前 case 的 tiling_key |

**脚本应保存到当前目录**，命名建议：

```
{op_name}_precision_test.py
```
#### dynamic + camodel 模式（用于 camodel 仿真 + trace 分析）

**dynamic 编译模式**通过 TBE 编译器在运行时动态编译算子，无需依赖预先安装到 OPP 的 binary kernel。dynamic 编译模式会**自动关闭 VF 融合**，且 camodel 仿真完成后可自动生成带 VF 函数名标注的简化 trace，**无需手动调用 `simplify_cannsim_trace.py`**。

构造 `KernelLauncher`：

```python
launcher = KernelLauncher(
    "{op_name}",
    device_id=0,
    kernel_meta="kernel_meta",  # 可以通过该目录隔离不同 dtype
    compile_mode="dynamic",
    camodel="CAMODEL" if args.camodel else None,
)
```

camodel 仿真完成后，调用 `generate_report()` 与 `annotate_camodel_trace()` 自动生成简化 trace 并标注 VF 函数名：

```python
if args.camodel:
    report_dir = launcher.generate_report(core_ids="0")
    if report_dir:
        print(f"\nCAModel report: {report_dir}")
        kernel_meta_dir = pathlib.Path(launcher._kernel_meta)
        # o_paths 与 tiling_keys 按 run() 顺序收集，用于 VF 函数名标注
        annotate_camodel_trace(report_dir, kernel_meta_dir, launcher.o_paths, launcher.tiling_keys)
```

> `annotate_camodel_trace` 从 `utils.trace_utils` 导入，需要把 `tools/` 目录加入 `PYTHONPATH`（见第 2.3 节）。

#### 脚本模板（参考 `run_add_camodel.py`，dynamic + camodel 模式）

```python
#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import argparse
import pathlib
import sys

import numpy as np

sys.path.insert(0, ".")
from KernelLaunch import KernelLauncher, setup_log_separation
from utils.trace_utils import annotate_camodel_trace

setup_log_separation(log_file="log_add.log", result_file="result_add.log")


def compute_golden(inputs):
    """CPU Golden 实现，返回 list，顺序与 set_output 一致。"""
    return [inputs[0] + inputs[1]]


def precision_test(output, golden, rtol=1e-3, atol=1e-3):
    is_pass = np.allclose(output, golden, rtol=rtol, atol=atol)
    max_diff = np.max(np.abs(output.astype(np.float64) - golden.astype(np.float64)))
    return is_pass, max_diff


def test_add(launcher, shape, dtype, label=""):
    a = np.random.randn(*shape).astype(dtype)
    b = np.random.randn(*shape).astype(dtype)
    golden = compute_golden([a, b])[0]

    launcher.set_input(0, a)
    launcher.set_input(1, b)
    launcher.set_output(0, shape, dtype=dtype)
    # 如果算子有属性，需在 run() 前调用 set_attr，例如：
    # launcher.set_attr(0, 1e-6)  # index 对应 show_op_info() 中 Attributes 的顺序
    print(f"  [{label:11s}] shape={str(shape):20s} dtype={np.dtype(dtype).name:10s}")
    try:
        outputs = launcher.run()
    except Exception as e:
        print(f"    [FAIL] {e}\n")
        return False

    result = outputs[0]
    is_pass, max_diff = precision_test(result, golden)
    print(f"    [Output 0] {'PASS' if is_pass else 'FAIL'}  max_diff={max_diff:.2e}\n")
    return is_pass


def main():
    OP_NAME = "add"     # specify the op_name
    parser = argparse.ArgumentParser(description=f"Kernel {OP_NAME} precision test")
    parser.add_argument("--device_id", type=int, default=0, help="Target NPU device ID (default: 0)")
    parser.add_argument(
        "--camodel",
        action="store_true",
        help="Force CAModel simulation mode (default: real hardware)",
    )
    args = parser.parse_args()

    device_id = 0 if args.camodel else args.device_id
    # 关键：使用 dynamic 编译模式（自动关闭 VF 融合）
    launcher = KernelLauncher(
        OP_NAME,
        device_id=device_id,
        kernel_meta="kernel_meta",  # 该参数可以控制输出目录名称
        compile_mode="dynamic",
        camodel="CAMODEL" if args.camodel else None,
    )
    launcher.show_op_info()
    print()

    test_shapes = [
        ((64, 127), "non-aligned"),
        ((1024,),   "aligned"),
        ((32, 64, 128), "aligned"),
        ((32, 63, 127), "non-aligned"),
    ]
    dtypes = [np.float32, np.float16]

    results = []
    print("=" * 60)
    print("Start testing add kernel with CAModel")
    print("=" * 60)
    for dtype in dtypes:
        print(f"\n[Dtype: {np.dtype(dtype).name}]")
        print("-" * 60)
        for shape, label in test_shapes:
            results.append(test_add(launcher, shape, dtype, label))

    launcher.close()

    print("=" * 60)
    print("Test summary")
    print("=" * 60)
    if all(results):
        print(f"[ALL PASSED] {OP_NAME} kernel tests passed!")
    else:
        print(f"[ SOME FAILED ] Some {OP_NAME} kernel tests failed!")

    if args.camodel:
        report_dir = launcher.generate_report(core_ids="0")
        if report_dir:
            print(f"\nCAModel report: {report_dir}")
            kernel_meta_dir = pathlib.Path(launcher._kernel_meta)
            # 自动生成 trace_core0_simplified.json 并标注 VF 函数名
            annotate_camodel_trace(report_dir, kernel_meta_dir, launcher.o_paths, launcher.tiling_keys)


if __name__ == "__main__":
    main()
```

### 4.3 执行验证

```bash
python3 {op_name}_precision_test.py --device_id 0
```

输出中会自动包含 OOB 检测结果：

```text
OOB check: output=['OK', 'OK'], workspace=['OK']
```

- `OK`：正常。
- `FAIL`：发生越界或 output 数据未变，应优先排查地址/长度/偏移。

---

## 5. 用例设计建议

### 5.1 边界用例

| 类型 | 示例 | 目的 |
|------|------|------|
| 对齐 shape | `[64, 1024]` | 验证主路径 |
| 非对齐 shape | `[129, 1023]` | 验证 tail 处理 |
| 极小 shape | `[1]` / `[1, 1]` | 验证边界分支 |
| 极大 shape | `[1024, 8192]` | 验证多 tile / 多核 |
| 特殊值域 | 全 0、全 1、含 NaN/Inf | 验证异常值处理 |

### 5.2 精度指标

| 算子类别 | 对比方法 | 误差度量 |
|---------|---------|---------|
| 浮点计算 | 双标杆或单标杆 | MARE / MERE / RMSE / `np.allclose` |
| 整数/搬移 | 单标杆 | Bitwise Match |
| 量化 | 单/双标杆 | AE / MARE |

默认 `np.allclose` 阈值：
- `float16`：`rtol=1e-3, atol=1e-3`
- `float32`：`rtol=1e-5, atol=1e-5`

具体阈值应根据算子语义和用户需求调整。

---

## 6. RegBase 编程参考

当自定义算子基于 Ascend950 RegBase（VF）实现时，精度调试需理解 RegBase 的编程模型与约束。

### 6.0 参考
在进行 RegBase 代码修改之前，务必参考如下文档：
- `skills/regbase-vf-test/references/ascend950_hardware_and_pipeline_control.md` — 流水线同步与 PipeBarrier。


### 6.1 三层调用链

RegBase 编程通常包含三层：

- `__aicore__` 层：Kernel 入口与调度，负责 GM ↔ UB 搬运、tiling 解析、队列管理。
- `__simd_vf__` 层：融合循环层，实际被编译为 VF，**计算逻辑必须放在这一层**。
- `__simd_callee__` 层：最细粒度 callee，供 `__simd_vf__` 调用。

完整算子的精度验证通常只需关注前两层。

### 6.2 核心 API

| API | 作用 | 精度调试意义 |
|-----|------|-------------|
| `AscendC::Reg::UpdateMask<T, trait>(count)` | 按剩余元素生成 mask | 尾块处理是否正确直接影响非对齐 shape 的精度 |
| `AscendC::Reg::LoadAlign(reg, ptr)` | 从 UB 加载到寄存器 | 非对齐地址加载会导致错误结果 |
| `AscendC::Reg::StoreAlign(ptr, reg, mask)` | 将寄存器写回 UB | mask 必须正确，否则尾块会写入 padding 值 |
| `AscendC::Reg::Muls/Add/Mul/...` | 向量运算 | 注意 dtype 与 mask merge mode 选择 |

### 6.3 关键约束

1. **计算必须在 `__simd_vf__` 内完成**：不得将 VF 计算逻辑外移到 `__aicore__` 层。
2. **禁止直接访问 `__ubuf__` 指针**：`__simd_vf__` 中不得使用 `[]` / `*` 访问 `__ubuf__` 内存，必须通过 `AscendC::Reg` API。
3. **Hardware Loop 条件**：`__simd_vf__` 中的循环需满足硬件循环条件，典型写法为 `for (uint16_t i = 0; i < repeatTime; ++i)`。

### 6.4 非 32B 对齐 2D 数据处理

处理 2D 数据（如 `[rows, cols]`）且 `cols * sizeof(T)` 非 32B 对齐时，必须在 kernel 内完成对齐，否则 `LoadAlign` 会因非对齐地址出错。标准模式：

```cpp
uint32_t numColAlign = ((numCol + ALIGN_ELEM - 1) / ALIGN_ELEM) * ALIGN_ELEM;
pipe.InitBuffer(inQueueX, 1, rows * numColAlign * sizeof(T));

DataCopyExtParams copyInParams{
    static_cast<uint16_t>(rows),
    static_cast<uint32_t>(numCol * sizeof(T)),
    0,  // srcStride
    0,  // dstStride：DMA 自动 pad 到 32B
    0
};
DataCopyPad(xLocal, xGm, copyInParams, padParams);
```

VF 函数需同时接收 `colAlign`（行间 stride）和 `cols`（实际列数）：

```cpp
__simd_vf__ inline void MyVfFunc(
    __ubuf__ T* dstUb, __ubuf__ T* srcUb,
    uint16_t rows, uint32_t colAlign, uint32_t cols)
{
    for (uint16_t row = 0; row < rows; ++row) {
        uint32_t baseOffset = row * colAlign;
        auto mask = AscendC::Reg::UpdateMask<T, trait>(cols);
        // LoadAlign(srcUb + baseOffset)
        // ... compute ...
        // StoreAlign(dstUb + baseOffset, ..., mask)
    }
}
```

### 6.5 寄存器超限与编译报错

若编译报 `error in backend: Do not know how to split the result of this operator!`，优先检查：

- `__simd_vf__` / `__simd_callee__` 修饰符是否正确使用。
- `__simd_vf__` 中是否直接使用了 `[]` / `*` 访问 `__ubuf__`。
- RegTensor 数量是否超出硬件限制。

---

## 7. 返回格式

本 Skill 执行完毕后，应在最终回复中输出机器可读标记：

```markdown
## RETURN: status={STATUS}, error_type={ERROR_TYPE}
```

### STATUS

| 值 | 含义 |
|---|---|
| `COMPLETED` | 精度验证通过 |
| `FAILED` | 精度验证失败 / 环境错误 / 编译错误 / 其他错误 |

### ERROR_TYPE

`status=FAILED` 时必填，`status=COMPLETED` 时留空：

| 值 | 含义 | 触发场景 |
|---|---|---|
| `PREC` | 精度失败 | NPU 输出与 Golden 对比未通过 |
| `OOB` | 越界错误 | OOB check 报 FAIL |
| `COMPILE` | 编译/出包问题 | 找不到 `.o` 文件、binary match 失败 |
| `ENV` | 环境错误 | CANN 未配置、NPU 不可用、ttk 找不到 |
| `INP` | 输入/参数错误 | 用户提供的 shape/dtype 与算子签名不匹配 |
| `OTH` | 其他 | 无法归入以上类别 |

### 返回前附加信息

`status=COMPLETED` 时，在 `RETURN` 标记前附加：

```markdown
## PRECISION_RESULT
status: COMPLETED
op_name: {op_name}
script_path: {path_to_generated_script}
test_summary: {passed}/{total} cases passed, max_diff={max_diff}
```

`status=FAILED` 时，在 `RETURN` 标记前附加：

```markdown
## PRECISION_RESULT
status: FAILED
error_type: {ERROR_TYPE}
error_info: |
  {一句话概括错误}
  {关键日志片段或 max_diff}
script_path: {path_to_generated_script}
```

---

## 8. 注意事项

1. **KernelLaunch 编译模式**：只有 camodel 仿真 + trace 分析时需要使用 `dynamic` 模式，否则直接开始上板测试。
2. **device_id 选择**：若 device 0 非 `Health:OK`，应提示用户更换 device_id。但使用 camodel 进行仿真时是虚拟设备，device_id 必须为 0。
3. **输出格式**：算子输出为 `np.ndarray`，注意 dtype 与 shape 是否与预期一致。
4. **复用与清理**：测试生成的 `kernel_meta/` 目录可能累积，建议每次在独立目录运行或在脚本中清理。
5. **强制工作流**：第 3 节的调试流程为强制要求——禁止跳步、禁止仅凭代码审查就改代码、修复后必须回验。详见第 3 节"工作流规则"。
6. **camodel 用小 shape**：camodel 是仿真，大 shape 慢且 trace 难分析。用能复现问题的最小 shape。
7. **所有测试脚本创建在当前路径下**：不要创建在 skill 所在目录下。

---

## 9. 示例：完整运行一次 Add 精度验证

```bash
# 1. 环境准备
source ${ASCEND_HOME_PATH}/bin/setenv.bash
source ${ASCEND_HOME_PATH}/opp/vendors/custom_nn/bin/set_env.bash
export PYTHONPATH=/absolute/path/to/skills/ascendc-custom-op-precision:$PYTHONPATH

# 2. 生成测试脚本（由本 skill 完成）
# 注意：脚本开头已内联 sys.path.insert(0, ".")，因此应在包含 KernelLaunch 的目录运行
# 或在脚本所在目录的父目录运行，并调整 PYTHONPATH
python3 {op_name}_precision_test.py --device_id 0
```

预期通过输出：

```text
Operator: {op_name}  (type: ...)
  Inputs:
    ...
  Outputs:
    ...

============================================================
Start testing {op_name} kernel
============================================================

[Dtype: float16]
------------------------------------------------------------
  [aligned    ] shape=(256,)             dtype=float16
    [Output 0] PASS  max_diff=0.00e+00

  [non-aligned] shape=(257,)             dtype=float16
    [Output 0] PASS  max_diff=1.23e-04

OOB check: output=['OK'], workspace=[]

============================================================
Test summary
============================================================
[ALL PASSED] {op_name} kernel tests passed!

## PRECISION_RESULT
status: COMPLETED
op_name: {op_name}
script_path: /path/to/{op_name}_precision_test.py
test_summary: 12/12 cases passed, max_diff=1.23e-04

## RETURN: status=COMPLETED, error_type=
```
