# 20260829 interpolate_custom PD-CONTRACT halt — 算子属性类型系统表达力缺口（L1 事实记录）

- **状态**：已定位根因，方案见 `docs/plan/op-attr-type-system/`（L3/L4）
- **批/执行**：批 `20260829-024316-f0252f`，exec `20260829-024316-3fc76c`（interpolate_custom），
  2026-08-29 13:36:52 codegen 尾段 stage halt（exit 65）

## 事实

### 1. 失败现场

deploy 尾段 smoke harness 生成期的属性契约校验拦下：

```
HarnessContractError: [PD-CONTRACT] test_cases[0].attrs['pools'] expected list[int], got list=[[1, 1]]
```

抛出点：`adapters/npu/runner.py::_validate_attrs`（按 op_spec 声明类型校验用例值）。
校验器行为正确——它忠实发现了两份上游产物对同一属性的编码分歧。

### 2. 三方对质（golden 为权威，§1.13）

| 来源 | 对 `pools` 的表达 | 语义 |
|---|---|---|
| golden.py 注解 + docstring（`tasks/level2/interpolate_custom/golden.py:25,40,43`） | `pools: list`；"第 i 项为 [ph_i, pw_i]"、`pools[i][0]` | **嵌套列表**（权威） |
| proto.yaml（`proto.yaml:27-29`） | `type: int[][]` | 嵌套列表 |
| requirement 阶段 op_spec（exec state 存档） | `type: list[int]` + description 自创"扁平编码：长度必须为偶数，相邻两项为一个 [ph_i, pw_i] 对" | 被迫压平 |
| test_design 阶段用例（state.test_cases） | `[[1,1]]`、`[[2,2]]`、`[[1,1],[2,2]]` 等 | 嵌套（忠实 golden） |

coder 生成的 C++ 全链与压平的 op_spec 自洽（OpDef `ListInt()`、plugin
`CheckAndParsePools` 偶数校验、ACLNN `aclIntArray`）——与用例/golden 的嵌套形态对立。
即使 smoke 放过，run_tests 喂 golden 时同样会炸。

### 3. 根因：类型系统表达力缺口（非 LLM 偷懒、非校验器误判）

- `domain/operator.py::CANON_ATTR_CHECKERS`（4394ca38，2026-08-06 阶段 A v2 建立起）
  仅支持 `int/float/str/bool/list[int]/list[float]`——**无嵌套列表类型，从未支持过**。
- 实证：即使 requirement 忠实声明 `int[][]`（未识别标签原样透传），fallback 检查
  "list elements must be scalar" 同样拒绝嵌套值——**正确声明在构造上不可能**，
  压平是 requirement LLM 为塞进表达力边界的合理化挣扎（其 description 抄录了 golden
  原文，说明信息在手、上报通道不在）。
- 触发条件：interpolate_custom 任务文件 2026-08-29 10:43（cann-bench 批临时提交
  `103f6cb`）**首次进入语料**——此前所有批任务参数中从未出现嵌套列表属性。

### 4. 语料普查（2026-08-29，全部 proto.yaml + golden 注解）

- 标签共 ~50 种写法，含既有枚举表盖不住的：`List[bool]`（表中无 `list[bool]` 行）、
  定长 `int[2]/int[3]/bool[3]/int64[5]`（~45 例）、联合 `int | int[4]`（~5 例，F.pad 式
  "单值或逐维"惯例）、嵌套 `int[][]`（1 例）、可空 `int?/List[int] | None`（~15 例）、
  语义别名 `Scalar/SymInt/ScalarType`、`tuple[int,int,int]`（1 例）。
- golden 注解容器类仅裸 `tuple` 1 例；属性值无 dict 形态（cases.yaml 抽查）。

### 5. 分歧为何 3 小时后才可观测（10:50 落盘 → 13:36 拦下）

- requirement 期：现有自检只做标签拼写归一（`list[int]` 合法即过）；golden 注解为裸
  `list`，机器比对注解区分不出嵌套性——语义真值只在 docstring/函数体，仅 LLM 阅读
  可获取。**无暴露面，非有信号被忽略**（全程零 WARN）。
- test_design 期：无"用例按 op_spec 契约自检"点位——用例符合契约是 test_design 自身
  产物的验收标准，该自检缺失（非越界查上游）。
- 构造上 op_spec 与 test_cases 的第一个联合消费点 = codegen 尾段 smoke harness 生成
  （`_build_test_harness` 途中 `_validate_attrs`）——止损点被构造性排到最后。
- 沉没成本：~2h46m 设计+编码+编译建于坏前提；修复须从 requirement 重跑整链
  （resume 从 codegen 续走不清——存档 state 的 op_spec 已错）。

### 6. 业界对照（判断"压平"技术形态的合法性）

- PyTorch `F.pad`：schema 即扁平 `int[]` + 文档配对约定 + 运行时校验——**扁平+步长
  约定是业界标准形态**（内层定长时结构无损）。
- `torch.repeat_interleave(repeats: Tensor)` / `roi_align(rois)`：变长数据张量化，
  组织信息进 shape。
- CANN：OpDef IR 层有 `ListListInt`（`OpAttrDef::ListListInt(std::vector<std::vector<int64_t>>)`，
  知识库 `api_reference_docs/Utils_API/原型注册与管理/OpAttrDef/OpAttrDef.md:36`）；
  但 ACLNN L2 运行时边界仅 `aclIntArray` 扁平。
- torch.ops schema 文法不支持嵌套列表（按文法知识成立；**实施期以
  `_jit_parse_schema('int[][]')` 实证**，本机会话无 torch 未验）。

### 7. 结论性事实

本轮真正错的不是"压平"这个 wire 形态（业界标准），而是**规格书把配对约定藏进散文
冒充类型**、且与用例/golden 三方脱钩；错位的构造根源是类型系统表达力缺口逼出的
静默合理化通道。
