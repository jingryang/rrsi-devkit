# 测试超时自适应 + scope_guard 职责边界 — L3 方案分析

> 层级：**L3 / 方案分析**。记录有哪些选项、选了哪个、为什么；调研中演进，拍板后冻结。
> L1 问题记录见 `01-problems.md`。

## 结论摘要（已冻结）

| 决策点 | 选择 | 替代被否原因 |
|---|---|---|
| 超时配置入口 | config `timeouts.harness_sec` 默认 + 请求覆盖（control.json 运行时放大） | 仅 CLI 传参 / 仅 env 均不如「config 默认 + per-run 覆盖」结构化 |
| 大 shape 判定 | **run_tests agent 语义评估**（结合算子类型 + 元素量级 + 超时值，不设硬阈值） | 元素阈值硬判依赖算子/硬件，不准；无条件放大重试浪费非大 shape 的一次超时等待 |
| 重试落层 | **run_tests 编排层**（agent 放大写回 control.json → 重跑 run-cases） | runner 内机械重试拿不到「是否大 shape」的语义判断（§1.12 不耦合算子） |
| 放大值持久化 | control.json `harness_timeout_sec`（三阶段共享） | 一次性放大则 fix/printf 复验重复超时，违背「后续测试感知」 |
| 职责边界 | run_tests 只如实传递 `observed_issues`；scope_guard 判定暴露 | run_tests 自行判 upstream/env 违反门边界（§2.9：发现问题修不了 → 制造噪音） |
| 放大上限 | `harness_timeout_max_sec = 1200`（用户指定） | 600 对超大 shape 仍不足 |
| 改动面 | 7 代码文件 + 3 skill 文件，每个改动极小（加参数/字段 + 透传） | 用户要求改动少、易评估影响 |

---

## 1. 超时配置入口

**选项**：
- A. config 默认（`timeouts.harness_sec`）+ 请求覆盖（`EvalRequest.test_timeout_sec`，由 debug_service 从 control.json 解析）
- B. 仅 `run-cases --test-timeout` CLI 参数
- C. 仅环境变量（仿 `WORKFLOW_TIMEOUT`）

**选择 A**。理由：
- 与既有超时配置体系一致（`timeouts` 段 + runtime_config loader 风格）。
- control.json 的 `harness_timeout_sec` 天然是 precision_debug 的 per-run 运行时覆盖载体（init-checkpoint seed + agent 放大写回），与 CLI/env 相比**无需额外透传层**。
- CLI `--test-timeout` 砍掉：非 precision_debug 的普通 run-cases 调用可用 config 默认，precision_debug 用 control.json 覆盖，两者覆盖了全部调用方诉求。

## 2. 大 shape 判定方式

**选项**：
- A. 元素总数阈值硬判（`max_input_elements > 阈值`）
- B. 无条件放大超时重试一次，用重试结果归因
- C. **run_tests agent 语义评估**（结合 shape 元素量级 + 算子类型 + 超时值）

**选择 C**（用户确认）。理由：
- 「大 shape」是**相对算子/硬件的语义判断**：一个 10M 元素的 reduce 算子可能慢，10M 的 add 很快。硬阈值（A）依赖算子/硬件，必然在某些场景误判；无条件放大（B）在非大 shape 超时（环境/死锁）时白白多等一次超时。
- agent 评估需要**客观输入**：runner 超时返回 `tested_cases` 摘要（各用例 shape + `max_input_elements`）——解决 L1-P3 的 shape 丢失。
- SKILL.md 给参考量级引导（元素数百万级起步），不设硬阈值，符合 §1.12（不耦合具体算子）。

## 3. 重试落层

**选项**：
- A. NPURunner 内机械重试（runner 有 test_cases，超时后自动放大重跑）
- B. **run_tests 编排层**（agent 评估大 shape → 放大写回 control.json → 重跑 run-cases）

**选择 B**（用户确认）。理由：
- 大 shape 判定归 agent（决策 2），重试必须由 agent 驱动。
- 放大值持久化到 control.json，`debug_service.run_cases` 读 control.json 覆盖 → **三阶段（run_tests/fix/printf_location）自动共享**同一放大超时——fix 复验、printf 单用例跑同一大 shape 用例同样慢，共享避免每阶段各自超时→重试。
- 有界：`×4` 每级、上限 1200s、仅大 shape 触发；死锁最坏等 1200s 封顶。

