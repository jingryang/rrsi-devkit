---
name: ops-requirement-from-source
description: 从算子源码目录 PATH 端到端生成标准算子需求包（golden.py、proto.yaml、cases.yaml、cases.csv、desc.md、design.md）。自动识别 PATH/docs（按算子名匹配接口文档版本）、PATH/op_kernel、PATH/op_host（tiling）、PATH/op_api（缺失时查 op_host）与 PATH/tests（golden 与用例），提取并规范化 golden，基于 tiling 模板和 tests/st 设计固定 20 个不重复、全覆盖用例，再交给 TTK 子代理做 aclnn 适配与精度测试，按结果回流修正 golden 与用例，最后生成 desc.md 与 design.md。支持“芯片种类”参数（默认 A5，可选 A3 或 A3,A5）约束分析、实现、配置、用例和文档的范围。
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, AskUserQuestion, Agent
---

# 算子源码 → 标准需求包

本技能把“给定算子源码目录，产出标准算子需求文件夹”的流程固定下来，包含源码布局自动发现、golden 提取、固定 20 个用例、TTK 适配与精度回流四个环节。TTK 环节通过子代理调用外部 ops-test-kit 的 `ttk-aclnn-adapt` 技能，交接契约见 `references/ttk-integration.md`。

## 一、输入与优先级

| 参数 | 必需 | 说明 |
|---|---|---|
| `PATH` | 是 | 算子源码根目录，例如 `.../ops-nn/norm/deep_norm`。`PATH` 最后一个 `base_dir` 即算子名 `ops_snake` |
| `芯片种类` | 否 | 约束本次分析与产物的芯片范围；默认 **A5**。取值 `A5`、`A3` 或 `A3,A5`，也接受 `950`/`3510`/`910b`/`910c` 等别名 |
| `输出路径` | 否 | 需求文件夹的父目录；默认当前工作目录，最终文件夹为 `<输出路径>/<ops_snake>/` |
| `TTK_WORKDIR` | 否 | TTK 适配与测试的产物目录；默认 `<需求文件夹>/ttk/`。目录约定见 `references/ttk-integration.md` |
| `TTK_REPO` | 否 | ops-test-kit 仓库根目录（`python3 -m ttk` 必须在此目录执行）。默认取环境变量 `OPS_TEST_KIT_ROOT`，否则从 `PATH` 逐级向上查找含 `ttk/__init__.py` 的同级 `ops-test-kit` 目录；找不到时询问用户 |
| 用户自定义信息 | 否 | 任意显式覆盖，例如 `golden_path`、`doc_path`、`cases_path`、`tests_path`、`kernel_path`、`host_path`、`api_path`，以及 dtype/布局/属性等语义约束 |

优先级固定为：

```text
用户显式输入（含芯片种类） > PATH 源码中发现 > 接口文档/golden 推断 > AI 需求决策
```

芯片种类是硬性范围约束，不是参考信息。未指定时默认 A5；用户显式指定时以用户为准。选定后只允许分析、引用和产出该芯片范围内的实现、文档、配置与用例，其他芯片一律标记为范围外，不得混入需求、golden、cases 或 design 的结论。

| 芯片种类 | 产品/SoC | 默认 arch 目录 | 默认 config 目录 |
|---|---|---|---|
| `A5`（默认） | Ascend 950（950PR/950DT）、3510 | `arch35` | `ascend950`、`ascend350` |
| `A3` | Atlas A3 910B/910C | `arch22` | `ascend910b`、`ascend910_93` |

- 同时选择 `A3,A5` 时，两条路径分别分析并在 `design.md` 中分节说明；用例需标注各自适用芯片。
- 所选芯片在源码中没有任何实现或配置时，停止并报告缺口，不得自动改用另一颗芯片。
- `ascend960*`、`ascend310p`、`kirin*` 等未列入所选范围的目录与分支一律视为范围外。


