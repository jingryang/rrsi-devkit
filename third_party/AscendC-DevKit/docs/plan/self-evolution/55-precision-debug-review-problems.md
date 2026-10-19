# 55 — precision-debug PR#10 review 问题记录（L1）

> 工作线：self-evolution / precision-debug skill 拆分收口
> 性质：**L1 问题/需求记录** —— 客观事实（哪里坏了、凭什么这么说），不提方案、不排顺序、不写决策。
> 状态：**冻结快照**（2026-07-18，HEAD `22d7877`，分支 `refactor/precision-debug-skill`）。
> 来源：仓外 review `/home/g00940185/PR-10-review.md`（ascendc-devkit-code-reviewer skill 产出）；本文件是其在仓内的产权落地（§1.7 自闭环），每条事实独立可核验。
> 对应 L4：`55-precision-debug-review-fixes-impl.md`。
> 被审对象：`54-precision-debug-skill-split-impl.md`（commit `22d7877` 的 precision-debug skill 拆分）。

## 核实方法

review 的 20 条断言经主 agent 逐行读 `precision_debug_substages.py` + 3 个 subagent 分核 `runner.py`/文档/`batch_runner`+doc54，**全部成立**（m7/m8 为部分成立）。下方每条给出：客观现象 + 凭证（文件:行）+ 影响。结论性判定（成立/部分）属事实快照一部分。

---

## Blocker

### P1 (B1) — 产物路径生成器有副作用，agent 写的文件框架读不到
- **现象**：`_phase_path(state, filename, round_suffix=True)` 不仅算路径，每次调用还读 `control.json`、`phase_counter += 1`、写回盘。
- **凭证**：`src/ascendc_devkit/orchestration/stages/precision_debug_substages.py:113-117`（自增+改盘在路径函数内）。一次 spawn 流程该函数被调 4 次：
  - `actions()` → `_build_prompt`(`:496`) → `_common_context`(`:445`) ：路径 P_a 嵌进 prompt
  - `actions()` → `context=self._common_context`(`:482`) ：路径 P_b 放进 context 字段
  - `transition()` → `_read_agent_summary`(`:533`) ：框架读 P_c
  - `transition()` → `_sync_phase_latest`(`:552`) ：框架读 P_d
  - 四个路径序号各不相同（计数器被自增 4 次）。
- **影响**：agent 只能按 P_a/P_b 写文件，框架去 P_c/P_d 读 → 永远读不到；`_read_agent_summary` 恒空、`_sync_phase_latest` latest 永不更新、diagnose 读 run_tests 的 `last_run_log` 拿到陈旧或空。跨 phase 文件 relay 在 run_tests 环节断。

### P2 (B2) — run_tests 收尾用旧副本覆盖磁盘，抹掉刚写入的 history
- **现象**：`RunTestsSubstage.transition` 加载 control.json 后，调用 `_append_history`（内部重读盘→append→写盘→返回新 dict），但返回值未接收；随后用最初加载的旧副本改 `run_iter_counter` 并写盘，覆盖了刚 append 的 history。
- **凭证**：`substages.py:664`（`cp = _load_control`，旧副本）→ `:687`（`self._append_history(state, summary)`，返回值丢弃；`_append_history` 在 `:528` `return cp`）→ `:689-691`（用旧 cp 改 counter + `_save_control` 覆盖盘）。
- **影响**：每轮 run_tests 的 history 条目「写完即删」。scope_guard 读 `history[0]` 拿不到首轮失败信息，首轮失败归属判定退回靠 `failed_case_queue` 猜。「每次 spawn 保证一条 history」的承诺对 run_tests 失效。

### P3 (F1) — skill 文档对「谁写 history」自相矛盾
- **现象**：run_tests skill 的两份文档对 history 写入权说法相反。
- **凭证**：
  - `.claude/skills/ascendc-precision-run-tests/SKILL.md:57`：「禁止直接修改 control.json.history。框架 `RunTestsSubstage.transition()` 会读 `_summary` 并追加 history 条目」。
  - `.claude/skills/ascendc-precision-run-tests/references/prompts/run_tests.md:238`（强调「直接 append」）+ `:248-259`（给 python3 骨架 `cp["history"].append(entry)`，entry 平铺，`failure_type` 在顶层）。
