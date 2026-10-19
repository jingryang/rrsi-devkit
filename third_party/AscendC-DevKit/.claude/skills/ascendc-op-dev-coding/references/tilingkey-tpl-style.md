# AscendC 模板化 TilingKey 写法详解（ASCENDC_TPL）

> 范围：介绍 **ASCENDC_TPL** 模板参数化 TilingKey 机制。本文优先把“这个特性是干什么的、为什么这样设计、每个宏到底在做什么”讲清楚；真实算子参考放在文末附录，供需要时对照。

---

## 1. 为什么需要 ASCENDC_TPL？

### 1.1 算子面临的变体问题

同一个算子在真实网络中往往要面对很多种“输入差异”：

- 数据类型不同：fp16、fp32、bf16、int8 等；
- 形状/维度不同：1D、2D、4D、8D，RANK 会影响数组维度和结构体大小；
- 实现策略不同：单缓冲还是双缓冲、是否把 fp16/bf16 升精到 fp32 计算、是否按组处理；
- 数据排布不同：interleaved 或 plain。

这些差异如果全部用运行时 `if` 分支处理，会带来运行时指令开销，且 buffer 大小、API 选型等必须按“最坏情况”预留，浪费内存和算力；如果完全拆成多个独立 kernel 文件，又会造成文件爆炸、维护困难，而且 CANN 图编译时希望同一个 `op_type` 只对应一个 binary。

**ASCENDC_TPL 的解决思路**：把变体差异抽象成 C++ 模板参数，编译器自动实例化出多个 kernel 函数并打包到同一个 binary 里，运行时通过 `TilingKey` 选择调用哪一个。

### 1.2 一句话总结

> ASCENDC_TPL = **把影响 kernel 实现的关键差异提升为模板参数**，由 host 在运行时通过 `TilingKey` 选择一个已经编译好的模板实例执行。

---

## 2. 核心概念与完整数据流

### 2.1 四个核心概念

| 概念 | 说明 | 典型位置 |
|------|------|----------|
| **模板参数** | Kernel 入口 `template<...>` 里的参数，如 `D_T`、`BUFFER_MODE`、`RANK`。 | `tiling_key.h` 中声明 |
| **TilingData / TilingStruct** | 普通 C++ `struct`，存放 host 计算的分核、分块、attr 等**运行时参数**。 | `*_tiling_data.h` |
| **TilingKey** | 一个 `uint64_t`，把模板参数值编码进位域。host 设置它，runtime 用它选择模板实例。 | host `TilingFunc` 中设置 |
| **模板组合选择表** | 告诉编译器“哪些模板参数组合需要生成实例”。 | `tiling_key.h` 中 `ASCENDC_TPL_SEL` |

### 2.2 完整数据流

```
┌─────────────────────────────────────────────────────────────────┐
│  Host 侧（Python/C++ Tiling 函数）                                │
│  1. 读 shape/dtype/attr                                          │
│  2. 计算 TilingData 字段（分核、分块、workspace 等）              │
│  3. 决定模板参数值（dType、bufferMode、needUpcast、rank...）      │
│  4. ASCENDC_TPL_SEL_PARAM(ctx, ...) → 编码成 uint64_t TilingKey │
│  5. ctx->SetBlockDim(...)                                        │
└────────────────────────────┬────────────────────────────────────┘
                             │ TilingKey
┌────────────────────────────▼────────────────────────────────────┐
│  离线编译阶段（compiler）                                        │
│  1. 读 tiling_key.h 的 ASCENDC_TPL_ARGS_DECL                     │
│  2. 按 ASCENDC_TPL_SEL 穷举所有合法组合                          │
│  3. 为每个组合实例化一个 kernel 模板函数                         │
│     template <D_T, BUFFER_MODE, NEED_UPCAST> my_op(...)          │
│  4. 每个实例对应一个唯一 TilingKey                               │
└────────────────────────────┬────────────────────────────────────┘
                             │ 编译产物（一个 binary，多个模板实例）
┌────────────────────────────▼────────────────────────────────────┐
│  Runtime 执行阶段                                                │
│  1. 根据 host 下发的 TilingKey 选择匹配的模板实例                │
│  2. kernel 内用模板参数做 if constexpr 分支                      │
│  3. 通过 GET_TILING_DATA_WITH_STRUCT 把 tiling 字节流解析成 struct│
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 关键理解

- **模板参数的值来自 host 的 TilingKey**，而不是来自 TilingData struct。
- **TilingData struct 里放的是运行时计算的数值**（如 `totalNum`、`blockFactor`），模板参数只是用来决定走哪条编译期分支。
- 一个 kernel 入口可以**同时**有模板参数和 TilingData：模板参数决定“用哪种实现”，TilingData 决定“这次跑多少数据”。

---

## 3. TilingKey 位域编码原理

`TilingKey` 是一个 64 位无符号整数。ASCENDC_TPL 会按 `ASCENDC_TPL_ARGS_DECL` 中参数声明的顺序，把每个参数的值依次放入位域。

### 3.1 位域排列规则

- 参数顺序 = 位域从低到高的排列顺序。
- 每个参数占用 `bitWidth` 位。
- 所有参数位宽之和 ≤ 64。
- dtype 参数直接放入 dtype 枚举值；uint 参数先映射到声明列表中的下标，再放下标。

### 3.2 示例

假设声明如下：

```cpp
ASCENDC_TPL_ARGS_DECL(MyOp,
    ASCENDC_TPL_DATATYPE_DECL(D_T, C_DT_FLOAT16, C_DT_FLOAT, C_DT_BF16, ASCENDC_TPL_INPUT(0)),
    ASCENDC_TPL_UINT_DECL(BUFFER_MODE, 8, ASCENDC_TPL_UI_LIST, 0, 1),
    ASCENDC_TPL_UINT_DECL(NEED_UPCAST, 8, ASCENDC_TPL_UI_LIST, 0, 1));
