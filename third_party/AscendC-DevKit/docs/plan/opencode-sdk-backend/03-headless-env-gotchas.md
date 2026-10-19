# OpenCode 后端 headless 真跑 —— 环境陷阱与排错清单

> **排错必读（出现 opencode 空输出 / 挂住 / status ok 但无文本时，先读本节，勿重新 debug）。**
> 本文件记录相2 探测中**反复踩中**的环境陷阱与其确定性判据。01/02 是冻结的 L3/L4 设计（只读）；本文件是 L4 补充的运维/排错参考，随新发现追加。

## 一、空输出 / status ok 但无文本 —— 两个真根因

opencode 的 `spawn` 返回 `status: ok` 却 `response_len: 0`、transcript 无内容时，**99% 是下面两条之一**，都不是代码 bug：

### 根因 A：baseURL 缺 `/v1`（最常复发）
- opencode 走 `@ai-sdk/anthropic`，POST 到 **`${baseURL}/messages`**（ai-sdk 约定 baseURL 已含版本段）。
- claude 官方 SDK 相反：base_url 不含 `/v1`，SDK 自己拼 `/v1/messages`。
- 所以**同一个网关，两个后端的 baseURL 字面量不同**：
  - claude（`.claude/settings.json`）：`ANTHROPIC_BASE_URL=http://1.95.37.146:3000`（**无** /v1）
  - opencode（`opencode.json`）：`provider.anthropic.options.baseURL=http://1.95.37.146:3000/v1`（**必须** /v1）
- **实测判据**（经代理 curl 该网关）：
  | 端点 | 结果 |
  |---|---|
  | `POST …:3000/v1/messages` | **HTTP 200** + 真实 completion（`{"content":[{"type":"text","text":"PONG"}]…}`） |
  | `POST …:3000/messages` | HTTP 200 + **admin dashboard HTML**（"New API"），ai-sdk 解析成空流 |
- **失败签名**：serve 日志 `stream providerID=anthropic …` → `llm runtime selected ai-sdk` → 紧接 `exiting loop`，`finish=unknown`、`tokens.output=0`、耗时~1s、**无任何 HTTP error 冒出**（静默）。加 `/v1` 后：`finish=stop`、`output=3`、text=`PONG`。

### 根因 B：企业 HTTP 代理没透传
- 网关 `1.95.37.146:3000` **只能经代理到达**：`http_proxy=http://…@10.224.201.29:8080`；直连超时（curl `--noproxy '*'` → code 000, 30s timeout）。
- Node/Bun fetch **确实读 `http_proxy`**（证据：opencode 抓 `https://models.dev/api.json` 报 `self signed certificate in certificate chain` = 代理 TLS MITM，说明请求走了代理）。
- 所以 headless 起 serve 时**必须透传** `http_proxy/https_proxy/no_proxy`（含大写）。`env -i` 一刀切剥掉 → opencode 连不上 → hang / "Unable to connect" / socket closed。
- `no_proxy` 含 `localhost,127.0.0.1` 但**不含**网关 IP —— serve 自身 127.0.0.1 直连、上游 gateway 经代理，二者并存无冲突。

## 二、其它已知非致命噪声（别当 bug 追）
- `Failed to fetch models.dev … self signed certificate` —— models.dev 是模型能力目录，代理 MITM 导致取不到；**非致命**，不影响生成。忽略。
- `OPENCODE_SERVER_PASSWORD is not set; server is unsecured` —— headless 本地回环，无害。

## 三、配置生效优先级（决定"改哪个文件"）
- opencode **原生发现** cwd→git-root 的 `opencode.json`，它**覆盖**我们经 `OPENCODE_CONFIG` 注入的组装配置。
  - 实测：只改注入配置（在 `_assemble_config` 里加 /v1）**无效**，被 on-disk `opencode.json` 覆盖；改 on-disk 文件才生效。
  - 结论：**`opencode.json`（工程目录）是权威配置源**（符合「配置在当前工程目录、跟 claude 类似」的指示）；注入配置只兜 cwd 在 repo 外的场景。
  - 二者都从同一个 `opencode.json` 读取 provider，所以 **/v1 只需在 `opencode.json` 写一次**，两条路都继承。

## 四、128KB E2BIG（config 投递方式，已修）
- `opencode serve` 的配置**不能**走 `OPENCODE_CONFIG_CONTENT` 内联 env：19 个 D3 agent 投影组装后 ~234KB，超过 Linux 单个 env 串 `MAX_ARG_STRLEN=128KB` → execve `[Errno 7] Argument list too long`。
- 修复：写文件 + `OPENCODE_CONFIG=<path>`；provider 密钥经 `{env:VAR}` 占位 + ephemeral serve env 传，不落注入文件。

