# cast — 类型转换 / 位宽变换 VF 范式

> 类别范式总纲：判据 → 指令链选型 → 结构模板 → 陷阱。检索先读本文件，再读下方条目。

## 判据（结构信号）

VF 的核心计算是 **dtype 变换**（同布局不同位宽 / 打包解包），非算术运算本身。常见形态：
- FP32 → FP16/BF16（压缩 cast，`DIST_PACK_B32`）
- FP16/BF16 → FP32（解包升宽，`DIST_UNPACK_B16`）
- 归一化 / 缩放与 cast 融合的出口 VF（`Muls/Mul` + `Cast` + Store）
- 累加结果收敛 cast（每 tile 最后一拍）

## 指令链选型

| 变换 | 标准链 | 要点 |
|------|--------|------|
| FP32→FP16/BF16 | `Cast<DY,float,CAST_RINT+NO_SAT>` + `StoreAlign<DY,DIST_PACK_B32>` | **单次 ZERO Cast + PACK 存储**是 A5 实测位级正确模式；禁 ZERO/ONE 双 Cast+Add 合并（`cast.md` §7.2 在该芯片产生错序数据） |
| FP16/BF16→FP32 | `LoadAlign<DX,DIST_UNPACK_B16>` + `Cast<float,DX,ZERO>` | mask 用 **fp32 源宽度**（`UpdateMask<float>`）；升宽无需 Interleave 还原 |
| fp32→fp32 | 纯 `LoadAlign/StoreAlign` 拷贝（`if constexpr` 编译期直通） | 零 Cast 指令 |

## 结构模板

两层（`__aicore__` wrapper + `__simd_vf__`）；纯 cast 简单 API 无需 `__simd_callee__`。每轮 64 元素（fp32 粒度）。

## 横切标签

`multi-dtype`（DTYPE_CODE 编译期分派）、`mask-tail`（fp32 粒度 mask 全程共用）。

## 常见陷阱（最高频）

1. **FP16/BF16 出口无 PACK**：16bit Store 按寄存器全宽写出，pad 区全毁；必须 `DIST_PACK_B32`。
2. **CastTrait RoundMode 命名空间**：`AscendC::RoundMode::`（非 `Reg::` 子空间）。
3. **golden 用 `astype`（RN）与硬件 `CAST_RINT`（RNE）位级一致**——可作为位级 golden 依据；但乘法/除法顺序必须与 kernel 逐指令镜像（fp32 不结合）。
4. **bf16 哨兵值可表示性**：777.0 在 bf16 舍入为 776，哨兵断言必须选低精度可精确表示值（如 768.0）。
5. **FP32→低精度 Cast 的 RoundMode/SatMode 不可用 UNKNOWN**：必须 `CAST_RINT` + `NO_SAT`/`SAT`。

## 条目索引

| 条目 | 内容 | 标签 |
|------|------|------|
| `experience-fp32-to-low-precision.md` | FP32→FP16/BF16 单 Cast+PACK 标准形、mask 粒度、极端值探针 | `multi-dtype`, `mask-tail` |
| `experience-golden-rounding-alignment.md` | 位级 golden 三要素（单除链/乘法顺序/RNE cast）、inf 探针与有限元素掩码、bf16 哨兵选型 | `multi-dtype` |

## 实证来源

`adaptive_avg_pool_3d/normalize_cast_out_vf_lesson.md`、`adaptive_avg_pool_3d/normalize_cast_vf_lesson.md`、`moe_finalize_routing/cast_output_vf_lesson.md`（已迁移，原 lesson 在算子 record dir）。
