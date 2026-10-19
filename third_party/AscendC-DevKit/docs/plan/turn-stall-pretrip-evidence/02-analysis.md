# L3 方案分析 — 判死前取证 + 杀工具不杀会话

> 状态：**冻结（2026-08-27 用户拍板：按建议实施；工具容忍界必须配置文件可配置）**。

## 0. 本质

看门狗判「死」的唯一依据是**传输静默**（SSE 三信号），而「agent 正在干什么」的
事实（bash running / 已跑多久 / 部分输出 / 进程活性）就在同一台机器上，从未被
消费——用机制特征（无流事件）代理业务语义（死/活），与 §1.10 同族。这是同一
缺陷的第三次现身：step-94（coder 的 smoke 子进程死活不可观测）、step-96（质量
事实不流转）→ 本次（agent 的工具执行死活不可观测）。

四杀里只有 kill-1/2 属看门狗设计人群（工具已完、静默）；kill-3 是纯误杀（工具
在飞、事实在盘上）；kill-4 是 workflow 墙（另案）。**判死前取证同时解决「误杀」
与「该杀谁」两个问题。**

## 1. 主修复 D1：trip 前取证（pre-trip evidence probe）

**单点落在 `opencode_backend._post_message_watched` 的看门狗循环**（判死的唯一
权威层，§1.15）：turn_stall 门与 keepalive 门在 trip **之前**，先对本 spawn 的
opencode db（per-spawn XDG → `data/opencode/opencode.db`，sqlite 只读、短超时、
best-effort）查该 session 最新 tool part：

| 取证结果 | 动作 |
|---|---|
| 最新 tool part `status=running` 且未超工具容忍界 | **不判死**——工具在飞，看门狗基准复位；顺带把 `metadata.output` 尾部透一行 `agent_stream` 日志（运维可观测：正在跑什么、已吐什么） |
| `running` 但超工具容忍界（挂死） | **杀工具不杀 serve**：定位 serve 子进程中 cmdline 与该 part command 匹配者，SIGKILL 其进程树 → opencode 把工具错误交还 agent → agent 带事实继续，新 turn 自然到来，看门狗复位 |
| 无 tool part / 已 `completed` 且静默 | 真静默（kill-1/2 人群）→ **现行 kill-serve 逻辑原样保持** |

- hard cap（workflow 墙）**不**接受取证门控——墙是真 deadline，到期必杀；
- 取证查询本身失败（db 锁/缺失）→ 退化现行行为 + warn（fail-open 有界、不冒充，
  §1.2）；sqlite 只读连接 + **短超时（≤1s）**，绝不阻塞看门狗循环（实施期实证
  本批 db 的 journal mode：WAL 则读写无锁冲突，非 WAL 则退化频率上升——退化=
  回到现状误杀率，不更糟）；
- 杀工具后的兜底：若 opencode 对被杀工具的回收本身挂死（未预期形态），后续静默
  再取证时已无 running part → 落入第三行 → kill-serve。有界。

### 决策表闭合性（反面质疑补：97-c 从「兜底」升格为「楔死检测器」）

三分支 + 匹配失败退化**组合成闭合决策表**，缺一不可：

| db 取证 | 界内？ | serve 后裔活进程匹配 | 动作 |
|---|---|---|---|
| running | 是 | —（不查） | 复位（工具在飞，活着） |
| running | 否（超容忍界） | 匹配到 | **杀该进程树**（真挂死工具）→ agent 带事实继续 |
| running | 否 | **匹配不到**（bash 早已死、serve 楔死未更新 part） | **kill-serve**——这是 serve 楔死形态的唯一检出通路（否则 db 恒显 running，看门狗被永久麻醉） |
| 无 part / completed | — | — | 现行 kill-serve（真静默） |

- 若没有第三行，serve 楔死（子进程死透、part 状态卡 running）会让 probe 永远
  报活——97-c 不是可选兜底，是闭合性必需；
- **进程搜索范围 = 本 serve pid 的后裔树**（opencode 工具进程是 serve 子进程）：
  限定后缀结构上不可能误杀其他算子/其他 execution 的进程；匹配用 db part 的
  command 文本对后裔 cmdline（含脚本路径等稳定 token）；
- partial-output 透出频率：一次静默期只透一行（首次取证时），不逐 poll 刷屏。

### 同时消解

- **§P9 数值清零问题**：running 判据取代 `max(600,600)` 静态让位公式——公式可
  删（probe 语义覆盖它，§2.5 唯一通路）；
- **孤儿挂死进程占卡**（P2）：杀的是工具进程树而非 serve，不留孤儿；
- **kill-3 形态的成果蒸发**：session 不死 → 无 teardown → 无 rollback → resume
  失配链从源头断掉（与
  [`precision-teardown-turnstall-mismatch/`](../precision-teardown-turnstall-mismatch/02-analysis.md)
  互补：那边兜「确需 kill-serve 时」的语义）。

## 2. 防御层 D2：工具层超时（实施期查证后定）

- 若 opencode 版本支持 bash 工具超时配置（opencode.json）：设为小于工具容忍界的
  值——opencode 自己把超时错误交还 agent，框架连杀工具都不需要（D1 只兜无超时
  的形态）；
- 不支持则跳过（D1 已自足），**不为它升级/替换 opencode**（§1.7 外部件不迁就）。

## 3. 否决项

- **❌ 只修 §P9 数值**（keepalive_idle > turn_stall，如 600/1800）：静态界永遠
  区分不了「挂死」与「慢而合法」，只能再调魔法数——120↔600 的乒乓史（P131→P9）
  已证明这条路；
- **❌ 轮询进程表做判死（不查 db）**：进程→session/命令的映射没有权威源会认错
  对象；db 是 opencode 自己写的权威账（part.command ↔ 进程 cmdline 匹配才可信）；
- **❌ 只靠 skill 教验证纪律**（timeout 包装/后台轮询）：引导非保证（§1.14 帮
  模型不控模型）；框架层保证（D1）落地后，skill 里一句话的验证纪律可作顺手
  加持，不作为主修复。

## 4. 原则对照

§1.2 四尺子（可维护=判死单点收口/可扩展=未知长命令自动归位 running 分支/可诊断=
部分输出透日志+取证失败 warn/架构=判死权威层持有取证）；§1.10（用业务事实
「工具在飞」判，不用机制特征「无流事件」代理）；§1.15（判死唯一通路上加取证，
不另开旁路）；§2.5（probe 取代 §P9 让位公式）。

## 5. 拍板结果（2026-08-27，用户确认）

1. **工具容忍界**：配置文件可配置——`timeouts.opencode_tool_grace_s`，默认
   1800s（与 `opencode_turn_stall_s` 同一配置面）；**0 = 禁用杀工具**（running
   只作存活复位，不触发杀）；
2. 部分输出透出：每次取证一行 `agent_stream`，截尾 200 字符——按建议；
3. 杀工具的进程匹配失败 → 退化 kill-serve + warn——接受；
4. D2（opencode bash 工具超时）：实施期查证版本支持后定去留。
