#!/usr/bin/env bash
# AscendC-DevKit 工程自身安装脚本
# 用法：
#   ./scripts/install_devkit.sh
#
# 说明：
# - 本脚本只负责安装 DevKit 工程本身（pip install -e .），不负责 CANN/torch_npu。
# - CANN 环境请用 scripts/install_cann_env.sh；torch/torch_npu 请用 scripts/install_torch_npu.sh。

set -uo pipefail

DEVKIT_ROOT=$(cd "$(dirname "$0")/.." && pwd)

echo "安装/更新 AscendC-DevKit 工程: $DEVKIT_ROOT"

if [ ! -f "$DEVKIT_ROOT/pyproject.toml" ]; then
    echo "ERROR: 未找到 $DEVKIT_ROOT/pyproject.toml"
    exit 1
fi

cd "$DEVKIT_ROOT" || exit 1

if pip show ascendc-devkit >/dev/null 2>&1; then
    echo "ascendc_devkit 已安装，执行更新..."
else
    echo "ascendc_devkit 未安装，执行安装..."
fi

pip install -e . || { echo "ERROR: pip install -e . 失败"; exit 1; }

echo ""
echo "===== 验证 ====="
python3 -c "import ascendc_devkit; print('ascendc_devkit:', ascendc_devkit.__file__)" || { echo "ERROR: 无法导入 ascendc_devkit"; exit 1; }

# 可选：验证 CLI 可调用
if python3 -m ascendc_devkit --help >/dev/null 2>&1; then
    echo "CLI: ok"
else
    echo "警告: CLI 调用失败（不影响 import，但可能影响后续使用）"
fi

echo ""
echo "DevKit 工程安装完成。"
