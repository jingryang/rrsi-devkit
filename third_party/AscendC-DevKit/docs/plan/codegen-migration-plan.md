# Codegen Regbase 迁移方案

## 1. 背景

- **旧工程**：`/home/h00616010/xyl/AscendC-DevKit`，commit `a27cd19`，含完整 Regbase codegen pipeline
- **新工程**：`/home/h00616010/xyl_new/AscendC-DevKit`，commit `0a7e30a`，强制 fork 自 upstream 另一谱系
- **两仓库无共同 Git 祖先**（remote 被 `forced update` 覆盖），无法 git merge，需手工迁移
- **旧工程改动量**：25 个文件，+5482 / -539 行
- **新工程本地无未提交改动**：`git diff HEAD` 对 codegen.py / state.py 均为空

---

## 2. 执行前提

```bash
# 确认旧工程可读
ls /home/h00616010/xyl/AscendC-DevKit/src/ascendc_devkit/orchestration/stages/codegen.py

# 确认新工程干净
cd /home/h00616010/xyl_new/AscendC-DevKit
git diff --exit-code HEAD -- src/ascendc_devkit/orchestration/stages/codegen.py
git diff --exit-code HEAD -- src/ascendc_devkit/orchestration/kernel/state.py

# 创建迁移分支
git checkout -b migrate/codegen-regbase
```

---

## 3. Step A：state.py — 添加 Regbase 状态机字段

### 变更点 A1：新增 9 个 dataclass 字段

**文件**：`src/ascendc_devkit/orchestration/kernel/state.py`

**插入位置**：L217 之后（`codegen_consecutive_failures: int = 0` 行后，`build_result: BuildResult | None = None` 行前）

**插入内容**：

```python

    # —— Regbase 多步编排状态（仅 A5 Regbase 路径使用；Membase 保持空字符串） ——
    # Phase 状态机: "" | "init" | "s2" | "s4" | "s5" | "done"
    codegen_phase: str = ""
    # RECORD_DIR 绝对路径（staging 子目录下）
    codegen_record_dir: str = ""
    # 当前 s4 子阶段 ID（如 "4.C.3.VT.0"），空字符串表示未开始或已完成
    codegen_s4_sub_stage: str = ""
    # 当前 s4 检查点组
    codegen_s4_checkpoint_group: str = ""
    # V(t) / E(t) 进度与错误度量
    codegen_vt: float = 0.0
    codegen_et: int = 0
    # 重试计数器（独立于 meta.json，Python 侧管理）
    codegen_retries: dict = field(default_factory=dict)
    # NEEDS_AGENT 暂存：目标 agent 名 + 恢复点
    codegen_pending_agent: str = ""
    codegen_pending_resume_point: str = ""
    # VF 失败重试时注入上次错误报告（从 agent_result.message/metrics 提取）
    codegen_vf_previous_error: str = ""
```

### 变更点 A2：新增 9 个迁移条目

**插入位置**：L486（`("design_known_issues", []),` 行后，`]:` 闭合括号之前）

> ⚠️ 注意：新工程 `_UPGRADE_MIGRATIONS` 列表末项是 `("design_known_issues", [])`（L486），不是 `("pending_advisories", [])`（L484）。旧工程中 `pending_advisories` 是末项，但新工程在其后新增了 `design_known_issues`。

**插入内容**：

```python
            # Regbase 多步编排状态（新增字段，旧快照兼容）
            ("codegen_phase", ""),
            ("codegen_record_dir", ""),
            ("codegen_s4_sub_stage", ""),
            ("codegen_s4_checkpoint_group", ""),
            ("codegen_vt", 0.0),
            ("codegen_et", 0),
            ("codegen_retries", {}),
            ("codegen_pending_agent", ""),
            ("codegen_pending_resume_point", ""),
            ("codegen_vf_previous_error", ""),
```

### 验证

```bash
python3 -c "import ast; ast.parse(open('src/ascendc_devkit/orchestration/kernel/state.py').read()); print('state.py: syntax OK')"
python3 -c "from ascendc_devkit.orchestration.kernel.state import State; s=State(); print('codegen_phase:', repr(s.codegen_phase))"
```

