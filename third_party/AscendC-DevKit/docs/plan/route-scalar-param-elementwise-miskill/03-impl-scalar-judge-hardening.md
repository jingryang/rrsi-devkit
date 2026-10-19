# 实施方案（L4）：消除标量判据重复（方向 2）+ 搬运兜底 + validate 非空门

> 回答"改哪个函数、什么顺序、怎么验证"。对应 `02-analysis.md` 拍板的 **A' + D**（最小根治集）
> + **F**（建议 defense-indepth，待决策点 1）。事实依据见 `01-problems.md`。
> 按 §3.1 TDD：先写测试再改代码。本文是动手前配方，不含实际 patch。
> **方向 2 = 消除 `_is_scalar_param` 重复，提取共享判据 `is_scalar_entry`，权威 `_route` 与
> design_spec 侧三路径共用（§2.5 单一通路）。**

## 0. 实施顺序（TDD）

```
Step 1  写回归 UT（红）           _route_scalar_params(Maximum 不搬) + 兜底场景        §1
Step 2  提取 is_scalar_entry      domain/operator.py（从 _route :265-298 提取）        §2
Step 3  _route 改用 is_scalar_entry domain/operator.py:265-300（构建逻辑保留）         §3
Step 4  _route_scalar_params + D 终版  design_substages:1990/2003 + 提取 classify_golden_params(复用 golden_binding)  §4  → Step1 UT 转绿
Step 5  _opdef_anchors 改用       design_substages.py:2216                             §5
Step 6  删除 _is_scalar_param     design_substages.py:1946-1961（含嘴硬注释）           §6
Step 7  全量 UT 零回归            §3.6 默认范围                                         §7
Step 8  [决策] heavy_llm 端到端   重跑 Maximum/同类逐元素（需用户确认 §3.11）           §8
```

Step 2-3 是"提取 + 权威侧无缝替换"（`_route` 行为不变，其既有 UT 是回归基线）；
Step 4-6 是"design_spec 侧切到权威判据 + 删重复"（Step 1 红→绿）。

---

## 1. Step 1 — 回归 UT（先写，TDD 红）

**落点**：`tests/` 下搜 `_is_scalar_param` / `_route_scalar_params` / `OperatorSpec` / `_route`
既有 test 文件追加；无则新建。纯逻辑 UT，无 `npu/llm` 标记（§3.5/§3.8）。

### 1.1 `is_scalar_entry` 判据覆盖（新函数，6 级 precedence）

| # | 输入特征 | 期望 | 覆盖 precedence |
|---|---|---|---|
| U1 | `shape=[], dtype=[6元素], role=None, format=ND`（Maximum x1） | **False** | 4（shape 键在→tensor）+ dtype 列表非标量 |
| U2 | `shape=[], dtype=["float16"], role=None`（单 dtype 逐元素） | **False** | 4（shape 键在→tensor） |
| U3 | `role="attr"` | True | 1 |
| U4 | `role="tensor"` | False | 1 |
| U5 | `param_type="DYNAMIC"` 无 shape | False | 2（variadic tensor） |
| U6 | output 同名 input（group=outputs, name∈input_names）无 shape | False | 3（in-place alias） |
| U7 | `format="SCALAR"`, 无 shape/role | True | 5（scalar type/format） |
| U8 | `type="float"` 无 shape/role | True | 5 |
| U9 | 无任何信号（无 shape/dtype/role/param_type） | False + **warn** | 6（不可判定→tensor + §1.3 告警） |

> U1 是 Maximum 核心回归；U2 覆盖方向 1（修判据）会漏网的单 dtype 算子，证明方向 2 必要。

### 1.2 `_route` 行为不变（提取后回归基线）

复用 `OperatorSpec.from_dict` / `_route` 既有 UT（epsilon→attr、DYNAMIC→tensor、in-place alias→tensor
等），Step 2-3 提取后必须仍全绿——证明判据"原样搬家"、无行为漂移。

### 1.3 `_route_scalar_params` 回归（Step 4 转 绿）

| # | 输入 design_spec | 期望 | 覆盖 |
|---|---|---|---|
| R1 | `inputs=[x1,x2 shape=[]], outputs=[y shape=[]], attrs=[]`（Maximum） | `moved=[]`，三处**不变** | P1 端到端回归（当前**红**） |
| R2 | `inputs=[tensor, epsilon{role:attr}], attrs=[]` | epsilon 搬 attrs，tensor 留 | 真标量正常搬运 |
| R3 | x1 被误搬进 attrs + golden 签名含 x1(tensor) | **撤销 x1 回 inputs**（golden 权威就地修） | D 终版 |
| R4 | inputs 空 + golden 签名含 tensor + requirement 空 | **从 golden 签名回填 inputs** | D 主权威=golden |
| R5 | golden 无 Tensor 注解 + requirement 也无 IO | 不修（到 codegen halt） | 真无 IO 兜底 |

