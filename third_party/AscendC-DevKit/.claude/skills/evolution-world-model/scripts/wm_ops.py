#!/usr/bin/env python3
"""
wm_ops.py — World Model CLI operations for evolution.

CLI subcommands:
  select          --path <wm.json> --n <int>      Select top-N open nodes by utility score
  validate        --path <wm.json>                Validate invariants (non-zero exit = errors)
  summary         --path <wm.json> [--max-chars 1200]  Compact summary for sub-agent injection
  deep-profiling  --wm-path <wm.json> --node-id <id> --work-dir <dir> --op-name <name>
                  Run deep profiling analysis and write evidence to world model
"""

import argparse
import json
import subprocess
import sys
from typing import Any


# ---------------------------------------------------------------------------
# Core algorithm: utility computation
# ---------------------------------------------------------------------------

def compute_utility(node: dict, nodes: dict) -> float:
    """Compute utility score for a given node using the unified world model formula.

    Unified formula (authoritative — all other docs reference this):
        utility = 3.0 × parent_score
                + 2.5 × (5 - difficulty)
                + 0.75 × depth
                + w_root_explore   (2.0 if parent is root, else 0.0)
                + w_evidence       (1.5 if parent has profiling_evidence, else 0.0)

    Rationale for each term:
        parent_score:    Exploit — children of high-performing nodes are more promising
        difficulty:      Prefer easier implementations first (low-hanging fruit)
        depth:           Mild encouragement for depth-first exploitation
        w_root_explore:  Ensure first-layer breadth is explored before deep-diving
        w_evidence:      Prioritize nodes whose parent has instruction-level profiling
                         (higher-confidence strategy recommendations)
    """
    parent_id = node.get("parent_id") or "root"
    parent = nodes.get(parent_id, {})
    parent_score = parent.get("score") or 1.0
    difficulty = node.get("difficulty", 3)
    depth = node.get("depth", 1)
    w_root_explore = 2.0 if parent_id == "root" else 0.0
    w_evidence = 1.5 if parent.get("profiling_evidence") else 0.0
    return (3.0 * parent_score
            + 2.5 * (5 - difficulty)
            + 0.75 * depth
            + w_root_explore
            + w_evidence)


# ---------------------------------------------------------------------------
# Optimization type inference
# ---------------------------------------------------------------------------

_BANDWIDTH_STRATEGIES = frozenset({
    "P1", "P7", "P10", "P11", "R5",
    # P19-P26: buffer management + DataCopy params
    "P19", "P20", "P21", "P22",
    "P24", "P25", "P26",
    # P32-P33: special copy patterns
    "P32", "P33",
    # P34-P45: buffer resident / reuse
    "P34", "P35", "P37", "P38", "P40",
    "P41", "P42", "P43", "P44",
    "P45",
    # P49, P52: hardware dequant, L2 cache hint
    "P49", "P52",
    # P53-P88: bandwidth-related (data movement, format, buffer, cache)
    "P53", "P56", "P59", "P60", "P61", "P63",
    "P64", "P65", "P66", "P69", "P70", "P71",
    "P74", "P76", "P78", "P81", "P83", "P85",
})
_TILING_STRATEGIES = frozenset({
    "P2", "P4", "P5", "P8",
    # P28-P30: sync & pipeline control
    "P28", "P29", "P30",
    # P47, P51: diagonal scheduling, dynamic core ratio
    "P47", "P51",
    # P53-P88: tiling-related (sync, partition, pipeline, core ratio)
    "P54", "P55", "P57", "P58", "P67", "P68",
    "P72", "P73", "P75", "P77", "P80", "P82",
    "P84", "P86", "P87", "P88",
})

