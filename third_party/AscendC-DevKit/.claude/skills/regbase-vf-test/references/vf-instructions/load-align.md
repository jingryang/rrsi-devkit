# Reg::LoadAlign

> **概述**：单/双寄存器加载、`PostLiteral` 地址更新模式、`LoadDist` 广播/解交错/解包模式及地址对齐要求。

## 1. 用途

将数据从统一缓冲区（UB）加载到向量寄存器，支持地址对齐和可选的数据分发模式。LoadAlign 是 VF 流水线的入口点——它决定原始数据从 UB 进入寄存器后的排列方式，然后再进行 Cast/Compute/Store。

## 2. API 签名

### 2.1 单寄存器加载

```cpp
Reg::LoadAlign<T, PostLiteral, LoadDist>(dstReg, srcAddr, elementNum);
```

### 2.2 双寄存器加载

```cpp
Reg::LoadAlign<T, PostLiteral, LoadDist>(dstReg0, dstReg1, srcAddr, elementNum);
```

| 参数 | 说明 |
|-----------|-------------|
| `T` | 寄存器元素类型（`uint8_t`、`uint16_t`、`bfloat16_t`、`float` 等） |
| `PostLiteral` | 地址更新模式（见第 3 节） |
| `LoadDist` | 数据分发模式（见第 4 节） |
| `dstReg` / `dstReg0, dstReg1` | 目标 `RegTensor`(s) |
| `srcAddr` | 源 UB 地址（`__ubuf__ T*`） |
| `elementNum` | 加载的元素数（以 `T` 计） |

**对齐**：`srcAddr` 必须按元素大小边界对齐。对于 `uint8_t`，任意地址均可；对于 `float`（4B），需 4 字节对齐。

## 3. PostLiteral：地址更新模式

| 模式 | 行为 | 使用场景 |
|------|----------|----------|
| `POST_MODE_UPDATE` | 加载后，`srcAddr` 自动增加 `elementNum * sizeof(T)` | 循环中的顺序加载 |
| `POST_MODE_KEEP` | `srcAddr` 保持不变 | 重复加载相同数据，或手动管理偏移 |

## 4. LoadDist：数据分发模式

LoadDist 控制数据从 UB 加载到寄存器后的重排方式。这是 LoadAlign 与普通内存拷贝的关键区别。

### 4.1 无 LoadDist（默认）

普通顺序加载。

```cpp
Reg::LoadAlign<uint8_t>(vd, addr, 256);
// vd[i] = addr[i], i = 0..255
```

### 4.2 DIST_DINTLV_B8 — 8-bit 解交错

加载并将交错数据拆分为两个寄存器。常用于以交错格式存储的 FP8 数据。

```cpp
Reg::LoadAlign<uint8_t, POST_MODE_UPDATE, DIST_DINTLV_B8>(
    vd0, vd1, addr, 512);  // 512 字节总计 → vd0(256), vd1(256)
```

**数据布局**（内存是交错的 `[a0, b0, a1, b1, ...]`）：
- `vd0 = [a0, a1, a2, ..., a255]`
- `vd1 = [b0, b1, b2, ..., b255]`

### 4.3 DIST_UNPACK4_B8 — 4× 8-bit 解包

将打包的 FP4 字节解包到稀疏的寄存器布局。每个源字节包含 2 个 FP4 值；`DIST_UNPACK4_B8` 展开它们以便直接 Cast。

```cpp
Reg::LoadAlign<uint8_t, POST_MODE_UPDATE, DIST_UNPACK4_B8>(
    vd, addr, 64);  // 加载 64 字节，解包到 256 字节寄存器布局
```

**数据布局**：4 个源字节被解包到 256B 寄存器的特定位置，为 `Cast<bf16, fp4x2_t, ZERO>` 做准备。

**注意**：在支持 `DIST_UNPACK4_B8` 的芯片上，FP4 解码**不需要**手动 Interleave+ShiftRights 流水线。硬件解包 + Cast(ZERO layout) 已足够。

### 4.4 DIST_E2B_B32 — 元素到块广播（32-bit）

将每个元素广播填满一个 32 字节块。用于需要与多个数据元素相乘的 scale 值。

```cpp
Reg::LoadAlign<float, POST_MODE_UPDATE, DIST_E2B_B32>(
    vdScale, scaleBufAddr, 8);  // 8 个 float 广播到 64-float 寄存器
```

**数据布局**：若源为 `[s0, s1, ..., s7]`：
- 每个 `si` 被广播到 `platform::GetUbBlockSize() / sizeof(float) = 8` 个连续 float 槽位
- 寄存器内容：`[s0×8, s1×8, ..., s7×8]`（共 64 个 float）

### 4.5 DIST_E2B_B16 — 元素到块广播（16-bit）

同上，但用于 16-bit 元素。

```cpp
Reg::LoadAlign<bfloat16_t, POST_MODE_UPDATE, DIST_E2B_B16>(
    vdScale, scaleBufAddr, 8);  // 8 个 bf16 值广播
```

**数据布局**：每个 `si` 广播到 16 个连续 bf16 槽位（因为 32B / 2B = 16）。
- 寄存器内容：`[s0×16, s1×16, ..., s7×16]`（共 128 个 bf16）

### 4.6 LoadDist 汇总表