---

## 2. Step 2 — 提取 `is_scalar_entry`（domain/operator.py）

**落点**：`src/ascendc_devkit/domain/operator.py`，模块级（`OperatorSpec` 之前）。

**改动配方**：把 `_route`（:265-298）内联判据提取为纯函数，判据逐条不变。

```python
# 模块级（现有 _route 内 :260-263 的集合提到此处）
_SCALAR_TYPES = {"int","int8","int16","int32","int64","uint","uint8","uint16",
                 "uint32","uint64","float","float16","float32","double","bool",
                 "str","string"}

def is_scalar_entry(entry, *, group="", input_names=frozenset()):
    """单一权威标量判据（§2.5 单一通路）。True=标量 attr，False=wire tensor。
    业务语义 precedence（§1.10），不用 shape 值空性等机制特征代理。详见 docstring。"""
    role = entry.get("role")
    if role == "attr":   return True                  # 1
    if role == "tensor": return False                 # 1
    if "param_type" in entry: return False            # 2
    name = entry.get("name", "")
    if group == "outputs" and name in input_names: return False   # 3
    if ("shape" in entry or "shape_formula" in entry
            or "shape_constraints" in entry): return False        # 4 键存在性
    stype = entry.get("type")
    if isinstance(stype, str) and stype.lower() in _SCALAR_TYPES: return True  # 5
    dtype = entry.get("dtype")
    if isinstance(dtype, str) and dtype.lower() in _SCALAR_TYPES: return True  # 5
    logger.warning("is_scalar_entry: %s entry %r declares neither tensor nor "
                   "scalar signal; keeping as tensor — declare its kind explicitly.",
                   group, name)                                   # 6 §1.3
    return False
```

**关键不变量**：第 4 级 `"shape" in entry`（键存在性）而非 `shape == []`（值空性）—— 这是 Maximum
`shape=[]` 判 tensor 的核心。第 5 级 dtype 要求 `isinstance(dtype, str)`（单标量），列表 dtype 不命中。

## 3. Step 3 — `_route` 改用 `is_scalar_entry`（domain/operator.py:265-309）

**改动配方**：`_route` 内联判据（:265-298）替换为一行调用，**构建逻辑保留**（:300-308）。

```python
def _route(entries, group):
    tensors = []
    for e in entries:
        name = e.get("name", "")
        is_attr = is_scalar_entry(e, group=group, input_names=_input_names)  # ← 替代内联 6 级判据
        if is_attr:
            attrs[name] = AttrSpec(name=name, type=e.get("type") or e.get("dtype",""),
                                   default=e.get("default"),
                                   description=e.get("note","") or e.get("description",""))
        else:
            tensors.append(TensorSpec.from_dict(e))
    return tensors
```

`_input_names`（:214 预计算）作为参数透传；原 warn（:292-298）随判据迁入 `is_scalar_entry`，`_route`
不再重复发。**行为不变** —— Step 1.2 的 `_route` 既有 UT 必须全绿。

## 4. Step 4 — `_route_scalar_params` 改用 + D 终版（design_substages.py:1964-2006）

**改动配方（两处）**：

(a) 判据切换（:1990）：`_is_scalar_param(e)` → `is_scalar_entry(e, group=side, input_names=input_names)`。
函数开头先算 `input_names = {i["name"] for i in design_spec.get("inputs",[]) if isinstance(i,dict) and i.get("name")}`。

(b) 兜底 D 终版（:2003 循环结束后、:2005 `return moved` 前插入；签名加 `golden_fn=None, requirement=None`）：

