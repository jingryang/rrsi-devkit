"""UT for domain.build_log_scanner — 检测被 build_run.sh ``||`` 吞掉的 kernel 编译失败。

守护第 5 类隐患的核心不变式(Plan lovely-painting-aurora):
  - build_run.sh 的 ``cmake --build --target binary || { echo WARNING; }`` 把 kernel
    编译失败吞成 RC=0;scanner 是 deploy.py:_run_command RC=0 分支的「真传感器」，
    让被吞的编译失败重走 RC≠0 通路(落盘 + 返回 False),供 codegen in-session 自修循环捕获。
  - **真信号**必须命中(clang ``error:`` / ``Op[..] compile failed, kernelName`` /
    ``Opc tool compile failed`` / ``Kernel Compilation Error`` / ``.json not generated``)。
  - **良性信号**绝不命中(``WARNING: ... may have errors`` 是 ``||`` 触发器非错误本身、
    ``Opc tool start working`` 成功时也有、clang ``note:`` 候选上下文、CMake/ Built target)。
  - 去重:同一 kernel 哈希按 tiling_key 复现多次只记一次;同一 ``.h:line:error`` 跨
    tiling_key 重复只记一条(CEL 实测 6 tiling_key × 5 error 位置 = 30 次 → 去重 5 条)。

样本来自真实 ``/tmp/cel_build.log``(CEL 手动 build,Cast×3 + DataCopyPad×2,
6 个 kernel 哈希全挂),fixture 内联以保持 UT 自包含(§3.8,不依赖外部文件)。
"""

from __future__ import annotations

from ascendc_devkit.capabilities.knowledge import KnowledgeBase
from ascendc_devkit.domain.build_log_scanner import (
    KernelCompileError,
    build_failure_analysis_footer,
    classify_build_error,
    format_kernel_error_summary,
    scan_kernel_compile_errors,
)

# 真实 CEL build 日志精简片段:含全部真信号(A1/A2/A4/A6/A7) + 夹杂良性信号(B1-B7)。
CEL_BUILD_LOG = """\
[INFO] Succeeded generated npu_supported_ops.json
CMake Warning at func.cmake
Consolidate compiler generated dependencies
Built target cross_entropy_loss_api
Opc tool start working now, please wait for a moment.
[ERROR] TBE(2743560,python3):2026-07-13-10:00:40.334.234 [opc.py:688][main] Opc tool compile failed.
Op[CrossEntropyLoss] of index[0] compile failed, kernelName: CrossEntropyLoss_5945fda914f1625e88f543659b5c0f58.
/home/x/code/cross_entropy_loss/op_kernel/cross_entropy_loss.h:294:13: error: no matching function for call to 'Cast'
/home/x/code/cross_entropy_loss/op_kernel/cross_entropy_loss.h:294:13: note: candidate function template not viable
/home/x/code/cross_entropy_loss/op_kernel/cross_entropy_loss.h:305:17: error: no matching function for call to 'Cast'
/home/x/code/cross_entropy_loss/op_kernel/cross_entropy_loss.h:164:9: error: no matching function for call to 'DataCopyPad'
/home/x/code/cross_entropy_loss/op_kernel/cross_entropy_loss.h:183:9: error: no matching function for call to 'DataCopyPad'
/home/x/code/cross_entropy_loss/op_kernel/cross_entropy_loss.h:221:13: error: no matching function for call to 'Cast'
RuntimeError: Kernel Compilation Error: OpType CrossEntropyLoss Kernel File /home/x/code/cross_entropy_loss/op_kernel/cross_entropy_loss_kernel.cpp!
/home/x/code/cross_entropy_loss/build/all_kernels/binary/ascend910b/cross_entropy_loss/CrossEntropyLoss_5945fda914f1625e88f543659b5c0f58.json not generated!
WARNING: Kernel binary build may have errors, continuing with package creation...
"""

# 纯良性日志:成功 build 的典型输出 + ``||`` 触发器行,无任何真信号。
BENIGN_BUILD_LOG = """\
[INFO] Succeeded generated npu_supported_ops.json
CMake Warning at func.cmake: PACKAGE_NAME is not supported now
Consolidate compiler generated dependencies
Built target cross_entropy_loss_api
Opc tool start working now, please wait for a moment.
Generating npu_supported_ops.json Done
WARNING: Package build may have errors due to missing kernel binaries
"""

