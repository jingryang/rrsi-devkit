# precision_debug 收尾交付修复前代码（step-119）

> 问题定位：批 20260903-073532-5ddae2（apply_adam_w）中 debug 链 20/20 全过但 cann-bench eval
> 只 1/20 通过。根因不是精度误判、也不是 debug/eval 判据分裂（同 import compare_tensors 同源同函数）——
> **eval 评测的是被 converge 收尾 rollback 回修复前的旧 binary**（失败签名逐位一致）。直接根因：
> diagnose agent 越权写 control.json 的 `best_passed_count=20` 而未动 `best_commit`，框架「严格大于」
> 比较（20>20=False）跳过本应拍到修复 commit 的快照；converge 遂回退到修复前锚点并重编译交付。
> 契约栅栏曾在 951a92c5 时代存在，被 dbf4d65a（P3-A）与 6d9a5022（N1）两次重构删除且无机制报警。
> 另有框架侧独立缺陷：平局不快照（严格大于语义）、快照语义为「测后 HEAD」、部署记录无 source_identity。

## 方案一句话

删 A3 control.json 的 `best_*` 字段、agent 无字段可写；交付物按退出路径分道——**全过退出交付「框架最近
一次全过测量的 source_identity」（不读字段、无 argmax/tie-break）**，非全过退出才从测量史 argmax（平局保留
较早）；交付物带来源标识含脏指纹（B，纯 git 探测不靠模型）；converge 结束加交接断言（C1）。A5 专有机制
不动。加固 git_commit 必填 + A3 教学单通路（D）。不搬家、不改 teardown/resume、不做 converge 重验精度。

## 层级文档

| 层 | 文件 | 内容 |
|----|------|------|
| L1 | `01-problems.md` | 事实 F1-F13：签名逐位一致的实证、时间线、越权写 transcript 实证、契约缺口与栅栏沿革、框架放大器、converge 后果链 |
| L3 | `02-analysis.md` | 方案 A-E（A3 删字段双路径/来源戳/交接断言/加固/回归测试）+ A0 容错对照 + A0.1 弱模型鲁棒性论证 + 明确不做（含 A5 不动）+ 决策点 |
| L4 | `03-impl.md` | 实施配方（A-1~A-10 函数级）+ TDD 验证 |

## 状态

- [x] L1 事实记录（2026-09-04）
- [x] L3 方案分析（2026-09-04，**v8 修订，含 A5 边界澄清 + 双路径设计，已评审方向**）
- [x] L4 实施方案（2026-09-04）
- [x] B 实施（source_identity provenance，UT 绿）
- [x] A 实施（删 best_* 字段 + 双路径交付 + converge/teardown/report/sync 改 history 派生 + schema/init-checkpoint 清理）
- [x] C1 实施（converge 交接断言 `_converge_check_handoff`）
- [x] D 实施（D1 git_commit 必填教学+框架 WARN；D2 A3 教学单通路 + 清 _shared-protocol best_* 邀请）
- [x] E 测试迁移 + 新增 UT（12 迁移 + 新函数测试；212 passed @ 核心 4 文件）
- [x] F 全量 UT 验证（**3288 passed** @ orchestration/application/skills/capabilities/adapters + 720 @ domain/infra）
- [ ] 下批真实 run 端到端验收（eval 报告可见被测 binary source_identity；debug 全过 run eval 测同一 identity）
