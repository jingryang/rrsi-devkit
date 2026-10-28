# AscendC-DevKit `03_参数定义.yaml` rank 缺陷分析

- 日期：2026-10-28
- 触发场景：RRSI `ascendc-devkit` baseline 跑批（9 算子 × k=3）
- 涉及组件：`third_party/AscendC-DevKit`
  - `src/ascendc_devkit/adapters/testdesign/convert_to_param_def.py`（写入侧）
  - `src/ascendc_devkit/adapters/testdesign/verify_param_def.py`（校验侧）
  - `src/ascendc_devkit/orchestration/stages/ascendc_st_design.py`（门的触发点）
  - `src/ascendc_devkit/domain/support_domain.py`（已有 rank 解析职责的层）
- 证据来源：`runs/ascendc-devkit/jobs/base/batches/20261027-211319-t000-94139/devkit/20261027-131833-30c4a5/`

---

## 1. 摘要

`ascendc-st-design` 阶段里，参数定义文件 `03_参数定义.yaml` **不是模型写的，是框架的确定性脚本生成的**。同一份约束信息，生产者和校验者各读了不同的字段，结果两个独立缺陷叠加：

| # | 缺陷 | 位置 | 后果 |
|---|---|---|---|
| **A** | 用符号 shape 的**占位符个数**冒充张量 rank | `convert_to_param_def.py:263` | 生成非法 `dimensions`（两个算子都含越界的 `1`） |
| **B** | 用 `domain.rank`（语义上只是 `rank(x)`）校验**所有**输入张量 | `verify_param_def.py:71-82` | 合法值被判死；逼得修复者写语义错误的值才能过关 |

真值其实一直就在 `requirement.json` 的 `inputs[].shape_constraints` 字段里，**两侧都没有读它**。

后果：同一批任务里 `group_norm_silu` 存活、`deep_norm` 与 `adaptive_max_pool3d_grad` 被 halt——差别仅在于 agent 是否自发修正了框架的产物，**流程正确性取决于 LLM 的自觉性**，不可靠。

---

## 2. 现象

`ascendc-st-design` 阶段 halting，报错形态：

```
Workflow halted: stage 'ascendc-st-design' failed with fail_strategy=halt:
03_参数定义.yaml 与上游 JSON 不一致（对质复验）:
  03 rank 越界：x.dimensions 含 [1] ∉ [2,8];
  03 rank 越界：gx.dimensions 含 [1] ∉ [2,8];
  03 rank 越界：beta.dimensions 含 [1] ∉ [2,8];
  03 rank 越界：gamma.dimensions 含 [1] ∉ [2,8]
```

| 任务 | 结果 | 耗时 |
|---|---|---|
| `deep_norm` | halt | 8756s（2.4h） |
| `adaptive_max_pool3d_grad` | halt | 7168s（2.0h） |
| `group_norm_silu` | 通过 | 继续进入后续阶段 |

---

## 3. 阶段职责分界

```
┌─ 框架（确定性脚本，秒级）─────────────────────────┐
│  requirement.json + design_spec.json              │
│         ↓ convert_to_param_def.py                 │
│  03_参数定义.yaml   ← 参数清单：名字/类型/dtype/维度 │
└───────────────────────────────────────────────────┘
                    ↓ 连同 prompt 一起交给模型
┌─ 模型（agent，数小时）────────────────────────────┐
│  从 skill 的 step 3 开始：                         │
│  04_测试因子.yaml / 05_约束定义.yaml               │
│  06_求解配置.yaml / 07_因子值.csv                  │
│  testcases/*.csv / 合并_测试用例.csv               │
│  测试设计方案.md                                   │
└───────────────────────────────────────────────────┘
                    ↓
┌─ 框架（校验，毫秒级）─────────────────────────────┐
│  检查 03 与上游 JSON 是否一致 → 放行 / halt        │
└───────────────────────────────────────────────────┘
```

模型从头到尾不负责生成 03，而是在框架给的基础上继续后续步骤。

---

## 4. Bug A —— 写入侧：用占位符个数冒充 rank

### 4.1 代码

