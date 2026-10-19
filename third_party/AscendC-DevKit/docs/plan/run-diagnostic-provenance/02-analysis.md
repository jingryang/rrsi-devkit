# Run 诊断可观测性 — 方案分析（L3）

> 冻结日期：2026-07-19。
> 用户拍板：① 一次性做完整批次（MVP + skill 指纹 + driver/soc 补全 + MANIFEST + verify/pack CLI + 运行时配置 + 截断检测）；② `repo_baseline_ref` → `target_repo_baseline_ref` 直接改名，不留兼容（§1.4）。

## 总目标

把「他人拿 output 日志来分析」从「信息不足、靠猜」变成「一份自描述、可校验的 run 包」：版本出处坐实、session 可定位可校验、运行时配置与截断诚实记录。

## 方案 A：Run Provenance（覆盖 P1）

**决策**：run 启动时一次性写 `<run>/PROVENANCE.json`（不可变），并向 `events.jsonl` 首行 append `run_started` 事件（带 provenance 摘要）——双写，因 `events.jsonl` 是权威。

字段分层：
- **DevKit 自身**：`git_commit`/`git_branch`/`git_describe`/`git_dirty`/`dirty_file_count`（`git -C` 本仓，自闭环 §1.7）+ `devkit_version`。
- **编排栈**：`agent_backend`(claude/opencode)、`backend_sdk_version`、`orchestration_config_hash`、`skill_manifest_fingerprint`、`agent_manifest_fingerprint`（批次 4）。
- **运行环境**：复用 `RunContext`（cann/python/torch_npu/compiler/detected_chip）+ 激活 `driver_version` + `soc_version` 字面量 + `npu_device_count` + `hostname`（批次 4）。
- **目标仓**：`target_repo_baseline_ref`（即原 `repo_baseline_ref` 改名澄清，与 DevKit 自身 git 明确区分）。

单一翻译点 `infra/provenance.py` 的 `build_provenance()`（呼应 `domain/chip.py` 的单一翻译点哲学）。取不到的字段明示 `null` + reason，绝不静默。

**选项与取舍**：
- 挂载点：新建 `run_started` 事件 vs 复用 `chip_decision`。**选新建**——`chip_decision` 语义是芯片解析，混入污染；`run_started` 是 run 级首事件，天然挂出处。复用 `event.make_event` 模式。
- 命名：`repo_baseline_ref` → `target_repo_baseline_ref`。§1.4 不留兼容，State 声明 + `from_snapshot` 注册表 + dispatcher 4 处消费点同步改。

## 方案 B：Session 可定位 + 完整性校验（覆盖 P2）

**决策**：三件齐下——
- **B1 可定位**：`spawn_context` 加 `transcript` + `session_id` 字段；run 收尾写 `agents/index.json`（file↔action↔session 映射 + record_count/byte_size/status）。
- **B2 可获取 + 可校验**：run 收尾写 `MANIFEST.json`（每文件 sha256 + size + role）；CLI 加 `pack-run`（tar 整个 run 含 `agents/` + MANIFEST + **SDK native session 原文**）与 `verify-run`（校验 checksum + 缺失/截断/失败-action session 标红「不可诊断」）。

**native session 纳入打包**（用户决策 2026-07-19）：工程的 `agents/*.jsonl` 是工程自序列化的统一 schema 副本，极端情况下可能不全（实证：step-66 前 opencode 后端每份 transcript 仅落 1 条收尾消息）；SDK 的 native session 存储是最权威的 ground truth。`pack-run` 据 `PROVENANCE.agent_backend` 从 SDK 标准位置捞本次 run 的 session 原文：
- claude → `~/.claude/projects/<encoded-cwd>/*.jsonl`
- opencode → `~/.local/share/opencode/session/*`

筛选键 = events 的 `spawn_context.session_id`（方案 B1 新增）∪ `agents/*.session.json` sidecar 里的 session_id，只纳入本次 run 的 session，不打包无关历史。纳入 tar 的 `native-sessions/` 子目录，MANIFEST 记其 sha256 + 来源绝对路径。best-effort：native 路径不存在 / 文件缺失 → MANIFEST 标 `native_session: missing`，不崩。此读取是**诊断取证**（非运行依赖），不违反 §1.7 自闭环——工程运行仍只认 `<run>/agents/`，native 原文仅供事后分析对照。
- **B3 联动**：`MANIFEST.json` 头部带 provenance 摘要。

**选项与取舍**：
- 失败-action session 缺失 → 从「软问题」升级为「硬约束」（report 标红），落 §1.3 加载期/打包期校验。
- 打包：提供 `pack-run` 命令而非每次自动 tar——体积大，自动 tar 拖慢每次 run；按需打包 + `verify-run` 反向校验是「他人提供日志」场景的正确闭环。

## 方案 C：运行时配置 + 截断检测（覆盖 P3）

**决策**：
- **记配置**：provenance 加 `runtime_config` 段——`opencode.json` 的 `provider.<p>.models.<m>.limit.{context,output}` + `model` + `baseURL`；claude 后端 SDK options（`max_turns`/`model`）。
- **记后果**：`event` 加 `output_truncated` 事件；backend 检测 `stop_reason`/`finish_reason` 为长度类信号（`max_tokens`/`end_turn` 之外）即 append。不光记「设了 8192」，还记「本次被截了 N 次」。
- **加载期告警**（§1.3）：run 启动若检出 `output ≤ 危险阈值`，PROVENANCE/report WARN。

**选项与取舍**：
- 截断信号粒度：per-turn `output_truncated` 事件 vs 仅 run 级汇总。**选 per-turn**——可定位到哪个 agent 哪一轮被截，可诊断性更强。
- 危险值阈值：`output ≤ 8192` 标 WARN（基于用户实证）。阈值常量化在 `provenance.py`，可调。

## 四把尺子（§1.2）

- **可维护**：复用 `Workspace`/`RunContext`/`events.jsonl`/harvest，只加字段 + 加文件，不重构。
- **可扩展**：provenance 是 dataclass，新维度加字段即可；新 skill/agent 自动纳入指纹。
- **可诊断**：`verify-run` + index + 失败-session 标红 + 截断事件，异常路径留信号不静默。
- **架构合理**：provenance 在 infra、事件在 kernel/event、校验在 cli、采集在 backend——各层职责正确。

## 不做的事

- 不改 backend 事件流主干（只加旁路记录）。
- 不自动每次 run 打 tar（按需 `pack-run`）。
- 不为旧 snapshot 留 `repo_baseline_ref` 别名（§1.4）。
