# F2: 定位证据不反哺产物收集（部分已解决）

## 现象

框架通过 `_harvest_relocation_evidence` 能从 transcript 中**提取出孤儿产物的确切路径**（`actual_path`），反馈文本里能明确写出"产物被写入了 `.../20260820-164bbc/...`"。定位到的 `actual_path` 是否被产物消费，取决于收集路径——**设计子阶段已解决，backend 通用收集（codegen）仍存在缺口**。

## 当前状态（2026-08-20 方案 A 实施后）

### ✅ 已解决：设计子阶段的孤儿收集

方案 A（commit `4a066149`）让 `_read_disk_artifacts` 在 transition 里消费孤儿产物：
- 孤儿 → `_harvest_relocation_evidence_detailed` 定位 → 非交互自动搬回 → `_locate_artifact` 找到 → 解析 → stage ok
- backend 层 `_collect_artifacts` 判 `empty_artifacts` **无影响**：`runner.py:567` 将 `empty_artifacts` 视为 ok，且 `_DesignSubstage.transition` 不检查 `agent_result.status`（只看磁盘产物）。

证据：
- `_DesignSubstage.transition` 走 `_parse_single` → `_read_disk_artifacts`，全程不读 `agent_result.status`（`design_substages.py`）。
- `runner.py:567-570`：`agent_status not in ("ok","empty_artifacts")` 才判 failed，empty_artifacts 不触发。

### ❌ 剩余缺口：codegen 的 `generated_sources` 收集不到孤儿

codegen 产物收集走 `_collect_changed_sources`（`_shared.py:744`），用 `ap.relative_to(op_dir.resolve())` 做 scope safety（`_shared.py:777`）：
- **op_dir 外的孤儿产物被过滤丢弃**（`ValueError → continue`）。
- coder 写错目录（孤儿）→ git diff 看到 → **scope filter 丢弃** → `generated_sources = {}` → 契约 `generated_sources` 不满足 → `codegen_consecutive_failures+1` → 熔断。

### codegen 缺口的真实边界（比初始判断更窄，也更彻底）

核对了孤儿路径的 git 归属后，codegen 的孤儿**彻底不可见、且无搬回机制**：

1. **git diff 看不到**：codegen 的 op_dir 在 cann-bench 仓，孤儿路径在 devkit 的 `output/` 下——**被 `.gitignore` 的 `output/` 忽略**，且是另一个 git 仓。git diff 视野完全不包含孤儿。
2. **scope filter 挡**：即便同仓，`relative_to(op_dir)` 也丢弃 op_dir 外（`_shared.py:777`）。
3. **无搬回机制**：codegen 的 transition 走 `_persist_sources`（`codegen.py:1170`），**不走** `_DesignSubstage._read_disk_artifacts`——所以 `_harvest_relocation_evidence` + 自动搬回在 codegen 场景下**不会触发**。

**结论**：codegen 的孤儿产物防护**只能靠方案 B（prompt 注入 cwd 绝对路径）在源头预防**。方案 A 的搬回机制在 codegen 层不适用（backend 收集无 transcript、codegen transition 不走设计子阶段路径）。若要给 codegen 加独立的孤儿检测，需跨层传 transcript 证据 + 处理与 scope filter 的冲突，成本高。

## 为什么剩余缺口暂不修（低优先级）

1. **本次批跑未触发**：moe_re_routing 的 coder 是空跑（0 write），不是写错目录——codegen 的孤儿缺口本次未暴露。
2. **修复成本高**：需把 `_harvest_relocation_evidence` 的 transcript 证据**跨层传进 `_collect_changed_sources`**（backend 层没有 transcript 参数），涉及 backend/collection 边界改造。
3. **scope filter 是刻意设计**：防"把 pre-existing op_dir 当本次输出"误扫（`_shared.py:753-759` 明确说明）。放宽有误扫风险，需谨慎权衡。
4. **方案 B 已提供预防**：prompt 注入 cwd 绝对路径降低路径幻觉概率，是 codegen 场景下的主要防护。

## 影响

- 设计子阶段：无（已解决）。
- codegen：**潜在**——coder 写错目录时 generated_sources 收不到 → 熔断。但本次未触发，且空跑（0 write）是更常见的失败模式。

## 根因定位（剩余部分）

定位证据（`_harvest_relocation_evidence`，设计子阶段层）与 backend 收集（`_collect_artifacts`/`_collect_changed_sources`，agent 层）**分层不同**——证据在设计 stage 的 transition 里，收集在 backend 的 spawn 里。方案 A 把证据用在了 transition（搬回），但 backend 收集在 spawn 结束即执行（`opencode_backend.py:814`），早于 transition，且不持有 transcript 参数。**跨层证据传递是剩余缺口的本质。**

## 建议

- F2 主体已解决（设计子阶段）。codegen 缺口记录为已知低优先级项，待 codegen 写错目录场景真实出现再评估。
- 触发条件：coder 把产物写到 op_dir 之外（含孤儿目录）。