---

## 4. Step B：codegen.py — 旧版复制 + 5 处路径修正

### 操作 B0：复制

```bash
cp /home/h00616010/xyl/AscendC-DevKit/src/ascendc_devkit/orchestration/stages/codegen.py \
   /home/h00616010/xyl_new/AscendC-DevKit/src/ascendc_devkit/orchestration/stages/codegen.py
```

旧版：1850 行 / 新版（替换前）：1010 行。增量 840 行包括完整的 Regbase 多步编排状态机。

### 修正 B1：`_regbase_skill_root()` DevKit 自身路径（~L211）

**搜索关键字**：`devkit_candidate =`

**Before**：
```python
        devkit_candidate = (devkit_root / ".claude" / "plugins"
                            / "stage-codegen" / "skills"
                            / "ascendc-op-dev-coding-regbase")
```

**After**：
```python
        devkit_candidate = (devkit_root / ".claude" / "skills"
                            / "ascendc-op-dev-coding-regbase")
```

### 修正 B2：`_regbase_skill_root()` 目标仓库候选路径（~L220）

**搜索关键字**：`Path(str(state.repo_root or "")) / ".claude" / "plugins"`

**Before**：
```python
        candidates = [
            Path(str(state.repo_root or "")) / ".claude" / "plugins"
            / "stage-codegen" / "skills" / "ascendc-op-dev-coding-regbase",
            Path.home() / ".claude" / "skills" / "ascendc-op-dev-coding-regbase",
        ]
```

**After**：
```python
        candidates = [
            Path(str(state.repo_root or "")) / ".claude" / "skills" / "ascendc-op-dev-coding-regbase",
            Path.home() / ".claude" / "skills" / "ascendc-op-dev-coding-regbase",
        ]
```

> 注意：`Path.home() / ".claude" / "skills"` 保持不变（新旧工程一致）。

### 修正 B3：`_regbase_vf_ref_dir()`（~L255）

**搜索关键字**：`_regbase_vf_ref_dir`

**Before**：
```python
        return str(Path(repo) / ".claude" / "plugins" / "stage-codegen"
                   / "skills" / "regbase-vf-test" / "references" / "vf-instructions")
```

**After**：
```python
        return str(Path(repo) / ".claude" / "skills"
                   / "regbase-vf-test" / "references" / "vf-instructions")
```

### 修正 B4：slash command 注释（~L745）

**搜索关键字**：`as a slash command`

**Before**：
```
    as a slash command (``/stage-codegen:<skill>``), NOT a model-invokable
```

**After**：
```
    as a slash command (``/<skill>``), NOT a model-invokable
```

### 修正 B5：SKILL.md 路径（~L107，在 Step E skill 迁移中处理）

**搜索关键字**：`realpath .claude/plugins/stage-codegen`

**Before**：
```
1. `realpath .claude/plugins/stage-codegen/skills/ascendc-op-dev-coding-regbase/`
```

**After**：
```
1. `realpath .claude/skills/ascendc-op-dev-coding-regbase/`
```

### 验证

```bash
python3 -c "import ast; ast.parse(open('src/ascendc_devkit/orchestration/stages/codegen.py').read()); print('codegen.py: syntax OK')"
# 确认无残留旧路径
grep -n "plugins.*stage-codegen\|stage-codegen.*plugins" src/ascendc_devkit/orchestration/stages/codegen.py && echo "ERROR: stale path!" || echo "PASS: no stale paths"
```

---

## 5. Step C：Agent 定义文件

| # | 文件 | 操作 | 改动内容 |
|---|------|------|---------|
| C1 | `.claude/agents/ascendc-dev-s5-compile.md` | **直接复制**（新文件，新工程不存在） | 255 行，Stage 5 编译 sub-agent |
| C2 | `.claude/agents/ascendc-dev-s2-analysis.md` | **旧版替换 + 1 处路径修正** | 双模式输入支持（JSON/Markdown），JSON 需求分析流程 — 需修正 VF 路径 |
| C3 | `.claude/agents/ascendc-dev-s4-coding.md` | **旧版替换 + 4 处路径修正** | 环境参数获取优先级 + 双模式详设列识别 — 需修正 VF 路径 |
| C4 | `.claude/agents/ascendc-coder-regbase.md` | **手动补一行** | 在 frontmatter 添加 `disallowed_tools: [AskUserQuestion]` |
| C5 | `.claude/agents/ascendc-vf-test-agent.md` | **旧版替换 + 8 处路径修正** | 新增 PATH 导出指令 + VF 经验/指令路径全部需修正 |

