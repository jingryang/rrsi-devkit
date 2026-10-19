# max+argmax 行内配对归约（值 + int64 索引，NaN 首见）

## 适用判据

逐行/行段内求**最大值及其索引**（argmax），或 max 归约同时维护下标：输出 = `(max_val, argmax_idx)`。
典型 `max_argmax`（`ComputeMaxArgmaxChunk`：T1 快路径行内配对归约；`ComputeGenMaxArgmax`：T2 泛化
逐行配对更新）。特征信号：**值 + 索引双路并行选择**、**索引为 int64**、**多 dtype 输入**
（fp16/fp32/bf16/int8/int32/int64）、**NaN 首见 / tie 取首见 / 尾块掩尾**语义。

## 结构模板（fold → finalize → merge 三阶段）

| 阶段 | 作用 | 关键 API |
|------|------|---------|
| fold | lane 内两两配对：值取 strictly-greater、下标同步选择（NaN 接管） | `Compare(GT)` + `Compare(NE, x, x)` 自比判 NaN + `Select`（值/下标**双 Select**） |
| finalize | 把 fold 后的每行多个候选收敛为单值 + 首见索引 | `Reduce`(ReduceType::MAX) 取 max + NaN 首见掩码 + `Reduce`(ReduceType::MIN) 取最小 idx |
| merge | 跨 chunk 维护 running max/idx：`isChunk0` 无条件初始化，否则逐行配对更新 | `Compare(GT)`/`Compare(NE)` + `Select`（值/idx 双 Select）|

- **尾向量**：`FirstN(tailMaskBits)` 掩尾，避免尾块 pad 通道污染归约。
- **running 初值**：`Duplicate(MIN(T))`（值）/ 首见 idx 用 `Duplicate(idxBase + r, int64)` 之类预置。
- **int64 下标**：idx 走独立 int64 通路，与值（T）双 Select 同步；不要试图把 idx 塞进值类型。

## 关键 API 选型与坑位

| 坑 | 根因 | 对策 |
|----|------|------|
| `__simd_vf__` 只可调 `__simd_callee__` | 三层链 `__aicore__ → __simd_vf__ → __simd_callee__`；`__simd_vf__` 函数体内再调 `__simd_vf__` 会被拒（"simd_vf function can only call simd_callee function"） | 顶层 VF（`__simd_vf__ __aicore__`）内嵌循环/分派逻辑，抽取的带循环子函数标 `__simd_callee__`（内联后仍可识别硬件循环） |
| int64 index 与 64-lane value 域对齐 | value 计算域 fp32/int32 是 64 lane，int64 原生 32 lane，`Compare/Select` 无法对齐 | 用 `RegTensor<int64_t, RegTraitNumTwo>`（内部 reg[0]=lo/reg[1]=hi 两个 64-lane uint32），`LoadAlign/StoreAlign/Select/Duplicate` 自动拆位；勿手工 `DeInterleave/Interleave` 拆 int64 lo/hi（lo/hi 映射易错） |
| 测试 tiling struct 含 int64 字段偏移错位 | Python `pack_tiling_data` 用 numpy 紧凑打包（int64 在 uint32 后 offset=4），C++ struct 按 8 字节对齐（int64 offset=8）→ kernel 读到 reduceIdx=0 | 测试 tiling struct 把 int64 字段**放最前**（`{int64_t; uint32_t;}`）使两端 offset 一致；或用 numpy `align=True` |
| 误用 `PairReduceElem` 做配对 max | `PairReduceElem` 仅 `PairReduce::SUM` 且仅 half/float | argmax 的行内配对 fold **必须**用 `Compare(GT)+Compare(NE 自比)+Select` 双 Select，不能用 PairReduceElem |
| int8/int32/int64 的 Compare/Select/Max/Min 支持不确定 | 各 API 的 dtype 支持矩阵不同（如 PairReduceElem 仅 half/float） | 逐 dtype 查 `a5-api-enhanced/{Compare,Select,Min,Max}.md` 支持表；查不到下钻 SDK 头文件，**不凭记忆假设** |
| bf16 的 Compare 可用性 | bf16 组合承担 Compare 可用性裁决（历史 clarification #5） | bf16 路径先单测 Compare 语义，确认可用再泛化 |
| NaN 首见语义丢失 | golden 要求 NaN 接管 + tie 取最先出现；直接 Max 不保证 | 用 `Compare(NE, x, x)` 自比判 NaN；tie 首见用 `Reduce(MIN)` 取最小 idx 实现 |
| 尾块污染 | 尾向量未掩，pad 通道参与归约 | `FirstN(tailMaskBits)` 掩尾；rm 初值 `Duplicate(MIN(T))` 兜底 |
| `__ubuf__ const T*` 签名被拒 | RegBase `LoadAlign` 对 const 限定 static_assert | VF 形参去 const（函数体内不写输入），见 `special-value-semantics-max-min.md` |
| int64 大值（2^39~2^45）对抗 | 大值下标/值可能触发边界 bug | 对抗 case 覆盖 int64 大值、全 −inf、多 NaN、tie 首见、尾块边界 |
| `Pack<uint32_t,int64_t,HIGHEST>` 静默返回低字 | RegTraitNumTwo 的 int64 寄存器 Pack 的 HIGHEST 分支内部仍 `Copy(srcReg.reg[0])`（低 32 位），高 32 位丢失、值被截断 | int64 标量写回用 `StoreAlign<int64_t, DIST_NORM>`（SDK 内部按 lo/hi Interleave 正确落 int64）；`srcReg.reg[0]`/`reg[1]` 下标被静态检查器 `simd_vf_ubuf_access` 禁止，`__simd_vf__`/`__simd_callee__` 内不要直接下标 |
| value/index lane 宽度错配 | 多 dtype 下 value（T）与 index（int64）的寄存器 lane 数不同，`Compare`/`Select` 无法对齐 | 用 `ArgmaxTraits<DX>` 派发**宽化统一计算域**：fp16/bf16/fp32/int8→fp32 值 + int32 索引（64 lane）；int32→int32 值+索引；int64→int64 值+索引（32 lane）；值域与索引域用同一 mask 双 Select |
| GetValue/SetValue 与 StoreAlign 标量/向量不连贯 | `__aicore__` 层 GetValue 读 fold 的 StoreAlign 结果读到 stale 值（缺 LocalMemBar），且 bf16 无标量比较指令 | 累加器 merge 全部 RegBase 完成：标量经 `DIST_BRC_*` 广播读、`DIST_FIRST_ELEMENT_*` 单元素写；int64 标量 buffer 需 pad 到整寄存器（`CeilDivision(sizeof,256)*256`）避免满寄存器 LoadAlign 越界 |

