# SIMT host Dynamic UB 引导 — 实施方案（L4）

> 改哪些文件、什么顺序、怎么验证。问题见 `01-problems.md`，决策见 `02-analysis.md`。
> 阶段 A：纯 skill/知识文档（host 配置引导）。阶段 B：路径 1（isolated VF 测试）工具缺口闭合（Python 改动 + 真机 smoke）。

## 改动文件与顺序（已完成）

### 1. 规范知识源（simt skill 内，单一权威配方）

**`.claude/skills/ascendc-simt-operator-design-patterns/references/workspace-contract.md`**
- §3 标题/正文从 "DCache 预留三档并存 + SetLocalMemorySize" 升级为 "**SIMT Dynamic Unified Buffer（host tiling 必配）**"：
  - 语义：Dynamic Unified Buffer = RTS SIMT 共享内存窗口；API 默认 0 = 不声明，不声明则大共享 buffer / DCache 越界；模板是 SIMT（VF Simt 线程 / SIMT 直访 GM）才配，SIMD 不配。
  - 接口：写 `context->SetDynUBufSize(usableUb)`；桥接说明 `SetLocalMemorySize` 是同函数废弃名（主线仓仍大量按旧名调用，语义一致）。
  - 数值：`usableUb = Ops::Base::GetUbSize(context) − DCache(32K/58K/128K) − 静态预留`，host 私有化决策与 device TPipe 分配同一个数；DCache 三档表保留。
  - 判据按结构信号不认算子名；出处给 ops-nn gather_v2（SIMT 模式调、SIMD 不调）等；参考 CANN 头文件 deprecated 标注。

**`.claude/skills/ascendc-simt-operator-design-patterns/SKILL.md`**
- 决策速查 Tiling 侧加第 6 条（SIMT host 必配 SetDynUBufSize），kernel 侧注释顺延 7/8/9。
- Guardrails 加 "**SIMT host 必配 Dynamic UB**" 条目（含废弃名桥接）。
- 资产表 Workspace 契约行补 "SIMT Dynamic UB 声明（SetDynUBufSize，DCache 三档）"。

**`.claude/skills/ascendc-simt-operator-design-patterns/references/{shared-memory,data-movement,dev-experience}.md`**
- 三处旧名教学改为 `SetDynUBufSize`（默认 0 = 不声明；`SetLocalMemorySize` 为同函数废弃名，主线仓 arch35 仍用旧名——生成代码用新名）。

**`.claude/skills/ascendc-simt-operator-design-patterns/kimi_simt_strategy.md`**
- 仅教学格（L54 通用约定表 DCache 预留行 / T2 策略说明 / 共性归纳第 4 条）加"现名 SetDynUBufSize / 旧名同函数"桥接；**主线仓 verbatim 源码片段（L134/270/1882/1885/4173/5955 等）不改**（保溯源）。

### 2. 设计/编码链引导（防流程漏配）

**`.claude/skills/ascendc-op-tiling/SKILL.md` §0.5（SIMT 先查模式库段）**
- 追加 "**SIMT host 契约**"：SIMT host tiling 必配 `context->SetDynUBufSize(usableUb)`（默认 0 = 不声明；旧名同函数），usableUb = 平台 UB − DCache − 静态预留，与 device TPipe 分配同一数；split 的 ubFactor / buffer-kernel 的 UB 预算以该值为上限。

**`.claude/skills/ascendc-op-dev-coding-regbase/references/per-substage-selfcheck.md` §B2**
- 追加自检行 7：结构信号判 SIMT → `*_tiling.cpp` 须有 `context->SetDynUBufSize(...)`（不写废弃旧名），缺即 fail 提示就地改（host 私有化决策 = device 分配，见 simt skill workspace-contract §3）。

### 3. 记录

**`docs/plan/simt-host-dynubuf-guidance/`** 新建 `01-problems.md`(L1) / `02-analysis.md`(L3) / `03-impl.md`(L4)；L2 `00-status-summary.md` 追加一条（引用本 workdir + 关联 simt-ub-window-misconception）。

## 验证

1. 残留扫描：`.claude/skills/ascendc-simt-operator-design-patterns/` 内 `SetLocalMemorySize` 每个残留均属「verbatim 主线仓片段」或「与 SetDynUBufSize/废弃桥接成对出现」→ 已人工核对无裸旧名教学。
2. 编译面核验：CANN 9.1 头文件 `exe_graph/runtime/tiling_context.h` 确认 `SetDynUBufSize` 存在且 `SetLocalMemorySize` 为 deprecated wrapper（L494-509）；平台 UB 取数 API `op_common/op_host/util/platform_util.h` 的 `Ops::Base::GetUbSize(context)` 存在。
3. 无 Python 改动 → 跑 skill 契约相关 UT（skill_config 等）确认无回归。
4. 不做真机实证（D2=B，用户拍板）；后续如需实证参照 `simt-ub-window-misconception` 探针 + cann_bench gather 改 host 调用的实验设计。

---

## 阶段 B：路径 1（isolated VF 测试）窗口放大工具缺口闭合（2026-09-02）

> 承接用户确认"路径一缺口补上"：SingleOperatorLaunch 此前不暴露 `simt_share_memory_size`，isolated VF 测试无法放大 SIMT 窗口。

### 改动

**`.claude/skills/regbase-vf-test/SingleOperatorLaunch/source_module.py`**
- 新增模块级 `_make_launch_args(...)` seam：统一构造 `LaunchKernelArgs` 并解析 `simt_share_memory_size`（`None`/`0` → 0 → RTS 8KB 兜底；`<0` → `ValueError`）。
- `_KernelFunction.__call__` / `profile` / `SourceModule.__call__` 增可选参数 `simt_share_memory_size=None`，两处原始 `LaunchKernelArgs(...)` 直构（__call__ 主路径 + profile 主循环）改走 `_make_launch_args` 透传；profile 的 warmup 循环同步转发。

**`.claude/skills/regbase-vf-test/SingleOperatorLaunch/tests/test_launch_args.py`**（新增，8 用例）
- `_make_launch_args` 纯 seam：默认解析 0 / 显式转发 / 0 合法 / 负数抛 ValueError。
- 三个公开入口签名均含 `simt_share_memory_size`（inspect 守卫）。
- fake device/diag 下 `__call__` / `profile` 实际转发进 `LaunchKernelArgs.simt_share_memory_size`。

**`.claude/skills/regbase-vf-test/references/vf_experiences/gather-scatter/experience-simt-async-infra.md`**
- "SIMT 共享内存窗口"节补"工具支持"：三个公开入口均支持该 kwarg、默认 None/0→8KB、`<0` ValueError；
- **对策**给出直接调用示例 `func(..., simt_share_memory_size=65536)`；坑表行对策更新。

### 验证
1. `pytest SingleOperatorLaunch/tests`（PYTHONPATH=ops-test-kit + skill 目录）：**71 passed**（含新增 8），无回归。
2. 真机 smoke（Ascend950DT/CANN 9.1.0，`/tmp/opencode/simt_ub_probe/sol_simt_param_smoke.py`，复用 ub_probe_custom 64KB pool）：默认 `None`→8KB 仅部分正确 + VEC_ERROR；显式 `simt_share_memory_size=65536` → **64KB 全窗口 PASS**。证明公开 kwarg 端到端生效。
3. 探针脚本保留 `/tmp/opencode/simt_ub_probe/`（不入仓）。
