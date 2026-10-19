"""Deterministic tests for the A5 VECTOR_ERROR P1 static rule layer."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[3]
_SCRIPT = (
    _REPO
    / ".claude/skills/ascendc-precision-vector-error-debug/scripts"
    / "scan_a5_vector_risks.py"
)


def _load_scanner():
    spec = importlib.util.spec_from_file_location("a5_vector_risk_scanner", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


scanner = _load_scanner()


_BAD_SOURCE = r"""
// DataCopy(commentOnlyDst, commentOnlySrc); must not be scanned
/* StoreUnAlignPost(commentOnlyDst, commentOnlyReg); */

__simd_vf__ inline void BrokenVF(
    __ubuf__ float* dst, __ubuf__ float* src, uint32_t remain)
{
    RegTensor<float> reg;
    MaskReg predicate = UpdateMask<float>(remain);
    UnalignRegForLoad loadState;
    UnalignRegForStore storeState;
    LoadUnAlign(reg, loadState, src);
    StoreUnAlign(dst, reg, storeState, 1);
    auto address = CreateAddrReg<float>(remain, 64);
    Cast<float, half, castTrait>(reg, reg, predicate);
    LoadAlign<float, LoadDist::DIST_DINTLV_B32>(reg, src, address);
    StoreAlign(dst, reg, predicate);
    StoreAlign(dst, reg, remain);
    LoadAlign(reg, dst);
    DataCopy(dst, src, remain);
    TQue<TPosition::VECIN, 1> illegalQueue;
}

__simd_vf__ int BadSignature(__ubuf__ float* src, uint32_t& count)
{
    return count;
}

__aicore__ inline void CallBroken()
{
    LocalTensor<float> local;
    VF_CALL<BrokenVF>(local, 64);
}

TQue<TPosition::VECIN, 1> inputQueue;
void QueuePath()
{
    auto tensor = inputQueue.AllocTensor<float>();
    inputQueue.EnQue(tensor);
}

void SyncPath()
{
    CrossCoreSetFlag<0x2, PIPE_MTE3>(3);
    TBuf<TPosition::TSCM> sharedBuffer;
    uint32_t tailCount = GetBlockIdx() == GetBlockNum() - 1 ? 3 : 64;
}
"""


_SAFE_SOURCE = r"""
// LoadUnAlign(reg, state, src);
// StoreUnAlign(dst, reg, state);
const char* ignored = "DataCopy(dst, src, 999)";

__simd_vf__ inline void SafeVF(
    __ubuf__ float* dst, __ubuf__ float* src, uint32_t count)
{
    RegTensor<float> reg;
    MaskReg mask = UpdateMask<float>(count);
    UnalignRegForLoad loadState;
    UnalignRegForStore storeState;
    LoadUnAlignPre(loadState, src);
    LoadUnAlign(reg, loadState, src);
    StoreUnAlign(dst, reg, storeState, 1);
    StoreUnAlignPost(dst, storeState, 1);
    StoreAlign(dst, reg, mask);
    LocalMemBar<MemType::VEC_STORE, MemType::VEC_LOAD>();
    LoadAlign(reg, dst);
}

TQue<TPosition::VECIN, 1> inputQueue;
void CompleteQueuePath()
{
    auto tensor = inputQueue.AllocTensor<float>();
    inputQueue.EnQue(tensor);
    auto consumed = inputQueue.DeQue<float>();
    inputQueue.FreeTensor(consumed);
}

void CompleteEventPath()
{
    CrossCoreSetFlag<0x2, PIPE_MTE3>(3);
    CrossCoreWaitFlag(3);
}

__aicore__ inline void CallSafe()
{
    LocalTensor<float> local;
    VF_CALL<SafeVF>((__ubuf__ float*)local.GetPhyAddr(), 64);
}
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_bad_source_covers_all_a5_generic_fault_domains(tmp_path: Path):
    source = _write(tmp_path / "op_kernel" / "bad.cpp", _BAD_SOURCE)
    result = scanner.scan_sources(explicit_sources=[source])

    subtypes = {item["subtype"] for item in result["static_findings"]}
    assert {
        "gm_ub_transport",
        "ub_reg_load_store",
        "mask_tail",
        "address_generation",
        "layout_cast_dist",
        "vf_call_abi",
        "incore_sync",
        "queue_lifecycle",
        "crosscore_tscm",
        "tiling_boundary",
    } <= subtypes

    suspected_rules = {
        item["rule_id"]
        for item in result["static_findings"]
        if item["status"] == "suspected"
    }
    assert {
        "A5-LS-002",
        "A5-LS-003",
        "A5-LS-004",
        "A5-VF-001",
        "A5-VF-002",
        "A5-VF-003",
        "A5-QUEUE-002",
        "A5-QUEUE-003",
        "A5-CROSS-001",
    } <= suspected_rules
    assert all(item["status"] in {"candidate", "suspected"}
               for item in result["static_findings"])
    assert result["summary"]["root_cause_confirmed"] is False


def test_comments_strings_and_complete_protocols_do_not_create_suspicions(
    tmp_path: Path,
):
    source = _write(tmp_path / "safe.cpp", _SAFE_SOURCE)
    result = scanner.scan_sources(explicit_sources=[source])

    assert not [
        item for item in result["static_findings"]
        if item["status"] == "suspected"
    ]
    evidence = "\n".join(item["evidence"] for item in result["static_findings"])
    assert "commentOnly" not in evidence
    assert "999" not in evidence
    assert not {
        "A5-LS-002", "A5-LS-003", "A5-QUEUE-002",
        "A5-QUEUE-003", "A5-CROSS-001",
    } & {item["rule_id"] for item in result["static_findings"]}


