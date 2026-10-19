# 算子属性类型系统通用化 — 实施方案（L4）

- **L3**：`01-analysis.md`（拍板冻结）
- **状态**：已实施（2026-08-29，用户"实施吧"放行）——as-built 见文末
- **同批**：step-106（perf 第五向量，配方在 `dispatch-npu-probe-subprocess/02-impl.md` 末节）

## 实施前置实证（已完成，2026-08-29，torch 2.10.0 + CANN beta.3）

1. ~~torch schema 拒嵌套~~ → **实测推翻**：`torch.library.Library.define("f(Tensor x, int[][] pools) -> Tensor")`
   注册成功；`torch.ops.ns.f(t, [[1,1],[2,2]])` 调用成功，impl 收到嵌套原样。
   边角：无张量参数的纯属性算子需 CompositeExplicitAutograd fallback key。
   **方案修正：决策③从 A′（wrapper 翻译层）改为直绑零翻译**（L3 已勘误）。
2. harness 符号解析：`torch_op` 走 `torch.ops.<ns>.<op>`、`pybind` 走模块函数
   （`__import__+getattr`）——直绑方案继续用 torch_op 路径，零改动（A′ 曾需要的
   "模块函数绑定"不再需要）。

## 改动 1：类型语法 + 递归检查器（`domain/operator.py`）

- 新增类型表达式解析：标签 → Python typing 规范形（`list[list[int]]`、`int | float`、
  `X | None`、`tuple[int,int]→list[int]+定长2`）。
- `_canonical_attr_type`（翻译点）扩别名表覆盖语料全部 ~50 种写法（清单：L1§4）：
  新增 `int[][]/List[List[int]]→list[list[int]]`、`?后缀/X|None→X|None`、
  `int[N]→list[int]+N`、`Scalar→int|float`、`SymInt→int`、`ScalarType→str`、
  `tuple[...]/kernel_size: tuple→list[...]`、`List[bool]/bool[]→list[bool]`、
  `ListFloat/float[]→list[float]`、`int|N`/联合串解析。
- 新增递归检查器 `check_attr_value(value, type_expr)`（~30 行，get_origin/get_args
  遍历）：叶类型复用既有 `_is_int_value` 等单点；`list[T]`=isinstance(list) 且逐元素
  递归；定长 N=长度断言；`X|None`/联合=任一分支通过。**dict/object 留显式扩展点
  （语料 0 例，不实现——宁缺毋滥 §2.12）。**
- `CANON_ATTR_CHECKERS` 枚举表退役为"叶类型表"（容器逻辑泛化进递归检查器，§2.5
  删旧通路）；`_validate_attrs`（runner）改为调递归检查器（单点，§1.15）。
- **UT**：嵌套 2/3 层、定长违例、联合（含 `(int|None)[2]` 形态）、可空、别名全表
  回放（语料 50 写法参数化用例）、负例（`[[1,1]]` 对 `list[int]` 必拒——本事故回归锚）。

## 改动 2：requirement 期自检（防线 2）

- 位置：requirement stage transition 产物校验（与既有 manifest 校验同层）。
- 检查：a) 每个声明类型可被语法解析——不可解析 **halt**，报错含原文标签与三选一
  处置指引（加别名/加形状规则/拒任务）；b) 与 golden 结构 cross-check——从 golden
  注解 + cases 样例值派生结构特征（嵌套性/定长），与声明不符 **halt**，报三方对照。
- **UT**：不可解析标签 halt；嵌套声明 vs 扁平 golden 样例（本事故正向锚）；一致通过。

## 改动 3：test_design 期自检（防线 3）

- 位置：test_design stage transition 产物校验。
- 检查：全部用例 attrs 过改动 1 的递归检查器（对 op_spec 契约）。失败 **halt**，
  报"用例↔契约不一致"+ 双方原文；**不自修**（冲突以 golden 为准上报，§1.13）。
- **UT**：用例嵌套值 vs 契约 `list[int]` → halt（本事故另一个回归锚）；一致通过。

## 改动 4：嵌套属性直绑（原 A′ wrapper 方案已随实证证伪撤销）

- 判定消失：不再有"schema 不可表达类型"分类——嵌套类型直接注册嵌套 schema
  （`int[][]`），公共可调用体 = torch.ops 符号（与所有算子同款）。
- coder 侧：skill 增一句结构性指引——"属性含嵌套列表时，plugin 注册 schema 用
  `int[][]` 形态、C++ 参数 `std::vector<std::vector<int64_t>>`、OpDef 用
  `ListListInt`；纯属性算子（无张量参数）注册实现需 CompositeExplicitAutograd
  fallback key"。**结构信号驱动，不点名算子（§1.12）。**
- 框架侧：callable_target/auto-rescue 零改动。
- **UT**：嵌套 schema 注册+调用的可行性别走 UT（torch 依赖属环境事实，已在
  前置实证钉住并记录于 L3）；框架侧无代码改动则无新增 UT。

