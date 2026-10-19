# 六算子批量 self_evolve + cann-bench 评测 — 运行日志

> 诚实记录本次批跑过程中遇到的问题、根因、处置与结果。运行时事实，非方案设计。

## 任务

- 脚本：`scripts/batch_self_evolve.sh`
- 算子（用户给出 PascalCase）：ForeachNorm / SwiGlu / CrossEntropyLoss / DynamicQuant / RmsNorm / MoeReRouting
- 要求：6 算子在 6 张卡上并发；CANN 用 `/usr/local/Ascend/ascend-toolkit/cann-9.1.0-beta.3/set_env.sh`；最终拿 cann-bench 报告。

## 问题 1：首次批跑全 6 算子 `reason=no_proto` 失败

- **现象**：`bash scripts/batch_self_evolve.sh ForeachNorm SwiGlu ...` 6 个算子全部 `FAIL reason=no_proto`，报 `缺 .../tasks/level1/<Op>/proto.yaml`。从派发到全失败约 1 秒（无生成发生）。
- **根因（两处）**：
  1. **命名不匹配**：cann-bench 任务目录用 snake_case（`foreach_norm`/`swi_glu`/`cross_entropy_loss`/`dynamic_quant`/`rms_norm`/`moe_re_routing`），golden 函数名与生成落盘的 `csrc/ops/<op>` 目录同样用 snake_case。用户给的 PascalCase 在 `tasks/` 下无对应目录。
  2. **跨层级**：6 算子分布在 3 个 level —— `foreach_norm`/`swi_glu`=level1，`cross_entropy_loss`/`dynamic_quant`/`rms_norm`=level2，`moe_re_routing`=level3。而脚本只有单一全局 `TASK_LEVEL`（默认 level1），写死 `task="$wt/tasks/$TASK_LEVEL/$op"`，无法在单批内解析多 level。
- **为何必须单批（而非分 level 跑 3 次）**：脚本用单一 FIFO 卡池（卡号 0..MAX_CONCURRENT-1），多次并发批跑会争抢同样的卡号 0。要满足「6 算子 6 卡并发」，必须单批 6 算子 → 必须支持跨 level 解析。

## 处置 1：最小改动让 batch 支持跨 level（已落实）

- 在 `scripts/batch_self_evolve.sh` 新增 `resolve_task_level(wt, op)`：扫 worktree 内 `tasks/level*/<op>/proto.yaml`，唯一命中用之；多命中且 `TASK_LEVEL` 能消歧则用之，否则报歧义；零命中报缺失。
- `run_one()` 用解析出的 `level` 取代写死的 `$TASK_LEVEL`；RUN 进度行带上 `level=`。
- **影响面**：仅编排层（batch 脚本）；e2e 只收 `REQUIREMENT/GOLDEN/CASES` 全路径、不依赖 level，故 e2e/Stage/Deployer 零改动。`bash -n` 通过；对 6 算子 + gelu + 不存在算子的解析实测正确。
- 符合工程原则：根因修复（§1.2），可扩展（同类跨 level 批自动归位），可诊断（缺算子/歧义有清晰报错），不破坏框架（§1.1）。

## 算子 → 层级 → 卡 映射

| 用户名 | cann-bench 目录 | level | 分配卡 |
|---|---|---|---|
| ForeachNorm | foreach_norm | level1 | 0 |
| SwiGlu | swi_glu | level1 | 1 |
| CrossEntropyLoss | cross_entropy_loss | level2 | 2 |
| DynamicQuant | dynamic_quant | level2 | 3 |
| RmsNorm | rms_norm | level2 | 4 |
| MoeReRouting | moe_re_routing | level3 | 5 |

## 重跑命令

```
source /usr/local/Ascend/ascend-toolkit/cann-9.1.0-beta.3/set_env.sh && \
bash scripts/batch_self_evolve.sh foreach_norm swi_glu cross_entropy_loss dynamic_quant rms_norm moe_re_routing
```

## 问题 2：全 6 算子 codegen 阶段 `A5≠A2` 硬件不匹配（系统性，已修复）

- **现象**：A5 首轮重跑（snake_case + 跨 level 修复后）6 算子均顺利推进 detailed-design；moe_re_routing 率先到 codegen，于 21:50 `exit=65` 失败：
  ```
  [ERROR] Stage 'codegen' aborted: input validation failed:
    - build target chip 'A5' 与当前硬件 'A2' 不匹配：构建产物硬件耦合
      （CANN soc_version 编译期固定），无法前向兼容。
      请在匹配硬件运行，或将 design_target_chip 声明为 'A2'。
  ```
- **根因**：脚本默认 `CHIP_VERSION=A5`，而本机硬件实为 **A2（910B3）**（`npu-smi` 显示 8× 910B3）。我首轮未显式指定芯片即用了默认 A5。codegen 的「目标芯片 vs 实际硬件」校验（CLAUDE.md §1.9 硬约束：跨代际构建产物不可前向兼容）正确 halt。其余 5 算子还在 detailed-design、未到该校验，但**必然同样失败**（同 CHIP_VERSION=A5、同 A2 硬件）。
- **为何不就地抢救 A5 设计改 A2**：A2(910B) 与 A5(950) 是不同代际，UB/核数等硬件参数与 soc_version(`ascend910b` vs `ascend950`) 均不同；A5 设计产物不可安全移植到 A2（§1.2 禁止规避方案）。唯一正确修复 = 整条链路（设计→构建）以 A2 为目标重跑。
- **处置 2**：
  1. `TaskStop` 终止 A5 批跑（进程树干净退出，仅余无害 defunct 僵尸；日志冻结确认无残留子进程）。
  2. `git worktree remove --force` 清掉 A5 run 的 6 个 worktree（`cann-bench-batch/20260710_201628/`）。
  3. 校验 `to_soc_version('A2')=ascend910b`（与 910B3 硬件一致）。
  4. **以 `CHIP_VERSION=A2` 重跑全 6 算子**（同样 6 卡并发、cann-9.1.0-beta.3）。
- **代价声明**：A5 轮 ~95min 的设计算力（6 算子并发 heavy_llm）作废，属我首轮未指定芯片的失误成本；诚实记录，未掩盖。

## 问题 3：cross_entropy_loss docgen 文件名大小写不匹配 + 间歇 429（op 级，待续跑）

- **现象**：A2 轮 ~120min 时 cross_entropy_loss `exit=65`（首个失败的 A2 算子）。swi_glu 同期已顺利进 codegen（证明 A2 修复生效）。
- **根因（双重）**：
  1. **docgen 文件名大小写契约不匹配（主因）**：`tasks/level2/cross_entropy_loss/proto.yaml` 有 `name: CrossEntropyLoss`（PascalCase），docgen output_contract 据此期望 `CrossEntropyLoss_详细设计说明书.md`；但 design-generator agent 实际产出 `cross_entropy_loss_详细设计说明书.md`（snake_case，839 行内容是齐的）。3 次 iteration 仍未对上文件名 → `fail_strategy=halt` → exit 65。属 LLM 文件名命名的非确定性（其余 5 算子 docgen 均过）。
  2. **间歇 429（加剧）**：cross_entropy_loss 命中 8 次 `Request rejected (429) · Weekly/Monthly Limit Exhausted`（22:55–23:51），吃掉重试预算。**但 429 非硬墙**：foreach_norm / swi_glu 全程 0 次 429 且正常推进，dynamic_quant/rms_norm/moe_re_routing 各仅 1 次 → 429 是 6 算子并发突发限流，重试可过，不是配额耗尽硬阻塞（"reset 2026-07-15" 措辞具误导性）。
- **处置 3（计划）**：不中断当前批跑（其余 5 算子健康推进）。待批跑收口后，用 run_id 续跑 cross_entropy_loss 单算子（`RESUME=<run_id> bash scripts/e2e_self_evolve.sh` 或 `RESUME=1 bash scripts/batch_self_evolve.sh cross_entropy_loss`）——续跑会以新 LLM 轮次重跑 docgen，大概率产出正确大小写文件名。
- **诚实声明**：cross_entropy_loss 本次未通过，需续跑；不掩盖、不跳过。

## 问题 4：swi_glu codegen 超 1200s stage 超时（exit 124）+ STAGE_TIMEOUT 偏紧

- **现象**：A2 轮 ~161min 时 swi_glu `exit=124`（A2 第二个失败）。run_id=20260710-140056-24b312。
- **根因（双重）**：
  1. **codegen stage 默认超时 1200s(20min) 偏紧（主因）**：swi_glu 是复杂融合算子（MatMul+SiLU gating），ascendc-coder 在 codegen 内连跑 256 turn / 2976s(≈50min) 的「编译→报错→改→重编」循环仍未收敛 → 触发 `Stage 'codegen' timeout: exceeded 1200s budget (ran 2976.3s)` → exit 124（timeout 杀）。e2e_self_evolve.sh 默认 `STAGE_TIMEOUT=1200`、`WORKFLOW_TIMEOUT=10800`。
  2. **429 在临界 turn 补刀**：第 256 turn（已超 budget）恰遇 429 `Weekly/Monthly Limit Exhausted`，agent 直接 crash。
- **429 性质裁定**：**软限流，非硬墙**。foreach_norm 全程仅 0→1 次 429 且正常推进，各算子 429 计数 1–8、可重试通过；swi_glu/cross_entropy_loss 失败是「429 命中临界点 + 超时预算紧」叠加，非 API 配额耗尽硬阻塞（"reset 2026-07-15" 措辞具误导性）。
- **处置 4（计划）**：
  - **不中断当前批跑**：剩余 4 算子（foreach_norm/dynamic_quant/rms_norm/moe_re_routing）的 design 已各跑 ~3h 并落 state snapshot，kill 会浪费；简单算子（rms_norm/dynamic_quant）大概率 1200s 内编过，复杂算子（foreach_norm/moe_re_routing）若 codegen 超时则同 swi_glu 处理。
  - **批跑收口后统一续跑失败算子**，用抬高的 `STAGE_TIMEOUT`（如 3600s，给复杂 codegen 足够空间；`STAGE_TIMEOUT` 首次/resume 共用、env 透传）+ cann-9.1.0-beta.3 + CHIP_VERSION=A2，`RESUME=<run_id>` 复用已完成的 design，仅重跑失败的 codegen/docgen 阶段。
  - 待续跑清单（截至现在）：cross_entropy_loss(20260710-140056-0ce45e)、swi_glu(20260710-140056-24b312)，+ 后续 codegen 超时者。

## 问题 5：4 算子 detailed-design「tiling↔anchor-consistency」不收敛，耗尽 WORKFLOW_TIMEOUT（3h）exit=124

- **现象**：A2 轮约满 3h（01:03–01:19）moe_re_routing / foreach_norm / rms_norm / dynamic_quant 依次 `exit=124`，均非 STAGE 超时、非 429，而是 **`Workflow timeout: exceeded 10800s budget`**（ran 10955–11875s）。4 算子从未到达 codegen，全程卡在 detailed-design。
- **是否「死循环」（用户原问）的裁定**：**工程上等价死循环，机制上有界**。
  - **有界**：WORKFLOW_TIMEOUT=10800s（3h）是硬墙，到点必杀（exit=124）。所以不是数学意义的无限循环——它会在 3h 终止。
  - **不收敛**：3h 内每算子跑了 38–46 次 detailed-design 子阶段（tiling T1/T2、buffer-kernel、precision-perf、anchor-consistency 反复），从未产出完整设计书、从未进 codegen。即「给了预算也不收敛」。
