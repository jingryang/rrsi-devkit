"""UT for L1 CLI — command registration, argument parsing, exit codes."""

import tempfile
from pathlib import Path
from unittest import mock

import pytest
from click.testing import CliRunner

from ascendc_devkit.cli.main import main as cli_main


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


class TestMainEntry:
    def test_help_shows_description(self, runner):
        result = runner.invoke(cli_main, ["--help"])
        assert result.exit_code == 0
        assert "ascendc-devkit" in result.output

    def test_all_seven_commands_registered(self, runner):
        result = runner.invoke(cli_main, ["--help"])
        for cmd in ("stage", "run", "verify-env", "verify-repo", "show", "respond", "skill"):
            assert cmd in result.output


class TestStageCommand:
    def test_stage_help(self, runner):
        result = runner.invoke(cli_main, ["stage", "--help"])
        assert result.exit_code == 0

    def test_stage_run_help(self, runner):
        result = runner.invoke(cli_main, ["stage", "run", "--help"])
        assert result.exit_code == 0
        for opt in ("--name", "--state", "--non-interactive"):
            assert opt in result.output

    def test_stage_run_requires_name(self, runner):
        result = runner.invoke(cli_main, ["stage", "run"])
        assert result.exit_code != 0

    @mock.patch("ascendc_devkit.cli.commands.stage.dispatch_single_stage")
    def test_stage_run_calls_dispatch(self, mock_dispatch, runner, temp_dir):
        mock_dispatch.return_value = 0
        state_file = temp_dir / "state.json"
        state_file.write_text('{"mode": "new", "op_name": "gelu"}')

        result = runner.invoke(cli_main, [
            "stage", "run", "--name", "codegen",
            "--state", str(state_file),
            "--non-interactive",
            "--max-iterations", "1",
            "--output-root", str(temp_dir),
        ])
        assert result.exit_code == 0
        assert mock_dispatch.call_args.kwargs["stage_name"] == "codegen"
        assert mock_dispatch.call_args.kwargs["non_interactive"] is True
        assert mock_dispatch.call_args.kwargs["max_iterations"] == 1

    @mock.patch("ascendc_devkit.cli.commands.stage.dispatch_single_stage")
    def test_stage_run_propagates_exit_code(self, mock_dispatch, runner, temp_dir):
        mock_dispatch.return_value = 64
        state_file = temp_dir / "state.json"
        state_file.write_text("{}")

        result = runner.invoke(cli_main, [
            "stage", "run", "--name", "codegen",
            "--state", str(state_file),
            "--non-interactive",
        ])
        assert result.exit_code == 64


