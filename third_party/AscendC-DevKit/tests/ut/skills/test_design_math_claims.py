"""design-math-claims 模板骨架守卫（V1，docs/plan/design-math-claims-verification L4 §6）。

守护 design 阶段"化简/降维声称验证"通用模板骨架本身正确：
  - 骨架已知正确，LLM 只填 FILL-ME 段（§2.7 缩小 LLM 错误表面积）；
  - ground truth = golden：声称与 golden 冲突即声称错（§1.13）；
  - fail-loud：声称只覆盖部分域 → 返回码 1 + 明确指引写 support_domain/known_limitations；
  - 能穷举就穷举：rank 2-4 全部 perm 穷举。

确定性（no-LLM），run via pytest.
"""

from __future__ import annotations

import itertools
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

_SKILLS_ROOT = Path(__file__).resolve().parents[3] / ".claude" / "skills"
_TEMPLATE = _SKILLS_ROOT / "ascendc-op-design-shared" / "references" / "design-math-claims" / "verify_simplification_claim.py"
_CHECKLIST = _SKILLS_ROOT / "ascendc-op-design-shared" / "references" / "design-math-claims" / "claim-verification-checklist.md"
_FACTS = _SKILLS_ROOT / "ascendc-op-design-shared" / "references" / "design-math-claims" / "verified_facts.md"


def _load_template():
    """动态加载通用模板模块（同目录 import），填充 transpose 声称逻辑。"""
    sys.path.insert(0, str(_TEMPLATE.parent))
    import importlib
    import verify_simplification_claim as T
    importlib.reload(T)
    return T


def _transpose_domain():
    """穷举 rank 2-4 全部 perm，随机 shape —— 覆盖声称与 golden 全域。"""
    rng = np.random.default_rng(42)
    out = []
    for n in range(2, 5):
        for perm in itertools.permutations(range(n)):
            shape = tuple(int(s) for s in rng.integers(2, 4, size=n))
            out.append((rng.random(shape), {"perm": list(perm)}))
    return out


def _cyclic_rotation_impl(inp, **attrs):
    """声称的化简 = 单个 2D 转置（只对循环旋转成立，非循环旋转错误返回原样——模拟设计声称）。"""
    perm = attrs["perm"]
    n = len(perm)
    if list(perm) == list(range(n)):
        return inp.copy()
    for b in range(1, n):
        exp = [(b + k) if k < n - b else (k - (n - b)) for k in range(n)]
        if list(perm) == exp:
            M = int(np.prod(inp.shape[:b]))
            N = int(np.prod(inp.shape[b:]))
            return inp.reshape(M, N).T.reshape([inp.shape[i] for i in range(b, n)] + [inp.shape[i] for i in range(b)])
    return inp.copy()  # 声称"非循环旋转也能降维"——骨架应抓出与 golden 不一致


class TestDesignMathClaimsTemplate:
    """骨架正确性：穷举抓域缺口、golden 裁判、fail-loud。"""

    def test_resources_exist(self):
        assert _TEMPLATE.exists(), "通用验证模板缺失"
        assert _CHECKLIST.exists(), "检查清单缺失"
        assert _FACTS.exists(), "已核验事实库缺失"

    def test_template_catches_domain_gap(self):
        """声称只覆盖循环旋转 → 骨架必须机械抓出域缺口（rc=1 + 指引）。"""
        T = _load_template()

        def golden(inp, **attrs):
            return np.transpose(inp, attrs["perm"])

        T.golden = golden
        T.claimed_impl = _cyclic_rotation_impl
        T.domain_candidates = _transpose_domain
        rc = T.main()
        assert rc == 1, f"声称覆盖不全时骨架应返回 1，实际 {rc}"
        # 循环旋转恰 9 个（rank2:2 + rank3:3 + rank4:4）→ 声称成立数应为 9
        assert "声称成立: 9" in str(T.main() if False else _capture(T)), "应恰好抓出 9 个循环旋转"

    def test_template_skeleton_has_fillme_markers(self):
        """骨架已知正确，LLM 只填 FILL-ME 段——骨架部分必须存在且可识别。"""
        text = _TEMPLATE.read_text(encoding="utf-8")
        assert "def golden(inp" in text and "FILL-ME" in text
        assert "def claimed_impl" in text and "FILL-ME" in text
        assert "def domain_candidates" in text and "FILL-ME" in text


def _capture(T):
    """捕获 main() stdout（重跑，供断言输出文本）。"""
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        T.main()
    return buf.getvalue()