用户提供的任一路径或语义信息直接覆盖默认发现结果。每次覆盖、来源冲突和最终取舍都写入 `design.md`，不得静默采用低优先级来源。

开始前验证：

1. `PATH` 存在且为目录；`ops_snake = Path(PATH).resolve().name`，必须为 snake_case。
2. 至少存在以下之一：`docs/`、`op_kernel/`、`op_host/`、`tests/`；全部缺失时停止并询问用户。
3. 确认 `芯片种类`：未指定时取默认 `A5`；再检查所选芯片在 `op_host/*_def.cpp`、`op_kernel/`、`op_host/config/` 中是否有对应配置。缺失时停止并报告，不得静默换芯片。
4. 不向 `PATH` 内写入任何文件；需求文件夹只创建在输出路径下。
5. 输出文件夹已存在时先读取内容，保留用户修改；无法安全合并时询问用户，不直接覆盖。

## 二、源码布局与文档版本选择

标准布局与回退顺序：

| 内容 | 默认位置 | 回退/说明 |
|---|---|---|
| 接口文档 | `PATH/docs` | 递归查找；可能有多个 API/版本，按算子名选择 |
| kernel | `PATH/op_kernel` | 含 `arch22`、`arch35` 等芯片子目录与公共头文件 |
| tiling / host | `PATH/op_host` | `<op>_tiling*.cpp/h`、`<op>_def.cpp`、`<op>_infershape*`、`config/` |
| aclnn 接口 | `PATH/op_api` | 不存在时依次查 `PATH/op_host/op_api`、`PATH/op_host` 下的 `aclnn_*.h/cpp` |
| 测试与 golden | `PATH/tests` | golden 常见于 `tests/assets/golden.py`；用例常见于 `tests/st/**`（ttk CSV、atk JSON、executor py） |

文档版本选择规则（完整判定表见 `references/source-layout.md`）：

1. 由 `ops_snake` 推导 `ops_pascal`，并用 `op_host/<op>_def.cpp` 的 `OpDef` 类名/`OP_ADD(...)` 校验；两者不一致时以源码注册名为准，并在 `design.md` 记录。
2. 候选文档按文件名归一化后匹配 `ops_pascal`：先精确匹配（含 `V2`/`V3` 等版本后缀），再忽略版本后缀匹配，最后用 `aclnn_*.h` 中的接口名、op def 的 `.Version(N)`、`tests/st` 的 executor 反向确认。
3. 优先级：`aclnn<Op>.md` > 含多个 aclnn 入口的组合文档（如 `aclnnX&aclnnInplaceX.md`）> `ascendir<Op>.md` > `torchapi_*.md`；排除 `*FusionPass*.md`、`*Pass.md`、README 等非接口文档。
4. 目录名版本与文档版本不一致时（例如目录 `quant_batch_matmul_v4` 对应 `aclnnQuantMatmulV5.md`），以 `op_api` 头文件与 `tests/st`/`examples` 实际调用的接口为准，并记录映射关系。
5. 仍有歧义时一次性询问用户；不得把两个版本的参数表拼接使用。

产出前把最终采用的文档路径、被排除候选及理由写入 `design.md`。

## 三、执行流程

### 第一步：清点源码与接口基线

读取并记录：

- 接口文档：功能、公式、输入输出、属性默认值/取值范围、dtype 组合、布局、shape 推导、精度要求、支持芯片。
- `op_host/<op>_def.cpp`：输入/输出顺序、必选/可选、属性、dtype、`.Version(N)`。
- `op_api`（或 `op_host` 下）的 `aclnnXxxGetWorkspaceSize`：参数顺序、张量/标量/属性槽位、输出张量槽位。
- `op_host` tiling：tiling key/模板分支、阈值常量、分核与分块公式。
- `op_kernel`：模板类/函数、tiling key 分发、各分支对应的计算路径。
- `tests`：golden 实现、`tests/st` 用例矩阵、executor 中的 golden 与调用签名。

