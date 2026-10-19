---
name: ascend-hardware
description: "AscendC 开发环境检查与硬件规格查询。(1) 检查驱动、CANN 环境变量、Python/torch_npu; (2) 检测 NPU 芯片型号; (3) 查询硬件参数（UB大小、核数、带宽、向量宽度、对齐要求等）; (4) 计算 derived_params（带宽、算力、max_tile_fp16_double_buf）; (5) evo进化场景输出 hw_params 结构和 hw_params_one_liner 摘要，供 world_model.json 初始化和子 agent prompt 注入。Use when: 开发前环境检查、'硬件参数', 'UB大小', '核数', '带宽', '芯片规格', 'hardware specs', Tiling 设计需要硬件约束、世界模型 hw_params 初始化。"
---

# Ascend Hardware Specs Query

查询 Ascend NPU 目标芯片的硬件规格参数，为 Tiling 计算和优化决策提供基础依据。

## 执行纪律

### 语言约束
- **所有思考、分析、推理、解释必须使用中文**
- **代码、技术标识符、JSON键、文件路径、技术术语（如UB、GM、TFLOPS）除外**

### 数据来源说明

本 skill 中的 `references/chips/*.json` 是从 CANN 安装包 INI 文件整理而来的**速查表**，日常查询直接使用 JSON 即可。

JSON 中的数据原始来源为 CANN 包中的 platform_config INI 文件：
```
${ASCEND_HOME_PATH}/{ARCH_DIR}/data/platform_config/{SoCVersion}.ini
```
其中 `{ARCH_DIR}` 因系统架构而异：`aarch64-linux` | `x86_64-linux` | `arm64-linux`。

**仅当用户对 JSON 数值存疑或需要 JSON 未覆盖的细节参数时**，回退到 INI 原始文件查询。
必须先通过 Step 1 确定精确芯片型号，再按 Step 2「芯片系列映射表」找到**确切的 INI 文件名**（如 `910B3` → `Ascend910B3.ini`，而非通配符 `Ascend910B*.ini`）：

```bash
ARCH=$(uname -m)
case "$ARCH" in
  aarch64) ARCH_DIR="aarch64-linux" ;;
  x86_64)  ARCH_DIR="x86_64-linux" ;;
  *)       ARCH_DIR="${ARCH}-linux" ;;
esac
INI_DIR="${ASCEND_HOME_PATH}/${ARCH_DIR}/data/platform_config"
# 使用精确文件名，如 Ascend910B3.ini，避免通配符误匹配
cat "$INI_DIR"/Ascend910B3.ini 2>/dev/null
```

### 精确查询原则
- **必须根据芯片型号选择正确的JSON文件**
- **用户存疑时，按芯片系列映射表模糊匹配 INI 文件名进行原始文件校验**
- **必须区分shared通用参数和variants特有参数**
- **必须计算derived_params（带宽、算力）**

### 检查点机制
查询完成后必须：
1. 验证返回的参数完整性
2. 标注精确值vs估算值

## Agent 集成说明

此 skill 是**开发前必须调用的第一个 skill**，负责：
1. **环境验证**（Step 0）：检查驱动、CANN、Python/torch_npu
2. **芯片检测**（Step 1）：自动识别 NPU 型号
3. **硬件参数查询**（Step 2-5）：为后续所有开发阶段提供硬件参数基础

返回的硬件参数将用于：
- **Tiling 设计**：UB size 用于计算分块参数，alignment 用于对齐检查
- **Profiling 分析**：提供硬件峰值用于利用率计算
- **优化决策**：core_num 用于并行度判断，带宽用于 memory-bound 判定

## Workflow

### Step 0: 开发环境检查

在查询硬件参数前，先验证开发环境是否就绪：

**Step 0a: 检查驱动库路径**
```bash
DRIVER_DIR="/usr/local/Ascend/driver/lib64/driver"
if [ -d "$DRIVER_DIR" ]; then
  echo "Driver dir: FOUND ($DRIVER_DIR)"
  echo $LD_LIBRARY_PATH | grep -q "$DRIVER_DIR" && echo "LD_LIBRARY_PATH: OK" || echo "LD_LIBRARY_PATH: MISSING"
else
  echo "Driver dir: NOT FOUND"
fi
```
- `LD_LIBRARY_PATH: MISSING` → 提示用户：`export LD_LIBRARY_PATH=/usr/local/Ascend/driver/lib64/driver:$LD_LIBRARY_PATH`

