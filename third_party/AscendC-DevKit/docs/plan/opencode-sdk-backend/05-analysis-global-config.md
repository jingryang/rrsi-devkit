# L3 方案分析 — opencode 后端支持用户全局配置

> 层次：L3（选项 + 取舍 + 决策）。问题事实见 `04-problems-global-config.md`（L1）。
> 改动配方见 `06-impl-global-config.md`（L4）。
> **决策演进已收敛**：本文只保留最终定案 + 关键否决依据；中间几版（env 屏蔽 /
> XDG 定向）已被后续实测推翻，作为「否决路径」留档以免重蹈。

## 最终决策（用户拍板）
按优先级排序的两条硬要求：
1. **全局配置优先**：所有符合 opencode 标准的全局配置方式都要支持——既包括写在
   `~/.config/opencode/opencode.json` 的 provider/key/model，也包括 `opencode auth`
   登录态（`~/.local/share/opencode/auth.json`）。
2. **仓内 skill 最高优先**：允许其他目录的 skill 被发现，但当前代码仓
   `.claude/skills` 的 skill 同名时必须胜出。

## 定案：serve 子进程用真实 HOME，不隔离，不加任何 skill 开关
- serve 继承主进程真实 `HOME`（及 `os.environ` 里的 `XDG_*`，若用户设了）。
- opencode 靠默认规则（`$XDG_CONFIG_HOME` 或 `$HOME/.config`）发现全局 config，靠
  `$XDG_DATA_HOME` 或 `$HOME/.local/share` 读 auth——两者自然生效，DevKit 不经手合并。
- 框架 D1–D4 块仍写独立的 `OPENCODE_CONFIG` 文件（落 scratch 目录，不落用户 HOME），
  优先级链 `全局 < 项目 opencode.json < OPENCODE_CONFIG`，headless 不变式恒最高优。
- **不加** `OPENCODE_DISABLE_*` 任何 skill 屏蔽。

## 为什么这样满足两条硬要求（四把尺子）
- **可维护**：删掉「空 HOME」这个反直觉隔离，配置/auth 来源与用户直跑 opencode 收敛为
  同一套，`opencode debug config` 可直接复现；改动仅一处（不覆盖 HOME）。
- **可扩展**：用户全局任意标准配置方式（文件 / auth / 未来新字段）自动生效，无需逐项
  加白名单或维护 XDG 定向表。
- **可诊断**：全局是否被读到、最终合并结果、skill 冲突赢家均可 `opencode debug
  config` / `opencode debug skill` 一键核对。
- **架构合理**：把「配置发现 + 合并 + skill 冲突消解」这些职责全部留在 opencode
  原生能力里，DevKit 只注入框架不变式（OPENCODE_CONFIG）+ 锚定仓内 skill 树
  （`_ensure_skills_anchor`），不越层复刻 opencode 的任何机制。

## 关键实测依据（opencode 1.18.3，全部控制变量真跑）
1. **仓内 skill 最高优先——天然成立**：真实 HOME、cwd 在 repo 外经锚点，三方同名
   skill（仓内 `.claude/skills` / 用户 `~/.claude/skills` / opencode 原生
   `~/.config/opencode/skills`）冲突 → **仓内版胜出**（description=REPO_WINS），
   去重后唯一。故硬要求 2 不需要额外代码保证。
2. **全局 config 默认回落**：`XDG_CONFIG_HOME` unset + 真实 HOME → opencode 自动读
   `$HOME/.config/opencode/opencode.json`（实测 GLOBAL_OK）。
3. **auth 跟 XDG_DATA_HOME / $HOME**：auth.json 在 `<XDG_DATA_HOME|$HOME/.local/share>/
   opencode/auth.json`（`auth list` 实测确认）。故真实 HOME 才能读到登录态。
4. **框架块恒最高优**：`OPENCODE_CONFIG` 写 model=FW，全局写 model=G → FW 胜；
   框架写 `provider:{}` 不清空全局 provider（deep-merge 逐键递归）。headless 不变式安全。

## 否决路径（留档防复发）
- **否决 A：真实 HOME + `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1`**。实测该 env 会连
  **仓内工程 skill 一起屏蔽**——DevKit 靠 `.claude/skills` 锚点发现工程 skill，此 env
  不区分「用户全局」与「工程锚点」两条 `.claude/skills` 通路，一刀切全关（proj skill
  归 0）。致命，出局。
- **否决 B：隔离 HOME + `XDG_CONFIG_HOME` 指真实 `~/.config`**。能放行 config，但
  ①opencode 原生全局 skill（`<XDG_CONFIG_HOME>/opencode/skills`）与 config 绑死在同一
  XDG 变量，会连带进来；②auth 跟 `XDG_DATA_HOME`/`$HOME`，隔离 HOME 下 `opencode auth`
  登录态读不到——违反硬要求 1。出局。
- **否决 C：Python 读全局手工 merge 进 OPENCODE_CONFIG**。需复刻 opencode 逐键
  deep-merge（provider/mcp/permission 嵌套语义），易随 opencode 版本漂移，且覆盖不到
  auth/references/plugin 等。可维护 & 可扩展均劣。出局。

## 与 SDKBackend 对齐的诚实定界
- SDKBackend（claude agent SDK）`setting_sources=["project","local"]` 不含 `user`，
  故它**不发现** `~/.claude/skills`（官方 `docs/agent-sdk-ref/skills.md:96`）。严格
  「完全一致」本应也不纳入 user skill。
- 但用户按业务优先级显式放宽为「全局配置优先，仓内 skill 最高优即可」——两后端在
  「用户全局 skill 是否可被发现」上因此**不强求逐项一致**；一致性由「仓内 skill 最高
  优先」这条更强的不变式承载（§4.2 skill 唯一权威源是仓内扁平树）。此定界是有意的、
  经用户确认的取舍，非疏漏。

## 保留不动的既有不变式
- `OPENCODE_CONFIG` 文件承载 D1–D4 + provider 密钥 `{env:VAR}` 占位（密钥仍不落盘、
  走 ephemeral serve env）。
- `_validate_project_config` 的 baseURL `/v1` 加载期校验（项目侧）。
- skill 锚点 `_ensure_skills_anchor`（仓内扁平树 project-wins）。
