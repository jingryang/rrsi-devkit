#!/usr/bin/env python3
"""
cann-recipes-spatial-intelligence 仓算子编译安装封装脚本。

封装 cann-recipes-spatial-intelligence 仓的 build.sh 编译流程，
生成 whl 包并安装到当前 Python 环境中。
可替代 ops_evaluation 中的 build_ops.py 用于 3DGS 算子 baseline 构建。

用法:
    # 环境检查
    python build_recipes.py --repo-root /path/to/cann-recipes-spatial-intelligence --check-env-only

    # 完整编译安装
    python build_recipes.py --repo-root /path/to/cann-recipes-spatial-intelligence --python-version 3.8

    # 仅编译不安装
    python build_recipes.py --repo-root /path/to/cann-recipes-spatial-intelligence --build-only

参数:
    --repo-root: cann-recipes-spatial-intelligence 仓根目录（绝对路径）
    --python-version: Python 版本号（如 3.8），默认自动检测
    --check-env-only: 仅执行环境检查，不编译
    --build-only: 仅编译生成 whl，不安装
    --skip-deps: 跳过安装 algorithms/gaussian_splatting/requirements.txt 依赖
    --clean: 编译前清理旧的构建产物

依赖:
    - ASCEND_OPP_PATH 环境变量需要设置（CANN 环境）
    - CANN 8.2.RC1
    - torch==2.1.0, torch_npu==2.1.0.post12
    - Python >= 3.8
"""

import argparse
import glob
import json
import logging
import os
import re
import subprocess
import sys


# ============================================================
# 常量定义
# ============================================================

REQUIRED_CANN_VERSION = "8.2"
REQUIRED_TORCH_VERSION = "2.1.0"
REQUIRED_TORCH_NPU_VERSION = "2.1.0.post12"
MIN_PYTHON_VERSION = (3, 8)

# 仓内相对路径
ASCENDC_SUBDIR = os.path.join("ops", "ascendc")
ALGORITHMS_SUBDIR = os.path.join("algorithms", "gaussian_splatting")
REQUIREMENTS_FILE = os.path.join(ALGORITHMS_SUBDIR, "requirements.txt")


# ============================================================
# 环境检查
# ============================================================

def get_python_version_str() -> str:
    """获取当前 Python 版本的 major.minor 字符串。"""
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def check_python_version() -> dict:
    """检查 Python 版本 >= 3.8。"""
    current = (sys.version_info.major, sys.version_info.minor)
    ok = current >= MIN_PYTHON_VERSION
    return {
        "name": "Python版本",
        "passed": ok,
        "current": f"{current[0]}.{current[1]}.{sys.version_info.micro}",
        "required": f">= {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]}",
        "fix": f"请使用 Python {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]} 或更高版本" if not ok else None,
    }


def check_cann_env() -> dict:
    """检查 CANN 环境变量。"""
    opp_path = os.environ.get("ASCEND_OPP_PATH", "")
    ok = bool(opp_path)
    return {
        "name": "CANN环境变量",
        "passed": ok,
        "current": opp_path if ok else "NOT SET",
        "required": "ASCEND_OPP_PATH 已设置",
        "fix": "source /path/to/cann/set_env.sh" if not ok else None,
    }


def check_cann_version() -> dict:
    """检查 CANN 版本是否为 8.2。"""
    opp_path = os.environ.get("ASCEND_OPP_PATH", "")
    version = "unknown"

    if opp_path:
        # 尝试从路径中提取版本: .../CANN-8.2.RC1/... 或 .../cann-8.2/...
        match = re.search(r"CANN[_-]?(\d+\.\d+)", opp_path, re.IGNORECASE)
        if match:
            version = match.group(1)

    if version == "unknown":
        # 尝试从 version.cfg 获取（适用于 latest 软链接场景）
        toolkit_home = os.environ.get("ASCEND_TOOLKIT_HOME", "")
        if toolkit_home:
            version_cfg = os.path.join(toolkit_home, "version.cfg")
            if os.path.isfile(version_cfg):
                try:
                    with open(version_cfg, "r") as f:
                        for line in f:
                            # 匹配 toolkit_running_version=[8.2.0.0.201:8.2.RC1]
                            if "toolkit_running_version" in line:
                                ver_match = re.search(r"\[(\d+\.\d+)", line)
                                if ver_match:
                                    version = ver_match.group(1)
                                    break
                except Exception:
                    pass

    if version == "unknown":
        # 尝试从 ascend_toolkit_install.info 获取
        toolkit_home = os.environ.get("ASCEND_TOOLKIT_HOME", "")
        if toolkit_home:
            info_file = os.path.join(toolkit_home, "ascend_toolkit_install.info")
            if os.path.isfile(info_file):
                try:
                    with open(info_file, "r") as f:
                        for line in f:
                            if "version" in line.lower():
                                ver_match = re.search(r"(\d+\.\d+)", line)
                                if ver_match:
                                    version = ver_match.group(1)
                                    break
                except Exception:
                    pass

    if version == "unknown":
        # 尝试从 OPP_PATH 解析 realpath（解析软链接后的实际路径）
        if opp_path:
            try:
                real_path = os.path.realpath(opp_path)
                match = re.search(r"(\d+\.\d+)\.RC", real_path)
                if match:
                    version = match.group(1)
            except Exception:
                pass

    ok = version.startswith(REQUIRED_CANN_VERSION)
    return {
        "name": "CANN版本",
        "passed": ok,
        "current": version,
        "required": f"CANN {REQUIRED_CANN_VERSION}.x",
        "fix": f"需要 CANN {REQUIRED_CANN_VERSION}.RC1，请安装对应版本" if not ok else None,
    }


