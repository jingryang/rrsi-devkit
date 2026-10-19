# L5 Capabilities — LLM 能力封装

> **所属架构**：[ascendc-devkit 架构总览](../architecture-overview.md) > §2 分层架构
> **上游依赖**：L3 Orchestration
> **下游依赖**：L4 Domain, L6 Adapters, L7 Infrastructure
> **实现状态**：`agent/backend.py` (AgentBackend, AgentResult) ✓ | `agent/sdk_backend.py` (SDKBackend, 仓内改动收集, webhook 通知, llm_provider 多态注入) ✓ | `agent/stub_backend.py` ✓ | `mcp_tools.py` (resolve_ambiguity + build_engine_mcp_server) ✓ | `skill/__init__.py` + `skill/loader.py` (SkillLoader: discover→SkillSpec, load_agent_manifest, resolve_skills, extra_paths) ✓ | `knowledge/__init__.py` (IndexNode + KnowledgeBase: load_index/search_api/load_document) ✓

---

## 1. 定位

把 LLM 作为一种"能力"提供给上层。这一层不包含算子业务知识——它不知道"怎么写 AscendC kernel"，只知道"怎么启动一个 Agent、怎么调一个 Skill、怎么查知识库"。

---

## 2. 子模块

```
capabilities/
├── agent/              # Agent 生命周期管理
│   ├── backend.py      #   AgentBackend protocol
│   ├── sdk_backend.py  #   SDKBackend（仓内 Write/Edit + 改动收集）
│   └── stub_backend.py #   测试用 stub（canned responses）
├── mcp_tools.py         #   resolve_ambiguity @tool + build_engine_mcp_server()
├── skill/              #   Skill 发现与解析
│   ├── __init__.py     #   SkillLoader + load_agent_manifest / resolve_skills 导出
│   └── loader.py       #   SkillLoader (discover→SkillSpec, load_agent_manifest, resolve_skills, extra_paths)
└── knowledge/          #   知识库加载
    └── __init__.py     #   IndexNode + KnowledgeBase (load_index/search_api/load_document)
```

---

## 3. Agent 生命周期

```
L3 Orchestration 发出 Action: spawn_agent("ascendc-coder", prompt, context,
        working_dir=op_dir, repo_baseline=<ref>, repo_root=<repo>)
        │
        ▼
L5 agent/sdk_backend.py
        │
        ├─ 1. 从 .claude/agents/ascendc-coder.md 加载 system prompt
        ├─ 2. 读取 skill 白名单
        ├─ 3. 以 working_dir（算子仓 op_dir）为 cwd 启动 agent 会话
        ├─ 4. 流式转发 agent 输出到 stdout (heartbeat 层)
        ├─ 5. agent 用 Write/Edit 直接改算子仓 + 写 changed_files.json
        ├─ 6. 收集本轮改动（自报清单 ∪ op_dir git diff）→ artifacts
        └─ 7. 返回 AgentResult 给 L3
```

### 3.1 AgentBackend Protocol

```python
class AgentBackend(ABC):
    """Agent 执行后端协议。SDKBackend 是默认实现，StubBackend 用于测试。"""

    @abstractmethod
    def spawn(self, agent_name: str, prompt: str, context: dict,
              skills: list[str] | None = None,
              model: str | None = None,
              working_dir: Path | str | None = None,
              repo_baseline: str | None = None,
              repo_root: Path | str | None = None) -> AgentResult:
        """启动 agent 会话，返回最终结果。

        working_dir   — 本次 spawn 的 cwd（算子仓 op_dir），按调用决定
        repo_baseline — 改动收集用的 git 基线 ref
        repo_root     — git diff 的仓根
        """
        ...
```

`working_dir` 按每次 spawn 决定，使 codegen/verify/perf 各自定位到算子仓 op_dir；不写仓的 agent（requirement/design）传 None。

### 3.2 AgentResult

```python
@dataclass(frozen=True)
class AgentResult:
    agent_name: str
    status: str                     # "ok" | "compile_error" | "precision_fail" | "fatal" | "empty_artifacts"
    transcript: Path | None         # agent 完整对话记录
    artifacts: dict[str, str]       # 本轮在 op_dir 内改动的文件（相对路径 → 内容）
    metrics: dict                   # {"elapsed_ms": ..., "tokens_in": ..., "tokens_out": ...}
```

### 3.3 改动收集

agent 直接在算子仓 op_dir 内用 Write/Edit 改文件。SDKBackend 在 agent 完成后按两路取并集得到本轮改动，写入 `AgentResult.artifacts`：

1. **agent 自报**：解析 op_dir 下的 `changed_files.json`（相对路径 + 操作类型 created/modified/deleted）。
2. **git diff 校验**：基于 `repo_baseline`，取 op_dir 范围内的 git diff 改动集（按 profile 的 `artifacts_ignore` 排除构建产物）。

两路取并集为权威改动清单：created/modified 读文件内容，deleted 仅记录路径；自报与 diff 的分歧打 warn。无 baseline/非 git 环境时降级为限定 op_dir 的目录扫描。改动集为空 → status=`empty_artifacts`。

---

## 4. Skill 发现与调度

### 4.1 注册发现

Skills 通过扫描 `<project>/resources/skills/` 目录下各子目录中的 `SKILL.md` 文件发现。默认自闭环——只扫描项目内 skill 目录，不依赖外部路径。

