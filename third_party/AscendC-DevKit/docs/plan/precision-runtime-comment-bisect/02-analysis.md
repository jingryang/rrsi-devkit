# precision_debug runtime 注释二分定位 — L3 方案分析（2026-07-22）

> 层级：**L3 方案分析**。每个问题列举候选方案 + 四尺子评估 + 选取结论。
> 实施方案见 `03-impl.md`（L4）。

## 文件简称映射

| 简称 | 实际路径 |
|------|---------|
| `substages` | `src/ascendc_devkit/orchestration/stages/precision_debug_substages.py` |
| `tree` | `src/ascendc_devkit/orchestration/precision_debug_tree.py` |
| `config` | `resources/orchestration-config.json` |
| `fix-skill` | `.claude/skills/ascendc-precision-fix/` |

---

## D1 — 注释二分定位的承载方式（覆盖 P1 / P2 / P4）

### 方案

| 选项 | 描述 | 四尺子评估 |
|------|------|-----------|
| O1 增强内嵌 | 把 fix 内消融从 ad-hoc 升级为「区域→行」结构化二分，仍由 fix agent spawn 内完成 | 可维护↓（定位/应用仍混杂，违 §2.5/§2.7）；可扩展↓（fix skill 膨胀）；可诊断↓（借用 fix_code_log，可观测差）；架构↓（与 printf_location 不对称） |
| **O2 新建独立 comment_bisect substage** ✅ | 仿 printf_location 新增 `CommentBisectSubstage` + skill + agent；删 fix 内嵌消融（§2.5） | 可维护✓（定位/应用分离，单一职责）；可扩展✓（新定位手段加新 stage 不污染 fix）；可诊断✓（独立 `precision_comment_bisect.json`，bisect_progress/experiments 可观测）；架构✓（与 printf_location 对称：precision→printf, runtime→comment_bisect，定位阶段统一模式） |

**选取 O2**。定位与应用是两个职责（定位=缩小病灶区间，应用=改代码验证 commit），应分属不同 stage。O2 与现有 printf_location 形成对称闭环，corrective 循环/退火机制（`corrective_cycles` / `deploy_fail_streak`）可直接复用，无需新增计数器。

### 代价处理（§2.5 不留旧债）
fix 内嵌消融随 O2 落地一并删除：fix.md:177-212 消融伪码段 + 注 2、fix SKILL.md:22 runtime 分流描述、agents/ascendc-precision-fix.md:45 回退引用。fix 回归「候选池验证 + 应用 + commit/rollback」单一职责。

---

## D2 — 多根因策略（覆盖 P3）

### 方案

| 选项 | 描述 | 四尺子评估 |
|------|------|-----------|
| **O1 增量定位** ✅ | comment_bisect 定位一处根因 → 生成 fix_plan(`source=comment_bisect`) → 回 fix 修 → run_tests 回归 → 同 case 仍 crash → fix `pool_exhausted` → `need_comment_bisect` → comment_bisect 读 `located_roots` 跳过已定位区域继续二分 | 可维护✓（复用现有 case 循环 + corrective_cycles，无新状态机）；可扩展✓（天然支持 N 处根因）；可诊断✓（located_roots 累积可观测）；架构✓（与「修一处→回归」现有节奏一致，单阶段 context 安全） |
| O2 穷举定位 | 一次 comment_bisect 把该 case 所有根因定位完再回 fix | 可诊断↓（单阶段实验多，context 风险）；架构↓（与「修一处→回归验证」节奏不契合） |

**选取 O1**。多根因由「case 循环 + 增量二分」天然承载：每轮 comment_bisect 只定位下一处，定位到即回 fix，修完由 run_tests 判定是否还有残留 crash。comment_bisect 读 `bisect_progress.located_roots` 在剩余区域继续，无需单次穷举。

---

## D3 — P5 悬空引用

随 O2 落地：注释二分有了真正实现（comment_bisect skill），fix 里「回退 comment-bisect（见 printf-debug.md）」的错引统一修正——runtime 定位已由框架路由接管（`need_comment_bisect`），fix 不再需要自行回退定位，相关引用删除。

---

## D4 — 区域二分加速策略（覆盖 P1 收敛速度）

### 方案

| 选项 | 描述 | 四尺子评估 |
|------|------|-----------|
| O1 盲区域二分 | 从注释整阶段开始二分 | 通用但慢；纯 Compute 段浪费 experiment |
| **O2 DataCopy/TQue 先验优先** ✅ | 先定向消融所有 DataCopy 调用 + TQue 使用点，命中直击行级；全不命中 fallback 盲区域二分 | 可维护✓（领域先验显式化）；可扩展✓；可诊断✓（每调用点消融进 `experiments`）；架构✓（跨算子通用领域知识归 skill，§2.7，不耦合具体算子） |

**选取 O2**。runtime crash（507035 向量核异常 / GM·UB 越界 / 地址非 32B 对齐）根因统计上高度集中在 **DataCopy / DataCopyPad**（地址对齐 / `blockLen` / `stride` / `burstLen` / UB 容量）与 **TQue**（buffer 生命周期 Alloc/Free / pipe 标志 / 跨 pipe 读写），纯 Vector Compute 极少直接 crash（UB 溢出也几乎总由 DataCopy 搬入尺寸错带出）。DataCopy/TQue 调用点数量有限（个位数～十几），O(N) 定向消融比盲阶段二分更快命中且直达行级。

### 消融纪律（避免假阳性）
- **DataCopy**：消融用**参数降级**（`blockLen` / `element` → 安全常量），**禁止裸注释**——裸注释后下游消费者读未初始化 buffer，引入无关假 crash，把二分带偏。
- **TQue**：消融用最小安全配对（保留 Alloc/Free 配对，不破坏 pipe 不变式）。
- 全部 DataCopy/TQue 点消融后 crash 仍在 → fallback 盲区域二分（阶段→区块→行）。

---

## 总体策略

四把尺子综合：**正确改动** = 新建 comment_bisect 独立 substage（D1-O2）+ 增量多根因（D2-O1）+ 删 fix 内嵌消融（§2.5）。

两层职责：
1. **定位层**（comment_bisect）：注释二分缩小病灶区间（阶段→区块→行），产出 `fix_plan(source=comment_bisect)` 入 `candidate_pool`
2. **应用层**（fix）：取 fix_plan 应用 + 单用例验证 + commit/rollback（单一职责，不再定位）

判定信号：纯 crash/no-crash 二分（注释后 errcode 变化 / `max_err` 是否脱出 999.0），**完全不依赖 printf 输出**——这正是 runtime crash 能用注释二分、不能用 printf 的根因。

## 变更记录

| 日期 | 内容 |
|------|------|
| 2026-07-22 | 初版：D1 选 O2（独立 substage）+ D2 选 O1（增量）+ D3 随落地修正引用 |
