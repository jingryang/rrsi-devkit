#!/bin/bash
# 功能：把宿主机 $SRC_DIR 下的 AscendC-DevKit、cann-bench 整体替换进镜像
#       pool-00001:0817（即 .../public/npu-operator/huangyuqian/pool-00001:pool-00001-0817）内的
#       /app/src/，并提交为【新镜像】（默认 tag 在原 tag 后加 -v2），不覆盖旧镜像 $IMG。
# 用法：在宿主机（有 docker 的机器）上执行:
#       bash update_pool_image.sh                # 替换后暂停，登录临时容器确认结果，确认后提交 + 打新短 tag
#       bash update_pool_image.sh --no-check     # 跳过登录确认，替换完成后直接提交
#       bash update_pool_image.sh --push         # 替换完成确认后提交，并顺带把新镜像推回平台

# 旧镜像 $IMG 全程不被修改。多次执行时请把 NEW_IMG / NEW_SHORT_TAG 改成不同值，
# 否则会覆盖上一次生成的"新镜像"。
set -euo pipefail

# ============ 配置区（按需修改） ============
# 原镜像（构建基线）
IMG="swr-coder-data-platform-wce1sr.swr-pro.myhuaweicloud.com/swesandbox/public/npu-operator/huangyuqian/pool-00001:pool-00001-0817"
# 宿主机上的源根目录（变量，可改）
SRC_DIR=""
# 要替换的目录名（位于 $DEST_DIR 下），可增删，例如再加 cann-bench-batch
DIRS=(AscendC-DevKit cann-bench)
# ---- 新镜像 tag----
NEW_IMG="${IMG%:*}:{新tag名}"
NEW_SHORT_TAG="pool-00001:{新tag名}"
# 工号 / 密码（密码需 URL 编码，如 ! 写 %21）；用于构造推送时 http_proxy / https_proxy
PROXY_USER=""
PROXY_PASS=""

# 镜像内目标父目录
DEST_DIR="/app/src"
# ---- 改写 batch_self_evolve.sh 默认路径（可选）----
# 拷贝完成后，会强制把镜像内 $DEST_DIR/AscendC-DevKit/scripts/batch_self_evolve.sh 里的
# CANN_BENCH 与 CANN_ENV_SCRIPT 默认值改成下面两个（无论原值是什么，整行重写）。
# 留空表示不改对应行。
NEW_CANN_BENCH_DEFAULT="/app/src/cann-bench"
NEW_CANN_ENV_SCRIPT_DEFAULT="/usr/local/Ascend/cann-9.0.0/set_env.sh"
# 临时容器名
CONTAINER="img-replace-tmp"

# 完成后是否推回平台（也可用命令行 --push 开启）
PUSH="${PUSH:-1}"
# 提交前是否暂停等待手动登录确认（也可用命令行 --no-check 关闭）
WAIT_CONFIRM="${WAIT_CONFIRM:-0}"

# devkit 要求 requires-python>=3.11（pyproject.toml），而镜像默认 python3 是 3.10。
# 当前基础镜像版本已是3.12
PY_SRC_IMAGE=""
PY_PREFIX="/usr/local/python3.12.13"

# ============ 参数解析 ============
for arg in "$@"; do
    case "$arg" in
        --push) PUSH=1 ;;
        --no-check) WAIT_CONFIRM=0 ;;
        *) echo "[错误] 未知参数: $arg"; exit 1 ;;
    esac
done

# ============ 逻辑开始 ============
# 0. 预检查
command -v docker >/dev/null 2>&1 || { echo "[错误] 未找到 docker（本脚本需在有 docker 的宿主机上执行）"; exit 1; }
docker image inspect "$IMG" >/dev/null 2>&1 || { echo "[错误] 本地无此镜像: $IMG（先 pull 或确认 tag）"; exit 1; }
for d in "${DIRS[@]}"; do
    [ -d "$SRC_DIR/$d" ] || { echo "[错误] 源目录不存在: $SRC_DIR/$d"; exit 1; }
done
# 0.5 预检查临时容器：本地已存在则先删除再构建（上次异常残留的容器）
if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    echo "[预检] 发现已存在的临时容器 $CONTAINER，先删除"
    docker rm -f "$CONTAINER"
fi