**Step 0b: 检查 CANN 环境变量**
```bash
echo "ASCEND_TOOLKIT_HOME: ${ASCEND_TOOLKIT_HOME:-NOT SET}"
echo "ASCEND_HOME_PATH: ${ASCEND_HOME_PATH:-NOT SET}"
echo "ASCEND_OPP_PATH: ${ASCEND_OPP_PATH:-NOT SET}"
```
- 任何变量 NOT SET → 提示用户 `source /path/to/cann-x.x.x/set_env.sh`

**Step 0c: 检查 Python & torch_npu（可选）**
```bash
python3 --version
python3 -c "import torch_npu; print('torch_npu:', torch_npu.__version__)" 2>/dev/null || echo "torch_npu: NOT INSTALLED"
```

**检查失败处理**：如果 Step 0a-0b 中任何关键检查失败（驱动或 CANN 环境缺失），报告失败项 → 给出修复命令 → 等用户确认后再继续。torch_npu 未安装为非关键项，记录后继续。

---

### Step 1: 芯片检测

如未指定芯片型号，按以下顺序自动检测，**任一步骤成功即停止**：

**Step 1a: 基础检测（npu-smi info）**
```bash
npu-smi info 2>/dev/null | grep -E "^\| [0-9]+" | head -1
```
从输出中提取芯片系列（如 910B3、310P 等）。

若输出仅为 `Ascend910`（无 B/C 后缀，老 910 系列），追加一次精确子型号查询：
```bash
npu-smi info -t board -i 0 -c 0 2>/dev/null | grep -i "NPU Name"
```
从 `NPU Name` 字段提取具体子型号（如 `Ascend910A` / `Ascend910ProA` / `Ascend910PremiumA`）。

> **注意**：A5 / David / 910_95xx (950 / 950PR / 950DT, 即 **Atlas 350 加速卡**) 当前不支持 `npu-smi info`，会输出为空 → 进入 Step 1b。

**Step 1b: asys 兜底（推荐二次确认，David 必走）**

当 Step 1a 输出为空时：
```bash
asys info -r=status 2>/dev/null | grep -i "Chip Name"
```
从 `Chip Name` 字段提取具体型号。David 平台用此命令可拿到型号。

**Step 1c: lspci PCI ID 兜底**

当 Step 1a、1b 均失败时，用 PCI ID 归一：
```bash
# lspci 未安装：apt-get install pciutils  /  yum install pciutils
lspci -n -D 2>/dev/null | grep -o '19e5:d[0-9a-f]\{3\}' | head -n1 | cut -d: -f2
```

PCI ID → 芯片系列归一表：

| PCI ID | 芯片代号 | 对应 npu-smi 系列 | 默认 JSON 文件 |
|---|---|---|---|
| `d802` | A2 | Ascend910B (910B1~B4，Atlas A2 系列) | `ascend_910b.json` |
| `d803` | A3 | Ascend910C / 910_93xx (Atlas A3 系列) | `ascend_910_93xx.json` |
| `d806` | A5 | David / 910_95xx / 950 / 950PR / 950DT (**Atlas 350 加速卡**, npu-smi 暂不支持) | `ascend_910_95xx.json` |

> Step 1c 命中 `d806` 时可直接落到 `ascend_910_95xx.json`（对应 Atlas 350 加速卡）；如需精确到 950PR / 950DT 子型号，再让用户从 variants 里指定（或回到 Step 1b 用 asys 拿 Chip Name）。

**三步全失败**：报告失败 → 让用户手动指定芯片型号后继续。

---

### Step 2: 查询规格参数

**芯片系列映射表**:

