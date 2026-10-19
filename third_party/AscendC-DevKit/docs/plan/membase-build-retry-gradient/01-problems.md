# Membase codegen build-retry 空转与方法论缺失 — 问题记录（L1）

> 纯事实快照（哪里坏了 / 凭什么这么说）。不提方案、不排顺序、不写决策。
> 来源：批跑 run `20260801-231442-5438ad` 下算子 `multi_add_rms_norm_dynamic_quant`
>（工作区 `20260801-231442-2bc384`）的 codegen transcript
> `agents/ascendc-coder-01.jsonl`（974 turn）+ 框架源码。相关 RCA 记忆
> `multi-addrmsnorm-rca-2bc384`、`batch-205112-codegen-precision-halts`。

## P1 — Membase codegen 的 build-retry 发生在 agent in-session，框架不可见、不可干预

**现象**：codegen stage 一次 spawn `ascendc-coder` 后，agent 在**同一会话内**自跑
`ascendc-devkit redeploy` 循环（最多 `max_rounds` 轮）自修编译错误；框架的
`actions(state, iteration)` 在这一次 spawn 内不介入每一轮 build-retry。

**证据**：
- `codegen.py:1199-1219`（in-session 循环 prompt）：「读完整编译/smoke stderr 自修 → 改码 →
  git commit → 再 redeploy，直到 smoke 通过或达 {max_rounds} 轮」。
- `codegen.py:74` `default_max_iterations = 40`；`codegen.py:927-940` `_max_rounds` 借
  `--max-iterations` 作为 in-loop 轮上限。
- transcript 实测：`ascendc-coder-01.jsonl` 共 **974 turn**、**244 次编译失败**（turn 41→959
  几乎全程在编译失败里），全部发生在一次 spawn 内；伴随 **27× `ascendc-devkit redeploy`** +
  **25× git commit**。
- run `20260802-171400-794e81`（commit `014707a0`，**已含阶段 1 + 阶段 2 的 deploy 层
  footer / classify / gradient**）codegen transcript：**726 turn / 153× `ascendc-devkit
  redeploy`**，仍全部发生在一次 spawn 内。相较 2bc384（974 turn）turn 数下降——阶段 2 的
  footer 让 agent 看到了错误分类与 gradient；但「build-retry 循环在 agent in-session」的
  本质未变，框架对每一轮 build-retry 仍不可见、不可干预。

**影响**：框架无法对每一次编译失败施加「重试策略 / 错误分类 / 换策略 / 升级」；244 次失败里
同一签名错反复出现即「同策略盲重试」，框架全程不知情、无法介入。794e81 进一步表明：即便
deploy 层 footer 把分类 / gradient 送达 agent，循环主体仍在 agent 会话内——框架不可见的
根因（P1）未被触及。

## P2 — 编译失败不进 `state.last_error`，框架级重 spawn 也拿不到编译错误

**现象**：codegen `transition` 写入 `last_error` 的路径全部是**结构/契约错误**，不含编译/签名错误；
smoke 未过（即编译失败）的路径显式设 `last_error=None`。

**证据**：
- `codegen.py:1416-1437` `callable_target missing` → `error_type="incomplete_output"`；
  `codegen.py:1448-1474` torch_op `symbol mismatch`；
  `codegen.py:1476-1497` `Missing expected sections`；
  `codegen.py:1500-1518` `no last_deploy.json`（`error_type="deploy_failed"`）。
  以上无一为编译/签名错误。
- `codegen.py:1520-1543`（step-84 D4）：smoke 未过 → `last_error=None`，带 `deploy_result`
  继续往下（不 halt、不重 spawn）。

**影响**：任何「基于 `state.last_error` 注入失败反馈」的修法（如本轮初版 OPT-A 设想的
`_build_codegen_prompt` 注入）对编译失败**无效**——即便框架重 spawn codegen（iteration>1），
`last_error` 也不含编译错误，打不到 244 次失败的真实位点。

## P3 — Membase 失败恢复无错误分类、无重试梯度、无签名重查

**现象**：in-session 循环 prompt 只说「读 stderr 自修 → 改 → 重试」，无错误分类、无
error→strategy 映射、无强制的签名重查；编码前查签名的指令是 LLM 自觉步骤、可跳过。