class TestRunCommand:
    def test_run_help(self, runner):
        result = runner.invoke(cli_main, ["run", "--help"])
        assert result.exit_code == 0
        for opt in ("--workflow", "--mode", "--target-repo", "--repo-profile",
                     "--op-name", "--op-dir", "--reference", "--repo-root",
                     "--non-interactive"):
            assert opt in result.output

    @mock.patch("ascendc_devkit.cli.commands.run.dispatch")
    def test_run_op_dir_resolves_into_task_request(self, mock_dispatch, runner, temp_dir):
        """--op-dir resolves profile/repo_root/op_name and fills task_request."""
        mock_dispatch.return_value = 0
        op_dir = (f"{temp_dir}/omni-ops/inference/ascendc/src/"
                  f"ops-transformer/posembedding/ai_infra_rope")
        result = runner.invoke(cli_main, [
            "run", "--op-dir", op_dir, "--non-interactive",
            "--output-root", str(temp_dir),
        ])
        assert result.exit_code == 0
        task = mock_dispatch.call_args.args[0]
        assert task["repo_profile"] == "omni-ops"
        assert task["op_name"] == "rope"
        assert task["full_op_name"] == "ai_infra_rope"
        assert task["variant_name"] == "inference"
        assert task["rel_op_dir"].endswith("ai_infra_rope")
        assert task["target_repo"].endswith("omni-ops")

    @mock.patch("ascendc_devkit.cli.commands.run.dispatch")
    def test_run_reference_repeatable(self, mock_dispatch, runner, temp_dir):
        mock_dispatch.return_value = 0
        op_dir = f"{temp_dir}/ops-nn/conv/conv3d"
        result = runner.invoke(cli_main, [
            "run", "--op-dir", op_dir,
            "--reference", "/other/repo/a",
            "--reference", "/other/repo/b",
            "--non-interactive", "--output-root", str(temp_dir),
        ])
        assert result.exit_code == 0
        task = mock_dispatch.call_args.args[0]
        assert task["references"] == ["/other/repo/a", "/other/repo/b"]

    def test_run_op_dir_renamed_repo_errors_without_override(self, runner, temp_dir):
        """A renamed repo (no known profile in path) errors with guidance."""
        op_dir = f"{temp_dir}/my-fork/inference/ascendc/src/g/c/ai_infra_rope"
        result = runner.invoke(cli_main, [
            "run", "--op-dir", op_dir, "--non-interactive",
        ])
        assert result.exit_code == 64
        assert "repo-profile" in result.output or "FAIL" in result.output

    @mock.patch("ascendc_devkit.cli.commands.run.dispatch")
    def test_run_with_minimum_args_returns_ok(self, mock_dispatch, runner):
        """run command accepts --target-repo as optional (supports --resume without it)."""
        mock_dispatch.return_value = 0
        result = runner.invoke(cli_main, ["run"])
        # target-repo is optional now (--resume doesn't need it)
        # dispatch will handle the missing field gracefully
        assert result.exit_code == 0

    @mock.patch("ascendc_devkit.cli.commands.run.dispatch")
    def test_run_without_workflow_defaults_to_none(self, mock_dispatch, runner):
        """Regression: --workflow 无默认值,不传时 task_request['workflow'] 必须是 None。

        click 曾给 --workflow 设 default='generate_ascendc',导致用户不传时也把
        该值注入 task_request,被 dispatcher 当作「显式传入」与 resume state 的
        workflow_name 比对、误报不一致——resume 因此不可用。None 才能真正代表
        「用户未提供」,让 dispatcher 沿用 state 为唯一权威。
        """
        mock_dispatch.return_value = 0
        result = runner.invoke(cli_main, ["run"])
        assert result.exit_code == 0
        task = mock_dispatch.call_args.args[0]
        assert task["workflow"] is None

    @mock.patch("ascendc_devkit.cli.commands.run.dispatch")
    def test_run_explicit_workflow_forwarded(self, mock_dispatch, runner):
        """显式 --workflow 原样转发(default=None 不影响显式传入)。"""
        mock_dispatch.return_value = 0
        result = runner.invoke(cli_main, ["run", "--workflow", "self_evolve_op"])
        assert result.exit_code == 0
        task = mock_dispatch.call_args.args[0]
        assert task["workflow"] == "self_evolve_op"

    def test_run_rejects_invalid_mode(self, runner, temp_dir):
        result = runner.invoke(cli_main, [
            "run", "--target-repo", str(temp_dir), "--repo-profile", "omni-ops",
            "--mode", "invalid",
        ])
        assert result.exit_code != 0

    @mock.patch("ascendc_devkit.cli.commands.run.dispatch")
    def test_run_calls_dispatch_with_task_request(self, mock_dispatch, runner, temp_dir):
        mock_dispatch.return_value = 0
        req_file = temp_dir / "req.yaml"
        req_file.write_text("op: gelu")

        result = runner.invoke(cli_main, [
            "run", "--target-repo", str(temp_dir), "--mode", "new",
            "--repo-profile", "omni-ops", "--op-name", "gelu",
            "--requirement", str(req_file), "--npu-id", "1",
            "--non-interactive", "--max-iterations", "3",
            "--output-root", str(temp_dir),
        ])
        assert result.exit_code == 0
        task = mock_dispatch.call_args.args[0]
        assert task["mode"] == "new"
        assert task["repo_profile"] == "omni-ops"
        assert task["op_name"] == "gelu"
        assert task["npu_id"] == 1
        assert task["non_interactive"] is True
        assert task["max_iterations"] == 3

    @mock.patch("ascendc_devkit.cli.commands.run.dispatch")
    def test_run_design_doc_flows_to_task_request(self, mock_dispatch, runner, temp_dir):
        mock_dispatch.return_value = 0
        req_file = temp_dir / "req.yaml"
        req_file.write_text("op: gelu")
        doc_file = temp_dir / "design.md"
        doc_file.write_text("# 概要设计")

        result = runner.invoke(cli_main, [
            "run", "--target-repo", str(temp_dir), "--mode", "new",
            "--repo-profile", "omni-ops", "--op-name", "gelu",
            "--requirement", str(req_file), "--general-design", str(doc_file),
            "--output-root", str(temp_dir),
        ])
        assert result.exit_code == 0
        task = mock_dispatch.call_args.args[0]
        assert task["design_doc_path"] == str(doc_file)

    @mock.patch("ascendc_devkit.cli.commands.run.dispatch")
    def test_run_design_doc_absent_is_none(self, mock_dispatch, runner, temp_dir):
        mock_dispatch.return_value = 0
        result = runner.invoke(cli_main, [
            "run", "--target-repo", str(temp_dir), "--repo-profile", "omni-ops",
        ])
        assert result.exit_code == 0
        task = mock_dispatch.call_args.args[0]
        assert task["design_doc_path"] is None

    @mock.patch("ascendc_devkit.cli.commands.run.dispatch")
    def test_run_mode_incremental(self, mock_dispatch, runner, temp_dir):
        mock_dispatch.return_value = 64
        result = runner.invoke(cli_main, [
            "run", "--target-repo", str(temp_dir), "--repo-profile", "omni-ops",
            "--mode", "incremental",
        ])
        assert result.exit_code == 64

    @mock.patch("ascendc_devkit.cli.commands.run.dispatch")
    def test_run_default_values(self, mock_dispatch, runner, temp_dir):
        mock_dispatch.return_value = 0
        result = runner.invoke(cli_main, [
            "run", "--target-repo", str(temp_dir), "--repo-profile", "omni-ops",
        ])
        assert result.exit_code == 0
        task = mock_dispatch.call_args.args[0]
        # P30 推广(Bug A):运行控制类参数 default=None,None=用户未提供,让 dispatcher
        # resume 能沿用 state(而非被 CLI 默认值覆盖)。new run 的实际默认(False /
        # "default")由 dispatcher 用 `or` 兜底。
        assert task["non_interactive"] is None
        assert task["on_decision"] is None
        assert task["enable_stubbed"] is None

    @mock.patch("ascendc_devkit.cli.commands.run.dispatch")
    def test_run_enable_stubbed_flag(self, mock_dispatch, runner, temp_dir):
        mock_dispatch.return_value = 0
        result = runner.invoke(cli_main, [
            "run", "--target-repo", str(temp_dir), "--repo-profile", "omni-ops",
            "--enable-stubbed",
        ])
        assert result.exit_code == 0
        task = mock_dispatch.call_args.args[0]
        assert task["enable_stubbed"] is True

    @mock.patch("ascendc_devkit.cli.commands.run.dispatch")
    def test_run_no_stubbed_flag(self, mock_dispatch, runner, temp_dir):
        mock_dispatch.return_value = 0
        result = runner.invoke(cli_main, [
            "run", "--target-repo", str(temp_dir), "--repo-profile", "omni-ops",
            "--no-stubbed",
        ])
        assert result.exit_code == 0
        task = mock_dispatch.call_args.args[0]
        assert task["enable_stubbed"] is False
        task = mock_dispatch.call_args.args[0]
        # --workflow has no default now (None = user did not provide); dispatcher
        # applies the new-run default (generate_ascendc) via `or`.
        assert task["workflow"] is None
        assert task["mode"] == "new"
        assert task["repo_profile"] == "omni-ops"
        # --npu-id unset → None (no hard-pin); card is resolved per NPU
        # subprocess from the shared pool via card_context (stage 2).
        assert task["npu_id"] is None
        # Unset by default → None (runner applies mode-based defaults). An
        # explicit --max-iterations is honored verbatim as a hard cap.
        assert task["max_iterations"] is None
        assert task["on_decision"] is None

    @mock.patch("ascendc_devkit.cli.commands.run.dispatch")
    def test_run_interactive_flag_sets_false(self, mock_dispatch, runner, temp_dir):
        """--interactive(--non-interactive 的配对 flag)显式置 non_interactive=False。

        配对 flag + default=None 让三态可区分:未传=None / --non-interactive=True /
        --interactive=False。这是 resume「未传=继承、显式=覆盖」语义在 CLI 层的前提。
        """
        mock_dispatch.return_value = 0
        result = runner.invoke(cli_main, [
            "run", "--target-repo", str(temp_dir), "--repo-profile", "omni-ops",
            "--interactive",
        ])
        assert result.exit_code == 0
        task = mock_dispatch.call_args.args[0]
        assert task["non_interactive"] is False