- **影响**：agent 收到矛盾指令；若按 prompt 走，平铺条目与框架嵌套条目双写进同一 history，schema 混杂。
- **同模式蔓延（F1 扩展，均成立）**：`cp["history"].append(...)` 骨架出现在 5 份 `_shared-protocol.md:37-39`（diagnose/fix/printf/run-tests/scope-guard，byte-identical）+ `diagnose.md:158-160` + `fix.md:178-180` + `printf.md:222,250`。框架侧 4 个主 phase 的 transition 均只读 `_summary`（`substages.py:676/752/837/921`），agent 照 prompt 执行会重复追加。
- **关联事实（框架 entry schema 不自洽）**：框架 `_append_history`(`:520-525`) 写**嵌套** entry（`failure_type` 在 `content` 里），但路由函数 `_get_current_failure_type`(`:256`) 读 `entry.get("failure_type")` 顶层 → 即便 history 没被 P2 抹掉，框架自己写的嵌套条目也读不到 `failure_type`。run 级失败类型路由可能反复退回 case 级。

---

## Major

### P4 (M1) — per-phase schema 加载期校验承诺未实现
- **现象**：doc54 §6 Stage 3 白纸黑字承诺「各子 stage `transition()` 读自己 phase json 时用 `SchemaLoader.load_contract_from_skill(...).parse(raw)` 校验」，代码零落地。
- **凭证**：承诺在 `54-precision-debug-skill-split-impl.md:196`；代码侧 `substages.py` 顶部无 `import SchemaLoader`，`load_contract_from_skill` / `.parse(` 在该文件 0 命中（仅 docstring `:24/401/417` 提及）。`transition()` 只校验了 control.json（`_assert_control_contract` `:665`），读 phase json 只取 `_summary` 子字段。
- **影响**：per-phase json 兼容性无防护；agent 写出字段缺失/错类型的 phase json 不会被框架拦截。性质：**承诺未实现**（非「未承诺」）。

### P5 (M2) — harness 用例形态校验承诺未实现
- **现象**：doc54 §6 Stage 3 承诺「`_build_test_harness` / run-cases 加载 cases 处校验 cases 形态（TensorList 嵌套 shape / numeric attr），旧形态报错」，代码无此校验。
- **凭证**：承诺在 `54-precision-debug-skill-split-impl.md:197`；代码侧 `src/ascendc_devkit/adapters/npu/runner.py:384-426`（`_build_test_harness`）全程无 `raise`，循环仅 `if isinstance(inp, dict)`，非 dict 输入静默跳过、dict 内畸形 shape 原样存入、空集兜底塞默认值。
- **影响**：resume 复用历史脏 harness 不被拦截，畸形 shape 下游 `int(d) for d in shape` 才以 TypeError 炸。性质：**承诺未实现**。

### P6 (M3) — `_json_to_py` 字符串替换改坏用例名
- **现象**：把 JSON 转 Python 字面量用朴素子串替换，会误伤含 `true`/`false`/`null` 子串的字符串。
- **凭证**：`runner.py:440-443` `def _json_to_py(s): return s.replace("true","True").replace("false","False").replace("null","None")`；在 `:485`/`:492` 被调（序列化 test_cases / DTYPE_THRESHOLDS）。
- **影响**：含这些字面量的算子用例数据被静默改坏（如用例名 `"true_div_op"` → `"True_div_op"`），harness 语法没错但数据错，极难调试。

