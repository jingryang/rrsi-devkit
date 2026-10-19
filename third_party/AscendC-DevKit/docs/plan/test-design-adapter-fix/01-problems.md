# 测试设计适配器静默丢参 — L1 问题记录（2026-09-17）

> 层级：**L1 / 问题记录**。只陈述「哪里坏了、凭什么这么说」（证据/现象/根因/影响）。
> 不提方案、不排顺序、不写决策。
> 方案分析见同目录 `02-analysis.md`（L3），实施方案见 `03-impl-*.md`（L4，按需）。
>
> **编号说明**：P1 为本件核心缺陷；P10 保留给独立缺陷「可选参数形状错位」
> （另行跟踪，不在本文件）；本文件的 P2-P9、P11 为支撑事实编号。
> 全部问题事实来自 run `20260831-104218-2dce42` 的产物、日志与源码实测。

**事实摘要**：`ascendc-st-design`（测试设计）stage 在 run `20260831-104218-2dce42`
耗时 3.08h，其中 2h44m（87%）是 4 次失败重试。根因是输入适配器
`convert_to_param_def.py` 按**从不存在的嵌套字段**读取上游 `requirement.json`，
导致 8 个张量参数被静默丢弃，且**不抛错、不告警**，残缺产物一路流到用例生成阶段，
最终以「找不到合并 CSV」的形式暴露，4 次重试报错逐字节相同。**该适配器在本次 run 中
始终未被修改，缺陷仍在。**

---

## P1（核心）：适配器按不存在的嵌套字段取 requirement.json，8 个张量静默丢弃

### 现象

`design/03_参数定义.yaml` 只产出 2 个标量参数（`vocab_start_index` /
`vocab_end_index`），而上游声明为 3 输入 + 5 输出 + 2 属性 = **8 张量 + 2 标量**。
适配器不报错，照常打印 `Wrote 2 parameters` 并正常返回。

**时间账**（本次 run）：

| 次 | 开始 | 耗时 | 结果 |
|---|---|---|---|
| 06 | 20:42:20 | 13m42s | ❌ `contract broken` |
| 07 | 20:56:02 | **78m51s** | ❌ `contract broken` |
| 08 | 22:14:53 | 64m22s | ❌ `contract broken` |
| 09 | 23:19:15 | 7m01s | ❌ `contract broken` |
| **10** | 23:26:16 | **20m55s** | ✅ 通过（**手工重建 03**） |

- 4 次失败合计 **2h44m**，占整个阶段 **87%**；成功那次仅 **21 分钟**
- 4 次报错**逐字节相同**：`no merged test-case CSV found`（只报症状，不含病因）
- 第 5 个 agent **手工重建** `03_参数定义.yaml` 才绕过——**适配器始终未被修改**

### 根因

`src/ascendc_devkit/adapters/testdesign/convert_to_param_def.py:345`：

```python
op_block = req.get("op_spec", req.get("op", req.get("operator", {})))
```

`requirement.json` 的实际结构是**平铺**的（`op_name` / `inputs` / `outputs` / `attrs`
直接在顶层），三层包装一个都不存在 → `op_block` 为 `{}`。
下游 `:354` / `:368` / `:377` 全部挂在 `op_block` 上：

```python
req_inputs  = op_block.get("inputs", [])    # → []
req_outputs = op_block.get("outputs", [])   # → []
raw_attrs   = op_block.get("attrs", {})     # → {}
```

`for entry in req_inputs:` 空列表 → **循环体一次都不执行**。

### 证据

- **上游实际结构**：`artifacts/test_design/requirement.json` 顶层键 =
  `op_name / op_type / mutation_mode / description / inputs / outputs / attrs /
  math_formula / golden_alignment / domain / shape_constraints / data_format /
  boundary_handling / constraints / test_cases / unclear_items`（实测）。
