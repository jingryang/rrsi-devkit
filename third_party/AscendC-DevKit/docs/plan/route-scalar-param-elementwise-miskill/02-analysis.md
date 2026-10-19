# 方案分析（L3）：消除标量判据重复实现 + 搬运兜底 + 防线前移

> 回答"有哪些选项、选了哪个、为什么"。按 §1.2 四把尺子（可维护 / 可扩展 / 可诊断 / 架构合理）
> 评估。**主修复已按用户决策定为方向 2（消除重复）**；事实依据见 `01-problems.md`（L1），
> 代码改动配方见 `03-impl-*.md`（L4）。

## 0. 问题定性（根因 = 重复实现 + 进化不同步）

标量/张量归类在工程里有**两条通路**：
- **权威**：`OperatorSpec._route`（`domain/operator.py:219`）—— 已进化为业务语义判据
  （shape 键存在性 `has_shape="shape" in e` + dtype 单标量字符串 + role/param_type/alias precedence），
  正确处理 `shape=[]` 的逐元素 wire tensor。
- **重复**：`_is_scalar_param`（`design_substages.py:1946`）—— 停留在 `_route` 已废弃的旧判据
  （`shape == []` 值空性），误杀 `shape=[]` 的逐元素 wire tensor（Maximum 根因）。

两者判据**进化不同步**：权威早已修对，重复未跟上 → bug 潜伏到 Maximum 暴露。这是 §2.5
（同一职责单一通路）违反的系统性后果，而非孤立笔误。详见 L1 P1 根因深化。

## 1. 主修复方向：两个方向

### 方向 1（已否决）— 就地修 `_is_scalar_param` 的判据

把 `_is_scalar_param` 的 `shape==[]` 判据改成业务语义（role/format）。
- **否决理由（§2.5）**：这只是把"错判据的重复"换成"对判据的重复"——手工重新发明权威 `_route`
  已经做对的事。未来 `_route` 再进化（如新增一种 tensor 信号），`_is_scalar_param` 又会漂移成 bug。
  治标不治本，留下"进化不同步"这个会复发的病根。

### 方向 2（用户选定，推荐）— 消除重复：提取共享判据，权威与重复共用

把权威 `_route` 的判据逻辑提取成**一个共享纯函数** `is_scalar_entry`（落在 domain 层，权威源
所在层），让三条调用路径都消费它，**删除 `_is_scalar_param`**：

```
                    ┌─ OperatorSpec._route        （build TensorSpec/AttrSpec）
is_scalar_entry ────┼─ _route_scalar_params        （原地改写 design_spec dict）
  (domain/operator  └─ _opdef_missing_canonical_anchors （OpDef 渲染 Attr/Input 判定）
   .py，单一权威)            ↑
                       删除 _is_scalar_param（重复通路）
```

- **可维护（§2.5 核心论据）**：标量归类从此**只有一条判据通路**。权威进化时只改 `is_scalar_entry`
  一处，三条路径自动同步，"进化不同步"类 bug 从结构上根除。
- **可扩展（§1.12）**：`is_scalar_entry` 继承权威 `_route` 已验证的 6 级 precedence，任何逐元素/
  广播算子（shape=[] 单/多 dtype）自动正确归位。
- **可诊断**：权威 `_route` 的 precedence 6（不可判定→张量 + 大声 warn，§1.3）一并带入，歧义
  显式暴露而非静默错杀。
- **架构合理（§1.2）**：判据落在职责正确的层（domain 层的标量归类语义）；orchestration
  （design_substages）向下依赖 domain（合法，L1→L7），只是消费权威判据，不自造。

### 拍板：**方向 2**。下面 A' 即方向 2 的展开。

## 2. 主修复 A'：提取 `is_scalar_entry` + 三路径复用 + 删重复

### A'.1 提取共享判据 `is_scalar_entry`（domain/operator.py）

把 `_route` 内联的 6 级判据（:265-298）提取为模块级纯函数（或 `OperatorSpec` staticmethod）：

```python
_SCALAR_TYPES = {"int","int8",...,"float","float16","float32","bool","str","string"}  # 现有集合，提到模块级

def is_scalar_entry(entry: dict, *, group: str = "", input_names: set[str] | frozenset[str] = frozenset()) -> bool:
    """单一权威标量判据（§2.5 单一通路）。判 entry 是标量 attr（True）还是 wire tensor（False）。
    业务语义 precedence（§1.10），不用机制特征（shape 值空性）代理：
      1. role=="attr" → 标量 / role=="tensor" → 张量（显式意图）
      2. param_type 存在 → 张量（tensor-only 概念 REQUIRED/OPTIONAL/DYNAMIC）
      3. output 同名 input → 张量（in-place alias，shape 由 shape_formula 承载）
      4. 有 shape 信号（shape / shape_formula / shape_constraints 键存在）→ 张量
      5. 标量 type（int/float/str/bool）或标量 dtype（单标量字符串，且无 shape）→ 标量
      6. 不可判定 → 张量 + warn（§1.3 surface ambiguity，绝不静默丢一个可能的 tensor）
    """
```

