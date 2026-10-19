"""L7 Infrastructure — ASCEND_CUSTOM_OPP_PATH 环境契约守护（单点，step-108）。

批 20260829-142941-49134b P3（docs/plan/batch-20260829-49134b-codegen-delivery/）：
外部 sitecustomize 在解释器启动期把**正确的** vendor 级 ``ASCEND_CUSTOM_OPP_PATH``
后缀剥掉——症状经 GE 静默回退、dlopen 错库、dlsym 失败三层传导后与 codegen bug
同形，agent 烧小时级预算现场诊断，自救时反向污染机器（三向量）。本模块是修复的
工程侧最小件：**契约自守、秒级归因、不空烧**——外部毒本体归 ops 清理（既有裁定：
外部 infra 不归框架修，框架只保证不误报/不空烧/留信号）。

不变式（唯一产权）：框架设入的期望值必须**原样作为元素出现在实际运行子进程同名
env 的冒号列表中**（``expected in actual.split(":")``）。用成员而非全等：CANN 官方
语义该变量是优先级列表，``set_env.bash`` 合法追加不触发；剥离/替换才触发。判据只认
契约语义、不认投递机制（§1.10）——换前缀匹配、挪系统 site、换投递载体，断言照样命中。

三层消费（docs/plan/05-impl-env-contract-guard.md）：
① dispatcher ``_run_runtime_checks`` Check 3（开跑秒级，合成但**形态忠实**的探测值
   ——哑值触发不了后缀匹配类毒，形态必须真实）；
② deploy ``_run_smoke_phase`` 尾探针（真实生产值，失配 raise
   EnvironmentNotAvailableError → pause 家族 preserve，不回滚树）；
③ harness 生成器 ``harness_assert_block`` 烘入模板入口（消费点地面真值 + ownership
   机械输入，专用退出码 + ``[ENV_CONTRACT]`` stderr 标记；判定权仍在模型，非门）。

主进程纯度（step-104 红线）：探针子进程纯 stdlib（``import os``），零 torch import。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from ascendc_devkit.infra.logger import Logger

#: harness 侧专用退出码（step-94 rc 契约通道的一个保留值；模板此前仅用 1）
ENV_CONTRACT_EXIT_CODE = 90
#: stderr 可 grep 标记——coder skill 引用语义词（"环境契约专用错误"），不引数字
ENV_CONTRACT_MARKER = "[ENV_CONTRACT]"
#: 开跑预检的合成探测值——**形态忠实**（后缀必须与生产值同形），哑值探不出后缀匹配类毒
PREFLIGHT_PROBE_VALUE = "/tmp/devkit-env-preflight/vendors/custom_ops"

_PROBE_CHILD_CODE = (
    "import os\n"
    "print(os.environ.get('ASCEND_CUSTOM_OPP_PATH', ''))\n"
)


def expected_ascend_custom_opp(per_op_opp_dir: str) -> str:
    """值形态单源（§1.15）：vendor 级路径由且仅由本函数拼出。

    CANN 官方语义（知识库 算子包部署.md）：该变量粒度是 vendor 级
    ``<path>/<vendor_name>``；runner/deploy/eval 三处构造点一律经本函数，
    禁止再出现裸 f-string 拼接（第二形态源=drift 温床，UT 源级守护）。
    """
    return f"{per_op_opp_dir}/vendors/custom_ops"


def ascend_custom_opp_intact(expected: str, actual: str) -> bool:
    """成员断言：期望值必须是实际值冒号列表的元素（合法追加允许，剥离/替换失配）。"""
    return expected in actual.split(":")


def probe_env_contract(env: dict, timeout_sec: float = 10.0) -> str | None:
    """回环探针：spawn 纯 stdlib 子进程回读 ``ASCEND_CUSTOM_OPP_PATH``，与 env
    中期望值做成员断言。

    返回 ``None``=通过；``str``=失配诊断行（含期望/实际双值对照，10 秒人工可判）。
    子进程零 torch import（step-104 主进程纯度不变式同样适用于探测路径）。
    探针子进程自身失败（rc≠0）单独归因——那是启动/解释器层问题，不是值改写，
    不得误报成「在子进程内被改写」。
    """
    expected = env.get("ASCEND_CUSTOM_OPP_PATH", "")
    if not expected:
        return None  # 无契约可守（非 NPU 上下文）——诚实跳过，不假报
    try:
        result = subprocess.run(
            [sys.executable, "-c", _PROBE_CHILD_CODE],
            env=env, capture_output=True, text=True, timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        return (
            f"{ENV_CONTRACT_MARKER} env 回环探针超时（{timeout_sec:.0f}s）——"
            f"expected {expected!r}，子进程未返回"
        )
    except OSError as e:
        return (
            f"{ENV_CONTRACT_MARKER} env 回环探针失败：{e}"
            f"（expected {expected!r}）"
        )
    if result.returncode != 0:
        stderr_lines = (result.stderr or "").strip().splitlines()
        tail = f"，stderr 尾行: {stderr_lines[-1]}" if stderr_lines else ""
        return (
            f"{ENV_CONTRACT_MARKER} env 回环探针子进程启动失败"
            f"（rc={result.returncode}{tail}）——expected {expected!r}，"
            f"未取得回读值（探针自身失败，非值改写）"
        )
    actual = (result.stdout or "").strip().splitlines()[-1] if result.stdout.strip() else ""
    if not ascend_custom_opp_intact(expected, actual):
        return (
            f"{ENV_CONTRACT_MARKER} ASCEND_CUSTOM_OPP_PATH 在子进程内被改写：\n"
            f"  expected: {expected}\n"
            f"  actual:   {actual or '(空)'}\n"
            f"  候选成因：解释器启动钩子（sitecustomize / .pth）——"
            f"环境问题，非算子代码问题"
        )
    return None


def diagnose_env_hooks() -> list[str]:
    """失败路径专用诊断（只读、报事实不定罪）：列出可见的启动钩子证据。

    覆盖两类投递位置：``PYTHONPATH`` 目录与 user-site 目录（``sitecustomize.py``
    与 ``*.pth``）。诊断本身绝不上抛——它只是失配信号的附属线索（§1.2 可观测）。
    """
    lines: list[str] = []
    for d in (p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p):
        f = Path(d) / "sitecustomize.py"
        if f.is_file():
            lines.append(f"PYTHONPATH 目录含启动钩子: {f}")
    try:
        import site
        usp = Path(site.getusersitepackages())
        f = usp / "sitecustomize.py"
        if f.is_file():
            lines.append(f"user-site 含启动钩子: {f}")
        if usp.is_dir():
            lines.extend(f"user-site 含 .pth: {p}" for p in sorted(usp.glob("*.pth")))
    except Exception as e:  # noqa: BLE001 — 诊断通道自坏不得掩盖主失配信号
        lines.append(f"user-site 检查异常（只读诊断，不影响判定）: {e}")
    return lines


# 撞名 WARN 进程级去重：同一实体树只 WARN 一次——多阶段重复扫描同一 vendors
# 树时事实已留痕，重复行不增信息、只刷屏。
_VENDOR_COLLISION_WARNED: set[str] = set()


def warn_system_vendor_collisions(
    op_names: list[str], opp_path: str | None = None,
) -> int:
    """撞名 WARN（信息级，不拦跑）：本批任务算子名撞系统 OPP vendors 内实体。

    判据用业务语义——任务名与环境实体**精确同名**（§1.10/§1.12：算子名从运行时
    任务清单派生，无内置清单；「系统目录非空」这类机制特征不作判据）。命中打一行
    WARN（进程级去重：同树只 WARN 一次）：批 20260829 的 take_along_dim 兄弟
    覆盖事后 2h 取证，此类况开跑即留痕。
    """
    root = opp_path if opp_path is not None else os.environ.get("ASCEND_OPP_PATH", "")
    if not root:
        return 0
    vendors = Path(root) / "vendors"
    if not vendors.is_dir():
        return 0
    hits = 0
    for name in (n for n in op_names if n):
        for match in vendors.rglob(name):
            if match.is_dir():
                key = str(match)
                if key in _VENDOR_COLLISION_WARNED:
                    continue
                _VENDOR_COLLISION_WARNED.add(key)
                Logger.warn(
                    f"系统 OPP vendors 已存在与本任务同名的实体: {match} "
                    f"（前次运行的残留会经 GE 系统扫描干扰本任务——建议清理）")
                hits += 1
    return hits


def harness_assert_block(expected_opp: str) -> str:
    """harness 模板入口断言块（生成器单点块本体；空期望 → 空块不注入）。

    失配三要素：``[ENV_CONTRACT]`` 标记 + 期望/实际双值 + 归属指引（环境问题非代码
    问题，按 ownership 判 not_codegen 交棒；勿写系统目录自建通路）。专用退出码走
    step-94 rc 契约通道——判定权仍在 coder 模型（step-93），框架只供机械事实。
    """
    if not expected_opp:
        return ""
    return (
        f"\n# step-108 env 契约断言：框架下传的 ASCEND_CUSTOM_OPP_PATH 必须原样\n"
        f"# 存活到本进程（成员语义：合法追加允许，剥离/替换即失配）。\n"
        f"_expected_opp = {expected_opp!r}\n"
        f"_actual_opp = os.environ.get('ASCEND_CUSTOM_OPP_PATH', '')\n"
        f"if _expected_opp not in _actual_opp.split(':'):\n"
        f"    sys.stderr.write('{ENV_CONTRACT_MARKER} ASCEND_CUSTOM_OPP_PATH "
        f"mutated in-flight\\n')\n"
        f"    sys.stderr.write('  expected: %r\\n' % _expected_opp)\n"
        f"    sys.stderr.write('  actual:   %r\\n' % _actual_opp)\n"
        f"    sys.stderr.write('{ENV_CONTRACT_MARKER} likely: interpreter startup "
        f"hook (sitecustomize/.pth) — environment problem, NOT kernel code; "
        f"report per ownership (not_codegen); do NOT write system dirs to work "
        f"around\\n')\n"
        f"    sys.exit({ENV_CONTRACT_EXIT_CODE})\n"
    )
