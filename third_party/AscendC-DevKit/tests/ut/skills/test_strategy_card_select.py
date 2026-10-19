"""ascendc-strategy-card-select：cardlib 路径解析、卡片生成器契约与静态守卫。

纯静态分析 + 合成 fixture，不依赖外部策略库、不依赖 LLM、不调用网络。
真实策略库的端到端连通性由 tests/st 的 heavy_llm 用例覆盖（需用户确认才跑）。
"""

import importlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "ascendc-strategy-card-select"
SCRIPTS = SKILL_DIR / "scripts"

# 外部策略库（跨仓单源依赖）：_catalog.py 只在这里存在，本仓不含副本。
EXTERNAL_CATALOG = Path("/home/l00940202/pangu/ascendc-strategy-opt")

sys.path.insert(0, str(SCRIPTS))
cardlib = importlib.import_module("cardlib")
build_cards = importlib.import_module("build_cards")

CARD_ROW_KEYS = {"strategy_id", "text", "text_sha256"}


# ── 合成策略库 fixture ──────────────────────────────────────────────────────

def _card_md(slug, mechanism, classification="validated_strategy",
             generality="op_class", operator_class="sort-select",
             bottleneck=None, intent="意图", required=None,
             excluded=None, constraints=None, risks=None):
    entry = {
        "id": slug.upper(), "slug": slug, "name": f"名 {slug}",
        "classification": classification, "generality": generality,
        "operator_scope": "该类的数据流",
        "summary": "摘要", "intent": intent, "principle": "原理",
        "mechanism": mechanism,
        "applicability": {
            "required_conditions": required or ["条件甲", "条件乙"],
            "excluded_conditions": excluded or ["排除甲"],
            "constraints": constraints or ["约束甲"],
        },
        "implementation_steps": ["步骤甲"], "risks": risks or ["风险甲"],
        "verification": {"correctness": ["正确性"], "performance": ["性能"],
                         "rollback_signals": ["回退"]},
        "evidence": [],
    }
    if generality == "op_class":
        entry["operator_class"] = operator_class
    if bottleneck is not None:
        entry["feature_signature"] = {"bottleneck": bottleneck, "pattern": f"p-{slug}",
                                      "structure": [f"s-{slug}"]}
    return f"<!-- strategy-metadata\n{json.dumps(entry, ensure_ascii=False, indent=2)}\n-->\n\n# 正文\n"


@pytest.fixture
def curator_scripts():
    """_catalog.py 所在目录：外部策略库的 curator skill。

    这是跨仓单源依赖，本仓不含副本；缺失时跳过依赖它的用例而非伪造一个。
    """
    p = EXTERNAL_CATALOG / ".claude" / "skills" / "ascendc-strategy-curator" / "scripts"
    if not (p / "_catalog.py").is_file():
        pytest.skip(f"外部策略库元数据解析器不可用: {p}")
    return p


@pytest.fixture
def catalog(tmp_path):
    """合成策略库：common 2 张（1 张无 bottleneck）+ sort-select 2 张、reduction 1 张。"""
    root = tmp_path / "catalog"
    (root / "strategies" / "common").mkdir(parents=True)
    (root / "strategies" / "op-class" / "sort-select").mkdir(parents=True)
    (root / "strategies" / "op-class" / "reduction").mkdir(parents=True)
    (root / "strategies" / "op-class" / "contraction").mkdir(parents=True)  # 零卡目录
    (root / "strategies" / "README.md").write_text("# 非卡片", encoding="utf-8")

    (root / "strategies" / "common" / "common-a.md").write_text(
        _card_md("common-a", "公共机制甲", generality="common"), encoding="utf-8")
    (root / "strategies" / "common" / "no-bottleneck.md").write_text(
        _card_md("no-bottleneck", "无瓶颈字段的机制", generality="common",
                 bottleneck=None, intent="该卡只有意图"), encoding="utf-8")
    (root / "strategies" / "op-class" / "sort-select" / "sel-a.md").write_text(
        _card_md("sel-a", "机制甲", bottleneck=["scalar-serial"]), encoding="utf-8")
    (root / "strategies" / "op-class" / "sort-select" / "falsified-b.md").write_text(
        _card_md("falsified-b", "机制乙", classification="negative_boundary",
                 bottleneck=["no-gain"]), encoding="utf-8")
    (root / "strategies" / "op-class" / "reduction" / "red-a.md").write_text(
        _card_md("red-a", "归约机制", operator_class="reduction"), encoding="utf-8")
    return root


