# 批 20260829-142941-49134b 失败归因 — L1 问题记录（2026-08-30）

> 层级：**L1 / 问题记录**。只陈述「哪里坏了、凭什么这么说」（证据/现象/代码事实）。
> **不提方案、不排顺序、不写决策**。方案分析待逐问题讨论后落 `02-analysis.md`（L3）。
>
> 本目录记录 2026-08-29 首跑批（6 算子，2/6 OK，3/6 出分）暴露的问题族。
> 用户关注点：这些问题里哪些是当前工程的问题、哪些可提升算子生成成功概率、
> 模型吐字速度的影响几何。

## 证据来源

- **批**：`batch_id=20260829-142941-49134b`（首跑，无 resume）
- **总日志**：`logs/batch_20260829_222922.log`（行号引用均指此文件）
- **exec 目录**：`output/20260829-142941-49134b/<exec_id>/`
  - logcumsumexp_custom → `20260829-142941-d4157b`（FAIL exit 124）
  - take_along_dim_custom → `20260829-142941-c1f443`（FAIL exit 124，eval 37.50）
  - unique_dim_custom → `20260829-142941-1e8e2e`（FAIL exit 65）
  - interpolate_custom → `20260829-142941-ecc9b4`（FAIL exit 124）
  - mse_loss_cross_entropy_loss_custom → `20260829-142941-6f61da`（OK，eval 50.00）
  - upsample_custom → `20260829-142941-bafa4e`（OK，eval 50.00）
- **worktree**：`cann-bench-batch/20260829_222922/`（保留；op_dir 已全部 repo_rollback 回 `c5fe7818`）
- **配置**：`resources/orchestration-config.json`；模型 `tokenfly-glm-5.3`
  （网关 `http://1.95.37.146:8082/v1`，context 200000 / output 128000，
  见 exec `.opencode_home/opencode-config.json`）
- **环境实证**：`/root/.local/lib/python3.11/site-packages/sitecustomize.py`（2026-08-21
  23:54 装入，2026-08-30 复现后缀剥离 + `PYTHONNOUSERSITE=1` 逃逸）、
  `/usr/local/Ascend/ascend-toolkit/latest/opp/vendors/`（custom_ops / logcumsumexp_custom
  残留，mtime 07:35:42 / 08:23:48）
- **marathon 会话复原**：`output/20260829-142941-49134b/20260829-142941-d4157b/.opencode_home/data/opencode/opencode.db`
  （sqlite part/message 表，session ses_fb14f7823ffelJU4CZKX5dx5GR，1032 tool parts——
  工程 transcript 零落盘时的幸存证据源）
- **env 语义权威**：知识库 `basic_knowledge_docs/附录/工程化算子开发/算子包编译/算子包部署.md`
  （ASCEND_CUSTOM_OPP_PATH = vendor 级冒号分隔优先列表）

## 批总况快照（事实）

| 算子 | 终态 | 全链耗时 | codegen 阶段 | 备注 |
|---|---|---|---|---|
| mse_loss_… | OK | 31134s | ok 17738s | codegen 893 turns 后干净完成 |
| upsample_custom | OK | 26608s | ok 6889s | 经 precision_debug 修复后 50 分 |
| take_along_dim | FAIL(124) | **36321s**（超 36000 预算 321s） | ok 24581s | **eval 已完成出分 37.50**，finalize 被超时杀 |
| logcumsumexp | FAIL(124) | 36028s | aborted 23269s | 见 P1/P2/P5 |
| interpolate | FAIL(124) | 36034s | aborted 20029s | 设计阶段 general-design 即耗 10405s；见 P1/P2 |
| unique_dim | FAIL(65) | 19622s | partial 9821s → halt | 见 P6；5 轮迭代仅落盘 2 个 tiling 头文件 |

批 wall：22:29:41 → 08:35:43（10h06m）。`workflow_timeout_sec=36000`。
批内 silent-cut 事件共 **30 次**，覆盖全部 6 算子、design/codegen/precision 全阶段类型。

---

## P1：产物验收依赖「turn 干净结束」的三个门组合——cut 边界验收正常，abort 边界验收被跳过，workflow 超时边界无条件销毁盘上产物

**现象**：logcumsumexp 与 interpolate 在被杀时刻，repo 内已有**完整且合规**的 codegen 产物，
但产物从未进入 build/smoke 验证，最终被 workflow 超时路径的 `repo_rollback` 清掉。

**机制（三道门，代码级核实）**：

- **门 1 · silent-cut 边界——读盘验收存在且工作正常**：
  `opencode_backend.py:838` 在 cut 判定前已 `_collect_artifacts`（盘上收集，git diff 派生权威
  changed_files）；cut 结果 `status="ok"` + artifacts（`base_backend.py:305-307`）；
  `is_infra_failure(cut)=False` → runner 直接调 transition（`runner.py:412`）。
  本批实证：04:44:02 与 05:06:01 两次 cut 边界 transition 均跑了 sections 校验并发出
  **定向 artifact-retry**（`Missing expected sections: ['op_api', 'op_host']` retry 1/5、2/5）——
  反馈回路有效，05:06 会话确实补齐了 op_host/op_api（08:30 git diff 15 文件全在）。
- **门 2 · abort/infra 边界——产物已收集但 transition 被跳过**：
  hard-cap kill 走 exception 路径（`opencode_backend.py:894` 同样收集了盘上 artifacts），但
  `aborted` → `error_type=infra` → `is_infra_failure=True` → runner 进 infra_backoff 重 spawn
  分支（`runner.py:412-437`），**不调 transition**——盘上已合规的产物要等「下一次干净结束的
  turn」才被认可。08:30:29 infra-retry 1/4 已批准（睡 20s 重采样），20s 后总超时到达。
- **门 3 · workflow 超时边界——无条件销毁**：
  `dispatcher.py:1068-1073`：`WorkflowTimeoutError/StageTimeoutError → _rollback_repo_if_needed`
  → `git checkout+clean op_dir`。对照：cancelled / decision-pending 走 `_preserve_repo_with_hint`
  （非破坏，保留改动 + 提示手动回滚）。timeout 路径不检查盘上产物的合规性。

**证据（logcumsumexp / d4157b）**：
- 05:06:01 第 5 次 codegen spawn。**该边界 crash-salvage 落盘的
  `artifacts/codegen/codegen_manifest.json`（147 字节，mtime 05:06）内容合规**：
  含 `op_name: "LogcumsumexpCustom"` + `callable_target{kind: torch_op, symbol: …}`；
  同目录有 `op_kernel/`、`op_plugin/` 源码目录。
- 05:06–08:30 同一 POST 持续 12260s（= 剩余总预算），期间补齐 op_host/op_api/CMakeLists，
  turn 始终未结束；
- 08:30:28 撞 hard cap 杀 serve；08:30:29 infra-retry 批准；08:30:49 workflow_timeout；
  git diff 列出 15 个文件（全套 op_host/op_kernel/op_api/op_plugin + codegen_manifest.json）；
- `repo_guard.py` 执行 `repo_rollback op_dir restored to c5fe7818b8c2 (checkout+clean)`——产物消失。