### C1 命令

```bash
cp /home/h00616010/xyl/AscendC-DevKit/.claude/agents/ascendc-dev-s5-compile.md \
   .claude/agents/ascendc-dev-s5-compile.md
```

### C2 命令 + 路径修正

```bash
cp /home/h00616010/xyl/AscendC-DevKit/.claude/agents/ascendc-dev-s2-analysis.md \
   .claude/agents/ascendc-dev-s2-analysis.md
```

**C2 路径修正**（复制后执行）：

**文件**：`.claude/agents/ascendc-dev-s2-analysis.md`

**位置**：L328（搜索关键字 `plugins.*stage-codegen.*regbase-vf-test`）

旧工程写的是 `$AGENT_ROOT/../../plugins/stage-codegen/skills/`，新工程扁平布局下应为 `$AGENT_ROOT/../skills/`。

**Before**：
```
| `vf-instructions:模式或指令` | ... | Read `$AGENT_ROOT/../../plugins/stage-codegen/skills/regbase-vf-test/references/vf-instructions/` ...
```

**After**：
```
| `vf-instructions:模式或指令` | ... | Read `$AGENT_ROOT/../skills/regbase-vf-test/references/vf-instructions/` ...
```

> 新旧工程路径关系：旧 `$AGENT_ROOT/../../plugins/stage-codegen/skills/` = 新 `$AGENT_ROOT/../skills/`（`$AGENT_ROOT` 指向 `.claude/agents/`，`../skills/` 即 `.claude/skills/`）

### C3 命令 + 路径修正

```bash
cp /home/h00616010/xyl/AscendC-DevKit/.claude/agents/ascendc-dev-s4-coding.md \
   .claude/agents/ascendc-dev-s4-coding.md
```

**C3 路径修正**（复制后执行，共 4 处）：

**文件**：`.claude/agents/ascendc-dev-s4-coding.md`

统一修正模式：`$AGENT_ROOT/../../plugins/stage-codegen/skills/regbase-vf-test/` → `$AGENT_ROOT/../skills/regbase-vf-test/`

| # | 行号 | 搜索关键字 |
|---|------|-----------|
| 1 | L174 | `vf-instructions:模式或指令` |
| 2 | L220 | `VF 指令参考文档` |
| 3 | L251 | `ascend_regbase_programing_guide.md` |
| 4 | L252 | `ascend950_hardware_and_pipeline_control.md` |

> ⚠️ 这 4 处路径在新工程原版中**已正确**（`../skills/`），旧版替换后需要修正回来。

### C4 手动操作（1 处插入）

**文件**：`.claude/agents/ascendc-coder-regbase.md`

**插入位置**：L18（`  - TaskUpdate`）之后，L19（`---` frontmatter 闭合）之前

**插入内容**：
```yaml
disallowed_tools:
  - AskUserQuestion
```

**变更效果**（上下文）：
```diff
   - Agent
   - TaskCreate
   - TaskUpdate
+disallowed_tools:
+  - AskUserQuestion
 ---
```

### C5 命令 + 路径修正

```bash
cp /home/h00616010/xyl/AscendC-DevKit/.claude/agents/ascendc-vf-test-agent.md \
   .claude/agents/ascendc-vf-test-agent.md
```

**C5 路径修正**（复制后执行，共 8 处）：

**文件**：`.claude/agents/ascendc-vf-test-agent.md`

统一修正模式：`$AGENT_ROOT/../../plugins/stage-codegen/skills/regbase-vf-test/` → `$AGENT_ROOT/../skills/regbase-vf-test/`

