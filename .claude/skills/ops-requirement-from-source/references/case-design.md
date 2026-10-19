# 20 个测试用例的设计与生成

## 1. 固定约束

- `cases.yaml` 的 case 条目数必须恰好为 **20**。
- `cases.csv` 是同一批数据的派生文件，不独立维护。
- 只生成合法输入域内的正常功能用例；不生成非法参数、非法 shape/dtype/layout、越界输入、预期报错用例。
- 合法边界、极小/极大规模、特殊值仅在需求契约明确允许时纳入。
- 用例描述不得出现 tiling key、内部模板编号、源码函数名。

## 2. 用例来源

### 2.1 tests/st 种子池

| 来源 | 提取内容 |
|---|---|
| `tests/st/arch35/ttk_*.csv` | `input_shapes`、`input_dtypes`、`input_formats`、`attributes`、`input_data_ranges`、`soc_series`、`remark` |
| `tests/st/<api>/atk_*.json` | `inputs[].dtype/shape/range_values`、attr 取值、`aclnn_name` |
| `tests/st/**/executor_*.py` | 输出顺序、布局转换、特殊构造、golden |

处理规则：

1. 只保留与所选芯片种类（默认 `A5`，`soc_series` 如 `("Ascend950",)`）一致的条目；其他芯片条目直接排除，不做转换。
2. 合并语义重复的条目（同 shape 同 dtype 只差无关参数）。
3. 从 `remark` 读取覆盖意图，但最终 note 用外部条件重写为一句自然语言。
4. ST 用例可能覆盖多种布局/视图，保留其构造方式；需要非默认布局或非连续视图时，在 `note` 中一句话说明，其余情况一律按默认约定构造。

### 2.2 tiling 阈值提取

从 `op_host` 的 `*_tiling*.cpp/h`、`*_infershape*`、`config/` 提取：

- dtype 分支（fp16/fp32/bf16/int8 等）；
- 规约维/末维长度阈值（例如 `D <= 500`、`4096 < D <= 15360`）；
- full-load / partial-load 的 UB 容量阈值；
- 对齐粒度（32B/block、VL、16 元素等）；
- 分核公式与尾核条件；
- 属性触发的分支（epsilon、alpha、axis、normalized_shape 等）；
- 输出 dtype/shape 分支（多输出、fp32 统计量）。

把每个内部条件翻译成外部表达式：

```text
内部：tilingKey 的 bit 表示 D <= 500
外部：dtype=float32，归一化维长度 D ∈ {1, 64, 500}
```

阈值取点规则：每个阈值至少考虑 `T-1`、`T`、`T+1`（合法时），并补充对齐/非对齐、单核/多核、尾块/无尾块的代表值。

### 2.3 文档约束

- dtype 组合必须来自文档或 op def；
- 属性取值必须在文档允许范围内；
- shape 维度数、各维大小、元素总数必须合法；
- 布局/format 只在文档声明支持时使用。

## 3. 覆盖维度与 20 个名额分配

建议按以下顺序分配，具体比例按算子调整：

1. **dtype 基线**（3~6 个）：每种支持的输入 dtype 至少 1 个。
2. **模板/分支边界**（6~10 个）：每个关键阈值取边界与跨阈值点。
3. **shape 规模**（3~5 个）：最小、常规、大规模；多核与尾核。
4. **对齐/尾块**（2~4 个）：32B/VL 对齐与非对齐、末维尾块。
5. **维度/布局/视图**（2~4 个）：不同维度数、ND/NCHW/NHWC、非连续视图。
6. **属性/多输出**（2~4 个）：非默认属性、多输出 dtype 差异、输出 shape 变化。
7. **特殊值**（0~2 个）：仅在契约明确时使用显式值列表。

若无法在 20 个内覆盖全部，按影响和代表性取舍，并在 `design.md` 的覆盖映射中标注“未覆盖”。

## 4. 去重与唯一性

两个用例视为重复当且仅当以下键完全相同：

```text
(input_shape, dtype, attrs, value_range)
```

- 只改变 `note` 的用例必须合并。
- 同 shape 不同 dtype 合法；同 dtype 不同 shape 合法。
- 视图不同但逻辑 shape 相同时，保留一个连续版本即可；确需非连续版本时在 `note` 中一句话写明。
- 每个用例必须至少覆盖一个其他用例未覆盖的维度单元，并在 `note` 中用一句话说明。

## 5. 数据构造与 note 约定

`cases.csv` 列顺序固定：