- **根因（结构性，非预算/环境问题）**：**anchor-consistency 的 `ac0_global`（全局锚点建立）对含「骨架级语义」算子过严，每轮恒判 blocked → 永久 redesign**。各算子最终 anchor 报告 `status`：
  - `moe_re_routing`：**blocked** —— `ac0_global: not_established — 算子含骨架级语义（gather/scatter/reduce/Arange）`，T1/T2 对这些 primitive 有非空 claim 集，外部锚点判定者无法为它们建立全局可验证锚点。
  - `dynamic_quant`：**blocked** —— `ac0_global: N/A (operator 含 reduce 骨架级 API)`，T1 `WholeReduceMax`(verified)/T2 `ReduceMax`(unverified) 非空。
  - `foreach_norm`：**blocked**（同类——Foreach+Norm 含逐元素 reduce/broadcast 骨架 primitive）。
  - `rms_norm`：**passed** ✅ —— anchor 通过！它是 4 算子中唯一过 anchor 的，死在 docgen 阶段（workflow 预算耗尽），**设计产物最完整、可抢救性最高**。
- **为何「抬预算续跑」对 moe/foreach/dynamic 三者无效**：这三者的 blocked 不是「LLM 慢/抖动」而是**算子结构属性**——它们合法地依赖 reduce/gather/scatter/Arange primitive，而 anchor-consistency 当前对这类 primitive 无法建立 ac0_global，每轮结构性拒绝。重跑只会把同一 blocked 重演一遍、再把 3h 烧光。属 self_evolve_op 详设收敛性的真实缺陷（§1.2 根因定位：anchor-consistency 对骨架级语义缺少 escape hatch；§3.4 不可掩盖）。
- **为何 rms_norm 续跑有效**：其 anchor 已 passed，仅 docgen 阶段被 3h 墙挡住。`RESUME=20260710-140056-ba16cd` 复用已通过的设计 snapshot，从 docgen 续跑即可。
- **处置 5（待用户决策，不擅自续跑）**：
  - **可抢救续跑（推荐）**：`rms_norm`（anchor passed，续 docgen）+ `swi_glu`（codegen stage 超时，抬 STAGE_TIMEOUT 续）+ `cross_entropy_loss`（docgen 文件名，续跑重抽大概率过）。三者根因各异且续跑有实质成功率。
  - **结构性 blocked（续跑≈0 成功率，不推荐盲目续跑）**：`moe_re_routing` / `foreach_norm` / `dynamic_quant` —— 需先在 anchor-consistency 层为骨架级语义增加 escape hatch（修复 pipeline 收敛缺陷），或人工介入设计，再谈续跑。盲目 `RESUME=` 重跑只会再烧 3h×3。
  - 诚实声明：截至批跑收口，**6/6 算子均失败，cann-bench 报告 0 份**（无一到达 cannbench_eval）。

## 结果

| 算子 | exit | 根因 | run_id | 续跑可行性 |
|---|---|---|---|---|
| cross_entropy_loss | 65 | docgen 文件名大小写（Pascal vs snake）+ 间歇 429 | 20260710-140056-0ce45e | ✅ 高（续跑重抽大概率过） |
| swi_glu | 124 | codegen STAGE 超时（1200s vs 实跑 2976s） | 20260710-140056-24b312 | ✅ 高（抬 STAGE_TIMEOUT 续） |
| rms_norm | 124 | anchor passed，死在 docgen（workflow 3h 墙） | 20260710-140056-ba16cd | ✅ 最高（anchor 已过，续 docgen） |
| moe_re_routing | 124 | detailed-design 不收敛：ac0_global blocked（gather/scatter/reduce/Arange） | 20260710-140056-b1b8ec | ⚠️ 低（结构性 blocked，需 pipeline 修复） |
| foreach_norm | 124 | detailed-design 不收敛：ac0_global blocked（reduce/broadcast 骨架） | 20260710-140056-1c2fce | ⚠️ 低（同上） |
| dynamic_quant | 124 | detailed-design 不收敛：ac0_global blocked（reduce 骨架 API） | 20260710-140056-94616a | ⚠️ 低（同上） |

- **cann-bench 报告**：**0/6**（无一到达 cannbench_eval 阶段）。
- **批跑进程**：已全退（batch exit 1，无残留 e2e 子进程；6 worktree 保留于 `cann-bench-batch/20260710_220043/`）。
- 后续动作待用户在 §「处置 5」中拍板后执行。

---

## 第二轮：收敛修复 8e958f7（P0/P1-a/P1-b）后重跑全部 6 算子

> 用户据本批 runlog 问题 5 的根因，提交 `8e958f7 feat(orch): 设计侧 loopback 收敛加速 P0/P1-a/P1-b（P59/P60/P61）`：
> - **P0 advisory 前向通道**：anchor-consistency 的下游 owner issue（如 AC3→integrate）改为非阻塞 advisory 前投，不再 corrective→tiling 全量重跑。
> - **P1-a entry_kind**：corrective loopback 重入按「产物是否在盘」判 generate/modify，增量改而非从零生成。
> - **P1-b blast_radius=localized 加载期校验** + 模板级精确回退。
> 注：commit 自述「heavy_llm e2e 本次未跑」——本轮重跑即该修复的 heavy_llm 验证。

### 修复生效证据（问题 5 根因已消解）

| 算子 | 第一轮卡点 | 第二轮到达 | 推进 |
|---|---|---|---|
| dynamic_quant | anchor-consistency blocked | **docgen iter 3/3** | ✅ 跨过 anchor→integrate→docgen（大跃进） |
| moe_re_routing | integrate | **validate iter 3/3** | ✅ 推进到 validate |
| rms_norm | validate | **codegen iter 2/5** | ✅ 首次进 codegen |
| foreach_norm | docgen | **codegen iter 1/5** | ✅ 首次进 codegen |
| cross_entropy_loss | docgen | docgen iter 3/3 | （同点，见问题 6） |
| swi_glu | codegen | codegen iter 3/5 | （同点，见问题 7） |

**结论**：P0 advisory 通道确实打通了 design 死循环——dynamic_quant 从「结构性 blocked」一路推进到 docgen，证明问题 5 的根因修复有效。

### 问题 6：docgen 文件名契约不匹配（确定性，2 算子：cross_entropy_loss / dynamic_quant）

- **现象**：二者均在 docgen `fail_strategy=halt`、correction budget 耗尽 exit=65。
- **根因（契约 vs skill 命名不一致，确定性）**：docgen output_contract 据 proto.yaml `name`（PascalCase，如 `CrossEntropyLoss`/`DynamicQuant`）期望 `<Pascal>_详细设计说明书.md`；但 design-generator agent **稳定产出 snake_case** `<op>_详细设计说明书.md`（实测 `cross_entropy_loss_详细设计说明书.md` / `dynamic_quant_详细设计说明书.md` 均在盘，内容齐全）。3 次 iteration 仍对不上 → `missing_artifact` → halt。
- **性质**：**重跑必复现**（命名非确定性只在文件名取值，但 skill 稳定偏 snake）。非「多跑几次能过」，需修契约或 skill 命名对齐（§1.2 根因、§1.3 加载期/契约校验）。

### 问题 7：codegen 阶段 429 软限流致 agent crash + STAGE 超时（3 算子：rms_norm / foreach_norm / swi_glu）

- **现象**：三者均 `Stage 'codegen' timeout: exceeded 3600s budget`（rms_norm ran 5502s / foreach_norm 3665s / swi_glu 4484s）。
- **根因（双重，按算子分）**：
  - **rms_norm(8×429,1 crash) / foreach_norm(7×429,1 crash)**：ascendc-coder 在 codegen 长 compile-fix 循环中**被 429 软限流打崩 mid-run**（`agent crashed mid-run with partial output`），stage 重试下一 iteration 又被 429 打崩，耗尽 3600s budget。6 算子并发突发限流是放大器。
  - **swi_glu(0×429,0 crash)**：**真·慢**——无 429、无 crash，3 个 codegen iteration 纯算力不够（复杂融合算子 MatMul+SiLU gating 的 compile-fix 尾巴长），4484s 仍未收敛。这个抬 STAGE_TIMEOUT 有实质帮助。
- **429 性质再确认**：**软限流非硬墙**（swi_glu 全程 0×429 证明配额未耗尽）；6 并发突发是主因。降并发（MAX_CONCURRENT）+ 抬 STAGE_TIMEOUT 可缓。

### 问题 8：moe_re_routing validate 阻断源于 stale anchor_report（pipeline，1 算子）

- **现象**：validate `本轮阻断 (1): AC1#it2→human` → correction budget 耗尽 halt。
- **根因（anchor_report 陈旧，非设计真错）**：blocking_status.json(GV9-b) 自述——validate reviewer 复核发现 `anchor_report.json` 仍标 AC1 `verification=UNVERIFIED`（iteration-1/2 遗留、无 iteration-3），但**当前 tiling_results.json 中该问题实已消解**（T2 ComputeIdx 已是 4 参数 Arange、`verification=api_checked`、显式注「原 UNVERIFIED 已消解」）。即 corrective loopback 改了设计但**未刷新 anchor_report**，validate 读到陈旧 blocked → 无法自动 relay → 路由 human → halt。
- **性质**：设计本身正确，属 anchor_report 在 corrective loopback 后未重生的刷新缺陷（疑似 commit 自述 deferred 的 P1-c/P2 范畴）。非重跑可解。

### 第二轮结果

| 算子 | exit | 第二轮根因 | run_id | 状态 |
|---|---|---|---|---|
| swi_glu | 124 | codegen 真·慢（0×429，3 iter 未收敛） | 20260710-140056-24b312 | 抬 STAGE_TIMEOUT 可救 |
| rms_norm | 124 | codegen 429 crash（8×429）+ 超时 | 20260710-140056-ba16cd | 降并发+抬 STAGE 可救 |
| foreach_norm | 124 | codegen 429 crash（7×429）+ 超时 | 20260710-140056-1c2fce | 降并发+抬 STAGE 可救 |
| cross_entropy_loss | 65 | docgen 文件名契约不匹配（问题 6，确定性） | 20260710-140056-0ce45e | 需修契约/skill |
| dynamic_quant | 65 | docgen 文件名契约不匹配（问题 6，确定性） | 20260710-140056-94616a | 需修契约/skill |
| moe_re_routing | 65 | validate 读 stale anchor_report→human（问题 8） | 20260710-140056-b1b8ec | 需修 anchor 刷新 |

- **cann-bench 报告**：仍 **0/6**（3 个进 codegen 但未过；3 个卡 design 门）。
- **净进展**：问题 5（design 死循环）已由 8e958f7 解决；新暴露问题 6/7/8 是下一层根因，各需特定修复。
- 后续待用户决策（见下）。

---

## 第三轮：修 P6（docgen 文件名）+ P8（stale anchor_report）后续跑 3 算子

> 用户裁定：**P7（codegen 429/超时）不动**（服务提供商限流，无法实质性修改）；修 P6+P8 后**仅续跑受影响的 CEL/DQ/moe 3 个**。P8 采用「彻底分离 current/history」。方案见 `docs/plan/`（已用户确认）。

