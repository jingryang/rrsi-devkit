"""A5 precision_debug transition table (new 5-stage flow)."""

from __future__ import annotations

# Transition table for the new A5 5-stage flow (regression 阶段已合入 kernel_debug)：
#   baseline -> kernel_debug /> op_plugin_debug
#   kernel_debug -> baseline(kl_all_pass) / kernel_debug(case_kl_fails) /
#                   vf_test / vector_error_debug / retry / exhausted
#   vf_test -> kernel_debug / vector_error_debug / exhausted
#   vector_error_debug -> kernel_debug / retry / exhausted
#   op_plugin_debug -> baseline / kernel_debug (need_kernel_debug) / retry / exhausted
# kernel_debug 修复当前 case 后批跑全量 KernelLaunch（原 regression 职责），KL 全过 →
# 回 baseline 做权威双跑验收；有失败 → 修下一个失败 case（队列由框架从 KL 实测调和）。
# baseline 分流：kernel 层失败优先（Q6 修订）——出现精度问题时优先调度
# ascendc-precision-kernel-debug；混合队列路由 kernel_debug 时，per-case 阶段的队列
# 推进会跳过 op_plugin case，kernel 工作收敛后回 baseline 重跑把适配层问题分流到
# op_plugin_debug。
_A5_TRANSITION_TABLE = {
    "baseline": {
        "all_pass": ("__escalate__:passed", "validation"),
        "has_op_plugin_failures": ("op_plugin_debug", "corrective"),
        "has_kernel_failures": ("kernel_debug", "corrective"),
        # baseline 跑了但没有任何 case 数据（空 cross_compare）→ 不是 all_pass，
        # 软门放行到 exhausted，避免空队列 false-pass 直通 passed。
        "no_case_data": ("__escalate__:exhausted", "validation"),
        "commit_failed": ("__escalate__:exhausted", "validation"),
        # agent 自报状态异常 → 重试该 agent。
        "retry": ("baseline", "corrective"),
        # §abort: transient → self-loop re-spawn; persistent (>=3) → escalate.
        # STATUS=FAILED（ENV/OTH 硬失败）→ escalate，不重试。
        "hard_failed": ("__escalate__:exhausted", "validation"),
        "agent_aborted": ("baseline", "corrective"),
        "abort_exhausted": ("__escalate__:exhausted", "validation"),
    },
    "kernel_debug": {
        # 修复后全量 KL 全过 → 回 baseline 做权威双跑验收（rc 与 kl 双双全过才
        # escalate:passed；任一未全过由 baseline 机械门槛继续分流 kernel/op_plugin）
        "kl_all_pass":    ("baseline", "validation"),
        # KL 有任一失败 → 回 kernel_debug 修下一个失败 case（队列已由框架 KL 调和：
        # 当前 case KL 通过会被标 resolved、index 由 spawn reconcile 推进）。
        "case_kl_fails":  ("kernel_debug", "corrective"),
        "need_vf":        ("vf_test", "corrective"),
        "vector_error":   ("vector_error_debug", "corrective"),
        "retry":          ("kernel_debug", "corrective"),
        "case_exhausted": ("kernel_debug", "corrective"),
        # 队列全部 case 已处理（最后一个 exhausted / 止损跳过）→ 不直接杀流程，回
        # baseline 做权威双跑验收：剩余失败 case 由 baseline 重新交叉对比分流（RC
        # 失败→op_plugin_debug / KL 失败→kernel_debug / 全过→passed），避免在仍有
        # 大量 case 精度未通过时提前 escalate 终止（2026-08-10 轨迹：case_20 最后一个
        # exhausted 后整个 A5 流程终止，14 个 tie-break case 仍挂）。重入受 corrective
        # 配额（max_corrective=30）与停滞守卫约束。
        "all_exhausted":  ("baseline", "validation"),
        # STATUS=FAILED（ENV/OTH 硬失败）→ escalate，不重试。
        "hard_failed": ("__escalate__:exhausted", "validation"),
        "agent_aborted":  ("kernel_debug", "corrective"),
        "abort_exhausted": ("__escalate__:exhausted", "validation"),
    },
    "vf_test": {
        "retry":          ("vf_test", "corrective"),
        "vf_passed":      ("kernel_debug", "corrective"),
        "vector_error":   ("vector_error_debug", "corrective"),
        "case_exhausted": ("kernel_debug", "corrective"),
        "all_exhausted":  ("baseline", "validation"),
        # STATUS=FAILED（ENV/OTH 硬失败）→ escalate，不重试。
        "hard_failed": ("__escalate__:exhausted", "validation"),
        "agent_aborted":  ("vf_test", "corrective"),
        "abort_exhausted": ("__escalate__:exhausted", "validation"),
    },
    "vector_error_debug": {
        "retry":          ("vector_error_debug", "corrective"),
        "fixed":          ("kernel_debug", "validation"),
        "case_exhausted": ("kernel_debug", "corrective"),
        "all_exhausted":  ("baseline", "validation"),
        # STATUS=FAILED（ENV/OTH 硬失败）→ escalate，不重试。
        "hard_failed": ("__escalate__:exhausted", "validation"),
        "agent_aborted":  ("vector_error_debug", "corrective"),
        "abort_exhausted": ("__escalate__:exhausted", "validation"),
    },
    "op_plugin_debug": {
        "retry": ("op_plugin_debug", "corrective"),
        "converged": ("baseline", "validation"),
        # op_plugin agent 判定适配层正确/已修复、残余失败在 kernel/tiling 层 →
        # 直接把对应 case 移交 kernel_debug 做 per-case 精度调试，不再被迫走
        # exhausted→escalate（流死）或 converged→baseline 全量重跑（浪费）。
        "need_kernel_debug": ("kernel_debug", "corrective"),
        "exhausted": ("__escalate__:exhausted", "validation"),
        # STATUS=FAILED（ENV/OTH 硬失败）→ escalate，不重试。
        "hard_failed": ("__escalate__:exhausted", "validation"),
        "agent_aborted": ("op_plugin_debug", "corrective"),
        "abort_exhausted": ("__escalate__:exhausted", "validation"),
    },
}

_A5_MAX_CORRECTIVE = 30
