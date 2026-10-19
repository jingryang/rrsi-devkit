# L1 问题记录 — 算子开发知识约束（PR #62 知识沉淀的来源）

> **性质**：L1 问题/需求记录。只记录客观事实（哪里坏了、凭什么这么说），不提方案、不排顺序、不写决策。
> **对应 PR**：`refs/merge-requests/62`（`70eeb483`，fix tanh bugs）。本 PR 把下列问题固化为
> `ascendc-op-design-shared/references/` 下的参考文档；本文件是它们的 L1 问题来源记录（产权层）。
> **纪律**：§1.8——L1 记事实，方案归 L3，实施归 L4。已有问题只引用不重复事实。

---

## ✅ P1: 跨核写同一 GM 地址时 `SetAtomicAdd` 不支持 int64（及其他 dtype），直接累加丢更新

### 事实

- **观测**：算子存在「多核写同一输出地址」的累加需求时（沿规约轴跨核切分 / segment scatter-add），
  若输出 dtype 为 int64，硬件 `SetAtomicAdd` 在 A2/A3 全产品线**不支持 int64**。
- **证据**：`ascendc-dev-knowledge/.../SetAtomicAdd.md` 参数表——A2/A3 支持的数据类型为
  `int8_t/int16_t/half/bfloat16_t/int32_t/float`，**不含 int64**（`uint64_t` 亦不在列）。
- **影响**：此时「多核直接写同一 GM 地址」会丢更新（非原子写互相覆盖），必须改走
  per-core workspace + 单核 reduce 汇总的两阶段方案，否则结果随机错误。
- **凭什么说是问题**：int64 输出在规约/segment 类算子中常见；编译与单核跑通都不暴露，
  只在跨核聚合场景随机错，属最贵粒度才暴露的缺陷。
- **固化产物**：`ascendc-op-design-shared/references/atomicadd_dtype_fallback.md`
  （两阶段 fallback 方案 + workspace 预算要求）。
- **状态**：已固化（随 PR #62）。后续其它不支持 dtype 的追加修改在 `common-pitfalls` 关联。

---

## ✅ P2: strided `DataCopyPad` 尾块/非 32B 对齐行的「搬运行距 ≠ 寻址行距」导致行错位/越界

### 事实

- **观测**：`DataCopyPad` 做 strided 搬运（`blockCount>1` 或含 `srcStride`/`dstStride`）时，
  UB 侧 `dstStride=0` 会按 `AlignUp(blockLen, 32)` 逐行补位；而 kernel 若按主块固定行步长寻址读尾块，
  行错位（读到 `2j` 行）或越界垃圾必现。**只在尾块/非 32B 对齐行触发**，主块恒对齐测不出。
- **证据**：cummin 实测——尾块 1 元素 bf16（2B→32B）vs 主块 64B：kernel 读 input row `2j`；
  尾块 9 列 fp16（18B→32B）vs 主块 1120B：rows 1..16 全错。触发条件唯一：
  `AlignUp(尾块宽×s,32) != AlignUp(主块宽×s,32)`。
- **影响**：算子尾块输出=错位行数据或越界垃圾；compile/单核主块测试均不暴露。
- **凭什么说是问题**：编码期「搬运按各自对齐、寻址按主块步长」的混搭是历史真实 bug 根因。
- **固化产物**：`ascendc-op-design-shared/references/datacopy-stride-consistency.md`
  （不变式 + 方案一/二取舍 + 各阶段自检判据）。
- **状态**：已固化（随 PR #62）。

---

## ✅ P3: `ReduceSum` 高阶 API 在 A2/A3 强制最内层轴 32B 对齐（`srcInnerPad` 仅 true）

### 事实

- **观测**：`ReduceSum` 高阶 API 的 `srcInnerPad` 参数在 A2/A3 **当前只支持 true**——
  最内层 reduce 轴数据必须 32B 对齐；非对齐时 API 以 32B 粒度访问 UB，可能触发 VEC UB OOB。
- **证据**：`ascendc-dev-knowledge/.../高阶API/归约操作/ReduceSum接口/ReduceSum.md`——
  `srcInnerPad` 描述原文「Atlas A3/A2 训练与推理系列产品，当前只支持 true」。
  对齐元素数阈值：fp32/int32=8，fp16/bf16=16，int8/uint8=32。
- **影响**：reduce 最内层轴元素数 `D % alignElems != 0` 时须 DataCopyPad 尾部补零 + reduce
  `srcShape` 传对齐后元素数；`ReduceMean` 不能直接套用（补零会改除数）。
- **凭什么说是问题**：非对齐在真实算子（如沿非 32B 整除维度归约）普遍存在，编译不报、运行期 OOB。
- **固化产物**：`ascendc-op-design-shared/references/reduce_align_strategy.md`。
- **状态**：已固化（随 PR #62）。

---

## ✅ P4: `Tanh` 原语存在两种独立的精度不足模式，可致 fp32 无法达精度阈值

### 事实

- **观测**：AscendC `Tanh` 有两种独立的精度不足模式：
  - **模式 A（公式层）**：公式含 `1 ± tanh(...)`（或 `1 ± saturating_func(...)`）且实参进入饱和区，
    发生 catastrophic cancellation（相对误差按量级放大）。误差来自**后续加减法**而非原语本身。
  - **模式 B（原语层）**：`Tanh` 多项式在近零域 `|x| < 0.1` 丢失 `tanh(x) ≈ x` 恒等式，
    绝对值误差恒小（≤1e-7）但输出趋于 0，以 ULP 计相对误差爆炸。即使输出直接是 `tanh(x)` 也失败。
- **证据**：GELU tanh 近似在 `|x| > 3` 时 fp32 diff 达 0.195；改写 sigmoid 链后 fp32=4.8e-7。
  中域/饱和区实测 bit-clean（≤4 ULP）。A2 基础 `Exp` 存在输入域限制（`|a| > ~6` 饱和失真），
  改写链须以实测精度为准。
- **影响**：涉及 tanh 原语或其差值型消费的算子，fp32 精度可能无法满足阈值；仅提高 Tanh
  实现精度修不了模式 A。
- **凭什么说是问题**：两模式独立、触发条件明确（饱和区 + `1 ± tanh` / 近零域），属需求/golden
  层的可解释事实，工程据此在详设选 API 序列时改写。
- **固化产物**：`ascendc-op-design-shared/references/numerical-stability-guide.md`。
- **状态**：已固化（随 PR #62）。

---

## 变更记录

| 日期 | 内容 |
|---|---|
| 2026-08-08 | 初版：记录 P1–P4（PR #62 四篇参考文档的 L1 来源问题）。P1–P4 均已随 PR #62 固化到 `ascendc-op-design-shared/references/` |
