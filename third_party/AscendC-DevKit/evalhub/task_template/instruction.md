# AscendC-DevKit 单算子任务：{ops_name}

本任务中，算子输入件已预置于 cann-bench task 目录（{level}/{ops_name}/），直接调用 `batch_self_evolve.sh` 启动全链路。

## 任务参数

- operator: `{ops_name}`
- devkit_root: `/app/src/AscendC-DevKit`
- cann_bench_root: `/app/src/cann-bench`
- task_dir: `$CANN_BENCH_ROOT/tasks/{level}/{ops_name}`
- artifact_dir: `$DEVKIT_ROOT/output/{ops_name}/`
- npu: 容器可见设备空间内的逻辑 NPU 0

## 路径变量

```bash
export DEVKIT_ROOT="/app/src/AscendC-DevKit"
export CANN_BENCH_ROOT="/app/src/cann-bench"
export TASK_DIR="$CANN_BENCH_ROOT/tasks/{level}/{ops_name}"
export ARTIFACT_DIR="$DEVKIT_ROOT/output"
```

> 执行本指令中任何 bash 块之前，先执行上述路径变量块。

## 执行流程

### 0. 前置操作

```bash
# LLM 网关配置：workflow 从 devkit/cann-bench 根读取 opencode.json（provider 凭证 + 默认 model）
cp /logs/agent/opencode/opencode.json "$DEVKIT_ROOT/opencode.json"
cp /logs/agent/opencode/opencode.json "$CANN_BENCH_ROOT/opencode.json"
python3 - <<'EOF'
import json, os
g = json.load(open("/logs/agent/opencode/opencode.json"))
prov = next(iter(g["provider"]))
mdl = next(iter(g["provider"][prov]["models"]))
model = f"{prov}/{mdl}"
for p in (os.environ["DEVKIT_ROOT"] + "/opencode.json", os.environ["CANN_BENCH_ROOT"] + "/opencode.json"):
    d = json.load(open(p))
    d.setdefault("model", model)
    json.dump(d, open(p, "w"), ensure_ascii=False, indent=2)
    print(p, "-> model =", d["model"])
EOF
```

> **执行前清理与调参**（首跑前必做；`RESUME=1` 恢复前禁止执行第 3) 步 ——
> 续跑依赖 `output/<batch_id>/` 下的 execution 目录）：

```bash
# 3) 清空 output：删除历史 batch 产物，避免最终 app_artifacts.tar.gz 全量打包
#    output/ 时带入历史批次（解压后会出现多个日期标号目录，绝大多数是旧批次）。
#    仅首跑前执行；RESUME 恢复前严禁执行。
rm -rf "$DEVKIT_ROOT/output"

# 4) opencode turn 卡死看门狗 120s → 600s：框架检测「连续 turn_stall_s 无新 turn」
#    即判死并杀会话重试。120s 会把单个慢 turn（如 codegen 大 shape，实测单 turn
#    可达 667s）误判为卡死；600s = 2× 网关 request_timeout(300s)，给慢/重试请求
#    存活窗口。框架仅从该配置文件读取，无环境变量入口。
python3 - "$DEVKIT_ROOT/resources/orchestration-config.json" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d["timeouts"]["opencode_turn_stall_s"] = 600
json.dump(d, open(p, "w"), ensure_ascii=False, indent=2)
print("opencode_turn_stall_s ->", d["timeouts"]["opencode_turn_stall_s"])
PY
```

### 1. 启动工作流（后台）

> 本任务是 LLM 全流程（每算子分钟级、整体数小时），**必须后台启动**：
> 用 `setsid nohup` 使脚本脱离当前会话（防 SSH/会话断开 SIGHUP 杀掉进程），
> 并把 PID 与退出码落盘，供「2. 执行期间检查」与「3. 中断恢复」使用。
> 禁止前台同步执行本脚本（会占用会话数小时）。

```bash
cd "$DEVKIT_ROOT"

# 1) 改写 DEFAULT_TASKS 
#    一律执行任务目录内预置的确定性脚本（自动定位块、整块替换、bash -n 自检、失败即停）。
REWRITE_SCRIPT="$DEVKIT_ROOT/evalhub/rewrite_batch_tasks.py"
OP_TASK_REL="tasks/{level}/{ops_name}"
python3 "$REWRITE_SCRIPT" "$DEVKIT_ROOT/scripts/batch_self_evolve.sh" "$OP_TASK_REL" || exit 1

# 2) 后台启动（安装/环境/产物路径由脚本自理，无需额外环境变量）：
#    setsid nohup 完全脱离会话；外层 bash -c 等待脚本结束并把退出码写入
#    logs/batch_self_evolve.rc（区分「正常结束」与「被杀死」的关键）。
#    首跑不带 RESUME/BATCH_ID；续跑见「3. 中断恢复」。
rm -f logs/batch_self_evolve.rc
setsid nohup env RESUME="${RESUME:-0}" BATCH_ID="${BATCH_ID:-}" \
  bash -c 'bash scripts/batch_self_evolve.sh; echo "BATCH_RC=$?" > logs/batch_self_evolve.rc' \
  > logs/batch_self_evolve.out 2>&1 &
echo "$!" > logs/batch_self_evolve.pid
echo "[launched] pid=$(cat logs/batch_self_evolve.pid)"
```