| # | 行号 | 上下文 |
|---|------|--------|
| 1 | L147 | VF 经验扫描路径 |
| 2 | L149 | vf_experiences 扫描路径 |
| 3 | L153 | VF 指令参考冲突处理 |
| 4 | L154 | VF lesson 归档路径 |
| 5 | L160 | VF 指令参考查阅说明 |
| 6 | L169 | INDEX.md 决策树 |
| 7 | L205 | vf_instruction_hints 参数说明 |
| 8 | L256 | ascend_regbase_programing_guide.md 检查规则 |

---

## 6. Step D：Skill 文件 — ascendc-op-dev-coding-regbase

**路径映射**：

| | 旧 | 新 |
|---|----|----|
| Skill 根 | `.claude/plugins/stage-codegen/skills/ascendc-op-dev-coding-regbase/` | `.claude/skills/ascendc-op-dev-coding-regbase/` |

### 需要替换的文件清单

| 文件（相对 skill 根） | 旧行数 | 新行数 | 说明 |
|----------------------|--------|--------|------|
| `SKILL.md` | 457 | 343 | 大幅重写，增加 Regbase 专用流程 |
| `references/env-and-platform.md` | +21 | — | 新增 §3.8 静态硬件参数查表 |
| `references/orchestrator-logic.md` | 大幅改动 | — | 3 阶段编排逻辑替代原 5 阶段 |
| `references/phase-c-prompts.md` | +71 | — | C 系列步骤 prompt 扩展 |
| `references/coding-plan-template.md` | +6 | — | 新增 api_code / plugin_code C 步骤 |
| `scripts/stage4_scheduler.sh` | +24 | — | s4 子阶段调度增强 |
| `tests/test_integration.sh` | 1010 | 不存在 | 新文件，集成测试脚本 |

### 操作命令

```bash
OLD_SKILL=/home/h00616010/xyl/AscendC-DevKit/.claude/plugins/stage-codegen/skills/ascendc-op-dev-coding-regbase
NEW_SKILL=/home/h00616010/xyl_new/AscendC-DevKit/.claude/skills/ascendc-op-dev-coding-regbase

# 替换修改过的文件（覆盖）
cp "$OLD_SKILL/SKILL.md"                       "$NEW_SKILL/SKILL.md"
cp "$OLD_SKILL/references/env-and-platform.md" "$NEW_SKILL/references/env-and-platform.md"
cp "$OLD_SKILL/references/orchestrator-logic.md" "$NEW_SKILL/references/orchestrator-logic.md"
cp "$OLD_SKILL/references/phase-c-prompts.md"  "$NEW_SKILL/references/phase-c-prompts.md"
cp "$OLD_SKILL/references/coding-plan-template.md" "$NEW_SKILL/references/coding-plan-template.md"
cp "$OLD_SKILL/scripts/stage4_scheduler.sh"    "$NEW_SKILL/scripts/stage4_scheduler.sh"

# 复制新文件
mkdir -p "$NEW_SKILL/tests"
cp "$OLD_SKILL/tests/test_integration.sh"      "$NEW_SKILL/tests/test_integration.sh"
chmod +x "$NEW_SKILL/tests/test_integration.sh"
```

**D7 路径修正**（复制后执行，1 处）：

**文件**：`.claude/skills/ascendc-op-dev-coding-regbase/tests/test_integration.sh`

**位置**：L315（搜索关键字 `plugins.*stage-codegen.*vf-instructions`）

**Before**：
```bash
VF_INSTR_DIR="$(dirname "$AGENT_VF")/../plugins/stage-codegen/skills/regbase-vf-test/references/vf-instructions"
```

**After**：
```bash
VF_INSTR_DIR="$(dirname "$AGENT_VF")/../skills/regbase-vf-test/references/vf-instructions"
```

### 需要修正的路径 — SKILL.md（同 Step B5）

**文件**：`.claude/skills/ascendc-op-dev-coding-regbase/SKILL.md`（Step D 复制完成后）

**位置**：L107（`## SKILL_ROOT 与 AGENT_ROOT` 章节下第 1 条，搜索关键字 `realpath .claude/plugins`）

