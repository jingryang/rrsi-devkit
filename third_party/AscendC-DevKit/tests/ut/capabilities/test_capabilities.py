"""UT for L5 Capabilities — AgentBackend ABC, StubBackend, mcp_tools, SkillLoader."""

import tempfile
from pathlib import Path

import pytest

from ascendc_devkit.capabilities.agent.backend import AgentBackend, AgentResult
from ascendc_devkit.capabilities.agent.stub_backend import StubBackend
from ascendc_devkit.capabilities.mcp_tools import (
    create_resolve_ambiguity_handler, build_engine_mcp_server,
)


class TestAgentResult:
    def test_creation_minimal(self):
        r = AgentResult(agent_name="test", status="ok")
        assert r.agent_name == "test"
        assert r.status == "ok"
        assert r.transcript is None
        assert r.artifacts == {}
        assert r.metrics == {}

    def test_creation_with_artifacts(self):
        r = AgentResult(agent_name="codegen", status="ok",
                        artifacts={"kernel.cpp": "content"})
        assert r.artifacts == {"kernel.cpp": "content"}

    def test_creation_with_metrics(self):
        r = AgentResult(agent_name="codegen", status="ok",
                        metrics={"elapsed_ms": 1500, "tokens_in": 200})
        assert r.metrics["elapsed_ms"] == 1500

    def test_frozen_prevents_reassignment(self):
        r = AgentResult(agent_name="test", status="ok")
        with pytest.raises(Exception):
            r.status = "failed"

    def test_status_values(self):
        for status in ("ok", "compile_error", "precision_fail", "fatal"):
            r = AgentResult(agent_name="x", status=status)
            assert r.status == status

    def test_error_type_defaults_none(self):
        # P50: error_type is None by default — callers that don't set it keep
        # the legacy "logic failure" semantics.
        r = AgentResult(agent_name="x", status="fatal")
        assert r.error_type is None

    def test_error_type_infra_settable(self):
        # P50: infra-class (config/quota/auth) failures carry error_type="infra"
        # so stages can avoid burning iteration/breaker budgets on them.
        r = AgentResult(agent_name="x", status="fatal", error_type="infra")
        assert r.error_type == "infra"


class TestInfraErrorClassification:
    """P50: the backend classifies infra errors (config/quota/auth) so stages
    can tell them apart from logic failures. Infra is NOT retryable (a missing
    gateway channel / exhausted quota won't recover by retrying within the run)
    and must NOT count toward a stage's failure budget."""

    def test_no_available_channel_is_infra(self):
        # The exact string from run 20260707-091803-29a24f's 503.
        from ascendc_devkit.capabilities.agent.sdk_backend import _classify_error_type
        text = ("API Error: 503 No available channel for model deepseek-v4-pro "
                "under group default (distributor)")
        assert _classify_error_type(text) == "infra"

    def test_usage_limit_reached_is_infra(self):
        # 429 quota window — retry futile until the reset time.
        from ascendc_devkit.capabilities.agent.sdk_backend import _classify_error_type
        text = "API Error: 429 Usage limit reached for 5 hour. Your limit will reset at 2026-07-07 16:32:49"
        assert _classify_error_type(text) == "infra"

    def test_auth_errors_are_infra(self):
        from ascendc_devkit.capabilities.agent.sdk_backend import _classify_error_type
        assert _classify_error_type("API Error: 401 Unauthorized") == "infra"
        assert _classify_error_type("API Error: 403 Forbidden") == "infra"

    def test_spawn_timeout_is_infra(self):
        # P93: backend HTTP spawn timeout (opencode message_timeout=3600 → except
        # str(e)) — agent never finished, environment/gateway side, NOT a logic
        # failure. run 20260720-095303-413565 buffer-kernel round-1 burned 60min
        # on this with no infra classification → burned 3 retries + misreported.
        from ascendc_devkit.capabilities.agent.sdk_backend import _classify_error_type
        assert _classify_error_type(
            "Agent ascendc-design-generator opencode spawn failed: timed out"
        ) == "infra"

    def test_gateway_price_not_configured_is_infra(self):
        # P93: LLM gateway (new-api/one-api) returns 400 isRetryable=False when
        # the model has no price configured. EN + ZH wordings both observed in
        # run 20260720-095303-413565 agent transcripts (the real failure cause).
        from ascendc_devkit.capabilities.agent.sdk_backend import _classify_error_type
        assert _classify_error_type(
            "Model GLM-5.2 price not configured. Go to System Settings..."
        ) == "infra"
        assert _classify_error_type(
            "模型 GLM-5.2 的价格未配置。请前往「系统设置 → 运营设置」开启自用模式"
        ) == "infra"

    def test_gateway_invalid_token_is_infra(self):
        # P93 旁证 (P92): gateway 401 wrapped as "Invalid token" by new-api —
        # does NOT match the literal "API Error: 401" marker, needs its own.
        from ascendc_devkit.capabilities.agent.sdk_backend import _classify_error_type
        assert _classify_error_type("request failed: Invalid token") == "infra"

    def test_rate_limit_429_not_misclassified_as_infra(self):
        # 回归守护：429 burst 走 _is_rate_limit_error 独立路径（step-57），新增
        # infra markers 不得把 429 误收为 infra（否则污染 step-27 不变式）。
        from ascendc_devkit.capabilities.agent.sdk_backend import _classify_error_type
        assert _classify_error_type("Request rejected (429)") is None

    def test_sse_transient_is_not_infra(self):
        # "Content block not found" is a mid-stream SSE glitch (handled by the
        # transient retry path), NOT an infra/config error.
        from ascendc_devkit.capabilities.agent.sdk_backend import _classify_error_type
        assert _classify_error_type("API Error: Content block not found") is None

    def test_logic_error_text_is_not_infra(self):
        from ascendc_devkit.capabilities.agent.sdk_backend import _classify_error_type
        assert _classify_error_type("compile failed: undefined symbol: GeluCustom") is None

    def test_none_and_empty_are_not_infra(self):
        from ascendc_devkit.capabilities.agent.sdk_backend import _classify_error_type
        assert _classify_error_type(None) is None
        assert _classify_error_type("") is None


class TestRateLimitClassification:
    """step-57 (P80): 429 burst is its own class — retried after a backoff
    resume, distinct from both infra (un-retryable) and SSE transient."""

    def test_request_rejected_429_is_rate_limit(self):
        from ascendc_devkit.capabilities.agent._shared import _is_rate_limit_error
        text = "API Error: Request rejected (429) · Weekly/Monthly Limit Exhausted"
        assert _is_rate_limit_error(text) is True

    def test_bare_429_marker_matches(self):
        from ascendc_devkit.capabilities.agent._shared import _is_rate_limit_error
        assert _is_rate_limit_error("some proxy said (429) throttled") is True

    def test_gateway_1310_monthly_limit_is_rate_limit(self):
        # 实测网关(new-api/oneapi distributor)透传形如,不含 "(429)",
        # 曾致 _is_rate_limit_error 漏判→框架重试未触发、run.log 静默爬行。
        from ascendc_devkit.capabilities.agent._shared import _is_rate_limit_error
        text = ("AI_APICallError: [1310][Weekly/Monthly Limit Exhausted. "
                "Your limit will reset at 2026-07-27 20:30:48]"
                "[20260725213316fb80f19055244d52] (request id: 20260725133316...)")
        assert _is_rate_limit_error(text) is True

    def test_gateway_1313_fair_usage_is_rate_limit(self):
        from ascendc_devkit.capabilities.agent._shared import _is_rate_limit_error
        text = ("AI_APICallError: [1313][Your account's current usage pattern "
                "does not comply with the Fair Usage Policy, and your request "
                "frequency has been limited.]")
        assert _is_rate_limit_error(text) is True

    def test_401_unauthorized_is_not_rate_limit(self):
        # 401 是不可重试的鉴权错误(属 _INFRA_ERROR_MARKERS),绝不能被限流 markers
        # 误判为可重试——否则会把鉴权失败拖入无意义退避。
        from ascendc_devkit.capabilities.agent._shared import _is_rate_limit_error
        assert _is_rate_limit_error(
            "Unauthorized: Invalid token (statusCode=401)") is False

    def test_sse_transient_is_not_rate_limit(self):
        from ascendc_devkit.capabilities.agent._shared import _is_rate_limit_error
        assert _is_rate_limit_error("API Error: Content block not found") is False

    def test_infra_is_not_rate_limit(self):
        from ascendc_devkit.capabilities.agent._shared import _is_rate_limit_error
        assert _is_rate_limit_error("No available channel for model X") is False

    def test_none_and_empty_are_not_rate_limit(self):
        from ascendc_devkit.capabilities.agent._shared import _is_rate_limit_error
        assert _is_rate_limit_error(None) is False
        assert _is_rate_limit_error("") is False

    def test_429_is_not_classified_infra(self):
        # 429 must NOT be swallowed by the infra classifier (else it would be
        # un-retryable). It carries error_type=None and is handled by the
        # backend backoff branch instead.
        from ascendc_devkit.capabilities.agent._shared import _classify_error_type
        assert _classify_error_type("Request rejected (429) · Limit Exhausted") is None


class TestComputeBackoffSeconds:
    """step-57: exponential backoff with a hard total-time cap (stop-loss)."""

    def test_exponential_progression_uncapped(self):
        from ascendc_devkit.capabilities.agent._shared import compute_backoff_seconds
        # base=30, factor=2, generous cap → 30, 60, 120 for attempts 0/1/2.
        assert compute_backoff_seconds(0, 30.0, 2.0, 0.0, 10000.0) == 30.0
        assert compute_backoff_seconds(1, 30.0, 2.0, 30.0, 10000.0) == 60.0
        assert compute_backoff_seconds(2, 30.0, 2.0, 90.0, 10000.0) == 120.0

    def test_returns_none_when_total_cap_exhausted(self):
        from ascendc_devkit.capabilities.agent._shared import compute_backoff_seconds
        assert compute_backoff_seconds(3, 30.0, 2.0, 900.0, 900.0) is None
        assert compute_backoff_seconds(3, 30.0, 2.0, 950.0, 900.0) is None

    def test_single_sleep_clamped_to_remaining_budget(self):
        from ascendc_devkit.capabilities.agent._shared import compute_backoff_seconds
        # want=240 but only 50s of budget left → clamp to 50.
        assert compute_backoff_seconds(3, 30.0, 2.0, 850.0, 900.0) == 50.0

    def test_factor_one_is_constant_base(self):
        from ascendc_devkit.capabilities.agent._shared import compute_backoff_seconds
        assert compute_backoff_seconds(0, 60.0, 1.0, 0.0, 900.0) == 60.0
        assert compute_backoff_seconds(5, 60.0, 1.0, 300.0, 900.0) == 60.0


class TestAgentBackendABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            AgentBackend()

    def test_subclass_must_implement_spawn(self):
        class Incomplete(AgentBackend):
            pass
        with pytest.raises(TypeError):
            Incomplete()

    def test_concrete_subclass_works(self):
        class Concrete(AgentBackend):
            def spawn(self, agent_name, prompt, context, skills=None,
                      model=None, working_dir=None, repo_baseline=None,
                resume_prompt=None,
                      repo_root=None):
                return AgentResult(agent_name=agent_name, status="ok")

        backend = Concrete()
        result = backend.spawn("test", "prompt", {})
        assert result.status == "ok"


class TestStubBackend:
    def test_default_returns_ok(self):
        backend = StubBackend()
        result = backend.spawn("agent", "prompt", {})
        assert result.status == "ok"
        assert result.agent_name == "agent"
        assert result.artifacts == {}

    def test_records_spawn_calls(self):
        backend = StubBackend()
        backend.spawn("a1", "p1", {"k": "v"}, skills=["s1"])
        assert len(backend.spawn_calls) == 1
        call = backend.spawn_calls[0]
        assert call["agent_name"] == "a1"
        assert call["prompt"] == "p1"
        assert call["context"] == {"k": "v"}
        assert call["skills"] == ["s1"]

    def test_multiple_calls_recorded(self):
        backend = StubBackend()
        backend.spawn("a", "p", {})
        backend.spawn("b", "q", {})
        assert len(backend.spawn_calls) == 2
        assert backend.spawn_calls[0]["agent_name"] == "a"
        assert backend.spawn_calls[1]["agent_name"] == "b"

    def test_canned_responses_cycled_in_order(self):
        canned = [
            AgentResult(agent_name="a1", status="ok"),
            AgentResult(agent_name="a2", status="compile_error"),
        ]
        backend = StubBackend(canned_responses=canned)
        r1 = backend.spawn("x", "p", {})
        r2 = backend.spawn("x", "p", {})
        assert r1.status == "ok"
        assert r2.status == "compile_error"

    def test_falls_back_to_ok_after_canned_exhausted(self):
        canned = [AgentResult(agent_name="a1", status="ok")]
        backend = StubBackend(canned_responses=canned)
        r1 = backend.spawn("x", "p", {})
        r2 = backend.spawn("x", "p", {})
        assert r1.status == "ok"
        assert r2.status == "ok"  # fallback

    def test_canned_with_artifacts(self):
        canned = [AgentResult(agent_name="a", status="ok",
                              artifacts={"out.json": '{"x":1}'})]
        backend = StubBackend(canned_responses=canned)
        result = backend.spawn("x", "p", {})
        assert result.artifacts == {"out.json": '{"x":1}'}

    def test_skills_none(self):
        backend = StubBackend()
        result = backend.spawn("agent", "prompt", {}, skills=None)
        assert result.status == "ok"
        assert backend.spawn_calls[0]["skills"] is None

    def test_records_working_dir_and_baseline(self):
        backend = StubBackend()
        backend.spawn("a", "p", {}, working_dir="/tmp/op",
                      repo_baseline="head-sha", repo_root="/tmp/repo")
        call = backend.spawn_calls[0]
        assert call["working_dir"] == "/tmp/op"
        assert call["repo_baseline"] == "head-sha"
        assert call["repo_root"] == "/tmp/repo"


def _has_git() -> bool:
    import subprocess
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


class TestCollectChangedSources:
    """step-109: product collection = git 单通路（diff ∪ untracked，含 deleted
    派生），契约元数据名单路由；自报通路已删（§2.5 收口）。"""

    def _git(self, repo, *args):
        import subprocess
        return subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=True, check=True)

    def _init_repo(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        self._git(repo, "init", "-q")
        self._git(repo, "config", "user.email", "t@e.com")
        self._git(repo, "config", "user.name", "T")
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "-q", "-m", "init")
        return repo

    def test_degrades_to_scan_without_baseline(self, tmp_path):
        from ascendc_devkit.capabilities.agent._shared import _collect_changed_sources
        op = tmp_path / "op"
        op.mkdir()
        (op / "k.cpp").write_text("int x;\n", encoding="utf-8")
        # No guard / baseline → scoped scan of op_dir.
        out = _collect_changed_sources(op, repo_guard=None, baseline="")
        assert out == {"k.cpp": "int x;\n"}

    def test_baseline_present_zero_changes_returns_empty(self, tmp_path):
        """T3 regression: with a baseline available and no signals (agent
        crashed before writing changed_files.json and git diff is empty), the
        run produced nothing — must NOT scan the pre-existing op_dir as if it
        were this run's output. Prevents snapshotting the whole operator dir."""
        from ascendc_devkit.capabilities.agent._shared import _collect_changed_sources
        op = tmp_path / "op"
        op.mkdir()
        # Pre-existing operator file (NOT produced this run).
        (op / "existing_kernel.cpp").write_text("int pre;\n", encoding="utf-8")
        out = _collect_changed_sources(
            op, repo_guard=None, baseline="", has_baseline=True)
        assert out == {}

    def test_no_baseline_still_scans(self, tmp_path):
        """Without a baseline the degradation scan is the only signal, so it
        must still kick in (has_baseline defaults False)."""
        from ascendc_devkit.capabilities.agent._shared import _collect_changed_sources
        op = tmp_path / "op"
        op.mkdir()
        (op / "k.cpp").write_text("int x;\n", encoding="utf-8")
        out = _collect_changed_sources(
            op, repo_guard=None, baseline="", has_baseline=False)
        assert out == {"k.cpp": "int x;\n"}

    def test_scan_carries_contract_files_degradation(self, tmp_path):
        """step-109 降级路径：无 git 基线时扫描**照带**契约元数据——收集层不再
        pop 特判（§1.15：分类归 _persist_sources 的名单路由统一管）。"""
        from ascendc_devkit.capabilities.agent._shared import _collect_changed_sources
        op = tmp_path / "op"
        op.mkdir()
        (op / "k.cpp").write_text("x\n", encoding="utf-8")
        (op / "changed_files.json").write_text('{"changed_files": []}', encoding="utf-8")
        out = _collect_changed_sources(op, repo_guard=None, baseline="")
        # 扫描是原始面：契约文件照带，落盘时由 CONTRACT_FILES 路由进 _contract/
        assert out == {"k.cpp": "x\n", "changed_files.json": '{"changed_files": []}'}

    def test_self_report_fully_ignored(self, tmp_path):
        """step-109：自报通路已死——changed_files.json 内容对收集零影响；
        列了盘上不存在的文件（ghost）绝不进 dict（旧 union 会带空内容混入）。"""
        from ascendc_devkit.capabilities.agent._shared import _collect_changed_sources
        op = tmp_path / "op"
        op.mkdir()
        (op / "k.cpp").write_text("int x;\n", encoding="utf-8")
        (op / "changed_files.json").write_text(
            '{"changed_files": [{"path": "k.cpp", "op": "created"},'
            ' {"path": "ghost.cpp", "op": "created"}]}',
            encoding="utf-8")
        out = _collect_changed_sources(op, repo_guard=None, baseline="")
        assert out == {"k.cpp": "int x;\n", "changed_files.json": out["changed_files.json"]}
        assert "ghost.cpp" not in out

    @pytest.mark.skipif(not _has_git(), reason="git not installed")
    def test_deleted_derived_from_git(self, tmp_path):
        """step-109：deleted 标签由 git 构造性派生（--diff-filter=D）——基线含
        gone.cpp、工作区删掉 → dict 记路径不读内容 + 派生报告 op=deleted。
        （原用例钉自报 deleted 标签——通路已死，git 是唯一来源。）"""
        from ascendc_devkit.capabilities.agent._shared import _collect_changed_sources
        from ascendc_devkit.infra.repo_guard import RepoGuard
        import json as _json
        repo = self._init_repo(tmp_path)
        op = repo / "ops" / "add"
        op.mkdir(parents=True)
        (op / "gone.cpp").write_text("old\n", encoding="utf-8")
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "-q", "-m", "base")
        guard = RepoGuard(ignore_globs=[])
        baseline = guard.create_baseline(repo, op)
        (op / "gone.cpp").unlink()          # 工作区删除（tracked）
        (op / "new.cpp").write_text("n\n", encoding="utf-8")  # 未跟踪新增
        out = _collect_changed_sources(op, repo_guard=guard,
                                       baseline=baseline, repo_root=repo)
        assert out.get("gone.cpp") == ""    # 删除文件：记路径、无内容
        assert out.get("new.cpp") == "n\n"
        derived = _json.loads(out["changed_files.json"])
        ops = {e["path"]: e["op"] for e in derived["changed_files"]}
        assert ops["gone.cpp"] == "deleted"
        assert ops["new.cpp"] == "modified"

    @pytest.mark.skipif(not _has_git(), reason="git not installed")
    def test_derived_report_pure_sources(self, tmp_path):
        """step-109：派生报告**仅算子源码**——契约元数据（manifest/decision_log/
        changed_files）被 git 视作未跟踪新文件，进 dict（下游读点）但**不进**报告
        （它们不是算子改动）；ignored 构建产物照常排除。"""
        from ascendc_devkit.capabilities.agent._shared import _collect_changed_sources
        from ascendc_devkit.infra.repo_guard import RepoGuard
        import json as _json
        repo = self._init_repo(tmp_path)
        op = repo / "ops" / "add"
        guard = RepoGuard(ignore_globs=["*.o"])
        baseline = guard.create_baseline(repo, op)
        op.mkdir(parents=True)
        (op / "add.cpp").write_text("int a;\n", encoding="utf-8")
        (op / "add.o").write_text("obj", encoding="utf-8")  # ignored artifact
        (op / "codegen_manifest.json").write_text('{"m": 1}', encoding="utf-8")
        (op / "decision_log.json").write_text('{"d": 1}', encoding="utf-8")
        out = _collect_changed_sources(op, repo_guard=guard,
                                       baseline=baseline, repo_root=repo)
        # dict 携带全部（下游 artifacts.get 读点依赖），ignored 除外
        assert "add.cpp" in out
        assert "codegen_manifest.json" in out and "decision_log.json" in out
        assert not any(k.endswith(".o") for k in out)
        # 派生报告纯源码：契约三件不进（changed_files.json 本身也不进）
        derived = _json.loads(out["changed_files.json"])
        paths = {e["path"] for e in derived["changed_files"]}
        assert paths == {"add.cpp"}

    @pytest.mark.skipif(not _has_git(), reason="git not installed")
    def test_git_only_collection_no_union(self, tmp_path):
        """step-109：收集面=git 权威单通路——agent 写了自报（含盘上不存在的
        ghost.cpp）也不产生任何自报独有路径；报告与 dict 均只反映 git 可见事实。"""
        from ascendc_devkit.capabilities.agent._shared import _collect_changed_sources
        from ascendc_devkit.infra.repo_guard import RepoGuard
        import json as _json
        repo = self._init_repo(tmp_path)
        op = repo / "ops" / "add"
        guard = RepoGuard(ignore_globs=[])
        baseline = guard.create_baseline(repo, op)
        op.mkdir(parents=True)
        (op / "add.cpp").write_text("int a;\n", encoding="utf-8")
        (op / "changed_files.json").write_text(
            '{"changed_files": [{"path": "ghost.cpp", "op": "created"}]}',
            encoding="utf-8")
        out = _collect_changed_sources(op, repo_guard=guard,
                                       baseline=baseline, repo_root=repo)
        assert "ghost.cpp" not in out
        assert "add.cpp" in out
        derived = _json.loads(out["changed_files.json"])
        assert {e["path"] for e in derived["changed_files"]} == {"add.cpp"}

    def test_degradation_no_derived_report(self, tmp_path):
        """step-109：无 git 基线（降级扫描）→ 无 diff 集 → 不派生
        changed_files.json（框架版只在 git 真值可用时生成）。"""
        from ascendc_devkit.capabilities.agent._shared import _collect_changed_sources
        op = tmp_path / "op"
        op.mkdir()
        (op / "k.cpp").write_text("int x;\n", encoding="utf-8")
        out = _collect_changed_sources(op, repo_guard=None, baseline="")
        # 扫描原始面（k.cpp）；无派生报告键
        assert set(out) == {"k.cpp"}