`convert_to_param_def.py:367-378`（合并上游两源）：

```python
ds_inputs = {e.get("name", ""): e for e in ds.get("inputs", [])}
for entry in req_inputs:
    ds_entry = ds_inputs.get(name, {})
    merged = {**entry, **{k: v for k, v in ds_entry.items() if v}}
```

`convert_to_param_def.py:260-263`（生成 dimensions）：

```python
shape = entry.get("shape", ["N"])          # 符号化 shape
if not isinstance(shape, list):
    shape = ["N"]
dimensions = list(range(1, len(shape) + 1)) if shape else [1]   # ← 病灶
```

上游 `shape` 是**符号列表**，可能含省略号 `'...'`，其**长度与真实 rank 无任何对应关系**。

### 4.2 实测：三个算子全部生成非法值

| 算子 | 张量 | `design_spec.inputs[].shape`（优先源） | 生成 `dimensions` | 真实合法 rank |
|---|---|---|---|---|
| deep_norm | x / gx | `['N_0','...','N_{m-1}','D_0','...','D_{k-1}']`（6 个） | `[1,2,3,4,5,6]` | `[2,8]` |
| deep_norm | beta / gamma | `['D_0','...','D_{k-1}']`（3 个） | `[1,2,3]` | `[1,7]` |
| group_norm_silu | x | `['N','C','D_1','...','D_k']`（5 个） | `[1,2,3,4,5]` | `[2,8]` |
| group_norm_silu | gamma / beta | `['C']`（1 个） | `[1]` | `[1]` |
| adaptive_max_pool3d_grad | x | `['N','C','D','H','W']`（5 个） | `[1,2,3,4,5]` | `[4,5]` |

> 注：deep_norm 的 `'...'` 是决定性反证——6 个占位符对应的真实 rank 是 `m + k` 的任意值，两者无映射关系。

### 4.3 真值在哪、有没有被读

| 文件 | 字段 | 内容 | 写入时读取 |
|---|---|---|---|
| `requirement.json` | `inputs[].shape` | 符号列表 | ✅ 读了，但**只用长度** |
| `requirement.json` | `inputs[].shape_constraints` | `"rank(x) = m + k ∈ [2, 8]…"` | ❌ **未读**（全文 grep 零命中） |
| `requirement.json` | `inputs[].shape_variants` | `[["N","C","D","H","W"],["C","D","H","W"]]` | ❌ 未读 |
| `requirement.json` | `domain.inputs[]` | 只有 `name` + `dtypes`，**无 per-tensor rank** | ❌ 未读 |

### 4.4 合并优先级（附带事实）

实测三个算子，`dimensions` 的 shape 均取自 **`design_spec.json`**（非空值覆盖 `requirement.json`），二者内容一致。真正的隐式 rank 来源是 `design_spec.inputs[].shape`。

### 4.5 `dimensions` 字段语义

`ascendc-st-design/SKILL.md:70`：

> `dimensions` 取值范围：通用最小为1、最大为8，需结合算子接口文档中的维度约束调整。例如接口文档写"不超过8维"时取 `[1, 2, 3, 4, 5, 6, 7, 8]`；写"3维"时取 `[3]`。

即：**`dimensions` = 该张量允许的 rank 集合**，不是"某个具体 rank"。

---

## 5. Bug B —— 校验侧：用 x 的域审判所有张量

### 5.1 代码

`verify_param_def.py:71-82`：

```python
rk = domain.get("rank") or {}
lo, hi = rk.get("min"), rk.get("max")
if isinstance(lo, int) and isinstance(hi, int):
    for p in (yaml_data.get("parameters") or []):
        dims = p.get("dimensions")
        if not isinstance(dims, list) or p.get("io_type") != "input":
            continue
        bad = [d for d in dims if not (lo <= d <= hi)]
        if bad:
            errors.append(f"03 rank 越界：{p['name']}.dimensions 含 {bad} ∉ [{lo},{hi}]")
```

`domain.rank` 的语义在 `requirement.json` 的 `domain.notes` 里写明：