| 用户输入 / npu-smi 输出 | INI 文件 (platform_config/) | SoC_version | Short_SoC | 匹配方式 | JSON 文件 |
|---|---|---|---|---|---|
| **910C** / 910C1~C4 / 910_93xx (Atlas A3) | Ascend910C1.ini ~ Ascend910C4.ini | Ascend910C1~C4 | Ascend910C | 前缀匹配 | `ascend_910_93xx.json` |
| **910B1~B4** / 910B2C (Atlas A2) | Ascend910B1.ini ~ Ascend910B4.ini, Ascend910B2C.ini | Ascend910B1~B4, Ascend910B2C | Ascend910B | **完全匹配** | `ascend_910b.json` |
| **910A** / 910ProA/B / 910PremiumA / 910B(Gen1) | Ascend910A.ini, Ascend910ProA.ini, Ascend910ProB.ini, Ascend910PremiumA.ini, Ascend910B.ini | 各自独立 | Ascend910 | - | `ascend_910.json` |
| **David** / 910_95xx / 950 / 950PR / 950DT (**Atlas 350 加速卡**) | - | - | - | - | `ascend_910_95xx.json` |
| **910_55xx** | - | - | - | - | `ascend_910_55xx.json` |
| **310B1~B4** | Ascend310B1.ini ~ Ascend310B4.ini | Ascend310B1~B4 | Ascend310B | - | `ascend_310b.json` |
| **310P1/P3** | Ascend310P1.ini, Ascend310P3.ini | Ascend310P1, Ascend310P3 | Ascend310P | - | `ascend_310p.json` |
| **610** / 610Lite | Ascend610.ini, Ascend610Lite.ini | Ascend610, Ascend610Lite | Ascend610 / Ascend610Lite | - | `ascend_610.json` |
| **BS9SX1A*** | BS9SX1AA.ini, BS9SX1AB.ini, BS9SX1AC.ini | BS9SX1AA~AC | BS9SX1A | - | `bs9.json` |
| **Hi3796** | Hi3796CV300ES.ini, Hi3796CV300CS.ini | Hi3796CV300ES/CS | Hi3796CV300ES/CS | - | `hi3796.json` |
| **SD3403** | SD3403.ini | SD3403 | SD3403 | - | `sd3403.json` |
| **Ascend031** | Ascend031.ini | Ascend031 | Ascend031 | - | `ascend_031.json` |
| **Ascend035*** | Ascend035.ini, Ascend035A.ini, Ascend035B.ini | Ascend035/A/B | Ascend035 | - | `ascend_035.json` |
| **AS31XM1X** | AS31XM1X.ini | AS31XM1X | AS31XM1 | - | `as31xm1x.json` |
| **Kirin*** | - | - | - | - | `kirin.json` |
| **MC6*** | - | - | - | - | `mc6x.json` |

> **注意**: 以下 INI 文件存在但暂无对应 JSON 速查表：
> - `Ascend710Vir01/02/04/08.ini` (Short: Ascend710) — 710 虚拟化系列
> - `Ascend310.ini` (Short: Ascend310) — 310 初代
> - `TSNSE.ini` / `TSNSC.ini` — TsnsE / TsnsC 系列
> - `OPTG.ini` — OPTG 系列
>
> **特别注意 910B Gen1 vs Gen2**: `Ascend910B.ini` (Short_SoC = `Ascend910`) 是 **910 初代** 的 B 变体，归入 `ascend_910.json`；而 `Ascend910B1~B4.ini` (Short_SoC = `Ascend910B`) 才是 **910B Gen2** 系列，归入 `ascend_910b.json`。

**参数来源**:
1. 从`shared`部分获取通用参数（UB、对齐、memory_rates、流水线）
2. 从`variants[检测到的型号]`获取型号特有参数（核数、频率、UB/L2大小、GM容量）

读取对应 JSON 文件：
```
references/chips/{json_file}
```

---

### Step 3: 计算derived_params

使用芯片JSON中的参数计算：

**带宽计算**:
```
带宽 = rate (Bytes/cycle) × freq (MHz) / 1000 = GB/s
```

**Vector算力计算**:
```
Vector算力 = vec_calc_size / dtype_size × freq × 2(FMA) / 1e6 = TFLOPS/core
```

