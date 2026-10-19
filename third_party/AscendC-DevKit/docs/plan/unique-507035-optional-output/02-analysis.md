# 02 — 方案分析（L3）：P2 可选输出算子输出数量不匹配

> 本工作：`docs/plan/unique-507035-optional-output/`。回答「有哪些选项、选了哪个、为什么」。
> 依据 `01-problems.md` 的 P2。**已冻结**（方案 C + 用户约束，见下）。

## 一、根因（最终版，坐实）

P2 的断点**不在 devkit 的 harness**，而在「skill 维11 的条件输出契约设计」与「cann-bench 评测层实际调用路径」的错配：

1. **golden 权威语义**（`tasks/level3/unique/golden.py`）：`return_inverse=False → y`（单张量）、`True → (y, inverse)`（二元组）。
2. **skill 维11 原设计**（`.claude/skills/ascendc-op-dev-coding/SKILL.md` 维11）：可选输出算子「schema 固定 `-> (Tensor, Tensor?)` + 调用入口层**裁剪 wrapper**（`cann_bench.{op}` 按参数裁剪）」，并假设**两套消费路径**——①评测经裁剪 wrapper、②harness 经 raw op。
3. **cann-bench 评测层实际**（`cann_matcher.py`）：查找顺序是「先 `torch.ops.cann_bench.{op}`（raw op，C++ 注册）→ 后 `cann_bench` 模块（wrapper）」。`unique`（snake_case）排在 `Unique`（PascalCase）前且 torch.ops 优先，故**评测层永远调 raw op，裁剪 wrapper 是死代码**。
4. **结果**：raw op 的固定元组 `(y, None)`（2 个）与 golden 的条件单返回 `y`（1 个）在 `compare_tensors` 顶层 `len(outputs) != len(goldens)` 处错位 → 报「输出数量不匹配」。

**关键区分（避免误判）**：
- 「可选输出」（proto `outputs[*].optional: true`，输出「有/无」随 bool 参数变）≠「可变数量输出」（`-> Tensor[]`，输出「数量」随输入/attr 的值变）。前者 cann-bench 里唯一是 unique；后者有 grouped_matmul/foreach_norm 等。
- grouped_matmul 等之所以没事，是因为它们的 **golden 始终返回 list**（类型恒定，只变长度），评测层 `_normalize_outputs` 天然对齐；unique 的 golden **返回类型本身可变**（单 tensor vs tuple），而 plugin 用了固定 tuple，两者错位。

## 二、方案（冻结：方案 C）

**方案 C — 修正 skill 维11，raw op 用 `-> Tensor[]` 返回**：

- 可选输出算子（proto `outputs[*].optional: true`）的 plugin schema 用 `-> Tensor[]`，C++ 返回 `std::vector<Tensor>`，按控制参数**条件 push**：`return_inverse=false → [y]`、`true → [y, inverse]`。
- 返回数量随参数变、与 golden 一致，`_normalize_outputs` 对 `[y]`/`y`、`[y, inverse]`/`(y, inverse)` 均归一化对齐。
- 删掉「裁剪 wrapper」这条死代码路径（评测层不调它）。

## 三、用户约束与方案收敛

- 用户拍板：**「cann-bench 仓有 bug 也不改」** → 方案 A（改评测层 `compare_tensors` 容忍 optional 尾输出）、方案 B（改 `cann_matcher` 优先 wrapper）**均出局**。
- 用户拍板：**「只做返回结构，不提 kernel 直调」** → 方案 C 范围锁定在「返回结构」这一层，不卷入 plugin 的「kernel 直调 vs ACLNN executor」调用方式（那是 P1 相关、另一个维度）。
- 唯一落在 devkit 边界内、且构造性对齐 golden 的根治是方案 C。

## 四、实证锚点

`/home/x00584171/temp/unique` 的 plugin 正是方案 C 的**逐字实现**——`m.def("unique(...) -> Tensor[]")` + `std::vector<at::Tensor>` 条件 push（`return_inverse=false → return {y}`、`true → return {y, inverse}`），且**通过了 cann-bench 评测**。证明：

1. PyTorch `Tensor[]` 返回在评测链路可行、checkSchema 接受。
2. `-> Tensor[]` + 条件 push 能让 raw op 返回数量随参数变、与 golden 对齐。
3. 方案 C 的「返回结构」部分不是新发明，是有实测背书的正确范式。

（注：temp/unique 同时用了「kernel 直调」，那是另一个维度、与 P2 的返回结构正交，方案 C 不取——见用户约束。）

## 五、保证强度（引导 vs 门，诚实边界）

方案 C 是**指导层**修正，不是**确定性保证**：

- 改的是 skill 维11（告诉 LLM 正确范式 `-> Tensor[]` + 条件 push），codegen 仍是 LLM 生成，**「是否按指导生成」是概率性的**。
- 框架门 `_return_verdict`（一致性检查）只拦「声明↔实现不一致」的机械错误，**不拦**「可选输出用 `(Tensor, Tensor?)` 固定元组」的语义错误——那是 skill 指导的职责（§2.9 门不越界）。
- 兜底是**评测层显式暴露**（P2 复发会报「输出数量不匹配」，非静默假绿）。
- 可选的更强保证：加一个「proto optional 输出 → plugin schema 必须 `-> Tensor[]`」的确定性门。按 §1.14（最小结构、「控模型」的门默认不加），**默认判断不加**，靠「skill 引导 + 评测兜底」。这是待定的权衡点，未落 L4。

## 变更记录

| 日期 | 内容 |
|------|------|
| 2026-08-17 | 初版：坐实 P2 根因，给出方案 A/C/B 评估，推荐 A。 |
| 2026-08-18 | 冻结版：用户约束「cann-bench 不能改」→ A/B 出局；发现 skill 维11 已有「裁剪 wrapper」设计但它是死代码；temp/unique 实证方案 C；锁定方案 C（修正维11）+ 保证强度边界。 |
