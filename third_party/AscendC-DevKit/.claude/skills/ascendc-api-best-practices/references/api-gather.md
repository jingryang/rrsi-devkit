# Gather / BilinearInterpolation 使用指南

> **适用场景**：按运行时索引/坐标间接寻址采样（输出每元素 = 输入里若干运行时确定、跨维偏移位置的加权组合）时，替代逐元素 DataCopyPad 单元素事务。

---

## 目录

- [概述](#概述)
- [平台适用性](#平台适用性)
- [Gather（ISASI）详解](#gatherisasi详解)
- [BilinearInterpolation（ISASI）详解](#bilinearinterpolationisasi详解)
- [常见错误](#常见错误)
- [检查清单](#检查清单)
- [适用性检测](#适用性检测)
- [参考资料](#参考资料)

---

## 概述

间接寻址采样（按 index/坐标张量取输入里非连续位置的值）时，三个原语按**粒度/dtype**选：

| 场景 | 原语 | 关键点 |
|------|------|--------|
| 运行时任意偏移（每元素独立，元素粒度） | `Gather`（ISASI） | `srcOffset` 为运行时字节偏移数组，src 在 UB；支持 fp16/fp32/bfloat16 |
| DataBlock 粒度采样 + 双线性（half） | `BilinearInterpolation`（ISASI） | 偏移取 DataBlock + 加权累加一条指令；**仅 half** |
| 固定间隔提取 | `GatherMask` | 属解交织主题，勿误用于运行时任意索引 |

分块策略（沿哪维切、采样窗口如何退化为局部条带）属概要设计模式，见设计模式库的「索引间接搬运」条目；本文件只讲 API 用法与约束。

## 平台适用性

| 平台 | 适用性 | 说明 |
|------|--------|------|
| **A2 / A3**（DAV_2201） | ✅ 推荐 | `Gather` 支持 fp16/fp32/bfloat16；`BilinearInterpolation` 仅 half。间接索引 = 分块搬入 + UB 内 `Gather`/`BilinearInterpolation` |
| **A5**（DAV_3510） | ✅ 支持 | 有 `Gather`（srcReg 寄存器为源，SIMT 模型）+ `GatherB`，寄存器间接寻址对随机访问更友好 |

> 数据经 UB 做矢量计算是 A2/A3 Vector 模型的通用前置（非 Gather 特例）：GM → 搬运 API → UB → 矢量计算 → UB → CopyOut。

---

## Gather（ISASI）详解

**功能**：按 `srcOffset`（运行时字节偏移数组）从 UB 里的 src 逐元素收集到 dst。

```cpp
template <typename T>
__aicore__ inline void Gather(const LocalTensor<T>& dst, const LocalTensor<T>& src,
                              const LocalTensor<uint32_t>& srcOffset,
                              const uint32_t srcBaseAddr, const uint32_t count);
```

**offset 越界钳制**（间接采样必做）：

- `srcOffset` 须落在 src（分块条带）内，越界位置**先坐标变换再钳制**——`min(floor, W-1)`（或对应维上限），配合 padding_mode 在权重侧实现 zeros（权重置 0）/ border（钳读边界值）；reflection 是坐标反射后再钳制。
- 示例（规则坐标一次预生成，任意坐标运行时逐元素算）：
  ```cpp
  // w0 = min(floor(wSrc), W-1)；w1 = min(w0+1, W-1)；字节偏移 = 索引 × sizeof(T)
  Mins(w0I, w0I, (int32_t)(WIn - 1U), n);          // 钳制
  Muls(w0Off_, w0I, (int32_t)sizeof(T), n);         // 字节偏移
  Adds(w1Off_, w0Off_, (int32_t)sizeof(T), n);
  Mins(w1Off_, w1Off_, (int32_t)((WIn - 1U) * sizeof(T)), n);
  Gather(gA_, src, w0OffU32_, rowBase, n);          // 按偏移向量提取
  ```

**约束**：

| 项 | 约束 |
|----|------|
| 对齐 | src / dst / srcOffset 起始地址均 32B 对齐 |
| offset 单位 | **字节**（相对 src 基地址，须 dtype 位宽对齐） |
| dtype | A2/A3 支持 int16/uint16/int32/uint32/float/half/bfloat16 |

---

## BilinearInterpolation（ISASI）详解

**功能**：水平迭代（每次从 `src0Offset` 取 8 个 DataBlock 偏移 + 8 个权重相乘累加）+ 垂直迭代（vRepeat 次累加），一条指令完成「偏移取块 + 加权累加」。

**粒度与 3D 覆盖**：

- `src0Offset` 是 **DataBlock（32B）粒度**——每个偏移指向一个 DataBlock 起始地址。
- 因此**不适用「元素粒度相邻角点」的插值**（相邻角点差 2B/4B、落在同一 DataBlock，DataBlock 粒度 offset 无法区分）。
- 元素粒度插值（含 3 维采样）走 `Gather`（元素粒度 offset）+ 手动向量乘加，而非本指令。

**约束**：

| 项 | 约束 |
|----|------|
| dtype | **仅 half**（A2/A3 均） |
| src0Offset | DataBlock（32B）粒度 |
| 地址重叠 | src0 / src1 / src0Offset 之间不允许重叠 |

---

## 常见错误

| 错误 | 原因 | 解决方案 |
|------|------|---------|
| 逐元素 DataCopyPad 单元素事务做间接采样 | 每元素独立搬 1 元素时，A2/A3 只有 Normal 模式（逐事务补 32B）+ dst 32B 对齐约束 → 每元素占 32B 槽位 UB 爆炸 + 全标量（PIPE_S）路径 | 分块搬入 + `Gather`（元素粒度 offset）做偏移提取 |
| offset 未钳制越界 | 越界 offset 指向 src（条带）之外，UB 越界 | 先坐标变换再 `min(floor, W-1)` 钳制，padding_mode 在权重侧实现 zeros/border |
| BilinearInterpolation 用于元素粒度相邻角点 | src0Offset 是 DataBlock 粒度，区分不了同 DataBlock 内的相邻元素 | 元素粒度插值走 `Gather` + 手动向量乘加 |
| 全局 `GlobalTensor::SetValue/GetValue` 逐元素读写 | 效率极低，仅调试可用 | 见 api-datacopy.md 黑名单 |

---

## 检查清单

- [ ] 间接采样走「分块搬入 + Gather」，非逐元素 DataCopyPad 单元素事务
- [ ] `srcOffset` 是字节偏移（相对 src 基地址），越界位置已钳制
- [ ] padding_mode（zeros/border/reflection）在权重侧实现
- [ ] src / dst / offset 起始地址 32B 对齐
- [ ] 元素粒度插值用 `Gather`，非 `BilinearInterpolation`（后者仅 DataBlock 粒度 + half）

---

## 适用性检测

```bash
# 逐元素 DataCopyPad 单元素事务（间接采样反模式）
grep -nE "DataCopyPad.*\{1,\s*sizeof|blockLen.?=.?1|DataCopyPad\(.*\{1\b" op_kernel/*.cpp

# 逐元素 SetValue/GetValue 数据搬送（主循环内）
grep -nE "for.*(SetValue|GetValue)" op_kernel/*.cpp
```

---

## 参考资料

- CANN 8.5.0 API 文档 — Gather（ISASI）：页面 ID atlasascendc_api_07_0092
- CANN 8.5.0 API 文档 — BilinearInterpolation（ISASI）：页面 ID atlasascendc_api_07_0222
- CANN 8.5.0 API 文档 — Gatherb（ISASI）：页面 ID atlasascendc_api_07_0234
