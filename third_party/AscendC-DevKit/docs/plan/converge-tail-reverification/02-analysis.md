# L3 方案分析 — converge 收尾链：质量事实不流转，收尾用崩溃重新发现已知

> 状态：**部分冻结（2026-08-27 用户拍板：D1 冻结、D4 暂缓；D2/D3 详述后待确认）**。
> 初版 O1-O4 是跳过本质的分支修补，保留于文末作演进记录。

## 0. 本质链（逐层问为什么，2026-08-27 与用户对齐后补）

1. **为什么 converge smoke 崩？** kernel 在该用例上崩——收尾决策时刻这已是
   **已知事实**（KI-1 交棒了完整签名；control.json 记录 best 0/20）。
2. **为什么系统表现得像「意外发现」？** 收尾决策**不消费任何已测得的质量
   事实**——不读 best_passed_count、不读 KI——靠「redeploy + smoke 重跑」把
   已知质量**重新发现成一次崩溃事件**，再用 deploy_failed 兜底。信息躺在
   control.json 里，决策是信息盲的。
3. **为什么 best 是 0/20 的 commit？** best 判据是相对 argmax（passed_count
   严格更大）；precision 被 hard-cap/infra 截断后从未收敛（全程 20/20 失败），
   argmax(0,0,…)= 首个 commit。**「烂中之最」与「好」没有被区分**——0/20
   照常被当作收敛产物送进收尾链。
4. **为什么收尾链要重验它？** 因为质量事实不流转，每层（converge-smoke /
   adapt-smoke / eval）各自重新测量、各有各的失败语言——**同一个事实被三
   个位点三次重新发现**，这就是「反复出现」的家族性来源。
5. **上游触发器跨 run 复现**：hard-cap 截断 precision（2331s=workflow 墙钳制
   `dispatcher min(remaining,14400)`、task_batch_norm 6698s 同签名）→ 半程
   best（status=running 快照）→ 收尾链撞已知缺陷。

**一句话本质：流水线没有「已测质量」这个一等状态随产物流转，收尾链用崩溃
重新发现本已携带的事实。**（与 step-93 host/kernel 边界同构：507035 出现在
converge smoke 里是**质量信号被误用作部署门**——smoke 的职责本应只是
「装得上、调得动」的部署完整性。）

## D1 质量事实随流转（✅ 冻结，用户拍板 2026-08-27）

**converge 决策直接消费 control.json 已测事实，不再用 redeploy+smoke 重跑来
「发现」质量**：

- converge_best_commit 决策时读 control.json：`best_passed_count` /
  `best_failed_count` / `best_commit` / `status` / known_issues（KI 签名）；
- **best 已知坏**（判定见 D2）→ 不再部署 known-bad 的 best，直接**选 fallback
  候选（上一可用 deploy_result）**：注意 **D1 改变的是部署哪个候选，不是取消
  部署验证**——fallback 候选仍要走 redeploy+smoke 验证自己的部署完整性
  （precision 期间的 redeploy 可能已覆盖共享 OPP 目录，必须重装；若 fallback
  候选自身的 smoke 崩，那是真新信息，现行 fallback 链语义正确）；
  fallback 候选不存在（首次部署即坏）→ 诚实记录「本轮无可交付产物 + 证据」；
- best 健康/部分健康 → 现行重部署路径保持（此时 smoke 崩才是**真意外**，
  现有 fallback 语义正确）；
- control.json 不存在/不可读 → 无质量事实可用 → 现行路径原样（fail-open，
  不劣化）；
- `status` 字段作为**事实**随记录携带（`running`=截断半程快照），不建
  截断语义机制（D4 暂缓，见下）。

## D2 best 判据补绝对底线（详述，待确认）

**现状**：best = 相对 argmax（passed_count 严格更大的 commit；初值=precision
入口 commit）。全部失败时 argmax(0,0,…)=入口 commit——「烂中之最」与「好」
无区分，照常进收尾链当交付物。

**问题不在 argmax 本身**（相对比较对「挑更好的」是对的），在**没有任何绝对
质量态**参与下游决策。D2 = 给 best 补一个**绝对质量分级**，由框架从
control.json 计数**客观派生**（非模型判定、非人工阈值委员会）：

| 质量态 | 判据（结构信号） | 收尾语义 |
|---|---|---|
| `good` | `total > 0 且 passed == total`（全过） | 现行：converge best → eval |
| `partial` | `0 < passed < total`（有正证据但不全） | converge best → eval **带已知失败清单**（失败 case 记 0，不 cascade、不断链） |
| `bad` | `total > 0 且 passed == 0`（零正证据——没有任何一个 case 通过） | **不把 best 当交付物**：走 D1 的 fallback + 结构化记录 |
| `unmeasured` | `total == 0`（无任何 case 测量记录） | **无质量信息，不启用 D1/D2 决策**，走现行路径（反面质疑补：否则 0==0 会被判成 good——未测量 ≠ 全过） |

