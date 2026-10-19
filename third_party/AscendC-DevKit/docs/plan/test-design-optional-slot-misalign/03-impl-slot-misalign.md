# 可选参数缺省错位修复 — L4 实施方案（2026-09-18，同日实施收口）

> 层级：**L4 / 实施方案**。只回答「改哪个函数、什么顺序、怎么验证」。
> 问题事实见 `01-problems.md`（L1）；选型与取舍见 `02-analysis.md`（L3，方案 A
> 已冻结）。全部行号基于本仓当前代码（2026-09-18 实测核对），实施前请复核。
>
> **前置**：`test-design-adapter-fix/`（step-126）已完成先行——本方案与其独立
> （L1 边界声明），但共享同一测试设计链路，全量回归须覆盖两者。
>
> **实施状态（2026-09-18，2026-09-20 ST 终版收口）**：9 处改动全部落地
> （改动 6 结论为零改动，见下）；TDD 红 10 → 绿；新增 UT 13 + 更新 1 个旧契约
> 测试；**全量 UT 4745 绿（0 failed）**（基线 4732 + 13）；ST 非 heavy 实施时
> 116 绿 + 8 failed 全为 opencode 环境缺失（同 step-126 记录，非本改动引入），
> **环境补齐后（2026-09-20）终版全量 ST 124 绿 0 failed**。

---

## 目录