_VALID_STRATEGY_IDS = frozenset({
    # D-series
    "D1", "D2", "D3", "D4", "D5",
    # P-series L0
    "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10", "P11", "P12", "P13",
    # P-series L1 (P14-P52)
    "P14", "P16", "P17", "P18",
    "P19", "P20", "P21", "P22",
    "P24", "P25", "P26",
    "P28", "P29", "P30",
    "P32", "P33",
    "P34", "P35", "P37", "P38",
    "P40", "P41", "P42", "P43", "P44", "P45",
    "P46", "P47", "P48", "P49", "P50", "P51", "P52",
    # P-series L1 (P53-P88, fork-B incremental)
    "P53", "P54", "P55", "P56",
    "P57", "P58",
    "P59", "P60", "P61", "P62", "P63", "P64", "P65", "P66",
    "P67", "P68", "P69",
    "P70", "P71", "P72",
    "P73", "P74", "P75",
    "P76", "P77", "P78",
    "P79", "P80", "P81", "P82", "P83", "P84",
    "P85", "P86", "P87", "P88",
    # A-series
    "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8",
    # X-series (discovered)
    "X1",
})
_REGISTER_OPT_STRATEGIES = frozenset({"R2"})
_VF_FUSION_STRATEGIES = frozenset({"R1"})
_INSTRUCTION_SCHED_STRATEGIES = frozenset({"R3", "R4", "R8"})


def infer_optimization_type(strategy_combination: list, mode: str = "strategy_guided") -> str:
    """Infer the performance optimization type from strategy combination.

    Returns one of: "bandwidth", "tiling", "algorithm",
    "register_opt", "vf_fusion", "instruction_sched".
    D/A-series strategies are ignored (precision constraints, not perf directions).
    P19-P88 (data movement / CV fusion / advanced) are classified as bandwidth, tiling (sync),
    or algorithm (default).
    A5 R-series strategies map to register_opt/vf_fusion/instruction_sched/bandwidth/algorithm.
    """
    if mode in ("open_exploration", "profiling_driven"):
        return "algorithm"
    s = set(strategy_combination) if strategy_combination else set()
    bw = len(s & _BANDWIDTH_STRATEGIES)
    tl = len(s & _TILING_STRATEGIES)
    ro = len(s & _REGISTER_OPT_STRATEGIES)
    vf = len(s & _VF_FUSION_STRATEGIES)
    isc = len(s & _INSTRUCTION_SCHED_STRATEGIES)
    counts = {"bandwidth": bw, "tiling": tl, "register_opt": ro,
              "vf_fusion": vf, "instruction_sched": isc}
    best_type = max(counts, key=counts.get)
    if counts[best_type] > 0:
        return best_type
    return "algorithm"


# ---------------------------------------------------------------------------
# select
# ---------------------------------------------------------------------------