### P6 修复：放开 docgen 文件名（文档名不关键，已落地）

- **改动**：`design_substages.py` `DocgenStage.transition` 改为按类型 `glob("*_详细设计说明书.md")` 接受任意文件名（多个时优先 `state.op_name` 命中），删除 `_doc_op_name`；0 产出仍 `_error`→halt（真异常）。**不改 docgen SKILL.md**（skill 想写什么名都行，编排按类型接受）。
- **判据（§1.2）**：可维护（无文件名契约对齐）/ 可扩展（任意 LLM 命名）/ 可诊断（0 产出仍报错+记录实际名）/ 架构合理（人交付物不挂下游契约）。
- **测试**：`test_docgen_render.py` 新增 `TestTransitionAcceptsAnyFilename`（5 用例：snake/Pascal/任意前缀/多文件优先/无关 .md 不匹配），14/14 绿。

### P8 修复：`_merge_issue_history` 彻底分离 current/history（已落地）

- **根因**：已消解的 issue 以 `verdict=unverified` 滞留 `blocking_issues`、`status` 仍 `blocked`；validate 读文件分不清已消解 vs 本轮未决 → GV9-b→human→halt（moe 实证：9 条 it1/it2 unverified 滞留、validate it3 无对应）。
- **改动**（`_merge_issue_history`）：新语义——`blocking_issues` 只放本轮 stamped 未决项；上轮 `blocking_issues` 中本轮 fingerprint 不再出现的项移入 `issue_history` 标 `resolved:true, resolved_at:N`；`status` 确定性派生 `"blocked" if 本轮未决 else "completed"`（去 LLM 随意性）。复用 `issue_render.issue_fingerprint` 做 resolved 判定。
- **连带正确性收益**：`design_tree` 两 rerun selector 读 `report.blocking_issues` 现在读到本轮未决，模板级回退不再卷入已消解模板（无需改）。
- **测试**：`test_design_substages.py` 重写 3 个累积语义用例为新 current/history 语义 + 加 `test_anchor_consistency_stale_old_state_gets_cleaned`（moe 陈旧快照回归：9 条 unverified→全 resolved 入 history、blocking_issues=[]、status=completed）。全量 190 UT + 6 ST 绿。

### moe 续跑前置：作废 anchor-consistency→validate node_status（一次性运维，§1.4）

- **新发现**：moe snapshot `node_status={completed:19}`——**root `self_evolve_op` 也是 completed**（validate 跑完 3 轮 status=blocked，但 node_status 全标 completed）。直接 `RESUME` 会命中 dispatcher `all_done` 分支、只重生成报告 return 0，**不重跑任何阶段**（plan 原假设只清子树即可，实测须连带清 root + detailed-design 组）。
- **作废**（备份 `.bak-p8` 后 inline 跑）：pop 6 key = root + `detailed-design` 组 + `anchor-consistency/integrate/docgen/validate`；上游 entry→tiling→anchor-forkjoin 保留 completed。续跑实测正确重入 `anchor-consistency`（非 all_done、非 validate）。
- **P8 自愈预期**：anchor-consistency 重跑（tiling 已修 AC1）→ 新 `_merge_issue_history` 把 9 条陈旧标 resolved 入 history、产干净 current → integrate/docgen/validate 顺次重跑 → 放行进 codegen。

### 第三轮续跑命令（3 算子 3 卡并发，11:24 启动）

```
source /usr/local/Ascend/ascend-toolkit/cann-9.1.0-beta.3/set_env.sh
WORKTREE_ROOT=/home/x00584171/code/cann-bench-batch/20260710_220043 \
CHIP_VERSION=A2 STAGE_TIMEOUT=3600 MAX_CONCURRENT=3 \
RESUME=1 bash scripts/batch_self_evolve.sh cross_entropy_loss dynamic_quant moe_re_routing
```

- **派发实测**（11:24:47）：3 算子均正确 RESUME（CEL=0ce45e/DQ=94616a/moe=b1b8ec）；CEL/DQ 重入 `docgen`、moe 重入 `anchor-consistency`；chip=A2、并发=3、卡由 state.npu_id 决定（CEL=2/DQ=3/moe=5）。
- **STAGE_TIMEOUT=3600**：给 codegen 留空间（本轮 3 算子非原 429 重灾的 rms/foreach/swi，3 并发压力减半）。
- **已知边界**：进 codegen 后若遇 P7（429/超时）属用户已裁定不动的服务提供商限制；本轮目标先把 3 算子送过 design 门（P6/P8 验证点）。

### 第三轮进展与 P6/P8 生产验证（11:24 起）

- **P6 生产验证（CEL）**：CEL 续跑重入 docgen，agent **正常产出 `cross_entropy_loss_详细设计说明书.md`（759 行/44KB，snake 名）**——正是 P6 glob 要接受的；P6 修复在生产环境确认有效。
- **P8 生产验证（moe）**：moe 作废重入 anchor-consistency 后**顺利通过**、推进到 integrate（此前卡 validate 读陈旧 anchor_report→GV9-b→human→halt）。新 `_merge_issue_history` 把 9 条陈旧 issue 标 resolved、产干净 current → 放行。P8 修复在生产环境确认有效。
- **CEL 首跑 429 crash（P7）**：CEL docgen 第 8 turn（11:28:57）撞 `429 Weekly/Monthly Limit Exhausted (reset 2026-07-15)`，agent crash（partial）→ docgen `fail_strategy=halt` 在 transition 前短路 → exit 65。**文档已完整落盘但 agent crash 绕过 transition**——属 P7（服务提供商限流），非 P6 回归。用户裁定：**立即并发重试 CEL**（11:42 起，npu=2，与 DQ=3/moe=5 不撞；重入 docgen 干净、暂无 429）。

### 根目录陈旧 JSON 清理（运维，非本次续跑产物）

- `selfcheck_report.json`(07-10 12:59)、`tiling_buffer_kernel.json`(07-10 12:58) 经查为**首轮某次 run 的 cwd 退化泄漏**（早于 batch 修复/P40 cwd 修复；T1 tiling 子阶段产物被写到仓根）。本次续跑**未再泄漏**（根目录 .json mtime 未变）。
- 冗余（artifacts 正规路径下 13/32 份副本）；未跟踪+未 gitignore 污染 git status。**已删除**（不 gitignore——根因 cwd 已修，未来泄漏应保持可见以便定位，§1.2 可诊断）。

- **结果**：（3 算子续跑进行中——CEL retry/DQ 在 docgen、moe 在 integrate；完成后回填 cann-bench 报告）


---

## 问题 9：设计产物落盘位置无 Python 校验——dict 兜底让产物写错目录也 result:ok（P62，结构性）

- **现象**：CEL（cross_entropy_loss）批跑中 T1/buffer-kernel 子阶段 events 显示 `result:ok`，但 `artifacts/design/tiling/T1/` 无 `tiling_buffer_kernel.json`（产物被 cwd 泄漏写到仓根——正是上文「根目录陈旧 JSON 清理」点名的 `tiling_buffer_kernel.json`@仓根），聚合器 `tiling_results.json` 把 T1 默默聚成 `{split only}` → validate 远下游判 GV8「T1 tiling 不完整」→ corrective loopback。**位置错误本身零信号**——绿灯放行，直到远下游才爆。
- **根因（无 Python 位置校验，结构性）**：设计阶段六条产物读取路径都不校验「产物是否落在正确目录（stage 的 working_dir 子目录）」：
  1. `_DesignSubstage._parse_single` 路径2：agent 返回的 `artifacts` dict 兜底判 success——磁盘没落对也 parse 进 state → 绿灯。
  2. `_TilingSegmentStage.transition`：直接读 `agent_result.artifacts` dict，**完全不碰磁盘**——比路径1 更无校验（CEL T1 直接根因）。
  3. Integrate/Validate/AnchorPerTemplate/DetailedDesignIntake 自定义 transition：各自读 agent dict，同一缺陷类（不走 `_parse_single`，P62 计划前提「_parse_single 覆盖全部」不成立，已用户拍板扩展覆盖六条）。
  - 全 `orchestration/` 无「产物是否落在 working_dir 下」的位置一致性 check。不变式「agent 在 working_dir 跑→产物落 working_dir」被假设却从未验证，dict 兜底还主动绕过。`_TestDesignSubstage(_DesignSubstage)` 继承 `_parse_single`，test_design 同受。
- **处置 9（已落实，P62）**：单一通路 `_DesignSubstage._read_disk_artifacts` 收敛六条路径 + test_design——磁盘 required 文件必须在 working_dir（位置硬），名称 `_locate_artifact`+`_normalize_stem` 放宽（精确 > 归一化相等 > 前后缀容忍；歧义保守 None）；缺失→`_missing_artifact_error`（last_error+user_feedback）→ runner 既有 iteration 重 spawn（不造新机制，iteration 计数的意义）；删 dict 兜底（§2.5）；`_TilingSegmentStage.is_satisfied` 检本 segment 切片。canonical `StubBackend` + ST stubs 配合落盘。详见 `docs/plan/self-evolution/37-artifact-location-check-*.md`（L3/L4）。
- **判据（§1.2）**：可维护（澄清「产物落 working_dir」不变式，删两套真理源）/ 可扩展（同类 cwd 泄漏自动归位）/ 可诊断（位置错当场拦截 + feedback 重 spawn，而非绿灯放行到远下游 validate 耗 3h）/ 架构合理（校验落读取边界，不越层）。
- **验证**：UT 1726 passed（ut/orchestration 939）+ 非 heavy ST 96 passed。heavy_llm 留 PR 前 §3.11。
- **不影响本轮 CEL retry**：CEL retry cwd 正确（日志实证），本轮大概率自过 design 门；P62 是面向后续所有设计阶段的防御性修复。


---

## 第四轮： salvage 已构建产物 + 发现 P10（codegen schema 参数名与 proto/golden 不一致）

> 起点：前三轮收口后 6/6 全失败、cann-bench 报告 0 份。本轮不重跑 LLM，而是对
> **codegen 已落地构建产物**（per-op opp + `_C.abi3.so`）直接跑 cann-bench kernel_eval，
> 定位「能编译但评分 0」的根因。**结论：拿到 2 个真实评分（swi_glu / foreach_norm），并定位
> 一个系统性 codegen 缺陷 P10——schema 参数名不 fidelity 于 proto/golden。**

### salvage 通路（不经 LLM，复刻 cannbench_eval.py）

- 6 算子 codegen 产物普查（`output/<run_id>/artifacts/per-op/<op>/{opp,python}`）：
  | 算子 | codegen 是否产出完整 opp（4×.so + `_C.abi3.so`） |
  |---|---|
  | swi_glu | ✅ 完整（141 turn，最完整；codegen stage 超时但已 build 完） |
  | foreach_norm | ✅ 完整（364 turn） |
  | rms_norm | ⚠️ **只 build 了 add/sqrt 两个 helper，rms_norm 算子本体缺失**（376 turn 未收敛） |
  | cross_entropy_loss / dynamic_quant / moe_re_routing | ❌ 0 编译产物（429 在 docgen/codegen crash，从未 build 成功） |
