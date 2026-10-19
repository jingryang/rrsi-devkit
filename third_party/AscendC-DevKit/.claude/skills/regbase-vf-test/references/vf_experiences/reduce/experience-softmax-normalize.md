# 两遍归一化（softmax 家族）与行规约基础

## 适用判据

逐行两遍处理：第一遍 `ReduceMax → Sub → Exp → ReduceSum`，第二遍 `exp/Σexp` 归一化。`dimSize × sizeof(DX)` 32B 对齐、`rowStride == dimSize`（T1_ALIGNED_LAST 约束）场景。

## 关键实现要点

1. **VF 单测优先用 `float`**（最重要经验）：float 的 LoadAlign 走 `DIST_NORM`（256B 对齐读，无需 cast），buffer 开销简单可预测；half 走 `DIST_UNPACK_B16`+Cast 两条指令，buffer 越界风险大。float 验证通过后再泛化到 half/bf16（`LoadDxToFp32` / `StoreFp32ToDx` 模式）。
2. **UB buffer 分配加安全余量**：`AlignUp(实际需求, 32) + 256`。反例：`rowStride*sizeof(DX)` 仅 32B → LoadAlign 读 128B → 96B 越界污染相邻 buffer。
3. **首段禁止 `pregFull`（ALL mask）**：dimSize < VL 时首段必须 `UpdateMask(dimSize)`；每段统一 `UpdateMask(sreg)` 递减 `min(VL, 剩余)`，不搞特殊化。
4. **中间结果全程 fp32**：`x(DX) → LoadDxToFp32 → 全 fp32 计算 → StoreFp32ToDx(exp) → Store(sumExp as float)`；ReduceMax/ReduceSum 的浮点掩码用 `UpdateMask<float>`（非 `UpdateMask<DX>`）。
5. **sumExp 存储**：`StoreAlign<float, DIST_FIRST_ELEMENT_B32> + MaskPattern::VL1`——每行只写首元素（标量）。

## 坑位与对策

| 现象 | 根因 | 对策 |
|------|------|------|
| half VF 输出全错、sum=0（OOB） | DX=half + 无 buffer guard + 首段 pregFull → 越界读 96B 污染相邻 buffer | float 优先；buffer +256 guard；首段 UpdateMask |
| OOB 检测到 sumExp 没被写 | sumExp buffer 被 load 越界写脏、StoreAlign 地址错位 | buffer 加 guard 防 load 超范围 |
| npy 精度对不上 | half 回路 Cast(fp32→half→fp32) 精度损失放大 | 先 float 通过再泛化 half |

## 可复用模式（最小骨架）

```cpp
uint32_t colAlignBytes = AlignUp(dimSize * sizeof(DX), 32);
uint32_t bufferBytes = AlignUp(tileRows * colAlignBytes + 256, 32);  // guard ≥256 覆盖最大读宽

uint32_t remaining = dimSize;
for (uint16_t r = 0; r < tileRows; r++) {
    uint32_t sreg = remaining;
    Reg::MaskReg mask = Reg::UpdateMask<float>(min(sreg, VL_FP32));  // 首段禁 pregFull
    // ... LoadDxToFp32 → ReduceMax/Sub/Exp/ReduceSum 全 fp32 ...
}
```

## 横切标签

`multi-dtype`、`mask-tail`、`reduce`。

## 实证来源

- `softmax` `compute_softmax_first_norm` / `second_norm`（10/10+；DX=float 首跑通过经验）
- 会话汇总（DX 选择、guard、首段 mask）原 lesson：`softmax/softmax_vf_tests_summary.md`