**证据（interpolate / ecc9b4）**：
- `artifacts/codegen/codegen_manifest.json` 内容合规（op_name + callable_target + 全 layers 清单），
  `generated_at: 2026-08-30T08:10:00`——**被杀（08:30:34）前 20 分钟刚落盘**；
- 同型：POST 撞 733s hard cap（= 剩余预算）→ timeout → rollback。

**因果链**：马拉松 turn（P8）把「补齐 sections」的完成时刻推到预算尽头；门 2 的重 spawn 刚
获批 20 秒后总超时到达；门 3 无差别销毁。三道门各自有合理设计意图（cut=防半成品、
infra=重采样网关窗口、timeout=保护仓干净），组合起来在慢模型下成为「差一口气全丢」。

**附带发现（推断，未实证 resume 行为）**：rollback 后 backend 侧 session sidecar 未清
（清除仅在 turn 干净结束时发生）——coder 会话记忆包含「已写过 op_host 等」，而树已被回滚。
resume 时记忆与代码分叉。step-98 已在 stage teardown 路径修过同型问题
（「resume ⇒ 不动树」），workflow timeout 的 rollback 未对齐该原则。

**影响面**：本批 4 个失败中 2 个（logcumsumexp、interpolate）直接源于此。

## P2：预算算术——36000s 总预算对当前吞吐不足，且无「剩余预算感知」的用度行为

> **状态（2026-08-30 裁定）：非工程改进点，收口。** 依据：① 预算值是运维参数
> （`WORKFLOW_TIMEOUT` env），用户手动管理，工程不做自适应/自动放宽（会自己长大的预算
> 不再是成本护栏）；② 质量第一——任何压缩 agent 工作/提前收尾去凑预算数字的方案不合格；
> ③ 超时后果已由 step-107 修复（preserve+resume 使超时降级为廉价检查点，分钟级代价）；
> ④ 预算内浪费逐项归位（2026-08-30 随 P5 撤销修正：原「判定后空转→P5」不成立，
> marathon 会话实为生产性工作）——cut churn → P6、消耗体量 → P10/P11、
> 形态 B 剩余代价 = 生产性工作撞墙，由 resume 继续；
> ⑤ 预算感知（含 P12）按 §1.14 暂不做，待 P5/P6 修复后重估。

**现象**：失败集中在预算边界；且存在「剩余预算不多时仍开启实际耗时超过全部剩余预算的单 turn」的用度形态。

**证据**：
- 各 op 全链耗时见总况表：OK 的两个为 26608/31134s；take_along 在 **36321s** 被杀时
  eval 已完成（08:26:51 起 CannbenchScorer 出分 37.50，08:35:42 完成），finalize 差 321s；
- codegen 单阶段实测 17738–24581s（ok 路径）；
- logcumsumexp 05:06 spawn 时剩余预算 12260s ≈ 3.4h，该 turn 实际跑满至预算耗尽
  （无中间检查点、无「预算不足不开新 marathon turn」的门）；
- interpolate 设计阶段 general-design-generator 单阶段 10405s（对照其他算子 2416–3678s），
  设计链提前吃掉 ~3h，使 codegen 可用预算更紧。

**对照事实（能力存在性）**：mse 以 893 turns 在 codegen 17738s 内干净完成并 OK——
当前吞吐下端到端可成，失败集中在边界与浪费，不是「做不出」。

## P3：环境污染完整证据链——外部 hack 篡改**正确的** env 契约，受害 agent 反向污染机器（三向量），跨算子假失败

**现象**：mse_loss 的 coder（exec 6f61da）在 codegen 尾段诊断出与算子代码无关的环境问题
（smoke 反复失败），判定 not_codegen 交 D4；环境单变量修复后 smoke 全绿，最终 eval 50.00。
**（2026-08-30 归属修正：原记录误归于 logcumsumexp；判定时间线属 mse，其 codegen 于
06:15:54 随判定消费而正常收束，最终 eval 50.00——D4 通道本身是成功案例。）**

### 证据①：框架的 env 值形态正确（语义之争定案）

CANN 官方文档（知识库 `basic_knowledge_docs/附录/工程化算子开发/算子包编译/算子包部署.md`）：
`ASCEND_CUSTOM_OPP_PATH` 的合法粒度是 **vendor 级路径**（`<path>/<vendor_name>`，
冒号分隔优先级列表；`set_env.bash` 追加的正是该层；指定目录安装优先于默认安装）。
框架 `deploy.py:857` 设的 `<per-op-opp>/vendors/custom_ops` **恰为 vendor 级——正确**。
sitecustomize 作者「剥到 opp 根」的假设与文档相悖——该 hack 是在把正确值改成错误值。

### 证据②：sitecustomize 篡改复现 + 确定性逃逸口（2026-08-30 实证）

- 复现：`ASCEND_CUSTOM_OPP_PATH=/tmp/demo_opp/vendors/custom_ops python3 -c ...`
  子进程读到 **`/tmp/demo_opp`**（`/vendors/custom_ops` 后缀被剥，一层偏高）；
- 逃逸口：`PYTHONNOUSERSITE=1` 时子进程读到原值——user-site 的 sitecustomize
  可被机械禁用（篡改可确定性规避）；
- 文件：`/root/.local/lib/python3.11/site-packages/sitecustomize.py`，2026-08-21 23:54
  root:root 装入——**先于本批 8 天，此后所有批均在该毒环境下跑**；
- coder 自证修复：`ASCEND_CUSTOM_OPP_PATH` 经 symlink 传入（值不以 `/vendors/custom_ops`
  结尾，绕开后缀匹配）后 `smoke_script.py` 完整通过（kernel_done 171.7ms，accuracy passed）。

### 证据③：系统 OPP 污染源=受害算子自己的 agent（opencode db 复原，2026-08-30 坐实）

logcumsumexp marathon 会话（05:06–08:30，工程侧 transcript 零落盘）的 **1032 个 tool
parts** 自 `d4157b/.opencode_home/data/opencode/opencode.db`（sqlite part/message 表）
复原，实锤该会话写入系统目录的**三个污染向量**：

1. `bash <dist>/cann_bench_*.run --quiet`（**默认安装、无 --install-path**）→ 写入系统
   `opp/vendors/custom_ops`（mtime **07:35:42**）；
2. 多轮 `rm -rf $TH/opp/vendors/logcumsumexp_custom && cp -r …`（**手工拷贝裸算子包**，
   末次 **08:23:48**；28+ 轮 build 循环 lcse_build2..31 期间反复重装）；
3. **两个共享包被整体 pip 重装**（比原记录的"cp 一个 `__init__.py`"严重，2026-08-30
   清理时坐实）：site-packages 的 `cann_bench`（07:04，含 `_C.abi3.so`）与
   `cann_bench_utils`（08:26，含 `_C.so`）dist-info 全套 mtime 落在 marathon 窗口内
   ——agent 把批 worktree 构建的 wheel 直接 pip install 进了共享解释器。

