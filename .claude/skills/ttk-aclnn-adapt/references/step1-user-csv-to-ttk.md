# Step 1：用户 CSV → TTK ACLNN CSV

用户 CSV 是"算子仓/数据集"风格，列名不固定；TTK 只认自己的列。转换的核心不是改列名，而是**先把 Step 0 的张量槽表补全，再按槽位落字段**。

> 本文用 `aclnnXxx`、`<op>`、`in0/out0`、`(4,8)` 等占位符示意结构；实际值一律取自 Step 0 契约和用户 CSV。

## 1. 先识别用户列语义

| 用户列常见名 | 语义 | 去向 |
|--------------|------|------|
| `operator` / `op` / `op_name` | 算子名 | 仅用于命名与定位文档；TTK 用 `api_name` |
| `case_id` / `id` / `case_name` | 用例标识 | `testcase_name`（需唯一、ASCII） |
| `input_shape` / `input_shapes` / `shapes` | 输入 shape 列表 | `tensor_view_shapes`（需补输出槽） |
| `dtype` / `dtypes` / `input_dtypes` | dtype 列表 | `tensor_dtypes`（需补输出槽） |
| `attrs` / `attributes` | 标量属性 | `attributes` |
| `value_range` / `input_data_ranges` / `data_range` | 输入随机范围 | `input_data_ranges` |
| `note` / `remark` / `expected` | 测试意图、期望输出 | 校验输出 shape/dtype；文本进 `remark` |
| `chips` / `soc` | 目标芯片 | 默认不映射（见下文） |

## 2. 张量槽补全（最容易错的一步）

用户通常只给**输入** shape，而 TTK ACLNN 的 `tensor_view_shapes` 必须覆盖**全部张量形参**（输入 + 输出），顺序与 C 形参一致。

假设 Step 0 的契约是 2 个输入 + 3 个输出：

```text
用户 input_shape: [[4,8],[8]]        # 对应 in0, in1
契约输出推导:
  out0 = <rule>  → (4,1)
  out1 = <rule>  → (4,1)
  out2 = <rule>  → (4,8)
最终 5 槽: ((4,8),(8,),(4,1),(4,1),(4,8))
output_tensor_indexes: (2,3,4)
```

若用户 `note` 里有 `expected`，把它作为**交叉校验**：

- shape/dtype 一致 → 采用推导值；
- 不一致 → 停止，向用户确认是文档约束还是用例期望有误，不能猜。

## 3. 字段映射规则

| TTK 列 | 生成规则 |
|--------|----------|
| `testcase_name` | `<op_snake>_<case_id 两位>`，如 `<op>_01`；保留原始 case_id 到 `remark` |
| `api_name` | Step 0 的 `aclnnXxx`（不是 `operator` 列） |
| `tensor_view_shapes` | 全部张量槽（输入 + 输出），C 形参顺序 |
| `tensor_dtypes` | 全部张量槽；混合 dtype 必须逐槽写全，不能用单值广播 |
| `tensor_formats` | 默认 `('ND',)` 可广播到所有槽；有非 ND 时逐槽写 |
| `attributes` | C 基本类型标量按形参名：`{'attr0': ..., 'attr1': ...}` |
| `input_data_ranges` | 按张量槽逐槽；**输出槽写 `(None,None)`**，输入槽用用户 `value_range` |
| `output_tensor_indexes` | Step 0 的输出槽索引，显式写出 |
| `remark` | 用户 `note` 的简短描述；不要把整段 JSON 塞进去 |
| `soc_series` | 默认留空。用户 CSV 里的芯片代号到 TTK SoC 名的映射不是通用规则，需要时用 `python3 -m ttk info` / `--plat` 的实际值核对后再填 |

**注意**：

- `attributes` 只放 C 基本类型/`aclTensor` 定值；`aclScalar*` 才用 `scalar_dtypes`。
- 输出槽虽然填了 shape/dtype，框架会用常量初始化，`input_data_ranges` 对其无效。
- 可选张量用 `None` 占位；TensorList 用嵌套元组。
- 单个用例的随机种子（用户 note 中的 `seed`）在 TTK 中没有逐用例字段；需要可复现时用 CLI `--seed`（按 `(seed, testcase_name)` 每用例确定性播种）。
- 用 `csv.DictReader` 读、`csv.DictWriter` 写，避免 JSON 里的逗号/引号破坏列。

## 4. 推荐表头

```csv
testcase_name,api_name,tensor_view_shapes,tensor_dtypes,tensor_formats,attributes,input_data_ranges,output_tensor_indexes,remark
```

（转换初期先写标准列；`pass`、`note` 两列在 Step 5 用 `finalize_cases.py` 追加，见第 7 节。）

## 5. 生成结果的结构示例

以第 2 节的 2 输入 + 3 输出为例：

```csv
testcase_name,api_name,tensor_view_shapes,tensor_dtypes,tensor_formats,attributes,input_data_ranges,output_tensor_indexes,remark
<op>_01,aclnnXxx,"((4,8),(8,),(4,1),(4,1),(4,8))","('float32','float32','float32','float32','float32')","('ND',)","{'attr0': 0.3, 'attr1': 1}","((-5,5),(-5,5),(None,None),(None,None),(None,None))","(2,3,4)","用户用例 1：<测试意图>"
<op>_02,aclnnXxx,"((8,16),(16,),(8,1),(8,1),(8,16))","('float16','float16','float32','float32','float16')","('ND',)","{'attr0': 0.3, 'attr1': 1}","((-5,5),(-5,5),(None,None),(None,None),(None,None))","(2,3,4)","用户用例 2：混合 dtype"
```

注意混合 dtype 的用例必须逐槽写全，输出强制 dtype（如统计量 float32、主输出跟随输入）按 Step 0 契约填。

## 6. 校验

```shell
python3 -m ttk aclnn -i "$WORKDIR/cases.csv" --validate
python3 -m ttk list -i "$WORKDIR/cases.csv"
```

- `--validate` 失败：优先看列名、括号/引号、dtype 拼写、输出索引越界；
- `ttk list` 的条数必须等于用户 CSV 的数据行数；
- 这一步不下设备，不需要 golden。

## 7. 最终交付的 cases.csv（追加 pass / note）

`$WORKDIR/cases.csv` 最终在标准列末尾追加两列：

| 列 | 来源 | 说明 |
|----|------|------|
| `pass` | `debug/result.csv` 的 `precision_status` | `PASS` / `FAIL` / `SKIP`；`FAILURE`/`GOLDEN_FAILURE`/`COMPARE_FAILURE` 等运行期失败归一为 `FAIL` |
| `note` | agent 写入的 `debug/notes.json` | 分析结论，例如"float32 golden 近零抵消点自身舍入，无法规避" |

回填命令：

```shell
python3 .claude/skills/ttk-aclnn-adapt/scripts/finalize_cases.py \
  --cases "$WORKDIR/cases.csv" \
  --result "$WORKDIR/debug/result.csv" \
  --notes "$WORKDIR/debug/notes.json"
```

这两列对 TTK 是未知列：运行时会打印 `Detected unidentified headers and will be ignored: ['pass', 'note']`，
但不影响解析与执行，所以交付后的 `cases.csv` 仍可直接重跑。

产物目录根下只保留 `golden.py` 和 `cases.csv`；验证日志、结果 CSV、dump、运行日志、
契约表、分析脚本一律放 `$WORKDIR/debug/`。
