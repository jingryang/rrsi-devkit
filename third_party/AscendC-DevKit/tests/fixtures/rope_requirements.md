# RotaryPositionEmbedding 算子需求说明

> 本文档从《Pangu-LightningIndexer算子需求分析与设计说明书》（rope_design.md，版本1.0）中提取需求相关的准确描述，不含算子设计实现细节。

| 项目 | 信息 |
|------|------|
| 来源文档 | rope_design.md（版本1.0，2025-12-11） |
| 拟制 | 宋航/00805634 |
| 密级 | 仅供内部使用 |

---

## 1 需求背景

Pangu-72B 在 Attention 模块中将 K 的 RmsNorm、K 的 Rope、KVCache 的更新融合成一个算子 KvRmsNormRopeCache 中。

剩余 Q 的 partial_rope 计算无合适算子完成，需要通过小算子拼接完成，涉及较多 slice 和 concat 操作（StridedSliceV2、Mul、Concat 等），性能较差（profiling 实测耗时约 60.448 us）。

**盘古72B-rope 旋转位置编码需求：**

- 单入单出，只对 Q 做旋转位置编码，和 KvRmsNormRopeCache 配套使用。
- rotary_mode: interleave-half，和 KvRmsNormRopeCache 数据对齐。
- partial_rope：只对 headDim 前面元素应用旋转位置编码。

**约束：** 基于现有 RotaryPositionEmbedding 算子开发新特性，要求**已有场景性能不劣化**。

**昇腾算子现状：** 目前单入单出的算子包括 InterleaveRope 和 RotaryPositionEmbedding，前者被后者部分收编，按 RotaryPositionEmbedding 算子支持。

---

## 2 设计约束

- 运行环境：910B / 910C AI 处理器。
- 调用方式：单算子 / 图模式。
- 调用框架：torch_npu。

---

## 3 算子功能与接口需求

### 3.1 算子功能

aclnnRotaryPositionEmbedding 算子功能：执行单路旋转位置编码计算。

### 3.2 计算公式

**(1) half 模式（mode 等于 0）：**

```
x1 = x[...,:x.shape[-1]//2]
x2 = x[...,x.shape[-1]//2:]
x_rotate = torch.cat((-x2, x1), dim=-1)
y = x * cos + x_rotate * sin
```

**(2) interleave 模式（mode 等于 1）：**

```
x1 = x[...,::2].view(-1, 1)
x2 = x[...,1::2].view(-1, 1)
x_rotate = torch.cat((-x2, x1), dim=-1).view(x.shape[0], x.shape[1], x.shape[2], x.shape[3])
y = x * cos + x_rotate * sin
```

**(3) quarter 模式（mode 等于 2）：**

```
x1 = x[...,:x.shape[-1]//4]
x2 = x[...,x.shape[-1]//4:x.shape[-1]//2]
x3 = x[...,x.shape[-1]//2:x.shape[-1]//4*3]
x4 = x[...,x.shape[-1]//4*3:]
x_rotate = torch.cat((-x2, x1, -x4, x3), dim=-1)
y = x * cos + x_rotate * sin
```

**(4) interleave-half 模式（mode 等于 3）：**

该模式会先将奇数位的输入抽取到前半部分，将偶数位的输入抽取到后半部分，再进行 half 处理：

```
x1 = x[...,::2]
x2 = x[...,1::2]
x_part1 = torch.cat((x1, x2), dim=-1)
x_part2 = torch.cat((-x2, x1), dim=-1)
y = x_part1 * cos + x_part2 * sin
```

### 3.3 函数原型

```c
aclnnStatus aclnnRotaryPositionEmbeddingGetWorkspaceSize(
    const aclTensor *x,
    const aclTensor *cos,
    const aclTensor *sin,
    int64_t mode,
    aclTensor *out,
    uint64_t *workspaceSize,
    aclOpExecutor **executor)

aclnnStatus aclnnRotaryPositionEmbedding(
    void *workspace,
    uint64_t workspaceSize,
    aclOpExecutor *executor,
    aclrtStream stream)
```

### 3.4 参数说明

| 参数名 | 输入/输出 | 描述 | 使用说明 |
|--------|-----------|------|----------|
| x | 输入 | 待执行旋转位置编码的张量。 | - |
| cos | 输入 | 位置编码张量，公式中的 cos。 | 与 x 数据类型一致。 |
| sin | 输入 | 位置编码张量，公式中的 sin。 | 与 x 数据类型一致。 |
| mode | 输入 | 旋转模式。 | A3/A2：0=half，1=interleave。A5：2=quarter，3=interleave-half。 |
| out | 输出 | 旋转位置编码计算结果，公式中的 y。 | 与 x 数据类型一致。 |

### 3.5 当前算子现状

- 算子仅支持 half / interleave 模式。
- 算子仅支持 x 与 cos/sin 的 headDim 相同。
- 当前 torchair 图模式下使用的是旧 tick 算子 RotaryMul。

---

## 4 算子需求项

- **需求1**：算子 RotaryPositionEmbedding 支持 interleave-half 模式。
- **需求2**：算子 RotaryPositionEmbedding 支持 partial_rope 特性。
- **需求3**：算子 RotaryPositionEmbedding 支持图模式下使用（当前图模式下使用旧 tick 算子，需切换到新算子）。

---

## 5 泛化性需求

由于算子支持的场景比较泛化，而现有功能性能不能劣化，需要设计同时满足高性能和通用性的泛化方案，需覆盖以下场景：

- B/N/S 轴的不同排布顺序。
- x 和 cos、sin 的 B/N/S 轴的不同对应关系，及对应轴是否需广播。
- 任意规格的 D 维度，D 维度是否 32B 对齐，D/2 维度是否 32B 对齐。
- partial_rope 场景的尾部处理。
- 任意规格的 Dx 维度是否 32B 对齐。
- 不同的计算模式（对应不同的计算流程、不同的对齐规则、不同的 UB 分配、不同的广播处理）。
- 不同的数据类型（影响计算流程及 UB 空间分配）。

---

## 6 性能需求

- 通过新模板满足新功能，同时收编所有现有功能且保证现有功能不劣化。
- 若无法满足，可部分保留现有模板，通过 Tiling 处理在特定场景下走原模板。

---

## 7 典型 Shape 需求

| 场景 | Tensor | Shape | 数据类型 |
|------|--------|-------|----------|
| Pangu-72B | x | [320, 16, 192] | BF16 |
| | cos/sin | [320, 16, 64] | BF16 |

---

## 8 交付需求

- 上主线，1月 poc 交付。

---

## 9 需求单（云龙平台）

**【标题】**：RotaryPositionEmbedding 算子支持 partial_rope

- 【编号】：US20251125519552
- 【状态】：初始
- 【链接】：https://clouddragon.huawei.com/cloudreq-obp/third/2093412366

**【标题】**：RotaryPositionEmbedding 算子支持 interleave 入 half 出模式

- 【编号】：US20251202694696
- 【状态】：初始
- 【链接】：https://clouddragon.huawei.com/cloudreq-obp/third/2093746956