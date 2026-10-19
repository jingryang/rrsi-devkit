# omni-ops profile 部署链与框架契约错位 — 问题记录（L1）

> 纯事实快照（哪里坏了 / 凭什么这么说）。不提方案、不排顺序、不写决策。
> 来源：真实 run `20260831-104218-2dce42`（cross_entropy_sumexp_and_index_logit / omni-ops /
> training 变体），`run.log` + DevKit 工作区 diff + CANN 打包模板 `install.sh` 源码实证。
> 时间均为本地时区（UTC+8）。

## 触发场景

`omni-ops` 是「目标算子仓」的 profile：框架的 `Deployer` 按 profile 里声明的 `role`
（build / install_runtime / install_python / smoke）驱动一条链——编译产物 → 装到 per-op 目录
→ smoke 验证真能调。该 profile 在本次修复前只有 2 个 build stage、无 `role` 声明，且
`install_runtime`（当时以现场补丁形式存在）把算子装到一个**固定的机器专属 CANN 根**。

框架侧则把「去哪儿找算子注册信息」这个路径钉死成一个变量：

```
env["ASCEND_CUSTOM_OPP_PATH"] = expected_ascend_custom_opp(per_op_opp_dir)
  # 值 = f"{per_op_opp_dir}/vendors/custom_ops"（infra/env_contract.py 单一实现点）
  deploy.py:889（smoke env） / runner.py:540（harness） / cannbench_env.py:163（评测）
```

（行号以目标仓当前实现为准；`expected_ascend_custom_opp` 是值形态的单一实现点，
`tests/ut/infra/test_env_contract.py` + `tests/ut/adapters/npu/test_harness_env_contract.py`
做源级守护，禁裸 f-string 二次拼接。）

两边一个写死 A、一个只读 B → 缝。本记录即该缝及同类错位的事实。

## P1 — install_runtime 装到固定 CANN 根，框架只读 per-op 视图 → 算子不注册，dlsym 守卫崩

- profile 的 `install_opp` 命令（run.log 实证）：

  ```
  bash .../CANN-omni_training_custom_ops--linux.aarch64.run --quiet \
       --install-path=/home/z00943229/cann/0831base
  ```

  固定的机器专属路径，且安装落点是 `<root>/vendors/omni_training_custom_transformer/`，
  与框架读取的 `<per_op_opp_dir>/vendors/custom_ops` **既不同位置、也不同目录名**。

- 框架 smoke/harness 无条件把 `ASCEND_CUSTOM_OPP_PATH` 指向 per-op 空目录（赋值覆盖，
  非追加），故看不到上面那份。

- 崩点实证（run.log `19:42:19`，codegen coder 判定）：

  > `host_phase_launch_failed` 的崩点是 `EXEC_NPU_CMD_V1` 的 dlsym 守卫（launch 之前），
  > 守卫读取的 `ASCEND_CUSTOM_OPP_PATH` 被框架 smoke 无条件覆盖到 per-op 空目录，
  > 而 omni-ops profile 的 install_runtime 刻意全局安装——**该 env 缝由框架(deploy.py)×
  > profile(omni-ops.yaml)组合决定，codegen 任何产物无法影响**。

  同条记录附控制变量实验：同一份产物在 env 修正后 kernel 正常执行（`kernel_done 560.4ms`）。

- 影响：codegen 在空视图上反复 smoke 失败（run.log 记 `codegen smoke failed` 3 次），
  最终 `Stage 'codegen' reached max iterations (40) without satisfying output_contract;
  missing: ['generated_sources', 'build_result', 'deploy_result']`。

## P2 — torch_ext 的 whl 落在子目录，Deployer 只搜「第一个 build stage 的 dist」

- Deployer 的产物定位（`deploy.py:1004-1006`）：

  ```python
  build_cwd = (repo_root / (build_stages[0].cwd if build_stages else ".")).resolve()
  dist_dir = build_cwd / "dist"
  whl_pkg  = self._find_file(dist_dir, "*.whl")
  ```

  只搜**第一个 build stage 的 cwd** 下的 `dist/`。

