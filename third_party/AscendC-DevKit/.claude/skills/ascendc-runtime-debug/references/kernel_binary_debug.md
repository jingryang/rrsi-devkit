# Kernel 二进制与构建系统调试

## 症状-根因速查

| 症状 | 最可能根因 | 详细步骤 |
|------|-----------|---------|
| 修改Kernel代码后输出不变 | 二进制缓存未清理 / 安装了旧包 | [流程1](#流程1修改后输出不变的调试) |
| `561003 FIND_KERNEL_ERROR` | TilingKey 与 SEL 声明不匹配 | [流程2](#流程2tilingkey--sel-不匹配) |
| 特定 dtype 返回 361001 | SEL 缺少该 dtype 条目 | [流程3](#流程3sel-dtype-条目缺失) |
| `BinaryGetFunctionByEntry failed, funcEntry=N` 但 binary 已安装 | kernelList 尾缀（tilingKey）与调用不匹配 / config json 别名缺失 | [流程2 readelf 核对](#readelf-静态核对对-361001--binarygetfunctionbyentry-的最快证据) + 命名转换见 ascendc-op-dev-coding-regbase 的 op-name-conversion.md |
| 多版本 vendor 包冲突 | vendors/ 和 opp/vendors/ 同时存在 | [流程4](#流程4多版本-vendor-包冲突) |
| opParaSize 不匹配 | TilingData struct 大小 ≠ JSON opParaSize | [流程5](#流程5opparasize-不匹配) |

---

## 流程1：修改后输出不变的调试

### 检查点1：编译缓存

```bash
# 1. 清理编译缓存
rm -rf build/
# 注意：仅清理 build 目录可能不够，opc 编译器有独立缓存

# 2. 检查 opc 编译器缓存（如果存在）
ls -la $HOME/atc_data/kernel_cache/ 2>/dev/null
# 如果存在且包含当前算子 → 删除对应条目

# 3. 完全清理后重新构建
rm -rf build/ $HOME/atc_data/kernel_cache/
bash build.sh
```

### 检查点2：二进制文件是否更新

> 产物路径提示：kernel binary 不在 `build/op_kernel/`（那是**源码**目录）。真实位置取决于工程：
> 官方 ASCENDC 工程在 `${CMAKE_INSTALL_PREFIX}/fatbin/<target>/`（默认 `build_out/fatbin/`）；
> cann-bench ACLNN 工程在 `build/all_kernels/binary/ascend950/<op_file>/`；已安装到 OPP 后是
> `kernel/ascend950/<op_file>/<OpType>_<hash>.o`。下方命令按实际工程调整路径。

```bash
# 对比构建前后的 sha256（核心验证手段）
# 官方工程：build_out/fatbin/；cann-bench 工程：build/all_kernels/binary/ascend950/
sha256sum build_out/fatbin/*/*.o 2>/dev/null
sha256sum build/all_kernels/binary/ascend950/*/*.o 2>/dev/null
# 已安装到 OPP 后：
sha256sum $ASCEND_OPP_PATH/vendors/*/op_impl/ai_core/tbe/kernel/ascend950/*/*.o 2>/dev/null
# 或
sha256sum build/out/*/op_kernel/lib/*.so 2>/dev/null

# 如果 edit 后 sha256 不变 → 编译器缓存问题，按检查点1处理
# 如果 sha256 变了但运行结果不变 → 检查点3
```

### 检查点3：是否安装了正确的包

```bash
# 查看 install 脚本实际安装到哪里
grep -n "cp\|install\|mv" build.sh

# 检查已安装的二进制的 sha256
sha256sum $ASCEND_OPP_PATH/vendors/<vendor_name>/op_impl/ai_core/tbe/op_kernel/lib/*.so

# 对比构建产物和安装产物的 sha256 是否一致
# 不一致 → install 脚本问题
```

### 检查点4：是否清理了旧安装包

```bash
# 完全卸载旧包
rm -rf $ASCEND_OPP_PATH/vendors/<vendor_name>/
rm -rf $ASCEND_HOME_PATH/vendors/<vendor_name>/

# 重新安装新包
bash build.sh
```

---

## 流程2：TilingKey / SEL 不匹配

### 核心概念

opc 编译器为每个 `(DTYPE, AXIS_MODE, LOAD_MODE, ...)` 模板参数组合编译**独立的 kernel 变体**，
通过 `kernelList[].kernelName` 尾缀区分。**尾缀是 tilingKey（`EncodeTilingKey` 编码值），不是
dtype 枚举**——dtype 已在二进制文件名（编译变体）中表达，tilingKey 是模板参数的按位拼接结果：

| 尾缀 | 含义 |
|------|------|
| `_0` / `_1` / `_27` | **单 DTYPE 模板参数**时的特例：tilingKey = dtype 枚举值（fp32=0 / fp16=1 / bf16=27） |
| `_1000` / `_2000` | **多模板参数**（UINT 等）时：`tilingKey |= encodeVal << totalBits` 按位拼接的编码值，与 dtype 无关 |

> 例：built-in `AddRmsNorm_bf16_high_performance.o` 内 `FUNC GLOBAL ..._1000` / `..._2000`
> 两个函数（`FUNCTION_ENTRY` meta 同为 1000/2000），且 bf16/fp16/fp32 三个变体共享同一尾缀组——
> 证明 tilingKey 与 dtype 正交。命名转换规则见
> [`references/op-name-conversion.md`](../../ascendc-op-dev-coding-regbase/references/op-name-conversion.md)。

运行时框架根据调用时实际模板参数计算 tilingKey 查找匹配的 kernel 符号，**找不到 → 361001 /
`BinaryGetFunctionByEntry failed`**。

### 必须对齐的 3 个位置

```
位置1: tiling_key.h — SEL 声明
  ↓
位置2: tiling.cpp — Host 侧传递模板参数实参（ASCENDC_TPL_SEL_PARAM）
  ↓
位置3: kernel 入口 — GET_TILING_KEY 取值
  ↓
opc 编译器自动生成 kernelList 尾缀（tilingKey）
```

### readelf 静态核对（对 361001 / BinaryGetFunctionByEntry 的最快证据）

> 路径按实际工程调整（见「检查点2」的产物路径提示）：官方工程 `build_out/fatbin/<target>/`、
> cann-bench 工程 `build/all_kernels/binary/ascend950/<op_file>/`、已安装 OPP
> `kernel/ascend950/<op_file>/`。

```bash
# 1. 看 .o 内函数符号尾缀（tilingKey）——与 json kernelList 逐字一致才可加载
readelf -sW <路径>/<OpType>_<hash>.o | grep "FUNC GLOBAL"

# 2. 看 FUNCTION_ENTRY（msobjdump 解 .ascend.meta）——BinaryGetFunctionByEntry 的 funcEntry 号
msobjdump --dump-elf <路径>/<OpType>_<hash>.o | grep -E "FUNCTION_ENTRY|KERNEL_TYPE"

# 3. 看入口参数总大小——与 json parameters 数组长度自洽（GM_ADDR×8，含 tiling 时多 1）
readelf -x __CCE_KernelArgSize <路径>/<OpType>_<hash>.o
```

核对逻辑：符号尾缀含 host 侧的 tilingKey → 编译产物与调用匹配；缺符号 → 该组合未编译（SEL 缺
条目，见流程3）；符号在但 funcEntry 失败 → config json 别名/OPP 安装问题（见
`ascendc-op-dev-coding-regbase` skill 的 `op-name-conversion.md`）。

### 常见错误

**错误 A：SEL 缺少 dtype**

```cpp
// ❌ 错误：只声明了 float32，fp16/bf16 调用时 361001
ASCENDC_TPL_DATATYPE_DECL(DTYPE, C_DT_FLOAT)

// ✅ 正确：声明全部 3 种 dtype，绑定 input[0] 类型
ASCENDC_TPL_DATATYPE_DECL(DTYPE, C_DT_FLOAT, C_DT_FLOAT16, C_DT_BF16, ASCENDC_TPL_INPUT(0))
```

> `ASCENDC_TPL_INPUT(0)` 将 DTYPE 模板参数绑定到 input[0] 的实际类型，确保 opc 为每种输入 dtype 生成独立 binary。

**错误 B：Host 侧 hardcode dtype**

```cpp
// ❌ 错误：硬编码为 float32，fp16/bf16 传错了 dtype 值
uint32_t dType = static_cast<uint32_t>(ge::DT_FLOAT);

// ✅ 正确：使用实际输入 dtype
uint32_t dType = static_cast<uint32_t>(dataType);
```

> `ge::DT_FLOAT=0`, `ge::DT_FLOAT16=1`, `ge::DT_BF16=27`（必须与 `C_DT_*` 值一致）。

**错误 C：缺少某个 TilingKey 组合的 SEL 条目**

```cpp
// ❌ 错误：TK1 (TAIL_AR_COL_SPLIT) 缺少 bf16 条目
ASCENDC_TPL_ARGS_SEL(
    ASCENDC_TPL_DATATYPE_SEL(DTYPE, C_DT_FLOAT),
    ASCENDC_TPL_UINT_SEL(LOAD_MODE, ASCENDC_TPL_UI_LIST, 1))

// ✅ 正确：为所有 dtype 添加对应 LOAD_MODE 的条目
ASCENDC_TPL_ARGS_SEL(
    ASCENDC_TPL_DATATYPE_SEL(DTYPE, C_DT_FLOAT),
    ASCENDC_TPL_UINT_SEL(LOAD_MODE, ASCENDC_TPL_UI_LIST, 1))
ASCENDC_TPL_ARGS_SEL(
    ASCENDC_TPL_DATATYPE_SEL(DTYPE, C_DT_FLOAT16),
    ASCENDC_TPL_UINT_SEL(LOAD_MODE, ASCENDC_TPL_UI_LIST, 1))
ASCENDC_TPL_ARGS_SEL(
    ASCENDC_TPL_DATATYPE_SEL(DTYPE, C_DT_BF16),
    ASCENDC_TPL_UINT_SEL(LOAD_MODE, ASCENDC_TPL_UI_LIST, 1))
```

> 注意：`ASCENDC_TPL_ARGS_SEL` 的参数必须使用内部选择宏（如 `ASCENDC_TPL_DATATYPE_SEL`、`ASCENDC_TPL_UINT_SEL`）包装，不能直接传裸值。

### 验证方法

```bash
# 查看构建后的 JSON 中的 kernelList（kernelName 尾缀 = tilingKey）
# 将 <op_file> 替换为实际算子目录；目录下每个 dtype 变体一个 json（如 fp16/bf16/fp32）
# 路径按实际工程调整（官方工程 build_out/fatbin/<target>/，cann-bench 工程
# build/all_kernels/binary/ascend950/<op_file>/，已安装 OPP kernel/ascend950/<op_file>/）
python3 -c "
import json, glob, sys
for f in glob.glob('build/all_kernels/binary/ascend950/<op_file>/*.json'):
    data = json.load(open(f))
    names = [k.get('kernelName', '?') for k in data.get('kernelList', [])]
    tails = [n.rsplit('_', 1)[-1] for n in names]
    print(f, '-> tilingKeys:', tails)
"

# 检查：单 DTYPE 参数算子应看到 _0, _1, _27 这类尾缀（支持 3 种 dtype 时）
```

---

## 流程3：SEL dtype 条目缺失

症状：特定 dtype + axis 组合返回 361001，其他组合正常。

排查步骤：
1. 确认 `tiling_key.h` 中该 TilingKey 是否有对应 dtype 的 `ASCENDC_TPL_ARGS_SEL` 条目
2. 确认 `tiling.cpp` 中 `ASCENDC_TPL_SEL_PARAM` 传递的 dtype 值与 SEL 一致
3. 确认构建后的 JSON 包含对应 kernelList 后缀

---

## 流程4：多版本 vendor 包冲突

### 问题场景

CANN 框架按以下顺序查找算子包：
1. `$ASCEND_OPP_PATH/vendors/<vendor_name>/` (opp 优先级高)
2. `$ASCEND_HOME_PATH/vendors/<vendor_name>/` (home 兜底)

如果两个位置都安装了同一算子：
- opp 版本被优先加载
- home 版本的旧配置可能被意外激活

### 排查方法

```bash
# 1. 列出所有安装位置
find $ASCEND_OPP_PATH/vendors/ -maxdepth 2 -type d 2>/dev/null
find $ASCEND_HOME_PATH/vendors/ -maxdepth 2 -type d 2>/dev/null

# 2. 检查每个位置的 kernel JSON（关键差异点）
for dir in $(find $ASCEND_OPP_PATH/vendors/ $ASCEND_HOME_PATH/vendors/ -name "<vendor_name>" -type d 2>/dev/null); do
    echo "=== $dir ==="
    python3 -c "
import json, glob, sys
for f in glob.glob('$dir/op_impl/ai_core/tbe/op_kernel/*.json'):
    d = json.load(open(f))
    names = [k.get('kernelName', '?') for k in d.get('kernelList', [])]
    print(f'  {f.split(\"/\")[-1]}: kernelList tails = {[n.rsplit(\"_\", 1)[-1] for n in names]}')
"
done

# 3. 关键差异检查：
#    - 不同版本的 opFile 名可能不同 (arch22 vs arch32)
#    - 不同版本的 dtype 列表可能不同
#    - 不同版本的 kernelList 条目数可能不同
```

### 修复方法

```bash
# 完全清理后重新安装
rm -rf $ASCEND_OPP_PATH/vendors/<vendor_name>/
rm -rf $ASCEND_HOME_PATH/vendors/<vendor_name>/
bash build.sh
# 验证只有一个安装位置
find $ASCEND_OPP_PATH/vendors/ $ASCEND_HOME_PATH/vendors/ -name "<vendor_name>" -type d
```

---

## 流程5：opParaSize 不匹配

### 问题描述

Kernel JSON 中 `opParaSize` 字段由 opc 编译器自动计算，可能与 `sizeof(TilingData)` 不同（编译器可能添加对齐 padding）。

### 排查方法

```cpp
// 在 tiling.cpp 或测试代码中添加
printf("sizeof(TilingData) = %zu\n", sizeof(TilingData));
// 对比 JSON 中 opParaSize 的值
```

### 应对策略

- **小幅差异**：可能是编译器添加的对齐 padding，通常不影响功能
- **大幅差异**：检查 struct 成员是否遗漏，或存在多余的字段
- **强制对齐**：如果确实需要匹配，可尝试 `#pragma pack` 或调整成员顺序

### 验证

```bash
# 从 JSON 提取 opParaSize（路径按实际工程，见「检查点2」产物路径提示）
grep '"opParaSize"' build/all_kernels/binary/ascend950/<op_file>/*.json

# 对比 sizeof
# 在 kernel 入口添加：
# printf("sizeof TilingData = %d\n", sizeof(TilingData));
```

---

## 调试工具速查

| 工具/命令 | 用途 |
|----------|------|
| `sha256sum build_out/fatbin/*/*.o build/all_kernels/binary/ascend950/*/*.o` | 验证二进制是否更新（按实际工程选路径） |
| `cat build/all_kernels/binary/ascend950/<op_file>/*.json \| grep kernelList` | 检查生成的所有 kernel 变体 |
| `readelf -sW <OpType>_<hash>.o \| grep "FUNC GLOBAL"` | 看函数符号尾缀（tilingKey），对 kernelList 逐字核对 |
| `readelf -x __CCE_KernelArgSize <OpType>_<hash>.o` | 看 kernel 入口参数总大小（GM_ADDR×8） |
| `msobjdump --dump-elf <OpType>_<hash>.o` | 解 `.ascend.meta`：FUNCTION_ENTRY / KERNEL_TYPE |
| `find $ASCEND_OPP_PATH/vendors -name "*.so"` | 检查已安装的二进制 |
| `find $ASCEND_HOME_PATH/vendors -name "*.so"` | 检查兜底位置的二进制 |
| `rm -rf $HOME/atc_data/kernel_cache/` | 清理 opc 编译器缓存 |
| `rm -rf build/` | 清理构建产物 |