def select_nodes(wm: dict, n: int) -> list:
    """
    Select top-N open nodes by utility score with open_exploration slot reservation.

    Slot allocation (matches lingxi-dsl-evo/SKILL.md §4.0):
      - Slots 0 .. (n-2):  strategy_guided nodes, sorted by utility descending
      - Slot (n-1):         reserved for the highest-utility open_exploration node
                            (falls back to next strategy_guided if none available)

    If n == 1, the single slot goes to the highest-utility node regardless of mode.

    Pads with free-exploration placeholders if open nodes are insufficient.

    Returns a list of dicts with parallel_index, node_id, utility, mode, and
    all node fields needed for prompt construction.
    """
    nodes: dict = wm.get("decision_tree", {}).get("nodes", {})
    open_nodes = [
        (nid, nd) for nid, nd in nodes.items()
        if nd.get("status") == "open"
    ]

    # Split by mode
    strategy_guided = []
    open_exploration = []  # includes both open_exploration and profiling_driven
    for nid, nd in open_nodes:
        mode = nd.get("mode", "strategy_guided")
        if mode in ("open_exploration", "profiling_driven"):
            open_exploration.append((nid, nd))
        else:
            strategy_guided.append((nid, nd))

    # Sort each group by utility descending
    strategy_guided.sort(key=lambda x: -compute_utility(x[1], nodes))
    open_exploration.sort(key=lambda x: -compute_utility(x[1], nodes))

    selected: list[tuple[str, dict]] = []

    if n == 1:
        # Single slot: pick the overall best regardless of mode
        all_sorted = sorted(open_nodes, key=lambda x: -compute_utility(x[1], nodes))
        if all_sorted:
            selected.append(all_sorted[0])
    else:
        sg_slots = n - 1

        # --- Guaranteed round: each optimization type with open nodes gets 1 slot ---
        type_best: dict[str, tuple[str, dict]] = {}
        for nid, nd in strategy_guided:
            t = nd.get("optimization_type") or infer_optimization_type(
                nd.get("strategy_combination", []),
                nd.get("mode", "strategy_guided"),
            )
            if t not in type_best:
                type_best[t] = (nid, nd)  # strategy_guided already sorted desc

        selected_sg: list[tuple[str, dict]] = []
        used_ids: set[str] = set()
        # Guaranteed round: each optimization type with open nodes gets 1 slot
        # Covers A3 types (bandwidth, tiling, algorithm) and A5 types
        # (register_opt, vf_fusion, instruction_sched)
        for t in type_best:
            if len(selected_sg) < sg_slots:
                nid, nd = type_best[t]
                selected_sg.append((nid, nd))
                used_ids.add(nid)

        # --- Remaining slots: pure utility-driven, no type constraint ---
        for nid, nd in strategy_guided:
            if len(selected_sg) >= sg_slots:
                break
            if nid not in used_ids:
                selected_sg.append((nid, nd))
                used_ids.add(nid)

        selected.extend(selected_sg)

        # --- open_exploration dedicated slot (unchanged logic) ---
        available_oe = [(nid, nd) for nid, nd in open_exploration if nid not in used_ids]
        if available_oe:
            selected.append(available_oe[0])
        else:
            remaining_sg = [(nid, nd) for nid, nd in strategy_guided if nid not in used_ids]
            if remaining_sg:
                selected.append(remaining_sg[0])

    # Pad with free-exploration placeholders if still not enough
    while len(selected) < n:
        idx = len(selected)
        selected.append((
            f"free_{idx}",
            {
                "id": f"free_{idx}",
                "mode": "strategy_guided",
                "status": "open",
                "strategy_combination": [],
                "description": "自由探索方向，基于已有经验选择多样化策略",
                "parent_id": "root",
                "difficulty": 3,
                "depth": 1,
                "score": None,
                "solution_ref": None,
                "parent_code_ref": None,
                "children": [],
            }
        ))

    result = []
    for i, (nid, nd) in enumerate(selected):
        parent_id = nd.get("parent_id") or "root"
        parent_node = nodes.get(parent_id, {})
        parent_score = parent_node.get("score") or 1.0
        parent_solution_ref = parent_node.get("solution_ref")  # may be None
        # Resolve parent profiling one-liner
        pi = parent_node.get("profiling_insight")
        parent_profiling_one_liner = (
            pi.get("profiling_one_liner") if isinstance(pi, dict) else None
        )

        entry = {
            "parallel_index": i,
            "node_id": nid,
            "utility": round(compute_utility(nd, nodes), 4),
            "mode": nd.get("mode", "strategy_guided"),
            "description": nd.get("description", ""),
            "strategy_combination": nd.get("strategy_combination", []),
            "parent_id": parent_id,
            "parent_score": parent_score,
            "parent_solution_ref": parent_solution_ref,
            "parent_profiling_one_liner": parent_profiling_one_liner,
            "difficulty": nd.get("difficulty", 3),
            "depth": nd.get("depth", 1),
        }
        result.append(entry)

    return result


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