- 原命令 `bash build_and_install.sh` 做的事（仓内脚本源码）：`python3 setup.py build
  bdist_wheel`（whl 落在 `torch_ops_extension/dist/`）+ `pip3 install *.whl --force-reinstall`
  （装进当前 conda 的 site-packages，**无路径参数**）。

- 两者错位：whl 留在 `torch_ops_extension/dist/`，Deployer 不搜该处 → `whl_pkg = ""`
  → `DeployResult.wheel_package` 为空（`deploy.py:1023/1033`）。

## P3 — 用户 CLI 相对路径跨进程即断

- `dispatch()` 把 CLI 路径字段写进 `State`，随后序列化进 `state_snapshot.json`
  （`dispatcher.py:_write_state_snapshot`，`json.dumps(..., default=str)`）。
- 下游是**独立进程**：`run-cases` / `redeploy` CLI 子进程、harness 子进程——各自 cwd 与
  初始进程不同（`run-cases` 的用户 cwd 是 `operator_dir`）。
- 修复前这些字段只经 `Path(v)` 包裹、**未 resolve**，相对路径被原样写入快照 → 下游按自己的
  cwd 解析 → `FileNotFoundError`（golden 相对路径在 harness 加载 golden 前即死亡）。
- 同性质字段 `op_dir` / `repo_root` 亦同。

## P4 — harness `_to_np_list` 不认 dict 返回

- `_harness_template.py` 的 `_to_np_list(out)` 只处理 `tuple` / `list`；多输出 golden 以
  **dict 按名返回**（常见形态）时落入末支 `_to_np(out)` → `np.asarray(dict)` 退化为 0-d
  `object_` 数组 → 下游 `torch.as_tensor` 失败。
- 模块自带的逐字节 golden 回归门（`tests/ut/adapters/test_runner_execute.py::
  TestHarnessExtractionSnapshot::test_harness_matches_golden`）与
  `fixtures/harness_devkit_golden.txt` 同步：改动模板须同步该 fixture，否则门失败。

## P5 — 对照事实：vendor 目录名两变体不同，且不能是 symlink

- `VENDOR_NAME` 由 CMake 定义，**两变体不同名**：
  `training` → `omni_training_custom_transformer`（`training/ascendc/CMakeLists.txt:18`）、
  `inference` → `omni_custom_transformer`（`inference/ascendc/CMakeLists.txt:18`）。
- `.run` 安装包把注册信息装到 `<install-path>/vendors/<VENDOR_NAME>/`；框架只认目录名
  `custom_ops` → 需把该目录落到 `vendors/custom_ops`。
- 框架读到的视图必须是**真实目录**（`op_api/lib/libcust_opapi.so` 供 dlsym 链、
  `op_impl`/`op_proto` 供 nnopbase 加载注册信息）——symlink 形态会触发 nnopbase 拒绝加载
  （认证信号：`161001 "SoC not configured / binary_info_config not loaded"`）。
- `.run` 的 `install.sh` 只要求 `--install-path` 为**绝对路径且可写**，不要求是 CANN 根
  （CANN 打包模板 `scripts/install.sh:45-57`，绝对路径校验在 L46-49、可写性在 L50-57）
  ——故可直接装进 per-op 目录，无需中转。

## 载体事实

- profile 无「指定安装路径」字段：`BuildStage` 仅 `name/cwd/command_template/default_chip/
  enabled/role`；`{per_op_opp_dir}` / `{per_op_python_dir}` / `{run_pkg}` / `{whl_pkg}` 由
  Deployer 运行时注入（`domain/repository.py:272-300`；`deploy.py:332` `_per_op_path`）。
- per-op 路径随 run 与算子生成：`<output_root>/<run_id>/artifacts/per-op/<op_name>/{opp,python}`。
- `has_deploy_capability()` 硬要求 profile 声明 `install_runtime` + `smoke`
  （`domain/repository.py:71` `_DEPLOY_ROLES` / `:310` `has_deploy_capability`），不满足时
  Deployer 报 "declares no deploy roles" 退出。
