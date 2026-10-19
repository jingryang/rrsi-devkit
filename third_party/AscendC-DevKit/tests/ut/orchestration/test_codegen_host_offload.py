"""UT: codegen plugin host-offload 契约门（维10③ 确定性机械扫描）。

判据（近零误判）：op_plugin/*.cpp 里出现 host 往返标记 ``.cpu()`` 或 ``kCPU``
（即 ``.to(torch::kCPU)`` / ``.to(at::kCPU)`` / ``.cpu()``）→ plugin_host_offload。
维10 已把 plugin 契约收窄到「接口适配 + 调 aclnn kernel」——标量控制输入走 attr、
shape 用 ``.sizes()``、空检查用 ``.numel()``，``*_npu`` 函数里没有合法 ``.cpu()``/``kCPU``。
故该信号在本项目生成插件语境下近零误判，可作硬门（fail → 定向 retry codegen）。

注释（``//`` / ``/* */``）先剥除再匹配，避免注释里提及 ``.cpu()`` 造成假阳性。
"""

from __future__ import annotations

from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.codegen import CodegenStage


def _state_with_plugin(source: str) -> tuple[CodegenStage, State, dict]:
    return (CodegenStage(), State(mode="new"),
            {"op_plugin/op_plugin.cpp": source})


class TestCodegenPluginHostOffload:
    def test_to_kcpu_flagged(self):
        """`.to(torch::kCPU)` 往返 → 命中 plugin_host_offload。"""
        stage, state, artifacts = _state_with_plugin("""
static std::vector<torch::Tensor> op_npu(const at::Tensor& x) {
    auto cpu_x = x.to(torch::kCPU).contiguous();
    auto out = torch::empty_like(x);
    out.copy_(cpu_x);
    return {out};
}
""")
        err = stage._plugin_host_offload_error(state, artifacts)
        assert err is not None, "host 往返应命中"
        assert err.details["reason"] == "plugin_host_offload"
        assert "op_plugin.cpp" in err.details.get("plugin_file", "")

    def test_cpu_method_flagged(self):
        """`.cpu()` 方法调用 → 命中。"""
        stage, state, artifacts = _state_with_plugin("""
static torch::Tensor op_npu(const at::Tensor& x) {
    auto v = x.cpu();
    return v;
}
""")
        err = stage._plugin_host_offload_error(state, artifacts)
        assert err is not None
        assert err.details["reason"] == "plugin_host_offload"

    def test_legitimate_plugin_clean(self):
        """合法 plugin（仅 contiguous + ACLNN_CMD，无 host 往返）→ 不命中。"""
        stage, state, artifacts = _state_with_plugin("""
static torch::Tensor op_npu(const at::Tensor& x) {
    auto xc = x.contiguous();
    auto y = torch::empty_like(xc);
    ACLNN_CMD(aclnnOp, xc, y);
    return y;
}
""")
        err = stage._plugin_host_offload_error(state, artifacts)
        assert err is None, "合法 plugin 不应命中"

    def test_zero_init_not_flagged(self):
        """设备侧 zero_() 初始化（缺 optional 时置零）不含 .cpu()/kCPU → 不命中。"""
        stage, state, artifacts = _state_with_plugin("""
static torch::Tensor op_npu(const at::Tensor& x) {
    auto y = torch::empty({x.size(0)}, x.options());
    y.zero_();
    return y;
}
""")
        err = stage._plugin_host_offload_error(state, artifacts)
        assert err is None

    def test_comment_mention_stripped(self):
        """注释里提及 .cpu() 不被当成命中（先剥注释再匹配）。"""
        stage, state, artifacts = _state_with_plugin("""
// NOTE: do NOT call .cpu() here; everything stays on device.
static torch::Tensor op_npu(const at::Tensor& x) {
    /* block comment: .to(torch::kCPU) is forbidden */
    auto y = torch::empty_like(x);
    return y;
}
""")
        err = stage._plugin_host_offload_error(state, artifacts)
        assert err is None, "注释里的 .cpu()/kCPU 不应命中"

    def test_no_plugin_sources_clean(self):
        """无 plugin 源 → 不命中、不崩。"""
        stage = CodegenStage()
        state = State(mode="new")
        err = stage._plugin_host_offload_error(state, {})
        assert err is None

    def test_message_has_dynamic_output_legal_alternative(self):
        """红线反馈不指向死路：文案须含动态输出类的合法替代(aclrtMemcpy D2H 读回 count)。"""
        stage, state, artifacts = _state_with_plugin("""
static std::vector<torch::Tensor> op_npu(const at::Tensor& x) {
    auto xc = x.contiguous();
    auto yUp = torch::empty({cap}, xc.options());
    ACLNN_CMD(aclnnOp, xc, yUp);
    auto count = yUp.to(torch::kCPU);   // 数据相关输出长度回读,却用 .to(kCPU)
    return {yUp.narrow(0, 0, count.item<int64_t>())};
}
""")
        err = stage._plugin_host_offload_error(state, artifacts)
        assert err is not None, "host 往返应命中"
        msg = err.message
        # 两类处置都应给出:①真 host 算值→迁回 kernel;②数据相关输出长度→aclrtMemcpy(D2H)
        assert "迁回 kernel/tiling" in msg, "应保留原有死路外的①类指引(真 host 算值)"
        assert "aclrtMemcpy(D2H)" in msg, "动态输出读回应给合法替代,而非死路"
        assert "aclrtSynchronizeStream" in msg
        assert "勿用 `.to(kCPU)`" in msg