- **`op_spec` 是不存在的字段**：requirement 的 schema
  （`.claude/skills/ascendc-op-req-analysis/schema/requirement.json`）`required_keys`
  为 `op_name / mutation_mode / inputs / outputs / golden_alignment`，**无 `op_spec`**
  （本仓 schema 文件实测核对）。
  `op_spec` 仅是 `domain/requirement.py:57` 的 **Python 属性名**
  （`Requirement.op_spec: OperatorSpec`），并非 JSON 字段——适配器探测的是从
  Python 属性名误推出来的死支（实测）。
- **实测复现**：用真实产物 `requirement.json` + `design_spec.json`
  喂当前未改动的适配器 →

  ```
  [convert_to_param_def] Wrote 2 parameters
  - name: vocab_start_index
  - name: vocab_end_index
  ```

  与生产事故现象一致。
- **反证（数据一直都在）**：把同一份 requirement 数据按嵌套形态重新包装
  （`{"op_spec": {name, inputs, outputs, attrs}}`）再喂 →

  ```
  Wrote 10 parameters    ← 8 张量 + 2 标量，完整
  ```

  证明缺陷在取值路径，不在上游数据（实测）。
- **2 个标量幸存的原因**（单变量实测）：删 `design_spec.attrs` → 参数数由 2 变 **0**；
  删 `design_spec.inputs` / `design_spec.outputs` → 参数数**不变**（仍为 2）。
  即适配器 docstring 所述「requirement.json + design_spec.json」与真实行为不符——
  **`design_spec.attrs` 是唯一实际生效的输入源**（`op_name` 仅用于命名）。

### 影响

- 03 残缺 → 04 测试因子无张量 → L0/L1 用例只剩属性、L2 缺失
- 下游 `ascendc_st_design.py:199-202` 报 `no merged test-case CSV found`
  （只报症状、不含病因），4 次重试烧 2h44m
- 最终由第 5 个 agent 手工重建 03 才绕过（**绕过而非修复**）

---

## P2：同一文件内两种读法自相矛盾

### 现象

同一函数里，读 `design_spec.json` 用**顶层**（正确），读 `requirement.json`
却套**三层嵌套**（错误）——而两个文件顶层结构相同。

### 证据

```python
ds_inputs  = {e.get("name", ""): e for e in ds.get("inputs", [])}    # :353 顶层，对
ds_outputs = {e.get("name", ""): e for e in ds.get("outputs", [])}   # :367 顶层，对
op_block   = req.get("op_spec", req.get("op", req.get("operator", {})))  # :345 三层，错
```

注释也与实现相反——`:352` 写 `# Inputs — from design_spec first (richer format
info), fall back to req`，实际是 **requirement 驱动循环、design_spec 仅作字段补充**
（`ds_entry = ds_inputs.get(name, {})` 在循环体**内部**，循环不执行则永不访问）。

---

## P3：2 个标量「幸存」的路径是唯一直接读 design_spec 的分支

### 证据

`convert_to_param_def.py:398-408` 有一段独立兜底，直接遍历 `ds.get("attrs")`，
不经过 `op_block`：

```python
ds_attrs = ds.get("attrs", [])
seen_names = {p["name"] for p in parameters}   # 此时 parameters 为空
for entry in ds_attrs:
    if name and name not in seen_names:        # → 全部通过
        parameters.append(_build_scalar_param(name, entry))
```

而 `design_spec.json` 的 `attrs` 恰好只有这 2 个标量 → 精确解释了「8 张量全丢、
2 标量幸存」这一半成功半失败的症状。单变量实测见 P1 证据。

---

## P4：适配器无任何空值校验，残缺产物静默通过

### 证据

`convert_to_param_def.py:437-441` 仅落盘 + 一行 print，无校验：

```python
out_path = base / output_path
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(yaml_text, encoding="utf-8")
print(f"[convert_to_param_def] Wrote {len(parameters)} parameters → {out_path}")
```

产出 2 个参数还是 10 个参数，行为完全相同。

**附带的迭代覆盖问题**：`actions()` 每次重试都会**无条件重跑适配器**（本仓
`ascendc_st_design.py:164-167` 实测核对）——事故中 4 次重试每次都拿到一份
**新生成的残缺 03**，agent 上一轮的排查与修复不被保留，这是「4 次从零排查」
的机制放大器。

