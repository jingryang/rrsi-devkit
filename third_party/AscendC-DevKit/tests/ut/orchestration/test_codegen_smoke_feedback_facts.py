"""step-94 — smoke 失败反馈：通道不变式 + 进度打点 + 客观事实块。

实证源：99c4c0 批 gelu（smoke 15s 静默死亡：stdout 空、stderr 仅 allocator
warning、rc 值被 `_run_smoke` 丢弃——反馈「首条错误行」退化为字面量
`=== stdout ===`；coder 逆向重建复现环境 65min）。本套件守护：

- 死亡方式（rc/信号）到达消费者：`_rc_label` 形态、smoke.log `=== rc ===` 头、
  ErrorFeedback.details 结构化字段；
- 调用现场到达消费者：smoke_script.py 落盘、env 四键 smoke_context、
  build 失败路径同样带 rc（单点收口）；
- 已产生输出到达消费者：harness 模板 start/invoking 打点（start 先于输入
  生成、invoking 紧邻 op 调用）、`_smoke_last_marker` 从日志提取最后打点；
- 反馈渲染事实第一性：客观事实块（rc/打点/复现现场/前次产物指针），
  invoking 段给判界实证法（非猜测）；
- stop-loss 签名含 rc+最后打点（段位推进=有进展，重置 streak）。
"""

import json
import re
from types import SimpleNamespace
from unittest.mock import patch

from ascendc_devkit.orchestration.stages.codegen import CodegenStage
from ascendc_devkit.orchestration.stages.deploy import Deployer, _rc_label


class TestRcLabel:
    def test_signal_death(self):
        assert _rc_label(-11) == "signal 11 (SIGSEGV)"

    def test_positive_exit(self):
        assert _rc_label(1) == "exit 1"

    def test_zero_and_none_are_empty(self):
        assert _rc_label(0) == "" and _rc_label(None) == ""


class TestPersistRcHeader:
    def test_rc_header_written(self, tmp_path):
        ws = SimpleNamespace(subprocess_log=tmp_path / "subprocess")
        p = Deployer._persist_subprocess_output(
            ws, "smoke", "", "", "boom", rc_label="signal 11 (SIGSEGV)")
        content = (tmp_path / "subprocess" / "smoke.log").read_text(encoding="utf-8")
        assert p is not None
        assert content.index("=== rc === signal 11 (SIGSEGV)") < content.index("=== stdout ===")

    def test_no_rc_header_when_label_empty(self, tmp_path):
        ws = SimpleNamespace(subprocess_log=tmp_path / "subprocess")
        Deployer._persist_subprocess_output(ws, "smoke", "", "out", "err")
        assert "=== rc ===" not in (tmp_path / "subprocess" / "smoke.log").read_text()


class TestSmokeMarkersInTemplate:
    """进度打点是判界的事实基础——start 先于一切用例处理、invoking 紧邻 op 调用。"""

    def test_start_marker_precedes_input_generation(self):
        from ascendc_devkit.adapters.npu._harness_template import HARNESS_TEMPLATE
        src = HARNESS_TEMPLATE.template
        start = src.index("[harness] case %s start")
        # start 打点先于首个输入生成调用（gen_input 定义之外的首个用例内调用点）
        first_gen = src.index("gen_input(_shp")
        assert start < first_gen

    def test_invoking_precedes_both_run_kernel_sites(self):
        from ascendc_devkit.adapters.npu._harness_template import HARNESS_TEMPLATE
        src = HARNESS_TEMPLATE.template
        # 两条路径（CANN/FALLBACK）各一处 invoking，均紧邻 _run_kernel 调用
        pairs = list(zip(
            (m.start() for m in re.finditer(r"\[harness\] case %s invoking", src)),
            (m.start() for m in re.finditer(r"_run_kernel\(", src))))
        # _run_kernel 出现 3 处（定义 1 + 调用 2），invoking 2 处均须先于其后的调用
        invoking_positions = [m.start() for m in re.finditer(r"\[harness\] case %s invoking", src)]
        assert len(invoking_positions) == 2
        for inv in invoking_positions:
            nxt = src.index("_run_kernel(", inv)
            assert inv < nxt
        assert pairs  # 静态存在性锚

    def test_existing_kernel_done_markers_kept(self):
        from ascendc_devkit.adapters.npu._harness_template import HARNESS_TEMPLATE
        assert "kernel_done" in HARNESS_TEMPLATE.template
        assert "golden_done" in HARNESS_TEMPLATE.template


