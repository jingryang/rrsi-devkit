"""step-113 (P11-B1) — staging per-template 切片视图 + prompt 指针 + source guards。

B1 的事实锁（机械拆分，零内容解释）：
  - 多模板 State → staging/tiling_results/<T>.json 各切片（包裹形态
    ``{<T>: <原段>}``），**合并 ≡ 原 dict**（UT 防物化漂移）；
  - 单模板 → 一个切片；tiling_results 缺省 → 不切；
  - 模板名 sanitize（路径非法字符）落盘可读回；sanitize 碰撞 → 跳过切片
    不抛错（单体仍写，确定性回退）；
  - 单体照写（并存——读通路唯一由 prompt 指针保证，单体退为全貌/取证/
    老批 RESUME 兼容形态）；
  - spawn prompt 注入行指切片目录（不再指单体文件路径）。
"""

from __future__ import annotations

import json
from pathlib import Path

from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.codegen import CodegenStage

_REPO = Path(__file__).resolve().parents[3]
_CODER_SKILL = (_REPO / ".claude" / "skills"
                / "ascendc-op-dev-coding" / "SKILL.md")

_TR = {
    "T1": {"split": {"axis": "N"},
           "buffer_kernel": {"buffer_num": 2,
                             "workspace": {"user_workspace_bytes": 8,
                                           "rationale": "r",
                                           "layout_contract": ["p: f"]}},
           "precision_perf": {"compute_dtype": "fp32"}},
    "T2": {"split": {"axis": "C"},
           "buffer_kernel": {"buffer_num": 2},
           "precision_perf": {"compute_dtype": "fp16"}},
}


def _stage() -> CodegenStage:
    return CodegenStage()


def _materialize(tmp_path, tiling_results):
    staging = tmp_path / "staging"
    _stage()._materialize_inputs(
        State.empty().with_updates(tiling_results=tiling_results), staging)
    return staging


class TestStagingSlices:
    def test_multi_template_slices_and_merge_equivalence(self, tmp_path):
        staging = _materialize(tmp_path, _TR)
        slc = staging / "tiling_results"
        assert (slc / "T1.json").is_file() and (slc / "T2.json").is_file()
        merged = {}
        for f in sorted(slc.glob("*.json")):
            merged.update(json.loads(f.read_text(encoding="utf-8")))
        assert merged == _TR  # 切片合并 ≡ 原 dict（机械性守护）
        # 单体并存（全貌视图）
        assert json.loads(
            (staging / "tiling_results.json").read_text(encoding="utf-8")) == _TR

    def test_slice_wrapped_form_is_self_describing(self, tmp_path):
        staging = _materialize(tmp_path, {"T1": _TR["T1"]})
        one = json.loads((staging / "tiling_results" / "T1.json")
                         .read_text(encoding="utf-8"))
        assert one == {"T1": _TR["T1"]}

    def test_single_template_one_slice(self, tmp_path):
        staging = _materialize(tmp_path, {"T_InterpolatePool": _TR["T1"]})
        files = list((staging / "tiling_results").glob("*.json"))
        assert [f.stem for f in files] == ["T_InterpolatePool"]

    def test_absent_tiling_results_no_slices(self, tmp_path):
        staging = _materialize(tmp_path, None)
        assert not (staging / "tiling_results").exists()
        assert not (staging / "tiling_results.json").exists()

    def test_template_name_sanitized(self, tmp_path):
        staging = _materialize(tmp_path, {"T/1:x": _TR["T1"], "T2": _TR["T2"]})
        names = sorted(f.name for f in
                       (staging / "tiling_results").glob("*.json"))
        assert "T2.json" in names
        assert all("/" not in n and ":" not in n for n in names)
        # sanitize 后仍可读回且内容完整
        merged = {}
        for f in (staging / "tiling_results").glob("*.json"):
            merged.update(json.loads(f.read_text(encoding="utf-8")))
        assert merged == {"T/1:x": _TR["T1"], "T2": _TR["T2"]}

    def test_sanitize_collision_skips_slices_not_fail(self, tmp_path):
        # "T/1" 与 "T:1" sanitize 后同为 "T_1" → 碰撞：跳过切片、单体照写、不抛错
        staging = _materialize(tmp_path, {"T/1": _TR["T1"], "T:1": _TR["T2"]})
        assert not (staging / "tiling_results").exists()
        assert json.loads(
            (staging / "tiling_results.json").read_text(encoding="utf-8")) == {
                "T/1": _TR["T1"], "T:1": _TR["T2"]}

    def test_reentry_prunes_stale_slices(self, tmp_path):
        """M7（review 整改）：重入后模板集缩减，陈旧切片必须消失。

        loopback/RESUME 复用同一 staging——增量覆写会让已移除模板的旧
        <T>.json 残留，prompt 的「跨模板一致性核对读相邻切片」会把 coder
        引向与当前 State 不符的旧蓝图。"""
        staging = _materialize(tmp_path, _TR)
        assert (staging / "tiling_results" / "T2.json").is_file()
        # 重入：模板改名/缩减（只剩 T1）
        staging = _materialize(tmp_path, {"T1": _TR["T1"]})
        names = sorted(f.name for f in
                       (staging / "tiling_results").glob("*.json"))
        assert names == ["T1.json"], f"stale slices survived re-entry: {names}"

    def test_collision_fallback_removes_stale_slices_dir(self, tmp_path):
        """M7：碰撞跳过切片时清掉残留旧目录——prompt 指针的 is_dir() 门
        才能确定性落到单体（残留目录会击穿「切片目录不在 → 指单体」回退）。"""
        staging = _materialize(tmp_path, _TR)
        assert (staging / "tiling_results").is_dir()
        # 重入：新模板名 sanitize 碰撞 → 跳过切片，旧切片目录必须一并消失
        staging = _materialize(tmp_path, {"T/1": _TR["T1"], "T:1": _TR["T2"]})
        assert not (staging / "tiling_results").exists()
        assert json.loads(
            (staging / "tiling_results.json").read_text(encoding="utf-8")) == {
                "T/1": _TR["T1"], "T:1": _TR["T2"]}