# ── cardlib：类别与路径 ─────────────────────────────────────────────────────

class TestCategories:
    def test_lists_common_plus_classes_with_cards(self, catalog):
        cats = cardlib.categories(catalog)
        assert cats[0] == "common"
        assert "sort-select" in cats and "reduction" in cats
        # 零卡目录（contraction）不是合法池
        assert "contraction" not in cats

    def test_rejects_missing_md_root(self, tmp_path):
        with pytest.raises(ValueError, match="策略 md 根不存在"):
            cardlib.categories(tmp_path)

    def test_pool_merges_common_into_class(self, catalog):
        pool = cardlib.pool_members(catalog, "sort-select")
        assert "common-a" in pool and "sel-a" in pool  # common ∪ class
        assert "red-a" not in pool

    def test_common_pool_is_common_only(self, catalog):
        assert cardlib.pool_members(catalog, "common") == ["common-a", "no-bottleneck"]

    def test_rejects_unknown_category(self, catalog):
        with pytest.raises(ValueError, match="非法类别"):
            cardlib.pool_members(catalog, "elementwis")  # 笔误


class TestSourceMdPath:
    def test_resolves_common_tier(self, catalog):
        p = cardlib.source_md_path(catalog, "common-a")
        assert p.parent.name == "common"

    def test_resolves_op_class_tier(self, catalog):
        p = cardlib.source_md_path(catalog, "red-a")
        assert p.parent.name == "reduction"
        assert p.parent.parent.name == "op-class"

    def test_unknown_id_raises(self, catalog):
        with pytest.raises(ValueError, match="策略 md 不存在"):
            cardlib.source_md_path(catalog, "no-such-card")

    def test_duplicate_slug_across_tiers_raises(self, catalog):
        """slug 唯一性是外部不变式；≥2 命中必须报错而非静默选一个。"""
        dup = catalog / "strategies" / "op-class" / "reduction" / "common-a.md"
        dup.write_text(_card_md("common-a", "重复", operator_class="reduction"),
                       encoding="utf-8")
        with pytest.raises(ValueError, match="命中 2 处"):
            cardlib.source_md_path(catalog, "common-a")


class TestStrategyRoot:
    def test_cli_value_wins(self, catalog, monkeypatch):
        monkeypatch.setenv(cardlib.ENV_STRATEGY_ROOT, "/nonexistent/xyz")
        assert cardlib.resolve_strategy_root(str(catalog)) == catalog.resolve()

    def test_env_fallback(self, catalog, monkeypatch):
        monkeypatch.setenv(cardlib.ENV_STRATEGY_ROOT, str(catalog))
        assert cardlib.resolve_strategy_root(None) == catalog.resolve()

    def test_absent_returns_none(self, monkeypatch):
        monkeypatch.delenv(cardlib.ENV_STRATEGY_ROOT, raising=False)
        assert cardlib.resolve_strategy_root(None) is None

    def test_bad_path_raises_with_remediation(self, monkeypatch):
        with pytest.raises(ValueError) as e:
            cardlib.resolve_strategy_root("/nonexistent/xyz")
        assert cardlib.ENV_STRATEGY_ROOT in str(e.value)


# ── 三态契约：未指定=skip 标记不阻塞 / 指定但无效=硬停 ───────────────────────

class TestPrepareThreeState:
    """「用户是否指定策略库」三态语义的脚本级契约（概设步骤6 依赖此处行为）。

    未指定 → run_inputs.json 落 status=skipped_no_library 且 exit 0（合法未启用，不阻塞）；
    指定但无效 → exit 2 硬停（显式意图失败，不伪装成未启用）。
    两态不得混淆：skip 标记不含任何检索结果字段。
    """

    def _run(self, argv, monkeypatch):
        import subprocess
        monkeypatch.delenv(cardlib.ENV_STRATEGY_ROOT, raising=False)
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "select_prepare.py")] + argv,
            capture_output=True, text=True)

    def test_unspecified_writes_skip_marker_and_exits_zero(self, tmp_path, monkeypatch):
        out = tmp_path / "skip"
        r = self._run(["--prepare", "--op-name", "t_op", "--out-dir", str(out)], monkeypatch)
        assert r.returncode == 0, r.stderr
        ri = json.loads((out / "run_inputs.json").read_text(encoding="utf-8"))
        assert ri["status"] == "skipped_no_library"
        assert ri["op_name"] == "t_op"
        # 反混淆：skip 标记不得携带检索结果字段（区别于「检索过但无命中」）
        for k in ("screening_pool_count", "card_count", "source_md_digest"):
            assert k not in ri

    def test_invalid_root_hard_stops_with_remediation(self, tmp_path, monkeypatch):
        r = self._run(["--prepare", "--op-name", "t_op", "--out-dir", str(tmp_path / "bad"),
                       "--strategy-root", "/nonexistent/xyz"], monkeypatch)
        assert r.returncode == 2
        assert cardlib.ENV_STRATEGY_ROOT in r.stderr

    def test_emit_screening_exits_cleanly_on_skip_marker(self, tmp_path, monkeypatch):
        import subprocess
        out = tmp_path / "skip"
        self._run(["--prepare", "--op-name", "t_op", "--out-dir", str(out)], monkeypatch)
        monkeypatch.delenv(cardlib.ENV_STRATEGY_ROOT, raising=False)
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "select_prepare.py"),
             "--emit-screening", "--out-dir", str(out)],
            capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert "skipped_no_library" in r.stdout