> `deep_norm`：`"rank 指 rank(x) ∈ [2,8]；归一化维数 k = rank(gamma) = rank(beta) ∈ [1,7] 且 k < rank(x)…"`
>
> `group_norm_silu`：`"domain 声明 golden 侧接受的支持域：rank ∈ [2,8]…"`

即它只是 **x 的域**，但门把它套到了所有 `io_type == "input"` 的张量。

### 5.2 实测：deep_norm 的四个 input 全部被检查

```
requirement.domain.rank = {"min": 2, "max": 8}

03[x     ] io_type=input  dimensions=[1,2,3,4,5,6]  [检查] → 含 1 越界
03[gx    ] io_type=input  dimensions=[1,2,3,4,5,6]  [检查] → 含 1 越界
03[beta  ] io_type=input  dimensions=[1,2,3]        [检查] → 含 1 越界   ← 错判，beta 合法是 [1,7]
03[gamma ] io_type=input  dimensions=[1,2,3]        [检查] → 含 1 越界   ← 错判，gamma 合法是 [1,7]
03[mean  ] io_type=output dimensions=[1,2,3,4,5,6]  [跳过]（output 一律不查）
03[rstd  ] io_type=output dimensions=[1,2,3,4,5,6]  [跳过]
03[y     ] io_type=output dimensions=[1,2,3,4,5,6]  [跳过]
03[alpha ] io_type=input  dimensions=None           [跳过]（标量无此字段）
03[epsilon]io_type=input  dimensions=None           [跳过]
```

group_norm_silu 的 gamma/beta 同样被检查——其合法 rank 是 `[1]`，但按门的全局 `[2,8]` 判定，`[1]` 会被拒。

### 5.3 由此产生的逆向激励

修复者为了过门，只能把 gamma/beta 的 `dimensions` 写成 `[2]`——**为了通过一个错误的门而故意写错语义**。这会污染下游：用例设计基于错误的参数定义展开。

### 5.4 顺带发现：§1.15 单点违规

`verify_param_def.py:57` 直接 `requirement.get("domain")`，绕过仓内已有的规范提取点 `support_domain.requirement_domain()`（`support_domain.py:139`）。后者还具备从 `shape_constraints.symbolic_rules` 解析 rank 的兜底能力（`support_domain.py:206-219`，`_parse_rank` + `_RANK_RE`）。同一职责存在两条通路。

---

## 6. 错位全貌

```
                    ┌─ inputs[].shape ──────────┐
   写入侧读 ────────►│ （符号列表，长度≠rank）    │──► 03.parameters[].dimensions
                    └───────────────────────────┘        │
                                                          │  比较
                    ┌─ domain.rank ─────────────┐        │
   校验侧读 ────────►│ {"min":2,"max":8}         │◄───────┘
                    │ 语义仅 rank(x)             │
                    └───────────────────────────┘

                    ┌─ inputs[].shape_constraints ─┐
   真值所在 ────────►│ "rank(x) ∈ [2,8]"            │  ← 两侧都没读
                    │ "rank(beta) ∈ [1,7] 且 < rank(x)" │
                    └──────────────────────────────┘
```

生产者用字段 A（符号 shape 长度）造值，校验者用字段 B（全局 `domain.rank`）判值，真值在字段 C（`shape_constraints`）无人问津。

---

## 7. 一活一死的机制

### 7.1 两道门，同一个校验函数

| 门 | 时机 | 不通过的行为 |
|---|---|---|
| **E-1** | agent 启动**前**，适配器刚生成 03 后（`ascendc_st_design.py:actions()` 中 `_verify_pd(wd_path)`） | 不 raise，写入 `state.user_feedback`：「请依据 requirement.json + design_spec.json 修复对应条目（不要整文件重建）」 |
| **E-3** | agent 完成后、阶段结束**前**（`ascendc_st_design.py:transition()`） | `_error(..., error_type="schema_violation")` → `halt` |

两处共用 `verify_from_dir`（单点，见 `verify_param_def.py` 文件头注释）。

### 7.2 最终产物对比

