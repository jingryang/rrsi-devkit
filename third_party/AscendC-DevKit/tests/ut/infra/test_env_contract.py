"""step-108 环境契约守护单测（docs/plan batch-20260829-49134b 05-impl 改动 1）。

被测：``infra/env_contract.py`` —— 成员断言不变式 / 回环探针（含机制级模拟毒）/
撞名 WARN / 失败诊断 / harness 断言块。

背景（批 20260829-142941-49134b P3）：外部 sitecustomize 把**正确的** vendor 级
`ASCEND_CUSTOM_OPP_PATH` 后缀剥掉，症状经三层传导后与 codegen bug 同形，烧 10h。
断言语义 = **成员断言**（期望值 ∈ 实际值冒号列表）——CANN 官方语义允许 set_env.bash
合法追加，追加不触发；剥离/替换才触发。
"""
import os
import textwrap
from pathlib import Path

from ascendc_devkit.infra import env_contract
from ascendc_devkit.infra.env_contract import (
    ENV_CONTRACT_EXIT_CODE,
    ENV_CONTRACT_MARKER,
    PREFLIGHT_PROBE_VALUE,
    ascend_custom_opp_intact,
    expected_ascend_custom_opp,
)

# sitecustomize 同款毒（批 20260829 实物的等价最小复现）：后缀剥离
_SUFFIX_STRIP_HOOK = textwrap.dedent("""\
    import os
    _acopp = os.environ.get("ASCEND_CUSTOM_OPP_PATH", "")
    if _acopp.endswith("/vendors/custom_ops"):
        os.environ["ASCEND_CUSTOM_OPP_PATH"] = _acopp[: -len("/vendors/custom_ops")]
""")


# ─── 成员断言（不变式本体）───────────────────────────────────────────────────

def test_membership_exact_passes():
    assert ascend_custom_opp_intact(
        "/a/vendors/custom_ops", "/a/vendors/custom_ops")


def test_membership_legit_append_passes():
    """CANN 语义：set_env.bash 合法追加不触发（成员断言非全等）。"""
    assert ascend_custom_opp_intact(
        "/a/vendors/custom_ops", "/b/vendors/x:/a/vendors/custom_ops")


def test_membership_suffix_strip_fails():
    """sitecustomize 后缀剥离 → 期望元素不在实际列表中 → 失配。"""
    assert not ascend_custom_opp_intact("/a/vendors/custom_ops", "/a")


def test_value_form_single_source_and_form_faithful_probe():
    """值形态单源 + 探测值必须形态忠实（哑值触发不了后缀匹配类毒，L3 硬约束）。"""
    assert expected_ascend_custom_opp("/a") == "/a/vendors/custom_ops"
    assert PREFLIGHT_PROBE_VALUE.endswith("/vendors/custom_ops")


# ─── 回环探针（机制级真实子进程，不 mock）─────────────────────────────────────

def _deterministic_env(value: str) -> dict:
    """确定性子进程 env：PYTHONNOUSERSITE=1 灭 user-site 钩子、清 PYTHONPATH——
    测试结论不随宿主机环境漂移。"""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONNOUSERSITE"] = "1"
    env["ASCEND_CUSTOM_OPP_PATH"] = value
    return env


