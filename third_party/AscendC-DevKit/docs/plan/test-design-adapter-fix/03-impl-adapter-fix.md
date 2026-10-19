# 测试设计适配器静默丢参 — L4 实施方案（2026-09-17，2026-09-18 实施收口）

> 层级：**L4 / 实施方案**。只回答「改哪个函数、什么顺序、怎么验证」。
> 问题事实见 `01-problems.md`（L1）；选型与取舍见 `02-analysis.md`（L3，方案 E）。
> 全部行号基于本仓当前代码（2026-09-17 核对过
> `convert_to_param_def.py` / `ascendc_st_design.py` / requirement schema 三处锚点），
> 实施前请复核。
>
> **已定决策（2026-09-17 用户确认）**：
> ① `aclnn_name` **由用户输入提供**（requirement.json 顶层必填，需求阶段照抄）；
> 适配器缺失即 `raise`，不做 `f"aclnn{op_name}"` 拼接回退。原「`full_op_name`
> 驼峰转换 + 物化注入」路径否决。
> ② `value_range` **声明优先**：用户声明了就**逐字照抄**（不并、不改写），
> 未声明才按 dtype 查通用表。原「声明值 ∪ 类型极端值」并集方案否决。
> ③ `value_range` **可选**：用户不输入 requirement.json 就没有该字段——
> schema example 不展示、不进 `required_keys`（2026-09-17 用户确认）。
> ④ **input-templates/ 不纳入**（2026-09-18 用户确认）：用户自建目录、命名不固定，
> 不由本仓补示例；用户输入契约落在 req-analysis skill 资源
> （`schema/requirement.json` + `references/op_spec_schema.md` + `SKILL.md`）。
> 原 改动 12/13 由 **op_spec_schema.md 修改**替代。
>
> **实施状态（2026-09-18）**：改动 1-11 + 12' + 14/15 全部落地；
> 新增 UT 19 个（13+6）全绿；schema 必填键 ripple 修复 6 个测试文件后
> **全量 UT 4732 passed / 0 failed**；§6.2/6.3 真实产物标定通过（见 §六）。
> ST / heavy_llm 未跑（§3.11 heavy_llm 需用户确认，见 §6.4 诚实记录）。

---

## 目录