class TestSmokeLastMarker:
    def _details_with_log(self, tmp_path, content):
        log = tmp_path / "smoke.log"
        log.write_text(content, encoding="utf-8")
        return {"log": str(log)}

    def test_last_marker_wins(self, tmp_path):
        d = self._details_with_log(tmp_path,
            "=== rc === signal 11 (SIGSEGV)\n=== stdout ===\n"
            "[harness] case 1 start\n[harness] case 1 invoking\n"
            "[harness] case 1 kernel_done 1.2ms\n"
            "[harness] case 2 start\n[harness] case 2 invoking\n=== stderr ===\n")
        assert CodegenStage._smoke_last_marker(d) == "case 2 invoking"

    def test_zero_markers_returns_empty(self, tmp_path):
        d = self._details_with_log(tmp_path, "=== stdout ===\n\n=== stderr ===\nwarn\n")
        assert CodegenStage._smoke_last_marker(d) == ""

    def test_missing_log_returns_empty(self):
        assert CodegenStage._smoke_last_marker({}) == ""
        assert CodegenStage._smoke_last_marker({"log": "/nonexistent/x.log"}) == ""

    def test_non_marker_harness_lines_ignored(self, tmp_path):
        d = self._details_with_log(tmp_path,
            "[harness] cann_bench.__file__ = /x\n[harness] bind: {'x': (2,)}\n")
        assert CodegenStage._smoke_last_marker(d) == ""


class TestSmokeSignatureIncludesFacts:
    def _err(self, rc_label, log_path):
        return SimpleNamespace(details={"rc_label": rc_label, "log": log_path})

    def test_marker_advance_changes_signature(self, tmp_path):
        """判界/修复使打点推进 = 有进展 → 签名变 → streak 重置（99c4c0 教训）。"""
        def log(marker):
            p = tmp_path / f"m_{marker.replace(' ', '_')}.log"
            p.write_text(f"=== stdout ===\n[harness] case 1 {marker}\n=== stderr ===\n",
                         encoding="utf-8")
            return str(p)
        s1 = CodegenStage._smoke_error_signature(self._err("signal 11 (SIGSEGV)", log("start")))
        s2 = CodegenStage._smoke_error_signature(self._err("signal 11 (SIGSEGV)", log("invoking")))
        assert s1 != s2
        assert "SIGSEGV" in s1 and "nomarker" not in s1

    def test_rc_change_changes_signature(self, tmp_path):
        p = tmp_path / "same.log"
        p.write_text("=== stdout ===\n[harness] case 1 invoking\n=== stderr ===\n",
                     encoding="utf-8")
        a = CodegenStage._smoke_error_signature(self._err("signal 11 (SIGSEGV)", str(p)))
        b = CodegenStage._smoke_error_signature(self._err("exit 1", str(p)))
        assert a != b


class TestSmokeFacts:
    def test_facts_gather_all_channels(self, tmp_path):
        log = tmp_path / "smoke.log"
        log.write_text("=== rc === signal 11 (SIGSEGV)\n=== stdout ===\n"
                       "[harness] case 2 invoking\n=== stderr ===\n", encoding="utf-8")
        dl_dir = tmp_path / "op"
        dl_dir.mkdir()
        (dl_dir / "decision_log.json").write_text(json.dumps({
            "known_issues": [{"title": "crash post-launch"}],
            "scalar_access_points": [{"location": "k.h:1"}],
        }), encoding="utf-8")
        stage = CodegenStage()
        state = SimpleNamespace(op_dir=str(dl_dir), op_identity=None)
        details = {
            "log": str(log), "rc_label": "signal 11 (SIGSEGV)",
            "smoke_context": {
                "rc_label": "signal 11 (SIGSEGV)",
                "script_path": "/x/subprocess/smoke_script.py",
                "env_summary": {"PYTHONPATH": "/p", "ASCEND_NPU_ID": "3",
                                "ASCEND_CUSTOM_OPP_PATH": "/o",
                                "LD_LIBRARY_PATH": "/l"},
            },
        }
        facts = stage._smoke_facts(state, details)
        assert facts["rc_label"] == "signal 11 (SIGSEGV)"
        assert facts["last_marker"] == "case 2 invoking"
        assert facts["script_path"].endswith("smoke_script.py")
        assert facts["env_summary"]["ASCEND_NPU_ID"] == "3"
        assert facts["prev_decision_log"]["known_issues"] == 1
        assert facts["prev_decision_log"]["scalar_access_points"] == 1

    def test_facts_degrade_silently_when_missing(self, tmp_path):
        stage = CodegenStage()
        state = SimpleNamespace(op_dir=str(tmp_path / "nope"), op_identity=None)
        facts = stage._smoke_facts(state, {"log": ""})
        assert facts == {"rc_label": "", "last_marker": "", "script_path": "",
                         "env_summary": {}}


