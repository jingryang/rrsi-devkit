"""L4 Domain — Stage artifact manifest.

Single source of truth for the files a Stage produces in the agent working
directory. Pairs with StageIOContract: where StageIOContract declares the
typed State fields a stage requires/provides, ArtifactSpec declares the
on-disk hand-off files an agent must write and how the orchestrator parses
them back.

Three artifact kinds:
  - "spec": structured JSON (requirement.json, design_spec.json, ...). These
    carry a canonical schema (required_keys + example) so the prompt the agent
    sees and the parser that reads it back can never drift apart.
  - "code": source files compiled by the toolchain (kernel.cpp, tiling.h, ...).
    Filenames are dynamic, so no fixed name or schema is enforced.
  - "doc": human-readable records (dev_record.md). Free-form; no schema.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


_VALID_KINDS = ("spec", "code", "doc")


@dataclass(frozen=True)
class ArtifactSpec:
    """Declares one artifact a stage produces.

    Attributes:
        name: Logical field name (usually the State field it parses into),
            e.g. "design_spec".
        kind: One of "spec" | "code" | "doc".
        filename: Fixed output filename for spec/doc artifacts (e.g.
            "design_spec.json"). Empty for "code" (dynamic filenames).
        required: When True, absence of a spec artifact is a stage error.
        required_keys: Top-level keys a spec mapping must contain. Validated
            against the parsed payload; ties the schema to its consumer.
        issue_required_keys: Keys each ``blocking_issues`` entry must contain
            (P47 Step 2 — gate-issue level, e.g. ``acceptance``). Validated
            against every issue in the parsed payload, enforcing an executable
            acceptance at load time (§1.3) — an issue whose judgment cannot be
            stated is not a special class of issue, it is an ill-formed one.
        allowed_top_level_keys: When non-empty, the CLOSED set of top-level keys
            a spec mapping may carry — any key outside it is a schema violation
            (方案 S, [[P100]]). Closes the "orphan sibling" class of bug: a
            gate-relevant design field the producer emits as a top-level sibling
            is structurally dropped by single-key aggregation
            (``tmpl_entry[k]=payload.get(k)``), so the consuming gate never sees
            it → AC0 dead-loop. Empty (default) = open (backward-compatible with
            every existing schema); only opt-in schemas enforce closure.
        description: Human description rendered into the agent prompt.
        example: Example payload rendered into the prompt as the schema the
            agent should follow. Only meaningful for "spec" artifacts.
    """

    name: str
    kind: str = "spec"
    filename: str = ""
    required: bool = True
    required_keys: tuple[str, ...] = ()
    issue_required_keys: tuple[str, ...] = ()
    allowed_top_level_keys: tuple[str, ...] = ()
    description: str = ""
    example: dict | None = None

    def __post_init__(self):
        if self.kind not in _VALID_KINDS:
            raise ValueError(
                f"ArtifactSpec.kind must be one of {_VALID_KINDS}, got '{self.kind}'")

    def validate_payload(self, data: object) -> list[str]:
        """Return schema errors for a parsed spec payload (empty = valid).

        Only "spec" artifacts are validated; code/doc always return [].
        P47 Step 2: ``issue_required_keys`` validates each ``blocking_issues``
        entry (gate-issue level), enforcing an executable acceptance so the
        producer states the judgment rather than the consumer guessing.
        """
        if self.kind != "spec":
            return []
        label = self.filename or self.name
        if not isinstance(data, dict):
            return [f"{label}: expected a JSON object, got {type(data).__name__}"]
        errors = []
        for key in self.required_keys:
            if key not in data:
                errors.append(f"{label}: missing required key '{key}'")
        # 方案 S (§1.3 加载期校验): closed schema rejects unknown top-level keys
        # at the producer boundary so a gate-relevant design field emitted as a
        # top-level sibling can never reach single-key aggregation (which would
        # drop it → consuming gate dead-loop, [[P100]]). Empty set = open.
        if self.allowed_top_level_keys:
            allowed = set(self.allowed_top_level_keys)
            unexpected = sorted(k for k in data if k not in allowed)
            if unexpected:
                errors.append(
                    f"{label}: unexpected top-level key(s) {unexpected}; "
                    f"allowed top-level keys: {sorted(allowed)}")
        if self.issue_required_keys:
            issues = data.get("blocking_issues")
            if isinstance(issues, list):
                for idx, issue in enumerate(issues):
                    if not isinstance(issue, dict):
                        errors.append(
                            f"{label}: blocking_issues[{idx}] must be a JSON object")
                        continue
                    for key in self.issue_required_keys:
                        if key not in issue:
                            errors.append(
                                f"{label}: blocking_issues[{idx}] missing required "
                                f"issue key '{key}'")
        return errors

    def to_prompt_block(self) -> str:
        """Render this spec as a markdown block for the agent prompt."""
        if self.kind != "spec":
            return ""
        header = f"### {self.filename} — {self.description}".rstrip(" —")
        lines = [header]
        # 方案 S: when the schema is closed, tell the producer the exact set of
        # top-level keys it may write — gate-relevant design content that does
        # NOT belong at top level (it must live inside the segment object so
        # single-key aggregation carries it to the consuming gate) is rejected
        # otherwise. The primary path is the agent self-conforming to this list;
        # the closure is the last-resort guard (§1.2).
        if self.allowed_top_level_keys:
            keys = ", ".join(self.allowed_top_level_keys)
            lines.append(f"(顶层只允许这些键: {keys}；其余设计内容请放进段对象内层)")
        if self.example is not None:
            body = json.dumps(self.example, ensure_ascii=False, indent=2)
            lines.append(f"```json\n{body}\n```")
        elif self.required_keys:
            keys = ", ".join(self.required_keys)
            lines.append(f"(必含字段: {keys})")
        return "\n".join(lines)


#: step-109 框架契约元数据文件（op_dir 顶层）——非算子源码改动：不进派生
#: changed-source 报告，落盘路由 ``artifacts/<stage>/_contract/``；内存 dict 照常
#: 携带（下游 ``artifacts.get(...)`` 读点零改动）。§1.15 单点：收集侧与落盘侧
#: 两处消费，新增契约文件加一行。匹配语义=顶层精确匹配（不做 basename 模糊
#: 匹配，防误伤子目录同名文件）。
CONTRACT_FILES = frozenset({
    "codegen_manifest.json",
    "decision_log.json",
    "changed_files.json",
})


@dataclass(frozen=True)
class ArtifactContract:
    """An ordered collection of ArtifactSpec for one stage."""

    artifacts: list[ArtifactSpec] = field(default_factory=list)
    def specs(self) -> list[ArtifactSpec]:
        """Spec-kind artifacts only."""
        return [a for a in self.artifacts if a.kind == "spec"]

    def required_specs(self) -> list[ArtifactSpec]:
        return [a for a in self.specs() if a.required]

    def by_name(self, name: str) -> ArtifactSpec | None:
        for a in self.artifacts:
            if a.name == name:
                return a
        return None

    def render_output_requirements(self, intro: str = "") -> str:
        """Build the prompt's output-requirements section from spec artifacts.

        Returns an empty string when the contract declares no spec artifacts.
        """
        specs = self.specs()
        if not specs:
            return ""
        lines = ["## 输出要求"]
        if intro:
            lines.append(intro)
        else:
            lines.append("请使用 Bash 或 Edit 工具将以下 JSON 文件写入当前工作目录：")
        for spec in specs:
            block = spec.to_prompt_block()
            if block:
                lines.append("")
                lines.append(block)
        return "\n".join(lines)

    def parse(self, artifacts: dict[str, str]) -> tuple[dict, list[str]]:
        """Parse spec artifacts from raw ``{filename: content}``.

        Returns ``({artifact_name: payload}, errors)``. Errors cover required
        artifacts that were not produced, invalid JSON, and required-key schema
        violations. Successfully parsed payloads are returned even when they
        have schema errors, so callers can decide whether to surface or store
        partial results.
        """
        parsed: dict = {}
        errors: list[str] = []
        for spec in self.specs():
            content = artifacts.get(spec.filename)
            if content is None:
                if spec.required:
                    errors.append(f"{spec.filename}: required artifact not produced")
                continue
            try:
                data = json.loads(content)
            except json.JSONDecodeError as e:
                errors.append(f"{spec.filename}: invalid JSON ({e})")
                continue
            errors.extend(spec.validate_payload(data))
            parsed[spec.name] = data
        return parsed, errors