def check_torch_version() -> dict:
    """检查 torch 版本是否为 2.1.0。"""
    try:
        import torch
        version = torch.__version__.split("+")[0]  # 去掉 +cu... 后缀
        ok = version == REQUIRED_TORCH_VERSION
        return {
            "name": "torch版本",
            "passed": ok,
            "current": torch.__version__,
            "required": REQUIRED_TORCH_VERSION,
            "fix": f"pip install torch=={REQUIRED_TORCH_VERSION}" if not ok else None,
        }
    except ImportError:
        return {
            "name": "torch版本",
            "passed": False,
            "current": "NOT INSTALLED",
            "required": REQUIRED_TORCH_VERSION,
            "fix": f"pip install torch=={REQUIRED_TORCH_VERSION}",
        }


def check_torch_npu_version() -> dict:
    """检查 torch_npu 版本是否为 2.1.0.post12。"""
    try:
        import torch_npu
        version = torch_npu.__version__
        ok = version == REQUIRED_TORCH_NPU_VERSION
        return {
            "name": "torch_npu版本",
            "passed": ok,
            "current": version,
            "required": REQUIRED_TORCH_NPU_VERSION,
            "fix": f"pip install torch_npu=={REQUIRED_TORCH_NPU_VERSION}" if not ok else None,
        }
    except ImportError:
        return {
            "name": "torch_npu版本",
            "passed": False,
            "current": "NOT INSTALLED",
            "required": REQUIRED_TORCH_NPU_VERSION,
            "fix": f"pip install torch_npu=={REQUIRED_TORCH_NPU_VERSION}",
        }


def run_env_checks() -> list:
    """执行所有环境检查，返回检查结果列表。"""
    checks = [
        check_python_version(),
        check_cann_env(),
        check_cann_version(),
        check_torch_version(),
        check_torch_npu_version(),
    ]
    return checks


def print_env_checks(checks: list) -> bool:
    """打印环境检查结果，返回是否全部通过。"""
    all_passed = True
    logging.info("=" * 60)
    logging.info("环境检查结果")
    logging.info("=" * 60)

    for check in checks:
        status = "✅ PASS" if check["passed"] else "❌ FAIL"
        logging.info(f"  {status} {check['name']}: {check['current']} (需要: {check['required']})")
        if not check["passed"]:
            all_passed = False
            if check.get("fix"):
                logging.info(f"         修复: {check['fix']}")

    logging.info("=" * 60)
    if all_passed:
        logging.info("所有环境检查通过 ✅")
    else:
        logging.warning("存在未通过的环境检查，请修复后重试")

    return all_passed


# ============================================================
# 编译安装
# ============================================================

def clean_build_artifacts(ascendc_dir: str):
    """清理旧的编译产物。"""
    dirs_to_clean = ["build", "dist", "meta_gauss_render.egg-info"]
    for d in dirs_to_clean:
        target = os.path.join(ascendc_dir, d)
        if os.path.exists(target):
            logging.info(f"清理目录: {target}")
            subprocess.run(["rm", "-rf", target], check=True)


