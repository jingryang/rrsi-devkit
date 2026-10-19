# elementwise — 逐元素 / 标量运算 VF 范式

> 类别范式总纲：判据 → 指令链选型 → 结构模板 → 陷阱。检索先读本文件，再读下方条目。

## 判据（结构信号）

VF 核心是**逐元素算术/激活链**：`y[i] = f(x[i])` 或 `y[i] = f(x0[i], x1[i])`，输入输出一一对应、同布局。常见形态：
- 纯逐元素链（add/mul/div/exp/relu/…）
- 混合精度链（低精度入→fp32 中间→低精度出，如 silu/gelu/swiglu）
- 标量参入（`y = x*s + b`，标量直传 `Muls/Adds`）

## 指令链选型

| 形态 | 标准链 | 要点 |
|------|--------|------|
| 同宽 fp32 | `LoadAlign → 计算链 → StoreAlign`，64 元素/轮 | `REPEAT_STRIDE = 256/4 = 64` |
| 低位宽入 | `LoadAlign<DX,DIST_UNPACK_B16>` + `Cast<float,DX,ZERO>` 升 fp32 | 中间全程 fp32 |
| 低位宽出 | `Cast<DX,float,CAST_RINT>` + `StoreAlign<DX,DIST_PACK_B32>` | 出口 cast 回输入 dtype |
| 标量运算 | `Muls/Adds(dst, src, scalar, mask)` | **标量直接作指令实参**，禁先广播到 UB 再 Load |
| 复合激活 | `Muls(-1) → Exp → Adds(1) → Div`（silu）；`Rsqrt = Sqrt + Div` | 组合逻辑可封装 `__simd_callee__`（仅操作 RegTensor） |

## 结构模板

两层（简单 API）或三层（复合 API：`__aicore__` → `__simd_vf__` → `__simd_callee__`）。循环内 `if constexpr` 按 `sizeof(DX)` 双路径分发零开销（Hardware Loop 合规）。

## 横切标签

`multi-dtype`（dtype 编译期分派）、`mask-tail`。

## 常见陷阱（最高频）

1. **RoundMode 命名空间**：`AscendC::RoundMode::`（非 `Reg::`）。
2. **低精度链精度**：先 fp32 验证通过再泛化 half/bf16（half 的 `DIST_UNPACK_B16`+Cast 两条指令 buffer 越界风险大）。
3. **golden 运算顺序镜像**：kernel 指令序（先加后乘/先乘后加）必须与 numpy golden 逐序一致（fp32 不结合）。
4. **硬件循环**：`uint16_t i`、0 起、++i、无运行时分支（仅 `if constexpr`）；`Duplicate/CreateMask` 外提。

## 条目索引

| 条目 | 内容 | 标签 |
|------|------|------|
| `experience-mixed-precision-elementwise.md` | 位宽 Cast 双 trait、低精度逐元素链（UNPACK 升宽 + PACK 降宽）、silu 四指令链、dtype 单 kernel 分派 | `multi-dtype`, `mask-tail` |

## 实证来源

`exp/compute_exp_vf_lesson.md`、`swi_glu/compute_swi_glu_lesson.md`（已迁移，原 lesson 在算子 record dir）。
