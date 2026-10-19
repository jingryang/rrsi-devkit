# TilingKey 写法统一 — 方案分析（L3）

> 选项 / 选择 / 理由。决策拍板后冻结。问题事实见 `01-problems.md`。
> 范围：把 codegen 引导链产出的 TilingKey 写法从「host 新 / kernel 旧混用」收敛到「host/kernel 同走一套机制」。

## 决策 1 — 统一到 ASCENDC_TPL 新机制，彻底废弃 TILING_KEY_IS 引导

- **选项 A**：保留两套并存，只补「一致性提醒」（文档警告 host/kernel 要对齐）。
- **选项 B**：统一到新机制 ASCENDC_TPL（host `ASCENDC_TPL_SEL_PARAM` ↔ kernel `template<typename...> __global__` + `if constexpr`），删除旧 TILING_KEY_IS / `extern "C"` + `SetTilingKey` 引导。
- **选 B**：
  1. **§2.5 唯一通路 / 不留旧债**：两套机制混用本身就是债（P1 错配的根源）。保留两套 + 提醒 = 把不变式交给 agent 服从度，不可靠。
  2. **主线仓权威印证（P5）**：Huawei 官方 CANNBot 生成的主线仓 arch35 算子（acosh/sort/cdist_grad 等）文件头明注「禁止使用废弃的 TILING_KEY_IS 宏」——新机制是官方既定方向，旧机制已废弃。
  3. **知识库已就绪**：`ascendc-dev-knowledge` 的 `Utils_API/Tiling模板编程/` + `910D_knowledge_extra/` 有完整新机制文档，缺的只是 codegen 引导指向。
  4. **全代际通用**：add 参考实现的 def.cpp 配了 ascend910b/910_93/950（A2/A3/A5），证明新机制全代际支持，不必按代际分叉。
- **不选 A**：提醒不解决根因，agent 仍可能在两侧各取一套。

## 决策 2 — 全链路正向化（引导层不提 TILING_KEY_IS token）

- **选项 A**：仅生成引导（codegen 编码规则 + coding-plan-template C.0）正向化；自检/红线表保留 TILING_KEY_IS 提及（诊断价值）。
- **选项 B**：全链路正向化——生成引导 + 自检表 + 红线表都正向锚定，引导层完全不出现 TILING_KEY_IS token；自检靠「正向特征缺失」catch 旧写法。
- **选项 C**：正向化但保留红线表 #2（红线本质是边界声明）。
- **选 B**（用户决策）：
  1. **priming 风险**：负向「禁 TILING_KEY_IS」把 `TILING_KEY_IS` token 摆在模型眼前，生成时反而更容易吐出（"不要想大象"效应）。正向「用 ASCENDC_TPL」让模型从引导里看不到旧 token，只能从 ref_op（新写法）学。
  2. **自检正向锚定仍能 catch**：自检检查「host 有 ASCENDC_TPL_SEL_PARAM 且 kernel 入口是 template + if constexpr」——全旧写法（host 缺 SEL_PARAM）或混用（kernel 非 template）都导致正向特征缺失 → fail。不依赖 grep TILING_KEY_IS 也能确定性检出。
  3. **构造性保证强化**：引导 + ref_op 都不出现旧 token → 模型几乎不可能学到旧写法。
- **不选 A/C**：自检表/红线表模型也会读到，残留 TILING_KEY_IS 仍有 priming；B 最彻底且自检不弱（正向特征缺失够诊断）。

## 决策 3 — 「保证不出现旧写法」的承担者分层（诚实认知）

引导文本（无论正负）**不能保证** LLM 不产出某写法——生成是概率性的。真正的「保证」来自两层，都不是引导：

- **层 2 自检门（确定性）**：host/kernel 机制一致性交叉自检，检测到错配即 fail。这是「保证」的承担者。
- **ref_op 构造性（最大化降概率）**：模型主要从 ref_op 学，ref_op 永远给新写法（add/acosh）→ 学到的就是新的。

引导正向化（决策 2）是**降低概率 + 减 priming**，不是保证机制本身。故本次「保证不出现旧写法」= 自检门确定性 catch + ref_op 新写法 + 引导正向化降概率，三者叠加接近保证，而非引导单方面保证。

## 决策 4 — A5 SIMT 新写法用主线仓静态印证，不做 minimal 编译验证

- **选项 A**：写最小 A5 SIMT 算子骨架，编译验证 v220 通道 + 模板实例化通过。
- **选项 B**：在主线仓找 A5 SIMT + ASCENDC_TPL 算子静态印证写法。
- **选 B**（用户建议，最快）：
  1. 主线仓 arch35 子目录有大量 A5 SIMT + ASCENDC_TPL 范例（P5），且是 CANNBot 官方生成，权威性高于自造 minimal。
  2. acosh 范例完整印证三件套：host `ASCENDC_TPL_SEL_PARAM` + tiling_key.h `ARGS_DECL/SEL` + kernel `template<typename T>` + `if constexpr`。
  3. 多模板路由范例（sort/cdist_grad 带 `ASCENDC_TPL_UINT_DECL`）印证 T1/T2 场景的 if constexpr 编译期分发。
- **不选 A**：编译验证是 heavy 操作（需 CANN 环境 + 写 minimal），主线仓静态印证 30 秒得出确定结论，更经济。

## 决策 5 — 层 3（设计产物加「模板参数维度」字段）不做

设计产物（template_division / tiling_strategy）当前用数值 tiling_key（1/2）描述路由，不显式声明「哪些维度模板化」。选项：加结构化「模板参数维度」字段给 codegen 明确信号。

**不做**（YAGNI）：层 1（引导统一）+ 层 2（交叉自检）落地后，模型从 ref_op + 知识库已能自洽推断模板参数维度，设计层加字段收益边际、且耦合设计 schema。若未来发现 codegen 因设计产物缺维度信号而频繁跑偏，再立 L1 补。
