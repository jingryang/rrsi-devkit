"""P79: PrecisionComparer 协议 — rule × backend 正交的 **backend 侧**。

策略对象（在主进程）负责 (1) 注入 subprocess harness 的 setup/import 行、
(2) 聚合子进程回传的 ``case_details``。比较本身在 subprocess harness 内执行
（张量在那，主进程只聚合）——故本协议**不是**主进程 ``compare(rule, output, golden)``
可调用对象，而是「harness 怎么判 + 主进程怎么读」的策略。

backend 显式选择：step-40 起由 ``EvaluationBackend``（``DevkitBackend`` /
``CannbenchBackend``）依 ``cases_source`` 选定——``CannbenchBackend`` 注入
``CannbenchComparer``（harness 走 cann-bench ``compare_tensors`` 权威路径），
``DevkitBackend`` 注入 ``DevkitComparer``（abs-diff 默认路径）。
**取代** runner 原 ``'tasks/' in golden_source_path`` 嗅探（同一事实的冗余再推导）。

rule（``CompareRule.dtype_thresholds`` = proto 真值）同时驱动 harness 阈值烘焙
（runner 在 ``DTYPE_THRESHOLDS`` / ``_custom_th`` 两处烘焙）+ 聚合判 diff>threshold。

预留 L4 ``CommandBackend``（命令注入）：未来只新增一个 adapter，协议签名
（``harness_setup_lines`` / ``aggregate``）稳定（§2.7 形状预留不实现）。

v1 范围（P79）：显式选择 + proto 桥接 + 删路径嗅探/``_custom_th`` 硬编。
FALLBACK 路径 abs-diff → ``precision_compare`` MERE/MARE 的方法升级预留 P79.1（待 ST 验证）。
"""

from __future__ import annotations

from typing import Protocol

from ascendc_devkit.domain.precision import CompareRule


class PrecisionComparer(Protocol):
    """subprocess-harness 精度判定策略（backend 侧）。

    比较在 harness 内执行；本协议在主进程负责 setup 注入 + 结果聚合。
    """

    degradation_signatures: tuple[str, ...]
    """harness stderr 中标志「本 backend 降级」的子串（由 backend 自声明：它知道
    自己注入的 warning 原文）。runner 通用层据此 scan 命中即上浮主 log [WARN]，不
    认识任何 backend 特定文本（§1.6 DI + §2.7 backend 自包含，避免通用 runner 耦合
    cann-bench）。空 tuple = 无降级（DevkitComparer 无外部 import）。"""

    def harness_setup_lines(self, rule: CompareRule) -> list[str]:
        """注入 harness 顶部 setup/import 行（如 kernel_eval import）。

        devkit 默认返回空（abs-diff 路径用 harness 内 numpy）。``rule`` 是 forward
        hook：留给需在 setup 烘焙阈值的 backend（如 CommandBackend 注入参数）；当前
        两个实现都不读它，但保留以稳定协议签名（§1.2 可扩展契约）。
        """
        ...

    def aggregate(self, rule: CompareRule, case_details: list[dict]) -> bool:
        """聚合子进程回传的 ``case_details`` → 全输出 pass/fail。

        逐 case 逐输出：output 带 ``passed``（cann-bench 路径）→ 权威；否则
        ``diff > threshold``（devkit abs-diff 路径，threshold 取 ``rule.dtype_thresholds``
        或 output 自带 threshold）。
        """
        ...


def judge_case_details(rule: CompareRule, case_details: list[dict]) -> bool:
    """共享聚合逻辑（原 ``runner._all_outputs_within_threshold``，P79 提取为单一通路）。

    三表合一后规范表 = ``precision_compare.DEFAULT_THRESHOLDS``（无 ``*`` 项），
    未知 dtype 经 ``dts.get(out_dtype, out.get('threshold', 1e-2))`` 回退 1e-2
    （与旧 ``_DTYPE_THRESHOLDS_FALLBACK['*']`` 等价，行为不变）。
    """
    dts = rule.dtype_thresholds
    for cd in case_details:
        # case 级执行异常（crash/timeout，harness 写 error 字段）→ 失败；
        # 不得靠空循环空真通过（error case 无 output_results 时旧逻辑假通过）。
        if cd.get("error"):
            return False
        # 无任何输出对比数据（compare_tensors 输出数量不匹配时返回空
        # output_results + passed=False，harness 曾丢弃 passed）→ 数据缺失
        # 不是通过证据，空循环空真通过是 unique 假通过根因。
        if not any(cd.get(k) for k in ("output_results", "outputs")):
            return False
        # 兼容两种键名（'output_results' 新格式 / 'outputs' 旧格式）
        for out_list_key in ("output_results", "outputs"):
            for out in cd.get(out_list_key, []):
                # cann-bench checker 判定优先（output 带 passed 字段）
                if "passed" in out and isinstance(out["passed"], bool):
                    if not out["passed"]:
                        return False
                    continue
                diff = out.get("diff", 999.0)
                if diff < 0:
                    continue  # 无 golden → 跳过该输出 pass/fail 判定
                out_dtype = out.get("dtype", "")
                threshold = dts.get(out_dtype, out.get("threshold", dts.get("*", 1e-2)))
                if diff > threshold:
                    return False
    return True