def _hook_env(tmp_path: Path, value: str) -> dict:
    """在 PYTHONPATH 目录放 sitecustomize.py（解释器启动钩子按 sys.path 加载，
    与 user-site 投递机制等价）——机制级模拟毒。"""
    (tmp_path / "sitecustomize.py").write_text(_SUFFIX_STRIP_HOOK, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONPATH"] = str(tmp_path)
    env["ASCEND_CUSTOM_OPP_PATH"] = value
    return env


def test_probe_clean_env_passes(tmp_path):
    v = env_contract.probe_env_contract(
        _deterministic_env("/tmp/clean/vendors/custom_ops"))
    assert v is None


def test_probe_detects_suffix_strip_poison(tmp_path):
    """毒经解释器启动钩子改值 → 探针失配并给出可诊断信息。"""
    v = env_contract.probe_env_contract(
        _hook_env(tmp_path, "/tmp/po/vendors/custom_ops"))
    assert v is not None
    assert "ASCEND_CUSTOM_OPP_PATH" in v


def test_probe_form_faithfulness_dummy_value_misses_poison(tmp_path):
    """形态忠实性的反证面：哑值（不带 /vendors/custom_ops 后缀）触发不了
    后缀匹配类毒——这就是探测值必须用生产值形态的原因。"""
    assert env_contract.probe_env_contract(_hook_env(tmp_path, "/tmp/plain")) is None


def test_probe_preflight_value_form_triggers_poison(tmp_path):
    """开跑预检的合成探测值用生产值形态 → 该形态的毒在 t=0 即被探出。"""
    assert env_contract.probe_env_contract(
        _hook_env(tmp_path, PREFLIGHT_PROBE_VALUE)) is not None


def test_probe_subprocess_failure_not_misattributed_as_rewrite(monkeypatch):
    """M8：探针子进程 rc≠0 单独归因「启动失败」（附 stderr 尾行），不再误报成
    「值被改写」——rc≠0 时根本没有回读值可比对。"""
    from types import SimpleNamespace
    monkeypatch.setattr(
        env_contract.subprocess, "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=1, stdout="", stderr="first\npython: fatal boot error"))
    v = env_contract.probe_env_contract(
        {"ASCEND_CUSTOM_OPP_PATH": "/x/vendors/custom_ops"})
    assert v is not None
    assert "启动失败" in v and "rc=1" in v
    assert "fatal boot error" in v  # stderr 尾行进诊断
    assert "被改写" not in v  # 不误归因值改写


# ─── 撞名 WARN（信息级，不拦跑）──────────────────────────────────────────────


# ─── 撞名 WARN（信息级，不拦跑）──────────────────────────────────────────────

def _make_vendor_op(opp_root: Path, op_name: str) -> None:
    (opp_root / "vendors" / "custom_ops" / "op_impl" / "ai_core" / "tbe"
     / "custom_ops_impl" / "dynamic" / op_name).mkdir(parents=True, exist_ok=True)


def test_collision_warn_hits_sibling_in_system_vendors(tmp_path, monkeypatch):
    _make_vendor_op(tmp_path, "my_op_custom")
    warned: list[str] = []
    monkeypatch.setattr(
        env_contract.Logger, "warn",
        staticmethod(lambda msg: warned.append(msg)))
    n = env_contract.warn_system_vendor_collisions(
        ["my_op_custom"], opp_path=str(tmp_path))
    assert n == 1
    assert any("my_op_custom" in w for w in warned)


def test_collision_silent_when_system_vendors_clean(tmp_path, monkeypatch):
    _make_vendor_op(tmp_path, "unrelated_op")
    warned: list[str] = []
    monkeypatch.setattr(
        env_contract.Logger, "warn",
        staticmethod(lambda msg: warned.append(msg)))
    n = env_contract.warn_system_vendor_collisions(
        ["my_op_custom"], opp_path=str(tmp_path))
    assert n == 0
    assert warned == []


def test_collision_noop_without_opp_path(monkeypatch):
    """无 $ASCEND_OPP_PATH（如 stub/纯设计机）→ 静默跳过，不报错。"""
    monkeypatch.delenv("ASCEND_OPP_PATH", raising=False)
    assert env_contract.warn_system_vendor_collisions(["any_op"]) == 0


def test_collision_warn_deduped_per_tree_within_process(tmp_path, monkeypatch):
    """M9：同树撞名 WARN 进程级去重——第二次扫描同一实体不再刷屏（事实首行已
    留痕），返回 hit 数亦只计新命中。"""
    _make_vendor_op(tmp_path, "dup_op_custom")
    warned: list[str] = []
    monkeypatch.setattr(
        env_contract.Logger, "warn",
        staticmethod(lambda msg: warned.append(msg)))
    assert env_contract.warn_system_vendor_collisions(
        ["dup_op_custom"], opp_path=str(tmp_path)) == 1
    assert env_contract.warn_system_vendor_collisions(
        ["dup_op_custom"], opp_path=str(tmp_path)) == 0  # 去重：不再 WARN
    assert len([w for w in warned if "dup_op_custom" in w]) == 1


# ─── 失败诊断（只读、报事实不定罪）────────────────────────────────────────────

def test_diagnose_reports_usersite_hook(tmp_path, monkeypatch):
    (tmp_path / "sitecustomize.py").write_text(
        _SUFFIX_STRIP_HOOK, encoding="utf-8")
    import site
    monkeypatch.setattr(site, "getusersitepackages", lambda: str(tmp_path))
    lines = env_contract.diagnose_env_hooks()
    assert any("sitecustomize" in ln and str(tmp_path) in ln for ln in lines)


def test_diagnose_reports_pythonpath_hook_dir(tmp_path, monkeypatch):
    (tmp_path / "sitecustomize.py").write_text(
        _SUFFIX_STRIP_HOOK, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    lines = env_contract.diagnose_env_hooks()
    assert any("sitecustomize" in ln and str(tmp_path) in ln for ln in lines)


def test_diagnose_clean_machine_returns_list_without_raise(monkeypatch):
    monkeypatch.delenv("PYTHONPATH", raising=False)
    import site
    monkeypatch.setattr(site, "getusersitepackages", lambda: "/nonexistent-usr")
    lines = env_contract.diagnose_env_hooks()
    assert isinstance(lines, list)


# ─── harness 断言块（生成器单点的块本体）─────────────────────────────────────

def test_harness_assert_block_contains_marker_expected_and_exit_code():
    blk = env_contract.harness_assert_block("/x/vendors/custom_ops")
    assert ENV_CONTRACT_MARKER in blk
    assert "/x/vendors/custom_ops" in blk
    assert f"sys.exit({ENV_CONTRACT_EXIT_CODE})" in blk


def test_harness_assert_block_empty_without_expected():
    """无 install_path（无部署上下文）→ 空块，不注入断言。"""
    assert env_contract.harness_assert_block("") == ""