def build_operators(repo_root: str, python_version: str,
                    clean: bool = True) -> str:
    """
    编译 cann-recipes-spatial-intelligence 算子。

    Args:
        repo_root: 仓根目录（绝对路径）
        python_version: Python 版本号（如 3.8）
        clean: 是否清理旧构建产物

    Returns:
        whl 文件路径

    Raises:
        RuntimeError: 编译失败
    """
    ascendc_dir = os.path.join(repo_root, ASCENDC_SUBDIR)

    if not os.path.isdir(ascendc_dir):
        raise FileNotFoundError(f"算子源码目录不存在: {ascendc_dir}")

    build_sh = os.path.join(ascendc_dir, "build.sh")
    if not os.path.isfile(build_sh):
        raise FileNotFoundError(f"build.sh 不存在: {build_sh}")

    # 清理
    if clean:
        clean_build_artifacts(ascendc_dir)

    # 执行编译
    build_cmd = f"bash build.sh --python={python_version}"
    logging.info(f"执行编译: {build_cmd}")
    logging.info(f"工作目录: {ascendc_dir}")

    result = subprocess.run(
        build_cmd,
        shell=True,
        cwd=ascendc_dir,
        capture_output=True,
        text=True,
        timeout=600,  # 10 minutes
    )

    if result.returncode != 0:
        error_msg = (
            f"编译失败!\n"
            f"Exit Code: {result.returncode}\n"
            f"Stdout (last 2000 chars):\n{result.stdout[-2000:]}\n"
            f"Stderr (last 2000 chars):\n{result.stderr[-2000:]}"
        )
        logging.error(error_msg)
        raise RuntimeError(error_msg)

    logging.info("编译成功")

    # 查找生成的 whl 文件
    dist_dir = os.path.join(ascendc_dir, "dist")
    whl_files = glob.glob(os.path.join(dist_dir, "*.whl"))
    if not whl_files:
        raise FileNotFoundError(
            f"未在 {dist_dir} 下找到 .whl 文件。"
            f" 请检查编译是否成功完成。"
        )

    # 取最新的 whl
    whl_files.sort(key=os.path.getmtime, reverse=True)
    whl_file = whl_files[0]
    logging.info(f"找到 whl 文件: {whl_file}")

    return whl_file


def install_whl(whl_file: str):
    """
    安装 whl 包。

    Args:
        whl_file: whl 文件路径

    Raises:
        RuntimeError: 安装失败
    """
    install_cmd = [sys.executable, "-m", "pip", "install",
                   whl_file, "--force-reinstall"]
    logging.info(f"安装 whl: {' '.join(install_cmd)}")

    result = subprocess.run(
        install_cmd,
        capture_output=True,
        text=True,
        timeout=300,  # 5 minutes
    )

    if result.returncode != 0:
        error_msg = (
            f"whl 安装失败!\n"
            f"Exit Code: {result.returncode}\n"
            f"Stdout:\n{result.stdout[-2000:]}\n"
            f"Stderr:\n{result.stderr[-2000:]}"
        )
        logging.error(error_msg)
        raise RuntimeError(error_msg)

    logging.info("whl 安装成功")


def install_requirements(repo_root: str):
    """
    安装 algorithms/gaussian_splatting/requirements.txt 中的依赖。

    Args:
        repo_root: 仓根目录

    Raises:
        RuntimeError: 安装失败
    """
    req_file = os.path.join(repo_root, REQUIREMENTS_FILE)
    if not os.path.isfile(req_file):
        logging.warning(f"requirements.txt 不存在: {req_file}，跳过依赖安装")
        return

    install_cmd = [sys.executable, "-m", "pip", "install",
                   "-r", req_file]
    logging.info(f"安装依赖: {' '.join(install_cmd)}")

    result = subprocess.run(
        install_cmd,
        capture_output=True,
        text=True,
        timeout=600,  # 10 minutes
    )

    if result.returncode != 0:
        error_msg = (
            f"依赖安装失败!\n"
            f"Exit Code: {result.returncode}\n"
            f"Stdout:\n{result.stdout[-2000:]}\n"
            f"Stderr:\n{result.stderr[-2000:]}"
        )
        logging.error(error_msg)
        raise RuntimeError(error_msg)

    logging.info("依赖安装成功")