class TestRenderSmokeFactsLines:
    def test_full_facts_block_and_invoking_boundary_method(self):
        fb = {"facts": {
            "rc_label": "signal 11 (SIGSEGV)",
            "last_marker": "case 2 invoking",
            "script_path": "/x/smoke_script.py",
            "env_summary": {"PYTHONPATH": "/p", "ASCEND_CUSTOM_OPP_PATH": "/o",
                            "ASCEND_NPU_ID": "0", "LD_LIBRARY_PATH": "/l"},
            "prev_decision_log": {"path": "/op/decision_log.json",
                                  "known_issues": 1, "scalar_access_points": 0,
                                  "known_issue_titles": ["crash post-launch"]},
        }}
        text = "\n".join(CodegenStage._render_smoke_facts_lines(fb))
        assert "signal 11 (SIGSEGV)" in text
        assert "case 2 invoking" in text
        assert "python -u /x/smoke_script.py" in text
        assert "勿自建副本" in text          # §2.5 双通路收敛
        assert "known_issues=1" in text
        assert "判界方法" in text and "launch 前后" in text  # 实证方法非猜测
        assert "verdict" in text

    def test_zero_progress_states_cpu_side_fact(self):
        fb = {"facts": {"rc_label": "signal 11 (SIGSEGV)", "last_marker": ""}}
        text = "\n".join(CodegenStage._render_smoke_facts_lines(fb))
        assert "首个用例未开始" in text
        assert "判界方法" not in text   # 非 invoking 段不给判界指令

    def test_empty_facts_renders_nothing(self):
        assert CodegenStage._render_smoke_facts_lines({}) == []
        assert CodegenStage._render_smoke_facts_lines({"facts": {}}) == []


class TestRunSmokeChannels:
    """_run_smoke 失败路径：script 落盘 + -u + rc/现场进 details 通道。"""

    def _state(self, tmp_path):
        sub = tmp_path / "subprocess"
        return SimpleNamespace(
            npu_id=None, _workspace=SimpleNamespace(subprocess_log=sub))

    def _run(self, tmp_path, fake_ret):
        import ascendc_devkit.orchestration.stages.deploy as dep
        stage = Deployer()
        captured = {}
        def fake_run(argv, **kw):
            captured["argv"] = argv
            return fake_ret
        with patch.object(stage, "_callable_target", return_value={
                "kind": "torch_op", "symbol": "torch.ops.cann_bench.gelu"}), \
             patch.object(stage, "_build_smoke_harness", return_value="print('hi')"), \
             patch.object(dep.subprocess, "run", side_effect=fake_run), \
             patch.object(Deployer, "_cann_lib_paths", return_value=[]):
            ok, err, log_path, ctx = stage._run_smoke(
                self._state(tmp_path), "gelu", "/opp", "/py", "/ld")
        return ok, err, log_path, ctx, captured

    def test_silent_signal_death_carries_full_context(self, tmp_path):
        ok, err, log_path, ctx, _ = self._run(
            tmp_path, SimpleNamespace(returncode=-11, stdout="",
                                      stderr="[W] alloc warning"))

        assert ok is False
        assert ctx["rc_label"] == "signal 11 (SIGSEGV)"
        # script 落盘且内容一致（复现现场）
        script = tmp_path / "subprocess" / "smoke_script.py"
        assert script.exists() and script.read_text() == "print('hi')"
        assert ctx["script_path"] == str(script)
        # env 四键（框架构造的确定性子集）
        assert set(ctx["env_summary"]) == {
            "PYTHONPATH", "ASCEND_CUSTOM_OPP_PATH",
            "LD_LIBRARY_PATH", "ASCEND_RT_VISIBLE_DEVICES", "ASCEND_NPU_ID"}
        # 日志含 rc 头（通道不变式：观测到达消费者）
        content = (tmp_path / "subprocess" / "smoke.log").read_text(encoding="utf-8")
        assert content.startswith("=== rc === signal 11 (SIGSEGV)")

    def test_subprocess_argv_has_dash_u(self, tmp_path):
        ok, _, _, ctx, captured = self._run(
            tmp_path, SimpleNamespace(returncode=0,
                                      stdout='{"case_details": [{}]}', stderr=""))
        assert ok is True
        assert captured["argv"][1] == "-u"
        assert ctx["rc_label"] == ""   # 成功路径 rc 空


class TestBuildFailureAlsoCarriesRc:
    """单点收口：build role 失败同样带 rc（编译器段错误今天同样不可诊断）。"""

    def test_run_command_failure_persists_rc(self, tmp_path):
        from ascendc_devkit.domain.repository import BuildStage
        stage = BuildStage(name="x", role="build", command_template="false")
        ws = SimpleNamespace(subprocess_log=tmp_path / "sub")
        ok, err, log_path = Deployer()._run_command(stage, tmp_path, {}, ws=ws)
        assert ok is False
        assert log_path and "=== rc ===" in open(log_path, encoding="utf-8").read()


