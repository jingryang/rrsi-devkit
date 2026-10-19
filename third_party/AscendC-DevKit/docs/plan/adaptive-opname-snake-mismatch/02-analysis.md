# adaptive_avg_pool_3d 361001 — 注册名派生源错位修复方案（L3）

> 层级：**L3 / 方案分析**。记录选项、选哪个、为什么。
> L1 事实见 `01-problems.md`（含改名复验闭环）。本文回答：
> **codegen 的注册名（OP_ADD / ADD_TO_LAUNCHER）应从哪个名派生，才能让 runtime 反推命中落盘
> config 产物、避免 361001。**

## 0. 决策总览

| # | 决策 | 状态 |
|---|------|------|
| D0 | **源头单一派生规则**：注册名（Pascal）必须从**落盘目录名 / op_name（golden snake）**经 `snake_to_pascal` 派生，**不直接抄 proto 的 `operator.name`** | ✅ 拍板（见 §1） |
| D1 | **机械校验**：codegen 出口校验「注册名反推的 config 名 == 实际落盘 config 名」，不等则拦（§1.3） | ✅ 拍板（见 §2） |
| D2 | 不做"deploy 后补发副本"兜底为主方案（仅作历史产物保险，见 §4） | ✅ 拍板 |
| D3 | 不动上游命名、不改 runtime、不教模型推导反推公式 | ✅ 拍板 |

---

## 1. 源头（本方案核心）：注册名从落盘目录名派生，而非从 proto 抄

### 病根（实测钉死）

runtime 反推 config 名的输入 = **coder 写的注册名**（`ADD_TO_LAUNCHER_LIST_AICORE` + `OP_ADD`），
不是 proto、不是 golden、不是任何锁死的值。coder 当前从 **proto 的 `AdaptiveAvgPool3D`（大写 D）**
抄进注册名 → runtime 反推 `adaptive_avg_pool_3_d` ≠ 落盘 config `adaptive_avg_pool_3d` → 361001。

**同一算子上，注册名写法决定成败**：
| 注册名写法 | runtime 反推 | 落盘 config | 结果 |
|---|---|---|---|
| `AdaptiveAvgPool3D`（大写D，抄 proto）| `adaptive_avg_pool_3_d` | `adaptive_avg_pool_3d` | ❌ 361001 |
| `AdaptiveAvgPool3d`（小写d，从落盘名派生）| `adaptive_avg_pool_3d` | `adaptive_avg_pool_3d` | ✅ 命中 |

### 派生规则（一条，通用）

**注册名 Pascal = `snake_to_pascal(落盘目录名末段)`**，其中落盘目录名 = 编译器派生 config 文件名的
机制真源（`op_file = op_dir + '.json'`）：无前缀仓 = `state.op_name`（golden 入口函数名派生，§1.13
golden 权威），带前缀 profile（如 omni-ops `ai_infra_`）= 前缀 + golden snake（≠ strip 后短名，
比对/派生均须用目录名——review 阶段发现并修正）。验证该规则对各类落盘名往返闭合：

| 落盘名 | `snake_to_pascal` | runtime camelsnake 反推 | 命中? |
|---|---|---|---|
| `adaptive_avg_pool_3d` | `AdaptiveAvgPool3d` | `adaptive_avg_pool_3d` | ✅ |
| `add` | `Add` | `add` | ✅ |
| `sqrt` | `Sqrt` | `sqrt` | ✅ |
| `conv_2d` | `Conv2d` | `conv_2d` | ✅ |

`snake_to_pascal` = cann-bench eval 已用同一函数（`cannbench_scorer.py:559`），即"每个 `_` 分隔段首字母
大写后拼接"——**该函数与 runtime camelsnake 对「落盘名 → Pascal → 落盘名」往返闭合**（数字段 `_3d`
段 capitalize 得 `3d` 不破坏，runtime 反推还原 `_3d`）。

### 为什么之前"教模型识别分叉"是错的（D0 修正记录）