# 多 tiling_key 场景:同一组 clang error 按 6 个 kernel 哈希各复现一次(A2) +
# 同一 .h:line:error 也复现(模拟每个 tiling_key 各编译一次)。
MULTI_TILING_KEY_LOG = """\
Op[CrossEntropyLoss] of index[0] compile failed, kernelName: CrossEntropyLoss_5945fda914f1625e88f543659b5c0f58.
Op[CrossEntropyLoss] of index[0] compile failed, kernelName: CrossEntropyLoss_7469948d6df57df721cf8939cc9b44a5.
Op[CrossEntropyLoss] of index[0] compile failed, kernelName: CrossEntropyLoss_8da7716046b4e0f8b9b1a282f469eb1f.
Op[CrossEntropyLoss] of index[0] compile failed, kernelName: CrossEntropyLoss_5945fda914f1625e88f543659b5c0f58.
/home/x/code/cross_entropy_loss/op_kernel/cross_entropy_loss.h:294:13: error: no matching function for call to 'Cast'
/home/x/code/cross_entropy_loss/op_kernel/cross_entropy_loss.h:294:13: error: no matching function for call to 'Cast'
/home/x/code/cross_entropy_loss/op_kernel/cross_entropy_loss.h:294:13: error: no matching function for call to 'Cast'
"""

# 无 clang error 行,但结构化信号表明编译失败(A1 + A4)→ 兜底返回一条。
NO_CLANG_BUT_FAILED_LOG = """\
[ERROR] TBE(123,python3):[opc.py:688][main] Opc tool compile failed.
RuntimeError: Kernel Compilation Error: OpType Foo Kernel File /home/x/foo/op_kernel/foo_kernel.cpp!
"""