随后该会话以自造 env（`ASCEND_CUSTOM_OPP_PATH=<pkg> + LD_PRELOAD=…/libcust_opapi.so +
PYTHONPATH=/root/lcse_pkg`）绕过框架 smoke 通道，转入真实 kernel ABI 级调试（ws 指针
ABI 探针、llvm-objdump 反汇编、`__CCE_KernelArgSize` 比对）。即 marathon 3.4h =
环境自救 + 深度 kernel 调试的混合，非空转。

**附带观察（另行跟踪）**：该会话直接 `ASCEND_RT_VISIBLE_DEVICES=1..5` 跨卡调试，
绕过 card_context 租约——卡租约旁路的又一实例。

### 证据④：跨算子损害与未决项

- mse 06:15 的 smoke 判定证明系统 vendors 批内更早即被污染（marathon 05:06 起床后于
  06:15 前已可装入 logcumsumexp_custom；判定提及的 TakeAlongDimCustom **来源已明**
  （2026-08-30 清理坐实）：系统 `custom_ops` 目录自 08-27 00:36 即存在（bin/scripts
  mtime），系某次批前会话默认 `.run` 安装所建——`.run` 包含仓内全部算子（含内置
  add/sqrt），take_along_dim 随包入内；marathon 07:35:42 的默认安装是刷新而非首装）；
- mse 全程 smoke 受扰（工具调用贯穿 turn 2..1102）；诊断集中尾段（sitecustomize 首现
  turn ~962/1105，精确分钟不可考——transcript 时间戳为会话回读时刻）；
- 时间成本：agent 现场诊断一次 ≈ 小时级预算；污染对全批生效，推高所有算子验证成本。

### 本质（证据链闭合后）

- 隔离边界是一条**无人守护的正确契约**：值形态正确（证据①），但共享解释器上任人可
  全局改写、且子进程 env 无完整性校验（证据②）；
- 破坏后的**放大机制**：框架 smoke 通道失效 → agent 的理性自救是污染系统目录自建通路
  （证据③）→ 反过来制造 KI-2 兄弟覆盖，把假失败传染给其他算子（证据④）——
  **一个外部 hack 繁殖出三个污染向量**；
- 全链无一处 fail-fast：sitecustomize 静默改值、GE 静默回退系统扫描、症状经三层传导后
  与 codegen bug 同形，直到 agent 烧掉小时级预算才定位。

### 现场清理记录（2026-08-30 21:48，用户授权执行）

依赖确认（全过）：shell 配置无引用、无活进程占用（lsof 空）、user-site 仅含
sitecustomize 单文件、系统 vendors 内全部算子均属批任务/批前会话产物（无人受益，
mse 的 smoke 是受害者而非受益者）。已删：

1. `opp/vendors/custom_ops` —— 经 `.run` 自带 `scripts/uninstall.sh`（连带清
   `config.ini` 的 load_priority）；
2. `opp/vendors/logcumsumexp_custom` —— rm；
3. `/root/.local/lib/python3.11`（user-site，仅含 sitecustomize.py）—— 整删；
4. `/root/lcse_pkg`（marathon 私有 PYTHONPATH 包）—— rm。

清理后验证：`opp/vendors` 恢复 CANN 安装期空目录；env 契约复测——子进程读到完整
`/tmp/demo_opp/vendors/custom_ops`（篡改消失）；`import cann_bench_utils, torch` 正常。

**保留项（非毒，用户判据：不伤工程 / 不伤 CANN+python 基座即可）**：site-packages 的
`cann_bench`/`cann_bench_utils` 两个 pip 包系 marathon agent 07:04/08:26 安装，但内容 =
origin 干净源码的构建产物（`git status` 无改动、绑定只有内置 add/sqrt）。工程链路对它
们零依赖有铁证：harness 生成物首行 `sys.path.insert(0, <exec>/artifacts/per-op/<op>/python)`
（注释原文 "per-op cann_bench before site-packages"）+ cann src 注入——工程自闭环，
site-packages 副本纯惰性，保留即无动作。

**其他惰性残留（留置，均无害）**：`/root/opencode_smoke`（mse coder 的隔离实验沙箱，
其 decision_log 引作证据）、toolkit 根下空 `vendors/` 目录、`vendors_test/`（批前测试区）。

**sitecustomize 写作动机（新增事实）**：其注释明写「Fix ASCEND_CUSTOM_OPP_PATH set
by ascendc-devkit run-cases」——作者因 run-cases 产物出现 SIGSEGV(-11) 而写，错误
归因于 vendor 级路径值（与 CANN 文档相悖）。本机 SIGSEGV 历史根因另有其物
（libcust_opapi.so SONAME 冲突 / torch_npu↔CANN 配套错配）；如原作者仍遇 SIGSEGV，
应向真根因方向排查，而非改全局 env。

### 产权边界

- 不归框架修：sitecustomize 内容、共享解释器、他人行为、GE 回退语义（既有裁定：外部
  infra 不归框架修）。
- 归框架可做（记录现状缺口，方案待 L3）：① smoke 前置环境断言（子进程 env 幸存探针 +
  系统 vendors/site-packages 干净度检测），命中即 fail-fast 留精确信号；② env 免疫
  形态机械构造（vendor 级 symlink 变体，coder 已实测可用；`PYTHONNOUSERSITE=1` 亦实证
  可逃逸——框架可确定性施加）；③ agent 侧系统目录写入的检测/信号（无法禁止 bash，
  但可让污染可见）；④ env 类失败与 codegen 类失败的机械区分。

## P4：changed_files 双轨报告残留——框架已从 git diff 派生权威报告，自报解析与交叉校验 WARN 仍在，产物格式坏时产生大量噪音

**代码事实**：`capabilities/agent/_shared.py:744-860` 的 `_collect_changed_sources`：
- git diff 侧是权威（`repo_guard.changed_paths`），自报 ∪ diff 取并集收集文件内容；
- **已存在构造性派生**：无论 agent 自报写没写/写成什么样，框架都从 git diff 机械派生
  `changed_files.json` 落进 artifacts（§2.9 注释明示，20260810 批 6/6 假 "didn't report" 根因后所修）；
- 残留：双向交叉校验 WARN（`_shared.py:820-823`）+ `stages/codegen.py:2326` 的 prompt
  仍教学 agent 写自报报告的位置与格式。

**本批实例**：interpolate 的 changed_files.json 非约定格式（顶层混入 `base_commit_scope` /
`generated_at` / `op_name` 等键 + 条目为带超长 desc 的 dict），自报解析产出垃圾键，
`lists files git diff didn't` WARN 单次打印数千字符。该校验为纯信息性（不触发重试），
主要代价是日志噪音 + prompt 篇幅。

**扩展事实（2026-08-31 用户观察 + 取证）**：
- **第三处教学点漏记勘误**：`perf.py:322` 同样教写 changed_files.json（原记录仅
  codegen:2326）；
- **每轮必响的告警根因**：三个契约元数据 json（`codegen_manifest.json` /
  `decision_log.json` / `changed_files.json`）按契约写在 op_dir 根（A3 共享 prompt
  教学 + A5 regbase SKILL:351 同款），git 视作**未跟踪新文件**收进 diff 侧，而
  agent 不在自报里列它们 → `git diff found changes the agent didn't report`
  每轮必响；且它们**混进派生"算子源码改动"报告**（非算子改动）并**混放**
  `artifacts/codegen/`（mse 实证：三个 json 与 op_kernel/ 等源码目录平级混放）；