class TestMcpTools:
    def test_resolve_ambiguity_non_interactive_returns_first_option(self):
        handler = create_resolve_ambiguity_handler(interactive=False)
        import asyncio
        result = asyncio.run(handler({
            "question": "Which strategy?",
            "options": ["tile_32", "tile_64", "tile_128"],
        }))
        assert result["content"][0]["text"] == "tile_32"

    def test_resolve_ambiguity_empty_options(self):
        handler = create_resolve_ambiguity_handler(interactive=False)
        import asyncio
        result = asyncio.run(handler({
            "question": "Q?",
            "options": [],
        }))
        assert result["content"][0]["text"] == ""

    def test_create_handler_returns_callable(self):
        handler = create_resolve_ambiguity_handler(interactive=True)
        assert callable(handler)

    # —— on_decision tests ——

    def test_on_decision_default_returns_first_option(self):
        """Non-interactive + on_decision='default': auto-select options[0]."""
        handler = create_resolve_ambiguity_handler(
            interactive=False, on_decision="default")
        import asyncio
        result = asyncio.run(handler({
            "question": "Pick one",
            "options": ["A", "B", "C"],
        }))
        assert result["content"][0]["text"] == "A"

    def test_on_decision_abort_writes_pending_file_and_returns_marker(self, tmp_path):
        """Non-interactive + on_decision='abort': write pending_decision.json,
        return __DECISION_PENDING__ marker."""
        ws = tmp_path / "workspace"
        ws.mkdir()
        handler = create_resolve_ambiguity_handler(
            interactive=False, on_decision="abort", workspace_dir=str(ws))
        import asyncio
        result = asyncio.run(handler({
            "question": "Which tiling?",
            "options": ["tile_32", "tile_64"],
        }))
        assert result["content"][0]["text"] == "__DECISION_PENDING__"

        pending = ws / "pending_decision.json"
        assert pending.exists()
        import json
        data = json.loads(pending.read_text())
        assert data["question"] == "Which tiling?"
        assert data["options"] == ["tile_32", "tile_64"]

    def test_resume_reads_decision_response(self, tmp_path):
        """When decision_response.json exists, use its choice regardless of on_decision."""
        ws = tmp_path / "workspace"
        ws.mkdir()
        import json
        (ws / "decision_response.json").write_text(
            json.dumps({"choice": 2, "selected": "tile_64", "question": "Q"}))

        handler = create_resolve_ambiguity_handler(
            interactive=False, on_decision="default", workspace_dir=str(ws))
        import asyncio
        result = asyncio.run(handler({
            "question": "Which tiling?",
            "options": ["tile_32", "tile_64", "tile_128"],
        }))
        # Should use response choice=2 → "tile_64", not default options[0]="tile_32"
        assert result["content"][0]["text"] == "tile_64"
        # Response file should be consumed
        assert not (ws / "decision_response.json").exists()

    def test_resume_text_field_overrides_choice(self, tmp_path):
        """A free-text `text` field (respond --text) takes precedence over the
        option set and is returned verbatim to the agent."""
        ws = tmp_path / "workspace"
        ws.mkdir()
        import json
        (ws / "decision_response.json").write_text(
            json.dumps({"text": "mode is required, no default", "question": "Q"}))

        handler = create_resolve_ambiguity_handler(
            interactive=False, on_decision="default", workspace_dir=str(ws))
        import asyncio
        result = asyncio.run(handler({
            "question": "Which mode?",
            "options": ["mode=0", "mode=1"],
        }))
        assert result["content"][0]["text"] == "mode is required, no default"
        assert not (ws / "decision_response.json").exists()

    def test_interactive_ignores_on_decision(self, tmp_path):
        """Interactive mode always prompts user; on_decision has no effect.
        Since we can't actually read stdin in test, verify the handler is callable."""
        handler = create_resolve_ambiguity_handler(
            interactive=True, on_decision="abort", workspace_dir=str(tmp_path))
        assert callable(handler)

    def test_abort_without_workspace_returns_marker_no_crash(self):
        """on_decision='abort' without workspace_dir: no file written, returns marker."""
        handler = create_resolve_ambiguity_handler(
            interactive=False, on_decision="abort", workspace_dir=None)
        import asyncio
        result = asyncio.run(handler({
            "question": "Q?",
            "options": ["A", "B"],
        }))
        assert result["content"][0]["text"] == "__DECISION_PENDING__"

    def test_interactive_returns_user_choice(self):
        """Interactive handler reads from stdin and returns selected option."""
        from unittest import mock as umock
        import asyncio
        handler = create_resolve_ambiguity_handler(interactive=True)
        # Simulate a TTY stdin so the prompt path runs (under pytest stdin is
        # non-TTY, which now raises EOFError before reading input).
        with umock.patch(
            "ascendc_devkit.capabilities.mcp_tools.Terminal.stdin_is_tty",
            return_value=True,
        ), umock.patch("ascendc_devkit.capabilities.mcp_tools.input", return_value="2"):
            result = asyncio.run(handler({
                "question": "Which approach?",
                "options": ["plan_a", "plan_b", "plan_c"],
            }))
        assert result["content"][0]["text"] == "plan_b"

    def test_interactive_empty_input_selects_default(self):
        """In interactive mode, Enter without input selects the default (first) option."""
        from unittest import mock as umock
        import asyncio
        handler = create_resolve_ambiguity_handler(interactive=True)
        with umock.patch(
            "ascendc_devkit.capabilities.mcp_tools.Terminal.stdin_is_tty",
            return_value=True,
        ), umock.patch("ascendc_devkit.capabilities.mcp_tools.input", return_value=""):
            result = asyncio.run(handler({
                "question": "Pick one",
                "options": ["default_choice", "other"],
            }))
        assert result["content"][0]["text"] == "default_choice"

    def test_interactive_takes_precedence_over_on_decision(self, tmp_path):
        """Path 1 vs Path 3: with a TTY available, real-time interaction wins
        over on_decision='abort' — no pending file is written, the user's live
        choice is returned in-session."""
        from unittest import mock as umock
        import asyncio
        ws = tmp_path / "workspace"
        ws.mkdir()
        handler = create_resolve_ambiguity_handler(
            interactive=True, on_decision="abort", workspace_dir=str(ws))
        with umock.patch(
            "ascendc_devkit.capabilities.mcp_tools.Terminal.stdin_is_tty",
            return_value=True,
        ), umock.patch("ascendc_devkit.capabilities.mcp_tools.input", return_value="2"):
            result = asyncio.run(handler({
                "question": "Which tiling?",
                "options": ["tile_32", "tile_64"],
            }))
        assert result["content"][0]["text"] == "tile_64"
        assert not (ws / "pending_decision.json").exists()

    def test_abort_empty_options_returns_marker(self, tmp_path):
        """on_decision='abort' with empty options: pending file has empty list, returns marker."""
        ws = tmp_path / "workspace"
        ws.mkdir()
        handler = create_resolve_ambiguity_handler(
            interactive=False, on_decision="abort", workspace_dir=str(ws))
        import asyncio
        result = asyncio.run(handler({
            "question": "Nothing to choose?",
            "options": [],
        }))
        assert result["content"][0]["text"] == "__DECISION_PENDING__"
        import json
        pending = ws / "pending_decision.json"
        assert pending.exists()
        data = json.loads(pending.read_text())
        assert data["options"] == []