class TestScanKernelCompileErrors:
    def test_real_cel_log_detects_all_five_error_sites(self):
        errs = scan_kernel_compile_errors(CEL_BUILD_LOG)
        # 5 个去重 error 位置:Cast×3 (294/305/221) + DataCopyPad×2 (164/183)
        assert len(errs) == 5
        msgs = [e.message for e in errs]
        assert sum("Cast" in m for m in msgs) == 3
        assert sum("DataCopyPad" in m for m in msgs) == 2
        # source 带文件名 + 行号,agent 可直接定位
        assert all("cross_entropy_loss.h:" in e.source for e in errs)
        assert any(":294" in e.source for e in errs)
        # op_name 从 A2 结构化信号提取
        assert all(e.op_name == "CrossEntropyLoss" for e in errs)

    def test_benign_log_returns_empty(self):
        # WARNING/Opc start/CMake Warning/Built target/Succeeded 都不是失败信号
        assert scan_kernel_compile_errors(BENIGN_BUILD_LOG) == []

    def test_empty_text_returns_empty(self):
        assert scan_kernel_compile_errors("") == []
        assert scan_kernel_compile_errors(None) == []  # type: ignore[arg-type]

    def test_clang_error_dedup_by_source_line(self):
        # 同一 .h:294 error 出现 3 次(多 tiling_key 各编译一次)→ 只记 1 条
        errs = scan_kernel_compile_errors(MULTI_TILING_KEY_LOG)
        cast_errs = [e for e in errs if "Cast" in e.message]
        assert len(cast_errs) == 1
        assert ":294" in cast_errs[0].source

    def test_clang_note_lines_not_flagged(self):
        # note: 行是 clang 候选上下文,不是 error
        text = (
            "/home/x/op_kernel/x.h:10:1: note: candidate function template not viable\n"
            "/home/x/op_kernel/x.h:10:1: note: constraint not satisfied\n"
        )
        assert scan_kernel_compile_errors(text) == []

    def test_fallback_when_no_clang_line_but_structured_failure(self):
        # 极端:有 Opc tool compile failed + Kernel Compilation Error 但无 clang error 行
        # → 兜底返回至少一条,op_name 从 RuntimeError(A4)提取
        errs = scan_kernel_compile_errors(NO_CLANG_BUT_FAILED_LOG)
        assert len(errs) >= 1
        assert errs[0].op_name == "Foo"
        assert errs[0].message  # 非空

    def test_cmake_and_package_errors_not_flagged(self):
        # 底部 CMake/CPack/ld 错误不属 kernel 编译失败(可能是 host 链接,RC≠0 已由现有通路捕获)
        text = (
            "CMake Error at CMakeLists.txt:10 (message)\n"
            "ld.lld: error: cannot open libfoo.so: No such file or directory\n"
            "ERROR: No run package found\n"
        )
        assert scan_kernel_compile_errors(text) == []

    def test_multiline_gcc_host_error_detected(self):
        """2026-09-10 transpose: host 侧 g++ 编译错误是两行形态——
        ``path:line:col:`` 与 ``error:`` 分两行,原单行正则漏掉。跨行正则必须命中。"""
        text = (
            "  /home/x/code/transpose/op_host/transpose_infershape.cpp:40:11:\n"
            "  error: 'TypedContinuousVector' does not name a type\n"
            "\n"
            "     40 |     const TypedContinuousVector<int64_t>* permVec = "
            "runtimeAttrs->GetListInt(0);\n"
        )
        errs = scan_kernel_compile_errors(text)
        assert len(errs) == 1
        assert "transpose_infershape.cpp:40" in errs[0].source
        assert "TypedContinuousVector" in errs[0].message

    def test_multiline_error_dedup_by_source_line(self):
        """跨行形态同一 file:line 出现多次(两个 .cpp 各一次)仍去重到一条。"""
        text = (
            "  /home/x/code/transpose/op_host/a.cpp:69:11:\n"
            "  error: 'TypedContinuousVector' does not name a type\n"
            "  /home/x/code/transpose/op_host/b.cpp:69:11:\n"
            "  error: 'TypedContinuousVector' does not name a type\n"
        )
        errs = scan_kernel_compile_errors(text)
        assert len(errs) == 2   # 不同文件 → 两条(不是同一源去重)
        assert {e.source for e in errs} == {
            "/home/x/code/transpose/op_host/a.cpp:69",
            "/home/x/code/transpose/op_host/b.cpp:69",
        }

    def test_multiline_error_matches_singleline_unified(self):
        """单行(asc_opc/TBE)与跨行(g++)两态统一进同一去重池——同源同消息只记一条。"""
        text = (
            "op_kernel/foo.h:294:13: error: no matching function for call to 'Cast'\n"
            "  /home/x/code/op_host/foo.cpp:294:13:\n"
            "  error: no matching function for call to 'Cast'\n"
        )
        errs = scan_kernel_compile_errors(text)
        # 两条不同源(one in op_kernel/foo.h, one in op_host/foo.cpp)→ 两条,不互相去重
        assert len(errs) == 2

    def test_multiline_gcc_host_error_detected(self):
        """2026-09-10 transpose: host 侧 g++ 编译错误是两行形态——
        ``path:line:col:`` 与 ``error:`` 分两行,原单行正则漏掉。跨行正则必须命中。"""
        text = (
            "  /home/x/code/transpose/op_host/transpose_infershape.cpp:40:11:\n"
            "  error: 'TypedContinuousVector' does not name a type\n"
            "\n"
            "     40 |     const TypedContinuousVector<int64_t>* permVec = "
            "runtimeAttrs->GetListInt(0);\n"
        )
        errs = scan_kernel_compile_errors(text)
        assert len(errs) == 1
        assert "transpose_infershape.cpp:40" in errs[0].source
        assert "TypedContinuousVector" in errs[0].message

    def test_multiline_error_dedup_by_source_line(self):
        """跨行形态同一 file:line 出现多次(两个 .cpp 各一次)仍去重到一条。"""
        text = (
            "  /home/x/code/transpose/op_host/a.cpp:69:11:\n"
            "  error: 'TypedContinuousVector' does not name a type\n"
            "  /home/x/code/transpose/op_host/b.cpp:69:11:\n"
            "  error: 'TypedContinuousVector' does not name a type\n"
        )
        errs = scan_kernel_compile_errors(text)
        assert len(errs) == 2   # 不同文件 → 两条(不是同一源去重)
        assert {e.source for e in errs} == {
            "/home/x/code/transpose/op_host/a.cpp:69",
            "/home/x/code/transpose/op_host/b.cpp:69",
        }

    def test_multiline_error_matches_singleline_unified(self):
        """单行(asc_opc/TBE)与跨行(g++)两态统一进同一去重池——同源同消息只记一条。"""
        text = (
            "op_kernel/foo.h:294:13: error: no matching function for call to 'Cast'\n"
            "  /home/x/code/op_host/foo.cpp:294:13:\n"
            "  error: no matching function for call to 'Cast'\n"
        )
        errs = scan_kernel_compile_errors(text)
        # 两条不同源(one in op_kernel/foo.h, one in op_host/foo.cpp)→ 两条,不互相去重
        assert len(errs) == 2

    def test_returns_kernel_compile_error_dataclass(self):
        errs = scan_kernel_compile_errors(CEL_BUILD_LOG)
        assert all(isinstance(e, KernelCompileError) for e in errs)
        # frozen dataclass(State/领域对象风格一致)
        try:
            errs[0].op_name = "x"  # type: ignore[misc]
            assert False, "KernelCompileError should be frozen"
        except AttributeError:
            pass


