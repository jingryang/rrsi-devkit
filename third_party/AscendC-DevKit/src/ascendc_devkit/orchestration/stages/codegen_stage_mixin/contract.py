"""
契约 mixin — CodegenStage 的契石门判定与 manifest 契约校验。

承载输入/输出/artifact 契约、expected code files、validate_inputs、plugin/torch 契约门、
manifest 校验族、domain-gap 安全网、scalar-access 契约判定（``_scalar_contract_violations``）。
经 MRO 合并回 ``CodegenStage``（RegbaseMixin → ContractMixin → FeedbackMixin → DeployMixin →
PromptMixin → Stage，mixin 必在 ``Stage`` 前）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.domain.artifact import ArtifactSpec, ArtifactContract
from ascendc_devkit.domain.mdef_parse import parse_mdef_op_name
from ascendc_devkit.domain.op_name import (
    registration_matches_disk,
    runtime_config_candidates,
    snake_to_pascal,
)
from ascendc_devkit.orchestration.kernel.state import ErrorFeedback

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State

# 模块级单点：host 往返标记（维10③ 确定性机械扫描）
_HOST_ROUNDTRIP_RE = re.compile(r"\.cpu\(\)|kCPU")
_TORCH_LIBRARY_FRAGMENT_RE = re.compile(
    r"TORCH_LIBRARY_FRAGMENT\s*\(\s*([A-Za-z_]\w*)\s*,"
)
_SMOKE_OWNERSHIP_HOST_RETRY_BEFORE_DECLINE = 2


# —— host 往返标记 & AICore 注册名提取（从 codegen.py 迁入，契石门单点） ——

def _first_host_roundtrip(source: str) -> tuple[int | None, str | None]:
    """返回注释之外首个 ``.cpu()``/``kCPU`` 的 (1-based 行号, 命中串)；无则 (None, None)。

    逐行扫描、跟踪 ``/* */`` 块注释状态、剥除 ``//`` 行注释后匹配——既避免注释里提及
    ``.cpu()`` 造成假阳性，又给出指向真实代码行（而非剥注释后错位的行号）。字符串字面量
    内的 ``//``/``/*`` 不单独处理（本工程生成 plugin 中该边界不会出现）。
    """
    in_block = False
    for lineno, raw in enumerate(source.split("\n"), start=1):
        code: list[str] = []
        j, n = 0, len(raw)
        while j < n:
            if in_block:
                end = raw.find("*/", j)
                if end == -1:
                    break  # 本行剩余全在块注释内
                in_block = False
                j = end + 2
            elif raw.startswith("//", j):
                break  # 行注释 → 本行剩余忽略
            elif raw.startswith("/*", j):
                in_block = True
                j += 2
            else:
                code.append(raw[j])
                j += 1
        m = _HOST_ROUNDTRIP_RE.search("".join(code))
        if m is not None:
            return lineno, m.group(0)
    return None, None



# —— AICore 注册名提取(注册名派生源机械校验) ——
#
# 只扫 AICore 注册宏——它们首参是 driver kernel 的注册 Pascal,决定 runtime 按注册名
# 反推去找 ``kernel/config/<soc>/<snake>.json``。op_plugin ``m.def`` 里的 snake **不**在
# 此列:它驱动 eval 符号、可合法加 ``npu_`` 前缀(避 torch 内置名),与 config 查找无直接
# 因果(见 ``_registrations_from_artifacts`` docstring)。
_OP_ADD_RE = re.compile(r"\bOP_ADD\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)")
_LAUNCHER_LIST_RE = re.compile(
    r"\bADD_TO_LAUNCHER_LIST_AICORE\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)")


def _registrations_from_artifacts(
        artifacts: dict | None
) -> list[tuple[str, str, str]]:
    """收集产物里的 AICore 注册名,返回 ``(rel_path, macro, registered_pascal)``。

    覆盖两类注册宏 + 归属文件:
      - OpDef 注册 ``OP_ADD(<Pascal>)``——位于 ``op_host/*_def.cpp``(class 名 = 注册名);
      - aclnn L2 注册 ``ADD_TO_LAUNCHER_LIST_AICORE(<Pascal>, ...)``——位于
        ``op_api/*.cpp``。
    每个宏首参即 driver kernel 的注册名,决定 runtime 的 config 反推查找。只取首个匹配
    (单算子单注册;多算子文件(如 bench_lab 聚合)不属于 codegen 单算子产物)。

    判据(结构信号,不认算子名):按 ``rel`` 前缀(``op_host/`` + ``_def.cpp`` / ``op_api/``)
    归属到对应宏类型,避免在错误文件里找错宏。
    """
    found: list[tuple[str, str, str]] = []
    for rel, content in (artifacts or {}).items():
        if not isinstance(content, str):
            continue
        if rel.startswith("op_host/") and rel.endswith("_def.cpp"):
            m = _OP_ADD_RE.search(content)
            if m:
                found.append((rel, "OP_ADD", m.group(1)))
        elif rel.startswith("op_api/"):
            m = _LAUNCHER_LIST_RE.search(content)
            if m:
                found.append((rel, "ADD_TO_LAUNCHER_LIST_AICORE", m.group(1)))
    return found


class ContractMixin:
    """契石门 mixin（职责见模块 docstring，经 MRO 合并回 CodegenStage）。"""

    # P1 收敛（2026-08-19）：inputs/outputs/attrs 降为可选——实测下游（deploy/smoke/precision/
    # adapt）只消费 callable_target + op_name，harness 绑 golden 用 op_spec；IO 只服务 codegen
    # 内部校验，属「三重冗余」（冗余于 m.def、op_spec、下游），不再要求 agent 在退化会话末尾
    # 声明，从源头消除 P1 的 manifest 非契约 retry 门。callable_target 框架从 TORCH_LIBRARY
    # 派生（_ensure_manifest_callable_target），op_name 从 op_dir。
    _REQUIRED_MANIFEST_KEYS = ("op_name", "callable_target")
    # 已知调试/报告字段（属 decision_log，不属 manifest）。仅 warn 不 hard-reject
    #（保 §1.4 可拓展：未知新字段放行）。这是字段语义结构信号，非算子名（§1.12）。
    _MANIFEST_DEBUG_NOTE_FIELDS = frozenset({
        "compile_status", "runtime_status", "suspected_root_causes", "next_steps",
        "files", "key_apis_used", "template_routes", "auxiliary_files_modified",
        "reference_scaffold", "codegen_phase", "generated_at",
    })

    def _scalar_contract_violations(self, state: State,
                                    decision_logs: dict,
                                    agent_result) -> list | None:
        """契石门 scalar-access 契约：声明集合包含关系 + 簿记一致性（结构信号）。

        从 design 声明（``tiling_strategy.scalar_access_points[].name``）与
        coder 的 ``decision_log.json`` / 源码逐点核对，返回违约列表（空 =
        通过）。仅在设计产物在场时启用（无 ``tiling_strategy`` 即无声明集可
        查，单测/隔离 State 不受影响）。
        """
        if state.tiling_strategy is None:
            return None
        ts = state.tiling_strategy or {}
        declared_pts = ts.get("scalar_access_points") \
            if isinstance(ts, dict) else None
        declared = [p.get("name") for p in declared_pts
                    if isinstance(p, dict)] \
            if isinstance(declared_pts, list) else []
        op_dir = state.op_dir or (
            state.op_identity.op_dir
            if state.op_identity else None)
        return _validate_scalar_contract(
            declared,
            decision_logs.get(self.name) or {},
            agent_result.artifacts, op_dir)

    def input_contract(self) -> StageIOContract:
        # kernel_architecture is provided by codegen_init (step 9), not design.
        return StageIOContract(
            requires=["design_spec", "tiling_strategy", "mode", "profile"],
            optional=["kernel_architecture", "op_identity", "reference_code", "last_error"],
        )

    def output_contract(self) -> StageIOContract:
        return StageIOContract(
            provides=["generated_sources", "codegen_iterations",
                      "build_result", "deploy_result"],
            optional_provides=["codegen_manifest"],
        )

    def artifact_contract(self) -> ArtifactContract:
        # Codegen emits source files whose names are dynamic (derived from the
        # design's kernel_architecture), so they are declared as a single
        # "code" artifact rather than fixed-name specs. The concrete expected
        # filenames are resolved at runtime via _expected_code_files().
        return ArtifactContract(artifacts=[
            ArtifactSpec(
                name="generated_sources",
                kind="code",
                required=True,
                description="AscendC 源文件（kernel.h/.cpp, tiling.h/.cpp 等）",
            ),
        ])

    @staticmethod
    def _expected_code_files(state: State) -> list[str]:
        """Return expected section directories (not individual filenames).

        Design's kernel_architecture declares which *sections* are needed
        (this is a design decision).  Specific filenames within each section
        are determined by the codegen agent by learning from reference
        operators — same mechanism as CMakeLists.txt.

        Omitted sections → not expected.  Validation checks that each
        returned directory exists and contains at least one source file.
        """
        arch = state.kernel_architecture or {}

        def _section_dir(kind: str, default_dir: str) -> str | None:
            if kind not in arch:
                return None                     # section not declared → skip
            section = arch[kind]
            if not isinstance(section, dict):
                return default_dir              # key present, non-dict → default dir
            return section.get("directory", "") or default_dir

        results: list[str] = []
        for kind, default_dir in [
            ("host_code", "op_host"),
            ("kernel_code", "op_kernel"),
            ("api_code", "op_api"),
            ("plugin_code", "op_plugin"),
        ]:
            d = _section_dir(kind, default_dir)
            if d:
                results.append(d)
        return results

    def validate_inputs(self, state: State) -> list[str]:
        errors = []
        ds = state.design_spec
        if not isinstance(ds, dict):
            errors.append("design_spec must be a dict")
        else:
            inputs = ds.get("inputs", [])
            outputs = ds.get("outputs", [])
            if not inputs:
                errors.append("design_spec.inputs is empty or missing")
            if not outputs:
                errors.append("design_spec.outputs is empty or missing")
        # §1.9 build-chip precondition (Option D): the compiled binary is
        # hardware-coupled (CANN soc_version is fixed at compile time), so a
        # target≠hardware mismatch is a HARD precondition — not a codegen-fixable
        # defect. Checked here (pre-spawn, pre-iteration-loop) so a non-empty
        # reason makes the runner raise PreconditionError → clean halt, codegen
        # never spawns (vs the old deploy-gate that stranded the check in a
        # service with an empty signal channel). Single-sourced by
        # chip_mismatch_reason (§2.5).
        #
        # step-34: pure comparison — runtime_target_chip was resolved once at
        # dispatch (probe authority), so the gate no longer probes (no
        # EnvironmentProbeTimeout path here; a probe timeout is handled at
        # dispatch via --runtime_target_chip fallback / EX_DATAERR).
        from ascendc_devkit.adapters.npu.detect import chip_mismatch_reason
        chip_reason = chip_mismatch_reason(
            state.design_target_chip,
            state.runtime_target_chip,
        )
        if chip_reason:
            errors.append(chip_reason)
        return errors

    def _check_section_dirs_have_files(self, state: State) -> bool:
        """检查 op_host/op_kernel 等 section 目录是否有源文件产出（对应 SKILL.md line 307）。"""
        code_path = state.op_dir or (
            state.op_identity.op_dir if state.op_identity else None)
        if not code_path:
            return False
        for d in ("op_host", "op_kernel", "op_api", "op_plugin"):
            section = Path(code_path) / d
            if section.is_dir():
                if any(section.glob("*.cpp")) or any(section.glob("*.h")):
                    return True
        return False

    @staticmethod
    def _profile_scaffolding_kind(state: State) -> str:
        """Return the profile-selected invocation protocol, if available.

        Real workflows resolve a repository profile before codegen.  Keeping the
        empty fallback makes isolated unit tests and legacy snapshots diagnosable,
        while never inventing a protocol when the authority is absent.
        """
        profile = getattr(state, "profile", None)
        return profile.scaffolding_kind() if profile is not None else ""

    def _required_codegen_sections(self, state: State) -> list[str]:
        """Merge design sections with repository invocation requirements."""
        sections = self._expected_code_files(state)
        if (self._profile_scaffolding_kind(state) == "torch_op"
                and "op_plugin" not in sections):
            sections.append("op_plugin")
        return sections

    @staticmethod
    def _plugin_sources(
            state: State, artifacts: dict | None = None
    ) -> list[tuple[str, str]]:
        """Collect generated ``op_plugin/*.cpp`` sources from artifacts and disk."""
        sources: list[tuple[str, str]] = []
        seen: set[str] = set()
        for rel, content in (artifacts or {}).items():
            if (rel.startswith("op_plugin/") and rel.endswith(".cpp")
                    and isinstance(content, str)):
                sources.append((rel, content))
                seen.add(rel)

        op_dir = state.op_dir or (
            state.op_identity.op_dir if state.op_identity else None)
        if op_dir:
            plugin_dir = Path(op_dir) / "op_plugin"
            if plugin_dir.is_dir():
                for path in sorted(plugin_dir.glob("*.cpp")):
                    rel = f"op_plugin/{path.name}"
                    if rel in seen:
                        continue
                    try:
                        sources.append((rel, path.read_text(encoding="utf-8")))
                    except OSError:
                        continue
        return sources

    def _resolve_torch_registration(
            self, state: State, artifacts: dict | None = None
    ) -> tuple[str, str] | None:
        """Resolve ``(namespace, op_name)`` from a real torch plugin registration.

        A torch callable target is valid only when one source contains both a
        ``TORCH_LIBRARY_FRAGMENT`` namespace and a parseable ``m.def`` schema.
        Missing or partial registration is not recoverable by guessing the
        operator name.
        """
        for _, source in self._plugin_sources(state, artifacts):
            namespace = _TORCH_LIBRARY_FRAGMENT_RE.search(source)
            registered_name = parse_mdef_op_name(source)
            if namespace and registered_name:
                return namespace.group(1), registered_name
        return None

    def _torch_plugin_contract_error(
            self, state: State, artifacts: dict | None = None
    ) -> ErrorFeedback | None:
        """Validate the mandatory registration contract for ``torch_op``."""
        if self._resolve_torch_registration(state, artifacts) is not None:
            return None
        sources = [name for name, _ in self._plugin_sources(state, artifacts)]
        return ErrorFeedback(
            stage_name="codegen",
            error_type="incomplete_output",
            message=(
                "repository profile selects torch_op, but no valid op_plugin "
                "registration was generated; require op_plugin/*.cpp containing "
                "both TORCH_LIBRARY_FRAGMENT(namespace, m) and m.def(\"op(...)\")"
            ),
            details={
                "reason": "torch_op_plugin_missing_or_invalid",
                "scaffolding_kind": "torch_op",
                "plugin_sources": sources,
                "required_section": "op_plugin",
            },
        )

    def _plugin_host_offload_error(
            self, state: State, artifacts: dict | None = None
    ) -> ErrorFeedback | None:
        """维10③ 确定性机械扫描：plugin host CPU 往返 → 契约错误（硬门）。

        op_plugin/*.cpp 里出现 ``.cpu()`` / ``kCPU``（``.to(torch::kCPU)`` 等）即判
        host 往返——plugin 把算子逻辑搬到 CPU host 再 copy 回输出，绕过 aclnn kernel
        （moe_re_routing 历史实证：``.to(torch::kCPU)`` + host 前缀和 + ``.copy_()``
        回写 permute_token_idx/expert_token_num → cann-bench no_npu_kernel_detected）。

        近零误判：维10 已把 plugin 契约收窄到「接口适配 + 调 aclnn」，标量控制输入走
        attr、shape 用 ``.sizes()``、空检查用 ``.numel()``，``*_npu`` 函数内无合法
        ``.cpu()``/``kCPU``。注释先剥除再匹配（_first_host_roundtrip），避免注释提及
        造成假阳性。命中 → 定向 retry codegen（feedback 带 file + line + 命中模式）。
        """
        for rel, source in self._plugin_sources(state, artifacts):
            line, pattern = _first_host_roundtrip(source)
            if line is None:
                continue
            return ErrorFeedback(
                stage_name="codegen",
                error_type="incomplete_output",
                message=(
                    f"op_plugin host CPU 往返（{pattern!r}）违反维10③：plugin 层 "
                    "把算子逻辑搬到 CPU host 再 copy 回输出，绕过 aclnn kernel。"
                    "分两类处置——"
                    "① 确为把数据/算值逻辑搬到 host 计算再写回输出（moe_re_routing 类）"
                    "→ 迁回 kernel/tiling，plugin 只保留接口适配 + aclnn kernel 调用；"
                    "② 若为数据相关输出长度收窄（输出某维长度须 kernel 运行后得知，如"
                    "去重/收集类算子读回 count 标量定 shape）→ 该信息在 kernel/tiling 无"
                    "归宿，合法写法是 `aclrtSynchronizeStream` + `aclrtMemcpy(D2H)` "
                    "读回 count 标量元数据，勿用 `.to(kCPU)` 整张搬回。"
                ),
                details={
                    "reason": "plugin_host_offload",
                    "scaffolding_kind": "torch_op",
                    "plugin_file": rel,
                    "line": line,
                    "pattern": pattern,
                },
            )
        return None

    def _aicore_registration_mismatch_error(
            self, state: State, artifacts: dict | None = None
    ) -> ErrorFeedback | None:
        """AICore 注册名派生源机械校验：注册名 runtime 反推须命中落盘目录名。

        背景(P 361001 / adaptive_avg_pool_3d):codegen 产物里 coder 常从 proto 的
        ``operator.name`` 抄注册 Pascal(数字段大写,如 ``AdaptiveAvgPool3D``),而 runtime
        按注册名反推(``adaptive_avg_pool_3_d``/``adaptive_avg_pool3d``)找不到以落盘目录
        名(``op_name`` snake,如 ``adaptive_avg_pool_3d``)命名的 config → 永不选中 custom
        binary → 静默落回内置同名 op → 361001。

        判据(结构信号):扫 ``op_host/*_def.cpp`` 的 ``OP_ADD`` / ``op_api/*.cpp`` 的
        ``ADD_TO_LAUNCHER_LIST_AICORE`` 首参 = 注册 Pascal,与落盘目录名(= ``state.op_name``
        snake,config 文件名基底)经 ``registration_matches_disk`` 比对——落盘名须 ∈ runtime
        候选集。误判近零:正确写法是从 ``state.op_name`` 经 ``snake_to_pascal`` 派生,必命中
        (见 domain/op_name round-trip);不命中 = 抄了别处。命中 → 定向 retry codegen
        (reason=reg_name_mismatch),指引从落盘名派生,不 halt。``m.def``/``op_plugin`` 不参与
        比对(见 ``_registrations_from_artifacts`` docstring)。
        """
        disk = ""
        op_dir = state.op_dir or (
            state.op_identity.op_dir if state.op_identity else None)
        if op_dir:
            # config 文件名基底的机制真源 = 编译器从 op_dir 目录名派生(op_file =
            # op_dir + '.json')。带前缀 profile(如 ai_infra_)的目录名 = 前缀+短名,
            # 与 strip 后的 state.op_name 不同——比对必须用目录名,用短名会误拦
            # 从目录名正确派生的注册名。
            disk = Path(op_dir).name
        if not disk:
            # profile-less/无 op_dir 单元态退回 op_name(无前缀仓二者一致)
            disk = (state.op_name or "").strip()
        if not disk:
            return None
        for rel, macro, reg in _registrations_from_artifacts(artifacts):
            if registration_matches_disk(reg, disk):
                continue
            derived = snake_to_pascal(disk)
            candidates = sorted(runtime_config_candidates(reg))
            return ErrorFeedback(
                stage_name="codegen",
                error_type="incomplete_output",
                message=(
                    f"AICore 注册名 {reg!r}({macro} in {rel}) runtime 反推候选 "
                    f"{candidates} 不命中落盘目录名 "
                    f"{disk!r}(config 文件名基底)。注册名须从落盘目录名({disk!r})经 "
                    f"snake_to_pascal 派生(得 {derived!r}),勿直接抄 proto/requirement 的 "
                    f"operator.name——proto 数字段大写会让 runtime 找不到 config → 361001。"
                ),
                details={
                    "reason": "reg_name_mismatch",
                    "registered_name": reg,
                    "disk_op_name": disk,
                    "macro": macro,
                    "reg_file": rel,
                    "runtime_candidates": candidates,
                    "expected_derived": derived,
                },
            )
        return None

    @staticmethod
    def _code_path_has_source_files(code_path: str) -> bool:
        """检查 op_host/op_kernel/op_api/op_plugin 中是否有源文件（SKILL.md 3.1）。"""
        if not code_path:
            return False
        for d in ("op_host", "op_kernel", "op_api", "op_plugin"):
            section = Path(code_path) / d
            if section.is_dir() and (
                    any(section.glob("*.cpp")) or any(section.glob("*.h"))):
                return True
        return (Path(code_path) / "CMakeLists.txt").is_file()

    @staticmethod
    def _update_meta_retries(rd: str, retries: dict) -> None:
        """写回 meta.json 的 retries 字段（与 SKILL.md dev_record.sh set-meta 对齐）。"""
        meta_path = Path(rd) / "meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                meta["retries"] = retries
                meta_path.write_text(
                    json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass

    @staticmethod
    def _return_verdict(declared: list[str], impl_kind: str) -> str | None:
        """高置信判定 m.def 声明返回 ↔ C++ 实现返回类型是否矛盾。

        - 声明 ``(A, B, ...)`` 元组 N≥2，实现 ``std::vector``（→ ``Tensor[]`` 1 变长）
          或单个 ``Tensor`` → 必错（返回数 1 vs N，checkSchema 拒）。
        - 声明单 ``-> Tensor``，实现 ``std::vector`` → 必错（``Tensor`` ≠ ``Tensor[]``）。
        - 两者都是元组但元素数不等 → 必错。
        - 其余（``Tensor[]``+``std::vector`` 合法、optional 灰区、``()``、解析不了）→
          fail-open 返回 None，由运行期 smoke（B）兜底。

        返回不匹配类别名，或 None（一致 / fail-open）。
        """
        n = len(declared)
        var_single = (n == 1 and declared[0] in ("Tensor[]", "Tensor[]?"))
        if impl_kind == "vector":
            if var_single:
                return None  # 合法：Tensor[] + std::vector
            if n >= 2:
                return "tuple_vs_vector"
            if n == 1 and declared[0] in ("Tensor", "Tensor?"):
                return "single_vs_vector"
            return None  # () / 未知声明 → fail-open
        if impl_kind.startswith("tuple"):
            m = re.match(r"tuple(\d+)", impl_kind)
            if m:
                arity = int(m.group(1))
                # 声明 arity != 实现 arity → 必错（checkSchema 按返回数拒）。唯一例外：
                # 两者都是 1（std::tuple<T> 单元素元组 PyTorch 解包为单返回，一致）。
                if arity != n and not (n == 1 and arity == 1):
                    return "tuple_arity_mismatch"
            return None
        if impl_kind == "tensor":
            if n >= 2:
                return "tuple_vs_single"
            return None
        return None  # optional/void/unknown → fail-open

    def _plugin_return_schema_mismatch(self, state: State,
                                       artifacts: dict) -> dict | None:
        """方案 A：静态对质每个 op_plugin 的 m.def 返回签名与 m.impl 实现返回类型。

        fail-open：任一侧解析不确定 → 跳过该文件继续；全部跳过 → None。只返回首个
        高置信不匹配（dict：reason/plugin_file/declared_returns/impl_return_kind）。
        """
        from ascendc_devkit.domain.mdef_parse import (
            parse_mdef_return_signature,
            plugin_impl_return_kinds,
        )
        for rel, src in self._plugin_sources(state, artifacts):
            declared = parse_mdef_return_signature(src)
            impl_kinds = plugin_impl_return_kinds(src)
            if declared is None or not impl_kinds:
                continue  # fail-open
            for kind in impl_kinds:
                reason = self._return_verdict(declared, kind)
                if reason is not None:
                    return {
                        "reason": reason,
                        "plugin_file": rel,
                        "declared_returns": declared,
                        "impl_return_kind": kind,
                    }
        return None

    @staticmethod
    def _read_smoke_ownership(decision_log_content) -> dict | None:
        """读 coder 的归属判定 verdict（§2.10 结构化；防作弊：必须带非空 reason）。

        ``decision_log_content`` 是 coder 的 decision_log.json 反序列化内容（transition 里
        从 ``agent_result.artifacts["decision_log.json"]`` 解析后存于 ``decision_logs[self.name]``）。
        """
        if not isinstance(decision_log_content, dict):
            return None
        ow = decision_log_content.get("codegen_smoke_ownership")
        if not isinstance(ow, dict):
            return None
        if ow.get("verdict") not in ("not_codegen", "upstream_design"):
            return None
        if not (ow.get("reason") or "").strip():
            return None
        return ow

    @staticmethod
    def _ownership_honored(phase: str | None, prior_smoke_streak: int, ownership: dict) -> bool:
        """归属判定是否生效（Part B 1f）：歧义区立即 honor；host 域需同错重试 ≥K 次防逃避。

        ``prior_smoke_streak`` 用 smoke 循环内**同签名**累计的
        ``codegen_smoke_same_error_streak``（只在 smoke re-spawn 路径累计、所有非 smoke
        路径重置、签名变化重置为 1）——不是共享的 ``codegen_build_retries``（后者含
        build/schema/artifact 重试，build 重试消耗后首轮 smoke 的 not_codegen 会被提前
        honor，「强制先真正尝试一轮」被稀释；M2 review 坐实）。语义：coder 已对该错误
        （同签名）真正尝试修复 ≥K 次后，才允许 not_codegen/upstream_design 放行下游。
        """
        if phase is None:
            return True
        if phase == "host":
            return prior_smoke_streak >= _SMOKE_OWNERSHIP_HOST_RETRY_BEFORE_DECLINE
        return False

    @staticmethod
    def _classify_smoke_schema_mismatch(err) -> dict | None:
        """方案 B：smoke 失败是否为 checkSchema schema 不匹配（运行期确定性信号）。

        读 smoke 完整日志（``log_path``，比 ``stderr_tail`` 可靠——checkSchema 错误在
        module-load 顶部，可能被 stderr 尾部截断）。命中 c10::Error 的
        ``"doesn't match the expected function schema"`` → 提取 expected/inferred 两套
        schema（checkSchema 错误同时含两者，确定性证据，§1.11 看实际产出）。非 schema
        类 smoke 失败 → None（维持原 D4 交 scope_guard，零误杀）。
        """
        details = getattr(err, "details", {}) or {}
        stderr = details.get("stderr_tail", "") or ""
        log_path = details.get("log", "") or ""
        full = stderr
        if log_path:
            try:
                with open(log_path, encoding="utf-8", errors="replace") as f:
                    full = f.read()
            except OSError:
                pass
        if "doesn't match the expected function schema" not in full:
            return None
        expected = re.search(r"expected='([^']*)'", full)
        inferred = re.search(r"inferred='([^']*)'", full)
        return {
            "expected_schema": expected.group(1) if expected else "",
            "inferred_schema": inferred.group(1) if inferred else "",
            "log_path": log_path,
        }

    def _warn_manifest_name_drift(self, state: State, manifest: dict) -> None:
        """P10 §1.3 加载期校验：manifest 参数名偏离 proto 时 warn（只观测，不修）。

        codegen_manifest.inputs[].name + attrs[].name 应逐字等于 proto
        (requirement.op_spec.inputs[].name + attrs.keys())。偏离 = codegen 用了泛化名
        (x/p) 而非 proto 名 (input/scalar)，cann-bench 关键字调用会失败。根治兜底
        在 cannbench_adapt，此处仅暴露可观测信号（参数名 fidelity 是 codegen skill 职责）。
        """
        from ascendc_devkit.infra.logger import Logger

        op_spec = state.requirement.op_spec if state.requirement else None
        if op_spec is None:
            return
        proto_names = [t.name for t in (op_spec.inputs or [])]
        if op_spec.attrs:
            proto_names.extend(op_spec.attrs.keys())
        if not proto_names:
            return
        manifest_names: list[str] = []
        for inp in manifest.get("inputs") or []:
            if isinstance(inp, dict) and inp.get("name"):
                manifest_names.append(inp["name"])
        for attr in manifest.get("attrs") or []:
            if isinstance(attr, dict) and attr.get("name"):
                manifest_names.append(attr["name"])
        if manifest_names and manifest_names != proto_names:
            Logger.warn(
                f"codegen: manifest param names {manifest_names} drift from proto "
                f"{proto_names} — cann-bench keyword-call will fail (P10); "
                f"cannbench_adapt will rename m.def schema to proto names as fallback"
            )

    def _check_plugin_schema_consistency(self, state: State, manifest: dict,
                                         artifacts: dict) -> None:
        """Q3-aggregate self-check: plugin ``m.def`` schema inputs must match
        ``manifest.inputs`` **when the manifest declares them**.

        Catches phantom-input bugs — e.g. plugin declares ``Tensor? mask=None``
        in ``m.def`` but manifest drops it (or vice versa) → ``ACLNN_CMD``
        position binding drifts at runtime → ``EZ1001 AclNN_Parameter_Error``
        (batch 20260727_225324 aggregate_hidden_grad root cause: plugin had 4
        inputs incl. mask, manifest had 3 → mask_c fell into the grad_input
        slot).

        P1 收敛（2026-08-19）：manifest inputs 降为可选（下游不消费 IO，harness 绑
        golden 用 op_spec）。plugin ``m.def`` 是运行时绑定的**唯一权威源**（ACLNN_CMD
        按 plugin schema 绑参）——故检查只在 manifest **主动声明**了非空 inputs 时
        才做对比：声明了却与 plugin 不符 → warn（agent 回声失真）；未声明 → 不报
        （agent 合法选择不回声，非失真）。Observable warn only。
        """
        from ascendc_devkit.infra.logger import Logger

        if not manifest or not artifacts:
            return
        plugin_keys = [k for k in artifacts
                       if "op_plugin/" in k and k.endswith("_plugin.cpp")]
        if not plugin_keys:
            return
        plugin_src = artifacts[plugin_keys[0]]
        if not isinstance(plugin_src, str):
            return
        # m.def("op_name(Tensor a, Tensor? b=None, ...) -> ...") — may span lines
        m = re.search(r'm\.def\(\s*"(\w+)\(([^)]*)\)', plugin_src, re.DOTALL)
        if not m:
            return
        schema_params = m.group(2)
        # W3 (precision-tensorlist-harness-contract): recognize the TensorList
        # form ``Tensor[] x`` (the variadic form) in addition to ``Tensor x`` /
        # ``Tensor? mask`` — the old ``Tensor\??\s+(\w+)`` regex matched no
        # tensor for ``Tensor[]``, false-positiving a phantom-input mismatch on
        # correct TensorList plugins and blind to real Tensor[]-shape phantom
        # bugs. ``Tensor?[]`` and ``Tensor[]?`` (optional variadic) also covered.
        tensor_params = [n for _, n in re.findall(
            r'Tensor\??(\[\])?\??\s*(\w+)', schema_params)]
        manifest_inputs = [i.get("name") for i in (manifest.get("inputs") or [])
                           if isinstance(i, dict) and i.get("name")]
        # P1 收敛：manifest 未主动声明 IO → 不校验（合法不回声），以 plugin 为权威。
        if not manifest_inputs:
            return
        # Order-sensitive compare (m1 fix): a count-only check (len !=) missed
        # equal-length position drift ([a,b] vs [b,a]) — the actual EZ1001 danger
        # (mask_c binds the grad_input slot). Compare the full sequence; classify
        # the drift so the warn says whether it's a phantom input or pure order.
        if tensor_params != manifest_inputs:
            only_plugin = sorted(set(tensor_params) - set(manifest_inputs))
            only_manifest = sorted(set(manifest_inputs) - set(tensor_params))
            same_set = set(tensor_params) == set(manifest_inputs)
            drift_kind = ("position/order drift (same names, wrong sequence — "
                          "drifts ACLNN_CMD position binding)"
                          if same_set
                          else "phantom/unmatched input")
            Logger.warn(
                f"codegen: plugin m.def tensor inputs {tensor_params} vs manifest "
                f"inputs {manifest_inputs} mismatch ({drift_kind}; "
                f"plugin_only={only_plugin}, manifest_only={only_manifest}) — "
                f"drifts ACLNN_CMD position binding (Q3-aggregate EZ1001 root cause)"
            )

    def _check_opdef_optional_output(self, state: State,
                                     artifacts: dict) -> dict | None:
        """F5: OpDef 输出声明 ``ParamType(OPTIONAL)`` → __CCE_KernelArgSize 膨胀隐患。

        codegen 契约门（非 warn-only）：AscendC 编译器对 OPTIONAL 输出多发射 8B 参数槽
        （48 vs host 40）→ kernel 入口读垃圾 tiling 指针 → 507057 向量核异常（历史实证）。
        aclnn 走 fail-closed smoke（无 kernel 执行探针）拦不住——必须 retry 回 codegen 重修
        （脚手架问题由 codegen 解决，§2.9）。规则 = OpDef 输出一律 REQUIRED，可选性归
        schema ``Tensor?`` + plugin 返回 None（维11）。命中 → warn（可观测）+ 返回 retry
        判定 dict（``reason/def_file/output_name``），由调用方 ``_plugin_schema_retry`` 定向
        retry；未命中 → None。判据（结构信号，不认算子名）：``{op}_def.cpp`` 中
        ``.Output("...")`` 链后跟 ``.ParamType(OPTIONAL)``。
        """
        from ascendc_devkit.infra.logger import Logger

        if not artifacts:
            return None
        for rel, content in artifacts.items():
            if not (rel.startswith("op_host/") and rel.endswith("_def.cpp")
                    and isinstance(content, str)):
                continue
            # 状态机：跟踪当前链是 Input 还是 Output，检出 Output + ParamType(OPTIONAL)。
            # 单行同时含 Input/Output 时以 Output 优先（本检查只关心输出的 OPTIONAL）。
            chain: str | None = None
            name: str | None = None
            for line in content.splitlines():
                s = line.strip()
                # 兼容 `this->Input("x")` 与 `.Input("x")`（def.cpp 惯用 this-> 声明、
                # ParamType 用 . 链式；\b 在 -> / . 后都成立）。
                m_out = re.search(r'\bOutput\("([^"]+)"', s)
                m_in = re.search(r'\bInput\("([^"]+)"', s)
                if m_out:
                    chain = "output"
                    name = m_out.group(1)
                elif m_in:
                    chain = "input"
                if re.search(r'\.ParamType\(\s*OPTIONAL\s*\)', s):
                    if chain == "output":
                        Logger.warn(
                            f"codegen: OpDef output '{name}' in {rel} declared "
                            f"ParamType(OPTIONAL) — AscendC compiler emits an extra "
                            f"8B kernel-arg slot (__CCE_KernelArgSize 48 vs host 40) "
                            f"→ kernel reads garbage tiling pointer → 507057. Use "
                            f"REQUIRED + express optionality via schema 'Tensor?' + "
                            f"plugin returning None (维5b/维11).")
                        return {
                            "reason": "opdef_optional_output",
                            "def_file": rel,
                            "output_name": name,
                        }
        return None

    def _inject_scaffolding_kind(self, state: State, manifest: dict) -> None:
        """Set ``callable_target.kind`` from the repo profile (single authority).

        The invocation protocol is a repo-level decision owned by
        ``profile.scaffolding.selected`` (§1.5 single source), not something the
        agent picks per run. We overwrite ``kind`` in place with the
        profile-selected value so every downstream consumer (smoke probe,
        deploy/precision call) reads one coherent protocol. If the agent wrote a
        divergent ``kind``, we warn (§1.2 可诊断: don't silently mask the drift)
        before overwriting. Mutates ``manifest`` in place.
        """
        from ascendc_devkit.infra.logger import Logger

        if state.profile is None:
            raise RuntimeError(
                "codegen: _inject_scaffolding_kind requires a profile, but "
                "profile is None. Ensure the workflow's preflight resolves a "
                "repo profile before reaching the codegen stage."
            )
        kind = state.profile.scaffolding_kind()
        ct = manifest.get("callable_target")
        if not isinstance(ct, dict):
            manifest["callable_target"] = {"kind": kind}
            return
        agent_kind = ct.get("kind")
        if agent_kind and agent_kind != kind:
            Logger.warn(
                f"codegen: manifest callable_target.kind '{agent_kind}' diverges "
                f"from profile-selected scaffolding '{kind}' — overwriting with "
                f"the profile authority (the agent must not choose the protocol)"
            )
        ct["kind"] = kind

    def _ensure_manifest_callable_target(self, state, manifest, artifacts):
        """Constructively ensure ``callable_target{kind,symbol}`` (§2.9).

        ``callable_target`` is determined by the repo profile (kind) + the
        ``op_plugin`` ``TORCH_LIBRARY_FRAGMENT`` registration (symbol) the agent
        already wrote — it is NOT independent information. We derive it (single
        source = plugin) rather than halt when the agent omitted it (the dequant
        case: plugin correct, manifest ``callable_target`` absent). Mirrors the
        regbase derivation at L1954-1963; factored here so the logic lives once.

        Only ``torch_op`` has a registration parser today. ``aclnn`` (no parser,
        smoke fail-closed) and ``pybind`` (no parser) stay honest (§3.7) — they
        return whatever the agent filled (caller validates/retries if incomplete).
        Adding a future protocol's derivation is a localized ``elif`` here
        (extensibility), gated on ``profile.scaffolding_kind()`` (generic, §1.12).

        Returns ``(manifest, ok)``: ``manifest`` may be newly constructed if it
        was ``None``; ``ok=True`` iff ``callable_target`` ends up with both
        ``kind`` + ``symbol`` (derived or agent-filled).
        """
        from ascendc_devkit.infra.logger import Logger

        profile_kind = self._profile_scaffolding_kind(state)
        # Non-torch_op: no registration source to derive symbol from. Stay honest
        # (§3.7) — return whatever the agent filled; caller retries if incomplete.
        if profile_kind != "torch_op":
            ct = (manifest.get("callable_target")
                  if isinstance(manifest, dict) else None)
            ok = (isinstance(ct, dict)
                  and bool(ct.get("kind")) and bool(ct.get("symbol")))
            return manifest, ok
        # torch_op: the op_plugin registration is the single authority for the
        # symbol (the framework already cross-validates manifest-vs-plugin below).
        # If the agent already filled a complete callable_target, trust it — no
        # derivation (and no plugin) needed. Only derive when it's incomplete.
        ct = (manifest.get("callable_target")
              if isinstance(manifest, dict) else None)
        if isinstance(ct, dict) and ct.get("kind") and ct.get("symbol"):
            return manifest, True
        registration = self._resolve_torch_registration(state, artifacts)
        if registration is None:
            # plugin missing/unparseable → can't derive → caller retries (not halt)
            return manifest, False
        namespace, registered_name = registration  # registered_name may be npu_<op>
        if not isinstance(manifest, dict):
            manifest = {
                "op_name": state.op_name or "unknown",
                "_fallback": True,
            }
        ct = manifest.get("callable_target")
        if not isinstance(ct, dict):
            ct = {}
            manifest["callable_target"] = ct
            if "_fallback" not in manifest:
                manifest["_fallback"] = True
        ct["kind"] = profile_kind  # profile authority (mirrors _inject_scaffolding_kind)
        ct["symbol"] = f"torch.ops.{namespace}.{registered_name}"  # plugin authority
        Logger.warn(
            f"codegen: derived callable_target.symbol '{ct['symbol']}' from "
            f"op_plugin TORCH_LIBRARY_FRAGMENT registration (agent omitted it "
            f"in manifest) — manifest auto-rescued, no halt")
        return manifest, True

    def _missing_required_manifest_fields(self, manifest) -> list[str]:
        """Return ``required_keys`` (per ``schema/codegen_manifest.json``) that
        are missing/empty. ``callable_target`` is deep-checked (kind+symbol).
        After ``_ensure_manifest_callable_target`` the callable_target is usually
        satisfied; this catches missing authored fields (op_name; inputs/outputs
        were dropped from required_keys — P1 收敛, IO 不被下游消费).
        """
        if not isinstance(manifest, dict):
            return list(self._REQUIRED_MANIFEST_KEYS)
        missing: list[str] = []
        for k in self._REQUIRED_MANIFEST_KEYS:
            v = manifest.get(k)
            if v is None or v == "" or v == []:
                missing.append(k)
        ct = manifest.get("callable_target")
        if ("callable_target" not in missing and isinstance(ct, dict)
                and (not ct.get("kind") or not ct.get("symbol"))):
            missing.append("callable_target")
        return missing

    def _warn_manifest_extra_fields(self, manifest) -> None:
        """Observable warn for known debug/report fields inside the manifest
        (§1.2 可诊断). Not hard-rejected — extensibility for unknown new fields
        (§1.4). The agent is told (skill 维8 + prompt) that debug/report content
        belongs in ``decision_log.json``; this surfaces drift when it doesn't.
        """
        from ascendc_devkit.infra.logger import Logger

        if not isinstance(manifest, dict):
            return
        found = [k for k in manifest if k in self._MANIFEST_DEBUG_NOTE_FIELDS]
        if found:
            Logger.warn(
                f"codegen: manifest contains non-contract fields {found} — "
                f"debug/report content belongs in decision_log.json, not "
                f"codegen_manifest.json (manifest is a signature contract)")

    def _scaffold_contract_summary(self, state: State) -> str | None:
        """Part 2 (2026-08-20): 从 ``reference_code`` 派生紧凑脚手架契约摘要，注入
        coder prompt，替代 agent 整读参考算子（round 1 ~90K 脚手架探索成本主因）。

        §1.12 结构信号：只提取文件布局 / CMakeLists 注册模式 / TORCH_LIBRARY+m.def，
        不认算子名、不耦合具体参考样例。摘要覆盖不了的细节，agent 仍可定向读对应
        ``ref_*.cpp``（不再是整读）。
        """
        rc = getattr(state, "reference_code", None)
        if not rc:
            return None
        files = sorted(str(k) for k in rc.keys())
        if not files:
            return None
        lines = [
            "## 参考算子脚手架契约摘要（替代整读参考算子）",
            "目标仓已提供单个干净参考算子代码（staging/ref_*）；以下是其脚手架契约摘要，",
            "**无需整读全部 ref_*.cpp** —— 仅当本摘要未覆盖的细节（如某宏完整签名）",
            "才定向读对应文件。文件布局/注册模式以摘要为准，照抄结构即可。",
        ]
        # 1) 文件布局
        lines.append("- 文件布局: " + ", ".join(
            f"`{f.rsplit('/', 1)[-1]}`" for f in files))
        # 2) CMakeLists 注册/glob 模式（若有）
        for f in files:
            if "CMakeLists" in f and isinstance(rc[f], str):
                key_lines = [
                    l.strip() for l in rc[f].splitlines()
                    if re.search(r"register|GLOB|add_subdirectory|op_kernel|_common", l)]
                if key_lines:
                    lines.append("- CMakeLists 关键模式（注册/glob）:")
                    for l in key_lines[:10]:
                        lines.append(f"  `{l[:150]}`")
                break
        # 3) plugin TORCH_LIBRARY + m.def 注册（若有）
        for f in files:
            if f.endswith("_plugin.cpp") and isinstance(rc[f], str):
                src = rc[f]
                tl = re.search(
                    r"TORCH_LIBRARY_FRAGMENT\s*\(\s*([A-Za-z_]\w*)\s*,", src)
                mdef = re.search(r'm\.def\s*\(\s*"([^"]+)"', src, re.DOTALL)
                if tl:
                    lines.append(f"- TORCH_LIBRARY 注册: namespace=`{tl.group(1)}`")
                if mdef:
                    lines.append(f"- m.def 签名: `{mdef.group(1)[:220]}`")
                break
        out = "\n".join(lines)
        return out if len(out) <= 5000 else out[:5000] + "\n...（摘要截断）"

    def _emit_domain_gap_signal(self, state: State, staging_dir: Path) -> None:
        """域对质安全网（非 halt）：requirement(golden) 域 ⊆ design.support_domain。

        docs/plan/design-math-claims-verification（D2/C1）。缺口 → Logger.warn +
        写 ``domain_gap_signal.json`` 到 staging（结构化信号，下游 codegen agent /
        debug / eval 可读），**不 halt**（no-halt 哲学：问题显式携带，安全网不阻断）。
        缺 requirement/design 域声明 → 跳过（不假阳性）；任何异常 → WARN 留可观测信号
        后跳过（安全网绝不因它崩 codegen，但引擎 bug 不静默失效，§1.2 可诊断）。
        """
        from ascendc_devkit.infra.logger import Logger
        try:
            import json
            from ascendc_devkit.domain.support_domain import (
                design_support_domain, domain_covers, requirement_domain,
            )
            req_path = staging_dir / "requirement.json"
            if not req_path.exists():
                return
            req = json.loads(req_path.read_text(encoding="utf-8"))
            gaps = domain_covers(
                requirement_domain(req),
                design_support_domain(state.design_spec or {}),
            )
            if not gaps:
                return
            Logger.warn(
                "[codegen domain-gap] design.support_domain 未覆盖 requirement(golden) 域：\n"
                + "\n".join(f"  - {g}" for g in gaps)
                + "\n按 no-halt 哲学继续；缺口写入 domain_gap_signal.json，由 debug/eval 兜底。")
            (staging_dir / "domain_gap_signal.json").write_text(
                json.dumps({"gaps": gaps, "source": "codegen domain-gap safety net"},
                           ensure_ascii=False, indent=1),
                encoding="utf-8")
        except Exception as e:  # noqa: BLE001 — 安全网绝不崩 codegen
            Logger.warn(f"[codegen domain-gap] 域对质安全网异常，跳过（不阻断）：{e!r}", exc_info=True)



# —— 设计标量点契约（§step-93 腿1 框架消费端）——————————————————————————————
# 纯函数：判据是声明集合包含关系 + 簿记一致性（结构信号），不做 C++ 语义解析。
# 违约由 transition 路由到 _plugin_schema_retry 同款定向 retry（共享 build-retry
# 预算 + 耗尽 D4 逃生），给 coder 三选一就地闭环：向量化 / 补引用 / 补证据。

# AR-1 ②③：这两类 usage 免 reference（非数据搬送），但必须登记——presence 簿记
# 依赖逐点清单完整。
_SCALAR_USAGE_EXEMPT = frozenset({"metadata", "index"})
_SCALAR_TOKENS = ("SetValue(", "GetValue(")

def _validate_scalar_contract(declared, decision_log: dict,
                              sources: dict, op_dir=None) -> list[str]:
    """校验 coder 的标量访问点契约，返回逐条违约描述（空 = 通过）。

    - 逐点：data-move 类 entry 的 ``reference`` 必须命中设计声明名
      （tiling_strategy.scalar_access_points[].name），或 ``deviation_evidence``
      三键齐备且 ``repro_or_log`` 指向真实存在的产物路径（相对路径按 op_dir
      解析——簿记级存在性检查，防空口引用）。
    - 簿记：op_kernel/ 源码出现 SetValue/GetValue 而 scalar_access_points 空
      （或非 list）→ 「有标量访问未声明」违约（事故 20260825-ccad38 形态：
      36 处标量访问、清单空、只有 topic 级 rationale）。

    已知边界（L3 范围声明）：指针标量解引用等语法变体不在 presence 捕获范围——
    契约以声明优先，presence 只做簿记一致性。
    """
    violations: list[str] = []
    declared_names = set(declared or [])

    raw = (decision_log or {}).get("scalar_access_points")
    entries = raw if isinstance(raw, list) else None
    if entries is None:
        entries = []
        if raw is not None:
            violations.append(
                "[scalar-contract] scalar_access_points 非 list"
                f"（{type(raw).__name__}）——按未声明处理")

    def _evidence_ok(ev) -> bool:
        if not isinstance(ev, dict):
            return False
        if not all(isinstance(ev.get(k), str) and ev.get(k).strip() for k in (
                "failure_signature", "repro_or_log",
                "why_no_vector_equivalent")):
            return False
        ref = ev.get("repro_or_log", "")
        p = Path(ref)
        if not p.is_absolute() and op_dir is not None:
            p = Path(op_dir) / ref
        return p.exists()

    for e in entries:
        if not isinstance(e, dict):
            violations.append(
                f"[scalar-contract] scalar_access_points 条目非 object：{e!r}")
            continue
        loc = str(e.get("location") or "?")
        if str(e.get("usage") or "") in _SCALAR_USAGE_EXEMPT:
            continue  # AR-1 ②③：元数据/纯索引免 reference
        if str(e.get("reference") or "") in declared_names:
            continue
        ev = e.get("deviation_evidence")
        if isinstance(ev, dict) and ev:
            if not _evidence_ok(ev):
                ref = ev.get("repro_or_log", "")
                violations.append(
                    f"[scalar-contract] {loc}: deviation_evidence 不完整或"
                    f" repro_or_log 不存在（{ref!r}）——三键齐备且引用真实"
                    f"产物路径")
            continue
        violations.append(
            f"[scalar-contract] {loc}: 标量数据搬送未获授权——reference 未命中"
            f" 设计声明 {sorted(declared_names)}，也无 deviation_evidence。"
            f"三选一：向量化（有 DataCopy 等价物时理由不成立）/ 补 reference"
            f"（设计声明的 name）/ 补 deviation_evidence")

    # 簿记覆盖：op_kernel/ 源码 presence（agent_result.artifacts 为全量内存态，
    # 无 prompt 注入的截断问题）
    hits = 0
    for rel, content in (sources or {}).items():
        if not isinstance(rel, str) or not rel.startswith("op_kernel/"):
            continue
        if not isinstance(content, str):
            continue
        hits += sum(content.count(t) for t in _SCALAR_TOKENS)
    if hits > 0 and not entries:
        violations.append(
            f"[scalar-contract] op_kernel/ 源码含 {hits} 处 SetValue/GetValue 而"
            f" scalar_access_points 清单为空——逐使用点登记（usage 注明 "
            f"metadata/index/data-move；data-move 类必须 reference 设计声明或"
            f" 携带 deviation_evidence）")

    return violations