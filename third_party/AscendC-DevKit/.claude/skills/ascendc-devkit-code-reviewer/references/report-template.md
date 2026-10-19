# Review 报告模板

## ⚠️ 可读性要求（强制）

报告必须**自包含、可独立读懂**——读者没读过被审代码、没参与 review，也要能看懂每条 finding。
为此硬性规定：

1. **报告开头必须有一段「背景」**：被审模块的架构 / 关键机制 / 数据流，只写「理解下面 finding 必需」的部分（通常 3-10 行）。不要假设读者知道 `_phase_path` 是干什么的、history 是谁写的。
2. **每条 blocker / major finding 用四段式**，缺一不可：
   - **背景**：这段代码的职责 + 它所在的数据流。为什么存在这个机制。（没这层，问题看不懂）
   - **问题**：具体哪里错。`file:line` + 关键代码片段或调用序列。
   - **影响**：不修会怎样。**具体的功能后果**（不是"可能有问题"）。
   - **建议**：怎么修。
3. **先汇总表（扫读），再详述（每条 blocker/major 单独成节，四段式）**。minor 可只在汇总表里带一句「位置 + 一句话」，但一句话也要让人看懂在说什么。
4. 禁止只有「`substages.py:97 — 路径漂移`」这种 insider 电报体。

---

## 人读 Markdown：`reviews/PR-<N>-review.md`

````markdown
# PR #<N> Review — <一句话标题>

- **分支/HEAD**: `<branch>` @ `<sha>`
- **基线 / 规模 / Verdict / 测试**: <一行汇总>

## 背景：<被审模块的架构与数据流>
<让读者理解 finding 必需的上下文。这模块干什么、关键机制、数据怎么流。
只写理解问题需要的部分，3-10 行。配一个小数据流示意更佳。>

## Findings 汇总
| # | Sev | 维度 | 位置 | 一句话（非行话） |
|---|---|---|---|---|
| B1 | blocker | D6 | substages.py:97 | <用读者能懂的话> |

## 详述

### 🔴 B1 (blocker) — <标题>
**背景**：<这段代码的职责 + 数据流。这个机制为什么存在。>
**问题**：<具体哪里错。file:line + 代码片段 / 调用序列。>
**影响**：<不修会怎样。具体功能后果。>
**建议**：<怎么修。>

### 🔴 B2 (blocker) — <标题>
（同四段式）

### 🟠 M1 (major) — <标题>
（同四段式，可更简）

## 🟡 Minors
<汇总表即可，但每条一句话要让人看懂>

## 测试详情
- UT / ST 非-heavy / heavy_llm：命令 + 结果 + 失败定性（环境 vs PR）

## 整改优先级 / 亮点 / review 元信息
````

## 机读 JSON：`reviews/PR-<N>-review.json`

```json
{
  "pr": {"number": "<N>", "head_sha": "...", "base_sha": "...", "branch": "pr-<N>-review"},
  "verdict": "request_changes",
  "background": "<供 bot 消费的简短架构背景，1-2 句>",
  "findings": [
    {"id": "B1", "severity": "blocker", "dimension": "D6", "rule": "§1.2",
     "file": "...", "lines": "...",
     "context": "<背景：这段代码干什么>",
     "evidence": "<问题：代码片段/调用序列>",
     "impact": "<不修的后果>",
     "suggestion": "<怎么修>"}
  ]
}
```

> JSON 加 `context`/`impact` 字段，让未来 gitcode 自动 review bot 贴的评论也带得上背景。

## verdict 判定
- `approve`：无 blocker/major，minor/nit 可选。
- `approve_with_minor`：仅 minor/nit。
- `request_changes`：存在 major（建议修后再合）。
- `reject`：存在 blocker（硬伤，不应合）。