### P7 (M4) — 迭代计数器 agent 和框架各加一次
- **现象**：`run_iter_counter` 有两个写入者。
- **凭证**：run_tests prompt `substages.py:629`（叫 agent `run_iter_counter = iter_n + 1`）+ 框架 `RunTestsSubstage.transition` `:689-690`（自己也加）；fix prompt `:800`、printf prompt `:891` 也叫 agent 加。
- **影响**：init=0 → agent 设 1 → transition 读 1 设 2 → 下轮 agent 设 3 → … `--iter` 值变成 0,2,4,…（跳号）。功能不崩（mkdir exist_ok），但计数语义错误、所有权混乱。

### P8 (F3) — `update-checkpoint.py` 用 exec() 跑外部代码串
- **现象**：脚本用 `exec()` 执行 CLI argv 传入的任意 Python 字符串，与 `_shared-protocol.md` 立的 heredoc 唯一写入通路职责重叠。
- **凭证**：`.claude/skills/ascendc-precision-run-tests/scripts/update-checkpoint.py:33,38`（`updater_src = sys.argv[2]` → `exec(updater_src, {"cp": cp, "json": json})`）。
- **影响**：§2.5 双通路并存；攻击面未扩大（agent 本有 Bash 权限），但诱导 agent「调脚本」而非走 heredoc，两套错叠加。

---

## Minor

### P9 (m1) — `phase_counter`/`run_iter_counter` 未登记
- **凭证**：`substages.py:150-156` `_CONTROL_REQUIRED_KEYS` 无这两字段；`54-*.md §4.2`（`:85-101`）字段表 0 命中。代码里两字段持久化到 control.json（`substages.py:115-116/454/689-690`）。

### P10 (m2) — tee 日志路径两处不一致
- **凭证**：`.claude/agents/ascendc-precision-run-tests.md:39,45`（写/读 `/tmp/run_iter_<N>.log`）vs `SKILL.md:66` + `run_tests.md:42,46,327`（`.precision-fix/run_iter_<N>.log`）。
- **影响**：stale 检测 / 跨 phase 工具按 SKILL.md 去 `.precision-fix/` 找，而 agent 按 agent.md 写到 `/tmp/` → 读不到。

### P11 (m3) — `_skill_dir` 缺 `.resolve()`
- **凭证**：`substages.py:433` `Path(__file__).parent.parent.parent.parent.parent`（无 resolve）vs `src/ascendc_devkit/capabilities/agent/opencode_backend.py:453,647` `Path(__file__).resolve().parents[4]`。两文件同深度、同目标（repo root），写法不一致。
- **影响**：editable/软链安装时 substages 的 `_skill_dir` 可能落在 symlink 链错误位置。

### P12 (m4) — doc54 §5 `_sync_debug_result` 位置漂移
- **凭证**：`54-*.md:146-147`（写在 `precision_debug.py`）vs 实际 `substages.py:342`（模块级函数，class 外）；`precision_debug.py` 全文仅 `:19` 注释提及。

### P13 (m5) — batch_runner `except Exception: continue` 不记日志
- **凭证**：`src/ascendc_devkit/application/batch_runner.py:382-383` profile 自动探测循环内 `except Exception: continue`，无 `_log.warning/exception`。

### P14 (m6) — `_sync_phase_latest` 找不到文件 silent return
- **凭证**：`substages.py:556-561`（`if not round_path.exists(): return` + `except OSError: pass`）。
- **影响**：掩盖了 P1 的数据丢失（round_path 由副作用路径函数算出，P1 下大概率不存在）。

### P15 (m7) — diagnose arch_gaps 空 `[]` 提示缺失（部分成立）
- **凭证**：`schema/precision_diagnose.json:3` `required_keys=["arch_gaps","diagnose_done"]`；`SKILL.md:48` 只说「runtime 路径写」，未提示 precision/compilation 路径需写空 `[]`。**但** `references/prompts/diagnose.md:225` 已明确提示。
- **结论**：SKILL.md 概览缺，phase prompt 有兜底；属信息分散，非完全缺失。

