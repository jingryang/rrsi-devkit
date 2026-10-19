# L4 实施方案 — deploy-precondition + Step 0 收紧（TDD）

> 对应 L3 冻结方案。改动顺序即实施顺序。

## 改动 1：`_build_measure_command` 前提段（precision_debug_substages.py）

- 新增 `_deploy_precondition(dbg_q, build_cmd) -> str` helper（或内联）：可用性判定（python3 -c，argv 传路径防引号嵌套）→ 不可用时 echo + build_cmd（`|| true` 容忍）→ 再判 → 仍不可用 FATAL exit 1。
- `dbg` 与 `build_cmd` 任一为空 → 返回空串（旧行为）。
- 插入点：`init_part` 之后、`run_part` 之前，每轮幂等。

## 改动 2：Step 0 断言收紧（3 处）

- `SKILL.md` Step 0 第二个 bullet（"工程内可修的"行）。
- `agents/ascendc-precision-diagnose.md` Step 0 对应行。
- `DiagnoseSubstage._phase_prompt` Step 0 段对应行。
- 统一断言：凡修复目标代码在算子工程内的缺陷一律就地修（含 host 侧 tiling/launch/注册脚手架）；上报仅限 golden 语义错 / devkit 框架自身 / 编译依赖缺失。

## 改动 3：docstring 修正

`precision_debug_run_tests/scripts/build-failed-case-queue.py` 两处（build_queue docstring + crash sentinel 注释）："route directly to comment_bisect (skipping diagnose/fix)" → post-P3 事实（哨兵条目路由进 diagnose，diagnose 读 crash dump；comment-bisect 是 diagnose 就地技巧非独立 phase）。

## 验证

1. **UT**（`tests/ut/orchestration/test_run_tests_deploy_precondition.py`，先红）：
   - 命令构造：有 workspace+build_cmd → 命令含前提段三要素（可用性判定/redeploy 容忍/FATAL）；无 build_cmd → 无前提段、run-cases 段仍在。
   - **shell 语义真实执行**（subprocess 跑 bash）：空目录 + fake redeploy（写可用 last_deploy.json 的脚本）→ 前提段 exit 0 且调用过 fake；fake 什么都不写 → FATAL exit 1 且 stderr 含 FATAL 文案；已有可用记录 → 不触发 redeploy。
2. **全量 UT**（`--quick`，PYTHONPATH=src）。
3. **事故现场离线实证**（真实数据端到端）：run_dir=`output/20260825-083544-c52f0b/20260825-083544-608989`——①`redeploy`（预期 smoke 失败 rc=1，容忍）②验证 last_deploy.json 落盘且 install_path/python_path 非空 ③`run-cases` 全量 ④验证 crash 哨兵/失败进 result.json 且 CLI exit 0 ⑤`build-failed-case-queue.py` 能建非空队列。全部通过 = 修复链在被修事故上闭环。
4. heavy_llm 真实批跑：§3.11 待用户决策。

## 不做清单（红线）

1. 不加 abort stderr 签名分类（构造性保证已消灭该签名；§2.9）。
2. 不给 codegen 加 last_deploy.json 写入（单一写入者 §2.5；P8 契约代价接受）。
3. 不动 K 守卫 / `_ABORT_EXHAUST_THRESHOLD` / 超时放大倍率。
4. 不修 P69 card 旁路（既有产权，声明）。
5. 不加 result.json 缺失的脚本级兜底（P9 有界残余，声明）。
6. `design_deviation` 等 step-88 机制不涉入（本工作范围外）。

## as-built（2026-08-25）

- **改动 1**：`_deploy_precondition(dbg, build_cmd)` 模块级 helper（`_design_paths` 后）+ `_build_measure_command` 于 init 段后插入（每轮幂等；`dbg`/`build_cmd` 任一空→空串旧行为）。可用性判定 python3 argv 传路径（防引号嵌套）；redeploy 容忍 rc；仍不可用 FATAL exit 1；`[deploy-precondition]` echo 可观测。
- **改动 2**：SKILL.md / manifest / `_phase_prompt` 三处 Step 0 收敛为同一断言：「凡修复目标代码在算子工程内的缺陷一律就地修——含 host 侧 tiling/launch/注册/脚手架缺陷，不因根因属上游生成而推诿」。
- **改动 3**：build-failed-case-queue.py 两处陈旧 comment_bisect 路由文案改为 post-P3 事实（哨兵条目进 diagnose，comment-bisect 是 diagnose 就地技巧）。路由未动。
- **验证**：
  - TDD `test_run_tests_deploy_precondition.py` **7 passed**（先红后绿；含 shell 语义真实执行 4 用例：缺记录触发 redeploy / 空路径记录触发（P2）/ 可用记录跳过 / redeploy 后仍不可用 FATAL；fake redeploy 刻意 `exit 1` 验证 rc 容忍（P3））。
  - targeted 179 passed；全量 `tests/ut --quick` **3618 passed / 0 failed**（3611+7，零回归）。
  - **事故现场离线实证**（run 20260825-083544-608989，worktree 停在 converge 回滚点 71e6c5b）：
    ① `redeploy` → smoke 确定性复现失败（空 stdout + 仅 padding warning），`last_deploy.json` 落盘且 install_path/python_path/run_package 全非空（无条件落盘+可用路径实证）；
    ② `run-cases` 全量 → **RC=0**，result.json 顶层 `failure_type=runtime_crash`（case_details/tested_cases 双空=进程 pre-output 死亡形态）；
    ③ `build-failed-case-queue.py` → 非空队列（1×runtime crash 哨兵）。
    原"两轮空转熔断 0 分"路径在真实事故数据上变为"diagnose 带崩溃队列接管"——修复链端到端闭环。
  - **heavy_llm 已跑（2026-08-25 晚，用户确认）4/4 通过**：①diagnose 就地修（真实 LLM 定位 CAST RoundMode 缺陷并修复）②reject-hint 多轮闭环 ③codegen 端到端 ④N1 全闭环 measure→diagnose→fix→remeasure（前提段真实激活）。首跑 ④ 失败——stub fixture 未随 §step-89 契约升级（stub_build 不落盘 last_deploy.json → precondition FATAL，rc=1）；修复=stub_build 镜像 DebugService.redeploy 契约（build 后无条件落盘可用记录），单跑复验 171s 通过。fixture 契约升级属测试忠实性修复非绕过（§3.12）。

### 追加（2026-08-25 晚，用户追问"不要遗漏小问题"触发 N1 余留清扫）

- **P10（追加发现并修复）**：N1 删除 run_tests agent 后，**14 处注释仍把已删 agent 描述为现行执行者**（超时放大 / 大 shape 判定 / history 折叠 / per-case 精修的 actor 全部过时）——runtime_config×2、runner×3、queue 脚本×6、evaluation×1、substages×2。这正是 N1 缺口的成因类别（"谁负责什么"的过时认知）。全部改为现行 actor（队列脚本 / 框架 transition / RunMeasure AMPLIFIED 循环 / diagnose N2）。
- **P11（追加发现并删除）**：`update-checkpoint.py`（run_tests scripts 目录）零调用方（src/.claude/tests 均无引用）——被删 agent 的孤儿脚本，§2.5 死代码，删除。
- 验证：全量 `tests/ut --quick` **3618 passed / 0 failed**（注释与删除无行为变化）。