- [一、改动总表](#一改动总表)
- [二、改动详述](#二改动详述)
- [三、四个实测陷阱](#三四个实测陷阱)
- [四、修复前后流程](#四修复前后流程)
- [五、测试用例](#五测试用例)
- [六、验证方式](#六验证方式)
- [七、验收判据](#七验收判据)

---

## 一、改动总表

| # | 文件 | 位置 | 改动 |
|---|---|---|---|
| 1 | `.claude/skills/ascendc-st-design/schema/testcase_csv.json` | 列说明 | 契约声明：`None` = 未提供；`()`/`[]` = 空张量；**三列（inputs/dtypes/formats）同位占位** |
| 2 | `.claude/skills/ascendc-st-design/scripts/generate_test_cases.py` | `:1521-1533` | `exist=False` 时 `input_shapes / input_dtypes / input_ranges` **三容器同步 append `None`** 再 continue |
| 3a | `src/ascendc_devkit/adapters/testdesign/csv_to_testcases.py` | `_as_shape_list` `:263` | 判据兼容 `None`（防整列误判为单个 shape） |
| 3b | 同上 | `_build_inputs` `:158-246` | 按位取用 + `None` 位 `continue`（保持紧凑）+ entry 带 `proto_idx`；`n_total` 取**非 `None`** 条目数；**DYNAMIC × 缺省并存 → 显式 raise**（L3 §4.5） |
| 3c | 同上 | `_flat_inputs` `:138-155` | entry 带 `proto_idx`；`None` 位 `continue`（否则 `list(None)` TypeError） |
| 3d | 同上 | `_as_scalar_list` `:280` + 平行契约校验 `:106-115` | dtypes/formats 归一化兼容 `None`；校验按**含位总长**对齐（文案区分 `None` 占位与张量数） |
| 4 | `src/ascendc_devkit/domain/cann_bench_cases_loader.py` | `:164` | entry 带 `proto_idx` |
| 5 | `src/ascendc_devkit/adapters/npu/runner.py` | `:806-809` | **删「猜名字」**，只读显式 `proto_idx` |
| 6 | `.claude/skills/ascendc-st-design/scripts/generate_empty_tensor_cases_derive.py` | entry 构造 | 遵循同一约定 |

**涉及 6 个文件、9 处改动**（`csv_to_testcases.py` 内 4 处）。
`_harness_template.py::_restore_proto_order`（`:257-276`）**一行不改**——
还原机制本就正确，只让数据源正确（L3 红线 1）。
`merge_test_cases.py` **预期零改动**（`repr(None)` 重序列化天然透传，L1 P7-2），
其按位搬运行为由 UT 场景 10 守护。

**实施补充（as-built，2026-09-18）**：

| 项 | 结论 |
|---|---|
| 改动 2 追加 | `format_ttk_tuple_str` 加 None 分支——否则 dtype 占位被引号包成字符串 `'None'`（非裸字面量），破坏三列同位语义 |
| 改动 2 边界确认 | `_process_attributes`（`:1269`）的 `exist=False` 是 attrs **字典**（按名消费、非位置载体），**无需占位**——位置载体只有张量三容器 |
| merge formats 列 | 占位位的 `stc_input_formats` 由 merge 广播为 `default_format`（非 None）——**良性**：消费端在 shape=None 位不产 entry，format 永不落 entry；长度校验只查 dtypes 列 |
| ranges 列 | `input_ranges` 同位 None——下游 `_resolve_vr(None)` 走默认值域（`_harness_template.py:439`），安全 |
| 改动 6 结论 | `generate_empty_tensor_cases_derive.py` **无缺省路径**（从既有 shape 派生空张量变体，从不省略输入）——**零功能改动**，占位约定对其不适用 |
| 旧契约测试更新 | `test_runner_execute.py::test_harness_serializes_proto_idx_from_loader_name` 编码了旧猜名字契约（`input_{i}` 名字解析）→ 更新为 `test_harness_serializes_explicit_proto_idx`（fixture 带显式字段，§2.5 删旧通路不留双轨） |

---

## 二、改动详述

### 改动 2：生成侧写占位（信息不再在落盘时丢失；三容器同步）

```python
# 现状（generate_test_cases.py:1521-1533）
input_shapes, input_dtypes, input_ranges = [], [], []   # 平行容器
...
if exist_col in ctx.row and not ctx.row[exist_col]:
    continue                                     # ← 跳过，三容器同时缺位

# 改为：三容器同步占位（只占 shapes 会破坏平行性 → 加载期契约拒收，L1 P7）
if exist_col in ctx.row and not ctx.row[exist_col]:
    input_shapes.append(None)
    input_dtypes.append(None)
    input_ranges.append(None)
    continue
```

> 占位穿透两跳（TTK 生成 → merge 重序列化 → 最终 CSV）：merge 以 `repr(v)`
> 重序列化，`repr(None)` = `None` 字面量、`ast.literal_eval` 可解析（实测）——
> 预期零改动，由场景 10 守护。

### 改动 3a：`_as_shape_list` 判据兼容 `None`

```python
# 现状：所有元素都是 tuple/list 才归组为多 shape；含 None 时 all(...) 为假
# → [(11,353,), None, (11,)] 被误判为「一个 shape」（实测）
if value and all(isinstance(e, (tuple, list)) or e is None for e in value):
    return [None if e is None else list(e) for e in value]
```

### 改动 3b：`_build_inputs` 按位取用（§1.14：改完更简单，零推断）

```python
# 现状：cursor 顺序补位 → 缺省即错位（L1 P1）
# 改为：按参数位取用
for i, op_param in enumerate(op_inputs):
    shape = flat_shapes[i] if i < len(flat_shapes) else None
    if shape is None:
        continue                                 # 未提供：不产 entry（保持紧凑）
    inputs.append({
        "name":      names[i],                   # 真实参数名，保留
        "shape":     list(shape),
        "proto_idx": i,                          # 显式位置
        "dtype":     flat_dtypes[i] if i < len(flat_dtypes) else None,
        "format":    flat_formats[i] if i < len(flat_formats) else None,
    })
```

> **计数语义（L3 §4.5）**：`n_total` 取**非 `None`** 条目数（占位不是张量）；
> 缺省位不消费张量。**DYNAMIC（Tensor[]）参数与可选缺省同用例并存 →
> 显式 `raise`**（flat 列表对 TensorList 成员无显式边界，surplus 归属有真歧义——
> 与既有 multiple-DYNAMIC 报错同构，§3.7 诚实拒绝，报错信息指明拆行二选一）；
> 非 DYNAMIC 算子的任意位置可选缺省全支持。

### 改动 3c / 3d / 4：另两条路径与平行列归一化

```python
# csv_to_testcases.py::_flat_inputs（3c：None 位跳过 + 显式位置）
for i in range(len(shapes)):
    if shapes[i] is None:
        continue                                 # 未提供：不产 entry
    entry = {"name": f"input_{i}", "shape": list(shapes[i]), "proto_idx": i}

# csv_to_testcases.py::_as_scalar_list（3d：dtypes/formats 兼容 None，
# 与 _as_shape_list 同款判据——否则平行列数量对不齐/归组错）
# 平行契约校验（:106-115）按含位总长对齐：三列同位 None，
# len 相等即过；错误文案区分「None 占位」与「张量数」

# cann_bench_cases_loader.py:164（改动 4）
  inputs.append({
      "name": f"input_{i}",
      "shape": list(shape) if isinstance(shape, list) else [shape],
      "dtype": _map_dtype(raw_dtype),
+     "proto_idx": i,
      **_per_input_value_range(value_range, i),
  })
```

### 改动 5：`runner.py` 删「猜名字」（§1.15/§2.5 单点收口）

```python
# 现状（:806-809）：靠名字形态推断
_nm = inp.get("name", "")
_proto_idx = (int(_nm.split("_", 1)[1])
              if _nm.startswith("input_") and _nm.split("_", 1)[1].isdigit()
              else len(inps))                    # ← DevKit 真名走这里 → 紧凑位置

# 改为：只读显式字段
_proto_idx = inp.get("proto_idx")
if not isinstance(_proto_idx, int):
    _proto_idx = len(inps)                       # 唯一退化：无位置信息 → 紧凑顺序
```

> `runner.py:827` 的写入行（`d = {..., "proto_idx": _proto_idx}`）**不变**——
> 两条路径的统一出口。

---

## 三、四个实测陷阱

| # | 陷阱 | 实测证据 | 对应 |
|---|---|---|---|
| 1 | `_as_shape_list` 把含 `None` 的列误判为「单个 shape」 | `[(11,353,), None, (11,)] → [[(11,353), None, (11,)]]` | 改动 3a |
| 2 | 占位必须写 `None` 不能写 `null` | 该列经 `ast.literal_eval`：`None` 通过、`null` ValueError | 改动 2 |
| 3 | `None` 绝不能进 `_tc['inputs']` 的 entry | `_harness_template.py:488` 遍历 `i['shape']` → TypeError | 改动 3b（continue） |
| 4 | `value_range=None` 语义已被占用 | `_harness_template.py:439`：`None` = 已提供、值域回退默认 | 三语义区分（L3 §4.3） |

---

## 四、修复前后流程

```
改前：exist=False → continue → CSV 少一项 → cursor 补位错位
      → runner 猜不到真实名 → proto_idx=紧凑位置 → harness 还原失效 → 张量绑错

改后：exist=False → CSV 写 None 占位（改动2）
      → _as_shape_list 兼容 None（3a）→ 按位取用、None 位 continue、entry 带 proto_idx（3b）
      → _tc['inputs'] 紧凑 + 带位置
      → runner 只读 proto_idx（改动5）
      → _restore_proto_order（不改）：_full[0]=tensor_a、_full[2]=tensor_c
      → golden/kernel 调用位置正确
```

三个生产方（cann_bench_cases_loader / _flat_inputs / _build_inputs）统一写
`proto_idx`；一个消费方（runner）只读；一个还原方（harness）零改动。

---

## 五、测试用例

**TDD（§3.1）**：先写红（对未改动代码，场景 1 必失败——错位发生）。

| # | 场景 | 断言 | 守护 |
|---|---|---|---|
| 1 | **中间可选参数缺省**（历史实例形态，非尾部） | 后续张量 `proto_idx` 正确、不误绑 | 核心（L1 P1） |
| 2 | 尾部可选参数缺省 | 正确识别（含 docstring 假设修正，L1 P5） | 改动 3b |
| 3 | 全部参数齐全 | 无回归 | 全部 |
| 4 | 空张量 `()` vs 未提供 `None` | 二者 entry 语义可区分 | 改动 3b |
| 5 | `ast.literal_eval` 解析含 `None` 列值 | 通过（且 `null` 报错的负例常驻） | 改动 2 |
| 6 | `_as_shape_list` 含 `None` 多输入 | 归组为多 shape 而非单个 | 改动 3a |
| 7 | cann-bench 路径回归（`input_{i}` + 显式 `proto_idx`） | 行为不变 | 改动 4 |
| 8 | DevKit `_flat_inputs` 路径回归 | 行为不变 | 改动 3c |
| 9 | runner：entry 无 `proto_idx` | 退化紧凑顺序（唯一兜底行为） | 改动 5 |
| 10 | **三列同位占位**：TTK 生成 → merge 重序列化 → CSV → 加载契约校验全链 | 三列含位总长相等、加载校验通过、`None` 字面量两跳无损（`repr`/`literal_eval`） | 改动 2/3d（L1 P7） |
| 11 | **DYNAMIC × 可选缺省并存** | 显式 `raise`，报错含「拆行二选一」指引（不猜测拆分） | 改动 3b（L1 P8 / L3 §4.5） |

fixture 一律**结构信号构造**（位置模式：齐全/中间缺/尾部缺），不引入算子名分支
（§1.12：fixture 可用具体样例，被测路径不得因算子名改变行为）。

---

## 六、验证方式

```bash
cd /home/z00943229/devkit_fix/AscendC-DevKit
# ⚠️ 必须前置 PYTHONPATH=src（editable 安装在源仓，否则跨仓误判——同 step-125 注）
PYTHONPATH=src python3 -m pytest tests/ut/adapters/test_csv_to_testcases.py -v
PYTHONPATH=src python3 -m pytest tests/ut/ -q            # 全量回归（含 step-126 的 19 个新用例）
PYTHONPATH=src python3 -m pytest tests/st/ -m "not heavy_llm" -q   # ST 非 heavy
```

| 范围 | 要求 |
|---|---|
| UT 全量 | 必过（含 step-126 已收口的 4732 基线不退化） |
| ST 非 heavy | 必过 | ✅ **终版 124 绿 0 failed**（2026-09-20 环境补齐后；实施时 116 绿 + 8 failed 全为 opencode 环境缺失，同 step-126 记录非本改动引入） |
| heavy_llm | §3.11 用户确认后执行；未跑须诚实记录 |
| 真实链路 | 本仓算子无可选输入（L1 取证说明）——真实 run 复现待含可选参数的算子；交付前由用户决策跑一次 |

---

## 七、验收判据

- [x] 9 处改动全部落地（改动 6 零改动有据）；`_build_inputs` 非 DYNAMIC 分支
      **较改前更简单**（按位取用、零 cursor 推断，§1.14）
- [x] 位置语义**单点**：三个生产方都写 `proto_idx`（loader / `_flat_inputs` /
      `_build_inputs`）；`runner.py` 无猜名字残留（grep `_nm` /
      `startswith("input_")` 为空，§1.15/§2.5）
- [x] `_restore_proto_order` 零改动（还原不引入第二套逻辑，L3 红线 1）
- [x] 无旧格式兼容分支（§1.4：CSV 行内格式直接改净；旧「猜名字」测试更新为
      显式字段契约，不留双轨）
- [x] UT 全绿（相关域 124：csv 34 + runner + loader + merge），含场景 1
      （中间缺省）与场景 5 负例（`null` 解析失败）
- [x] cann-bench / `_flat_inputs` 两路径行为不变（场景 7/8 + 既有测试全绿）
- [x] 全量 UT **4745 绿（0 failed）**；ST 非 heavy **终版 124 绿 0 failed**
      （2026-09-20 环境补齐后全量复核；实施时的 8 failed 全为 opencode 环境缺失，
      同 step-126 记录，无新增回归）
- [x] heavy_llm / 真实 run 复现状态如实记录：本仓算子无可选输入，真实链路
      复现待含可选参数的算子（L1 取证说明）；heavy_llm 按 §3.11 用户决策，
      本改动为确定性逻辑（非 §3.9 LLM 行为对象），UT 守护已足

---

## 附：改动文件清单

| 文件 | 改动 |
|---|---|
| `.claude/skills/ascendc-st-design/schema/testcase_csv.json` | 改动 1（None 语义契约） |
| `.claude/skills/ascendc-st-design/scripts/generate_test_cases.py` | 改动 2（占位） |
| `.claude/skills/ascendc-st-design/scripts/generate_empty_tensor_cases_derive.py` | 改动 6（同约定） |
| `src/ascendc_devkit/adapters/testdesign/csv_to_testcases.py` | 改动 3a/3b/3c |
| `src/ascendc_devkit/domain/cann_bench_cases_loader.py` | 改动 4 |
| `src/ascendc_devkit/adapters/npu/runner.py` | 改动 5（删猜名字） |
| `tests/ut/adapters/test_csv_to_testcases.py`（或同域新增） | 场景 1-9 |