**Before**（完整上下文）：
```
Session 首次调度前获取 SKILL_ROOT 绝对路径（session 内持有，失败不重试）：

1. `realpath .claude/plugins/stage-codegen/skills/ascendc-op-dev-coding-regbase/`
2. `realpath ~/.claude/skills/ascendc-op-dev-coding-regbase/`
3. 兜底 `find ~ ...`
4. 全部失败 → PAUSED ...
```

**After**：
```
1. `realpath .claude/skills/ascendc-op-dev-coding-regbase/`
2. `realpath ~/.claude/skills/ascendc-op-dev-coding-regbase/`    ← 不变
3. 兜底 `find ~ ...`                                              ← 不变
4. 全部失败 → PAUSED ...                                          ← 不变
```

> 注意：L108（`~/.claude/skills/`）在新旧工程中一致，不需要改。只改 L107。

### 不迁移的文件

| 文件 | 原因 |
|------|------|
| `test_full_flow.sh` | 新工程 `scripts/test_full_flow.sh` 已存在（位置不同，内容可能不同） |
| `scripts/get_repo_root.sh` | 新工程无此文件依赖，确认不需要 |

---

## 7. Step E：测试文件

全部为新文件，直接复制 + 路径修正。

### E1-E4：复制命令

```bash
OLD=/home/h00616010/xyl/AscendC-DevKit
NEW=/home/h00616010/xyl_new/AscendC-DevKit

cp "$OLD/tests/ut/orchestration/test_codegen_regbase_phases.py" "$NEW/tests/ut/orchestration/"
cp "$OLD/tests/ut/skills/conftest.py"                          "$NEW/tests/ut/skills/"
cp "$OLD/tests/ut/skills/test_regbase_script_behavior.py"       "$NEW/tests/ut/skills/"
cp "$OLD/tests/ut/skills/test_regbase_template_invariants.py"   "$NEW/tests/ut/skills/"
```

### E5：修正 test_regbase_template_invariants.py 路径（1 处）

**文件**：`tests/ut/skills/test_regbase_template_invariants.py`

**位置**：L20-22（`_SKILL_DIR` 定义，搜索关键字 `plugins.*stage-codegen`）

**Before**：
```python
_SKILL_DIR = (
    _REPO_ROOT / ".claude" / "plugins" / "stage-codegen"
    / "skills" / "ascendc-op-dev-coding-regbase"
)
```

**After**：
```python
_SKILL_DIR = (
    _REPO_ROOT / ".claude" / "skills"
    / "ascendc-op-dev-coding-regbase"
)
```

### E6：修正 test_regbase_script_behavior.py 路径（1 处）

**文件**：`tests/ut/skills/test_regbase_script_behavior.py`

**位置**：L23-25（`_SKILL_DIR` 定义，搜索关键字 `plugins.*stage-codegen`）

**Before**：
```python
_SKILL_DIR = (
    _REPO_ROOT / ".claude" / "plugins" / "stage-codegen"
    / "skills" / "ascendc-op-dev-coding-regbase"
)
```

**After**：
```python
_SKILL_DIR = (
    _REPO_ROOT / ".claude" / "skills"
    / "ascendc-op-dev-coding-regbase"
)
```

### 测试文件路径依赖检查结果

| 文件 | 硬编码路径 | 是否需要修正 |
|------|-----------|------------|
| `test_codegen_regbase_phases.py` | 无 | ✅ 无需修正 |
| `conftest.py` | 无 | ✅ 无需修正 |
| `test_regbase_template_invariants.py` | `_SKILL_DIR = ...plugins/stage-codegen/skills/...` | ❌ 需修正（见 E5） |
| `test_regbase_script_behavior.py` | `_SKILL_DIR = ...plugins/stage-codegen/skills/...` | ❌ 需修正（见 E6） |

### 测试文件导入依赖检查

`test_codegen_regbase_phases.py` 从 codegen.py 导入的符号：
- `CodegenStage`、`ERROR_WEIGHTS`、`RETRY_LIMITS`、`_FakeAgentResult`
- 以上均在旧版 codegen.py 中定义，迁移后可用 ✅

