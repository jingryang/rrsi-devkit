# Reg::Interleave

> **概述**：API 语义、粒度控制（uint8/16/32/64/float）、参数顺序规则、原地用法、两级交错模式，以及关键的 Src0/Src1 参数顺序陷阱。

## 1. 用途

通过交错两个源寄存器的元素进行交叉合并。Src0 的元素放在合并流的**偶数位置**，Src1 的元素放在**奇数位置**。

Reg::Interleave 是**恢复多布局 `Reg::Cast` 操作后的顺序**的主要工具，也用于**类型转换流水线中的寄存器级数据布局重排**。

---

## 2. API 签名

```cpp
Reg::Interleave(dst0, dst1, src0, src1);
```

| 参数 | 说明 |
|-----------|-------------|
| `dst0` | 第一个目标寄存器（接收偶数位置的元素） |
| `dst1` | 第二个目标寄存器（接收奇数位置的元素） |
| `src0` | 第一个源寄存器（元素进入偶数位置） |
| `src1` | 第二个源寄存器（元素进入奇数位置） |

**原地模式**（最常用）：
```cpp
Reg::Interleave(A, B, A, B);  // A 和 B 原地修改
```

---

## 3. 粒度控制

### 3.1 由元素类型决定的粒度

交错单元大小取决于 `RegTensor<T>` 的元素类型：

| 元素类型 | 交错单元 | 每次交换字节数 | 图示（16 个元素） |
|-------------|-----------------|----------------|---------------------|
| `uint8_t` | 1 字节 | 1 | `a0 b0 a1 b1 a2 b2 ...` |
| `uint16_t` | 2 字节 | 2 | `a0 a1 b0 b1 a2 a3 b2 b3 ...` |
| `uint32_t` / `float` | 4 字节 | 4 | `a0 a1 a2 a3 b0 b1 b2 b3 ...` |
| `uint64_t` | 8 字节 | 8 | `a0..a3 b0..b3 a4..a7 b4..b7 ...` |

### 3.2 通过类型转换实现粗粒度 Interleave

要以比寄存器原生类型更粗的粒度进行交错，转换 `RegTensor` 引用：

```cpp
// float 寄存器（4 字节元素）以 uint64（8 字节）粒度交错
Reg::Interleave(
    (Reg::RegTensor<uint64_t>&)vdFp32_a,
    (Reg::RegTensor<uint64_t>&)vdFp32_b,
    (Reg::RegTensor<uint64_t>&)vdFp32_a,
    (Reg::RegTensor<uint64_t>&)vdFp32_b);
```

**效果**：每 8 字节交换一次，而不是每 4 字节。这在第一级 `uint32` 交错后，合并 `(0,1)` 对与 `(2,3)` 对时很有用。

### 3.3 图示：不同粒度

从两个 float 寄存器开始（各 64 个 float，共 256 字节）：

**Interleave 前：**
```
vdA (float): [f0, f1, f2, f3, ..., f63]
vdB (float): [g0, g1, g2, g3, ..., g63]
```

**以 float (uint32) 粒度 Interleave 后：**
```
vdA: [f0, g0, f1, g1, f2, g2, ..., f31, g31]
vdB: [f32, g32, f33, g33, ..., f63, g63]
```

**以 uint64 粒度 Interleave 后：**
```
vdA: [f0, f1, g0, g1, f2, f3, g2, g3, ...]
vdB: [f32, f33, g32, g33, ...]
```

---

## 4. 参数顺序：关键规则

**规则**：`Src0` 的元素进入**偶数位置**，`Src1` 的元素进入**奇数位置**。

### 4.1 陷阱：FP4 解码

使用 Interleave 为 `uint16_t` 的 `reinterpret_cast`（小端）准备数据时：

```cpp
// 错误：zero 在前 → 低字节变为 0
Reg::Interleave(vdInter0, vdInter1, vdZero, vdFp4U8);
// 内存布局：[0, b0, 0, b1, ...]
// uint16[i] = vdInter[2*i] | (vdInter[2*i+1] << 8)
//           = 0 | (b[i] << 8)
// 低 4bit = 0 → Cast 读取 0，不是 FP4 数据！
```

```cpp
// 正确：data 在前 → 低字节包含数据
Reg::Interleave(vdInter0, vdInter1, vdFp4U8, vdZero);
// 内存布局：[b0, 0, b1, 0, ...]
// uint16[i] = b[i] | 0 = b[i]
// 低 4bit = b[i] & 0xF → Cast 正确读取 FP4 值！
```

### 4.2 经验法则

对于小端系统，将需要放在**低字节**的数据作为 **Src0**。

对于多布局 Cast 后的偶/奇下标分离：
- 若 `vdA` 有偶数下标，`vdB` 有奇数下标：
  - `Interleave(vdA, vdB, vdA, vdB)` → `vdA = [a0, b0, a1, b1, ...]`

---

## 5. 两级 Interleave 模式

