# 算子属性类型系统通用化 + 分层校验防线 + 嵌套接口边界（L3 方案分析）

- **问题**：`docs/issue-analysis/20260829-interpolate-pd-contract-attr-type-gap.md`（L1）
- **状态**：拍板冻结（2026-08-29 会话评审：决策 ①②③ 全部落定）
- **同批关联**：step-106（perf 第五向量，见 `dispatch-npu-probe-subprocess/02-impl.md`）

## 一、问题本质（两面）

1. **表达面**：属性类型系统是有限枚举表（`CANON_ATTR_CHECKERS` 6 行），无嵌套/定长/
   可空/联合——正确声明在构造上不可能，逼 requirement LLM 走"静默合理化"通道
   （压平+自创编码描述），与 golden/test_design 三方脱钩。
2. **暴露面**：op_spec 与 test_cases 的第一个联合消费点被构造性排在 codegen 尾段
   （3h 后）；requirement/test_design 两个更早自检点位缺一致性检查。

## 二、决策记录

### 决策 ①：类型记法与检查器 —— 通用结构语法，锚定既有标准（不自造记法）

- **规范记法 = Python typing（PEP 484/585/604）**：`list[list[int]]`、`int | float`、
  `X | None`。契约层描述的是 golden（Python 函数），其类型记法的既有标准就是 Python
  自己的类型系统。~~草稿期的 `list<T>` 尖括号记法~~属自造，**否决**（用户原则：不造
  新标准）。
- **检查语义 = 结构递归**，与 JSON Schema 的结构规则一致（array+items / null=可空 /
  anyOf=联合 / minItems==maxItems=定长）。检查器为 ~30 行递归函数（stdlib typing
  对象上的 get_origin/get_args 遍历），不引入外部依赖（typeguard/pydantic 为 6 个
  叶类型引依赖不成比例）。
- **别名层 = 有限拼写翻译表**（既有系统拼法 → 规范记法）：`int64→int`、
  `ListInt/int[]→list[int]`、`int[][]→list[list[int]]`、`tuple[...]→list[...]`、
  `?后缀/X|None→X|None`、`Scalar→int|float`、`SymInt→int`、`ScalarType→str`、
  `int[N]→list[int]+定长N`……覆盖语料全部 ~50 种写法（普查清单在 L1§4）。
  新拼写加一行合法；**新组合（嵌套深度/联合套列表）永远免费**。
- **值域封闭性论证**：属性值必须进出 JSON/YAML 工件（§2.10），JSON 值域封闭
  （null/bool/number/string/array/object）——语法+显式扩展点=构造性完备，无无限尾巴。
  目前唯一未含形态 object/dict 语料 0 例，留显式扩展点（真出现加一条递归规则）。
- **未来新类型的消化机制**（不逐类型打补丁）：新类型只来自两源头——ATen 镜像
  （schema 词汇表封闭可全量预映射：`Dimname/MemoryFormat→str`、`Scalar→int|float`、
  `Generator/Storage/Tensor→引用类型非值属性`）与自定义复合算子（标签开放但值域
  封闭）。真正未预测的标签由 requirement 期**响亮报错**（见决策②防线）暴露为
  有界三选一决策（加别名/加形状规则/拒任务），不存在静默通道。

### 决策 ②：分层校验防线（暴露面前移到产出当下）+ 冲突路由 = halt

| 防线 | 时点 | 检查 | 产权语义 |
|---|---|---|---|
| 1. 类型语法 | — | 让正确声明成为可能 | 消灭"只能造假"的构造困境 |
| 2. requirement 自检 | 产出当下 | 标签可被语法解析 + 与 golden 结构特征 cross-check（注解嵌套性/样例值），冲突即 halt | 对 golden 忠实（§1.13） |
| 3. test_design 自检 | 产出当下 | 用例过同一递归校验器（单点复用 §1.15）；冲突 halt 并报"用例↔契约不一致" | 对契约一致；冲突以 golden 为准上报，不自修迁就 |
| 4. smoke 联合校验 | codegen 尾段（现状） | 确定性兜底 | 本批实证有效，保留 |

- **冲突路由 = halt + 明确报错**（用户拍板）。否决自动反馈 requirement 重跑：易空转、
  掩盖分歧信号（§3.7 诚实优先）。
- **skill 硬规则**（requirement/test_design 两侧）：禁止为迁就类型系统发明编码变换
  （压平/序列化）；类型表达不了必须上报。本轮事故 LLM 手握正确知识却选择就地
  合理化——缺的就是这条通道。
- §2.9 合规性：防线 2/3 是 producer 对**自己产物**的自检（requirement 对 golden 忠实、
  test_design 对契约一致），非门越界查上游；防线 4 保留为联合兜底。

