---
name: ascendc-ttklog-debug
description: |
  当用户提到"算子调试"、"日志分析"、"越界问题"、"同步问题"、
  "dump日志"、"mte日志"、"ub日志"、"寄存器日志"时触发此技能。

  该技能用于通过 ttk 仿真日志定位 AscendC 算子的同步问题和越界问题，支持对 VEC_SCOPE(寄存器)内进行 debug。
  必需依赖：python3, bash。可选依赖：llvm-objdump（仅寄存器分析需要）。
---

# AscendC 算子日志级调试技能

## 目标

通过 ttk 仿真日志定位 AscendC 算子的同步问题和越界问题，支持对 VEC_SCOPE(寄存器)内进行 debug。

## 前置条件

### 场景 A（已有日志，直接分析）必选输入

缺任何一项则询问用户补充：

1. `coreX.mte_log.dump` 路径 — MTE 搬运日志
2. `coreX.veccoreY.ub.dump` 路径 — UB 内存访问日志
3. `case_result.csv` 路径 — 从中解析 TilingData（buffer 大小等）
4. kernel 实现文件路径 — 包含 `InitBuffer` 调用的具体 `.h` 文件（注意：调用形式可能是 `pipe_.InitBuffer`、`pipe.InitBuffer` 或 `this->pipe_.InitBuffer`）
5. TilingData 定义文件路径 — 包含 TilingData 字段定义的头文件（形式可能是 `BEGIN_TILING_DATA_DEF` 宏或普通 `struct`）

### 场景 B（需要先获取日志）必选输入

1. 算子方案（算子名、输入输出规格、约束、tiling 方案、kernel 方案）
2. CSV 用例文件路径
3. kernel 代码路径（`.cpp`/`.h`）

### 依赖工具

- **必需**：
  - `python3` - 运行 MTE/UB 分析脚本
  - `bash` - 执行 run.sh
- **可选**：
  - `llvm-objdump` - 反汇编 kernel（仅寄存器日志分析需要）

**如果工具缺失**：
- 必需工具缺失 → 停止执行，提示用户安装
- 可选工具缺失 → 跳过对应步骤，提示用户该步骤无法执行

---

## 工作流程

### Step 0: 场景选择

使用 AskUserQuestion 询问用户：

```yaml
question: "请选择调试场景"
header: "调试场景"
options:
  - label: "已有日志，直接分析（推荐）"
    description: "已有 mte_log.dump 和 ub.dump 日志文件，直接进行越界/同步分析"
  - label: "需要先获取日志"
    description: "还没有日志文件，需要先定位错误核、跑 ttk 仿真获取目标日志"
```

---

### 场景 A：已有日志，直接分析（推荐）

**必选输入**（缺任何一项则询问用户补充）：
1. `coreX.mte_log.dump` 路径
2. `coreX.veccoreY.ub.dump` 路径
3. `case_result.csv` 路径
4. kernel 实现文件路径 — 包含 `InitBuffer` 调用的具体 `.h` 文件
5. TilingData 定义文件路径 — 包含 TilingData 字段定义的头文件

收集完输入后，使用 AskUserQuestion 询问分析类型：

```yaml
question: "请选择分析类型"
header: "分析类型"
options:
  - label: "越界分析（推荐）"
    description: "分析 MTE 搬运和 UB 内存访问是否越界，定位越界地址和 buffer"
  - label: "同步分析（实验性）"
    description: "分析内存访问时序，定位同步问题（脚本能力开发中，当前仅提供 MTE+UB 基础分析）"
```

