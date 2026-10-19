# 55 — precision-debug PR#10 review 修复（L4 实施方案）

> 工作线：self-evolution / precision-debug skill 拆分收口
> 性质：**L4 实施方案** —— 改哪个文件/函数、什么顺序、怎么验证。
> 状态：**已实施（PR#10 review fixes，2026-07-19）**。N5/N6/N7 完成；F1/M2 由 happy-crafting-stallman.md 计划驱动。
> 前置 L1：`55-precision-debug-review-problems.md`（P1..P20 事实快照，2026-07-18 HEAD `22d7877`）。
> 被修对象：commit `22d7877`（doc54 对应的 precision-debug skill 拆分）。
> 仓外 review：`/home/g00940185/PR-10-review.md`（verdict `reject`）。

## 如何读本文档

- **Part 1（逐条修复）**：与 L1 的 P1..P20 **严格一一对应**，同序号同顺序。每条自包含：根因 → 修复（代码级）→ 影响（对现有设计/流程）→ 验证。拿 L1 的某个 P，直接到 Part 1 同号节看怎么修。
- **Part 2（总体设计）**：把 Part 1 的 20 条收拢成整体视图——总览表、跨问题的决策（D1-D5）、分 Stage 顺序、验证策略、风险边界。想看全局先读 Part 2。

## 目录

