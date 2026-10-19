# stateful-accumulator — 状态张量生命周期 VF 范式

> 类别范式总纲：判据 → 指令链选型 → 结构模板 → 陷阱。检索先读本文件，再读下方条目。

## 判据（结构信号）

VF 操作**跨调用持久的状态张量**，生命周期三段式：
- **init 段**：清 0 / 常量 / **哨兵位模式**填充候选区或累加器（`acc[i]=const`，全 k 槽）
- **accumulate 段**：**read-modify-write** 原地累加（`acc ← acc + term`），输出与输入同名（同一 UB buffer）
- **merge 段**：多个部分结果归并进状态（跨段/跨批）

判据核心：**输出与输入同名状态张量** / rmw 语义 / 跨调用持久（非本 VF 单次读写）。常与 `reduce` 计算模式配对（本类别管生命周期与测试编排，`reduce` 管归约算法）。

## 指令链选型

| 段 | 标准链 | 要点 |
|----|--------|------|
| init 填充 | `Duplicate(reg, 常量)`（循环外外提）+ 循环内 `UpdateMask(cnt)+StoreAlign(ub+i*VL, reg, mask)` | 各流按 `VL(T)` 满窗滚动（u8:256/u16:128/u32:64/u64:32），尾窗部分掩码天然不越写，**零分支**；双流独立同型 mask |
| init（flags 路由） | `__aicore__` 层 if/else 分发到多条无分支 `__simd_vf__`（4 路径） | 运行时 flag 不能进 `__simd_vf__` 循环体 |
| rmw 累加 | `Load(acc) → 计算 → Add(acc) → Store(acc)` | 同引擎程序序无同步需求；初值喂入见条目 |
| 哨兵填充 | 位模式标量 `Duplicate` 广播（按字节 bit-cast，全程无数值 Cast） | 方向反侧极值位模式（largest 反向）；**float 哨兵取 ±inf 非 NaN**（NaN 会被构键强制 KEY_MAX 反转为最优侧） |

## 结构模板

init 类两层；rmw 类两层。`sentinelBits` 位模式经 `__aicore__` 按字节拷贝 bit-cast 到 DX 标量（小端低位=DX 位模式），float 系 -inf/-NaN 位模式无损。

## 横切标签

`mask-tail`、`multi-dtype`、`simt-async`（SIMT 窗口累加）、`reduce`（累加即归约）。

## 常见陷阱（最高频）

1. **清零/常量输出不可观察**：写 0 与"未写"不可区分 → **双重哨兵**（GM 预填 777 + kernel 先把 UB acc 脏化再测被测 VF）+ **输出 0xCC 魔数初始化**（防 OOB data-unchanged 假阳性）。
2. **越写检测三件套**：GM 背景 CopyIn → VF 覆写 [0:k) → **全长 AU256 搬出**，断言 `[k:AU]` 背景不变（比仅验 [0:k) 严格，能抓尾窗 mask 失效越写）。
3. **条件循环内调 `__simd_callee__` → ccec 后端 segfault**（exit 139）：尾窗用 **UpdateMask 递减模式**替代"条件循环 + callee 调用"。
4. **rmw 测试 kernel 同步**：初值走 VECIN queue + V 引擎内 Copy seed（同引擎程序序）→ 被测 VF rmw → VECOUT EnQue/DeQue（V→MTE3）——跨引擎同步不能靠同一 queue 双向承载。
5. **类型驱动编译期常量路由**：模板 VF 内需按 DX 取不同常量（位模式/极值）时用**指针 tag dispatch**（重载函数族 + `static_cast<const DX*>(nullptr)`），零 traits 依赖、ccec 最稳、集成无宏环境可用。

## 条目索引

| 条目 | 内容 | 标签 |
|------|------|------|
| `experience-init-fill-sentinel.md` | 清零/常量/哨兵填充标准形、递减掩码、哨兵位模式表、指针 tag dispatch、越写检测三件套、0xCC 魔数 | `mask-tail`, `multi-dtype` |
| `experience-rmw-accumulate.md` | rmw 累加测试编排（seed 初值/queue 同步）、位级 golden 顺序、跨调用持久验证（batch 循环）、SIMT rmw | `reduce`, `simt-async`, `multi-dtype` |

## 实证来源

`adaptive_avg_pool_3d/init_acc_vf_lesson.md`、`adaptive_avg_pool_3d/accumulate_window_sum_vf_lesson.md`、`moe_finalize_routing/init_accumulator_vf_lesson.md`、`moe_finalize_routing/accumulate_term_vf_lesson.md`、`top_k/init_candidates_vf_lesson.md`、`top_k/init_cand_region_vf_lesson.md`（已迁移，原 lesson 在算子 record dir）。