| | group_norm_silu | deep_norm |
|---|---|---|
| 03 中 x 的 `dimensions` | `[2,3,4,5,6,7,8]` ✅ | `[1,2,3,4,5,6]` ❌ |
| 03 中 gamma/beta | `[2]` ⚠️ 语义错但过门 | `[1,2,3]` ❌ |
| 文件头 | `# Generated by convert_to_param_def.py` | 同 |
| E-3 结果 | 通过 | halt |

### 7.3 证据与推断边界

**确凿事实**：

1. 同一版本代码（worktree 与主树 md5 一致：`eec96e1209d1f849eba99b8118914ef6`）实测转换 group_norm 的 x 只可能产出 `[1,2,3,4,5]`，而盘上是 `[2,3,4,5,6,7,8]` → **该文件在生成之后被修改过**。
2. deep_norm 盘上内容与转换器输出逐字一致 → **未被修改**。
3. group_norm 的 `03_参数定义.yaml` mtime `04:24:41`，阶段结束 `04:25:41` → 修改发生在阶段尾声。
4. 文件头保留 `# Generated by convert_to_param_def.py`，仅 `dimensions` 行被改动 → 与「修复对应条目，不要整文件重建」的指令特征吻合。
5. E-1 的报错在两任务中相同（同样的 4 条违规），agent 收到的提示也相同。

**推断（未取得直接证据）**：agent 是按 E-1 的 `user_feedback` 修正的。日志未记录 agent 的具体文件编辑动作，`events.jsonl` 中亦无 `rank 越界` / `对质` 相关字段。

---

## 8. 影响面

1. **非确定性正确性**：同一份错误产物，能否存活取决于 LLM 该轮是否自发核对。这不是流程应有的行为。
2. **100% 复现**：只要 `parse shape 长度` 与真实 rank 域不一致，该算子在每个 trial、每一轮进化都会 halt，每轮白烧 2h+ agent 时间与 token。
3. **语义污染**：为过门而写的错误值（如 gamma/beta = `[2]`）会流入下游用例设计。
4. **只修 A 会更糟**：修好 A 后转换器会正确输出 gamma/beta 的 `[1..7]`，而当前 E-3 门会以 `∉ [2,8]` 拒绝——两个缺陷必须同时修。

---

## 9. 修复方案

### 9.1 新增单点：per-tensor rank 域提取

放在 `domain/support_domain.py`（已有 rank 解析职责的层），转换器与校验门共用（§1.15）：

```python
def tensor_rank_domain(requirement: dict, name: str) -> dict | None:
    """单张量合法 rank 域。优先级：结构化 → shape_variants → 措辞 → 精确 shape → None。"""
    # ① 结构化声明（推荐的上游形态，见 9.4）
    for ent in (requirement_support_domain(requirement).get("inputs") or []):
        if ent.get("name") == name and isinstance(ent.get("rank"), dict):
            return ent["rank"]

    ent = next((e for e in (requirement.get("inputs") or [])
                if e.get("name") == name), {})

    # ② shape_variants：结构化备选 shape → rank 集合
    #    如 [["N","C","D","H","W"], ["C","D","H","W"]] → {"min": 4, "max": 5}
    variants = ent.get("shape_variants")
    if isinstance(variants, list) and variants:
        ranks = sorted({len(v) for v in variants if isinstance(v, list) and v})
        if ranks:
            return {"min": ranks[0], "max": ranks[-1]}

    # ③ 逐张量 shape_constraints 措辞（过渡兜底，命中时留 warning）
    sc = ent.get("shape_constraints")
    if isinstance(sc, str):
        m = re.search(rf"rank\(\s*{re.escape(name)}\s*\)[^∈]*∈\s*\[(\d+)\s*,\s*(\d+)\]", sc)
        if m:
            return {"min": int(m.group(1)), "max": int(m.group(2))}
        # "1 维" 这类固定 rank 表述
        m = re.search(rf"{re.escape(name)}[^\n]{{0,12}}?(\d+)\s*维(?!\s*[，,至到~-])", sc)
        if m:
            r = int(m.group(1))
            return {"min": r, "max": r}

    # ④ 无省略号的具体 shape → 精确 rank
    shape = ent.get("shape")
    if isinstance(shape, list) and shape and "..." not in shape:
        return {"min": len(shape), "max": len(shape)}

    return None
```