- **自报残存的唯一真实功能**：per-file `deleted` 标签（`_report_op`）——缺它则纯
  diff 发现的删除文件因读不到内容被静默丢弃，不进审计产物（`git diff
  --diff-filter=D` 可构造性派生）；
- **A5 共享面**：regbase codegen 与 A3 同 stage 类（codegen.py:959 按 profile 选
  skill），`_persist_sources` 8 调用点/backend 收集/repo_guard 均 A3/A5 共享；
  A5 skill 不教自报（grep 零命中）。

## P5：（2026-08-30 复核撤销——原记录基于归属错误）

**撤销说明**：原记录「coder 产出 D4/not_codegen 判定后不终止 turn，继续生成 2h15m」
经复核为**事实归属错误**：06:15:54 的 D4 判定属于 **mse_loss**（exec 6f61da，紧随其后
`codegen done (17738.3s)` 即其 codegen 耗时），且该判定**在其会话终点被正确消费**——
ownership 通道按设计工作（step-93 机制的成功案例）：smoke 失败被 coder 正确归因为环境
问题 → `not_codegen` 判定 honored → D4 交下游 → codegen 正常收束 → 最终 eval 50.00。

logcumsumexp 的 marathon 会话（05:06–08:30）从未产出 D4 判定——它在执行 artifact-retry
反馈指派的工作（补齐 op_api/op_host，git diff 5→15 文件），属正常生产 + 预算墙
（P2/P8 语境，均已裁定/另立）。「判定后空转 2h15m」的浪费不存在。

**连带修正**：P2 收口注记④、P3 归属、P12 引用中的 P5 相关表述已同步更正；
D4 通道无需「判定即终止」的 skill 修改。

## P6：silent-cut 全批系统性发生；cut 恢复链每次全量重付（杀 serve + re-spawn + resume 重载大上下文）

**现象**：批内 `agent silent-cut (no artifact, thinking-only terminal)` 共 30 次，
覆盖 6 算子 × design（tiling/synthesize/docgen/general-design）× codegen × precision_debug。

**检测机制事实**：`base_backend.py:443`——末条 assistant 消息无 text 且无 tool_use（仅 thinking）
即判 cut；cut 不烧 iteration 预算（`runner.py:660-674`），cut_streak 阈值 5
（`orchestration-config.json retry_budgets.cut_streak_threshold`）。

**取证结论（2026-08-31，L6a 上游成因坐实——silent-cut = 输出 token 墙截断）**：

- **解剖签名**：每个 cut = `step-start → reasoning → step-finish`，末步**只有 reasoning、
  无 text/tool**，reasoning 文本**中断在推导句中间**（内容连贯进行时，非自然收尾）；
- **流活跃到最后一秒**（样本全查：reasoning 部件 time_updated == step-finish 时刻，
  10m38s 内累计 95084 chars ≈ 149 chars/s 正常速率）——排除"模型自己停"；
- **token 墙非时间墙**：全批 34 个签名步，步长 65–716s **散布**、reasoning 体量
  **87k–118k chars 聚集**；全库 4395 个 reasoning 部件 max=118132 **无一超越**，
  p99=86k 恰是截断起始——硬墙 ≈ **32k tokens/步**（混排文本 ~3 chars/token，
  87k–118k chars = 29k–39k tok 完美吻合；16k/64k 假设均被分布否决）。网关配置
  output=128000 **未按此执行**（推理 token 另受低限约束或网关覆盖）；
- **截断无协议标志**：全库 6425 个 step-finish 的 finishReason **全部为 None**
  （含正常步）——网关截断不带 finish_reason，opencode/框架无法从协议层感知原因；
- **恢复循环注定无效的机理**：resume 续同一深推理轨迹 → 再撞同一墙——logcumsumexp
  T3 同会话三连切实证（641s/703s/691s，每次 ~95k chars 全新推理）。cut 不烧 iteration
  但烧 wall 预算，30 次全量重付由此而来；
- **撞墙集中在深推理步**：reasoning p90=14k，设计阶段与 unique_dim 的"设计在脑内"
  型 codegen 才产生 85k+ 的单步推理（与 P10/P11 直接相连）；marathon 的 500 短步
  （每步小 reasoning）从不撞墙——同模型同网关；
- 旁证（另记，与 cut 无因果）：serve 日志含 `inotify_add_watch ... No space left
  on device`（watch 耗尽警告）。

**取证补充与修正（2026-08-31 第二轮，方案讨论前置验证）**：

- **resume 机制实证**：cut 恢复的首条 user 消息就是裸「继续」（`_RESUME_PROMPT`）；
  恢复后模型能续上自己的分析（样本开场 "Let me continue… Key insight from my
  analysis"）——模型对"被截断"毫不知情、靠自猜；该会话恢复后 22 轮健康收束；
- **修正「恢复注定无效」**：准确表述为「**剩余推理仍超墙的任务**恢复才无效」
  （take_along 一次恢复成功 vs logcumsumexp T3 三连切）；
- **双计数器语义核实**：`resume_fails`（sidecar，会话级退化策略）与 `cut_streak`
  （runner，阶段级放弃策略）判**两个不同事实**；「复位不一致」是正确语义非 bug
  （非 cut 轮打断连续性/自然结束重建会话合法性）——L1 原「双计数器观察」条目
  据此定性为可读性问题，非缺陷。

**取证第三轮（2026-08-31，用户质询触发——撞墙内容可否 resume 续用）**：

- **thinking 在 resume 时回放、模型中点无缝续写**〔**本条结论已被第四轮证伪，
  保留原文仅为取证史**〕：三连切样本中 cut 尾部悬问（"could route S use
  M0/M1/S0/S1 as xFp32/yFp32??"）被 resume 后**首条输出**直接以解答公式接上
  （"UB 公式统一为 24B×P + 8B×tileLine"）——当时解读为撞墙内容不丢失、零重推；
- **墙按步计算（机械事实）**：marathon 单 POST 500 步不撞墙、resume 簇中
  38k/31k chars 推理步安全通过、仅 87k+ 单步被切 → **写文件/调工具=切步=重置
  单步输出预算**，是机械上已证明的避墙法；
- **方案修订（用户裁定）**〔已随第四轮结论再次修订，见下〕：当时改为
  `resume_fails≥1` 升级式——前提"裸继续已证明无效"与"thinking 可续"均被
  第四轮推翻。

**取证第四轮（2026-09-01，用户质询"thinking 是否真的能续上"触发——全消息
序列级证伪）**：

- **thinking 分步独立、不可续写**：T3 三连切会话全消息序列实证——被切步
  98,801c reasoning 终止后，resume 首条消息 **0c reasoning**（纯 text 直接
  给出答案），下一条消息才是**全新** 38,745c reasoning。resume 续的是**可见
  输出**（text/tool 结果，留在会话历史里），**不是 thinking 回放**——第三轮
  看到的"无缝接上"实为模型在无推理步里依据上下文作答，非思考续流；
