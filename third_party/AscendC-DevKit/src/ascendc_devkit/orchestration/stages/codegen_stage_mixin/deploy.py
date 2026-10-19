"""部署 mixin — CodegenStage 的部署职责承载（m1 God module 治理后归属本模块）。

承载部署产物读取（``_read_deploy_result``）与源码快照（``_persist_sources``）。
两端共享：反馈 retry（FeedbackMixin）与 transition（编排壳）都依赖 ``_persist_sources``，
经 ``self`` 跨 mixin 可达。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from ascendc_devkit.domain.verification import DeployResult

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State


class DeployMixin:
    """部署 mixin（职责见模块 docstring，经 MRO 合并回 CodegenStage）。"""

    def _read_deploy_result(self, state: State) -> DeployResult | None:
        """Read the agent's last redeploy handoff (last_deploy.json) written by
        ``ascendc-devkit redeploy`` during the in-session build loop (B4).

        Returns the ``DeployResult``, or ``None`` when there is no workspace or
        no usable handoff file (the build loop did not run / produced nothing) —
        the caller turns that into a deploy_failed halt (§1.2 可诊断: surface
        the missing-loop cause, not a silent contract gap).
        """
        ws = getattr(state, "_workspace", None)
        if ws is None:
            return None
        op_name = (state.op_name
                   or (state.op_identity.spec.name if state.op_identity else "op"))
        p = ws.dir / "artifacts" / "debug" / op_name / "last_deploy.json"
        if not p.exists():
            return None
        try:
            return DeployResult(**json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
    # =========================================================================
    # Artifact persistence
    # =========================================================================

    def _persist_sources(self, state: State, sources: dict[str, str]) -> None:
        """Snapshot generated sources into the run output dir for traceability.

        Plan-A generates in-repo, so a later `git checkout` rollback would erase
        the products. Mirroring them under artifacts/codegen/ (alongside the
        design/requirement artifacts) keeps every iteration's work reviewable and
        recoverable. Best-effort: a write failure never blocks the run.
        """
        ws = getattr(state, "_workspace", None)
        if ws is None or not sources:
            return
        try:
            dest = ws.artifacts / "codegen"
            dest.mkdir(parents=True, exist_ok=True)
            for rel, content in sources.items():
                # 纵深防御：剥离重复前导 codegen/ 段。cwd 若误落 artifacts（有 working_dir
                # 兜底失败等回归时应不可见，但防御），收集会重扫本镜像目录 artifacts/codegen/，
                # 给 key 带上 codegen/ 前缀；不归一化则 dest/codegen/... 写出 codegen/codegen/...
                # 嵌套，且每次 codegen 再跑累积一层（run 20260710-140056-ba16cd 的根因放大器）。
                # 归一化后伪源落回正确深度，反馈环断。startswith("codegen/") 带斜杠，不会误伤
                # 字面名为 codegen 的顶层文件。
                norm = rel
                while norm.startswith("codegen/"):
                    norm = norm[len("codegen/"):]
                if not norm:
                    continue
                # step-109：契约元数据路由独立子目录——源码平铺、元数据
                # （CONTRACT_FILES 单点名单，顶层精确匹配）进 _contract/，不再混放。
                from ascendc_devkit.domain.artifact import CONTRACT_FILES
                if norm in CONTRACT_FILES:
                    target = dest / "_contract" / norm
                else:
                    target = dest / norm
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content or "", encoding="utf-8")
        except Exception as e:  # noqa: BLE001 — traceability is best-effort
            from ascendc_devkit.infra.logger import Logger
            Logger.warn(f"failed to snapshot codegen sources: {e}")

