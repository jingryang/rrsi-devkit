# 模板路由与 tilingKey 编码

> SIMT 算子普遍同时存在 SIMD / SIMT / 排序 / 确定性等多条实现路径，靠 tiling 阶段的路由决策选择最优模板。本节覆盖路由机制与 key 编码。

## 1. IsCapable 优先级竞选（SIMT 大号兜底）

同一算子注册多个 tiling 模板，框架按 priority **从小到大**遍历 `IsCapable()`，SIMT 模板普遍以**大号优先级**作为恒真兜底：

```cpp
// 注册（priority 越小越优先）
REGISTER_OPS_TILING_TEMPLATE(AvgPool, AvgPoolNCHWSmallKernelTiling, 0);   // SIMD 小核优先
REGISTER_OPS_TILING_TEMPLATE(AvgPool, AvgPoolNHWCBigKernelTiling, 4);
REGISTER_OPS_TILING_TEMPLATE(AvgPool, AvgPoolSimtTiling, 19);             // SIMT 最后兜底
// 入口只调注册表
ge::graphStatus TilingForOp(gert::TilingContext* ctx) {
    return TilingRegistry::GetInstance().DoTilingImpl(ctx);
}
```

- 出处：`pooling/avg_pool`、`index/unsorted_segment_max`（OutFullLoad=1→Simt=100）、`math/mul`

**IsCapable 的典型门控条件**：dtype 白名单、shape 形态（如 condition 是否 `(a,1,...,1)` 广播）、数据量阈值、UB 容量检查、deterministic 标志。

## 2. SIMT 兜底 vs 专项路径的经典分流（gather_v2 为例）

```cpp
if (emptyShape)        return EMPTY;
if (twoDim && small)   return SIMD_TWO_DIM;    // 尾轴字节数足够大 → SIMD 批量搬
if (lastGatherFitsUb)  return LAST_GATHER;      // UB 驻留 + vgather
if (allLoadFitsUb)     return GA_ALL_LOAD;
if (twoDim)            return SIMT_TWO_DIM;
return SIMT;                                    // 最终兜底
```

- 出处：`index/gather_v2/op_host/arch35/gather_v2_tiling.cpp`

## 3. 经验阈值表（SIMT ↔ SIMD 分流）

| 判据 | 阈值 | 出处 |
|------|------|------|
| gather 尾轴字节数 | 通用 2048B；按 dtype 收紧 B8=218/B16=360/B32=620 | gather_v2 |
| embedding_bag SIMT 准入 | embeddingDim×dtype ≤ 512B | embedding_bag |
| reverse_v2 SIMD 准入 | 尾轴 ≥128B | reverse_v2 |
| scatter_add 尾轴阈值 | <128B 走 SIMT；排序场景 <512B | scatter_add |
| histogram 全载/分块 | bins < UB 容量；输入密度 > bins/100；分块 ≤8 轮 | histogram |
| unsorted_segment Sort+SIMT | 入出比 ≥5 且 innerDim < 512 | unsorted_segment_common |
| pad_v3 SIMT 兜底 | 输出 ≤4KB 或维数 >5 | pad_v3 |
| msda SIMT 路径 | embedDims < 64 | multi_scale_deformable_attn |

完整表见深度策略库 `kimi_simt_strategy.md`（skill 根目录）附录 A。

## 4. tilingKey 三代编码并存

```cpp
// ① 老式大数段：基数 + dtype 提升档，int64 地址加位段
SIMT_TWO_DIM_BASE_KEY = 2000000000UL + improveDtypeSize;
if (gatherDimSize * innerSize > INT32_MAX || ySize > INT32_MAX) { key += 100; }

// ② 组合式：两个枚举叉乘（op × dtype）
tilingKey = opCode * 4 + dtypeIdx;   // add/sub/mul/div × 4 dtype = 16 个 schMode

// ③ 新式声明式：同一棵 ASCENDC_TPL 树多特性位，两分支可挂不同 tiling struct
context->SetTilingKey(GET_TPL_TILING_KEY(schMode, hasClamp, isWeight, isYOrigin, isGroupIndex));
```

- 出处：`gather_v2`（老式）、`foreach_binary_op`（组合式）、`swiglu_group_grad`（声明式）

## 5. 索引降位 Cast 缩短排序 key（降低 radix pass 数）

排序类聚合算子（segment/scatter/unique）按目标值域把索引从 int32/int64 降为 uint8/int16/int32，减少 radix sort 轮数，castMode 编入 tilingKey：

```cpp
if      (varInAxis < 255)       { castType = CAST_UINT8; }    // 一轮 radix 排完
else if (varInAxis < 32767)     { castType = CAST_INT16; }
else if (varInAxis < INT32_MAX) { castType = CAST_INT32; }
// tilingKey = GET_TPL_TILING_KEY(TEMPLATE_MODE_SIMT_SORT, indiceCastMode, addrMode)
```

- 出处：`index/inplace_index_add/op_host/arch35/inplace_index_add_base_tiling.cpp`、`index/unsorted_segment_common`（idCastMode）

## 注意事项

- 模板路由的 `IsCapable` 与 kernel 侧 `if constexpr` / `TILING_KEY_IS` 必须一一对应，防止路由到不存在的模板。
- 多模板注册时 SIMT 兜底的 `IsCapable()` 应恒 `return true`，否则所有路由失败时无退路。