# ── 使用留痕：选中→逐条 USED；无命中→REASON 原因说明 ────────────────────────

class TestUsageLog:
    """strategy_usage.log 契约（用户需求 2026-09-24）：指定策略库且完成检索后强制留痕。"""

    @staticmethod
    def _finalize():
        import importlib
        return importlib.import_module("select_finalize")

    def test_selected_logs_one_used_line_per_strategy(self, tmp_path):
        sel = {
            "selected_strategies": [
                {"strategy_id": "heap-topk", "applicability_status": "supported",
                 "confidence": 0.9, "bottleneck_fit": "主瓶颈假设1"},
                {"strategy_id": "row-vec-sort", "applicability_status": "uncertain",
                 "confidence": 0.6, "bottleneck_fit": "高k备选"},
            ],
        }
        self._finalize().append_usage_log(tmp_path, {"op_name": "topk", "category": "sort-select"}, sel)
        text = (tmp_path / "strategy_usage.log").read_text(encoding="utf-8")
        assert "outcome=selected count=2" in text
        assert "USED heap-topk status=supported confidence=0.9" in text
        assert "USED row-vec-sort status=uncertain confidence=0.6" in text

    def test_no_match_logs_reason_from_rationale(self, tmp_path):
        sel = {"selected_strategies": [],
               "rationale": "候选A适用条件与设计意图不符（轴长度约束冲突）；候选B被红线否决。"}
        self._finalize().append_usage_log(tmp_path, {"op_name": "op_x", "category": "common"}, sel)
        text = (tmp_path / "strategy_usage.log").read_text(encoding="utf-8")
        assert "outcome=no_match count=0" in text
        assert "REASON " in text
        assert "轴长度约束冲突" in text  # 原因说明必须落进 log，不只是状态

    def test_append_semantics_rerun_keeps_history(self, tmp_path):
        sel = {"selected_strategies": [], "rationale": "首次无命中原因说明文字。"}
        fn = self._finalize().append_usage_log
        fn(tmp_path, {"op_name": "a", "category": "c"}, sel)
        fn(tmp_path, {"op_name": "b", "category": "c"},
           {"selected_strategies": [{"strategy_id": "s1", "applicability_status": "supported",
                                     "confidence": 0.8, "bottleneck_fit": "f"}]})
        text = (tmp_path / "strategy_usage.log").read_text(encoding="utf-8")
        assert "op=a" in text and "op=b" in text  # 追加式：重跑不覆盖历史


# ── 生成器：契约、确定性、回退 ──────────────────────────────────────────────

