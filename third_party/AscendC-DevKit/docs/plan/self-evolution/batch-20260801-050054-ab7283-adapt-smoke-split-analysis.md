# batch 20260801-050054-ab7283 — adapt smoke 拆分方案（L3）

> **状态**：已实施完成（2026-08-02）。方案 B + deploy 分解 + 补 UT；UT 全量 3448 + ST（含真 NPU deploy/precision）全绿。实施中发现并修了 2 个 pre-existing latent bug（见 §8）。
> **来源**：L1 [`batch-20260801-050054-ab7283-issues.md`](./batch-20260801-050054-ab7283-issues.md) P5；本会话根因深挖 + 架构讨论（四把尺子 + §2.9/§2.5/§1.3 评估）。
> **适用范围**：通用框架改进（deploy/build_install/smoke 按职责分解 + adapt 不冒烟 + 解耦 eval），源于本 batch `multi_add_rms_norm_dynamic_quant` 案例，方案不限算子/batch。
> **本会话约束**：只落档、不改代码（另一 session 正在改代码，两边并改会冲突）。本文供实施 session 对齐。

## 1. 核心矛盾（事实见 L1 P5，此处只提炼判据）

**smoke 的存在价值 = 失败后是否有修复路径**（§2.9）。`Deployer.deploy` 现状是 build→install→**smoke(real-call)** 的原子事务（`deploy.py`），4 个调用方（debug_service / codegen / adapt / precision_debug）全拿全量 `DeployResult`，`smoke_passed` 是下游（`cannbench_eval.py:85`、`cannbench_adapt.py:131`）统一的「包可用」判据。

codegen 有意「带病前进」（`codegen.py:1520-1521`，smoke 没过也不 halt，交 precision_debug triage），定义了职责分层：

| 阶段 | 职责 | 失败后 |
|---|---|---|
| codegen | 产出 + smoke 自检 | 不 halt，带病交下游 triage |
| precision_debug | triage + 修 | 修不好耗尽预算（如本次）|
| adapt | 确定性胶水（wrapper + m.def）| fail=continue |
| eval | one-shot 评分 | **never loop back**（`cannbench_eval.py:112-115`）|

**adapt smoke 在「评分前置」塞了修复性检查，而它失败无人修**（adapt 无 agent、fail=continue、eval never-loop-back）—— §2.9 禁止的「只发现问题、无法解决」的门；且 real-call **越界查 kernel**（precision_debug 职责），把 kernel bug 误判为 `cannbench_adapt=error`。

## 2. 决策（用户 2026-08-01 拍板：方案 B + deploy 分解 + 补 UT）

1. **adapt 只 `build_install`，不验证**：adapt 不做 smoke / import-only，只调 deploy 的 `build_install()` 出包。
2. **deploy 按职责分解**：`deploy() = build_install() + smoke()`（build+install 强绑合成一个原语，smoke 独立）；codegen 仍用全量 `deploy()`，adapt 用 `build_install()`。§2.5 单一通路分解（deploy 复用子集，非新旧并存）。
3. **解耦 cannbench_eval**：前置从 `not deploy.smoke_passed`（`cannbench_eval.py:85`）改成 `deploy is None`（包是否产出）；胶水 bug 靠 eval 加载期 infra-0 兜。
4. **补确定性函数 UT**：给 `generate_and_inject_wrapper` / `rename_mdef_schema_if_needed` 补 UT（§3.1），把胶水正确性前移到开发期（构造性保证）。

## 3. 为什么是 B（基本原则推导）

- **§2.9 构造性保证优先于检查门**：adapt 的胶水改动是确定性函数，正确性应由开发期 UT 构造性保证，而非运行期 import-only 兜底。
- **§1.3 产出期校验（UT）优于运行期暴露（import-only/smoke）**。
- **eval never-loop-back**：运行期验证（smoke / import-only）不创造修复价值，只创造归因价值；胶水 bug 是确定性函数 bug，归因到 adapt 还是 eval infra，结论都是「改确定性函数」，差异边际小。
- **§2.5**：deploy 分解是单一通路分解（`deploy` 复用 `build_install`），非多通路。
- **codegen smoke 保留**（有 self-fix loop，构造性保证 kernel 可调用）。

## 4. 排除 / 备选

- **A（现状 real-call smoke）排除**：撞 §2.9（无消费渠道门）+ 越界查 kernel + 误导归因 + 全或无误伤可拿分 case。
- **D（smoke + loopback precision_debug）排除**：precision_debug 已空转未收敛，loopback 落入无效回环（§2.9 禁止「期待重新生成解决问题」，参见 memory `design-review-infeasible-loopback-deadloop`）；real-call 越界未解。
- **C（adapt import-only 符号检查）降为备选**：若确定性函数 UT 不可行 / 覆盖不足（m.def schema 形式多样难穷举），C 的 import-only 作为运行期 defense-in-depth 兜底启用。UT 可行时 C 冗余（被 UT 取代）。决定性分叉 = 「确定性函数 UT 能否覆盖胶水正确性」。
- **deploy 拆分形态 (ii) 开关 / (iii) 独立专用方法 排除**：(ii) 一通路带开关 = 实质两通路，违 §2.5 + §1.10（机制特征代理业务语义）；(iii) 两通路并存违 §2.5（除非 `deploy` 复用它，即退化为 (i)）。

