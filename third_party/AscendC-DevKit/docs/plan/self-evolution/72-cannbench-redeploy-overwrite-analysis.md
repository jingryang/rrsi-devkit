# 72 — deploy install_python pip --target 不覆盖 per-op 包（P99）方案分析

> 层级：**L3 / 方案分析**。回答「有哪些选项、选了哪个、为什么」。
> 问题事实见 `06-problems.md` [[P99]]；实施见 `72-cannbench-redeploy-overwrite-impl.md`。

## 问题域

P98 修复后（smoke PASS）rerun，cannbench_eval 仍 `operators=[]`：`pip install --target --force-reinstall` 不覆盖 per-op 包已存在的文件，redeploy 后 per-op `__init__.py` 残留旧版（无 exp wrapper），eval `scan_interfaces` 第 1 路 `dir(cann_bench)` 发现不到 exp。

- **打包链正确**：agent 改 example 源 `__init__.py`（加 exp wrapper）→ build.sh whl 实含 exp wrapper（unzip 实证）。
- **断点在 install**：`pip install --target <per_op_python> --force-reinstall` 遇已存在的 `cann_bench/` 不覆盖 `__init__.py`（pip `--target` 已知行为；`--force-reinstall` 不强制覆盖已存在文件）。
- deploy install_python 原只清 `__pycache__`（不清包目录），无法绕过；per-op `__init__.py` mtime 停在原始 run（16:02:32），rerun 19:18:20 的 install 未更新它。

## 归属判定（排除法 + 反证）

- **框架缺陷**（非 cann-bench、非 transient）：修复落在 devkit deploy 的 install_python 步骤。确定性（任何 cann-bench 算子 redeploy 复现）。
- 非 cann-bench 侧（whl 打包正确）、非 [[P98]]（symbol 修复正交，已让 smoke 通过）。
- 是 [[P97]] 方案 1（redeploy per-op）的实施缺陷：redeploy 命令成功执行，但未真正覆盖 per-op 包文件。

## 选项与取舍

**问题**：让 redeploy 真正覆盖 per-op 包。

| 选项 | 做法 | 取舍 |
|---|---|---|
| ① install_python pip 前清空 per_op_python_dir（选）| `iterdir` → rmtree 目录 / unlink 文件 | ✓ 构造性保证（空目录 + pip = 干净覆盖）；通用（不依赖包名）；per-op 隔离 dir 清空安全 |
| ② pip 加 --upgrade | `pip install --target --upgrade` | ✗ pip `--target` + `--upgrade` 对已存在文件覆盖行为不可靠（已知 pip 缺陷） |
| ③ 改 cann-bench build | 让 whl install 强制覆盖 | ✗ cann-bench 外部只读；且根因在 deploy 调用方式，不在 whl |

**选 ①**：`per_op_python_dir` 是 per-op 隔离的 whl target dir（`_per_op_path`，`<run-artifacts>/per-op/<op>/python/`），专为该算子 whl，清空其内容让 pip 干净重装——直接表达「redeploy = 重新 install」语义，不依赖包名或 pip 覆盖行为。

## 拍板

- **修复**：install_python 步骤 pip 前清空 `per_op_python_dir` 内容（选项①）。
- **归属**：`deploy.py` `_run_command` 的 install_python 分支。
