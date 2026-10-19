"""Unit tests for L2 op_dir resolver (§9 verification plan)."""

import pytest

from ascendc_devkit.application.op_dir_resolver import (
    resolve_op_dir, OpDirResolveError,
)


KNOWN = ["omni-ops", "ops-nn", "ops-transformer"]


class TestResolveRealRopePath:
    def test_omni_inference_rope(self):
        op_dir = ("/home/x00584171/code/omni-ops/inference/ascendc/src/"
                  "ops-transformer/posembedding/ai_infra_kv_rms_norm_rope_cache")
        r = resolve_op_dir(op_dir, known_profiles=KNOWN)
        assert r.profile_name == "omni-ops"
        assert r.repo_root == "/home/x00584171/code/omni-ops"
        assert r.rel_op_dir == ("inference/ascendc/src/ops-transformer/"
                                "posembedding/ai_infra_kv_rms_norm_rope_cache")
        assert r.full_op_name == "ai_infra_kv_rms_norm_rope_cache"
        assert r.op_name == "kv_rms_norm_rope_cache"
        assert r.variant_name == "inference"
        assert r.confidence == "matched"

    def test_omni_training_variant(self):
        op_dir = "/home/x/omni-ops/training/ascendc/src/grp/cat/ai_infra_foo"
        r = resolve_op_dir(op_dir, known_profiles=KNOWN)
        assert r.variant_name == "training"
        assert r.op_name == "foo"

    def test_mainline_no_prefix(self):
        op_dir = "/data/ops-nn/conv/conv3d"
        r = resolve_op_dir(op_dir, known_profiles=KNOWN)
        assert r.profile_name == "ops-nn"
        assert r.full_op_name == "conv3d"
        assert r.op_name == "conv3d"
        assert r.variant_name == "default"


class TestFallback:
    def test_renamed_repo_needs_override(self):
        op_dir = "/home/x/my-fork/inference/ascendc/src/g/c/ai_infra_rope"
        with pytest.raises(OpDirResolveError):
            resolve_op_dir(op_dir, known_profiles=KNOWN)

    def test_unmatched_with_repo_root_only_still_raises(self):
        """repo_root_override pins the repo PATH but does NOT substitute for the
        profile (downstream needs the profile object). Unmatched path + only
        repo_root (no profile_override) → raise at the resolution layer (§1.3 /
        §1.2 — fail here, not silently as profile_name='' downstream). This is
        the批跑 case: worktree checked out under cann-bench-batch/<ts>/<op>/ →
        path segment 'cann-bench-batch' matches no known profile."""
        op_dir = "/home/x/cann-bench-batch/20260715/advance_step_v2/examples/ops/advance_step_v2"
        with pytest.raises(OpDirResolveError):
            resolve_op_dir(
                op_dir, known_profiles=KNOWN,
                repo_root_override="/home/x/cann-bench-batch/20260715/advance_step_v2",
            )

    def test_unmatched_with_profile_override_resolves(self):
        """profile_override is the legitimate escape hatch: an unmatched path +
        an explicit profile resolves cleanly (repo_root pins the root). This is
        how批跑 should declare its profile (manifest task repo_profile: cann-bench)."""
        wt = "/home/x/cann-bench-batch/20260715/op"
        op_dir = f"{wt}/examples/aclnn_launch_example/csrc/ops/op"
        r = resolve_op_dir(
            op_dir, known_profiles=["cann-bench"],
            profile_override="cann-bench",
            repo_root_override=wt,
        )
        assert r.profile_name == "cann-bench"
        assert r.repo_root == wt
        assert r.rel_op_dir == "examples/aclnn_launch_example/csrc/ops/op"
        assert r.confidence == "matched"

    def test_renamed_repo_with_profile_and_root_override(self):
        op_dir = "/home/x/my-fork/inference/ascendc/src/g/c/ai_infra_rope"
        r = resolve_op_dir(
            op_dir, known_profiles=KNOWN,
            profile_override="omni-ops",
            repo_root_override="/home/x/my-fork",
        )
        assert r.profile_name == "omni-ops"
        assert r.repo_root == "/home/x/my-fork"
        assert r.rel_op_dir == "inference/ascendc/src/g/c/ai_infra_rope"
        assert r.variant_name == "inference"
        assert r.op_name == "rope"

    def test_multi_segment_hit_flagged_then_resolved_with_root_override(self):
        # repo name appears twice (nested checkout): the shallowest hit is the
        # default boundary but ambiguity is flagged so the caller can confirm.
        op_dir = "/work/omni-ops/x/omni-ops/inference/ascendc/src/g/c/ai_infra_rope"
        # Without an override, the shallowest boundary makes rel_op_dir start
        # with the inner 'x/omni-ops/...', matching no variant → error.
        with pytest.raises(OpDirResolveError):
            resolve_op_dir(op_dir, known_profiles=KNOWN)
        # Confirming the real (inner) repo root resolves cleanly.
        r = resolve_op_dir(
            op_dir, known_profiles=KNOWN,
            repo_root_override="/work/omni-ops/x/omni-ops",
            profile_override="omni-ops",
        )
        assert r.repo_root == "/work/omni-ops/x/omni-ops"
        assert r.variant_name == "inference"

    def test_nested_checkout_confidence_is_ambiguous(self):
        from ascendc_devkit.application.op_dir_resolver import _identify_profile, _segments
        segs = _segments("/work/omni-ops/x/omni-ops/inference/ascendc/src/g/c/ai_infra_rope")
        name, idx, conf = _identify_profile(segs, KNOWN)
        assert conf == "ambiguous"
        assert name == "omni-ops"


class TestErrors:
    def test_empty_op_dir(self):
        with pytest.raises(OpDirResolveError):
            resolve_op_dir("", known_profiles=KNOWN)

    def test_no_variant_match(self):
        # known repo but op_dir under a tree no variant matches
        op_dir = "/home/x/omni-ops/some/other/tree/ai_infra_rope"
        with pytest.raises(OpDirResolveError):
            resolve_op_dir(op_dir, known_profiles=KNOWN)

    def test_unknown_profile_override_raises(self):
        """A profile_override naming a profile with NO installed YAML → raise
        at the resolution layer (§1.3 加载期校验), not silently return and let
        downstream context hit FileNotFoundError again → profile=None degrade.
        Covers both a misspelled override and a path-matched name whose YAML
        isn't installed."""
        op_dir = ("/home/x/cann-bench-batch/20260715/op/"
                  "examples/aclnn_launch_example/csrc/ops/op")
        with pytest.raises(OpDirResolveError):
            resolve_op_dir(
                op_dir, known_profiles=KNOWN,
                profile_override="no-such-profile-installed",
                repo_root_override="/home/x/cann-bench-batch/20260715/op",
            )