### 9.2 Fix A：转换器消费它

`convert_to_param_def.py:260-263`：

```python
rank = tensor_rank_domain(requirement, name)     # 需将 requirement 传入 _build_tensor_param
if rank:
    dimensions = list(range(rank["min"], rank["max"] + 1))
else:
    dimensions = list(range(1, 9))                # skill 文档的通用 [1,8]
    log.warning("%s: rank 域未知，dimensions 取通用 [1,8]", name)   # §1.3 可观测
```

> 现状 `_build_tensor_param(name, entry, io_type)` 只接收合并后的 `entry`，需增加 `requirement` 参数（或让调用方预先解析好后传入 `per_tensor_rank`）。三种 upstream 形态（平铺 / `op` / `operator` 嵌套）都要覆盖。

修复后预期输出：

| 算子 | 张量 | 修复后 `dimensions` | 走哪条分支 |
|---|---|---|---|
| deep_norm | x / gx | `[2..8]` | ③ 措辞 |
| deep_norm | beta / gamma | `[1..7]` | ③ 措辞 |
| group_norm_silu | x | `[2..8]` | ③ 措辞 |
| group_norm_silu | gamma / beta | `[1]` | ③ 「1 维」 |
| adaptive_max_pool3d_grad | x | `[4, 5]` | ② `shape_variants`（结构化，零脆弱） |

### 9.3 Fix B：门改为 per-tensor

`verify_param_def.py:71-82`：

```python
for p in (yaml_data.get("parameters") or []):
    if p.get("io_type") != "input":
        continue
    dims = p.get("dimensions")
    if not isinstance(dims, list):
        continue
    rk = tensor_rank_domain(requirement, p["name"])
    if not rk:
        continue                      # 域未知 → 不查（不臆造，§2.12）
    bad = [d for d in dims if not (rk["min"] <= d <= rk["max"])]
    if bad:
        errors.append(f"03 rank 越界：{p['name']}.dimensions 含 {bad} ∉ [{rk['min']},{rk['max']}]")
```

同时把 `verify_param_def.py:57` 的 `requirement.get("domain")` 改为经 `requirement_support_domain()` 的统一入口。

### 9.4 Fix C（建议）：上游补结构化字段

`requirement` 阶段在 `domain.inputs[]` 每条内补 `rank: {"min": int, "max": int}`。有了它，转换器与门全部走分支 ①，regex 兜底永不触发，消除对 LLM 措辞的依赖。

### 9.5 验证（TDD，§3.1）

用本次跑批的真实 `requirement.json` 作 fixture：

| # | 用例 | 断言 |
|---|---|---|
| 1 | deep_norm x | 转换 → `[2..8]`，门通过 |
| 2 | deep_norm beta/gamma | 转换 → `[1..7]`，门通过（**回归点**：旧门会拒） |
| 3 | group_norm_silu x | 转换 → `[2..8]`，门通过 |
| 4 | group_norm_silu gamma/beta | 转换 → `[1]`，门通过 |
| 5 | group_norm_silu 手工植入 `[1]` 到 x | 门仍拒绝（确认门未被削弱） |
| 6 | grad x | 转换 → `[4,5]`（走 `shape_variants`） |
| 7 | rank 未知 + 具体 shape | 走分支 ④ 精确值 |
| 8 | rank 完全未知 | 走 `[1,8]` 并留 warning |

---

## 10. 附：本次跑批的其它 halt（与本缺陷无关）

同批次另有 2 个任务因网关流中断 halt，属环境抖动，与本文缺陷正交：

| 任务 | 阶段 | 原因 |
|---|---|---|
| `adaptive_max_pool3d` | `requirement` | `gateway_stream_error`，requirement-analyst 流错误 ×3 复发 |
| `layer_norm_v4` | `general-design` | `gateway_stream_error`，ascendc-design-generator 流错误 ×4 |

