# L3 方案分析 — omni-ops 部署链对齐 per-op 契约（已拍板，冻结）

- 拍板时间：2026-09-11（`set_env.bash` 一项为用户当场复议后改判，见决策 5）
- 输入：`01-problems.md`（L1 事实 P1-P5）
- 实施：`03-impl.md`（L4）

## 决策清单与结论摘要

| # | 决策点 | 采纳 | 否决 |
|---|---|---|---|
| 1 | `.run` 的安装落点 | 装进 per-op 目录 | 全局 CANN 根 / 任意处 + `source` |
| 2 | vendor 落位方式 | `--install-path` 直装 + `mv` | 中转根 + `cp -r` / `symlink` |
| 3 | whl 安装方式 | per-op `pip --target` | 全局 `pip install` |
| 4 | dispatcher 路径锚定范围 | 全部 8 个路径字段 | 只锚 6 个 / 各消费点各自解析 |
| 5 | `install.sh` 生成的 `set_env.bash` | 保留不动（记未处理 minor） | 删除 / 覆写为正确路径 |
| 6 | `mv` 失败的语义 | 让它显式失败 | `\|\| true` 静默兜底 |

---

## 决策 1 — `.run` 装到哪

**背景约束**：框架 smoke/harness **无条件**把 `ASCEND_CUSTOM_OPP_PATH` 指向
`<per_op_opp_dir>/vendors/custom_ops`（赋值覆盖，非追加；值形态单源
`infra/env_contract.py::expected_ascend_custom_opp`）。算子注册信息必须在这个位置被找到。

### 选项 a — 装进 per-op 目录（✅ 采纳）

- 优点：与框架读取路径**构造性一致**（同一个 `{per_op_opp_dir}` 变量派生，不存在"装 A 读 B"的缝）；
  多算子天然隔离；per-op 目录是框架可清空/重建的私有地盘，新鲜度可保证。
- 缺点：脱离框架手动跑时，需按 yaml 文件头自己 export 环境变量（框架不依赖全局安装）。

### 选项 b — 装到全局 CANN 根（`$ASCEND_OPP_PATH`）（否决）

走 `ASCEND_OPP_PATH` 那条线（框架不覆盖该变量），装进 `<ASCEND_OPP_PATH>/vendors/`。

- 否决理由：
  1. **多算子互相覆盖**——`$ASCEND_OPP_PATH` 全局唯一，A 装完 B 覆盖；
  2. **新鲜度不可保证**——混在系统 CANN 目录里，框架不敢清空重装；
  3. 需 root 权限写系统目录；
  4. 与 §1.7（资源路径不硬编码、仓自闭环）精神相悖。
- 附：L1 记录的原始故障正是这一族——当时的现场补丁装到了 `/home/z00943229/cann/0831base`，
  **既不在任何 CANN 搜索路径上、也没 `source` 安装包生成的 `set_env.bash`**，故框架与 CANN 都读不到。

### 选项 c — 装任意位置 + `source set_env.bash`（否决）

- 否决理由：**在框架内不成立**——框架对 `ASCEND_CUSTOM_OPP_PATH` 是赋值覆盖，
  会把 `source` 进来的值冲掉。即"装哪都行、只要指定了路径"这条通用规则，在框架的
  smoke/harness 链路上被覆盖写死，只剩 per-op 一个有效位置。

## 决策 2 — vendor 目录怎么落位

**背景约束**：`.run` 装出的目录名 = 仓的 `VENDOR_NAME`（L1 P5：training 与 inference
**不同名**），框架只认 `custom_ops`。

### 选项 a — `--install-path={per_op_opp_dir}` 直装 + `mv` 改名（✅ 采纳）

- 依据：CANN 打包模板 `install.sh` 对 `--install-path` 只校验「绝对路径 + 可写」
  （L1 已核源码），**不要求是 CANN 根**。故可一步装进 per-op，再用 `mv` 落到框架认的名字。
