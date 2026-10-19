"""UT: codegen 产物落点正确性 — working_dir 兜底 + _persist_sources 防累积嵌套。

背景（run output/20260710-140056-ba16cd 实证）：new 模式 op_identity 恒为 None，
codegen.actions() 用 op_identity.op_dir 取 working_dir 且无 state.op_dir 兜底
→ cwd 退化到 SDKBackend 实例默认 workspace.artifacts → 产物收集扫整棵 artifacts 树；
而 _persist_sources 又把镜像写进 artifacts/codegen/（在收集根内）→ 每次 codegen 再跑
重扫上一轮镜像的 codegen/ 子树，key 累积 codegen/ 前缀 → 物理目录 codegen/codegen/...。

锁两件事：
  ① op_identity=None（new 模式）时 SpawnAgent.working_dir == state.op_dir（根因），
     对齐 deploy.py / cannbench_adapt.py 的 `state.op_dir or op_identity.op_dir` 写法；
  ② _persist_sources 对带 codegen/ 前缀的 key（重扫伪源）归一化、不产生 codegen/codegen/
     （纵深防御：即便 cwd 再误落 artifacts 也不累积）。
"""

from pathlib import Path

from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.codegen import CodegenStage
from ascendc_devkit.infra.workspace import Workspace


class TestCodegenWorkingDirFallback:
    """new 模式 op_identity=None，working_dir 必须兜底到 state.op_dir，不能是 None
    (None 会让 backend 退化到 workspace.artifacts 当 cwd —— 嵌套 bug 的根因)。"""

    def test_new_mode_uses_state_op_dir_when_op_identity_none(self, tmp_path):
        stage = CodegenStage()
        op_dir = tmp_path / "repo" / "ops" / "rms_norm"
        state = State(mode="new", op_dir=op_dir)  # op_identity 默认 None（new 模式）
        actions = stage.actions(state, 1)
        assert len(actions) == 1
        assert actions[0].working_dir == op_dir, (
            "new 模式 op_identity=None 时 working_dir 必须兜底到 state.op_dir；"
            "否则 cwd 退化到 workspace.artifacts → 收集扫整棵 artifacts 树 → 嵌套")


class TestCodegenPersistSourcesNoNesting:
    """_persist_sources 镜像 generated_sources 到 artifacts/codegen/。即便 key 因
    cwd 误落 artifacts 被重扫而带上 codegen/ 前缀（伪源），persist 也必须归一化、
    绝不写出 codegen/codegen/ 嵌套（锁死反馈环）。"""

    def test_strips_codegen_prefix_no_nesting(self, tmp_path):
        ws = Workspace.create(output_root=str(tmp_path))
        stage = CodegenStage()
        state = State(mode="new", _workspace=ws)
        # 模拟重扫产物：key 带 0/1/2 层 codegen 前缀（收集根含 persist 目标的反馈特征）
        sources = {
            "staging/changed_files.json": "depth0",
            "codegen/staging/changed_files.json": "depth1",
            "codegen/codegen/staging/changed_files.json": "depth2",
        }
        stage._persist_sources(state, sources)
        dest = ws.artifacts / "codegen"
        # 归一化后所有 key 落到同一处（深度 0）
        assert (dest / "staging" / "changed_files.json").exists()
        # 绝不产生嵌套 —— 任何 codegen/codegen/ 都是反馈环未断的信号
        assert not (dest / "codegen").exists(), (
            "_persist_sources 写出了 codegen/codegen/ —— 键归一化缺失，反馈环未断")


class TestContractFileRouting:
    """step-109：契约元数据（CONTRACT_FILES）落盘路由 _contract/——源码平铺、
    元数据独立子目录；顶层精确匹配（带目录的同名文件不误伤）。"""

    def test_contract_files_routed_to_contract_dir(self, tmp_path):
        ws = Workspace.create(output_root=str(tmp_path))
        stage = CodegenStage()
        state = State(mode="new", _workspace=ws)
        sources = {
            "op_kernel/k.cpp": "src",
            "codegen_manifest.json": '{"m": 1}',
            "decision_log.json": '{"d": 1}',
            "changed_files.json": '{"c": 1}',
            "staging/changed_files.json": "nested",  # 带目录 → 非顶层 → 不路由
        }
        stage._persist_sources(state, sources)
        dest = ws.artifacts / "codegen"
        # 源码平铺照旧
        assert (dest / "op_kernel" / "k.cpp").exists()
        # 三个契约文件 → _contract/，顶层不再混放
        assert (dest / "_contract" / "codegen_manifest.json").exists()
        assert (dest / "_contract" / "decision_log.json").exists()
        assert (dest / "_contract" / "changed_files.json").exists()
        assert not (dest / "codegen_manifest.json").exists()
        assert not (dest / "decision_log.json").exists()
        assert not (dest / "changed_files.json").exists()
        # 顶层精确匹配：带目录的同名文件不误伤（仍按原路径落）
        assert (dest / "staging" / "changed_files.json").exists()


class TestPromptSelfReportTeachingRemoved:
    """step-109：自报填表教学已删（§1.14 git 真值，不让模型填表）——源级守护
    防教学字符串回潮。保留的 git diff --name-only 自验句不在禁用面内。"""

    def test_codegen_prompt_no_self_report_teaching(self):
        import inspect
        from ascendc_devkit.orchestration.stages import codegen
        src = inspect.getsource(codegen)
        assert "必须在当前工作目录写" not in src, (
            "codegen prompt 残留自报填表教学（写 changed_files.json）")
        assert "核对 changed_files.json 完整性" not in src

    def test_perf_prompt_no_self_report_teaching(self):
        import inspect
        from ascendc_devkit.orchestration.stages import perf
        src = inspect.getsource(perf)
        assert "更新工作目录下的 changed_files.json" not in src, (
            "perf prompt 残留自报填表教学")
