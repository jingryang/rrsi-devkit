# infra/未知失败默认有界重试（fail-open）— 方案分析（L3）

> 有哪些选项、选了哪个、为什么。事实见 `01-problems.md`（P1/P2/P3），实施见 `03-impl.md`。

## 目标（拍板）

凡「agent 没干净跑完一轮」的失败（crash / 被杀 / 环境故障 / 连接重置），默认走**有界**退避重试
（fresh resample），预算耗尽才 halt；「跑完了但产物错」（logic）仍走 stage loopback。方向是
**默认 fail-open，halt 仅预算耗尽**。

## 选项

### A — 把连接重置判为 `aborted="hard_timeout"` 借道 P131c 重试（否决）

把 `_is_hard_timeout_exc` 扩到覆盖 `ConnectionError`，让连接重置也得到 `aborted="hard_timeout"`，
自动走 P131c 重试。**否决**：`aborted="hard_timeout"` 语义是「看门狗杀掉了一个还活着的、只是卡住的
spawn」，下游还带 D5 teardown/回滚语义（`_run_stage_teardown` 按 hard-kill 处理 op_dir 半写状态）；连接
重置是「serve 没干净起来」，是**另一种**业务语义。硬塞同一标签 = 让一种错误冒充另一种（§1.10 反模式），
且会无谓触发一次 op_dir 回滚。

### B — 独立 `error_type` 值 + 集中重试谓词 + 默认 fail-open（采纳）

- 分类（fact）：新增 `error_type="infra_transient"`（连接重置/断开，可重试），与既有 `"infra"`（永久
  config/quota/auth）并列；`aborted` 保持「被杀活 spawn」不变。三者正交、标签诚实、日志可区分。
- 重试决策（policy）：一个集中谓词 `is_infra_failure(result)`，凡「没干成活」都进**有界**重试
  （复用 P131c 的 `_infra_backoff_retry` 预算），含永久 `"infra"`（用户决策：永久 infra 也值得有界重试，
  赌分类可能错）；预算耗尽才 halt。
- 反散弹（§2.5 单一通路）：分类、结果构造、重试谓词、重试决策各只有**一个权威实现点**；marker 列表从
  「重试门槛」降级为「halt 原因诊断标签」，新错误默认进重试、不再需要往 marker 加文案。

采纳 B。

## 已拍板（2026-08-14）

1. **预算统一**：永久 `"infra"` 与瞬时 `"infra_transient"` 共用同一套 `infra_backoff()` 预算
   （默认 max_retries=4、backoff 总时长 600s）。不另设更小预算参数——简单、单一通路。
2. **`empty_artifacts` 不进 infra 重试**：属 logic（干净跑完、无产物），走 stage contract/loopback。
   `is_infra_failure` 以 error_type/aborted 为权威信号、不看 status，故天然排除。
3. **teardown 仅 `aborted` 触发**：连接重置/永久 infra 时 spawn 没写 op_dir，不回滚。

## 实施修正（比 03-impl 初稿多出的一处关键改动）

初稿 `is_infra_failure` 拟用 `status in ("partial","fatal")` 判「crash」，但 `status="fatal"` 在 AgentResult
上语义歧义（`_build_result` 里 = crash，历史测试里 = logic）。改为：**`_build_result` 对所有 crashed 结果兜底
`error_type="infra_transient"`（未知 crash 也归瞬时）**，`is_infra_failure` 只认 `error_type/aborted`。这样
「未知 crash」也进有界重试，且不误伤 logic。

## 边界与风险

- 有界重试不会回到历史 401 空转 38 分钟（那是无界重试）；有界（`infra_backoff()` 的 count + backoff 总时长）
  后仍 halt，且 halt 原因更可诊断（「bounded retry exhausted」+ failure_reason）。
- `should_server_backoff`（in-session 429/503 resume）是另一条机制（session 未断、软拒绝），本方案不动它，
  不把两条重试通路混为一谈。