def validate(wm: dict) -> list[str]:
    """
    Validate world model invariants.

    Returns a list of error strings. Empty list means valid.

    Invariants checked:
      1. All parent_id values point to existing nodes
      2. best_score >= 1.0
      3. status values are legal
      4. All passed nodes have at least 1 open child (continuation invariant)
      5. stagnation_count and stagnation_count_vs_base are non-negative integers
    """
    errors: list[str] = []
    nodes: dict = wm.get("decision_tree", {}).get("nodes", {})
    legal_statuses = {"open", "in_progress", "passed", "failed", "completed"}

    # Invariant 1: parent_id references
    for nid, nd in nodes.items():
        pid = nd.get("parent_id")
        if pid is not None and pid not in nodes:
            errors.append(
                f"Invariant 1 FAIL: node '{nid}' has parent_id='{pid}' "
                f"which does not exist in nodes"
            )

    # Invariant 2: best_score >= 1.0
    best_score = wm.get("best_score", 1.0)
    if best_score is None or best_score < 1.0:
        errors.append(
            f"Invariant 2 FAIL: best_score={best_score} is less than 1.0"
        )

    # Invariant 3: legal status values
    for nid, nd in nodes.items():
        status = nd.get("status")
        if status not in legal_statuses:
            errors.append(
                f"Invariant 3 FAIL: node '{nid}' has illegal status='{status}'"
            )

    # Invariant 4: passed nodes must have >= 1 open descendant (continuation)
    # (Only applies to non-root passed nodes that are not leaf of a termination)
    all_open_ids = {nid for nid, nd in nodes.items() if nd.get("status") == "open"}
    for nid, nd in nodes.items():
        if nd.get("status") == "passed":
            children_ids = nd.get("children", [])
            has_open_child = any(cid in all_open_ids for cid in children_ids)
            # Also check recursively for open descendants
            if children_ids and not has_open_child:
                # Check if any descendant is open (breadth-first)
                queue = list(children_ids)
                found = False
                visited: set[str] = set()
                while queue and not found:
                    cid = queue.pop(0)
                    if cid in visited:
                        continue
                    visited.add(cid)
                    cnode = nodes.get(cid, {})
                    if cnode.get("status") == "open":
                        found = True
                    queue.extend(cnode.get("children", []))
                if not found:
                    errors.append(
                        f"Invariant 4 FAIL: passed node '{nid}' has no open "
                        f"descendant (continuation invariant violated)"
                    )

    # Invariant 5: stagnation counters are non-negative integers
    for key in ("stagnation_count", "stagnation_count_vs_base"):
        val = wm.get(key)
        if not isinstance(val, int) or val < 0:
            errors.append(
                f"Invariant 5 FAIL: '{key}'={val!r} is not a non-negative integer"
            )

    # Invariant 6: profiling_evidence field structure validation
    for nid, nd in nodes.items():
        pe = nd.get("profiling_evidence")
        if pe is not None:
            if not isinstance(pe, dict):
                errors.append(
                    f"Invariant 6 FAIL: node '{nid}' has profiling_evidence "
                    f"that is not a dict: {type(pe).__name__}"
                )
            else:
                required_keys = {"bottleneck_type", "suggested_strategies"}
                missing = required_keys - set(pe.keys())
                if missing:
                    errors.append(
                        f"Invariant 6 FAIL: node '{nid}' profiling_evidence "
                        f"missing required keys: {missing}"
                    )
                legal_bottlenecks = {
                    "mte2_stall", "mte3_stall", "tiling_imbalance",
                    "scalar_loading", "scalar_compute",
                    "compute_bound", "near_optimal",
                    "no_overlap", "partial_overlap",
                    "undersize_transfer", "bus_contention", "icache_miss",
                }
                bt = pe.get("bottleneck_type")
                if bt and bt not in legal_bottlenecks:
                    errors.append(
                        f"Invariant 6 FAIL: node '{nid}' profiling_evidence "
                        f"has illegal bottleneck_type='{bt}'"
                    )

    # Invariant 7: optimization_type values are legal (if present)
    legal_opt_types = {"bandwidth", "tiling", "algorithm",
                        "register_opt", "vf_fusion", "instruction_sched"}
    for nid, nd in nodes.items():
        ot = nd.get("optimization_type")
        if ot is not None and ot not in legal_opt_types:
            errors.append(
                f"Invariant 7 FAIL: node '{nid}' has illegal "
                f"optimization_type='{ot}'"
            )

    return errors


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------