## 5. 落地改点（供实施 session；本会话不改代码）

1. `orchestration/stages/deploy.py`：`deploy()` 分解出 `_build_install()` + `_run_smoke()`，`deploy() = build_install() + smoke()`；暴露 public `build_install()`。
2. `orchestration/stages/cannbench_adapt.py:121-132`：transition 调 `build_install()` 替代全量 `deploy(clean_build=True)`；`rebuilt` 判定改为「build_install 成功产出包」（不依赖 `smoke_passed`）。
3. `orchestration/stages/cannbench_eval.py:84-88`：前置 `deploy is None or not deploy.smoke_passed` → `deploy is None`。
4. 补 UT：`generate_and_inject_wrapper` / `rename_mdef_schema_if_needed`（§3.1，构造性保证胶水正确性）。

> **实施顺序（关键）**：先改 cannbench_eval（解耦 smoke_passed），再改 deploy 分解 + adapt。顺序反了会导致 deploy 一拆 / adapt 一不 smoke 时，eval 仍依赖 smoke_passed → eval 永远 skip（比现状更糟）。

## 6. 前提与风险

- **前提**：第 4 点（补 UT）是 B 的构造性保证。不补 UT 则胶水正确性失构造性保证，B 的 §2.9/§1.3 论证站不住 → 此时启用备选 C（import-only）。
- **风险**：胶水 bug 推迟到 eval infra 暴露（归因稍模糊于 C），靠 eval infra-0 + `last_error` 兜，UT 前移作主防线。

## 7. 边界 / 不做

- 不动 codegen 的 smoke（有 self-fix loop，价值成立）。
- 不在 precision_debug 加 smoke（run_tests 更强，冗余）。
- 不为「省 eval 时间」保留 adapt smoke（eval 跑挂 0 分可接受）。
- 不改 L1 P5 已记录的事实（本方案是 P5 的 L3 延伸，事实产权留 L1）。

## 8. 实施记录（2026-08-02 完成）

**代码改动**：
- `cannbench_eval.py`：transition 前置 `deploy is None or not smoke_passed` → `deploy is None`（解耦 smoke_passed）。
- `deploy.py`：`deploy()` 分解为 `_resolve`（共享 resolve）+ `build_install`（public，build+install）+ `_run_smoke_phase`；`deploy()` = build_install + smoke（codegen/redeploy 行为不变）；删 `_run_profile_chain`。§2.5 单一通路分解（deploy 复用 build_install，非多通路）。
- `cannbench_adapt.py`：transition 调 `build_install`（不 smoke）；`rebuilt` 判定从 `smoke_passed` 改为「build_install 成功产出包」。
- `mdef_parse.py`：`_PARAM_RE` type-token 字符类加 `?`/`()!`（修 §8 bug①）。

**测试改动**：各 stage UT 同步（mock `deploy`→`build_install`、新增 `build_install` UT、`TestSmokeGate`→`TestDeployPresenceGate`）；`test_mdef_parse.py` +5 UT。

**实施中发现的 2 个 pre-existing latent bug**（与方案 B 正交，由 task 4「构造性保证」+ task 5「ST 验证」暴露）：

1. **`mdef_parse._PARAM_RE` 不认 `Tensor?` / `Tensor(a!)`**（task 4）：type-token 字符类 `[\w\[\]&\s]` 缺 `?`/`()!` → `parse_mdef_params` fallback 返回整个 token → `rename_mdef_schema` 静默 no-op，但 P10 日志/状态误报 renamed。本 batch `multi_add` 的 `Tensor? smooth_scale1=None` 即此 form —— L1 P5 run.log 里 P10 `from='Tensor? smooth_scale1=None'`（整个 token）的根因即此。修：字符类加 `?`/`()!` + 5 UT。

2. **fixture golden 缺 Tensor 注解**（task 5）：`tests/fixtures/add_golden*.py` 的 `reference(a,b)` / `add(a,b)` 无注解 → `bind_golden_args`（`golden_binding.py:82` 靠 `"Tensor" in annotation` 识别 tensor 参数）把 a/b 当 scalar attr、不绑定 → `reference() missing required arguments 'a' and 'b'` → `test_npu.py` 3 个真 NPU precision ST 全 999.0 失败。根因：P135 引入 `bind_golden_args`（契约要求 golden 参数带 Tensor 注解）但 fixture 未跟进，且 `test_npu.py` 真 NPU ST 自 P135 后未跑（5a5dcdb2 impl 文档自承「待真 NPU 补跑」）。修：fixture 加 `"Tensor"` 字符串注解。隔离验证（stash 我的改动重跑）确认 3 failed 在原始 src 同样复现 —— pre-existing，非本次方案 B 引入。

**验证**：
- UT 全量：3448 passed / 7 skipped（parity 需 PYTHONPATH）/ 1 deselected。
- 确定性 ST（`test_cannbench_discovery_st`）：4 passed。
- 真 NPU ST（`test_npu.py::TestNPURunnerRealExecution`，直接调 `Deployer().deploy`）：7 passed / 2 skipped（修 bug② 后从 3 failed → 全绿）。