```python
# capabilities/skill/loader.py

class SkillLoader:
    @staticmethod
    def discover(resources_root: Path | None = None,
                 extra_paths: list[Path] | None = None) -> set[SkillSpec]:
        """扫描 skill 目录，返回 SkillSpec 对象集合。
        
        默认扫描 <project>/resources/skills/ 下的子目录。
        extra_paths 参数支持按需传入额外 skill 目录。
        """
        ...

    @staticmethod
    def list_available(extra_paths: list[Path] | None = None) -> list[SkillSpec]:
        """列出所有可用 skill（按名称排序）。"""
        ...

    @staticmethod
    def validate(skill_names: list[str],
                 extra_paths: list[Path] | None = None) -> list[str]:
        """校验 skill 名称列表，返回不存在的名称列表。"""
        ...
```

额外路径通过 `extra_paths` 参数显式传入——不使用环境变量或隐式全局配置。

### 4.2 Agent Manifest 解析

每个 Agent 的 `.md` 文件支持两种格式：

**格式 A — YAML frontmatter**（推荐）：
```yaml
# .claude/agents/ascendc-coder.md
---
name: ascendc-coder
plugins: [stage-codegen, codegen-coder-extra, shared]
---
You are an expert AscendC developer...
```

**格式 B — 纯文本 "named <name>" 模式**（兼容）：
```markdown
# Agent: My Agent

named my-agent

You are an expert...
```

```python
def load_agent_manifest(agent_name: str,
                        resources_root: Path | None = None) -> AgentManifest:
    """解析 resources/agents/<name>.md 的 frontmatter 或 named 标记。
    返回 AgentManifest(name, skills, description)。"""
    ...

def resolve_skills(agent_name: str, requested: list[str],
                   resources_root: Path | None = None,
                   extra_paths: list[Path] | None = None) -> list[SkillSpec]:
    """按 agent frontmatter 白名单过滤 skill。
    若 agent 无 frontmatter 或未声明 skills，不过滤（返回全部匹配）。
    """
    ...
```

### 4.3 白名单路由

L5 在启动 agent 时调用 `resolve_skills()` 按白名单过滤，不在白名单中的 skill 对该 agent 不可见。若 agent manifest 未声明 skills 白名单，则所有 skill 可见。

### 4.4 SDK 与框架分工

`claude_agent_sdk` **不提供 skill 发现/加载能力**——它只传递 skill 名称白名单给 CLI 子进程（`--model` / `--add-dir` 等参数）。框架层自己读 SKILL.md 完成 discovery 和 loading 是必须的。

---

## 5. 知识库加载

```python
# capabilities/knowledge/__init__.py

@dataclass
class IndexNode:
    """INDEX.md 解析后的文档树节点。"""
    name: str
    path: Path | None = None
    children: dict[str, IndexNode] = field(default_factory=dict)

class KnowledgeBase:
    """按需加载 AscendC API 参考和编程指南。

    Parameters:
        root: 知识库根路径，默认 ~/.claude/skills/ascendc-dev-knowledge/references/
    """

    def __init__(self, root: Path | None = None): ...

    def load_index(self, index_path: Path) -> IndexNode:
        """解析 INDEX.md 为可导航的文档树。

        解析规则：
        - `# Heading` → 重命名根节点
        - `## Section` / `### SubSection` → 嵌套 IndexNode
        - `- [Title](relative/path.md)` → 叶子节点
        """

    def load_document(self, doc_path: Path) -> str:
        """读取知识文档全文（带内存缓存）。"""

    def search_api(self, api_name: str) -> dict | None:
        """在 api_reference_docs/INDEX.md 树中搜索指定接口。
        返回 {"name": ..., "doc": ..., "path": ...} 或 None。
        """

    def list_available_indices(self) -> list[str]:
        """列出 root 下可用的 INDEX.md 子目录名。"""
```

知识库加载优先级：INDEX.md → 具体文档。不扫描 CANN 目录。

`KnowledgeBase` 根路径默认为 `~/.claude/skills/ascendc-dev-knowledge/references/`，依赖用户预先安装知识库 skill，也可通过构造函数参数自定义根路径。

---

## 6. 关键设计决策

- **Agent system prompt 和 Skill 指南是 Markdown 文件**，放在 `resources/` 里，不进 Python 代码
- **加一个 agent = 写一个 `.md` 文件**，不改 Python
- **改 agent 行为 = 改 `.md` 文件**，不动代码
- **Agent 的行为变更可以独立于引擎版本发布**
- **Skill 发现默认自闭环**：只扫描 `<project>/resources/skills/`，不依赖外部路径。额外路径通过 `extra_paths` 参数显式传入
- **SDK 不提供 skill 加载**：`claude_agent_sdk` 只传递 skill 名称白名单给 CLI 子进程，框架层自己读 SKILL.md 是必须的
- **分层穿透**：L4 定义 `SkillSpec`/`AgentManifest` 纯数据类型 → L5 SkillLoader 实现 → L3 orchestration/skill 薄封装 → L2 skill_service 薄封装 → L1 CLI 消费

---

## 7. 边界

L5 不知道"当前在跑什么 workflow"、"现在是第几个 Stage"、"算子叫什么名字"。它只接收 prompt 文本，返回 agent 结果。

streaming token 转发到 stdout 是 L5 的职责（Heartbeat 层），但 L5 不知道 stdout 是终端还是文件——那是 L7 Terminal 的职责。

---

## 8. 与邻层的关系

| 方向 | 层 | 关系 |
|---|---|---|
| 向上 | L3 Orchestration | 接收 `SpawnAgent` Action，返回 `AgentResult` |
| 向下 | L4 Domain | import `SkillSpec`、`AgentManifest` 等类型 |
| 向下 | L6 Adapters | 通过 `LLMProvider` protocol 调用 LLM API |
| 向下 | L7 Infrastructure | 写 agent transcript 到 workspace |
