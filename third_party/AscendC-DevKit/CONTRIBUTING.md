# 贡献指南（提 PR 前自检）

本仓所有 PR 在提交前 **必须** 通过自检。自检已规则化为一条命令，无需手动逐项查。

## 一句话流程

```bash
# 1.（一次性）安装 push 前自动兜底
bash scripts/install_hooks.sh

# 2. 提 PR 前跑完整自检（两段：pytest 硬门 + review skill）
scripts/pre_pr.sh <你的分支名>
```

`scripts/pre_pr.sh` 做三件事：

1. **pytest 硬门**：`pytest -m "not heavy_llm"`（UT 全量 + 非 heavy_llm ST，需真实 LLM/NPU/CANN 环境）。不过直接退出，不浪费 token。
2. **review skill**：`ascendc-devkit skill run ascendc-devkit-code-reviewer`，对当前分支的净变更做设计原则 + 测试真实性 + 方案合理性审查（CLAUDE.md §1/§2/§3/§4），产出 `reviews/PR-*-review.{md,json}`。
3. **判定**：读 `verdict` —— `approve` / `approve_with_minor` 通过（exit 0）；`request_changes` / `reject` 不通过（exit 1）。

## 后端选择（claude / opencode）

review skill 走 DevKit 的 `skill run`，双后端统一、默认 **opencode**：

```bash
ASCENDC_AGENT_BACKEND=claude scripts/pre_pr.sh <分支>   # 强制 claude
# 或写进 resources/orchestration-config.json 的 agent_backend.kind
```

两个后端的 skill 注入由 DevKit 在 backend 边界统一处理（claude 加 `/<skill>`、opencode 加 system steer），脚本不感知差异。

## 常用选项（环境变量）

| 变量 | 作用 |
|---|---|
| `PRE_PR_QUICK=1` | ① 段改用 `pytest --quick`（排除 llm/npu/cann，秒级、无环境依赖）—— 无 NPU/LLM 时用 |
| `PRE_PR_SKIP_PYTEST=1` | 跳过 ① 段 |
| `PRE_PR_SKIP_SKILL=1` | 跳过 ② 段（LLM 不可达时；只跑 pytest 硬门） |
| `PRE_PUSH_SKIP=1 git push` | 临时跳过 pre-push hook |

## 关于 heavy_llm（§3.11）

`heavy_llm`（端到端 LLM 全流程，分钟级 + 高 token）**默认不跑**，`pre_pr.sh` 也不自动纳入。特性交付 / PR 合并前，应由人在关键节点决策跑一次：

```bash
python -m pytest -m "heavy_llm"    # 单独跑，跑前确认耗时与成本
```

## 失败必须修根因（§3.4）

自检失败时禁止用 `pytest.skip()` / `try/except pass` / 条件跳过绕过。定位根因、修复、再跑直到通过。环境缺失是前置条件问题，诚实报错、不打桩（§3.7）。
