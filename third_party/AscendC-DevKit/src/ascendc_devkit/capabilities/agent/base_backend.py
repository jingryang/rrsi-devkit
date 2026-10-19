"""L5 Capabilities — SDK-agnostic base for agent backends.

``SDKBackend`` (claude_agent_sdk, in-process) and ``OpenCodeBackend``
(``opencode serve``, HTTP+SSE) differ only in HOW they drive the model and
produce the event stream. Everything *after* the stream — persisting a
transcript, flushing the resume sidecar, collecting the run's changed files,
salvaging partial output — is backend-neutral. This base owns that single
implementation so the two backends cannot drift (§2.5 single implementation
path / §1.6 dependency injection).

Module-level pure functions (serialization, error classification, changed-source
collection, the stall constants) live in ``_shared.py``; the *stateful*
instance methods that need ``_decision_workspace`` / ``_spawn_seq`` /
``_artifacts_ignore`` live here. Subclasses implement the abstract ``spawn``
(the SDK-specific event loop) and reuse these helpers verbatim.

This module MUST NOT import any concrete SDK — SDK coupling stays in the
respective backend module.
"""

from __future__ import annotations

import json
import time
from collections import deque
from pathlib import Path

from .backend import AgentBackend, AgentResult
from ._shared import (
    _classify_error_type,
    _collect_changed_sources,
    _TOOL_SIG_WINDOW,
    BOOTSTRAP_GRACE_TURNS,
    BOOTSTRAP_MAX_STALLED,
    NORMAL_MAX_STALLED_TURNS,
)
from ascendc_devkit.infra.logger import Logger


