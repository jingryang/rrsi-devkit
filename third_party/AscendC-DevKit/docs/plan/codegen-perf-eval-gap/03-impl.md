# L4 实施方案 — eval 超时归档 partial 报告（§P3 选项②）

> 对应 L3 冻结选项②。改动清单 + 验证。

## 改动 1：scorer 传 `--output` 到已知路径

`CannbenchScorer` 的 kernel_eval argv 加 `--output ws.subprocess_log/cannbench_eval_<op>.partial.json`
（ws 可用时；kernel_eval 的 evaluator 增量写它）。`_eval_partial_path` 返回 `str|None`（ws=None → None，不传）。

## 改动 2：超时分支归档 partial 报告

`_archive_eval_partial`：超时后读增量 partial json，WARN 留痕「N case(s) completed and archived」，
score 仍按 infra 0。dump 与 archive 都 try/except（可观测性绝不崩错误路径，§1.2）。

## 验证

1. UT：`test_timeout_archives_partial_report`（超时 + 有增量 partial → 留盘且含已完成 case）先红后绿。
2. 全量 `tests/ut --quick`。
3. 真实回放（§3.11 需用户决策，因会再跑 30 分钟 eval）——下次同类超时自然验证。

## 不做

1. 不按算子名特判（§1.12）；2. 不加性能 halt（§L3 P2 分析）；3. 不动 30 分钟超时墙本体。

## as-built（2026-08-26）

- 改动 1/2 按上落地；`_eval_partial_path` 加 ws=None 守卫（单元测试 ws=None 场景）。
- TDD：`test_timeout_archives_partial_report` 先红（原无该路径）后绿。
- 全量 `tests/ut --quick` **3645 passed / 0 failed**。