class TestSkillLoader:
    """Skill discovery and validation."""

    def test_discover_default_scans_project_skills(self):
        from ascendc_devkit.capabilities.skill import SkillLoader
        skills = SkillLoader.discover()
        # Project .claude/skills/ may be empty — default discovery should not crash
        assert isinstance(skills, set)

    def test_discover_with_extra_paths(self):
        from ascendc_devkit.capabilities.skill import SkillLoader
        # ascend-hardware migrated into the shared plugin; discover scans the
        # plugin's skills/ dir via extra_paths.
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        shared_skills = project_root / ".claude" / "skills"
        extra = [shared_skills] if shared_skills.exists() else []
        skills = SkillLoader.discover(extra_paths=extra) if extra else SkillLoader.discover()
        names = {s.name for s in skills}
        if extra:
            assert "ascend-hardware" in names

    def test_discover_returns_skill_spec_objects(self, tmp_path):
        from ascendc_devkit.capabilities.skill import SkillLoader
        from ascendc_devkit.domain.skill import SkillSpec
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Test Skill\n\nDescription.")
        skills = SkillLoader.discover(resources_root=tmp_path, extra_paths=[tmp_path])
        for s in skills:
            assert isinstance(s, SkillSpec)
            assert s.name
            assert s.path

    def test_list_available_returns_sorted_by_name(self, tmp_path):
        from ascendc_devkit.capabilities.skill import SkillLoader
        (tmp_path / "b-skill").mkdir()
        (tmp_path / "b-skill" / "SKILL.md").write_text("# B")
        (tmp_path / "a-skill").mkdir()
        (tmp_path / "a-skill" / "SKILL.md").write_text("# A")
        specs = SkillLoader.list_available(extra_paths=[tmp_path])
        assert isinstance(specs, list)
        names = [s.name for s in specs]
        assert names == sorted(names)
        assert "a-skill" in names
        assert "b-skill" in names

    def test_validate_with_extra_paths(self):
        from ascendc_devkit.capabilities.skill import SkillLoader
        # ascend-hardware and ascendc-dev-knowledge migrated into the shared
        # plugin; validate against the plugin's skills/ dir.
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        shared_skills = project_root / ".claude" / "skills"
        if not shared_skills.exists():
            return  # skip if shared plugin doesn't exist
        missing = SkillLoader.validate(
            ["ascend-hardware", "ascendc-dev-knowledge"],
            extra_paths=[shared_skills],
        )
        assert missing == []

    def test_validate_detects_missing(self, tmp_path):
        from ascendc_devkit.capabilities.skill import SkillLoader
        (tmp_path / "existing").mkdir()
        (tmp_path / "existing" / "SKILL.md").write_text("# X")
        missing = SkillLoader.validate(
            ["existing", "nonexistent-skill-xyz"],
            extra_paths=[tmp_path],
        )
        assert missing == ["nonexistent-skill-xyz"]

    def test_empty_skills_dir_returns_empty(self):
        from ascendc_devkit.capabilities.skill.loader import SkillLoader
        with tempfile.TemporaryDirectory() as tmpdir:
            skills_dir = Path(tmpdir)
            result = SkillLoader._find_skill_dirs(skills_dir)
            assert result == set()

    def test_find_skill_dirs_detects_valid_skills(self):
        from ascendc_devkit.capabilities.skill.loader import SkillLoader
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a valid skill dir with SKILL.md
            skill_dir = Path(tmpdir) / "my-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("# My Skill")
            # Create a dir without SKILL.md — should be skipped
            (Path(tmpdir) / "not-a-skill").mkdir()
            result = SkillLoader._find_skill_dirs(Path(tmpdir))
            assert result == {"my-skill"}

    def test_skill_validation_in_spawn_agent_warns_on_missing(self):
        """Runner warns but doesn't block when skills are missing."""
        from ascendc_devkit.orchestration.kernel.action import SpawnAgent
        from ascendc_devkit.orchestration.kernel.runner import Runner
        runner = Runner()
        result = {}
        action = SpawnAgent(
            agent_name="test-agent",
            prompt="test",
            skills=["nonexistent-skill-abc-123"],
        )
        # Should not raise — just logs warning
        runner._execute_spawn_agent(action, result)
        # No backend set, so no agent_result in result
        assert "agent_result" not in result


class TestAgentManifest:
    """Agent manifest parsing from .md files."""

    def test_load_manifest_from_named_pattern(self, tmp_path):
        from ascendc_devkit.capabilities.skill.loader import load_agent_manifest
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "test-agent.md").write_text(
            "You are an expert developer named test-agent.\n\n"
            "Your task is to write code.\n"
        )
        manifest = load_agent_manifest("test-agent", resources_root=tmp_path / "resources")
        assert manifest.name == "test-agent"
        assert manifest.skills == []
        assert "expert developer" in manifest.description

    def test_load_manifest_with_frontmatter(self, tmp_path):
        from ascendc_devkit.capabilities.skill.loader import load_agent_manifest
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "my-agent.md").write_text(
            "---\n"
            "name: my-agent\n"
            "skills: [skill-a, skill-b]\n"
            "description: A test agent\n"
            "---\n"
            "Body content here.\n"
        )
        manifest = load_agent_manifest("my-agent", resources_root=tmp_path / "resources")
        assert manifest.name == "my-agent"
        assert manifest.skills == ["skill-a", "skill-b"]
        assert manifest.description == "A test agent"

    def test_load_manifest_missing_file(self, tmp_path):
        from ascendc_devkit.capabilities.skill.loader import load_agent_manifest
        manifest = load_agent_manifest("no-such-agent", resources_root=tmp_path / "resources")
        assert manifest.name == "no-such-agent"
        assert manifest.skills == []
        assert manifest.description == ""

    def test_load_manifest_frontmatter_name_defaults(self, tmp_path):
        from ascendc_devkit.capabilities.skill.loader import load_agent_manifest
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "coded.md").write_text(
            "---\n"
            "skills: [s1]\n"
            "---\n"
            "You are an expert named actual-name.\n"
        )
        manifest = load_agent_manifest("coded", resources_root=tmp_path / "resources")
        assert manifest.name == "coded"  # fallback to filename
        assert manifest.skills == ["s1"]

    def test_load_manifest_parses_tools_and_max_turns(self, tmp_path):
        from ascendc_devkit.capabilities.skill.loader import load_agent_manifest
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "tooled.md").write_text(
            "---\n"
            "name: tooled\n"
            "skills: [s1]\n"
            "allowed_tools: [Read, Write, mcp__engine__resolve_ambiguity]\n"
            "disallowed_tools: [Task]\n"
            "max_turns: 20\n"
            "---\n"
            "Body.\n"
        )
        m = load_agent_manifest("tooled", resources_root=tmp_path / "resources")
        assert m.allowed_tools == ["Read", "Write", "mcp__engine__resolve_ambiguity"]
        assert m.disallowed_tools == ["Task"]
        assert m.max_turns == 20

    def test_load_manifest_tools_default_empty(self, tmp_path):
        from ascendc_devkit.capabilities.skill.loader import load_agent_manifest
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "bare.md").write_text(
            "---\nname: bare\nskills: [s1]\n---\nBody.\n"
        )
        m = load_agent_manifest("bare", resources_root=tmp_path / "resources")
        assert m.allowed_tools == []
        assert m.disallowed_tools == []
        assert m.max_turns is None


class TestValidateManifest:
    """validate_manifest surfaces bad skills/tools at load time (D2)."""

    def _agent(self, tmp_path, frontmatter: str, name: str = "a"):
        from ascendc_devkit.capabilities.skill.loader import load_agent_manifest
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        (agents_dir / f"{name}.md").write_text(frontmatter)
        return load_agent_manifest(name, resources_root=tmp_path / "resources")

    def _mk_skill(self, tmp_path, skill_name: str):
        d = tmp_path / ".claude" / "skills" / skill_name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(f"# {skill_name}")

    def test_valid_manifest_no_errors(self, tmp_path):
        from ascendc_devkit.capabilities.skill.loader import validate_manifest
        self._mk_skill(tmp_path, "good-skill")
        m = self._agent(
            tmp_path,
            "---\nname: a\nskills: [good-skill]\n"
            "allowed_tools: [Read, mcp__engine__resolve_ambiguity]\nmax_turns: 5\n---\nBody.\n",
        )
        assert validate_manifest(m, resources_root=tmp_path / "resources") == []

    def test_missing_skill_reported(self, tmp_path):
        from ascendc_devkit.capabilities.skill.loader import validate_manifest
        m = self._agent(tmp_path, "---\nname: a\nskills: [no-such-skill]\n---\nBody.\n")
        errs = validate_manifest(m, resources_root=tmp_path / "resources")
        assert any("no-such-skill" in e for e in errs)

    def test_malformed_mcp_tool_reported(self, tmp_path):
        from ascendc_devkit.capabilities.skill.loader import validate_manifest
        m = self._agent(
            tmp_path,
            "---\nname: a\nallowed_tools: [mcp_engine_resolve]\n---\nBody.\n",
        )
        errs = validate_manifest(m, resources_root=tmp_path / "resources")
        assert any("mcp__" in e for e in errs)

    def test_bad_max_turns_reported(self, tmp_path):
        from ascendc_devkit.capabilities.skill.loader import validate_manifest
        m = self._agent(tmp_path, "---\nname: a\nmax_turns: 0\n---\nBody.\n")
        errs = validate_manifest(m, resources_root=tmp_path / "resources")
        assert any("max_turns" in e for e in errs)


