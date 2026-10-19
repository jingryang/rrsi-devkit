"""UT for scripts/trace_export (one-click trajectory export).

Deterministic no-LLM guard on the export chain: id resolution by location
(mirrors application/resume_resolver.py's three states) → canonical record
reconstruction from a synthetic opencode.db → 2.0 SFT JSONL conversion with
teacher derived from each session's own logged model id.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent.parent.parent
_SCRIPTS = _REPO / "scripts" / "trace_export"
sys.path.insert(0, str(_SCRIPTS))

import convert_to_sft  # noqa: E402
import export_trace  # noqa: E402


# ---------------------------------------------------------------------------
# synthetic run fixtures — minimal opencode schema (session/message/part)
# ---------------------------------------------------------------------------

def make_run(run_dir: Path, sessions: list[dict]) -> Path:
    """One DevKit run dir: state snapshot + .opencode_home db + config.

    Each ``sessions`` entry: {sid, agent, model_id, reasoning (optional),
    time}. Every session gets one user text message and one assistant answer
    (text + optional reasoning part).
    """
    home = run_dir / ".opencode_home"
    db_dir = home / "data" / "opencode"
    db_dir.mkdir(parents=True, exist_ok=True)
    run_dir.joinpath("state_snapshot.json").write_text("{}", encoding="utf-8")
    home.joinpath("opencode-config.json").write_text(
        json.dumps({"permission": {"skill": {"*": "allow"}}}), encoding="utf-8")

    con = sqlite3.connect(db_dir / "opencode.db")
    con.executescript("""
        CREATE TABLE session (id TEXT PRIMARY KEY, title TEXT, directory TEXT,
                              agent TEXT, model TEXT, time_created INTEGER);
        CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT,
                              time_created INTEGER, data TEXT);
        CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT,
                           time_created INTEGER, data TEXT);
    """)
    for i, s in enumerate(sessions):
        sid = s["sid"]
        con.execute(
            "INSERT INTO session VALUES (?,?,?,?,?,?)",
            (sid, s.get("title", sid), str(run_dir), s.get("agent", "tester"),
             json.dumps({"id": s["model_id"], "providerID": "p", "variant": "default"}),
             s.get("time", 1_000 + i)))
        parts = []
        for role, texts in (("user", [{"type": "text", "text": f"task {sid}"}]),
                            ("assistant",
                             ([{"type": "reasoning", "text": s["reasoning"]}]
                              if s.get("reasoning") else [])
                             + [{"type": "text", "text": f"done {sid}"}])):
            mid = f"msg_{sid}_{role}"
            con.execute("INSERT INTO message VALUES (?,?,?,?)",
                        (mid, sid, s.get("time", 1_000 + i) * 10,
                         json.dumps({"role": role})))
            for j, p in enumerate(texts):
                parts.append((f"{mid}_p{j}", mid, 0, json.dumps(p)))
        con.executemany("INSERT INTO part VALUES (?,?,?,?)", parts)
    con.commit()
    con.close()
    return run_dir


@pytest.fixture()
def runs_root(tmp_path: Path) -> Path:
    root = tmp_path / "output"
    root.mkdir()
    return root


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------------------
# id resolution (three location states)
# ---------------------------------------------------------------------------

class TestResolveRuns:
    def test_flat_single_run(self, runs_root):
        make_run(runs_root / "run_a", [])
        assert export_trace.resolve_runs("run_a", runs_root) == [runs_root / "run_a"]

    def test_batch_lists_only_run_subdirs(self, runs_root):
        batch = runs_root / "batch_b"
        make_run(batch / "exec_1", [])
        make_run(batch / "exec_2", [])
        (batch / "cann_bench").mkdir()          # non-run subdir alongside
        runs = export_trace.resolve_runs("batch_b", runs_root)
        assert runs == [batch / "exec_1", batch / "exec_2"]

    def test_nested_execution_unique(self, runs_root):
        make_run(runs_root / "batch_b" / "exec_9", [])
        assert export_trace.resolve_runs("exec_9", runs_root) == [
            runs_root / "batch_b" / "exec_9"]

    def test_nested_execution_ambiguous_raises(self, runs_root):
        make_run(runs_root / "b1" / "dup", [])
        make_run(runs_root / "b2" / "dup", [])
        with pytest.raises(export_trace.TraceExportError, match="multiple nested"):
            export_trace.resolve_runs("dup", runs_root)

    def test_unknown_id_raises(self, runs_root):
        with pytest.raises(export_trace.TraceExportError, match="not found"):
            export_trace.resolve_runs("nope", runs_root)


# ---------------------------------------------------------------------------
# single-run end-to-end export
# ---------------------------------------------------------------------------

def _two_session_run(run_dir: Path) -> Path:
    return make_run(run_dir, [
        {"sid": "ses_slow", "agent": "ascendc-coder", "model_id": "glm-4.7",
         "reasoning": "thinking hard", "time": 100},
        {"sid": "ses_fast", "agent": "requirement-analyst", "model_id": "glm-air",
         "time": 200},
    ])


class TestExportRun:
    def test_end_to_end_outputs_and_teacher_from_log(self, tmp_path):
        run = _two_session_run(tmp_path / "run_a")
        out = tmp_path / "out" / "run_a"

        entry = export_trace.export_run(run, out)

        assert entry["native_sessions"] == 2
        assert entry["operator"] == "unknown_op"   # no artifacts → honest label
        canonical = sorted((out / "canonical").glob("*.json"))
        assert [p.name.split("_", 1)[1] for p in canonical] == ["ses_slow.json", "ses_fast.json"]

        slow = read_jsonl(out / "slow_thinking.jsonl")
        fast = read_jsonl(out / "fast_thinking.jsonl")
        assert len(slow) == 1 and len(fast) == 1
        # teacher defaults to each record's OWN logged model id
        assert slow[0]["meta_info"]["teacher"] == "glm-4.7"
        assert slow[0]["meta_info"]["unique_info"] == {"session_id": "ses_slow"}
        assert fast[0]["meta_info"]["teacher"] == "glm-air"
        # SFT structure: first message is system, last is assistant
        for rec in (*slow, *fast):
            assert rec["messages"][0]["role"] == "system"
            assert rec["messages"][-1]["role"] == "assistant"
        # slow/fast classification follows the logged reasoning part
        assert any(m.get("reasoning_content") for m in slow[0]["messages"]
                   if m["role"] == "assistant")
        assert not any(m.get("reasoning_content") for m in fast[0]["messages"]
                       if m["role"] == "assistant")

    def test_teacher_flag_overrides_log(self, tmp_path, capsys):
        run = _two_session_run(tmp_path / "run_a")
        out = tmp_path / "out"
        export_trace.export_run(run, out, meta={"teacher": "teacher-x"})
        lines = read_jsonl(out / "slow_thinking.jsonl") + read_jsonl(out / "fast_thinking.jsonl")
        assert all(r["meta_info"]["teacher"] == "teacher-x" for r in lines)

    def test_no_db_raises_skip_condition(self, tmp_path):
        run = tmp_path / "run_a"
        run.mkdir()
        (run / "state_snapshot.json").write_text("{}", encoding="utf-8")
        with pytest.raises(export_trace.TraceExportError, match="no opencode.db"):
            export_trace.export_run(run, tmp_path / "out")

    def test_final_code_exported(self, tmp_path):
        run = _two_session_run(tmp_path / "run_a")
        kernel = run / "artifacts" / "codegen" / "op_kernel"
        kernel.mkdir(parents=True)
        (kernel / "foo_kernel.cpp").write_text("// final code", encoding="utf-8")
        out = tmp_path / "out"

        entry = export_trace.export_run(run, out)

        # 有 op_kernel 文件无 manifest → 从 <op>_kernel.cpp 派生算子名
        assert entry["native_sessions"] == 2
        assert entry["operator"] == "foo"
        assert (out / "code" / "op_kernel" / "foo_kernel.cpp").read_text() == "// final code"

    def test_contract_metadata_excluded_from_code_export(self, tmp_path):
        """M1：契约元数据已路由 ``_contract/``（step-109）——manifest 命名解析读
        新位置；``_contract/`` 非代码语料，不进 code/ 导出。"""
        run = _two_session_run(tmp_path / "run_a")
        cg = run / "artifacts" / "codegen"
        (cg / "_contract").mkdir(parents=True)
        (cg / "_contract" / "codegen_manifest.json").write_text(
            json.dumps({"op_name": "MyOp"}), encoding="utf-8")
        kernel = cg / "op_kernel"
        kernel.mkdir(parents=True)
        (kernel / "my_op_kernel.cpp").write_text("// final code", encoding="utf-8")
        out = tmp_path / "out"

        entry = export_trace.export_run(run, out)

        assert entry["operator"] == "my_op"  # manifest（新路径）优先于 kernel 文件名
        assert (out / "code" / "op_kernel" / "my_op_kernel.cpp").is_file()
        assert not (out / "code" / "_contract").exists()

    def test_no_code_flag_skips_code_export(self, tmp_path):
        run = _two_session_run(tmp_path / "run_a")
        (run / "artifacts" / "codegen").mkdir(parents=True)
        out = tmp_path / "out"
        export_trace.export_run(run, out, include_code=False)
        assert not (out / "code").exists()

    def test_missing_code_tree_is_warn_not_fail(self, tmp_path, capsys):
        run = _two_session_run(tmp_path / "run_a")   # no artifacts/ at all
        out = tmp_path / "out"
        export_trace.export_run(run, out)
        assert not (out / "code").exists()
        assert "no final code" in capsys.readouterr().out

    def test_session_filter_narrows_native_sessions(self, tmp_path):
        run = _two_session_run(tmp_path / "run_a")
        records = export_trace.build_canonical_records(
            export_trace.find_db(run), None, needle="requirement-analyst")
        assert [r["session"]["id"] for r in records] == ["ses_fast"]

    def test_records_sorted_by_start_time(self, tmp_path):
        run = make_run(tmp_path / "run_a", [
            {"sid": "ses_late", "model_id": "m", "time": 900},
            {"sid": "ses_early", "model_id": "m", "time": 100},
        ])
        records = export_trace.build_canonical_records(export_trace.find_db(run), None)
        assert [r["session"]["id"] for r in records] == ["ses_early", "ses_late"]


# ---------------------------------------------------------------------------
# CLI orchestration (batch loop / skip / exit codes)
# ---------------------------------------------------------------------------

class TestMain:
    def test_batch_exports_each_run_skips_dbless(self, tmp_path):
        root, out = tmp_path / "output", tmp_path / "traces"
        batch = root / "batch_b"
        _two_session_run(batch / "exec_1")
        (batch / "exec_2").mkdir()
        (batch / "exec_2" / "state_snapshot.json").write_text("{}", encoding="utf-8")

        rc = export_trace.main(["batch_b", "--runs-root", str(root), "--out", str(out)])

        assert rc == 0
        assert (out / "unknown_op_exec_1" / "slow_thinking.jsonl").is_file()
        assert not (out / "unknown_op_exec_2" / "slow_thinking.jsonl").exists()
        idx = json.loads((out / "index.json").read_text())
        assert [e["run_id"] for e in idx] == ["exec_1"]
        assert idx[0]["operator"] == "unknown_op"
        assert idx[0]["source_run_dir"].endswith("batch_b/exec_1")

    def test_single_run_export(self, tmp_path):
        root, out = tmp_path / "output", tmp_path / "traces"
        _two_session_run(root / "run_flat")
        rc = export_trace.main(["run_flat", "--runs-root", str(root), "--out", str(out)])
        assert rc == 0
        assert (out / "unknown_op_run_flat" / "canonical").is_dir()

    def test_unknown_id_exit_2(self, tmp_path):
        rc = export_trace.main(["ghost", "--runs-root", str(tmp_path)])
        assert rc == 2

    def test_all_runs_without_db_exit_nonzero(self, tmp_path, capsys):
        root, out = tmp_path / "output", tmp_path / "traces"
        empty = root / "run_empty"
        empty.mkdir(parents=True)
        (empty / "state_snapshot.json").write_text("{}", encoding="utf-8")
        rc = export_trace.main(["run_empty", "--runs-root", str(root), "--out", str(out)])
        assert rc == 1
        assert "no opencode.db" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# convert_to_sft module-level contract
# ---------------------------------------------------------------------------

class TestConvertToSft:
    def test_derive_teacher_shapes(self):
        assert convert_to_sft.derive_teacher({"session": {"model": {"id": "glm-5"}}}) == "glm-5"
        assert convert_to_sft.derive_teacher({"session": {"model": "raw-id"}}) == "raw-id"
        assert convert_to_sft.derive_teacher({"session": {}}) == ""
        assert convert_to_sft.derive_teacher({}) == ""

    def test_export_jsonl_reports_issues_not_drops(self, tmp_path):
        # 未注册的 tool_call（tools 为空）且非末尾位置——归一化保留 tool 消息，
        # 工具注册检查应报 issue；report-only 不丢数据
        record = {
            "session": {"id": "ses_x", "model": {"id": "glm-5"}, "time_created": 1},
            "system": "sys",
            "tools": [],
            "messages": {"provider": [
                {"role": "assistant", "content": [{"type": "text", "text": "hi"}],
                 "tool_calls": [{"id": "c1", "type": "function",
                                 "function": {"name": "ghost_tool", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "c1", "name": "ghost_tool", "content": "ok"},
                {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
            ]},
        }
        slow, fast, issues = convert_to_sft.export_jsonl([record], tmp_path)
        assert (slow, fast) == (0, 1)  # no reasoning → fast bucket
        assert issues >= 1
        lines = read_jsonl(tmp_path / "fast_thinking.jsonl")
        assert len(lines) == 1  # report-only: data kept

    def test_consecutive_duplicate_user_collapsed(self):
        # backoff-resume 会在 db 里把同一条框架反馈 append 多次（模型只应答
        # 一次）——紧邻逐字节相同的 user 折叠为 1 条，SFT 反映模型真实所见
        record = {
            "session": {"id": "ses_dup", "model": {"id": "glm-5"}, "time_created": 1},
            "system": "sys",
            "tools": [],
            "messages": {"provider": [
                {"role": "user", "content": [{"type": "text", "text": "fix the smoke failure"}]},
                {"role": "user", "content": [{"type": "text", "text": "fix the smoke failure"}]},
                {"role": "user", "content": [{"type": "text", "text": "fix the smoke failure"}]},
                {"role": "assistant", "content": [{"type": "text", "text": "fixed"}],
                 "reasoning_content": "think"},
            ]},
        }
        rec = convert_to_sft.convert_record(record)
        users = [m for m in rec["messages"] if m["role"] == "user"]
        assert len(users) == 1
        assert users[0]["content"] == "fix the smoke failure"

    def test_repeated_user_after_reply_kept(self):
        # 非紧邻的重复 user（中间有应答）是真实的多轮反馈，保留
        record = {
            "session": {"id": "ses_rpt", "model": {"id": "glm-5"}, "time_created": 1},
            "system": "sys",
            "tools": [],
            "messages": {"provider": [
                {"role": "user", "content": [{"type": "text", "text": "go"}]},
                {"role": "assistant", "content": [{"type": "text", "text": "done"}],
                 "reasoning_content": "r"},
                {"role": "user", "content": [{"type": "text", "text": "go"}]},
                {"role": "assistant", "content": [{"type": "text", "text": "again"}]},
            ]},
        }
        rec = convert_to_sft.convert_record(record)
        users = [m for m in rec["messages"] if m["role"] == "user"]
        assert len(users) == 2

    def test_consecutive_distinct_user_kept(self):
        record = {
            "session": {"id": "ses_seq", "model": {"id": "glm-5"}, "time_created": 1},
            "system": "sys",
            "tools": [],
            "messages": {"provider": [
                {"role": "user", "content": [{"type": "text", "text": "first"}]},
                {"role": "user", "content": [{"type": "text", "text": "second"}]},
                {"role": "assistant", "content": [{"type": "text", "text": "ok"}],
                 "reasoning_content": "r"},
            ]},
        }
        rec = convert_to_sft.convert_record(record)
        users = [m for m in rec["messages"] if m["role"] == "user"]
        assert [u["content"] for u in users] == ["first", "second"]

    def test_check_record_flags_adjacent_duplicate_user(self):
        rec = {
            "meta_info": {"unique_info": {"session_id": "ses_bad"}},
            "tools": [],
            "messages": [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "go"},
                {"role": "user", "content": "go"},
                {"role": "assistant", "content": "ok", "reasoning_content": "r"},
            ],
        }
        issues = convert_to_sft.check_record(rec)
        assert any("未去重干净" in i for i in issues)

    def test_meta_owner_defaults_unknown_and_flags_override(self, tmp_path):
        run = _two_session_run(tmp_path / "run_a")
        records = export_trace.build_canonical_records(export_trace.find_db(run), None)
        out = tmp_path / "sft"

        convert_to_sft.export_jsonl(records, out)
        lines = read_jsonl(out / "slow_thinking.jsonl") + read_jsonl(out / "fast_thinking.jsonl")
        assert all(r["meta_info"]["owner"] == "unknown" for r in lines)
        assert all(r["meta_info"]["query_source"] == "operator" for r in lines)

        convert_to_sft.export_jsonl(records, tmp_path / "sft2", owner="zhangsan",
                                    query_source="synthesized", category="code")
        lines = read_jsonl(tmp_path / "sft2" / "slow_thinking.jsonl") \
            + read_jsonl(tmp_path / "sft2" / "fast_thinking.jsonl")
        assert all(r["meta_info"]["owner"] == "zhangsan" for r in lines)
        assert all(r["meta_info"]["query_source"] == "synthesized" for r in lines)

    def test_resolve_op_name_sources(self, tmp_path):
        run = tmp_path / "run_a"
        run.mkdir(parents=True)
        # ① codegen manifest op_name（CamelCase → snake；step-109 后位于 _contract/）
        cg = run / "artifacts" / "codegen"
        (cg / "_contract").mkdir(parents=True)
        (cg / "_contract" / "codegen_manifest.json").write_text(
            json.dumps({"op_name": "FakeQuantizePerTensorAffine"}))
        assert export_trace.resolve_op_name(run) == "fake_quantize_per_tensor_affine"
        # ② 无 manifest → kernel 文件名派生
        (cg / "_contract" / "codegen_manifest.json").unlink()
        (cg / "op_kernel").mkdir()
        (cg / "op_kernel" / "my_op_kernel.cpp").write_text("//")
        assert export_trace.resolve_op_name(run) == "my_op"
        # ③ 都没有 → unknown_op
        import shutil as _sh; _sh.rmtree(cg)
        assert export_trace.resolve_op_name(run) == "unknown_op"

    def test_index_upsert_idempotent_by_run_id(self, tmp_path):
        idx = tmp_path / "index.json"
        e1 = {"operator": "foo", "run_id": "r1", "source_run_dir": "/x/r1",
              "exported_at": "t", "export_dir": "foo_r1", "native_sessions": 1,
              "slow_thinking": 1, "fast_thinking": 0, "code_files": 0}
        e2 = dict(e1, native_sessions=9)
        export_trace.upsert_index(idx, e1)
        export_trace.upsert_index(idx, e2)          # same run_id → replaced
        entries = json.loads(idx.read_text())
        assert len(entries) == 1 and entries[0]["native_sessions"] == 9

    def test_standalone_cli_on_canonical_dir(self, tmp_path, capsys):
        run = _two_session_run(tmp_path / "run_a")
        canonical = tmp_path / "canonical"
        records = export_trace.build_canonical_records(export_trace.find_db(run), None)
        export_trace.write_canonical(records, canonical)
        rc = convert_to_sft.main(["--input-dir", str(canonical),
                                  "--output-dir", str(tmp_path / "sft")])
        assert rc == 0
        assert (tmp_path / "sft" / "slow_thinking.jsonl").is_file()