另有 4 个任务（`adaptive_max_pool2d`、`add_rms_norm_cast`、`avg_pool3_d`、`max_pool3d_with_argmax_v2`）在 `21:18` 构造 workflow 后无任何后续日志，疑似 opencode spawn 链路问题，未在本分析范围内定位。

此外，该批次整体在 12h 硬超时后全部记为 `harness_error + timed_out`，与卡 6 的 RAS 硬件告警（`80CB8001 80CB800A`，AIV `module error can not be fixed` + `service timeout`）同期发生。

---

## 11. 修复状态（2026-10-28 已实施）

按 9.1 + 9.2 + 9.3 实施（Fix C 未做，留作上游演进方向）：

| 文件 | 改动 |
|---|---|
| `domain/support_domain.py` | 新增 `merged_input_entries()`（合并口径单点）与 `tensor_rank_domain()`（per-tensor rank 域单点，五级优先级：结构化 rank → `shape_variants` → `shape_constraints` 措辞 → 具体 shape → 同形张量继承） |
| `adapters/testdesign/convert_to_param_def.py` | `_build_tensor_param(..., rank=)` 改用 `tensor_rank_domain()`；无证据时退回通用 `[1..8]` 并 `log.warning`（不再用占位符个数） |
| `adapters/testdesign/verify_param_def.py` | 校验③ 改为逐张量取域；张量无证据则跳过；域提取改走 `requirement_domain()`（§1.15） |

### 11.1 真实现场验收

对本次跑批的三个批次产物重跑「转换 + 对质」：

| 算子 | 修复后 `dimensions`（输入） | 对质结果 |
|---|---|---|
| deep_norm | x `[2..8]`、gx `[2..8]`、beta `[1..7]`、gamma `[1..7]` | PASS |
| group_norm_silu | x `[2..8]`、gamma `[1]`、beta `[1]` | PASS |
| adaptive_max_pool3d_grad | x/grad/argmax `[4,5]`（走 `shape_variants`） | PASS |

负向注入（把主输入 `dimensions` 改为 `[1, 9]`）三例均被门正确拦截，报告该张量自己的域。

### 11.2 新增测试

| 文件 | 覆盖 |
|---|---|
| `tests/ut/domain/test_support_domain.py` | `tensor_rank_domain` 五级优先级 / 通配符不臆造 / 同形继承 / 环检测；`merged_input_entries` 覆盖口径 |
| `tests/ut/adapters/test_convert_to_param_def.py` | 措辞区间 / 固定维数 / `shape_variants` / 同形继承 / 未知退回 `[1..8]` / 具体 shape 精确 / 结构化优先 |
| `tests/ut/adapters/test_verify_param_def.py` | 低秩参数不被主输入域误判 / 各自域越界仍抓 / 无证据跳过 / 输出张量不查 |

### 11.3 运行测试的注意事项

`ascendc_devkit` 的 editable install 可能指向另一份 checkout。跑本仓测试必须显式指定源码树：

```bash
cd third_party/AscendC-DevKit
PYTHONPATH=src python3 -m pytest tests/ut --quick -q
```

---

## 12. 复现命令

```bash
# 直接验证转换器的错误输出（不需跑 workflow）
cd third_party/AscendC-DevKit/src && python3 - <<'EOF'
import json, sys
sys.path.insert(0, '.')
from ascendc_devkit.adapters.testdesign.convert_to_param_def import _build_tensor_param

BASE = '<...>/devkit/20261027-131833-30c4a5'
for op in ('deep_norm', 'group_norm_silu', 'adaptive_max_pool3d_grad'):
    req = json.load(open(f'{BASE}/t000-{op}/artifacts/test_design/requirement.json'))
    x = [i for i in req['inputs'] if i['name'] == 'x'][0]
    print(op, '->', _build_tensor_param('x', x, 'input')['dimensions'])
EOF
```

实测输出：

```
deep_norm                  -> [1, 2, 3, 4, 5, 6]
group_norm_silu            -> [1, 2, 3, 4, 5]
adaptive_max_pool3d_grad   -> [1, 2, 3, 4, 5]
```

三者均含越界的 `1`（grad 还含 `2`、`3`，其合法域为 `[4,5]`）。