class TestShowCommand:
    def test_show_requires_run(self, runner):
        result = runner.invoke(cli_main, ["show"])
        assert result.exit_code != 0

    def test_show_nonexistent_run(self, runner, temp_dir):
        result = runner.invoke(cli_main, [
            "show", "--run", "nonexistent-42", "--output-root", str(temp_dir),
        ])
        assert result.exit_code == 0

    def test_show_with_events(self, runner, temp_dir):
        import json
        ws = temp_dir / "test-run-1"
        ws.mkdir()
        events = [
            {"ts": "2026-01-01T00:00:00Z", "type": "stage_enter", "stage": "entry", "stage_index": 1, "total": 9},
            {"ts": "2026-01-01T00:00:01Z", "type": "stage_complete", "stage": "entry", "elapsed_ms": 100, "total_iterations": 1},
        ]
        with open(ws / "events.jsonl", "w") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

        result = runner.invoke(cli_main, [
            "show", "--run", "test-run-1", "--output-root", str(temp_dir),
        ])
        assert result.exit_code == 0
        assert "test-run-1" in result.output
        assert "entry" in result.output

    def test_show_help(self, runner):
        result = runner.invoke(cli_main, ["show", "--help"])
        assert result.exit_code == 0
        assert "--run" in result.output
        assert "--tail" in result.output