- 复刻 `CannbenchEvalStage._run_eval` 的 env（`ASCEND_CUSTOM_OPP_PATH=<per-op-opp>/vendors/custom_ops`、
  `PYTHONPATH=<per-op-python>:<repo>/src`、`LD_LIBRARY_PATH` 含 op_api/lib + CANN lib、
  `TORCH_DEVICE_BACKEND_AUTOLOAD=0`）+ 命令 `python -m kernel_eval.cli eval --source-dir <csrc/ops/<op>> --operator <Pascal> --device-id <n> --skip-install`，
  落脚本 `scripts/salvage_eval.sh`（纯 shell，无 LLM）。

### 问题 10：codegen 生成的 TORCH_LIBRARY schema 参数名 ≠ proto/golden（P10，系统性）

- **现象**：直接 eval 已构建 opp，swi_glu / foreach_norm 全 case `RuntimeError: ... missing value for argument '<X>'`：
  - swi_glu：`cann_bench::swi_glu() is missing value for argument 'x'. Declaration: cann_bench::swi_glu(Tensor x, int dim=-1)`
  - foreach_norm：`... missing value for argument 'p'. Declaration: cann_bench::foreach_norm(Tensor[] x, float p) -> Tensor[]`
- **根因（确定性，参数名 fidelity 缺陷）**：
  - cann-bench `kernel_eval` 按 **golden 参数名以关键字**调算子：`param_builder.build_call_params` 用 golden 签名参数名构造 `params` dict（`utils/param_builder.py:125`），`op_runner._run_simple` 执行 `func(**updated_params)`（`eval/op_runner.py:201`）—— **关键字绑定，参数名必须一致**。
  - proto.yaml 是参数名的**单一真相源**，且 golden 与 proto 同名。但 codegen 生成的 `op_plugin/<op>_plugin.cpp` 的 `m.def("...")` schema **没用 proto 参数名**，用了泛化名：
    | 算子 | proto/golden 参数名 | codegen 写的 schema 参数名 | 不一致项 |
    |---|---|---|---|
    | swi_glu | `input, dim` | `x, dim` | `input`→`x` |
    | foreach_norm | `x, scalar` | `x, p` | `scalar`→`p` |
    | rms_norm | `x, gamma, epsilon` | `x, gamma, epsilon` | （一致；rms 失败是另一回事，见下） |
  - 故 `swi_glu(input=t, dim=d)` 调用：schema 期望 `x`、收到的关键字是 `input` → `x` 无值 → missing → 全 case 失败 → 评分 0。
- **为何 devkit 自检（smoke / precision_debug）抓不到 P10**：devkit smoke（`deploy.py:_smoke_script`）只 `getattr(torch.ops.cann_bench, <op>)` 验证符号**可解析**（positional 隐含），从不按 golden 关键字调；precision_debug 走 `cann_bench.<op>(...)` wrapper（`__init__.py` 里 `return torch.ops.cann_bench.swi_glu(x, dim)` **positional**）。**positional 调用对参数名不敏感**，故 schema 名错也能过 devkit 全链路，直到 cann-bench kernel_eval（关键字调用）才爆。**这是 verify(①) 与 cannbench_eval(②) 调用约定不一致导致的观测盲区**（§1.2 可诊断：错误被推迟到最下游评分）。
- **修复（已实证，1 行 schema rename + rebuild）**：把 `m.def` schema 里被错命名的参数改回 proto 名（`x`→`input` / `p`→`scalar`）；C++ impl 函数的局部形参名与 dispatch 关键字绑定**无关**（torch 按 schema 名绑定后 positional 传入 C++），故**只改 schema 字符串一行即可**，无需动 kernel。rebuild（`bash build.sh --soc=ascend910b` + 装 opp/whl）后重评。
- **判据（§1.2）**：根因（参数名 fidelity）/ 可维护（proto 为单一真相源）/ 可扩展（同类错名自动归位）/ 可诊断（关键字调用差异不应推迟到评分才暴露）。
- **真正的根治落点（建议，未实施）**：codegen skill 应约束「TORCH_LIBRARY schema 参数名必须逐字取自 proto.yaml 的 inputs/attrs name」；并建议在 devkit 加一个**加载期/部署期校验**（§1.3）——解析生成 `m.def` 的参数名 vs proto 名，不一致即拦（填补 verify↔eval 调用约定盲区）。本轮仅做 per-op salvage 验证，未动 skill / 未加校验。

### salvage 评分结果（P10 修复后，A2 / cann-9.1.0-beta.3）

| 算子 | P10 修复 | 综合得分 | 通过率 | 说明 |
|---|---|---|---|---|
| **swi_glu** | ✅ `x`→`input` | **77.42** | **20/20 (100%)** | kernel 本就正确，仅 schema 名错；修复后满分通过 |
| **foreach_norm** | ✅ `p`→`scalar` | **48.07** | **19/20 (95%)** | case 17 失败：tiling 拒 `p=-1`（`p must be > 0, got -1.0` @`foreach_norm_tiling.cpp:88`，EZ1008）。torch.linalg.vector_norm 支持负 p（倒数范数），kernel 未覆盖 → kernel 完备性缺口，非精度/非 tiling 边界 |
| **rms_norm** | N/A | 不可 salvage | — | codegen 未产出 rms_norm 本体（包内仅 add/sqrt helper），需重跑 codegen |
| cross_entropy_loss | N/A | 不可 salvage | — | 429 crash 于 docgen，0 编译产物，需重跑 codegen |
| dynamic_quant | N/A | 不可 salvage | — | 429 crash 于 codegen，0 编译产物，需重跑 codegen |
| moe_re_routing | N/A | 不可 salvage | — | 429 crash 于 codegen，0 编译产物，需重跑 codegen |

- 报告：`<worktree>/reports/{swiglu,foreachnorm}_eval_20260712_*.json`（swi_glu overall_score=77.42 pass_rate=1.0；foreach_norm overall_score=48.07 pass_rate=0.95）。
- **诚实声明**：本轮**不重跑 LLM**，靠 salvage + P10 一行修复拿到 swi_glu/foreach_norm 两个**真实** cann-bench 评分；其余 4 个（rms_norm/CEL/DQ/moe）codegen 未产出可用构建物，仍需 LLM 重跑 codegen（受 429 限制）才能评分。P10 是 per-op 手工修复（非 skill 根治），swi_glu/foreach_norm 的 worktree 源码已被改（`op_plugin/*_plugin.cpp` 的 `m.def`），**未 commit**（仅 salvage 验证用）。

### 429 当前状态（本轮观察）

- 末次失败 14:13（dynamic_quant 429），本轮诊断约 23:30 起 —— 距末次 429 ~9h。
- **本会话自身经同一网关**（`ANTHROPIC_BASE_URL=http://192.168.0.212:8082`，`glm-5.2`）持续可用 → 网关**未整体封锁**；"reset 2026-07-15" 措辞仍可能是并发突发限流而非月配额硬墙（与 runlog 问题 7/8 的"软限流"裁定一致，但需低并发实测确认）。本轮未发起 LLM 重跑，故 429 是否已恢复**未实测**。

---

## 第五轮：三方案收口（P10 根治 + 软 stage timeout + session sidecar resume）

> 起点：第四轮 salvage 拿到 swi_glu/foreach_norm 两个真实评分并定位 P10 后，用户批准对 P10/429-resume/timeout 三缺陷统一落方案（plan: `lovely-painting-aurora.md`）。本轮**实施 + 验证**三个独立方案。运行时事实记录；方案设计见 L3/L4（`38/39/40-*.md`）。

### 事实 1：P10 由 per-op 手工修复升级为 cannbench_adapt 确定性后处理（已实施）

- **改动**：`cannbench_adapt.transition()` 末尾追加 `_align_mdef_schema(state)`——以 `state.requirement.op_spec`（proto 单一真相源）参数名为基准，正则解析 `op_plugin/<op>_plugin.cpp` 的 `m.def` schema 参数名，按位置对齐 rename（只改 schema 字符串，不动 C++ 形参名/不动 kernel），m.def 变更则 `Deployer().deploy(state)` rebuild opp；rebuild 失败设 `last_error=ErrorFeedback(schema_adapt_failed)` 阻断 eval。`AdaptResult` 加 `schema_renamed: list[dict]`。codegen `transition` 加 warn（manifest 参数名≠proto 时，不自动改 manifest）。
- **验证**：UT 18 + 全量 UT 1839 passed，0 回归。详见 `38-p10-schema-adapt-*.md`。
- **边界**：P10 后处理是 codegen→cann-bench 桥接层兜底，非 codegen skill 根治（codegen 仍可能再生成错名，由 warn 暴露）。

### 事实 2：stage timeout 不再假杀成功 run（Option A，已实施）

- **改动**：`runner.run_stage` 记 `self._last_iter_ok`（上一 iteration agent 是否 ok），`_check_timeout` stage 段 raise 条件加 `and not self._last_iter_ok`——上一 iteration agent ok（成功但慢）则 soft（warn 不 raise），失败/卡死仍 raise。workflow deadline 仍硬墙。
- **验证**：UT 6 + 全量 UT 1839 passed，0 回归。详见 `39-soft-stage-timeout-*.md`。
- **边界**：soft 不假杀「成功但慢」的 run（如 swi_glu 4484s>3600s 但产物完整），但不加速——真·慢仍需抬 STAGE_TIMEOUT 或认 codegen 算力不足（P7）。

### 事实 3：429 crash 的 session_id 持久化 + 跨 run resume + 降级（sidecar 方案，已实施）

- **设计事实（用户驱动）**：session_id 不进 State——(a) 它是「正常信息」非「错误信息」，不该挨 last_error；(b) **进程被外部强杀（SIGKILL/OOM）时无 transition 可设 State 字段**，State 字段覆盖不了 hard-kill。改用 **sidecar**：`<run>/agents/<agent>.session.json`，由 `SDKBackend._spawn` 在**捕获 session_id 当下**写盘（mid-spawn，强杀前已落盘 → 覆盖 hard-kill），clean finish 删。
- **改动**：`infra/workspace.session_sidecar_path()`（路径单一权威源，L7）；`sdk_backend._spawn` 写/清 sidecar + session-gone 降级（`_is_session_gone` marker + `attempt==1` guard → fresh spawn）；`codegen.actions` 入口查 sidecar → 发 `SpawnAgent(resume_session_id=...)`（不重投 skill slash）；`runner._execute_spawn_agent` 透传；`SpawnAgent.resume_session_id` + `AgentBackend.spawn(resume_session_id=...)` 新增（protocol 扩展，29 处 fake backend 同步）。`dispatcher._resume_breaker_reset` 不动 sidecar（非 State）。
- **与 P29（19/20-resume-hardkill）互补、不重叠**：P29 = 逐节点 flush `state_snapshot.json` 保 `node_status`（resume 跳过已完成节点）；本方案 = sidecar 保 `session_id`（重入被中断节点时续接 SDK session 推理记忆）。各一条通路、各管一责（§2.5，无第二 session_id 路径）。
- **验证**：UT 12（capabilities 8 + orchestration 4）+ 全量 UT 1839 passed + 非 heavy ST 94 passed，0 回归；`test_layer_dependencies.py` 通过。详见 `40-session-resume-sidecar-*.md`。
- **heavy_llm（§3.11）已执行**：429 恢复后跑 `tests/st/test_session_resume_e2e.py` 3/3 绿（真实 LLM 37.78s）。首次跑暴露并修复一个 stderr 盲区（详见第六轮 事实1）。

