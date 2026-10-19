
# Design — 算子设计

> **所属架构**：[ascendc-devkit 架构总览](../architecture-overview.md) > §3 统一 Pipeline
> **实现状态**：已实现 ✓（自动注册, 由 GraphExecutor 经 CompositeGroup + AtomicStage 驱动）
> **位于 L3**: `orchestration/stages/design_substages.py`（细粒度 substage）+ `orchestration/design_tree.py`（组装）

---

## 1. 定位

基于结构化的需求规格，生成算子设计——Tiling 策略、Kernel 架构、数据流。新生成模式做完整设计；增量模式在已有设计上做 delta，只改受影响的部分。

---

## 2. Mode 差异

| 维度 | mode=new | mode=incremental |
|---|---|---|
| 输入 | Requirement + 参考代码 | ChangeRequirement + 已有算子代码 |
| 设计范围 | 完整算子 + Tiling 策略 | 只改受影响部分 |
| Tiling 审查 | 完整策略设计 | 变更策略与现有策略的兼容性 |

---

## 3. IO 契约

### 3.1 input_contract

```python
def input_contract(self) -> StageIOContract:
    return StageIOContract(
        requires=["requirement", "mode"],
        optional=["op_identity", "reference_code", "profile"]
    )
```

### 3.2 output_contract

```python
def output_contract(self) -> StageIOContract:
    return StageIOContract(
        provides=[
            "design_spec",               # 算子设计规格
            "tiling_strategy",           # Tiling 策略描述
            "kernel_architecture",       # Kernel 架构（类/函数拆分）
            "data_flow",                 # 数据流描述 (Init/CopyIn/Compute/CopyOut)
        ]
    )
```

---

## 4. Gate

`RequirementCompleteGate`：需求分析阶段产出了有效的 `requirement`（所有不明确项已澄清）。

---

## 5. 编排结构（细粒度 substage）

design 不再是单发一个 agent 的原子 stage，而是一组 substage 的编排（`design_tree.py` 组装，
`design_substages.py` 实现），概设组 + 详设组：

```
概设组：  gd-generate → general-design-review
详设组：  dd-intake（详设输入短路入口）→ template-division
          → tiling[ split / buffer-kernel / precision-perf ] （按模板 fork-join 并行）
          → anchor-check → integrate → docgen → validate
```

每个 substage 在 `actions()` 里 `SpawnAgent`，复用 A/B/C 三个角色 agent，并按 `STAGE_SKILL_MAP`
（`resources/orchestration-config.json` 的 `skills` 段）指派本步骤的 stage-design skill。skill 的
设计方法通过 spawn 首条消息以 `/stage-design:<skill>` 开头触发注入（本 CLI 把 plugin skill 暴露
为 slash command）。

```python
# 每个 substage 的 actions() 共性（_DesignSubstage.actions）
def actions(self, state, iteration=1):
    skill = STAGE_SKILL_MAP.get(self.name)          # D7 集中配置
    return [SpawnAgent(
        agent_name=self.agent_name,                 # 角色 A/B/C
        prompt=self._with_trigger(self._build_prompt(state, iteration)),  # 首行 /stage-design:<skill>
        context=self._context(state),
        skills=[skill] if skill else None,
        working_dir=self._working_dir(state),        # tiling 段按 <template> 隔离
        stage_name=self.name, branch_label=self._branch_label())]
```

---

## 6. Agent 交互（A/B/C 三角色）

| 角色 agent | 权限 profile | 服务的 substage | 指派 skill（stage-design:） |
|---|---|---|---|
| `ascendc-design-generator`（A 生成） | Read/Write/Edit/Bash/Glob/Grep | gd-generate / dd-intake / template-division / split / buffer-kernel / precision-perf / integrate | 各 substage 对应的生成 skill |
| `ascendc-design-reviewer`（B 评审） | 去 Write，只就地 Edit | general-design-review / validate | general-design-review / validate |
| `ascendc-design-anchor`（C 外部锚点） | 禁 Write/Edit（disallowed_tools） | anchor-check | anchor-check |

**design_spec/tiling_strategy/kernel_architecture 的唯一权威来源**：
- 正常流 = `integrate` 整合所有模板的 tiling 产物；
- 详设输入短路流 = `dd-intake` 把用户提供的详设文档解析为三件套。

docgen 不 spawn agent（由 `DocgenStage` 确定性渲染）。

---

## 7. 错误分类

| 错误 | 类别 | 处理 |
|---|---|---|
| substage 设计不完整（缺少关键部分） | Recoverable | 注入 feedback，对应角色 agent 补充 |
| anchor-check 判 tiling 不可实现（AC0/AC1/AC2） | Recoverable | 回退对应 tiling 段重做（GraphExecutor 路由） |
| 增量模式：变更与现有设计冲突 | User-input | 提示用户确认优先级 |
| Agent 响应超时 | Transient | 自动重试 |

---

## 8. 迭代行为

`max_iterations = 10`（代码默认；可在 `resources/orchestration-config.json` 的 `iterations.stages.design` 全局调整）。设计迭代通常 1-2 次即收敛——Tiling 策略审查反馈一轮即可。

**回退入口**：design 作为升级（escalation）目标，只接收来自 perf 的 `redesign`（性能穷尽战术调优后的战略性重设计）。verify 的编译/精度失败穷尽后走 `__halt__` 停机，**不再**回退到 design——详见 `docs/stages/verify.md` §9。此外 design 自身在收到不完整 requirement 时会 corrective 回退到 requirement 重新澄清。

---

## 9. 事件 schema

```jsonl
{"ts":"...","type":"stage_enter","stage":"design","stage_name":"gd-generate"}
{"ts":"...","type":"action_start","action":"spawn_agent","agent":"ascendc-design-generator","stage_name":"gd-generate","skills":["stage-design:ascendc-op-general-design"]}
{"ts":"...","type":"action_complete","action":"spawn_agent","result":"ok"}
{"ts":"...","type":"action_start","action":"spawn_agent","agent":"ascendc-design-generator","stage_name":"split","branch_label":"T1_Half","skills":["stage-design:ascendc-op-tiling-split"]}
{"ts":"...","type":"action_start","action":"spawn_agent","agent":"ascendc-design-anchor","stage_name":"anchor-check","skills":["stage-design:ascendc-op-design-anchor-check"]}
{"ts":"...","type":"stage_complete","stage":"design","elapsed_ms":180000}
```

---

## 10. 与邻 Stage 的关系

| 方向 | Stage | 传递数据 |
|---|---|---|
| 前置 | requirement | requirement, op_identity |
| 后置 | codegen | design_spec, tiling_strategy, kernel_architecture |
