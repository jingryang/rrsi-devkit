# 69 — 设计子阶段 infra 错误分类传导（step-27 DEFER 反例）+ crash 轮 transcript 覆盖 — 方案分析（L3）

> 选项 / 选择 / 理由。**调研态，未冻结**——待用户拍板后再冻结、再写 L4。本轮不修改任何代码。
> 问题事实见 `06-problems.md` P93（主）/ P94（独立观察）。
> 来源 run：`20260720-095303-413565`（self_evolve_op / moe_re_routing / A2，buffer-kernel T1/T2/T3 失败）。

## 一、问题浓缩（引自 L1，不重复事实细节）

外部 LLM 网关 GLM-5.2 价格未配置（HTTP 400 `isRetryable=False`）+ 第 1 轮 spawn 被 `message_timeout=3600s` 硬切，两个 infra 性质的错误都没被 `_classify_error_type` 判为 infra（markers 不覆盖）→ `error_type=None` → 设计子阶段不消费 error_type（step-27 DEFER）→ 烧满 3 轮 iteration 预算，且在 missing_artifact 文案 / iteration reason / halt 文案三个独立层面**把外部基础设施故障误报成 agent 自身质量问题**。

一句话：**框架多处缺一条「这是 infra 错误（不可重试、非 agent 锅），别当逻辑失败处理」的贯通信号。** step-27 在 codegen 建了这条信号（`error_type="infra"`）却把设计子阶段的消费 DEFER 了；step-57 为 429 单开一条 marker 线；本次实证两者都没兜住「网关配置类 400 / spawn timed out」。

## 二、方案分层（四层互相独立，可分别拍板）

| 层 | 缺口 | 落点职责 | 受益面 |
|---|---|---|---|
| **层 1** backend 分类判据 | markers 不覆盖 timeout / 网关配置类 400（P93-c） | `capabilities/agent/*`（根因层） | 所有 stage |
| **层 2** 设计子阶段消费 error_type | DEFER 导致 infra 烧预算 + missing_artifact 误报（P93-d/e） | `orchestration/stages/design_substages.py` + `transition` | 设计子阶段 |
| **层 3** runner iteration reason | infra 被归 "quality check not satisfied"（P93-f） | `orchestration/kernel/runner.py` | 可观测 |
| **独立** crash 轮 transcript 覆盖 | 失败轮取证丢失（P94） | `capabilities/agent/opencode_backend.py` `_open_transcript` | 可观测 |

---

## 层 1 — backend infra 分类判据：文本 marker 扩充 vs 结构化判据

### 现状

- `_build_result`（`base_backend.py:241-285`）crashed 路径已自动 `_classify_error_type(crash_reason)`（line 32-33），机制在位。
- `_INFRA_ERROR_MARKERS`（step-27 A-1）= `No available channel` / `Usage limit reached` / `API Error: 401` / `API Error: 403`。本次 `"timed out"`、`价格未配置`/`price not configured` 均不命中 → `None`。
- opencode 后端 except 路径（`opencode_backend.py:364-376`）`crash_reason=str(e)`——**结构化 error 对象被压成字符串**，网关返回的 `statusCode:400 / isRetryable:False` 字段在压扁后只能靠文本反解。

### 选项

- **选项 A — 纯文本 marker 扩充**：往 `_INFRA_ERROR_MARKERS` 加 `timed out` / `price not configured` / `价格未配置` / `Invalid token` 等。
  - 优点：最小改动，复用 step-27 / step-57 既定范式，TDD 简单。
  - 缺点（四把尺子之「可维护」「可扩展」违例）：文本匹配脆弱——网关换文案即漏判（P93 旁证：同日 401 网关返回的是 `Invalid token`，与现有字面 `API Error: 401` 都不匹配）；每出现新文案要加一条，marker 集无限膨胀（step-57 已为 429 单立 `_RATE_LIMIT_MARKERS`，第三类错误再立第四个集合的趋势）。
- **选项 B — 结构化判据（statusCode + isRetryable）**：让 backend 在 except/crashed 路径**保留原始 error 对象**（不压成 `str(e)`），`_classify_error_type` 优先按结构化信号判：HTTP 4xx 且 `isRetryable=False` → infra；结构化信号缺失时回退文本 marker。
  - 优点（四把尺子）：可维护（判据是「不可重试的配置/鉴权/网关错误」这一稳定语义，非易变文案）；可扩展（新网关错误自动归位，无需手工加 marker）；可诊断（保留结构化字段便于 halt 文案精准）；架构合理（修复落在产生 error 的 backend 层，符合 §1.6 依赖注入边界）。
  - 缺点：需先确认 opencode/sdk 两后端在 except 时能否拿到结构化 error dict（opencode 的 APIError.data 含 `statusCode`/`isRetryable`，见 P93-a transcript 原文；sdk 侧需核对），有一定调研成本；`crash_reason` 字段语义需扩（保留 str 给人读 + 结构化给分类器）。