只分析与所选 `芯片种类` 对应的实现：A5 读 `op_kernel/arch35`、`op_host/config/ascend950|ascend350` 与文档 A5 支持行；A3 读 `op_kernel/arch22`、`op_host/config/ascend910b|ascend910_93` 与文档 A3 支持行。其他芯片分支、配置、文档行和测试条目一律记录为范围外，不进入任何产物。可以用 tiling key 辅助分析，但最终需求与用例只使用外部可观察条件表达。

### 第二步：提取并规范化 golden.py

golden 来源优先级：

```text
用户指定 golden_path > tests/assets/golden.py > tests/**/golden*.py
> tests/st/**/executor_*.py 中的 compute_golden > 由文档公式与 kernel 推导
```

处理要求（详见 `references/golden-extraction.md`）：

1. 源码 golden 常见形态包括 `__golden__ = {"kernel": ..., "aclnn": ...}` 注册表、numpy + `ml_dtypes`、`**kwargs` 测试框架参数、`compute_golden` 辅助函数。只提取真实计算语义，去掉测试框架钩子。
2. 若 golden 委托兄弟算子（相对路径 import/读取），必须解析并内联实际计算，产出物不得依赖源码仓库路径。
3. 改写成独立 torch golden：
   - 唯一公开模块级函数名为 `ops_snake`，其余辅助函数以下划线开头或写成嵌套函数；
   - 入口不得有 `self` 形参，按仓库约定改名为 `params` 或语义等价名称；
   - 为张量参数补 `torch.Tensor` / `Optional[torch.Tensor]` / `List[torch.Tensor]` 标注；
   - 多输出顺序严格按 op def / aclnn 输出槽位，返回 list 或 tuple；
   - 保持源码的升精度计算、输出 dtype 转换和特殊值语义（NaN/Inf/±0、空张量、广播、边界）。
4. 无来源冲突时只改命名与结构，不改数值逻辑。若按需求决策调整语义，必须在 `design.md` 记录原行为、最终规则、依据和影响。
5. golden 必须自包含、确定性、可在 CPU 上运行；不 import `torch_npu`，不读源码树文件。
6. 用 2~3 组代表性 shape/dtype 在 CPU 上运行，并与源码 golden 做数值对照；记录对照方式、最大误差和未覆盖情形。多输出分别对照。无法运行或无法对照时明确标记，不得声称已验证。

### 第三步：生成 cases.yaml 与 cases.csv

固定生成 **20 个**合法功能用例，不重复、尽量覆盖全部可由外部输入触发的实现分支。

用例来源与设计顺序：

1. `tests/st` 已有用例：读取 `arch35/*.csv`（ttk 格式）、`aclnn*/atk_*.json`、`executor_*.py`，提取 shape、dtype、属性、value_range、布局/视图构造方式，作为种子池。
2. tiling 模板：从 `op_host` 提取阈值与分支条件（dtype、规约维长度、行数、对齐、UB 容量、核数、尾块、full-load/partial-load 等），把内部条件翻译成外部可观察的 shape/dtype/属性组合。每个关键阈值至少取 `T-1`、`T`、`T+1` 中合法且有代表性的点。
3. 文档约束：dtype 组合、维度范围、属性取值、布局限制、输出 shape 规则。

固定规则（详见 `references/case-design.md`）：