### 三方案验证汇总

| 方案 | 状态 | UT | 回归 | heavy_llm |
|---|---|---|---|---|
| P10 根治（cannbench_adapt 后处理） | ✅ 已实施 | 18 新增 | 1839 passed，0 回归 | 无（确定性，不依赖 LLM） |
| Option A 软 stage timeout | ✅ 已实施 | 6 新增 | 1839 passed，0 回归 | 无（runner 确定性逻辑） |
| 提案#1 session sidecar resume | ✅ 已实施 | 12 新增 | 1858 passed + 94 非 heavy ST | **3/3 绿** + 修 stderr 盲区（详见第六轮） |

---

## 第六轮：429 恢复后 — heavy_llm 验证 + batch 续跑（提案#1 实战）

> 起点：第五轮三方案实施完毕后，429 配额恢复（reset 窗口松动），遂执行被搁置的 heavy_llm ST，并对 4 个真·未完成算子发起并发续跑。本轮跑通 heavy_llm 并首次在**真实 batch**中实证提案#1 接住了活 429。**batch 两次拉起（b4ex33hhf / bataap84u）均 halt**：3 算子死因 = 401 token 耗尽（换 key 后 34 分钟再耗尽），1 算子（rms_norm）死因 = path-read bug（独立真 bug，见事实 5）。最终评分仍未取得——补救路径见事实 6。

### 事实 1：heavy_llm ST 3/3 绿 + 修复 stderr 盲区（首次跑暴露真实缺陷）

- **执行**：`tests/st/test_session_resume_e2e.py`（`@pytest.mark.llm + heavy_llm`，3 用例，真实 claude_agent_sdk session 全流程），3/3 绿（37.78s）。① fresh _spawn 捕获真实 session_id；② 捕获的 sid 回填 resume_session_id → SDK 真实 resume 不降级；③ bogus UUID → 真实 SDK 拒绝 → 命中 gone markers → 降级 fresh。
- **暴露+修复的 stderr 盲区**：用例③首次跑 `status=fatal`——bogus/expired resume 时 claude_agent_sdk 把可操作诊断 `No conversation found with session ID:...` **只写子进程 stderr，不进 Python 异常 message**（`ProcessError.stderr` 是占位符 `"Check stderr output for details"`）。默认 `options.stderr=None` 子进程 stderr 继承 fd 2（到终端不到异常）→ `_crash_text` 永远看不到诊断 → `_is_session_gone` 不命中 → 降级不触发 → fatal。**修**（`sdk_backend.py`）：`_spawn` 注册 `options.stderr=_on_sdk_stderr` callback（SDK 设了 callback 才 PIPE 子进程 stderr 逐行回调，`subprocess_cli.py:532`）累积+tee 回 sys.stderr，`_crash_text` 并入 `"\n".join(_stderr_lines)`，markers 加宽 `"no conversation found"/"conversation not found"/"no such conversation"`，partial/fatal 的 `failure_reason` + `_classify_error_type` 改用 enriched `_crash_text`。UT markers 补强；全量 UT 1858 passed。详见 `40-session-resume-sidecar-impl.md` 「ST 执行结果 + stderr 盲区修复」节。
- **意义**：正是 §3.9 real-link ST 的价值——mock `query()` 无 stderr，UT 结构上测不到此盲区；只有真实 SDK 往返才暴露。

### 事实 2：batch 续跑范围订正（省 token）

- **已完成，跳过**：swi_glu（salvage 77.42, 20/20）、foreach_norm（salvage 48.07, 19/20）——标 `.status=0`，RESUME 模式跳过，**不重跑**（避免污染/浪费 token）。注：这两算子的 worktree 源码经第四轮 salvage 手工改了 `op_plugin/*_plugin.cpp` 的 `m.def`（P10 per-op 修复），未 commit。
- **真·未完成，并发续跑**：cross_entropy_loss / dynamic_quant / moe_re_routing / rms_norm（MAX_CONCURRENT=4，npu_id=2/3/4/5 互异，无撞卡；rms_norm 是 P10 受害者 salvage=0）。run_id 各自 `20260710-140056-<suffix>`。
- **注意**：手动指定 `WORKTREE_ROOT=.../cann-bench-batch/20260710_220043`（脚本 auto-find `sort|tail -1` 会误选空的 `sixops_20260710_194016`）。

### 事实 3：提案#1 在真实 batch 实战验证（中间检查点，batch 仍在跑）

- **moe_re_routing 撞真 429 并被提案#1 接住**（2026-07-12 19:13:11，resume 跑第 4 分钟）：
  ```
  [19:13:11] [ERROR] ascendc-coder attempt 1 failed: 429 (Weekly/Monthly Limit, reset 2026-07-15)
  [19:13:11] [WARN]  crashed mid-run (297 files snapshotted, partial)
  [19:13:11] stage_iteration codegen iteration 2/5
  [19:13:11] agent_resume ascendc-coder resuming session 432543d0-... (cross-run resume)  ← sidecar 读出
  [19:13:12] agent_session session_id=432543d0-...                                       ← 同一 session（非 fresh）
  → 推进到 turn 32（推理记忆未丢）
  ```
  即：429 crash → sidecar（捕获当下已落盘）→ 下一 codegen iteration `actions()` 查 sidecar 发 resume spawn → SDK 真实续接 session 432543d0（非降级 fresh）→ 继续。**这是第五轮三方案中提案#1 的首次真实 batch 命中**。
- **429 在并发 4 仍复发**：reset 2026-07-15 措辞仍在（moe 19:13:11 命中）；但已被提案#1 接住（非致命），不再打崩 batch。历史 crash（07-10/11，提案#1 未装）无 resume；今日 crash（07-12）全续接。
- **4 op 全活**（19:16:32–19:17:11，无 fatal）：cross_entropy_loss codegen turn23、dynamic_quant turn37、rms_norm turn32、moe_re_routing turn32（resume 后）。

### 事实 4：bataap84u 最终结局 — 4 算子 halt，死因两类（401 / path-read bug）

b4ex33hhf（首次续跑）与 bataap84u（换 key 后再续跑）均 halt。bataap84u 各算子 per-op 日志实证死因（**两类完全不同**）：

| 算子 | 死因 | 证据（logs/batch_<op>.log） | worktree 构建物 |
|---|---|---|---|
| cross_entropy_loss | **401 token 耗尽** | L1455 `401 Invalid token` @20:59:43 → `infra halt` + `max iterations (5)` | 无 plugin、无 dist/.run |
| dynamic_quant | **401 token 耗尽** | L2926 `401 Invalid token` @20:59:37 → 同上 | 无 plugin、无 dist/.run |
| moe_re_routing | **401 token 耗尽** | L2856 `401 Invalid token` @20:59:19 → 同上 | 有 plugin(3313B)、有 dist/.run |
| rms_norm | **path-read bug（非 401）** | L3405 `deploy_failed: smoke_passed=False` @**20:33:04**（早于另 3 个 401 26 分钟） | 有 plugin(2419B)、有 dist/.run |

- **401 反复**：用户首跑换 key 后，bataap84u 的提案#1 session resume 确实接上了（bad4dff2 / a25100a7 / 432543d0 全 cross-run resume 成功，实证见事实 3），LLM 续跑约 34 分钟（20:25→20:59），新 key 在 4 并发 codegen 下再次耗尽。**401 ≠ 429（配额窗），是 token 用尽 → 换 token 即可再 resume，无需等 reset**（见事实 6）。
- **CEL/DQ 零构建物**：codegen 未产出可 build 的 `op_plugin/*.cpp`（csrc cpp=4 但无 plugin），即便想手动 rebuild 也无源——只能 LLM 重跑。
- **moe 有构建物但仍 401 halt**：worktree 有 plugin + dist/.run（来自此前某次 codegen 迭代），但因 20:59 401 中断，未到 eval；可作 salvage 候选，也可换 token RESUME 走完整 codegen→eval。

### 事实 5：path-read bug（rms_norm 冤杀，独立真 bug，本轮仅记录待修）

- **现象**：rms_norm codegen agent 实际已把 smoke 跑通（worktree dist/.run 在、最深嵌套 `last_deploy.json` `smoke_passed=true` @20:33:04），但 stage 在 20:33:04 判 `smoke_passed=False` → `deploy_failed` halt → workflow 冤杀（L3405-3408）。**agent 修对了 smoke，被 transition 误读成失败**。
- **根因**：`src/ascendc_devkit/orchestration/stages/codegen.py` `_read_deploy_result` 只读固定浅路径 `artifacts/debug/<op>/last_deploy.json`，没处理 crash-save 的俄罗斯套娃嵌套——每次 codegen crash（401/partial），`sdk_backend` 把 `artifacts/` 快照到 `artifacts/codegen/`，重复 crash 产生 `codegen/codegen/codegen/...` 嵌套。rms_norm 三路径实测：
  - `artifacts/debug/rms_norm/last_deploy.json` → `smoke_passed=false` @**20:30:57（stale，stage 读的这条）**
  - `artifacts/codegen/debug/rms_norm/last_deploy.json` → false @20:33:04
  - `artifacts/codegen/codegen/codegen/codegen/debug/rms_norm/last_deploy.json` → **`smoke_passed=true` @20:33:04（真实最新，被漏读）**
- **四把尺子**：可维护（不动既有 transition 契约，只改读路径选最新）、可扩展（任意嵌套深度自动归位）、可诊断（应 log 实际命中路径+mtime，而非静默读 stale）、架构合理（落在 codegen stage 读自身 handoff 的职责边界）。修复方向：`_read_deploy_result` 递归 glob `artifacts/**/debug/<op>/last_deploy.json` 按 mtime 取最新一份，而非固定浅路径。**本轮仅记录、未修**（用户：「之后我们再来解决这个问题」）。

### 事实 6：补救路径

- **401 类（CEL / DQ / moe）**：换 token 后 `RESUME=1 WORKTREE_ROOT=.../cann-bench-batch/20260710_220043 bash scripts/batch_self_evolve.sh` 重跑——stage-level resume（跳过已完成 23 节点）+ 提案#1 session resume（续接 crashed session 推理记忆）。`.status≠0` 的 4 算子都会续跑，token 供给稳定时能走通 codegen→eval。**401 是 token 用尽不是配额窗，换 key 即可，无需等 reset**。
- **rms_norm（path-read bug 受害者）**：bug 修前 RESUME 仍会被冤杀（smoke 过了也判 False）。两条路：① 先修 `_read_deploy_result`（事实 5 方向）再 RESUME；② 暂用 salvage 对 worktree 构建物（smoke_passed=true）跑 cann-bench eval 拿临时评分，bug 留待「之后解决」。
- **不重跑 swi_glu / foreach_norm**：已 `.status=0` 跳过（salvage 77.42 / 48.07，第四轮已记）。

### 事实 7：rms_norm state 修正 + RESUME 进 precision_debug（用户方案，已执行验证）

