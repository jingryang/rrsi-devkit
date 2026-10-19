# 06 — 并发 opencode SQLite DB lock 修复实施（G+A，L4）

> 对应 L3 `05-engine-mcp-handshake-hang-analysis.md`（根因坐实：批跑并发 SQLite DB lock；方案：G+A/B 组合）。
> 本 L4 记具体改哪个函数、顺序、验证。B/C 经评估 deferred/保守（见末）。

## 改动 1: G — per-spawn XDG 隔离（主修复，根治）

**文件**：`src/ascendc_devkit/capabilities/agent/opencode_backend.py`
**函数**：`_build_serve_env`（:1135-1167）
**改动**：env dict 加 `XDG_DATA_HOME` + `XDG_CONFIG_HOME` → scratch_dir 子目录（per-spawn 独立 opencode SQLite DB）。

```python
env["OPENCODE_CONFIG"] = str(cfg_path)          # 现有
# G: per-spawn 独立 opencode data/config → 独立 SQLite DB，隔离全局共享 DB（消除并发抢锁）
env["XDG_DATA_HOME"]   = str(Path(scratch_dir) / "data")
env["XDG_CONFIG_HOME"] = str(Path(scratch_dir) / "config")
```

**为什么**：opencode serve 透传真实 HOME → 全局 SQLite DB（`~/.local/share/opencode/opencode.db`，实测 399MB）被 5+ 并发 serve 共享 → `database is locked`（ed4992 serve log 铁证）。framework 已 env 注入 credentials（`OPENCODE_SECRET_*`）+ cwd 锚定 skill（`_ensure_skills_anchor`），**不依赖 opencode global auth** → per-spawn XDG 隔离不断 framework 依赖（P-BC5 的「global-auth invariant」顾虑对批跑不成立）。

**覆盖范围（关键）**：所有 opencode serve（批跑层 5 算子 + 算子内 ForkJoin T1/T2/T3）都走 `_build_serve_env` 统一入口 → **自动覆盖两层并发**（§1.2 可扩展：改在统一入口，同类新情况自动归位）。

**UT**：断言 `_build_serve_env` 设 `XDG_DATA_HOME`/`XDG_CONFIG_HOME` → scratch 子目录；两 spawn 的 XDG 路径独立；不污染 `os.environ`（env 只传子进程）。

## 改动 2: A — engine_mcp_stdio 握手超时（可诊断兜底）

**文件**：`src/ascendc_devkit/capabilities/engine_mcp_stdio.py`
**函数**：`_serve` / `main`（:158-186）
**改动**：首次 readline 设 deadline（`HANDSHAKE_TIMEOUT=30s`，env `ASCENDC_MCP_HANDSHAKE_TIMEOUT` 可调），超时未收到 `initialize` → stderr 报错 + `sys.exit(1)`。

**为什么**：engine_mcp_stdio 对「client 不握手」零防御（silent `readline` 等 1h，违 §1.2 可诊断）。A 让 engine 30s 无 initialize 主动 exit → opencode serve 检测 MCP 子进程 stdio EOF → 报错 → framework 立即看到（不再 silent 等 message_timeout 1h）。即使 G 后，若 opencode 因别因不握 MCP，A 兜底暴露。

**UT**：mock stdin 不发 initialize + monkeypatch 时钟加速 → 断言超时后 stderr 含 `handshake timeout` + exit 1；正常 initialize（30s 内）不被误杀。

## B/C 评估（deferred / 保守，不本次实施）

- **B（keepalive 子进程监控）→ deferred**：A 已让 engine 主动 exit（~30s 暴露）+ G 根治主 hang 源（DB lock）。B（framework 监控 opencode serve 的 engine_mcp_stdio 子进程 CPU/存活）需 /proc PID 跟踪，复杂度高、G+A 后增量有限。G+A 真机验证后若仍有 hang 盲区再补。
- **C（message_timeout 3600→900）→ 保守不改**：G+A 后 message_timeout 作最后硬墙兜底；收敛 900 需评估误伤合法长 design turn（单 message POST）。保留 3600。

## 验证

- **UT（§3.1 TDD）**：G（env XDG 隔离）+ A（握手超时）单测全绿；全量 UT 无回归。
- **ST（heavy_llm，§3.11，用户确认后跑）**：全批 resume（5 算子 × ForkJoin T1/T2/T3）design 阶段，断言：① serve log 无 `database is locked`；② design-generator 持续推进；③ 不再 1h 收口。
- **回归**：单算子 spawn 行为不变（G 只加 XDG env）；正常 design-generator（30s 内完成 MCP 握手）不被 A 误杀。

## 顺序

1. G（`_build_serve_env`）+ UT → 2. A（`engine_mcp_stdio`）+ UT → 3. 全量 UT → 4. 报告（ST heavy_llm 留用户确认）。