# 临时容器清理兜底：脚本中途失败也要删掉，避免残留 sleep 容器
cleanup() { docker rm -f "$CONTAINER" >/dev/null 2>&1 || true; }
trap cleanup EXIT

# 1. 记录原镜像 ENTRYPOINT / CMD。
#    原因：docker commit 会把临时容器的配置一并存进新镜像，而临时容器为了能
#    用 docker exec，入口被改成了 sleep。所以提交时用 --change 把原配置还原。
ENTRYPOINT_JSON=$(docker inspect --format '{{json .Config.Entrypoint}}' "$IMG")
CMD_JSON=$(docker inspect --format '{{json .Config.Cmd}}' "$IMG")
echo "原镜像 ID:         $(docker inspect --format '{{.Id}}' "$IMG")"
echo "原镜像 Entrypoint: $ENTRYPOINT_JSON"
echo "原镜像 CMD:        $CMD_JSON"

# 2. 创建并启动临时容器：
#    --entrypoint sleep 3600 -> 跳过镜像默认入口（默认入口大概率需要 NPU 设备，
#    没有 --device 映射会启动失败），sleep 让容器保持运行，docker exec/cp 才能用。
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker create --name "$CONTAINER" --entrypoint sleep "$IMG" 3600
docker start "$CONTAINER"

# 2.5 (可选) 烘焙 python>=3.11 进镜像
#     镜像 ENV PATH 里的 $PY_PREFIX/bin 决定运行时 python3 解析到谁——
#     opencode 的 bash 工具是非交互 shell，不读 .bashrc，只有 ENV PATH 生效。
#     这里的改动在容器 fs 里，随后面 docker commit 一并进镜像。
PY_BAKED=0
NEED_PATH=0
ENV_PATH=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$IMG" | sed -n 's/^PATH=//p')
if docker exec "$CONTAINER" test -x "$PY_PREFIX/bin/python3.12" 2>/dev/null; then
    echo "[python] 镜像已含 $PY_PREFIX"
    case ":$ENV_PATH:" in
        *":$PY_PREFIX/bin:"*) : ;;
        *) NEED_PATH=1; echo "[python] 镜像 ENV PATH 未包含 $PY_PREFIX/bin，提交时补上" ;;
    esac
elif [ -n "$PY_SRC_IMAGE" ]; then
    echo "[python] 镜像缺少 $PY_PREFIX，从 $PY_SRC_IMAGE 拷贝..."
    docker image inspect "$PY_SRC_IMAGE" >/dev/null 2>&1 || docker pull "$PY_SRC_IMAGE"
    PY_SRC_CONTAINER="py-src-extract"
    docker rm -f "$PY_SRC_CONTAINER" >/dev/null 2>&1 || true
    docker create --name "$PY_SRC_CONTAINER" --entrypoint sleep "$PY_SRC_IMAGE" 3600 >/dev/null
    docker start "$PY_SRC_CONTAINER" >/dev/null
    docker cp "$PY_SRC_CONTAINER:$PY_PREFIX" /tmp/py-prefix-extract
    docker rm -f "$PY_SRC_CONTAINER" >/dev/null
    docker cp /tmp/py-prefix-extract/python3.12.13 "$CONTAINER:/usr/local/"
    rm -rf /tmp/py-prefix-extract
    PY_BAKED=1
    NEED_PATH=1
    echo "[python] 已拷入容器，提交时补 PATH"
else
    echo "[WARN] 镜像无 $PY_PREFIX 且未配置 PY_SRC_IMAGE —— 任务运行时需要 python>=3.11，devkit 自装逻辑会兜底，但建议补上"
fi

# 3. 先删掉镜像内旧目录——先删再拷才是"替换"。
#    如果不删直接 docker cp 到已存在的目录，docker cp 会"合并"进旧目录，
#    旧目录里新目录没有的文件会残留下来。
for d in "${DIRS[@]}"; do
    echo "[$d] 删除镜像内旧目录 $DEST_DIR/$d ..."
    docker exec "$CONTAINER" rm -rf "$DEST_DIR/$d"
done

# 4. 把宿主机新目录拷进容器（目标给到 $DEST_DIR/ 本身，旧目录已删，直接生成新的）
for d in "${DIRS[@]}"; do
    echo "[$d] 拷贝 $SRC_DIR/$d -> $DEST_DIR/$d ..."
    docker cp "$SRC_DIR/$d" "$CONTAINER:$DEST_DIR/"