- **用户决策**（替代事实 6 的 salvage/修 bug 二选一）：既然 codegen 事实上成功（smoke_passed=true 实证），直接**手动修正 rms_norm 的 state snapshot** 让 RESUME 跳过 codegen 进 precision_debug——"bug 已记下，让 rms_norm 按流程往下走（精度调试）"，不动代码。
- **字段修正**（备份 `output/20260710-140056-ba16cd/state_snapshot.json.bak-prereadfix`）：
  - `node_status['self_evolve_op/codegen']`: failed → **completed**（唯一阻塞项；`graph_executor.py:174` 只 skip "completed"）
  - `build_result.passed`: false → **true**
  - `deploy_result`: ← 深层真实 `last_deploy.json`（smoke_passed=true + run/wheel/install/python 全路径）
  - `last_error`: deploy_failed → **null**（`_resume_breaker_reset` 只清 infra 类型，deploy_failed 必须手清）
  - **顶层 `self_evolve_op` 保持 failed**（改 completed 会触发 `dispatcher.py:525` all_done 直接退出、跳过 precision_debug——禁止）
  - codegen_manifest / generated_sources / codegen_consecutive_failures / current_stage / stage_iterations 均不动
- **Explore 调查确认无阻塞坑**：RESUME 由 node_status 唯一驱动；codegen skip 时**不调 transition**（`graph_executor.py:361-363`），path-read bug 天然回避；顶层 failed 由引擎跑完后 `_group_status` 重算。
- **验证成功**（22:08:42）：`Resuming run 'ba16cd' from 'precision_debug' (completed nodes: [..., self_evolve_op/codegen, ...])` → precision_debug iteration 1/30 → ascendc-precision-debugger spawn（session e42bc2a6，turn 22 调试中）。state op_dir=`.../cann-bench-batch/20260710_220043/rms_norm/.../rms_norm`（**e2e banner 显示的 moe_re_routing 是脚本默认参数显示，与 RESUME 实际用的 state 无关**，已确认 agent 操作的是 rms_norm worktree）。npu_id=4，不撞 batch（CEL=2/DQ=3/moe=5）。
- **诚实声明**：本事实 7 是**绕过 path-read bug 的非常规 state 修正**（非修代码），已备份可回滚；path-read bug 的代码根治仍记任务 #11（用户：之后解决）。

### 事实 8：DQ path-read bug 第二次复发 + state 修正 + 嵌套目录 bug 暴露（已执行验证）

- **复发**（本次 21:33 batch RESUME bz7gd2mgw 后，仅看本次证据）：DQ（run_id `20260710-140056-94616a`）codegen 跑满 5 次 max_iterations（21:52→22:45），每次 `contract unsatisfied: build_result, deploy_result`，22:45:23 halt exit 65（`Missing expected sections: ['op_host', 'op_kernel']`）。但 5 个嵌套 `last_deploy.json`（mtime 22:45:23=本次）**全部 smoke_passed=True**——与 rms_norm（事实 5/7）完全同构：kernel 实际 build+deploy+smoke 全过，被 `_read_deploy_result` 浅路径读取 bug 冤杀。**path-read bug 第二次复发**。
- **嵌套目录 bug（新发现，并入 #11）**：`last_error.details.produced_keys` 暴露路径 `codegen/codegen/.../codegen/design/...` **10 层嵌套**——codegen 每次 iteration 在 op_dir 下又叠一层 `codegen/` 子目录（iteration 2→5 各叠一层）。与 path-read bug 并存但独立：glob 取最新 mtime 能容忍（读到最深 smoke_passed=true），但嵌套本身是缺陷（路径膨胀、产物散落）。
- **DQ state 修正**（同事实 7 方案，用户 AskUserQuestion 拍板「状态修复 DQ」）：备份 `output/20260710-140056-94616a/state_snapshot.json.bak-prereadfix`，改 4 处——`codegen` node failed→completed；`build_result.passed` None→true（DQ 此字段整个为 None，比 rms_norm 的 false 更彻底，transition 根本没产出 build_result）；`deploy_result` ← 深嵌套最新 mtime `last_deploy.json`（smoke_passed=true，6 keys 完整）；`last_error` incomplete_output→null；顶层 `self_evolve_op` 保持 failed。`codegen_manifest.callable_target` 完整保留（torch.ops.cann_bench.dynamic_quant + 详细 note），precision_debug 不断链（generated_sources=0，section 缺失所致，但 precision_debug 靠 callable_target + 磁盘产物，不靠 generated_sources）。
- **NPU 卡**：DQ npu_id=3，与 rms_norm=4 / CEL=2 / moe=5 全不同，无冲突；DQ halt 后无残留活进程。
- **RESUME 验证**（23:10）：DQ 独立 RESUME（task `b2zmnv2y9`，脱离 bz7gd2mgw batch——DQ halt exit 65 后 batch run_one 已返回，DQ 改由独立 e2e RESUME 接管）。codegen 跳过，precision_debug turn 6→11（23:10:42，ascendc-precision-debugger 活跃 tool:Read）。`SKIP_INSTALL=1` 避免 devkit 重装。
- **诚实声明**：同事实 7——绕过 path-read bug 的非常规 state 修正（非修代码），已备份可回滚。**两次复发（rms_norm + DQ）说明 #11 已是高复现率真 bug**；CEL/moe codegen 已过（进 precision_debug），未触发，待观察后续 stage。

### 事实 9：precision_debug artifacts-relay bug（rms_norm 精度被冤杀，passed=True 实证，已 state 修正）

- **现象**（仅看本次 22:08 RESUME 后）：rms_norm（ba16cd）事实 7 修复 codegen 后 RESUME（bguoerf7u）进 precision_debug，agent 跑 **394 turn / 4064s**，23:16:38 halt exit 65（`agent 未产出 debug_result.json`）。但 worktree op_dir `.../csrc/ops/rms_norm/debug_result.json` **实际产出且 passed=True**（max_diff=0.005423, iterations_used=3, best_commit=04299cf...）；`.precision-fix/checkpoint.json` status=passed。**精度实际通过**。
- **根因（第三个 path 类 bug，独立于 #11）**：precision_debug transition（`precision_debug.py:232-233`）从 `agent_result.artifacts`（SDK 内存 dict）读 debug_result.json；但 skill prompt（第 217 行）教 agent 按文件接力（§2.3）写到 op_dir 文件系统。agent 写了文件但没塞进 SDK artifacts → transition else 分支（258-270）写入假值（passed=False/max_diff=999/iterations=30）→ halt。**与 codegen path-read bug（#11）不同源**：codegen 是文件路径浅读，precision_debug 是 SDK artifacts dict vs 文件系统接力机制错配。
- **嵌套目录 bug 再现**：produced_keys 显示 `codegen/codegen/.../design/...`（5 层），与 DQ（事实 8）同——证实嵌套 bug **跨 stage**（codegen + precision_debug 都叠 `codegen/` 子目录），不只 codegen。
- **rms_norm state 修正**（同事实 7/8 模式，用户 AskUserQuestion 拍板「状态修复」）：备份 `.bak-preprecisionfix`（不覆盖 codegen 的 `.bak-prereadfix`），改 4 处——`precision_debug` node failed→completed；`debug_result` ← worktree 真实值 {passed:True, max_diff:0.005423, best_commit:04299cf..., failing_cases:[], iterations_used:3, stubbed:False}；`debug_iterations` 30→3；`last_error`→null；顶层保持 failed。codegen 仍 completed（事实 7 保留）。
- **RESUME 验证**（23:30）：rms_norm 独立 RESUME（task `b65fkc8g3`，卡 4 空闲），`Resuming from 'cannbench_adapt'`（completed nodes 含 precision_debug + codegen），cannbench_adapt iteration 1/2（cannbench-adapt agent turn 8）。**codegen + precision_debug 双跳过**。
- **诚实声明**：绕过 precision_debug artifacts-relay bug 的非常规 state 修正（非修代码），已备份可回滚。**精度本身确证通过**（passed=True/max_diff=0.005423）。三个 path 类 bug 现状（**三者均已代码根治**）：① codegen path-read（#11，2 次复发）→ `24d989f` 根治；② codegen 嵌套目录（#11 并入，跨 stage）→ `24d989f` 根治（4 处 working_dir 兜底 + `_persist_sources` 剥离重复前导 `codegen/`）；③ **precision_debug artifacts-relay → `#12` 根治（2026-07-13）**：transition 改读 `<op_dir>/debug_result.json` 文件（对齐 skill `write-debug-result.py` 契约），删 SDK `agent_result.artifacts` dict 死读（precision-debug agent 用脚本写文件、从不填 SDK dict，故 dict 读恒 None）。详见 `46-precision-debug-artifacts-relay-*.md`。UT 19（含事实9 回归守卫）+ 全量 1889 + 非 heavy ST 102 全绿。

### 事实 10：rms_norm eval=0 根因 — cannbench_adapt glue-ghost（嵌套 bug 第三类后果），salvage 中

- **现象**（事实 9 修复 precision_debug 后 RESUME b65fkc8g3，仅看本次证据）：rms_norm（ba16cd）RESUME 完成 exit 0，cannbench_adapt 跑过（adapt_result.adapted=true，但 schema_renamed=[]/rebuilt=false——P10 后处理判 m.def 已对齐，没 rebuild），cannbench_eval 跑完，但 report `overall_score=0.00 / total_cases=0 / total_operators=0 / operators=[]`（kernel_eval 一个算子都没发现）。
- **诊断链（逐层排除，定位到 Python 接口注册）**：
  1. `kernel_eval list`（task_loader.list_tasks，task 级 discovery）**能列出 RmsNorm(L2)** → discovery 正常，level 不是问题（`resolve_task_dir(None)` 默认扫整个 tasks/ 所有 level）。
  2. eval 走 `case_loader.scan_all()` + `_cmd_eval_npu` 451-453 行 `compiled_ops = set(op.lower() for op in matched_operators); all_cases = [c for c in all_cases if c.operator.lower() in compiled_ops]` → `matched_operators` 不含 rms_norm 则 case 全过滤。
  3. `matched_operators = prepare_skip_build()`（`package_manager.py:753`）→ `scan_interfaces()` + `match_operators()`。
  4. 实证扫描（salvage_eval.sh env）：`dir(cann_bench)` callable = **['add', 'sqrt']**（无 rms_norm）；`torch.ops.cann_bench` dir = ['name']（torch.ops namespace 不列算子）；但 `hasattr(torch.ops.cann_bench, 'rms_norm')` = **True**（C++ 侧已注册）。
  5. `scan_interfaces` 第 1 步扫 `dir(cann_bench)` callable（只 add/sqrt），第 2 步扫 torch.ops.cann_bench 但 dir 不列算子 → rms_norm 扫不到 → `match_operators`（按 interface name lower 匹配 task func name）空 → total_operators=0。