- 越界分析 → 跳转到 [完整分析流程](#完整分析流程)
- 同步分析 → 跳转到 [完整分析流程](#完整分析流程)，完成后额外跳转到 [寄存器日志分析](#寄存器日志分析)

---

### 场景 B：需要先获取日志

1. 读取 `tbetoolkits-compare.log`，定位错误核（见 [核标号说明](#核标号说明)）
2. 使用固定输入 + 指定核日志级别，跑 ttk 仿真获取日志（见 [执行方法](#执行方法)）
3. 获取日志后，回到 **场景 A** 继续分析

---

## 执行方法

### 基础仿真执行

```bash
bash run.sh --overflow-mode=1 --seed=1 -d --1982model=esl <用例csv路径> -t=<用例名>
```

### Dump 输入输出数据

在基础命令后添加 `--dump` 参数。

### 使用固定数据执行

在用例 CSV 内添加：
- 列标签：`manual_input_data_binaries`
- 内容格式：`('输入1.bin', '输入2.bin'),('输入1.bin', '输入2.bin')`

### 指定对应核日志

1. 找到 `model_result/<用例名>/dynamic/etc/1982*****_cloud_config.toml`
2. 修改 `[LOG] core_enable_mask` 为指定核（bit 表示法）：
   - 第 1 核：0x1
   - 第 2 核：0x2
   - 第 30 核：0x20000000
3. 执行命令（添加 `--model-download=false --model-config=false`）

---

## 核标号说明

日志文件中的核标号格式为 `coreX.veccoreY`。

**芯片架构（Ascend 950）**：
- 32 个物理核，编号 0-31
- 每个物理核包含 2 个 veccore（Vector Core），编号 0 和 1
- 共计 64 个 veccore 可用于并行计算

**核标号对应关系**：

| 物理核编号 | veccore 编号 | 日志核标号 |
|-----------|-------------|-----------|
| 0 | 0 | core0.veccore0 |
| 0 | 1 | core0.veccore1 |
| 1 | 0 | core1.veccore0 |
| 1 | 1 | core1.veccore1 |
| ... | ... | ... |
| 31 | 0 | core31.veccore0 |
| 31 | 1 | core31.veccore1 |

**错误核定位**：
根据 `tbetoolkits-compare.log` 中的错误数据 index 和 outputshape，可定位到发生错误的核。index 对应 veccore 编号，outputshape 帮助确认具体的 tile。

---

## 执行日志

| 日志文件 | 用途 |
|---------|------|
| `tbetoolkits-info.log` | 查看 tilingkey、tilingdata、执行状态 |
| `tbetoolkits-error.log` | 查看报错信息 |
| `tbetoolkits-compare.log` | 查看精度失败数据与 golden 对比，定位错误核 |
| `model_results/<用例名>/dynamic/log_ca/coreX.mte_log.dump` | 算子搬运日志 |
| `model_results/<用例名>/dynamic/log_ca/coreX.veccoreY.ub.dump` | 算子 UB 日志 |
| `model_results/<用例名>/dynamic/log_ca/coreX.veccoreY.ub.rd_log.dump` | UB 读操作详情 |
| `model_results/<用例名>/dynamic/log_ca/coreX.veccoreY.ub.wr_log.dump` | UB 写操作详情 |
| `model_results/<用例名>/dynamic/log_ca/coreX.veccoreY.rvec_pv.dump` | 寄存器日志 |
| `model_results/<用例名>/dynamic/log_ca/coreX.veccoreY.instr_log.dump` | Scalar 日志 |

---

## 完整分析流程

### 调度规则

**⚠️ 严格按 Step 1 → 2 → 3 → 4 → 5(可选) 顺序执行，不可跳过、不可并行、不可乱序。**

```
Step 1 [脚本] → 检查输出 → Step 2 [AI] → 提示验证 → Step 3 [脚本] → 检查输出 → Step 4 [脚本] → 检查输出 → Step 5 [脚本,可选] → 完成
   ↓ 失败              ↓ 失败                        ↓ 失败              ↓ 失败
 停止报告            停止报告                       停止报告            停止报告
```

**调度职责**（每步执行前后）：
1. **前置检查**：确认该步所需的全部输入文件/数据已就绪
2. **调用执行**：按执行规格执行（脚本步骤运行命令，AI 步骤按子流程操作）
3. **输出验证**：确认输出文件存在且非空
4. **失败处理**：任何步骤失败 → 立即停止，向用户报告失败步骤、命令、错误信息，等待用户指示

**禁止行为**：
- 禁止直接读取 `.dump` 日志原文（必须通过脚本处理后读取 `.json`/`.txt`/`.log` 输出）
- 禁止跳过失败步骤继续执行后续步骤
- 禁止在未完成前置步骤的情况下提前执行后续步骤

---

### Step 1: MTE 分析

**执行者**：脚本

**输入**：
- `coreX.mte_log.dump` — 用户提供的 MTE 搬运日志路径

**输出**（保留在 `<工作目录>`）：
- `mte_analysis.json` — 去重后的搬运记录
- `mte_timeline.json` — 按 veccore 分组的时间线
- `mte_timeline_veccoreY.txt` — 可读报告（供 Step 4 使用）

**执行命令**：
```bash
cd <技能目录>/scripts/MTE/
python run_mte_analysis.py <coreX.mte_log.dump路径> veccoreY --output-dir <工作目录>
```

**输出验证**：检查上述三个文件均存在且非空。

---

### Step 2: UB 地址映射

**执行者**：AI + 脚本

**输入**：
- TilingData 定义文件 — 包含 TilingData 字段定义的头文件（`BEGIN_TILING_DATA_DEF` 宏或普通 `struct`）
- `case_result.csv` — 用例结果（TilingData 实际值）
- kernel 实现文件 — 包含 `InitBuffer` 调用的具体 `.h` 文件（调用形式：`pipe_.InitBuffer` / `pipe.InitBuffer` / `this->pipe_.InitBuffer`）

**输出**（保留在 `<工作目录>`）：
- `buffer_config.json` — AI 生成的 buffer 配置
- `memory_map.json` — 脚本计算的地址映射

**AI 执行子流程**：

1. **读 TilingData 定义文件**：获取 TilingData 结构体的字段名和类型定义（支持 `BEGIN_TILING_DATA_DEF` 宏和普通 `struct` 两种形式）
2. **读 `case_result.csv`**：根据字段定义，提取当前用例的 TilingData 实际值（buffer 大小等）
3. **读 kernel 实现文件**：找到所有 `InitBuffer` 调用（匹配 `pipe_.InitBuffer`、`pipe.InitBuffer`、`this->pipe_.InitBuffer` 等形式），用 TilingData 实际值代入 `size` 参数
4. **写 `buffer_config.json`**：只需写 buffer 名称、slot 数量、单个 slot 大小，**不需要计算地址**

**buffer_config.json 格式**：
```json
{
  "buffers": [
    {"name": "groupIdxQue_", "num": 1, "size": 32},
    {"name": "xQue_", "num": 4, "size": 55776},
    {"name": "tempResBuf_", "num": 1, "size": 1024}
  ]
}
```

- `name`：buffer 变量名（与 InitBuffer 第一个参数一致）
- `num`：slot 数量（3 参数形式的第二个参数，2 参数形式默认为 1）
- `size`：单个 slot 大小（字节，代入 TilingData 实际值后的结果）

**脚本执行**：
```bash
cd <技能目录>/scripts/UB/
python gen_memory_map.py <工作目录>/buffer_config.json -o <工作目录>/memory_map.json
```

**输出验证**：检查 `memory_map.json` 存在且非空，脚本 stderr 输出的 UB 总用量合理（不超过 248KB）。

**可选验证**：使用 AskUserQuestion 询问用户是否需要验证地址映射正确性（默认不验证）。
```yaml
question: "是否需要验证地址映射？"
header: "地址验证"
options:
  - label: "跳过验证，继续（默认）"
    description: "信任计算结果，直接进入 Step 3"
  - label: "验证"
    description: "结合 kernel 代码的 DataCopy 调用和 MTE 日志，逐条比对地址是否一致"
```

---

### Step 3: UB 分析

**执行者**：脚本

**输入**：
- `coreX.veccoreY.ub.dump` — 用户提供的 UB 内存访问日志路径
- Step 2 输出：`<工作目录>/memory_map.json`

**输出**：
- `ub_analysis_veccoreY.log`（供 Step 4 使用）

**执行命令**：
```bash
cd <技能目录>/scripts/UB/
python show_by_buffer.py <coreX.veccoreY.ub.dump路径> --merge-mte --mte-focus -m <工作目录>/memory_map.json > <工作目录>/ub_analysis_veccoreY.log
```

**输出验证**：检查 `ub_analysis_veccoreY.log` 存在且非空。

---

### Step 4: 合并分析

**执行者**：脚本

**输入**：
- Step 1 输出：`<工作目录>/mte_timeline_veccoreY.txt`
- Step 3 输出：`<工作目录>/ub_analysis_veccoreY.log`

**输出**：
- `merged_report.log` — 最终越界检查报告

**执行命令**：
```bash
cd <技能目录>/scripts/UB/
python merge_logs.py <工作目录>/mte_timeline_veccoreY.txt <工作目录>/ub_analysis_veccoreY.log -o <工作目录>/merged_report.log
```

**输出验证**：检查 `merged_report.log` 存在且非空。

**合并逻辑**：
- MTE_W/MTE_R 记录以 MTE 为准（地址范围更完整，含起止时间戳）
- VEC/AIV 记录保留 UB 分析结果
- 越界检查：MTE 越界新计算，VEC 越界复用 UB 分析结果
- 忽略第一次初始化（Tilingdata）搬运（与业务逻辑无关）
- UB 日志中 GM→UB 的搬运记录可能不完整，MTE 数据更准确

---

### Step 5: 可视化（可选）

**执行者**：脚本

**输入**：
- Step 4 输出：`<工作目录>/merged_report.log`

**输出**：
- `visualization.html` — 自包含交互式甘特图

**执行命令**：
```bash
cd <技能目录>/scripts/UB/
python visualize.py <工作目录>/merged_report.log -o <工作目录>/visualization.html
```

**功能**：
- 甘特图：X 轴时间，Y 轴双层结构（外层 buffer 名，内层 MTE_W/MTE_R/VEC/AIV 通道）
- 交互：鼠标滚轮缩放、拖拽平移、点击折叠/展开 buffer、悬停查看详情
- 过滤：顶部复选框按单元类型过滤
- 无外部依赖，单 HTML 文件直接浏览器打开

---

## 寄存器日志分析

当错误发生在 vec_scope 内时，需要分析 `coreX.veccoreY.rvec_pv.dump`。

### 分析步骤

1. **反汇编 kernel**：
   ```bash
   llvm-objdump -d kernel_meta/dyn_op_<用例名>.o > dyn_op_<用例名>.s
   llvm-objdump -d kernel_meta/dyn_op_<用例名>_<tilingKey>.o > dyn_op_<用例名>_<tilingKey>.s
   ```

2. **查找指令对应地址**：在反汇编结果中找到 dyn_op 函数的第一条指令

3. **分析 Scalar 日志**：读取 `instr_log.dump`，找到 getValue/setValue 操作的内存地址映射

4. **判断同步问题**：将读取到的目标时间戳和 UB 日志结合，判断是否存在同步问题

### 示例

```
[info] [00011343] (PC: 0x9000d15200) SCALAR: LD_XD_XN
  XD:X1=0xef7        # 取到的值
  XN:X1=0x3aac0      # 读取地址
```

---

## 辅助脚本说明

| 脚本位置 | 功能 |
|---------|------|
| `scripts/MTE/run_mte_analysis.py` | **一键 MTE 分析**（原子化执行下列三阶段） |
| `scripts/MTE/analyze_mte_transfers.py` | 解析 mte_log.dump |
| `scripts/MTE/process_mte_timeline.py` | 生成时间线 JSON |
| `scripts/MTE/show_timeline.py` | 输出可读的时间线文本 |
| `scripts/UB/gen_memory_map.py` | 从 buffer_config.json 计算地址映射，输出 memory_map.json |
| `scripts/UB/ub_analyzer.py` | 核心 UB 解析模块（运行时加载 memory_map.json） |
| `scripts/UB/show_by_buffer.py` | 按 buffer 显示分析结果（需 `-m memory_map.json`） |
| `scripts/UB/show_by_time.py` | 按时间显示分析结果（需 `-m memory_map.json`） |
| `scripts/UB/merge_logs.py` | 合并 MTE 和 UB 分析结果（支持 MTE 起止时间戳） |
| `scripts/UB/visualize.py` | 从 merged_report.log 生成交互式甘特图 HTML |
| `scripts/REG/llvm-objdump` | 反汇编 kernel 工具 |

**show_by_buffer.py 常用选项**：
- `--merge-mte` — 按 instr_id 合并 MTE 操作
- `--mte-focus` — MTE 聚焦模式（MTE 详情 + VEC/AIV 聚合摘要）
- `--merge-vec-aiv` — mte-focus 模式下将 VEC 和 AIV 合并为一行（默认分开显示）
- `-m <memory_map.json>` — 指定地址映射文件

**合并行为说明**：
- VEC 和 AIV 默认分开显示（`[VEC]` 和 `[AIV]` 各自独立行）
- 不同单元类别（VEC/AIV/MTE）互为合并屏障：两个同类操作之间如果出现了另一类操作，不会被合并
- 时间间隔过大的同类操作也不会被合并

详细使用方法见 `references/MTE_guide.md`、`scripts/UB/README.md` 和 `references/UB_guide.md`。

---

## 重要提醒

1. **严格按流程执行**：不要跳过步骤，每个步骤的结果确认后再继续
2. **越界检查**：关注地址是否超过 248KB UB 边界(算子为950场景，不同芯片可得到结果后提示用户)
3. **指定核日志**：重点关注需要固定输入，再进行指定核
4. **同步问题**：重点关注 getValue/setValue 的时序是否正确（该功能未完善）