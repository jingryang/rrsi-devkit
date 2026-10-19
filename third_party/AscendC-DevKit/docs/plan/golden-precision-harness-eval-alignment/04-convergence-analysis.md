# precision_debug 收敛速度分析（resize_bilinear，7.23h）

> 用户问题：收敛能否加快？时间花在哪？是「最终实现与设计相差太大」吗？
> 本次只交付分析，加速项实施另立任务讨论。

## 一、时间分布（7.23h，events.jsonl + fix transcript 实证）

| 阶段 | 耗时 | 占比 | 明细 |
|---|---|---|---|
| fix（4 轮） | 4.17h | 57.6% | 单点最大 = fix#2 129.8min（30%） |
| diagnose（4 轮） | 2.37h | 32.9% | diagnose#2 71min（16%） |
| run_tests（5 轮全量回归） | 0.44h | 6.0% | 每轮 ~3min，其中 agent 开销占 ~2.8min |
| bounds_check + scope_guard | 0.26h | 3.6% | |

按消耗类别拆（以 7.23h 为基准）：

| 类别 | 耗时 | 占比 |
|---|---|---|
| agent 推理/试错 | ~2.7h | 37% |
| 编译部署固定成本（23 次 redeploy × 5-7min） | ~1.9h | 26% |
| numpy 仿真/分析（diagnose#2/#3） | ~0.7h | 10% |
| 单用例验证（~25 次 × 1-2min） | ~0.5h | 7% |
| 全量回归（5 轮 × ~3min） | ~0.4h | 6% |
| 代码阅读/架构对比/查知识库 | ~0.5h | 7% |
| 框架开销（agent spawn/skill 加载/结果解析） | ~0.5h | 7% |

## 二、「实现与设计相差大」？—— 否（codegen 与设计逐位一致，偏差 0%）

四轮 fix 逐轮归类（codegen 生成的 kernel 结构/分片/内存/数据流与设计文档完全一致）：

| 轮次 | commit | 失败→通过 | 归类 | 根因 |
|---|---|---|---|---|
| 1 | ae5d740 | 20→14 | A+C | codegen schema 可选参数缺 `=None` 默认值 + 既有脚手架 bug（ConvertType 作用域/OP_ATTR 形式/tiling attr）——**非 kernel 设计/实现** |
| 2 | 9ca6230 | 14→7 | B（设计缺陷） | 设计选的两趟 lerp 形 `A+(B-A)*w` 在 fp32 以下与 golden 加权和形数值不等价；codegen 忠实实现设计。设计只在 fp64 下验证了可分性（最大绝对差 8.88e-16），未验非 fp64 |
| 3 | 7fddfcb | 7→1 | D（硬件精度） | A2 硬件 FusedMulAdd 两步舍入 vs torch 合成 FMA（1 ULP）；设计精度分析未讨论硬件 FMA 语义 |
| 4 | 6be45b4 | 1→0 | D（二级） | FmaSoft 对 ±Inf 不安全（Dekker Split(-Inf)→NaN） |

责任占比：**设计缺陷 ~25%（round2）+ 硬件本质差异 ~50%（round3/4）+ 脚手架/框架 ~25%（round1）+ codegen 实现偏差 0%**。

**额外发现（关键）**：round3/4 的 FmaSoft 是为「逐位对齐 native torch」（harness 的 native
golden 目标）做的；但 eval 用 fp64 参考（见 01/02），**FmaSoft 对该参考既不充分也不必要**
（fp64 参考要的是「fp32 权重 + 近精确累加」，不是「复刻 torch 的 FMA 舍入」）→ 追错目标浪费 ~2h。

## 三、回答「golden_precision 对齐后能否同时加速收敛」

**能，但机制是「消除无效工作」而非「机械提速」**：

1. **消除追错目标**：对齐后 debug loop 不再为 native-torch 逐位一致做 FmaSoft（round3/4 ~2h），
   改为针对 fp64 参考的正确目标。收敛方向对、不白跑。
2. **消除假收敛的二次返工**：当前 20/20 是假态，对 eval 无效——对齐前跑完的 4 轮在 eval 眼里
   等于没收敛，还得再跑一轮。对齐后单轮即收敛到 eval 标准，避免 double-work。
3. **诚实代价**：对齐后 harness 会诚实显示 7 例失败，fix 轮次可能不比现在少（可能 5-6 轮才真
   修完 fp64 参考下的 7 例），但每轮都朝 eval 标准走，不存在「跑到头发现白跑」。

## 四、真正的大头与后续加速方向

1. **单次 redeploy 5-7min（build_run.sh:43 / build_wheel.sh:23 无条件 rm -rf build 全量重编）×
   23 次 ≈ 1.9h →【已实施】** cann-bench profile 声明 `incremental_command_template`（`[ -d
   build ]` 门 → cmake 复用只重编改动 kernel / else 全量），BuildStage 新增该可选字段。
   预期 5-7min/次 → ~3min/次。其他仓 profile 不声明，恒走全量（零影响）。
2. **fix#2 的 227 turns agent 试错** → diagnose 直接产出「计算形 + 精度约束」的可执行 fix_plan，
   减少 fix agent 试错轮数。【未实施】
3. **设计阶段守精度约束（skill 层）** → 设计精度分析必须验证非 fp64 数值等价性 + golden
   算术/权重量化/硬件 FMA 语义，从源头避免 round2 级算术重写（本轮最大单点浪费）。【未实施】
