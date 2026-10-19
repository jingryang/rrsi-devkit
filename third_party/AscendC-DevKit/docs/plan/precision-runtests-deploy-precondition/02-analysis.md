# L3 方案分析 — run_tests deploy-precondition + Step 0 断言收紧（已冻结）

> 对应 L1 P1-P9。2026-08-25 用户拍板立项（"不要遗漏已经发现的所有问题"），冻结。

## 0. 产权框架

- **数值权威 golden、结构权威设计**（step-88 已确立，本次不涉及）。
- **host 侧缺陷产权（用户拍板）**：codegen 优先解决（确定性 host 证据 → `_smoke_retry` 自闭环；无证据 → K 守卫强制真重试 ≥K 后才允许 coder 判定放行——既有机制不动）；**泄漏到 precision 的必须兜底就地修复**，不是上报——因 `upstream_signal` 语义是 halt 整 run（0 分），与 fail-open（halt 仅预算耗尽/真超范围）冲突。上报仅保留：golden 语义错 / devkit 框架自身抛错 / 编译依赖缺失无法本地补。
- **测量前提是构造性保证**（§2.9）：redeploy→run-cases 的文件接力契约（§2.3）在测量前由框架确定性保证，不做事后错误分类。

## 1. 方案（四项改动）

### 改动 1：RunMeasure deploy-precondition（主修复，P1/P2/P3）

`_build_measure_command` 在 init 段后、run 段前插入（每轮幂等）：

```bash
# 可用性判定：install_path AND python_path 非空（结构字段判据，§1.10/§1.12）
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if d.get("install_path") and d.get("python_path") else 1)' <last_deploy.json> 2>/dev/null \
  || { echo "[deploy-precondition] last_deploy.json missing/unusable — running redeploy"; <build_command> || true; }
<同上可用性判定> \
  || { echo "FATAL: redeploy produced no usable last_deploy.json (install_path/python_path empty)" >&2; exit 1; }
```

- **判据是"记录可用"不是"文件存在"**（P2：空路径记录必须触发 redeploy）。
- **redeploy 的 rc 不是判据**：redeploy CLI 在 deploy 失败时 `sys.exit(1)`（debug.py:59-60）但已无条件落盘——smoke 失败/部署中间态失败均容忍，只看落盘结果。
- 仍不可用 → FATAL exit 1：真部署 infra 坏，measurement abort 熔断此时才正确（P3 的确定性错误从此不可能出现；rc≠0 重试+熔断只剩真 infra，fail-open 语义归位）。
- `build_command`/debug 目录缺失（无 workspace 边缘态）→ 整段跳过，行为同旧（run-cases 自身诚实报错）。
- 可观测性：`[deploy-precondition]` echo（§1.2）。

### 改动 2：Step 0 断言收紧（P4，三处同步：SKILL.md / manifest / `_phase_prompt`）

"工程内可修的"从例子枚举改为可判定断言（§2.12）：

> **凡修复目标代码在算子工程内的缺陷一律就地修**——含 host 侧 tiling/launch/注册/脚手架（不因根因属上游生成而推诿；plugin/manifest/注册仅为子集例）。仅以下三类如实上报：golden 语义错 / devkit 框架自身抛错 / 编译依赖缺失无法本地补。

### 改动 3：build-failed-case-queue.py docstring 修正（P6）

陈旧"route directly to comment_bisect"文案改为 post-P3 事实（路由进 diagnose，comment-bisect 是 diagnose 的就地技巧）。只改文档不动路由。

### 改动 4：验证（P5 + 端到端严谨性）

- TDD UT：命令构造（含前提段/无 build_cmd 跳过）+ **shell 语义真实执行**（不可用→fake redeploy 写可用记录→通过；redeploy 后仍不可用→FATAL exit 1）。
- **事故现场离线实证**：对 20260825-083544-608989 真实 run 目录执行 redeploy（容忍失败）→ 验证 last_deploy.json 落盘且路径非空 → run-cases 全量 → 验证 crash 哨兵 + exit 0 + 队列可建——在被修的真实事故数据上走完整条链。
- heavy_llm 真实批跑端到端：§3.11 待用户决策。

## 2. 否决项（含理由，勿回潮）

| 否决 | 理由 |
|---|---|
| abort stderr 签名分类（识别 no last_deploy.json 后分流） | 构造性保证优先于检查门（§2.9）；改动 1 落地后该签名不可能出现，分类是死代码 |
| codegen 成功路径也写 last_deploy.json（省首轮 redeploy） | 破坏 redeploy 单一写入者（§2.5/§2.3 契约单点）；首轮 ~45s 是契约本来代价（P8） |
| 调整 K 守卫/熔断阈值/放大倍率 | 弱模型误判已由换模型解决；机制层无实证缺陷；不过度设计（§1.14） |
| 修 P69 card 隔离旁路 | 既有问题另有产权，新前置行为与 diagnose build_command 一致（P7 声明） |
| result.json 缺失脚本级兜底建队列 | CLI 级失败场景熔断语义本就正确；为罕见边角加机制违反 §1.14（P9 声明） |

## 3. 四把尺子

- **可维护**：恢复被 N1 弄断的文件接力契约；前提单点（`_build_measure_command`）；写入者单点不变。
- **可扩展**：所有算子、smoke 成败两态、fresh/resume 全部入口自动正确。
- **可诊断**：`[deploy-precondition]`/FATAL 明示原因；空路径记录触发可观测动作而非静默误测。
- **架构合理**：前提在测量边界（框架）；失败性质判断在 diagnose（模型）；codegen 自闭环不动。

## 4. 关联教训（L1 末节）

去 LLM 化必须枚举 agent 隐式前置为显式确定性步骤；fresh-entry 形态须有测试看护（本次 UT 的 shell 语义真实执行即为此）。
