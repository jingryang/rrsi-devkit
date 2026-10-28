"""support_domain 域对质引擎 UT（docs/plan/design-math-claims-verification L4 §6 V2/V3）。

确定性（no-LLM）。判据：设计 support_domain ⊇ 需求(golden) 域；
transpose 用真实 requirement.json 验证"任意 perm ⊆ 循环旋转"必抓出缺口。
"""

from __future__ import annotations

import json
import logging

from ascendc_devkit.domain.support_domain import (
    design_support_domain,
    domain_covers,
    merged_input_entries,
    requirement_domain,
    tensor_rank_domain,
    validate_support_domain_structure,
)

# transpose requirement 结构 fixture（golden=torch.permute 支持任意 perm）。
# requirement_domain() 优先读 domain 字段，此处直接给结构化表达。
_TRANSPOSE_REQ: dict = {
    "domain": {
        "inputs": [{
            "name": "x",
            "dtypes": ["bfloat16", "float16", "float32", "int8", "int16", "int32", "int64"],
            "rank": {"min": 1, "max": 8},
        }],
    }
}


def _transpose_design(perm_constraint: str, rank_max: int = 8) -> dict:
    return {
        "support_domain": {
            "inputs": [{"name": "x", "dtypes": ["bfloat16", "float16", "float32", "int8", "int16", "int32", "int64"],
                        "rank": {"min": 1, "max": rank_max}}],
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
        req_d = {"inputs": [{"name": "x", "rank": {"min": 1, "max": 8}}]}
        design_d = {"inputs": [{"name": "x", "rank": {"min": 1, "max": 2}}]}
        gaps = domain_covers(req_d, design_d)
        assert any("rank" in g and "x" in g for g in gaps), gaps

    def test_per_tensor_rank_not_judged_by_other_tensor(self):
        """低秩参数在自己的域内合法——不得被主输入的域判死（本次事故形态）。"""
        req_d = {"inputs": [{"name": "x", "rank": {"min": 2, "max": 8}},
                            {"name": "gamma", "rank": {"min": 1, "max": 7}}]}
        design_d = {"inputs": [{"name": "x", "rank": {"min": 2, "max": 8}},
                               {"name": "gamma", "rank": {"min": 1, "max": 7}}]}
        assert domain_covers(req_d, design_d) == []

    def test_gamma_over_claim_detected(self):
        """设计对 gamma 声称比需求更窄的域 → 按 gamma 自己的域抓缺口。"""
        req_d = {"inputs": [{"name": "gamma", "rank": {"min": 1, "max": 7}}]}
        design_d = {"inputs": [{"name": "gamma", "rank": {"min": 2, "max": 7}}]}
        gaps = domain_covers(req_d, design_d)
        assert any("rank[gamma]" in g for g in gaps), gaps

    def test_rank_missing_in_design_flagged(self):
        """需求声明 rank、设计 support_domain 缺 rank → 保守 flag（与 dtype/attr 同口径，F5）。"""
        req_d = {"inputs": [{"name": "x", "rank": {"min": 1, "max": 8}}]}
        gaps = domain_covers(req_d, {"inputs": [{"name": "x", "dtypes": ["float16"]}]})
        assert any("rank" in g and "未声明" in g for g in gaps), gaps

    def test_rank_missing_design_input_flagged(self):
        """设计根本没声明该输入 → 保守 flag。"""
        req_d = {"inputs": [{"name": "x", "rank": {"min": 1, "max": 8}}]}
        gaps = domain_covers(req_d, {})
        assert any("rank[x]" in g and "未声明" in g for g in gaps), gaps

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
        req_d = {"inputs": [{"name": "x", "rank": {"min": 0, "max": 8}}]}
        design_d = {"inputs": [{"name": "x", "rank": "0..8（任意 shape，逐元素等价）"}]}
        gaps = domain_covers(req_d, design_d)  # 不应抛异常
        assert any("rank" in g and "无法对质" in g for g in gaps), gaps

    def test_rank_dict_with_string_values_flagged_no_crash(self):
        """设计 rank 是 dict 但 min/max 是字符串（{"min":"1","max":"8"}）→ 不抛异常，
        产生「无法对质」flag（M1 review 坐实：int < str 曾抛 TypeError 被吞成泛化 WARN）。"""
        req_d = {"inputs": [{"name": "x", "rank": {"min": 1, "max": 8}}]}
        design_d = {"inputs": [{"name": "x", "rank": {"min": "1", "max": "8"}}]}  # dict 但值非数值
        gaps = domain_covers(req_d, design_d)  # 不应抛异常
        assert any("rank" in g and "无法对质" in g for g in gaps), gaps

    def test_rank_string_values_in_requirement_skip(self):
        """需求侧 rank.min/max 为字符串 → 跳过，不假阳性（同 rr 非 dict 口径）。"""
        req_d = {"inputs": [{"name": "x", "rank": {"min": "1", "max": "8"}}]}
        design_d = {"inputs": [{"name": "x", "rank": {"min": 1, "max": 8}}]}
        assert domain_covers(req_d, design_d) == []

    def test_malformed_dtype_inputs_no_crash(self):
        """设计 inputs 条目 dtypes 非 list → 不崩，降级为保守缺口。"""
        req_d = {"inputs": [{"name": "x", "dtypes": ["float16"]}]}
        design_d = {"inputs": [{"name": "x", "dtypes": "fp16"}]}  # dtypes 字符串（malformed）
        gaps = domain_covers(req_d, design_d)
        assert any("x" in g for g in gaps), gaps  # 保守 flag，不崩

    def test_rank_string_in_requirement_skip(self):
        """需求侧 rank 为字符串 → 跳过，不假阳性。"""
        req_d = {"inputs": [{"name": "x", "rank": "1..8（prose）"}]}
        design_d = {"inputs": [{"name": "x", "rank": {"min": 1, "max": 8}}]}
        assert domain_covers(req_d, design_d) == []

    def test_malformed_attrs_no_crash(self):
        """设计 attrs 条目 domain 为字符串 → 不崩，走「未声明」保守 flag。"""
        req_d = {"attrs": [{"name": "perm", "domain": {"kind": "permutation", "constraint": "any"}}]}
        design_d = {"attrs": [{"name": "perm", "domain": "any"}]}  # domain 非 dict
        gaps = domain_covers(req_d, design_d)
        assert any("未声明" in g for g in gaps), gaps

    def test_all_malformed_no_crash(self):
        """两侧全为异常形态 → 不抛异常，返回空/保守缺口（安全网绝不崩）。"""
        req_d = {"rank": 5, "inputs": [{"name": "x", "rank": 5}, "junk"], "attrs": [7]}
        design_d = {"rank": "x", "inputs": [{"name": "x", "rank": "x"}, 1], "attrs": ["y"]}
        assert isinstance(domain_covers(req_d, design_d), list)  # 不抛异常


class TestValidateSupportDomainStructure:
    """validate_support_domain_structure（§1.3 加载期校验，validate 阶段调用）：
    只查结构形态（dict/list/字段类型），不查覆盖语义。"""

    def test_structured_passes(self):
        sd = {
            "inputs": [{"name": "x", "dtypes": ["float16", "float32"],
                        "rank": {"min": 1, "max": 8}},
                       {"name": "gamma", "dtypes": ["float16"], "rank": {"min": 1, "max": 1}}],
            "attrs": [{"name": "perm", "domain": {"kind": "permutation", "constraint": "any"}}],
        }
        assert validate_support_domain_structure(sd) == []

    def test_op_level_rank_rejected(self):
        """算子级 rank 直接拒绝——它无法表达张量间差异，正是本次事故的语义源头。"""
        sd = {"rank": {"min": 1, "max": 8},
              "inputs": [{"name": "x", "dtypes": ["float16"]}]}
        errors = validate_support_domain_structure(sd)
        assert any("不应有算子级 rank" in e and "inputs[].rank" in e for e in errors), errors

    def test_prose_rank_string_flagged(self):
        """gelu 场景：prose 字符串 rank → 结构错误。"""
        sd = {"inputs": [{"name": "x", "rank": "0..8（任意 shape，逐元素等价）"}]}
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
        assert "rank" not in d, f"rank 是张量属性，不得出现在算子级 domain：{d}"
        inputs = {i["name"]: i["dtypes"] for i in d.get("inputs", [])}
        ranks = {i["name"]: i.get("rank") for i in d.get("inputs", [])}
        assert ranks["x"] == {"min": 1, "max": 8}, ranks
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


# ---------------------------------------------------------------------------
# tensor_rank_domain / merged_input_entries — per-tensor 合法 rank 域单点
# ---------------------------------------------------------------------------
#
# 契约：`dimensions`（03_参数定义.yaml）表示「该张量允许的 rank 集合」，
# 必须由**该张量自己的**结构信号派生。历史缺陷形态：用符号 shape 的占位符
# 个数冒充 rank（含 '...' 时长度与 rank 无对应关系），校验侧又用 op 级
# `domain.rank`（语义上只是主输入的域）审判所有张量。fixture 全部为通用
# 标识符；代码路径不得因算子名分支（§1.12）。


_RANKED_REQ: dict = {
    "op_name": "sample_reduce_norm",
    "aclnn_name": "aclnnSampleReduceNorm",
    "inputs": [
        {"name": "main", "dtype": ["float16"],
         "shape": ["N_0", "...", "D_0", "..."],
         "shape_constraints": "rank(main) = m + k ∈ [2, 8]；后 k 维为归约维"},
        # 与 main 符号 shape 完全相同、自身无约束 → 结构化别名继承
        {"name": "residual", "dtype": ["float16"],
         "shape": ["N_0", "...", "D_0", "..."]},
        {"name": "scale", "dtype": ["float16"], "shape": ["D_0", "..."],
         "shape_constraints": "rank(scale) ∈ [1, 7] 且严格小于 rank(main)"},
        {"name": "bias", "dtype": ["float16"], "shape": ["C"],
         "shape_constraints": "1 维，numel == C"},
        {"name": "pool_idx", "dtype": ["int32"],
         "shape": ["N", "C", "D", "H", "W"],
         "shape_variants": [["N", "C", "D", "H", "W"], ["C", "D", "H", "W"]]},
        {"name": "fixed", "dtype": ["float16"], "shape": ["N", "C", "D", "H"]},
        {"name": "wild", "dtype": ["float16"], "shape": ["*"]},
        {"name": "wild2", "dtype": ["float16"], "shape": ["*"]},
    ],
    "domain": {
        "rank": {"min": 2, "max": 8},
        "inputs": [{"name": "main", "dtypes": ["float16"]}],
    },
}


def _add_structured_entry(req: dict, *, rank_site: str = "inputs") -> dict:
    """补一个带结构化 rank 声明的张量（措辞故意写错，用来证明结构化生效）。"""
    req = json.loads(json.dumps(req))
    entry = {"name": "structured", "dtype": ["float16"], "shape": ["A", "..."],
             "shape_constraints": "rank(structured) ∈ [1, 2]"}
    if rank_site == "inputs":
        entry["rank"] = {"min": 3, "max": 6}
        req["inputs"].append(entry)
    else:                                   # domain.inputs[] 形态
        req["inputs"].append(entry)
        req["domain"]["inputs"].append(
            {"name": "structured", "dtypes": ["float16"], "rank": {"min": 3, "max": 6}})
    return req


class TestTensorRankDomain:
    def test_structured_rank_on_input_entry_wins_over_prose(self):
        """inputs[].rank（结构化）优先于 shape_constraints 措辞。"""
        req = _add_structured_entry(_RANKED_REQ)
        assert tensor_rank_domain(req, "structured") == {"min": 3, "max": 6}

    def test_structured_rank_in_domain_inputs_also_honoured(self):
        """domain.inputs[].rank 同为结构化声明，一样生效。"""
        req = _add_structured_entry(_RANKED_REQ, rank_site="domain")
        assert tensor_rank_domain(req, "structured") == {"min": 3, "max": 6}

    def test_input_entry_rank_beats_domain_inputs_rank(self):
        """两处都写且冲突时，以张量条目自身为准（它描述这个张量）。"""
        req = _add_structured_entry(_RANKED_REQ, rank_site="domain")
        for e in req["inputs"]:
            if e["name"] == "structured":
                e["rank"] = {"min": 5, "max": 7}
        assert tensor_rank_domain(req, "structured") == {"min": 5, "max": 7}

    def test_design_spec_input_rank_honoured(self):
        """design_spec 的 inputs[].rank 同样可声明（合并后同源）。"""
        req = {"inputs": [{"name": "y", "dtype": ["float16"], "shape": ["A", "..."],
                           "shape_constraints": "rank(y) ∈ [1, 2]"}]}
        ds = {"inputs": [{"name": "y", "dtype": ["float16"],
                          "rank": {"min": 4, "max": 5}}]}
        assert tensor_rank_domain(req, "y", design_spec=ds) == {"min": 4, "max": 5}

    def test_shape_variants_give_rank_set(self):
        """shape_variants 是结构化备选 shape → rank 集合，优先于任何措辞。"""
        assert tensor_rank_domain(_RANKED_REQ, "pool_idx") == {"min": 4, "max": 5}

    def test_prose_range_parsed(self):
        assert tensor_rank_domain(_RANKED_REQ, "main") == {"min": 2, "max": 8}
        assert tensor_rank_domain(_RANKED_REQ, "scale") == {"min": 1, "max": 7}

    def test_prose_fixed_rank_parsed(self):
        """「1 维，…」这类固定 rank 表述 → {1,1}（张量名可不出现在句中）。"""
        assert tensor_rank_domain(_RANKED_REQ, "bias") == {"min": 1, "max": 1}

    def test_concrete_shape_gives_exact_rank(self):
        assert tensor_rank_domain(_RANKED_REQ, "fixed") == {"min": 4, "max": 4}

    def test_identical_symbolic_shape_inherits(self):
        """与已解析张量符号 shape 完全相同 → 继承其域（结构信号，不解析措辞）。"""
        assert tensor_rank_domain(_RANKED_REQ, "residual") == {"min": 2, "max": 8}

    def test_wildcard_without_evidence_is_unknown(self):
        """通配符形状（'*' / '...'）且无任何约束 → None（不臆造，§2.12）。

        互相同形的两个未解析张量不得互相递归成环。
        """
        assert tensor_rank_domain(_RANKED_REQ, "wild") is None
        assert tensor_rank_domain(_RANKED_REQ, "wild2") is None

    def test_unknown_name_returns_none(self):
        assert tensor_rank_domain(_RANKED_REQ, "no_such_tensor") is None

    def test_design_spec_shape_overrides_for_resolution(self):
        """design_spec 的具体 shape 覆盖符号 shape → 可解析出精确 rank。"""
        req = {"inputs": [{"name": "y", "dtype": ["float16"], "shape": ["..."]}]}
        ds = {"inputs": [{"name": "y", "dtype": ["float16"], "shape": ["N", "C", "H", "W"]}]}
        assert tensor_rank_domain(req, "y", design_spec=ds) == {"min": 4, "max": 4}


class TestMergedInputEntries:
    def test_design_spec_non_empty_values_override(self):
        req = {"inputs": [{"name": "y", "dtype": ["float16"], "shape": ["..."],
                           "shape_constraints": "rank(y) ∈ [2, 8]"}]}
        ds = {"inputs": [{"name": "y", "dtype": ["float16"], "shape": ["N", "C"],
                          "semantic": ""}]}
        merged = merged_input_entries(req, ds)
        assert merged["y"]["shape"] == ["N", "C"]           # ds 非空值覆盖
        assert merged["y"]["shape_constraints"] == "rank(y) ∈ [2, 8]"   # 空值不覆盖

    def test_entries_keep_all_inputs(self):
        merged = merged_input_entries(_RANKED_REQ)
        assert set(merged) == {e["name"] for e in _RANKED_REQ["inputs"]}


class TestLegacyOpLevelRank:
    """算子级 rank 已废弃：不参与对质，但不得静默丢弃（§1.2 可诊断）。"""

    def test_op_level_rank_ignored_with_warning(self, caplog):
        req = {"domain": {"rank": {"min": 2, "max": 8},
                          "inputs": [{"name": "x", "dtypes": ["float16"]}]}}
        with caplog.at_level(logging.WARNING, logger="ascendc_devkit.domain.support_domain"):
            requirement_domain(req)
        messages = [r.getMessage() for r in caplog.records]
        assert any("已被忽略" in m and "inputs[].rank" in m for m in messages), messages

    def test_op_level_rank_not_used_for_gap_check(self):
        """旧产物只有算子级 rank → rank 轴跳过，不产生假阳性缺口。"""
        req = {"domain": {"rank": {"min": 2, "max": 8},
                          "inputs": [{"name": "x", "dtypes": ["float16"]}]}}
        design = {"inputs": [{"name": "x", "dtypes": ["float16"]}]}
        assert domain_covers(requirement_domain(req), design) == []