def _find_best_path(wm: dict) -> str:
    """Trace the best path from root to the highest-scoring passed node."""
    nodes: dict = wm.get("decision_tree", {}).get("nodes", {})

    # Find node with best score
    best_nid = None
    best_score = -1.0
    for nid, nd in nodes.items():
        sc = nd.get("score")
        if sc is not None and sc > best_score:
            best_score = sc
            best_nid = nid

    if best_nid is None:
        return "root(baseline)"

    # Trace path from best node up to root
    path = []
    current = best_nid
    while current is not None:
        nd = nodes.get(current, {})
        sc = nd.get("score")
        label = f"{current}({sc:.2f}x)" if sc is not None else current
        path.append(label)
        current = nd.get("parent_id")

    path.reverse()
    return " → ".join(path)


def _count_unexplored_root_branches(wm: dict) -> str:
    """Summarize root's direct children that are still open."""
    nodes: dict = wm.get("decision_tree", {}).get("nodes", {})
    root = nodes.get("root", {})
    open_children = []
    for cid in root.get("children", []):
        cnode = nodes.get(cid, {})
        if cnode.get("status") == "open":
            strats = "+".join(cnode.get("strategy_combination", []) or ["free"])
            open_children.append(f"{cid}({strats})")
    return ", ".join(open_children) if open_children else "(none)"


def summary(wm: dict, max_chars: int = 1200) -> str:
    """
    Generate a compact world model summary for sub-agent prompt injection.

    Output is plain text, ≤ max_chars characters.
    """
    nodes: dict = wm.get("decision_tree", {}).get("nodes", {})
    open_count = sum(1 for nd in nodes.values() if nd.get("status") == "open")
    passed_count = sum(1 for nd in nodes.values() if nd.get("status") == "passed")
    failed_count = sum(1 for nd in nodes.values() if nd.get("status") == "failed")

    stagnation_count = wm.get("stagnation_count", 0)
    stagnation_window = wm.get("stagnation_window", 2)
    best_score = wm.get("best_score", 1.0)
    kernel_summary = wm.get("kernel_summary", "N/A")
    open_questions = wm.get("open_questions", [])

    active_path = _find_best_path(wm)
    unexplored_roots = _count_unexplored_root_branches(wm)

    lines = [
        "[World Model Summary]",
        f"Best: {best_score}x | Stagnation: {stagnation_count}/{stagnation_window}",
        f"Open nodes: {open_count} | Passed: {passed_count} | Failed: {failed_count}",
        f"Active path: {active_path}",
        f"Unexplored root branches: {unexplored_roots}",
    ]

    if open_questions:
        lines.append("Key findings:")
        for q in open_questions[:5]:
            lines.append(f"  - {q}")

    text = "\n".join(lines)

    # Truncate to max_chars if needed
    if len(text) > max_chars:
        text = text[:max_chars - 3] + "..."

    return text


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def cmd_select(args: argparse.Namespace) -> None:
    with open(args.path, "r", encoding="utf-8") as f:
        wm = json.load(f)
    result = select_nodes(wm, args.n)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_validate(args: argparse.Namespace) -> None:
    with open(args.path, "r", encoding="utf-8") as f:
        wm = json.load(f)
    errors = validate(wm)
    if errors:
        print("Validation FAILED:")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)
    else:
        print("Validation PASSED: all invariants satisfied.")


def cmd_summary(args: argparse.Namespace) -> None:
    with open(args.path, "r", encoding="utf-8") as f:
        wm = json.load(f)
    print(summary(wm, max_chars=args.max_chars))