- 判据与权威 `_route`（:265-298）**逐条一致**，非重新发明。
- 关键：第 4 级用**键存在性**（`"shape" in entry`），第 5 级 dtype 要求**单标量字符串**
  （`isinstance(dtype, str)`）—— Maximum 的 `shape=[]`（键在）+ `dtype` 列表 → 张量，正确。

### A'.2 `_route` 改用 `is_scalar_entry`（domain/operator.py:265-300）

`_route` 内联判据替换为 `is_attr = is_scalar_entry(e, group=group, input_names=_input_names)`；
**构建逻辑保留**（:300-308，is_attr → `AttrSpec(...)` / else → `TensorSpec.from_dict(e)`）。
warn（precedence 6）随判据迁入 `is_scalar_entry`，`_route` 不再重复发。`_input_names`（:214 预计算）
作为参数透传。

### A'.3 `_route_scalar_params` 改用 `is_scalar_entry`（design_substages.py:1964-2006）

- 计算 `input_names = {i["name"] for i in design_spec.get("inputs",[])}`。
- 遍历 inputs（`group="inputs"`）/ outputs（`group="outputs"`），用 `is_scalar_entry(e, group=side, input_names=input_names)`
  替代 `_is_scalar_param(e)`（:1990）。标量搬 attrs、张量留原位（其余改写逻辑不变）。
- 调用点 `:1842` 无需改签名（`_route_scalar_params` 内部自取 input_names；兜底 D 仍需 requirement 参数，见 §3）。

### A'.4 `_opdef_missing_canonical_anchors` 改用 `is_scalar_entry`（design_substages.py:2216）

`:2216` `kind = "Attr" if _is_scalar_param(item) else "Input"` →
`kind = "Attr" if is_scalar_entry(item, group="inputs") else "Input"`（inputs pass，alias 不触发）。

### A'.5 删除 `_is_scalar_param`（design_substages.py:1946-1961）

三条路径都改用 `is_scalar_entry` 后，`_is_scalar_param` 再无调用方，**彻底删除**（§2.5 唯一通路、
§1.4 不留过渡层）。删除后 `:1941-1944` 那段"嘴硬"注释一并清除。

### 影响面（同源同治）

- P1（搬运 :1990）+ P5（OpDef 渲染 :2216）共用 `is_scalar_entry`，Maximum 在两处都正确归类。
- 权威 `_route` 行为不变（判据逻辑原样提取，仅位置从内联变函数调用）—— 其既有 UT 是回归基线。

## 3. 兜底加固 D 终版 — design_spec IO 以 golden 签名为权威就地确定性修复

**原则（用户拍板）**：能修的绝对不 halt、不空转；只有真无 IO（不可解决）才 halt。D 的职责：任何原因
导致的 design_spec IO 归类偏差（误搬、产出空、requirement 漂移），都在 integrate **就地确定性修复**
——不 halt、不 loopback 重跑（重跑 design/req-analysis 是空转：IO 契约权威在 golden，不在那些 LLM
agent 的重跑）。

**权威源：golden 函数签名（确定性）为主，requirement 为辅（§1.13 golden 唯一权威）**：
- 主：复用 `adapters/npu/golden_binding.py` 的 `inspect.signature(fn)` + 按参数注解（`Tensor`）分类
  逻辑（§2.5 单一通路，不另造），确定性得到 golden 的 **inputs tensor 名单**。
- 辅：requirement 补 golden 签名不直接给的——**outputs**（golden 返回值不在签名里，需 return 解析
  或 requirement.outputs）、shape/dtype 细节；golden 无 Tensor 注解时退 requirement 作 fallback。

**就地修复逻辑**（`_route_scalar_params` 末尾，`:2003` 后；签名加 `golden_fn` + `requirement` 参数，
调用点 `:1842` 透传 `state.golden_path` 加载的 fn + requirement）：
- 权威 tensor 名单（golden 签名 inputs + requirement outputs）里的 name：
  - 在 design_spec.attrs（被误搬）→ 撤销，从权威源回填 shape/dtype 进 inputs/outputs。
  - 缺失（design 产出空/漏）→ 从权威源回填。
- design_spec 多出的（权威名单没有）→ 保留 + warn（可能是 design 中间 tensor，不擅自删）。
- 全程**就地改 design_spec**，确定性，不重跑任何 stage。

**不空转的关键**：IO 归类偏差的根因不在 design/req-analysis agent 的"重跑"能解决（IO 契约在 golden，
golden 是固定输入）——D 直接读 golden 签名对齐，比 loopback 重跑 LLM 更确定、更省，零空转。

