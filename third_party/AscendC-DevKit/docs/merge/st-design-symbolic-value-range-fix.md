# 修复说明 — st-design 符号值域流入用例(A3 批量精度全挂根修)

- **日期**:2026-10-12
- **提交**:`79a8e979`(fix(st-design): 符号值域三层诚实闸口 + 转换端逐输入挂载)
- **关联**:评估报告 P12(`post-merge-assessment.md` §6)· 四层文档(`docs/plan/st-design-symbolic-value-range/`)· 台账 M5 后续追记
- **定位**:本文是面向阅读的修复说明(改了什么、为什么这么改、怎么验证的);决策与实施细节的产权在四层文档,本文只引用。

---

## 1. 一句话结论

int64 类别下标(targets)的值域上界在测试设计产物里写的是**符号表达式 `C-1`**,整条生成链没有任何环节能实例化它,也没有任何环节拦截它——符号原样流进用例,消费端读不到合法值域就回退 `[-1,1]`,给 int64 targets 生成了 -1,109 条 devkit 用例在 cross_entropy 处全体非法。修法不是"容忍符号"也不是"猜出 C 是什么",而是:**声明候选一律数值化;形状依赖的值域唯一合法表达是形状来源的 calculate 约束;符号敢出现就在生成端指名报错,并告诉作者怎么改。**

## 2. 事故回顾:五跳根因链

事故行(run `20261010-075905-02c9f4`,原样):

```
testcase:    aclnnMseLossCrossEntropyLoss_L0_001
stc_inputs:  [(1,2,3,1,1,1,1,8,), (1,3,1,1,1,1,8,), (1,2,3,1,1,1,1,8,)]
dtypes:      ('bfloat16', 'int64', 'bfloat16')      ← 第二个输入是 int64 targets
input_data_ranges: ((0,0,),(0,C-1,),(0,0,),)         ← (0, C-1) 上界是符号
```

| 跳 | 环节 | 发生了什么 |
|---|---|---|
| ① 声明 | `design/04_测试因子.yaml` | `targets.value_range_int64: [[0, "C-1"]]`——符号直接写成声明候选。`C = logits.shape[1]` 只存在于 `requirement.json` 的 prose,全链无机器可执行定义 |
| ② 求解 | `generate_factor_values.py` | 三个读取口(`expand_value_range_for_dtype` 的 dtype 扩展、`get_factor_domain` 的无约束兜底、`_declared_value_ranges` 的覆盖补齐)把候选**原样**装进组合/结果,零数值校验。附:`IMPLICIT-RANGE-targets` 机械约束 target 写的是 `targets.value_range`,与 per-dtype 因子名精确匹配不中,在真实链路里是死约束 |
| ③ 渲染 | `generate_test_cases.py` | `_format_number` 对不认识的字符串原样 `str(x)`,`(0, C-1)` 照抄进用例 CSV |
| ④ 装箱 | `csv_to_testcases.py` | 历史实现把 ranges 原始字符串塞进 case 级 `generator_params.ranges`——**全仓零消费者**(死字段) |
| ⑤ 运行 | harness | 只读 per-input `value_range`(读不到)→ 回退 `[-1,1]` → int64 targets 采样出 -1 → `IndexError` × 109 |

**为什么现在才炸**:缺陷双端同源——950 侧 runner/harness 同样没有 ranges 处理,但 A5 的算子没有受限整数域,`[-1,1]` 回退对 float 无害,所以 A5 一直绿。合并的 #15 融合裁决(用户拍板"A3 沿用")让 st-design 对外部用例也跑 LLM 因子设计,109 条 devkit 用例**首次进入 A3 test set**(base 上这条路径是 NoOp skip)。合并改变的是**触发面**,不是引入缺陷——但既然 A3 上要跑,就得在 A3 上修(用户裁决"改 a3 通路")。

## 3. 先钉死语义(修复的前提)

对 ranges 单元格里的三种形态逐一看设计产物取证:

| 形态 | 权威语义 | 证据 | 处置 |
|---|---|---|---|
| `(0, 0)` | **字面区间**——候选列表里被选中的"全零输入"边界因子 | `04_测试因子.yaml` 候选表显式列有 `[0, 0]` | 忠实挂载,**不是**空占位/无约束(最早假设它是占位,取证后推翻——丢掉会静默丢失边界覆盖) |
| `'inf' / '-inf' / 'nan' / '+0' / '-0'` | 特殊值字面量 | 真实合并 CSV 52 行含此形态(带引号,可解析) | 转字符串数值后挂载 |
| `C-1` | **未实例化表达式** | `C = logits.shape[1]` 仅在 prose | 生成端硬报错 + 补救配方;唯一合法表达是约束 |

## 4. 改动总览