class TestProjectAgentManifests:
    """Regression: real .claude/agents manifests parse and validate clean."""

    AGENTS = [
        "requirement-analyst", "ascendc-coder",
        "incremental-developer", "perf-tuner",
        "ascendc-design-generator",
    ]

    def test_all_manifests_validate(self):
        from ascendc_devkit.capabilities.skill.loader import (
            load_agent_manifest, validate_manifest,
        )
        for agent in self.AGENTS:
            m = load_agent_manifest(agent)
            # 相1: skills are discovered natively from the single flat tree
            # (.claude/skills/<skill>/) by both backends — no plugin packaging,
            # no `plugins:` frontmatter. The manifest just parses + validates.
            assert validate_manifest(m) == [], f"{agent} manifest invalid"

    def test_decision_agents_whitelist_mcp_tool(self):
        """Agents that resolve design ambiguity must allow the decision tool."""
        from ascendc_devkit.capabilities.skill.loader import load_agent_manifest
        for agent in ("requirement-analyst", "ascendc-design-generator"):
            m = load_agent_manifest(agent)
            assert "mcp__engine__resolve_ambiguity" in m.allowed_tools


class TestResolveSkills:
    """Skill resolution with agent whitelist filtering."""

    def test_resolve_with_whitelist_filters(self, tmp_path):
        from ascendc_devkit.capabilities.skill.loader import resolve_skills
        # Create skills for testing
        skills_dir = tmp_path / ".claude" / "skills" / "skill-a"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text("# Skill A")
        skills_dir2 = tmp_path / ".claude" / "skills" / "skill-b"
        skills_dir2.mkdir(parents=True)
        (skills_dir2 / "SKILL.md").write_text("# Skill B")

        # Create agent with whitelist
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "test-agent.md").write_text(
            "---\n"
            "name: test-agent\n"
            "skills: [skill-a]\n"
            "---\n"
            "Body.\n"
        )

        result = resolve_skills("test-agent", ["skill-a", "skill-b"],
                                resources_root=tmp_path / "resources")
        names = [s.name for s in result]
        assert "skill-a" in names
        assert "skill-b" not in names

    def test_resolve_without_whitelist_passes_all(self, tmp_path):
        from ascendc_devkit.capabilities.skill.loader import resolve_skills
        skills_dir = tmp_path / ".claude" / "skills" / "skill-x"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text("# Skill X")

        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "no-fm.md").write_text("Plain text agent.")

        result = resolve_skills("no-fm", ["skill-x"],
                                resources_root=tmp_path / "resources")
        assert len(result) == 1
        assert result[0].name == "skill-x"


class TestSkillSpecDescription:
    """Skill description extraction from SKILL.md."""

    def test_reads_description_from_heading(self, tmp_path):
        from ascendc_devkit.capabilities.skill.loader import SkillLoader
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# NPU hardware environment checker\n\nBody content.")
        desc = SkillLoader._read_skill_description(skill_dir)
        assert desc == "NPU hardware environment checker"

    def test_reads_description_heading_without_space(self, tmp_path):
        from ascendc_devkit.capabilities.skill.loader import SkillLoader
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("#MySkill\n\nBody.")
        desc = SkillLoader._read_skill_description(skill_dir)
        assert desc == "MySkill"

    def test_no_heading_returns_first_line(self, tmp_path):
        from ascendc_devkit.capabilities.skill.loader import SkillLoader
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("Just some text.\nMore text.")
        desc = SkillLoader._read_skill_description(skill_dir)
        assert desc == "Just some text."

    def test_missing_skill_md_returns_empty(self, tmp_path):
        from ascendc_devkit.capabilities.skill.loader import SkillLoader
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        desc = SkillLoader._read_skill_description(empty_dir)
        assert desc == ""


