# 算子名：PascalCase / snake_case / opFile / 二进制产物 的关系（唯一权威）

> 面向：s4-coding（写 def.cpp / kernel 入口名 / opFile.value）、s5-compile（诊断
> `BinaryGetFunctionByEntry failed`）、精度/性能调试（readelf 核对编译产物）。CANN 工具链各
> 环节对同一个算子名使用**不同字面量**，不一致即断链——本文件是这几者关系的唯一权威源，
> 遇命名疑问先查这里。
>
> 背景：L1 `docs/plan/codegen-s5-deploy-contract/01-problems.md` P2——opInterface 与
> opFile.value 不一致 → kernel config json 别名缺失 → runtime 找不到 kernel。

## 三个位点 + 二进制命名的第四个正交维度

| 位点 | 命名 | 例子 | 由谁决定 / 作用 |
|------|------|------|----------------|
| **opType（算子名）** | **PascalCase（大驼峰）** | `MoeGatingTopKSoftmax` | OpDef 注册 / runtime 查找 kernel 的裸名（错误日志里的 `kernel name: MoeGatingTopKSoftmax`） |
| **opInterface / kernel 入口函数名** | **snake_case（全小写下划线）** | `moe_gating_top_k_softmax` | kernel 源码的 C 入口函数名；由 opType 按「PascalCase → snake_case」转换得到 |
| **opFile.value（config json 文件名）** | **snake_case（含下划线）** | `moe_gating_top_k_softmax` | def.cpp 中 `ExtendCfgInfo("opFile.value", "...")`；决定 `kernel/config/ascend950/<name>.json` 的文件名 |
| **二进制产物名（`.o`/`.json`）** | `opType_<dtype/变体>_<implMode>` | `MoeGatingTopKSoftmax_15a99...`、`AddRmsNorm_bf16_high_performance` | 编译变体名（dtype、implMode 等）；`kernelList[].kernelName` 尾缀是**tilingKey**，见下节 |

> **两个正交维度**：二进制**文件名**表达「编译变体」（dtype/implMode，如 `_bf16_high_performance`、
> 自定义 hash）；**函数符号尾缀**表达「模板参数组合的 tilingKey 编码」。二者独立——同一
> 变体的不同 tilingKey 共用一个 `.o` 文件、不同函数符号。

## kernelList 尾缀 = tilingKey（EncodeTilingKey 编码值，非 dtype 枚举）

`.json` 的 `kernelList[].kernelName` 与 `.o` 内函数符号尾缀（readelf `FUNC GLOBAL` 符号名）是
**同一个 tilingKey**，由 `AscendC::EncodeTilingKey`（`template_argument.h` 的
`FastEncodeTilingKeyDirect`）把全部 ASCENDC_TPL 模板参数**按位拼接**得到：

```
tilingKey |= (encodeVal << totalBits);  totalBits += bitWidth
# DTYPE 参数：encodeVal = 原始 dtype 值；UINT 参数：encodeVal = 在 DECL 值列表中的索引
```

**例 1 — 单 DTYPE 参数**（如简单算子 `MoeGatingTopKSoftmax`）：tilingKey 恰好 = dtype 枚举值
（fp32=0 / fp16=1 / bf16=27），符号尾缀 `_0`/`_1`/`_27`。

**例 2 — 多模板参数**（如 built-in `AddRmsNorm_*_high_performance`）：tilingKey 是多个参数按位
组合的编码值，**不是 dtype 值**。实测 readelf 符号尾缀为 `_1000`/`_2000`（`FUNCTION_ENTRY`
meta 同为 1000/2000），与 dtype 无关（bf16/fp16/fp32 三个变体共享同一尾缀组）。

**定位意义**：`BinaryGetFunctionByEntry failed, funcEntry=N, tiling key: M` 里的 `N`/`M`
都是这个 tilingKey——先看 `kernelList[].kernelName` 尾缀与 host 侧 `ASCENDC_TPL_SEL_PARAM`
实参编码是否一致，再用 readelf 核对 `.o` 内函数符号存在与否。

## PascalCase → snake_case 转换规则（CANN 权威，已被真实 run 验证）

**规则**：在每个**大写字母前**插入下划线（首字符除外），然后整体转小写。
等价于 Python：

```python
import re
def to_snake(name: str) -> str:
    return re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()
```

| PascalCase（opType） | snake_case（opInterface / 期望的 opFile.value） |
|---------------------|------------------------------------------------|
| `Add` | `add` |
| `Sqrt` | `sqrt` |
| `MhcSinkhorn` | `mhc_sinkhorn` |
| `MoeGatingTopKSoftmax` | `moe_gating_top_k_softmax` |
| `AdaptiveAvgPool3D` | `adaptive_avg_pool3_d` |

**关键边界**（按此规则，不靠记忆/直觉）：
- **缩写连续大写**：每个大写字母前都插下划线。`TopK` → `top_k`（不是 `topk`）、
  `TopKSoftmax`（K 与 S 相邻两个大写）→ `top_k_softmax`。注意 `Softmax` 中 S 是首字母、
  其后无大写 → `softmax`（不是 `soft_max`）。
