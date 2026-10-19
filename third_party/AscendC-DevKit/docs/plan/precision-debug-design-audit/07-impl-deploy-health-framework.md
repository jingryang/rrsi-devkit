# L4 实施方案：deploy_health 框架自算（P1 完整版）

> 对应 L1 [01-problems.md](01-problems.md)（P1）+ R3（`../design-artifact-retry-observability/issues/R3-deploy-health-responsibility-misplaced.md`）。
> R3（null 值域校验）是申报消费期的过渡补丁；本方案把判定输入换成 CLI 确定性产物，申报层彻底删除（§2.5）。

## 0. 实施中的意外发现（比方案本身更重要）

`CommentBisectSubstage` 有阶段 C 合并**漏删的 transition/resolve_condition override**（与基类逐行等价、仅 deploy 块不同）——导致 **R3 修复只落了基类，comment_bisect 仍带 rms_norm 原始 bug**（`dh.get("build_ok", True)` 把 null 误判失败）。§1.15"漏写一处即出错"的实证：同一行为的重复实现让后续修复只命中一份。本方案删除 override（基类泛化全覆盖），这是 P1 之外修掉的活 bug。

## 1. 机制

```
旧路：agent 每轮申报 _summary.deploy_health{build_ok, output_ok, agent_fallback}
      → 框架值域校验（R3）→ streak
新路：actions() 盖戳 spawn_ts.fw.json（框架自有 sidecar，agent 不可丢——
      同 harness_timeout.fw.json 先例）
      → agent 正常跑 build_command（redeploy CLI，无条件落盘 last_deploy.json）
      → transition 只消费 mtime ≥ 戳 的 last_deploy.json（本 spawn 窗口内）：
         build_ok  = install_path/python_path 非空（build+install 成功路径才有值）
         output_ok = smoke_passed（真实 fn() 调用探针）
      → streak 更新；agent 申报不再消费（申报显式 bool 但无新鲜产物 → WARN 违约信号）
```

- **新鲜度窗口**：窗口外（上轮 deploy / 本轮纯静态分析没跑 redeploy）→ 不更新 streak——R3"没 deploy 就没有 deploy 失败"语义的构造性版本。
- **sidecar 而非 control.json 键**：agent 重写 control.json 会弄丢框架自有字段（harness_timeout 历史实证），健康判定基准放框架自己的文件。
- **fail-open**：盖戳/读失败（OSError/JSON 坏）→ 不更新 streak（不误熔断）。

## 2. 改动清单

| 文件 | 改动 |
|---|---|
| `precision_debug_substages.py` | `_DeviceBisectSubstage`：actions 盖戳 + `_fresh_deploy_result` + transition 框架派生块；**删除 CommentBisectSubstage 的 stale transition/resolve_condition override**（活 bug） |
| 两 skill `SKILL.md` + `references/prompts/*` | deploy_health 从"每轮必写"改"无需申报"（含 heredoc 示例行） |
| 框架 prompt（printf/comment_bisect） | 同步收敛 |
| 测试 | `TestDeployHealthNullNoMeltdown`（R3）→ `TestDeployHealthFrameworkDerived`（P1）：盖戳/成功清零+谎报忽略/smoke 失败+1/build 失败+1/stale 不更新/无 deploy 不更新，6 测试 |

## 3. 三问对照

- **不 halt**：stale/absent → 不更新（静态分析轮不误熔断）；fresh 失败 → streak++（熔断语义保留，3 次是设计内预算退出）；agent 谎报被忽略（框架真值优先）。
- **兜底**：sidecar/产物读失败 → fail-open 不更新；agent 申报违约 → WARN 可观测。
- **消费者**：streak → `resolve_condition` deploy_broken（程序化）；`deploy_health{source=framework}` → control.json 留痕；WARN → run.log。

## 4. 验证

- [x] precision_debug UT 244 全绿（含 6 个新 P1 测试）
- [x] orchestration + capabilities 全量 2253 passed
- [ ] 批跑实证（下次批跑覆盖：printf/comment_bisect 轮的 deploy 健康来源与熔断行为）