```

则 TilingKey 布局为：

| 参数 | 位宽 | 取值说明 | 放置值 |
|------|------|----------|--------|
| `D_T` | 8 | dtype 枚举值 | `ge::DT_FLOAT16` 等 |
| `BUFFER_MODE` | 8 | 候选列表 `[0, 1]`，放索引 | `0` 或 `1` |
| `NEED_UPCAST` | 8 | 候选列表 `[0, 1]`，放索引 | `0` 或 `1` |

对应的 TilingKey：

```
[63 ... 24 | 23..16 NEED_UPCAST | 15..8 BUFFER_MODE | 7..0 D_T ]
```

注意：

- `D_T` 直接放 dtype 枚举值，**不是** `C_DT_FLOAT16` 在列表中的下标。
- `BUFFER_MODE` 放的是候选列表中的下标：如果选 `0` 放下标 `0`，选 `1` 放下标 `1`。
- 若 host 传入的值不在 `ASCENDC_TPL_UINT_DECL` 候选列表中，`GET_TPL_TILING_KEY` 会返回 `INVALID_TILING_KEY`（全 1）。

---

## 4. 同一份 `tiling_key.h` 的三次编译

理解 ASCENDC_TPL 必须意识到：**`tiling_key.h` 会在三种不同的编译阶段被包含，每次宏展开不同**。

| 阶段 | 编译目标 | 宏开关 | `ASCENDC_TPL_ARGS_DECL` 展开成 | `ASCENDC_TPL_SEL` 展开成 |
|------|----------|--------|-------------------------------|---------------------------|
| 预编译/编译器解析 | 让 CANN 工具链读取模板声明与组合 | `ASCENDC_TPL_PRE` | `@@ASCENDC_TPL_ARGS_DECL_xxx@@ = {...}` 这类标记 | `@@ASCENDC_TPL_LISTS@@ = {...}` 这类标记 |
| Host 编译 | 生成 host 侧的 TilingKey 编码 | 无 `ASCENDC_TPL_PRE/KERNEL` | `static TilingDeclareParams g_tilingDeclareParams{...}` | `static TilingSelectParams g_tilingSelectParams{...}`（仅调试态） |
| Kernel 编译 | 实际编译 kernel，此时这些宏已无意义 | `ASCENDC_TPL_KERNEL` | 空 | 空 |

这就是为什么要写 `ASCENDC_TPL_ARGS_DECL` / `ASCENDC_TPL_SEL` / `GET_TPL_TILING_KEY` / `ASCENDC_TPL_SEL_PARAM`：

- `ARGS_DECL` 同时给**工具链**（读参数定义）和 **host**（读位宽和候选值）使用。
- `SEL` 主要给**工具链**读，告诉它需要实例化哪些组合。
- `GET_TPL_TILING_KEY` / `ASCENDC_TPL_SEL_PARAM` 给 **host** 使用，把运行时值编码成 key。

---

## 5. 主要宏说明

### 5.1 `ASCENDC_TPL_ARGS_DECL(OpName, ...)`

声明本算子的模板参数列表，同时决定 TilingKey 位域编码顺序。

```cpp
ASCENDC_TPL_ARGS_DECL(MyOp,
    ASCENDC_TPL_DATATYPE_DECL(D_T, C_DT_FLOAT16, C_DT_FLOAT, C_DT_BF16, ASCENDC_TPL_INPUT(0)),
    ASCENDC_TPL_UINT_DECL(BUFFER_MODE, 8, ASCENDC_TPL_UI_LIST, 0, 1),
    ASCENDC_TPL_UINT_DECL(NEED_UPCAST, 8, ASCENDC_TPL_UI_LIST, 0, 1));
