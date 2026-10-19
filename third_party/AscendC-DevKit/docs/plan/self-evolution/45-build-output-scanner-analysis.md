# 41 — 第5类隐患根治：build 输出扫描器（L3 方案分析）

> 工作线：self-evolution（六算子批跑收口）
> 状态：**已拍板冻结 + 已实施**（2026-07-13）；UT 1885 绿，ST 非 heavy 101 passed（2 预存失败与本方案正交）
> 关联 L4：`45-build-output-scanner-impl.md`；L1：`batch-sixops-runlog.md` 第481行 第5类隐患
> 上游 plan：`/root/.claude/plans/lovely-painting-aurora.md`

## 问题（L1 事实引用）

cann-bench `build_run.sh` 的 `cmake --build --target binary || { echo WARNING; }` 把 **kernel 编译失败吞成 RC=0**——`.run` 包仍产出（host .so + opp 注册不依赖 kernel bin），devkit `deploy.py:_run_command` 在 RC=0 分支 `return True, "", None` **丢弃整个 stdout**（含 `error: no matching function for call to 'Cast'`）且不落盘，smoke（aclnn kind 空操作，deploy.py:361-365）不验 kernel bin → `smoke_passed=True`（**假阳性绿灯**）。codegen in-session 自修循环（agent 自己 redeploy、读 `subprocess/*.log`、改码）因此**收不到失败信号**，从不修 kernel → kernel 0 bin → eval 全 0。

CEL 是唯一中招者（0/20）：codegen 产出 5 处 AscendC API 签名错（Cast×3 + DataCopyPad×2），6 tiling_key 全 not generated。

### 证伪：系统性盲区，非 CEL 特例

代码逻辑决定 **kernel 编译失败永远不会触发 `smoke_passed=False`**（被 `||` 吞成 RC=0 + run_pkg 仍产出 + smoke 空操作 = True）。6 算子对照（最终批 smoke 演化 + cann-bench eval 三维度分数）：

| 算子 | smoke演化 | compilation | function | performance | 结论 |
|---|---|---|---|---|---|
| CEL | F T⁶ | **0** | 0 | 0 | kernel 编译失败=盲区；build_ascendc.log 仅第1次落盘，后续6次RC=0未落盘 |
| rms_norm | T F³ T | **20** | 12 | 10 | kernel 编译满分，丢分在精度（数值），与盲区正交 |
| foreach_norm | F² T³ | 19 | 28.5 | **0.57** | 丢分在性能；1失败case是运行时EZ1008非编译失败 |
| moe/DQ/swi_glu | — | ≥19 | — | — | kernel 全编译成功 |

**rms_norm 是最干净反例**：compilation=20 满（零编译失败）+ function=12 低（8/20 精度），证明精度问题与 build 盲区正交。其他算子"分数不高"分别在 function（精度）/performance（性能）维度，盲区只伤 compilation 维度。

**精确丢失点 = `deploy.py:332`**：RC=0 时 `_persist_subprocess_output` 不被调用 + stdout 丢弃。

## 选项

### A. 修 cann-bench `build_run.sh` 去掉 `||`
- 缺点：`build_run.sh` 属 cann-bench 仓（非 devkit），devkit 不该跨仓改；`||` 可能是 cann-bench 有意设计（容忍部分 kernel 失败以产出 package 供 host 侧测试）；即使改了，devkit 不能依赖外部仓的修复（§1.7 自闭环）。

### B. 在 cannbench-adapter 重做等价 build.sh 让 codegen 调用
- 缺点：违反 §2.5（第二 build 通路）/ §1.5（路径硬编码）/ §2.7（build 脚手架属非核心，应外移给 LLM 现场参考目标仓，不写进 skill/工具）/ §1.1（adapter 层重做 build 越层）。等于复制一份 build 逻辑进 devkit，长期双轨。

### C. 扩 DeployResult 加 `kernel_compile_failed` 字段 + 改 transition 路由
- 缺点：多余——`smoke_passed=False` 已足够让 transition halt（output_contract 满足 → is_terminal）；扩字段 + 改 transition 把编译原文喂回 agent 违背 B5/B1 设计（跨 stage build 回路已显式移除，build 修复 100% 走 in-session 自修）；改动面大（verification + transition + codegen prompt 三处）。

### D. build 输出扫描器（`deploy.py:_run_command` RC=0 分支扫描）✅ 选定
- 落点：新建 `domain/build_log_scanner.py`（纯函数）+ `deploy.py:_run_command` 在 RC=0 且 `stage.role=="build"` 时扫描 stdout+stderr，命中 kernel 编译失败信号 → 视为 build 失败，**复用现有 RC≠0 通路**（`_persist_subprocess_output` 落盘 + 返回 False + `_err`）。
- 优点：最小改动（1 新纯函数模块 + 1 处分支）；复用全部现有反馈通路（`_run_profile_chain` build 循环 `if not ok` → `_err` → `DeployResult(smoke_passed=False)` → redeploy CLI 返回 agent → agent 读 `subprocess/*.log` 自修），**零改动 codegen/transition/DeployResult**；契合 B5/B1（不改 in-session 自修机制，只让它"看见"被吞的失败）；§2.5 单通路（不新增第二条反馈路径）；扫描的是 CANN 工具链诊断模式（asc_opc/TBE/clang）非算子知识（§1.5 不冲突）。
- 缺点：正则清单需随 CANN 版本演进维护——但信号是工具链稳定输出（clang `error:` / `Op[..] compile failed`），漂移概率低，且有 UT 守护（真实 `/tmp/cel_build.log` 片段作 fixture）。

## 决策

**D（scanner）承担根治**。组合理由（§1.2 四把尺子）：
- **可维护**：在信号丢失的精确点（deploy.py:332 传感器失明）加真传感器，维持「build 失败必须落盘 + 返回 False 让自修循环捕获」的不变式；不改 in-session 自修机制（B5/B1）。
- **可扩展**：同类情况（任何算子 kernel 编译失败被 `||` 吞）自动归位，不需逐算子打补丁；扫描器是 build role 通用传感器。
- **可诊断**：命中即落盘全文 + summary 带 op 名/文件:行/编译器原文，agent 在 redeploy CLI 输出就能看到要点（不打开全文也知道改哪）；错误不再被 RC=0 静默吞掉推迟到 eval 全 0 才暴露。
- **架构合理**：纯函数扫描器落 domain 层（§3.8 UT 测纯逻辑）；调用点落 deploy stage 的 `_run_command`（产物校验层，build 产物的合法性校验）；不越层到 codegen/transition/verification。

### 与既有方案的关系
- 与 P10（方案38，schema 参数名 fidelity）正交：P10 修「schema 名→关键字调用」桥接；本方案修「kernel 编译失败信号→自修循环」传感器。两者都是 codegen→cann-bench 链路的盲区，但落点不同（桥接层 vs deploy 传感器）。
- 与前4类隐患（path-read/artifacts-relay/glue-ghost/by-design-aclnn）正交：前4类是评测链路 bug，本方案是 build 反馈链路盲区。