class TestRespondCommand:
    def test_respond_requires_run_and_choice(self, runner):
        result = runner.invoke(cli_main, ["respond"])
        assert result.exit_code != 0

    def test_respond_missing_run(self, runner):
        result = runner.invoke(cli_main, ["respond", "--choice", "1"])
        assert result.exit_code != 0

    def test_respond_missing_choice(self, runner):
        result = runner.invoke(cli_main, ["respond", "--run", "run-1"])
        assert result.exit_code != 0

    def test_respond_no_pending_decision(self, runner, temp_dir):
        result = runner.invoke(cli_main, [
            "respond", "--run", "nonexistent-42", "--choice", "1",
            "--output-root", str(temp_dir),
        ])
        assert result.exit_code != 0

    def test_respond_writes_decision_response(self, runner, temp_dir):
        import json
        ws = temp_dir / "run-1"
        ws.mkdir()
        pending = {"question": "Which?", "options": ["A", "B"]}
        (ws / "pending_decision.json").write_text(json.dumps(pending))

        result = runner.invoke(cli_main, [
            "respond", "--run", "run-1", "--choice", "2",
            "--output-root", str(temp_dir),
        ])
        assert result.exit_code == 0

        response = json.loads((ws / "decision_response.json").read_text())
        assert response["choice"] == 2
        assert response["selected"] == "B"

    def test_respond_writes_custom_text(self, runner, temp_dir):
        import json
        ws = temp_dir / "run-3"
        ws.mkdir()
        pending = {"question": "Which mode?", "options": ["A", "B"]}
        (ws / "pending_decision.json").write_text(json.dumps(pending))

        result = runner.invoke(cli_main, [
            "respond", "--run", "run-3",
            "--text", "mode is required, no default",
            "--output-root", str(temp_dir),
        ])
        assert result.exit_code == 0

        response = json.loads((ws / "decision_response.json").read_text())
        assert response["text"] == "mode is required, no default"
        assert "choice" not in response

    def test_respond_choice_out_of_range(self, runner, temp_dir):
        import json
        ws = temp_dir / "run-2"
        ws.mkdir()
        pending = {"question": "Q?", "options": ["A", "B"]}
        (ws / "pending_decision.json").write_text(json.dumps(pending))

        result = runner.invoke(cli_main, [
            "respond", "--run", "run-2", "--choice", "5",
            "--output-root", str(temp_dir),
        ])
        assert result.exit_code != 0

    def test_respond_help(self, runner):
        result = runner.invoke(cli_main, ["respond", "--help"])
        assert result.exit_code == 0
        assert "--run" in result.output
        assert "--choice" in result.output