- **数字 + 大写**：数字保留，其后的大写字母前插下划线。`3D` → `3_d`、`Pool3D` → `pool3_d`。
- 这就是为什么 `AdaptiveAvgPool3D → adaptive_avg_pool3_d`（带 `_d`），而不是
  `adaptive_avg_pool_3d`——**手写时最容易错的就是这类缩写/数字边界**。

## 三者必须一致（断链后果）

- **opInterface（kernel 入口名）必须等于 opType 按上述规则转换的结果**：
  `MoeGatingTopKSoftmax` → 入口名 `moe_gating_top_k_softmax`。
- **opFile.value 必须与 opInterface 同形（含下划线）**。若 opFile.value 写成**不含下划线的
  紧凑名**（如 `moegatingtopksoftmax`），编译工具只生成 `moegatingtopksoftmax.json`，而 runtime
  按 opInterface 名查 `moe_gating_top_k_softmax.json` → 缺别名 →
  `BinaryGetFunctionByEntry failed, funcEntry=N, tiling key: M`。
- **修复**：def.cpp 中 `ExtendCfgInfo("opFile.value", "<opInterface 名含下划线>")`，重编译后
  config 目录会出现**两个 json**（原名 + 别名，内容相同）。
- **诊断速查**：对比同 OPP 中可正常运行的算子的 config 目录——正常算子有两个 json
  （含下划线的 opInterface 名 + 别名），异常算子只有一个（无下划线紧凑名）。

## 反方向：snake_case → PascalCase（如从 proto/requirement 的 op 名推导 opType）

按下划线分段，每段首字母大写后拼接：`moe_gating_top_k_softmax` → `MoeGatingTopKSoftmax`。
**注意**：此反转换无法唯一还原缩写边界（`top_k` 可能源自 `TopK` 也可能源自 `Top_K`），
故**不要**从 snake_case 反向推导 opType 的缩写拼写——opType 的权威来源是需求/OpDef 声明，
不是转换推导。

## 使用提醒（§1.12）

- 以上规则基于**结构信号**（大小写/下划线/数字位置），不认具体算子身份——任何新算子
  只需按规则生成，无需特判。
- 生成 def.cpp 时用工具函数（如上面的 `to_snake`）自动生成 opInterface 与 opFile.value，
  禁止手写拼字面量（避免 `TopK→topk`、`3D→3_d` 这类边界手误）。

## 用 readelf 核对二进制产物（对 `BinaryGetFunctionByEntry failed` 的静态证据）

> Ascend kernel `.o` 是 Ascend 专用指令集（AIV 向量核，Machine 0x1029）的 ELF **EXEC**
> 文件，不是普通可重定位目标文件。readelf 各字段直接对应 runtime 加载 kernel 的环节。
> 实测示例：`AddRmsNorm_bf16_high_performance.o`、`MoeGatingTopKSoftmax_15a99....o`。

| readelf 观察 | 对应产物/字段 | 运行时意义 |
|---|---|---|
| `ELF 头: EXEC + Machine 0x1029` | — | AIV 指令集，runtime 直接 `BinaryGetFunctionByEntry` 取函数，不做常规链接 |
| `FUNC GLOBAL <symbol>`（`.symtab`） | `kernelList[].kernelName` | **函数入口**，符号名 = `<opType>_<编译变体>_<tilingKey>`；与 json 逐字一致才可加载 |
| `.ascend.meta.<符号名>`（NOTE 0x200） | kernelName | per-kernel 元数据 section，符号名 = 上面那个 |
| `FUNCTION_ENTRY`（msobjdump 解 `.ascend.meta`） | 符号尾缀 tilingKey | **funcEntry 号**——`BinaryGetFunctionByEntry failed, funcEntry=N` 里的 N 就是它 |
| `__CCE_KernelArgSize`（NOTE 0x4） | kernel 入口 GM 参数总数 | = GM_ADDR 数 × 8（含 tiling）；与 json `parameters` 数组长度应一致（不含 tiling 少 1） |
| `.rela.text` 重定位 → `_ZN7AscendC8Internal*` / `g_vecTPipePtr` | — | 依赖 AscendC runtime 全局，加载期绑定；缺失会 load 失败 |
| `.comment`：`LLD 15.0.5 + clang 15.0.5` | — | 编译工具链版本（A5 生成） |

**校验命令**（s5 排查用；`<op>` 指实际 `.o` 路径——官方工程 `build_out/fatbin/<target>/`、
cann-bench 工程 `build/all_kernels/binary/ascend950/<op_file>/`、已安装 OPP
`kernel/ascend950/<op_file>/`）：
```bash
readelf -sW <op>.o | grep -E "FUNC GLOBAL"      # 看函数符号尾缀（tilingKey）
readelf -x __CCE_KernelArgSize <op>.o           # 看入口参数大小
msobjdump --dump-elf <op>.o                      # 解 .ascend.meta：FUNCTION_ENTRY / KERNEL_TYPE
```

**用法**：当 smoke 报 `BinaryGetFunctionByEntry failed, funcEntry=N, tiling key: M` 时，
用 readelf 核对——① `.o` 内 `FUNC GLOBAL` 符号尾缀是否含 `_<M>`；② `FUNCTION_ENTRY` 是否 =
N；③ `__CCE_KernelArgSize` 与 json `parameters` 是否自洽。三者自洽 → 问题在 config json 别名/
OPP 安装（见上文「三者必须一致」）；不自洽 → 编译产物与入口签名不符，回编译侧查。