### 5.1 问题

4-layout Cast（FP8 → FP32）后，4 个寄存器持有：
- `_0 = [v0, v4, v8, ...]`
- `_1 = [v1, v5, v9, ...]`
- `_2 = [v2, v6, v10, ...]`
- `_3 = [v3, v7, v11, ...]`

一级交错无法恢复完全顺序。

### 5.2 Level 1：Cross-Pair（0+2, 1+3）

```cpp
Reg::Interleave(vd_0, vd_2, vd_0, vd_2);  // vd_0 获得 0/2 交错
Reg::Interleave(vd_1, vd_3, vd_1, vd_3);  // vd_1 获得 1/3 交错
```

Level 1 后：
- `vd_0 = [v0, v2, v4, v6, ...]`（前半部分偶数）
- `vd_1 = [v1, v3, v5, v7, ...]`（前半部分奇数）
- `vd_2 = [v128, v130, ...]`（后半部分偶数）
- `vd_3 = [v129, v131, ...]`（后半部分奇数）

### 5.3 Level 2：合并对（0+1, 2+3）

仅** FP32 输出路径**需要：

```cpp
Reg::Interleave(vd_0, vd_1, vd_0, vd_1);  // vd_0 = [v0..v63], vd_1 = [v64..v127]
Reg::Interleave(vd_2, vd_3, vd_2, vd_3);  // vd_2 = [v128..v191], vd_3 = [v192..v255]
```

Level 2 后：
- `vd_0 = [v0, v1, v2, ..., v63]`（完全顺序）
- `vd_1 = [v64, v65, ..., v127]`（完全顺序）
- `vd_2 = [v128, ..., v191]`
- `vd_3 = [v192, ..., v255]`

### 5.4 Level 2 以 uint64 粒度（替代方案）

```cpp
// 以 8 字节粒度合并 (0,1) 对与 (2,3) 对
Reg::Interleave(
    (Reg::RegTensor<uint64_t>&)vd_0, (Reg::RegTensor<uint64_t>&)vd_2,
    (Reg::RegTensor<uint64_t>&)vd_0, (Reg::RegTensor<uint64_t>&)vd_2);
Reg::Interleave(
    (Reg::RegTensor<uint64_t>&)vd_1, (Reg::RegTensor<uint64_t>&)vd_3,
    (Reg::RegTensor<uint64_t>&)vd_1, (Reg::RegTensor<uint64_t>&)vd_3);
```

这与 float 粒度的 Level 2 效果相同，但使用不同的交错单元。

### 5.5 何时跳过 Level 2

对于** BF16/FP16 输出**，跳过 Level 2。Level 1 后：
- `vd_0 = [v0, v2, v4, ...]`（偶数下标）
- `vd_1 = [v1, v3, v5, ...]`（奇数下标）

改用多布局 Cast + Add：
```cpp
Reg::Cast<bf16, float, trait_0>(vdZ, vd_0, mask);  // ZERO → 偶数槽位
Reg::Cast<bf16, float, trait_1>(vdO, vd_1, mask);  // ONE → 奇数槽位
Reg::Add(vdZ, vdZ, vdO, mask);  // 合并 → 完全顺序
```

### 5.6 Self-Interleave 用于广播扩展

**目标**：将寄存器内广播值的重复次数翻倍。

**上下文**：`LoadAlign` 配合 `DIST_E2B_B16` 后，每个 scale 值占据 16 个连续槽位。FP4 反量化每个 block 需要 32 个 scale 重复（每 FP4 字节 2 个值 × 每 block 16 字节）。Self-Interleave 将 16 次重复块扩展为 32 次重复块。

**数据流**：
```
Before: vdScaleTmp = [A×16, B×16, C×16, D×16, E×16, F×16, G×16, H×16]
Interleave(vdScaleTmp, vdScaleTmp):
  vdScale0 = [A×32, B×32, C×32, D×32]  (前半部分)
  vdScale1 = [E×32, F×32, G×32, H×32]  (后半部分)
```

**代码**：
```cpp
Reg::LoadAlign<bfloat16_t, POST_MODE_UPDATE, DIST_E2B_B16>(
    vdScaleTmp0, scaleBufAddr, elementAfterReduce_);  // 8 scales × 16 reps each

// Self-interleave: src0 == src1 将重复数翻倍
Reg::Interleave(vdScale0, vdScale1, vdScaleTmp0, vdScaleTmp0);
// vdScale0 现在有 4 scales × 32 reps (covers blocks 0..3)
// vdScale1 现在有 4 scales × 32 reps (covers blocks 4..7)
```

**核心思路**：当 `src0 == src1` 时，交错相同的元素实际上将相邻的相同块合并为更大的相同块。寄存器被分为两半：前半部分进入 `dst0`，后半部分进入 `dst1`。

---

## 6. 单指令使用示例

### 6.1 2-Layout Cast 后恢复顺序