class TestBuildCards:
    def _gen(self, catalog, out, curator_scripts, category="sort-select", terms=None):
        argv = ["--strategy-root", str(catalog), "--category", category,
                "--out", str(out), "--quiet",
                "--curator-scripts", str(curator_scripts)]
        if terms:
            tf = out / "terms.json"
            tf.write_text(json.dumps({"terms": terms}, ensure_ascii=False),
                          encoding="utf-8")
            argv += ["--retrieval-terms", str(tf)]
        else:
            argv += ["--retrieval-terms", str(out / "absent.json")]
        return build_cards.main(argv)

    def test_row_contract_is_exactly_three_keys(self, catalog, tmp_path, curator_scripts):
        """行键恰为三键：扩合约会同时破坏 finalize 门禁，必须显式钉住。"""
        assert self._gen(catalog, tmp_path, curator_scripts) == 0
        doc = json.loads((tmp_path / "cards" / "op-class"
                          / "sort-select.texts.json").read_text(encoding="utf-8"))
        assert set(doc) == {"strategies"}
        for row in doc["strategies"]:
            assert set(row) == CARD_ROW_KEYS

    def test_every_row_passes_validation(self, catalog, tmp_path, curator_scripts):
        self._gen(catalog, tmp_path, curator_scripts)
        rows, errs = cardlib.load_cards_file(
            tmp_path / "cards" / "op-class" / "sort-select.texts.json")
        assert errs == []
        assert rows is not None

    def test_deterministic_across_runs(self, catalog, tmp_path, curator_scripts):
        a, b = tmp_path / "a", tmp_path / "b"
        assert build_cards.main(["--strategy-root", str(catalog), "--all",
                                 "--out", str(a), "--quiet",
                                 "--curator-scripts", str(curator_scripts),
                                 "--retrieval-terms", str(a / "x.json")]) == 0
        assert build_cards.main(["--strategy-root", str(catalog), "--all",
                                 "--out", str(b), "--quiet",
                                 "--curator-scripts", str(curator_scripts),
                                 "--retrieval-terms", str(b / "x.json")]) == 0
        rels = sorted(str(p.relative_to(a)) for p in (a / "cards").rglob("*.texts.json"))
        assert rels  # 确有产物可比
        for rel in rels:
            assert (a / rel).read_bytes() == (b / rel).read_bytes(), rel

    def test_negative_boundary_gets_prefix(self, catalog, tmp_path, curator_scripts):
        self._gen(catalog, tmp_path, curator_scripts)
        doc = json.loads((tmp_path / "cards" / "op-class"
                          / "sort-select.texts.json").read_text(encoding="utf-8"))
        by_id = {r["strategy_id"]: r["text"] for r in doc["strategies"]}
        assert by_id["falsified-b"].startswith("动作：负向边界：")
        assert by_id["sel-a"].startswith("动作：机制甲")  # 正向卡不加前缀

    def test_cost_field_never_emitted(self, catalog, tmp_path, curator_scripts):
        """「代价」无元数据来源，必须整行省略而非留空占位。"""
        self._gen(catalog, tmp_path, curator_scripts)
        for f in (tmp_path / "cards").rglob("*.texts.json"):
            for row in json.loads(f.read_text(encoding="utf-8"))["strategies"]:
                assert "代价：" not in row["text"]

    def test_bottleneck_fallback_to_intent(self, catalog, tmp_path, curator_scripts):
        """8/113 张卡无 feature_signature.bottleneck，须回退 intent 而非留空。"""
        self._gen(catalog, tmp_path, curator_scripts, category="common")
        doc = json.loads((tmp_path / "cards" / "common.texts.json").read_text(encoding="utf-8"))
        text = {r["strategy_id"]: r["text"] for r in doc["strategies"]}["no-bottleneck"]
        assert "机会：该卡只有意图" in text

    def test_missing_terms_falls_back_without_failing(self, catalog, tmp_path, curator_scripts):
        """检索词缺失 → 回退到结构标签，生成继续（不因外部库新增卡而打停设计链）。"""
        assert self._gen(catalog, tmp_path, curator_scripts) == 0
        doc = json.loads((tmp_path / "cards" / "op-class"
                          / "sort-select.texts.json").read_text(encoding="utf-8"))
        text = {r["strategy_id"]: r["text"] for r in doc["strategies"]}["sel-a"]
        assert "检索词：p-sel-a s-sel-a scalar-serial" in text

    def test_terms_used_when_present(self, catalog, tmp_path, curator_scripts):
        self._gen(catalog, tmp_path, curator_scripts, terms={"sel-a": "堆 候选 快速拒绝"})
        doc = json.loads((tmp_path / "cards" / "op-class"
                          / "sort-select.texts.json").read_text(encoding="utf-8"))
        text = {r["strategy_id"]: r["text"] for r in doc["strategies"]}["sel-a"]
        assert "检索词：堆 候选 快速拒绝" in text

    def test_all_generates_every_pool(self, catalog, tmp_path, curator_scripts):
        assert build_cards.main(["--strategy-root", str(catalog), "--all",
                                 "--out", str(tmp_path), "--quiet",
                                 "--curator-scripts", str(curator_scripts),
                                 "--retrieval-terms", str(tmp_path / "x.json")]) == 0
        assert (tmp_path / "cards" / "common.texts.json").is_file()
        assert (tmp_path / "cards" / "op-class" / "reduction.texts.json").is_file()

    def test_bad_category_dies(self, catalog, tmp_path, curator_scripts):
        with pytest.raises(SystemExit):
            self._gen(catalog, tmp_path, curator_scripts, category="elementwis")

    def test_clip_respects_field_budget(self, tmp_path, curator_scripts):
        """超预算的元数据文本必须被裁到预算内，且不在词中截断。"""
        root = tmp_path / "cat"
        (root / "strategies" / "common").mkdir(parents=True)
        (root / "strategies" / "op-class").mkdir(parents=True)
        long_mech = "；".join(f"分段{i}" for i in range(200))
        (root / "strategies" / "common" / "long.md").write_text(
            _card_md("long", long_mech, generality="common"), encoding="utf-8")
        out = tmp_path / "out"
        assert build_cards.main(["--strategy-root", str(root), "--category", "common",
                                 "--out", str(out), "--quiet",
                                 "--retrieval-terms", str(out / "x.json"),
                                 "--curator-scripts", str(curator_scripts)]) == 0
        rows, errs = cardlib.load_cards_file(out / "cards" / "common.texts.json")
        assert errs == []
        action = [l for l in rows[0]["text"].split("\n") if l.startswith("动作：")][0]
        assert len(action) - len("动作：") <= cardlib.FIELD_BUDGETS["动作"]