```
.claude/skills/ascendc-st-design/
├── SKILL.md                          ← 作者契约(§2.1 新增一段)
└── scripts/
    ├── utils.py                      ← 共享单点:+3 个校验函数
    ├── generate_factor_values.py     ← 求解端:三读取口校验 + 异常防吞
    ├── generate_test_cases.py        ← 渲染端:兜底校验
    └── generate_implicit_constraints.py ← 符号候选不产机械假约束
src/ascendc_devkit/adapters/testdesign/
└── csv_to_testcases.py               ← 转换端:逐输入挂载 + 删死字段
```

设计原则:同一个行为("符号边界不许过")在**三个时机**各设一道闸,但**判定逻辑只有一个实现**(§1.15 单点):

- **生成端**是根治——错误在最早、最可诊断的位置暴露,报错信息直接给配方;
- **渲染端**是兜底——未来任何人新增第四条承载路径,漏网符号在这里被拦;
- **转换端**是挂载——数值形式的值域第一次变成消费者真正读得到的 per-input 事实。

## 5. 逐文件细节

### 5.1 `utils.py` — 判定与校验的唯一实现

```python
def is_numeric_range_bound(value) -> bool:
    # 合法边界 = int/float,或可 float() 解析的字符串(inf/-inf/nan/+0/-0/1e3)。
    # bool 显式排除(True 是 int 子类但当边界无意义)。
    # 其余——"C-1"、"batch"、None、嵌套结构——一律不可执行。

def validate_numeric_value_range_candidates(candidates, origin: str) -> None:
    # 候选对 [[lo,hi], ...] 逐对校验,含不可执行边界 → ValueError:
    #   值域候选 [0, 'C-1'](因子 targets.value_range_int64)含不可实例化的
    #   符号边界 'C-1'。符号值域不能作为声明候选:消费端无法在渲染期实例化
    #   它。请在约束定义中为该参数声明形状来源的 calculate 约束(sources 指向
    #   具体 shape 类因子,expression 计算出数值 [lo, hi],如 expression:
    #   "[0, sources[0][1] - 1]"),或将候选改为数值。
    # —— 报错即配方,作者照着改就能通(§2.9 就地自检闭环)。

def validate_rendered_value_ranges(input_ranges, testcase_name) -> None:
    # 渲染期兜底:深度优先扫出所有 [lo,hi] 对(兼容 TensorList 嵌套
    # ((lo,hi),...) 与缺省可选的 None 占位),含符号 → 指名用例报错。
```

### 5.2 `generate_factor_values.py` — 求解端三读取口 + 异常口

声明候选进入组合只有三条路,现在**每条路读取即校验**:

| 读取口 | 谁在用 | 改动 |
|---|---|---|
| `get_value_range_for_dtype` | dtype 扩展(`expand_value_range_for_dtype`)、机械约束 `derive_value_range_from_dtype` | 返回前 `validate_numeric_value_range_candidates` |
| `get_factor_domain` | 无约束因子的候选兜底(`derive_non_shape_factors`) | `value_range*` 属性分支返回前校验 |
| `_declared_value_ranges` | 覆盖补齐(`complete_value_range_coverage`,会把每个声明候选**强制注入**结果) | 声明读取时校验 |

外加一处异常口修复——原来的裸 `except` 会把诚实错误吞成 None:

```python
try:
    ...
except ValueError:
    raise   # 新增:诚实校验错误(如符号值域)不许被兜底吞掉
except:
    return None   # 保留:求值失败的既有兜底语义
```

### 5.3 `generate_test_cases.py` — 渲染端兜底

```python
def _build_ttk_case_data(case, data):
    # 渲染期兜底:任何生产端漏网的符号值域边界在此拒绝渲染(指名用例)。
    validate_rendered_value_ranges(data.input_ranges, case.get('testcase_name', ''))
    ...
```

### 5.4 `generate_implicit_constraints.py` — 拆掉假承诺

原 `IMPLICIT-RANGE-*` 机械约束声称"按 dtype 选值即可",候选含符号时这话不成立。现在三个 value_range 消费检查(`_check_value_range_from_dtype` / `_check_value_from_value_range` / `_check_array_value_from_range`)遇到符号候选**不生成机械约束**,改为打印警告 + 手写约束配方(见 §6),让设计期就暴露问题,而不是拖到求解期。

### 5.5 `SKILL.md` — 作者契约(§2.1 value_range 规范)

新增一段:边界必须可执行数值(`inf/-inf/nan/+0/-0` 合法);依赖 shape 的值域**禁止写成符号候选**,给出唯一的表达模板:

```yaml
- id: "RANGE-<param>"
  type: calculate
  sources: [<提供维度语义的参数>.shape]
  target: "<param>.value_range"
  expression: "[0, sources[0][1] - 1]"
```

`expression` 必须算出数值 `[lo, hi]`(`sources` 在作用域内可直接引用);与 shape 无关的值域直接写数值,无需约束。

### 5.6 `csv_to_testcases.py` — 转换端单点挂载(消费侧终于能读到了)