done

# 4.5 (可选) 改写 batch_self_evolve.sh 里的 CANN_BENCH / CANN_ENV_SCRIPT 默认值。
#     整行重写为"${VAR:-用户指定值}"，与原行是相对/绝对路径无关，一律改成配置区的新值。
#     sed 替换串里对 \ & | 转义，避免用户填的路径里出现这些字符时被 sed 当特殊字符。
MOD_FILE="$DEST_DIR/AscendC-DevKit/scripts/batch_self_evolve.sh"
if [ -n "$NEW_CANN_BENCH_DEFAULT" ] || [ -n "$NEW_CANN_ENV_SCRIPT_DEFAULT" ]; then
    if docker exec "$CONTAINER" test -f "$MOD_FILE"; then
        echo "[mod] 改写 $MOD_FILE 中的默认路径"
        mod_escape() { printf '%s' "$1" | sed 's/[\\&|]/\\&/g'; }
        if [ -n "$NEW_CANN_BENCH_DEFAULT" ]; then
            esc="$(mod_escape "$NEW_CANN_BENCH_DEFAULT")"
            docker exec "$CONTAINER" sed -i "s|^CANN_BENCH=.*|CANN_BENCH=\"\${CANN_BENCH:-$esc}\"|" "$MOD_FILE"
            echo "[mod]   CANN_BENCH=$NEW_CANN_BENCH_DEFAULT"
        fi
        if [ -n "$NEW_CANN_ENV_SCRIPT_DEFAULT" ]; then
            esc="$(mod_escape "$NEW_CANN_ENV_SCRIPT_DEFAULT")"
            docker exec "$CONTAINER" sed -i "s|^CANN_ENV_SCRIPT=.*|CANN_ENV_SCRIPT=\"\${CANN_ENV_SCRIPT:-$esc}\"|" "$MOD_FILE"
            echo "[mod]   CANN_ENV_SCRIPT=$NEW_CANN_ENV_SCRIPT_DEFAULT"
        fi
    else
        echo "[WARN] $MOD_FILE 在镜像内不存在，跳过改写（请检查 DIRS 是否包含 AscendC-DevKit）"
    fi
fi

# 4.7 (手动确认) 暂停，登录临时容器检查是否预期结果后再提交
if [ "$WAIT_CONFIRM" = "1" ]; then
    echo
    echo "=== 临时容器 $CONTAINER 已就绪，可登录检查： ==="
    echo "    docker exec -it $CONTAINER bash"
    echo "    检查无误后回到本脚本输入 y 提交；输入 n 放弃（删除临时容器，原镜像不变）"
    while :; do
        if ! read -r -p "确认提交为新镜像 $NEW_IMG? [y/N] " ans; then
            echo "[提示] 非交互环境未收到输入，按继续提交处理"
            break
        fi
        case "$ans" in
            y|Y|yes|YES) break ;;
            n|N|no|NO|"") echo "已放弃提交，删除临时容器 $CONTAINER（原镜像不变）"; exit 0 ;;
            *) echo "请输入 y 或 n" ;;
        esac
    done
    echo
fi

# 5. 停止容器并提交为【新镜像】$NEW_IMG（不覆盖原镜像 $IMG）。
#    docker commit 保存的是容器文件系统的改动（sleep 进程本身不影响内容）。
#    --change 还原 ENTRYPOINT/CMD 这一步不能省：不还原的话，新镜像的入口
#    会变成 commit 时容器的配置（sleep），镜像就没法正常启动了。
docker stop "$CONTAINER"
COMMIT_FLAGS=()
[ "$ENTRYPOINT_JSON" != "null" ] && COMMIT_FLAGS+=(--change "ENTRYPOINT $ENTRYPOINT_JSON")
[ "$CMD_JSON" != "null" ] && COMMIT_FLAGS+=(--change "CMD $CMD_JSON")
if [ "$NEED_PATH" = "1" ]; then
    # 把 python 目录加进镜像 ENV PATH（原 PATH 必须整体带上，ENV 是整体覆盖语义）
    COMMIT_FLAGS+=(--change "ENV PATH=$PY_PREFIX/bin:$ENV_PATH")
    echo "[python] 提交时追加 ENV PATH=$PY_PREFIX/bin:...（保留原 PATH）"