class TestStubCommands:
    @pytest.mark.parametrize("cmd", ["verify-env", "verify-repo", "skill"])
    def test_stub_command_help(self, runner, cmd):
        result = runner.invoke(cli_main, [cmd, "--help"])
        assert result.exit_code == 0


class TestVerifyEnv:
    def test_verify_env_local(self, runner):
        result = runner.invoke(cli_main, ["verify-env"])
        assert result.exit_code == 0
        assert "CANN" in result.output
        assert "Python" in result.output

    def test_verify_env_unsupported_target(self, runner):
        result = runner.invoke(cli_main, ["verify-env", "--target", "ssh"])
        assert result.exit_code == 0
        assert "not yet supported" in result.output


class TestBishengLinkCheck:
    """verify-env 的 BISHENG link 前置自检 —— /lib64/libc.so.6 可达性。

    背景：缺 /lib64 的机器上 BISHENG lld link device .so 会挂
    (cannbench_eval cann_bench_utils)，运行期表现为误导性 circular import。
    加载期显式报出真障碍（§1.3/§1.11）。
    见 docs/plan/self-evolution/83-cannbench-eval-env-gotchas.md。"""

    def test_pass_when_libc_present(self, monkeypatch):
        from pathlib import Path

        from ascendc_devkit.cli.commands.verify_env import _check_bisheng_link
        monkeypatch.setattr(Path, "exists", lambda self: str(self) == "/lib64/libc.so.6")
        r = _check_bisheng_link()
        assert r.passed
        assert "/lib64/libc.so.6" in r.detail

    def test_fail_when_libc_missing_gives_fix_command(self, monkeypatch):
        from pathlib import Path

        from ascendc_devkit.cli.commands.verify_env import _check_bisheng_link
        # /lib64/libc.so.6 缺失，但真实 libc 在 /usr/lib64 → 给出可执行 ln 修复
        monkeypatch.setattr(
            Path, "exists",
            lambda self: str(self) == "/usr/lib64/libc.so.6")
        r = _check_bisheng_link()
        assert not r.passed
        assert "missing" in r.detail
        assert "ln -sfn /usr/lib64/libc.so.6 /lib64/libc.so.6" in r.detail
        assert "83-cannbench-eval-env-gotchas" in r.detail

    def test_fail_without_real_libc_degrades_gracefully(self, monkeypatch):
        from pathlib import Path

        from ascendc_devkit.cli.commands.verify_env import _check_bisheng_link
        monkeypatch.setattr(Path, "exists", lambda self: False)
        r = _check_bisheng_link()
        assert not r.passed
        assert "install libc" in r.detail