class DevkitComparer:
    """§1.7 自包含默认 backend：harness 走 devkit 默认比较路径（abs-diff）。

    零 import cann-bench。FALLBACK 路径阈值来自 ``rule.dtype_thresholds``（proto 真值）。
    预留 P79.1：FALLBACK 升级为 ``precision_compare`` MERE/MARE——待 ST 验证，本次不做。
    """

    degradation_signatures = ()  # 无 cann-bench import，不存在降级

    def harness_setup_lines(self, rule: CompareRule) -> list[str]:
        return []  # abs-diff 路径用 harness 内 numpy，无需额外 import

    def aggregate(self, rule: CompareRule, case_details: list[dict]) -> bool:
        return judge_case_details(rule, case_details)


class CannbenchComparer:
    """可选注入 backend：harness 走 cann-bench ``compare_tensors``（权威）。

    选择 = 显式（``debug_service`` 依任务加载传入）；import 路径解析（定位 cann-bench
    src）在 harness 内以 ``src/kernel_eval/utils/compare.py`` 结构锚点自 golden 向上
    找仓根——cann-bench ``package=false`` 不可 pip 安装，需从 golden 目录反推 src，但**不**
    依赖 golden 落在 ``tasks/`` 还是 ``bench_lab/kernel_bench/``（原 ``'tasks/' in path``
    嗅探对后者失配，已改结构锚点定位，落实本类 docstring 早先宣称的「取代路径嗅探」）。
    软降级：import 失败 → ``_cann_checker_used=False`` → harness 自动退 devkit 默认路径
    （``warnings.warn`` 留痕 + runner 上浮主 log，§1.2 可诊断，不静默吞）。
    """

    # runner 通用层据此 scan harness stderr 上浮降级 [WARN]——不 hardcode cann-bench
    # 文本（§1.6 DI + §2.7 backend 自包含）。两个串是 harness_setup_lines 注入的
    # warning 原文，由本 backend 自己声明（改 warning 文案时同步改这里）。
    degradation_signatures = ("compare_tensors 不可用", "退 devkit 默认路径")

    def harness_setup_lines(self, rule: CompareRule) -> list[str]:
        # 注入 harness：尝试 import cann-bench compare_tensors（软失败降级）。
        # backend 选择已由 debug_service 显式决定（传入 CannbenchComparer）；此处只做
        # cann-bench src 定位（结构锚点向上找，见下）。
        #
        # 契约：``_compare_tensors`` / ``_cann_checker_used`` 的默认值由 runner 模板
        # 提供（``_compare_tensors = None`` / ``_cann_checker_used = False``）——本方法
        # 只做 **specialization**（import 成功则翻转 flag）。不再重复声明默认值，模板
        # 是默认值的单一来源（TestHarnessBackendContractVars 守护此契约）。
        return [
            "# 定位 cann-bench src（package=false 不可 pip 装）：以稳定结构锚点",
            "#   <cann-bench>/src/kernel_eval/utils/compare.py",
            "# 自 golden_source_path 向上找含此文件的仓根——不依赖 golden 在 tasks/",
            "# 还是 bench_lab/kernel_bench/ 下（原 'tasks/' in path 嗅探对后者失配）。",
            "_cann_src = None",
            "_p = os.path.dirname(os.path.abspath(str(golden_source_path))) if golden_source_path else ''",
            "for _ in range(8):  # 至多向上 8 层，覆盖 golden 嵌套深度",
            "    _cand = os.path.join(_p, 'src')",
            "    if os.path.isfile(os.path.join(_cand, 'kernel_eval', 'utils', 'compare.py')):",
            "        _cann_src = _cand",
            "        break",
            "    _np = os.path.dirname(_p)",
            "    if _np == _p:",
            "        break",
            "    _p = _np",
            "if _cann_src and _cann_src not in sys.path:",
            "    sys.path.insert(0, _cann_src)",
            "try:",
            "    from kernel_eval.utils.compare import compare_tensors as _compare_tensors",
            "    _cann_checker_used = True",
            "except ImportError as _cann_imp_err:",
            "    import warnings",
            "    warnings.warn('CannbenchComparer: cann-bench compare_tensors 不可用 "
            "(%r)，退 devkit 默认路径' % (_cann_imp_err,))",
        ]

    def aggregate(self, rule: CompareRule, case_details: list[dict]) -> bool:
        return judge_case_details(rule, case_details)