```

参数类型宏：

| 宏 | 含义 | 参数说明 |
|----|------|----------|
| `ASCENDC_TPL_DATATYPE_DECL(name, ...)` | dtype 模板参数 | 参数名 + 候选 dtype 常量；`ASCENDC_TPL_INPUT(n)` 是哨兵值 `100000000+n`，表示允许取第 n 个输入的实际 dtype |
| `ASCENDC_TPL_UINT_DECL(name, bw, flag, ...)` | 无符号整数模板参数 | 参数名、位宽、列表/范围标志、候选值 |
| `ASCENDC_TPL_BOOL_DECL(name, ...)` | bool 模板参数 | 参数名、候选值 `0/1` |
| `ASCENDC_TPL_FORMAT_DECL(name, ...)` | 数据格式模板参数 | 较少用 |

`ASCENDC_TPL_INPUT(n)` 重点说明：

- 它**不是**一个 dtype 常量，而是一个占位标记。
- 出现在声明里表示“这个 dtype 参数也可以等于第 n 个输入的 dtype”。
- host 在 `ASCENDC_TPL_SEL_PARAM` 中仍然要传真实的 dtype 枚举值，例如 `static_cast<uint32_t>(inputInfo.dataType)`。

标志说明：

- `ASCENDC_TPL_UI_LIST`：后面跟离散列表。
- `ASCENDC_TPL_UI_RANGE`：后面跟范围对 `[start, end]`。
- `ASCENDC_TPL_UI_MIX`：列表 + 范围混合。

### 5.2 `ASCENDC_TPL_SEL(...)`

声明编译器需要实例化的模板参数组合。**host 运行时可能产生的每一种组合都必须出现在这里**。

```cpp
ASCENDC_TPL_SEL(
    ASCENDC_TPL_ARGS_SEL(ASCENDC_TPL_DATATYPE_SEL(D_T, C_DT_FLOAT16),
                         ASCENDC_TPL_UINT_SEL(BUFFER_MODE, ASCENDC_TPL_UI_LIST, 0),
                         ASCENDC_TPL_UINT_SEL(NEED_UPCAST, ASCENDC_TPL_UI_LIST, 1)),
    ASCENDC_TPL_ARGS_SEL(ASCENDC_TPL_DATATYPE_SEL(D_T, C_DT_FLOAT16),
                         ASCENDC_TPL_UINT_SEL(BUFFER_MODE, ASCENDC_TPL_UI_LIST, 1),
                         ASCENDC_TPL_UINT_SEL(NEED_UPCAST, ASCENDC_TPL_UI_LIST, 1)),
    // ... 穷举所有合法组合
);
```

选择宏：

| 宏 | 含义 |
|----|------|
| `ASCENDC_TPL_ARGS_SEL(...)` | 一个完整模板实例的参数组合 |
| `ASCENDC_TPL_DATATYPE_SEL(name, value)` | 为 dtype 参数选定一个值 |
| `ASCENDC_TPL_UINT_SEL(name, flag, value, ...)` | 为 uint 参数选定一个或多个值 |
| `ASCENDC_TPL_BOOL_SEL(name, value)` | 为 bool 参数选定一个值 |

### 5.3 `GET_TPL_TILING_KEY(...)`

Host 侧把模板参数值编码成 `uint64_t`。

- 参数顺序和类型必须与 `ASCENDC_TPL_ARGS_DECL` 完全一致。
- 对 dtype 参数，直接传 dtype 枚举值（如 `ge::DT_FLOAT16`）。
- 对 uint 参数，必须传声明列表中存在的值；工具内部会把它转成列表下标再编码。

```cpp
uint64_t key = GET_TPL_TILING_KEY(dType, bufferMode, needUpcastFlag);
context->SetTilingKey(key);
```

### 5.4 `ASCENDC_TPL_SEL_PARAM(context, ...)`

`GET_TPL_TILING_KEY` + `SetTilingKey` 的便利封装。

```cpp
uint32_t dType = static_cast<uint32_t>(inputInfo.dataType);
uint32_t bufferMode = (inputInfo.totalNum > MIN_SPLIT_THRESHOLD) ? 1 : 0;
uint32_t needUpcastFlag = (inputInfo.dataType == ge::DT_FLOAT16) ? 1 : 0;
ASCENDC_TPL_SEL_PARAM(context, dType, bufferMode, needUpcastFlag);
```

等价于：

```cpp
uint64_t key = GET_TPL_TILING_KEY(dType, bufferMode, needUpcastFlag);
context->SetTilingKey(key);
```

### 5.5 `REGISTER_TILING_DEFAULT(TilingStruct)`

在 kernel 入口中声明：**本入口使用 `TilingStruct` 作为默认 TilingData 结构体**。编译器会用它生成 `GET_TILING_DATA` / `GET_TILING_DATA_WITH_STRUCT` 的解析代码。

```cpp
template <typename D_T, int BUFFER_MODE, int NEED_UPCAST>
__global__ __aicore__ void my_op(GM_ADDR x, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling)
{
    REGISTER_TILING_DEFAULT(MyOpTilingData);
    // ...
}
```

### 5.6 `GET_TILING_DATA_WITH_STRUCT(TilingStruct, var_name, tiling_arg)`

从 kernel 入口的 `tiling` 指针中解析出 `TilingStruct` 对象。

```cpp
GET_TILING_DATA_WITH_STRUCT(MyOpTilingData, tilingData, tiling);
MyOpKernel<D_T, BUFFER_MODE, NEED_UPCAST> op;
op.Init(x, y, &tilingData);
```

如果结构体名与 `REGISTER_TILING_DEFAULT` 注册的默认结构体一致，也可以简写：

```cpp
GET_TILING_DATA(tilingData, tiling);
```

### 5.7 `GET_TILING_DATA_PTR_WITH_STRUCT(TilingStruct, var_name, tiling_arg)`

与 `GET_TILING_DATA_WITH_STRUCT` 类似，但生成的是**指向 TilingData 的指针变量**，适合传给需要指针的 atvoss 封装类。

```cpp
GET_TILING_DATA_PTR_WITH_STRUCT(MyOpTilingData, tilingData, tiling);
// 构造函数接收 MyOpTilingData*
SomeAptSch<schMode, OpDAG<half>> sch(tilingData);
```

---

## 6. 典型代码模式

### 6.1 单 dtype 模板参数

适用于只需要根据输入 dtype 区分代码路径的场景。

**`my_op_tiling_key.h`**：

```cpp
#ifndef _MY_OP_TILING_KEY_H_
#define _MY_OP_TILING_KEY_H_