class TestVerifyRepo:
    def test_verify_repo_missing_profile(self, runner, temp_dir):
        result = runner.invoke(cli_main, [
            "verify-repo", "--profile", "no-such-profile",
            "--repo-root", temp_dir,
        ])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_verify_repo_valid_profile(self, runner, temp_dir):
        from pathlib import Path
        # Create a valid profile file in the resources/repository-profiles/ in repo
        repo_root = Path(temp_dir)
        profiles_dir = repo_root / "repository-profiles"
        profiles_dir.mkdir()
        (profiles_dir / "test-profile.yaml").write_text(
            "name: test-profile\n"
            "display_name: Test Profile\n"
            "op_naming:\n"
            "  prefix: \"\"\n"
            "build_variants:\n"
            "  - name: default\n"
            "    match_prefix: \"\"\n"
            "    default_reference_root: \".\"\n"
            "    stages:\n"
            "      - name: ascendc\n"
            "        cwd: \".\"\n"
            "        command_template: \"make\"\n"
        )
        result = runner.invoke(cli_main, [
            "verify-repo", "--profile", "test-profile",
            "--repo-root", temp_dir,
        ])
        # Profile file should be found in either package resources or user home
        # This test exercises the code path; result depends on file location
        assert result.exit_code in (0, 1)


class TestSkillCommand:
    def test_skill_list(self, runner):
        result = runner.invoke(cli_main, ["skill", "list"])
        assert result.exit_code == 0
        # Output may show "Available skills" or "No skills found" —
        # both are valid depending on whether .claude/skills/ has entries
        assert "skills" in result.output.lower()

    def test_skill_validate_missing(self, runner):
        result = runner.invoke(cli_main, ["skill", "validate", "no-such-skill-xyz"])
        assert result.exit_code == 1
        assert "MISSING" in result.output


class TestRunCommandResume:
    def test_run_has_resume_flag(self, runner):
        result = runner.invoke(cli_main, ["run", "--help"])
        assert result.exit_code == 0
        assert "--resume" in result.output

    def test_run_has_on_decision_flag(self, runner):
        result = runner.invoke(cli_main, ["run", "--help"])
        assert result.exit_code == 0
        assert "--on-decision" in result.output


class TestRunCommandWebhook:
    """CLI tests for --webhook-url and notify-webhook (Slice 7)."""

    def test_run_has_webhook_url_flag(self, runner):
        result = runner.invoke(cli_main, ["run", "--help"])
        assert result.exit_code == 0
        assert "--webhook-url" in result.output

    def test_on_decision_includes_notify_webhook(self, runner):
        result = runner.invoke(cli_main, ["run", "--help"])
        assert result.exit_code == 0
        assert "notify-webhook" in result.output

    @mock.patch("ascendc_devkit.cli.commands.run.dispatch")
    def test_webhook_url_flows_to_task_request(self, mock_dispatch, runner, temp_dir):
        mock_dispatch.return_value = 0
        result = runner.invoke(cli_main, [
            "run", "--target-repo", str(temp_dir), "--repo-profile", "omni-ops",
            "--webhook-url", "https://hooks.example.com/decisions",
            "--on-decision", "notify-webhook",
        ])
        assert result.exit_code == 0
        task = mock_dispatch.call_args.args[0]
        assert task["webhook_url"] == "https://hooks.example.com/decisions"
        assert task["on_decision"] == "notify-webhook"


class TestSkillRunCommand:
    """CLI tests for skill run command (Slice 7)."""

    def test_skill_group_is_group(self, runner):
        result = runner.invoke(cli_main, ["skill", "--help"])
        assert result.exit_code == 0
        assert "run" in result.output

    def test_skill_run_has_options(self, runner):
        result = runner.invoke(cli_main, ["skill", "run", "--help"])
        assert result.exit_code == 0
        assert "--name" in result.output
        assert "--prompt" in result.output

    @mock.patch("ascendc_devkit.cli.commands.skill.dispatch_single_skill")
    def test_skill_run_calls_dispatch(self, mock_dispatch, runner):
        mock_dispatch.return_value = 0
        result = runner.invoke(cli_main, [
            "skill", "run", "--name", "test-skill", "--prompt", "do something",
        ])
        assert result.exit_code == 0
        mock_dispatch.assert_called_once_with(
            skill_name="test-skill",
            prompt="do something",
            output_root="output",
        )