### 关键矛盾：调用方的 except 已就位，但从未触发

`src/ascendc_devkit/orchestration/stages/ascendc_st_design.py:164-176` 已有
`try/except`，注释明写设计意图：

> 适配器失败留下可观测信号……**不要静默假装 step 1-2 已由适配器完成**。

**设计意图正确但未兜住**——适配器不抛异常，它「成功地」写出了残缺文件。
错误信号到达不了消费者。

---

## P5：`03_参数定义.yaml` 是链上唯一无机器校验契约的中间产物

### 证据

| 环节 | 有无机器校验 |
|---|---|
| `requirement.json` 产出 | ✅ schema（`required_keys: op_name/mutation_mode/inputs/outputs/golden_alignment`） |
| **`03_参数定义.yaml`（适配器产出）** | ❌ **无 schema**，只有 `references/parameter-definition.md` 的文字表格 |
| 合并 CSV | ⚠️ 只有 `schema/testcase_csv.json` 的 `required_keys`（顶层列名） |

**关键**：残缺的 03 语法完全合法、格式完全正确，只是内容残缺，**没有任何东西能拦住它**。

> 补充：`required_keys` 类校验**只能查顶层 key 是否存在，查不到数组内部**。
> 残缺 03 的顶层确实有 `aclnn_name` 与 `parameters`，纯 `required_keys` 校验会**放行**。

---

## P6：契约检查只查存在性，报错不含病因

### 证据

`ascendc_st_design.py:199-202`：

```python
csv_path = self._locate_csv(wd_path)
if csv_path is None:
    return self._error(state, f"no merged test-case CSV found under {wd}")
```

只判断文件在不在，不判断内容对不对。4 次失败的报错**逐字节相同**：

```
contract broken: missing_artifact — no merged test-case CSV found under
.../artifacts/test_design
```

病因（03 残缺）在 5 个文件之外，报错不携带任何指向。

---

## P7：标量键名不一致导致标量被误判为张量

### 证据

`_is_scalar_attr`（`:64-83`）在 `:71` 只读 `type` 键名：

```json
{"name": "vocab_start_index", "dtype": "int32"}    // 用户模板 → type_field=None → 判成张量
{"name": "vocab_start_index", "type": "int", ...}  // 框架 agent 产出 → 正常
```

两条输入路径标量用**不同的键名**。用户原始模板
（`input-templates/cross_entropy_sumexp_and_index_logit/requirement.json`）
用的是嵌套 `op` + `dtype` 键（实测：顶层键为 `op / constraints / test_cases /
unclear_items`，`op.name` = `cross_entropy_sumexp_and_index_logit`）。

**影响范围有限**：框架链路里 requirement-analyst 会把 `dtype` 重写为 `type`，
平铺路径不受影响；**只在直接喂用户原始模板时触发**。

---

## P8：`aclnn_name` 无来源，拼接出错误接口名

### 现象

`convert_to_param_def.py:344-347` 用算子名拼接口名，产出与真实接口名不符：

```python
op_block = req.get("op_spec", req.get("op", req.get("operator", {})))
op_name = op_block.get("name", ds.get("op_name", "unknown"))
aclnn_name = op_name if op_name.startswith("aclnn") else f"aclnn{op_name}"
```

| 来源 | 值 |
|---|---|
| 算子仓接口文档（真实） | `aclnnAiInfraCrossEntropySumexpAndIndexLogit` |
| 适配器产出 | `aclnncross_entropy_sumexp_and_index_logit` |
| 合并 CSV `stc_op_name` 列 | `aclnncross_entropy_sumexp_and_index_logit` |

### 根因：DevKit 下该字段的来源缺失

`aclnn_name` 是 **skill 的必填字段**（SKILL.md「**aclnn_name 必填**」），
skill 原始设计已规定其来源：

> 值为算子的 aclnn 接口名称（**从接口文档名称获取**，如 `aclnnGridSampler2DBackward.md`
> → `aclnnGridSampler2DBackward`）