#include "ascendc/host_api/tiling/template_argument.h"

ASCENDC_TPL_ARGS_DECL(MyOp,
    ASCENDC_TPL_DATATYPE_DECL(D_T, C_DT_FLOAT16, C_DT_FLOAT, ASCENDC_TPL_INPUT(0)));

ASCENDC_TPL_SEL(
    ASCENDC_TPL_ARGS_SEL(ASCENDC_TPL_DATATYPE_SEL(D_T, C_DT_FLOAT16)),
    ASCENDC_TPL_ARGS_SEL(ASCENDC_TPL_DATATYPE_SEL(D_T, C_DT_FLOAT)),
);

#endif
```

**Host `TilingFunc`**：

```cpp
MyOpTilingData* tiling = context->GetTilingData<MyOpTilingData>();
memset_s(tiling, sizeof(MyOpTilingData), 0, sizeof(MyOpTilingData));
tiling->totalNum = totalNum;
// ... 填充其他字段

context->SetBlockDim(usedCoreNum);
uint32_t dType = static_cast<uint32_t>(dataType);
ASCENDC_TPL_SEL_PARAM(context, dType);
```

**Kernel 入口**：

```cpp
template <typename D_T>
__global__ __aicore__ void my_op(GM_ADDR x, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling)
{
    REGISTER_TILING_DEFAULT(MyOpTilingData);
    GET_TILING_DATA_WITH_STRUCT(MyOpTilingData, tilingData, tiling);
    MyOpKernel<D_T> op;
    op.Init(x, y, &tilingData);
    op.Process();
}
```

### 6.2 多模板参数：dtype + 运行时策略

适用于需要同时根据 dtype、buffer 策略、是否升精等多个维度展开的场景。

**Host `TilingFunc`**：

```cpp
MyOpTilingData* tiling = context->GetTilingData<MyOpTilingData>();
// ... 填充 TilingData

uint32_t dType = static_cast<uint32_t>(inputInfo.dataType);
uint32_t bufferMode = (inputInfo.totalNum > MIN_SPLIT_THRESHOLD) ? 1 : 0;
uint32_t needUpcastFlag = (dType == ge::DT_FLOAT16 || dType == ge::DT_BF16) ? 1 : 0;
ASCENDC_TPL_SEL_PARAM(context, dType, bufferMode, needUpcastFlag);
```

**Kernel 入口**：

```cpp
template <typename D_T, int BUFFER_MODE, int NEED_UPCAST>
__global__ __aicore__ void my_op(GM_ADDR x, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling)
{
    REGISTER_TILING_DEFAULT(MyOpTilingData);
    GET_TILING_DATA_WITH_STRUCT(MyOpTilingData, tilingData, tiling);

    MyOpKernel<D_T, BUFFER_MODE, NEED_UPCAST> op;
    op.Init(x, y, &tilingData);
    op.Process();
}
```

**Kernel 类内部**：

```cpp
template <typename T, int BUFFER_MODE, int NEED_UPCAST>
class MyOpKernel {
    using IO_T = T;
    using COMPUTE_T = typename std::conditional<NEED_UPCAST == 1, float, T>::type;
    static constexpr int32_t BUFFER_NUM = BUFFER_MODE ? 2 : 1;
    // ...
    __aicore__ inline void Compute(int64_t currentNum)
    {
        if constexpr (NEED_UPCAST == 1) {
            // 升精到 fp32 计算
        } else {
            // 原精度计算
        }
    }
};
```

### 6.3 非 dtype 模板参数 + `if constexpr` 多模板

适用于 dtype 由算子注册/构建时的编译宏控制，而 TPL 只控制其他运行时分支的场景。

**`my_op_tiling_key.h`**：

```cpp
#ifndef _MY_OP_TILING_KEY_H_
#define _MY_OP_TILING_KEY_H_

