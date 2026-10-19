# F5: `empty_artifacts` 在 runner 与 codegen 两处语义冲突

## 现象

同一状态 `empty_artifacts`（agent 无产物产出），在框架两个地方被当作**相反**的语义：

- **runner**（`runner.py:567`）：`agent_status not in ("ok", "empty_artifacts")` → failed。即 **`empty_artifacts` 视为 ok**（"合法无产出阶段"）。
- **codegen transition**（`codegen.py:2862`）：`empty_artifacts` 走失败分支，`codegen_consecutive_failures + 1`，3 次触发 circuit breaker（`max_consecutive_failures=3`）→ halt。

## 凭什么这么说（证据）

- moe_re_routing 的 codegen：3 次 spawn 全 `empty_artifacts` → `codegen_consecutive_failures` 累加到 3 → circuit breaker 返回空 actions → stage `[failed]` + `fail_strategy=halt`。
- 同一 `empty_artifacts` 在 requirement（continue 策略）下被 runner 视为 ok，继续下游。

## 影响

- codegen 熔断 3 次即 halt，**实际是"对的"**（防止无限烧 token），但**语义不自洽**——靠 status 字面量巧合判对，换个 stage 或换个状态流转就误判。
- `empty_artifacts` 本身含义模糊：它同时可能是"合法无产出"（某些 continue 阶段）与"该产出却空跑"（codegen）。

## 根因定位

用 status 字面量（`empty_artifacts`）作语义判据，而不是用**业务语义**（该 stage 是否必须有产物）。按 CLAUDE.md §1.10，判据应用业务语义显式声明（stage 声明"必须有产物"），而非机制特征。

## 补充

这不是"该不该熔断"的问题——熔断是对的。问题是**判据**：应改为"该 stage 有 output_contract.provides 却 empty → 失败"，而不是对所有 stage 一视同仁按 status 字面量。
