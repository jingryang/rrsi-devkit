# 特殊值语义对齐：elementwise Max/Min 的 API 原语选型

> **定位**：浮点特殊值（NaN / ±0 tie）语义对齐的预防规则，**产权层为详设**。
>
> 解决的问题是一类反复踩坑：为与 golden **逐位对齐**（precision threshold=0 / bit-exact）
> 实现 elementwise "取较大/较小"（`torch.maximum`/`torch.minimum` 及 foreach 变体）时，
> 直接选用硬件 SIMD `Max`/`Min`（或 `Maxs`/`Mins`）原语，会把"官方文档没写特殊值语义"
> 误当"与 golden 一致 / 没限制"。文档未提 ≠ 无约束，也不代表任何特定行为——这会导致
> NaN/±0 用例的精度失配，把问题推迟到编码/精度调试阶段才暴露。

## 谁必须读本文件

- **详设阶段（产权层）**：`ascendc-op-tiling-vf-design`（A5，决定 `vf_design.vfs[].compute_ops`
  选型的**当下**）、`ascendc-op-tiling-buffer-kernel`（A5 kernel API 序列 / verifiable_claims
  查证）、`ascendc-op-tiling-precision-perf`（精度链声明是否依赖未文档化语义）。
  **选 compute_ops / API 序列的当下**就应据本文件定案，不得把该决策留给下游编码阶段兜底。
- **编码/测试阶段（二次校验）**：`ascendc-op-dev-coding-regbase`、`ascendc-vf-test-agent`
  在核对详设 compute_ops 是否已正确改写时 Read 本文件比对。

## 触发条件（客观，满足即进入下文规则）

算子语义为 elementwise 二元"取较大/较小"（maximum / minimum / 同族 NaN-传播选择），
**且**约束要求与 golden 逐位一致。若输入域已保证无 NaN 且 ±0 tie 侧与 golden 核对过，
或 golden 本身就是 fmax 式忽略-NaN 语义，则不触发，可直接用原生指令。

## 语义事实（知识库锚点，均已查证）

| 对象 | 来源锚点 | 特殊值语义 |
|------|---------|-----------|
| golden `torch.maximum`/`_foreach_maximum` | 算子侧 `golden.py` 实证（本类算子实测 42/42 bit-exact，详见 kernel 注释与 vf-test 记录） | **NaN 传播**（任一输入为 NaN → 输出该 NaN）；有序域/±0 tie 取 **self（第一个输入）侧** |
| SIMD RegTensor `Max`/`Min`（`Maxs`/`Mins` 同理） | `ascendc-dev-knowledge/references/910D_knowledge_extra/Max-43.md`（官网同文见 `regbase-vf-test/references/a5-api-enhanced/Max.md`） | **仅一条约束**：`srcReg0=-0, srcReg1=+0 → 输出 +0`（Max-43 约束说明）。**NaN 行为全篇未文档化**；`Max-97`/`Maxs-48` 等变体约束为"无" |
| SIMT 标量 `__hmax` / `fmaxf` | `ascendc-dev-knowledge/references/910D_knowledge_extra/__hmax.md`、`fmaxf.md` | 有完整 8 条返回值语义（x NaN→返 y、y NaN→返 x、双 NaN→返 NaN、±0/inf 规则）= C `fmax`：**忽略 NaN，非传播** |

**两条关键判据（本文件的核心结论）**：

1. **SIMD `Max` 文档没有 NaN 字眼，绝不等于它做 NaN 传播**——更不等于与 golden 一致。
   `Max-43.md` 唯一写明的 ±0 tie（`-0/+0 → +0`）甚至**与 golden "tie 取 self" 相冲突**
   （按文档 max(-0,+0)=+0，不是第一输入 -0）。仅凭该文档不足以支撑"逐位对齐 golden"
   的正确性断言。
2. **SIMT `fmax`/`__hmax` 的"忽略 NaN"语义与 golden maximum 的"传播 NaN"相反**，
   不能拿 fmax 文档去为 SIMD `Max` 的 NaN 行为背书，也不能把 `fmax` 语义当作
   `torch.maximum` 语义。

## 结论规则（design 期定死，不留给编码）

1. **默认安全选型 = 语义确定的 Compare + Select 复合原语**（所有参与指令特殊值语义明确，
   可逐位复现"NaN 传播 + tie 取 self"）：

   ```
   nanSelf  = Compare(NE, self,  self)          // x != x 判 NaN（golden 传播侧）
   nanOther = Compare(NE, other, other)         // 同理
   gt       = Compare(GT, other, self)          // 有序域：仅 other>self 取 other
   y        = Select(gt ? other : self)         // tie（含 ±0）落在 self 侧
   // 需要 NaN 传播时再倒序覆盖：y = nanOther ? other : y; y = nanSelf ? self : y
   ```

   该组合不依赖任何未文档化的指令行为，可直接写进 `vf_design.vfs[].compute_ops`
   （如 `["Compare","Compare","Compare","Select",...]`）。
2. **想直接用 `Max`/`Maxs` 原语**：仅当 (a) golden 是 fmax 式忽略-NaN 语义，或
   (b) 输入域排除 NaN 且 ±0 tie 语义与 golden 逐项核对过（注意 Max-43 明文的 `-0/+0→+0`
   ≠ golden tie 取 self）。满足才可写入 compute_ops；否则记录在决策里并走规则 1。
3. **对 golden 特殊值语义有疑问时**：以算子侧 `golden.py` 实测为准，禁止猜测、禁止
   用"无 NaN 输入"等假设掩盖。结论写入 decisions / `verifiable_claims`（带来源锚点 +
   verification），避免编码阶段重新推导一遍。

## 典型产出落点

- `vf_design.vfs[].compute_ops`：写 `Compare/Compare/Compare/Select…` 组合，而非裸 `["Max"]`。
- `decision_log.json` / 段对象 `decisions`：记录"为何不用 Max 原语"，理由指向 Max-43 文档
  缺口（`-0/+0→+0` 与 golden tie 冲突 + NaN 未文档化）。
- `buffer_kernel.verifiable_claims`：如需对 Max/Min 语义作硬断言，标 `api_checked` 并附
  锚点（`Max-43.md` / `__hmax.md` / `fmaxf.md`）；文档未覆盖的点按
  `knowledge_policy.md` 的"信息遗漏处理"暴露，不静默假设。
