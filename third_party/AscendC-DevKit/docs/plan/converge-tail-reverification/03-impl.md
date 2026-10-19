# L4 实施方案 — D1 质量事实随流转 / D2 绝对质量态 / D3 死亡位置二分

> 对应 L3（D1 冻结 + D2/D3 详述确认 2026-08-27；D4 暂缓）。

## 改动 1：D2 质量分级纯函数（precision_debug_substages.py）

- `_classify_best_quality(dc)`：good（total>0 且全过）/ partial（0<passed<
  total）/ bad（total>0 且 passed==0，零正证据）/ unmeasured（total==0）；
  刻度=证据有无，非比例；
- `PrecisionDebugResult` 增 `best_quality: str` 字段，`_sync_debug_result`
  物化时填入（§2.10 结构化流转）；
- 附带修复：`best_passed_count=int(dc.get(...) or -1)` 的 falsy 吞 0 bug
  （0 是 bad 态的合法计数，`or -1` 会把它误报「未初始化」）。

## 改动 2：D1 converge 决策消费事实（`_converge_to_best_commit`）

- 入口读 `_classify_best_quality(dc)`；
- **bad** → 不 rollback/不 redeploy best（对已知坏 kernel 重新 build+smoke
  = 用崩溃重新发现已知事实，99c4c0 形态）；保留既有 deploy_result（部署阶段
  已验证的产物记录）；结构化 Logger.error 携带 passed/total/status；质量事实
  经 `debug_result`（best_quality/best_passed_count/failing_cases/halt_reason）
  流转 eval/report；
- **unmeasured**（total==0）→ 现行重部署路径（smoke 即首测）；
- **good/partial** → 现行重部署路径保持（此时 smoke 崩是真意外）。

## 改动 3：D3 死亡位置二分（smoke 失败分支）

- 分类器提升为模块级单点 `codegen.classify_smoke_failure_phase(err)`
  （§1.15——与 codegen 重试路由共用；类内留 staticmethod 别名，调用点零改动）；
- smoke 失败且 `phase == "kernel"`（launch 后设备侧死亡，507035 族）→
  **质量信号非部署失败**：接受新鲜 deploy_result（eval 本不以 smoke_passed
  为门——cannbench_eval.py:56 明示；新鲜包才是安装一致态，precision 期间的
  redeploy 可能已覆盖共享 OPP 目录）；
- `phase == "host"`/None → 现行 fallback（保留 prior deploy_result）。

## 范围诚实记录

- eval 内部 per-case 的「预期失败不执行」：per-case 执行在 cann_bench
  （外部仓）内，框架侧无法注入 skip——D3 的框架侧语义止于「部署放行+质量
  事实流转」；cann_bench 侧改动属外部仓产权（§1.12/外部 infra 边界）。
- D4（截断态一等化 + spawn 前预算检查）：用户拍板暂缓（预算不好评估）；
  `status` 字段已作为事实随 debug_result 携带。

## 验证（UT `tests/ut/orchestration/test_step96_converge_quality.py` 10 例）

- D2 四态 + 0==0 陷阱；
- D1 bad 不动树/不重部署、unmeasured 现行路径；
- D3 kernel 放行新鲜包 / host 保守 fallback / 歧义区保守 fallback；
- `_sync_debug_result` 携带 best_quality（terminal 态物化）。

## as-built（2026-08-27）

- 改动 1-3 全部落地；全量 UT 3736 绿（含既有 precision 套件 172 例）。
- 有效性最终验证属下批真实跑：观测点 = best 0/20 类算子的收尾路径
  （应见 quality=bad 记录、无 redeploy 崩溃重发现、不断链）。
