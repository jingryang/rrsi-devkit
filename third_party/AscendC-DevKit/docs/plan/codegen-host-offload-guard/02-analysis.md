# L3 方案分析：codegen host-offload 契约门

> 层级：**L3 / 方案分析**。记录选项、选了哪个、为什么。前置 L1 `01-problems.md`。

---

## 候选方案

| 方案 | 处置 | 误判风险 | 消费渠道 |
|---|---|---|---|
| A 纯 LLM 自检（现状） | 维10 LLM 自觉 | 概率性（LLM 可能走过场） | 无确定性 |
| B 确定性机械门 + WARN 结构化信号放过 | 命中写 `host_offload_signal.json`，不 halt | 低 | 下游 debug/eval/报告 |
| C 确定性机械门 + 硬门定向 retry codegen | 命中 `plugin_host_offload` → retry | **近零（判据收窄后）** | codegen 确定性消费 |

## 决策：C，判据收窄到近零误判

**判据**：`op_plugin/*.cpp` 出现 `.cpu()` / `kCPU`（`.to(torch::kCPU)`/`.to(at::kCPU)`/`.cpu()`），注释之外 → `plugin_host_offload` 硬门。

**为什么近零误判**：维10 已把 plugin 契约收窄到「接口适配 + 调 aclnn kernel」。本项目生成插件里：
- 标量控制输入走 **attr（int/float）**，非 tensor → 无需 `.cpu().item()`；
- shape 决策用 `.sizes()`（device 无关）、空检查用 `.numel()`（device 无关）→ 无需 `.cpu()`；
- `*_meta` 函数只 `torch::empty` 推导 shape → 无 `.cpu()`/`kCPU`。

故 `*_npu` 函数内出现 `.cpu()`/`kCPU` 即 host 往返，无合法用例。

## 为什么选 C 而非 B

- **§2.9「优先本 agent 范围内自检闭环」**：C 让 codegen 命中即就地改（硬门 retry 带 file+line 反馈），比 B「放过给下游」更符合「发现与解决在同一 agent 内闭合」。
- **§1.10 业务语义 vs 机制特征代理**：判据不用「机制特征」（裸 `.cpu()` 出现）泛化，而锚定「在维10 收窄的 plugin 契约内 `.cpu()`/`kCPU` 无合法位置」这一**业务语义**——机制特征本身不构成代理，语境（plugin 契约）赋予了它近零误判的语义。
- **B 的「放过」正是 transpose 反面**：`design-math-claims/02-analysis.md` 明言「打无人消费的 WARN 就是反面」。B 若无确定性消费点，就是静默滑过；C 的消费点是 codegen 定向 retry，确定性、有 acceptance 判据（retry 后重扫消除才算过）。

## 四把尺子

- **可维护**：单一判据 `.cpu()`/`kCPU`，与维10③ 同源，不新增词汇表；判据不认算子名（§1.12）。
- **可扩展**：同类 host-offload（`at::_unique2`、`torch::sort`、host 前缀和）凡走 `.cpu()`/`kCPU` 一律命中；无需为每个算子打补丁。
- **可诊断**：硬门 feedback 带 `plugin_file` + `line` + `pattern`，coder 有确定性修的目标；命中留结构化信号（ErrorFeedback.reason=plugin_host_offload）。
- **架构合理**：落在 codegen 契约校验层（与 `_torch_plugin_contract_error` 并列），不越层到 debug/eval 兜底（那些仍是独立更硬的网）。

## 残余风险（诚实声明）

- **字符串字面量内**的 `.cpu()`/`kCPU`（plugin 源码几乎不会出现）——未单独处理，命中即硬门（保守）。
- **`.item()` 隐式同步**（读标量 tensor）不含 `.cpu()` 字面量 → 不命中（漏判）。但本工程标量控制输入走 attr，该场景不出现。
- 判据是「`*_npu` 内 `.cpu()`/`kCPU`」的近似（未精确区分函数边界），`*_meta` 内若误写 `.cpu()` 也会命中——但 `*_meta` 无合法 `.cpu()`，命中仍是违规。
