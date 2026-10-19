# Step 0：从算子文档抽取 aclnn 契约

目标：在动 CSV 和 spec 之前，得到一张**有序、可核对**的形参表。后续所有字段顺序都以它为准。

> 本文所有 `aclnnXxx`、`in0`、`out0`、`<API>` 都是占位符，按实际算子替换。

## 1. 定位文档与签名材料

```shell
ls "$OP_DIR/docs"
grep -rl "${API}GetWorkspaceSize" "$OP_DIR/docs" "$OP_DIR/tests" "$OP_DIR/examples" 2>/dev/null
```

按以下优先级交叉核对：

| 来源 | 位置 | 用途 |
|------|------|------|
| 算子文档 | `$OP_DIR/docs/<API>.md` | 函数原型、参数表、约束（首要来源） |
| 调用示例 | `$OP_DIR/examples/test_aclnn_*.cpp` | 真实参数顺序、输出 shape 构造方式 |
| ST executor | `$OP_DIR/tests/st/aclnn*/executor_*.py` | `get_cpp_func_signature_type()` 的 C 签名、参考 golden |
| 源码头文件 | `$OP_DIR/op_api/**/aclnn_*.h` | `aclnnXxxGetWorkspaceSize` 的权威顺序 |
| 已安装头文件 | `$ASCEND_HOME_PATH/include/aclnnop/aclnn_*.h` | **TTK 运行期实际解析的头文件** |

> 文档与头文件冲突时：执行以头文件为准（TTK 由 `OpApiInfoKeeper` 解析头文件），但要把差异报告给用户。

源码有头文件、机器上未安装该算子时：

```shell
export TTK_OP_API_HEADER_PATH="$OP_DIR/op_api/include"   # 指向包含 aclnn_*.h 的扁平目录
# 若同时指定了源码 .so：
# export TTK_OP_API_SO_PATH=/path/to/libtorch_npu_opapi.so
```

## 2. 核对 TTK 实际解析到的签名

```shell
mkdir -p "$WORKDIR/debug"
python3 .claude/skills/ttk-aclnn-adapt/scripts/dump_aclnn_signature.py "$API" \
  > "$WORKDIR/debug/signature.txt"
```

脚本输出的 `tensor slot` 列就是 CSV `tensor_view_shapes` 的顺序；`others` 列对应 `attributes`。

## 3. 抽取规则

从 `aclnnXxxGetWorkspaceSize` 原型中：

1. 去掉 `workspaceSize`、`executor`（TTK 不把它们传给 golden）。
2. 按出现顺序给 **每个 `aclTensor*` / `aclTensorList*`** 编号（0-based）——这是张量槽。
3. 记录每个张量是输入还是输出；输出槽编号集合即 `output_tensor_indexes`。
4. `aclScalar*` / `aclScalarList*` → CSV `scalar_dtypes`（多数算子为 0 个）。
5. `double` / `int64_t` / `bool` / `char*` 等 C 基本类型 → CSV `attributes` 的同名键。
6. `aclnnIntArray*` 等 → `attributes` 的列表值。

从参数表和约束章节中抽出：

- 每个张量的 dtype 集合、format（通常 ND）、维度范围；
- shape 之间的约束（同 shape / 后缀相同 / broadcast 关系）；
- **输出 shape 的推导规则**（用户 CSV 往往没有输出 shape）；
- 输出 dtype 规则（例如统计量强制 float32、主输出与输入同 dtype）；
- SoC 支持差异、空 Tensor、非连续 Tensor、Inf/NaN 行为。

## 4. 产出模板

在 `$WORKDIR/debug/contract.md` 里落成：

```text
API: aclnnXxx
原型: aclnnStatus aclnnXxxGetWorkspaceSize(
        const aclTensor *in0, const aclTensor *in1,
        double attr0, int64_t attr1,
        const aclTensor *out0, const aclTensor *out1, const aclTensor *out2,
        uint64_t *workspaceSize, aclOpExecutor **executor)

张量槽（C 形参序）:
  0 in0   input   <dtype 集合>  <format>  <维度范围/约束>
  1 in1   input   <dtype 集合>  <format>  <与 in0 的 shape/dtype 关系>
  2 out0  output  <dtype>，shape = <推导规则>
  3 out1  output  <dtype>，shape = <推导规则>
  4 out2  output  <dtype>，shape = <推导规则>
输出索引: (2, 3, 4)
标量属性: attr0(double), attr1(int64_t)
约束: <format / 空 Tensor / 非连续 / 广播 / SoC 差异 / Inf-NaN 行为>
```

模板里的每个字段都必须来自文档、头文件或示例代码；没有依据的写"待确认"并问用户，不要猜。
