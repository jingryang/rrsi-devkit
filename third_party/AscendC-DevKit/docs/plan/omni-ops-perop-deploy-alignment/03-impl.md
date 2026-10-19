# omni-ops 部署链对齐 per-op 契约 — 实施方案（L4）

> 产权：本文件对应 L1 `01-problems.md` 的 P1–P4（P5 是约束事实，非缺陷）。
> 状态：已实施 + UT 通过（2026-09-11）。

## 总览

三条独立的错位，共用一条原则：**让 profile 声明的落点与框架实际读取/定位的路径一致**
（profile 只描述「这个仓怎么编」，路径由框架的 role 契约统一决定）。

| L1 问题 | 改动位置 |
|---|---|
| P1 装到固定 CANN 根 | `resources/repository-profiles/omni-ops.yaml` 的 `install_runtime` stage |
| P2 whl 落点 Deployer 搜不到 | 同文件 `build` stage（`torch_ext`） |
| P3 相对路径跨进程断 | `src/ascendc_devkit/application/dispatcher.py` |
| P4 harness 不认 dict | `src/ascendc_devkit/adapters/npu/_harness_template.py` |

## P1 — install_runtime 装进 per-op 目录

### 根因

装到固定机器路径，且目录名与框架约定不符 → 框架 smoke/harness 读不到算子注册信息。

### 改动（`omni-ops.yaml`，两变体各自）

```yaml
- name: install_opp
  role: install_runtime
  command_template: "bash {run_pkg} --quiet --install-path={per_op_opp_dir} && \
    rm -rf {per_op_opp_dir}/vendors/custom_ops && \
    mv {per_op_opp_dir}/vendors/<VENDOR_NAME> {per_op_opp_dir}/vendors/custom_ops"
```

要点：
1. `--install-path={per_op_opp_dir}` —— 装进框架读取的位置（`install.sh` 只要求绝对路径
   且可写，已核实 CANN 模板源码），消掉固定路径中转。
2. `mv` 而非 `cp -r` —— 同一文件系统内重命名，省一次完整拷贝。
3. `<VENDOR_NAME>` 两变体不同（`omni_training_custom_transformer` /
   `omni_custom_transformer`），**不可复用**；用真实目录，不用 symlink（L1 P5）。

### 验证

- `tests/ut/adapters/test_adapters.py::TestProfileLoader::test_omni_ops_install_opp_targets_framework_view`
  —— 断言 `--install-path={per_op_opp_dir}` 与 `vendors/custom_ops` 均在命令中。
- 同文件 `test_omni_ops_variants_deploy_capable` —— 断言两变体 `has_deploy_capability()`。

## P2 — whl 落到第一个 build stage 的 dist/

### 根因

`Deployer` 只从第一个 build stage 的 cwd（`training/ascendc`）下找 `*.whl`，而原脚本把 whl
留在 `torch_ops_extension/dist/`。

### 改动（`omni-ops.yaml`，两变体各自）

```yaml
- name: torch_ext
  role: build
  command_template: "rm -rf build && python3 setup.py build bdist_wheel && \
    mkdir -p ../dist && cp dist/*.whl ../dist/"
```

要点：
1. `cp` 到上层 `dist/`（= 第一个 build stage 的 cwd/dist）供 Deployer 定位。
2. 去掉脚本自带的 `pip3 install`（全局装）——安装交给 per-op 隔离的 `install_python` stage。
3. `rm -rf build` 保留原脚本的 bdist_wheel 缓存清理（框架侧无 `clean_dirs` 覆盖该目录）。
4. `enabled: false → true`：per-op 流程需要它真正产出 whl。

### 验证

`test_profile_templates_use_no_absolute_paths`（防路径回潮）+ yaml schema 门
（`test_all_shipped_profiles_pass_schema`）。

## P3 — CLI 路径字段入口锚定

### 根因

相对路径写入快照后，下游独立进程按各自 cwd 解析即断。

### 改动（`dispatcher.py::dispatch`）

```python
def _cli_path(v):
    # 入口边界锚定为绝对路径；下游各进程 cwd 不同，入口 resolve 一次即可
    return Path(v).resolve() if v else None

target_repo = _cli_path(...); req_path = _cli_path(...); design_doc = _cli_path(...)
golden = _cli_path(...); cases_path = _cli_path(...); detailed_dd = _cli_path(...)
op_dir = _cli_path(...); repo_root = _cli_path(...)
```

覆盖全部 8 个 CLI 路径字段（单点抽象，不留裸 `Path()` 例外）；空值 → `None`
（避免 `Path('').resolve()` 退化成 cwd）。`State(...)` 处改引用变量。

### 验证

`tests/ut/application/test_dispatcher_path_anchoring.py`（9 条）：
7 个字段参数化断言 `is_absolute()` / 相对 golden 解析到入口 cwd / 空值保持 `None`。
逐条对改前版本重跑确认为「本用例断言失败」而非环境错误。

## P4 — harness 认 dict 返回

### 改动（`_harness_template.py::_to_np_list`）

```python
if isinstance(out, dict):
    out = list(out.values())   # Python 3.7+ dict 保序，值序 = golden 声明的输出序
```

### 验证

同步 `tests/ut/adapters/fixtures/harness_devkit_golden.txt`（逐字节 golden 回归门要求），
`test_harness_matches_golden` 通过。

## 全量回归

| 范围 | 结果 |
|---|---|
| `tests/ut/adapters/` | 558 passed, 16 skipped |
| `tests/ut/application/` | 237 passed |
| `tests/ut/orchestration/test_deploy.py` | 65 passed |

> 注：本仓测试须显式 `PYTHONPATH=<repo>/src` 运行——`ascendc-devkit` 以 editable 方式
> 安装在源仓，否则测试会解析到源仓实现，产生跨仓误判。

## 未覆盖 / follow-up

- 两条 minor 未处理：`mv` 非幂等（中途失败重跑可能 no such file）；
  `install.sh` 生成的 `bin/set_env.bash` 在 `mv` 后内容过期（框架不读它，仅会误导手动跑的人）。
- 两变体的 `install_opp` / `install_whl` / `smoke` / `torch_ext` 命令体逐字重复，
  仅 vendor 名与 cwd 前缀不同——profile 模型无 variant 继承机制，属既有结构限制。