## 4. 职责边界（run_tests 传递 vs scope_guard 判定）

**设计**：run_tests 把本轮发现的问题观察写成**通用清单 `observed_issues`**：
`[{"category": timeout|upstream_signal|test_script|golden|env|other, "evidence": 日志原文, "case_id"?, "timeout_reason"?}]`。
run_tests **只分类观察、不做「是否暴露」的决策**；`resolve_condition` 检测 `observed_issues` 非空 → 路由 `needs_scope_check` → scope_guard 重判。

**为什么通用清单而非硬编码字段**（§1.12）：
- 用户明确要求「run_tests 发现的任何问题（测试脚本、golden 等）都能如实传递」——对具体信号写死字段会在新问题类型出现时打补丁。
- `category` 枚举可扩展；run_tests 分类是客观观察，判定（upstream/pass/env_blocker）归 scope_guard。

**为什么不是 run_tests 自行判定**（§2.9 门的边界）：
- run_tests 若自行判「上游、不进调试」= 在发现问题却无法解决的阶段制造决策，且与 scope_guard 语义重复；发现与判定分离，判定方（scope_guard）有完整证据链 + 预算兜底。

**scope_guard 触发扩展**：
- 从「仅首轮（scope_checked != true）」扩展为「首轮 **或** `observed_issues` 非空」。
- 判定后框架清空 `observed_issues`（消费），只对新观察重判。
- 判定输入新增消费 `observed_issues`（回 run.log 核对原文），`scope_verdict.json` 的 `evidence` 升级为 `{source, quote, basis}` 逐条可审计结构（用户要求更详细日志）。

**fix 引入的回归 vs 真实上游缺陷（重判时防误 halt）**（用户确认的风险）：
- 循环中 fix/printf 修改 kernel 后，可能**自己引入**编译错误 / schema 不匹配 / `Cannot find binary`。若重判把这些当「上游产物缺陷」halt，会把**本该继续修复的问题错误终止**。
- **判据**：重判时查首轮 run_tests history——信号在首轮**不存在**（首轮无此类别，fix 修改后新出现）→ **fix 引入的回归，判 pass**（本阶段职责，fix 继续修复或回滚）；信号指向的产物（golden/test_design/deploy）**从未被本循环修改**且首轮即存在 → **upstream**。拿不准倾向 pass。
- 本质：**「上游产物缺陷」仅指循环开始前就存在的上游产物问题**；循环内 kernel 改动引入的回归归 fix，不归「上游」。

## 5. 超时归因语义

| timeout_reason | 含义 | 处置 |
|---|---|---|
| `large_shape_resolved` | 大 shape 放大超时后重试成功 | 非缺陷，记录，继续循环 |
| `large_shape_over_cap` | 放大到上限仍超时 | 如实反馈「大 shape 超上限」，不消耗精度预算空转 |
| `non_large_shape` | 非大 shape 超时 | 如实反馈「疑似环境/死锁」，不重试 |

归因写入 `failed_case_queue` 条目 + `observed_issues`（category=timeout）。best_metrics 语义不变（超时仍计入 failed）。

## 6. 权衡与边界

- **改动面**：7 代码文件（config / runtime_config / runner / evaluation / precision_debug / debug_service / substages）+ 3 skill 文件（run-tests SKILL.md + run_tests.md + scope-guard SKILL.md + scope_verdict schema）。每个改动是「加参数/字段 + 透传」，无逻辑重构。
- **不改 init-checkpoint**：substages 的 `_CONTROL_REQUIRED_KEYS` + `_CONTROL_DEFAULTS` 在 `_load_control` 时 auto-repair 缺失的 `harness_timeout_sec`（用 config 默认），旧 control.json 兼容。
- **不动 routing 表**：`precision_debug_tree.py` 复用既有 `needs_scope_check` 路由，无需改。
- **不设环境终止出口**：本次 scope_guard 对 `env` 类别只做暴露（scope_reason 标注），终止出口联动 `precision-env-blocker/` 方案留后续。