- **选项 C — A+B 组合（B 为主，A 兜底）**：结构化判据优先；文本 marker 作为结构化信号缺失时的回退（兼容 sdk_backend 现有 marker 范式，不强行铲除）。

### 推荐：**C（B 主 + A 兜底）**

理由（§1.2 组合）：用「正确改动」（B，结构化判据）承担主修复，保住「infra = 不可重试的配置/鉴权/网关错误」不变式；用「宽容兜底」（A，文本 marker 回退）兜住结构化信号缺失的老链路；不与 step-27/57 的既有 marker 冲突（它们退为 B 的回退分支）。**待用户拍板**：是否接受 B 的调研成本（核对两后端结构化 error 可达性），还是先上 A 应急。

### 范围边界（待拍板）

- 是否把 step-27 的 `_INFRA_ERROR_MARKERS` 与 step-57 的 `_RATE_LIMIT_MARKERS` 统一到一个「按结构化信号分流」的分类器——**倾向不在本步做**（属另一次重构，避免扩大面，§1.2 最小改动）。

---

## 层 2 — 设计子阶段消费 error_type：修撤 step-27 DEFER

### 现状

- step-27「范围边界」明文 DEFER 设计子阶段接线，理由：无 sticky 熔断器、resume 天然重跑、不会永久卡死。
- 本次反例：虽不永久卡死，但 (1) 烧满 3 轮 ×（第 1 轮最多 3600s）iteration 预算；(2) missing_artifact 把 infra 误报成「写错目录」喂给下一轮（P93-e）；(3) iteration reason 归 quality check（P93-f）。DEFER 的「不会卡死」前提仍成立，但「不会造成大问题」被证伪。

### 选项

- **选项 A — 全 `_DesignSubstage` 接线**：`transition` 失败尾判 `agent_result.error_type=="infra"` → 首次即短路（不再烧 iteration 预算）+ `last_error.error_type="infra"` + halt。撤销 step-27 DEFER。
  - 优点：与 codegen 对称；彻底治「烧预算」。
  - 缺点：扩大面（step-27 当初 DEFER 即为避免 overdesign）；需明确「infra 首次短路」的语义——是 halt 该 stage（ForkJoin 下游靠 step-65 join 信号停），还是直接 halt run；与既有 missing_artifact → user_feedback → 重试的迭代语义有交互，需小心不破坏 design-halt-diagnostics 决策5 的反馈通道。
- **选项 B — 仅 `_missing_artifact_error` 感知 infra（最小改动）**：调 `_missing_artifact_error` 前先看本轮 `agent_result.error_type`；若为 infra，跳过「写错目录」文案，改报 infra 文案、且**不写误导性 `user_feedback`**（不教 agent 去修路径）。
  - 优点：最小、精准修 P93-e 误报；不动 iteration 预算语义，与 step-27 DEFER 的「不扩大面」一致。
  - 缺点：不治「烧 3 轮」（P93-d 仍在）——infra 仍会被当可重试失败烧满预算。
- **选项 C — B + transition 短路（组合）**：B 修误报（可诊断），加一个轻量 transition 守卫：infra 时 `last_error.error_type="infra"` 并让该 stage 在首次 infra 即终止迭代（不烧满 3 轮），但**不引入 codegen 式 sticky 熔断器**（resume 仍天然重跑，保 step-27 DEFER 的合理内核）。
  - 理由（§1.2 组合）：B 是「正确改动」修可诊断违例；transition 短路是「正确改动」修预算浪费；不抄 codegen 熔断器是「克制」——设计子阶段没有「永久卡死」风险，无需跨 resume 计数。

### 推荐：**C**

理由（四把尺子）：可维护（infra 短路逻辑与 codegen 同构但更轻，不引入设计子阶段不需要的熔断状态）；可扩展（任何设计子阶段遇 infra 自动短路，不逐 stage 接线）；可诊断（halt 文案 + iteration reason 都能据 `error_type="infra"` 给准确信息，正是本次 triage 被带偏的教训）；架构合理（修复落在 `_DesignSubstage` 的 transition，不越层兜底）。

**对 step-27 DEFER 的处置**：不整体撤销 DEFER，而是**收窄**——保留「设计子阶段不需要 sticky 熔断器 / resume 天然重跑」内核，补「设计子阶段需要 infra 感知（短路 + 不误导）」。即 DEFER 的是「熔断器」，不是「infra 感知」。**待用户拍板**：同意此收窄，还是倾向更保守的 B（只修误报、暂不短路）。

### 范围边界（待拍板）

- ForkJoin 下的 infra 短路与 step-65（forkjoin-branch-halt）join 信号的关系：infra 短路该分支 stage → 走既有 fail_strategy=halt → step-65 的 join 处理失败分支。**预期无需改 step-65**，但 L4 须验证。
- 与 design-halt-diagnostics 决策5（missing_artifact user_feedback 通道有效）的兼容：B 明确「infra 时不写路径修正 feedback」，与决策5 不冲突（决策5 说通道有效，不是说任何情况都该喂路径修正）。