#include "ascendc/host_api/tiling/template_argument.h"

#define MODE_A 0
#define MODE_B 1
#define NO_GROUP 0
#define GROUPED 1

ASCENDC_TPL_ARGS_DECL(MyOp,
    ASCENDC_TPL_UINT_DECL(mode, 1, ASCENDC_TPL_UI_LIST, MODE_A, MODE_B),
    ASCENDC_TPL_UINT_DECL(isGroup, 1, ASCENDC_TPL_UI_LIST, NO_GROUP, GROUPED));

ASCENDC_TPL_SEL(
    ASCENDC_TPL_ARGS_SEL(
        ASCENDC_TPL_UINT_SEL(mode, ASCENDC_TPL_UI_LIST, MODE_A, MODE_B),
        ASCENDC_TPL_UINT_SEL(isGroup, ASCENDC_TPL_UI_LIST, NO_GROUP, GROUPED)),
);

#endif
```

**Host `TilingFunc`**（手动 `GET_TPL_TILING_KEY`）：

```cpp
uint64_t modeKey = someCondition ? MODE_B : MODE_A;
uint64_t groupKey = hasGroup ? GROUPED : NO_GROUP;
uint64_t tilingKey = GET_TPL_TILING_KEY(modeKey, groupKey);
context->SetTilingKey(tilingKey);
```

**Kernel 入口**：

```cpp
template <uint64_t mode, uint64_t isGroup>
__global__ __aicore__ void my_op(GM_ADDR x, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling)
{
    KERNEL_TASK_TYPE_DEFAULT(KERNEL_TYPE_AIV_ONLY);
    REGISTER_TILING_DEFAULT(MyOpTilingData);
    GET_TILING_DATA_WITH_STRUCT(MyOpTilingData, tilingData, tiling);

    if constexpr (mode == MODE_A && isGroup == GROUPED) {
        MyOpKernel<DTYPE_X, true, true> op(&tilingData);
        op.Init(x, y);
        op.Process();
    }
    // ... 其他 if constexpr 分支
}
```

其中 `DTYPE_X` 是算子注册/构建时根据输入 0 dtype 生成的编译期宏（类似 `DTYPE_INPUT0`），不是 TPL 模板参数。

### 6.4 atvoss 风格：`GET_TILING_DATA_PTR_WITH_STRUCT`

当上层封装类的构造函数需要 `TilingStruct*` 时使用。

```cpp
template <uint64_t schMode, uint64_t dType>
__global__ __aicore__ void my_op(GM_ADDR x, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling)
{
    REGISTER_TILING_DEFAULT(MyOpTilingData);
    GET_TILING_DATA_PTR_WITH_STRUCT(MyOpTilingData, tilingData, tiling);
    KERNEL_TASK_TYPE_DEFAULT(KERNEL_TYPE_AIV_ONLY);

    if constexpr (dType == TPL_FP16) {
        SomeAptSch<schMode, OpDAG<half>> sch(tilingData);  // 接收指针
        sch.Init(x, y);
        sch.Process();
    }
    // ... 其他 dtype 分支
}
```

---

## 7. 一致性约束

要使 ASCENDC_TPL 正确工作，以下几处必须严格一致：

1. **参数顺序一致**
   - `ASCENDC_TPL_ARGS_DECL` 中的参数顺序
   - `ASCENDC_TPL_SEL` 中每个 `ARGS_SEL` 的参数顺序
   - `ASCENDC_TPL_SEL_PARAM` / `GET_TPL_TILING_KEY` 的参数顺序
   - Kernel 入口 `template <...>` 的参数顺序

2. **组合覆盖完整**
   - `TPL_SEL` 必须穷举 host 可能产生的所有合法组合。
   - 漏掉一种组合会导致运行时找不到 kernel 实例。

3. **总位宽不超过 64**
   - 所有 `bitWidth` 之和 ≤ 64。

4. **结构体一致**
   - `REGISTER_TILING_DEFAULT` 注册的默认结构体应与 `GET_TILING_DATA_WITH_STRUCT` 使用的结构体一致。

5. **空 tensor 也要设置 TilingKey**
   - 即使 `totalNum == 0`，也要根据 dtype 等设置 TilingKey，保证 kernel 入口能匹配到实例。

---

## 8. codegen 生成顺序建议

按以下顺序生成文件和代码：

1. `op_kernel/arch35/<op>_tiling_data.h`
   - 定义 TilingData struct。

2. `op_kernel/arch35/<op>_tiling_key.h`
   - `ASCENDC_TPL_ARGS_DECL` 声明模板参数。
   - `ASCENDC_TPL_SEL` 穷举所有合法组合。

3. `op_kernel/arch35/<op>.h`
   - Kernel 类模板，模板参数与 `TPL_ARGS_DECL` 一致。
   - 内部使用 `if constexpr` 根据模板参数选择分支。

4. `op_kernel/<op>_apt.cpp`（或 `<op>.cpp`）
   - 模板 kernel 入口函数。
   - `REGISTER_TILING_DEFAULT(<Op>TilingData);`
   - `GET_TILING_DATA_WITH_STRUCT(<Op>TilingData, tilingData, tiling);`
   - 实例化并调用 Kernel 类。

5. `op_host/arch35/<op>_tiling_arch35.cpp`
   - 计算 shape、分核、分块、workspace。
   - 填充 TilingData。
   - 根据运行时条件计算模板参数值。
   - `ASCENDC_TPL_SEL_PARAM(context, ...)` 设置 TilingKey。

---

## 9. 自检清单

- [ ] 理解 ASCENDC_TPL 是“编译期模板实例化 + 运行期 TilingKey 路由”两层机制。
- [ ] `ASCENDC_TPL_ARGS_DECL` 的参数顺序与 kernel 入口 `template<...>` 顺序一致。
- [ ] `ASCENDC_TPL_SEL` 中每个 `ARGS_SEL` 的参数顺序与 `ARGS_DECL` 一致。
- [ ] `ASCENDC_TPL_SEL_PARAM` 的参数顺序与 `ARGS_DECL` 一致。
- [ ] `TPL_SEL` 穷举了 host 可能产生的所有组合。
- [ ] 所有模板参数的 `bitWidth` 之和 ≤ 64。
- [ ] dtype 值使用 `C_DT_FLOAT16`、`C_DT_FLOAT`、`C_DT_BF16` 等 CANN 常量；host 传真实 dtype 枚举值。
- [ ] `ASCENDC_TPL_INPUT(n)` 是占位标记，host 仍需传入真实 dtype 值。
- [ ] Kernel 入口中 `REGISTER_TILING_DEFAULT` 和 `GET_TILING_DATA_WITH_STRUCT` 使用同一个结构体。
- [ ] 空 tensor 场景也设置了 TilingKey。
- [ ] 如果用了 `REGISTER_NONE_TILING`，各分支 `GET_TILING_DATA_WITH_STRUCT` 使用的结构体要与 host 对应该 TilingKey 下发的结构体一致。
- [ ] 所有 `if constexpr` 分支在对应模板参数下都能编译通过。

---

## 10. 一个 kernel 有多个模板时，TilingStruct 是共用还是分开？

**两种做法都存在，取决于模板参数是否会导致 TilingData 本身的结构或大小不同。**

### 10.1 典型做法：所有模板实例共用一个 TilingStruct

大多数 elewise / activation 算子采用这种方式。模板参数只控制 kernel 内部代码路径，不影响 TilingData 布局。

```cpp
template <typename D_T, int BUFFER_MODE, int NEED_UPCAST>
__global__ __aicore__ void my_op(...)
{
    REGISTER_TILING_DEFAULT(MyOpTilingData);
    GET_TILING_DATA_WITH_STRUCT(MyOpTilingData, tilingData, tiling);

    MyOpKernel<D_T, BUFFER_MODE, NEED_UPCAST> op;
    op.Init(x, y, &tilingData);
    op.Process();
}
```

- `MyOpTilingData` 只有一个普通 struct。
- 所有 `TPL_SEL` 组合都读同一个结构体。
- `BUFFER_MODE`、`NEED_UPCAST` 通过 `if constexpr` 控制分支，不访问的字段不产生影响。

### 10.2 进阶做法：不同模板实例使用不同 TilingStruct

当模板参数会改变 TilingData 本身大小或数组维度时，需要为不同模板实例准备不同的结构体。

典型场景是模板参数 `RANK` 取 4 或 8，TilingData 是模板化的 `MyOpTilingData<4>` 和 `MyOpTilingData<8>`，内部数组维度随 `RANK` 变化，因此结构体大小不同。

**Host 侧**：根据实际 rank 选择对应的 TilingData 模板实例，并设置对应的 TilingKey。

```cpp
ge::graphStatus MyOpTiling::RunTiling()
{
    int64_t mapped = (rank_ <= 4) ? 4 : 8;
    if (mapped == 4) {
        DoTilingAndSet<4>();
        ctx_->SetTilingKey(GET_TPL_TILING_KEY(RANK_4));
    } else {
        DoTilingAndSet<8>();
        ctx_->SetTilingKey(GET_TPL_TILING_KEY(RANK_8));
    }
}
```

**Kernel 侧**：使用 `REGISTER_NONE_TILING` 不注册默认结构体，然后在 `if constexpr` 分支中显式读取对应结构体。

```cpp
using TilingData4 = MyOpTilingData<4>;
using TilingData8 = MyOpTilingData<8>;