| 环境 | 来源 | 结果 |
|---|---|---|
| **skill 单跑（TUI）** | CWD 里有 `./aclnn{Op}.md` | ✅ 从文件名取，**确定** |
| **DevKit 编排** | 该文档**未物化**（`_upstream_inputs` 只有 requirement/design_spec/tiling_strategy） | ❌ 退化为 `f"aclnn{op_name}"`，**错** |

**即：`aclnn_name` 本来有确定来源，DevKit 接管 step 1-2 后该来源消失。**

### 为什么不能用 `full_op_name` 转换

`state.full_op_name` = `ai_infra_cross_entropy_sumexp_and_index_logit`（带前缀目录名），
理论上可逐段首字母大写转成 `aclnnAiInfraCrossEntropySumexpAndIndexLogit`。
**但这是"靠规则推断"**——且经实测，该规则虽在 8 个样例上无特例，仍是**推断**：
不同仓的接口命名规则不保证一致（如 `manifold_constrained_...` 不带 `ai_infra_` 前缀，
结果也不带 `AiInfra`）。

**用户的决定**（2026-09-17 再次确认）：该字段由**用户输入提供**——
接口名是**用户/算子产权方知道的事实**，不该由框架猜（落点见 L4 改动 2/6/12/13）。

### 实测补充：`op_name` 是死变量候选

`op_name` 在 `convert()` 内的**唯一消费者**就是上述拼接（`:346-347`）；
YAML 产物只写 `aclnn_name`（`:414`），不写 `op_name`（本仓代码实测核对）。
即一旦 `aclnn_name` 改从用户输入读取，`op_name` 推导链（含 `ds.get("op_name")`
回退）整体成为死代码。

### 用户输入侧现状：也没有

实测用户提供的 `input-templates/<op>/requirement.json`：

```
op.name = cross_entropy_sumexp_and_index_logit
有 aclnn 相关吗: []
```

`requirement.md` 亦无 `aclnn` 字样。**故需在用户输入侧新增该字段（必填）。**

### 影响

`stc_op_name` 是合并 CSV 的列，**面向 cann-bench 侧**（按算子名调度）。
DevKit 内部**无消费者**（全仓 grep 确认：仅测试 fixture 与注释出现）。

**注意**：此缺陷**不被「修 `op_block` 取值路径」覆盖**——`op_name` 的推导链
（`op_block.get("name")` → `ds["op_name"]`）独立于取值路径存在，错误照旧。
故须单列改动（L4 改动 2）。

---

## P9：agent 静默切断后续跑无检查点，导致空转

### 证据

前 3 次失败日志为 `agent_resume ... (sidecar present — silent-cut recovery)`——
同一 session `f1a9f86f` 续跑，非 4 个不同 agent。

失败方的行为特征（会话 07）：**100 次 Bash、0 次写入**——陷在
「读文档 → 跑脚本 → 排查」循环里，从未走到「动手修」就被切断；续跑后拿不到
「上一段已排查出什么」的结构化结论，又从零查。

成功那次（会话 10）：Bash 最少、Write 最多（3 次），没有在探索上打转。

### 影响

4 次失败合计 2h44m，占该 stage 总耗时 87%；成功那次仅 20m55s。

---

## P11：`value_range` 无确定来源，且显式值域会短路类型极端值

> 编号说明：本条原拟编号 P10；P10 已保留给独立缺陷「可选参数形状错位」
> （另行跟踪），故本条编号 **P11**（2026-09-17）。

### 现象

`03_参数定义.yaml` 里每个输入张量的 `value_range`（取值范围），当前由适配器
**按 dtype 查通用表**填写：

```yaml
- name: global_logits_max
  dtype_with_ranges:
    - dtype: bfloat16
      value_range: [[-1, 1], [0, 0], [1, 10], [-10, -1]]     # ← 通用表，不认算子
```

### 两个子问题

#### P11-a：通用表只认 dtype、不认算子

`_default_value_range`（`:221-249`，本仓代码实测核对）按 dtype 硬编码：

