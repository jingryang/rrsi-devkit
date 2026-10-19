# 38 — P10 根治：cannbench_adapt 确定性对齐 m.def schema 名（L3 方案分析）

> 工作线：self-evolution（六算子批跑收口）
> 状态：**已拍板冻结**（2026-07-12）
> 关联 L4：`38-p10-schema-adapt-impl.md`；L1：`batch-sixops-runlog.md` 问题 10 / 第四轮
> 上游 plan：`/root/.claude/plans/lovely-painting-aurora.md` 方案一

## 问题（L1 事实引用）

codegen 生成的 `op_plugin/<op>_plugin.cpp` 的 `m.def("<op>(Tensor x, ...) -> ...")` schema 参数名（`x`/`p`）**不 fidelity 于 proto.yaml/golden 名**（`input`/`scalar`）。cann-bench `kernel_eval` 按 golden 名**关键字调用** `func(**params)`（`param_builder.build_call_params` 用 golden 名建 dict，`op_runner._run_simple` 执行 `func(**params)`），故 schema 名错 → `missing value for argument` → 全 case 0 分。salvage 实证：swi_glu `x`→`input` 后 77.42(20/20)、foreach_norm `p`→`scalar` 后 48.07(19/20)。

**devkit 自检盲区**：smoke 只 `getattr` 验符号可解析、precision_debug 走 positional wrapper——positional 调用对参数名不敏感，故 schema 名错也过 devkit 全链路，到 cann-bench（关键字）才爆。

## 选项

### A. codegen skill 约束「schema 参数名逐字取自 proto」
- 优点：源头修，最干净。
- 缺点：skill 改动 + 需 codegen 重跑才验证；存量已 build 的 opp 仍需 salvage；skill 约束对 LLM 非硬保证（仍可能漂）。

### B. devkit 加载期/部署期校验（解析 m.def 参数名 vs proto，不一致即拦）
- 优点：填补 verify(positional)↔eval(keyword) 调用约定盲区，可诊断（§1.3）。
- 缺点：只拦不修——拦下后仍需人/LLM 改 m.def + rebuild，不自动闭环。

### C. cannbench_adapt 确定性后处理（rename m.def schema + rebuild）✅ 选定
- 落点：`cannbench_adapt.transition()` 末尾追加确定性 Python 段——以 `state.requirement.op_spec`（proto 单一真相源）参数名为基准，正则解析 m.def schema 参数名，按位置对齐 rename，m.def 变更则 rebuild opp。
- 优点：确定性、可审计、自动闭环（rename + rebuild + 重评一条龙）；存量 opp 也救（不依赖 codegen 重跑）；**不入 codegen skill**（避免 skill 耦合 cann-bench，§2.1/§2.7——cannbench_adapt 本就是 codegen→cann-bench 桥接层，对齐 m.def 是其职责延伸）；只改 schema 字符串不动 kernel（torch 按 schema 名绑定后 positional 传 C++，runlog 实证）。
- 缺点：治标（codegen 仍可能再生成错名）——但配 B 的 warn 即可暴露。

## 决策

**C 为主修复（承担根治）+ B 的轻量版（codegen `transition` warn，不自动改 manifest）做可观测性**。组合理由（§1.2 四把尺子）：
- **可维护**：proto 为单一真相源，cannbench_adapt 后处理维持「桥接层让 codegen 产物能被 cann-bench 关键字调用」的职责不变式。
- **可扩展**：同类错名（任何算子 m.def 参数名≠proto）自动归位，不需逐算子打补丁。
- **可诊断**：codegen `transition` warn 暴露参数名 fidelity 问题（不推迟到 cann-bench 评分才爆）；rebuild 失败设 `last_error=ErrorFeedback(schema_adapt_failed)` 阻断 eval（不静默放行旧 opp 全 0）。
- **架构合理**：确定性后处理落在桥接层（cannbench_adapt），不越层到 codegen skill / 不在 workflow 加载期校验（参数名 fidelity 是产物合法性，非配置合法性，§1.3 只能产物生成后校验）。

**fail_strategy 区分**：glue 适配失败 → continue（现有，eval 能 fallback）；P10 rebuild/m.def 解析失败 → `last_error=schema_adapt_failed` + 阻断 eval（旧 opp 全 0 不能放行）。

## 不选 A 单独的理由

codegen skill 约束对 LLM 非硬保证，且存量 opp 无法靠 skill 改动救（需重跑 codegen，受 429 限制）。C 自动闭环 + B warn 是更稳健的组合。后续若 warn 频繁，可再强化 codegen skill（A）——C 不依赖 A。