fi
docker commit "${COMMIT_FLAGS[@]}" "$CONTAINER" "$NEW_IMG"
# 不解除 EXIT trap：脚本正常/失败退出时 cleanup 会自动删除临时容器 $CONTAINER
echo "[提示] 新镜像: $NEW_IMG（旧镜像 $IMG 未被修改，临时容器将自动删除）"

# 6. 给新镜像打短 tag（本地用，推平台也用这个名字）
echo "打短 tag: $NEW_SHORT_TAG"
docker tag "$NEW_IMG" "$NEW_SHORT_TAG"

# 7. 验证
echo "=== 新镜像内 $DEST_DIR 内容 ==="
docker run --rm --entrypoint ls "$NEW_IMG" "$DEST_DIR"
echo "=== 关键文件抽查 ==="
docker run --rm --entrypoint sh "$NEW_IMG" -c \
  "ls -l $DEST_DIR/AscendC-DevKit/scripts/batch_self_evolve.sh $DEST_DIR/cann-bench/tasks/level1/absolute_custom_ 2>&1 | head -20"
echo "=== batch_self_evolve.sh 改写后的默认值 ==="
docker run --rm --entrypoint sh "$NEW_IMG" -c \
  "grep -nE '^(CANN_BENCH|CANN_ENV_SCRIPT)=' $DEST_DIR/AscendC-DevKit/scripts/batch_self_evolve.sh"
echo "=== python3 版本（应为 >=3.11，若此行为 3.10 说明未烘焙成功） ==="
docker run --rm --entrypoint bash "$NEW_IMG" -c 'python3 --version'
echo "=== 新镜像 Entrypoint（应和原镜像一致） ==="
docker inspect --format '{{json .Config.Entrypoint}}' "$NEW_IMG"
echo "=== 新/旧镜像 ID（应不同，旧镜像未被覆盖） ==="
docker inspect --format '{{.Id}}' "$NEW_IMG"
docker inspect --format '{{.Id}}' "$IMG"
docker inspect --format '{{.Id}}' "$NEW_SHORT_TAG"
echo "完成 -> $NEW_IMG（原镜像 $IMG 未动）"

# 8. 可选：把新镜像推回平台（内嵌 Python，自动 docker login + tag + push）
#    推送路径: public/<line>/<user>/pool-00001:<本地名去冒号>
#    预期远端: swr-.../swesandbox/public/npu-operator/huangyuqian/pool-00001:pool-00001-0817-v2
if [ "$PUSH" = "1" ]; then
    echo "=== 推回平台（新镜像 $NEW_SHORT_TAG） ==="
    command -v python3 >/dev/null 2>&1 || { echo "[错误] 未找到 python3（push 需要）"; exit 1; }
    LOCAL_IMAGE="$NEW_SHORT_TAG" PROXY_USER="$PROXY_USER" PROXY_PASS="$PROXY_PASS" python3 - <<'PY'
import os
from cwm import CwmClient

os.environ["http_proxy"] = "http://{u}:{p}@proxysg-spl.huawei.com:8080".format(u=os.environ["PROXY_USER"], p=os.environ["PROXY_PASS"])
os.environ["https_proxy"] = "http://{u}:{p}@proxysg-spl.huawei.com:8080".format(u=os.environ["PROXY_USER"], p=os.environ["PROXY_PASS"])
os.environ["no_proxy"] = "localhost,127.0.0.1,.huawei.com,7.244.3.60"

LOCAL_IMAGE = os.environ.get("LOCAL_IMAGE", "pool-00001:0817")
LINE = "npu-operator"
USER = "huangyuqian"
POOL_ID = 1

with CwmClient(
    platform_api_base_url="http://7.244.3.60:8088",
    platform_username="huangyuqian",
    platform_password="huangyuqian",
) as client:
    result = client.image_management.push_public(
        local_image=LOCAL_IMAGE,
        line=LINE,
        user=USER,
        pool_id=POOL_ID,
        timeout=3600,
    )
    print("pushed:", result)
PY
else
    echo "未推平台。如需推送: bash $0 --push（或改配置区 PUSH=1）"
fi