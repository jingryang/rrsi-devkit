# Reg::StoreAlign

> **概述**：单寄存器存储、`PostLiteral` 地址更新模式、`StoreDist` 模式、掩码用法及对齐要求。

## 1. 用途

将数据从向量寄存器存储到统一缓冲区（UB），支持地址对齐和可选的存储分发模式。StoreAlign 是 VF 流水线的出口点——它将计算结果写回 UB，以便后续 DataCopy 到 GM。

## 2. API 签名

```cpp
Reg::StoreAlign<T, PostLiteral, StoreDist>(dstAddr, srcReg, elementNum, maskReg);
```

| 参数 | 说明 |
|-----------|-------------|
| `T` | 元素类型（`float`、`bfloat16_t`、`half`、`uint8_t` 等） |
| `PostLiteral` | 地址更新模式（见第 3 节） |
| `StoreDist` | 存储分发模式（见第 4 节） |
| `dstAddr` | 目标 UB 地址（`__ubuf__ T*`） |
| `srcReg` | 源 `RegTensor` |
| `elementNum` | 存储的元素数（以 `T` 计） |
| `maskReg` | 控制哪些元素被写入的掩码 |

**对齐**：`dstAddr` 必须按元素大小边界对齐。

## 3. PostLiteral

| 模式 | 行为 | 使用场景 |
|------|----------|----------|
| `POST_MODE_UPDATE` | 存储后，`dstAddr` 自动增加 `elementNum * sizeof(T)` | 循环中的顺序存储 |
| `POST_MODE_KEEP` | `dstAddr` 保持不变 | 覆盖同一位置，或手动管理偏移 |

## 4. StoreDist：存储分发模式

StoreDist 控制寄存器数据写入 UB 时的排列方式。

### 4.1 无 StoreDist（默认）

标准顺序存储。

```cpp
Reg::StoreAlign<float>(scaleBufAddr, vdFp32, 64, mask);
// scaleBufAddr[i] = vdFp32[i], i = 0..63
```

### 4.2 DIST_NORM_B32 — 正常 32-bit 存储

针对 32-bit 元素优化的顺序存储。

```cpp
Reg::StoreAlign<float, POST_MODE_UPDATE, DIST_NORM_B32>(
    yLocalAddr, vdFp32, vfLen32, maskFp32);
```

**效果**：顺序存储 `vfLen32`（64）个 float。`yLocalAddr` 前进 `64 * sizeof(float) = 256` 字节。

### 4.3 DIST_NORM_B16 — 正常 16-bit 存储

针对 16-bit 元素优化的顺序存储。

```cpp
Reg::StoreAlign<bfloat16_t, POST_MODE_UPDATE, DIST_NORM_B16>(
    yLocalAddr, vdBf16, vfLen16, maskAll);
```

**效果**：顺序存储 `vfLen16`（128）个 bf16 值。`yLocalAddr` 前进 `128 * 2 = 256` 字节。

### 4.4 StoreDist 汇总表

| StoreDist | 元素类型 | 用途 |
|-----------|-------------|---------|
| (无) | Any | 默认顺序存储 |
| `DIST_NORM_B32` | `float` | 正常 32-bit 顺序 |
| `DIST_NORM_B16` | `bfloat16_t` / `half` | 正常 16-bit 顺序 |

## 5. MaskReg

Store 使用 `MaskReg` 决定哪些元素被写入。创建时需匹配元素类型。

```cpp
// 为 float 存储创建掩码
Reg::MaskReg maskFp32 = Reg::CreateMask<float, Reg::MaskPattern::ALL>();
Reg::StoreAlign<float>(addr, vdFp32, 64, maskFp32);

// 为 bfloat16_t 存储创建掩码
Reg::MaskReg maskBf16 = Reg::CreateMask<bfloat16_t, Reg::MaskPattern::ALL>();
Reg::StoreAlign<bfloat16_t>(addr, vdBf16, 128, maskBf16);
```

## 6. 单指令使用示例

### 6.1 存储 FP32 Scale 缓冲区

```cpp
Reg::StoreAlign<float, Reg::PostLiteral::POST_MODE_UPDATE>(
    scaleBufAddr, vdScaleFp32_0_0, vfLen32, storeMask);
```

### 6.2 存储 BF16 输出

