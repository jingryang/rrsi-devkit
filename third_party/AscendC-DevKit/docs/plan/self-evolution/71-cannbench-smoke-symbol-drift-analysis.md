# 71 — regbase codegen manifest 兜底 symbol 与 op_plugin 注册名错位（P98）方案分析

> 层级：**L3 / 方案分析**。回答「有哪些选项、选了哪个、为什么」。
> 问题事实见 `06-problems.md` [[P98]]；实施见 `71-cannbench-smoke-symbol-drift-impl.md`。

## 问题域

run `20260722-143612-b4fa39`（exp，regbase 路径）`cannbench_adapt` 阶段 deploy smoke 失败：`getattr(torch.ops.cann_bench, 'exp')` AttributeError，因 op_plugin 实际注册名是 `npu_exp`（避 torch 内置 exp 冲突），而 `manifest.callable_target.symbol` 被兜底盲拼成 `...exp`。

四点错位叠加：

1. **op_plugin 注册名 ≠ op_name**：codegen 为避 torch 内置名冲突，常注册成 `npu_<name>`（exp→npu_exp）。
2. **regbase manifest 兜底盲拼**：s5 未回传 `codegen_manifest.json` 时，兜底用 op_name 拼 symbol（`torch.ops.cann_bench.<op_name>`），不反映真实注册名。
3. **adapt 修复碰不到验证点**：adapt agent 禁改 op_plugin，只能在 Python 层加 wrapper（救 `dir(cann_bench)` 发现），但救不了 smoke 查的 C++ OpNamespace 属性。
4. **adapt prompt 系统性误导**：prompt 把发现钉死在 `dir(cann_bench)`、明示「symbol 无关紧要」，agent 据此判定 wrapper 即足——是认知盲点的来源，非偶然。

与 [[P95]]-[[P97]] 的边界：前者修 **cann-bench 评测侧**发现链路（PYTHONPATH / `_C` / per-op wrapper）；本条修 **devkit deploy 自己的 smoke 验证门**（消费 manifest.symbol）。run 在 P97 三 commit 之后启动仍失败，证 P97 未覆盖此点。

## 归属判定（排除法 + 反证）

- **框架缺陷**（非 codegen skill、非 transient）：修复落在 codegen stage 的兜底分支 + cannbench_adapt prompt，均为框架层。确定性（任何 regbase + 注册名≠op_name 的算子复现），非 transient。
- **非 op_plugin/codegen skill 职责**：注册名用 `npu_<name>` 避冲突是合理设计；问题在框架未把「实际注册名」回灌进 manifest.symbol。

## 选项与取舍

**问题**：让 `manifest.callable_target.symbol` 反映真实 C++ 注册名。

| 选项 | 做法 | 取舍 |
|---|---|---|
| ① 兜底从 op_plugin 源解析注册名（选，主修复）| 兜底分支读 op_plugin 的 `m.def`，提取注册名构造 symbol | ✓ 构造性一致（symbol↔实际注册名）；✓ 可扩展（任意冲突名自动正确）；复用已有 m.def 解析；解析失败回退 op_name+warn |
| ② 强制 s5 产出 manifest | regbase s5 prompt 要求产出 codegen_manifest（对齐 Membase）| ✓ 减少兜底触发；✗ 改 skill、LLM 产出仍可能不准；范围大，列为 follow-up |
| ③ smoke 容错跳过 | smoke 失败不阻断 | ✗ 违 §3.4（失败必修复不掩盖）；回归 false-green |

**选 ①**：构造性正确——manifest.symbol 的真值就是 op_plugin 实际注册名，从其源头（`m.def`）派生是直接表达，不依赖 op_name 假设。

**防御（叠加）**：修正 cannbench_adapt prompt——明确 symbol 是 smoke/runner 权威符号、须与 m.def 注册名一致。主修复让 agent 收到的 manifest.symbol 本身就准；prompt 澄清消除「symbol 无关紧要」的系统性误判，与 P97「根治+防御」风格一致。

**m.def 解析归属**：原散落在 cannbench_adapt 私有；抽到 `domain/mdef_parse`（§2.5 唯一通路、§1.1 分层），codegen 与 cannbench_adapt 共享。`align_schema_params` 依赖 op_spec（业务对齐），留 cannbench_adapt。

## 拍板

- **主修复**：regbase manifest 兜底从 op_plugin 解析真实注册名（选项①）。
- **防御**：修正 adapt prompt 的 symbol 认知误导。
- **归属**：m.def 解析集中 `domain.mdef_parse`。
- **follow-up（不阻塞）**：选项②（regbase s5 产出 manifest，减少兜底触发）。