```text
operator,case_id,input_shape,dtype,attrs,value_range,note
```

- `operator`：`ops_pascal`。
- `case_id`：1~20，唯一。
- `input_shape`：每个输入一个 shape 数组，顺序与 op def 输入顺序一致。
- `dtype`：每个输入一个 dtype，顺序同上；只描述输入。
- `attrs`：对象；无属性写 `{}`。
- `value_range`：每个输入一个区间 `[lo, hi]` 或显式值列表；特殊值用 `"nan"`、`"inf"`、`"-inf"`。
- `note`：一句话自然语言描述，概括该用例区别于其他用例的外部可观察特征（dtype、规模、对齐/尾块、值域、属性取值、特殊值、非连续视图等）。要求单行、简明，不写 JSON、不堆砌字段清单，不写芯片种类，不出现 tiling key、模板编号、源码函数名、kernel 名称等内部标识。

示例：`非对齐二维、非对称值域，验证 base=2 与 scale=1.5 组合`

机器语义不放进 `note`：

- 芯片种类由本次所选 `--chip` 统一决定，不逐用例标注；
- 输出 shape/dtype 由 `proto.yaml` 的 outputs 与 shape 规则推导；
- 数据构造与布局采用全局约定（见下节），仅非默认构造需要在 `note` 中点明。

全局构造约定（不逐用例记录）：

- 默认 `generator=uniform`：CPU `torch.Generator().manual_seed(seed)`，在有限区间 `[lo, hi]` 上均匀生成，再转目标 dtype；禁止对无穷区间采样。
- `mixed`：某输入的 `value_range` 为显式值列表时，按物理行优先循环；其余输入用 uniform。
- `noncontiguous_input`：需要非连续视图时，创建末维加倍的底层存储，把逻辑值写入 `base[..., ::2]`，以该视图作为输入；golden 按逻辑张量计算；并在 `note` 中一句话点明。
- `seed` 固定为 `case_id`，保证可复现。
- 默认布局 `ND`、连续视图；只有非默认构造需要在 `note` 中说明。

## 6. 期望值与精度

- 期望数值只能由最终 `golden.py` 计算；用例不记录期望值，输出 shape/dtype 由 `proto.yaml` 与 golden 推导。
- 浮点输出按生态算子精度标准：MERE < Threshold 且 MARE < 10 × Threshold；float16 2^-10、bfloat16 2^-7、float32 2^-13。
- 多输出分别判定；float32 统计量不与低精度主输出混用阈值。
- 用大规模用例覆盖长归约时，取较窄 value_range，避免统计量被 epsilon 主导或溢出。

## 7. 与 TTK 用例的映射约束

需求包 `cases.csv` 直接作为 TTK 适配的 `USER_CASES`，但以下字段语义不完全等价，必须在第四步交接时显式处理：

| 字段 | 映射规则 |
|---|---|
| `input_shape` / `dtype` | 按 aclnn 张量槽顺序补全输出槽；输出 shape/dtype 由 `proto.yaml` outputs 与 shape 规则推导，并与 Step 0 推导交叉校验 |
| `attrs` | 转为 TTK `attributes`；顺序/键名按 aclnn 形参名 |
| `value_range` | 转为 `input_data_ranges`；输出槽填 `(None, None)` |
| 布局 / 视图 | 默认 `ND`、连续；`note` 中声明非 ND 或非连续视图时，由 TTK 环节落成 `tensor_formats` / `tensor_view_strides` / `tensor_view_offsets` / `tensor_storage_shapes` |
| 显式值列表（mixed） | TTK 的第 3 项起是“必现值混入”，不是逐值循环；需要精确序列时用 spec 的 `customize_inputs` |
| `seed` | 固定为 `case_id`；TTK 只有全局 `--seed`，按 `(seed, testcase_name)` 派生 |
| 芯片种类 | 由本次 `--chip` 统一决定，不逐用例映射为 `soc_series`；用 `python3 -m ttk info` 的实际平台名核对 |

特殊值：

- Inf 可写成 `1e309` / `-1e309`（`ast.literal_eval` 会溢出为 ±inf）。
- NaN 不能用 `input_data_ranges` 表达（`nan` / `float('nan')` 均解析失败），必须走 `customize_inputs`。
- 任何 TTK 无法忠实表达的构造，记入 `debug/handoff.json` 的 `leftovers`，不得用近似值替代后仍声称覆盖。

TTK 用例命名固定为 `<ops_snake>_<case_id:02d>`，用于把 `pass`/`note` 回映到需求包 case。