class TestFormatKernelErrorSummary:
    def test_summary_contains_op_name_and_first_errors(self):
        errs = scan_kernel_compile_errors(CEL_BUILD_LOG)
        summary = format_kernel_error_summary(errs)
        assert "CrossEntropyLoss" in summary
        assert "no matching function" in summary  # clang 错误原文
        assert "cross_entropy_loss.h" in summary  # 定位信息

    def test_summary_empty_errors(self):
        assert format_kernel_error_summary([]) == ""

    def test_summary_truncates_long_error_list(self):
        # 30 条 error 不应刷屏,截断到合理条数
        many = [
            KernelCompileError(
                op_name="Op", source=f"op_kernel/x.h:{i}", message=f"err {i}")
            for i in range(30)
        ]
        summary = format_kernel_error_summary(many)
        # 含总数提示 + 截断(出现次数 < 30 的 error 行)
        assert "30" in summary
        assert summary.count("op_kernel/x.h:") < 30


# 纯链接器症状:ld.lld cannot open .o,无 clang 诊断行、无结构化 marker。
# 这是 codegen transcript 里 70× 静默失败案例的形态——footer 必须诚实返回 ""（日志里
# 没有可富化的信号，不加噪；真静默需另走 kernel_meta 日志，非本函数职责）。
LINKER_SYMPTOM_LOG = """\
[ 87%] Building CXX object .../op_kernel/foo.cpp.o
ld.lld: error: cannot open /home/x/examples/aclnn_launch_example/build/Foo_ascend910b/kernel_0/kernel_meta/Foo_abc_9.o: No such file or directory
cmake --build ... failed
"""

KB_ROOT = KnowledgeBase().root  # in-repo, self-contained (§1.7)


