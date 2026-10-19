"""Unit tests for L7 Infrastructure."""

import json
import threading
import tempfile
from pathlib import Path

from ascendc_devkit.infra.workspace import Workspace
from ascendc_devkit.infra.event_log import EventLog
from ascendc_devkit.infra.filesystem import FileSystem
from ascendc_devkit.infra.logger import Logger
from ascendc_devkit.infra.terminal import Terminal


class TestWorkspace:
    def test_create_creates_full_directory_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace.create(output_root=tmp)
            assert ws.dir.exists()
            assert (ws.dir / "artifacts").is_dir()
            assert (ws.dir / "agents").is_dir()
            assert (ws.dir / "subprocess").is_dir()
            assert ws.events_path.parent == ws.dir
            assert ws.state_snapshot_path.parent == ws.dir
            assert ws.run_id

    def test_create_with_custom_run_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace.create(output_root=tmp, run_id="my-run")
            assert ws.run_id == "my-run"

    def test_from_existing_raises_for_missing_dir(self):
        try:
            Workspace.from_existing("nonexistent-run", output_root="/tmp/nonexistent-root")
            assert False, "Should have raised"
        except FileNotFoundError:
            pass

    def test_from_existing_finds_existing_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws1 = Workspace.create(output_root=tmp, run_id="r1")
            ws2 = Workspace.from_existing("r1", output_root=tmp)
            assert ws2.dir == ws1.dir

    def test_mark_dirty_and_is_dirty(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace.create(output_root=tmp)
            assert not ws.is_dirty()
            ws.mark_dirty()
            assert ws.is_dirty()

    def test_cleanup_removes_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace.create(output_root=tmp)
            assert ws.dir.exists()
            ws.cleanup()
            assert not ws.dir.exists()

    def test_properties_return_correct_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace.create(output_root=tmp, run_id="test")
            assert ws.artifacts.name == "artifacts"
            assert ws.agents_log.name == "agents"
            assert ws.subprocess_log.name == "subprocess"
            assert ws.events_path.name == "events.jsonl"
            assert ws.state_snapshot_path.name == "state_snapshot.json"
            assert ws.report_path.name == "report.md"
            assert ws.report_json_path.name == "report.json"

    def test_transcript_path_layout_and_seq(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace.create(output_root=tmp, run_id="test")
            p1 = ws.transcript_path("ascendc-coder", 1)
            p2 = ws.transcript_path("ascendc-coder", 12)
            assert p1.parent == ws.agents_log
            assert p1.name == "ascendc-coder-01.jsonl"
            assert p2.name == "ascendc-coder-12.jsonl"
            # agents/ is ensured to exist even on workspaces missing it.
            assert ws.agents_log.is_dir()

    def test_remove_skills_anchors_removes_symlinks_across_stage_cwds(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace.create(output_root=tmp, run_id="test")
            real_skills = Path(tmp) / "repo" / ".claude" / "skills"
            real_skills.mkdir(parents=True)
            (real_skills / "some-skill").mkdir()

            stage_cwds = [
                ws.artifacts / "design" / "template-division",
                ws.artifacts / "design" / "anchor" / "T1",
                ws.artifacts / "requirement",
            ]
            for cwd in stage_cwds:
                anchor_dir = cwd / ".claude"
                anchor_dir.mkdir(parents=True)
                (anchor_dir / "skills").symlink_to(real_skills, target_is_directory=True)

            for cwd in stage_cwds:
                assert (cwd / ".claude" / "skills").is_symlink()

            removed = ws.remove_skills_anchors()

            assert removed == len(stage_cwds)
            for cwd in stage_cwds:
                assert not (cwd / ".claude" / "skills").exists()
                assert not (cwd / ".claude" / "skills").is_symlink()
            # The anchor target itself (repo tree) is untouched.
            assert (real_skills / "some-skill").is_dir()

    def test_remove_skills_anchors_leaves_real_directory_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace.create(output_root=tmp, run_id="test")
            real_dir = ws.artifacts / "design" / ".claude" / "skills"
            real_dir.mkdir(parents=True)
            (real_dir / "marker.txt").write_text("not a symlink")

            removed = ws.remove_skills_anchors()

            assert removed == 0
            assert (real_dir / "marker.txt").exists()

    def test_remove_skills_anchors_no_anchors_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace.create(output_root=tmp, run_id="test")
            assert ws.remove_skills_anchors() == 0

    def test_remove_skills_anchors_missing_run_dir_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace.create(output_root=tmp, run_id="test")
            ws.cleanup()
            assert ws.remove_skills_anchors() == 0


class TestEventLog:
    def test_append_and_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            log = EventLog(path)
            log.append({"type": "stage_enter", "stage": "smoke"})
            log.append({"type": "stage_complete", "stage": "smoke"})
            events = EventLog.read(path)
            assert len(events) == 2
            assert events[0]["type"] == "stage_enter"
            assert events[1]["type"] == "stage_complete"

    def test_read_nonexistent_file(self):
        events = EventLog.read(Path("/tmp/nonexistent-events.jsonl"))
        assert events == []

    def test_replay_yields_events_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            log = EventLog(path)
            log.append({"type": "e1"})
            log.append({"type": "e2"})
            log.append({"type": "e3"})
            replayed = list(EventLog.replay(path))
            assert len(replayed) == 3
            assert [e["type"] for e in replayed] == ["e1", "e2", "e3"]

    def test_replay_nonexistent_file(self):
            replayed = list(EventLog.replay(Path("/tmp/nonexistent-events.jsonl")))
            assert replayed == []

    def test_concurrent_append_no_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            log = EventLog(path)
            n_per_thread = 100
            errors = []

            def writer(prefix):
                try:
                    for i in range(n_per_thread):
                        log.append({"type": prefix, "idx": i})
                except Exception as e:
                    errors.append(e)

            t1 = threading.Thread(target=writer, args=("a",))
            t2 = threading.Thread(target=writer, args=("b",))
            t1.start()
            t2.start()
            t1.join()
            t2.join()

            assert not errors, f"Errors during concurrent write: {errors}"
            events = EventLog.read(path)
            assert len(events) == n_per_thread * 2


class TestFileSystem:
    def test_atomic_write_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "file.txt"
            FileSystem.atomic_write(path, "hello world")
            assert path.read_text() == "hello world"

    def test_atomic_write_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "file.txt"
            path.write_text("old")
            FileSystem.atomic_write(path, "new")
            assert path.read_text() == "new"

    def test_ensure_dir_creates_parents(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a" / "b" / "c"
            FileSystem.ensure_dir(path)
            assert path.is_dir()

    def test_temp_dir_cleanup(self):
        tmp_path = None
        with FileSystem.temp_dir(prefix="test-") as p:
            tmp_path = p
            assert p.is_dir()
            (p / "dummy.txt").write_text("test")
        assert not tmp_path.exists()

    def test_sync_dir_copies_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            dst = Path(tmp) / "dst"
            src.mkdir()
            (src / "a.txt").write_text("aaa")
            (src / "sub").mkdir()
            (src / "sub" / "b.txt").write_text("bbb")
            FileSystem.sync_dir(src, dst)
            assert (dst / "a.txt").read_text() == "aaa"
            assert (dst / "sub" / "b.txt").read_text() == "bbb"


class TestTerminal:
    def test_is_tty_returns_bool(self):
        assert isinstance(Terminal.is_tty(), bool)

    def test_stdin_is_tty_returns_bool(self):
        assert isinstance(Terminal.stdin_is_tty(), bool)

    def test_stdin_is_tty_false_when_stdin_none(self):
        from unittest import mock
        with mock.patch("ascendc_devkit.infra.terminal.sys") as msys:
            msys.stdin = None
            assert Terminal.stdin_is_tty() is False

    def test_stdin_is_tty_false_when_isatty_raises(self):
        """A closed/detached stdin raises ValueError on isatty() — treat as non-TTY."""
        from unittest import mock
        fake_stdin = mock.Mock()
        fake_stdin.isatty.side_effect = ValueError("I/O operation on closed file")
        with mock.patch("ascendc_devkit.infra.terminal.sys") as msys:
            msys.stdin = fake_stdin
            assert Terminal.stdin_is_tty() is False

    def test_width_returns_positive_int(self):
        assert Terminal.width() > 0

    def test_supports_color_returns_bool(self):
        assert isinstance(Terminal.supports_color(), bool)

    def test_supports_unicode_returns_bool(self):
        assert isinstance(Terminal.supports_unicode(), bool)