工作流阶段：requirement → general-design → detailed-design → test_design → codegen → deploy → precision_debug → cannbench_adapt → cannbench_eval → finalize

### 2. 执行期间检查

> 每次执行下述幂等检查命令（秒级返回），按判定表行动。任务整体数小时，
> 建议每 60–120 秒检查一次，循环直到 `FINISHED` 或 `INTERRUPTED`。
> 用 PID 文件检查，不要用 `pgrep -f` 字符串匹配（会误匹配其他会话的同名脚本）。

```bash
PID="$(cat "$DEVKIT_ROOT/logs/batch_self_evolve.pid")"
if kill -0 "$PID" 2>/dev/null; then
  echo "RUNNING  etime=$(ps -o etime= -p "$PID" | tr -d ' ')"
  tail -n 5 "$(ls -t "$DEVKIT_ROOT"/logs/batch_*.log | head -1)"
else
  if [ -f "$DEVKIT_ROOT/logs/batch_self_evolve.rc" ]; then
    echo "FINISHED rc=$(cat "$DEVKIT_ROOT/logs/batch_self_evolve.rc")"
  else
    echo "INTERRUPTED"
  fi
fi
```

判定表：

| 检查结果 | 含义 | 行动 |
| --- | --- | --- |
| `RUNNING` | 正常进行中 | 等 60–120s 后重查 |
| `FINISHED rc=0` | 成功结束 | 进入「4. 产物收尾」 |
| `FINISHED rc≠0` | 脚本内失败 | 读日志尾部定位原因（`logs/batch_self_evolve.out` 为脚本自身输出，`logs/batch_*.log` 为工程 run 输出） |
| `INTERRUPTED` | 被会话/环境杀掉（无退出码） | 进入「3. 中断恢复」 |

### 3. 中断恢复

> 进程被异常杀掉不是终点：脚本自带 RESUME 续跑机制（manifest 与 `.batch_id`
> 均已落盘）。恢复 = 重发下述后台启动命令（幂等可重入）。

```bash
# 自动恢复：RESUME=1 自动找最新 batch（读 .batch_id），续跑所有未完成算子
cd "$DEVKIT_ROOT"
rm -f logs/batch_self_evolve.rc
setsid nohup env RESUME=1 \
  bash -c 'bash scripts/batch_self_evolve.sh; echo "BATCH_RC=$?" > logs/batch_self_evolve.rc' \
  > logs/batch_self_evolve.out 2>&1 &
echo "$!" > logs/batch_self_evolve.pid
echo "[resumed] pid=$(cat logs/batch_self_evolve.pid)"

# 显式指定批次（多历史 batch 时）：BATCH_ID=<batch_id> RESUME=1 重发上述命令
```

> 注意：若中断发生在 run --batch 派发之前（尚无 batch_id 落盘），直接按首跑
> 重发「1. 启动工作流」即可（worktree 已存在会复用，manifest 重新生成）。
> 恢复前可先查看已有进度：`ls "$DEVKIT_ROOT"/output/`（每批一个目录）。

### 4. 产物收尾（FINISHED 后）

- 本批 batch_id 与执行目录：`BATCH_ID="$(cat "$DEVKIT_ROOT"/../cann-bench-batch/*/.batch_id 2>/dev/null | head -1)"`，执行目录 `$DEVKIT_ROOT/output/$BATCH_ID/`
- 执行以下命令，将源码从 worktree（cann-bench-batch/<ts>/{ops_name}/）复制到 `$ARTIFACT_DIR`/{ops_name}/src/ 并随 `app_artifacts.tar.gz` 打包，同时生成`verification.md`。

```bash
bash "$DEVKIT_ROOT/evalhub/task_template/tests/test.sh" 
EOF
```

## 产物落点

- 运行日志：`$DEVKIT_ROOT/output/<batch_id>/<execution_id>/run.log`
- 部署产物：`$DEVKIT_ROOT/output/<batch_id>/<execution_id>/artifacts/per-op/{ops_name}/`

## 平台验收核对

阅读生成的 `verification.md`。

```text
FINAL_COMPILE_STATUS: <pass|fail|not_run>
FINAL_LOAD_STATUS: <pass|fail|not_run>
FINAL_ACCURACY_STATUS: <pass|fail|not_run>
FINAL_REASON: <一行最终原因>
```

## 结束日志摘要

```text
DONE: {ops_name}
PHASE_SUMMARY:
- kernel_dev: <pass|fail|skipped> - <一句话摘要>
OUTPUT_DIR: $DEVKIT_ROOT/output/<batch_id>/<execution_id>/
ARTIFACT_DIR: $ARTIFACT_DIR/
SELF_ASSESSMENT: <pass|fail|unknown>
```