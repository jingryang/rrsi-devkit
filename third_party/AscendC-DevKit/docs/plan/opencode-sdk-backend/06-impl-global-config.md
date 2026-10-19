# L4 实施方案 — opencode 后端支持用户全局配置

> 层次：L4（改哪个函数 + 顺序 + 验证）。决策见 `05-analysis-global-config.md`（L3）。
> 目标文件：`src/ascendc_devkit/capabilities/agent/opencode_backend.py`
> 测试文件：`tests/ut/capabilities/test_opencode_backend.py`

## 核心改动：serve 用真实 HOME，框架 config 文件落独立 scratch 目录

当前 `_prepare_home_dir` 造空 HOME、且 `OPENCODE_CONFIG` 文件写进该 HOME，掐断了
opencode 对用户全局 config/auth 的原生发现（L1 P-GC1）。改法是**解隔离**：serve 继承
真实 HOME（全局 config 默认回落 + auth 自然可达），但框架 `OPENCODE_CONFIG` 文件**绝
不能**写进用户真实 HOME，故拆两个概念：

- **HOME**：serve 子进程继承的真实 HOME（`os.environ` 原值，不覆盖）。
- **cfg scratch 目录**：框架 `OPENCODE_CONFIG` 文件落盘处（workspace 本地或临时），
  与 run 同生命周期清理。

## 改动清单（TDD：先改测试，再改实现）

### 1. `_prepare_home_dir` → 改名 `_cfg_scratch_dir`（§2.5 删旧通路）
- 语义从「隔离 HOME」变为「框架 config 文件的落盘目录」。
- 目录选择逻辑不变（`<decision_workspace>/.opencode_home` 或 `tempfile.mkdtemp`），
  但**返回值不再用作 HOME**。目录名可保留（无功能影响），docstring 重写：删掉
  「Prevents opencode from reading the operator's global config/auth」——那正是现在
  要恢复的能力；改述为「框架 OPENCODE_CONFIG 文件的落盘目录，独立于用户真实 HOME」。

### 2. `_build_serve_env`：HOME 用真实、cfg 写 scratch、不加 skill 开关
- `env = dict(os.environ)`：保留（proxy/PATH/真实 HOME/XDG 全透传）。
- **删除** `env["HOME"] = home_dir`：不再覆盖 HOME。用户全局 config 靠 opencode 默认
  回落（`$XDG_CONFIG_HOME`/`$HOME/.config`）生效，auth 靠 `$XDG_DATA_HOME`/`$HOME`
  生效。
- `cfg_path = Path(scratch_dir) / "opencode-config.json"`：写 scratch，不写 HOME。
- `env["OPENCODE_CONFIG"] = str(cfg_path)`：不变（框架层恒最高优）。
- 保留 `env.pop("OPENCODE_CONFIG_CONTENT")` / `env.pop("OPENCODE_CONFIG_DIR")`。
- **不新增**任何 `OPENCODE_DISABLE_*`（L3 否决路径 A：会误杀仓内 skill）。
- 密钥 ephemeral env（`_split_provider_secrets`）不变。
- docstring：把「pins an isolated HOME」改述为「继承真实 HOME 以支持用户全局
  config/auth；框架配置写独立 scratch 文件」。

### 3. `spawn` 调用点（约 170 行）
- `scratch_dir = self._cfg_scratch_dir()`；`env = self._build_serve_env(config,
  scratch_dir, project_cfg)`。纯改名，无行为变化。

## 不动的部分
- `_load_project_config` / `_assemble_config` / `_split_provider_secrets` /
  `_validate_project_config` / `_ensure_skills_anchor`：全不动。
- 优先级由 opencode 原生保证：全局 < 项目 opencode.json < 框架 OPENCODE_CONFIG
  （L1 实测），仓内 skill 同名最高优（L3 实测），DevKit 无需额外代码。

## 测试改动（`tests/ut/capabilities/test_opencode_backend.py`）

### 改：`test_build_serve_env_isolates_home_and_writes_config_file`
- 重命名 `test_build_serve_env_keeps_real_home_and_writes_config_to_scratch`。
- `monkeypatch.setenv("HOME", "/real/home")` 钉真实 HOME，断言 `env["HOME"] ==
  "/real/home"`（**不再**等于 scratch）。
- `cfg_path.parent == scratch_dir`（不再 == home）。
- 断言 `"OPENCODE_DISABLE_CLAUDE_CODE_SKILLS" not in env`（钉住「不屏蔽」）。
- proxy 透传 / `OPENCODE_CONFIG_CONTENT not in env` / 密钥 ephemeral：保留。
- 调用签名改 `_build_serve_env(config, scratch_dir, ...)`（形参名随实现改）。

### 其它引用 `_prepare_home_dir` 的用例
- 全局搜 `_prepare_home_dir` 改为 `_cfg_scratch_dir`（含 spawn happy-path 等间接
  经过的用例，确认改名无遗漏）。

## 验证顺序（前台，§3.3）
1. `pytest tests/ut/capabilities/test_opencode_backend.py -v`（UT 全绿）。
2. `pytest tests/ut -q`（回归，确认改名未破坏其它引用）。
3. ST 双后端（§3.9 真实链路守护）：现有
   `tests/st/test_skill_invocation_dual_backend.py` 等 @llm 用例仍绿即证明「解隔离
   HOME 后 opencode 真实链路（skill 注入 / 工具权限 / 子 agent 派发）不回归」。
4. 手动 smoke（可选）：真实 HOME 下放全局 `~/.config/opencode/opencode.json`，
   `opencode debug config` 核对全局字段出现、框架字段最高优、仓内 skill 冲突胜出。

## 与规范对齐
- §2.5 单一通路：改名删旧 `_prepare_home_dir`，不留新旧并存。
- §1.4 不backward-compat：直接改函数名与断言，不留别名。
- §4.2 skill 唯一权威源=仓内扁平树：由 opencode 原生「仓内 skill 冲突最高优」+
  `_ensure_skills_anchor` 锚点共同保证（L3 实测）。