## 可复用骨架要点（不展开源码）

- **值/下标双 Select 对称**：每个 `Compare` 产生 mask 后，值 `Select(vDst, vSrc0, vSrc1, m)` 与
  下标 `Select(iDst, iSrc0, iSrc1, m)` 用**同一个 mask**，保证二者严格同步（这是 argmax 正确性核心）。
- **NaN 接管顺序**：先 `Compare(GT)` 判有序域，再 `Compare(NE, x, x)` 判 NaN 倒序覆盖，末级兜底
  保 self 侧（与 `special-value-semantics-max-min.md` 的复合语义一致）。
- **finalize 取首见**：max 与 idx 分两条 Reduce 链——max 用 `Reduce(MAX)`，idx 用"最大处索引"经
  `Reduce(MIN)` 取首见（多 max 相同时最小 idx = 最先出现）。
- **merge 与 fold 同构**：merge 的 per-row running 更新复用 fold 的 Compare+Select 双路，避免两套逻辑。
- **标量累加器全 RegBase merge**：跨 tile 的 rmw 累加器（标量 accMax/accIdx）在 `__simd_vf__` 内完成
  load（`DIST_BRC_*` 广播读）→ merge（`Compare(GT)` + `Select`）→ store（`DIST_FIRST_ELEMENT_*` 单元素写），
  不要在 `__aicore__` 层混用 `GetValue`/`SetValue`（与 StoreAlign 标量/向量不连贯）。

## 横切标签

`reduce`、`argmax`、`multi-dtype`（含 int8/int32/int64）、`mask-tail`、`nan-aware`、`int64-index`。

## 实证来源

- `max_argmax` `compute_max_argmax_chunk` / `compute_gen_max_argmax`（6 dtype 组合 + §5.1 对抗场景，
  tie 首见 / NaN / 多 NaN / 全 −inf / int64 大值 / 尾块边界）
- `max_argmax` `MaxArgmaxReduceVF`（198/198 max_diff=0.0；宽化统一 lane 宽度 + int64 StoreAlign<DIST_NORM>
  写回 + 全 RegBase 标量累加器 merge + tie 首见/NaN 对抗）
- `max_argmax` `ComputeGenMaxArgmax`（498/498 max_diff=0.0；`RegTraitNumTwo` int64 索引 + 值/下标双 Select +
  逐元素 rmw 累加器 + tiling int64 字段对齐）
