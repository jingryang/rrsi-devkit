"""UT: coder 设计蓝图缺陷处置 — docs/plan/design-blueprint-feasibility/04-impl-1b''。

根因（批 20260911-172304-501e35 adaptive_avg_pool_3d，5-cut 39.4min 零落盘 halt）：蓝图算法
路径物理不可实施（移位向量 Add 违反操作数 32B 对齐）+ coder skill 无处置分支——「忠实翻译」
无冲突出口、「无法确定编码路径→报错退出」为输入缺失设计、:238 layout_contract 条款仅覆盖
GM 布局冲突 → 模型正确诊断却三次 FINAL DECISION 被自我推翻，静态分析膨胀至输出截断。

本测试守护五件事（grep SKILL.md 文本防漂移，写法同 test_codegen_a5_constraints.py）：
  ① Step 4 含「设计蓝图缺陷处置」节：明显先改（等价变形）+ 疑点送测仲裁（按设计直译）；
  ② **尽量解决优先于报错**（用户整改 2026-09-14 二轮）：无最小变形 → 允许更大等价重实现，
     报错退出被窄化为仅限两种情形；
  ③ 判据与护栏：明显=可证明性；变形登记+交棒；先改不豁免测试；降级规避不属等价变形；
     仲裁措辞后端无关；归因由修复层级派生；
  ④ 零交互纪律收窄：旧「无法确定编码路径→报错退出」删除，可行性怀疑明文不属此列；
  ⑤ :238 layout_contract 条款仍在（同族并存不互斥），且无「无条件忠实翻译」矛盾措辞。
"""

import re
from pathlib import Path

SKILL_MD = (Path(__file__).resolve().parents[3] /
            ".claude/skills/ascendc-op-dev-coding/SKILL.md")

_WS = re.compile(r"\s+")


class TestBlueprintDefectHandling:
    """SKILL.md 须含蓝图缺陷处置紧凑条款 + 尽量解决优先 + R-c 收窄，无矛盾措辞。"""

    def setUp(self):
        self.text = SKILL_MD.read_text(encoding="utf-8")

    def test_step4_has_blueprint_handling_section(self):
        self.setUp()
        t = self.text
        assert "设计蓝图缺陷处置" in t, "Step 4 缺「设计蓝图缺陷处置」节"
        assert "等价变形" in t, "缺明显缺陷先改（等价变形）分支"
        # 空白归一化后断言（skill 词组可跨行排版，避免把 markdown 换行写死）
        assert "按设计蓝图直译" in _WS.sub("", t), "缺疑点送测（按设计直译）分支"
        assert "唯一裁判" in t, "缺构建与测试仲裁条款"
        # 节落在 Step 4 内（管辖分层编码全过程）；节锚前置断言——节名变更时干净失败
        assert "### Step 4" in t, "SKILL.md 缺 Step 4 节锚（节名变更须同步测试）"
        assert "#### GM workspace 设置" in t, "SKILL.md 缺 GM workspace 节锚（节名变更须同步测试）"
        step4 = t[t.index("### Step 4"):t.index("#### GM workspace 设置")]
        assert "设计蓝图缺陷处置" in step4, "处置节不在 Step 4 内"

    def test_solving_preferred_over_error(self):
        """用户整改点：设计缺陷尽量解决，不轻易报错（R3）。"""
        self.setUp()
        t = self.text
        assert "能解决的不报错" in t, "缺「能解决的不报错」总则"
        assert "等价重实现" in t, "无最小变形时应允许更大等价重实现而非报错"
        assert "报错退出仅限" in t, "报错未被窄化为明确列举的少数情形"

    def test_criterion_and_guardrails(self):
        self.setUp()
        t = self.text
        assert "可证明性" in t, "缺「明显」判据=可证明性"
        assert "known_issues" in t and "交棒" in t, "缺登记+交棒设计侧要求"
        assert "照常过全部构建/测试" in t, "缺「先改不豁免测试」边界"
        # 仲裁措辞后端无关（§2.1：TUI 单跑不依赖框架阶段名）
        assert "构建与测试" in t, "仲裁措辞未用后端无关的「构建与测试」"
        # 归因由修复层级派生，非模型另行判断
        assert "修复层级" in t, "缺归因=修复层级派生条款"
        # 降级规避护栏（维4 AR-1 红线引用）
        assert "降级规避" in t and "维4 AR-1" in t, "缺降级规避不属等价变形护栏"

    def test_zero_interaction_narrowed(self):
        self.setUp()
        t = self.text
        assert "无法确定编码路径" not in t, \
            "旧 R-c 语义未删除（应为「输入缺失/契约歧义」）"
        assert "输入缺失/契约歧义" in t, "R-c 未收窄为输入缺失/契约歧义"
        assert "可行性怀疑不属此列" in t, "未声明可行性怀疑不属报错退出门"

    def test_layout_contract_clause_preserved_no_contradiction(self):
        self.setUp()
        t = self.text
        assert "layout_contract" in t, ":238 layout_contract 条款被误删"
        # 无条件忠实措辞不得与新协议并存（R4：弱模型不可面对矛盾规则）
        assert "一律忠实翻译" not in t, "存在与新条款矛盾的「一律忠实翻译」措辞"
        assert "必须忠实翻译" not in t, "存在与新条款矛盾的「必须忠实翻译」措辞"
