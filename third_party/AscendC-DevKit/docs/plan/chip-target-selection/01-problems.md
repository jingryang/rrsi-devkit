# L1 — chip 目标代际选择：问题记录

> 本层只记客观事实（哪里坏 / 凭什么这么说），不提方案、不排顺序、不写决策。
> 方案见 `02-analysis.md`（L3）；步骤索引见根目录 `skills-integration-and-tdd-plan.md` step-34（L2）。
> 相关已结工作：`chip-gate-precondition/`（step-32，chip-match 前置条件化）、`chip-version-generation/`（step-17，canonical A2/A3/A5 + `to_soc_version`）。

## P1 — 一致性 gate 触发过晚，target≠hardware 时上游设计全废才 halt
**事实**：chip-match gate（step-32 落在 `codegen.validate_inputs` 作主 gate、`Deployer.deploy` 作深防第二入口）在 pipeline 顺序里位于 `requirement → 概设 → 详设 → test_design` **之后**。target≠hardware 要等到 codegen 前置检查才被拦——此时需求分析、概设、详设、测试设计四段产物已全部产出。用户测试复现：A2 机指定 A5、到 codegen 才发现、设计全废。
**凭据**：pipeline 注册的 stage 顺序（entry → context → requirement → design 组 → test_design → codegen_init → codegen → …）；`chip_mismatch_reason` 仅两处调用点（codegen.validate_inputs、Deployer.deploy），均在 design 组之后。

## P2 — design_target_chip 字段 + 转正逻辑存在但被 schema 缺口架空（wired-but-undriven）
**事实**：`Constraint.design_target_chip` 字段（domain 层，hardware-kind constraint）与 `RequirementStage.transition` 里 `_apply_design_target_chip` 转正逻辑（把 design_target_chip 覆盖进 `state.target_chip` 并重建 RunContext.hardware_target）都已写好；但 requirement **机器校验 schema** 没有该字段（required_keys 仅 op_name/inputs/outputs），**人读 schema** 有一个 top-level `target_chip` 但词表是过期的 Ascend310P/910A（非 canonical A2/A3/A5）且位置在 op_spec 顶层（domain 期望在 constraints 里）。解析走 `filter_known_fields` 且路径不匹配 → 即便 agent 按人读 schema 产出，也不会被当作 design_target_chip constraint 消费。
**凭据**：机器校验 schema 的 required_keys 与 constraints example；人读 schema 的 target_chip enum + 位置；domain `Constraint.design_target_chip`；`_apply_design_target_chip` 转正点。

## P3 — 单字段 target_chip 把「设计目标」与「构建/运行目标」压成一个值，靠 silent override 切换
**事实**：state 只有一个 `target_chip` 字段，多来源（CLI `--chip-version` / dispatcher 探测 / profile `default_chip` / design_target_chip 覆盖）。`design_target_chip` 在 requirement 阶段经 `_apply_design_target_chip` 覆盖 `target_chip`——**有日志**（`Logger.info` 记录生效、`Logger.warn` 记录降级），但日志与字段都压成**单值**，无确认通道。「为哪个代际设计」与「为哪个代际构建/运行」两个可能不同的语义在单字段里无法分别表达：override 覆写后，原 design 意图被运行值抹掉，读者无法从 state/日志还原「设计目标是 A5、但本机是 A2」这一双值事实。
**凭据**：`state.target_chip` 单字段定义及其多来源注释；`_apply_design_target_chip` 覆盖动作（有 info/warn 日志，但日志与字段均为单值，无法承载双语义）。

## P4 — --assume-chip 一个 flag 同时顶替硬件侧与（经泄漏）target 侧，gate 退化为恒等式
**事实**：`--assume-chip` 落 `state.assume_chip`，被 `detect_chip_version` 当作「探测到的硬件」直接返回（跳过探机）。当 `--chip-version` 缺失时，`target_chip` 的兜底解析**复用同一个 `detect_chip_version`** → assume_chip 同时污染 target 侧。结果「只传 `--assume-chip A5`」时 target(A5) == 硬件侧(A5)，gate 退化为恒等式，真实硬件若是 A2 也放行，到 deploy/run 才炸。
**凭据**：`detect_chip_version` 的 assume_chip 短路返回；`chip_mismatch_reason` 把 assume_chip 作 hardware 侧（docstring 明示 “hardware side of the comparison”）；dispatcher `resolved_chip` 兜底复用 `detect_chip_version`。

## P5 — 探机在 missing-hardware 下静默伪装 A2，与「探机为最高真相」矛盾
**事实**：`_probe_chip_blocking` 对 torch_npu 缺失 / 0 设备 / 未知设备名**一律 `return _FALLBACK_CHIP`（A2）**。「没有硬件」与「真的是 A2」在探机输出里不可区分。`EnvironmentProbeTimeout` docstring 引 §3.7「never silently fall back to a guessed chip」只防 driver hang，未防 missing-hardware 这类 ordinary error——同一原则两类错误口径不一致。
**凭据**：`_probe_chip_blocking` 的三处 fallback 分支（import 失败 / device_count==0 / 无关键字匹配）；`_FALLBACK_CHIP = A2`。

## P6 — 当前模型无法干净承载跨代设计（已确认真需求）
**事实**：用户确认跨代设计（如在 A2 机上产出 A5 的设计/产物、拿到别处跑）是真实需求。当前单 `target_chip` 字段 + 探机锁定的运行 gate，无法同时表达「设计目标代际（A5）」与「本机硬件代际（A2）」两个独立且可能不同的值——跨代设计要么被运行 gate 当 mismatch 拦下，要么靠 silent override 糊过去。
**凭据**：用户确认（2026-07-10）。
