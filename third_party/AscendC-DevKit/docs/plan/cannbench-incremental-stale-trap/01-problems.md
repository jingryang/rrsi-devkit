# L1 问题记录 — cann-bench 增量构建 mtime 陷阱（kernel 源变更不进 binary，smoke 幽灵失败循环）

- 立项时间：2026-08-28
- 实证批次：`20260827-132819-41aea1`（unique execution `20260827-132819-95e52f`）
- 状态：L1 冻结；L3 已拍板（见同目录 02-analysis.md）

## P1 — 增量构建的源拷贝 mtime 陷阱：kernel 源改了，binary 永不重编

### 现象（客观事实）

1. unique codegen 阶段 smoke 幽灵失败循环：EZ9999 `Parse dynamic kernel config fail`
   反复复现，retry 4→6 约 5 轮 coder 重派（01:13–01:49，每轮 ~10 min 会话 +
   skill 重载 token）。
2. coder 归属判定原文（01:49:58，`not_codegen` 交棒）：
   - 部署的 kernel binary 由 01:06 的 D23 源（含 3 参软 SyncAll，两次实证产出
     MIX/intercoreSync=1）编译，而非 01:27 交付的 D24 源（SyncAll-free 手工屏障）；
   - 增量路径**连 kernel 重编译都不触发**（kernel `.o` 新于 build 内陈旧源拷贝
     的 mtime）；
   - 解锁 = 干净重编（`build.sh` 会 `rm -rf build/`）或删
     `build/autogen/copy_kernel_src.timestamp` + `build/all_kernels/binary/dynamic/`
     后再增量；否则任何 codegen 改动都无法进入 binary。
3. 事后佐证"幽灵"判定：diagnose 接手 + converge 后框架 `clean_build` 全量重编
   → 精度 **20/20 passed**（0/20→18/20→20/20 两轮收敛）——源码从头是对的，
   失败全部来自构建产物与源码脱钩。
4. 触发条件（两算子对照实证）：陷阱只在「**增量构建建立后 kernel 源再变更**」
   时兑现——moe_re_routing 同走增量但 schema 重派只改 manifest 不动 kernel 源，
   未兑现；unique 在首次全量后又改 kernel 源（D23→D24），兑现。

### 机制事实（产权拆分）

| 层 | 归属 | 事实 |
|---|---|---|
| 陷阱本体（源拷贝 + timestamp 短路 + mtime 判定） | **cann-bench 仓**构建脚本/CMake | `autogen` 拷贝机制实证于 `examples/aclnn_launch_example/CMakeLists.txt:41+`；`copy_kernel_src.timestamp` 的生成逻辑在其源码中 grep 不可得（coder 从 build 目录实测发现）——外部仓内部结构 |
| 增量通路（`incremental_command_template`） | **devkit** `resources/repository-profiles/cann-bench.yaml` | 引入动机=省时（注释宣称 precision fix 循环 23 次 redeploy 各省 2-3min） |
| 增量字段覆盖面 | devkit profile 体系 | **仅 cann-bench.yaml 有**；omni-ops / ops-nn / ops-transformer 三个 profile 均无增量命令 |

### 成本实测（本批）

- 增量构建：28~35 s/次（4 个成功样本）；全量构建（`build.sh`）：68 s → **单次
  差距 ~35 s**，run 级（~10 次 deploy）约 6 分钟。
- profile 注释宣称的"省 2-3min"**已过时**（本批实测仅 35 s）。
- 陷阱一次兑现成本：~5 轮 codegen 重派 ≈ 50 min LLM 会话 + token。

### 暴露面（未兑现但同在风险下）

- diagnose 阶段改 kernel 源后的 redeploy 走**同一条** deploy 命令，同样暴露；
  本批未兑现是因 diagnose 自行执行了干净重编（agent 实施能力），非通路安全。

### 用户约束（拍板输入）

- cann-bench 是外部仓且用户**无修改权限**（origin-only 基仓），根因不可修。
- cann-bench 定位为评测仓，部署频度低，本身不需要增量编译提速。