```python
# D 终版：design_spec IO 以 golden 签名（主，§1.13）+ requirement（辅）权威就地确定性修复。
# 能修绝不 halt、不空转（IO 权威在 golden 固定输入，重跑 LLM agent 是空转）。
from ascendc_devkit.adapters.npu.golden_binding import classify_golden_params  # 见下：从 bind_golden_args 提取

auth_tensors = set()                       # 权威 tensor 名单
if golden_fn is not None:                  # 主：golden 签名确定性给 inputs tensor（按 Tensor 注解）
    auth_tensors |= classify_golden_params(golden_fn).tensor_names
if isinstance(requirement, dict):          # 辅：requirement 补 outputs（golden 返回值不在签名里）+ 兜底
    for side in ("inputs", "outputs"):
        for e in (requirement.get(side) or []):
            if isinstance(e, dict) and e.get("name"):
                auth_tensors.add(e["name"])

if auth_tensors:                           # 就地确定性修复，不重跑任何 stage
    keep_attrs, restored = [], []
    for a in attr_list:                    # 权威 tensor 误搬进 attrs → 撤销
        (restored if a.get("name") in auth_tensors else keep_attrs).append(a)
    existing = {i.get("name") for i in design_spec.get("inputs", []) if isinstance(i, dict)}
    existing |= {o.get("name") for o in design_spec.get("outputs", []) if isinstance(o, dict)}
    for name in (auth_tensors - existing): # 权威 tensor 缺失 → 从 requirement 同名项回填
        side, entry = _lookup_in_requirement(name, requirement)
        design_spec.setdefault(side or "inputs", []).append(
            entry or {"name": name, "dtype": [], "shape": [], "format": "ND", "param_type": "REQUIRED"})
    design_spec["attrs"] = keep_attrs
    moved = [m for m in moved if m.split("/", 1)[-1] not in auth_tensors]
    if restored or (auth_tensors - existing):
        Logger.warn(f"_route_scalar_params reconciled design_spec IO to golden-signature "
                    f"authority (restored {len(restored)} misrouted, filled "
                    f"{len(auth_tensors - existing)} missing): {sorted(auth_tensors)}")
# 无 auth_tensors（golden 无注解 ∧ requirement 也空）= 算子真无 IO → 不在此修，
# 留 codegen.validate_inputs 拒空 halt（唯一真不可解决情况）。
return moved
```

**`classify_golden_params(fn)`**（从 `golden_binding.bind_golden_args:75-94` 提取的共享分类逻辑，§2.5 单一
通路）：遍历 `inspect.signature(fn)`，按 `"Tensor" in annotation` 分出 `tensor_names` / `scalar_names`；
`bind_golden_args` 改为调用它（消除重复）。依赖 golden 参数带 Tensor 注解——无注解返回空，退 requirement
fallback（§1.13：golden 无注解是其自身质量，产权在 golden 方，框架不兜）。

**`_lookup_in_requirement(name, requirement)`**（小工具）：在 requirement.inputs/outputs 找 name，返回
`(side, entry)`；找不到返回 `(None, None)`。

**调用点同步**（:1842）：`_route_scalar_params(ds)` →
`_route_scalar_params(ds, golden_fn=_load_golden_fn(state), requirement=getattr(state,"requirement",None))`。
`_load_golden_fn` 从 `state.golden_path` 加载 golden.py 取 golden callable（与 harness 侧加载一致）。

**验证**：R1（Maximum 不搬）红→绿；R3（golden 签名权威撤销误搬 + 回填缺失）绿；R2（真标量）不受影响；
新增 R4（golden 无注解 → fallback requirement 仍修复）、R5（golden+requirement 都无 IO → 不修，到 codegen halt）。

## 5. Step 5 — `_opdef_missing_canonical_anchors` 改用（design_substages.py:2216）

**改动配方**：
```python
# before
kind = "Attr" if _is_scalar_param(item) else "Input"
# after（inputs pass；alias 判定对 inputs 不触发，传 input_names 保持判据一致）
kind = "Attr" if is_scalar_entry(item, group="inputs", input_names=_ds_input_names) else "Input"
```
`_ds_input_names` 在函数内从 `spec.get("inputs")` 预计算一次（与 `_route` 同构）。Maximum x1 →
`Input("x1")` 期望（P5 同源治好）。

## 6. Step 6 — 删除 `_is_scalar_param`（design_substages.py:1946-1961）

Step 4-5 改用 `is_scalar_entry` 后，`_is_scalar_param` 无调用方。**彻底删除**函数定义（:1946-1961）
+ `:1938-1944` 那段"judge by BUSINESS SEMANTICS"嘴硬注释（§1.4 不留过渡层、§2.5 唯一通路）。

`grep "_is_scalar_param src/"` 应返回 0 命中（除可能的 test，一并改/删）。

## 7. Step 7 — 全量 UT 零回归（§3.6）

- 范围：UT 全量 + 非 heavy_llm ST + 预检 LLM/NPU/CANN 可达性（§3.6）。
- 重点回归：
  - `OperatorSpec._route` / `from_dict` 既有 UT（Step 3 提取后行为不变）—— **最关键**，证明判据
    "原样搬家"无漂移。
  - `is_scalar_entry` 新 UT（U1-U9）。
  - `_route_scalar_params` / `_opdef_missing_canonical_anchors` UT（R1-R3 + OpDef 渲染）。
  - integrate / validate stage transition UT。
