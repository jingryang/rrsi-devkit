# PR 质量门方案（CI 主 + 本地 hook 可选）

> 状态：方案已定（CI 跑 `not heavy_llm`），待 gitcode 平台确认后落 `.yml`。
> 关联：本地脚本 `scripts/pre_pr.sh`、`scripts/install_hooks.sh`（已落盘）；CONTRIBUTING.md。

## 一、问题（L1）

多人向本仓提 PR，维护者无法逐一把控质量。要求每个 PR 提交前自检——通过 review skill + 通过 UT 及非 heavy_llm。

现有的本地机制（`scripts/pre_pr.sh` + pre-push hook）是**自觉执行、可绕过**的：不装 hook / 不跑脚本的人照样能提 PR。需要一道**远端强制硬门**兜底，把"自觉"变成"必须"。

## 二、决策（L3）

**CI 范围 = `pytest -m "not heavy_llm"`**：除 heavy_llm 外，UT 全量 + 所有 ST（含 llm / npu / cann）都要在 CI 跑。

| 候选范围 | 用例数 | 取舍 |
|---|---|---|
| ~~`pytest --quick`~~ | 2737 | 排除 llm/npu/cann，覆盖不到真实链路——**不选** |
| **`pytest -m "not heavy_llm"`** | **2758** | **选定**：覆盖真实 NPU/LLM/CANN 链路（§3.9）；代价是 runner 必须配齐 NPU+CANN+LLM |
| ~~含 review skill~~ | — | review 是 LLM 判断（分钟级 + token + 产物消费复杂），CI 只承担机械测试硬门；设计原则审查靠本地 `pre_pr.sh` / 人工 |
| heavy_llm | 23 | §3.11：分钟级 + 高 token，CI 不跑；由人在特性交付 / PR 合并前决策单独跑 |

核心理由：CI 是"机械可验证的硬门"，跑测试 pass/fail；review skill 的"设计原则审查"是 LLM 判断，留本地/人工。CI 不碰 LLM 判断类工作，只保证测试真实通过。

## 三、CI 实施（L4）

### 3.1 runner 要求（self-hosted，配齐真实环境）

普通云 runner 无 NPU，跑不了。需 **self-hosted runner**，镜像/机器预装：

- python 3.11+、git
- **NPU**：driver + torch_npu + device（`torch.npu.device_count > 0`）
- **CANN**：`ccec` / `bishengir-compile` / `asc_opc` 之一在 PATH
- **LLM**：opencode 凭证（`baseURL` + `apiKey`，经 CI secrets 注入 `opencode.json`）或 claude 可达——因为 `not heavy_llm` 含普通 `@llm` 用例
- 本仓 checkout + `pip install -e ".[dev]"`（含 pytest；`install_devkit.sh` 只装核心依赖、**不带 [dev]**）

### 3.2 触发

PR 创建 / 更新（target: `main`）。

### 3.3 CI 配置草稿

> 文件路径与语法待 gitcode 确认（§五）。以下为 GitHub Actions 兼容语法，Gitea 系多半兼容。

```yaml
# 路径待定：.github/workflows/pr-check.yml | .gitea/workflows/pr-check.yml | gitcode 自有路径
name: PR Check
on:
  pull_request:
    branches: [main]
jobs:
  pytest-not-heavy-llm:
    runs-on: [self-hosted, ascend-npu]   # 带 NPU 的自建 runner
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - name: Install DevKit with dev deps (pytest)
        run: pip install -e ".[dev]"
      - name: Write opencode.json from secret   # LLM 凭证（not heavy_llm 含 @llm 用例）；仓根 opencode.json 被 .gitignore 排除，不污染仓库
        run: printf '%s\n' "${{ secrets.OPENCODE_JSON }}" > opencode.json
      - name: pytest (not heavy_llm)
        run: python -m pytest -m "not heavy_llm"
```

### 3.4 环境预检

conftest 自动预检 LLM/NPU/CANN。CI（非交互）下：三者齐 → 直接跑；缺失 → 默认 abort（诚实报错 §3.7，**不打桩**）。runner 必须配齐，否则 CI 红。

**边界**：`external_repo` 用例（依赖 cann-bench / ops-nn 兄弟仓）在 CI 上会 `skip`（conftest 非 TTY 仅 banner、不 abort）。要让这部分也跑，需在 runner 上挂载这两个参考仓。

### 3.5 分支保护（硬强制的关键）

CI 跑通只是"能跑"；要"阻断 merge"，必须在 **gitcode 仓库设置里给 `main` 开分支保护**：合并前必须通过 `PR Check` 状态检查。**不开这个，CI 失败了照样能合**，硬门形同虚设。

## 四、本地可选方案：pre-push hook

CI 是远端兜底；本地 hook 提供 push 前的**即时反馈**（秒级、不占 CI 排队、不烧 CI 资源）。

- **装**：`bash scripts/install_hooks.sh`（一次性；`.git/hooks` 不进版本控制，需手动装）
- **跑**：`pytest --quick`（2737，无 NPU/LLM 依赖，秒级）——本地快速反馈，不需要 runner 级环境
- **跳过**：`PRE_PUSH_SKIP=1 git push`

hook 用 `--quick`（本地快速筛），不跑完整 `not heavy_llm`（那需本地有 NPU，且 push 前跑全量太慢）。完整范围 + review skill 用手动的 `scripts/pre_pr.sh <分支>`。

## 五、gitcode 待确认（落地前置）

1. **gitcode 原生 CI 机制**：语法是 `.github/workflows` 兼容 / `.gitea/workflows` / 自研 yaml？决定 §3.3 草稿放哪、要不要改写。
2. **runner 来源 + 架构**：gitcode 托管 runner 还是 self-hosted？架构 aarch64（本仓生产架构）？
3. **NPU runner 可得性**：带 NPU 的 self-hosted runner 是否就绪 / 是否排队（稀缺）——这是 CI 范围可行性的硬约束。若 NPU runner 不可得，CI 只能退回 `--quick`（覆盖不到真实链路）。
4. **分支保护**：「合并前必须通过状态检查」在 gitcode 哪里配？

## 六、覆盖矩阵

| 门 | 范围 | 用例 | 触发 | 环境 | 强制力 |
|---|---|---|---|---|---|
| **CI** | `not heavy_llm` | 2758 | PR 提交 | NPU+LLM+CANN runner | **硬**（分支保护阻断 merge） |
| pre-push hook（可选）| `--quick` | 2737 | git push | 无外部依赖 | 软（`PRE_PUSH_SKIP` 可绕过） |
| `scripts/pre_pr.sh`（手动）| `not heavy_llm` + review skill | 2758 + review | 人工 | 本地 NPU+LLM | 自觉 |
| heavy_llm | `heavy_llm` | 23 | 人工决策 | LLM+NPU | 特性交付 / 合并前 |

## 七、失败处理

CI / hook 失败 → §3.4 必修根因，禁止 `pytest.skip()` / `try/except pass` / 条件跳过掩盖。环境缺失是前置条件问题，诚实报错、不打桩（§3.7）。

## 八、与现有本地脚本的关系

- `scripts/pre_pr.sh`（已落盘）：手动完整自检（`pytest not heavy_llm` + `skill run` review + parse verdict）。
- `scripts/install_hooks.sh`（已落盘）：装 pre-push hook（§四）。
- **本方案新增**：CI 配置（§3.3，待 gitcode 确认后落 `.yml`）+ `main` 分支保护（§3.5）。
