# TilingKey 写法 host/kernel 机制错配 — 问题记录（L1）

> 纯事实快照（哪里坏了 / 凭什么这么说）。不提方案、不排顺序、不写决策。
> 触发：别人反馈 run `output/20260723-144018-ce4a7e_only_pass_design`（softmax，A5 Regbase / ascend950）「设计时 tilingkey 写法不统一」。
> 范围：codegen 引导链（codegen.py 编码规则 + ascendc-op-dev-coding{,-regbase} skill 文档）产出的 TilingKey 写法一致性。

## P1 — softmax run 产出 host/kernel TilingKey 机制错配

run `20260723-144018-ce4a7e_only_pass_design` 实际生成的 softmax 代码两侧用了**两套互斥机制**：

- **host 侧**（`softmax_tiling.cpp`）+ tiling_key 声明（`softmax_tiling_key.h`）：**新机制** `ASCENDC_TPL_SEL_PARAM(context, dTypeX, templateKey)` / `ASCENDC_TPL_ARGS_DECL/SEL`（selfcheck_4.B2.md / 4.B1.md 记录）。
- **kernel 侧**（`softmax_kernel.cpp`）：**旧机制** `extern "C" __global__ __aicore__ void softmax(...)` + `if (TILING_KEY_IS(TEMPLATE_KEY, 1/2))` 运行时分支（selfcheck_4.C.0.md 记录）。

`coding_index.md` 的字段映射表把两套缝合成「同一套的两端」：`ASCENDC_TPL_SEL_PARAM(context, templateKey, ...) | ... | TILING_KEY_IS(templateKey)`——产出方（s4-coding agent）未识别这是两套不能混用的机制。

两套机制的本质差异（客观对照）：
- 新机制（ASCENDC_TPL）：host `ASCENDC_TPL_SEL_PARAM`（宏展开 = `GET_TPL_TILING_KEY` → `context->SetTilingKey`）+ kernel `template<typename D_T_X,...> __global__ __aicore__` 模板函数 + `if constexpr` 编译期路由，由构建系统按 `ASCENDC_TPL_SEL` 列表实例化特化。
- 旧机制：host 手动 `context->SetTilingKey(数值)` + kernel `extern "C" __global__` + `TILING_KEY_IS` 运行时分支。

## P2 — CANN v220 编译器按新机制解析 kernel 入口，与旧 kernel 入口对不上

`build_attempt3.log` 在 `get_code_channel_v220_by_first_tiling_key`（`ascendc_compile_v220.py`）阶段异常：CANN v220 编译器已按「模板参数化」机制（host 侧 `ASCENDC_TPL_SEL_PARAM` 触发的 v220 code_channel）解析 kernel 入口，期望 kernel 是模板函数；但 softmax kernel 入口是旧 `extern "C"` + 运行时 `TILING_KEY_IS` 分支 → 找不到匹配的模板特化 → 编译链路异常。（注：该 build log 的直接编译错误另有 `std::numeric_limits` 应为 `AscendC::NumericLimits`，是独立编码 bug，与机制错配正交。）

## P3 — selfcheck 缺 host/kernel 机制一致性交叉检查，错配被放过

selfcheck_4.B2（host 侧 TilingKey 分支覆盖）与 selfcheck_4.C.0（kernel 侧 TILING_KEY_IS 分支覆盖）**各自通过**——两者分别检查本侧写法完整，无交叉校验「host/kernel 是否同走一套机制」。结果 host 新 / kernel 旧 的错配在编码期自检绿灯放行，推迟到编译期才暴露。

## P4 — 引导链对 kernel 侧的旧写法引导证据

softmax run 走 regbase 路径（s2→s4→s5）。codegens 编码索引 `coding_index.md` 的 C.0 行（kernel 入口）按 regbase skill 模板生成，证据指向（改动前的引导文本现状）：
- `ascendc-op-dev-coding-regbase/references/coding-plan-template.md` C.0 行（标准表 / A3 路径 / A5 路径三处）引导 kernel 入口 `extern "C" __global__` + `TILING_KEY_IS 路由`。
- `ascendc-op-dev-coding-regbase/references/orchestrator-logic.md` C.0 示例行 `extern "C" | TILING_KEY_IS 路由`。
- `ascendc-op-dev-coding-regbase/references/env-and-platform.md` 平台对照表 A2/A3 Membase 标注 `TILING_KEY_IS`；路径映射 A3 Membase `C.0 TILING_KEY_IS 路由`。
- `codegen.py` CodegenStage 编码规则段含 `TILING_KEY_IS 每个值都有对应分支`。
- host 侧（`coding-plan-template.md` B2 行）无对应旧引导；模型跟 `ref_cache/add`（新机制参考实现）学了 host 新写法。

→ 单边正确、对不上：host 新写法（自学 ref_op）+ kernel 旧写法（skill 硬引导）= P1 的错配。

## P5 — 主线仓 A5 SIMT 新写法范例存在性（外部只读参考）

`cann-bench/examples/` 下用 `ASCENDC_TPL` 的算子（add/moe_re_routing/sqrt/exp）均为 A3 Membase，无 A5 SIMT 范例。主线生产仓（ops-math/ops-nn/ops-transformer）按 `op_kernel/arch35/`（=A5）子目录分版，含大量 A5 SIMT + ASCENDC_TPL 算子（如 `ops-math/math/acosh/op_kernel/arch35/acosh_tiling_key.h`，文件由 CANNBot 生成，头部注释明注 `❌ 禁止使用废弃的 TILING_KEY_IS 宏`）。这是 A5 SIMT 新写法的权威外部范例源。

## 状态

已实现（2026-07-25，commit `d966c0a`）。L3 见 `02-analysis.md`、L4 见 `03-impl.md`。review 报告 `reviews/PR-d966c0a-review.md`。