def cmd_deep_profiling(args: argparse.Namespace) -> None:
    """Run deep profiling on a node and write results to world_model.json."""
    import os

    # Step 1: Run run_deep_profiling.py via subprocess
    script_path = os.path.join(
        os.path.dirname(__file__), "..", "..",
        ".claude", "skills", "ascendc-profiling-analysis", "scripts",
        "run_deep_profiling.py",
    )
    script_path = os.path.abspath(script_path)
    result_path = os.path.join(args.work_dir, "deep_profiling_result.json")

    cmd = [
        sys.executable, script_path,
        "--work-dir", args.work_dir,
        "--op-name", args.op_name,
        "--output", result_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        print(f"deep-profiling: run_deep_profiling.py failed:\n{proc.stderr}", file=sys.stderr)
        sys.exit(1)

    # Step 2: Read profiling result
    with open(result_path, "r", encoding="utf-8") as f:
        prof_result = json.load(f)

    evidence = prof_result.get("profiling_evidence")
    if not evidence:
        print("deep-profiling: no profiling_evidence produced", file=sys.stderr)
        sys.exit(1)

    # Step 3: Write evidence into world_model.json node
    with open(args.wm_path, "r", encoding="utf-8") as f:
        wm = json.load(f)

    nodes = wm.get("decision_tree", {}).get("nodes", {})
    node = nodes.get(args.node_id)
    if not node:
        print(f"deep-profiling: node '{args.node_id}' not found", file=sys.stderr)
        sys.exit(1)

    node["profiling_evidence"] = evidence

    # Step 4: Optionally merge strategies into open children
    if args.merge_children:
        try:
            from profiling_evidence import merge_strategies_with_evidence
        except ImportError:
            _script_dir = os.path.dirname(os.path.abspath(__file__))
            sys.path.insert(0, _script_dir)
            from profiling_evidence import merge_strategies_with_evidence

        updated_children = []
        for cid in node.get("children", []):
            child = nodes.get(cid)
            if child and child.get("status") == "open":
                old_strats = child.get("strategy_combination", [])
                child["strategy_combination"] = merge_strategies_with_evidence(old_strats, evidence)
                updated_children.append(cid)
        if updated_children:
            print(f"deep-profiling: updated strategies for children: {updated_children}")

    # Step 5: Write back
    with open(args.wm_path, "w", encoding="utf-8") as f:
        json.dump(wm, f, ensure_ascii=False, indent=2)

    print(f"deep-profiling: wrote profiling_evidence to node '{args.node_id}'")
    print(f"  bottleneck_type: {evidence.get('bottleneck_type')}")
    print(f"  suggested_strategies: {evidence.get('suggested_strategies')}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="World Model CLI operations for evolution."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # select
    p_select = subparsers.add_parser("select", help="Select top-N open nodes")
    p_select.add_argument("--path", required=True, help="Path to world_model.json")
    p_select.add_argument("--n", type=int, required=True, help="Number of nodes to select")
    p_select.set_defaults(func=cmd_select)

    # validate
    p_validate = subparsers.add_parser("validate", help="Validate invariants")
    p_validate.add_argument("--path", required=True, help="Path to world_model.json")
    p_validate.set_defaults(func=cmd_validate)

    # summary
    p_summary = subparsers.add_parser("summary", help="Compact summary for prompt injection")
    p_summary.add_argument("--path", required=True, help="Path to world_model.json")
    p_summary.add_argument(
        "--max-chars", type=int, default=1200,
        help="Maximum characters in output (default: 1200)"
    )
    p_summary.set_defaults(func=cmd_summary)

    # deep-profiling
    p_dp = subparsers.add_parser("deep-profiling", help="Run deep profiling and write to world model")
    p_dp.add_argument("--wm-path", required=True, help="Path to world_model.json")
    p_dp.add_argument("--node-id", required=True, help="Node ID to write profiling_evidence to")
    p_dp.add_argument("--work-dir", required=True, help="Operator work directory (with build artifacts)")
    p_dp.add_argument("--op-name", required=True, help="Operator name")
    p_dp.add_argument("--merge-children", action="store_true",
                       help="Merge evidence strategies into open child nodes")
    p_dp.set_defaults(func=cmd_deep_profiling)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
