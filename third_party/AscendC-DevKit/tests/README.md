# 测试手册

## 快速开始

```bash
# 默认全量模式 — UT + ST 全部，走真实 LLM/NPU/CANN 环境
# 任一环境缺失时报错并询问是否继续（非交互/CI 默认中止），绝不静默打桩
pytest

# 快速开发模式 — 排除 llm/npu/slow/cann 标记，跳过环境预检，秒级反馈
pytest --quick

# 仅单元测试（UT 目录，天然无外部依赖，不触发预检）
pytest --ut

# 仅系统测试（ST 目录）
pytest --st

# 仅列出匹配用例，不执行（不触发预检）
pytest --collect-only --st -m llm
```

## 设计原则：默认真实环境，缺失即报错

默认 `pytest` 跑全量真实环境，而不是静默回退到桩模式。原因：每遇到错误就打桩会
掩盖大量真实问题（编译错误、精度问题、API 失败等）。因此默认行为是：

- 预检 LLM / NPU / CANN 三类真实环境；
- 任一缺失时，**报错并列出缺失项**，再由用户决定是否继续；
- 非交互/CI（无 TTY）默认中止，避免无人应答时挂起；
- 用户选择继续时，相关用例若失败将**如实报告**，不做打桩。

开发者想快速验证时，主动用 `--quick` 或 `-m` 排除对应标签，或显式传
`enable_stubbed=True`（用例内）走桩——打桩必须是显式选择，而非失败兜底。

## CLI 选项

| 选项 | 来源 | 说明 |
|---|---|---|
| `pytest` | 原生 | **默认全量**：跑所有用例，预检 LLM/NPU/CANN，缺失则询问/中止 |
| `--quick` | **新增** | 快速开发模式：排除 `llm`/`slow`/`npu`/`cann`，跳过环境预检 |
| `--st` | 新增 | 仅收集 `tests/st/` 目录 |
| `--ut` | 新增 | 仅收集 `tests/ut/` 目录（不触发预检） |
| `-m "llm or slow"` | 原生 | 标记 OR 组合筛选（显式 -m 覆盖默认，按你写的执行） |
| `-m "not cann"` | 原生 | 排除 `cann` 标记 |
| `-k "keyword"` | 原生 | 用例名关键字筛选 |
| `--collect-only` | 原生 | 仅列出匹配用例，不执行（不触发预检） |
| `--no-env-check` | 新增 | 跑全量但跳过环境预检（自担风险） |

## 环境预检

默认全量模式下，pytest 在**收集测试之前**预检 LLM / NPU / CANN，缺失则汇总报告
并询问是否继续。

### CANN 预检（新增）

复用运行时同一套 `CANNToolchain` 检测：要求 `ops_compile` **真正在 PATH 中**
（仅设置 `ASCEND_TOOLKIT_HOME` 不算通过）。失败时给出精准修复指引——区分
“装了 CANN 但未 source set_env.sh”与“未安装 CANN”，前者直接给出
`source <set_env.sh>` 命令。

### LLM 预检（两阶段）

1. **凭据检查** — 验证 `.claude/settings.json` 或环境变量中存在 `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN`
2. **连通性检查** — 发送极简 `"hi"` 请求（`max_tokens=1`），验证 endpoint 可达且模型正常响应

连通性检查优先使用 Anthropic 原生格式（`POST /v1/messages`, `x-api-key` 认证），404/405 时自动 fallback 到 OpenAI 兼容格式（`POST /v1/chat/completions`, `Bearer` 认证）。

### NPU 预检

- 依次检查 `torch_npu` 导入、NPU 驱动、NPU 设备（`device_count() > 0`）

### 缺失时的决策

- 交互式（有 TTY）：打印缺失项 + 修复指引，询问 `是否仍要继续运行？ [y/N]`；
- 非交互/CI（无 TTY）：默认中止，退出码 1；
- 自动化中确需跑可用子集：设 `ASCENDC_TEST_CONTINUE_ON_MISSING=1` 强制继续。

### 跳过预检

```bash
# 快速开发：排除外部依赖标记，自动跳过预检
pytest --quick

# 跑全量但显式跳过预检（自担风险，相关用例可能失败）
pytest --no-env-check

# 仅收集用例名（不需要环境）
pytest --collect-only --st
```

## 预检触发规则

预检仅在**实际可能选中对应标记的用例**时触发：

| 命令 | LLM | NPU | CANN | 说明 |
|---|---|---|---|---|
| `pytest` | ✅ | ✅ | ✅ | 默认全量，预检三类环境 |
| `pytest --quick` | ❌ | ❌ | ❌ | 排除外部标记，跳过预检 |
| `pytest --ut` | ❌ | ❌ | ❌ | UT 不含外部标记，天然无依赖 |
| `pytest --st` | ✅ | ✅ | ✅ | ST 含 llm/npu/cann 用例 |
| `pytest -m llm` | ✅ | ❌ | ❌ | 仅选中 @llm |
| `pytest -m npu` | ❌ | ✅ | ❌ | 仅选中 @npu |
| `pytest -m cann` | ❌ | ❌ | ✅ | 仅选中 @cann |
| `pytest -m "not llm"` | ❌ | ❌ | ❌ | 排除 @llm，未显式选其它 |
| `pytest --no-env-check` | ❌ | ❌ | ❌ | 显式跳过 |
| `pytest --collect-only` | ❌ | ❌ | ❌ | 干跑不执行 |
| `pytest -m "llm or npu"` | ✅ | ✅ | 明确选中两类 |
| `pytest -m "llm or slow"` | ✅ | ❌ | 选中 @llm，未选 @npu |
| `pytest -m "slow and not llm"` | ❌ | ❌ | 排除 @llm，未选 @npu |
| `pytest --no-env-check --st` | ❌ | ❌ | 显式跳过 |
| `pytest --collect-only --st` | ❌ | ❌ | 干跑不执行 |