## 五、headless 启动必备 5 条（速查）
1. 透传 `http_proxy/https_proxy/no_proxy`（+大写）—— 最关键，别 `env -i`。
2. `opencode.json` 的 anthropic baseURL 必须带 `/v1`。
3. `rg` 放 PATH（否则 opencode 去 `$HOME/.cache` 下载 ripgrep，此环境被墙；且 /tmp noexec）。
4. `permission.skill={"*":"allow"}`（`*:deny` 会整颗 drop skill 工具，系统提示不出 `<available_skills>`）。
5. 隔离干净 HOME（避免 `~/.claude/skills` 陈旧项经 home-wins 覆盖项目扁平树）。
6. **cwd 在 repo 外时，须在 `<cwd>/.claude/skills` 植软链锚点**（指向 repo 扁平树）。原设想「opencode 原生沿 cwd→git-root 发现，无需锚点」**只在 cwd 在 repo 内成立**；spawn 的 working_dir 是 repo 外临时工作目录时，opencode 只看到内置 `customize-opencode`，D2 steer 的 `skill({name})` 报「技能不存在」。修复 = 复用 claude 侧同一 `_ensure_skills_anchor(effective_cwd)`（§2.5 单一 skill 通路）。2026-07-16 Spike-1 双后端真跑捕获。

## 六、代码侧防复发
- `OpenCodeBackend` 加载 `opencode.json` 时**加载期校验**（§1.3）：anthropic baseURL 存在且不以 `/v1` 结尾 → 抛 `ConfigError`，把「静默空流」变成「启动即报错并指明修法」，不再靠人肉 debug 复现。

## 七、2.4 双后端验证进度（真跑结论，随 spike 追加）
- **Spike-1（D2 skill 注入）双后端 PASS**（2026-07-16）：`tests/st/test_skill_invocation_dual_backend.py`，claude + opencode 各真跑，transcript 出现 SKILL.md 独有术语（枚举验证法/loopTimes/tailRows/负载均衡）。真跑中捕获并修复「cwd 在 repo 外时 opencode 缺 skill 锚点」（见 §五.6）。
- **Spike-3（工具权限 edit allow）双后端 PASS**（2026-07-16）：`tests/st/test_tool_permission_dual_backend.py`，claude + opencode 各真跑，agent 经真实运行时产出文件产物（`permission_probe.txt`）。证明各后端组装的 `permission` 块**确被运行时消费**、文件产出能力端到端成立（codegen 流水线的地基）。**deny 侧**（`question`/manifest-disallowed → `deny`）由 UT 确定性钉住（opencode `deny` 立即拒绝、非 `ask` 阻塞，但要触发 deny 须强制模型选工具、不确定性高，故 deny 走 UT、edit-allow 走真跑——§3.7 诚实定界）。
- **共享 ST 助手**：`tests/st/_dual_backend.py`（非测试模块）单源承载双后端 env 前置（settings env 折叠 / anthropic 探活 / rg on PATH / factory 建后端），Spike-1/Spike-3 共用（§2.5 单一通路）。
- **heavy_llm 全量回归批次 PASS（2026-07-16）**：`pytest -m "heavy_llm"`，10 用例全绿，耗时 29:38（anchor_hwparams / design_docgen / design×3 / session_resume×3 / smoke codegen 全流水线 / testdesign）。**覆盖边界诚实定界**：这 10 个用例**全部**经 `SDKBackend`（claude 侧）直接构造、不走 factory 默认，故它们验证的是「claude SDKBackend 端到端在相1/相2 重构（扁平 skill + 默认翻 opencode + D2 注入下沉）后仍绿」+「claude 切到 GLM 模型后真实链路成立」——**不**经 OpenCodeBackend。opencode 侧的真实链路由 Spike-1/3（@llm，默认范围）守护。本次跑前两后端已统一为 GLM（消除 model parity 变量）。
- **Spike-2（D3 子 agent 派发）双后端 PASS（2026-07-16）**：`tests/st/test_subagent_dispatch_dual_backend.py`（@llm+@heavy_llm），claude + opencode 各真跑 `ascendc-precision-debugger`（唯一带 Agent/Task 的 primary）派发 `ascendc-precision-run-tests`。两侧均走**强证据路径**——经真实传输派发后子 agent 写出标记文件 `dispatch_probe.txt`=DISPATCH_OK、status=ok、无 not-found 错误（持久目录实证复跑捕获：claude turn3 `tool:Agent`→turn4 `tool:Write`；opencode 经 serve session 解析投影子 agent 执行）。证明 D3 投影/注册的子 agent **确实可解析、可调用**（config 层 UT 之外补上 live 守护，§3.9）。设计吸收 LLM 非确定性（§3.10）：3 次有界重试，命中标记文件即早 break，断言「派发解析（无 not-found）」这一确定性机制而非赌模型服从。precheck 同步验过 NPU/CANN 可达。

