# P3 环境契约守护 — L4 实施方案（2026-08-30）

> 层级：**L4 / 实施方案**。改哪个函数、什么顺序、怎么验证。
> 上游：`04-analysis-env-contract-guard.md`（L3，已拍板冻结）。
> 盘点结论（2026-08-30 已实证，不留 TBD）：
> ① 预检挂载点 = `dispatcher._check_runtime_once → _run_runtime_checks`（既有
> Check 1 CANN toolchain / Check 2 NPU smoke 子进程，带缓存+锁）——env 探针为
> **Check 3**，共享全部结构（§1.15）；
> ② harness 单点 = `adapters/npu/_harness_template.py`（1018 行模板，`$npu_id`
> 等占位符替换；smoke/run_tests/precision 全部 harness 同源生成）；
> ③ harness 退出码现状 = 裸 `sys.exit(1)`（:77/:411），专用码可安全新定。

## 改动 1：`infra/env_contract.py` 新模块（不变式 + 探针单实现）

先例：`infra/npu_probe.py`（step-106 单点先例）。内容：

```python
ENV_CONTRACT_EXIT_CODE = 90          # harness 侧专用退出码（现模板仅用 1，90 无冲突）
_ENV_CONTRACT_MARKER = "[ENV_CONTRACT]"   # stderr 可 grep 标记（skill 引用语义词，不引数字）

def ascend_custom_opp_intact(expected: str, actual: str) -> bool:
    """成员断言：expected 必须是 actual 冒号列表的元素（CANN 语义允许合法追加）。"""

def probe_env_contract(env: dict, timeout_sec: float = 10.0) -> str | None:
    """spawn 纯 stdlib 子进程（python -c "import os; print(...)"，不 import
    torch/torch_npu——step-104 主进程纯度红线），回读 ASCEND_CUSTOM_OPP_PATH，
    与 env 中期望值做成员断言。返回 None=通过；str=失配诊断行（期望 vs 实际）。"""

def diagnose_env_hooks() -> list[str]:
    """仅失败路径调用：试探 import sitecustomize / 列 user-site 路径与 mtime，
    措辞'候选成因'报事实。纯只读。"""

PREFLIGHT_PROBE_VALUE = "/tmp/devkit-env-preflight/vendors/custom_ops"
# 形态忠实（§L3 硬约束）：后缀必须真实——哑值触发不了后缀匹配类毒。

def warn_system_vendor_collisions(op_names: list[str]) -> None:
    """撞名 WARN：从 $ASCEND_OPP_PATH 运行时派生（不硬编码路径），查
    <opp>/vendors/**/<op_name> 精确匹配，命中打 Logger.warn 一行，不拦跑。"""
```

> **As-built 回填**：`diagnose_env_hooks` 实现为只读文件系统扫描（PYTHONPATH
> 目录 + user-site 找 `sitecustomize.py`/`*.pth`），**不 import sitecustomize**
> ——避免主进程执行毒本体（上方 docstring「试探 import sitecustomize」为设计期
> 表述，实施时按此收紧）。

## 改动 2：dispatcher 预检 Check 3（扩进 `_run_runtime_checks`）

- Check 3 = `probe_env_contract(env={**os.environ, ASCEND_CUSTOM_OPP_PATH:
  PREFLIGHT_PROBE_VALUE})`；失配 → `Logger.error` 诊断行（含 `diagnose_env_hooks()`
  输出）→ `return EX_CONFIG`——**与 Check 1/2 同一返回码惯例，零新增控制流**（L3
  所述 EnvironmentNotAvailable 语义按代码库实际惯例细化：预检=返回码；deploy=raise，
  见改动 3）。
- 撞名 WARN 在 `run()` 内 workflow 解析后调 `warn_system_vendor_collisions([op_name])`
  （有状态依赖，不进无状态可缓存的 `_run_runtime_checks`）。

## 改动 3：deploy 尾探针（真实生产值）

`orchestration/stages/deploy.py` env 构造点（:857 区域）装完 `.run` 后：
`probe_env_contract(env)` 失配 → `raise EnvironmentNotAvailableError(诊断行)`
（pause 家族既有语义——preserve + EX_CONFIG，走 §1.15 `_terminate_preserving`）。

## 改动 4：harness 模板断言（生成器单点）

`_harness_template.py` 入口段（现有 `os.environ.setdefault('ASCEND_NPU_ID', ...)`
旁）追加：