1. case 总数必须为 20；`cases.yaml` 为主数据，`cases.csv` 由同一批数据派生，不独立维护。
2. 不重复：`(input_shape, dtype, attrs, value_range)` 不得完全一致；只改 `note` 或无关参数的用例必须合并。
3. 覆盖：dtype 组合、模板/分支、shape 规模与边界、对齐/尾块、维度数、属性取值、布局/非连续视图、多输出 dtype 差异都要在 20 个名额内取舍；无法覆盖的分支在 `design.md` 明确记录，不得伪称全覆盖。
4. 只生成有效输入域内的正常用例，不生成非法参数、非法 shape/dtype/layout、预期报错等异常用例。合法边界和特殊值只在需求契约明确要求时纳入。
5. 用例名称、note、desc 中不得出现 tiling key、模板编号、源码函数名等内部标识；用外部条件描述覆盖目的。
6. 期望值必须由最终 golden 计算，不得手工猜测；输出 shape/dtype 由 `proto.yaml` 的 outputs 与 shape 规则推导，不写入 note。
7. 数据构造遵循仓库约定：默认 `generator=uniform`，seed 固定为 `case_id`，使用有限区间 `[lo, hi]`；特殊值只允许用显式值列表表达。布局默认 `ND`、连续视图。
8. 列格式固定为 `operator,case_id,input_shape,dtype,attrs,value_range,note`；`input_shape`/`dtype`/`attrs`/`value_range` 用 JSON，`note` 为一句话自然语言描述，只概括该用例的外部可观察特征（例如“非对齐二维、非对称值域，验证 base=2 与 scale=1.5 组合”），不承载机器可读字段、不写 JSON、不写芯片种类。
9. dtype、shape、属性组合必须来自所选芯片实际支持的范围；其他芯片独有的约束不得写入用例或 note。

### 第四步：TTK 适配与精度测试（子代理执行）

本步骤把第三步的 `golden.py` 与 `cases.csv` 交给 TTK 做 aclnn 通路适配和真机精度比对。完整交接契约、命令模板与差异处理见 `references/ttk-integration.md`。

**执行前提**（任一不满足时整体跳过本步骤，在 `design.md` 记录“未执行”及原因，直接进入第五步静态路径）：

1. `TTK_REPO` 可定位，且 `cd <TTK_REPO> && python3 -m ttk info` 能识别到与所选芯片种类匹配的设备。
2. `op_api`（或 `op_host` 下）能确定唯一 `aclnnXxx` 接口名。
3. TTK skill 目录 `<TTK_REPO>/.claude/skills/ttk-aclnn-adapt/SKILL.md` 存在。

无可用设备时一律跳过，不启用 `--backend npusim`，不因设备错误反复重试。

**子代理调用**：用 `Agent`（general-purpose）启动子代理，prompt 必须包含：

```text
只使用 <TTK_REPO>/.claude/skills/ttk-aclnn-adapt/SKILL.md 及其 references/，
先完整阅读后按该 skill 的 Step 0→5 执行。
不得使用其他位置（包括本仓库 .claude/skills/）下的同名 ttk-aclnn-adapt 副本，
即使它在技能列表中已注册。
所有 python3 -m ttk 命令必须在 <TTK_REPO> 根目录执行。
OP_DIR=<PATH>
API=<aclnnXxx>
DOC_PATH=<我们选定的接口文档>
USER_GOLDEN=<需求文件夹>/golden.py
USER_CASES=<需求文件夹>/cases.csv
WORKDIR=<TTK_WORKDIR，默认 <需求文件夹>/ttk/>
CHIP=<芯片种类>
硬约束：
- 不修改 USER_GOLDEN / USER_CASES；所有产物写入 WORKDIR。
- 不臆造输出 shape/dtype、属性值、SoC 平台名；有歧义时停止并报告。
- 精度失败先证伪 golden，再考虑用例；不得静默放宽 tolerance。
- 不得并行执行多条 ttk 命令。
```

**门禁**（由子代理在自检中保证，不再逐项写进脚本）：Step 0 形参表与 `design.md` 一致；Step 1 `--validate` 通过且 20 条；Step 2 包装层注册名为 `API` 且覆盖输出槽；Step 3 冒烟无 golden 异常；Step 4 产出 `debug/result.csv`；Step 5 `pass`/`note` 已回填、FAIL 已归因。

**交接文件** `<WORKDIR>/debug/handoff.json`（最小结构）：