class TestBuildFailureAnalysisFooter:
    """阶段1 (Plan cozy-wiggling-emerson): build 失败时框架确定性富化 agent 读的 log。

    codegen in-session redeploy 循环里 agent 读 subprocess/*.log 自修；原本只看到
    原始 stderr（签名错也凭记忆改 → 244 次失败）。footer 把「结构化 clang 错误」+
    「API 签名权威指路」追加到 log，agent 每轮读到 → 不再瞎猜。
    """

    def test_signature_error_footer_has_doc_path_and_directive(self):
        footer = build_failure_analysis_footer(
            "", CEL_BUILD_LOG, "Membase", KB_ROOT)
        # Cast 是 CEL_BUILD_LOG 里的签名错；footer 应含其权威 doc 路径 + 逐字指令。
        assert footer != ""
        assert "框架错误分析" in footer  # 标注段（区别于编译器原文）
        assert "Cast" in footer
        assert "高阶API" in footer or "api_reference_docs" in footer  # doc 路径
        assert "逐字" in footer or "Read" in footer  # 权威指路指令

    def test_footer_labeled_distinct_from_compiler_output(self):
        # footer 必须有清晰的起止标注，agent 不会把它当成编译器诊断。
        footer = build_failure_analysis_footer(
            "", CEL_BUILD_LOG, "Membase", KB_ROOT)
        assert footer.startswith("\n=== 框架错误分析")
        assert "=== end 框架错误分析" in footer

    def test_footer_combines_summary_and_signature_hint(self):
        # 同一 log 同时含 clang 错误（→结构化摘要，带 file:line）+ 签名错（→doc 指路）。
        footer = build_failure_analysis_footer(
            "", CEL_BUILD_LOG, "Membase", KB_ROOT)
        assert "cross_entropy_loss.h" in footer  # clang 摘要的 file:line
        assert "Cast" in footer  # 签名指路

    def test_clean_log_no_footer(self):
        # 良性 build 日志 → 不加噪，返回 ""。
        assert build_failure_analysis_footer(
            "", BENIGN_BUILD_LOG, "Membase", KB_ROOT) == ""

    def test_pure_linker_symptom_no_footer(self):
        # 真静默链接器症状（70× 案例）：日志里无 clang 行、无结构化 marker、无签名错
        # → footer 诚实返回 ""（无可富化信号；硬要加噪反而误导）。
        assert build_failure_analysis_footer(
            "", LINKER_SYMPTOM_LOG, "Membase", KB_ROOT) == ""

    def test_non_signature_clang_error_still_summarized(self):
        # clang 错但非签名类（如 undeclared identifier）→ 无签名指路段，但 clang 摘要仍在。
        text = "op_kernel/foo.h:10:5: error: use of undeclared identifier 'bar'\n"
        footer = build_failure_analysis_footer("", text, "Membase", KB_ROOT)
        assert footer != ""
        assert "foo.h" in footer  # clang 摘要
        # 无签名 API → 不含签名指路段标题
        assert "API 签名修正" not in footer

    def test_programming_model_unknown_still_returns_hint(self):
        # programming_model 拿不到时（传空/未知）仍给出有效 doc 路径（选首个候选），
        # 不阻塞——只是可能不是最优变体。
        footer = build_failure_analysis_footer(
            "", CEL_BUILD_LOG, "", KB_ROOT)
        assert footer != ""
        assert "Cast" in footer


class TestClassifyBuildError:
    """阶段2 改动1: build 错误分类（C-API/C-SYM/C-TYP/C-LNK/unknown）。

    口径对齐 Regbase classify_compile_error.sh（Python 实现，不耦合 skill 脚本 §2.1）。
    多类命中按 C-API > C-TYP > C-SYM > C-LNK 优先级（签名类最可修、最值得阶段1 签名指路）。
    """

    def test_c_api_signature_mismatch(self):
        assert classify_build_error(
            "op_kernel/foo.h:10:5: error: no matching function for call to 'ReduceSum'") == "C-API"
        assert classify_build_error("error: too many arguments to function") == "C-API"
        assert classify_build_error("error: 'class X' has no member named 'FloatAttr'") == "C-API"

    def test_c_typ_type_mismatch(self):
        assert classify_build_error("error: cannot convert 'int' to 'half'") == "C-TYP"
        assert classify_build_error("static assertion failed due to requirement 'SupportType'") == "C-TYP"

    def test_c_sym_undefined_symbol(self):
        assert classify_build_error("undefined reference to 'some_symbol'") == "C-SYM"
        assert classify_build_error("error: use of undeclared identifier 'foo'") == "C-SYM"

    def test_c_sym_does_not_name_a_type(self):
        """2026-09-10 transpose: ``'TypedContinuousVector' does not name a type``
        (g++ host 编译,类型未定义)→ C-SYM(未定义符号族),而非 unknown。"""
        assert classify_build_error(
            "error: 'TypedContinuousVector' does not name a type") == "C-SYM"

    def test_c_lnk_linker(self):
        assert classify_build_error("ld returned 1 exit status") == "C-LNK"
        assert classify_build_error("undefined symbol: foo") == "C-LNK"

    def test_priority_c_api_over_sym(self):
        # 同时命中 C-API（签名）+ C-SYM（未定义）→ 返回 C-API（最可修）。
        text = "no matching function for call to 'Cast'\nundefined reference to 'x'"
        assert classify_build_error(text) == "C-API"

    def test_unknown_and_empty(self):
        assert classify_build_error("ld.lld: cannot open foo_9.o: No such file") == "unknown"
        assert classify_build_error("some random cmake progress") == "unknown"
        assert classify_build_error("") == "unknown"
        assert classify_build_error(None) == "unknown"
