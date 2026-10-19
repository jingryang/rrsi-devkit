# 可选参数缺省导致张量-形状错位 — L1 问题记录（2026-09-18）

> 层级：**L1 / 问题与需求记录**。只记录客观事实（哪里坏了、凭什么这么说），
> 不提方案、不排顺序、不写决策。方案与选型见 `02-analysis.md`（L3）；
> 实施见 `03-impl-slot-misalign.md`（L4）。
> 本目录问题编号独立于其他 plan 目录。
>
> **取证说明（§3.7 诚实报错）**：本缺陷的触发环境是**其他机器上实际发生过**的
> 算子运行（含可选输入参数的算子）；本仓最近一次 run（`20260831-104218-2dce42`）
> 的算子**无可选输入**，故**未经本仓 run 实证复现**。本文件全部事实来自：
> ① 本仓源码路径核对（下方所有行号均为本仓当前代码实测）；
> ② cann-bench 路径同源缺陷的**已修复先例**（仓内注释明记 run `20260803-164157`）；
> ③ 关键函数的实测行为（`_as_shape_list` 归组、`ast.literal_eval` 解析）。

---

## P1（核心）：可选参数缺省时，后续张量的形状被错绑到前一个（可选）参数上

### 现象

某算子存在可选输入参数（03 中 `required: false`，即 `param_type == "OPTIONAL"`）。
当测试用例**不提供**该可选参数时，CSV 消费端按**顺序补位**重建输入列表——
第 N 个张量被绑到第 N-1 个（可选）参数名上，末尾参数补空列表。

历史实例（cann-bench 路径，run `20260803-164157`，仓内注释佐证）：
conv1d 的 `query_start_loc`（可选、位于参数表**中间**）缺省时，
其后的 `cache_indices` 被错误绑到 `query_start_loc` 的位置上。

### 根因链

```
03:   required=false                        → 参数可选（信息 ✓）
04:   {param}.exist: [True, False]          → 显式建模存在性（信息 ✓）
用例: exist=False                            → 生成端 continue 跳过该参数（信息 ✓）
CSV:  stc_inputs 少一项                       → ★ 信息在此丢失
消费: _build_inputs 按 cursor 顺序补位         → ★ 张量-形状错位
```

**关键事实**：缺省信息在上游是**存在的**（04 的 `exist` 因子已显式建模），
丢失发生在 **CSV 落盘环节**（跳过而不留占位）——是工程链路问题，不是上游没建模。

### 证据（本仓行号实测，2026-09-18 核对）

1. **`exist` 因子显式建模可选参数存在性**：
   `.claude/skills/ascendc-st-design/scripts/generate_test_factors.py:434-436`——
   可选参数生成 `[True, False]` 两个存在性取值。
2. **生成端正确消费该因子（跳过）**：
   `.claude/skills/ascendc-st-design/scripts/generate_test_cases.py:1531-1533`——
   `exist=False` 时 `continue`，该参数**不进** CSV 输入列表、不留任何占位。
3. **合并端不处理 `exist`**：
   `.claude/skills/ascendc-st-design/scripts/merge_test_cases.py` 全文 grep
   无 `exist` 关键字——「某参数被跳过」这一事实未写入 CSV。
4. **消费端按 cursor 顺序补位（错位点）**：
   `src/ascendc_devkit/adapters/testdesign/csv_to_testcases.py:158-245`
   （`_build_inputs`）——`cursor` 逐位递增取 `flat_shapes[j]`，不辨可选缺省；
   用例少一个张量时整体前移一位，末尾补 `[]`。
5. **`_as_shape_list` 判据不含 `None`**（同文件 `:263`）：列值含占位时会被误判
   （实测：`[(11,353,), None, (11,)]` 被归组为「单个 shape」而非三个条目）。

### 影响

- 可选参数缺省场景（**恰是该参数最该覆盖的合法调用路径**）的参数-形状绑定错误；
- 下游 golden/kernel 收到的张量对不上签名，报与算子逻辑无关的错
  （cann-bench 先例表现为 golden 报 `a Tensor with 3 elements`、scope_guard 误 halt）。

---

## P2：位置语义靠「猜名字」——三个输入生产方命名不统一，消费端只能推断

### 事实

三个生产输入的地方，`name` 形态不一致：

| 生产方 | `name` 形态 | 位置信息 |
|---|---|---|
| `src/ascendc_devkit/domain/cann_bench_cases_loader.py:164` | `input_{i}` | 编码在名字里 |
| `csv_to_testcases.py:138`（`_flat_inputs`） | `input_{i}` | 同上 |
| `csv_to_testcases.py:158`（`_build_inputs`） | **真实参数名** | ❌ 无 |

消费端 `src/ascendc_devkit/adapters/npu/runner.py:806-809` 只能从名字猜位置：
`input_` 前缀且后缀数字 → 解析；否则 → **紧凑位置**（DevKit 路径走此分支）。

### 判定（引用事实，不作决策）

「位置」这一通用行为没有统一字段承载，靠每个生产方自觉用 `input_{i}` 命名——
漏写一处即错位（对应 §1.15 所述「缺失抽象」的结构特征）。

---

## P3：`proto_idx` 两条路径的值不同源——DevKit 路径产出的值错误

`runner.py:827` 对两条路径**统一写入** `proto_idx` 字段，但值的来源不同
（`:806-809` 的名字解析）：

