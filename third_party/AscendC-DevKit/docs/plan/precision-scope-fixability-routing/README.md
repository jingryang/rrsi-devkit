# precision_debug 修复可达性路由（能修就修）+ 上游根因兜底 WARN

> L1 指令记录 + L3 方案 + L4 实施（单一决策，合一片）。
> 用户指令（2026-08-22）两条：
> ① 最终目的是产出高质量算子——**只要错误可以修（修了 eval 认账），precision_debug 就要修**，不因"上游"标签把可修缺陷挡在修复循环外；
> ② 若识别出是**上游根因**但可兜底修复，**必须先在日志输出 WARN**（上游缺陷信号留档），再继续往下修。

## L1：原来哪里坏了？

scope_guard 判定表把「根因在算子工程外（codegen 脚手架/生成注册文件缺陷）」判 upstream → halt → 本 run 0 分。但查证：

- codegen 生成的脚手架（plugin 注册、CMakeLists、op_host 适配）**全部落在 operator_dir**，fix agent（cwd=operator_dir）编辑范围本就覆盖全工程（fix.md 连 op_plugin 副作用检测都有）；
- 修这里**随 deploy 交付 eval，eval 认账**——aggregate（plugin schema 漏 token）、multi_add（manifest/plugin mismatch）等历史案例本可在 run 内修掉，被 halt 成 0 分。

即：**"上游标签挡住了可修缺陷"**，与"产出高质量算子"的目的相悖。同时须守住反向边界：改 golden/用例/阈值让 kernel 过 = 循环验证，eval 分数不再代表算子质量——那条路不是"修"。

## L3：判据从「谁的锅（ownership）」改为「修哪里 eval 认账（fixability + delivery）」

| 缺陷位置 | scope_verdict | 行为 |
|---|---|---|
| **算子工程内一切产物**（kernel/host/tiling/plugin/注册/CMakeLists 脚手架，无论 codegen 生成还是人写） | **pass** | 进 diagnose/fix 就地修；若根因源自上游生成（origin_stage=codegen 等）→ **框架 WARN 留档后继续修**（指令②） |
| **eval 权威侧文件**（golden.py、用例定义、需求规格） | **upstream** | halt。硬理由：不在 operator_dir 且 cann-bench 权威侧不认本地改动（下轮 clone 即失）；改判卷=循环验证。**防循环验证红线**：禁止改 golden/用例/阈值使 kernel 过 |
| **框架/harness 自身**（devkit src 抛错且载荷合法） | **upstream**（origin_stage=framework） | halt + 归属框架侧标注，不甩 codegen/test_design（run 内修不了，仓级修复走人；fail-fast 不烧预算） |
| **环境/设备** | 环境通道（既有） | env_blocker 语义不变 |

**B1/B3 复议结论**（用户挑战"只改指向的修改无意义"后的重判）：
- B1（ownership 判据）：**无独立意义**——被本表第 3 行吸收，且 halt+框架标注比 B1 原案（pass 进循环空转）更优。
- B3（failure_type 结构性分类）：**转为必要配套**——新表把脚手架/注册缺陷放进循环后，failure_type 是 diagnose 选修法的路由依据；分类错（契约错标 compilation → 读不存在的编译日志）则新放进来的缺陷修不动。实施换范式：分类结果必须索引到 diagnose 的正确修法。

## L4：实施清单

| 层 | 文件 | 改动 |
|---|---|---|
| 框架 | `precision_debug_substages.py` | `_extract_debug_checkpoint` + `scope_origin_stage`；`ScopeGuardSubstage.transition` WARN（pass ∧ origin∈上游集）+ 物化；`_CONTROL_TEMPLATE` + required keys；`_FAILURE_TYPE_PRIORITY` 加 `schema_contract`（runtime>compilation>schema_contract>precision）；`_phase_prompt` 判定规则四类 |
| skill | `ascendc-precision-scope-guard/SKILL.md` | 判定表四类范式重写 + `origin_stage` 输出（第 5 个 scope_* 字段）+ 防循环验证红线 |
| schema | `scope_verdict.json` | description/example 加 origin_stage |
| agent manifest | `ascendc-precision-scope-guard.md` | 第 3 步四类重写（删平铺 compile/schema→upstream） |
| 分类 | run_tests `SKILL.md` item70 + `build-failed-case-queue.py` | failure_type 四分法：编译期/运行期/**契约注册类 schema_contract**/精度；脚本初始分类加契约注册字面量 |
| diagnose | `SKILL.md` + manifest | 四分路由：schema_contract → 查 plugin 注册/manifest/契约声明，不走编译日志路径 |
| 测试 | `test_precision_debug_stage.py` | origin WARN 三态（pass+上游 origin→warn+persist / pass+kernel→无 / upstream→halt 不变）+ aggregate 优先级 |

## 验证

- [x] UT：TestScopeGuardOriginWarn 3 态（pass+codegen→WARN+persist / pass+kernel→无 WARN / upstream→halt 不变）+ TestFailureTypeAggregateSchemaContract 3（schema_contract 优先级）；254 全绿
- [x] 相关回归：test_precision_debug_stage + test_stages + test_self_evolution_stages + test_artifact_retry_common 509 全绿
- [ ] 全量默认 pytest
- [ ] 批跑实证（下次批跑：脚手架类缺陷应进循环被修而非 halt；日志出现上游根因兜底 WARN）
