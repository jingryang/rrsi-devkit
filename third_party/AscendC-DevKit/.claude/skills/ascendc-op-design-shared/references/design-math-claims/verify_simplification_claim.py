#!/usr/bin/env python3
"""化简/降维/等价声称 — 通用验证模板（骨架已知正确，LLM 只填 FILL-ME 段）。

用法：设计 agent 声称"把 X 化简为 Y"时，复制本文件到工作目录，填 FILL-ME 段，运行。
三段式输出：声称支持域 vs 实测可覆盖域，供写 `support_domain` / `known_limitations`。

骨架（本文件不变的部分）：
  1. 生成测试输入（domain generator）
  2. 调 golden（ground truth = golden，非 LLM 脑补期望）
  3. 应用声称的化简（claim function）
  4. 逐一对比，汇总"哪些输入声称成立"
骨架由 UT 守护；LLM 只填声称逻辑，错误表面积最小。

规则（见同目录 claim-verification-checklist.md）：
  - ground truth = golden；声称与 golden 冲突即声称错。
  - 能穷举就穷举（小空间全枚举），大空间随机抽样。
  - fail-loud：断言不通过即失败，绝不静默通过。
  - 跑不通先 agent 内部多轮自修；多次尝试后仍跑不通 → 标 known_limitations 继续，不 halt。
"""
import itertools
import sys

import numpy as np


# =====================================================================
# FILL-ME 1: golden（算子真值，权威源；transpose 例 = np.transpose）
# =====================================================================
def golden(inp, **attrs):
    """返回该输入下算子的正确输出。"""
    raise NotImplementedError("FILL-ME: 用 golden/参考实现实现")


# =====================================================================
# FILL-ME 2: 声称的化简（claim function：声称"kernel/实现"如何算）
# =====================================================================
def claimed_impl(inp, **attrs):
    """按设计声称的化简方式计算输出（如"reshape(M,N)+2D转置"）。"""
    raise NotImplementedError("FILL-ME: 用声称的化简逻辑实现")


# =====================================================================
# FILL-ME 3: 输入域生成器（穷举优先，超大空间才随机）
# =====================================================================
def domain_candidates():
    """产出 (inp, attrs) 列表——覆盖声称与 golden 的完整输入域。

    穷举优先：小参数空间全枚举（如 rank≤5 的全部 perm）。
    随机兜底：大 shape 空间 `np.random` 抽样（注明 N）。
    """
    raise NotImplementedError("FILL-ME: 枚举声称支持域 + golden 全域的输入")


# =====================================================================
# 骨架（不要改）：对比 + 报告
# =====================================================================
def _report_fail(name, inp, attrs, got, want):
    print(f"  ✗ {name}: 声称与 golden 不一致 | 输入={inp} attrs={attrs}")
    print(f"      claimed={np.asarray(got).shape} golden={np.asarray(want).shape}")
    return False


def main():
    ok, fail = 0, 0
    fail_examples = []
    for inp, attrs in domain_candidates():
        try:
            want = golden(inp, **attrs)
            got = claimed_impl(inp, **attrs)
        except NotImplementedError as e:
            print(f"[FILL-ME 未完成] {e}")
            return 2
        except Exception as e:
            fail += 1
            fail_examples.append((inp, attrs, f"异常 {type(e).__name__}: {e}"))
            continue
        if np.array_equal(np.asarray(got), np.asarray(want)):
            ok += 1
        else:
            fail += 1
            fail_examples.append((inp, attrs, "数值不一致"))

    total = ok + fail
    print(f"\n=== 声称覆盖域 vs 实测覆盖域 ===")
    print(f"总测试输入: {total}  声称成立: {ok}  不成立: {fail}")
    if fail_examples:
        print(f"前 {min(10, len(fail_examples))} 条失败输入:")
        for inp, attrs, why in fail_examples[:10]:
            print(f"  - {inp} | attrs={attrs} | {why}")
        print("\n结论: 声称只覆盖部分域。把这些输入归入 `known_limitations`；")
        print("      支持域（声称成立的部分）写进 `support_domain`。")
        return 1
    print("结论: 声称覆盖全部测试输入域。可写 `support_domain` = 全部，`known_limitations` 依残余风险定。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