- **解析**:`input_data_ranges` 经 `literal_eval` 解析 + `_normalize_range_slots` 归一——空→不挂载;单输入行的扁平对→包装;数值对→字面保留(含 `[0,0]`);`'inf'/'nan'` 字符串→float;符号串→`ValueError` 指名。未加引号的符号(`(0,C-1,)`)在解析期就报错。
- **挂载**:`_flat_inputs` / `_build_inputs` 把每个参数自己的值域挂到对应输入的 `value_range`,与 cann_bench loader 的既有挂载语义同构。长度平等性按路径各自把关:proto 路径按逻辑参数、flat 路径按张量槽、DYNAMIC(TensorList)单值域管全部成员(DYNAMIC 分支里 fixed 参数的挂载是本轮补的遗——原实现只有 DYNAMIC 分支挂了,fixed 参数会漏)。
- **删死字段**:`generator_params.ranges`(全仓零消费者)整体移除,`generator_params=None`(§2.5 唯一通路/§1.4 不留兼容)。

## 6. 补救通路(作者视角,已端到端实测)

以事故算子为例,正确写法是把符号从声明里拿出来、放进约束:

```yaml
# 04_测试因子.yaml —— 删掉 targets.value_range_int64(或只留数值候选)

# 05_约束定义.yaml —— 把机械 dtype 约束换成形状来源约束:
- id: "RANGE-targets"
  type: calculate
  sources: [logits.shape]
  target: "targets.value_range"
  expression: "[0, sources[0][1] - 1]"     # C = logits.shape[1]
```

后续全自动,无需新机制:

1. `generate_solver_config.py` 的拓扑排序按 `sources` 自动把 `targets.value_range` 排到 `logits.shape` 之后(level_2)——排序能力本来就在;
2. 求解器对每个 case 用既有的 `eval` 机制实例化 → 30 case 产出 `[0,8] / [0,15] / [0,5683] …`(各 case 自己的 C);
3. 渲染/合并/转换照旧——merge 环节会把 inf/nan 归一成带引号的可解析形态。

也就是说:**表达能力没有损失(逐 case 随 shape 变的值域照样表达),只是从"写个机器看不懂的字符串"变成"写个机器能执行的公式"。**

## 7. 验证

### 7.1 UT(TDD,先红后绿)

| 套件 | 结果 | 新增覆盖 |
|---|---|---|
| `tests/ut/adapters/test_csv_to_testcases.py` | **49 passed** | +12:10 条 ranges 挂载契约(逐输入挂载、`(0,0)` 字面、inf/nan、引号/裸符号报错、None 槽、三路径长度平等)+ **2 条真实事故行回归**(事故行原样嵌入:必须报错;实例化行:必须挂载) |
| `tests/ut/skills/test_st_design_scripts.py` | **33 passed** | +10:符号闸口(判定函数、三读取口、覆盖补齐路径、异常不吞、渲染兜底、隐式约束门) |
| `tests/ut/adapters/` 全目录 | 620 passed | 回归零破坏 |
| 全量 UT(除既有挂死 application/cli) | **4527 passed / 12 skipped / 0 failed** | — |
| 非 heavy ST | 106 passed / 8 skipped / 2 failed | 2 failed 均为既有 P10(NPU 卡 0 探测失败,base 复现确认,与本改动无关) |

heavy_llm 未跑(本机无网关,P2 如实记录)——修正链在机器侧已验证到转换端,全流程批量复跑需网关环境。

### 7.2 真实产物四步链(用事故现场的真实设计文件)

| 步骤 | 输入 | 结果 |
|---|---|---|
| 事故设计直接求解 | 原版 04/05/06(含 `[[0,"C-1"]]`) | `ValueError: 值域候选 [0, 'C-1'](因子 targets.value_range_int64)含不可实例化的符号边界 'C-1'…` ✓ 指名 + 配方 |
| 修正设计求解 | 04 去符号 + 05 形状来源约束 | 30 case 的 `targets.value_range` 全数值实例化,零符号 ✓ |
| 渲染 | 03 + 04 + 07 | 12 case 的 `input_data_ranges` 全数值,inf/nan 特殊值保留 ✓ |
| 合并 + 转换 | merge → `parse_testcase_csv` | 12 case 逐输入挂载,`targets=[0,8]` 等实例值,`generator_params` 无 ranges,零符号残留 ✓ |

## 8. 遗留与决策项

| 项 | 状态 | 说明 |
|---|---|---|
| heavy_llm 批量复跑(P2) | 等环境 | 需网关机器重跑 A3 批量确认全链跑绿 |
| 整型输入缺声明值域的回退 | 另案 | 渲染端 `[-2,2]` / harness `[-1,1]` 对"完全未声明 ranges"的整型输入仍会产出 -1——同类终点、不同入口(声明缺失而非符号)。根治需拍板"受约束整型必须显式声明值域"的契约,已记录于 L4 遗留节 |
| 950 侧同源缺口 | 不回写(用户裁决) | 950 侧 runner/harness 的 ranges 缺失同源存在但未触发;若 950 后续出现同类整数域批量失败,根因即此——台账已记 |