template <int RANK>
__global__ __aicore__ void my_op(...)
{
    REGISTER_NONE_TILING;
    KERNEL_TASK_TYPE_DEFAULT(KERNEL_TYPE_AIV_ONLY);

    if constexpr (RANK == 4) {
        GET_TILING_DATA_WITH_STRUCT(TilingData4, td, tiling);
        MyOpKernel<DTYPE_INPUT0, 4> kernel;
        kernel.Init(ins, outs, &td);
        kernel.Process();
    } else {
        GET_TILING_DATA_WITH_STRUCT(TilingData8, td, tiling);
        MyOpKernel<DTYPE_INPUT0, 8> kernel;
        kernel.Init(ins, outs, &td);
        kernel.Process();
    }
}
```

### 10.3 选择建议

| 场景 | 推荐做法 | 说明 |
|------|----------|------|
| 模板参数只影响代码路径，不影响 TilingData 布局 | 共用一个 TilingStruct + `REGISTER_TILING_DEFAULT` | 简单，出错概率低 |
| 模板参数会改变 TilingData 大小/数组维度 | 每个模板用不同 TilingStruct + `REGISTER_NONE_TILING` + 显式 `GET_TILING_DATA_WITH_STRUCT` | Host 必须下发对应大小的数据 |

### 10.4 关键约束

- `REGISTER_TILING_DEFAULT` 在一个 kernel 入口中只能注册一个默认结构体。
- 如果不同模板实例需要不同结构体，不要依赖默认注册，应使用 `REGISTER_NONE_TILING` 并在各分支显式读取。
- Host 下发的 TilingData 大小和布局，必须与 kernel 侧 `GET_TILING_DATA_WITH_STRUCT` 解析的 struct 完全匹配。
- TilingKey 必须与模板实例一一对应：host 设置 `RANK_4` 时，kernel 必须进入 `RANK == 4` 分支并读取 `MyOpTilingData<4>`。

---

## 11. `REGISTER_NONE_TILING` 的作用

### 11.1 宏定义

`REGISTER_NONE_TILING` 定义在 `ascendc/include/basic_api/impl/utils/kernel_utils_macros.h` 中：

```cpp
#ifdef __CHECK_FEATURE_AT_PRECOMPILE
#define REGISTER_NONE_TILING auto __enable_no_register_custom_tiling ascendc_trigger_tiling_struct = default
#else
#define REGISTER_NONE_TILING
#endif
```

- 在普通 kernel 编译时，它展开为空，不产生任何实际代码。
- 在预编译检查阶段（`__CHECK_FEATURE_AT_PRECOMPILE`），它生成一个特殊标记变量，用于向编译器工具链声明：**本 kernel 入口（或本函数作用域）没有注册默认 TilingData 结构体**。

### 11.2 什么时候用

当一段代码满足以下任一条件时使用 `REGISTER_NONE_TILING`：

1. **不同模板实例需要读取不同 TilingData 结构体**（如 `RANK==4` 和 `RANK==8` 用不同大小的 struct）。
2. **同一函数内多个 `if constexpr` 分支读取不同 TilingData 结构体**（如某些 atvoss 封装里不同 `schMode` 分支读不同结构体）。
3. **函数本身只是调度/封装层，不拥有单一默认 TilingData**。

### 11.3 用法示例

```cpp
using TilingData4 = MyOpTilingData<4>;
using TilingData8 = MyOpTilingData<8>;