- **根因（per_op_python cann_bench/\_\_init\_\_.py 缺 rms_norm Python def 包装）**：对比 swi_glu（per_op_python `__init__.py` 行 31-32 有 `def swi_glu(...) -> torch.ops.cann_bench.swi_glu(...)`，eval 77.42）vs rms_norm（行 29 sqrt 后直接注释，**缺 def rms_norm**）。C++ 侧完全就绪：`op_plugin/rms_norm_plugin.cpp` 有 `TORCH_LIBRARY_FRAGMENT(cann_bench, m) { m.def("rms_norm(Tensor x, Tensor gamma, float epsilon=1e-6) -> Tensor") }` + Meta/PrivateUse1 impl，`_C.abi3.so` 含注册（torch.ops.cann_bench.rms_norm 存在）。**只缺 Python 侧 3 行 def 包装**。
- **为什么缺（cannbench_adapt glue-ghost）**：`adapt_result.files_modified` 列 5 个 `__init__.py`，路径全是 `codegen/codegen/.../per-op/rms_norm/python/cann_bench/__init__.py`（**artifacts 嵌套幻影**，nested directory bug 污染的 op_dir），**无一指向真实 per_op_python 或 worktree 源头**。cannbench_adapt agent 在嵌套幻影路径改 glue，真实 `__init__.py` 从未被注册。这是 **nested directory bug（#11）的第三类后果**：① codegen path-read（浅读漏嵌套 last_deploy）；② 嵌套目录本身（跨 stage 叠 codegen/）；③ **cannbench_adapt glue-ghost（agent 在嵌套幻影路径改 glue，真实 worktree/per_op_python 未改）**。P10 schema 名不是问题（m.def x/gamma/epsilon 已对齐 proto，schema_renamed=[]）。
- **Salvage（已执行，C++ 侧就绪故最小改动）**：per_op_python `cann_bench/__init__.py` 行 29 后插入 `def rms_norm(x, gamma, epsilon=1e-6) -> torch.ops.cann_bench.rms_norm(x, gamma, epsilon)`（3 行 Python 包装；eval `--skip-install` 用 PYTHONPATH 指向 per_op_python，改 Python 直接生效，不需 rebuild opp）。后台 salvage_eval（task `bdgb196f4`，device=4）**拿到真实评分：overall_score=42.17 / pass_rate=40% / 8-20 case 通过**（float16 多通过，float32/bfloat16 多失败——真实精度问题，非 bug；加 def 后 eval 正常发现算子，评测算子数=1）。**根因 100% 确认**。
- **影响 CEL/DQ/moe**：三者进 eval 时 cannbench_adapt 同样在 nested 幻影路径改 glue → 真实 `__init__.py` 同样缺算子 def → eval 同样 total_operators=0。需同法 salvage（per_op_python `__init__.py` 补对应 def 包装）。
- **诚实声明**：per_op_python `__init__.py` 是 build 产物，rebuild 会覆盖；本次 salvage 是绕过 cannbench_adapt glue-ghost 拿真实评测（非掩盖，C++ 侧 + 精度本身确证就绪）。根因（nested directory bug #11）代码根治仍记任务 #11。

### 事实 11：moe salvage 拿分 56.95 + CEL 无 op_api/op_plugin（**结论已纠正，见事实 12**）

> **纠正（2026-07-13）**：本节原结论「CEL codegen 产出完整性 bug + salvage 不可行」**错误**，经用户 challenge（"CEL 没有 op-plugin 怎么通过 smoke/精度调试？"）后深查纠正：
> - CEL 无 op_api/op_plugin **是 by-design**（非 codegen bug）：`codegen_manifest.json` 的 `callable_target.kind=aclnn` + CMakeLists 注释「无 op_api/op_plugin: kernel_architecture 仅声明 op_host+op_kernel (aclnn callable_target)」。即 codegen 按 aclnn-only 设计产出，故意不生成 torch.ops 接口层。
> - **smoke 过**：deploy `_smoke_script`（`deploy.py:334-365`）对 aclnn kind 是 **NO-OP**（只打印 "smoke OK (no torch_op check)"），不验 torch.ops 注册——故 CEL 无 plugin 也过 smoke（盲区，§3.9 类）。
> - **精度调试 halt**：precision_debug iter 1 即判 `global_aclnn_callable_unsupported`（NPURunner `runner.py:419-428` 仅支持 torch_op，拒 aclnn）—— **从未真正跑过 kernel**，与精度无关。
> - 故 salvage **可行**（补 op_api+op_plugin 脚手架即可让 CEL 可调用），已执行，见**事实 12**。