- 优点：一条命令落位，无中转根、无机器专属路径；`mv` 为同文件系统内 rename，
  毫秒级、不增加磁盘占用。
- 缺点：`mv` 非幂等（源不存在即失败）——见决策 6。

### 选项 b — 装到某个中转根再 `cp -r`（否决）

原现场补丁的形态（`--install-path=/home/z00943229/cann/0831base` + `cp -r`）。

- 否决理由：引入机器专属中转路径（换机即断）；`cp -r` 完整拷贝一份 3MB 级 `.so`，
  而源目录并不需要保留。

### 选项 c — `symlink` 代替 `mv`/`cp`（否决）

- 否决理由：**实测结论**（来源：源仓 `omni-ops.yaml` 注释引用的 run `20260831-104218`
  diagnose 受控实验，同二进制单变量翻转）——symlink 形态下 dlsym 守卫通过，但
  nnopbase 拒绝加载注册信息，报 `161001 "SoC not configured / binary_info_config not loaded"`；
  必须是**真实目录**才全链路成功。
- 注：该结论为**源仓现场实验转述**，本次未在目标机复现。

## 决策 3 — whl 怎么装

### 选项 a — per-op `pip install --target {per_op_python_dir}`（✅ 采纳）

- 优点：与框架的消费路径一致（smoke 设 `PYTHONPATH=<per_op_python_dir>`；harness
  `sys.path.insert(0, per_op_python_dir)`）；`install_python` stage 装前会清空该目录，
  保证 redeploy 后 agent 改的 wrapper 一定生效（`deploy.py` 的 P99 纪律）；
  多算子不互相覆盖。
- 缺点：与全局 `site-packages` 相比，手动跑时需自己 export `PYTHONPATH`。

### 选项 b — 全局 `pip install`（否决）

即原 `build_and_install.sh` 的行为（无路径参数 → 落当前 conda 的 site-packages）。

- 否决理由：
  1. **不隔离**——包名固定（`setup.py` 的 `name=`），多算子共用一份，后装覆盖先装；
  2. **无新鲜度保证**——`--force-reinstall` 不覆盖所有残留文件（框架 P99 注释的实证），
     且共享环境无法像 per-op 目录那样"清空再装"；
  3. 污染框架自身所处的运行环境。
- **诚实边界**：全局装**并非跑不起来**——site-packages 在 `sys.path` 上，smoke 能 import
  （本次实测过：把包复制到独立目录配 `PYTHONPATH` 也能 import 成功）。否决理由是隔离/新鲜度/
  可追踪，不是"读不到"。§1.7 亦指向同一取舍。

## 决策 4 — dispatcher 路径锚定范围

**背景**：CLI 路径字段写入 `State` → 序列化进 `state_snapshot.json` → 下游独立进程
（run-cases / redeploy / harness 子进程）各自 cwd 不同。

### 选项 a — 全部 8 个路径字段统一走 `_cli_path`（✅ 采纳）

`target_repo` / `requirement_path` / `design_doc_path` / `golden_path` / `cases_path` /
`detailed_design_path` / `op_dir` / `repo_root`。

- 优点：单点抽象（§1.15）——"CLI 路径字段在入口锚定一次"成为可判定的规则，
  新增字段有明确的归位处；不留例外。
- 缺点：`op_dir` 本已由 CLI 层 `op_dir_resolver` 要求绝对路径（约定保证），
  再 resolve 一次属冗余——但冗余无害，换来规则一致性。

### 选项 b — 只锚 6 个（`op_dir`/`repo_root` 不锚）（否决）

即 review 初版实现的形态。

- 否决理由：同性质字段留 2 个例外 = 散点（§1.15「漏写一处即出错」）；
  `op_dir`/`repo_root` 同样进 snapshot、同样被下游按 cwd 解析。约定保证（CLI 层已绝对化）
  不等于代码保证——一旦该校验放宽或出现新调用方（如 batch_runner），故障重现且更难定位。

### 选项 c — 各消费点各自 resolve（否决）