---

## 8. Step F：配置与脚本

### F1：orchestration-config.json

**文件**：`resources/orchestration-config.json`

**搜索关键字**：`"codegen": 5`

**Before**：
```json
      "codegen": 5,
```

**After**：
```json
      "codegen": 40,
```

### F2：e2e_self_evolve.sh

**文件**：`scripts/e2e_self_evolve.sh`

**策略**：以旧版替换（此文件与 codegen regbase pipeline 配套，旧版是旧工程核心基础设施的一部分）

```bash
cp /home/h00616010/xyl/AscendC-DevKit/scripts/e2e_self_evolve.sh \
   scripts/e2e_self_evolve.sh
```

旧版新增内容（3 处独立改动）：
1. CANN 9.1.0 嵌套目录 `LD_LIBRARY_PATH` 修正
2. `ENABLE_STUBBED` + `--enable-stubbed` 支持
3. `--runtime-target-chip` 参数

### F3：cannbench_eval.py

**文件**：`src/ascendc_devkit/orchestration/stages/cannbench_eval.py`

**策略**：以旧版替换（修复 `torch_npu` autoload 双重注册问题）

```bash
cp /home/h00616010/xyl/AscendC-DevKit/src/ascendc_devkit/orchestration/stages/cannbench_eval.py \
   src/ascendc_devkit/orchestration/stages/cannbench_eval.py
```

### F4：tiling_buffer_kernel.json

**文件**：`tiling_buffer_kernel.json`（284 行，新文件）

```bash
cp /home/h00616010/xyl/AscendC-DevKit/tiling_buffer_kernel.json .
```

---

## 9. Step G：验证

```bash
cd /home/h00616010/xyl_new/AscendC-DevKit

# G1：Python 语法
python3 -c "import ast; ast.parse(open('src/ascendc_devkit/orchestration/stages/codegen.py').read()); print('codegen.py: OK')"
python3 -c "import ast; ast.parse(open('src/ascendc_devkit/orchestration/kernel/state.py').read()); print('state.py: OK')"
python3 -c "import ast; ast.parse(open('src/ascendc_devkit/orchestration/stages/cannbench_eval.py').read()); print('cannbench_eval.py: OK')"

# G2：确认无残留旧路径引用（含测试文件）
! grep -rn "plugins.*stage-codegen\|stage-codegen.*skills" \
  src/ascendc_devkit/orchestration/stages/codegen.py \
  .claude/skills/ascendc-op-dev-coding-regbase/SKILL.md \
  tests/ut/skills/test_regbase_template_invariants.py \
  tests/ut/skills/test_regbase_script_behavior.py \
  && echo "ERROR: stale paths remain" || echo "PASS: no stale paths"

# G3：Regbase UT
python3 -m pytest tests/ut/orchestration/test_codegen_regbase_phases.py -v --timeout=60 2>&1 | tail -20
python3 -m pytest tests/ut/skills/test_regbase_template_invariants.py -v --timeout=60 2>&1 | tail -20
python3 -m pytest tests/ut/skills/test_regbase_script_behavior.py -v --timeout=60 2>&1 | tail -20

# G4：全部 UT 回归（不含 heavy_llm）
python3 -m pytest tests/ut/ -v --timeout=120 -k "not heavy_llm" 2>&1 | tail -30
```

---

## 10. 文件变更矩阵