## 测试分级

| 级别 | 标记 | 依赖 | 耗时 | 用例数 |
|------|------|------|------|--------|
| UT | 无 | StubBackend | <1s | ~610 个，覆盖 L1-L7 全层 |
| ST | 无 | StubBackend | <1s | ~35 个，管线/物化/决策回路/超时/增量/回放 |
| ST | `@pytest.mark.llm` | 真实 LLM API | ~15s-5min | ~8 个，仅真正访问 LLM 的用例 |
| ST | `@pytest.mark.npu` | NPU 硬件 | ~30s | ~3 个 |
| ST | `@pytest.mark.slow` | LLM + 时间 | ~5min | ~5 个 |
| ST | `@pytest.mark.cann` | 真实 CANN 工具链 | 视用例 | 预留：需 `ops_compile` 真实编译的用例 |

## 常用命令

```bash
# 单文件
pytest tests/ut/orchestration/test_stages.py -v

# 单条用例（需同时指定 -m 以覆盖默认排除）
pytest -m llm tests/st/test_llm.py::TestLLMRealAPI::test_anthropic_returns_llm_response -v

# 仅 ST
pytest --st -v --tb=short

# 失败立即停止
pytest -x

# 验证架构合规
pytest tests/ut/test_layer_dependencies.py -v
```

## 目录结构

```
tests/
├── conftest.py                  # pytest 配置：自定义选项、目录过滤、默认排除、环境预检
├── fixtures/                    # 测试数据
│   ├── requirement.json         # Requirement 样本
│   └── ...
├── ut/                          # 单元测试（无外部依赖）
│   ├── domain/
│   │   └── test_domain.py              # L4: dataclass 序列化/不可变性/stubbed 字段
│   ├── infra/
│   │   └── test_infra.py               # L7: Workspace/EventLog/FileSystem/Terminal
│   ├── orchestration/
│   │   ├── test_kernel.py              # L3: State/Action/Event/Gate/Runner/Timeout/Progress
│   │   ├── test_stages.py              # L3: 9 Stage + SmokeStage 全覆盖
│   │   ├── test_workflow.py            # L3: Workflow 声明式编排 + IO 链验证
│   │   ├── test_loopback.py            # L3: Loopback E2E
│   │   └── test_decision_log.py        # L3: Decision 日志
│   ├── adapters/
│   │   ├── test_adapters.py            # L6: Repository/CANN/NPU Slot/PTA Toolchain
│   │   └── test_llm.py                 # L6: LLMProvider ABC + Anthropic/Bedrock/Vertex
│   ├── application/
│   │   ├── test_application.py         # L2: Dispatcher/Report/ProgressCallback
│   │   └── test_state_machine_dispatcher.py
│   ├── capabilities/
│   │   ├── test_capabilities.py        # L5: AgentBackend/StubBackend/MCP/SkillLoader
│   │   └── test_knowledge.py           # L5: KnowledgeBase/IndexNode/search_api
│   ├── cli/
│   │   └── test_cli.py                 # L1: CLI 命令/TUI 4-Panel/DebugAgent
│   └── test_layer_dependencies.py      # 架构合规: 7 层依赖方向 + KNOWN violations
└── st/                          # 系统测试（按需标记外部依赖）
    ├── test_integration.py             # 管线/物化/决策回路/超时/增量/回放
    ├── test_llm.py                     # 真实 LLM API 用例标 @pytest.mark.llm；stub/错误路径用例不标记
    ├── test_smoke.py                   # @pytest.mark.llm / @pytest.mark.slow
    ├── test_npu.py                     # @pytest.mark.npu — 真实 NPU 执行
```

## 测试策略

- **UT**：用 StubBackend 替代真实 Agent，验证 State 迁移、Action 生成、IO 契约、Gate 判定、Runner 循环控制、超时/取消/恢复
- **ST**：走 `dispatch()` 完整链路（L1→L2→L3→L5→L7），验证 events.jsonl 和 state_snapshot.json 产生与回放
- **标记策略**：ST 中需要外部依赖的用例标记对应 marker，由 `tests/conftest.py` 在默认模式下自动排除

## 自定义标记

在 `pyproject.toml` 中注册：

```toml
[tool.pytest.ini_options]
addopts = "-v"    # marker 过滤由 tests/conftest.py 接管
markers = [
    "llm: tests that require a real LLM backend (claude_agent_sdk)",
    "slow: long-running tests (codegen stage etc.)",
    "npu: tests that require NPU hardware",
    "cann: tests that require a real CANN toolchain (ops_compile in PATH)",
]
```

## 环境配置

LLM 凭据通过 `.claude/settings.json` 或环境变量配置：

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
    "ANTHROPIC_AUTH_TOKEN": "sk-...",
    "ANTHROPIC_API_KEY": "sk-..."
  },
  "model": "claude-sonnet-4-20250514"
}
```

优先级：环境变量 > `settings.json`。预检按以下顺序查找凭据：
`ANTHROPIC_API_KEY` → `ANTHROPIC_AUTH_TOKEN` → `settings.json env.ANTHROPIC_API_KEY` → `settings.json env.ANTHROPIC_AUTH_TOKEN`
