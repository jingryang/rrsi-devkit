---
name: ops-preinput-gen
description: 输入算子名（如 aten_abs / gelu / TopK）**或一份 golden 实现**（KernelBench 风格 class Model），生成一套算子前置输入五文件（desc.md + cases.yaml + cases.csv + proto.yaml + golden.py），供 ops-direct-invoke 直接消费、跳过自生成 spec 阶段。Use when：需要为某个算子准备/补齐前置需求输入、把一段 golden 融合实现转成前置需求文件、批量为算子清单生成需求文件、替换产线的需求生成阶段、或校验既有前置输入是否合规可跑。
argument-hint: <算子名 | golden.py 路径> [输出目录]
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch
---

# 算子前置输入生成

输入一个算子名，产出五文件算子需求前置输入。

**产物契约（不可变）**：`desc.md` + `cases.yaml` + `cases.csv` + `proto.yaml` + `golden.py`。
spec 文件名必须是 `desc.md`；cases 必须恰好 **20** 例；字段集是封闭的，不得自行扩展。
完整 schema 见 `references/format-contract.md`。

**本 skill 自包含**：格式契约、用例骨架、设计规范都在 `references/` 里，
不依赖任何外部算子库或参考目录即可运行。

## 两种输入模式

| 模式 | 输入 | Step 1 事实来源 | 特有参考 |
|---|---|---|---|
| **name-driven**（原有） | 算子名（`aten_abs` / `gelu` / `TopK`） | `resolve_semantics.py`：PyTorch 自省取权威签名 → 反推着写 golden.py | —— |
| **golden-driven**（新） | 一份 golden 实现（KernelBench 风格 `class Model`，文件名常为编号如 `0873.py`） | `resolve_golden.py`：拆解 Model → **golden 实现即语义唯一事实源**，先转写成自由函数 golden.py | `references/golden-driven.md` |

两模式**只有 Step 0/1 不同**：拿到事实包后，Step 2~6（定级分类 / 写 cases /
写 proto·desc / 派生 csv / 校验门 / 交付）完全一致。golden 模式下五文件全部对齐
「Model.forward 转写出的自由函数」。

## 为什么必须自校验

下游没有 `cases.yaml` / `desc.md` 的强 schema 校验器 —— 唯一的程序化读取是
`proto.yaml` 的 `operator.category`（作为 `{category}` 注入 prompt 上下文），其余文件都是被 LLM
当 prompt 上下文读。**畸形产物不会被拒绝，只会静默拉低成功率。**
所以 Step 5 的校验门不是可选项，是本 skill 的主要价值来源。

## 执行流程

### Step 0 — 判定输入模式

- 输入是**算子名** → name-driven，走 Step 1 的 `resolve_semantics.py`。
- 输入是**一份 golden 实现**（含 `class Model(nn.Module)`，或用户直接给了 `.py` 路径）
  → golden-driven：**先读 `references/golden-driven.md`**，用 `resolve_golden.py` 拆解，
  把 `Model.forward` 转写成可导入的自由函数即 `golden.py`（其余四文件对齐它）。

```bash
# golden-driven 的 Step 1 机械部分：
python3 ${CLAUDE_SKILL_DIR}/scripts/resolve_golden.py <golden.py>
#   有构造参数时补：--init-args num_channels=4 alpha=0.25 --input-shape 2,4,8
```

它输出 `forward_args` / `stateful`（Parameter/子模块权重的分类）/ `op_sequence` /
`tensor_inputs`（已把权重展开成一路路输入）/ `suggested_name`（按算子组合描述）/
`hints`（定级·分类初判）。**关键规约**：`__init__` 里所有 Parameter 与子模块权重
**一律提升为 golden 函数的显式张量输入**，不是烘焙常量 —— 否则下游无法用同一组随机输入
复现精度比对。子模块（BatchNorm/PReLU/Linear…）内联成对应 `F.*` 泛函（取推理语义）。
细节全在 `references/golden-driven.md`。

**golden 模式定完事实包后，直接进 Step 2**（Step 1 的 name-driven 自省不适用）。