---

## 层 3 — runner iteration reason：加 infra 类

### 现状

pipeline-observability P7 的 iteration reason 三分类（`contract unsatisfied` / `quality check not satisfied` / `agent continuing`）无 infra 类，infra 被归到 `quality check not satisfied`（run.log line 130 实证）。

### 选项（单一，无实质分歧）

扩第四类 `infrastructure error (unrecoverable): {reason}`——runner 在判 iteration 原因时，若上轮 `agent_result.error_type=="infra"`，reason 标此类。与层 2 的 `error_type="infra"` 信号同源。

### 推荐：**做**

理由（四把尺子之「可诊断」）：直接对应本次 triage 被「quality check not satisfied」带偏的教训；与层 1/层 2 同源信号，几乎零额外成本。**待用户拍板**：是否与层 2 同批做（依赖层 2 把 error_type 透传到 runner 可见处）。

---

## 独立项（P94）— crash 轮 transcript 被 next iteration 覆盖

### 现状（机制待定位）

`_open_transcript(agent_name, branch_label)` 的 seq 分配 + 打开模式（truncate?）未在本分析中逐行确认。L1 P94 的推断是：crash 轮 transcript 已被 `_open_transcript` truncate 打开、却没写 record，下一轮同 seq 再次 truncate → 覆盖。

### 选项（初稿，待定位后定稿）

- **选项 A — 每 spawn 唯一 seq**：seq 不按 (agent, branch_label) 复用，而是每 spawn 递增（含 crash 轮），crash 轮 transcript 留独立文件。
- **选项 B — crash 路径 flush + 保留**：except 路径把已 open 的 transcript 强制 flush 并重命名加 `.crash` / 轮次后缀，避免被下一轮覆盖。
- **选项 C — 仅可观测**：不修覆盖，但在 events.jsonl 的 spawn_context 里记录「该轮 transcript 可能被覆盖」的标记，提示排查者去看 native session（run-diagnostic-provenance step-67 的 pack-run 双份对照）。

### 推荐：**先定位再定**

L4 动手前必须先读 `_open_transcript` + `_write_transcript_record` 确认 seq/truncate 语义，否则选项是空中楼阁。倾向 A（根因层，crash 轮取证本就该留），但**待用户拍板**是否纳入本批（它与 P93 的 infra 主线正交，可独立排期）。

---

## 三、推荐执行顺序与拍板点（汇总，待用户决策）

| 顺序 | 层 | 推荐 | 关键拍板点 |
|---|---|---|---|
| 1 | 层 1 | C（结构化判据主 + 文本 marker 兜底） | 接受 B 的调研成本（两后端结构化 error 可达性）？还是先上 A 应急？ |
| 2 | 层 2 | C（missing_artifact infra 感知 + transition 短路，不引熔断器） | 同意「收窄 step-27 DEFER」而非整体撤销？还是先只做 B（仅修误报）？ |
| 3 | 层 3 | 做（iteration reason 加 infra 类） | 与层 2 同批？ |
| 4 | P94 | 先定位 _open_transcript 再定 | 纳入本批还是独立排期？ |

## 四、本轮明确不做（边界）

- **不修改任何代码**（用户定调「没有我的决策，先不要修改代码」）。
- **不冻结本 L3、不写 L4**：以上为调研态选项 + 推荐 + 理由，待用户拍板后冻结为决策、再产出 L4 符号级改动配方 + TDD 红→绿。
- **不重构 marker 集合统一**（step-27/57 marker 合并）——属另一次工作，避免扩大面。
- **外部根因（网关 GLM-5.2 价格配置）不在本方案范围**——那是 new-api 网关运营设置，需在 `192.168.0.212:8082` 后台开启自用模式 / 配置模型价格，框架侧方案只解决「网关故障时框架如何不误报、不空烧」。

## 五、关联产权（不重复，仅引用）

- step-27（`27-infra-error-classification-impl.md`）：infra 分类机制 + 设计子阶段 DEFER（本步层 2 收窄其 DEFER）。
- step-57（`57-burst-429-resume-analysis.md`）：429 marker 扩充 + 退避 resume 先例（本步层 1 判据设计的参照）。
- design-halt-diagnostics（决策5）：missing_artifact user_feedback 通道有效（本步层 2-B 与之兼容）。
- pipeline-observability（P7）：iteration reason 三分类（本步层 3 扩第四类）。
- opencode-artifact-provenance（step-66）/ run-diagnostic-provenance（step-67）：transcript 落盘（本步 P94 与之正交）。
- forkjoin-branch-halt（step-65）：ForkJoin join 失败分支处理（本步 infra 短路预期复用其 join 信号，L4 验证）。