### 决策 ③：嵌套接口边界 —— 原拍板 A′，实施前置实证推翻前提后修正为「直绑零翻译」

**原前提（已被实测推翻）**：torch.ops schema 文法不支持嵌套列表 → 需要一处翻译。

**实测（2026-08-29，torch 2.10.0 + CANN beta.3 环境）**：

```
lib.define("nested_call_op(Tensor x, int[][] pools) -> Tensor")  → 注册成功
torch.ops.ns.nested_call_op(t, [[1,1],[2,2]])                    → 调用成功
impl 收到 pools = [[1,1],[2,2]]（嵌套原样到达实现层）
```

torch 运行时**原生支持嵌套列表**（schema 文法 + dispatcher + python 绑定全链）。
边角：无张量参数的纯属性算子需 CompositeExplicitAutograd fallback 注册 key（实现
细节登记，非边界）。此前"schema 不支持嵌套"系按文法知识想当然——L4 的"实施期
实证"护栏按设计兜住了它。

**修正后方案（比 A′ 更简：直绑零翻译）**：

- 嵌套属性算子公共可调用体 = 直接注册嵌套 schema 的 torch.ops 符号；C++ 插件侧
  `std::vector<std::vector<int64_t>>`；CANN OpDef 侧 `ListListInt`（IR 层原生支持，
  三层同构）。
- ~~wrapper 绑定层~~ / ~~类型机械转换~~ / ~~契约层与 wire 层各锚定不同标准~~：
  整层删除——契约类型与 wire 类型同一标准贯穿，**零翻译点**。
- callable_target / auto-rescue 零改动（继续派生 torch.ops 符号）。
- 类型语法 / 四层防线 / 别名表不变（与边界方案正交）。

**否决项**（A′/B/C/D + 事故形态，保留否决记录）：

- **A′（wrapper 翻译层）**：前提（schema 不支持嵌套）被实测证伪——在无需翻译的系统
  上加翻译层 = 自造复杂度，弃。
- **B（pybind 直绑全嵌套）**：弃 torch.ops 注册惯例、丢 dispatcher 集成——且其动机
  （"torch.ops 表达不了嵌套"）同样被证伪。
- **C（接口诚实扁平 + harness 侧编码转换）**：公共接口永久偏离语义真相、harness 热
  路径内建编码引擎、kernel/golden 喂值形态分叉——短视的便宜。
- **D（用例存扁平 + golden 侧适配还原）**：动权威调用侧，§1.13 一票否决。
- **压平+散文约定（本次事故形态）**：约定藏进规格书冒充类型、三方脱钩。

**业界对照修正**：`F.pad` 扁平+文档约定属 schema 时代遗产（ATen 历史签名），不是
"torch 表达不了嵌套"的证据；现代 `torch.library` 注册（本工程 plugin 所用路径）
原生支持。CANN OpDef `ListListInt` 与 aclnn 运行时扁平的差异不约束本工程（本工程
走 torch plugin 注册路径，非 aclnn L2 直调）。

### 决策 ④（随③附带）：与 perf 第五向量同批实施（用户拍板）——一次验证批覆盖
"主进程/契约纯度"家族。perf 修法产权在 `dispatch-npu-probe-subprocess/02-impl.md`。

## 三、标准对齐硬约束（单列，用户原则）

凡有既有标准的表面必须锚定既有标准；无标准可循的仅限工程内部流程；**禁止发明
记法/格式/协议**。对照表：

| 表面 | 锚定标准 |
|---|---|
| 参数值格式 | YAML/JSON |
| 类型记法（契约层） | Python typing（PEP 484/604） |
| 校验语义 | JSON Schema 结构规则 |
| wire 格式 | ATen/PyTorch 惯例（扁平+约定+定长校验，F.pad 同款） |
| 嵌套 IR 层表达（需要时） | CANN OpDef `ListListInt` |
| 变长升级路径 | ATen 张量化惯例 |
| 拼写翻译 | 翻译点模式（§1.9 to_soc_version 同款） |

## 四、与四把尺子的对照（§1.2）

- **可维护**：不变式（golden 忠实、契约一致）从散文约定变机器强制；类型单点。
- **可扩展**：新组合零成本；新形状一条递归规则；同类新算子（任意嵌套属性）自动
  正确归位——interpolate 类事故构造性不再发生。
- **可诊断**：不可表达类型在 requirement 期响亮报错（原文标签入报错文案）；冲突
  halt 带三方对照信息。
- **架构合理**：域层持有类型语法（纯数据+规则）；adapter 层执行校验；边界转换在
  生成代码（wrapper）有主拥有；分层校验各归其位（§2.9）。
