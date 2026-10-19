# L1 问题记录 — codegen agent 会话内无受控构建正门：自研 build/install/smoke 越权 + 轨迹浪费

- 层级：**L1 / 问题记录**。只陈述「哪里坏了、凭什么这么说」（证据/现象/代码事实）。
  **不提方案、不排顺序、不写决策**。方案分析待拍板后落 `02-analysis.md`（L3）。
- 发现契机：复盘批 `20260829-142941-49134b` run
  `20260829-142941-6f61da`（算子 mse_loss_cross_entropy_loss_custom）的 run.log + coder
  transcript（2026-09-05 分析）。
- 状态：L1 冻结；L3 已拍板方案 2（2026-09-05，见 `02-analysis.md`）。

### 环境清除证据（2026-09-05 实查，附 P1）

越权 agent 造成的环境污染，实查当前真实状态：

| 污染源（越权指向） | 当前状态（2026-09-05 实查） | 处理 |
|---|---|---|
| 系统 vendors `.../opp/vendors/custom_ops` 被越权装包 | 已空（只剩空骨架，08-30 起） | 无需处理 |
| 机器全局剥路径 sitecustomize（user site-packages） | 不存在；当前 python3（3.11.12）`import sitecustomize` → ModuleNotFoundError | 无需处理 |
| `/root/opencode_smoke` 越权 agent 自建（exp/ext1-9/smoke*.py） | 仍在，08-30 04:33 后无活动；无活跃进程引用；DevKit 仓零引用；非代码仓产物 | **已删除**（2026-09-05） |
| 各批算子仓根 `sitecustomize.py`（gelu/moe 等） | **不影响后续生成与分析（2026-09-05 实证）**——框架 smoke/run 子进程 `PYTHONPATH`=per_op_python_dir（`deploy.py:886`），不含外仓仓根 → 不被自动 import、不执行；对抗问题已被框架 step-108 `env_contract.py` 覆盖。决策权归各外仓，无需本仓处理 | 不处理（记录实证） |
| `ASCEND_CUSTOM_OPP_PATH` | 当前空（未污染） | 无需处理 |

> 本主题是**跨批共性架构缺陷**（非本批一次性修复）：multi-addrmsnorm 974-turn
> （batch-20260801）、本批 mse 805-turn 同形——codegen 会话内无受控构建正门，agent
> 只能自研 build 链。问题记录的产权在证据层，方案取舍不在此处。

---

## P1 — codegen 会话内没有「框架受控的构建入口」，agent 自研 build/install/smoke 越权

### 现象（行为事实，run 20260829-142941-6f61da 实证）

1. codegen iteration 1（01:20→04:35，约 3h15m，单会话 805 turn）期间，run.log **没有任何
   框架 deploy 事件**（`deploy [` 前缀事件在 05:20 之前为 0）。
2. 同一时段 coder-01 transcript 里 agent 用**裸 Bash 自研整条构建链**：
   - `bash build.sh --soc=ascend910b` × **16**
   - `rm -rf build` + 手动 `cmake -S . -B build ... && cmake --build build` × 1+3
   - **手动跑 `.run` 安装**（`install.sh` / `--install-path`）到系统 vendors × **16**
   - **手动 smoke**（`smoke.py` 8 用例）× 4
   - **裸 `ccec` 单文件编译测试** × 20（探 API 签名）
   - 把 run package 装进 `/usr/local/Ascend/.../opp/vendors/custom_ops`、`/root/opencode_smoke`
     （后者是越权 agent 自建目录，2026-08-30 04:33 属主 root）
3. iteration 1 结束时以 schema/契约不符（scalar_access_contract retry）结束——**框架静态门
   没过，根本没到框架 deploy**。
4. coder transcript 里 agent 自报 "Full build `bash build.sh --soc=ascend910b` SUCCEEDED"
   ——但同 turn 注释自证 "(but binary target failure was swallowed)"：agent **误判自己编过了**，
   kernel binary 其实没出来。

### 证据链（代码事实，现状）

1. **Deployer 设计意图是「agent 会话内可调受控构建」**（`stages/deploy.py:24-25`）：
   "为 agent 会话内调用的原子能力（codegen 在 session 内 build 自修，precision_debug 经 CLI
   ``redeploy`` 复用 ``Deployer``）"。`deploy.py:170-172` "Single source for the codegen
   agent (in-session build) + CLI ``redeploy``"。