## 改动 5：skill 治理规则（两侧）

- requirement/req-analysis skill：**禁止为迁就类型系统发明编码变换（压平/序列化/
  自创规则）；类型表达不了 = 框架缺口，如实声明 + 上报**（通用语义表述，不带编号
  §2.11）。
- test_design skill：用例值形态忠实 golden 语义；与契约不一致时以 golden 为准。

## 验证

1. **UT/ST**：上述各改动用例 + 全量绿（§3.6 默认范围）。
2. **语料回放**：全部 ~50 种既有标签 + 全部既有任务用例过校验器，零误伤（脚本化
   回放，防修复引入回归）。
3. **heavy_llm 端到端（用户确认后，§3.11）**：
   - interpolate_custom **fresh 重跑**（存档 state 的 op_spec 已错，resume 从 codegen
     续不清——需新 exec 从 requirement 起）→ 四层防线全过 + wrapper 边界真实走通。
   - 批 `20260829-024316-f0252f` 其余 2 exec（upsample/mse，守卫 halt 已由 5a8c23b0
     修复）`RESUME=1` 续跑 → 过 codegen 续走后续 stage。
   - perf 修复验证（step-106）：devkit 工作流路径 UT + 单算子真跑（不依赖本批）。

## 过严防护红线（实施必须遵守——评审补充 2026-08-29）

1. **定长是声明的约束，不是硬编码的真理**：`int[N]` 仅在声明为定长时校验长度；
   语义可变的参数（F.pad 式）应声明 `list[int]`——声明忠实由防线 2 cross-check 保证，
   不由校验器强加。语料回放含"声明定长但样例变长"用例，验证走 halt 而非误拦。
2. **cross-check 只拦矛盾，不拦细化**：golden 裸注解（`list`）⊃ 细化声明
   （`list[list[int]]`）= 通过；只有"声明与样例结构矛盾"（声明标量/扁平 vs 样例
   列表/嵌套）才 halt。禁止实现为结构相等比对。
3. **wrapper 签名核对比类型兼容，不比文本**：只针对 schema 不可表达的属性，只验证
   对应参数类型兼容（容忍默认值/kwargs/子类型化）；禁止注解字符串相等比对。
4. **语料回放是过严回归门**：全部既有任务标签+用例回放零误伤是合入硬条件
   （见"验证"节 2）。

## 不做清单（边界）

- dict/object 属性类型（语料 0 例，仅留扩展点）；枚举值域约束（正交层，出现需求再议）；
- pybind 全嵌套通路（B，已否决）；harness 编码引擎（C，已否决）；golden 适配（D，否决）；
- 既有任务存量 op_spec 的批量翻新（无消费压力，新产物按新语法；存量遇消费时按新
  校验器自然暴露）。

## As-built（2026-08-29）

- **改动 1**：`domain/operator.py` 类型文法落地——`check_attr_value`（单一递归
  检查器：base | list[T] | T1|T2，null 仅显式 union 成员合法）+ `is_grammar_type`
  （结构判定）+ 翻译点重写（`_canonical_attr_type`/`canonical_attr_type` 元组形）
  + `AttrSpec.length` 承载定长（规范串不带 N）。`CANON_ATTR_CHECKERS` 退役为
  叶+常用复合表（deploy 断言不破坏）。runner `_validate_attrs` 切换递归检查器
  + 定长断言。**语料回放：proto.yaml 全量 55 标签/1112 例，51 标签/1107 例可翻
  （99.55%）；透传 4 种 5 例=Tensor×3（张量误标属性）/裸 list/带中文注释标签
  ——响亮暴露正是设计行为**。
- **改动 2**：requirement `_validate_attr_type_grammar`（a 文法可表达性+b cases.yaml
  样例 cross-check，只拦矛盾不拦细化）。错误走既有 schema_violation 重试通路
  （路由=halt 语义由 stage 迭代预算承载）。
- **改动 3**：test_design casegen 两条用例生产路径（CSV/外部加载）落 state 前
  统一 `_validate_cases_against_spec`（单点复用 runner `_validate_attrs`）。
- **改动 4**：直绑落地——coder skill 增维13（嵌套属性 schema `int[][]` 直传、
  禁压平+配对约定、`std::vector<std::vector<int64_t>>`/`ListListInt` 三层同构、
  纯属性算子 CompositeExplicitAutograd fallback key）。框架零改动（实证支持）。
- **改动 5**：req-analysis skill 类型声明规则重写（嵌套必须声明嵌套、禁自创编码
  变换、表达不了如实声明保留原写法）；generate-case skill 增属性值形态忠实规则。
- **实施偏差**：L3 决策③ A′ → 直绑（前置实证推翻"schema 不支持嵌套"，L3 已
  勘误——比原方案更简：零翻译层）。
- **UT**：test_attr_type_grammar（93）+ test_attr_defense_lines（10）+ 既有
  test_runner_contract 断言升级（IntList 从"透传"升为"可翻译"）。
