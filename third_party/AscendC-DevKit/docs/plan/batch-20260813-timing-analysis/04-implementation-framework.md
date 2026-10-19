# L4 — 框架代码改动实施方案（R1 / R2 / R5 / R7）

> 定位：L4 实施方案，覆盖「改 Python 框架代码」的 4 个方案。改 skill 内容的 R3/R4/R10 见 `05-implementation-skill.md`。
> 上游：L1 `01-problems.md`、L3 `02-analysis.md` §6 方案清单（R6 已实现、R4/R10 部分落地，本文件只写「待实施/补缺」的代码改动）。
> 原则：TDD（§3.1 先写测试再开发）、加载期校验优于运行期暴露（§1.3）、最小改动 + 正确改动（§1.2）。

## 改动清单总览

| 方案 | 文件 | 行号 | 改动性质 | 验证 |
|---|---|---|---|---|
| R1 早期 resume | `runtime_config.py` | 742 | ✅ 已实施（600→120）| 84 UT |
| R2 resume 通路统一 | `codegen.py` | 605-627 | ✅ 已实施（删 stage 层 resume）| 143 UT |
| R5 删除越界门 | `design_substages.py` + `anchor-consistency/SKILL.md` | — | ✅ 已实施（论证见 06）| 196 UT |
| R7 deploy 超时 | `deploy.py` | 61 + 524 | ⚠️ 降级预防性（本批无超时）| — |

---

## R1 — 早期 resume（turn_stall 阈值 600s→120s）

**改动点**：`runtime_config.py:742`
```python
_DEFAULT_OPENCODE_TURN_STALL_S = 600.0   # 改前
_DEFAULT_OPENCODE_TURN_STALL_S = 120.0   # 改后
```

**依据**：turn_stall 是「网关不吐字」的端侧死等；600s = 2× 网关窗口（注释自述），但观测到 11 次 stall 全是「模型真卡死/网关静默」，600s 只放大死等。缩到 120s（模型生成阶段不吐字即判死），工具执行阶段误判风险低（deploy build 走 `subprocess.run` 有独立 poll+timeout 不依赖 SSE；coder 试探编译短命，见 P17）。不必做 block_types 分阶段。

**验证（TDD）**：
1. UT：`runtime_config` 默认值测试，断言 `opencode_turn_stall_s` 默认 120.0。
2. UT：turn_stall 触发判定测试——模拟 SSE 静默 120s → 触发 resume（用 mock 时钟，不真实等 120s）。
3. ST（真实网关，llm 标记）：观察一次真实 stall 从 600s 死等缩到 120s 快速恢复。

---

## R2 — resume 通路统一（删 stage 层 sidecar resume）

**改动点**：`codegen.py:605-627` —— 删除 stage 层 session resume 逻辑（读 sidecar `session_sidecar_path` → 返回 `SpawnAgent(resume_session_id=...)`），统一走 backend 层 resume（`base_backend.py` 的 `_write_session_sidecar`/`_bump_session_resume_fails`/`_clear_session_sidecar`，含 `resume_fails >= resume_attempts → degrade fresh spawn`）。

**依据**：§2.5 唯一通路——同一职责（session resume）只允许一条实现通路。stage 层 resume 只读 `session_id` 不累计 `resume_fails`，导致「坏 session 反复 resume 永不 degrade」；backend 层已含完整 resume_fails 累计 + degrade，stage 层是重复通路（§2.5 违反，P15）。

**验证（TDD）**：
1. UT：删除后 `codegen` 不再有 stage 层 sidecar 读；resume 统一经 backend 层（mock backend 断言 resume_fails 累计逻辑被触发）。
2. 回归：resume 路径的既有 UT/ST 全绿（确保删除不破坏正常 resume）。

---

## R5 — 删除越界门（跨模板一致性判定）【已实施，论证见 06-cross-template-gate-overreach.md】

> 注：本节原写「加段非空校验」，后坐实为**误诊**——「段空」根因是 `_extract_shared_summary` 提取白名单字段漂移（越界查上游的必然结果，见 Q16），非「tiling 产出没写全」。正确改动 = 删除「跨模板一致性判定」这个越界门 + 补上游自检。

**已实施改动**：
1. 重写 `anchor-consistency/SKILL.md`：删 §3 跨模板一致性判定 + `tiling_shared_summary` 输入，AC0 改从 per-template `skeleton_api_verdict` 汇总。
2. 删 `design_substages.py` `_extract_shared_summary` + `_upstream_inputs` 提取 + `_INPUT_FILENAMES` 映射。
3. 补上游自检：`TemplateDivisionStage.transition` 加「tiling_key 唯一」校验 + template_division SKILL.md 补自检项。

**验证**：196 UT 通过（含新增 tiling_key 唯一测试）。

---

## R7 — deploy 构建超时动态化【降级预防性，暂缓】

> 注：坐实后降级——本批无 build 超时 600s 案例（build 走增量命令门但增量未生效，GLOB 全量重编 51 个 .o 仅 ~34s，见 P16/Q11），「600s 误判」是「防未来复杂算子首次全量编译超时」的预防性假设，非本批已发生 bug。原方案保留供未来参考。

**改动点**：`deploy.py:61` `_BUILD_TIMEOUT = 600` + `deploy.py:524` `timeout = _BUILD_TIMEOUT if stage.role == "build" else _INSTALL_TIMEOUT`

**改动内容**：把「固定 600s」改为「按 build 日志增长 / poll 存活判断是否真卡死」——`_run_command` 已有 `subprocess.run(timeout=600, capture_output=True)`，改为 poll + 日志增长心跳：build 日志（`build_ascendc.log`）持续增长 → 未卡死，继续等；日志停滞超阈值 → 才判死 kill。

**依据**：P17——复杂算子（如 grid_sampler）编译 >600s 会被 600s 硬阈值误判。框架有精确信号（poll + build 日志），不依赖 SSE，可精确判断真卡死 vs 长编译。

**验证（TDD）**：
1. UT：mock 长编译（日志持续增长）→ 不被 600s 误判。
2. UT：mock 真卡死（日志停滞）→ 超阈值 kill。
3. ST：真实复杂算子编译 >600s 不被误判（可复用本批 grid_sampler 的编译场景）。

---

## 实施状态（截至 2026-08-14）

- **R1** ✅ 已实施（600→120，84 UT）
- **R2** ✅ 已实施（删 stage 层 resume，143 UT）
- **R5** ✅ 已实施（删除越界门，196 UT，论证见 06）
- **R7** ⚠️ 降级预防性（本批无超时，暂缓）
