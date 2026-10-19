"""L5 Capabilities — Stub backend for testing (no real LLM calls)."""

import json
import time
from pathlib import Path

from .backend import AgentBackend, AgentResult


class StubBackend(AgentBackend):
    """Testing stub that returns canned responses."""

    def __init__(self, canned_responses: list[AgentResult] | None = None):
        self._responses = canned_responses or []
        self._idx = 0
        self.spawn_calls: list[dict] = []

    def spawn(self, agent_name: str, prompt: str, context: dict,
              skills: list[str] | None = None,
              model: str | None = None,
              working_dir: Path | str | None = None,
              repo_baseline: str | None = None,
              repo_root: Path | str | None = None,
              stage_name: str = "",
              branch_label: str = "",
              resume_session_id: str | None = None,
              resume_prompt: str | None = None,
              primary_skill: str | None = None,
              deadline_monotonic: float | None = None) -> AgentResult:
        self.spawn_calls.append({
            "agent_name": agent_name,
            "prompt": prompt,
            "context": context,
            "skills": skills,
            "primary_skill": primary_skill,
            "working_dir": working_dir,
            "repo_baseline": repo_baseline,
            "repo_root": repo_root,
            "stage_name": stage_name,
            "branch_label": branch_label,
            "resume_session_id": resume_session_id,
            "resume_prompt": resume_prompt,
            "deadline_monotonic": deadline_monotonic,
        })
        # D3 硬墙：deadline 到点 → 立即返回 aborted，不返回 canned、不落产物（构造性
        # 保证：硬终止不留半个产物）。真实 backend（claude B'/opencode）同语义。
        if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
            return AgentResult(agent_name=agent_name, status="fatal",
                               aborted="hard_timeout")
        if self._idx < len(self._responses):
            result = self._responses[self._idx]
            self._idx += 1
        else:
            result = AgentResult(agent_name=agent_name, status="ok")
        # P62: model a real agent — its products land as FILES in working_dir
        # (the invariant design-stage transitions now enforce: location strict,
        # disk-only read). The canned ``artifacts`` dict represents what the
        # agent would have written; materialize it to disk so the disk-only read
        # pathway sees the products exactly as a real spawn's cwd would leave
        # them. Non-str values are JSON-encoded (artifacts is typed str, but be
        # tolerant of test fixtures that pass dicts/lists).
        if working_dir is not None and result.artifacts:
            wd = Path(working_dir)
            wd.mkdir(parents=True, exist_ok=True)
            for fn, content in result.artifacts.items():
                if not isinstance(content, str):
                    content = json.dumps(content)
                (wd / fn).write_text(content, encoding="utf-8")
        return result