- 红线（§3.4）：任何回归必修根因，禁止 skip/except。
- 纯逻辑，无 npu/llm 依赖，无需 heavy_llm（§3.11）。

## 8. Step 8 — heavy_llm 端到端验证（§3.11，需用户确认；仓内自闭环优先）

> **§1.7 / §3.7 约束**：回归门必须是仓内自闭环 UT/ST，**禁止押在 cann-bench 等第三方仓算子上**
> （memory `test-no-third-party-repo-dep`）。bug 虽在 self_evolve 批跑 cann-bench 算子 Maximum 时
> 暴露，但 `design_spec` 是框架 design stage **自产**（cann-bench 仅提供算子源码 + golden 作为
> 输入），修复对任何来源的逐元素算子生效，与 cann-bench 无关。

- **回归门（必做，零仓依赖）**：Step 1/7 的仓内 UT（`is_scalar_entry` + `_route` 既有 UT 回归 +
  `_route_scalar_params` fixture ST）——纯框架内部，已覆盖 Maximum `shape=[]` 场景（U1/R1），
  是修复的权威验证，**不依赖任何外部仓**。
- **heavy_llm 端到端（可选，§3.11）**：若需真实 design agent 全链路守护，优先用**仓内自带样例
  算子**驱动 design→codegen；若用 Maximum 等 cann-bench 算子，明确标注为**有条件集成验证**
  （依赖外部仓，缺仓则 skip，§3.7），**不计入回归门**。
- 成本：真实 design agent 全流程，分钟级耗时 + token（§3.11 heavy_llm）。
- **执行前向用户列清单 + 预估成本，由用户决策**（§3.11）。未跑须诚实记录"本次未覆盖
  heavy_llm"（§3.11 与 §3.4 边界）。
- 通过判据（§3.10）：codegen 不再 `PreconditionError`，inputs/outputs 含 tensor，进入正常迭代。

---

## 9. 回归风险与边界

- **`_route` 提取的行为等价性**（最大风险点）：Step 2-3 必须保证判据"原样搬家"。靠 Step 1.2 既有
  `_route` UT 全绿守门（epsilon/DYNAMIC/in-place alias/shape 各 case）。若 UT 暴露差异，回退 Step 2
  核对 precedence 顺序与边界（键存在性 vs 值空性、dtype str vs list）。
- **`is_scalar_entry` warn 噪音**：precedence 6 对不可判定 entry 发 warn。design_spec 正常 entry 都
  有 shape/dtype/role 之一，warn 罕见；若某 stage 大量缺信号，warn 聚合后可降级（按 name 去重）。
- **D 终版就地修复（不空转）**：D 读 golden 签名（确定性）就地改 design_spec，不重跑任何 stage
  （IO 权威在 golden 固定输入，重跑 design/req-analysis LLM 是空转）。误搬撤销/缺失回填都以 golden
  权威为准；正常搬运（R2）不动 design_spec 的 IO。
- **golden 注解依赖（D 主权威的边界）**：`classify_golden_params` 靠参数 `Tensor` 注解分 tensor/scalar。
  golden 无注解 → 返回空 → 退 requirement fallback；requirement 也空 → 不修，到 codegen halt（算子
  真无 IO，§1.13 产权在 golden/需求方，框架不兜）。
- **不触碰**：`_reconcile_shape_ranks` / `_reconcile_param_types` / `_reconcile_inplace_outputs`
  （integrate transition 另三段兜底，用权威对照判据，本次不在范围；`_reconcile_param_types` Pass2
  位置对齐是潜在同类风险，记为后续单独评估项，不在本次修）。codegen.validate_inputs halt 仅兜底
  「golden+requirement 都无 IO = 算子真无 IO」（真不可解决），不再作首选。

## 10. 完成定义（DoD）

- [ ] Step 1 UT 全绿（U1-U9、R1-R3），`_route` 既有 UT 零回归。
- [ ] Step 7 全量 UT + 非 heavy_llm ST 零回归。
- [ ] `grep "_is_scalar_param" src/` 返回 0 命中（重复通路已删）。
- [ ] F 已撤（§2.9 只拦截不解决），不实施（见 02 §4）。
- [ ] [Step 8 决策] heavy_llm：已跑通过 / 已记录"本次未覆盖"。
- [ ] L1 问题状态更新（P1-P5 标注修复落点）；L2 总纲索引表挂载本子目录。

## 11. L2 总纲挂载（建议）

`docs/plan/skills-integration-and-tdd-plan.md`（L2 全局总纲）索引表新增一行挂载本子目录，
"覆盖问题"列填 `P1-P5`。L2 是活文档，挂载行由实施者动手时一并更新（本文档不直接改 L2）。