```json
{
  "status": "executed | skipped",
  "skip_reason": "",
  "failures": [
    {"case_id": 12, "attribution": "false_failure", "detail": "近零抵消点"}
  ],
  "leftovers": []
}
```

`failures` 只登记 FAIL 用例；`attribution` 取 `golden` / `case` / `false_failure` / `operator_defect` / `environment`，`leftovers` 记录未解决项与 TTK 无法表达的用例构造。

### 第五步：根据 TTK 产物改进 golden、cases.yaml、cases.csv

读取 `<TTK_WORKDIR>/debug/handoff.json` 与 `$WORKDIR/cases.csv`（查证据时再看 `debug/result.csv`、`debug/notes.json`），按归因处理：

| 归因 | 允许动作 | 禁止动作 |
|---|---|---|
| `golden`（语义/接线错） | 修需求包 `golden.py`，同步 `desc.md` 第 5 节逐字符代码块；必要时同步 `proto.yaml` | 不得把 TTK TestSpec 包装层复制进需求 golden |
| `case`（shape/dtype/attrs/value_range 违反契约） | 修 `cases.yaml`，重新派生 `cases.csv`，仍保持 20 条 | 不得增删用例凑数 |
| `false_failure`（近零抵消等） | **一律不改 golden 与用例**；在 `design.md` 覆盖表标记“豁免”，记录证据与 `debug/notes.json` 结论 | 不改 value_range、不放宽 tolerance、不删除用例 |
| `operator_defect` | 保留 FAIL；记录最小复现、失败槽与 ULP 量级 | 不得改判 PASS |
| `environment` | 记录设备/瞬时错误与复跑结果 | 不得据此改用例 |

- 需求包 `cases.csv` 始终保持七列；TTK 的 `$WORKDIR/cases.csv`（含 `pass`/`note` 列）只作为验证证据，不写回、不合并。
- golden 或用例被修正后，最多再执行两轮“第四步 → 第五步”收敛；仍不收敛的失败转为遗留事项。
- **TTK 未执行时**：只做静态一致性检查（golden 公式与文档/kernel 分支、输出 dtype/顺序、用例覆盖与去重、value_range 合理性），TTK 相关结论标记为“未执行/未验证”。
- 只有真实出现在 `result.csv` 中的 case 才能在 `design.md` 覆盖映射表升级为“已运行验证”；其余保持“静态推断”。
- 记录每次变更的原因、影响的 case_id 与遗留事项；不得删除失败用例来掩盖问题。

### 第六步：生成 proto.yaml、desc.md 与 design.md

在需求文件夹内补齐：

1. `proto.yaml`：`operator.name = ops_pascal`、`schema = ops_snake(...)`；inputs/outputs/attrs 顺序与 op def、aclnn 头文件一致；dtype 列表、默认值、约束与最终需求一致。
2. `desc.md`：外部行为文档，章节结构固定为 `1 算子简介 / 2 算子定义 / 3 接口规范 / 4 精度要求 / 5 标准 Golden 代码 / 6 额外信息`。要求：
   - 一级标题为 `# <ops_pascal> 算子 API 描述`；
   - 原型写成 `cann_bench.<ops_snake>(...)`；
   - 第 5 节 `python` 代码块必须与 `golden.py` 从第一个顶层 import/from 到文件末尾逐字符一致；
   - 第 6 节包含 `cann_bench` 调用示例和“用例执行与数据构造约定”；
   - 只写外部可观察行为，不出现 tiling key、模板名、源码路径、内部函数名。