class TestCatalogAdapterIsolation:
    def test_malformed_card_does_not_kill_generation(self, tmp_path, curator_scripts):
        """一张坏卡只记入 card_errors，不整体崩溃（隔离 _catalog 的 SystemExit）。"""
        root = tmp_path / "cat"
        (root / "strategies" / "common").mkdir(parents=True)
        (root / "strategies" / "op-class").mkdir(parents=True)
        (root / "strategies" / "common" / "good.md").write_text(
            _card_md("good", "正常机制", generality="common"), encoding="utf-8")
        (root / "strategies" / "common" / "broken.md").write_text(
            "<!-- strategy-metadata\n{ 这不是合法 JSON }\n-->\n\n# 坏卡\n",
            encoding="utf-8")
        out = tmp_path / "out"
        rc = build_cards.main(["--strategy-root", str(root), "--category", "common",
                               "--out", str(out), "--quiet",
                               "--retrieval-terms", str(out / "x.json"),
                               "--curator-scripts", str(curator_scripts)])
        assert rc == 0
        rows, _ = cardlib.load_cards_file(out / "cards" / "common.texts.json")
        assert [r["strategy_id"] for r in rows] == ["good"]


# ── 静态守卫 ────────────────────────────────────────────────────────────────

class TestStaticGuards:
    def _skill_files(self, *globs):
        out = []
        for g in globs:
            out += [p for p in SKILL_DIR.glob(g) if p.is_file()]
        return out

    def test_dependency_declaration_present(self):
        """§2.1 driver 类 skill 必须显式声明仓外依赖，声明块不可被删。"""
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        assert "依赖声明" in text
        assert cardlib.ENV_STRATEGY_ROOT in text
        assert "单源引用" in text

    def test_no_vendored_card_copy(self):
        """不 vendor 策略卡：skill 目录内不得出现策略库的卡片目录。"""
        assert not (SKILL_DIR / "strategy").is_dir()
        assert not (SKILL_DIR / "strategies").is_dir()

    @pytest.mark.parametrize("pattern", ["DAV_", "ascend910", "ascend950", "dav-3510"])
    def test_no_chip_literal_in_skill(self, pattern):
        """芯片命名走代际码；soc_version 字面量只允许出现在 domain/chip.py。"""
        for p in self._skill_files("*/*.md", "*/*.py", "*/*.json"):
            assert pattern not in p.read_text(encoding="utf-8"), p

    @pytest.mark.parametrize("pattern", ["cv-A3", "vec-A3", "FA-A5"])
    def test_no_upstream_category_residue(self, pattern):
        """类目体系是本策略库原生的 common + op-class/<class>，不得残留上游六类。"""
        for p in self._skill_files("*.md", "*/*.md", "*/*.py"):
            assert pattern not in p.read_text(encoding="utf-8"), p

    def test_no_absolute_path_or_home(self):
        for p in self._skill_files("*.md", "*/*.md", "*.py", "*/*.py"):
            t = p.read_text(encoding="utf-8")
            assert "/home/" not in t, p
            assert "Path.home()" not in t, p
            assert "~/.claude" not in t, p

    def test_scripts_are_stdlib_only(self):
        for p in SCRIPTS.glob("*.py"):
            t = p.read_text(encoding="utf-8")
            for banned in ("import numpy", "import requests", "import jsonschema",
                           "import pandas", "subprocess"):
                assert banned not in t, (p, banned)