```cpp
Reg::StoreAlign<bfloat16_t, Reg::PostLiteral::POST_MODE_UPDATE,
                Reg::StoreDist::DIST_NORM_B16>(
    yLocalAddr, vdBf16_0_z, vfLen16, maskAll);
```

### 6.3 带分发模式的 FP32 输出存储

```cpp
Reg::StoreAlign<float, Reg::PostLiteral::POST_MODE_UPDATE,
                Reg::StoreDist::DIST_NORM_B32>(
    yLocalAddr, vdFp32_0_0, vfLen32, maskFp32);
```

### 6.4 手动地址存储（无自动递增）

```cpp
Reg::StoreAlign<float, Reg::PostLiteral::POST_MODE_KEEP>(
    yLocalAddr + offset, vdFp32, 64, mask);
// yLocalAddr 不变；下次存储需要新偏移
```

## 7. 常见陷阱

### 7.1 掩码类型不匹配

```cpp
// 错误：float 掩码用于 bfloat16_t 存储
Reg::MaskReg maskFp32 = Reg::CreateMask<float, Reg::MaskPattern::ALL>();
Reg::StoreAlign<bfloat16_t>(addr, vdBf16, 128, maskFp32);
// 行为未定义 —— 掩码元素宽度（4B）!= 存储元素宽度（2B）

// 正确：掩码类型与存储元素类型匹配
Reg::MaskReg maskBf16 = Reg::CreateMask<bfloat16_t, Reg::MaskPattern::ALL>();
Reg::StoreAlign<bfloat16_t>(addr, vdBf16, 128, maskBf16);
```

### 7.2 多寄存器存储缺少 POST_MODE_UPDATE

```cpp
// 错误：所有存储写入同一地址
for (int i = 0; i < 4; i++) {
    Reg::StoreAlign<float, POST_MODE_KEEP>(addr, vd[i], 64, mask);
}

// 正确：每次存储后地址自动前进
for (int i = 0; i < 4; i++) {
    Reg::StoreAlign<float, POST_MODE_UPDATE>(addr, vd[i], 64, mask);
}
```

### 7.3 StoreDist 类型不匹配

```cpp
// 错误：DIST_NORM_B32 用于 bfloat16_t
Reg::StoreAlign<bfloat16_t, ..., DIST_NORM_B32>(addr, vdBf16, 128, mask);

// 正确：16-bit 元素使用 B16 变体
Reg::StoreAlign<bfloat16_t, ..., DIST_NORM_B16>(addr, vdBf16, 128, mask);
```

### 7.4 寄存器组之间忘记推进地址

```cpp
// 错误：4 次存储后 addr 只前进了 64 个 float（256 字节）
// 但 4 个寄存器 × 64 个 float = 256 个 float 应该已被存储
Reg::StoreAlign<float, POST_MODE_UPDATE>(addr, vd0, 64, mask);  // addr += 256B
Reg::StoreAlign<float, POST_MODE_KEEP>(addr, vd1, 64, mask);    // 覆盖！
Reg::StoreAlign<float, POST_MODE_KEEP>(addr, vd2, 64, mask);    // 覆盖！
Reg::StoreAlign<float, POST_MODE_KEEP>(addr, vd3, 64, mask);    // 覆盖！

// 正确：所有存储自动前进
Reg::StoreAlign<float, POST_MODE_UPDATE>(addr, vd0, 64, mask);
Reg::StoreAlign<float, POST_MODE_UPDATE>(addr, vd1, 64, mask);
Reg::StoreAlign<float, POST_MODE_UPDATE>(addr, vd2, 64, mask);
Reg::StoreAlign<float, POST_MODE_UPDATE>(addr, vd3, 64, mask);
```

## 8. 相关模式

见 `INDEX.md` 了解使用 StoreAlign 的组合模式：
- **模式 1.1**：完全顺序恢复（FP8 → FP32）
- **模式 1.2**：多布局 Cast + Add（→ BF16/FP16）
- **模式 1.4**：FP4 快速解码（DIST_UNPACK4_B8 + Cast）
- **模式 1.5**：Scale 预处理（FP8_E8M0 → BF16 → FP32）
- **模式 1.6**：Scale 预处理（FP8_E8M0 → BF16 only）
