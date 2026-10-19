# Membase codegen build-retry 空转与方法论缺失 — 方案分析（L3）

> 选项 / 选择 / 理由。决策拍板后冻结。问题事实见 `01-problems.md`。
> 关联：阶段 1 已落地（见记忆 `codegen-signature-footer-phase1`，`deploy.py` build 失败日志富化），
> 本文档为阶段 2（治本）的方案分析。同源 `batch-205112-codegen-precision-halts`。

## 决策 1（P1+P3）— build-retry 修法：prompt-only 方法论 / 框架工具 / 框架驱动 → **选框架驱动**

- **选项 A 仅强化 in-session prompt 的方法论**（在 `codegen.py:1199-1219` 补「先分类→按类施策→
  换策略」指令）：改动最小。但 `ascendc-coder.md:20-22` 与 `codegen.py:1018` 已有「编码前查
  INDEX.md 拿签名」的指令，transcript 实测被跳过 244 次（P3）——prompt-only 仍是 LLM 自觉，
  不可靠，等于把同一遗漏留在原地。
- **选项 B 框架提供工具，agent 在循环里调用**（如 `ascendc-devkit lookup-signature` CLI，
  agent 见签名错时调用拿权威指路）：计算确定性，但「是否调用」仍靠 agent 自觉；且不解决
  分类/梯度/升级的**执行**问题。
- **选项 C 框架驱动 build-retry**（仿 Regbase `s5-compile`）：agent 每个框架迭代只生成一版代码 →
  框架跑 build → 框架分类错误 → 按 retry-gradient（同策略→换策略→升级）调度下一轮；持久化重试预算
  + 稳定性约束。让分类/梯度/预算**确定性执行**，框架全程可见。
- **选 C 的理由**（四把尺子）：
  - 可维护：与 Regbase `s5-compile` 同构，复用 `classify_compile_error.sh` + 阶段 1 的
    `api_signature_lookup` / `build_failure_analysis_footer`，不另起一套。
  - 可扩展：新错误类自动走 gradient，无需为每类打补丁（§1.12 结构信号驱动）。
  - 可诊断：框架见证每次 build+分类+调度，可观测（P1 的「框架不可见」被消除）。
  - 架构合理：build-retry 归框架 L3 orchestration（`codegen.py` + `deploy.py`），agent 只管
    「生成代码」——职责落在正确层；不再让 agent 在会话内自跑无界 40 轮。

## 决策 2（P1）— 是否照搬 Regbase 的 s2→s4→s5 多阶段分解 → **不照搬**

Regbase 的多阶段分解（`s2-analysis` → `s4-coding` → `vf-test` → `s5-compile`）绑定 **VF 分阶段验证**
（A5 Regbase 专属，`ascendc-vf-test-agent` 用 `SingleOperatorLaunch` 隔离测 VF 函数）。Membase
（A2/A3，传统 AscendC Vector，无 VF/RegTensor）不需要这套分阶段验证。**只移植「框架驱动 build-retry +
gradient + 分类」这一通用机制**，不搬多阶段分解与 VF 单测。

## 决策 3（P3）— retry-gradient 的「3rd → FAILED」是否违背「不主动 halt」原则 → **不违背**

用户原则：只要有修复可能性就**不主动 halt**，只认外部硬超时 / 用户打断。gradient 的「第 3 次 →
返回 FAILED」**不是 halt**：编排器读取累计计数（`meta.json` `retries.used/.limit`）后决定——
未超累计上限则再调度一次（fresh 预算 `min(3, 30-N)`）、超限则升级。「第 2 次换策略」正是
「继续试、但换路子」。稳定性约束 `E(t) > 10 → 升级` 同理（升级到决策点，非静默 halt）。整套机制
与原则一致：**用「换策略 + 升级」替代「同策略盲重试 40 次」**，是在「继续试」的前提下让它能收敛。

## 决策 4（P2）— 编译错误进 `last_error` 的通路 → 随决策 1 自然消解，不单独处理

决策 1 把 build-retry 移到框架级后，编译错误在**框架的 build 步骤**产生，框架直接分类 + 调度，
不再需要经 `state.last_error`。P2「`last_error` 不含编译错」从「障碍」变为「无关」——框架驱动
路径不依赖 `last_error` 传编译错误。`last_error` 仍只承载结构/契约错误（其原有职责不变）。

## 决策 5 — 阶段 1（已落地）与阶段 2 的关系 → 阶段 1 是阶段 2 的子集，不白做

阶段 1 的 `deploy.py` build 失败日志富化（`build_failure_analysis_footer`：clang 摘要 + API 签名
权威指路）在阶段 2 框架驱动 build-retry 里**仍被复用**（框架 build 失败时的分类 + 签名指路同一份
产出）。阶段 1 已独立见效（签名类失败的瞎猜下降），阶段 2 在其上补「gradient + 分类 + 升级」的
**确定性执行**。两者不冲突、不重叠。

## 决策 6（阶段 3 启动，2026-08-03）— 完成决策 1 的完整 C：build-retry 循环外提到框架级