- **推论（方案地基）**：撞墙丢的是那一步未完成的思考；resume 无法挽回它，
  唯一通路=引导把后续思考**转成落盘产物**（落盘不丢 + 切步重置单步预算）；
- **Python 侧运行时证据可得性坐实**：opencode SSE `message.part.delta` →
  增量 thinking 块（`opencode_sse.py:149`），消费器可实时累计 thinking 增量；
  34/34 硬切步"末次 thinking 增量距截断 ≤0.58s（中位 0.12s）"——**gap 判据**
  （截断时思考流仍活跃）零模型参数、运行时可判；
- **方案定稿（用户设计，多轮否定后收敛）**：首次正常执行零注入；判据
  `cut + gap≤阈值` 命中时 resume 原上下文 + 兜底提示「先落草稿，再边落边思考」
  （仅此判定注入）；未命中判定的 cut 维持 resume_attempts=3 原路径（未知中断
  试探语义对瞬态故障仍正确）；硬切分类**不** bump resume_fails（达阈退化
  fresh 会丢上下文重放同一深推理再撞墙）；**上限=既有 cut_streak=5（连续
  语义，已可配置）+ 迭代天花板（穿插进展），硬切总次数纯观测**——曾设
  `cut_recovery_max=30` 独立预算，用户指出其算术依据（30 段续完一条
  thinking）随"可续"证伪，2026-09-01 二次裁定**删键**（零新无据阈值）；
  唯一新配置键 `thinking_active_gap_s`（默认 0.6，网关 flush 粒度参数）进
  retry_budgets 统一组。质量序（用户裁定）：高质量 > 低质量 > 不产出。
  **定稿过程的方案否定清单见 L3（08-analysis）防回头路表**。

**错误族分解与归并（2026-08-31，方案讨论定稿）**：五错误分解（①墙本体 ②恢复
信息缺失 ③unique_dim halt=复合 ④呈现偏离事实 ⑤计数器可读性）；**归并**：错误
1+3 的根因事实（蓝图缺物理层→深推理）**前移 P10 吸收**（撞墙实证随迁；作业顺序
P10 提前为 P6 后下一题）；错误 2+4+5 合并为事实呈现修复；**P7 并入 step-110**
（同一日志位点的共性修复）；网关不可控（用户确认），框架侧零阈值原则（不引入
magic threshold 分类，全部呈现实测值）。

**churn 成本实例（logcumsumexp codegen）**：5 次 spawn（02:02 / 03:33 / 04:25 / 04:44 / 05:06）；
4 个 coder transcript 共 33MB（单会话最大 6.05MB，模型 context 上限 200k）；
每次 cut = 杀 serve + 新端口 + 重建配置 + resume 重载上下文。

**双计数器观察（机制记录，未深查）**：backend 侧 sidecar `resume_fails`（阈值 3，达阈退化 fresh）
与 runner 侧 `cut_streak`（阈值 5）复位语义不同——unique_dim 呈 1/3→2/3→3/3→退化→重新 1/3；
logcumsumexp codegen 三次无效 resume 均显示 1/3（其间夹 artifact-retry 非 cut 轮，疑似被复位）。

**unique_dim 终局事实（细化）**：codegen 5 轮迭代（state：iterations=5, artifact_retries=2）
仅落盘 2 个 tiling 头文件 + changed_files.json，cut_streak 5/5 耗尽 → `fail_strategy=halt`
（exit 65）。其 coder 并非"没干活"：1.7M chars thinking 为高质量非重复推理（见 P10），
问题是**设计迭代停留在脑内、不转化为代码落盘**。

**transcript 语义事实**：resume 会话的 transcript 文件包含**全部历史**（每次 spawn 后从
session 历史回写），跨文件相加会重复计数；永不返回的 POST（hard-cap 杀）transcript 零落盘
（仅 137B crash 记录）。跨会话体量统计必须取最末文件累计口径。

**网关侧并发事实**：6 并发重会话共用同一网关；批内 1 次 spawn 超时
（05:32:16 take_along `opencode spawn failed: timed out`，infra-retry 自愈）、
2 次 hard-cap 杀 POST（08:30 logcumsumexp 12260s / interpolate 733s）。
silent-cut 的上游成因（网关掐流 vs 模型行为）未取证：本批 opencode serve 日志中
未检索到 429/1313 类错误记录。

## P7：循环退出日志「reached max iterations (40)」与真实退出原因不符（可诊断性缺陷）

> **状态（2026-08-31）**：并入 step-110（与 P6 呈现修复同属一个日志位点的共性
> 修复——cut_streak 耗尽路径的退出原因诚实化），不单独实施。

**代码事实**：`runner.py:691` 的该 WARN 在**任何**循环退出且契约未满足时触发
（含 cut_streak 耗尽路径），文案固定为迭代耗尽。

**本批实例**：unique_dim 03:57:23 连续输出
`cut_streak=5/5，iteration 保持 1/40` 与 `reached max iterations (40) without satisfying output_contract`——
实际生产 iteration 为 1（state：iterations=5 含 cut 恢复轮），退出原因是 cut_streak 耗尽。
日志会把排查引向「迭代预算耗尽」的错误方向。

## P8：模型吞吐形态实测——纯吐字速率与设计阶段持平，codegen 慢在体量与 turn 数；marathon turn 受「slow-but-alive」保护不可提前杀

**测量方法**：解析总日志 `agent_stream` 事件（累计 chars + 累计秒），取同 turn 内相邻事件
Δchars/Δt（Δt>0.3s、段内无 tool 边界），按阶段聚合。样本 n：design 2049 / codegen 3682 / precision 487。

| 阶段 | p50 | p90 |
|---|---|---|
| design | 186.5 chars/s | 352.0 |
| codegen | 273.7 chars/s | 376.0 |
| precision | 224.8 chars/s | 295.1 |

（换算 ≈ 93–137 tok/s，按 2 chars/token 粗估）

**体量对照（每算子取最末 transcript 的累计口径——resume 会话会把全部历史重写进新 transcript
文件，跨文件相加会重复计数；此为实测发现的 transcript 语义，本身记录在 P6）**：

| 算子 | codegen thinking 总量 | 最大单块 | compaction 次数 | 蓝图(tiling_results)重读 |
|---|---|---|---|---|
| logcumsumexp（失败） | ≈2.0M chars / 491 turns（至 05:06）+ 末段 ~500 turns 未落盘 | 98692 | 8 | 26 次 |
| mse（成功） | ≈2.26M chars | 61063 | 11 | 36 次 |
| unique_dim（失败） | ≈1.7M chars | **118132** | 5 | 30 次 |

单 turn thinking 峰值 98692 chars（logcumsumexp turn 230）、118132 chars（unique_dim turn 197）。

