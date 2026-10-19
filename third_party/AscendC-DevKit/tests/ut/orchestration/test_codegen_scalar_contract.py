"""step-93 改动3 — scalar 契约机械校验（设计标量点契约的框架消费端）。

腿1（docs/plan/codegen-design-faithfulness-contract/）：coder 的每个标量数据
搬送点必须引用设计声明（tiling_strategy.scalar_access_points[].name）或携带
完整 deviation 证据（含可存在的复现引用）；源码 op_kernel/ 有 SetValue/GetValue
而清单空 = 簿记违约。违约 → 定向 retry（共享 build-retry 预算 + 耗尽 D4 逃生），
不 halt。判据是声明集合包含关系 + 簿记一致性（结构信号），不做 C++ 语义解析。
"""

import json

from ascendc_devkit.orchestration.stages.codegen_stage_mixin.contract import (
    _validate_scalar_contract,
)

DECLARED = ["scatter_position", "prev_key_carry"]


def _entry(**kw):
    base = {
        "location": "op_kernel/unique.h:291",
        "usage": "data-move",
        "reason": "数据依赖散射",
    }
    base.update(kw)
    return base


def _sources(hits: int, path: str = "op_kernel/unique.h") -> dict:
    body = "// kernel\n"
    if hits:
        body += "auto v = gmX.GetValue(i);\n" * hits
        body += "gmY.SetValue(j, v);\n"
    return {path: body}


class TestPointwiseReference:
    def test_reference_hit_passes(self):
        dlog = {"scalar_access_points": [_entry(reference="scatter_position")]}
        assert _validate_scalar_contract(
            DECLARED, dlog, _sources(1), None) == []

    def test_reference_miss_without_evidence_violates(self):
        dlog = {"scalar_access_points": [_entry(reference="nonexistent")]}
        v = _validate_scalar_contract(DECLARED, dlog, _sources(1), None)
        assert len(v) == 1 and "unique.h:291" in v[0]

    def test_metadata_and_index_usage_exempt_from_reference(self):
        """AR-1 ②③：TilingData 元数据 / 纯索引计算免 reference——但必须登记
        （usage 分类），presence 簿记才能精确。"""
        dlog = {"scalar_access_points": [
            _entry(usage="metadata", location="op_kernel/unique.h:10"),
            _entry(usage="index", location="op_kernel/unique.h:20")]}
        assert _validate_scalar_contract(
            DECLARED, dlog, _sources(2), None) == []


class TestDeviationEvidence:
    def _evidence(self, tmp_path, **kw):
        rep = tmp_path / "sync_race.log"
        rep.write_text("ERROR stale keys", encoding="utf-8")
        ev = {
            "failure_signature": "507035 vector core exception",
            "repro_or_log": str(rep),
            "why_no_vector_equivalent":
                "散射目标地址逐元素数据依赖，无 Gather 等价形态",
        }
        ev.update(kw)
        return _entry(deviation_evidence=ev)

    def test_complete_evidence_passes(self, tmp_path):
        dlog = {"scalar_access_points": [self._evidence(tmp_path)]}
        assert _validate_scalar_contract(
            DECLARED, dlog, _sources(1), None) == []

    def test_missing_repro_path_violates(self, tmp_path):
        entry = self._evidence(
            tmp_path, repro_or_log=str(tmp_path / "nope.log"))
        dlog = {"scalar_access_points": [entry]}
        v = _validate_scalar_contract(DECLARED, dlog, _sources(1), None)
        assert len(v) == 1 and "nope.log" in v[0]

    def test_relative_repro_resolved_against_op_dir(self, tmp_path):
        (tmp_path / "logs").mkdir()
        (tmp_path / "logs" / "r.log").write_text("x", encoding="utf-8")
        entry = self._evidence(tmp_path, repro_or_log="logs/r.log")
        dlog = {"scalar_access_points": [entry]}
        assert _validate_scalar_contract(
            DECLARED, dlog, _sources(1), tmp_path) == []

    def test_incomplete_evidence_violates(self, tmp_path):
        entry = self._evidence(tmp_path)
        del entry["deviation_evidence"]["why_no_vector_equivalent"]
        dlog = {"scalar_access_points": [entry]}
        assert len(_validate_scalar_contract(
            DECLARED, dlog, _sources(1), None)) == 1