**Cube算力计算**:
```
Cube算力 = cube_m × cube_n × cube_k × 2 × freq / 1e6 = TFLOPS/core
```

**Tiling 参数（用于进化优化场景）**:
```
max_tile_fp16_double_buf = (ub_size // (2 × 3 × 2)) // 16 × 16   # 双缓冲·3级流水·fp16·32B对齐
```

**字段来源映射**:
- `ddr_rate`：`memory_rates.ddr_rate`（Bytes/cycle）
- `freq_mhz`：`variants[型号].cube_freq_mhz`（MHz）
- `vec_calc_size`：`shared.vector_unit.vec_calc_size_bytes`（Bytes）
- `cube_m/n/k`：`shared.cube_unit.cube_m/n/k_size`
- `ub_size`：`variants[型号].ub_size_bytes`（Bytes）

**910_95xx 系列特殊处理**:
910_95xx 系列 CubeCore 和 VectorCore 有独立的 ddr_rate：
- CubeCore 带宽：使用 `variants[型号].ddr_rate_cube`
- VectorCore 带宽：使用 `variants[型号].ddr_rate_vector`（约为 CubeCore 的一半）

对于 Vector 算子优化场景，应使用 `ddr_rate_vector` 计算带宽上界。

---

### Step 4: 补充通用知识（如需要）

根据需要读取`references/`下的架构知识文件：
- `ai_core_architecture.md`: AI Core内部结构
- `memory_hierarchy.md`: 内存层次详解
- `pipeline_structure.md`: 流水线结构
- `formulas/tiling_and_utilization_formulas.md`: Tiling、带宽、计算利用率等定量计算公式

---

### Step 5: 输出参数

返回结构化的硬件参数数据，标注哪些参数是精确值、哪些是估算值。

**进化场景额外输出**：当被 `lingxi-dsl-evo` / `lingxi-ops-evo` 等进化 agent 调用时，额外提供以下两种输出形式：

1. **`hw_params` 结构**：用于写入 `world_model.json` 顶层 `hw_params` 字段
   ```json
   {
     "chip_model": "910B3",
     "ub_size_bytes": 196608,
     "core_num": 40,
     "peak_bw_gbps": 57.6,
     "peak_vector_tflops_per_core": 0.2304,
     "peak_cube_tflops_per_core": 14.746,
     "alignment_bytes": 32,
     "max_tile_fp16_double_buf": 16384
   }
   ```

2. **`hw_params_one_liner`**：单行摘要，供子 agent prompt 注入使用
   ```
   Chip: 910B3 | UB: 192KB | Cores: 40 | Peak BW: 57.6GB/s | Max tile(FP16,2buf): 16384 elems
   ```

## 进化流程集成点

- **调用时机**：`lingxi-dsl-evo` / `lingxi-ops-evo` 的世界模型初始化之前调用一次
- **输出去向**：写入 `world_model.json` 顶层 `hw_params` 字段
- **后续使用**：
  - 世界模型节点设计：Roofline 分析 + 具体 tile_size 建议
  - 子 agent prompt `[Hardware Specs]` 块：为 DSL 生成和 Local Refinement 提供硬件约束
  - Profiling 分析：峰值带宽/算力用于利用率计算

## 输入规范

```yaml
chip_model: string|null               # 芯片型号，如"910B3"，不填则自动检测
query_type: string|null               # 查询类别
  # full: 返回全部规格（默认）
  # memory_hierarchy: 内存层次参数
  # compute_capability: 计算能力参数
  # roofline_params: Roofline建模所需参数
  # alignment: 对齐要求
```

## 输出规范