- 刻度刻在**证据有无**上（passed==0 ⇔ 没有任何正证据证明这个 kernel 干过活），
  不刻在比例上（50%/80% 是魔法数，1/20 与 0/20 的差别是「有正证据」的质的
 差别）；
- 派生是纯函数（control.json 计数 → 四态），可加载期/决策期校验；
- 与 D1 的关系：D1 说「决策要读事实」，D2 说「读了之后 bad 态怎么处置」——
  D1 的「best 已知坏」判定即 D2 的 `bad`。

## D3 smoke 职责收窄回部署完整性（详述，待确认）

**现状**：redeploy smoke 跑若干用例，kernel 在用例上崩（设备侧错误如 507035
MTE invalid GM）→ smoke FAILED → `deploy_failed` → 收尾断链 → fallback。
即：**「这个 kernel 算错/会崩」这个质量事实，被当作「这个部署不能用」的部署
失败使用**。

**smoke 的本职（部署完整性）**：构建产物装得上、算子符号能解析、aclnn 入口
能 launch——回答「这份产物**可部署、可调用**吗」。它不回答「调用了之后结果
对不对/崩不崩」——那是质量，产权在 precision/run_tests/eval。

**D3 = smoke 失败按「死亡位置」二分**：

| 死亡位置 | 语义 | 处置 |
|---|---|---|
| host/部署侧：库加载失败、符号缺失、launch API 报错、安装损坏（EZ/561xxx 家族等） | 部署完整性失败 | **保留现行 deploy_failed 门**（部署真不行，fallback 正确） |
| launch 成功、kernel 执行期设备侧死亡（507035 等设备错误码、含执行期挂死超时） | **质量信号**，非部署失败 | 部署放行（产物确实装得上调得动）；崩溃签名随产物流给 eval 作**预期失败** |

- **范围诚实性（反面质疑补）**：launch 期的模糊地带（如 tiling OOM 在 launch
  时炸——按表落 deploy_failed，实为质量）D3 **不改善也不劣化**——判据复用
  step-93 已落地的 `_classify_smoke_phase` 结构分类器（已验证的 host/kernel
  归属边界），D3 只对清晰的「launch 后设备死亡族」改善，其余保持现状，不宣称
  完备；
- **预期失败 case 的执行语义**：eval 对预期失败 case **记录 0 分而不实际执行**
  ——重跑已知会崩的 case 既浪费预算又可能把设备打成挂死态，无收益；
- 用本批实例走一遍：05:52 converge 重部署 a5a7431，smoke case unique_1:1048576
  launch 成功、kernel 死于 507035 → D3 下：部署放行 + 「unique_1:1048576 预期崩
  （KI-1 同签名）」流向 eval → 其余 case 正常计分、断链不发生。对照现状：
  deploy_failed → 断链 → 回退更旧产物 → eval 在陈旧产物上跑；
- 与 D1/D2 组合后分工：D1 让决策知道 best 是 bad → 直接 fallback（根本不部署
  best）；D3 兜住**剩余场景**（best 是 partial/good、或 adapt 链路的
  clean-rebuild smoke、eval per-case 执行）中「崩=质量」的一致语义——收尾链
  三个位点从此用同一语言。

## D4 截断态一等化（⏸ 暂缓，用户拍板 2026-08-27：预算不好评估）

- 暂缓项：`status=running` 的截断语义机制（半程快照标注+收尾链消费）、
  spawn 前预算检查（剩余预算<最低有用窗口不 spawn）；
- 不丢的事实：D1 的结构化记录已携带 `status` 字段（事实读取，非机制）；
- 若 D1+D2+D3 落地后仍有「截断 best 被误当收敛产物」的复发，再以实证重开。

## 与初版 O1-O4 的关系（演进记录）

初版（2026-08-27 早）未做本质分析即给分支方案：O1 重验败重试一次、O2 质量
账本、O3 eval partial、O4 KI 打通。用户质询「没分析到本质直接给方案」后补
本质链；O2 碰到 D1/D2 的边、O3 被 D3 的预期失败取代、O1/O4 是给「不该存在的
决策分支」打补丁。D1-D4 由本质导出，取代 O1-O4。

## 原则对照

§1.2（四尺子）、§1.10（质量态/死亡位置=业务语义，非机制代理）、§1.12（判据
全结构信号：计数/错误码家族，无算子名）、§1.13（golden/run_tests 测得的质量
是权威事实，下游忠实消费）、§1.15（质量分级单点派生）。
