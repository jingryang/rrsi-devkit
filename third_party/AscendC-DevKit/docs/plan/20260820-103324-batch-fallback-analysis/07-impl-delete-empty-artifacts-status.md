# L4 实施方案：删 empty_artifacts 状态类别——结论从契约派生，机制信号只做诊断

> 对应问题：F5（`empty_artifacts` 在 runner 与 codegen 两处语义冲突）。
> 用户决策（2026-08-21）：方案 1（runner 白名单加特判）被否——是给陷阱加警示牌；
> **采纳方案 2：把陷阱填了**（删类别，判主权颠倒）。用户质询推动的关键修正：
> 初版方案 1 没发现 runner 分支 3 已有契约判定（行为增量微小且重复），且陷阱留给
> 其他 3 个消费方——同构于 F1/F2 犯过的错。

## 一、本质论证

`empty_artifacts` ⟺ `¬crashed ∧ ¬artifacts`（base_backend `_build_result`）——**完全可由
(crashed, artifacts) 推出的零信息语法糖**。它制造了"空产出是一个语义类别"的假象，但
"空产出意味着什么"没有全局答案：

| 消费方 | 业务问题 | 正确判据 |
|---|---|---|
| runner stage_status | stage 是否交付了声明的产物 | `output_contract.provides`（显式业务声明） |
| runner `_last_iter_ok`（:412） | 有无可信完整产出（deadline 抢救） | `status=="ok" ∧ artifacts 非空` |
| codegen 失败门（:2555） | 代码树是否落地 | **已是** `status=="ok" ∧ artifacts`（无需改） |
| dispatcher skill 模式（:1619） | skill 进程是否干净完成 | status=="ok"（skill 允许无产出） |

每个业务问题一比特答案，status 提前坍缩了本不该坍缩的二维事实。**修复 = 删类别**：
干净完成一律 `ok`，产出有无看 `artifacts` 字典（就在结果上，谁要谁查）——结构上强迫
每个判断去看契约/产物，不存在"忘了特判"。

## 二、消费点核实清单（grep 全仓穷举）

**src（7 处）**：
| 位置 | 现状 | 改动 |
|---|---|---|
| `base_backend.py:293` | `else: status="empty_artifacts"` | 改 `"ok"`（artifacts 已为 {}） |
| `backend.py:14` | status 枚举注释 | 更新（"ok" \| "partial" \| "fatal"） |
| `runner.py:570` | 白名单 `("ok","empty_artifacts")` | 收窄为 `("ok",)`；分支 3 细化（见下） |
| `runner.py:412` | `_last_iter_ok = status=="ok"` | 加 `∧ bool(artifacts)`（行为保持：空跑仍 False） |
| `codegen.py:2893` | `error_type=...status`（空跑时="empty_artifacts"） | 干净空跑 → `"incomplete_output"`（既有 selffix 类目）+ message 如实 |
| `requirement.py:421` | 同上模式 | 同上 |
| `dispatcher.py:1619` | `ok or empty_artifacts` | 收窄 `=="ok"`（行为等价：空跑仍 exit 0） |

**tests（14 文件 35 处）**：fixture/断言从 `"empty_artifacts"` 迁移到 `"ok"`+空
artifacts（test_stage_failure_status 为语义核心，重写期望）。

**ST helper（2 处）**：`_dual_backend.py:104`、`test_session_resume_e2e.py:48` 的
completed 元组去 literal。

**非 Python 消费**：resources/scripts/docs(stages) 无（已 grep 确认）。

## 三、runner stage_status 目标语义（契约优先）

```
契约满足（provides 全就位）              → ok（过程异常只进 metrics，不推翻业务结论）
契约未满足：
  - 有部分产出（任一 provides 已就位）   → partial（slow-but-salvageable）
  - 一点没有（零 provides 就位）         → failed（该产出却空跑）
provides 为空（continue 型 stage）       → ok（合法无产出）
```

实现：分支 3 从恒 `partial` 细化为 `partial if has_any(provides) else failed`
（`has_any` 用 `has_all` 同款 not-None 判据现场实现，不新增 State 方法——单点使用）。
分支 1/2（agent status / own_error）保留——它们供应失败**原因**（诊断）而非翻案
业务结论；P8（partial+契约满足→ok）不变。

## 四、不改的东西

- codegen 成功门 `:2555`（`ok ∧ artifacts`）——已是业务判据，零改动。
- codegen 熔断 `max_consecutive_failures=5` 与孤儿区分（daaf5ef8）——空跑路径
  error_type 换 `incomplete_output` 后计数行为不变。