**marathon POST 事实（修正：非单 turn 停滞，而是单 POST 内持续高产的 agentic 循环）**：
logcumsumexp 终局 spawn（05:06）的单个 POST 内跑了 **~500 个 turn**（24.5s/turn 均匀节奏，
bash/edit/read/grep 密集，08:29 仍在 turn 498 出流）——期间 chars 持续增长（slow-but-alive），
`opencode_backend.py` 的 turn-stall 门（P137：chars 在涨即不杀）与 keepalive 门（SSE 帧在流即
不杀）按设计均不触发，唯一上限为**spawn 时一次性冻结的 eff_msg_timeout = min(剩余总预算,
14400)**。即：**一个 POST 的时长上界 = spawn 时刻的剩余预算，与会话实际生产力无关**。
另：该会话 transcript 零落盘（`ascendc-coder-05.jsonl` 仅 137B crash 记录——transcript 只在
POST 返回后从 session 历史回写，永不返回的 POST 留不下内容证据；幸存证据仅 batch log 的
agent_stream 行与 opencode session db）。

**因果归并（事实层）**：模型速度通过三条路径影响成功率——① marathon POST 吃满剩余预算且
不可中断（见 P1/P2 实例）；② 每次 cut/resume 重付大上下文加载（见 P6）；③ silent-cut 本身
疑似网关/模型不稳（成因未取证，见 P6）。纯速率本身与成功算子（mse 同为 2.26M thinking 仍 OK）
无必然矛盾。

**状态（2026-09-02，用户裁定收口）**：已被 107/110/111/112/113/115 吸收，框架侧无待修项
——①后果→step-107；②→110/112；③→110/115；体量源头→111/113。marathon 不干预
（P2 质量第一 + P12 催收尾降质量双重裁定；step-107 已把超时后果降为廉价检查点）。
速率/模型选型=运维域非工程。终验判据挂下批复盘：thinking 总量 2.0-2.26M 对照、补设计
占比 66.9%→<20%、整读占比 81% 对照、每算子 wall time 对照、marathon POST 时长分布。
条件触发的后续：layout_contract 覆盖不足→补设计侧；整读未降→收紧指针/收单体；
marathon 频繁撞墙→重开 P12；429 聚簇/吞吐随并发降→立并发对照。

## P10：设计产物缺少「物理级不变式」层——复杂族算子的硬不变式留给 codegen 现场补设计

**现象**：logcumsumexp/unique_dim 的 coder 在 codegen 里做了大量**架构级设计推理**（本应在
设计阶段完成），thinking 内容为真实高质量的 AscendC 工程推理（在线进位 combine、路由算法、
workspace 布局推导），非重复非垃圾（unique_dim 118k 字符大块 8-词 shingle 重复率 4/6709）。

**证据（蓝图 vs thinking 的精度差）**：
- coder **确实重度消费了设计蓝图**：tiling_results.json 被工具引用 26 次（logcumsumexp）/
  36 次（mse）/30 次（unique_dim），是全部 staging 文件之最；spawn prompt 明示其为
  「实现蓝图主源」；skill 在 turn 2 正常加载。
- 蓝图含**逻辑级协议**：T3.split 写明两阶段兜底「workspace[blockDim][totalLineNum][2] fp32
  → SyncAll → PhaseB 读前序段总量前缀 fold」；buffer_kernel.kernel_structure 含逐路由伪代码
  （F 路由的在线 (m,s) 进位数学完整）。
- 蓝图**不含物理级公式**：`tiling_results.json` 全文 `wsStride` 0 次、`publish` 0 次——
  而 coder 98k thinking 块的核心内容恰是推导 ws 平面布局公式、publish/fold 地址恒等式、
  host/kernel 公式一致性（原文自评「FRAGILE (host/kernel formula drift)」）。
- unique_dim 更极端：turn 197 的 118k thinking 在「T1 伪代码 vs 自己的 v3 改进」之间做
  对齐与再设计，1.7M thinking 只落盘 2 个 tiling 头文件——**设计在脑内迭代、不落地**。
- 对照组 mse（成功）：同为 2.26M thinking、11 次 compaction，但 elementwise+reduce 族
  蓝图精度足够直译，thinking 是翻译+验证性质（最大块 61k），893 turns 后干净完成。

**推断（待 L3 检验）**：设计 skill 的产物 schema（buffer_kernel.kernel_structure 等）止步于
shape_semantics + 上界描述，没有承载物理级公式/地址布局的字段——设计 agent 的深推理在
输出时被 schema 压缩掉，coder 只能重推。复杂族（scan/carry/fold、data-dependent sort 族）
暴露此缺口；简单族（elementwise/reduce）不暴露。

### 归因取证（2026-09-01，db 口径全量分类）

- **提取口径**：6 个 exec 的 opencode db 中全部 reasoning part ≥80,000 chars，共
  **50 块 / 4,817,487 chars**（无 transcript 重放）。口径修正：P6 记录的「4×98k 相同块」
  实为**同一 db part 在 transcript 读侧出现 4 次**（重放=重读，非再生），db 单实例；
  P6 的「34」是 cut 签名步数口径，与本 cohort 定义不同。
- **会话归属**（session.title）：design 侧（tiling/概设/synthesize/docgen）21 块
  2,042,952 chars（42.4%）；codegen 侧 29 块 2,774,535 chars（57.6%）。
- **codegen 侧按主导活动分类**（头/中双采样人工判定）：
  - **补设计**：19 块 1,856,062 chars（**占 codegen 侧 66.9%**）——内核算法重设计与
    物理布局推导：workspace slot 布局、跨核直方图前缀基址、tile 状态布局、broadcast
    stride 复合映射、span bound 公式、2^24 精度边界、跨管同步边界、kernel 结构 v3 重构。
    样本：118k「T1 伪代码 vs 自己的 v3 改进对齐再设计」、107k「kernel design v3 final +
    TilingData 17 字段」、98k「header 与修正理解不符→重构为 G lane-form」。
  - **编码期本职**：10 块 918,473 chars（33.1%）——API/样例验证（DataCopyPad 语义、
    ReduceSum 形态、Cast 模式、isPad dummy 行为、host AddAttr 重载）+ 实现层流水工艺 +
    golden 语义边界核对。其中 **3 块为 coder 期才发现的知识库级 API 事实纠错**
    （count 形态 ReduceSum A2/A3 无此形态、isPad=false 时 dummy 填待搬数据首元素值、
    Cast FLOOR/CEIL 对 fp32→fp32 适用性存疑）——设计期伪代码建立在未验证 API 假设上的
    同构缺口（验证本应在 buffer-kernel 期完成）。
- **逐算子分布**：unique_dim 10 块全部 ≥103k，其中**单个 codegen 会话 8 块 874k chars、
  7 块为补设计**（撞墙会话本体）；logcumsumexp 17 块中 11 块在 design 侧（scan 族设计
  内生深推理最重）；interpolate 14 块中 codegen 侧 11 块（5 补设计 + 6 验证）；
  take_along 5 块（2 补设计）；upsample 3 块 / mse 1 块全在设计侧或验证（对照成功组）。
- **resume 续块**：5 块带「reassess/recap where I am」式重锚定开头（design 侧为主），
  内容为继续真实推导非重复再生——与 step-110「resume 经全新推理继续」结论一致。
- **判定边界**：补设计/本职分界为人工判定，±2 块不确定性；即使 2 块移入本职，
  codegen 侧补设计占比仍 ≥60%。50 块逐块分类表（会话归属+头/中采样）见
  `10-analysis-design-physical-invariants.md` 附录。