def test_schema_and_sorting_are_stable(tmp_path: Path):
    source = _write(tmp_path / "kernel.cpp", _BAD_SOURCE)
    first = scanner.scan_sources(explicit_sources=[source])
    second = scanner.scan_sources(explicit_sources=[source])
    assert first == second
    assert first["schema_version"] == "1.0"
    assert first["scanned_files"] == ["kernel.cpp"]

    ranking = first["candidate_ranking"]
    assert [item["rank"] for item in ranking] == list(range(1, len(ranking) + 1))
    assert [item["final_score"] for item in ranking] == sorted(
        (item["final_score"] for item in ranking), reverse=True
    )
    required = {
        "rule_id", "fault_domain", "subtype", "file", "line", "api",
        "symbol", "evidence", "reason", "confidence", "base_score",
        "final_score", "status", "reference",
    }
    assert all(required <= item.keys() for item in first["static_findings"])
    assert all(0 <= item["base_score"] <= 100 for item in ranking)
    assert all(0 <= item["final_score"] <= 100 for item in ranking)


def test_p0_evidence_boosts_relevant_candidates_without_pc_mapping(
    tmp_path: Path,
):
    source = _write(
        tmp_path / "sync.cpp",
        """
__simd_vf__ inline void Hazard(__ubuf__ float* ptr) {
  RegTensor<float> reg;
  MaskReg mask;
  StoreAlign(ptr, reg, mask);
  LoadAlign(reg, ptr);
}
TQue<TPosition::VECIN, 1> q;
""",
    )
    baseline = scanner.scan_sources(explicit_sources=[source])
    evidence = {
        "vector_error_evidence": {
            "kernel_name": "kernel_x",
            "pc_offset": "0x88",
            "source_phase": "finalize",
            "buffer_mode": "double",
            "reproducibility": "intermittent",
        }
    }
    boosted = scanner.scan_sources(explicit_sources=[source], evidence=evidence)

    def score(result, subtype):
        return max(
            item["final_score"] for item in result["candidate_ranking"]
            if item["subtype"] == subtype
        )

    assert score(boosted, "incore_sync") == score(baseline, "incore_sync") + 18
    assert score(boosted, "queue_lifecycle") == score(baseline, "queue_lifecycle") + 18
    assert boosted["classification"]["evidence_quality"] == "pc_mapped"
    assert all("PC maps to" not in item["reason"]
               for item in boosted["candidate_ranking"])


def test_operator_cli_excludes_generated_dirs_uses_relative_paths_and_is_read_only(
    tmp_path: Path,
):
    operator = tmp_path / "operator"
    source = _write(operator / "op_kernel" / "kernel.cpp", _SAFE_SOURCE)
    _write(operator / "build" / "generated.cpp", _BAD_SOURCE)
    _write(operator / "output" / "generated.cpp", _BAD_SOURCE)
    _write(operator / ".git" / "hidden.cpp", _BAD_SOURCE)
    evidence = operator / "checkpoint.json"
    evidence.write_text(json.dumps({
        "vector_error_evidence": {
            "error_code": "507035",
            "fault_va": "0x1000",
            "source_phase": "vf_test",
        }
    }), encoding="utf-8")
    output = tmp_path / "scan.json"
    before = hashlib.sha256(source.read_bytes()).hexdigest()

    completed = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--operator-dir", str(operator),
            "--evidence", str(evidence),
            "--output", str(output),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    stdout_result = json.loads(completed.stdout)
    file_result = json.loads(output.read_text(encoding="utf-8"))

    assert stdout_result == file_result
    assert stdout_result["scanned_files"] == ["op_kernel/kernel.cpp"]
    assert all(item["file"] == "op_kernel/kernel.cpp"
               for item in stdout_result["static_findings"])
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert stdout_result["classification"]["evidence_quality"] == "partial"


def test_explicit_source_cli_outputs_json(tmp_path: Path):
    source = _write(tmp_path / "one.h", _SAFE_SOURCE)
    completed = subprocess.run(
        [sys.executable, str(_SCRIPT), "--source", str(source)],
        check=True,
        text=True,
        capture_output=True,
    )
    result = json.loads(completed.stdout)
    assert result["scanned_files"] == ["one.h"]
    assert result["summary"]["scanned_file_count"] == 1


def test_maskreg_store_with_addrreg_is_not_reported_as_missing_mask(
    tmp_path: Path,
):
    source = _write(
        tmp_path / "mask_store.cpp",
        """
__simd_vf__ inline void StoreMask(__ubuf__ uint8_t* dst) {
  MaskReg mask;
  AddrReg offset;
  StoreAlign(dst, mask, offset);
}
""",
    )
    result = scanner.scan_sources(explicit_sources=[source])
    assert not [
        item for item in result["static_findings"]
        if item["rule_id"] == "A5-LS-004"
    ]


def test_nested_phase_result_evidence_participates_in_ranking(
    tmp_path: Path,
):
    source = _write(
        tmp_path / "nested_evidence.cpp",
        """
__simd_vf__ inline void Load(__ubuf__ float* src) {
  RegTensor<float> reg;
  LoadAlign(reg, src);
}
""",
    )
    payload = {
        "error_type": "PREC",
        "precision_result": {
            "failed_cases": [{
                "failure_type": "VECTOR_ERROR",
                "runtime_evidence": {
                    "kernel_name": "Load",
                    "pc_offset": "0x20",
                    "error_code": "507035",
                    "source_phase": "vf_test",
                    "exception_type": "vector core exception",
                },
            }],
        },
    }
    result = scanner.scan_sources(
        explicit_sources=[source], evidence=payload
    )
    assert result["classification"]["evidence_quality"] == "pc_mapped"
    load = next(
        item for item in result["candidate_ranking"]
        if item["rule_id"] == "A5-LS-001"
    )
    assert load["final_score"] > load["base_score"]