- 否决理由：消费点分散（多个 CLI 子进程 + harness），逐点补正是多条通路（§2.5），
  且每新增一个消费点就多一个漏点。

## 决策 5 — `install.sh` 生成的 `set_env.bash` 怎么处置

**背景**：`install.sh` 装完会在 vendor 目录生成 `bin/set_env.bash`，内容写死**安装当时**的
路径（2 个变量）。`mv` 改名后该路径失效。

**事实**：框架**不读**该文件（全仓 grep 无消费点，实测确认）；框架自行注入 4 个变量
（`PYTHONPATH` / `ASCEND_CUSTOM_OPP_PATH` / `ASCEND_NPU_ID` / `LD_LIBRARY_PATH`）。

### 选项 a — 保留不动（✅ 最终采纳）

- 理由：**框架不受影响**，问题仅限"会误导手动跑的人"。已在 L4 记为**未处理 minor**。
- 代价：手动跑的人若 `source` 它，会拿到失效路径，且它只覆盖 2 个变量
  （缺 `PYTHONPATH` / `ASCEND_NPU_ID`）。

### 选项 b — 在 `install_opp` 末尾 `rm -f` 删除（曾实施，后改判）

- 曾实施的理由：消除对后来人的误导；`-f` 保证幂等；框架不读它，删除无副作用。
- **改判理由（用户拍板）**：不引入该改动——删除动作本身未解决问题（手动跑仍缺环境变量），
  只是抹掉线索；保持改动面最小，把"文件内容过期"作为已知 minor 记录在案即可。

### 选项 c — 覆写为正确路径（否决）

- 否决理由：把**框架的路径知识**写进 profile（profile 只该描述"该仓怎么编"），
  且两变体各写一遍；§2.5 意义上属另立通路（该文件与框架注入的 4 变量职责重叠）。

## 决策 6 — `mv` 失败的语义

### 选项 a — 让它显式失败（✅ 采纳）

- 理由：若 `install.sh` 未产出预期的 vendor 目录，`mv` 报 `cannot stat` 并以非零退出，
  stage 立即失败。符合 §1.2「不静默吞错」——错误在现场暴露，而非拖到 smoke 阶段。

### 选项 b — `mv ... 2>/dev/null || true`（否决）

- 否决理由：吞掉真实错误。若 `install.sh` 真的没产出目录，后续 smoke 会在更远、
  更贵的位置失败，且丢失第一现场信号。
- 附：常规重跑走的是"`install.sh` 重新装出 vendor 目录 → `mv` 有源可动"路径（实测三场景），
  故非幂等的实际触发条件较窄。

---

## 拍板结论（冻结）

1. **落点**：`.run` 与 whl 一律装进框架的 per-op 目录——位置与目录名均由框架的
   `{per_op_opp_dir}` / `{per_op_python_dir}` 变量派生，profile 不出现机器专属路径。
2. **边界原则**：profile 只描述"该仓怎么编/装"（build.sh、vendor 名、变体划分），
   **落点由框架的 role 契约统一决定**。判据：换一台机器、换一个算子，profile 无需改动。
3. **路径锚定**：CLI 路径字段在 `dispatch()` 入口单点锚定为绝对路径，全部字段无例外；
   下游一律按"绝对路径 + cwd 无关"消费。
4. **`set_env.bash`**：保留不动，作为已知 minor 记录；不为其增加 profile 命令。
5. 已知遗留（不修，L4 记录）：`mv` 非幂等；两变体命令体逐字重复（profile 无 variant
   继承机制，属既有结构限制）。

## 对后续同类工作的适用性

本组决策**不限于 omni-ops**——凡声明了 deploy role 的 profile（cann-bench / ops-nn /
ops-transformer）都受同一框架契约约束：装到 per-op、vendor 落到 `custom_ops`、
真实目录非 symlink。差别只在各仓自己的 `VENDOR_NAME`、build 命令与 dist 产物位置。
