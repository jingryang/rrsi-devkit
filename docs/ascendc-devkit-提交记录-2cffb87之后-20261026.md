# `2cffb87` 之后的提交都在解决什么问题

- 仓库：`/home/s00940212/experiment/rrsi-devkit`
- 范围：`2cffb87..HEAD`（3 个提交）
- 当前 HEAD：`e9fd190`
- 日期：2026-10-26
- 说明：这 3 个提交此前未推送到 `origin`，2026-10-26 已把提交信息补写为详细中文（代码树未变），因此哈希已由 `693877a / 0c4f17f / 77ee62b` 变为 `0ccddac / fb091e5 / e9fd190`

---

## 0. 结论速览

| 提交 | 时间 | 主题 | 解决的问题 | 类型 |
|---|---|---|---|---|
| `0ccddac` | 2026-10-23 18:01 | 把 ascendc-devkit 接上本机，并把进化任务收窄为 swi_glu | 仓库配置指向另一台机器；venv 解释器被 `resolve()` 抹掉；进化任务换成 `swi_glu` | 环境接线 |
| `fb091e5` | 2026-10-24 01:13 | 深度推理的 codegen turn 放宽到 600s 再触发看门狗 | 180s 的 turn-stall 看门狗误杀 deepseek 长推理，codegen 5 次重试全被打断 | 稳定性 |
| `e9fd190` | 2026-10-24 01:20 | 把 ascendc-devkit 的卡池换到 NPU 6 | NPU 3 卡的 device context 被宿主机孤儿进程占满，open-device probe 全失败 | 硬件绕行 |

三个提交都是**为把实验在这台机器上拉起来**做的环境/稳定性修复，没有改 RRSI 的算法逻辑。三次提交对应前三次失败的逐步排除：第一次解决“路径和解释器不对”，第二次解决“看门狗误杀”，第三次解决“卡被占”。

---

## 1. 起点：`2cffb87`

```
2cffb87 Add the first ascendc-devkit RRSI run report
```

这是上一轮实验留下的运行报告提交，本身不改代码。它是本次 `2cffb87..HEAD` 区间的起点；之后的三个提交才是在这台机器上真正把实验跑起来所做的修改。

---

## 2. `0ccddac` — 把 ascendc-devkit 接上本机，并把进化任务收窄为 swi_glu

**时间**：2026-10-23 18:01:17
**改动文件**：3 个，+23 / −12

### 2.1 解决的问题

这一提交同时解决了四个会让实验“根本起不来”的问题。

#### 问题 A：配置指向另一台机器

`domains/ascendc-devkit/rrsi.json` 里还是旧机器的路径：

| 配置项 | 修改前 | 修改后 |
|---|---|---|
| `cann_bench` | `/home/s00940212/experiments/cann-bench`（复数） | `/home/s00940212/experiment/cann-bench` |
| `python` | `/home/ma-user/anaconda3/envs/PyTorch-2.10.0/bin/python` | `/home/s00940212/venvs/rrsi-agentic/bin/python` |
| `cann_env` | `/usr/local/Ascend/cann-9.1.0/set_env.sh` | `/mnt/paas/gyx/cann/install/cann-9.1.1/set_env.sh` |
| `chip` | `""`（自动探测） | `"A5"`（显式指定） |

这些路径在本机都不存在（`experiments` 是复数、`ma-user` 用户不存在、CANN 版本是 9.1.1 而不是 9.1.0）。不改的话，`bench.config.validate_environment()` 会直接报缺失项，trial 连环境检查都过不了。

#### 问题 B：venv 解释器被 `resolve()` 解析掉

`domains/ascendc-devkit/bench/config.py` 原来用 `_path()` 读取解释器路径，而 `_path()` 内部会 `value.resolve()`。venv 的 `bin/python` 是指向基础解释器的符号链接：

```
/home/s00940212/venvs/rrsi-agentic/bin/python
  → /opt/uv/python/cpython-3.13.14-linux-aarch64-gnu/bin/python3.13
```

`resolve()` 会把 venv 路径抹掉，后续子进程就用了基础解释器，**丢失 venv 的 site-packages**（没有 torch / torch_npu），评测直接失败。