- `partial`/`fatal` status——过程事实（crashed 派生），语义无歧义，保留。

## 五、验证（TDD）

新增/重写：
1. backend 工厂：干净无产物 → `status="ok", artifacts={}`。
2. runner：干净空跑 + provides 未满足 + 零就位 → **failed**；部分就位 → **partial**；
   provides 空 → ok。
3. codegen：干净空跑 → 失败分支 error_type=`incomplete_output` + 熔断 +1；
   孤儿分支（transcript 证据）不受影响。
4. requirement：干净空跑 → last_error.error_type=`incomplete_output`。
5. `_last_iter_ok`：空跑轮后仍 False（deadline 抢救语义保持）。

回归：14 个测试文件迁移 + 全量 UT `--quick`。

## 六、行为变化披露

- "空跑到迭代耗尽且 transition 未记 own_error"的 stage：events 从 `partial` 变
  `failed`（零产出）——日志从"含糊"变"诚实"；fail_strategy=halt 的正确触发
  `_stage_failed`。
- 历史上"空跑后重试成功"的 stage 不受影响（最终契约满足 → ok）。
- codegen 空跑的 last_error.error_type：`empty_artifacts` → `incomplete_output`
  （对齐 state.py 既有 taxonomy，selffix-class 可重试）。

## 七、原则符合性

- §1.10：判据 = output_contract（业务显式声明），机制信号降为诊断。
- §1.4：类别删干净，全消费点同批收口，不留别名/兼容层。
- §2.5：判定收敛 runner 单点契约优先通路；codegen 门已同判据。
- §1.14：净删一个枚举值 + 一个白名单特例，未加结构。
- §1.2 可扩展：新增 stage 声明 provides 即自动正确归位，不靠自带兜底。

## 八、实施结果（2026-08-21）

已按上表全量落地；全仓（src+tests）`empty_artifacts` 字面量清零。
UT 3654 pass / 0 fail（`--quick`，heavy_llm 按约定延后统一补）。

实施中发现的两个替身级修正（生产代码零改动）：

1. **cut/abort 抢救轮的真实形态**：cut 后 runner 在同 iteration 内重试、
   fatal+aborted 后走 P131c infra 回退重试——此前这些测试用 StubBackend
   耗尽后的默认 bare-ok（零产物）充当"抢救成功"，F5 后按新不变式合法地
   不点亮 `_last_iter_ok`。修法：抢救轮 fixture 带产物（真实成功形态）；
   cut 测试改为「ok 产物轮 + 5 连 cut 撞 MAX_CUT_STREAK」的强形态（信号
   只可能来自首轮，断言诊断性）；aborted 豁免的诊断性断言补进
   test_cut_allowance 的 `_guard` 纯逻辑用例（原缺 aborted 用例）。
2. **StubBackend 默认保持 bare-ok**（不给默认塞假产物）：dispatcher 无
   backend 配置时的降级路径复用它，塞产物会污染真实回退运行。测试要
   "有产出的成功"必须显式 canned artifacts。

一处超出原表的行为修正披露：branch 3 细化用现成的
`_unsatisfied_contract_fields`（missing 长度 < provides 长度 ⇒ partial），
判据与"为何再迭代"的 missing 单源一致，未新增 helper。

## 九、ST 验证决策（2026-08-21 用户拍板）

当前 opencode 配置指向**待测模型**，不适合做 ST 验证——非 heavy ST 的实际执行
暂停，与 heavy_llm 一并等**换测试模型后统一回归**。本次只做用例补齐与静态一致性
核对：

- 全 ST 目录 grep：`empty_artifacts` 零残留；唯二 literal（`_dual_backend.py`
  `_SMOKE_COMPLETED`、`test_session_resume_e2e.py` `_COMPLETED`）已收窄为
  `("ok", "partial")`——干净零产出落 "ok"，成员资格语义不变。
- ST 无任何对 stage 级 "partial"/"failed" 的期望断言、无 `_last_iter_ok` 依赖、
  无 codegen/requirement 失败分支 error_type 字面量断言（唯一相关断言
  `test_self_evolution_stages.py:300` 期望的 `incomplete_output` 与 F5 选用的
  taxonomy 类目天然一致）。
- `test_self_evolution_stages.py` 的 `_StubBackend`（status="ok"+artifacts={}）
  本就是 F5 后的干净零产物形态，无需改动。
- 真实链路守护（§3.9）由 dual-backend 系 ST 承担，统一回归时一并生效。
