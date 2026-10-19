# 化简/降维/等价声称 — 验证检查清单

> 用途：设计阶段（general-design / template-division / tiling）遇到"化简/降维/等价/复用/覆盖"声称时，
> 按本清单验证并声明支持域。**核心判据：支持域 ⊇ 需求(golden)域；未验证必须显式标 `known_limitations`，禁止裸描述。**
> 机制背景：docs/plan/design-math-claims-verification/（L1 D1 / L3 §D1）。

## 声称类型 → 验证方法

| 声称类型 | 示例 | 验证方法 | 工具 |
|---|---|---|---|
| 可穷举 | perm 类型学、rank≤5 置换分类、小空间组合 | 穷举全空间（确定性） | `verify_simplification_claim.py` 穷举段 |
| 可形式化 | 降维等价、reshape 等价、shape 公式 | 代数/集合推导（支持域 = 显式集合） | 形式化声明 + 推导 |
| 可原型 | 地址映射、dtype 转换、broadcast 等价 | numpy/torch **对照 golden** 随机核验 | `verify_simplification_claim.py` 随机段 |
| 可引用 | 已核验事实库条目 | 引用 `verified_facts.md` + 标注核验日期 | `verified_facts.md` |
| 不可验证 | 性能估计、启发式 | **显式标"未验证 + 域限制"** | `known_limitations` |

## 执行要求（LLM 自检，主动验证）

1. **优先写并运行 Python 验证**：把声称操作化为可运行代码（用 `verify_simplification_claim.py` 骨架），
   **对照 golden 函数**（不是自己脑补的期望）穷举/随机核验，得到"声称支持域 vs 实测可覆盖域"。
2. **ground truth = golden**：裁判是 golden（transpose=`np.transpose`），golden 不会撒谎；声称与 golden 冲突即声称错。
3. **能穷举就穷举**（小参数空间全枚举），大空间才随机抽样。
4. **记录验证方法 + 残余风险**：产物写清"验证了什么（穷举范围 / 随机 N / 引用事实）"，残余风险进 `known_limitations`。
   **不把"跑过 Python"冒充"已证明"**。
5. **fail-loud**：断言不通过即失败，触发声称/测试二选一自洽，绝不静默通过。

## 不 halt 规则（含自修语义）

- 脚本跑不通 / 声称被证伪 → **先 agent 内部多轮自修**（改脚本→重跑→再改，§2.9 自检闭环）。
  **"跑不通" = 多次内部尝试后仍跑不通，不是一次机会。**
- 自修不动 → 标 `known_limitations`（reason=验证不可运行/未验证）+ `support_domain`（声明域）→ **继续进入下游**
  （codegen 域对质 / debug 兜底自有保障），**不 halt、不 loopback 空转**。
- 仅当问题**真正不可解且需上游裁决**（需求/golden 歧义、算法不可行需人决策）才走
  `resolve_ambiguity` / `blocking_issues target=human` 通道。

## 产物要求（写进设计产物）

> **support_domain 必须是结构化 schema**——**单一权威契约见
> `ascendc-op-design-shared/schema/support_domain.json`**（与需求侧 `requirement.json.domain`
> 共享词汇表，供 codegen 域对质引擎 `domain/support_domain.py` 机器解析；结构由
> `domain/support_domain.py::validate_support_domain_structure` 在 validate 阶段加载期校验）。
> 核心形态：`rank` 是 `{min,max}` dict、`inputs` 是 `[{"name","dtypes"}]`、`attrs` 是
> `[{"name","domain":{kind,constraint}}]`。**禁止写成 prose 字符串**（如 `"rank": "1..8"`）——
> 引擎按结构化解析，prose 会无法对质（降级为保守缺口）。`desc` 仅作人读附属。

```json
"support_domain": {
  "desc": "（可选，人读）声称支持的输入域",
  "rank": {"min": 1, "max": 8},
  "inputs": [{"name": "x", "dtypes": ["float16", "float32"]}],
  "attrs": [{"name": "perm", "domain": {"kind": "permutation", "constraint": "any"}}]
},
"known_limitations": [
  {"claim": "kernel 只支持循环旋转 perm", "reason": "未验证/不可运行/域限制", "residual_risk": "非循环旋转 perm 输出错误"}
]
```

## 参考

- 验证模板：`verify_simplification_claim.py`（同目录，骨架已知正确，LLM 只填算子特定声称逻辑）。
- 已核验事实：`verified_facts.md`（同目录）。
- transpose 完整示例：`docs/plan/design-math-claims-verification/verify_transpose_perm.py`。
