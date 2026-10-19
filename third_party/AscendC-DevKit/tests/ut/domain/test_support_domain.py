"""support_domain 域对质引擎 UT（docs/plan/design-math-claims-verification L4 §6 V2/V3）。

确定性（no-LLM）。判据：设计 support_domain ⊇ 需求(golden) 域；
transpose 用真实 requirement.json 验证"任意 perm ⊆ 循环旋转"必抓出缺口。
"""

from __future__ import annotations

from ascendc_devkit.domain.support_domain import (
    design_support_domain,
    domain_covers,
    requirement_domain,
    validate_support_domain_structure,
)

# transpose requirement 结构 fixture（golden=torch.permute 支持任意 perm）。
# requirement_domain() 优先读 domain 字段，此处直接给结构化表达。
_TRANSPOSE_REQ: dict = {
    "domain": {
        "rank": {"min": 1, "max": 8},
        "inputs": [{
            "name": "x",
            "dtypes": ["bfloat16", "float16", "float32", "int8", "int16", "int32", "int64"],
        }],
    }
}


def _transpose_design(perm_constraint: str, rank_max: int = 8) -> dict:
    return {
        "support_domain": {
            "rank": {"min": 1, "max": rank_max},
            "inputs": [{"name": "x", "dtypes": ["bfloat16", "float16", "float32", "int8", "int16", "int32", "int64"]}],
            "attrs": [{"name": "perm", "domain": {"kind": "permutation", "constraint": perm_constraint}}],
        }
    }


class TestDomainCovers:
    def test_transpose_cyclic_rotation_gap_detected(self):
        """设计只声明循环旋转 → 引擎必须抓出"任意 perm ⊄ 循环旋转"缺口（transpose 真实反例）。"""
        req_d = {"attrs": [{"name": "perm", "domain": {"kind": "permutation", "constraint": "any"}}]}
        design_d = {"attrs": [{"name": "perm", "domain": {"kind": "permutation", "constraint": "cyclic_rotation"}}]}
        gaps = domain_covers(req_d, design_d)
        assert any("perm" in g and "⊄" in g for g in gaps), f"应抓出 perm 域缺口: {gaps}"

    def test_transpose_full_perm_pass(self):
        """设计声明任意 perm → 无缺口。"""
        req_d = {"attrs": [{"name": "perm", "domain": {"kind": "permutation", "constraint": "any"}}]}
        design_d = {"attrs": [{"name": "perm", "domain": {"kind": "permutation", "constraint": "any"}}]}
        assert domain_covers(req_d, design_d) == []

    def test_dtype_gap_detected(self):
        req_d = {"inputs": [{"name": "x", "dtypes": ["float16", "float32", "int8"]}]}
        design_d = {"inputs": [{"name": "x", "dtypes": ["float16", "float32"]}]}
        gaps = domain_covers(req_d, design_d)
        assert any("int8" in g for g in gaps)

    def test_rank_gap_detected(self):
        req_d = {"rank": {"min": 1, "max": 8}}
        design_d = {"rank": {"min": 1, "max": 2}}
        gaps = domain_covers(req_d, design_d)
        assert any("rank" in g for g in gaps)

    def test_rank_missing_in_design_flagged(self):
        """需求声明 rank、设计 support_domain 缺 rank → 保守 flag（与 dtype/attr 同口径，F5）。"""
        req_d = {"rank": {"min": 1, "max": 8}}
        gaps = domain_covers(req_d, {})
        assert any("rank" in g and "未声明" in g for g in gaps), gaps

    def test_missing_axis_no_false_positive(self):
        """两侧都缺某轴 → 跳过，不假阳性。"""
        assert domain_covers({}, {}) == []
        assert domain_covers({"inputs": []}, {}) == []

    def test_design_missing_attr_declared_in_req(self):
        req_d = {"attrs": [{"name": "perm", "domain": {"kind": "permutation", "constraint": "any"}}]}
        assert any("未声明" in g for g in domain_covers(req_d, {}))

    def test_rank_string_in_design_no_crash_but_flag(self):
        """设计 support_domain.rank 为 prose 字符串（gelu 场景）→ 不抛异常，产生「无法对质」保守 flag。

        20260809-170202 gelu run 回归：skill 教设计 LLM 写 prose support_domain，引擎按
        结构化 schema 解析曾抛 AttributeError → 被外层吞成泛化 WARN → 整次域对质静默失效。
        """
        req_d = {"rank": {"min": 0, "max": 8}}
        design_d = {"rank": "0..8（任意 shape，逐元素等价）"}
        gaps = domain_covers(req_d, design_d)  # 不应抛异常
        assert any("rank" in g and "无法对质" in g for g in gaps), gaps

    def test_rank_dict_with_string_values_flagged_no_crash(self):
        """设计 rank 是 dict 但 min/max 是字符串（{"min":"1","max":"8"}）→ 不抛异常，
        产生「无法对质」flag（M1 review 坐实：int < str 曾抛 TypeError 被吞成泛化 WARN）。"""
        req_d = {"rank": {"min": 1, "max": 8}}
        design_d = {"rank": {"min": "1", "max": "8"}}  # dict 但值非数值
        gaps = domain_covers(req_d, design_d)  # 不应抛异常
        assert any("rank" in g and "无法对质" in g for g in gaps), gaps

    def test_rank_string_values_in_requirement_skip(self):
        """需求侧 rank.min/max 为字符串 → 跳过，不假阳性（同 rr 非 dict 口径）。"""
        req_d = {"rank": {"min": "1", "max": "8"}}
        design_d = {"rank": {"min": 1, "max": 8}}
        assert domain_covers(req_d, design_d) == []

    def test_malformed_dtype_inputs_no_crash(self):
        """设计 inputs 条目 dtypes 非 list → 不崩，降级为保守缺口。"""
        req_d = {"inputs": [{"name": "x", "dtypes": ["float16"]}]}
        design_d = {"inputs": [{"name": "x", "dtypes": "fp16"}]}  # dtypes 字符串（malformed）
        gaps = domain_covers(req_d, design_d)
        assert any("x" in g for g in gaps), gaps  # 保守 flag，不崩

    def test_rank_string_in_requirement_skip(self):
        """需求侧 rank 为字符串 → 跳过，不假阳性。"""
        req_d = {"rank": "1..8（prose）"}
        design_d = {"rank": {"min": 1, "max": 8}}
        assert domain_covers(req_d, design_d) == []

    def test_malformed_attrs_no_crash(self):
        """设计 attrs 条目 domain 为字符串 → 不崩，走「未声明」保守 flag。"""
        req_d = {"attrs": [{"name": "perm", "domain": {"kind": "permutation", "constraint": "any"}}]}
        design_d = {"attrs": [{"name": "perm", "domain": "any"}]}  # domain 非 dict
        gaps = domain_covers(req_d, design_d)
        assert any("未声明" in g for g in gaps), gaps

    def test_all_malformed_no_crash(self):
        """两侧全为异常形态 → 不抛异常，返回空/保守缺口（安全网绝不崩）。"""
        req_d = {"rank": 5, "inputs": ["junk"], "attrs": [7]}
        design_d = {"rank": "x", "inputs": [1], "attrs": ["y"]}
        assert isinstance(domain_covers(req_d, design_d), list)  # 不抛异常


