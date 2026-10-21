# examples —— 通过全部门禁的参考样例

11 个算子，覆盖 L1/L2/L3/L4 与全部结构模式。**写不下去时照着抄结构。**
所有样例都用本仓的直调约定（`torch.ops.npu.<op>`），`--target direct-invoke` 下 0 FAIL。

## 两类样例，用途不同

| 来源 | 算子 | 用途 |
|---|---|---|
| **改编自参考语料**（人工撰写，接口约定已改为本仓直调形态） | `foreach_addcdiv_scalar` / `dynamic_quant` / `top_k` / `grouped_matmul` / `mha` / `gqa` | **结构与写作范例**，尤其是罕见结构与 L4 注意力场景 |
| **本 skill 生成并验证** | `abs` / `softsign` / `hardswish` / `index_select` / `baddbmm` | 端到端产物长什么样 |

改编项**只动调用约定**（§3 算子原型前缀、§6 调用示例）+ 删 `baseline_kernels` 注解，其余内容保持原样。

## 按「你缺哪种结构」查表

| 结构模式 | 去看哪个 |
|---|---|
| 最简单输入 elementwise（L1 骨架原样） | `level1/abs`、`level1/softsign`、`level1/hardswish` |
| **多输出** | `level3/top_k`（值+索引）、`level2/dynamic_quant`（量化值+scale） |
| **可选输入 `null` 三列同位占位** | `level3/grouped_matmul` |
| **`is_list` 张量列表输入** | `level1/foreach_addcdiv_scalar` |
| **`precision_thresholds` / 自定义阈值 §4 变体** | `level2/dynamic_quant`、`level1/foreach_addcdiv_scalar` |
| **`compare: false` / `index_gather` 输出字段** | `level3/top_k`（索引不做逐元素比对） |
| **索引类输入值域联动** `[0, x.shape[dim]-1]` | `level2/index_select` |
| **多输入 shape 耦合**（B/N/M/P 共享） | `level3/baddbmm`、`level3/conv` 类见 `l2-l3-design.md` |
| **符号维度 + `约束：` 行的写法** | `level3/grouped_matmul`（约束文档写得最完整） |
| **整型 dtype 全谱轮转** | `level3/top_k`、`level1/abs` |
| **attr 取值组合设计** | `level3/grouped_matmul`（`split_item`/`transpose_weight`） |
| **L4 注意力（场景驱动 20 例 / is_causal / NaN 保护 / `[0,0]` 退化）** | `level4/mha`，规范见 `l4-fa-design.md` |
| **GQA 分组耦合（`N_q%N_kv==0` / MQA·MHA 退化行）** | `level4/gqa` |

## 自查

```bash
python3 ../scripts/validate_preinput.py --run-golden */*/
```

预期：11 个算子 0 FAIL。残留 WARN 均为算子语义所致（如 `baddbmm` 按定义只接受 3D、
`grouped_matmul` 的支持范围行名是纯符号维度无法机械归因），不是缺陷。
`level4/mha`、`level4/gqa` 为 0 fail 0 warn（G10 走 G10-scenario、G8 放行 L1 句式均已内建）。