**状态**：归因完成（2026-09-01）；step-111 已实施（2026-09-02，代码待 commit）。
L3/L4 = `10-analysis-design-physical-invariants.md` /
`11-impl-design-physical-invariants.md`。端到端判据待下批。

## P11：上下文经济性——200k 上限 vs 175k 设计产物，compaction 周期性冲掉已积累的理解

**事实**：每算子 codegen 会话 compaction 8–11 次（logcumsumexp 8 / mse 11 / unique_dim 5）；
蓝图重读 26–36 次/算子；单会话 transcript 最大 6MB。logcumsumexp staging 设计产物合计
约 300KB（tiling_results 175k + tiling_strategy 42k + general_design 40k + …），模型
context 上限 200k token。coder 的 98k thinking 块中可见「✓✓」式自我反复验证——对自己
记忆中的推导不信任，与 compaction 冲刷一致。

**推论（事实层）**：深推导 → compaction 冲掉 → 重读蓝图 + 重推导的循环，是 thinking
体量膨胀的直接机制之一；每次 silent-cut 杀 serve + resume 重载（P6）进一步加重同一循环。

### 取证补强（2026-09-02，opencode db 全 6 codegen 会话）

- **冲刷节奏**：compaction 每 **21–32 分钟**一次/会话（中位间隔 21.4–32.1min），
  触发时上下文 **130k–149k token**（模型 context 200k，≈75% 阈值自动触发）；
  每次 summary 输出仅 **6.6k–11.3k token**（冲掉 ≈130k 只留 <10k）。
- **冲刷→重读循环坐实**：设计产物读取 **58%–70% 发生在 compaction 后 ≤5min 内**
  （take_along 70%、interpolate 64%、upsample 58%；中位距上次冲刷 3.3–3.8min）；
  每冲刷窗口内重读 3.1–6.5 次。对照：unique_dim 仅 27%（其 codegen 更倾向**重推导**
  而非重读——正是 P10 归因的补设计 cohort）；mse（成功组）35%、3.1 次/窗口。
- **读的形态**：Read 工具的设计产物读取 **81% 为整文件读**（54/67，仅 13 次带
  limit/offset）；重读最多单文件 = `tiling_results.json`（22 次；logcumsumexp 份
  175KB ≈ 单次回灌 ~44k token——一次整读即回填冲刷量的 1/3 以上）。
- **会话量级**：code session 消息 197–1105 条；compaction 5–16 次/会话。
- **可观测性缺口**：compaction 事件只在 opencode db（`mode=compaction` 消息），
  框架侧零指标零日志——本循环需 db 取证才可见（§1.2 可诊断缺口）。
- **已缓解部分（先行步骤的旁证）**：step-112 反馈重派 resume 后，产物不合格
  重试不再全新 spawn（fresh spawn 的整上下文重建 >> 单次 compaction 重读）；
  P10 layout_contract 使 coder 需**持有**的事实从「推导链」缩为「契约字段」。

**状态**：已立案 step-113（L3/L4 冻结 2026-09-02，`14-analysis-context-economy.md`
/ `15-impl-context-economy.md`）；实施完成待下批端到端验证。

## P12：agent 对剩余预算零可见性——marathon 会话至 08:2x 仍在 edit/restructure，无「收尾」信号

> **状态（2026-08-30）**：随 P2 裁定暂不做——step-107 后超时=廉价检查点（preserve+resume
> 分钟级代价），预算可见性的主要价值已被吸收；且 quality-first 下"催收尾"有降质量风险。
> （原注"待 P5 修复后重估"随 P5 撤销失效；重估触发条件改为：P6/P10/P11 修复后
> 若 marathon 会话仍频繁以撞墙收尾，再重开。）

**事实**：coder 的 spawn prompt（5092 字符，含 9 个设计输入与全部契约）**不含任何剩余
时间/预算信息**；logcumsumexp 终局会话在预算耗尽前 10 分钟（08:20-08:30）仍在做
8606/19381 字符的 text+thinking+tool 轮次（read/grep/edit），未进入「固化产物 + 写 manifest +
结束」的收尾模式。框架持有剩余预算（eff_msg_timeout 即由它算出），但不向 agent 传达。


## P13：卡租约旁路家族——card_context 隔离可被 agent 手工 env 覆盖（P3 同根，独立成题）

**现象（本批实证）**：logcumsumexp marathon 会话（d4157b，05:06–08:30）在其 bash 内直接
设 `ASCEND_RT_VISIBLE_DEVICES`（1..5 轮换）跨卡调试，完全不经框架 card_context 分配。
证据源：opencode db（ses_fb14f7823ffelJU4CZKX5dx5GR）tool parts 复原（2026-08-30）。
原 P3 的「附带观察」一行升级立题。

**家族事实（既有同型实例）**：子进程路径旁路 card_context（更早批次已识别，为 NPU pool
transient 根因之一；step-90 实施记录）。即该家族至少两条旁路向量：①agent 在自己 bash
export 覆盖可见性 env；②命令串不经 card_context 前缀直接起子进程。

**机制事实**：step-90 的隔离 = card_context env 兜底 + 命令串前缀注入 + 阶段租约；
上述两种行为均落在机制覆盖之外——框架无法禁止 agent bash 内的 export。

**影响（结构性，本批未实证到具体受害算子——诚实边界）**：内核/ACLNN 调用可落到
租给兄弟 exec 的卡上，制造设备级争用；症状与既往 hdcdrv 偶发死等同族，难以区分归因。

**与 P3 的关系**：同根不同题——都是「框架 env 契约无人守护」的实例；P3 主修
ASCEND_CUSTOM_OPP_PATH 契约（值形态），P13 是可见性 env（卡的归属）。方案未讨论，
仅立题记录。

**状态（2026-09-02 更新）**：已立项修复（step-116，L3/L4 见 `18-npu-op-card-lease.md`）。
方案讨论中用户苏格拉底式质询五轮收敛：skill 零卡知识（D 纯删）→ agent 零卡知识、
卡问题=环境问题走 infra halt（B 砍）→ 子树结构 pin（env 继承）为机制本体 →
租约粒度按四把尺子+活性全谱审计裁 op 级（§1.15「漏写一处即出错」判据句已用本
事故演示过一次）。五项核实事实 + remap 语义实验 + 检测通道死路（fd/proc-mem）
见 L3 文档。用户裁定「op 级方案能够完全解决问题即按建议做」。

## P14：设计子阶段产物反馈重派走全新 spawn——丢会话上下文重付重定向成本（codegen 侧 step-100 已统一 resume，设计侧未跟进）

**事实**（2026-09-02，用户质询「为什么要重新 spawn 不能 resume」触发取证）：

- 同一行为类「产物不合格 + 带反馈重派 + 会话内可修」，两侧实现分叉：
  - **codegen**（step-100）：transition 入口写回 session_id 进 State → 反馈重派轮
    actions 带 `resume_session_id` + 短 resume_prompt（原会话已有完整任务书，
    不重发全量）。立项实测：全新 spawn 丢 152-turn 决策上下文、修复实为改一处
    却重付 ~7.5min 冷启动。`test_codegen_retry_session_resume.py` 锚定。
  - **设计子阶段**（含测试设计）：`_DesignSubstage.actions` 构造 SpawnAgent **不带
    resume_session_id**；session_id 在 transition 后丢弃（State 无承载字段）→
    反馈重派 = 全新会话。