修复：新增 `_executable_path()`，只做相对路径展开和 `.absolute()`，不解析符号链接：

```python
def _executable_path(key: str, default: str) -> Path:
    """读取解释器路径：只做相对路径展开，不 resolve 符号链接。"""
    value = Path(str(_get(key, default))).expanduser()
    if not value.is_absolute():
        value = DOMAIN_DIR / value
    return value.absolute()
...
PYTHON = _executable_path("python", "/usr/local/python3.12.13/bin/python")
```

#### 问题 C：进化任务要换成 `swi_glu`

按要求“当前只用一个算子进化”，把 evolve split 和 smoke 门都从 `exp` 换成 `swi_glu`：

- `domains/ascendc-devkit/data/ops_train.txt`：`tasks/level1/exp` → `tasks/level1/swi_glu`
- `rrsi.json`：`smoke_ids: ["exp"]` → `["swi_glu"]`

任务 id 取自 golden 入口函数名（`swi_glu`），不是目录名，这是 `tasks.py` 的解析规则。

#### 问题 D：成本参数

| 配置 | 修改前 | 修改后 | 原因 |
|---|---|---|---|
| `trial_timeout_sec` | 14400（4h） | 28800（8h） | 一次完整 trial 要 5–7h，4h 不够 |
| `max_attempts` | 3 | 1 | 失败不自动 ×3 重试，避免一次故障烧掉 20+ 小时 |

### 2.2 验证

- `bench.config.validate_environment()` 返回 `[]`；
- venv 解释器能 `import torch, torch_npu`；
- 第一次 baseline 能正常进入 requirement 阶段。

### 2.3 遗留

- `npu_ids` 仍是 `[3]`，要到 `e9fd190` 才改；
- `trial_timeout_sec` 8h 仍偏紧，`fb091e5` 又提到 12h。

---

## 3. `fb091e5` — 深度推理的 codegen turn 放宽到 600s 再触发看门狗

**时间**：2026-10-24 01:13:55
**改动文件**：2 个，+2 / −2

### 3.1 解决的问题

第一次 baseline（`20261024-baseline-turnstall`）里，DevKit 的 turn-stall 看门狗在 180s 没有新 turn 时就判定 agent 死链并杀掉：

```
Agent ascendc-dev-s4-coding [swi_glu/codegen] abort:
no new turn for 189s > stall bound 180s (chars static 190s)
```

实际发生时间线：

| 时刻 | 事件 |
|---|---|
| 18:08:19 | requirement-analyst 在 188s 被误杀；stage 重试后恢复 |
| 20:57:29 | codegen 在 202s 被误杀；stage 重试 |
| 23:37:12 | 再次误杀（185s） |
| 23:41 / 23:45 / 23:51 | 连续三次（189s），5 次迭代耗尽 |
| 23:51:31 | codegen `fail_strategy=halt`，阶段 14907.6s 后产物不完整 |

deepseek 的深推理 turn 经常要 185–202s 才输出下一个 turn，180s 的界限正好卡在它的正常节奏上。日志里没有 `stream error`，应用侧也没有网关错误证据——这不是网关死了，是看门狗把“慢但活着”判成了“死”。

### 3.2 改动

```diff
# third_party/AscendC-DevKit/resources/orchestration-config.json
- "opencode_turn_stall_s": 180
+ "opencode_turn_stall_s": 600
```

同时给 trial 留出余量：

```diff
# domains/ascendc-devkit/rrsi.json
- "trial_timeout_sec": 28800
+ "trial_timeout_sec": 43200
```

### 3.3 为什么是 600s

DevKit 的看门狗体系里：

- `opencode_gateway_error_probe_s = 30`：应用日志出现网关错误时提前 trip（<1 分钟），不靠 turn-stall；
- `opencode_tool_grace_s = 1800`：工具在飞时静默是预期，不判死；
- `opencode_turn_stall_s`：只剩“真正无证据的深推理静默”这一类残差兜底，必须大于正常推理 turn 的间隔。

180s 对 deepseek 太紧；600s 覆盖了观察到的 185–202s，也留出了网关抖动时的余量。

### 3.4 验证

