# L1 问题记录 — converge 收尾链对「best commit 仍坏」的核验-回退语义缺口（反复复现家族）

> 记录客观事实，不提方案。本次实证：批 20260826-114823-99c4c0 unique（execution
> 0f7ba0）；既往同族：ab7283 批 multi_add P5（docs/plan/self-evolution/
> batch-20260801-050054-ab7283-issues.md，已坐实至 tiling UB 公式少算）、以及
> 更早 run b5b4c895f636 同报错。至少第 3 次复现。

## P1：best commit 重部署 smoke 失败 → 回退到更旧的 deploy_result

- 2026-08-27 05:52:52（run.log:7880）：
  `converge_best_commit: redeploy of a5af7431f917 failed smoke (err=deploy_failed)
  — eval falls back to prior deploy_result`；
- smoke.log 坐实失败真因 = **507035 vector core exception / MTE invalid GM
  address**（case unique_1:1048576，device dump：fftsplus aivector error，
  vec 0x900000053，MTE not aligned + invalid GM）——与 KI-1（coder 在
  known_issues 里交棒的已知 kernel 崩溃，同签名）一致；
- 回退目标 prior deploy_result 是 precision 会话前的更旧产物——对一个
  已知会崩的产物做 eval，风险即 crash cascade 0 分（同族既往结局）。

## P2：precision 未收敛时 best commit 本身就可能是坏的

- unique 的 precision_debug 未收敛（05:49 diagnose 撞 2331s spawn 硬顶 +
  infra abort 重试又败），teardown 回滚到 best_commit；
- 该 commit 的 kernel 仍带 KI-1 记录的崩溃（coder 已按 step-93 腿 2 结构化
  交棒：症状/设备 dump/已排除方向齐全）——**best ≠ 健康，只是最好**；
- ab7283 P5 同构：bounds_check 坐实 tiling UB 公式少算、18/20 形状仍越界，
  precision 耗尽预算 → best commit 在 smoke/adapt 用例上仍崩。

## P3：收尾链（converge redeploy → adapt clean-rebuild smoke → eval）三次核验同一件事、任一崩即断链

- converge smoke、adapt 的 clean rebuild + smoke、eval 的 per-case 执行——
  对「kernel 会在运行期崩」这一事实核验了多次，每次崩都换不同失败形态
  （deploy_failed / stage failed / cascade 0 分）；
- 无「带着已知缺陷进入 eval 并诚实记 partial」的通路：精度 20/20 过但
  perf case 崩的 kernel，当前只能得 0 或断链，分数无法反映真实部分质量
  （既往 ab7283 的 multi_add 即整段 0 收场）。

## P4：best commit 是「烂中之最」——0/20 通过的 commit 被当作收敛产物（2026-08-27 补证）

- unique `artifacts/debug/unique/control.json`（收尾决策时刻的状态）：
  `best_passed_count = 0`、`best_failed_count = 20`、
  `best_commit = a5af7431f917…`、`status = "running"`；
- best 判据（precision_debug_substages.py:470）＝ **passed_count 严格更大的相对
  argmax**——precision 被 2331s spawn 硬顶 ×2 + infra abort 三连败后从未收敛，
  全程 20/20 失败，argmax(0,0,…)= 首个 commit；
- **相对最好 ≠ 好**：0/20 的 commit 没有任何绝对质量底线判拦，照常进入收尾链。

## P5：收尾决策不消费已测质量事实（信息盲，靠重跑重新发现）

- 收尾决策时刻 control.json 已携带「best 0/20 + KI-1 崩溃签名」；
- `converge_best_commit` 的决策路径不读 best_passed_count、不读 known_issues/
  KI——用「redeploy + smoke 重跑一次」把**已知质量**重新发现成一次崩溃事件
  （deploy_failed），再兜底 fallback；
- 同一事实（kernel 会崩）在收尾链三个位点（converge-smoke / adapt-smoke /
  eval per-case）被**三次重新发现**，各失败形态不同（deploy_failed /
  stage failed / 0 分）——「反复出现」的家族性来源。

## P6：precision 被 hard-cap 截断的产物状态不是一等状态

- 本批 unique：diagnose 撞 2331s spawn 硬顶；另一 run（task_batch_norm_
  update_stats_custom，e8200d）同签名 `exceeded 6698s hard cap`——上游触发器
  跨 run 复现；
- **2026-08-27 补证**：2331s 不是固定 spawn 预算，是 workflow 墙钳制——
  `dispatcher.py:488-502` 每次 spawn 的 eff_msg_timeout =
  `min(max(remaining_deadline,1.0), 14400)`；w4 于 05:10 spawn 时 10h 墙仅剩
  39min，被杀于最高产编辑流中间（详见 `turn-stall-pretrip-evidence/01-problems.md`
  P4）；
- 截断后 control.json `status="running"`——best 是**半程快照**，收尾链不
  消费该状态（不知道 best 来自未收敛会话）。

## 待调研问题（L3 调研态，未冻结）

1. best commit 重验失败时的候选语义：单次重试（竞态类可能过）/ 接受重建
   产物直接 eval（记录 smoke 红）/ partial 评测报告（已知崩 case 记 0 不
   cascade）三者如何按崩溃性质选择；
2. smoke 用例与 run_tests/eval 用例集的差异是否让「run_tests 过、smoke 崩」
   成为结构性窗口（unique_1:1048576 是否在 run_tests 集内、KI-1 崩溃的
   数据依赖性/竞态性未定）；
3. precision 硬顶（spawn 2331s cap）与 infra abort 叠加导致收尾质量不可控
   的边界（本次 05:49-05:52 三连击）。