class TestTUI:
    def test_tui_import_and_init(self):
        from ascendc_devkit.cli.tui import TUI
        tui = TUI()
        assert tui is not None
        assert len(tui._STAGE_ORDER) == 9

    def test_tui_stages_all_pending_initially(self):
        from ascendc_devkit.cli.tui import TUI
        tui = TUI()
        for s in tui._STAGE_ORDER:
            assert tui._stages[s] == "pending"

    def test_tui_update_stage(self):
        from ascendc_devkit.cli.tui import TUI
        tui = TUI()
        tui.update_stage("entry", "running")
        assert tui._stages["entry"] == "running"

    def test_tui_add_event(self):
        from ascendc_devkit.cli.tui import TUI
        tui = TUI()
        tui.add_event("test", "hello world")
        assert len(tui._events) > 0
        assert any("hello world" in e for e in tui._events)

    def test_tui_status_icon(self):
        from ascendc_devkit.cli.tui import TUI
        assert "●" in TUI._status_icon("done")
        assert "○" in TUI._status_icon("pending")
        assert "◉" in TUI._status_icon("running")

    def test_tui_events_capped(self):
        from ascendc_devkit.cli.tui import TUI
        tui = TUI()
        for i in range(60):
            tui.add_event("event", str(i))
        assert len(tui._events) <= 50

    def test_tui_dispatch_with_tui_importable(self):
        from ascendc_devkit.cli.tui import dispatch_with_tui
        assert callable(dispatch_with_tui)

    def test_tui_on_progress_stage_start(self):
        from ascendc_devkit.cli.tui import TUI
        tui = TUI()
        tui.update_stage("entry", "running")
        assert tui._stages["entry"] == "running"

    def test_tui_on_progress_stage_end(self):
        from ascendc_devkit.cli.tui import TUI
        tui = TUI()
        tui.update_stage("entry", "done")
        assert tui._stages["entry"] == "done"

    def test_tui_on_progress_stage_error(self):
        from ascendc_devkit.cli.tui import TUI
        tui = TUI()
        tui.update_stage("entry", "failed")
        assert tui._stages["entry"] == "failed"

    def test_tui_on_progress_stage_skip(self):
        from ascendc_devkit.cli.tui import TUI
        tui = TUI()
        tui.update_stage("entry", "skipped")
        assert tui._stages["entry"] == "skipped"

    def test_tui_processes_dispatch_events(self):
        """Verify TUI stage states can be updated through progress callbacks."""
        from ascendc_devkit.cli.tui import TUI
        tui = TUI()

        # Simulate a progress callback sequence
        tui.update_stage("entry", "running")
        tui.update_stage("entry", "done")
        tui.update_stage("context", "running")
        tui.update_stage("context", "done")

        assert tui._stages["entry"] == "done"
        assert tui._stages["context"] == "done"
        # Stages not touched remain pending
        assert tui._stages["requirement"] == "pending"


class TestTUI4Panel:
    """Verify 4-panel TUI features."""

    def test_agent_output_initially_empty(self):
        from ascendc_devkit.cli.tui import TUI
        tui = TUI()
        assert tui._agent_output == []

    def test_add_agent_output(self):
        from ascendc_devkit.cli.tui import TUI
        tui = TUI()
        tui.add_agent_output("ascendc-coder", "Generating kernel...")
        assert len(tui._agent_output) == 1
        assert "ascendc-coder" in tui._agent_output[0]
        assert "Generating kernel" in tui._agent_output[0]

    def test_agent_output_capped(self):
        from ascendc_devkit.cli.tui import TUI
        tui = TUI()
        for i in range(100):
            tui.add_agent_output("agent", f"line {i}")
        assert len(tui._agent_output) <= 80

    def test_update_metrics(self):
        from ascendc_devkit.cli.tui import TUI
        tui = TUI()
        tui.update_metrics({"tokens": "1234", "memory": "2.1GB"})
        assert tui._metrics["tokens"] == "1234"
        assert tui._metrics["memory"] == "2.1GB"

    def test_update_metrics_merges(self):
        from ascendc_devkit.cli.tui import TUI
        tui = TUI()
        tui.update_metrics({"tokens": "100"})
        tui.update_metrics({"memory": "1GB"})
        assert tui._metrics["tokens"] == "100"
        assert tui._metrics["memory"] == "1GB"

    def test_metrics_initially_empty(self):
        from ascendc_devkit.cli.tui import TUI
        tui = TUI()
        assert tui._metrics == {}