def verify_installation() -> bool:
    """
    验证 meta_gauss_render 是否成功安装。

    Returns:
        True if import 成功
    """
    verify_cmd = [
        sys.executable, "-c",
        "import meta_gauss_render; print('version:', getattr(meta_gauss_render, '__version__', 'unknown'))"
    ]

    result = subprocess.run(
        verify_cmd,
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode == 0:
        logging.info(f"安装验证成功: {result.stdout.strip()}")
        return True
    else:
        logging.warning(f"安装验证失败: {result.stderr.strip()}")
        return False


# ============================================================
# 主流程
# ============================================================

def build_and_install(repo_root: str, python_version: str = None,
                      build_only: bool = False, skip_deps: bool = False,
                      clean: bool = True) -> dict:
    """
    完整的编译安装流程。

    Args:
        repo_root: cann-recipes-spatial-intelligence 仓根目录（绝对路径）
        python_version: Python 版本号（如 3.8），None 则自动检测
        build_only: 仅编译不安装
        skip_deps: 跳过安装 requirements.txt
        clean: 编译前清理旧产物

    Returns:
        dict: 构建结果信息
    """
    # 验证路径
    if not os.path.isabs(repo_root):
        raise ValueError(f"repo_root 必须是绝对路径, 当前值: {repo_root}")

    if not os.path.isdir(repo_root):
        raise FileNotFoundError(f"仓目录不存在: {repo_root}")

    # 自动检测 Python 版本
    if python_version is None:
        python_version = get_python_version_str()
        logging.info(f"自动检测 Python 版本: {python_version}")

    ascendc_dir = os.path.join(repo_root, ASCENDC_SUBDIR)

    logging.info(f"构建配置:")
    logging.info(f"  仓根目录: {repo_root}")
    logging.info(f"  算子目录: {ascendc_dir}")
    logging.info(f"  Python版本: {python_version}")
    logging.info(f"  仅编译: {build_only}")
    logging.info(f"  跳过依赖: {skip_deps}")

    # Step 1: 编译
    whl_file = build_operators(repo_root, python_version, clean=clean)

    result = {
        "repo_root": repo_root,
        "ascendc_dir": ascendc_dir,
        "whl_file": whl_file,
        "python_version": python_version,
        "installed": False,
        "import_check": False,
    }

    if build_only:
        logging.info("仅编译模式，跳过安装")
        return result

    # Step 2: 安装 whl
    install_whl(whl_file)
    result["installed"] = True

    # Step 3: 安装依赖
    if not skip_deps:
        install_requirements(repo_root)

    # Step 4: 验证
    result["import_check"] = verify_installation()

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Build and install cann-recipes-spatial-intelligence operators"
    )
    parser.add_argument(
        "--repo-root", required=True,
        help="cann-recipes-spatial-intelligence 仓根目录路径（绝对路径）"
    )
    parser.add_argument(
        "--python-version", default=None,
        help="Python 版本号（如 3.8），默认自动检测"
    )
    parser.add_argument(
        "--check-env-only", action="store_true",
        help="仅执行环境检查，不编译安装"
    )
    parser.add_argument(
        "--build-only", action="store_true",
        help="仅编译生成 whl 包，不安装"
    )
    parser.add_argument(
        "--skip-deps", action="store_true",
        help="跳过安装 requirements.txt 依赖"
    )
    parser.add_argument(
        "--clean", action="store_true", default=True,
        help="编译前清理旧构建产物（默认开启）"
    )
    parser.add_argument(
        "--no-clean", action="store_true",
        help="编译前不清理旧构建产物"
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    # 环境检查
    checks = run_env_checks()
    all_passed = print_env_checks(checks)

    if args.check_env_only:
        # 输出 JSON
        print(f"\n--- ENV_CHECK_JSON ---")
        print(json.dumps(checks, ensure_ascii=False, indent=2))
        print(f"--- END_ENV_CHECK_JSON ---")
        sys.exit(0 if all_passed else 1)

    if not all_passed:
        logging.error("环境检查未通过，请修复后重试。"
                       "如需强制继续，请先修复上述问题。")
        sys.exit(1)

    # 编译安装
    try:
        clean = not args.no_clean
        result = build_and_install(
            repo_root=args.repo_root,
            python_version=args.python_version,
            build_only=args.build_only,
            skip_deps=args.skip_deps,
            clean=clean,
        )

        print(f"\n构建安装完成:")
        print(f"  仓根目录: {result['repo_root']}")
        print(f"  算子目录: {result['ascendc_dir']}")
        print(f"  whl文件: {result['whl_file']}")
        print(f"  Python版本: {result['python_version']}")
        print(f"  已安装: {result['installed']}")
        print(f"  import检查: {result['import_check']}")

        # 输出 JSON 供脚本解析
        result_json = json.dumps(result, ensure_ascii=False, indent=2)
        print(f"\n--- BUILD_RESULT_JSON ---")
        print(result_json)
        print(f"--- END_BUILD_RESULT_JSON ---")

    except Exception as e:
        logging.error(f"构建安装失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()