class TestPromptPointer:
    def test_prompt_injection_points_to_slices(self, tmp_path):
        # spawn prompt 的设计文件注入段：指切片目录（读通路唯一），不注入单体路径。
        # 真实调用序：先 _materialize_inputs（切片落盘）再建 prompt（指针 stat 目录）。
        ws = type("W", (), {"artifacts": tmp_path})()
        s = State.empty().with_updates(
            _workspace=ws, tiling_results=_TR,
            op_identity=None, target_repo_baseline_ref=None)
        _stage()._materialize_inputs(s, tmp_path)
        prompt = _stage()._build_codegen_prompt(s, 1, staging_dir=tmp_path)
        assert "tiling_results" in prompt
        assert f"{tmp_path}/tiling_results" in prompt
        assert "tiling_results.json" not in prompt

    def test_prompt_falls_back_to_monolith_when_slices_skipped(self, tmp_path):
        # 碰撞跳过切片（目录不存在）→ 指针回退指单体，不指向不存在的路径
        ws = type("W", (), {"artifacts": tmp_path})()
        s = State.empty().with_updates(
            _workspace=ws, tiling_results={"T/1": _TR["T1"], "T:1": _TR["T2"]},
            op_identity=None, target_repo_baseline_ref=None)
        _stage()._materialize_inputs(s, tmp_path)
        prompt = _stage()._build_codegen_prompt(s, 1, staging_dir=tmp_path)
        assert "tiling_results.json" in prompt
        assert "per-template 切片" not in prompt


class TestSkillSourceGuard:
    def test_skill_carries_slice_pointer_and_read_discipline(self):
        text = _CODER_SKILL.read_text(encoding="utf-8")
        # 切片读单元 + 全貌视图说明
        assert "tiling_results/" in text or "tiling_results/<" in text
        # 读纪律（A）：先定位后读段 + 定位失败允许整读的自服回退
        # （无回退子句的绝对禁令会把「定位失败」变「瞎猜/违规」——禁令下界
        # 必须兜在基线，见 L3 §2.2 修正）
        assert "整文件" in text
        assert "定位失败" in text and "允许整文件读" in text

    def test_no_operator_names_in_new_lines(self):
        blacklist = ("unique_dim", "UniqueDim", "logcumsumexp", "Logcumsumexp",
                     "interpolate", "Interpolate", "take_along", "TakeAlong",
                     "upsample", "Upsample", "MseLoss")
        lines = _CODER_SKILL.read_text(encoding="utf-8").splitlines()
        hits = [i for i, ln in enumerate(lines)
                if "tiling_results/" in ln or "整文件" in ln]
        scoped = []
        for i in hits:
            scoped.extend(lines[max(0, i - 2):i + 3])
        for ln in scoped:
            for name in blacklist:
                assert name not in ln, f"契约段落耦合算子名 {name!r}: {ln.strip()}"