class BaseAgentBackend(AgentBackend):
    """Concrete SDK-agnostic helpers shared by every agent backend.

    Holds the run-directory handle (``_decision_workspace``), the per-stem
    transcript sequence counter (``_spawn_seq``), and the product-collection
    ignore globs (``_artifacts_ignore``). Subclasses call ``super().__init__``
    with these and then implement ``spawn``.
    """

    def __init__(self, *, decision_workspace: Path | str | None = None,
                 artifacts_ignore: list[str] | None = None):
        self._decision_workspace = (
            Path(decision_workspace) if decision_workspace else None)
        # Build-artifact globs excluded from git-diff product collection (R3).
        self._artifacts_ignore = list(artifacts_ignore or [])
        # Per-stem spawn counter for transcript file sequencing (Task 1.2).
        self._spawn_seq: dict[str, int] = {}

    # —— Transcript sink ——————————————————————————————————————————————————
    # Persist the message stream to <run>/agents/<agent>-<seq>.jsonl so `show`
    # can replay a session. Best-effort: a write failure never aborts a run.

    def _open_transcript(self, agent_name: str, branch_label: str = ""):
        """Open a per-spawn transcript file under <run>/agents/, or None.

        Derives the path from ``_decision_workspace`` (the run directory).
        Returns a writable file handle, or None when no workspace is configured
        or opening fails — transcript persistence is best-effort and never
        blocks a spawn (D1).

        ``branch_label`` (tiling template name) is folded into the file stem and
        the sequence key so N parallel branches of a reused role agent each get
        their own transcript (§P2 third gap), instead of colliding on one seq
        counter.
        """
        if not self._decision_workspace:
            return None
        try:
            stem = f"{agent_name}-{branch_label}" if branch_label else agent_name
            seq = self._spawn_seq.get(stem, 0) + 1
            self._spawn_seq[stem] = seq
            agents_dir = self._decision_workspace / "agents"
            agents_dir.mkdir(parents=True, exist_ok=True)
            path = agents_dir / f"{stem}-{seq:02d}.jsonl"
            return path.open("w", encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            Logger.warn(f"could not open transcript for {agent_name}: {e}")
            return None

    def _write_transcript_record(self, transcript, record: dict,
                                 agent_name: str = "") -> None:
        """Write one pre-serialized jsonl record to the transcript sink.

        Both backends produce the SAME on-disk record schema
        (``{ts, type, turn, blocks[, result]}``) but build it from their own
        native event objects (claude ``_serialize_event`` / opencode part
        mapping). This method owns only the write+flush so the two backends
        cannot diverge on the sink itself. Best-effort (D1/D2).
        """
        if transcript is None:
            return
        try:
            transcript.write(json.dumps(record, ensure_ascii=False) + "\n")
            transcript.flush()
        except Exception as e:  # noqa: BLE001 — best-effort logging
            Logger.warn(f"transcript write failed for {agent_name}: {e}")

    # —— Cross-run session resume sidecar ————————————————————————————————
    # The session_id is captured mid-spawn but lives only in memory until
    # written to disk. A hard kill (SIGKILL/OOM) would lose it, so a later
    # manual resume could not re-enter the interrupted session. The sidecar is
    # the durable handle: written the instant session_id is captured, deleted on
    # clean finish. Read by codegen.actions (via state._workspace) to resume.

    def _session_sidecar_path(self, agent_name: str, branch_label: str = "",
                              stage_name: str = ""):
        from ascendc_devkit.infra.workspace import session_sidecar_path
        return session_sidecar_path(self._decision_workspace, agent_name,
                                    branch_label, stage_name)

    def _write_session_sidecar(self, agent_name: str, branch_label: str,
                               session_id: str, stage_name: str = "",
                               resume_fails: int = 0) -> None:
        """Flush session_id to the sidecar at capture time. Best-effort: a write
        failure never blocks a spawn (resume is an optimization, not a
        correctness invariant). stage_name 并入 sidecar 键（review M2）：不同
        stage 复用同 agent 时键构造性分离，避免跨任务误 resume。
        resume_fails = 连续失败的 resume 次数（退化 spawn 阈值）：fresh 新
        session 写 0；resume 续写保留值；自然结束清 sidecar 一并清除。"""
        path = self._session_sidecar_path(agent_name, branch_label, stage_name)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "agent_name": agent_name,
                "session_id": session_id,
                "stage_name": stage_name,
                "resume_fails": int(resume_fails),
            }, ensure_ascii=False), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            Logger.warn(f"could not write session sidecar for {agent_name}: {e}")

    def _clear_session_sidecar(self, agent_name: str, branch_label: str,
                               stage_name: str = "") -> None:
        """Delete the sidecar on clean finish / resume-degrade / resume 退化 spawn —
        the session is no longer resumable (completed or confirmed gone).
        Best-effort."""
        path = self._session_sidecar_path(agent_name, branch_label, stage_name)
        if path is None:
            return
        try:
            path.unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001
            Logger.warn(f"could not clear session sidecar for {agent_name}: {e}")

    def _bump_session_resume_fails(self, agent_name: str, branch_label: str,
                                   stage_name: str = "") -> int:
        """无效 resume 计数 +1（read-modify-write，best-effort），返回 bump 后的
        连续计数（sidecar 缺失/写失败返回 0）。两类调用方：resume 会话被硬杀/
        turn_stall abort（调用失败）；resume 后仍 silent-cut（恢复无效，F4
        20260821）。读到该计数 >= resume_attempts 的下一次 spawn 会退化 fresh
        （docs/plan/turn-stall-resume-escalation/）。fresh 首跑不调本方法。"""
        path = self._session_sidecar_path(agent_name, branch_label, stage_name)
        if path is None or not path.exists():
            return 0
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["resume_fails"] = int(data.get("resume_fails", 0) or 0) + 1
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return int(data["resume_fails"])
        except Exception as e:  # noqa: BLE001
            Logger.warn(f"could not bump session resume_fails for {agent_name}: {e}")
            return 0

    # —— 硬切分类的 sidecar 读写（P6，两侧 backend 共享） ——————————————————
    # 分类键生命周期：判切点 `_set_sidecar_cut` 是唯一写 True/False 的地方
    # （soft cut 显式写 False，保证分类始终反映最近一次 cut）；resume 期
    # `_write_session_sidecar` 重写不含这两键 = 自然消费；自然结束清 sidecar。
    # bump 的 read-modify-write 保留既有键（与判切点写入正交）。

    def _set_sidecar_cut(self, agent_name: str, branch_label: str,
                         stage_name: str, cut_facts: dict | None,
                         cut_hard: bool) -> None:
        """判切点单点写入 cut 分类（read-modify-write，不动 resume_fails）。
        sidecar 不存在（无 resume 句柄可指）时跳过——分类无处路由，诚实放弃
        而非凭空造句柄。Best-effort。"""
        path = self._session_sidecar_path(agent_name, branch_label, stage_name)
        if path is None or not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["cut_hard"] = bool(cut_hard)
            if cut_facts:
                data["cut_facts"] = cut_facts
            else:
                data.pop("cut_facts", None)
            path.write_text(json.dumps(data, ensure_ascii=False),
                            encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            Logger.warn(f"could not write cut classification for {agent_name}: {e}")

    def _read_sidecar_cut_hard(self, agent_name: str, branch_label: str = "",
                               stage_name: str = "") -> bool:
        """resume 消息路由读取：上一次 cut 是否硬切分类（兜底提示仅此注入）。
        缺文件/缺键/损坏 → False（旧 sidecar 自然走裸「继续」原路径）。"""
        path = self._session_sidecar_path(agent_name, branch_label, stage_name)
        if path is None or not path.exists():
            return False
        try:
            return bool(json.loads(
                path.read_text(encoding="utf-8")).get("cut_hard"))
        except Exception:  # noqa: BLE001 — 分类是路由优化，不是正确性不变式
            return False

    # —— Product collection ————————————————————————————————————————————————

    @staticmethod
    def _count_files(cwd) -> int:
        """Count files under *cwd* recursively (no git needed).

        Used by the no-progress gate to track whether the agent produced new
        files this retry round. Decoupled from ``_collect`` (Plan-A product
        collection via git-diff) so design stages that write to an independent
        working_dir also get progress tracking.
        """
        if not cwd:
            return 0
        try:
            return sum(1 for _ in Path(cwd).rglob("*") if _.is_file())
        except Exception:
            return 0

    @staticmethod
    def _read_all_files(cwd) -> dict[str, str]:
        """Read every file under *cwd* into a {relpath: content} dict.

        Fallback for crash-salvage when no git baseline exists. Reads files from
        the agent's working_dir directly so partially-written work is still
        surfaced as a "partial" AgentResult. Skips the agents/ dir
        (infrastructure: transcripts, not agent-produced artifacts).
        """
        if not cwd:
            return {}
        result: dict[str, str] = {}
        try:
            cwd = Path(cwd)
            agents_dir = cwd / "agents"
            for f in cwd.rglob("*"):
                if not f.is_file():
                    continue
                # Transcript sink — not agent output
                if agents_dir in f.parents or f.parent == agents_dir:
                    continue
                try:
                    content = f.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    content = ""
                result[str(f.relative_to(cwd))] = content
        except Exception:
            pass
        return result

    def _collect(self, cwd, repo_baseline, repo_root) -> dict[str, str]:
        """Collect changed sources for an agent run (Plan-A product collection).

        Codegen path: builds a RepoGuard scoped with this backend's ignore
        globs, then delegates to ``_collect_changed_sources`` (self-report ∪ git
        diff). Requires a git baseline — raises when absent (design stages use
        the deterministic disk-read path in _parse_single, see P4).
        """
        if not cwd:
            return {}
        if not repo_baseline:
            # P4: codegen must have a baseline; design stages use the
            # deterministic disk-read path (_read_all_files via _collect_artifacts).
            raise ValueError("codegen requires a git baseline (repo_baseline)")
        guard = None
        try:
            from ascendc_devkit.infra.repo_guard import RepoGuard
            guard = RepoGuard(ignore_globs=self._artifacts_ignore)
        except Exception as e:
            Logger.warn(f"RepoGuard unavailable for collection: {e}")
        return _collect_changed_sources(
            Path(cwd), repo_guard=guard,
            baseline=repo_baseline,
            repo_root=Path(repo_root) if repo_root else None,
            has_baseline=True,
        )

    def _collect_artifacts(self, cwd, repo_baseline, repo_root) -> dict[str, str]:
        """Collect the run's products, degrading to a direct disk read when no
        git baseline exists.

        This is the single collection entry point both backends call (clean
        finish AND crash salvage): codegen passes a baseline → git-diff
        collection; design/test stages and baseline-less spawns fall back to
        reading working_dir directly so their artifacts still surface.
        """
        try:
            return self._collect(cwd, repo_baseline, repo_root)
        except ValueError:
            return self._read_all_files(cwd) if cwd else {}

    # —— Result factory (step-68) ————————————————————————————————————————
    # The single AgentResult constructor. Replaces the 8 scattered return sites
    # (sdk 3 + opencode 4 + early-fatal). Status state machine here; subclasses
    # pass (consumer, crashed, crash_reason, artifacts) and nothing else.

    def _build_result(self, agent_name: str, *, consumer: "IRConsumer | None",
                      crashed: bool, crash_reason: str | None,
                      artifacts: dict, transcript_path,
                      attempt: int, start_ms: int,
                      response_len: int | None = None,
                      error_type_override: str | None = None,
                      aborted: str | None = None,
                      final_response: str | None = None,
                      cut: bool = False,
                      cut_facts: dict | None = None,
                      cut_hard: bool = False,
                      extra_metrics: dict | None = None) -> AgentResult:
        """Single AgentResult factory. ``consumer`` supplies session_id /
        truncated_turns / full_response (None when no stream ran, e.g. early
        fatal). Status: crashed+artifacts→partial, crashed→fatal, else ok
        (artifacts={} when the run produced nothing — "空产出"不是一个语义
        类别，有无产物由消费方按业务判据查 artifacts 字典，F5）。Fixes
        opencode session_id 断链① (consumer carries it for both backends now)."""
        session_id = consumer.session_id if consumer else ""
        truncated = list(consumer.truncated_turns) if consumer else []
        response = (response_len if response_len is not None
                    else (len(consumer.full_response) if consumer else 0))
        if crashed and artifacts:
            status, base = "partial", artifacts
        elif crashed:
            status, base = "fatal", {}
        else:
            status, base = "ok", artifacts
        metrics: dict = {
            "elapsed_ms": int(time.time() * 1000) - start_ms,
            "response_len": response,
        }
        # Backend-specific additive metrics (step-113：opencode `compactions`).
        # Caller-owned keys must not collide with the fixed ones above — a
        # silent overwrite would corrupt elapsed_ms/response_len consumers
        # (R6：fail-fast，调用方 bug 属编程错误而非运行态)。
        if extra_metrics:
            _clash = set(extra_metrics) & set(metrics)
            if _clash:
                raise ValueError(
                    f"extra_metrics collides with fixed metric keys: "
                    f"{sorted(_clash)}")
            metrics.update(extra_metrics)
        # P6 硬切分类携带通道（runner 只读这两个固定键；缺键 = 无思考流证据，
        # runner 降级现文案）。仅在判切点有分类时传入。
        if cut_facts is not None:
            metrics["cut_facts"] = cut_facts
            metrics["cut_hard"] = bool(cut_hard)
        error_type = error_type_override
        if crashed:
            metrics["failure_reason"] = crash_reason or ""
            metrics["resume_attempts"] = max(0, attempt - 1)
            if error_type is None:
                error_type = _classify_error_type(crash_reason)
            # P125 (trial-20260730, §1.10): a watchdog kill (turn-stall / keepalive
            # / hard-cap) sets ``aborted`` but its crash_reason text carries NO
            # _INFRA_ERROR_MARKERS (e.g. "no new turn for 305s > turn_stall 300s"),
            # so _classify_error_type returns None → downstream attribution (which
            # only consults error_type=="infra") mislabels "被外部杀死" as "写错目录"
            # (missing_artifact). ``aborted`` non-empty IS the explicit business
            # signal "this turn was killed by cross-cutting control flow, not a
            # logic failure — un-retryable in place, resume re-runs"; that is
            # exactly infra semantics (short-circuit iteration + node_status failed
            # + resume). Translate it here rather than proxying on wording.
            if error_type is None and aborted:
                error_type = "infra"
            if error_type is None:
                # 兜底（fail-open）：crashed 但无 infra marker、无 aborted、也非连接异常
                # → 「未知 crash」。默认 fail-open 归为 infra_transient（瞬时、有界重试），
                # 不落回「中性失败 → fail_strategy 决定 halt」的旧夹缝（P1）。
                error_type = "infra_transient"
        return AgentResult(
            agent_name=agent_name, status=status, artifacts=base,
            transcript=transcript_path, metrics=metrics,
            error_type=error_type, session_id=session_id,
            truncated_turns=truncated, aborted=aborted, cut=cut,
            final_response=final_response if final_response is not None
            else (consumer.last_assistant_text if consumer else None))


# —— IR consumer (step-68) ——————————————————————————————————————————————
# Owns ALL per-event signal extraction + accounting that was previously inlined
# in each subclass's event loop. Subclasses map native→IR (AgentEvent record);
# this owns everything after. The on-disk transcript record IS the IR record
# (the subclass writes it via _write_transcript_record; the consumer only reads
# IR to extract signals — IO stays in the backend, semantics move here).


def _ir_tool_sig(block: dict) -> str:
    """IR block dict → tool-use signature (name + input). IR-dict counterpart of
    ``_shared._tool_use_signature`` (which takes a native SDK block)."""
    name = block.get("tool_name", "") or ""
    raw = block.get("tool_input")
    try:
        args = json.dumps(raw, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        args = str(raw)
    return f"{name}:{args}"


def classify_cut(thinking_chars: int, last_thinking_ts: float | None, *,
                 gap_threshold_s: float,
                 now: float | None = None) -> tuple[dict, bool] | None:
    """硬切分类（单点，两侧 backend 判切点调用——§2.5 同一分类一条通路）。

    判据：thinking 流在截断时刻仍活跃——末次 thinking 增量距结束 ≤ 阈值秒。
    gap 是物理事件测量而非模型参数：网关输出墙切流发生在「最后一个 token
    输出 → 立即断流」，gap≈0 与模型速度无关（批 49134b 实证 34/34 ≤0.58s、
    中位 0.12s）；gap 大 = 别的失败形态（停滞后断流/空闲超时），自然不命中。
    不用 thinking 体量阈值（模型不同/同名不同部署，阈值不可行）、不用 output
    配置比例（运维值不可靠）——零模型参数。

    Returns ``(cut_facts, hard)``；``None`` = 无思考流证据（判据不成立，走
    未知中断原路径）。``gap_threshold_s`` 由 backend 构造注入
    （retry_budgets.thinking_active_gap_s，网关 flush 粒度参数可调）。
    """
    if last_thinking_ts is None or thinking_chars <= 0:
        return None
    _now = time.time() if now is None else now
    gap_s = max(0.0, _now - last_thinking_ts)
    facts = {"thinking_chars": int(thinking_chars),
             "last_delta_to_end_s": round(gap_s, 2)}
    return facts, gap_s <= gap_threshold_s


class IRConsumer:
    """Consumes normalized IR records, owning per-event signal extraction +
    accounting (turn count / full_response / session_id / truncation / stall).
    Ported verbatim from sdk_backend :456-546 so stall semantics don't drift.
    Does NOT write transcript (the backend owns the IO sink); callers persist
    the IR record themselves and feed the same dict here."""

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.turn_count = 0
        self.full_response = ""
        self.last_result_text = ""
        # 最后一轮 assistant 回复的纯文本（text block，不含 thinking）。供
        # _build_result 灌入 AgentResult.final_response，stage 层解析 RETURN。
        self.last_assistant_text = ""
        self._cur_assistant_turn = -1
        self._cur_turn_text = ""
        self.session_id = ""
        self.truncated_turns: list[int] = []
        # stall accounting
        self.stalled_turns = 0
        self.recent_tool_sigs: deque[str] = deque(maxlen=_TOOL_SIG_WINDOW)
        self._this_turn_sigs: set[str] = set()
        self._errored_sigs: set[str] = set()
        # 20260810 批根因修复 Part 1 — silent-cut 检测：自然 agent 回合以 text
        # （总结）或 tool_use 结束；第三方网关静默切流（"一段吐字后突然中断"）在
        # 一个完整 thinking 块后截断，末条 assistant 消息只有 thinking、无 text 且
        # 无 tool_use。逐条 assistant 消息刷新，流结束时反映最后一条。默认 True
        # （无 assistant 消息的异常流不误判为 cut）。
        self._last_turn_actionable = True
        # 硬切分类证据（消费侧实时累计——sdk 侧 IR 记录即流内事件，到达时刻
        # 真实；opencode 侧以 SSE 增量流为准，此字段仅兜底呈现不进判据）。
        # thinking_chars = 末条 assistant 消息的 thinking 体量（逐消息覆写——
        # cut 判的是末条消息，体量语义同源）；last_thinking_ts = 末次 thinking
        # 块到达时刻（跨 reset 持续——与 full_response 同类持久事实）。
        self.thinking_chars = 0
        self.last_thinking_ts: float | None = None

    @staticmethod
    def _scan_tool_results(ir: dict) -> tuple[bool, bool]:
        """IR-dict counterpart of ``_shared._scan_tool_results``. Returns
        (all_errored, any_seen) over tool_result blocks in this record."""
        seen = False
        errored = True
        for b in ir.get("blocks", []) or []:
            if b.get("kind") == "tool_result":
                seen = True
                if not b.get("is_error"):
                    errored = False
        return (errored if seen else False), seen

    def consume(self, ir: dict) -> None:
        """Consume one IR record: extract signals + update stall accounting.
        Faithful port of sdk_backend :456-546 (scan→errored_sigs→assistant
        progress→stall), operating on IR dicts instead of native SDK objects.

        Owns the canonical ``turn`` stamp on the record: assistant messages
        increment FIRST (so turn N is the Nth assistant turn, matching
        sdk_backend which incremented at the top of the AssistantMessage branch
        before recording/truncation); other roles inherit the running turn as
        context. Overrides the preliminary value ``_serialize_event`` set from
        the pre-consume count."""
        role = ir.get("role", "")
        # Stamp canonical turn FIRST (consumer owns turn_count).
        if role == "assistant":
            self.turn_count += 1
        ir["turn"] = self.turn_count
        # tool_result scan (rides on user-role records) feeds next turn's
        # repeat-errored dampening (sdk :456-465).
        tr_errored, tr_seen = self._scan_tool_results(ir)
        if tr_seen and tr_errored:
            self._errored_sigs = set(self._this_turn_sigs)
        else:
            self._errored_sigs.clear()
        self._this_turn_sigs.clear()
        # session_id (first non-empty wins; base owns capture now)
        sid = ir.get("session_id")
        if sid and not self.session_id:
            self.session_id = sid
        # result text (ResultMessage.result)
        if ir.get("result"):
            self.last_result_text = str(ir["result"])[:500]
        # stop_reason → truncation (sdk :558-561); turn_count already reflects
        # this turn (incremented above for assistant messages).
        sr = ir.get("stop_reason")
        if sr and sr in ("max_tokens", "length", "max-output-tokens"):
            self.truncated_turns.append(self.turn_count if self.turn_count else 1)
        # assistant turn: accumulate text/tool sigs + progress + stall
        if role == "assistant":
            # 每轮独立的回复文本（用于 final_response）：turn 变化时重置缓冲区。
            if self.turn_count != self._cur_assistant_turn:
                self._cur_assistant_turn = self.turn_count
                self._cur_turn_text = ""
            prev_len = len(self.full_response)
            had_new_tool_use = False
            _had_text = False
            _had_tool = False
            _rec_thinking = 0
            for b in ir.get("blocks", []) or []:
                kind = b.get("kind")
                if kind in ("text", "thinking"):
                    text = b.get("text", "") or ""
                    self.full_response += text
                    # final_response 只保留可见 text（thinking 含噪声）
                    if kind == "text":
                        self._cur_turn_text += text
                        _had_text = True
                    else:
                        _rec_thinking += len(b.get("text", "") or "")
                        self.last_thinking_ts = time.time()
                elif kind == "tool_use":
                    _had_tool = True
                    sig = _ir_tool_sig(b)
                    if sig not in self.recent_tool_sigs:
                        had_new_tool_use = True
                    self.recent_tool_sigs.append(sig)
                    self._this_turn_sigs.add(sig)
            # 当前轮最终文本 = 本轮全部 text 块（同 turn 的多条 record 依次追加）
            self.last_assistant_text = self._cur_turn_text
            # 硬切分类证据：末条 assistant 消息的 thinking 体量（逐消息覆写）
            self.thinking_chars = _rec_thinking
            # silent-cut 检测信号：末条 assistant 消息是否有 text 或 tool_use。
            # 刷新到流结束即反映最后一条（cut 时 = False）。
            self._last_turn_actionable = _had_text or _had_tool
            made_progress = len(self.full_response) > prev_len or had_new_tool_use
            if made_progress:
                self.stalled_turns = 0
            else:
                self.stalled_turns += 1

    def reset_stall(self) -> None:
        """Reset per-attempt stall accounting. Called at the top of each query
        attempt (resume/retry) so consecutive-no-progress counting starts fresh
        for the new stream — matches sdk_backend's per-attempt reset of
        ``stalled_turns`` / ``recent_tool_sigs`` / ``_this_turn_sigs`` /
        ``_errored_sigs``. Persistent signals (turn_count, full_response,
        session_id, truncated_turns, last_result_text) are NOT reset: they
        accumulate across resume attempts exactly as the old locals did."""
        self.stalled_turns = 0
        self.recent_tool_sigs = deque(maxlen=_TOOL_SIG_WINDOW)
        self._this_turn_sigs = set()
        self._errored_sigs = set()
        # per-attempt 信号：resume 尝试从"未判定为 cut"开始，直到本流首条
        # assistant 消息刷新。避免上一轮 cut 的 False 残留误判本轮。
        self._last_turn_actionable = True

    def clear_session(self) -> None:
        """Clear the captured session_id. Called after a resume-degrade abandons
        a gone/expired session so the fresh spawn's new id is captured (consume
        only sets session_id while it is empty)."""
        self.session_id = ""

    @property
    def should_stop(self) -> bool:
        """Stall decision (sdk :534-537). The literal `break` stays in the
        subclass (can't break from a method); subclasses poll this."""
        if self.stalled_turns <= 0:
            return False
        limit = (BOOTSTRAP_MAX_STALLED if self.turn_count <= BOOTSTRAP_GRACE_TURNS
                 else NORMAL_MAX_STALLED_TURNS)
        return self.stalled_turns >= limit