第三次、第四次运行中不再出现任何 `turn_stall` abort（第三次的失败是网关头超时，第四次是评测/评分问题）。

---

## 4. `e9fd190` — 把 ascendc-devkit 的卡池换到 NPU 6

**时间**：2026-10-24 01:20:13
**改动文件**：1 个，+1 / −1

### 4.1 解决的问题

第二次 baseline 启动后**秒败**：

```
NPU card 3 probe failed — dropped from batch card pool [3]
ConfigError: Invalid config 'batch': all resolved cards failed the open-device probe;
every card in the pool [3] is unavailable
(driver context-pool exhaustion? check zombie processes or restart the container)
```

宿主机 `npu-smi info` 显示 3 卡有约 829 MB 占用，但占用进程的 PID 在容器内不可见——典型的宿主机孤儿进程导致的 Ascend device context 泄漏。容器内没有权限清理，只能换卡。

### 4.2 改动

```diff
# domains/ascendc-devkit/rrsi.json
   "npu_ids": [
-    3
+    6
   ],
```

### 4.3 验证

逐卡做 open-device probe 后确认 6 卡可用（`Ascend950DT_9582` 能正常打开）。第三次、第四次 baseline 都在 6 卡上正常跑完。

### 4.4 注意

`npu_ids` 是硬编码的单卡。如果下次 6 卡也被占，需要重新探测并改这个值；或者把 `npu_ids` 设为 `[]`，让 `run_tasks.py` 用 `npu-smi` 自动探测健康卡（但自动探测在本机的可靠性没有验证过）。

---

## 5. 时间线与因果关系

```
10-23 17:31  2cffb87  上一轮运行报告（起点）
10-23 18:01  0ccddac  修路径 / 修 venv / 换 swi_glu / 降 max_attempts
                │
                ├─ 18:01 第一次 baseline 启动
                └─ 23:51 死于 turn-stall（180s 误杀 codegen）
10-24 01:13  fb091e5  stall 180 → 600，trial timeout 8h → 12h
                │
                ├─ 01:15 第二次 baseline 启动
                └─ 01:15 秒败：NPU 3 卡上下文耗尽
10-24 01:20  e9fd190  NPU 3 → 6
                │
                ├─ 01:20 第三次 baseline 启动
                └─ 03:36 死于网关 300s 头超时
                └─ 05:04 第四次 baseline 启动
                └─ 12:00 算子 30/100 通过，但被 RRSI 评分检查记 0
```

三个提交是**串行排障**的结果：每修掉一个，下一个问题才暴露出来。它们没有解决后面的问题：

- 网关 300s 头超时 / 空响应 / 404（外部，未处理）；
- RRSI `verdict_from_snapshot()` 漏算 `bonus_score`（代码问题，2026-10-26 已修复，见 `docs/RRSI-评分一致性检查-bonus漏项-20261026.md` §5.4）；
- profiler 采集失败导致 performance 分为 0（评测环境问题，未处理）。

---

## 6. 每个提交“没有做什么”

| 提交 | 没有做 |
|---|---|
| `0ccddac` | 没有改 RRSI 的核心循环；没有验证网关链路；没有处理 NPU 3 卡的占用 |
| `fb091e5` | 没有改网关超时参数；没有处理评测评分逻辑 |
| `e9fd190` | 没有改成自动探测卡；没有清理 3 卡的孤儿进程（容器内做不到） |

---

## 7. 当前工作区状态

`HEAD = e9fd190`。工作区里只有未跟踪的文档和机器本地文件：

```
?? .claude/settings.json
?? docs/RRSI-ascendc-devkit-四次运行复盘-20261026.md
?? docs/RRSI-评分一致性检查-bonus漏项-20261026.md
?? docs/cann-bench-打分机制说明-20261026.md
?? docs/ascendc-devkit-提交记录-2cffb87之后-20261026.md   ← 本文
?? jobs/
?? opencode.json
```

`run_tasks.py` 的评分漏项已在工作区修复（`M domains/ascendc-devkit/bench/run_tasks.py`，尚未提交），新增 `tests/test_ascendc_verdict.py` 覆盖 1.x / 2.x 两种口径。