class TestRenderSkillInjection:
    """D2 (2.1): skill delivery lives at the backend boundary, not the stage.

    render_skill_injection is the SDK-agnostic seam the stages feed via
    SpawnAgent.primary_skill. Claude renders it as a LEADING /<skill> slash
    (session expands SKILL.md); opencode consumes primary_skill differently
    (first-call + permission closure) so it does NOT reuse this function.
    """

    def test_prepends_slash_when_skill_given(self):
        from ascendc_devkit.capabilities.agent._shared import (
            render_skill_injection)
        out = render_skill_injection("do the thing", "ascendc-op-dev-coding")
        assert out == "/ascendc-op-dev-coding\n\ndo the thing"
        # first line is exactly the bare slash command (§4.3 expansion trigger)
        assert out.split("\n", 1)[0] == "/ascendc-op-dev-coding"

    def test_passthrough_when_none(self):
        from ascendc_devkit.capabilities.agent._shared import (
            render_skill_injection)
        # primary_skill=None (codegen keeps open allowlist / skill-less spawns)
        assert render_skill_injection("body", None) == "body"

    def test_passthrough_when_empty(self):
        from ascendc_devkit.capabilities.agent._shared import (
            render_skill_injection)
        assert render_skill_injection("body", "") == "body"

    def test_no_concrete_sdk_import_in_shared(self):
        # _shared must stay SDK-agnostic (§1.6): its source must not import
        # claude_agent_sdk (concrete SDK). Static AST guard — no global
        # sys.modules mutation, so it can't pollute sibling tests.
        import ast
        import ascendc_devkit.capabilities.agent._shared as shared
        tree = ast.parse(Path(shared.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all("claude_agent_sdk" not in a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert "claude_agent_sdk" not in (node.module or "")
    """SDKBackend._spawn() detecting pending_decision.json → DecisionPendingError."""

    def test_raises_decision_pending_when_pending_file_exists(self, tmp_path):
        """After agent completes, pending_decision.json triggers DecisionPendingError."""
        from unittest import mock as umock
        from ascendc_devkit.domain.exceptions import DecisionPendingError
        import json
        import asyncio

        decision_ws = tmp_path / "decision_ws"
        decision_ws.mkdir()
        (decision_ws / "pending_decision.json").write_text(json.dumps({
            "question": "Which tiling strategy?",
            "options": ["tile_32", "tile_64"],
        }))
        (tmp_path / "agents").mkdir()

        async def fake_query(*args, **kwargs):
            from claude_agent_sdk.types import AssistantMessage, TextBlock
            yield AssistantMessage(content=[TextBlock(text="done")], model="claude-sonnet-4-6")

        with umock.patch("ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server", return_value={}):
            with umock.patch("claude_agent_sdk.query", side_effect=fake_query):
                from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
                backend = SDKBackend(
                    interactive=False,
                    working_dir=tmp_path,
                    on_decision="abort",
                    decision_workspace=decision_ws,
                )
                with pytest.raises(DecisionPendingError) as exc_info:
                    asyncio.run(backend._spawn("test-agent", "do something", {}))
                assert "Which tiling strategy?" in str(exc_info.value.question)
                assert exc_info.value.options == ["tile_32", "tile_64"]

    def test_no_pending_file_returns_agent_result(self, tmp_path):
        """When no pending_decision.json, _spawn returns normal AgentResult."""
        from unittest import mock as umock
        import asyncio

        (tmp_path / "agents").mkdir()

        async def fake_query(*args, **kwargs):
            from claude_agent_sdk.types import AssistantMessage, TextBlock
            yield AssistantMessage(content=[TextBlock(text="result content")], model="claude-sonnet-4-6")

        with umock.patch("ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server", return_value={}):
            with umock.patch("claude_agent_sdk.query", side_effect=fake_query):
                from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
                backend = SDKBackend(
                    interactive=False,
                    working_dir=tmp_path,
                    on_decision="abort",
                    decision_workspace=tmp_path,
                )
                result = asyncio.run(backend._spawn("test-agent", "do something", {}))
                assert result.agent_name == "test-agent"
                assert result.status == "ok"


class TestSDKBackendFailureHandling:
    """F1/F4: query crash mid-run must not be reported as 'ok'; stalled
    turns are cut short."""

    def test_spawn_pins_project_settings_in_options(self, tmp_path, monkeypatch):
        """The spawned ClaudeAgentOptions must pin the project settings file by
        absolute path and constrain setting_sources, so auth loads from the deep
        artifacts cwd (root cause of "Not logged in"). The repo checkout ships no
        .claude/settings.json (machine-local, §1.7) — construct one under the
        temp working dir and chdir into it so _resolve_project_settings finds it."""
        from unittest import mock as umock
        import asyncio
        from pathlib import Path

        (tmp_path / "agents").mkdir()
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.json").write_text(
            '{"env": {}}', encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        captured = {}

        async def fake_query(*args, **kwargs):
            from claude_agent_sdk.types import AssistantMessage, TextBlock
            captured["options"] = kwargs.get("options")
            yield AssistantMessage(content=[TextBlock(text="done")],
                                   model="claude-sonnet-4-6")

        with umock.patch(
            "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
            return_value={},
        ), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
            from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
            backend = SDKBackend(interactive=False, working_dir=tmp_path,
                                 on_decision="default", decision_workspace=tmp_path)
            asyncio.run(backend._spawn("coder", "code it", {}))

        opts = captured["options"]
        # settings pinned to the project's .claude/settings.json (absolute).
        assert opts.settings is not None
        p = Path(opts.settings)
        assert p.is_absolute() and p.exists()
        assert p.name == "settings.json" and p.parent.name == ".claude"
        # Loading constrained to project/local layers (no implicit cwd walk-up).
        assert opts.setting_sources == ["project", "local"]

    def test_query_crash_with_files_returns_partial(self, tmp_path):
        """F1: an exception after the agent wrote files → status 'partial'
        (not 'ok'), with the failure reason captured in metrics."""
        from unittest import mock as umock
        import asyncio

        (tmp_path / "agents").mkdir()

        async def fake_query(*args, **kwargs):
            from claude_agent_sdk.types import AssistantMessage, TextBlock
            yield AssistantMessage(content=[TextBlock(text="partial work")],
                                   model="claude-sonnet-4-6")
            # Agent writes a file, then the query crashes.
            (tmp_path / "gelu.cpp").write_text("// half-written")
            raise RuntimeError("API Error: Content block not found")

        with umock.patch(
            "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
            return_value={},
        ), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
            from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
            backend = SDKBackend(interactive=False, working_dir=tmp_path,
                                 on_decision="default", decision_workspace=tmp_path)
            result = asyncio.run(backend._spawn("coder", "code it", {}))
        assert result.status == "partial"
        assert "gelu.cpp" in result.artifacts
        assert "Content block not found" in result.metrics.get("failure_reason", "")
        # fail-open：一个无 infra marker 的普通 crash → _build_result 兜底
        # infra_transient（未知 crash 默认有界重试），不再落「中性失败」夹缝。
        assert result.error_type == "infra_transient"

    def test_query_crash_infra_marker_classified_through_salvage(self, tmp_path):
        """P50: a crash whose text carries an infra marker (gateway has no
        channel for the model — a config/quota error, not a logic failure) is
        classified error_type="infra" via the *real* salvage path, not just by
        direct _classify_error_type calls. Guards the salvage→error_type wiring."""
        from unittest import mock as umock
        import asyncio

        (tmp_path / "agents").mkdir()

        async def fake_query(*args, **kwargs):
            from claude_agent_sdk.types import AssistantMessage, TextBlock
            yield AssistantMessage(content=[TextBlock(text="x")],
                                   model="claude-sonnet-4-6")
            raise RuntimeError("Error: No available channel for model deepseek-v4-pro")

        with umock.patch(
            "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
            return_value={},
        ), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
            from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
            backend = SDKBackend(interactive=False, working_dir=tmp_path,
                                 on_decision="default", decision_workspace=tmp_path)
            result = asyncio.run(backend._spawn("coder", "code it", {}))
        assert result.status == "fatal"
        assert result.error_type == "infra"

    def test_query_crash_no_files_returns_fatal(self, tmp_path):
        """F1: a crash with no files written stays 'fatal'."""
        from unittest import mock as umock
        import asyncio

        (tmp_path / "agents").mkdir()

        async def fake_query(*args, **kwargs):
            from claude_agent_sdk.types import AssistantMessage, TextBlock
            yield AssistantMessage(content=[TextBlock(text="x")],
                                   model="claude-sonnet-4-6")
            raise RuntimeError("boom")

        with umock.patch(
            "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
            return_value={},
        ), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
            from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
            backend = SDKBackend(interactive=False, working_dir=tmp_path,
                                 on_decision="default", decision_workspace=tmp_path)
            result = asyncio.run(backend._spawn("coder", "code it", {}))
        assert result.status == "fatal"
        # fail-open：非 infra 文案的 crash（"boom"）→ 兜底 infra_transient。
        assert result.error_type == "infra_transient"

    def test_stalled_turns_break_early(self, tmp_path):
        """F4: many consecutive no-progress turns (no new text, no tool use)
        stop the loop early and collect existing output."""
        from unittest import mock as umock
        import asyncio
        from ascendc_devkit.capabilities.agent import sdk_backend as sb

        (tmp_path / "agents").mkdir()
        emitted = {"n": 0}

        async def fake_query(*args, **kwargs):
            from claude_agent_sdk.types import AssistantMessage, TextBlock
            # First turn produces text, then 10 empty (stalled) turns.
            yield AssistantMessage(content=[TextBlock(text="initial")],
                                   model="claude-sonnet-4-6")
            for _ in range(10):
                emitted["n"] += 1
                yield AssistantMessage(content=[TextBlock(text="")],
                                       model="claude-sonnet-4-6")

        with umock.patch(
            "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
            return_value={},
        ), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
            from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
            backend = SDKBackend(interactive=False, working_dir=tmp_path,
                                 on_decision="default", decision_workspace=tmp_path)
            result = asyncio.run(backend._spawn("coder", "code it", {}))
        # The loop must break after NORMAL_MAX_STALLED_TURNS rather than
        # draining all 10.  Adaptive threshold: turns 1-8 use bootstrap max (5),
        # so the stall breaks at turn 6 (stalled_turns=5).  Assert against the
        # actual threshold the code uses, not the doc-default MAX_STALLED_TURNS.
        assert emitted["n"] <= sb.BOOTSTRAP_MAX_STALLED
        assert result.status == "ok"


def _result_msg(text):
    """Build a ResultMessage carrying `text` as its result, filling the
    many required dataclass fields with neutral values (step-5a tests)."""
    from claude_agent_sdk.types import ResultMessage
    return ResultMessage(
        subtype="success", duration_ms=1, duration_api_ms=1, is_error=True,
        num_turns=1, session_id="sess-1", stop_reason=None,
        total_cost_usd=0.0, usage={}, result=text,
        structured_output=None, model_usage={}, permission_denials=[],
        deferred_tool_use=None, errors=[], api_error_status=None, uuid="u1")


class TestSDKBackendResumeRetry:
    """step-5a B2-resume: on transient 'Content block not found', the spawn
    resumes the crashed session by session_id rather than failing the whole
    run. Two gates bound the loop (total budget N, no-progress M)."""

    def test_transient_crash_then_resume_succeeds(self, tmp_path):
        """T2: first attempt crashes with the transient error; the resume
        attempt writes a file. The file is salvaged and query is called >=2x."""
        from unittest import mock as umock
        import asyncio
        from claude_agent_sdk.types import (
            AssistantMessage, TextBlock, SystemMessage)

        (tmp_path / "agents").mkdir()
        calls = {"n": 0}

        async def fake_query(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                yield SystemMessage(subtype="init",
                                    data={"session_id": "sess-1"})
                yield AssistantMessage(content=[TextBlock(text="thinking")],
                                       model="m")
                yield _result_msg("API Error: Content block not found")
                raise RuntimeError("API Error: Content block not found")
            # resume attempt: writes a file and finishes cleanly
            yield AssistantMessage(content=[TextBlock(text="resumed")],
                                   model="m")
            (tmp_path / "k.cpp").write_text("// done")

        with umock.patch(
            "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
            return_value={},
        ), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
            from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
            backend = SDKBackend(interactive=False, working_dir=tmp_path,
                                 on_decision="default", decision_workspace=tmp_path)
            result = asyncio.run(backend._spawn("coder", "code it", {}))
        assert calls["n"] >= 2  # resume was attempted
        assert "k.cpp" in result.artifacts
        assert result.status in ("ok", "partial")

    def test_no_progress_gate_stops_early(self, tmp_path):
        """T3: every attempt crashes with zero progress (no text/tool/files).
        The no-progress gate (M=3) stops well before the budget (N=10)."""
        from unittest import mock as umock
        import asyncio
        from claude_agent_sdk.types import SystemMessage

        (tmp_path / "agents").mkdir()
        calls = {"n": 0}

        async def fake_query(*args, **kwargs):
            calls["n"] += 1
            yield SystemMessage(subtype="init", data={"session_id": "sess-1"})
            yield _result_msg("API Error: Content block not found")
            raise RuntimeError("API Error: Content block not found")

        with umock.patch(
            "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
            return_value={},
        ), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
            from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
            backend = SDKBackend(interactive=False, working_dir=tmp_path,
                                 on_decision="default", decision_workspace=tmp_path)
            result = asyncio.run(backend._spawn("coder", "code it", {}))
        # first attempt + up to M=3 no-progress resumes; far below N=10.
        assert calls["n"] <= 5
        assert result.status == "fatal"

    def test_non_transient_error_not_retried(self, tmp_path):
        """T4: a non-transient error ('boom') is not retried — exactly one
        query call, and the existing fatal/partial semantics hold."""
        from unittest import mock as umock
        import asyncio
        from claude_agent_sdk.types import AssistantMessage, TextBlock

        (tmp_path / "agents").mkdir()
        calls = {"n": 0}

        async def fake_query(*args, **kwargs):
            calls["n"] += 1
            yield AssistantMessage(content=[TextBlock(text="x")], model="m")
            raise RuntimeError("boom")

        with umock.patch(
            "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
            return_value={},
        ), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
            from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
            backend = SDKBackend(interactive=False, working_dir=tmp_path,
                                 on_decision="default", decision_workspace=tmp_path)
            result = asyncio.run(backend._spawn("coder", "code it", {}))
        assert calls["n"] == 1  # no retry on non-transient error
        assert result.status == "fatal"

    def test_total_budget_gate_caps_retries(self, tmp_path):
        """T5: each attempt makes progress (writes a new file) but always
        crashes transiently. The total-budget gate (N) caps the loop."""
        from unittest import mock as umock
        import asyncio
        from claude_agent_sdk.types import (
            AssistantMessage, TextBlock, SystemMessage)

        (tmp_path / "agents").mkdir()
        calls = {"n": 0}

        async def fake_query(*args, **kwargs):
            calls["n"] += 1
            yield SystemMessage(subtype="init", data={"session_id": "sess-1"})
            # each attempt writes a *new* file → always "progress"
            (tmp_path / f"f{calls['n']}.cpp").write_text("//")
            yield AssistantMessage(content=[TextBlock(text=f"t{calls['n']}")],
                                   model="m")
            yield _result_msg("API Error: Content block not found")
            raise RuntimeError("API Error: Content block not found")

        with umock.patch(
                "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
                return_value={}), \
             umock.patch("claude_agent_sdk.query", side_effect=fake_query):
            from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
            # N=4 budget injected via constructor (DI; config resolved in L2).
            backend = SDKBackend(interactive=False, working_dir=tmp_path,
                                 on_decision="default", decision_workspace=tmp_path,
                                 resume_max_retries=4, resume_max_no_progress=3)
            result = asyncio.run(backend._spawn("coder", "code it", {}))
        # first attempt + N=4 resumes = 5 total; never reaches an unbounded loop
        assert calls["n"] == 5
        assert result.status == "partial"


class TestSDKBackendTranscript:
    """Task 1.2: agent session transcript persisted to <run>/agents/*.jsonl."""

    def test_transcript_records_text_and_tool_use(self, tmp_path):
        """A spawn writes one jsonl line per SDK event, including tool_use."""
        from unittest import mock as umock
        import asyncio
        import json

        async def fake_query(*args, **kwargs):
            from claude_agent_sdk.types import (
                AssistantMessage, TextBlock, ToolUseBlock,
            )
            yield AssistantMessage(
                content=[TextBlock(text="thinking about it")],
                model="claude-sonnet-4-6")
            yield AssistantMessage(
                content=[ToolUseBlock(
                    id="t1", name="mcp__engine__resolve_ambiguity",
                    input={"question": "Q?", "options": ["a", "b"]})],
                model="claude-sonnet-4-6")

        with umock.patch(
            "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
            return_value={},
        ), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
            from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
            backend = SDKBackend(
                interactive=False,
                working_dir=tmp_path,
                on_decision="default",
                decision_workspace=tmp_path,  # <run> root → agents/ derived
            )
            asyncio.run(backend._spawn("ascendc-coder", "do it", {}))

        transcript = tmp_path / "agents" / "ascendc-coder-01.jsonl"
        assert transcript.exists()
        lines = [json.loads(ln) for ln in transcript.read_text().splitlines() if ln]
        assert len(lines) == 2
        kinds = [b["kind"] for rec in lines for b in rec.get("blocks", [])]
        assert "text" in kinds
        assert "tool_use" in kinds
        tool_rec = next(b for rec in lines for b in rec.get("blocks", [])
                        if b["kind"] == "tool_use")
        assert tool_rec["tool_name"] == "mcp__engine__resolve_ambiguity"
        assert tool_rec["tool_input"]["options"] == ["a", "b"]

    def test_transcript_seq_increments_per_agent(self, tmp_path):
        """Multiple spawns of the same agent produce -01, -02 files."""
        from unittest import mock as umock
        import asyncio

        async def fake_query(*args, **kwargs):
            from claude_agent_sdk.types import AssistantMessage, TextBlock
            yield AssistantMessage(content=[TextBlock(text="ok")],
                                   model="claude-sonnet-4-6")

        with umock.patch(
            "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
            return_value={},
        ), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
            from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
            backend = SDKBackend(
                interactive=False, working_dir=tmp_path,
                on_decision="default", decision_workspace=tmp_path,
            )
            asyncio.run(backend._spawn("ascendc-coder", "r1", {}))
            asyncio.run(backend._spawn("ascendc-coder", "r2", {}))

        agents = tmp_path / "agents"
        assert (agents / "ascendc-coder-01.jsonl").exists()
        assert (agents / "ascendc-coder-02.jsonl").exists()

    def test_transcript_branch_label_in_filename(self, tmp_path):
        """§P2: parallel branches of a reused role agent get distinct transcript
        files keyed by branch_label, not a colliding per-agent seq."""
        from unittest import mock as umock
        import asyncio

        async def fake_query(*args, **kwargs):
            from claude_agent_sdk.types import AssistantMessage, TextBlock
            yield AssistantMessage(content=[TextBlock(text="ok")],
                                   model="claude-sonnet-4-6")

        with umock.patch(
            "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
            return_value={},
        ), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
            from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
            backend = SDKBackend(
                interactive=False, working_dir=tmp_path,
                on_decision="default", decision_workspace=tmp_path,
            )
            asyncio.run(backend._spawn("ascendc-design-generator", "r", {},
                                       stage_name="split", branch_label="T1"))
            asyncio.run(backend._spawn("ascendc-design-generator", "r", {},
                                       stage_name="split", branch_label="T2"))

        agents = tmp_path / "agents"
        # Distinct files per template, each starting its own seq at 01.
        assert (agents / "ascendc-design-generator-T1-01.jsonl").exists()
        assert (agents / "ascendc-design-generator-T2-01.jsonl").exists()

    def test_no_workspace_skips_transcript_without_error(self, tmp_path):
        """Without decision_workspace, spawn still works (no transcript)."""
        from unittest import mock as umock
        import asyncio

        async def fake_query(*args, **kwargs):
            from claude_agent_sdk.types import AssistantMessage, TextBlock
            yield AssistantMessage(content=[TextBlock(text="ok")],
                                   model="claude-sonnet-4-6")

        with umock.patch(
            "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
            return_value={},
        ), umock.patch("claude_agent_sdk.query", side_effect=fake_query):
            from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
            backend = SDKBackend(
                interactive=False, working_dir=tmp_path, on_decision="default")
            result = asyncio.run(backend._spawn("ascendc-coder", "x", {}))
        assert result.agent_name == "ascendc-coder"
        assert not (tmp_path / "agents").exists()


class TestSDKBackendProvider:
    """SDKBackend LLM provider and webhook URL integration (Slice 7)."""

    def test_default_allowed_tools_uses_mcp_full_name_only(self, tmp_path):
        """Task 1.1: default allowed_tools exposes the MCP-qualified decision
        tool and no longer carries the redundant bare alias. The bare name was
        proven unnecessary by tests/st/test_decision_transcript.py (real link).
        """
        from unittest import mock as umock
        with umock.patch(
            "ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
            return_value={},
        ):
            from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
            backend = SDKBackend(interactive=False, working_dir=tmp_path)
            assert "mcp__engine__resolve_ambiguity" in backend._allowed_tools
            assert "resolve_ambiguity" not in backend._allowed_tools

    def test_sdk_backend_stores_webhook_url(self, tmp_path):
        """SDKBackend stores webhook_url for MCP server construction."""
        from unittest import mock as umock
        with umock.patch("ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
                         return_value={}):
            from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
            backend = SDKBackend(
                interactive=False,
                working_dir=tmp_path,
                webhook_url="https://hooks.example.com/decisions",
            )
            assert backend._webhook_url == "https://hooks.example.com/decisions"

    def test_sdk_backend_webhook_url_none_by_default(self, tmp_path):
        """Without webhook_url, _webhook_url defaults to None."""
        from unittest import mock as umock
        with umock.patch("ascendc_devkit.capabilities.agent.sdk_backend.build_engine_mcp_server",
                         return_value={}):
            from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
            backend = SDKBackend(interactive=False, working_dir=tmp_path)
            assert backend._webhook_url is None


class TestNotifyWebhookHandler:
    """notify-webhook handler tests (Slice 7)."""

    def test_notify_webhook_returns_default_on_timeout(self, tmp_path):
        """When webhook times out, handler falls back to default (first option)."""
        handler = create_resolve_ambiguity_handler(
            interactive=False,
            on_decision="notify-webhook",
            workspace_dir=str(tmp_path),
            webhook_url="http://localhost:19999/nonexistent",
        )
        import asyncio
        result = asyncio.run(handler({
            "question": "Which tiling?",
            "options": ["tile_32", "tile_64"],
        }))
        # Should fall back to first option on timeout
        assert result["content"][0]["text"] == "tile_32"

    def test_notify_webhook_no_url_returns_default(self, tmp_path):
        """When webhook_url is None, immediately falls back to default."""
        handler = create_resolve_ambiguity_handler(
            interactive=False,
            on_decision="notify-webhook",
            workspace_dir=str(tmp_path),
            webhook_url=None,
        )
        import asyncio
        result = asyncio.run(handler({
            "question": "Q?",
            "options": ["A", "B"],
        }))
        assert result["content"][0]["text"] == "A"

    def test_build_engine_mcp_server_passes_webhook_url(self):
        """build_engine_mcp_server returns valid MCP server config."""
        # Use a simpler test: build_engine_mcp_server doesn't crash with webhook_url
        from unittest import mock as umock
        # claude_agent_sdk may not be available in CI — test that the function
        # handles the import correctly
        try:
            from claude_agent_sdk import create_sdk_mcp_server  # noqa: F401
            sdk_available = True
        except ImportError:
            sdk_available = False

        if not sdk_available:
            pytest.skip("claude_agent_sdk not available")

        result = build_engine_mcp_server(
            interactive=False,
            on_decision="notify-webhook",
            workspace_dir="/tmp/test",
            webhook_url="https://hooks.example.com/decisions",
        )
        assert result is not None


class TestAgentPromptLoading:
    """_find_agent_prompt loads from .claude/agents and strips frontmatter so
    the same file is discoverable by the Claude Code TUI and usable by the SDK."""

    def test_strip_frontmatter_removes_yaml_block(self):
        from ascendc_devkit.capabilities.agent.sdk_backend import _strip_frontmatter
        text = "---\nname: foo\ndescription: bar\n---\n\nYou are foo.\nBody line."
        assert _strip_frontmatter(text) == "You are foo.\nBody line."

    def test_strip_frontmatter_passthrough_without_block(self):
        from ascendc_devkit.capabilities.agent.sdk_backend import _strip_frontmatter
        text = "You are foo.\nNo frontmatter here."
        assert _strip_frontmatter(text) == text

    def test_strip_frontmatter_malformed_no_close_returns_text(self):
        from ascendc_devkit.capabilities.agent.sdk_backend import _strip_frontmatter
        text = "---\nname: foo\nno closing fence\nbody"
        assert _strip_frontmatter(text) == text

    def test_find_agent_prompt_loads_from_claude_agents(self):
        from ascendc_devkit.capabilities.agent.sdk_backend import _find_agent_prompt
        prompt = _find_agent_prompt("requirement-analyst")
        # Real project file is loaded (not the fallback placeholder)...
        assert prompt.startswith("You are a requirement analyst")
        # ...and the TUI frontmatter is not leaked into the system prompt.
        assert not prompt.lstrip().startswith("---")

    def test_find_agent_prompt_unknown_returns_fallback(self):
        from ascendc_devkit.capabilities.agent.sdk_backend import _find_agent_prompt
        prompt = _find_agent_prompt("no-such-agent-xyz")
        assert prompt == "You are no-such-agent-xyz. Complete the task as described."

    def test_placeholder_true_for_missing_agent(self):
        from ascendc_devkit.capabilities.agent.sdk_backend import (
            agent_prompt_is_placeholder,
        )
        assert agent_prompt_is_placeholder("no-such-agent-xyz") is True

    def test_placeholder_false_for_real_agent(self):
        from ascendc_devkit.capabilities.agent.sdk_backend import (
            agent_prompt_is_placeholder,
        )
        assert agent_prompt_is_placeholder("requirement-analyst") is False
        assert agent_prompt_is_placeholder("ascendc-design-generator") is False


class TestResolveProjectSettings:
    """_resolve_project_settings pins .claude/settings.json by absolute path so
    auth (ANTHROPIC_* in its env block) loads regardless of the deep artifacts
    cwd the agent is spawned in — root cause of the "Not logged in" failure."""

    def test_resolves_project_settings_absolute_when_present(self, monkeypatch, tmp_path):
        """Verify absolute-path pinning of .claude/settings.json.

        The repo checkout itself does NOT ship .claude/settings.json (it was moved
        out of git tracking as machine-local auth config — commit 82b4ea3a, §1.7),
        so the fixture is a temp project with the file, chdir'd into for the
        cwd-based fallback arm of _resolve_project_settings."""
        from ascendc_devkit.capabilities.agent.sdk_backend import (
            _resolve_project_settings,
        )
        from pathlib import Path

        (tmp_path / ".claude").mkdir()
        settings = tmp_path / ".claude" / "settings.json"
        settings.write_text('{"env": {}}', encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        path = _resolve_project_settings()
        # A present settings.json must resolve...
        assert path is not None
        p = Path(path)
        # ...as an existing, absolute path to that exact file.
        assert p.is_absolute()
        assert p.exists()
        assert p.name == "settings.json"
        assert p.parent.name == ".claude"

    def test_returns_none_when_absent(self, monkeypatch, tmp_path):
        """When neither the package-root nor cwd has .claude/settings.json,
        return None so the SDK falls back to default discovery (no crash)."""
        import ascendc_devkit.capabilities.agent.sdk_backend as sb
        # _resolve_project_settings now lives in the SDK-agnostic _shared module
        # (2.1 extraction); its Path(__file__) walk reads _shared's __file__, so
        # patch the owning module, not the re-exporting backend.
        import ascendc_devkit.capabilities.agent._shared as shared

        # Point the module's __file__-derived root and cwd at empty dirs.
        fake_pkg_file = tmp_path / "a" / "b" / "c" / "d" / "e" / "mod.py"
        fake_pkg_file.parent.mkdir(parents=True)
        monkeypatch.setattr(shared, "__file__", str(fake_pkg_file))
        monkeypatch.chdir(tmp_path)
        assert sb._resolve_project_settings() is None


class TestAskUserUiNonInteractive:
    """_render_ask_user_ui must never hang in non-TTY environments (CI,
    backgrounded runs, piped/redirected stdin). It raises EOFError so the
    caller applies the configured on_decision strategy rather than the UI
    silently stealing the decision. Regression for the infinite-retry hang.
    """

    def test_non_tty_raises_eoferror_without_calling_input(self):
        from unittest import mock
        from ascendc_devkit.capabilities.mcp_tools import _render_ask_user_ui
        # stdin is the stream that matters (not stderr) — gate on stdin_is_tty.
        with mock.patch(
            "ascendc_devkit.capabilities.mcp_tools.Terminal.stdin_is_tty",
            return_value=False,
        ), mock.patch(
            "ascendc_devkit.capabilities.mcp_tools.input",
            side_effect=AssertionError("input() must not be called when non-TTY"),
        ):
            with pytest.raises(EOFError):
                _render_ask_user_ui("pick one", ["approve", "revise"], default_index=0)

    def test_tty_reads_user_choice(self):
        from unittest import mock
        from ascendc_devkit.capabilities.mcp_tools import _render_ask_user_ui
        with mock.patch(
            "ascendc_devkit.capabilities.mcp_tools.Terminal.stdin_is_tty",
            return_value=True,
        ), mock.patch(
            "ascendc_devkit.capabilities.mcp_tools.input", return_value="2",
        ):
            result = _render_ask_user_ui("pick", ["a", "b", "c"], default_index=0)
        assert result == "b"

    def test_tty_empty_input_selects_default(self):
        from unittest import mock
        from ascendc_devkit.capabilities.mcp_tools import _render_ask_user_ui
        with mock.patch(
            "ascendc_devkit.capabilities.mcp_tools.Terminal.stdin_is_tty",
            return_value=True,
        ), mock.patch(
            "ascendc_devkit.capabilities.mcp_tools.input", return_value="",
        ):
            result = _render_ask_user_ui("pick", ["a", "b", "c"], default_index=2)
        assert result == "c"

    def test_tty_custom_input_slot_returns_free_text(self):
        """Selecting the custom slot (index = len(options)+1) reads a second
        line and returns it verbatim, bypassing the agent's option set."""
        from unittest import mock
        from ascendc_devkit.capabilities.mcp_tools import _render_ask_user_ui
        with mock.patch(
            "ascendc_devkit.capabilities.mcp_tools.Terminal.stdin_is_tty",
            return_value=True,
        ), mock.patch(
            "ascendc_devkit.capabilities.mcp_tools.input",
            side_effect=["3", "mode is required, no default"],
        ):
            result = _render_ask_user_ui("pick", ["a", "b"], default_index=0)
        assert result == "mode is required, no default"

    def test_tty_custom_input_empty_falls_back_to_default(self):
        """Empty free-text in the custom slot falls back to the default option."""
        from unittest import mock
        from ascendc_devkit.capabilities.mcp_tools import _render_ask_user_ui
        with mock.patch(
            "ascendc_devkit.capabilities.mcp_tools.Terminal.stdin_is_tty",
            return_value=True,
        ), mock.patch(
            "ascendc_devkit.capabilities.mcp_tools.input",
            side_effect=["3", "   "],
        ):
            result = _render_ask_user_ui("pick", ["a", "b"], default_index=1)
        assert result == "b"

    def test_tty_eof_mid_prompt_propagates(self):
        """stdin closes mid-session → EOFError propagates so the caller's
        on_decision strategy takes over (never spin on a dead stream)."""
        from unittest import mock
        from ascendc_devkit.capabilities.mcp_tools import _render_ask_user_ui
        with mock.patch(
            "ascendc_devkit.capabilities.mcp_tools.Terminal.stdin_is_tty",
            return_value=True,
        ), mock.patch(
            "ascendc_devkit.capabilities.mcp_tools.input", side_effect=EOFError(),
        ):
            with pytest.raises(EOFError):
                _render_ask_user_ui("pick", ["approve", "revise"], default_index=1)

    def test_interactive_handler_non_tty_falls_back_to_default(self):
        """resolve_ambiguity(interactive=True) on non-TTY stdin must not hang;
        it falls through to on_decision=default and returns the first option."""
        from unittest import mock
        import asyncio
        from ascendc_devkit.capabilities.mcp_tools import (
            create_resolve_ambiguity_handler,
        )
        handler = create_resolve_ambiguity_handler(
            interactive=True, on_decision="default")
        with mock.patch(
            "ascendc_devkit.capabilities.mcp_tools.Terminal.stdin_is_tty",
            return_value=False,
        ), mock.patch(
            "ascendc_devkit.capabilities.mcp_tools.input",
            side_effect=AssertionError("must not read input on non-TTY"),
        ):
            result = asyncio.run(handler({
                "question": "half or interleave?",
                "options": ["half", "interleave"],
            }))
        assert result["content"][0]["text"] == "half"


class TestFilebackupBaselineScans:
    """M3（review 整改）：filebackup: 前缀基线是非 git 降级态——git 侧恒空
    是「不适用」而非「零改动」。此前 has_baseline=True 把整轮产物收集静默
    折叠为空（与「本轮零产出」不可区分）。"""

    def test_filebackup_baseline_degrades_to_scan(self, tmp_path):
        from ascendc_devkit.capabilities.agent._shared import _collect_changed_sources
        from ascendc_devkit.infra.repo_guard import RepoGuard
        op = tmp_path / "op"
        op.mkdir()
        (op / "k.cpp").write_text("int x;\n", encoding="utf-8")
        out = _collect_changed_sources(
            op, repo_guard=RepoGuard(), baseline="filebackup:/tmp/bak",
            has_baseline=True)
        assert "k.cpp" in out, (
            "filebackup 降级基线下产物收集不得恒空（非 git 环境零信号）")

    def test_git_baseline_zero_changes_still_empty(self, tmp_path):
        from ascendc_devkit.capabilities.agent._shared import _collect_changed_sources
        from ascendc_devkit.infra.repo_guard import RepoGuard
        op = tmp_path / "op"
        op.mkdir()
        (op / "pre.cpp").write_text("int pre;\n", encoding="utf-8")
        out = _collect_changed_sources(
            op, repo_guard=RepoGuard(), baseline="HEAD", has_baseline=True)
        assert out == {} or "pre.cpp" not in out  # git 真值：零改动不 scan


class TestDerivedReportProvenance:
    """F7（review 整改）：派生报告带 derived 标记 + 纯契约轮报告恒在。"""

    def test_filebackup_report_not_marked_derived(self, tmp_path):
        # 降级 scan 照带的 agent 自写 changed_files.json 无 derived 标记——
        # 消费方可辨「框架派生」与「agent 自报」。
        import json as _json
        from ascendc_devkit.capabilities.agent._shared import _collect_changed_sources
        from ascendc_devkit.infra.repo_guard import RepoGuard
        op = tmp_path / "op"
        op.mkdir()
        (op / "changed_files.json").write_text(
            _json.dumps({"changed_files": [{"path": "fake.cpp"}]}),
            encoding="utf-8")
        out = _collect_changed_sources(
            op, repo_guard=RepoGuard(), baseline="filebackup:/tmp/bak",
            has_baseline=True)
        assert '"derived"' not in out.get("changed_files.json", "")
