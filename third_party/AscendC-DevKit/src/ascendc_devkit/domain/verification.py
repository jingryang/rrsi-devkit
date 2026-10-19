"""L4 Domain — Verification result types."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class PrecisionDebugResult:
    """precision_debug 闭环结果：CompositeGroup（run_tests→diagnose→fix→printf
    四子 stage）的 in-group 精度调试闭环产物（P54；P0 后由组 transition 物化到 State）。

    子 agent 经 checkpoint 闭环迭代（改码→commit→redeploy→run-cases→读日志→再改），
    轮数耗尽或全部用例通过为止。组终态时 ``_sync_debug_result`` 从 checkpoint 字段
    物化本结果写入 ``state.debug_result``（perf 的 gate + dispatcher 终态消息消费）。

    Fields:
        passed: 全部用例精度是否通过
        max_diff: 最佳 commit 的最大 diff（轮数耗尽时为最小 max_diff）
        best_commit: 最佳 commit sha（轮数耗尽回退目标，防越改越差）
        best_passed_count: 最佳 commit 的通过用例数（passed_count = total - failed；
            best_commit 判据 = passed_count 严格更大；-1 = 未初始化）
        failing_cases: 仍失败的用例名（诊断 + blocking_issues 可见性）
        iterations_used: agent 实际迭代轮数
        stubbed: True 若来自 stub（NPU 不可用降级）
        halt_reason: scope_guard 判定 upstream 时的拦截原因（供 dispatcher 终端消息 +
            log 可见性）
        best_quality: best 的绝对质量态（§step-96 D2，框架从 control.json 计数客观
            派生，非模型判定）——"good"（total>0 且全过）/"partial"（0<passed<total，
            有正证据）/ "bad"（total>0 且 passed==0，零正证据——烂中之最，不当交付物）/
            "unmeasured"（total==0，无任何测量记录）/ ""（未派生）。收尾链据此消费
            质量事实，不靠 redeploy 崩溃重新发现（§step-96 D1）。
    """
    passed: bool
    max_diff: float = 0.0
    best_commit: str = ""
    best_passed_count: int = -1
    failing_cases: list = field(default_factory=list)
    iterations_used: int = 0
    stubbed: bool = False
    halt_reason: str = ""
    best_quality: str = ""


@dataclass(frozen=True)
class PerformanceResult:
    passed: bool
    baseline_ms: float = 0.0
    actual_ms: float = 0.0
    speedup: float = 0.0
    stubbed: bool = False  # True if result came from stub, not real hardware


@dataclass(frozen=True)
class BuildResult:
    passed: bool
    stdout: str = ""
    stderr: str = ""
    artifacts: list[Path] = field(default_factory=list)
    stubbed: bool = False  # True if result came from stub, not real compilation


@dataclass(frozen=True)
class DeployResult:
    """Deployer 产物：部署链成功时的运行态路径信息（Deployer.deploy 返回）。

    Fields:
        run_package: .run 包路径（opp 安装包）
        wheel_package: .whl 包路径（cann_bench python 包）
        ld_library_path_add: 需追加到 LD_LIBRARY_PATH 的 opp lib 目录
            （后续 Stage 调用算子前必须 re-export，deploy 进程内 export 不跨进程）
        smoke_passed: 冒烟测试是否通过（实际调用一次算子验证可调用）。
            codegen 的 smoke 经 precision_debug 同款 harness 真实调用 fn() 一次
            （单用例、无 golden、不验精度），故 smoke_passed=True 名副其实 =
            算子可执行，与 precision_debug 的 run-cases 无断裂。aclnn/unknown 无
            执行探针则 fail-closed（不伪造 True）。
        install_path: per-op opp install-path（02 D 方案：外层 install 到 per-op 目录）
        python_path: pip --target 的 python 模块路径（02 D 方案：PYTHONPATH 注入）
        source_identity: 被测/构建源码的来源标识（纯 git 探测：{HEAD 短12}-{clean|dirty-{n}}，
            见 step-119 precision-control-ownership）。dep=deploy 时对 source_dir 所在仓探测；记录「这个
            包是哪份代码编出来的」，使 eval/debug 能关联被测 binary 与源码 commit，杜绝「跑错代码无人知」。
            dirty 标记编码「构建时工作区有未提交改动」——deploy 先于 commit 时 HEAD 不指向被测内容，
            裸 HEAD 会指错（F6/F7）。默认 ""（旧 last_deploy.json 无此键时 dataclass 兼容）。
    """
    run_package: str = ""
    wheel_package: str = ""
    ld_library_path_add: str = ""
    smoke_passed: bool = False
    install_path: str = ""
    python_path: str = ""
    # 本轮 smoke 失败时持久化的子进程完整输出路径（'' = 本轮 smoke 未失败/未执行）。
    # 供下游（如 Regbase s5 smoke 失败分流 _regbase_smoke_phase）做**新鲜度锚点**：
    # 只有本轮 deploy 真的跑过 smoke 且失败才可能非空——build 阶段失败（未到 smoke）
    # 恒为空，避免读到上一 iteration 的 stale smoke.log 误分类（review m6）。
    smoke_log_path: str = ""
    source_identity: str = ""


@dataclass(frozen=True)
class AdaptResult:
    """CannbenchAdaptStage 产物：仓胶水文件适配结果 + m.def schema 对齐。

    Fields:
        adapted: 是否执行了适配修改
        files_modified: 修改的文件列表（仓胶水文件路径，非算子代码）
        errors: 适配过程中的错误（非算子代码质量问题）
        schema_renamed: P10 根治——m.def schema 参数名对齐 proto.yaml 的 rename
            记录，每项 {"from": <旧名>, "to": <新名>}。空 = 无需对齐或对齐失败
            （失败时 errors 记原因）。torch 按 schema 名绑定，C++ 局部形参名无关，
            故只改 m.def schema 字符串 + rebuild opp，不动 kernel。
        rebuilt: m.def 改动后是否触发了 opp rebuild（Deployer.deploy）
    """
    adapted: bool = False
    files_modified: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    schema_renamed: list[dict] = field(default_factory=list)
    rebuilt: bool = False


@dataclass(frozen=True)
class EvalResult:
    """CannbenchEvalStage 产物：cann-bench 评测三维度得分。

    Weight scheme (cann-bench src/kernel_eval/benches/cann_scoring.py):
        w_c = 0.2 (compilation), w_f = 0.3 (function), w_p = 0.5 (performance)
        overall_score = compilation_score + function_score + performance_score [0, 100]

    Fields:
        overall_score: 三维度加权总分
        pass_rate: 功能用例通过率 (passed / total)
        compile_score: 编译维度分 (0-20)
        function_score: 功能维度分 (0-30)
        performance_score: 性能维度分 (0-50)
        report_json: cann-bench eval_*.json 报告路径
        baseline_source: "inherited" (继承标准 task baseline) | "fallback" (合成 baseline)
        num_cases: 评测用例总数
        num_passed: 通过用例数
    """
    overall_score: float = 0.0
    pass_rate: float = 0.0
    compile_score: float = 0.0
    function_score: float = 0.0
    performance_score: float = 0.0
    report_json: str = ""
    baseline_source: str = ""
    num_cases: int = 0
    num_passed: int = 0