2. **但 agent 会话内实际只有裸 Bash**，没有「受控构建工具/入口」被框架注入；fresh prompt
   （`codegen.py:2322-2323`「## 目标仓约定 编译命令: bash build.sh --soc=ascend910b」）只把
   编译命令当"目标仓约定"列出，未提供受控封装。
3. **"不自己构建"的禁令只在 retry 反馈段**（`codegen.py:2494-2596` 全部
   `**不要自己运行 build/redeploy**`），**fresh prompt 无此句** → 首轮 agent 无边界。
4. **skill 授权会话内自检编译**（`ascendc-op-dev-coding/SKILL.md:181`「会话内构建优先增量
   `cmake --build build`… 最终构建正确性由框架 deploy/smoke 门验证，会话内构建只为自检定位
   错误」）——把「自检编译」扩张成"自己 build/装包/smoke 到通过"的授权空隙，agent 实际越过。
5. **框架的正门 deploy 只在 agent 会话结束、transition 收尾跑一次完整链**（`codegen.py:3149`
   「阶段3 方案 Z：框架驱动 build-retry。transition 直调 Deployer().deploy(state)」），
   会话内框架不介入。

### 后果

- **轨迹浪费**：agent 花 ~3h15m/805-turn 复刻「构建方法论」（读 build.sh/cmake/op_build 链、
  试 ccec、手动装包），不是写码。同类：multi-addrmsnorm 974-turn。
- **污染共享环境**：装系统 vendors + `/root/opencode_smoke`，影响并行/后续兄弟算子包
  （本批 06:15 not_codegen 判定已指控该污染：被剥路径后回退扫描系统 vendors、被兄弟包
  TakeAlongDimCustom/logcumsumexp_custom 覆盖）。
- **误判编译结果**：agent 自判 build 成功而 binary 未出（证据 4），质量信号不可信。
- **上下文膨胀**：build 原始输出/试错轨迹持续进 agent 会话，是 805-turn 失控的上下文源之一。

---

## P2 — build / install / smoke 在 Deployer 内部绑定，无「只编译不装系统」的独立入口

### 现象（代码事实）

1. `stages/deploy.py:277-310` `deploy()` = `_resolve` → `_run_build_install`（build+install
   两段绑定）→ `_run_smoke_phase`。
2. `deploy.py:253-275` `build_install()` = build+install（无 smoke），仅给 cannbench_adapt。
3. **没有"只 build、不 install 系统"的独立公共入口**；docstring 明说 "Every other method is
   an `_`-prefixed internal step"（`deploy.py:178`）。build 与 install 在 `_run_build_install`
   里绑定，颗粒到不了单拆。

### 后果

- 「让 agent 编产物验证、但不允许装系统/污染」这个**合法诉求没有对应的受控入口**可暴露——
  暴露给 agent 的只有"全链 deploy"或"全禁"，两难。
- 与 P1 同根：正因为没有一个"只编译不装系统"的中间形态，agent 要么全链自研（越权），要么
  无任何会话内验证能力。

---

## 需求（纯事实，不提方案）

- codegen agent 会话内应有一个**框架受控的构建入口**，而非自由裸 Bash（P1）。
- 编译产物验证与「装系统 / 触发部署」应**可分离**，使"验证编译"不必连带"污染环境"（P2）。
- 编译/运行错误应**结构化收集**（全量去重、带 file:line 定位）注入 agent，而非让 agent 自己
  从原始日志找（现状 build 侧 `domain/build_log_scanner.py::scan_kernel_compile_errors` 已
  具备全量去重 `KernelCompileError[]`，但只在轮末反馈用，未接会话内循环）。
- kernel 阶段（runtime/数据/同步）错误**不在 codegen 会话内吸收** → known_issues → precision
  （现状路由已存在）。

## 边界

- **禁止**用轮次限制/压缩单轮工作量来换取机制便利（用户 2026-09-05 明确绝对禁止——质量优先，
  compaction/长 session 用状态物化解决，不用限轮）。见项目记忆
  `codegen-no-turn-limit-never-sacrifice-quality`。
- 不空谈 compaction / 长 session 行为（用户 2026-09-05：未遇真实问题前不预判）。
- precision_debug 的 diagnose agent（本职含 build+回验，经 redeploy CLI）**不在本问题范围**——
  它是 build 的合法消费者，与 codegen「agent 不应自研构建」是两种角色。
- A5 regbase 路径产权归同事，不越界（若有涉及需单独确认）。