### Step 1 — 解析算子语义（name-driven；不要靠记忆猜签名）

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/resolve_semantics.py <算子名>
#   二元算子加 --n-tensor-args 2；有既有算子库可加 --precedent-dir <路径>（可选）
```

脚本按优先级取**权威事实**并输出 JSON：

1. `torch.ops.aten.<name>.default._schema` —— ATen 权威签名（参数名/类型/默认值），
   算子原型的第一来源
2. `torch.<name>` / `torch.nn.functional.<name>` —— golden 的可调用体
3. dtype 与定义域空跑探测 —— 定 `value_range` 的依据

读 JSON 后按顺序补齐仍缺的事实：

| 缺什么 | 到哪里取 | 要求 |
|---|---|---|
| 无 aten op（如 `softsign`） | `torch.nn.functional` 层 + PyTorch 文档 | 用 python 层签名，参数名规范化（`input`→`x`） |
| 硬件/dtype 上限、NPU 侧约束 | AscendC 文档 / web | **必须在 desc.md 注明来源**，不要编造数字 |

> CPU 探测出的 dtype 支持面 ≠ NPU 声明面。浮点 elementwise 算子一律声明
> `{float16, float32, bfloat16}`，不要因 CPU 探不通就缩小声明。

### Step 2 — 定级与分类

- `difficulty` 与输出目录层级**必须一致**：`level1↔L1`、`level2↔L2`、`level3↔L3`、`level4↔L4`。
  单输入逐元素 → L1；含 reduce/normalize/gather 等一层结构 → L2；
  contraction / 多算子融合 / 排序选择 → L3；
  **注意力融合 / `softmax(Q·Kᵀ·scale)·V` 家族（mha / gqa / mla / sparse_flash_attention /
  mla_prolog）→ L4**，先读 `references/l4-fa-design.md`。
- `category` **只能取 13 类之一**（清单见 `references/format-contract.md` §4），
  别造新词 —— 它作为上下文注入下游 prompt，写错会让下游 LLM 拿到错误的算子归类、静默拉低质量。
  （L4 FA 家族一律 `FusedComposite`。）

### Step 3 — 写 cases.yaml（唯一事实来源）

**先读 `references/case-design.md`；多输入算子（L2/L3）必须再读 `references/l2-l3-design.md`；
L4 FA 注意力家族必须再读 `references/l4-fa-design.md`。**

20 例不是自由发挥的组合矩阵。单输入 elementwise 算子**直接套用 case-design.md §2
的骨架表**（20 行 shape/dtype/value_range 已固化），只按语义改必须改的槽位：

- 值域必须落在算子定义域内（`sqrt`/`log` 改正区间，`asin`/`acos` 收进 [-1,1]）
- 槽位 10~14 是五个特殊值（fp16 边界 / fp32 边界 / inf / nan / 零值），保留
- dtype 序列换成 proto 实际声明集；整型算子的 `value_range` 用各自满量程
- 每个 attr 至少 2 种取值，且与 dtype/规模正交
- **不要写 `baseline_kernels`** —— 那是下游 profiling 回填的度量，生成侧无法测量

**L2/L3 多输入算子额外要求**（详见 `references/l2-l3-design.md`）：

- `input_shape` 顺序严格同 `proto.inputs`；**shape 间耦合必须成立**
  （如 conv 的 `x[1]==filter[1]`(C_in)、`filter[0]==bias[0]`(C_out)）
- 值域**按输入角色**分配：权重与数据同量级、bias/scale 约为其 1/10、
  索引取 `[0, 被索引维-1]`、概率类固定 `[0,1]`
- 覆盖矩阵多两维：**耦合维取不同值**（别所有例都 `C_out==C_in`）、
  **可选输入的在场/缺省组合**；保留空组 / 单元素 / 无效索引等边界用例
- 单例总元素数控制在 ~16M 以内
- 可选输入缺省时用 `null` 三列同位占位

**L4 FA 注意力家族额外要求**（详见 `references/l4-fa-design.md`）：

- 20 例**按计算场景铺**（prefill / decode / cross / MTP / causal），不套 L1 的
  shape/dtype/对齐/特殊值骨架；维度取真实 head dim（64/128/256）
- 场景覆盖 ≥3 类、head dim ≥2 档（**G10-scenario** 会校验）；dtype 只有 `{float16, bfloat16}`
  且 Q/K/V 每例三列相同
- scaleValue 覆盖 `-1.0`（auto=1/√D）与显式 `≈1/√D`；is_causal 两值都有；保留 1 例 `[0,0]` 全零退化
- `is_causal=True` 要求 `S ≤ S_kv`；**golden.py 必须内联全 mask 行 NaN 保护**（desc §5 可省略并加差异说明）
- 语义等价不变量（MLA `v==k_nope`、sparse `value==key[...:Dv]`、sparse 索引互异）**只能靠 desc.md 文字兜底**
- note 删除 `| baseline_kernels: ...` 后缀

### Step 4 — 写 proto.yaml / golden.py / desc.md，然后派生 cases.csv

三处接口必须**逐字一致**：`desc.md` §3 算子原型（去掉 `torch.ops.npu.` 前缀）
== `proto.operator.schema` == `golden.py` 的 `def` 名与参数序列。

**调用约定用本仓真实的直调形态**（详见 `references/format-contract.md` §5.3）：

- §3 算子原型：`torch.ops.npu.<op>(Tensor x, ...) -> Tensor y`
- §6 调用示例（**仅 L1/L2/L3；L4 FA 家族不写 §6**）：`import torch_npu` 后直接
  `torch.ops.npu.<op>(x.npu())`，末尾 `torch.npu.synchronize()`。
  **不写** `torch.ops.load_library("build/lib<op>_ops.so")` 及其加载注释，**也不写**
  「> 算子编译为…注册到 npu…接口契约」的收尾 blockquote —— 这些是接入背景说明，
  不属于前置输入内容（G16 会拦）。
- `proto.yaml` 的 `schema:` 保持**裸签名无前缀**（等于 `TORCH_LIBRARY` 的 `m.def()` 字符串）
- **禁止 `cann_bench.<op>` / `import cann_bench`** —— 那是另一个基准仓的包，本仓没有

`desc.md` 节骨架见 `references/format-contract.md` §5（L1/L2/L3 六节；**L4 FA 家族五节，无 §6**）。
**§3「支持范围」表的两列分工是最容易做错的地方**：

- **范围** 列 = 声明支持的上界，由语义合法性 + 硬件/dtype 上限推出，与 cases 无关
- **备注** 列 = cases 实测覆盖面，**必须从 cases.yaml 反算**，写成 `cases.csv 实测 A ~ B`
- 自洽律：`备注(实测) ⊆ 范围(声明)`，且备注数字等于 cases 真实极值

**L2/L3 的 desc.md 比 cases 本身更关键** —— 下游造数时和校验器面临同样的困难，
凡是没写进 desc.md 的跨输入约束，下游只能靠猜。所以必须：

- 先定义**符号维度**（`N` / `C_in` / `K` / `E`），shape 用符号表达
- 支持范围表的**行名是符号维度**，不是「x 各维大小」
- 表后加一行 `约束：…` 集中声明跨输入关系（≥3 输入必须有）
- 每条语义不变量（计数和 / 整除 / 单调 / 索引合法 / dtype 联动）都要落到文字
- 会改变输入输出形态的 attr，单开 `### <attr> 说明` 小节配表