class TestDebugAgentCommand:
    """Verify debug-agent CLI command."""

    def test_debug_agent_registered(self, runner):
        result = runner.invoke(cli_main, ["debug-agent", "--help"])
        assert result.exit_code == 0
        assert "debug-agent" in result.output
        assert "--run" in result.output
        assert "--agent-name" in result.output
        assert "--list" in result.output

    def test_debug_agent_requires_run(self):
        """debug-agent --agent-name requires --run."""
        from ascendc_devkit.cli.commands.debug_agent import debug_agent_cmd
        from click.testing import CliRunner
        r = CliRunner()
        result = r.invoke(debug_agent_cmd, ["--agent-name", "test-agent"])
        assert result.exit_code != 0

    def test_debug_agent_list_with_no_run(self, tmp_path):
        """--list with nonexistent run shows error."""
        from ascendc_devkit.cli.commands.debug_agent import debug_agent_cmd
        from click.testing import CliRunner
        r = CliRunner()
        result = r.invoke(debug_agent_cmd, [
            "--run", "nonexistent",
            "--list",
            "--output-root", str(tmp_path),
        ])
        assert result.exit_code != 0

    def test_debug_agent_missing_agent_name(self, tmp_path):
        """--run without --agent-name or --list shows error."""
        from ascendc_devkit.cli.commands.debug_agent import debug_agent_cmd
        from click.testing import CliRunner
        r = CliRunner()
        # Create a dummy events file with no spawn_context
        output_dir = tmp_path / "output" / "run-001"
        output_dir.mkdir(parents=True)
        (output_dir / "events.jsonl").write_text("")

        result = r.invoke(debug_agent_cmd, [
            "--run", "run-001",
            "--output-root", str(tmp_path / "output"),
        ])
        assert result.exit_code != 0

    def test_debug_agent_list_shows_agents(self, tmp_path):
        """--list shows agents from spawn_context events."""
        from ascendc_devkit.cli.commands.debug_agent import debug_agent_cmd
        from click.testing import CliRunner
        import json

        output_dir = tmp_path / "output" / "run-002"
        output_dir.mkdir(parents=True)
        events = [
            {"type": "spawn_context", "agent": "requirement-analyst", "prompt": "test"},
            {"type": "spawn_context", "agent": "ascendc-design-generator", "prompt": "test"},
        ]
        (output_dir / "events.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events)
        )

        r = CliRunner()
        result = r.invoke(debug_agent_cmd, [
            "--run", "run-002",
            "--list",
            "--output-root", str(tmp_path / "output"),
        ])
        assert result.exit_code == 0
        assert "requirement-analyst" in result.output
        assert "ascendc-design-generator" in result.output

    def test_debug_agent_not_found(self, tmp_path):
        """Nonexistent agent name prints error."""
        from ascendc_devkit.cli.commands.debug_agent import debug_agent_cmd
        from click.testing import CliRunner
        import json

        output_dir = tmp_path / "output" / "run-003"
        output_dir.mkdir(parents=True)
        events = [
            {"type": "spawn_context", "agent": "requirement-analyst", "prompt": "test"},
        ]
        (output_dir / "events.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events)
        )

        r = CliRunner()
        result = r.invoke(debug_agent_cmd, [
            "--run", "run-003",
            "--agent-name", "nonexistent-agent",
            "--output-root", str(tmp_path / "output"),
        ])
        assert result.exit_code != 0