class TestErrExtraMerge:
    def test_extra_keys_merge_into_details(self):
        ef = Deployer._err("smoke", "boom", "/x/log",
                           extra={"rc_label": "exit 1",
                                  "smoke_context": {"rc_label": "exit 1"}})
        assert ef.details["step"] == "smoke"
        assert ef.details["rc_label"] == "exit 1"
        assert ef.details["smoke_context"]["rc_label"] == "exit 1"

    def test_no_extra_keeps_base_shape(self):
        ef = Deployer._err("smoke", "boom")
        assert set(ef.details) == {"step", "log", "stderr_tail"}


class TestCollectorsCarryFacts:
    """反馈收集器必须携带 facts（通道末端：details → fb → 渲染）。"""

    def _err(self, rc_label, log_path):
        return SimpleNamespace(details={
            "step": "smoke", "log": log_path, "stderr_tail": "warn",
            "rc_label": rc_label,
            "smoke_context": {"rc_label": rc_label, "script_path": "/s.py",
                              "env_summary": {"PYTHONPATH": "/p"}},
        })

    def test_owner_judge_feedback_includes_facts(self, tmp_path):
        log = tmp_path / "smoke.log"
        log.write_text("=== rc === exit 1\n=== stdout ===\n"
                       "[harness] case 1 invoking\n=== stderr ===\n", encoding="utf-8")
        fb = CodegenStage()._collect_smoke_owner_judge_feedback(
            SimpleNamespace(op_dir=None, op_identity=None),
            self._err("exit 1", str(log)), 0)
        assert fb["facts"]["rc_label"] == "exit 1"
        assert fb["facts"]["last_marker"] == "case 1 invoking"

    def test_host_feedback_includes_facts(self):
        fb = CodegenStage()._collect_smoke_host_feedback(
            SimpleNamespace(op_dir=None, op_identity=None),
            self._err("signal 6 (SIGABRT)", ""), 2)
        assert fb["facts"]["rc_label"] == "signal 6 (SIGABRT)"


class TestPromptRendersFactsEndToEnd:
    """transition 级：facts → _build_codegen_prompt 的 owner-judge 段。"""

    def test_owner_judge_prompt_contains_facts_block(self):
        from ascendc_devkit.orchestration.kernel.state import State
        stage = CodegenStage()
        state = State(
            mode="new",
            codegen_build_feedback={
                "kind": "smoke_owner_judge", "reason": "ambiguous_phase",
                "error_line": "", "log_path": "/x/smoke.log",
                "stderr_tail": "", "retry_count": 1,
                "facts": {
                    "rc_label": "signal 11 (SIGSEGV)",
                    "last_marker": "case 2 invoking",
                    "script_path": "/x/subprocess/smoke_script.py",
                    "env_summary": {"PYTHONPATH": "/p", "ASCEND_NPU_ID": "0",
                                    "ASCEND_CUSTOM_OPP_PATH": "/o",
                                    "LD_LIBRARY_PATH": "/l"},
                    "prev_decision_log": {"path": "/op/decision_log.json",
                                          "known_issues": 0,
                                          "scalar_access_points": 0},
                },
            },
        )
        prompt = stage._build_codegen_prompt(state, 2)
        assert "进程死亡方式: **signal 11 (SIGSEGV)**" in prompt
        assert "case 2 invoking" in prompt
        assert "python -u /x/subprocess/smoke_script.py" in prompt
        assert "判界方法" in prompt

    def test_first_error_line_skips_structural_headers(self, tmp_path):
        log = tmp_path / "smoke.log"
        log.write_text("=== rc === signal 11 (SIGSEGV)\n=== stdout ===\n"
                       "[harness] case 1 start\n=== stderr ===\n"
                       "RuntimeError: boom\n", encoding="utf-8")
        line = CodegenStage._first_smoke_error_line({"log": str(log)})
        assert line == "RuntimeError: boom"

    def test_first_error_line_no_error_falls_to_first_content(self, tmp_path):
        log = tmp_path / "smoke.log"
        log.write_text("=== rc === exit 1\n=== stdout ===\n"
                       "[harness] case 1 invoking\n=== stderr ===\n"
                       "[W] alloc warning\n", encoding="utf-8")
        line = CodegenStage._first_smoke_error_line({"log": str(log)})
        assert line == "[harness] case 1 invoking"   # 不再退化为 === 头字面量