- [Part 1 — 逐条修复（P1..P20）](#part-1--逐条修复p1p20)
- [Part 2 — 总体设计](#part-2--总体设计)

---

# Part 1 — 逐条修复（P1..P20）

> 每条与 L1 同号问题一一对应。模板统一：**根因 / 修复 / 影响 / 验证**。涉及跨问题决策时标注「见 Part 2 §决策 D#」。

## P1 (B1·blocker) — 产物路径生成器有副作用，agent 写的文件框架读不到

> 对应 L1 P1。

**根因**：`_phase_path(round_suffix=True)`（`substages.py:97-119`）混合了「纯计算」与「副作用」——`:113-117` 读 `control.json`、`phase_counter+=1`、写回盘。而 `actions()` 里 `_common_context` 被调两次（`_build_prompt:496` 一次、`context=:482` 一次），加上 `transition()` 里 `_read_agent_summary:533` / `_sync_phase_latest:552` 各一次——一次 spawn 共自增 4 次，prompt 嵌的路径 ≠ context 路径 ≠ 框架读的路径。

**修复**（见 Part 2 §决策 D1，推荐 A；**保留 `_p{idx}` 序号**）：
1. `_phase_path`（`:97-119`）改**纯函数**：删 `:114-117` 的读盘+自增+写盘，只读 `phase_counter` 现值；**保留 `_p{idx}` 序号**（理由见下「为何不能去序号」）。
2. 自增点收敛到 `actions()`（`:477-493`）——每次 spawn 自增一次，此后 `_build_prompt`/`_common_context`/transition 的 `_read_agent_summary`/`_sync_phase_latest` 全部读同一值（纯函数）：
   ```python
   def _phase_path(state, filename, round_suffix=False):
       d = _precision_fix_dir(state)
       if d is None:
           return None
       if not round_suffix:
           return d / filename
       r = _current_round(state)
       cp = _load_control(state)                          # 纯读，不自增/不写盘
       idx = int(cp.get("phase_counter", 0))
       stem, ext = filename.rsplit(".", 1) if "." in filename else (filename, "json")
       return d / f"{stem}_r{r:03d}_p{idx:03d}.{ext}"

   def actions(self, state, iteration=1):
       cp = _load_control(state)
       cp["phase_counter"] = int(cp.get("phase_counter", 0)) + 1   # 唯一自增点
       _save_control(state, cp)
       ctx = self._common_context(state)                  # 纯函数读到刚自增的 idx
       return [SpawnAgent(
           agent_name=self.agent_name,
           prompt=self._phase_prompt_from_ctx(ctx, iteration),    # 复用 ctx，不再 _common_context 二次调用
           context=ctx,
           skills=skill_allowlist(self._assigned_skill()),
           primary_skill=self._assigned_skill(),
           working_dir=_operator_dir(state),
           ...,
       )]
   ```
   `_build_prompt`(`:495-501`) 改为 `_phase_prompt_from_ctx(ctx, ...)`，不再自调 `_common_context`（消除第 2 次调用）。
3. transition 的 `_read_agent_summary`(`:533`) / `_sync_phase_latest` 调同一纯函数 → idx 与 actions 时一致（spawn 完成到 transition 之间 `phase_counter` 不再变）。

**为何不能去掉 `_p{idx}` 序号（用户质询点，已核实）**：scoped transition_table（`precision_debug_tree.py:58-71`）里 **fix 自循环**（`fix:{"retry":("fix",…),"skip_more":("fix",…)}`）与 **printf_location 自循环**（`printf_location:{"continue":("printf_location",…)}`）会让**同一 round 内同一 phase 被 spawn 多次**；框架重试同一 phase 同理。`_phase_path` docstring（`:100-103/110-112`）即说明序号为此而设。若只留 `_r{round}`，fix retry 第二次会**覆盖**第一次的 `precision_fix_r{round}.json`，归档丢失。**结论：序号保留，只把自增从「每次调用」收敛到「每次 spawn 一次」。**

**影响**：归档命名**不变**（仍 `_r{round}_p{idx}`）；`phase_counter` 字段**保留**并需登记（见 P9，已修正原「删除」误判）。一次 spawn 内路径从「4 个不同值」收敛为「1 个值」——B1 根除。

**验证**：UT 断言「同一次 spawn：prompt 路径 == context 路径 == transition 读路径」（纯函数一致性）；另断言「同一 round 内 fix 二次 spawn（retry）的归档路径不同、互不覆盖」（序号语义保留）。

---

## P2 (B2·blocker) — run_tests 收尾用旧副本覆盖磁盘，抹掉刚写入的 history

> 对应 L1 P2。

**根因**：`RunTestsSubstage.transition`（`substages.py:663-695`）：`:687` `self._append_history(state, summary)` 返回值丢弃（`_append_history:528` 确有 `return cp`）；`:689-691` 用 `:664` 加载的旧 cp 改 counter 并写盘，覆盖了 `:687` 刚 append 的 history。

**修复**：接收 `_append_history` 返回值，后续基于最新 cp：
```python
cp = _load_control(state)
_assert_control_contract(cp)
# ... queue reset / dc / stale detect 不变 ...
cp = self._append_history(state, summary)        # ★ 接收（含 history append + 已写盘）
iter_n = int(cp.get("run_iter_counter", 0))
cp["run_iter_counter"] = iter_n + 1
_save_control(state, cp)                          # 此时 cp 含 history + 新 counter
self._sync_phase_latest(state)
```

**影响**：history 条目不再被抹掉；`run_iter_counter` 自增逻辑与 P7 协调（见 P7，框架独占）。

**验证**：UT 构造 run_tests transition，断言执行后 `control.json.history` 末尾恰有一条本轮条目。

---

## P3 (F1·blocker) — skill 文档对「谁写 history」自相矛盾 + 框架 entry schema 不自洽

> 对应 L1 P3。

**根因**：(a) 5 份 `_shared-protocol.md:36-43` + `run_tests.md:238,248-259` + `diagnose.md:158-160` + `fix.md:178-180` + `printf.md:222,250` 仍教 agent `cp["history"].append(entry)`（平铺），而 SKILL.md:57 禁止、框架改读 `_summary`。(b) 框架 `_append_history:520-525` 写**嵌套** entry（`failure_type` 在 `content`），但 `_get_current_failure_type:256` 读顶层 `entry.get("failure_type")` —— 即便 history 没被 P2 抹掉，框架自己写的嵌套条目也读不到。

**修复**（见 Part 2 §决策 D5，推荐 A 统一嵌套）：

*文档侧*：
1. 5 份 `_shared-protocol.md`：删 `cp["history"].append(entry)` 骨架，改「history 由框架 transition 从你的 `_summary` 物化（含 timestamp/round/phase 框架控制字段），你**禁止**直接 append/修改 history。把本轮摘要写进 `precision_<phase>.json._summary`」。
2. 4 个 phase prompt（run_tests/diagnose/fix/printf）：删 append 骨架，字段改写入 `_summary`（run_tests 的 `_summary` 字段 SKILL.md:649-653 已定义，prompt 对齐即可）。
3. `run_tests/SKILL.md:57` 保持（它是权威）。

*框架侧（entry schema 统一嵌套）*：
4. `_get_current_failure_type`（`:253-259`）改读嵌套：
   ```python
   def _get_current_failure_type(cp):
       for entry in reversed(cp.get("history", []) or []):
           content = entry.get("content") or {}
           ft = content.get("failure_type")
           if ft:
               return ft
       return None
   ```
5. **连带（scope_guard 读取适配）**：scope_guard agent 的 prompt（`substages.py:963-975`）教它读 history 的 `failure_type`/`test_result`。统一嵌套后这些值移到 `content` 下。scope_guard 是 AI 判定，读 JSON 能自适应嵌套，但 prompt 措辞同步更新（指明 failure_type 在 `history[].content`），免得 agent 困惑。

**影响**：history 写入权归框架（agent 只写 `_summary`）；entry schema 统一为嵌套，所有硬编码消费者（`_get_current_failure_type`）配套改。scope_guard entry（content 只有 `scope_*`，无 `failure_type`）被路由函数自然跳过——符合语义。

**验证**：UT 断言 `_get_current_failure_type` 对嵌套 entry 取值、对 scope_guard entry 跳过；skill 自包含校验脚本扫 5 份 shared-protocol + 4 prompt 无 `history` 的 append 字样。

---

## P4 (M1·major) — per-phase schema 加载期校验承诺未实现

> 对应 L1 P4。

**根因**：doc54 §6:196 承诺「各子 stage `transition()` 读 phase json 时用 `SchemaLoader.load_contract_from_skill(...).parse(raw)` 校验」，`substages.py` 零调用（连 import 都没有）。

**修复**（见 Part 2 §决策 D2，推荐 A 落实）：基类 `_PrecisionDebugSubstage` 加方法：
```python
def _validate_phase_json(self, state):
    from ascendc_devkit.adapters.schema.loader import SchemaLoader
    p = _phase_path(state, self._phase_filename(), round_suffix=False)
    if p is None or not p.exists():
        return
    raw = json.loads(p.read_text(encoding="utf-8"))
    contract = SchemaLoader.load_contract_from_skill(
        self._assigned_skill(), self._schema_files[0])
    try:
        contract.parse(raw)
    except ContractError as e:
        raise PrecisionDebugContractError(f"[PD-CONTRACT] phase json invalid: {e}")
```
5 个 transition（run_tests/diagnose/fix/printf/scope_guard）在读 `_summary` 前调 `self._validate_phase_json(state)`。错误包装为 `PrecisionDebugContractError`（`[PD-CONTRACT]`）走 non-fixable halt（与 `_assert_control_contract` 同路径）。

**影响**：脏 phase json 从静默变 halt（兑现 §1.3 承诺）。`SchemaLoader.load_contract_from_skill` 签名以 `adapters/schema/loader.py` 实际为准（实施时核对）。

**验证**：UT 覆盖 5 schema × {缺 required_key / 错类型 / 合法} 三态。

> 若选 D2=B（撤回）：删 docstring 的 SchemaLoader 提述（`:24/401/417`）+ doc54 §6 删 `:196` + §10 记撤回理由。不推荐。

---

## P5 (M2·major) — harness 用例形态校验承诺未实现

> 对应 L1 P5。

**根因**：doc54 §6:197 承诺 `_build_test_harness` 校验 cases 形态（TensorList 嵌套 shape / numeric attr）+ 旧形态报错；`runner.py:384-426` 全程无 `raise`，仅 `isinstance(inp, dict)`，畸形静默塞默认值。

**修复**（见 Part 2 §决策 D2，推荐 A 落实）：`_build_test_harness` 序列化循环前加形态校验门：
```python
def _validate_case_form(tc, idx):
    if not isinstance(tc.inputs, (list, tuple)):
        raise PrecisionDebugContractError(
            f"[PD-CONTRACT] test_cases[{idx}].inputs must be list (stale harness)")
    for j, inp in enumerate(tc.inputs):
        if not isinstance(inp, dict):
            raise PrecisionDebugContractError(
                f"[PD-CONTRACT] test_cases[{idx}].inputs[{j}] must be dict")
        shape = inp.get("shape")
        if not isinstance(shape, (list, tuple)) or not all(
                isinstance(d, int) for d in shape):
            raise PrecisionDebugContractError(
                f"[PD-CONTRACT] test_cases[{idx}].inputs[{j}].shape must be list[int]")
        # numeric attr 校验同理
```
（错误类型若 runner 不便依赖 substages，定义独立 `HarnessContractError` 并由 caller 转 `[PD-CONTRACT]` 分类。）

**影响**：resume 复用旧形态 harness 从静默塞默认值变 halt（挡脏数据）；新 harness 由本函数生成、形态正确，不受影响。

**验证**：UT 构造旧形态 harness（inputs 非 list / shape 含 None），断言 raise。

---

## P6 (M3·major) — `_json_to_py` 字符串替换改坏用例名

> 对应 L1 P6。

**根因**：`runner.py:440-443` `s.replace("true","True").replace("false","False").replace("null","None")` 子串匹配误伤含这些子串的字符串。

**修复**：改正规序列化：
```python
def _json_to_py(obj):
    """Serialize a JSON-native structure as a valid Python literal.
    Never substring-replace (would corrupt names like 'true_div_op')."""
    import pprint
    return pprint.pformat(obj, width=120, sort_dicts=False)
```
调用点 `:485`/`:492` 从 `_json_to_py(_json.dumps(serial_cases))` 改为 `_json_to_py(serial_cases)`（直接传对象）。

**影响**：输入输出语义不变（仍 dict→Python 字面量），正常用例零影响，含 true/false/null 子串的从"改坏"变"正确"。

**验证**：UT 含用例名 `"true_div_op"` / 属性 `"construct_via_true_mode"` / 键 `"nullability"`，断言字面量原样保留、`ast.literal_eval` 往返一致。

---

## P7 (M4·major) — 迭代计数器 agent 和框架各加一次

> 对应 L1 P7。

**根因**：run_tests prompt `:629` + fix prompt `:800` + printf prompt `:891` 叫 agent 加 `run_iter_counter`；transition `:689-690` 框架也加 → 跳号。

**修复**（见 Part 2 §决策 D4，推荐 A 框架独占）：
1. 删 prompt 三处 agent 自增指令（`:629/800/891`）。
2. 保留 transition `:689-690`（P2 修复后已正确，是唯一写入者）。
3. prompt 的 `iter_n` 注释改为「只读使用，框架 transition 负责自增」。

**影响**：`run_iter_counter` 单 owner（框架）；`--iter` 值从 0,2,4,… 跳号变 0,1,2,… 单调。agent 不再写路由控制字段（符合 doc54 §4「FW owns routing-control」）。

**验证**：UT 模拟多轮 run_tests→fix→run_tests，断言 `run_iter_counter` 单调 +1；prompt 文本 grep 无自增指令。

---

## P8 (F3·major) — `update-checkpoint.py` 用 exec() 跑外部代码串

> 对应 L1 P8。

**根因**：`update-checkpoint.py:38` `exec(updater_src, ...)`，`updater_src` 来自 `sys.argv[2]`（任意 Python 串），与 `_shared-protocol.md` heredoc 通路职责重叠。

**修复**（见 Part 2 §决策 D3，推荐 B 保留脚本改子命令）：
```python
# update-checkpoint.py <control.json> set-case-failure-type <case_id> <failure_type>
#                      <control.json> set-case-status <case_id> <status>
def main():
    cp_path, action, *rest = sys.argv[1], sys.argv[2], sys.argv[3:]
    cp = _load(cp_path)
    if action == "set-case-failure-type":
        _set_case_field(cp, rest[0], "failure_type", rest[1])
    elif action == "set-case-status":
        _set_case_field(cp, rest[0], "status", rest[1])
    else:
        print(f"unknown action: {action}", file=sys.stderr); sys.exit(2)
    _save(cp_path, cp)
```
配套 SKILL/agent 文档职责分工：「per-case 分类/状态用 `update-checkpoint.py` 子命令；其他通用 control.json 变更用 heredoc」。

**影响**：消除 exec 安全隐患 + 双通路；agent 调用方式从 `-c '<code>'` 变子命令。run_tests agent.md Step 3 同步改。

> 若选 D3=A（删脚本）：删 update-checkpoint.py，agent.md Step 3 改 heredoc 直接 patch `failed_case_queue[idx].failure_type`。

**验证**：UT 子命令正确改字段；确认无 `exec(` 残留。

---

## P9 (m1·minor) — `phase_counter`/`run_iter_counter` 未登记

> 对应 L1 P9。

**根因**：两字段持久化到 control.json（`:115-116/689-690`），但 `_CONTROL_REQUIRED_KEYS:150-156` 无、doc54 §4.2 无。

**修复**：
- `phase_counter` 进 `_CONTROL_REQUIRED_KEYS`；doc54 §4.2 字段表登记（owner=FW，每次 spawn 自增；P1/D1=A 修复后唯一自增点在 `actions()`）；`init-checkpoint.py` 写初值 0。
- `run_iter_counter` 进 `_CONTROL_REQUIRED_KEYS`；doc54 §4.2 登记；`init-checkpoint.py` 写初值 0。

**影响**：resume 复用缺这两字段的旧 control.json 会 halt（预期）。

> 注：P1（D1=A）**保留** `phase_counter`（初稿误判为「删除」，已修正——序号承载「同 round 内同 phase 多次 spawn 独立归档」语义，见 P1「为何不能去序号」）。

**验证**：UT 构造缺字段 control.json，断言 `_assert_control_contract` raise。

---

## P10 (m2·minor) — tee 日志路径两处不一致

> 对应 L1 P10。

**根因**：`agent.md:39,45` 用 `/tmp/run_iter_<N>.log`，SKILL.md:66 / run_tests.md 用 `.precision-fix/run_iter_<N>.log`。

**修复**：`.claude/agents/ascendc-precision-run-tests.md:39,45` 路径 `/tmp/...` → `.precision-fix/run_iter_<N>.log`（统一到 SKILL.md 约定）。

**影响**：日志落点从 `/tmp` 变 `.precision-fix/`（往正确方向）；stale 检测/跨 phase 工具能读到。

**验证**：文档 grep 无 `/tmp/run_iter`。

---

## P11 (m3·minor) — `_skill_dir` 缺 `.resolve()`

> 对应 L1 P11。

**根因**：`substages.py:433` `Path(__file__).parent×5` 无 resolve；`opencode_backend.py:453,647` 用 `.resolve().parents[4]`。

**修复**：`substages.py:433` → `project_root = Path(__file__).resolve().parents[4]`。

**影响**：非软链下结果一致；软链下从"错位置"变"对位置"。

**验证**：软链安装场景下 `_skill_dir` 指向真实 repo。

---

## P12 (m4·minor) — doc54 §5 `_sync_debug_result` 位置漂移

> 对应 L1 P12。

**根因**：doc54 §5 `:146-147` 写 `precision_debug.py`，实际在 `substages.py:342`。

**修复**：doc54 §5 改动点 `precision_debug.py` → `precision_debug_substages.py`。

**影响**：纯文档对齐。

**验证**：doc54 §5 指向与代码定义位置一致。

---

## P13 (m5·minor) — batch_runner `except Exception: continue` 不记日志

> 对应 L1 P13。

**根因**：`batch_runner.py:382-383` 裸 except + continue 无日志。

**修复**：
```python
except Exception as exc:
    _log.warning("auto-detect profile=%s failed: %s", _pn, exc, exc_info=True)
    continue
```

**影响**：控制流不变（仍 continue），坏配置从静默变留痕。

**验证**：构造坏 profile，断言 warning 输出。

---

## P14 (m6·minor) — `_sync_phase_latest` 找不到文件 silent return

> 对应 L1 P14。

**根因**：`substages.py:556-561` 缺文件 silent return + OSError silent pass。

**修复**：缺文件 / OSError 改 `Logger.warn("[PD-RELAY] %s round file missing — phase json not synced", ...)`。

**影响**：P1 修复后此情况不应再发生；warn 用于兜底暴露残留问题。

**验证**：构造缺失场景，断言 warn 输出。

---

## P15 (m7·minor) — diagnose arch_gaps 空 `[]` 提示缺失（部分成立）

> 对应 L1 P15。

**根因**：`diagnose/SKILL.md:48` 未提示非 runtime 路径需写空 `[]`（`diagnose.md:225` 有，但 SKILL 概览缺）。

**修复**：`diagnose/SKILL.md:48` 加一句「非 runtime 路径（precision/compilation）须写空 `[]`（required_key，详见 diagnose.md:225）」。

**影响**：纯文档补充。

**验证**：SKILL.md 含空 `[]` 提示。

---

## P16 (m8·minor) — printf schema 未说明 bisect_progress fresh-null（部分成立）

> 对应 L1 P16。

**根因**：`printf/schema/precision_printf.json` description 提「回 fresh 时归档」但未明说 fresh 态可为 null（SKILL.md:66 有）。

**修复**：schema description 加「`bisect_progress` 在 fresh 态为 `null`（故不进 required_keys；见 SKILL.md:66）」。

**影响**：纯 schema 自描述补充。

**验证**：schema description 含 fresh-null 说明。

---

## P17 (m9·minor) — scope-guard SKILL 说写 `_summary`，框架不读

> 对应 L1 P17。

**根因**：`scope-guard/SKILL.md:49`「额外写 `_summary`：框架 transition 从此字段生成 history」与框架行为不符（`ScopeGuardSubstage.transition:991-995` 从 dc 直接构造，不读 `_summary`）。

**修复**：`scope-guard/SKILL.md:49` 删「额外写 `_summary`…」，改「scope_verdict/upstream_stage/scope_reason 写入 `control.json.scope_*`（框架 transition 据此构造 history + 路由）；phase json 仅写 schema required 的字段」。框架不改。

**影响**：纯文档对齐框架行为。

**验证**：SKILL.md 无「框架从 `_summary` 生成 history」误导。

---

## P18 (m10·minor) — doc54 §10 as-built 空模板

> 对应 L1 P18。

**根因**：doc54 §10 `:246-248` 仅占位，无回填。

**修复**：doc54 §10 回填实际偏差（本次 review P1-P20 即偏差来源）、UT 数、commit。

**影响**：纯文档补全。

**验证**：§10 含实质内容。

---

## P19 (m11·minor) — 生成的 harness 子进程 import ascendc_devkit

> 对应 L1 P19。

**根因**：`runner.py:794` 生成的脚本含 `from ascendc_devkit.adapters.npu.precision_compare import compare_outputs`，子进程须装包。

**修复**（推荐 b：fail-fast 报错）：harness 头部包 try/except，缺包时明确报错而非裸 ImportError：
```python
try:
    from ascendc_devkit.adapters.npu.precision_compare import compare_outputs
except ImportError as e:
    raise SystemExit("[HARNESS] ascendc_devkit not installed in subprocess venv: %s" % e)
```

**影响**：不消除耦合（彻底脱钩需内联比对逻辑，成本高，列后续可选），仅改报错体验。

**验证**：子进程 venv 缺包时输出明确报错。

---

## P20 (n1·nit) — doc54 命名与代码双向漂移

> 对应 L1 P20。

**根因**：doc54 `:48/140/195` 用 `_assert_checkpoint_contract` / `FrameworkError`；代码是 `_assert_control_contract`（`:166`）/ `PrecisionDebugContractError`（`:50`）。

**修复**：doc54 三处命名统一为代码侧（`_assert_control_contract` / `PrecisionDebugContractError`）。

**影响**：纯文档对齐。

**验证**：doc54 grep 无旧命名。

---

# Part 2 — 总体设计

> 把 Part 1 的 20 条收拢成整体视图。先读本部分建立全局认知，再到 Part 1 看具体配方。

## §A 修复总览表

| P# | 级别 | 主题 | Stage | 决策 | 依赖 |
|---|---|---|---|---|---|
| P1 | blocker | 路径生成器去副作用 | 1 | D1 | — |
| P2 | blocker | 接收 `_append_history` 返回值 | 1 | — | — |
| P3 | blocker | 统一 history 写入权 + entry schema | 1 | D5 | — |
| P4 | major | per-phase schema 校验落地 | 2 | D2 | — |
| P5 | major | harness 形态校验落地 | 2 | D2 | — |
| P6 | major | `_json_to_py` 改 pprint | 3 | — | — |
| P7 | major | 计数器框架独占 | 3 | D4 | P2 |
| P8 | major | update-checkpoint 去 exec | 4 | D3 | — |
| P9 | minor | 字段登记 | 3 | — | P1 |
| P10 | minor | tee 路径统一 | 1 | — | — |
| P11 | minor | `_skill_dir` 加 resolve | 5 | — | — |
| P12 | minor | doc54 §5 位置 | 0 | — | — |
| P13 | minor | batch_runner 加日志 | 5 | — | — |
| P14 | minor | `_sync_phase_latest` 改 warn | 1 | — | P1 |
| P15 | minor | diagnose arch_gaps 提示 | 5 | — | — |
| P16 | minor | printf schema 补 null | 5 | — | — |
| P17 | minor | scope-guard SKILL 去 `_summary` 误导 | 1 | — | — |
| P18 | minor | doc54 §10 回填 | 0 | — | — |
| P19 | minor | harness ImportError fail-fast | 5 | — | — |
| P20 | nit | doc54 命名统一 | 0 | — | — |

## §B 决策表（D1-D5，待用户拍板）

| # | 决策点 | 选项 | 推荐 | 理由 |
|---|---|---|---|---|
| **D1** | P1 路径副作用修复（**保留 `_p{idx}` 序号**） | A. `_phase_path` 改纯函数 + 自增收敛到 `actions()`<br>B. 路径缓存经 state 中转 | **A** | 根除副作用（一次 spawn 自增一次）；actions/transition 同值天然一致；改动最小。**序号必须保留**：transition_table fix/printf_location 同 round 自循环（`fix:retry/skip_more`、`printf_location:continue`）+ 框架重试同 phase，去掉会覆盖归档（用户质询已核实） |
| **D2** | P4/P5 加载期校验 | A. 落实承诺<br>B. 诚实撤回 | **A** | §1.3；schema 已存在；resume 脏 harness 是真实痛点。仅交付极紧时选 B |
| **D3** | P8 update-checkpoint | A. 删脚本全走 heredoc<br>B. 保留改子命令 | **B** | 确定性脚本防错（§2.4）；子命令消除 exec + 不与 heredoc 重叠 |
| **D4** | P7 计数器 owner | A. 框架独占<br>B. agent 独占 | **A** | routing-control 字段归 FW（doc54 §4）；与 P3「agent 不写 history」同精神 |
| **D5** | P3 entry schema | A. 统一嵌套<br>B. 统一平铺<br>C. 路由双兼容 | **A** | 框架已嵌套；§1.4 不留兼容；F1 修后 agent 不写 history，全嵌套安全 |

> 未列决策的修复（P6、所有 minor/nit）采用唯一合理方案，Part 1 直接给出。

## §C 分 Stage 实施（每 Stage 独立验证 + commit）

| Stage | 覆盖 P# | 主题 | 说明 |
|---|---|---|---|
| **0** | P12 / P18 / P20 | 文档对齐 | doc54 漂移修正；L1/L4 落地；L2 加 step-55 |
| **1** | P1 / P2 / P3 / P10 / P14 / P17 | **history/relay 正确性** | blocker 主战场，强耦合一组改 |
| **2** | P4 / P5 | 加载期校验落地 | D2=A 时 |
| **3** | P6 / P7 / P9 | 序列化 + 计数器 + 字段登记 | P7 与 P2 同函数 |
| **4** | P8 | 写入通路收敛 | D3=B 时 |
| **5** | P11 / P13 / P15 / P16 / P19 | 剩余 minors（可并行） | 独立 |
| **6** | 全部 | 测试 | UT 补 + heavy_llm |

**关键耦合**：P1/P2/P7 都改 `RunTestsSubstage`，必须 Stage 1+3 协调；P3 文档修复必须配套框架 entry schema 统一（含 scope_guard 读取适配）；P9 的字段登记随 P1（D1）变化。

## §D 验证策略

1. **blocker**：P1 路径一致性、P2 history 不被抹、P3 嵌套读取 —— 各 UT。
2. **加载期校验**（Stage 2）：5 schema × 三态 UT；harness 旧形态 raise UT。
3. **序列化/计数器**（Stage 3）：`_json_to_py` 子串保留 UT；`run_iter_counter` 单调 +1 UT。
4. **全量回归**：`PYTHONPATH=src pytest tests/ut -m "not heavy_llm"` 全绿 + 非 heavy ST。
   - ⚠️ **环境注意**：本 checkout 的 `ascendc_devkit` 可能被主 checkout editable 遮蔽本地 src，裸跑会 import 到错代码还显示全绿。**必须 `PYTHONPATH=src`** 或从本 checkout 重装。
5. **heavy_llm**（交付前用户决策，§3.11）：真实 precision_debug 全流程 ×1（验证 B1/B2/F1 修通后 history relay 真通）+ 上游缺陷算子 ×1（scope guard）+ resume 旧产物算子 ×1（M1/M2 加载期校验）。优先合并入既有 precision_debug heavy 用例。

## §E 风险 / 不改边界

- **不改设计**：doc54 冻结的 5 决策（混合切分 / scope guard 独立 / control.json 契约 / 加载期 non-fixable halt / `working_dir=op_dir`）一个不动；Stage 契约 / transition_table / CompositeGroup 编排 / `_sync_debug_result` 终态物化 / `run_precision_cases()` / `DEBUG_RESULT_CONTRACT`（step-40 接口点）全不动。
- **核心流程语义变化**（唯一需重点验证）：B1+B2+F1 修通后 history relay 真正生效，循环路由依据从"错/缺失"变"正确"——必须 heavy_llm 验证走对路而非卡死。
- **D5=A 统一嵌套**：UT fixture 中残留的旧平铺 history entry 须同步更新为嵌套，否则 `_get_current_failure_type` 读不到。
- **M1/M2 落实后**：原本静默通过的脏 phase json / 脏 harness 会 halt。预期（§1.3），但 heavy_llm 前用真实产物跑一遍确认不误伤。
- **P1 路径公式变更**：归档文件名变；工程未发布（§1.4）直接改，不留迁移。
- **算子核心代码零改动**；改动集中在框架中继层（`substages.py` / `runner.py`）+ skill 文档 + doc54。
- **不重建 A5 路径**。

## §F as-built（实施记录，完成后回填）

> 按 Stage 回填实际偏差、UT 数、commit；记录 D1-D5 最终取值与执行差异。