| 步骤 | 文件 | 操作类型 | 行数变化 |
|------|------|---------|---------|
| A1 | `state.py` | 插入 9 字段 + 注释 | +20 |
| A2 | `state.py` | 插入 10 行迁移条目 | +10 |
| B0 | `codegen.py` | 全文替换 | 1010→1850 |
| B1-B5 | `codegen.py` | 修正 4 个路径字符串 | ~-2 |
| C1 | `ascendc-dev-s5-compile.md` | 新建 | +255 |
| C2 | `ascendc-dev-s2-analysis.md` | 替换 + 1 处修正 | 改动 |
| C3 | `ascendc-dev-s4-coding.md` | 替换 + 4 处修正 | 改动 |
| C4 | `ascendc-coder-regbase.md` | 插入 2 行 | +2 |
| C5 | `ascendc-vf-test-agent.md` | 替换 + 8 处修正 | 改动 |
| D | skill SKILL.md | 替换 | 343→457 |
| D | skill references/ ×4 | 替换 | 改动 |
| D | skill scripts/stage4_scheduler.sh | 替换 | 改动 |
| D | skill tests/test_integration.sh | 新建 | +1010 |
| E | tests/ut/ ×4 | 新建 | +2292 |
| F1 | `orchestration-config.json` | 1 行改动 | 0 |
| F2 | `e2e_self_evolve.sh` | 替换 | 改动 |
| F3 | `cannbench_eval.py` | 替换 | 改动 |
| F4 | `tiling_buffer_kernel.json` | 新建 | +284 |

---

## 11. 不迁移的文件

| 文件 | 原因 |
|------|------|
| `MEMORY.md` | 工程本地 Memory 指针，新工程有独立状态 |
| `decision_log.json` | 工程本地决策日志 |
| `.claude/plugins/stage-codegen/` 下其他 skill（ascendc-dumptensor, ascendc-op-dev-coding, regbase-vf-test） | 不在本次 codegen regbase 变更范围内；regbase-vf-test 已在 `.claude/skills/` 存在 |

---

## 12. codegen.py 结构对比

以旧版（1850 行）替换新版（1010 行）后，新增约 840 行。以下是旧版相较新版增加的完整结构：

```
新版 1010 行                          旧版 1850 行（= 新版 + 以下新增）

                                      import 扩展：+re, +subprocess, +namedtuple, +Path, +ErrorFeedback
                                      ERROR_WEIGHTS / RETRY_LIMITS 常量定义
                                      _FakeAgentResult namedtuple

actions()           ─────────→        actions()  改：按编程模型分派
                                        ├── _actions_membase()     ← 新版 actions() 逻辑迁移至此
                                        └── _actions_regbase()     ← 新增
transition()        ─────────→        transition()  改：按 phase 分派
                                        ├── _transition_membase()  ← 新版 transition() 逻辑
                                        └── _transition_regbase()  ← 新增

                                      Regbase 辅助方法（全部新增）：
                                      ├── _bash()
                                      ├── _regbase_record_dir()
                                      ├── _regbase_skill_root()     ← 含路径搜索，需修正 B1/B2
                                      ├── _regbase_agent_root()
                                      ├── _regbase_scripts_dir()
                                      ├── _regbase_vf_ref_dir()     ← 含路径搜索，需修正 B3
                                      ├── _is_vf_step()
                                      ├── _check_section_dirs_have_files()
                                      ├── _code_path_has_source_files()
                                      ├── _update_meta_retries()
                                      ├── _regbase_ensure_init()

                                      Regbase 专用方法（全部新增）：
                                      ├── _actions_regbase_s2/s4/s4_step/vf/s5/needs_agent
                                      ├── _transition_regbase_s2/s4/s5/needs_agent_done
                                      ├── _is_code_step()
                                      ├── _handle_regbase_failure()
                                      ├── _skill_trigger()
                                      ├── _with_trigger()
                                      ├── _build_s2_prompt()
                                      ├── _build_s4_prompt()
                                      ├── _build_vf_prompt()
                                      └── _build_s5_prompt()
```

## 13. 全量修改点索引

以下按执行顺序列出所有修改点，可逐项核对。

