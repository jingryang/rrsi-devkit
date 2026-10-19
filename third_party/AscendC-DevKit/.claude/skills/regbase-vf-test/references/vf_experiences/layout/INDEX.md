# layout — 布局变换 VF 范式

> 类别范式总纲：判据 → 指令链选型 → 结构模板 → 陷阱。检索先读本文件，再读下方条目。

## 判据（结构信号）

VF 核心是**数据重排**（transpose / interleave / deinterleave / 压缩扩展），输入输出元素相同但位置不同，不做数值计算。

## 指令链选型

| 形态 | 标准链 | 要点 |
|------|--------|------|
| 2D tile 转置（b16/b32/b64） | 目标行 `Gather`：`Arange+Muls(×pitch)` 生成段内索引 → 按目标行 `Gather(dstReg, xUb+行基址, idxReg, mask)` → `StoreAlign(yUb+行基址)` | 行号 j 与段偏移 s·VL·pitch 都折叠进 Gather 的 **baseAddr 指针算术**（双重折叠），寄存器只保留 `k·pitch` |
| 索引零搬运 | `Arange(IS,0)` + `Muls(×pitch)` 寄存器内生成 | Arange 无 unsigned dtype，用有符号别名 `IS`(int16/int32) 生成，`RegTensor<IX>&` reinterpret 为 unsigned 索引读取 |
| b8 转置 | `Gather(u16, u8源, u16 idx)`（b8→b16 零扩展）→ `DeInterleave(同源)` 压紧偶字节 → StoreAlign | Gather 不支持 b8→b8；DeInterleave 同源 `(src0==src1)` 按 1 字节粒度压紧，比 `Pack` 输出布局可靠 |

## 结构模板

两层或三层（段循环抽到 `__simd_callee__`）。段偏移**不进寄存器**（折叠进基址指针），规避 `Adds<u16>` 符号域溢出（>32767 错乱；`Muls<u16>` 无此问题）。

## 横切标签

`multi-dtype`、`mask-tail`。

## 常见陷阱（最高频）

1. **b8 的 UpdateMask 计数**：`UpdateMask<uint8_t>` 按 VL_T=256 递减，但 b8 段每段只产 128 个有效元素——共享计数器跨段导致段 0 mask 越界 + 段 1 计数下溢丢数据。**每段独立 `min(remain,128)`**（callee 内、循环外初始化，满足 static_check）。
2. **契约签名不可增参**：VF 单测验证的函数必须与 s4 集成按契约调用的一致；host 索引表/额外 tensor 参数方案（+idxLocal+模板参）即使 42/42 通过也判签名失配。索引一律寄存器内生成。
3. **static_check：UpdateMask 计数必须简单变量且循环体内无赋值**——需要"每行重置"时把段循环抽到 `__simd_callee__`。
4. **StoreAlign 模板类型**：寄存器声明统一用 DX，reinterpret 仅用于 DeInterleave。

## 条目索引

| 条目 | 内容 | 标签 |
|------|------|------|
| `experience-gather-transpose.md` | 目标行 Gather 转置、双重折叠、索引零搬运、b8 DeInterleave 压紧、UpdateMask 计数陷阱、manifest 门校验 | `multi-dtype`, `mask-tail` |

## 实证来源

`transpose/transpose2_d_tile_vf_lesson.md`（已迁移，原 lesson 在算子 record dir）。