- 设计侧后果：工作目录产物虽保留、prompt 带「增量修改上下文」补偿段，但新会话
    仍须重载 skill、重读上游产物、重建推导意图；修复 turn 与推导 turn 分属两会话，
    证据链断裂。受影响：全部设计子阶段（概设/模板划分/tiling×N/synthesize/docgen）
    + 测试设计三段——含 step-111 F2 打回的补字段轮。
- 机制前提已核实在位：SpawnAgent.resume_session_id 通路（runner :1120 转发）、
  双 backend 支持、fork-join 只合并 provides 字段（分支局部字段不进 join）、
  设计 review 为交互提问非 agent spawn（无会话双写）。
- **与 step-94 的表面张力（需在 L3 消解）**：step-94 曾对 codegen **smoke 反馈通道**
  否决 resume（否决理由原文：「iter1 带错误信念结束+无界会话泥潭是方案 Z 原始病灶+
  反馈自含后 fresh 优于 resume；resume 管线留 429 崩溃恢复本职」）；step-100 又对
  codegen **schema/build/artifact 反馈**采纳 resume。两裁定不矛盾，分界是语义性的
  （修复需不需要会话积累的上下文），L3 §3 展开——设计子阶段产物打回复属 step-100 类。

**状态**：已实施（2026-09-02，step-112 代码待 commit，UT 4029/ST 125 绿）。
L3/L4 = `12-analysis-design-feedback-resume.md` /
`13-impl-design-feedback-resume.md`。方案经用户确认：resume 是正确解
（§1.15 裁定），仅过程另立 step。端到端判据待下批。

## P9：eval 侧基线缺失（cann-bench 侧事实，仅记录）

take_along kernel_eval exit 5；全部 case `T_HW (0.0000 us) 非正 → 性能项按 None`，
perf=0.00；overall=37.50（compile 15.00 / func 22.50 / pass_rate 75%）。
T_HW=0 意味着 HW baseline 未测得——评分解释时注意与算子本身质量区分。

---

## 附：本 L1 未覆盖 / 待讨论时补充取证的事项

- silent-cut 上游成因（网关掐流 vs 模型行为）：opencode serve 日志无 429/1313 记录，
  需要的话可对 ses_* 会话 db / 网关侧日志另行取证；
- P6 双计数器复位语义的代码级确认；
- 并发度（design_concurrency=6）与网关争用的关系：本批仅观察到聚簇现象，未做对照，
  不构成结论。

## P15：diagnose skill API 查证链的假闭环——「知识库无记录」被判「API 不存在」+ 真值源被禁

**事实**（2026-09-02，用户在 step-113 复核中提出证词：「先前 debug 阶段因为禁止读取
CANN 导致问题迟迟无法定位」；文本证据 = `ascendc-precision-diagnose/SKILL.md:176`）：

- 该行规定 API 查证优先级：`ascendc-api-best-practices` → `ascendc-dev-knowledge`
  INDEX（①精确搜→②模糊搜→**③ 都找不到则 API 不存在，按假设证伪处理——排除该
  修复方向，写进 _summary.validation**），并以「禁止 grep CANN 系统路径
  （$ASCEND_TOOLKIT_HOME、/usr/local/Ascend/）」收尾。
- 结构缺陷两处：
  1. **假闭环**：知识库是精选子集（索引），「子集无记录」≠「系统不存在」——
     把索引缺口当 ground truth 下「不存在」结论并**排除修复方向**，错误把
     §1.3 的知识库当 §1.13 的权威真值源用；
  2. **真值源被禁且无自服回退**：能证伪「不存在」结论的 CANN 安装树被整体
     禁 grep，替代链止于「按假设证伪」——debug 期遇到知识库覆盖缺口时，
     模型唯一合法出路是排除真修复方向 → 定位迟滞（用户证词的机制）。
- 对照：`.claude/rules/ascendc-dev.md:41` 的版本较软——只禁「broadly search」、
  替代链以「Ask user for exact path」收尾（暗示精确路径定向读合法）；硬化出
  假闭环的是 diagnose skill 的转写。硬化的经济性动机（mega 级泛 grep 撑爆
  上下文）本身成立，缺陷在闭环推理与回退缺失，不在「禁广撒网」。
- 波及：所有走 diagnose 的精度调试会话（API 存在性判定错误→修复方向错误排除）。

**状态**：已实施（2026-09-02，用户裁定立项即修，step-114 代码待 commit）。
L3/L4 = `16-fix-diagnose-api-closure.md`（合并文档）。

## P16：静默判死无视阳性网关错误证据——死会话白等满 600s 时长界

**事实**（2026-09-02，ST 运行中现场取证）：

- 死窗口内 opencode 应用日志（本 spawn scratch
  `…/.opencode_home/data/opencode/log/opencode.log`）** POST 后 +14s 即出现
  `level=ERROR message="stream error" error.error="AI_APICallError: Gateway
  Time-out"`**，此后内部每 ~10-15s 一轮 `stream→error` 循环（单次取证 35 轮）；
  但框架看门狗只认「静默时长（turn_stall_s=600）+ db 工具存活探针」，对阳性
  错误证据零消费 → 每次死尝试白等满 600s。
- opencode 会吞掉上游错误、`SessionRetry.policy` 无上限内部重试、POST 永不
  返回（runtime_config :772-774 注释明载）——「服务端已出错」时 POST 不会
  秒回，600s 等待发生在错误**已可查证**之后。
- 实际代价：本次 ST 单用例在坏窗口内 3+ 轮 × 600s + 退避 ≈ 50 分钟无产出
  （17:14→18:00+），每轮判死后 backoff-resume 立即重采样新窗口——判死本身
  是正确动作，晚 10 倍。
- 信号源无 §1.7 顾虑：日志在本 spawn scratch home（per-spawn XDG 隔离），
  step-97 判死前取证已读同目录 db。
- 历史裁决链（runtime_config :782-800）：600→120（P131/batch-20260813，11 次
  stall 全永久）→回调 600（P9/batch-20260821，120 系统性误杀 pangu 无增量
  静默深推理，整算子 exit 65）。

**用户裁定（2026-09-02）**：
1. 阳性错误证据（Gateway Time-out 等）提取出来，立即 trip 提前进入
   backoff-resume 重采样；
2. 残差时长界（无任何证据时的静默兜底）**降为 180s**——误杀风险（pangu
   >180s 无证据静默深推理会触发 P9 形态误杀）已知悉接受，配置面
   `timeouts.opencode_turn_stall_s` 随时可回调；trip 打标 evidence/duration
   两类，后续用真实数据校准。

**状态**：已实施（2026-09-02，step-115 代码待 commit，UT 4052 绿）。L3/L4 =
`17-gateway-evidence-accel.md`。实施补充：构造默认三值统一 180
（opencode 300/sdk 180/config 600 的漂移随裁定收敛，用户质询「全局统一」确认）。
