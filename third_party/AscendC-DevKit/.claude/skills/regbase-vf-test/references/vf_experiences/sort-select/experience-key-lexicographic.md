# 构键字典序编码（key 构造 + 哨兵 + padding 三元组）

## 适用判据

排序/选择 VF 需要把「比较语义」编码进位流（Top-K 字典序 `(key DESC, idx ASC)` 决胜）。**构键必须与 python golden 逐位同构**。

## 关键实现要点

1. **三模式构键**：
   - int 系：`INT_SIGN_FLIP(bits ^ sign)`（符号位翻转后按无符号比较）
   - uint 系：`UINT_IDENTITY`（直接按无符号）
   - float 系：`FLOAT_TOTAL_ORDER`（pos=`b|sign`、neg=`~b`、符号位 NE 选择）+ `NaN→KEY_MAX`（仅 NAN_ON）+ `largest=0 整体 Not`
2. **升域（宽 key 压缩进 u32 流）**：`Interleave-with-zero`（u16 1 级 / u8 2 级）——全流 u32 域（Gather 不支持 B64，见 dual-stream 条目）。
3. **padding 三元组 `(key=0, ~idx=0)`**：复合字典序恒最劣，universe 有效元素恒 ≥ k → padding 不入前 k。
4. **哨兵位模式表**（largest=1→KEY_MIN 端 / 0→KEY_MAX 端）：

   | DX | largest=1 (KEY_MIN) | largest=0 (KEY_MAX) |
   |----|--------------------|--------------------|
   | int8 | 0x80 | 0x7F |
   | uint8 | 0x00 | 0xFF |
   | int32 | 0x80000000 | 0x7FFFFFFF |
   | int64 | 0x8000000000000000 | 0x7FFFFFFFFFFFFFFF |
   | fp16 | 0xFC00 (-inf) | 0x7C00 (+inf) |
   | fp32 | 0xFF800000 (-inf) | 0x7F800000 (+inf) |
   | bf16 | 0xFF80 (-inf) | 0x7F80 (+inf) |

   **float 哨兵取 ±inf 非 NaN**——NaN 在构键时被强制 KEY_MAX，哨兵若用 NaN 位模式会被检测捕获反转为最优侧（方向反转灾难）。
5. **golden 口径**：universe 按 `(key DESC, idx 位模式 ASC)` 全排序取前 k，**bit-exact 位模式比较**（整数/位域输出走 `compare_tensor` exact 或 `threshold=0.0`，禁默认 MERE/MARE 放行位差异）；NaN 语义开关必须与 kernel `nanMode` 镜像（模板 bool ↔ golden 参数）。

## 坑位与对策

| 现象 | 根因 | 对策 |
|------|------|------|
| u8/u16 候选区后窗 Store 覆盖前窗 | 窗 ELEMS(64) < VL（u8:256/u16:128） | key 升到 K32 域使 ELEMS=VL |
| 升域域翻转失配（跨段 key 值域不一致） | 升域后 largest=0 用全宽 Not（0xFFxx 域 vs 0x00xx 域，u32 流上恒大恒赢） | **方向取反限定原宽有效域**：`Xor 0x00FF`（高 8 位保持 0），与"原宽 Not 后零扩展"逐位一致 |
| golden NaN 口径分歧（期望顶置、kernel 沉底） | golden 恒做 NaN→KEY_MAX，kernel 在 `if constexpr(NAN_ON)` 内 | golden `build_key(..., nan_on)` 参数化与 kernel 一致传递 |
| golden u64→int64 序反转 | `(~idx).astype(np.int64)` 是 wrap（模 2^64），跨 wrap 边界降序反转 | 保序平移 `(x - np.uint64(1<<63)).view(np.int64)`（禁 astype） |
| all_min 全同键+哨兵冲突 | 字典序决胜需要 idx 参与 | golden 与 kernel 同规则（哨兵 idx 参与位模式竞争） |

## 可复用模式（最小骨架）

- 位级比较用 `np.array_equal`；u64 位模式域全程 uint 视图（int8→uint8/fp16→uint16/fp32→uint32/bf16→uint16）。
- sentinel_bits python 侧与 kernel 同源（int 按 `(1<<(w-1))`、uint 按 `0/(1<<w)-1`、float 按 `float_to_bits(∓inf)`，方向由 largest 选择）。

## 横切标签

`multi-dtype`、`mask-tail`。

## 实证来源

- `top_k` `top_k_select`（3 轮 60/60；构键语义 + 坑 1-17 + probe17）
- `top_k` `sort_emit_top_k` / `local_top_k_merge` / `final_sort`（构键逐位同款；坑 36 golden NaN 口径）
- `top_k` `init_cand_region`（哨兵位模式表 + 指针 tag dispatch）