```cpp
// Cast ZERO/ONE 后：vdA 有偶数，vdB 有奇数
Reg::Interleave(vdA, vdB, vdA, vdB);
// vdA = [v0, v1, v2, ..., v127] (顺序)
// vdB = [v128, v129, ..., v255] (顺序)
```

### 6.2 FP4 手动解码后恢复顺序

使用手动 FP4 解码流水线（无 `DIST_UNPACK4_B8`）时：

```cpp
// vdLow = [fp4_0, fp4_2, fp4_4, ...]  (来自 Cast low 4bit)
// vdHigh = [fp4_1, fp4_3, fp4_5, ...] (来自 ShiftRights 后的 Cast)
Reg::Interleave(vdMerged0, vdMerged1, vdLow0, vdHigh0);
// vdMerged0 = [fp4_0, fp4_1, fp4_2, fp4_3, ...] (顺序)
```

**注意**：在支持 `DIST_UNPACK4_B8` 的芯片上，此手动流水线不必要——`LoadAlign` + `Cast(ZERO)` 直接处理 FP4 解码。见 `INDEX.md` 模式 1.4。

### 6.3 原地 Self-Interleave

```cpp
// vdA 和 vdB 既是源也是目标
Reg::Interleave(vdA, vdB, vdA, vdB);
// 无需临时寄存器
```

---

## 7. 常见陷阱

### 7.1 Src0/Src1 顺序错误

```cpp
// 错误：用于小端低字节提取
Reg::Interleave(vdInter0, vdInter1, vdZero, vdData);

// 正确
Reg::Interleave(vdInter0, vdInter1, vdData, vdZero);
```

见第 4.1 节详细说明。

### 7.2 忘记原地修改

```cpp
// 若 Interleave 后需要原始值，先复制
Reg::RegTensor<float> vdA_orig, vdB_orig;
// ... 将 vdA 复制到 vdA_orig，vdB 复制到 vdB_orig ...
Reg::Interleave(vdA, vdB, vdA, vdB);
// 现在 vdA 和 vdB 已修改；vdA_orig/vdB_orig 持有原始值
```

### 7.3 粒度与目标不匹配

```cpp
// 错误：需要 uint64 时使用了 float 粒度
// 第一级 Interleave 后：vd_0 有 (0,1) 对，vd_2 有 (2,3) 对
// Float Interleave 会在每个 4 字节组内产生 [0,1,2,3]
// 但我们需要跨寄存器合并这些对

// 正确：第二级使用 uint64 粒度
Reg::Interleave((uint64_t&)vd_0, (uint64_t&)vd_2, ...);
```

### 7.4 BF16/FP16 不必要地做第二级 Interleave

```cpp
// 错误：做完完整 2 级 Interleave 后再 Cast 到 BF16
// 浪费指令；第一级后的 Cast + Add 已足够

// 正确：跳过 Level 2，使用 Cast + Add
// 见 INDEX.md 模式 1.2
```

---

## 8. 速查

### 8.1 Interleave 粒度选择

| 目标 | 使用类型 | 效果 |
|------|----------|--------|
| 合并字节级数据 | `uint8_t` | 每字节交换 |
| 合并 16-bit 元素 | `uint16_t` | 每 2 字节交换 |
| 合并 32-bit 元素 / float 对 | `uint32_t` / `float` | 每 4 字节交换 |
| 合并 64-bit 块 / float 四元组 | `uint64_t` | 每 8 字节交换 |

### 8.2 何时使用 Interleave

| 场景 | 操作 |
|----------|--------|
| 2-layout Cast 后 | 1× Interleave 恢复顺序 |
| 4-layout Cast → FP32 | 2× Interleave（Level 1 cross-pair + Level 2 merge） |
| 4-layout Cast → BF16/FP16 | 1× Interleave（仅 Level 1），然后 Cast + Add |
| FP4 手动解码（低 + 高 nibble） | 1× Interleave(vdLow, vdHigh) 恢复顺序 |
| Scale 预处理（FP8_E8M0 → BF16） | 1× Interleave 在 2-layout Cast 后 |
| Scale 预处理（BF16 → FP32） | 1× Interleave 在 2-layout Cast 后 |
| Scale 广播扩展（FP4 路径） | 1× Self-Interleave 将重复数翻倍 |

---

## 9. 相关模式

见 `INDEX.md` 了解使用 Interleave 的组合模式：
- **模式 1.1**：完全顺序恢复（4-layout → FP32）
- **模式 1.2**：多布局 Cast + Add（→ BF16/FP16）
- **模式 1.3**：FP4 解码流水线（手动）
- **模式 1.4**：FP4 快速解码（DIST_UNPACK4_B8 + Cast）
- **模式 1.5**：Scale 预处理（FP8_E8M0 → BF16 → FP32）
- **模式 1.6**：Scale 预处理（FP8_E8M0 → BF16 only）
- **模式 1.7**：Scale 广播扩展（Self-Interleave）