- [一、改动总表](#一改动总表)
- [二、实施顺序（4 阶段）](#二实施顺序4-阶段)
- [三、改动详述（1-7）](#三改动详述1-7)
- [四、E 对质三件套（8-11）](#四e-对质三件套8-11)
- [五、测试用例](#五测试用例)
- [六、验证方式](#六验证方式)
- [七、验收判据](#七验收判据)
- [八、待确认项](#八待确认项)

---

## 一、改动总表

| # | 阶段 | 文件 | 位置 | 改动 | 标记 |
|---|---|---|---|---|---|
| 1 | A | `src/ascendc_devkit/adapters/testdesign/convert_to_param_def.py` | `:345` | `op_block` 兜底到顶层，**删 `op_spec` 死支** | ★E-A |
| 2 | A | 同上 | `:344-347` | `aclnn_name` **从用户输入读**（必填，缺失 `raise`）；**删除 `op_name` 拼接链**（死代码） | ★E-A |
| 3 | A | 同上 | `:71` | `_is_scalar_attr` 兼容 `dtype` 键名 | ★E-A |
| 4 | A | 同上 | `:437` 前 | 新增两条空值断言（**写盘前**） | ★E-A |
| 5 | V | 同上 | `:286` / `:320` | 读上游 `value_range`：**声明照抄，未声明按 dtype 通用表**（现状不读声明） | ★E-V2 |
| 6 | V | `.claude/skills/ascendc-op-req-analysis/schema/requirement.json` | 顶层 + `inputs[]` | 加**必填** `aclnn_name`（进 `required_keys`）+ **可选** `value_range` | ★E-V1 |
| 7 | V | `.claude/skills/ascendc-op-req-analysis/SKILL.md` | 「执行步骤」内 | 加**简短判据**（何时该写 `value_range`；语义引用 schema） | ★E-V1 |
| 8 | E | 新增 `src/ascendc_devkit/adapters/testdesign/verify_param_def.py` | — | 对质模块（三维护校验 + `verify_from_dir` 单点入口） | ★E-1 |
| 9 | E | `src/ascendc_devkit/orchestration/stages/ascendc_st_design.py` | `actions()`，适配器调用后 | 接入对质（spawn agent 前） | ★E-1 |
| 10 | E | 同上 | `prompt_intro`（`:66-86`） | 加「03 修改边界」段（权限收窄） | ★E-2 |
| 11 | E | 同上 | `transition()`，`_locate_csv` 前 | 复验对质 + 报错带病因 | ★E-3 |
| 12 | A | `.claude/skills/ascendc-op-req-analysis/references/op_spec_schema.md` | schema 块 + 示例 | `required` 加 `aclnn_name`（含产权/照抄说明）+ `inputs[].value_range` 属性（仅用户声明才有）| ★E-A（替代原 input-templates 两项，2026-09-18 用户确认） |
| 14 | 测试 | `tests/ut/adapters/test_convert_to_param_def.py` | 新建 | 13 个用例（P1 回归 + aclnn + value_range） | — |
| 15 | 测试 | `tests/ut/adapters/test_verify_param_def.py` | 新建 | 6 个用例（对质三维护 + 标定 + E-3 机制 + dtype 别名归一守护） | — |

**涉及 8 个文件**（5 改 + 3 新建）：改动 1-5/8-11 的 3 个源文件、req-analysis skill
3 个资源文件（schema / SKILL.md / op_spec_schema.md）、2 个新建测试。
（曾另设 `tests/ut/adapters/fixtures/testdesign/` 真实产物 fixture ×2；2026-09-20
用户决策「仓内不留算子具体数据」→ **结构内联进测试**（`_full_structure()`
helper：结构形态取自真实产物、标识符通用化，§1.12）后删除——守护等价，
全量 UT 用例数不变。）

---

## 二、实施顺序（4 阶段）

> 按 L3 §三的选型结论：**A → E 三件套 → value_range 声明优先 → 观察后评估删适配器**。
> **A 是 E 的前半段**，可独立提交、独立验证。

### 阶段 1：A（适配器修复）——半天

```
1. 写测试（红）
     ├─ 平铺输入 → 期望 10 参数，实际 2 个        ✗
     ├─ 三源皆空 → 期望 raise，实际不抛           ✗
     └─ 无 aclnn_name → 期望 raise，实际静默拼接  ✗
2. 改改动 1（取值路径 + 删 op_spec）
3. 改改动 2（aclnn_name 用户输入 + 删 op_name 死链）
4. 改改动 3（_is_scalar_attr）
5. 改改动 4（两条空值断言，写盘前）
6. 测试转绿
7. 真实产物标定 → 期望 Wrote 10 parameters + aclnn_name 照抄
8. 全量 UT 回归
```

**产出**：适配器不再丢参，残缺即 `raise`。**P1 止血。**

### 阶段 2：E（对质三件套）——半天

```
1. 写对质模块（改动 8）+ 测试
2. 接入 stage：改动 9（actions，spawn 前）+ 改动 11（transition，复验）
3. 改改动 10（prompt_intro 权限收窄）
4. 真实产物标定：对真实成功产物**放行**（无误报）
5. 全量 UT + 非 heavy ST 回归
```

**产出**：03 的两条产出路径（适配器写 / agent 改）均受同一校验守护，失败报错带病因。

### 阶段 3：value_range 声明优先——半天

```
1. 改改动 6/7（需求 schema + SKILL.md）
2. 改改动 5（适配器读声明：照抄 / 通用表）
3. 写 value_range 测试（声明照抄 / 未声明通用表 / 标量同款）
4. 验证：注入声明的 fixture 走查 03 逐字一致
```

**产出**：value_range 单一优先级（用户声明 > 类型通用表），用户声明不再被静默丢弃。

### 阶段 4：观察（不实施）

```
观察 1~2 个 run：
    - agent 是否仍尝试重建 03？
    - 对质是否误报？
若稳定 → 评估删适配器（走 D）
```

**产出**：数据支撑"是否走 D"的决策。

---

## 三、改动详述（1-7）

### 改动 1：`op_block` 取值路径兜底（★E-A）

**文件**：`src/ascendc_devkit/adapters/testdesign/convert_to_param_def.py:345`

**现状**：

```python
op_block = req.get("op_spec", req.get("op", req.get("operator", {})))
```

**改为**：

```python
# requirement.json 有两条真实形态（非新旧版本，二者并存）：
#   平铺  —— DevKit requirement stage 产出，顶层直接是 op_name/inputs/outputs/attrs
#   嵌套  —— 用户原始模板与 cann-bench proto.yaml，算子块在 op / operator 下
# 故逐级探测后回退到 req 本身。必须用 `or` 串联：dict.get(key, default)
# 在 key 存在但值为 None 时返回 None，嵌套写法取不到兜底。
op_block = req.get("op") or req.get("operator") or req
```

**为什么删 `op_spec`**：它不是任何现存输入的字段（requirement schema `required_keys`
为 `op_name / mutation_mode / inputs / outputs / golden_alignment`，本仓 schema 文件
实测核对），只是 `domain/requirement.py:57` 的 Python 属性名。保留会让读者误以为
存在该输入形态（§2.5）。

---

### 改动 2：`aclnn_name` 从用户输入读 + 删 `op_name` 死链（★E-A）

**位置**：`:344-347`（整个 `# ── aclnn_name ──` 块）

**现状**：

```python
op_block = req.get("op_spec", req.get("op", req.get("operator", {})))
op_name = op_block.get("name", ds.get("op_name", "unknown"))
aclnn_name = op_name if op_name.startswith("aclnn") else f"aclnn{op_name}"
```

**改为**（配合改动 1 的 `op_block` 行）：

```python
# ── aclnn_name：用户输入提供（必填），需求阶段照抄进产物；适配器只读 ──
op_block = req.get("op") or req.get("operator") or req          # 改动 1
aclnn_name = req.get("aclnn_name")                              # 改动 2
if not aclnn_name:
    raise ValueError(
        "requirement.json 缺必填字段 aclnn_name（ACLNN 接口名，由用户输入"
        "提供、需求阶段照抄进产物）。requirement.json 顶层键 = "
        f"{sorted(req.keys())}")
```

**三处一并处理**：

| 处理 | 说明 |
|---|---|
| **读 `req.get("aclnn_name")`** | 用户在 requirement.json 顶层提供；需求 schema `required_keys` 保证产物必有（改动 6） |
| **缺失即 `raise`，不做拼接回退** | ① ``f"aclnn{op_name}"`` 产出的是**静默错误值**，沿 03 → 合并 CSV `stc_op_name` 列污染交付物——正是本修复要消灭的失效模式（§1.2 可诊断）；②「缺失回退（兼容存量输入）」属迁移分支（§1.4 禁止）；③ `required_keys` 已在需求产出点拦截，此 `raise` 只防上游契约被绕过的破洞（§1.3），正常流程不可达 |
| **删除 `op_name` 变量** | 实测核对（L1 P8）：`op_name` 在 `convert()` 内**唯一消费者**就是上述拼接（`:346-347`），YAML 只写 `aclnn_name`（`:414`）。改从用户输入读后 `op_name` 及其 `ds.get("op_name")` 回退整体成为死代码（§2.5） |

#### 为什么是「用户输入必填」而非其他方案（2026-09-17 用户确认）

| 方案 | 评价 |
|---|---|
| **用户输入必填（选）** | ✅ 接口名是**用户/算子产权方知道的事实**（§1.13）；与 `value_range` 同源（都在用户 `requirement.json`）；不推理、不推断 |
| `full_op_name` + 驼峰转换 | ⚠️ **靠规则推断**——虽 8 样例验证无特例，但仍是推断，违 §1.13「不猜测」；曾列为待确认注入方式，现已否决 |
| 保持现状（拼接 + 缺失回退） | ❌ 明知错；且属 §1.4 禁止的兼容分支 |

#### 用户输入侧配套（改动 12'，替代原 12/13）

用户输入目录（如 `input-templates/`）是**用户自建**的，命名不固定，不由本仓补示例
（2026-09-18 用户确认）。用户输入的契约落在 req-analysis skill 的语义文档——
`references/op_spec_schema.md`（改动 12'）：

| # | 文件 | 改动 |
|---|---|---|
| 12' | `.claude/skills/ascendc-op-req-analysis/references/op_spec_schema.md` | JSON Schema 块 `required` 数组加 `"aclnn_name"` + property 描述（唯一来源=用户输入照抄，不拼接，历史缺陷注明）；`inputs` items 加 `value_range` property（仅用户声明才有，与 param_type 正交）；示例加 `"aclnn_name": "aclnnAdd"`（**不加** value_range——可选字段不进示例，防照抄污染） |

#### 需求 schema 配套（改动 6 的一部分）

`aclnn_name` **进 `required_keys`**（与 `value_range` 的可选性质不同）：

```json
"required_keys": ["op_name", "aclnn_name", "mutation_mode", "inputs", "outputs", "golden_alignment"]
```

> **注**：需求阶段 agent 从用户输入**照抄**该字段，不生成、不推断。

---

### 改动 3：`_is_scalar_attr` 兼容 `dtype`（★E-A，与主线解耦的附带修复）

**位置**：`:71`

```python
# 现状
type_field = entry.get("type")

# 改为
type_field = entry.get("type", entry.get("dtype"))  # 用户模板用 dtype
```

**说明**：`dict.get(key, default)` 在此**是安全的**——`entry` 里键存在但值为 `None`
时返回 `None`，后续 `isinstance` 判断均判假，行为与原始代码一致。
**与改动 1 的 `or` 要求不冲突**（两处语义不同：这里只需 `None` 兜底，不需"空值继续兜底"）。

---

### 改动 4：两条空值断言（★E-A，**写盘之前**）

**位置**：`:437` 之前（`out_path = base / output_path` **之前**）

```python
# ── 自检（§2.9 producer 自检 / §1.3 加载期校验 / §1.2 可诊断）──
# 放在写盘之前：残缺产物不落盘（§3.12 不拿有损数据冒充权威输入）；
# 且 actions() 每次重试都会重跑适配器——断言在写盘前，适配器失败就不会
# 覆盖 agent 上一轮手工修复的 03，重试轮次间的工作得以保留（L1 P4）。
declared_tensors = max(
    len(req.get("inputs", [])) + len(req.get("outputs", [])),
    len(ds.get("inputs", [])) + len(ds.get("outputs", [])),
    len(op_block.get("inputs", [])) + len(op_block.get("outputs", [])),
)
produced_tensors = sum(1 for p in parameters if p.get("type") == "aclTensor")

# 校验 1：一个参数都没提取到（三源皆空 / 结构完全不匹配）
if not parameters:
    raise ValueError(
        "参数定义为空：未能从 requirement.json / design_spec.json 提取到任何参数。"
        f"requirement.json 顶层键 = {sorted(req.keys())}")
# 校验 2：张量数与上游声明不符（本次事故：0 < 8）
if declared_tensors and produced_tensors < declared_tensors:
    raise ValueError(
        f"参数定义不完整：上游声明 {declared_tensors} 个张量，"
        f"实际转换出 {produced_tensors} 个。"
        f"requirement.json 顶层键 = {sorted(req.keys())}")

yaml_text = "\n".join(yaml_lines)

out_path = base / output_path
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(yaml_text, encoding="utf-8")
print(f"[convert_to_param_def] Wrote {len(parameters)} parameters → {out_path}")
return str(out_path)
```

**两条必须分开写**：

| 场景 | 校验 1 | 校验 2 |
|---|---|---|
| 三源皆空 | ✅ 触发 | —（`0 < 0` 为假） |
| 结构不匹配（本次 bug） | — | ✅ 触发（0 < 8） |
| 正常 | 通过 | 通过 |

**合成一条会漏**：`if declared_tensors or not parameters` 在三源皆空时
`declared_tensors = 0`，内层 `0 < 0` 为假，一条都拦不住。

**消费者无需改动**：`ascendc_st_design.py:164-176` 的 `except` 已就位
（注释：「不要静默假装 step 1-2 已由适配器完成」），加 `raise` 后它才真正生效
——第一轮就 fail-fast，省掉 2h44m 全部空转。

---

### 改动 5：适配器读 `value_range`——声明照抄，未声明按类型（★E-V2）

**文件**：`convert_to_param_def.py`

**现状（病灶，本仓代码实测核对）**：`_build_tensor_param` `:286` 与
`_build_scalar_param` `:320` **无条件**用 `_default_value_range(dt)` 填值域，
**不读上游声明**——用户声明被静默丢弃（L1 P11 归属缺失），且令 03 恒有值域、
skill 脚本的 `or` 兜底（含更全极端值的内置表）永不生效（P11-b 机制归属）。

**`_build_tensor_param`（`:282-288`）改为**：

```python
dtype_entries: list[dict] = []
for dt in dtypes:
    de: dict = {"dtype": dt}
    if io_type == "input":
        # 声明优先（§1.13 忠实传递）：用户声明照抄，未声明才按 dtype 查通用表
        de["value_range"] = entry.get("value_range") or _default_value_range(dt)
    dtype_entries.append(de)
param["dtype_with_ranges"] = dtype_entries
```

**`_build_scalar_param` 非枚举分支（`:320`）同款**：

```python
de["value_range"] = entry.get("value_range") or _default_value_range(param_dtype)
```

**语义（2026-09-17 用户确认）**：

| 上游 `value_range` | 03 的值域 |
|---|---|
| **有声明** | **逐字照抄**——不并、不加、不改写（§1.13 忠实传递） |
| **无声明 / 空列表 `[]`** | 按 dtype 查 `_default_value_range` 通用表（现状兜底行为，不变） |

**为什么不做并集**（原草案 `_merge_extremes` 方案，已否决）：

| # | 否决理由 | 条款 |
|---|---|---|
| 1 | 并集 = 用工程逻辑**改写用户声明的事实**——往声明值域里塞 `inf`/`-inf`/`nan`/`±0`，属「修正/覆盖」输入表达 | §1.13 忠实传递 |
| 2 | 与需求侧 v3 判据**自相矛盾**——需求阶段「照抄不推理」，适配器侧却替用户补值，同一事实两个标准 | §1.13 |
| 3 | 整型无 inf/nan、±0 同数，并入即等价重复项——为不成立的收益引入特判分支 | §1.14 |

**不引入 `_merge_extremes` / `_TYPE_EXTREMES`**。

**如实记录——P11-b 在本方案下不修**：适配器恒写值域（声明或通用表），
`generate_test_factors.py:411` 的 `or` 右侧（skill 内置表 `DEFAULT_VALUE_RANGES`，
含 inf/nan 等更全极端值）仍不触发。备选方案「未声明时**不写**该字段、由脚本 `or`
兜底」可解，但改变 03 形态（字段可缺省）——未取，将来需要极端值覆盖时再评估
（见 L3 §4.5）。

**下游脚本不改**：03 恒有值域，`generate_test_factors.py:411` 行为不变。

---

### 改动 6：需求 schema 加 `aclnn_name`（必填）+ `value_range`（可选）（★E-V1）

**文件**：`.claude/skills/ascendc-op-req-analysis/schema/requirement.json`
（本仓现状 `required_keys` 实测核对：`op_name / mutation_mode / inputs / outputs /
golden_alignment`）

**定位**：**字段语义的唯一承载处**——字段形态、取值格式、缺省含义都写在这里
（改动 7 的 SKILL.md 只引用，不重复）。

**改什么**：

```json
{
  "required_keys": ["op_name", "aclnn_name", "mutation_mode", "inputs", "outputs", "golden_alignment"],
  "description": "……（在现有 description 末尾补充）\n\n【aclnn_name】必填。算子的 ACLNN 接口名，从用户输入照抄（用户 requirement.json 提供），不生成、不推断。\n\n【inputs[].value_range】可选。取值形态 [[min,max], ...]。仅当用户输入资料中已明确声明该输入的取值范围时填写（照抄，不推理）。缺失表示输入未声明，下游将使用通用类型值域兜底——非漏写。禁止自行推理/推测取值范围：输入没写就是没有。",
  "example": {
    "op_name": "算子名",
    "aclnn_name": "aclnn算子接口名",
    "inputs": [{
      "name": "x",
      "dtype": "fp16",
      "shape": ["N"],
      "param_type": "REQUIRED"
    }]
  }
}
```

> **注（2026-09-17 用户确认）**：example **不展示** `value_range`——可选字段进示例
> 会诱导 agent 照抄示例补值（「示例有 = 该有」），恰是要消灭的推理补齐。
> 语义只在 `description` 说明。

**两个字段的性质对比**：

| 字段 | 必填？ | 进 `required_keys`？ | 来源 | 缺失时 |
|---|---|---|---|---|
| **`aclnn_name`** | ✅ **必填** | ✅ **进** | **用户输入照抄** | ❌ 不该缺失（适配器缺失即 `raise`，见改动 2） |
| **`value_range`** | ⚪ 可选 | ❌ 不进 | 用户输入照抄（有则填） | 下游通用表兜底 |

**要点**：

| 项 | 说明 |
|---|---|
| **`aclnn_name` 进 `required_keys`** | 它是**必填的算子标识**（skill SKILL.md「aclnn_name 必填」），缺失即不合格 |
| **`value_range` 不进** | 条件性产出，强求会制造假数据 |
| **语义写在 `description`** | 与现有 `domain` / `attr.type` 同款做法 |
| **example 用算子无关占位** | 与全部现有 schema 一致（不嵌具体算子参数） |

> **注**：需求阶段 agent 对这两个字段都只做**照抄**——不生成、不推断（§1.13）。

---

### 改动 7：需求 SKILL.md 加简短判据（★E-V1）

**文件**：`.claude/skills/ascendc-op-req-analysis/SKILL.md`

**定位**：**只加判据，不展开**——字段语义已在 schema `description` 说明（改动 6），
此处只回答「何时该写」这一 workflow 问题（§2.8：方法归 SKILL.md，语义归 schema）。

**新增内容**（追加在现有「边界与异常语义分析」步骤之后）：

```markdown
**取值范围与接口名**：
- `aclnn_name`（必填）：算子的 ACLNN 接口名，从用户输入 requirement.json 照抄
  （字段语义见 `schema/requirement.json` 的 description）。用户输入缺失时按
  unclear/resolve_ambiguity 流程向用户确认，不生成、不推断。
- `inputs[].value_range`（可选）：**仅当用户输入资料中已明确声明**该输入的取值范围时
  照抄填写；没写就不写（缺省 = 下游用通用类型值域兜底）。

**禁止自行推理/推测取值范围**——输入没写就是没有。
```

**判据为什么是「输入里有没有」**：

| 版本 | 判据 | 问题 |
|---|---|---|
| v1 | 「通用类型值域对它的角色适用吗？」 | ❌ **不可执行**——agent 看不到通用表（`convert_to_param_def.py` 的 Python 常量 / `st-design/references` 的表格，均不在需求阶段阅读路径） |
| v2 | 「能否从公式/算子语义说明取值范围？」 | ⚠️ **可执行但会编**——实测 agent 曾据此编出「`global_logits_max` 非负」，**用户输入资料中并无此约束** |
| **v3（选）** | **「输入资料里有没有明确声明？」** | ✅ **可执行 + 不引入新错误**——只做识别与照抄，不做推理 |

**v3 的依据（§1.13）**：

> 工程实现只负责**忠实读取 / 对齐 / 传递**输入表达的事实，
> **不得用工程逻辑去"修正""猜测""覆盖"**

**推理 = 猜测**，会引入无依据的约束（代价是丢失合法取值覆盖）。

**分工**：

```
用户输入（含事实）→ 有声明 → 照抄进 aclnn_name / value_range
代码（不知道算子）→ 兜底   → 输入没给时用通用类型值域
```

**值域事实的唯一来源是用户输入**（§1.13 忠实传递）：算子仓文档不属用户提供的
需求材料，不作为本阶段输入（超出用户输入边界、依赖仓布局，§1.12）。

**后果（如实记录）**：用户未声明 `value_range` 时，03 仍使用通用表——
**P11-a（通用表不贴合作子语义）与 P11-b（skill 脚本内置表极端值不生效）在本方案下
均不修**。该缺陷另立条目（见 L3 §七）。

**为什么这么短**：

| 内容 | 归属 | 理由 |
|---|---|---|
| 字段形态、取值格式、缺省语义 | **schema `description`** | 契约（§2.8 知识/数据） |
| 「何时该写」的判据 | **SKILL.md** | workflow 决策点（§2.8） |

**不写完整小节**（含典型信号表等）——那会让 SKILL.md 膨胀，且与 schema
description 重复（§1.14 最小结构）。

---

## 四、E 对质三件套（8-11）

### 4.1 改动 8：新增 `src/ascendc_devkit/adapters/testdesign/verify_param_def.py`（★E-1）

```python
"""03_参数定义.yaml ↔ requirement.json 对质校验（§2.9 构造性保证）。

只查结构，不查语义——语义无唯一正确答案，硬查会造成误报。
E-1（spawn 前）与 E-3（transition 复验）共用同一入口 verify_from_dir（§1.15 单点），
覆盖 03 的两条产出路径：适配器写 / agent 改。
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from ascendc_devkit.adapters.testdesign.convert_to_param_def import (
    _normalise_dtype,  # 唯一 dtype 归一化点（§1.15）——两侧同源，别名不误报
)


def _canon(d) -> str:
    """dtype 归一化（空安全）：上游 JSON 与 03 的 dtype 表述统一后再比较。"""
    return _normalise_dtype(str(d).lower()) if d else ""


def verify(requirement: dict, design_spec: dict, yaml_data: dict) -> list[str]:
    """返回违规项列表（空 = 通过）。"""
    errors: list[str] = []

    # ① 参数清单：03 的张量集 == JSON 声明集
    #    ⚠ dtype 必须经同一归一化点：上游可写别名（fp16/bf16），03 里是
    #    _normalise_dtype 后的规范名（float16/bfloat16）——两侧不同源会误报
    #    「缺参数」（requirement schema 的 example 恰用 "fp16"，必触发）。
    auth: set[tuple[str, str]] = set()
    for src in (requirement, design_spec):
        for e in (src.get("inputs") or []) + (src.get("outputs") or []):
            if isinstance(e, dict) and e.get("name"):
                dt = e.get("dtype")
                for d in (dt if isinstance(dt, list) else [dt] if dt else []):
                    auth.add((e["name"], _canon(d)))
    produced: set[tuple[str, str]] = set()
    for p in (yaml_data.get("parameters") or []):
        if p.get("type") == "aclTensor":
            for de in (p.get("dtype_with_ranges") or []):
                produced.add((p["name"], _canon(de.get("dtype"))))
    for name, dt in sorted(auth - produced):
        errors.append(f"03 缺参数：{name} ({dt})")

    # ② dtype 域：03 的 dtype ⊆ domain.inputs[].dtypes（同经 _canon 归一）
    domain = requirement.get("domain") or {}
    for ent in (domain.get("inputs") or []):
        allowed = {_canon(d) for d in (ent.get("dtypes") or [])}
        if not allowed:
            continue
        for p in (yaml_data.get("parameters") or []):
            if p.get("name") != ent.get("name"):
                continue
            for de in (p.get("dtype_with_ranges") or []):
                got = _canon(de.get("dtype"))
                if got and got not in allowed:
                    errors.append(
                        f"03 dtype 越界：{p['name']}.{got} ∉ {sorted(allowed)}")

    # ③ rank：03 的 dimensions ∈ domain.rank.{min,max}
    rk = domain.get("rank") or {}
    lo, hi = rk.get("min"), rk.get("max")
    if isinstance(lo, int) and isinstance(hi, int):
        for p in (yaml_data.get("parameters") or []):
            dims = p.get("dimensions")
            if not isinstance(dims, list) or p.get("io_type") != "input":
                continue
            bad = [d for d in dims if not (lo <= d <= hi)]
            if bad:
                errors.append(
                    f"03 rank 越界：{p['name']}.dimensions 含 {bad} ∉ [{lo},{hi}]")
    return errors


def verify_from_dir(wd: Path) -> list[str]:
    """从 stage 工作目录加载三份产物并跑对质（E-1 / E-3 共用，§1.15）。"""
    req = json.loads((wd / "requirement.json").read_text(encoding="utf-8"))
    ds_path = wd / "design_spec.json"
    ds = (json.loads(ds_path.read_text(encoding="utf-8"))
          if ds_path.exists() else {})
    yaml_data = (yaml.safe_load(
        (wd / "design" / "03_参数定义.yaml").read_text(encoding="utf-8"))
        or {})
    return verify(req, ds, yaml_data)
```

**两条设计决策（防后人误改）**：

| 决策 | 理由 |
|---|---|
| **dtype 两侧统一经 `_canon`（复用适配器 `_normalise_dtype`）** | 上游 JSON 可写别名（`fp16`/`bf16`），03 里是归一化后的规范名（`float16`/`bfloat16`）——两侧不同源必误报「缺参数」（requirement schema 的 example 恰用 `"fp16"`，必触发）。归一化点只此一家（§1.15），不得在对质里另写映射 |
| **维度①只查「缺」方向（`auth − produced`），不查「多出」** | 适配器的 ds-attrs 兜底分支可**合法**产出 auth 集之外的张量条目（attrs 不在 auth 的 inputs/outputs 来源里；P7 场景下 attr 还可能被建成张量）——查 `produced − auth` 会误报。「多出」的约束由维度②③（域/rank）+ E-2/E-3 承担 |

### 4.2 改动 9：接入 stage `actions()`（★E-1）

**文件**：`src/ascendc_devkit/orchestration/stages/ascendc_st_design.py`

**位置**：适配器 `try/except` 块（`:164-176`）之后、`return super().actions(...)`
（`:178`）之前

```python
            # ── E-1：03 对质（适配器产物 vs 上游 JSON）──
            # agent 改过的路径由 E-3（transition 复验）覆盖；两处共用
            # verify_from_dir（§1.15 单点）。违规走 user_feedback（agent 可消费、
            # 就地修对应条目），不 raise——不静默、也不直接 fail stage。
            from ascendc_devkit.adapters.testdesign.verify_param_def import (
                verify_from_dir as _verify_pd,
            )
            _pd_path = wd_path / "design" / "03_参数定义.yaml"
            if _pd_path.exists():
                _violations = _verify_pd(wd_path)
                if _violations:
                    _log.error("[%s] 03 对质校验失败: %s",
                               self.name, "; ".join(_violations))
                    state = state.with_updates(user_feedback=(
                        "03_参数定义.yaml 与上游 JSON 不一致："
                        + "; ".join(_violations[:5])
                        + "。请按 ascendc-st-design skill 的 step 1-2 依据 "
                        "requirement.json + design_spec.json 修复对应条目"
                        "（不要整文件重建）。"))
```

> **注**：适配器 `raise` 时 03 未落盘，`_pd_path.exists()` 自然跳过——
> 两个失败路径（断言 raise / 对质违规）互不重复报。

### 4.3 改动 10：`prompt_intro` 加「03 修改边界」（★E-2）

**文件**：同上，`prompt_intro`（`:66-86`）末尾追加一段：

```python
        "\n"
        "【03_参数定义.yaml 的修改边界】03 由输入适配器从 requirement.json + "
        "design_spec.json 确定性生成，执行中不要重建或改写它（参数结构与 "
        "value_range 等字段一律不改——值域问题应修上游声明，而非就地改 03）。仅当"
        "框架反馈明确指出 03 与上游 JSON 不一致（适配器失败 / 对质违规）时，才按 "
        "skill step 1-2 依据两个 JSON 修复对应条目。\n"
```

**语义边界（2026-09-17 用户确认：收紧为「一律不改」）**：

| 场景 | 允许的动作 |
|---|---|
| 正常执行 | **03 一律不改**（参数结构 + value_range 等全部字段） |
| 框架反馈不一致（E-1 违规 / 适配器 raise） | 按 step 1-2 依据两个 JSON 修复**对应条目**（按 JSON 修 = 恢复声明/通用表的值，非 agent 自由裁量） |
| 值域本身有错 | 正解 = 修**用户输入的声明**（上游产权），下轮适配器重新生成 |

**为什么收紧**（原草案「value_range 可就地修正」，已否决）：

| # | 理由 | 依据 |
|---|---|---|
| 1 | 与「声明优先」冲突——agent 就地改值域 = 在「用户声明 + 类型通用表」之外开第二个来源，而对质**不查值域**（无权威可比），改了无人校验 | L3 §4.3 / §6.2 |
| 2 | L3 §4.6 本就否决「让测试设计 agent 现场推值域」（非确定性、无人校验）——「就地修正」与「现场推」实际无法区分 | L3 §4.6 |
| 3 | DevKit 下 agent 本就无 step 2 授权：skill 自带跳过条款（SKILL.md:18-19「可跳过 step 2 直接从 step 3 开始」）+ stage prompt「从 step 3 开始」——E-2 只是把「不该改」显式化 | 本仓 SKILL.md / `prompt_intro` 实测核对 |

- 不写进 SKILL.md——skill 单跑（TUI）时 step 1-2 本就归 LLM（§2.1 即插即用），
  这是 DevKit 编排层的分工声明，落 stage prompt。
- 保留事故中的救援通道：适配器真坏时（改动 4 raise → except → user_feedback），
  agent 仍被明确授权按 JSON 修复 03——E-2 收窄的是「无反馈时的擅动」，
  不是「堵死救援」。
- 漂移风险仍在（agent 挂载的 SKILL.md §2.1 带着完整的 step 2 值域编写教学，
  事故的整文件重建即实证）——由 E-3 复验兜底，不靠 prompt 单点。

### 4.4 改动 11：`transition()` 复验对质（★E-3）

**文件**：同上，`transition()` 内 `_locate_csv`（`:198-202`）**之前**

```python
        wd_path = Path(wd)

        # ── E-3：03 复验（agent 执行中可能就地改过 03）──
        # 先查病因（03 与上游 JSON 不一致）再查症状（CSV 缺失），修 L1 P6。
        from ascendc_devkit.adapters.testdesign.verify_param_def import (
            verify_from_dir as _verify_pd,
        )
        _pd_path = wd_path / "design" / "03_参数定义.yaml"
        if _pd_path.exists():
            _violations = _verify_pd(wd_path)
            if _violations:
                return self._error(
                    state,
                    "03_参数定义.yaml 与上游 JSON 不一致（对质复验）: "
                    + "; ".join(_violations[:5])
                    + "。请依据 requirement.json + design_spec.json 修复 03"
                      "对应条目（不要整文件重建）。",
                    error_type="schema_violation")

        # Locate the merged 13-column CSV (from agent prompt)
        csv_path = self._locate_csv(wd_path)
        ...
```

**与 §2.9 的关系**：03 是**本 stage 产物**（agent 在本 stage 内改过它），
复验属 stage 自检边界内、非越界查上游；违规经 `_error` → `last_error` /
重试反馈给 agent，有明确消费渠道（修复 = 按 JSON 改对应条目 → 下轮 E-1 再验）。

**对 P6 的疗效**：本次事故的 4 次重试若在 transition 先跑对质，报错将是
「03 缺参数：vocab_parallel_logits (bfloat16) …」（带病因），而非
「no merged test-case CSV found」（只报症状）。

---

## 五、测试用例

### 5.1 `tests/ut/adapters/test_convert_to_param_def.py`（新建，改动 14）

| # | 用例 | 断言 | 守护 |
|---|---|---|---|
| 1 | `test_flat_requirement_all_tensors` | 平铺形态 → 张量数 == 声明数 | ★E-A 改动 1 |
| 2 | `test_nested_requirement_all_tensors` | 嵌套 `op` 形态 → 张量数 == 声明数 | ★E-A 改动 1 |
| 3 | `test_empty_sources_raises` | 三源皆空 → `ValueError` | ★E-A 改动 4 |
| 4 | `test_tensor_count_mismatch_raises` | 结构不匹配（0 < 8）→ `ValueError` | ★E-A 改动 4 |
| 5 | `test_no_yaml_on_failure` | 断言失败时 **03 不落盘** | ★E-A 改动 4 |
| 6 | `test_aclnn_name_from_input` | req 有 `aclnn_name` → 03 **照抄**（无拼接） | ★E-A 改动 2 |
| 7 | `test_aclnn_name_missing_raises` | req 无 `aclnn_name` → `ValueError` | ★E-A 改动 2 |
| 8 | `test_scalar_dtype_key` | 标量用 `dtype` 键 → 不误判为张量 | ★E-A 改动 3 |
| 9 | `test_upstream_value_range_verbatim` | 上游给了 → 03 **逐字等于**其值（无添加、无并集） | ★E-V2 改动 5 |
| 10 | `test_no_upstream_value_range_fallback` | 上游没给 → 03 = 通用表（现状行为不变） | ★E-V2 改动 5 |
| 11 | `test_scalar_declared_range_verbatim` | 标量声明照抄（`_build_scalar_param` 非枚举分支） | ★E-V2 改动 5 |
| 12 | `test_output_no_value_range` | 输出张量不携带 value_range（现状守护） | 现状 |
| 13 | `test_full_structure_regression` | **完整结构标定**：跑通、10 参数、`aclnn_name` 照抄 | 全部 |

> 用例 13 是**关键标定**——`_full_structure()` 内联携带 8 张量（3 入 5 出、
> bfloat16/int32/float32 混合）+ 2 标量 + domain 嵌套的完整产物结构（结构形态
> 取自 run `20260831-104218-2dce42` 的真实产物、标识符通用化——合成小 fixture
> 只有 1-2 个张量，覆盖不到多张量完整组合的规模面，历史丢参缺陷恰发生在该层面）。
> 期望 10 参数（8 张量 + 2 标量）且 03 的 `aclnn_name` 逐字照抄。其余用例用
> 算子无关的小结构（§1.12：测试 fixture 可用具体算子做样例，但被测代码路径
> 不得因算子名改变行为）。无 value_range 声明 → 03 值域 = 通用表；
> 「声明照抄」由用例 9 用注入声明的 fixture 验证。

### 5.2 `tests/ut/adapters/test_verify_param_def.py`（新建，改动 15）

| # | 用例 | 断言 |
|---|---|---|
| 1 | 缺参数 → 报错 | 维度 ① |
| 2 | dtype 越界 → 报错 | 维度 ② |
| 3 | rank 越界 → 报错 | 维度 ③ |
| 4 | **完整结构（8 张量 + 2 标量）→ 放行（无误报）** | 关键标定（`_full_structure()` 内联） |
| 5 | 工作目录 03 被改坏 → `verify_from_dir` 报违规且**带病因**（tmp_path 构造 wd） | E-3 机制（stage `transition` 无既有测试 harness，在 `verify_from_dir` 机制层守护——E-1/E-3 共用同一入口，§1.15 单点保证等价） |
| 6 | **dtype 别名：上游声明 `fp16` / 03 产出 `float16` → 不误报缺参数** | 归一化守护（`_canon`） |

### 5.3 红→绿顺序（§3.1）

```
1. 先写用例 1/3/4/5/7，对【未改动】代码跑 → 全红（复现 P1 + aclnn 静默拼接）
2. 实施改动 1 + 2 + 4 → 转绿
3. 补用例 2/6/8，验证改动 1（嵌套形态）/ 2 / 3
4. 补用例 9-11，实施改动 5（用例 12 为现状守护，无红）
5. 补用例 13 标定
6. 实施改动 8-11 + verify 用例 1-6
```

---

## 六、验证方式

### 6.1 单元

```bash
# ⚠️ 本机已 pip 安装的 ascendc_devkit 指向另一份代码（/home/c00933192/...），
# 必须以仓根为 cwd 并前置 PYTHONPATH=src，否则 ModuleNotFoundError / 测到旧实现
cd /home/z00943229/devkit_fix/AscendC-DevKit
PYTHONPATH=src python3 -m pytest tests/ut/adapters/test_convert_to_param_def.py -v
PYTHONPATH=src python3 -m pytest tests/ut/adapters/test_verify_param_def.py -v
PYTHONPATH=src python3 -m pytest tests/ut/ -q            # 全量回归
```

**实施记录（2026-09-18）**：

- 新增 19 用例（13 + 6）**全绿**。
- schema 必填 `aclnn_name` 引发 18 个既有用例失败（fixture 产物缺新必填键 +
  `test_schema_loader.py` 断言旧 5 键元组）——按 §3.4 修根因：
  `test_stages.py` 的 `_with_golden_alignment` helper 单点注入（§1.15）、
  `test_requirement_{proto,golden,design_target,tensorlist}.py` 各 fixture /
  helper 补键、`test_schema_loader.py:44` 断言改 6 键。
- 修复后全量 UT：**4732 passed / 0 failed / 19 skipped**（既有 skip，非新增）。

### 6.2 真实产物标定（关键）

```bash
cd /home/z00943229/devkit_fix/AscendC-DevKit
python3 - <<'PY'
import json, pathlib, sys
sys.path.insert(0, 'src')
from ascendc_devkit.adapters.testdesign.convert_to_param_def import convert
base = pathlib.Path('/tmp/verify_td'); base.mkdir(exist_ok=True)
# 前置：把 run 20260831-104218-2dce42 的
#   artifacts/test_design/{requirement.json, design_spec.json} 拷到 base，
# 并给 requirement.json 顶层补 "aclnn_name":
#   "aclnnAiInfraCrossEntropySumexpAndIndexLogit"（模拟改动 6 后的输入形态）
req = json.loads((base / 'requirement.json').read_text(encoding='utf-8'))
req['aclnn_name'] = 'aclnnAiInfraCrossEntropySumexpAndIndexLogit'
(base / 'requirement.json').write_text(json.dumps(req, ensure_ascii=False),
                                       encoding='utf-8')
convert('requirement.json', 'design_spec.json', 'design/03_参数定义.yaml',
        base_dir=base)
PY
```

**期望**：`Wrote 10 parameters`（8 张量 + 2 标量），且 03 的 `aclnn_name` =
`aclnnAiInfraCrossEntropySumexpAndIndexLogit`（照抄）；
对照**未改动**版本应只出 2 个参数 + 错误的拼接名。
（该真实产物**无 value_range 声明** → 03 值域与改动前一致，均为通用表；
「声明照抄」行为由 UT 用例 9 以注入声明的 fixture 验证。）

**实施记录（2026-09-18，已跑）**：`Wrote 10 parameters` ✓、
`aclnn_name: aclnnAiInfraCrossEntropySumexpAndIndexLogit` 逐字照抄 ✓、
8 张量 + 2 标量 ✓；bfloat16 输入值域 = 通用表 4 条（`[-1,1] [0,0] [1,10] [-10,-1]`，
无 inf/nan——与适配器子集表一致，P11-b 如实不修）、输出张量值域 0 条 ✓。
修改前基线（实施前实测）：`Wrote 2 parameters` + 拼接名
`aclnncross_entropy_sumexp_and_index_logit`（P1 复现）。
该标定同时由 UT 用例 13（`test_full_structure_regression`，`_full_structure()`
内联完整结构——2026-09-20 起替代原真实产物 fixture 文件，守护等价）常驻守护，
不依赖手工重跑。

### 6.3 失败路径标定

用三源皆空 / 结构不匹配 / 缺 `aclnn_name` 的输入验证断言各触发一次，
且 **`design/03_参数定义.yaml` 不存在**（写盘前已 raise）。

**实施记录（2026-09-18）**：三条失败路径由 UT 用例 3/4/5（校验 1/校验 2/
不落盘）+ 用例 7（缺 aclnn raise）确定性守护，全绿。

### 6.4 回归范围（§3.2）

| 范围 | 要求 | 实施记录（2026-09-18） |
|---|---|---|
| UT 全量 | 必过 | ✅ **4732 passed / 0 failed** |
| ST 非 heavy | 必过 | ✅ **终版 124 passed / 0 failed / 14 skipped / 29 deselected**（2026-09-20 环境补齐后全量复核，588s）。过程记录：首次跑 116 绿 + 8 failed，全部为 opencode 环境缺失（`ConfigError: opencode.json (top-level model)`——本机无仓根 `opencode.json` 且未装 `opencode` CLI；**stash 基线实证**回退全部改动后同错，与本方案无关，§3.7 不强绿）；2026-09-20 用户放置仓根 `opencode.json`（model: `huawei/a:deepseek-v4-flash`，已在 .gitignore）+ `npm i -g opencode-ai`（v1.18.31）后原 8 用例单跑 **8/8 通过**（235s 真实 spawn，step-115 的 no_proxy 504 顾虑未触发）。本改动相关 2 处修复：`test_test_design_e2e.py` M5 fixture 补 `aclnn_name` + 张量补 `shape`（无 shape 被既有 `_is_scalar_attr` 启发式判为标量 → 校验 2 正确拦截退化产物——防护生效的实证，修 fixture 使其表达真实契约 §3.12）；smoke 失败经诊断即上述 opencode 环境问题 |
| heavy_llm | 按 §3.11 执行前需用户确认；未跑须诚实记录 | ⬜ **本次未覆盖 heavy_llm：无**（本改动未新增 heavy 用例；既有 heavy 与本改动无交互） |
| 真实链路 | 本改动为确定性逻辑（非 §3.9 的 LLM 行为对象），UT + 真实产物标定即可守护；**建议**下次真实 run 观察 03 参数数、`stc_op_name` 列、agent 是否仍重建 03 | ⬜ 观察项留待下次真实 run（阶段 4） |

---

## 七、验收判据

### 7.1 阶段 1（A）

- [x] 真实产物（补 `aclnn_name`）→ **10 个参数**（8 张量 + 2 标量）（§6.2 实施记录）
- [x] 三源皆空 / 结构不匹配 / 缺 `aclnn_name` → **抛 `ValueError`**，非静默返回（UT 3/4/7）
- [x] 断言失败时 **03 不落盘**（UT 5）
- [x] `op_block` 取值链中**无 `op_spec`**；`convert()` 内**无 `op_name` 变量**（死链已删）
- [x] `aclnn_name` 与用户输入**逐字一致**（照抄，无拼接、无转换）（UT 6 + §6.2）
- [x] 全量 UT 回归无退化（4732 passed / 0 failed）

### 7.2 阶段 2（E 三件套）

- [x] E-1：对质接入 `actions()`（适配器产出后、spawn 前），违规走 `user_feedback`
- [x] E-2：`prompt_intro` 含「03 修改边界」段（**03 一律不改**，含 value_range）
- [x] E-3：`transition()` 在 `_locate_csv` 前复验，违规 `_error` **带病因**
- [x] 对质三维护均可触发（UT 用例 1-3）
- [x] **真实成功产物放行（无误报）**（UT 用例 4）

### 7.3 阶段 3（value_range 声明优先）

- [x] 需求 schema 含必填 `aclnn_name`（进 `required_keys`）+ 可选 `value_range`，
      description 说明缺省语义（example **不展示** value_range）
- [x] 需求 SKILL.md 含 v3 判据（照抄，不推理）
- [x] op_spec_schema.md（改动 12'）同步契约（替代 input-templates 方案）
- [x] 适配器：上游**声明 → 03 逐字照抄**（无并集、无添加）；未声明 → 通用表
      （与现状一致，无回归）
- [x] `convert()` 内**无 `_merge_extremes` / `_TYPE_EXTREMES`**（并集方案不引入）

> 如实记录：P11-a / P11-b 在本方案下均不修（L3 §4.5）——不作为验收项。

---

## 八、待确认项

| # | 项 | 阻塞什么 | 状态 |
|---|---|---|---|
| ~~1~~ | ~~`aclnn_name` 需 `full_op_name`，注入方式未定~~ | — | ✅ **已定（2026-09-17 用户确认）**：**用户输入提供**——requirement.json 顶层必填 `aclnn_name`，需求阶段照抄，适配器缺失即 `raise`。否决 `full_op_name` 驼峰转换（推断，§1.13）与框架物化注入两条路径。见 §三改动 2 |
| 2 | 未声明输入的类型极端值覆盖（P11-b） | 改动 5 | **如实不修**：适配器恒写值域（声明或通用表），skill 脚本内置表（含更全极端值）仍不生效。备选「未声明不写字段、由 `generate_test_factors.py:411` 的 `or` 兜底」未取（改变 03 形态、行为面更大）；将来需要极端值覆盖时再评估 |
| 3 | 对质是否**也查 `value_range`** | 改动 8 | 当前**不查**——无权威源可比（L3 §6.2）。若将来 golden 声明值域，可补维度 ④ |

---

## 附：改动文件清单（as-built，2026-09-18）

| 文件 | 改动 |
|---|---|
| `src/ascendc_devkit/adapters/testdesign/convert_to_param_def.py` | 改动 1/2/3/4/5 |
| `src/ascendc_devkit/adapters/testdesign/verify_param_def.py` | **新建**（改动 8） |
| `src/ascendc_devkit/orchestration/stages/ascendc_st_design.py` | 改动 9/10/11 |
| `.claude/skills/ascendc-op-req-analysis/schema/requirement.json` | 改动 6 |
| `.claude/skills/ascendc-op-req-analysis/SKILL.md` | 改动 7 |
| `.claude/skills/ascendc-op-req-analysis/references/op_spec_schema.md` | 改动 12'（替代原 input-templates 两项） |
| `tests/ut/adapters/test_convert_to_param_def.py` | **新建**（改动 14，13 用例） |
| `tests/ut/adapters/test_verify_param_def.py` | **新建**（改动 15，6 用例） |
| ~~`tests/ut/adapters/fixtures/testdesign/`~~ | 曾新建（真实产物 fixture ×2）；2026-09-20 用户决策后**删除**——结构内联为两测试文件的 `_full_structure()` helper（标识符通用化），守护等价、仓内不留算子具体数据 |
| *（schema 必填键 ripple 修复，非方案改动）* `tests/ut/orchestration/test_stages.py`、`test_requirement_{proto,golden,design_target,tensorlist}.py`、`tests/ut/adapters/test_schema_loader.py` | fixture 补 `aclnn_name` / 断言改 6 键（§6.1 实施记录） |