| dtype | 通用表给的区间 |
|---|---|
| `float16` | `[-1,1], [0,0], [1,10], [-10,-1], [inf], [-inf], [nan]` |
| `bfloat16` | `[-1,1], [0,0], [1,10], [-10,-1]`（**无 inf/nan**） |
| `int32` | `[-1,1], [0,100], [-100,-1]` |

对 `global_logits_max`（逐行 max 值）而言，`[-1,1]` / `[-10,-1]` / `inf` / `nan`
**都是无效输入**；对 `target`（vocab 索引）而言，`[0,100]` 这种笼统区间**没有实际意义**。

**实证**：本次 run 中 agent 手工重建 03 时自行给出了算子特定值域——
`global_logits_max` 给 `[[0,0],[0,1],[1,10],[10,100],[100,1000]]`（全非负），
与通用表的 `[-1,1]`/`[-10,-1]`/`inf`/`nan` 完全不同。

> **该推断的依据可追溯**：需求文档 `requirement.md:11` 记 `m = global_logits_max`，
> 且 `math_formula` 为 `shifted = logits - max`（log-sum-exp 稳定化模式）→
> `max` 是逐行最大值。**注**：由此推出「非负」**不严密**（若 logits 全负则 max 为负），
> 属 agent 的额外假设。

#### P11-b：显式值域会**短路**掉类型极端值

```python
# .claude/skills/ascendc-st-design/scripts/generate_test_factors.py:411
value_range = dtype_item.get("value_range") or get_default_value_range(dtype)
#                              ↑ 03 里有值域就用它    ↑ 没有才查内置全版表
```

**`or` 是二选一**——一旦 03 里写了值域，**内置表的 `inf`/`nan` 部分即被短路**。

> **机制归属（处置见 L3 §四 / L4 改动 5）**：脚本侧 `or` 兜底本身是「声明优先」的
> 正确优先级；使内置表失效的病灶在适配器——`:286` / `:320` **无条件**用自建子集表
> 填值域（不读上游声明），令 03 恒有值域、脚本内置表永不生效（本仓代码实测核对）。

### 证据（实测）

```
04_测试因子.yaml   → 全文 0 处 inf/nan
07_因子值.csv      → 0 处
合并_测试用例.csv   → 0 处
```

而脚本内置表里 `float16` 有 25 条、`bfloat16` 有 26 条**都含 `inf`/`-inf`/`nan`**
（`generate_test_factors.py` 的 `DEFAULT_VALUE_RANGES`）——**从未生效**。

### 归属缺失

`value_range` 是**算子语义**（「这个参数实际长什么样」），但当前：

| 环节 | 现状 | 问题 |
|---|---|---|
| **需求分析阶段** | 不产 `value_range` | 它读公式、读 golden，**本可判断** |
| **适配器** | 按 dtype 查通用表 | 不认算子，必然推错 |
| **测试设计 agent** | 事故时手工重建 03 会补值域 | **非确定性**（两次重建 diff 27 行），且**无人校验** |

---

## 附：取证方式说明

为避免「间接指标替代直接证据」的误判，以下均经实测而非推断：

1. **适配器行为**：直接用真实产物复现（P1），并用嵌套重包装做反证，确认数据本身完整。
2. **字段存在性**：`op_spec` 经 schema `required_keys` 与源码双向核对，确认为不存在的字段。
3. **单变量实验**：删 `design_spec.attrs` → 参数数 0；删 `inputs`/`outputs` → 不变。
   确认 `design_spec.attrs` 是唯一实际生效的输入源。
4. **`or` 短路**：确认 04/07/合并 CSV 全文 0 处 `inf`/`nan`，与内置表含 inf/nan 矛盾。
5. **golden 无值域**：`input-templates/.../golden.py:53-71` 只断言 shape/dtype/关系，
   **不含任何数值域断言**（grep 确认）。
6. **`op_name` 消费者**：本仓 `convert_to_param_def.py` 全文核对——`op_name` 仅
   `:346-347` 拼接 `aclnn_name` 使用，YAML 只写 `aclnn_name`（`:414`）。