| 路径 | `name` 形态 | `proto_idx` 值 |
|---|---|---|
| cann-bench | `input_2`（位置号在名字里） | ✅ 真实原始位置 |
| DevKit | `vocab_parallel_logits`（真实参数名） | ❌ 紧凑位置（缺省时 ≠ 原始位置） |

即 DevKit 路径**不是不产该字段，而是产出的值在可选缺省时错误**——
harness 的还原消费端（`_harness_template.py:257-276` `_restore_proto_order`，
按 `proto_idx` 还原 None 占位）拿到错值即失效。

---

## P4：两条路径的缺省表示机制不对称

| 路径 | 缺可选参数时 | 位置信息 |
|---|---|---|
| cann-bench（CSV 行内） | 该位置为 `null` | ✅ 保留 |
| DevKit（CSV 行内） | 该参数直接被跳过、列表变短 | ❌ 丢失 |

同属「CSV → TestCase」消费链，两条路径对同一语义（参数未提供）的表达不一致。

---

## P5：`_build_inputs` 的「尾部省略」假设不成立

`csv_to_testcases.py:177-179` docstring 写道：under-count 时「OPTIONAL input
omitted **at the tail** is legitimate」。事实反例：可选参数不必位于尾部
（cann-bench 先例的 `query_start_loc` 即位于参数表中间）——中间缺省同样合法。

---

## P6：`[]`（空张量）与「未提供」语义混淆

错位补尾时写入 `[]`。实测（`_harness_template.py:488` 消费 `shape`）：
`[]` 经 `_flatten_shape` 得 `total=1` 的空张量语义（真实存在的 0 元素张量），
与「该可选参数未提供」是两个业务语义（§1.10）。另：`value_range=None` 也已被
占用（「已提供、值域未指定」→ 回退默认值域，`_harness_template.py:439`）。

---

## P7：占位修复的落点跨两跳、且被平行列契约约束（修复面事实）

修复「CSV 丢位置」不能只改 `stc_inputs` 一列——占位信息要穿过**两跳**、
**三列平行**（2026-09-18 本仓实测）：

1. **TTK 生成端**（`.claude/skills/ascendc-st-design/scripts/generate_test_cases.py:1521-1523`）：
   `input_shapes / input_dtypes / input_ranges` 三个**平行容器**逐参数 append；
   `exist=False` 的 `continue`（`:1531-1533`）同时跳过三者——占位必须三容器同步。
2. **merge 端**（`.claude/skills/ascendc-st-design/scripts/merge_test_cases.py:105/110/344-346`）：
   以 `repr(v)` 重序列化写 TARGET 列（`repr(None)` = `None` 字面量，
   `ast.literal_eval` 可解析——天然可无损透传，但须实施时验证其按位搬运
   不引入数量假设）。
3. **消费端平行数组契约**（`csv_to_testcases.py:106-115`）：
   **加载期校验** `len(stc_input_dtypes) == len(stc_inputs)`——只给 `stc_inputs`
   占位而 dtype 列不占位，行会**直接被拒收**（契约报错，非错位）。
   `_as_scalar_list`（`:280`）同须 `None` 兼容。

## P8：DYNAMIC（Tensor[]）参数与可选缺省并存的定位歧义

`_build_inputs`（`csv_to_testcases.py:158-246`）中 DYNAMIC 参数按
**surplus 计数吸收**成员（`n_dyn = n_total − n_fixed`，flat 列表对 TensorList
成员**无显式边界**——docstring 自述）。引入 `None` 占位后：

- `n_total` 若含 `None` 条目会污染 surplus 计算；
- 缺省的可选参数**不消费张量**，`n_fixed` 的消费计数必须排除缺省位；
- 「单 DYNAMIC + 中间可选缺省」时，surplus 归属（DYNAMIC 前段还是后段）
  存在**真歧义**——与既有 multiple-DYNAMIC 显式报错（`:193-197`）同构。

即修复方案必须对「DYNAMIC × 可选缺省并存」显式表态（支持并定义规则 /
诚实报错），不能回避。

---

## 与「测试设计适配器静默丢参」（另一独立问题）的边界

| | 适配器静默丢参（`test-design-adapter-fix/`） | 本问题 |
|---|---|---|
| 环节 | `convert_to_param_def.py`（JSON→03） | **`csv_to_testcases.py`（CSV→TestCase）及 CSV 落盘** |
| 症状 | 参数清单残缺（张量整批丢失） | 参数清单完整，但**张量与形状绑定错位** |
| 触发 | 任何算子 | 仅含可选参数的算子且用例中缺省 |
| 性质 | 取值路径错误 | 位置信息在落盘时丢失 |

两者互不重叠，各自立项（§1.8 单问题产权）。

---

## 附：取证方式说明

- 本仓源码核对：上表全部行号于 2026-09-18 在本仓实测（`generate_test_factors.py`
  / `generate_test_cases.py` / `merge_test_cases.py` / `csv_to_testcases.py` /
  `runner.py` / `cann_bench_cases_loader.py` / `_harness_template.py`）。
- `stc_inputs` 的消费方唯一性：`src/` 全量 grep 仅
  `csv_to_testcases.py` 一处（排除 pyc），无 DevKit 之外的下游消费者。
- 关键函数实测：`_as_shape_list([(11,353,), None, (11,)])` 归组行为；
  `ast.literal_eval` 对 `None`（通过）与 `null`（ValueError）的解析差异。
- 未经本仓 run 复现的原因：本仓最近 run 的算子无可选输入（见头部取证说明）。