3. `design.md`：内部设计文档，标题标注所选芯片，至少包含：
   - 芯片范围声明：本次只分析所选芯片，列出被排除的芯片/目录/分支；
   - 源码布局与文档版本选择（采用路径、排除候选、理由、aclnn 接口映射）；
   - 实现概览与主要数据流；
   - 模板设计（tiling key/分支、触发条件、计算差异，需结合实际分发逻辑）；
   - 分核设计、分块设计（阈值含义、对齐、尾块、UB 预算）；
   - 性能调优技巧（只写源码实际存在的机制与取舍）；
   - 模板与测试覆盖映射（目标芯片固定为所选芯片、内部模板/分支、源码依据、外部触发条件、case_id、验证状态：静态推断/已运行验证/未覆盖/不适用）；
   - 源码依据与需求决策（区分源码事实、推断、AI 决策、用户覆盖、TTK 状态与遗留事项）。

格式细节以 `references/artifact-formats.md` 与 `references/exp/` 为准；示例只用于对齐结构，不是目标算子的语义来源。

### 第七步：校验与交付

运行：

```bash
python3 <skill目录>/scripts/validate_artifacts.py <需求文件夹路径> --chip <A5|A3|A3,A5>
# TTK 已执行时追加：
python3 <skill目录>/scripts/validate_artifacts.py <需求文件夹路径> --chip <A5|A3|A3,A5> \
  --with-ttk [--ttk-workdir <TTK_WORKDIR>]
```

脚本检查必需文件、文件夹名、golden 唯一公开函数与 `self` 参数、desc 标题与 golden 代码块一致性、proto/schema、CSV 列顺序、YAML/CSV 一致性、case_id 唯一、**固定 20 个用例**、用例去重、`note` 为单句自然语言、`design.md` 标注所选芯片。`--with-ttk` 额外做轻量检查：`handoff.json` 可解析且 `status` 正确（`skipped` 需 `skip_reason`）、TTK `cases.csv` 行数为 20、`pass` 为三态、FAIL 用例有合法 `attribution`。TTK 内部细节以子代理的交付为准，不在此重复校验。修复所有错误后，再人工检查信息隔离和语义一致性。

最终报告必须包含：

- 需求文件夹路径与文件清单（含 `ttk/` 是否生成）；
- 本次采用的芯片种类及被排除的芯片范围；
- 算子功能摘要与最终需求决策；
- 采用的文档版本、golden 来源、用户覆盖项；
- 20 个用例的覆盖摘要、未覆盖分支及取舍理由；
- TTK 环节状态（未执行及原因 / 已执行及 PASS-FAIL 分布 / 逐归因摘要 / 是否发生回流修正）；
- 未能验证的项和原因；
- 校验脚本结果。

## 四、验收标准

- 输出文件夹结构与格式符合 `references/artifact-formats.md` 和 `references/exp/`。
- 所有源码分析、文档引用、配置、kernel/tiling 分支、用例和 design 结论都限定在所选芯片范围内。
- `cases.yaml` 恰好 20 个用例，`cases.csv` 与其逐项一致；无重复、无异常用例；每个 `note` 都是一句话描述用例特征。
- 用例覆盖来自所选芯片的 tiling 模板与 `tests/st` 分析，覆盖映射可追溯到 `design.md`。
- `golden.py` 为单公开函数、无 `self` 形参、可独立运行，语义与源码 golden/kernel 一致。
- `desc.md` 不泄露任何内部实现标识；`design.md` 中的内部标识不反向进入其他产物。
- 文档、golden、proto、cases 的参数、shape、dtype、attrs 完全一致。
- TTK 环节：有设备时已完成适配与全量跑，每个 FAIL 有归因；无设备时明确标记未执行及原因，不伪造精度结论。
- TTK 的 `pass`/`note` 只存在于 `<TTK_WORKDIR>/cases.csv`，需求包 `cases.csv` 仍为七列。
- `false_failure` 只做豁免标记，未修改用例或放宽 tolerance。
- `scripts/validate_artifacts.py --chip <芯片种类>` 通过；TTK 已执行时再加 `--with-ttk --ttk-workdir <TTK_WORKDIR>`；若环境缺少 Python 3/PyYAML，如实记录未执行。