- 期望值占位符 `$expected_opp_path`（渲染时从 deploy 同一 env 构造函数取值——
  **活值单源**，防 resume 换 exec 目录后的 stale 假红）；
- 失配 → stderr 三要素（`[ENV_CONTRACT]` 标记 + 期望 vs 实际值 + 归属指引一行：
  环境问题非代码问题，按 ownership 交棒；勿改系统目录自建通路）→
  `sys.exit(ENV_CONTRACT_EXIT_CODE)`。
- 同模板渲染的全部 harness（smoke/run_tests/precision）自动覆盖。

## 改动 5：coder skill 两行（通用语义，无编号无算子名）

smoke/ownership 节追加：
1. 验证脚本以环境契约专用错误（stderr 含 `[ENV_CONTRACT]` 标记）失败 ⇒ 环境问题
   非代码问题，按 ownership 判 not_codegen 交棒；
2. 禁止以写系统目录/改共享环境的方式自建通路。

## 实施顺序（TDD，§3.1）

1. **红测**（`tests/ut/infra/test_env_contract.py`）：
   - 成员断言：追加通过 / 剥离失败 / 全等通过；
   - 探针：干净 env 通过；**确定性模拟毒**——tempdir 造 `sitecustomize.py`（后缀
     剥离同款逻辑），`PYTHONPATH=<tempdir>` spawn（sitecustomize 按 sys.path 加载，
     机制级真实复现，不 mock）；form-faithfulness：哑值探不出该毒、形态忠实值探出；
   - 撞名：tmpdir 造 `$ASCEND_OPP_PATH` 命中/静默；
   - 诊断：只读性（无写调用）。
2. **红测**（dispatcher/deploy 既有 UT 文件）：Check 3 失配 → EX_CONFIG + 诊断行；
   deploy 探针失配 → EnvironmentNotAvailableError + preserve 路径（复用 step-107
   `_terminate_preserving` 回归网）。
3. **红测**（模板渲染 UT）：渲染产物含 `[ENV_CONTRACT]` 标记与活值烘入的期望值
   （字符串级断言；两轮渲染换 env 值 → 期望值跟随，守护 stale 防范）。
4. 实施改动 1 → 红测转绿；改动 2/3 → 绿；改动 4 → 绿；改动 5（无 UT，skill prose）。
5. 回归：全量 UT（PYTHONPATH=src，共享机 editable 陷阱）+ 定向 ST（deploy/precision
   harness 路径）。

## 验证

```bash
PYTHONPATH=src pytest tests/ut/infra/test_env_contract.py -x
PYTHONPATH=src pytest tests/ut/application/test_application.py -k "env_contract or preserve or runtime_check"
PYTHONPATH=src pytest tests/ut   # 全量（§3.6 预检）
PYTHONPATH=src pytest tests/st -k "deploy or harness"   # 定向 ST
```

不新增 heavy_llm（无 LLM 链路）。端到端判据 = 下批批跑：毒若再现，开跑数秒
`[ENV_CONTRACT]` 拦截（对照本批 10h 空烧）；干净环境零变化（三检测全只读、
<1s、不占卡）。

## 判据（完成的定义）

- 成员断言语义三例（追加/剥离/全等）UT 全绿；
- 机制级模拟毒（真实 sitecustomize 子进程）被探针命中，哑值探不出（形态忠实守护）；
- 全部 harness 渲染产物含断言段，期望值随 env 单源变化（stale 防护）；
- deploy 失配走 pause 家族（不回滚树——step-107 不变式延伸）；
- 预检/探针子进程零 torch import（step-104 纯度）；
- grep 验收：`ascend_custom_opp_intact` 仅存在于 `infra/env_contract.py`（§1.15）。

## 风险清单

| 风险 | 缓解 |
|---|---|
| 未来 CANN 规范化值 → 假红 | 失败信息双值对照 10 秒可判；拦在开跑级，代价=一次启动 |
| resume 后 exec 目录变化 → stale 期望值 | 期望值渲染时从活 env 单源取；UT 两轮渲染守护 |
| 预检子进程在 6 并发下争用 | 单次 ~0.3s、纯 stdlib、无卡；与 Check 2 同量级 |
| 专用退出码 90 与外部脚本冲突 | harness 现仅用 1；90 保留位；标记以 stderr `[ENV_CONTRACT]` 为准（skill 引用语义词） |
