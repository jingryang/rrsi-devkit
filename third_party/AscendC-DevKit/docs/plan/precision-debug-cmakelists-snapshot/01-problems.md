# L1 问题记录 — 快照提交误杀 CMakeLists.txt,回滚后重建必死

> 日期:2026-10-12 冻结。本文件只记客观事实与证据,不含方案与排序。

## P1 触发事实:收尾两次构建 ~3 秒即死于同一 cmake 错误

- run:`output/20261012-024454-792f87/20261012-024454-7c05d5`(A3 机器,`mse_loss_cross_entropy_loss` 批次,precision_debug 129/129 已全绿)。
- 12:36:16 `converge_best_commit` 重部署最优提交 dfa6242 → deploy_failed;12:36:18 `cannbench_adapt` 的 clean rebuild → 同样 deploy_failed。
- 直接报错(`subprocess/build_ascendc.log` / retry2 / retry3 三份一致):

  ```
  CMake Error at csrc/ops/CMakeLists.txt:18 (add_subdirectory):
    The source directory
      .../examples/aclnn_launch_example/csrc/ops/mse_loss_cross_entropy_loss
    does not contain a CMakeLists.txt file.
  ```

- 参照:同 run 内成功构建耗时 34–65s(11:49 失败 65s、11:53 成功 34s);收尾两次 2–3s 即死 = cmake configure 期即失败,非编译错误。

## P2 根因链:排除表误杀 → 快照缺文件 → 回滚 git clean 物理删除

1. cann-bench 每算子目录需自己的 `CMakeLists.txt`(`csrc/ops/CMakeLists.txt:18` add_subdirectory 自注册);兄弟算子 add/sqrt 的该文件是 git 跟踪文件,本算子的这份由 codegen 生成、**未被任何提交跟踪**(`git log --all -- '*mse_loss_cross_entropy_loss/CMakeLists.txt'` 为空)。
2. 入口快照提交 9d2edd4("A5 precision_debug entry: snapshot codegen products")实际只含 12 个源文件,**不含 CMakeLists.txt**(ls-tree 实证)。
3. 排除机制:`git_safety.py::_allowed_operator_files` 的 `_DEBUG_EXCLUDES = ("*.log", "*.bak", "*.txt", ...)`——`_matches_globs` 同时匹配全路径与 **basename**,`fnmatch("CMakeLists.txt", "*.txt")` 为真 → 被排除。而 profile `resources/repository-profiles/cann-bench.yaml` 的 `precision_debug_commit.include` **显式声明了 `"CMakeLists.txt"`**(注释:「只允许生产代码目录和根 CMakeLists.txt」)——框架不可覆盖排除表压过了 profile 的显式意图。
4. 12:36:16 `repo_rollback op_dir restored to dfa624264cd1 (checkout+clean)`——`git clean` 物理删除未跟踪的 CMakeLists.txt(本机 ls 实证:文件已不存在)。
5. 其后所有构建(converge 重部署、cannbench_adapt clean rebuild、任何手工重建)必死于 P1 的 cmake 错误。

## P3 影响面:成绩未失真,丢的是「最终提交态可独立复建」的保证

- eval 回退使用的"旧包"= `artifacts/per-op/mse_loss_cross_entropy_loss/{opp,python}`,安装时间 **12:32:47**(`last_deploy.json` `source_identity='4b435489aa6a-dirty-6'`)——诊断 agent 修好 kernel 后重装的那一版,即 run_tests 129/129 所测的最终 kernel 代码;**eval 100% 测的就是修好的 kernel,成绩未失真**。
- 丢失的保证:`converge_mismatch` 标记所记录的——最优提交 dfa6242 的提交态从未被重新构建/部署/smoke 验证过(交付记录里的 `a8c0900a8937-dirty-2` 与物理安装内容不一致,属元数据滞后)。
- 结构性影响:任何"快照→回滚→重建"路径(收尾 converge、resume、teardown 后复跑)遇到"codegen 产物含构建清单"的仓都会同样必死——不只本 run。

## P4 机制代理反模式(§1.10)

- `*.txt` 排除的本意是「调试文本抓拍不进提交」(docstring: plain-text captures)。以扩展名代理「是否调试产物」的分类,与构建清单这一基础设施文件名冲突——机制特征代理必有一类被静默误判,本例即被误判类。