| ID | 步骤 | 文件 | 行号 | 操作 | 搜索关键字 |
|----|------|------|------|------|-----------|
| A1 | Step A | `kernel/state.py` | L217 后 | 插入 9 个 dataclass 字段 | `codegen_consecutive_failures: int = 0` |
| A2 | Step A | `kernel/state.py` | L486 后 | 插入 10 行迁移条目 | `("design_known_issues", []),` |
| B0 | Step B | `stages/codegen.py` | 全文 | 旧版文件复制替换 | — |
| B1 | Step B | `stages/codegen.py` | L211 | 改 DevKit skill 路径 | `devkit_candidate =` |
| B2 | Step B | `stages/codegen.py` | L220 | 改 repo skill 路径 | `"plugins" / "stage-codegen"` |
| B3 | Step B | `stages/codegen.py` | L252 | 改 VF ref 路径 | `def _regbase_vf_ref_dir` |
| B4 | Step B | `stages/codegen.py` | L745 | 改注释中 slash command 格式 | `as a slash command` |
| B5 | Step D | `skills/.../SKILL.md` | L107 | 改 SKILL_ROOT 第 1 条路径 | `realpath .claude/plugins` |
| C1 | Step C | `agents/ascendc-dev-s5-compile.md` | 全文 | 旧版文件复制（新文件） | — |
| C2 | Step C | `agents/ascendc-dev-s2-analysis.md` | 全文+修正 | 旧版复制 + L328 改 VF 路径 | `plugins.*stage-codegen.*regbase` |
| C3 | Step C | `agents/ascendc-dev-s4-coding.md` | 全文+修正 | 旧版复制 + L174/220/251/252 改 VF 路径（4处） | `plugins.*stage-codegen.*regbase` |
| C4 | Step C | `agents/ascendc-coder-regbase.md` | L18 后 | 插入 `disallowed_tools` 2 行 | `- TaskUpdate` |
| C5 | Step C | `agents/ascendc-vf-test-agent.md` | 全文+修正 | 旧版复制 + 修正 8 处 VF 路径 | `plugins.*stage-codegen.*regbase` |
| D1 | Step D | `skills/.../SKILL.md` | 全文 | 旧版文件复制替换 | — |
| D2 | Step D | `skills/.../env-and-platform.md` | 全文 | 旧版文件复制替换 | — |
| D3 | Step D | `skills/.../orchestrator-logic.md` | 全文 | 旧版文件复制替换 | — |
| D4 | Step D | `skills/.../phase-c-prompts.md` | 全文 | 旧版文件复制替换 | — |
| D5 | Step D | `skills/.../coding-plan-template.md` | 全文 | 旧版文件复制替换 | — |
| D6 | Step D | `skills/.../stage4_scheduler.sh` | 全文 | 旧版文件复制替换 | — |
| D7 | Step D | `skills/.../test_integration.sh` | 全文+修正 | 旧版复制 + L315 改 VF 路径 | `plugins.*stage-codegen.*vf-instructions` |
| E1 | Step E | `tests/ut/.../test_codegen_regbase_phases.py` | 全文 | 旧版文件复制（新文件） | — |
| E2 | Step E | `tests/ut/skills/conftest.py` | 全文 | 旧版文件复制（新文件） | — |
| E3 | Step E | `tests/ut/skills/test_regbase_script_behavior.py` | 全文+修正 | 旧版复制 + L23-25 改 `_SKILL_DIR` | `plugins.*stage-codegen` |
| E4 | Step E | `tests/ut/skills/test_regbase_template_invariants.py` | 全文+修正 | 旧版复制 + L20-22 改 `_SKILL_DIR` | `plugins.*stage-codegen` |
| F1 | Step F | `orchestration-config.json` | L75 | `"codegen": 5` → `"codegen": 40` | `"codegen": 5` |
| F2 | Step F | `e2e_self_evolve.sh` | 全文 | 旧版文件复制替换 | — |
| F3 | Step F | `cannbench_eval.py` | 全文 | 旧版文件复制替换 | — |
| F4 | Step F | `tiling_buffer_kernel.json` | 全文 | 旧版文件复制（新文件） | — |

**统计**：
- 全文复制替换：11 个文件
- 全文复制 + 路径修正：7 个文件（SKILL.md + s2 + s4 + vf-test-agent + test_integration.sh + 2 个测试文件）
- 行级精确修改：6 处（A1, A2, B1, B2, B3, B4, C4, F1 = 8 个行级修改点）
- 新文件创建：7 个（C1, D7, E1-E4, F4）

## 14. 回滚

```bash
# 出问题时直接切回 main
cd /home/h00616010/xyl_new/AscendC-DevKit
git checkout main
git branch -D migrate/codegen-regbase
```