class TestValidateSupportDomainStructure:
    """validate_support_domain_structure（§1.3 加载期校验，validate 阶段调用）：
    只查结构形态（dict/list/字段类型），不查覆盖语义。"""

    def test_structured_passes(self):
        sd = {
            "rank": {"min": 1, "max": 8},
            "inputs": [{"name": "x", "dtypes": ["float16", "float32"]}],
            "attrs": [{"name": "perm", "domain": {"kind": "permutation", "constraint": "any"}}],
        }
        assert validate_support_domain_structure(sd) == []

    def test_prose_rank_string_flagged(self):
        """gelu 场景：prose 字符串 rank → 结构错误。"""
        sd = {"rank": "0..8（任意 shape，逐元素等价）", "dtype": "fp16 / fp32 / bf16"}
        errors = validate_support_domain_structure(sd)
        assert any("rank" in e and "dict" in e for e in errors), errors

    def test_dtypes_not_list_flagged(self):
        sd = {"inputs": [{"name": "x", "dtypes": "fp16"}]}
        errors = validate_support_domain_structure(sd)
        assert any("dtypes" in e and "list" in e for e in errors), errors

    def test_attr_domain_not_dict_flagged(self):
        sd = {"attrs": [{"name": "perm", "domain": "any"}]}
        errors = validate_support_domain_structure(sd)
        assert any("domain" in e for e in errors), errors

    def test_non_dict_sd_flagged(self):
        assert validate_support_domain_structure("0..8（prose）")
        assert validate_support_domain_structure(None)

    def test_missing_fields_ok(self):
        """缺失 = 未声明，不报（不假阳性）。"""
        assert validate_support_domain_structure({}) == []
        assert validate_support_domain_structure({"desc": "人读"}) == []


class TestRequirementDomainExtraction:
    def test_transpose_real_requirement(self):
        """从 transpose 真实 requirement.json 提取结构化域：dtypes 7 种、rank 1-8。"""
        d = requirement_domain(_TRANSPOSE_REQ)
        assert d.get("rank") == {"min": 1, "max": 8}, d
        inputs = {i["name"]: i["dtypes"] for i in d.get("inputs", [])}
        assert "x" in inputs and set(inputs["x"]) == {
            "float16", "float32", "bfloat16", "int8", "int16", "int32", "int64",
        }, inputs

    @staticmethod
    def _with_structured_perm(req_d):
        """补结构化 attr 域（Phase 2 后 req-analysis 应产出；旧 requirement.json 只有 prose）。"""
        req_d = dict(req_d)
        req_d["attrs"] = [{"name": "perm", "domain": {"kind": "permutation", "constraint": "any"}}]
        return req_d

    def test_extraction_feeds_domain_covers(self):
        """端到端：需求(任意 perm) + 设计声明循环旋转 → 引擎抓缺口（即 transpose 场景）。"""
        req_d = self._with_structured_perm(requirement_domain(_TRANSPOSE_REQ))
        design_d = design_support_domain(_transpose_design("cyclic_rotation"))
        gaps = domain_covers(req_d, design_d)
        assert any("perm" in g for g in gaps), f"端到端应抓出 perm 缺口: {gaps}"

    def test_extraction_full_domain_passes(self):
        """需求(任意 perm) + 设计声明任意 perm → 通过（rank/dtype/attr 全覆盖）。"""
        req_d = self._with_structured_perm(requirement_domain(_TRANSPOSE_REQ))
        design_d = design_support_domain(_transpose_design("any"))
        assert domain_covers(req_d, design_d) == []