```yaml
chip_model: string                    # 实际芯片型号
params:                               # 结构化的硬件参数对象
  # 通用参数（来自shared）
  ub_size_bytes: int                  # UB大小（bytes）
  alignment_bytes: int                # 对齐要求（bytes）
  vec_calc_size_bytes: int            # 向量宽度（bytes）

  # 型号特有参数（来自variants）
  core_num: int                       # 核数（Vector算子用 vector_core_cnt）
  cube_core_cnt: int                  # Cube核数
  freq_mhz: int                      # 频率（MHz）
  l2_size_bytes: int|null             # L2大小（bytes）
  gm_size_bytes: int|null             # GM容量（bytes）

  # 计算参数（derived_params）
  peak_bw_gbps: float                 # 峰值带宽（GB/s per core）
  peak_vector_tflops_per_core: float  # Vector峰值算力（TFLOPS/core）
  peak_cube_tflops_per_core: float    # Cube峰值算力（TFLOPS/core）
  max_tile_fp16_double_buf: int|null  # FP16双缓冲最大tile元素数（进化场景使用）

  # 参数来源标注
  _annotations:
    ub_size_bytes: exact              # exact | derived | estimated
    peak_bw_gbps: derived
    peak_cube_tflops_per_core: derived
```

## 错误处理

| 错误场景 | 处理策略 | 返回值 |
|---------|---------|--------|
| 芯片型号未指定且自动检测失败 | 明确报错，列出支持的芯片型号 | {status: "error", reason: "无法检测芯片型号", supported_chips: [...]} |
| 指定的芯片型号不在支持列表中 | 提示错误，建议相近型号 | {status: "error", reason: "不支持的芯片型号", suggestion: "..."} |
| 芯片JSON文件读取失败 | 尝试3次，仍失败则使用默认值并标注 | {status: "partial", params: {...}, _annotations: {estimated: true}} |
| shared/variants参数缺失 | 使用默认值，明确标注为estimated | {status: "partial", params: {...}, missing_params: [...]} |
| derived_params计算异常 | 记录异常，跳过计算，使用原始参数 | {status: "partial", params: {...}, derivation_failed: true} |
| npu-smi命令执行失败 | 降级到仅返回通用知识，不返回芯片特有参数 | {status: "degraded", params: {shared_only: true}, reason: "..."} |
| 参考文档读取失败（如需要） | 跳过该文档，继续返回基本参数 | {status: "partial", params: {...}, docs_unavailable: [...]} |

## 参考文档

### 架构知识
- `references/ai_core_architecture.md`: AI Core架构通用知识
- `references/memory_hierarchy.md`: 内存层次详解
- `references/pipeline_structure.md`: 流水线结构与气泡成因
- `references/formulas/tiling_and_utilization_formulas.md`: 基于硬件参数的定量计算公式

### 芯片规格文件索引

| 系列 | 文件 | 典型型号 |
|------|------|---------|
| 910B (Atlas A2) | `references/chips/ascend_910b.json` | 910B, 910B1, 910B2, 910B2C, 910B3, 910B4, 910B4-1 |
| 910初代 | `references/chips/ascend_910.json` | 910A, 910PremiumA, 910ProA, 910ProB |
| 910_93xx (Atlas A3) | `references/chips/ascend_910_93xx.json` | 910_9351, 910_9352, 910_9354, 910_9356 |
| 910_95xx (Atlas 350 加速卡) | `references/chips/ascend_910_95xx.json` | 910_950z, 910_9572~9599 (8/28/32/36核); 950/950PR/950DT |
| 910_55xx | `references/chips/ascend_910_55xx.json` | 910_5561, 910_5562, 910_5564 |
| 310B | `references/chips/ascend_310b.json` | 310B1, 310B2, 310B3, 310B4 |
| 310P | `references/chips/ascend_310p.json` | 310P1, 310P3, 310P5, 310P7 |
| 610 | `references/chips/ascend_610.json` | 610, 610Lite |
| BS9 | `references/chips/bs9.json` | BS9SX系列 |
| Kirin | `references/chips/kirin.json` | Kirin系列 |
| Hi3796 | `references/chips/hi3796.json` | Hi3796CV300系列 |
| SD3403 | `references/chips/sd3403.json` | SD3403 |
| Ascend031 | `references/chips/ascend_031.json` | Ascend 031 |
| Ascend035 | `references/chips/ascend_035.json` | Ascend 035系列 |
| AS31XM1X | `references/chips/as31xm1x.json` | AS31XM1X |
| MC6x | `references/chips/mc6x.json` | MC6x系列 |