cases.csv **一律机械派生，禁止手写**：

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/gen_cases_csv.py <op_dir>
```

### Step 5 — 校验门（全绿才算完成）

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/validate_preinput.py --run-golden <op_dir>
```

16 道门：G1 文件齐备 / G2 cases schema / G3 用例内自洽 / G4 proto schema /
G5 proto↔cases 交叉 / G6 desc 结构 / G7 三处接口一致 / G8 支持范围自洽 /
G9 值域与 dtype 范围 / G10 用例设计覆盖 / G11 CSV==YAML /
G12 golden 可导入 / G13 **golden 20 例实跑复算** /
**G14 索引值域可解释 / G15 跨输入约束已文档化**（L2/L3/L4）/
**G16 调用约定为 torch.ops.npu 直调**。

- **FAIL 必须修到 0**。不要改校验器去迁就产物。
- WARN 需逐条判断：确属算子语义所致（如 conv 只有 4D）可保留并在交付说明里写明理由。
- **`G13-unsynth` 是 L2/L3/L4 的核心信号**：它列出的每条「通用造数满足不了的约束」，
  都是下游同样会撞上的坑。看到它必须回 `desc.md` 确认该约束已写清楚，不要当噪音略过。
- **L4 FA 家族**：G10 走 **G10-scenario**（场景 slug + head dim 覆盖），G8 支持范围
  自动放行 L1 的「各维大小/实测 A~B」句式 —— 这两条已按 `difficulty==L4` 内建，属正常，非缺陷。
  G13 对大 head dim 用例会 skip（`mla_prolog` 可能 20/20 全 skip），交付报告须点名实跑/skip 例数。

### Step 6 — 交付

报告：输出路径、`--run-golden` 结果、残留 WARN 及理由、
以及**语义事实的来源**（aten 自省 / F 层 / 文档 URL）。

## 输出位置

默认写到下游会读的算子目录：`operators/<op_snake_case>/`（五文件平铺，无子目录）。
调用方指定了输出目录则以其为准。

按难度分层归档时用 `<root>/level{1,2,3,4}/<op>/` —— `difficulty` 必须与层级一致（G4 会校验）。
L4 FA 注意力家族归档在 `level4/`。

## 参考

- `references/format-contract.md` —— 五文件硬 schema 与调用约定
- `references/case-design.md` —— 20-case 设计规则 + L1 骨架表 + 常见错误清单
- `references/l2-l3-design.md` —— **L2/L3 多输入必读**：耦合模式库、角色化值域、语义不变量
- `references/l4-fa-design.md` —— **L4 FA 注意力家族必读**：符号维度、场景覆盖矩阵、
  is_causal NaN 保护、语义等价不变量、G13 skip 现实
- `references/golden-driven.md` —— **golden 实现输入必读**：Model → 五文件转换、子模块→泛函速查、stateful→输入
- `references/downstream-integration.md` —— 下游消费链路与接入方式
- `examples/` —— 通过全部门禁的完整样例（L1/L2/L3/L4），覆盖多输出 / 可选输入
  `null` 占位 / `is_list` / bit-exact / 索引联动 / 多输入耦合 / **注意力场景（mha/gqa）** 等全部结构模式。
  **拿不准结构时先查 `examples/README.md` 的「按你缺哪种结构」查表**，照着抄。

## 边界

- 只产出前置输入五文件，**不写 kernel、不碰 DESIGN.md/PLAN.md**（那是下游的事）。
- 不编造硬件数字与 profiling 数据；取不到就注明来源与不确定性。
- 目标目录已存在时先读再决定：若已合规，报告并停止，不要覆盖。