**背景（决策 1 实施复盘）**：决策 1 调研结论选 C（框架驱动 build-retry），但 L4 实施时（L2
step 81）**退化为「deploy 层 footer 通道」**——只在 `deploy.py` 加 classify / gradient /
`build_retry_state.json`，经阶段 1 的 footer 把分类送达 in-session agent，**没有把循环从
agent 内搬到框架**。L2 step 81 明文记录此退化理由：「选 deploy 层实现而**非**整体搬 agent
循环——复合阶段 1、低风险、非干扰」。

**794e81 实证（commit `014707a0`，含阶段 1 + 2）**：codegen 仍 **726 turn / 158min**、4 次
compaction，且 compaction 抹掉 agent 已达成的 smoke-passed（L1 P5）。即 deploy 层 footer
让 agent 看到了错误分类 / gradient（turn 数 974→726 下降），但：
- 循环主体仍在 agent in-session，框架对每一轮 build-retry 仍不可见（P1 未触及）；
- 跨轮里程碑（smoke 是否已过）是 agent 上下文记忆，compaction 一压就没（P5）。

→ deploy 层方案是「让 agent 看得更准」，不是「让循环归框架」——治标未治本。

**决策：启动决策 1 当初选定的完整 C**。把 build-retry 循环从 agent in-session 搬到框架的
iteration 机制：每轮 spawn 一个短 coder agent（只读本轮编译错误 + 当前代码 → 改一版 →
redeploy 一次 → 报告），框架 transition 读 `last_deploy.json` / `build_retry_state.json`
驱动下一轮；smoke 过 → 退出，没过 → 把 classify 后的错误作为反馈 spawn 下一轮。跨轮状态
走文件，不靠 agent 上下文。复用阶段 2 已落地的 `classify_build_error` /
`build_retry_gradient_section` / `build_retry_state.json`——它们本就是为框架级循环设计的，
阶段 2 建好但没接到主循环，本阶段接通。

**四把尺子复核**：
- 可维护：复用阶段 2 的 classify / gradient / state 设施，与 Regbase `s5-compile` 同构，
  不另起一套。
- 可扩展：框架级循环对任何 Membase 算子自动适用，不认算子身份（§1.12）。
- 可诊断：框架见证每轮 build + 分类 + 调度，P1「框架不可见」被消除。
- 架构合理：build-retry 归 codegen stage 职责（`actions` / `transition` + 已有 iteration /
  max_iterations / circuit breaker），agent 只管「生成代码」，职责落在正确层。

**约束（实施必守）**：
- **§2.5**：删 `codegen.py` 旧 prompt 里的 in-session max_rounds 自修指令（`_actions_membase`
  + `_build_codegen_prompt` 的 build 闭环段），替换为框架级循环——唯一通路，不留新旧并存。
- **§2.1 / §2.8**：in-session build 循环契约写在框架 prompt（`codegen.py`），不在 skill 本体
  （`ascendc-op-dev-coding/SKILL.md` 只讲编码方法，grep 无 redeploy / smoke / max_rounds）。
  故本阶段**不碰 skill 本体**，skill 即插即用与 TUI 单跑编码产物一致性不变。
- **§1.10**：框架级 retry 是横切控制流，判据消费 `classify_build_error` 的业务语义分类
  （C-API / C-TYP / unknown），不用机制特征代理。

**与阶段 1 / 2 的关系**：阶段 1（footer 富化）+ 阶段 2（deploy 层 classify / gradient /
state）是本阶段的**前置设施**，全部复用、不重做；本阶段补「把循环搬到框架、让这些设施真正
驱动循环」的最后一公里。阶段 2 不白做——没有它的 classify / gradient，框架级循环也无法做
错误分类驱动的调度。

## 本轮不做（登记留存）

- **VF 单元测试**（`ascendc-vf-test-agent` / `SingleOperatorLaunch`）：A5 Regbase 专属，不移植到
  Membase。
- **Regbase `s2→s4→s5` 分阶段分解**：见决策 2，不照搬。
- **真静默链接器案例**（transcript 70× `ld.lld: cannot open .o`，日志无 clang 行）：框架驱动
  build-retry + 分类对其帮助有限（日志无信号可分类）——需另走「指向 `kernel_meta` 编译日志」或
  运行时信号，**不在本方案范围**，单列后续。

## 待落点（L4 实施时定，本文档不写代码配方）

- `codegen.py`：把 in-session redeploy 循环（`_actions_membase` + prompt 1199-1219）改为框架迭代——
  agent 每轮生成一版，框架 build（`deploy.py`）+ 分类（复用 `classify_compile_error.sh`）+ gradient 调度。
- 复用 `domain/api_signature_lookup.py` + `domain/build_log_scanner.build_failure_analysis_footer`
  （阶段 1 产出）。
- 持久化重试预算字段（参照 Regbase `meta.json` `retries.*.used/.limit`）。
- L4 动手前另写 `03-impl-*.md`，含具体函数/顺序/验证。