class TestBookkeepingPresence:
    def test_undeclared_presence_violates(self):
        """源码 op_kernel/ 有标量访问而清单空 → 簿记违约（事故形态：
        36 处标量访问、scalar_access_points 为空、只有 topic 级 rationale）。"""
        v = _validate_scalar_contract(
            DECLARED, {"scalar_access_points": []}, _sources(3), None)
        assert len(v) == 1 and "scalar_access_points" in v[0]

    def test_clean_sources_empty_list_passes(self):
        assert _validate_scalar_contract(
            DECLARED, {"scalar_access_points": []}, _sources(0), None) == []

    def test_non_kernel_sources_not_scanned(self):
        srcs = _sources(3, path="op_host/unique_tiling.cpp")
        assert _validate_scalar_contract(
            DECLARED, {"scalar_access_points": []}, srcs, None) == []

    def test_malformed_list_treated_as_absent(self):
        v = _validate_scalar_contract(
            DECLARED, {"scalar_access_points": "garbage"}, _sources(1), None)
        # 两条都是真信号：形态违约 + 簿记覆盖（源码有访问而清单不可用）
        assert len(v) == 2
        assert any("非 list" in x for x in v)
        assert any("清单为空" in x for x in v)

    def test_non_dict_entry_violates(self):
        dlog = {"scalar_access_points": ["not-a-dict"]}
        v = _validate_scalar_contract(DECLARED, dlog, _sources(1), None)
        assert any("not-a-dict" in x for x in v)


class TestTransitionRouting:
    def test_violation_routes_to_targeted_retry_not_deploy(self):
        """transition 级：违约 → _plugin_schema_retry 同款定向 retry（共享
        build-retry 预算 + D4 逃生），不写 deploy_result、不 halt；反馈 kind
        = scalar_contract，含逐条违约与三选一修复指引。"""
        from unittest.mock import patch
        from ascendc_devkit.domain.operator import OperatorSpec
        from ascendc_devkit.domain.requirement import Requirement
        from ascendc_devkit.domain.repository import (
            RepositoryProfile, Scaffolding)
        from ascendc_devkit.capabilities.agent.backend import AgentResult
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.orchestration.stages.codegen import CodegenStage

        deployed: list = []

        class _FakeDeployer:
            def deploy(self, state):
                deployed.append(1)
                from ascendc_devkit.domain.verification import DeployResult
                return DeployResult(smoke_passed=True), None

        manifest = {
            "op_name": "unique", "op_pascal": "Unique",
            "callable_target": {
                "kind": "torch_op", "symbol": "torch.ops.cann_bench.unique"},
        }
        plugin = ('TORCH_LIBRARY_FRAGMENT(cann_bench, m) {\n'
                  '    m.def("unique(Tensor x) -> Tensor");\n'
                  '}\n')
        # 事故形态复刻：源码有标量访问、decision_log 无逐点清单
        kernel = ("// kernel\n"
                  "for (int i = 0; i < n; ++i) {\n"
                  "    gmY.SetValue(i, gmX.GetValue(i));\n"
                  "}\n")
        agent_result = AgentResult(
            agent_name="ascendc-coder", status="ok", artifacts={
                "codegen_manifest.json": json.dumps(manifest),
                "op_kernel/unique_kernel.cpp": kernel,
                "op_host/unique_def.cpp": "// host\n",
                "op_plugin/unique_plugin.cpp": plugin,
                "decision_log.json": json.dumps({
                    "key_decisions": [{"decision": "d", "reason": "r",
                                       "constraints": []}],
                    "known_issues": [], "assumptions": []}),
            })

        with patch("ascendc_devkit.orchestration.stages.deploy.Deployer",
                   _FakeDeployer):
            stage = CodegenStage()
            state = State(
                mode="new",
                profile=RepositoryProfile(
                    name="omni-ops",
                    scaffolding=Scaffolding(
                        supported=("torch_op",), selected="torch_op")),
                requirement=Requirement(
                    op_spec=OperatorSpec(name="unique")),
                design_target_chip="A2",
                tiling_strategy={"scalar_access_points": [
                    {"name": "scatter_position",
                     "location_semantic": "阶段2 散射",
                     "reason": "目标地址逐元素数据依赖",
                     "derivation": "R6 排除：偏移矩阵非常数",
                     "verification": "derived"}]},
                decision_logs={},
                codegen_iterations=0,
            )
            out = stage.transition(state, {"agent_result": agent_result})

        assert deployed == [], "违约必须拦在 deploy 之前"
        fb = out.codegen_build_feedback
        assert fb is not None and fb.get("kind") == "scalar_contract"
        assert fb.get("violations"), "反馈须含逐条违约"
        assert out.deploy_result is None, "retry 路径不写 deploy_result"
        assert out.last_error is None, "定向 retry 不进 halt 通道"