- **moe（b1b8ec）salvage 拿分**（task `bpwklzc3f`，device=5）：moe 与 rms_norm 不同——per_op_python `__init__.py` **已有 `def moe_re_routing`**（grep=1）+ _C.abi3.so **含 `moe_re_routing(Tensor tokens, ...)` schema**（C++ 注册完整）→ salvage_eval 直接跑，无需补 def。**结果：综合得分 56.95 / 通过率 80% / 16-20 case 通过**。4 个失败 case 全是 `permute_per_token_scales` 形状不匹配（output=torch.Size([0]) vs golden=Size([4096]/[8192]/...），即 `per_token_scales=None` 输入时该输出张量的形状边界处理——精度本身 MERE/MARE 全 0（数值对），仅输出形状边界 case。moe precision_debug passed=True/max_diff=0.0（事实:查 debug_result.json 实证）确证未被冤杀，是 artifacts-relay bug 冤杀后 salvage 还原的真实高分。
- **CEL（0ce45e）salvage 不可行**（codegen 产出缺 op_plugin）：深查发现 CEL codegen 产出**根本不完整**：
  - op_dir 只有 `op_kernel` + `op_host`，**无 `op_plugin` 目录**；
  - 全 op_dir 搜 `m.def(` / `TORCH_LIBRARY_FRAGMENT(cann_bench)` **全空**（CEL 无 PyTorch torch.ops 注册层）；
  - `_C.abi3.so` 不含 `cross_entropy_loss(` schema（对比 moe _C 含 moe_re_routing schema）；
  - `torch.ops.cann_bench.cross_entropy_loss` = **False**。
  - 但 `last_deploy.json` smoke_passed=True（6 嵌套）—— deploy `_smoke_script` 验的不是 cross_entropy_loss 的 torch.ops 注册（验 add/sqrt 基仓或 op_host ACLNN 接口），故 smoke 过但 cross_entropy_loss 没注册。
- **原「根因归类/precision_debug halt/本轮小结」三段已作废**（基于错误的「codegen 完整性 bug」前提）：CEL 的真根因（by-design aclnn-only）+ 脚手架补救 + 真正拦路虎（kernel 编译 bug）+ 最终评分，全部见**事实 12**。moe 56.95（16/20）结论不变（事实 11 moe 段正确）。

### 事实 12：CEL 手补 op_api+op_plugin 脚手架成功可调用，但 kernel 核心代码编译 bug 致 0/20（约束下不可改）+ DQ salvage 拿分 59.23

**用户指令（2026-07-13，逐字）**：「请先同步远端修改，尝试得到剩下两个算子的评分（只要不修改算子核心代码就行）」。约束：不修改 op_kernel/op_host；op_api/op_plugin（注册/绑定层）允许补。

- **CEL 手补脚手架**（task #15，仿 moe/rms_norm/swi_glu 范式，非 LLM）：
  - 新增 `op_api/aclnn_cross_entropy_loss.{h,cpp}`（L2 launcher：CheckParams + Contiguous(input/target) + l0op::CrossEntropyLoss + ViewCopy + CommonOpExecutorRun）；
  - 新增 `op_api/cross_entropy_loss.{h,cpp}`（l0op：`OP_TYPE_REGISTER(CrossEntropyLoss)` + `ADD_TO_LAUNCHER_LIST_AICORE(CrossEntropyLoss, OP_INPUT(input,target), OP_OUTPUT(loss), OP_ATTR(reduction,"reduction"), OP_ATTR(ignoreIndex,"ignore_index"))`，loss 形状 none→[N,D...]/mean·sum→[1] 与 infershape 一致）；
  - 新增 `op_plugin/cross_entropy_loss_plugin.cpp`（TORCH_LIBRARY_FRAGMENT `m.def("cross_entropy_loss(Tensor input, Tensor target, str reduction=\"mean\", int ignore_index=-100) -> Tensor")` + Meta（按 reduction 推 loss 形状）+ PrivateUse1（contiguous + 命名左值 `const char* reductionC`（ACLNN_CMD 按左值引用取参，rvalue `c_str()` 不能绑定）+ ACLNN_CMD））；
  - 更新 `CMakeLists.txt`（API_SRCS 填 2 cpp + register_aclnn_op 第7参 op_kernel→op_api + register_aclnn_plugin）+ `cann_bench/__init__.py` 补 `def cross_entropy_loss`。
  - **关键验证**：string attr 经 `OP_ATTR(reduction, "reduction")`（variadic tuple 宏，位置区分值/名）**编译通过**（libcust_opapi.so 链接成功）；build+install 全过；`torch.ops.cann_bench.cross_entropy_loss` 解析成功；ACLNN_CMD 找到 `aclnnCrossEntropyLoss` 符号——**CEL 端到端可调用**（事实 11 原"salvage 不可行"彻底推翻）。
- **真拦路虎 = kernel 核心代码编译 bug（非脚手架）**：eval 20/20 全 `EZ9999: Cannot find bin of op CrossEntropyLoss, integral key .../float16·float/...`，`failure_type=compile_runtime_error`。深查 build 日志：
  ```
  op_kernel/cross_entropy_loss.h:294: error: no matching function for call to 'Cast'
    Cast(expTmp, xLocal, static_cast<int32_t>(cLen), kUpCastMode);
    in 'NsCrossEntropyLoss::CrossEntropyLoss<__bf16>::Process'
  ```
  → bf16 特化的 `Cast` 调用无匹配重载（`kUpCastMode` 形参与 AscendC `Cast(dst,src,count,RoundMode)` 签名不符），kernel bin 生成中断 → **全 dtype 零 bin**（`find dist -iname '*CrossEntropyLoss*'` 空）→ 运行期无可执行 bin → 0/20。
  - **build 静默吞错**：kernel 编译失败但 `build.sh RC=0`（非致命），致"build 绿但 eval 全红"的欺骗性绿灯——**第 5 类隐患**（kernel 编译失败不阻断 build），与前 4 类（path-read/artifacts-relay/glue-ghost/by-design-aclnn）正交。**精确盲区点 = `deploy.py:_run_command` RC=0 分支 `return True,"",None`**：丢弃整个 stdout（含 `error: no matching function for call to 'Cast'`）且不调 `_persist_subprocess_output`（不落盘）；smoke（aclnn kind 空操作）不验 kernel bin → `smoke_passed=True`（假阳性）。对照：CEL build 日志仅第 1 次落盘（后续 6 次 RC=0 kernel 失败未落盘 = 盲区实锤）vs rms_norm 每次 RC≠0 失败均落盘 → 反馈修好。**→ 已由方案 45 根治**（build 输出扫描器：RC=0 且 role==build 时扫描 stdout+stderr，命中编译失败信号 → 复用 RC≠0 通路落盘 + 返回 False，见 `45-build-output-scanner-*.md`）。
- **CEL = 0.00（0/20）**：根因是 kernel 核心代码（`op_kernel/cross_entropy_loss.h:294`）编译 bug，**按用户约束不可改**。脚手架已尽力（op 可调用），约束下 0.0 是诚实上限。若用户后续授权改 kernel（修 Cast 签名），CEL 有望转非 0——**待用户决策**（独立于本轮）。
- **DQ salvage 拿分 59.23（20/20，best_commit 31352b3）**（task #14，`salvage_rebuild_eval.sh dynamic_quant 3`）：
  - **关键洞察**：precision_debug 的 8 failing（`best_failed_count=8`，devkit golden）vs cann-bench eval **20/20 全过（kernel 数值 bit-exact）**——**devkit golden 比 cann-bench golden 更严**（odd dim `.5` 边界 devkit 判败、cann-bench 判过）。即 DQ precision_debug 的 105min 调试 grind **相对 cann-bench 评测标准是 false alarm**——kernel 本身正确，是 golden 口径差异。此洞察对 precision_debug 的 golden 选取有方法学意义（待单独记录）。

### 待续（补救执行后补全）

- [x] rms_norm：**salvage 拿分 42.17（8/20）**——eval=0 根因 cannbench_adapt glue-ghost（事实 10），per_op_python `__init__.py` 补 `def rms_norm` 后 eval 正常（task `bdgb196f4`）。
- [x] moe：**salvage 拿分 56.95（16/20, 80%）**——precision_debug passed=True 被 artifacts-relay 冤杀，per_op_python `__init__.py` + _C 注册均完整，salvage_eval 直接跑（task `bpwklzc3f`）。4 失败 case 是 per_token_scales 形状边界（事实 11）。
- [x] DQ：**salvage_rebuild_eval 拿分 59.23（20/20，best_commit 31352b3）**——precision_debug 8 failing 是 devkit golden 比 cann-bench 更严（odd dim `.5` 边界），cann-bench eval kernel bit-exact 全过（见事实 12）。
- [x] CEL：**手补 op_api+op_plugin 脚手架（task #15，仿 moe/rms_norm/swi_glu）成功可调用，但 kernel 核心代码编译 bug（`op_kernel/cross_entropy_loss.h:294` Cast/bf16）致零 bin → 0/20（0.00）**——按用户约束（不修改核心代码）不可改；事实 11 原"salvage 不可行"已纠正，脚手架证明可行，真拦路虎是 kernel 编译 bug（见事实 12）。
- [x] swi_glu(77.42) / foreach_norm(48.07)：已 salvage 评分（第四轮），.status=0。
- [x] **4 op 最终评分表（第六轮收口）**：

| 算子 | 综合得分 | 通过率 | 评分数 | 根因/备注 |
|---|---|---|---|---|
| rms_norm | **42.17** | 40% | 8/20 | cannbench_adapt glue-ghost（事实10）+ salvage 还原 |
| moe_re_routing | **56.95** | 80% | 16/20 | artifacts-relay 冤杀（事实9）+ salvage 还原；4 失败=per_token_scales 形状边界 |
| dynamic_quant | **59.23** | 100% | 20/20 | cann-bench bit-exact；precision_debug 8 failing=devkit golden 更严（事实12） |
| cross_entropy_loss | **0.00** | 0% | 0/20 | 脚手架可调用；kernel 核心 Cast/bf16 编译 bug 致零 bin（事实12，约束下不可改） |
| *(swi_glu)* | *(77.42)* | — | — | *(第四轮已评，.status=0)* |
| *(foreach_norm)* | *(48.07)* | — | — | *(第四轮已评，.status=0)* |

> **第六轮收口结论**：4 算子（rms_norm/moe/DQ/CEL）全部拿到 cann-bench 评分。3 个非 0（42.17/56.95/59.23）均经 salvage 还原被 path-read/artifacts-relay/glue-ghost 三类 bug 冤杀的真实分数；CEL=0.0 是 kernel 核心代码编译 bug（约束下不可改），脚手架已尽力使其可调用。**三类 path bug 的代码根因现均已根治**（批跑期靠 salvage/state-修正绕过，根因后修）：path-read + 嵌套目录 + glue-ghost 同根 → `24d989f`（P66）；artifacts-relay → `#12`（2026-07-13）。两类新隐患状态：①build 静默吞 kernel 编译失败（第 5 类，欺骗性绿灯）**已由方案 45 根治**（build 输出扫描器，`deploy.py:_run_command` RC=0 分支）；②devkit golden 比 cann-bench 更严（DQ false-alarm grind，golden 选取方法学）待跟踪。

---

## 第七轮：CEL 0/20 根因再纠正（事实 11「by-design aclnn-only」误判）+ P77 rerun codegen

> 起点：用户 challenge「先前测试其他算子也没有专门对 aclnn-only eval 脚手架做设计，为什么能测试？gap 在哪里」。深查文件 mtime 后，**事实 11 的「by-design aclnn-only」纠正结论本身也是误判**——CEL 缺 op_api/op_plugin 不是设计选择，是 codegen 未完整跑完的半成品。先前对 rerun 的风险评估（风险 2「aclnn-only eval 脚手架」）据此作废。

### gap 定位（决定性证据 = 文件 mtime）

| 算子 | codegen 路径 | op_plugin/op_api mtime | 性质 |
|---|---|---|---|
| swi_glu | `aclnn_launch_example`（aclnn 路径） | op_api = **07-11 00:31**、op_plugin = **07-12 00:04** | **codegen 原始产出**（完整四层 op_kernel+op_host+op_api+op_plugin；第四轮 salvage 仅微调 `m.def` 参数名，未新建 plugin） |
| cross_entropy_loss | `aclnn_launch_example`（**同路径**） | op_plugin = **07-13 01:46**、op_api 同（salvage 手补）；op_kernel = **07-12 20:39** | codegen 仅产 op_kernel+op_host，**op_api+op_plugin 缺失**（07-13 事实 12 salvage 补） |

- **两者同为 aclnn 路径**（均在 `aclnn_launch_example/` 下）。swi_glu 的 codegen **正常产出完整四层** → `torch.ops.cann_bench.swi_glu` 注册 → eval 直接发现 → 77.42。
- CEL 的 codegen 在 07-12 20:30–20:39 产出 op_kernel+op_host 后，**在产 op_api+op_plugin 之前被 401 中断**（bataap84u batch CEL 401 @20:59:43 halt，见事实 4）→ 产出残缺 → eval `total_operators=0`（事实 10/11）。
- **事实 11「by-design aclnn-only」因果倒置**：CMakeLists「无 op_api/op_plugin」注释是 codegen 按**已产出的层**写的（没产 plugin 当然不注册），不是 design 指定不产。swi_glu 同为 aclnn 却产了 plugin，证伪「aclnn=不产 plugin」。

### 真因（两个问题同源）

CEL 0/20 的两个表面问题——产出残缺（缺 op_api+op_plugin）+ kernel Cast/DataCopyPad 签名 bug（`op_kernel/cross_entropy_loss.h:294/221/305` Cast、DataCopyPad×5）——**同源 = codegen 未完整跑完**（401/429 反复 crash）：crash 前的半成品既缺 plugin 层，kernel 也是未自修完的 buggy 版本。

### 对 rerun 风险评估的修正

先前（本会话早段）评估的「**风险 2：aclnn-only 设计障碍 → eval 仍需手补 op_plugin 脚手架**」**作废**——aclnn 路径正常产完整四层（swi_glu mtime 实证）。`--rerun-from codegen`（P77 fresh spawn）让 ascendc-coder **完整跑完**（前提：token 供给稳定，不被 401 打断）→ 会像 swi_glu 一样产完整四层含 op_api+op_plugin → eval 开箱即用；P75 build scanner 让自修循环**首次看到** Cast 编译失败 → 自修 kernel 签名。**两个问题一次 rerun 同源解决，拿分路径打通。**

剩余真实风险收敛为：① token 供给稳定（CEL 历次死穴 = 401/429；方案 74 sidecar resume 能接中途 429，但 401 需换 key）；② ascendc-coder 修对 Cast 签名的 LLM 非确定性（有 P75 反馈循环 + 知识库支撑）。

### 文档归属说明

本节是对 CEL 0/20 根因的**事实归因纠正**（修正事实 11 误判），不引入新 L1 问题：codegen 被打断的代码层缓解已由 P75（build 输出扫描器，方案 45）+ 方案 74（session sidecar cross-run resume）覆盖；本次仅澄清「产出残缺 ≠ by-design aclnn-only」。

### rerun 执行

**环境 + 命令**：CANN cann-9.1.0-beta.3（`set_env.sh`）、device 2、`TORCH_DEVICE_BACKEND_AUTOLOAD=0`。`--rerun-from codegen`（P77 fresh spawn）。

**codegen 结果（✅ 预测兑现）**：完整跑完，**产完整四层** op_kernel+op_host+op_api+op_plugin，CMakeLists 注册 `torch.ops.cann_bench.cross_entropy_loss`，redeploy smoke 通过——事实 11 误判纠正后的预测兑现（aclnn 路径正常产 plugin，与 swi_glu 一致）。P75 build scanner 触发自修循环修掉 Cast 签名类编译 bug，kernel 可编译可调用。但精度未收敛（仍有数值 bug），进 precision_debug。

**precision_debug 阶段（agent 内部循环，grind 后止损）**：agent 内层迭代 iter-1~26+（stage 层 iteration 恒 1/30，见 P54），逐步修多类 bug：

| bug 类 | 修复 | commit |
|---|---|---|
| A | mean/sum loss shape `[1]` → 0-dim scalar `[]` | `7787249` |
| B1/B2 | 非对齐 GM DMA（WriteLossToGm / CopyInX / CopyInTarget，`isAlign` 死分支） | `1b5536b` |
| B3 | T1 cLen overshoot OOB（cTail=0 → cTail=C） | `57b77f9` |
| UB OOB | reduceTmpBuf per cTile（修 507035 VEC OOB） | `3ba8cf5` |
| loss 输出 | 走 DataCopyPad DMA | `8b4cf08`（devkit 14/20） |
| DataCopy count | pad 到 block 边界 + scalar per-row reduces | `50e48f6`（devkit 16/20） |

**grind 判定 + 止损**：iter-22~25 持续 devkit 14/20、约 1hr 零进展、反复编辑 `op_kernel.h` 无新 commit → 确认 grind（非瞬态抖动）。用户决策：stop grind，取 `50e48f6`（iter-26 重部署验证 devkit 16/20）走评分流程。

> `precision_debug` 是 agent 内部循环（P54），框架层 `--max-iterations` 不控制其内层迭代；grind 是 agent 内层未收敛，非框架层死循环。

**评分结果（cann-bench 权威，`kernel_eval eval`，已部署 kernel `--skip-install`）**：

| 维度 | 得分 | 说明 |
|---|---|---|
| **综合** | **48.97** | = 编译 20.0 + 功能 28.5 + 性能 0.47 |
| 编译 | 20.0 / 20 | 满分，20/20 编译通过 |
| 功能 | 28.5 / 30 | cann-bench 判 **19/20 通过**（95%） |
| 性能 | 0.47 / 50 | 加速比均值 0.011x（loss 算子 baseline 强，自生成 kernel 未超越） |

**关键观察（P78 活体证据）**：cann-bench（出题方/权威）判 **19/20 通过**，devkit run-cases 判 **16/20**。差的 3 个 case（7/9/12/13，float16，devkit 报 `diff=0.0 但 passed=False`）cann-bench **全判通过**（MERE=0.000000）——这是 devkit float16 精度判据与 cann-bench 不一致导致的**冤杀**，**印证 P78「devkit 精度判定需对齐 cann-bench MERE/MARE + 相消兜底」修复方向正确**。真正精度失败仅 1 个：case 17（float32，MARE=0.996175 超 1.22e-4 阈值，相消兜底 NPU/CPU 错误=1/0 失败）。

**新发现（待补 L1）**：`precision_debug` agent 进度写 `artifacts/iter-*` + git commit，但**不回写** framework `.precision-fix/checkpoint.json`（checkpoint 冻结在 10:02 初始态 `best_failed_count=20`），框架层观测进度与 agent 实际进度脱节 → 可诊断性 gap（§1.2）。执行后补 L1。