### P16 (m8) — printf schema 未说明 bisect_progress fresh-null（部分成立）
- **凭证**：`schema/precision_printf.json` `required_keys=["tried_bisect_paths"]`，description 提「回 fresh 时归档」但未明说 `bisect_progress` fresh 态可为 null（故不进 required_keys）。**但** `SKILL.md:66` 表格已写「回 fresh 时清空为 null」。
- **结论**：schema 自描述不完整，SKILL.md 有兜底。

### P17 (m9) — scope-guard SKILL 说写 `_summary`，框架不读
- **凭证**：`scope-guard/SKILL.md:49`（「额外写 `_summary`：框架 transition 从此字段生成 history」）vs `substages.py:991-995`（`ScopeGuardSubstage.transition` 直接从 `_extract_debug_checkpoint(cp)` 的 dc 构造 dict 传 `_append_history`，**不**调 `_read_agent_summary`；dc 来自 control.json 的 `scope_*`，`:336-338`）。
- **影响**：scope_verdict.json 的 `_summary` 根本没被读；文字与框架行为不符。

### P18 (m10) — doc54 §10 as-built 空模板
- **凭证**：`54-*.md:246-248`（§10 仅占位说明，无回填的偏差/UT 数/commit）。

### P19 (m11) — 生成的 harness 子进程 import ascendc_devkit
- **凭证**：`runner.py:794`（生成的脚本含 `from ascendc_devkit.adapters.npu.precision_compare import compare_outputs`，FALLBACK 分支），子进程以 `[sys.executable, harness_path]`(`:251`) 执行。
- **影响**：子进程 venv 必须装 `ascendc_devkit` 才能走该分支，加深 harness 对包的硬依赖。

---

## Nit

### P20 (n1) — doc54 命名与代码双向漂移
- **凭证**：`54-*.md:48/140/195` 用 `_assert_checkpoint_contract` + `FrameworkError`；代码 `substages.py:50`（`class PrecisionDebugContractError(RuntimeError)`，消息带 `[PD-CONTRACT]`）+ `:166`（`def _assert_control_contract`）。doc 完全没出现代码侧命名。

---

## 汇总（事实快照）

| P# | review 编号 | 级别 | 结论 | 核心证据 |
|---|---|---|---|---|
| P1 | B1 | blocker | 成立 | substages.py:113-117 + 4 调用点 |
| P2 | B2 | blocker | 成立 | substages.py:664/687/689-691 |
| P3 | F1 | blocker | 成立 | SKILL.md:57 vs run_tests.md:238/248-259 + 5 shared-protocol |
| P4 | M1 | major | 成立（承诺未实现） | doc54:196 vs 代码零调用 |
| P5 | M2 | major | 成立（承诺未实现） | doc54:197 vs runner.py:384-426 |
| P6 | M3 | major | 成立 | runner.py:440-443 |
| P7 | M4 | major | 成立 | substages.py:629/689-690/800/891 |
| P8 | F3 | major | 成立 | update-checkpoint.py:33,38 |
| P9 | m1 | minor | 成立 | substages.py:150-156 + doc54 §4.2 |
| P10 | m2 | minor | 成立 | agent.md:39,45 vs SKILL.md:66 |
| P11 | m3 | minor | 成立 | substages.py:433 vs opencode_backend.py:453 |
| P12 | m4 | minor | 成立 | doc54:146-147 vs substages.py:342 |
| P13 | m5 | minor | 成立 | batch_runner.py:382-383 |
| P14 | m6 | minor | 成立 | substages.py:556-561 |
| P15 | m7 | minor | 部分成立 | SKILL.md:48 缺 / diagnose.md:225 有 |
| P16 | m8 | minor | 部分成立 | schema 缺 / SKILL.md:66 有 |
| P17 | m9 | minor | 成立 | scope-guard SKILL:49 vs substages.py:991-995 |
| P18 | m10 | minor | 成立 | doc54:246-248 |
| P19 | m11 | minor | 成立 | runner.py:794 |
| P20 | n1 | nit | 成立 | doc54:48/140/195 vs substages.py:50/166 |