| LoadDist | 元素类型 | 加载元素总数 | 用途 |
|----------|-------------|----------------------|---------|
| (无) | Any | `elementNum` | 顺序加载 |
| `DIST_DINTLV_B8` | `uint8_t` | `elementNum`（50/50 分到 2 个寄存器） | 解交错字节流 |
| `DIST_UNPACK4_B8` | `uint8_t` | `elementNum`（解包 4×） | 解包 FP4 字节 |
| `DIST_E2B_B32` | `float` | `elementNum`（每个广播 ×8） | 广播 float scale |
| `DIST_E2B_B16` | `bfloat16_t`/`half` | `elementNum`（每个广播 ×16） | 广播 16-bit scale |

## 5. 单指令使用示例

### 5.1 顺序加载（Scale 预处理）

```cpp
Reg::LoadAlign<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(
    vdScale0, scaleLocalAddr, vfLen8);  // 加载 256 个 scale 字节，自动递增
```

### 5.2 双寄存器解交错加载（FP8 数据）

```cpp
Reg::LoadAlign<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE,
               Reg::LoadDist::DIST_DINTLV_B8>(
    vdFp8_0, vdFp8_1, xLocalAddr, vfLen8Double);  // 512 字节 → 2×256
```

### 5.3 Scale 广播加载（FP8 反量化）

```cpp
// elementAfterReduce_ = platform::GetVRegSize() / UBBlockSize_ = 256/32 = 8
Reg::LoadAlign<float, Reg::PostLiteral::POST_MODE_UPDATE,
               Reg::LoadDist::DIST_E2B_B32>(
    vdScale_0, scaleBufAddr, elementAfterReduce_);  // 8 个 float → 广播 ×8
```

### 5.4 FP4 解包加载

```cpp
Reg::LoadAlign<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE,
               Reg::LoadDist::DIST_UNPACK4_B8>(
    vdFp4U8_0, xLocalAddr, vfLen32);  // 64 字节解包到 256B 布局
```

### 5.5 BF16 Scale 广播加载（FP4 反量化）

```cpp
Reg::LoadAlign<bfloat16_t, Reg::PostLiteral::POST_MODE_UPDATE,
               Reg::LoadDist::DIST_E2B_B16>(
    vdScaleTmp0, scaleBufAddr, elementAfterReduce_);  // 8 个 bf16 → 广播 ×16
```

## 6. 常见陷阱

### 6.1 双寄存器加载的元素数错误

```cpp
// 错误：elementNum 是总数，但每个寄存器只得到一半
Reg::LoadAlign<uint8_t, ..., DIST_DINTLV_B8>(vd0, vd1, addr, 256);
// vd0 得到 128 字节，vd1 得到 128 字节 —— 调用者期望各 256！

// 正确：elementNum = 总字节数 = 512（两个 256 字节寄存器）
Reg::LoadAlign<uint8_t, ..., DIST_DINTLV_B8>(vd0, vd1, addr, 512);
```

### 6.2 循环中缺少 POST_MODE_UPDATE

```cpp
// 错误：每次迭代加载相同数据
for (uint16_t i = 0; i < loopNum; i++) {
    Reg::LoadAlign<uint8_t, Reg::PostLiteral::POST_MODE_KEEP>(vd, addr, 256);
}

// 正确：地址自动前进
for (uint16_t i = 0; i < loopNum; i++) {
    Reg::LoadAlign<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(vd, addr, 256);
}
```

### 6.3 LoadDist 元素类型不匹配

```cpp
// 错误：DIST_E2B_B32 用于 16-bit 元素类型
Reg::LoadAlign<bfloat16_t, ..., DIST_E2B_B32>(vd, addr, 8);

// 正确：16-bit 元素使用 B16 变体
Reg::LoadAlign<bfloat16_t, ..., DIST_E2B_B16>(vd, addr, 8);
```

### 6.4 DIST_UNPACK4_B8 后忘记 Cast

```cpp
// 错误：解包数据不能直接使用
Reg::LoadAlign<uint8_t, ..., DIST_UNPACK4_B8>(vdU8, addr, 64);
Reg::Mul(vdDst, vdU8, vdScale, mask);  // vdU8 仍是原始字节！

// 正确：解包后 Cast
Reg::LoadAlign<uint8_t, ..., DIST_UNPACK4_B8>(vdU8, addr, 64);
Reg::Cast<bfloat16_t, fp4x2_e2m1_t, traitFp4>(vdBf16, (Reg::RegTensor<fp4x2_e2m1_t>&)vdU8, mask);
Reg::Mul(vdDst, vdBf16, vdScale, mask);
```

## 7. 相关模式

见 `INDEX.md` 了解使用 LoadAlign 的组合模式：
- **模式 1.1**：完全顺序恢复（FP8 → FP32）
- **模式 1.2**：多布局 Cast + Add（→ BF16/FP16）
- **模式 1.3**：FP4 解码流水线（手动，无 DIST_UNPACK4_B8）
- **模式 1.4**：FP4 快速解码（DIST_UNPACK4_B8 + Cast）
- **模式 1.5**：Scale 预处理（FP8_E8M0 → BF16 → FP32）
- **模式 1.6**：Scale 预处理（FP8_E8M0 → BF16 only）