**证据**：
- `.claude/agents/ascendc-coder.md` 仅 28 行，方法论极简（「首条消息注入技能方法论，按其流程执行」
  + 编码前查 `ascendc-dev-knowledge` INDEX.md）。
- `codegen.py:1199-1219` 无分类 / 无梯度 / 无升级判定。
- transcript 实测 244 次编译失败的签名类聚类：`no matching function for call to 'ReduceSum'`×10、
  `'Sqrt'`×6、`'Round'`×6、`'ReduceMax'`×3、`static_assert SupportType`×8、`tilingkey`×8、
  `ListTensorDesc '__gm__ uint8_t* → T**'`×7 —— agent 凭记忆猜签名、不去查权威签名，反复在同一
  API 上失败。
- **对照组（Regbase 路径）有完整方法论**：`classify_compile_error.sh`（C-SYM/C-TYP/C-DUP/C-LNK/C-API
  5 桶）+ `references/error-handling.md`（类→策略表）+ `ascendc-dev-s5-compile.md:112-122`
  retry-gradient（1st 同策略→2nd 换策略→3rd FAILED）+ 持久化重试预算
  （`meta.json` `retries.stage5_compile.used/.limit`，`min(3, 30-N)`）+ 稳定性约束 E(t)>10→升级。
  Membase 路径无任何对应物。

**影响**：失败恢复本质是「读错误 → 凭记忆改」，同类错误反复；无「换策略」触发、无升级机制
（除 `max_rounds` 耗尽）。

## P4 — 框架对 in-session 循环的唯一可达通道是 agent 读的 `subprocess/*.log`

**现象**：框架不能注入每一次 in-session 迭代，但 agent 每轮都被 prompt 指引去读落盘的
build 日志。

**证据**：`codegen.py:1211-1212`「读完整编译/smoke stderr 自修（已落盘在 `{run_dir}/subprocess/*.log`）」；
`deploy.py:_persist_subprocess_output` 把 build 的 stdout+stderr 落盘到
`<run>/subprocess/<role>_<stage>.log`。

**影响**：框架要向 in-session 循环传递确定性信息，唯一通路是富化该日志（这条事实是「阶段 1」
得以生效的根据；但日志富化只解决「信息到位」，不解决 P1/P3 的方法论空缺——分类/梯度/升级仍无法
确定性执行，需把 build-retry 移到框架级）。

## P5 — compaction 抹掉 agent in-session 已达成的 smoke-passed / 攻坚里程碑（794e81 新增）

**现象**：codegen agent 在单个 in-session 会话内跑长 build 循环时，上下文累积触发 opencode
自动 compaction（上下文压缩）；compaction 后 agent 重新声明 Objective，**此前已达成的关键
里程碑（如「smoke 已通过、准备 commit」）从上下文丢失**，agent 从零重做已完成的工作。

**证据**（run `20260802-171400-794e81`，726 turn，4 次 compaction @ turn 111 / 309 / 500 / 687）：
- turn 308 agent 文本：「**Smoke passed!** Now let me verify the deliverables and commit」
- turn 309 compaction
- turn 310 agent 文本：「## Objective - Generate AscendC code for MultiAddRmsNormDynamicQuant
  ... redeploy until smoke passes」（从零重声明目标，丢失「已 smoke passed」）
- 最终到 **turn 720** 才再次 SMOKE PASSED——中间约 410 turn，在 compaction 抹掉「已通过」
  状态后重新攻坚 aclTensorList 解包 / Cast bf16 UB 等此前已解决过的问题
- 4 次 compaction 模式一致：每约 180 turn 一次，每次后均触发 Objective 重声明

**影响**：in-session 循环的「状态」全在 agent 上下文，compaction 是结构性丢状态源。阶段 1 / 2
的 deploy 层 footer 通道（P4）只能把**当轮**编译错误 / gradient 送进上下文，保护不了**跨轮的
里程碑达成**（smoke 是否已过）——那是 agent 的上下文记忆，compaction 一压就没了。agent 因此
重复已完成的攻坚，是 794e81 codegen 158min 里最大的一块浪费。