template <int RANK>
__global__ __aicore__ void my_op(..., GM_ADDR tiling)
{
    REGISTER_NONE_TILING;          // 不注册默认 TilingData
    KERNEL_TASK_TYPE_DEFAULT(KERNEL_TYPE_AIV_ONLY);

    if constexpr (RANK == 4) {
        GET_TILING_DATA_WITH_STRUCT(TilingData4, td, tiling);
        MyOpKernel<DTYPE_INPUT0, 4> kernel;
        kernel.Init(ins, outs, &td);
        kernel.Process();
    } else {
        GET_TILING_DATA_WITH_STRUCT(TilingData8, td, tiling);
        MyOpKernel<DTYPE_INPUT0, 8> kernel;
        kernel.Init(ins, outs, &td);
        kernel.Process();
    }
}
```

### 11.4 与 `REGISTER_TILING_DEFAULT` 的区别

| 宏 | 含义 | 使用场景 |
|----|------|----------|
| `REGISTER_TILING_DEFAULT(TilingStruct)` | 声明本 kernel 使用 `TilingStruct` 作为默认 TilingData | 单一 TilingData 即可覆盖所有模板实例 |
| `REGISTER_NONE_TILING` | 声明本 kernel 没有默认 TilingData | 不同模板/分支需要读取不同 TilingData |

### 11.5 约束

- `REGISTER_NONE_TILING` 通常要与显式的 `GET_TILING_DATA_WITH_STRUCT` 或 `GET_TILING_DATA_PTR_WITH_STRUCT` 配合使用。
- 所有分支读取的 TilingData 总大小不能超过 host 下发的 tiling buffer 容量。
- Host 侧必须保证：下发给某个 TilingKey 对应的模板实例的 TilingData，与 kernel 侧该分支解析的 struct 大小和布局一致。

---

## 12. 为什么必须写 `REGISTER_TILING_DEFAULT` 或 `REGISTER_NONE_TILING`？

这两个宏不是装饰，而是**向 CANN 编译器声明本 kernel 入口如何解析 host 下发的 TilingData**。不写会在预编译阶段直接报错。

### 12.1 根本原因：kernel 需要知道把 `tiling` 指针按哪个 struct 解析

Host 下发的 `tiling` 本质上只是一段字节流。Kernel 侧要用 `GET_TILING_DATA_WITH_STRUCT` 把它解释成有类型的 C++ struct，编译器必须事先知道：

1. **结构体叫什么名字** —— 用来生成 `static constexpr TilingStruct tiling_data = convert_from_bytes<TilingStruct>(...)`；
2. **结构体多大** —— 用来生成 `.ascendc_tiling.<struct>_<key>_<counter>` 段信息，最终进入 `meta_info.o`；
3. **每个 TilingKey 对应哪个结构体** —— 当存在多模板实例时，编译器要为每个 key 准备正确的 struct/size。

`REGISTER_TILING_DEFAULT(TilingStruct)` 就是告诉编译器：**“本 kernel 入口的默认 TilingData 是 `TilingStruct`”**。随后 `get_op_tiling.py` 在生成 kernel 头文件时会用这个结构体构造 `GET_TILING_DATA_WITH_STRUCT`（或 `GET_TILING_DATA`）。

### 12.2 预编译阶段真的会检查

CANN 在 `__CHECK_FEATURE_AT_PRECOMPILE` 阶段会对 kernel 做预处理，并通过 `kernel_info_infer.py` 扫描中间文件中的 `__enable_custom_tiling`（来自 `REGISTER_TILING_DEFAULT` / `REGISTER_TILING_FOR_TILINGKEY`）或 `__enable_no_register_custom_tiling`（来自 `REGISTER_NONE_TILING`）。

- 如果扫描到了 `__enable_custom_tiling`，就提取出结构体名作为 `default_tiling_struct`。
- 如果扫描到了 `__enable_no_register_custom_tiling`，就把 `ascendc_tiling_no_register` 置为 true。
- **两者都没有**，且当前算子需要用户自定义 TilingData 时，会抛出异常：

```text
if use user-defined tiling structure, must provide default tiling struct, use macro REGISTER_TILING_DEFAULT
```

也就是说，编译器必须至少知道“默认结构体是什么”或“本入口没有默认结构体”二者之一，否则无法继续生成 TilingData 解析代码。

### 12.3 `REGISTER_NONE_TILING` 为什么也是一种声明

有些入口在不同模板分支里使用**不同大小/布局**的 TilingData，无法用一个默认结构体概括。这时就要显式写 `REGISTER_NONE_TILING`，意思是：

> “本入口没有单一默认结构体，具体结构体由模板分支里的 `GET_TILING_DATA_WITH_STRUCT` 自行指定。”

在这种模式下，`get_op_tiling.py` 不再为 `GET_TILING_DATA` 生成默认结构体代码，而会把生成重任交给 `GET_TILING_DATA_WITH_STRUCT` 里嵌入的 `REGISTER_TILINGDATA_SIZE` 段；链接阶段再通过 `compile_op.py` 扫描 `.ascendc_tiling.*` 段生成 `meta_info.o`。

### 12.4 不写会有什么现象

| 场景 | 现象 |
|------|------|
| 普通动态 shape 算子 | 编译器无法生成 `GET_TILING_DATA_WITH_STRUCT`，预编译报错 |
| 静态 shape 算子 | 无法建立 TilingKey → TilingStruct 映射，`gen_static_shape_v2` 拿不到结构体 |
| 多模板多结构体算子 | 编译器坚持要一个默认结构体，而你又给不出，只能卡住 |

### 12.5 一句话总结

`REGISTER_TILING_DEFAULT` 是告诉编译器“按这个结构体解析 tiling”；`REGISTER_NONE_TILING` 是告诉编译器“这里没有默认结构体，各分支自己用 `GET_TILING_DATA_WITH_STRUCT` 解析”。**两者必须二选一**，否则 CANN 在预编译阶段就不知道该用哪种 TilingData 类型生成后续代码。

---

## 附录：真实算子参考

如果你需要对照真实代码，可参考 `/root/workspace/ops-nn` 中的以下样例（均为 arch35/Ascend950）：

| 场景 | 算子/文件 |
|------|----------|
| 单 dtype 模板参数 | `activation/celu` |
| dtype + buffer_mode + need_upcast 多模板 | `activation/hard_shrink` |
| 非 dtype 模板参数 + `if constexpr` | `activation/clipped_swiglu` |
| atvoss 风格 `GET_TILING_DATA_PTR_WITH_STRUCT` | `activation/gelu` |
| 不同 RANK 用不同 TilingStruct | `optim/adam_apply_one_assign`、`activation/softplus_v2_grad`、`activation/threshold_grad_v2_d` |

---

*文档基于 CANN 9.1.0 + `/root/workspace/ops-nn` 样例研究。*