早稿方案（本文件历史版本）设「源头 = 模型识别身份分叉 + 机械判定」，假设注册名/落盘名被上游锁死、
只能识别后补发。**深挖证伪**：注册名是 coder 可写、可从落盘名派生的——不是不可改的外部约束。
正确源头 = 让 coder 按**正确派生源**写注册名，而非识别"已经写错的分叉"。这更简单、更直接，
也不需要模型懂反推规则（反推规则只由派生函数保证，模型照抄落盘名即可）。

### 落地位置（skill / 渲染规格，§2.7 非核心脚手架归 LLM 现场）

- `.claude/skills/ascendc-op-dev-coding/SKILL.md`：注册名（`OP_ADD`/class/`ADD_TO_LAUNCHER`）派生指令，
  明确"从 `state.op_name`（snake）经 `snake_to_pascal` 派生 Pascal；**不直接抄 proto `operator.name`**"。
- `OpDef渲染规格映射.md:184`：`class 名 = op_name（首字母大写保 PascalCase）`——这条本身没错（op_name
  是 snake），但需明确 **op_name 权威源 = 落盘目录名/state.op_name**，且 example 不应示范 Pascal `"Add"`
  误导（schema example `"op_name": "Add"` 与 golden snake 冲突，见 01-problems）。
- req-analysis schema：op_name 语义补"以 golden 入口函数名为准（snake）"，不示范 Pascal。

### 为什么 codegen 内部现在有两个 op_name 来源（附带修正 req/design 分叉）

链条上有两个 op_name：`state.op_name`（snake/golden，batch 派生）vs design_spec/requirement 的
Pascal（proto 抄）。本方案**不要求消除这个并存**（下游各有用途），只要求**注册名（影响 runtime 反推）
跟 state.op_name 派生**。若 design_spec.op_name 保持 proto Pascal，须明确它**不用于注册名派生**，
仅作参考/文档。

## 2. 机械校验（§1.3 生成期拦截）：注册名派生正确性的硬保证

- **位置**：codegen 产物收尾、compile 前（与既有契约校验同层）。
- **动作**：读 coder 产出的注册名（从 def.cpp `OP_ADD` / op_api `ADD_TO_LAUNCHER` 提取）+
  `state.op_name`（落盘目录末段），断言「`runtime_camelsnake(注册名)` ∈ {落盘名, ...}」或
  「注册名 == `snake_to_pascal(落盘名)`」。不等 → 生成期报错，指引"注册名应从 op_name（落盘目录名）
  经 snake_to_pascal 派生，勿抄 proto 的 Pascal"。
- **为什么需要**：派生规则是知识（§1），模型可能漏/错 → 机械校验兜住（§1.3 加载期校验优先）。
- 判定函数单点实现（`runtime_camelsnake` 复刻 runtime 反推），不依赖模型。

## 3. 落盘名与 op_name 的既有关联（不改动，仅说明）

落盘目录名 = batch 从 golden 函数名派生（`batch_self_evolve.sh` `csrc/ops/$op`），`state.op_name`、
`golden_entry`、落盘目录四者同源。本方案不改 batch、不改落盘名、不改 golden——只改 coder 派生
注册名的**来源**（从落盘名而非 proto）。

## 4. 兜底（降级为历史产物保险，非主方案）

对**已生成的、注册名已错位的历史产物**（本方案上线前），deploy 后补发 config 候选名副本
（复验闭环已验证有效）。新产物走 §1/§2 源头不再错位，兜底仅覆盖存量。

## 5. 验证（§3 TDD）

1. **UT（派生规则）**：对含 `_3d`/`_2d`/多下划线/无数字段落盘名，断言 `runtime_camelsnake(snake_to_pascal(落盘名)) == 落盘名`。
2. **UT（机械校验）**：coder 注册名 = `AdaptiveAvgPool3D`（抄 proto）→ 校验拦；= `AdaptiveAvgPool3d`（派生）→ 放行。
3. **复验**：adaptive task（`adaptive_avg_pool_3d`）上 coder 按派生规则写注册名 → runtime 命中 → 361001 消失。
4. **回归**：add/sqrt（注册名本就从落盘派生）不受影响。

## 6. 不做清单

- 不改 runtime 反推规则（CANN）。
- 不改上游 task 命名 / golden / proto。
- 不教模型推导反推公式（规则由派生函数 + 机械校验保证）。
- 不加产物 checkpoint/回炉等控模型 gate。
