"""P3 heavy_llm ST — diagnose 两段闭环就地定位能力（降级形态，本仓自闭环）。

场景：一个「Cast 用错 RoundMode」的 kernel 精度缺陷。run_tests 已跑完（result.json
报告失败），diagnose 被 spawn：读失败用例 → 就地定位（比对 golden 找发散点 + 查 API
约束）→ 就地修那一处（Edit→build→单用例验证→commit/rollback）→ 写 case.status。

**降级形态**（不依赖外部算子仓 / 真实 NPU / 真实编译）：
- kernel 是 seed 的最小源码；build/test 是 stub 脚本（确定性：kernel 含修复信号即通过）
- 验证的是 **diagnose 的就地定位 + 修复能力**（P3 减法核心），不是真实编译链路
- 框架 prompt 用真实 `DiagnoseSubstage._phase_prompt` 生成（复用生产契约）

**P3 减法断言**：diagnose 不生成 candidate_pool / 不写 route_to / 不枚举错误类型——
产物 `precision_diagnose.json` 只含 `_summary` + `fix_code_log`，不含旧机制字段。
（§1.14/§2.5：控模型结构已删，诊断产物不应回退。）

Heavy by nature（真实 LLM spawn）→ marked heavy_llm per §3.11。
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from tests._llm_env import has_anthropic as _has_llm, load_settings_env

load_settings_env()

_SKILL = "ascendc-precision-diagnose"
_AGENT = "ascendc-precision-diagnose"
_FIX_SIGNAL = "CAST_RINT"   # kernel 修复信号：改用正确 RoundMode
_BUG_MARK = "CAST_NONE"     # seed 缺陷：用错 RoundMode
# §3.10：真实 LLM 闭环用例的判据=有界重试内至少一次完整闭环（非每次都服从）。
# 仅吸收 LLM 行为段（spawn 返回/产物/修复/标注）的抖动；确定性断言保持硬断言
# （失败即测试失败，不进重试吸收）。同 design_tui_selfclosure 先例。
_MAX_ATTEMPTS = 3


# ── seed 场景构造 ─────────────────────────────────────────────────────────────

def _seed(op_dir: Path, artifacts: Path) -> None:
    """构造最小缺陷 kernel + golden + 预置 run_tests 失败产物。"""
    op_dir.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "phases" / "run_tests").mkdir(parents=True, exist_ok=True)
    (artifacts / "phases" / "diagnose").mkdir(parents=True, exist_ok=True)

    # 缺陷 kernel：Cast 用错 RoundMode（CAST_NONE 静默留垃圾，应为 CAST_RINT）
    (op_dir / "kernel.cpp").write_text(
        "// round 取整算子\n"
        "void round_kernel(Tensor<float> in, Tensor<float> out) {\n"
        f"  Cast(in, out, RoundMode::{_BUG_MARK});  // BUG: 应 CAST_RINT\n"
        "}\n",
        encoding="utf-8")

    # golden：round 到最近整数
    (op_dir / "golden.py").write_text(
        "import numpy as np\n"
        "def golden(inp):\n"
        "    return np.round(inp.astype(np.float32))\n",
        encoding="utf-8")

    # stub build：kernel 无语法标记即过
    (op_dir / "stub_build.py").write_text(
        "import pathlib\n"
        "src = pathlib.Path('kernel.cpp').read_text()\n"
        "assert '// SYNTAX_ERR' not in src, 'syntax error'\n"
        "print('BUILD_OK')\n",
        encoding="utf-8")

    # stub test：kernel 代码行含修复信号 → passed，否则 failing（--case 同理）
    # 精确匹配 RoundMode::CAST_RINT（避免注释里提到修复方案骗过判定）
    (op_dir / "stub_test.py").write_text(
        "import json, pathlib, sys\n"
        "src = pathlib.Path('kernel.cpp').read_text()\n"
        "case_id = sys.argv[sys.argv.index('--case')+1] if '--case' in sys.argv else 'c1'\n"
        f"passed = 'RoundMode::{_FIX_SIGNAL}' in src\n"
        "detail = {'case_id': case_id, 'shape': '[16]', 'dtype': 'fp32',\n"
        "          'accuracy': {'passed': passed,\n"
        "                       'max_diff': 0.0 if passed else 0.5},\n"
        "          'output_results': [{'index': 0, 'passed': passed}]}\n"
        "json.dump({'case_details': [detail]}, open('result.json', 'w'))\n"
        "print('TEST_OK' if passed else 'TEST_FAIL')\n"
        "sys.exit(0 if passed else 1)\n",
        encoding="utf-8")

    # 预置 run_tests 失败产物：control.json + result.json + precision_run_tests.json
    (artifacts / "control.json").write_text(json.dumps({
        "status": "running",
        "max_iterations": 15,
        "max_attempts_per_case": 8,
        "time_budget_sec": 36000,
        "current_case_index": 0,
        "failed_case_queue": [
            {"case_id": "c1", "shape": "[16]", "dtype": "fp32",
             "failure_type": "precision", "max_err": 0.5,
             "attempt_count": 0, "status": "pending",
             "outputs": [{"index": 0, "diff": 0.5, "status": "failing"}]},
        ],
        "history": [{
            "phase": "run_tests",
            "content": {"failure_type": "precision", "failed_count": 1,
                        "total_count": 1, "max_err": 0.5, "test_result": "partial"},
        }],
        "upstream_signal": False,
        "upstream_stage": None,
        "upstream_reason": None,
        "phase_counter": 0,
        "run_iter_counter": 0,
        "consecutive_aborts": 0,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    (artifacts / "result.json").write_text(json.dumps({
        "case_details": [{
            "case_id": "c1", "shape": "[16]", "dtype": "fp32",
            "accuracy": {"passed": False, "max_diff": 0.5},
            "output_results": [{"index": 0, "passed": False}],
        }],
    }), encoding="utf-8")

    (artifacts / "phases" / "run_tests" / "precision_run_tests.json").write_text(
        json.dumps({
            "last_result_json": str(artifacts / "result.json"),
            "last_run_log": str(artifacts / "run.log"),
        }), encoding="utf-8")

    (artifacts / "phases" / "diagnose" / "precision_diagnose.json").write_text(
        json.dumps({"diagnose_done": False, "fix_code_log": {}}), encoding="utf-8")


def _build_diagnose_prompt(op_dir: Path, artifacts: Path) -> str:
    """用真实 DiagnoseSubstage._phase_prompt 构造 diagnose prompt（复用生产契约）。"""
    from ascendc_devkit.orchestration.stages.precision_debug_substages import DiagnoseSubstage
    phase_json = artifacts / "phases" / "diagnose" / "precision_diagnose.json"
    ctx = {
        "op_name": "round_kernel",
        "build_command": f"python3 {op_dir / 'stub_build.py'}",
        "test_command": f"python3 {op_dir / 'stub_test.py'}",
        "iter_n": 0,
    }
    return DiagnoseSubstage()._phase_prompt(
        ctx, str(op_dir), str(artifacts / "control.json"),
        str(phase_json), str(Path(__file__).resolve().parents[2] / ".claude" / "skills"
                             / _SKILL), 1)


def _spawn(op_dir: Path, artifacts: Path) -> None:
    from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
    from ascendc_devkit.orchestration.skill_config import skill_allowlist
    prompt = _build_diagnose_prompt(op_dir, artifacts)
    backend = SDKBackend(interactive=False, working_dir=op_dir.parent,
                         on_decision="default", decision_workspace=op_dir)
    backend.spawn(_AGENT, prompt, {},
                  skills=skill_allowlist(_SKILL),
                  working_dir=op_dir, stage_name="tui")


def _read_diagnose_product(artifacts: Path) -> dict:
    """解析 diagnose 产物：latest 有 _summary 用 latest，否则回退最新 round 文件。

    生产契约：agent 写 round-suffix（precision_diagnose.round1.json），latest
    （precision_diagnose.json）由框架 transition 的 _sync_phase_latest 拷贝——
    本 ST 只 spawn 不跑 transition，latest 停留在 seed 占位，须读 round 产物
    （heavy 实证 2026-08-25：agent 写全 round1.json，latest 仍占位）。"""
    latest = artifacts / "phases" / "diagnose" / "precision_diagnose.json"
    if latest.exists():
        try:
            data = json.loads(latest.read_text(encoding="utf-8"))
            if data.get("_summary"):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    rounds = sorted((artifacts / "phases" / "diagnose")
                    .glob("precision_diagnose.round*.json"))
    assert rounds, "diagnose 未写任何产物（latest 占位且无 round 文件）"
    return json.loads(rounds[-1].read_text(encoding="utf-8"))


@pytest.mark.llm
@pytest.mark.heavy_llm
class TestPrecisionDiagnoseInplaceLoop:
    """P3 两段闭环：diagnose 就地定位 + 修复（不枚举、不产候选池、不 route_to）。"""

    def test_diagnose_locates_and_fixes_cast_roundmode(self, tmp_path):
        if not _has_llm():
            pytest.skip("no LLM creds — real diagnose link unavailable (§3.7)")
        # §3.10 有界重试：全部断言都是 LLM 行为产物（软收集驱动重试），每次
        # attempt 用全新 seed 现场（脏现场残留产物会让重试断言失真）。
        attempts_diag: list[str] = []
        for attempt in range(_MAX_ATTEMPTS):
            run = tmp_path / f"run{attempt}"
            op_dir = run / "op"
            artifacts = run / "debug"
            _seed(op_dir, artifacts)
            _spawn(op_dir, artifacts)

            try:
                # —— 断言 diagnose 就地闭环（LLM 产物：软收集）——
                diag = _read_diagnose_product(artifacts)
                summary = diag.get("_summary") or {}
                fix_log = diag.get("fix_code_log") or {}
                shortfall: list[str] = []

                # 1. 就地定位：root_cause 指向 Cast/RoundMode 缺陷
                root = str(summary.get("root_cause") or "")
                if not any(k in root for k in ("Cast", "cast", "RoundMode", "round",
                                               "CAST_NONE", "CAST_RINT")):
                    shortfall.append(f"root_cause 未指向缺陷: {root!r}")

                # 2. 就地修复：fix_code_log 有 applied_fix 且验证通过
                # verification_result 契约见 schema：'confirmed' / null / 非空验证
                # 证据字符串（build/test 命令与结果——heavy 实证 agent 常写详式，
                # 可诊断性更好，§1.2）。框架不消费该字段，仅记录；带通过信号即算
                # 验证通过。
                applied = str(fix_log.get("applied_fix") or "")
                if not applied:
                    shortfall.append("diagnose 未产出 applied_fix（应就地修那一处）")
                vr = fix_log.get("verification_result")
                vr_s = str(vr or "").lower()
                if not (vr and ("confirmed" in vr_s or "passed=true" in vr_s
                                or "test_ok" in vr_s or "pass" in vr_s)):
                    shortfall.append(f"verification_result 应含验证通过信号: {vr!r}")

                # 3. kernel 真的被修：CAST_NONE → CAST_RINT
                # 代码形锚定（同 stub_test 先例）：种子注释 "// BUG: 应 CAST_RINT"
                # 含裸子串可骗过修复信号；agent 修复后的解释性注释提及旧值亦不
                # 该算残留。
                kernel = (op_dir / "kernel.cpp").read_text(encoding="utf-8")
                if f"RoundMode::{_FIX_SIGNAL}" not in kernel:
                    shortfall.append("kernel 未被修到正确 RoundMode")
                if f"RoundMode::{_BUG_MARK}" in kernel:
                    shortfall.append("kernel 仍含 BUG 调用")

                # 4. 框架路由：case 标记 resolved_pending → run_tests 回归
                cp = json.loads((artifacts / "control.json").read_text(
                    encoding="utf-8"))
                case = (cp.get("failed_case_queue") or [{}])[0]
                if case.get("status") != "resolved_pending":
                    shortfall.append(
                        f"case 应标 resolved_pending（转 run_tests 全量回归）: "
                        f"{case.get('status')!r}")

                # 5. P3 减法：诊断产物不含旧控模型字段
                for legacy in ("candidate_pool", "route_to", "arch_gaps",
                               "bounds_check_result", "printf_location_result"):
                    if legacy in diag:
                        shortfall.append(f"P3 减法后 diagnose 产物不应含 {legacy}")
            except Exception as e:  # noqa: BLE001 — 产物缺失/畸形 = 本轮未闭环，进重试诊断
                shortfall = [f"产物读取异常: {e!r}"]

            if not shortfall:
                return  # 闭环完整达成（§3.10：有界重试内至少一次）
            attempts_diag.append(f"attempt {attempt}: {'; '.join(shortfall)}")
            print(f"[inplace-loop] attempt {attempt}: 未全过 → 重试\n  {shortfall}")
        pytest.fail(
            f"diagnose 就地闭环在 {_MAX_ATTEMPTS} 次有界重试内未完整达成:\n  "
            + "\n  ".join(attempts_diag))


# ── N1 全闭环：RunMeasure 纯 Python 测量 → 路由 diagnose → LLM 修复 → 复测 ─——
# 与 TestPrecisionDiagnoseInplaceLoop 同场景族（同缺陷/同 stub 模式），但走完整
# 框架契约：RunTestsSubstage.actions → RunMeasure（真实 subprocess）→ transition
# → resolve_condition 路由 → diagnose 真实 LLM spawn → 复测 all_pass。验证：
# 1) run_tests 不再 spawn agent（测量确定性）；2) agent 用工具提效（Edit 修
# kernel + Bash 单用例验证，从 transcript JSONL 取证，§1.11 实际产出为证）。


def _seed_full_loop(tmp_path: Path, ws_root: Path) -> Path:
    """N1 全闭环 seed：git 化 op_dir + 缺陷 kernel + stub 脚本 + 空 phase 目录。

    与 _seed 的差异：
    - 不预置 control.json / result.json —— 由 RunMeasure 前置 init-checkpoint.py
      确定性创建（框架首测链路，非预置产物）。
    - op_dir 是 git 仓（_entry_commit_codegen 需要）。
    - stub_test 全量模式（--iter N）镜像 run-cases CLI 语义：**失败用例也
      exit 0**（失败记进 result.json；仅基础设施错误才非零——RunMeasure 的
      rc!=0 abort 判据只捕 infra 失败，测试失败走 result.json→queue→diagnose）。
      result.json 落 $PD_ARTIFACTS/run_tests_iter-N/（RunMeasure 命令消费的
      确定性路径约定）；单用例模式（--case）写 CWD（diagnose 消费）。

    Returns the framework debug artifacts dir ({ws_root}/artifacts/debug/<op>).
    """
    import subprocess as sp
    op_dir = tmp_path / "op"
    op_dir.mkdir(parents=True, exist_ok=True)

    def g(*a):
        sp.run(["git", "-C", str(op_dir), *a], capture_output=True, check=True)
    g("init", "-q")
    g("config", "user.email", "t@t.t")
    g("config", "user.name", "T")

    (op_dir / "kernel.cpp").write_text(
        "// round 取整算子\n"
        "void round_kernel(Tensor<float> in, Tensor<float> out) {\n"
        f"  Cast(in, out, RoundMode::{_BUG_MARK});  // BUG: 应 CAST_RINT\n"
        "}\n", encoding="utf-8")
    (op_dir / "golden.py").write_text(
        "import numpy as np\n"
        "def golden(inp):\n"
        "    return np.round(inp.astype(np.float32))\n", encoding="utf-8")
    (op_dir / "stub_build.py").write_text(
        "import json, os, pathlib\n"
        "src = pathlib.Path('kernel.cpp').read_text()\n"
        "assert '// SYNTAX_ERR' not in src, 'syntax error'\n"
        "# 镜像 DebugService.redeploy 契约（§step-89 deploy-precondition）：build 后\n"
        "# 无条件落盘 last_deploy.json（含可用路径字段——precondition 的判据）。\n"
        "dbg = pathlib.Path(os.environ.get('PD_ARTIFACTS', '.'))\n"
        "dbg.mkdir(parents=True, exist_ok=True)\n"
        "(dbg / 'last_deploy.json').write_text(json.dumps({\n"
        "    'install_path': str(dbg / 'opp'), 'python_path': str(dbg / 'python'),\n"
        "    'smoke_passed': True}))\n"
        "print('BUILD_OK')\n", encoding="utf-8")
    # 全量模式 exit 0 镜像 run-cases（失败进 result.json，不进退出码）；
    # 单用例模式保持 exit 1 语义（diagnose 读输出 + 退出码判断单点验证）。
    (op_dir / "stub_test.py").write_text(
        "import json, os, pathlib, sys\n"
        "src = pathlib.Path('kernel.cpp').read_text()\n"
        f"passed = 'RoundMode::{_FIX_SIGNAL}' in src\n"
        "case_id = (sys.argv[sys.argv.index('--case')+1]\n"
        "           if '--case' in sys.argv else 'c1')\n"
        "detail = {'case_id': case_id, 'shape': '[16]', 'dtype': 'fp32',\n"
        "          'accuracy': {'passed': passed,\n"
        "                       'max_diff': 0.0 if passed else 0.5},\n"
        "          'output_results': [{'index': 0, 'passed': passed}]}\n"
        "payload = {'case_details': [detail]}\n"
        "if '--iter' in sys.argv:\n"
        "    n = sys.argv[sys.argv.index('--iter')+1]\n"
        "    out_dir = pathlib.Path(os.environ.get('PD_ARTIFACTS', '.')) / f'run_tests_iter-{n}'\n"
        "    out_dir.mkdir(parents=True, exist_ok=True)\n"
        "    json.dump(payload, open(out_dir / 'result.json', 'w'))\n"
        "    print('TEST_OK' if passed else 'TEST_FAIL')\n"
        "    sys.exit(0)  # run-cases 语义：失败用例不进退出码\n"
        "json.dump(payload, open('result.json', 'w'))\n"
        "print('TEST_OK' if passed else 'TEST_FAIL')\n"
        "sys.exit(0 if passed else 1)\n", encoding="utf-8")
    g("add", "-A")
    g("commit", "-q", "-m", "seed")

    dbg = ws_root / "artifacts" / "debug" / "round_kernel"
    (dbg / "phases" / "run_tests").mkdir(parents=True, exist_ok=True)
    (dbg / "phases" / "diagnose").mkdir(parents=True, exist_ok=True)
    return dbg


def _full_loop_state(tmp_path: Path, op_dir: Path, ws_root: Path):
    from types import SimpleNamespace
    from ascendc_devkit.domain.operator import OperatorIdentity, OperatorSpec
    from ascendc_devkit.domain.requirement import Requirement
    from ascendc_devkit.domain.verification import DeployResult
    from ascendc_devkit.orchestration.kernel.state import State
    ws = SimpleNamespace(dir=ws_root, artifacts=ws_root / "artifacts")
    return State(
        mode="new",
        op_identity=OperatorIdentity(spec=OperatorSpec(name="round_kernel"),
                                     repo_root=tmp_path, op_dir=op_dir),
        requirement=Requirement(op_spec=OperatorSpec(name="round_kernel")),
        golden_path=op_dir / "golden.py",
        golden_entry="golden",
        golden_input_type="float32",
        deploy_result=DeployResult(smoke_passed=True),
        design_target_chip="A2",
        _workspace=ws,
    )


def _stub_ctx(op_dir: Path) -> dict:
    """Stub measure ctx——替换 _common_context 的 run-cases/redeploy 派生
    （生产派生是 UT 覆盖的 `ascendc-devkit run-cases --workspace`；ST 注入
    stub 命令验证测量/路由/diagnose 契约本身）。"""
    return {
        "op_name": "round_kernel",
        "build_command": f"python3 {op_dir / 'stub_build.py'}",
        "test_command": f"python3 {op_dir / 'stub_test.py'}",
        "precision_max_iterations": 15,
        "precision_max_attempts_per_case": 8,
        "precision_time_budget_sec": 36000,
    }


def _run_measure(m, env_extra: dict | None = None) -> dict:
    """镜像 Runner._execute_run_measure 的 subprocess 执行（shell=True/cwd/rc+tail）。"""
    import subprocess as sp
    import os
    env = {**os.environ, **(env_extra or {})}
    proc = sp.run(m.command, shell=True, capture_output=True, text=True,
                  cwd=m.working_dir, timeout=m.timeout, env=env)
    return {"returncode": proc.returncode,
            "stdout": (proc.stdout or "")[-4000:], "stderr": (proc.stderr or "")[-2000:]}


def _tool_evidence(transcript) -> dict:
    """从 diagnose session transcript JSONL 提取工具使用证据（§1.11 实际产出）。"""
    ev = {"edited_kernel": False, "single_case_verify": False, "built": False,
          "tool_calls": 0, "chars": 0}
    if not transcript or not Path(transcript).exists():
        return ev
    for line in Path(transcript).read_text(encoding="utf-8", errors="replace").splitlines():
        ev["chars"] += len(line)
        if '"name":' not in line and '"tool_use"' not in line:
            continue
        ev["tool_calls"] += line.count('"tool_use"') or (1 if '"name":' in line else 0)
        if '"Edit"' in line or '"name": "Edit"' in line:
            ev["edited_kernel"] = ev["edited_kernel"] or "kernel.cpp" in line
        if '"Bash"' in line or '"name": "Bash"' in line:
            blob = line
            ev["single_case_verify"] = ev["single_case_verify"] or (
                "stub_test" in blob and "--case" in blob)
            ev["built"] = ev["built"] or "stub_build" in blob
    return ev


@pytest.mark.llm
@pytest.mark.heavy_llm
class TestPrecisionFullLoopN1Measure:
    """N1 全闭环：RunMeasure 纯 Python 测量 → has_failures 路由 → diagnose LLM
    就地修 → 复测 all_pass。run_tests 零 LLM（测量确定性）；判断/修复在 diagnose。"""

    def test_measure_routes_diagnose_fixes_remeasures(self, tmp_path, monkeypatch):
        if not _has_llm():
            pytest.skip("no LLM creds — real diagnose link unavailable (§3.7)")
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            DiagnoseSubstage, RunTestsSubstage,
        )
        from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
        from ascendc_devkit.orchestration.skill_config import skill_allowlist
        # §3.10 有界重试：LLM 段（spawn/修复/标注/工具证据）软收集驱动重试，
        # 每次 attempt 全新 seed 现场；测量/路由/复测是确定性框架契约——硬断言，
        # 失败即测试失败（不进重试吸收）。
        attempts_diag: list[str] = []
        for attempt in range(_MAX_ATTEMPTS):
            run = tmp_path / f"run{attempt}"
            op_dir = run / "op"
            ws_root = run / "ws"
            dbg = _seed_full_loop(run, ws_root)
            state = _full_loop_state(run, op_dir, ws_root)
            monkeypatch.setattr(RunTestsSubstage, "_common_context",
                                lambda self, s: _stub_ctx(op_dir))
            monkeypatch.setenv("PD_ARTIFACTS", str(dbg))

            # —— 1. 首测：RunMeasure 确定性测量（无 LLM；硬断言）——
            rt = RunTestsSubstage()
            actions = rt.actions(state, 1)
            assert len(actions) == 1 and type(actions[0]).__name__ == "RunMeasure"
            mr = _run_measure(actions[0])
            assert mr["returncode"] == 0, (
                f"测量应成功（失败用例不进退出码，run-cases 语义）: "
                f"rc={mr['returncode']} stderr={mr['stderr'][-400:]}")
            ctrl = dbg / "control.json"
            assert ctrl.exists(), "init-checkpoint 应由 RunMeasure 前置创建 control.json"
            cp = json.loads(ctrl.read_text(encoding="utf-8"))
            queue = cp.get("failed_case_queue") or []
            assert len(queue) == 1 and queue[0]["case_id"] == "c1", (
                f"build-failed-case-queue 应建 1 条失败队列: {queue!r}")
            assert queue[0]["status"] == "pending"

            # —— 2. transition → 路由 has_failures（→ diagnose；硬断言）——
            st2 = rt.transition(state, {"measure_result": mr})
            assert rt.resolve_condition(st2) == "has_failures", (
                f"1 失败 case 应路由 diagnose: {rt.resolve_condition(st2)!r}")
            assert st2._debug_checkpoint.get("rounds") == 1

            # —— 3. diagnose 真实 LLM spawn（读测量产物，就地修；软收集）——
            phase_json = dbg / "phases" / "diagnose" / "precision_diagnose.json"
            ctx = dict(_stub_ctx(op_dir), iter_n=0)
            prompt = DiagnoseSubstage()._phase_prompt(
                ctx, str(op_dir), str(ctrl), str(phase_json),
                str(Path(__file__).resolve().parents[2] / ".claude" / "skills" / _SKILL), 1)
            backend = SDKBackend(interactive=False, working_dir=op_dir.parent,
                                 on_decision="default", decision_workspace=op_dir)
            ar = backend.spawn(_AGENT, prompt, {}, skills=skill_allowlist(_SKILL),
                               working_dir=op_dir, stage_name="tui")
            shortfall: list[str] = []
            if ar is None or ar.status != "ok":
                shortfall.append(
                    f"diagnose spawn 未正常结束: status={getattr(ar, 'status', None)!r}")
            else:
                # 就地修复断言（同 TestPrecisionDiagnoseInplaceLoop 契约：
                # 代码形锚定，注释提及不判）
                kernel = (op_dir / "kernel.cpp").read_text(encoding="utf-8")
                if not (f"RoundMode::{_FIX_SIGNAL}" in kernel
                        and f"RoundMode::{_BUG_MARK}" not in kernel):
                    shortfall.append("kernel 未被修")
                cp = json.loads(ctrl.read_text(encoding="utf-8"))
                case = (cp.get("failed_case_queue") or [{}])[0]
                if case.get("status") != "resolved_pending":
                    shortfall.append(
                        f"case 应标 resolved_pending 转全量回归: "
                        f"{case.get('status')!r}")

                # —— 4. agent 工具使用证据（提效判定：Edit 修 kernel + 单用例
                #    验证；LLM 行为 → 软收集）——
                ev = _tool_evidence(ar.transcript)
                if ev["chars"] <= 0:
                    shortfall.append("transcript 无内容（实际产出为证，§1.11）")
                if not ev["edited_kernel"]:
                    shortfall.append(
                        "diagnose 应以 Edit 就地修 kernel.cpp（而非重写/绕过）")
                if not (ev["single_case_verify"] or ev["built"]):
                    shortfall.append(
                        "diagnose 应用 stub 工具验证（单用例 --case 或 build）"
                        "后再标 resolved")
            if shortfall:
                attempts_diag.append(f"attempt {attempt}: {'; '.join(shortfall)}")
                print(f"[N1] attempt {attempt}: LLM 段未全过 → 重试\n  {shortfall}")
                continue

            # —— 5. 复测：修复后 RunMeasure 全量回归 → all_pass（硬断言）——
            actions2 = rt.actions(st2, 2)
            mr2 = _run_measure(actions2[0])
            assert mr2["returncode"] == 0
            st3 = rt.transition(st2, {"measure_result": mr2})
            # status=passed 由 transition 派生写（测量后、transition 前仍 running）
            cp = json.loads(ctrl.read_text(encoding="utf-8"))
            assert cp.get("status") == "passed", (
                f"复测全过应 status=passed: {cp.get('status')!r}")
            assert not (cp.get("failed_case_queue") or []), "复测后队列应为空"
            assert rt.resolve_condition(st3) == "all_pass", (
                f"复测通过应路由 all_pass: {rt.resolve_condition(st3)!r}")

            # —— 6. 观测记录（工具效率人读信号，不进断言临界区）——
            print(f"\n[N1-obs] metrics={getattr(ar, 'metrics', None)} tool_ev={ev}")
            return  # 全链闭环达成（§3.10：有界重试内至少一次）
        pytest.fail(
            f"N1 全闭环在 {_MAX_ATTEMPTS} 次有界重试内未完整达成（LLM 段）:\n  "
            + "\n  ".join(attempts_diag))


@pytest.mark.llm
@pytest.mark.heavy_llm
class TestPrecisionRejectHintVisible:
    """§weak-model A：拒因可见链路（真实 LLM）——上轮 stalled 缺 self_check 被打回后，
    本轮 diagnose prompt 含「框架打回」段（ctx 注入→渲染），且拒因段不破坏正常闭环
    （agent 仍完成定位+修复）。走框架生产契约 `_common_context`（拒因从 control.json
    读取并按 round 匹配渲染）。

    ctx 命令字段用 `_stub_ctx` 覆盖（2026-09-11）：生产派生的 redeploy/run-cases 在
    ST 脚手架必然失败（redeploy 需 state_snapshot.json，stub workspace 没有）——
    拒因注入走生产契约验证，验证命令走 stub（对齐 N1 语义：生产命令派生由 UT 覆盖，
    ST 不给 LLM 一条死命令；此前继承生产命令致 agent 验证死路 → 4 挂 3 的抖动源）。
    LLM 闭环段按 §3.10 有界重试吸收残余非确定性。"""

    def test_reject_hint_rendered_and_loop_completes(self, tmp_path):
        if not _has_llm():
            pytest.skip("no LLM creds — real diagnose link unavailable (§3.7)")
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            DiagnoseSubstage,
        )
        from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
        from ascendc_devkit.orchestration.skill_config import skill_allowlist
        # §3.10 有界重试：拒因注入/渲染是确定性契约（硬断言，失败即测试失败）；
        # LLM 闭环段（定位+修+标注）软收集驱动重试，每次 attempt 全新 seed 现场。
        attempts_diag: list[str] = []
        for attempt in range(_MAX_ATTEMPTS):
            run = tmp_path / f"run{attempt}"
            op_dir = run / "op"
            ws_root = run / "ws"
            dbg = _seed_full_loop(run, ws_root)
            state = _full_loop_state(run, op_dir, ws_root)
            ctrl = dbg / "control.json"
            # 预置「上轮被打回」现场：stalled 缺 self_check 的拒因（round=当前 rounds）
            ctrl.write_text(json.dumps({
                "status": "running", "rounds": 4, "max_iterations": 15,
                "max_attempts_per_case": 8, "time_budget_sec": 36000,
                "current_case_index": 0, "failed_case_queue": [
                    {"case_id": "c1", "shape": "[16]", "dtype": "fp32",
                     "failure_type": "precision", "max_err": 0.5,
                     "attempt_count": 0, "status": "pending",
                     "outputs": [{"index": 0, "diff": 0.5, "status": "failing"}]}],
                "history": [],
                "upstream_signal": False, "upstream_stage": None,
                "upstream_reason": None, "phase_counter": 1, "run_iter_counter": 1,
                "consecutive_aborts": 0,
                "last_reject_reason": {
                    "cond": "stalled_without_selfcheck",
                    "detail": "声明 stalled 但缺 self_check 自检证据。请按自检项补 "
                              "self_check 后重新声明，或继续调试产出修复",
                    "round": 4},
            }, ensure_ascii=False, indent=2), encoding="utf-8")

            # 1. 拒因经生产契约注入+渲染（round 匹配当前 rounds=4）——确定性硬断言
            s = DiagnoseSubstage()
            ctx = {**s._common_context(state), **_stub_ctx(op_dir)}
            assert "框架打回" in str(ctx.get("reject_reason") or ""), \
                f"拒因应注入 ctx: {ctx.get('reject_reason')!r}"
            prompt = s._phase_prompt(
                ctx, str(op_dir), str(ctrl),
                str(dbg / "phases" / "diagnose" / "precision_diagnose.json"),
                str(Path(__file__).resolve().parents[2] / ".claude" / "skills" / _SKILL), 2)
            assert "## 框架打回（上轮 diagnose 产物被拒）" in prompt
            assert "stalled_without_selfcheck" in prompt

            # 2. 真实 LLM：拒因段在场，闭环仍完成（定位+修+标 resolved_pending）
            #    ——LLM 行为段软收集
            backend = SDKBackend(interactive=False, working_dir=op_dir.parent,
                                 on_decision="default", decision_workspace=op_dir)
            ar = backend.spawn(_AGENT, prompt, {}, skills=skill_allowlist(_SKILL),
                               working_dir=op_dir, stage_name="tui")
            shortfall: list[str] = []
            if ar is None or ar.status != "ok":
                shortfall.append(
                    f"spawn 未正常结束: status={getattr(ar, 'status', None)!r}")
            else:
                kernel = (op_dir / "kernel.cpp").read_text(encoding="utf-8")
                if not (f"RoundMode::{_FIX_SIGNAL}" in kernel
                        and f"RoundMode::{_BUG_MARK}" not in kernel):
                    shortfall.append("闭环未完成修复（kernel 未改到正确 RoundMode）")
                cp = json.loads(ctrl.read_text(encoding="utf-8"))
                case = (cp.get("failed_case_queue") or [{}])[0]
                if case.get("status") != "resolved_pending":
                    shortfall.append(
                        f"case 应标 resolved_pending: {case.get('status')!r}")
            if not shortfall:
                return  # 拒因在场 + 闭环完整达成（§3.10：有界重试内至少一次）
            attempts_diag.append(f"attempt {attempt}: {'; '.join(shortfall)}")
            print(f"[reject-hint] attempt {attempt}: 闭环未完整 → 重试\n  {shortfall}")
        pytest.fail(
            f"拒因在场时 diagnose 闭环在 {_MAX_ATTEMPTS} 次有界重试内未完整达成"
            "（拒因注入/渲染硬断言已通过——失败在 LLM 行为段）:\n  "
            + "\n  ".join(attempts_diag))