**halt 的唯一兜底**（D + codegen.validate_inputs）：D 用尽 golden 签名 + requirement 都解析不出任何
IO（golden 无 Tensor 注解 ∧ requirement 也空）= 算子**真的没有输入输出**。这是不可解决（框架无法凭空
造 IO），halt 正当。除此之外所有"空/误搬"都被 D 就地修复，不 halt。

## 4. 防线前移 F（已撤 — §2.9「只拦截不解决」禁区）

原拟在 `ValidateStage.transition` 加 inputs/outputs 非空门，空则注入 blocking `target=integrate`
回 integrate 重跑。**撤掉，不实施**，因为它落入 §2.9 禁区（门若只能报问题、修复只能靠重跑 producer
碰运气，不准加）：

- A' 生效时 inputs/outputs 不会空，F **永不触发**（多余）。
- A' 漏网时，loopback 回 integrate 重跑用的是**同一个判据**，同样判错 → 死循环空转，或靠 design
  agent 这次产出不同结构"碰巧"通过 = discover+regenerate（§2.9 明禁）。
- 无"validate 就地修"的合理形态：标量归类产权在 integrate，validate 改它越界（§2.9 门不越界）；
  要就地修就得重复 `_route_scalar_params` 逻辑，违反 §2.5 单一通路。

§2.9 允许的"门 + 反馈渠道"要求反馈渠道构成**确定性**修复；F 的 loopback 重跑不满足。故撤掉。
（codegen.validate_inputs 的 halt 闸定位见 §3：仅在「golden 签名 + requirement 都解析不出 IO = 算子
真无 IO」时触发——真不可解决；其余空/误搬已由 D 就地修复，不会到 codegen。）

## 5. 归档真实性 H（保留，可选，低优）

integrate 归档存 route 后版本（或 route 前/后都存），消除"归档正确、下游错误"迷惑（P2）。
A'+D 修好后 route 不再改坏，此项自然消解；优先级最低。

## 6. 拍板汇总与决策点

| 项 | 选项 | 性质 | 必要性 | 落点 |
|---|---|---|---|---|
| 主修复 | **A'**：提取 `is_scalar_entry`，三路径复用，删 `_is_scalar_param` | 消除重复，根治进化不同步 | **必修** | `domain/operator.py` + `design_substages.py` |
| 兜底 | **D 终版**：design_spec IO 以 golden 签名权威就地确定性修复（误搬撤销/缺失回填），不 halt 不空转 | 能修绝不 halt（用户拍板） | **必修** | `_route_scalar_params` :2003 后，复用 `golden_binding` |
| ~~防线前移 F~~ | ~~validate 非空门~~ | **已撤（§2.9 只拦截不解决，见 §4）** | 不实施 | — |
| 归档真实性 | **H**：归档 route 后版本 | 诊断改进 | 可选（低优） | 归档逻辑 |

**方案 = A' + D**（F 已撤，见 §4；H 为可选低优增强）。

### 决策点（待用户拍板）

1. **heavy_llm 端到端验证**（L4 Step 8）：真实 design agent 全链路守护，按 §3.11 需用户确认
   耗时/token；回归门仍以仓内自闭环 UT/ST 为准（§1.7/§3.7）。
   （F 已撤，无「是否实施 F」决策。）

## 7. 四把尺子总检（A' + D）

- **可维护**：标量判据**单一通路**（`is_scalar_entry`），三路径共用，权威进化只改一处——
  "进化不同步"类 bug 从结构上根除（§2.5，**这是方向 2 优于方向 1 的根本**）。
- **可扩展**：继承权威 `_route` 已验证的 6 级判据，逐元素/广播算子自动正确归位（§1.12）。
- **可诊断**：判据 precedence 6 的 ambiguity-warn 带入所有路径；D 的修复在 integrate 当场就地完成
  （改 design_spec，不重跑、不空转、留告警）。
- **架构合理 + 能修绝不 halt**：A' 治搬运根因；D 以 golden 签名（§1.13 唯一权威，确定性，复用
  `golden_binding`）就地修复所有 IO 归类偏差（误搬/产出空/requirement 漂移），**不 halt、不 loopback
  空转**（IO 权威在 golden 固定输入，重跑 LLM agent 是空转）；codegen halt 仅兜底「golden+requirement
  都解析不出 IO = 算子真无 IO」（真不可解决）。F 已撤（target=integrate loopback 只拦截不解决，§2.9 禁区）。

符合条款：§1.2（四把尺子组合）、§1.4（删重复不留过渡层）、§1.10（业务语义不用机制特征代理）、
§1.12（与算子解耦）、§1.13（requirement 权威对照 + dtype 结构信号）、§2.5（单一通路，**核心**）、
§2.9（producer 自检 + 构造性保证 + 门有反馈渠道 + 不越界）。
