import os
import re
import shutil
from pathlib import Path


# ===== 全局配置（运行前修改） =====
OPS_LIST = ["level2/arg_max", "level1/exp"]  # 只接受算子名，格式: levelX/算子名
IMG_NAME = "swr-coder-data-platform-wce1sr.swr-pro.myhuaweicloud.com/swesandbox/public/npu-operator/huangyuqian/pool-00001:pool-00001-0817"  # docker 镜像名称
IMG_ID = "a07f59cb815c35044289185e72b573c9a9748b1baeff9b08eb2b9e7ba1eefa8c"          # 镜像 hash id
TEMPLATE_DIR = Path("AscendC-DevKit/resources/evalhub/task_template")
TARGET_DIR="ascend-test"  # 必须以ascend开头命名

os.makedirs(TARGET_DIR, exist_ok=True)
# =================================

TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".sh", ".yaml", ".yml", ".json", ".toml",
    ".cfg", ".conf", ".ini", ".csv", ".xml", ".html", ".css", ".js",
    ".c", ".h", ".cpp", ".hpp", ".java", ".go", ".rs", ".ts",
}

TEXT_FILENAMES = {"docker-compose.yaml", "Dockerfile", "Makefile", "requirements.txt"}

BINARY_EXTENSIONS = {".pyc", ".pyo", ".so", ".dll", ".exe", ".o", ".a", ".tar", ".gz", ".zip"}


def parse_level_and_ops(req_dir: str):
    parts = req_dir.strip().split("/")
    level = [p for p in parts if p.startswith("level")][0]
    ops_name = parts[-1]
    return level, ops_name


def is_text_file(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    base = os.path.basename(path)
    if ext in BINARY_EXTENSIONS:
        return False
    if ext in TEXT_EXTENSIONS or base in TEXT_FILENAMES:
        return True
    try:
        with open(path, "rb") as f:
            data = f.read(4096)
    except OSError:
        return False
    return b"\x00" not in data


def fix_line_endings(root: str) -> int:
    changed = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            if not is_text_file(path):
                continue
            with open(path, "rb") as f:
                data = f.read()
            if b"\r\n" not in data:
                continue
            data = data.replace(b"\r\n", b"\n")
            with open(path, "wb") as f:
                f.write(data)
            print(f"    fixed line endings: {os.path.relpath(path, root)}")
            changed += 1
    return changed


def create_task(ops_name: str, level: str):
    target_dir = Path(f"{TARGET_DIR}/task_{ops_name}")
    if target_dir.exists():
        print(f"  warning: {target_dir} 已存在，跳过")
        return

    shutil.copytree(TEMPLATE_DIR, target_dir)

    yaml_path = target_dir / "environment" / "docker-compose.yaml"
    content = yaml_path.read_text()
    content = content.replace("image:", f"image: {IMG_NAME}", 1)
    yaml_path.write_text(content)

    dockerfile_path = target_dir / "environment" / "Dockerfile"
    content = dockerfile_path.read_text()
    content = content.replace("FROM", f"FROM {IMG_NAME}@sha256:{IMG_ID}", 1)
    dockerfile_path.write_text(content)

    toml_path = target_dir / "task.toml"
    content = toml_path.read_text()
    content = content.replace("docker_image =", f'docker_image = "{IMG_NAME}"', 1)
    toml_path.write_text(content)

    instr_path = target_dir / "instruction.md"
    content = instr_path.read_text()
    content = content.replace("{level}", level).replace("{ops_name}", ops_name)
    instr_path.write_text(content)

    ops_path = target_dir / "operators.txt"
    content = ops_path.read_text()
    content = content.replace("{ops_name}", ops_name)
    ops_path.write_text(content)

    test_sh_path = target_dir / "tests" / "test.sh"
    content = test_sh_path.read_text()
    content = re.sub(r'DEFAULT_OP_NAME="[^"]*"', f'DEFAULT_OP_NAME="{ops_name}"', content, count=1)
    test_sh_path.write_text(content)

    fix_line_endings(str(target_dir))

    print(f"  done: {target_dir}")


def main():
    rows = OPS_LIST
    print(f"\n共读取 {len(rows)} 条数据:\n")
    for item in rows:
        print(f"  {item}")

    for item in rows:
        level, ops_name = parse_level_and_ops(item)
        create_task(ops_name, level)

    print("\n全部完成")


if __name__ == "__main__":
    main()
