# L1 — chip_version 命名代际化:问题记录

> 本层只记客观事实(哪里坏 / 凭什么这么说),不提方案、不排顺序、不写决策。
> 方案见 `02-analysis.md`(L3);步骤索引见根目录 `skills-integration-and-tdd-plan.md` step-17(L2)。

## P1 — chip_version 命名词表繁多且不对齐
**事实**:同一颗芯片在工程不同层用不同名字——CLI / profile 传 soc_version 风格名,_detect_ 用数字代际,run_context `_CHIP_SPEC_FILE` 用 spec-family 名,ascend-hardware SKILL 的 PCI 表用 A2/A3/A5,概设 common_knowledge 用架构代 A3/A5。多套词表从未对齐。
**凭据**:四处 key 互不匹配——detect 的数字代际、run_context 的 spec-family key、profile 的 soc_version 风 default_chip、SKILL PCI 表的 A2/A3/A5。

## P2 — 双词表漂移导致 hw_params 接地丢失(cann-bench e2e WARN)
**事实**:cann-bench self_evolve e2e 日志出现 `chip_version 'ascend950' has no chip-spec mapping; hw_params unverifiable` WARN。运行时 chip_version 来自 detect/profile/CLI 用 `ascend950`,而 run_context spec 映射的 key 用 `ascend910_95xx`(spec-family 名)——两套词表不对齐,查不到 spec → 静默丢硬件参数接地,tiling 设计失去 UB 真值依据。
**凭据**:cann-bench e2e 运行日志 WARN 行;spec 映射 key 命名与运行时 chip_version 来源不一致。

## P3 — detect 误识 910B 为 A3 + 缺 910C 关键字
**事实**:detect 的显示名/docstring 把 910B 叫 "A3"(与 ascend-hardware PCI 表 910B=A2 冲突);且 device 关键字表没有 910C(A3)entry,910C 会被 substring `Ascend910` 误判成 910B。
**凭据**:detect 旧显示名映射、device 关键字表(无 910C entry)。

## P4 — common_knowledge 代际标签错配(910B 挂 A3)
**事实**:概设 common_knowledge 平台速查章节标题 `### A3 (910B / 220x)` 把 910B 归到 A3 代际下,与代码 canonical(A3=910C)字面冲突。该 "A3" 实指 Membase/SIMD 架构代(含 910B+910C),但标签与 canonical A3=910C 混淆,读者无法判断 "A3" 指 910B 还是 910C。
**凭据**:common_knowledge 旧 `### A3 (910B / 220x)` 章节标题。

## P5 — UB 硬编码散落 patterns,多源副本漂移
**事实**:概设 patterns(atomic/fused)的"平台相关设计考量"表格普遍硬编码 `UB 容量（~192KB）`、A5 行 `UB 更大（248KB）`,与 common_knowledge 顶部 P24 单源声明("不再硬编码具体数值,读 hw_params.json")相悖;历史上曾因多源副本出现 192/240/248/256KB 四值并存。
**凭据**:patterns 表格 UB 行(common_knowledge 顶部已声明单源,但 patterns 仍存硬编码数值)。

## P6 — 真实内核 ST 曾被 ASCEND_TOOLKIT_HOME 指向过期 CANN 9.0.0 阻塞(已解决,环境配置类)
**事实**:cann-bench `bash build.sh --soc=ascend910b` 编译 C++ 插件时失败,报 `acl_rt.h:3523: 'aclmdlRITask' was not declared in this scope`(4729 是级联次生)。根因是**编译头版本分叉**:`ASCEND_TOOLKIT_HOME` 被解析成过期的 `/usr/local/Ascend/cann-9.0.0`(`ascend-toolkit/latest → cann → 9.0.0`,叠加 `~/.bashrc` line 101 source `cann-9.0.0/.../ascendnpu-ir/bin/set_env.sh` 再次覆盖),编译吃 9.0.0 旧头,其 `acl_base.h` 不含新类型 `aclmdlRITask`;而 torch_npu 运行时链的是已装的 CANN 9.1.0-beta.3(故 `a+a` 真机算子正常)——**编译 toolkit-home 与运行库版本分叉**,非 torch_npu 缺陷、非 DevKit 代码缺陷。显式 `source /usr/local/Ascend/ascend-toolkit/cann-9.1.0-beta.3/set_env.sh`(`ASCEND_TOOLKIT_HOME` 指真 9.1.0)后,构建全通(产出 whl+run),`TestNPURunnerRealExecution` 4/4 通过(113s)。
**凭据**:编译首因 `acl_rt.h:3523`;`aclmdlRITask` typedef 在 `acl_base_rt.h:47`,9.0.0 头链缺失、9.1.0 头链完整;真机 `torch.randn(3,4).npu()+自身` 输出正常(运行库 9.1.0 可用);修正 `ASCEND_TOOLKIT_HOME` 后 build + 4 ST 全绿。**教训**:见 [[toolkit-home-compile-runtime-version-split]] —— 编译头版本(ASCEND_TOOLKIT_HOME)可静默指向过期 CANN,而运行库用正确版本,表现为"真机算子正常但算子仓 C++ 编译报未知类型"。
