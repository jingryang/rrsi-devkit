# L1 问题记录 — opencode 后端不读用户全局配置

> 层次：L1（客观事实 + 证据）。方案取舍见 `05-analysis-global-config.md`（L3），
> 改动配方见 `06-impl-global-config.md`（L4）。

## P-GC1：`OpenCodeBackend` 完全无视用户全局 opencode 配置

### 现象
用户把 provider / 凭证 / 默认 model 写在全局配置
`~/.config/opencode/opencode.json`（opencode 原生全局目录，`opencode debug paths`
的 `config` 项确认 = `$HOME/.config/opencode`）后，经 DevKit spawn 的 opencode
agent **读不到**；只有写进项目 `opencode.json` 才生效。claude(SDK) 后端因跑在主
进程、继承真实 `os.environ`，用户感知上"两者都支持"，opencode 后端则不支持。

### 根因（两处叠加，均在 `src/ascendc_devkit/capabilities/agent/opencode_backend.py`）

1. **强制隔离 HOME —— 掐断 opencode 原生全局发现链**
   `_prepare_home_dir()`（约 567 行）把 serve 子进程 HOME 指向一个**空隔离目录**
   （`<workspace>/.opencode_home` 或临时目录），`_build_serve_env()` 里
   `env["HOME"] = home_dir`。opencode 全局配置发现依赖真实 `$HOME/.config/opencode`，
   HOME 被换空后全局层永远发现不到。

2. **折叠进 `OPENCODE_CONFIG` 的配置只来自项目**
   `_load_project_config()`（约 471 行）只沿 cwd→repo_root 找**项目**
   `opencode.json`，从不读全局。

### 证据（opencode 1.18.3 实测，`opencode debug config`，控制变量、中性 cwd）

| 场景 | model | small_model | 结论 |
|---|---|---|---|
| A 仅全局 | `GLOBAL_MODEL` | `GLOBAL_SMALL` | 全局能被原生读到 |
| B 全局 + `OPENCODE_CONFIG`(只写 model) | `OVERRIDE_MODEL` | `GLOBAL_SMALL` | **逐键 deep-merge，OPENCODE_CONFIG 覆盖同名键，全局其余键保留** |
| C `OPENCODE_CONFIG` + 空 HOME（**当前后端**） | `OVERRIDE_MODEL` | —（丢失） | 隔离 HOME 掐断全局层 = 本 bug |

三层优先级链实测（global + project(cwd) + OPENCODE_CONFIG 各写重叠键）：
`model=P_model`(project 覆盖 global)、`small_model=G_small`(仅 global 有则保留)、
且当框架 `OPENCODE_CONFIG` 也写 model 时由它取胜 → 优先级
**global < project opencode.json < OPENCODE_CONFIG**，与 opencode 官方内置
customize skill 文档一致："Configs from each scope are deep-merged. Project
overrides global."（OPENCODE_CONFIG = 追加的 explicit/local scope，位于最上层）。

deep-merge 是逐键递归实测确认：框架 `OPENCODE_CONFIG` 写 `provider:{}` **不会**
清空全局 provider（全局 `baseURL/apiKey` 存活），写 `permission.skill:"allow"`
成功注入 → **"全局作基座、框架块最高优"在 opencode 原生语义下自动成立**。

### opencode 没有 claude 式"全量走 env"的等价物（回答"能否像 claude 走全局变量"）
opencode provider/凭证只能经**配置文件**或 `opencode auth` 提供，无
`ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN` 式单值 env 覆盖。故"纯走全局 env
变量"不可选；正解是让 opencode 用**真实 HOME** 原生发现全局配置文件。

## P-GC2：隔离 HOME 的原初理由（skill 覆盖风险）实测证伪

隔离 HOME 当初的正当性（`03-headless-env-gotchas.md` §五.5）：防
`~/.claude/skills` 陈旧项经 home-wins **覆盖**项目扁平 skill 树。实测（opencode
1.18.3）该「覆盖」担忧不成立：

- **三方同名冲突仓内胜出**：真实 HOME、cwd 在 repo 外经锚点，仓内 `.claude/skills`
  vs 用户 `~/.claude/skills` vs opencode 原生 `~/.config/opencode/skills` 同名
  `shared-skill` → **仓内版赢**（description=REPO_WINS），去重后唯一。故「陈旧
  home 版覆盖工程树」不发生。
- 泄漏只是**额外**出现 home-only skill（多几个可选项），不覆盖工程权威 skill。

因此隔离 HOME 对 skill 的防护是针对一个不存在的风险，可安全移除。移除后用户全局
config/auth 恢复可达（P-GC1 修复），仓内 skill 最高优先由 opencode 原生冲突消解
保证（无需任何 `OPENCODE_DISABLE_*` 开关）。

### 反例定界：`OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1` 不可用
曾考虑用该 env 挡外部 skill，实测它会**连仓内工程 skill 一起屏蔽**——DevKit 靠
`.claude/skills` 锚点发现工程 skill，此 env 不区分「用户全局」与「工程锚点」两条
`.claude/skills` 通路，一刀切全关（proj-devkit-skill 归 0）。故不采用；详见 L3
否决路径 A。
