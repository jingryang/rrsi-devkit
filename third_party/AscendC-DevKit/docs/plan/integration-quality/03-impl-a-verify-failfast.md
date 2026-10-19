# 03-impl-a: verify stage fail-fast + NPURunner 架构归位

> 层级：**L4 / 实施方案**。回答「改哪个文件、什么顺序、怎么验证」。
> 对应 `01-problems.md` P1 全部子项 + `02-analysis.md` 选型 B。

---

## 概览

| 文件 | 改动范围 | 工作量 |
|------|---------|--------|
| `src/ascendc_devkit/adapters/npu/runner.py` | 移除 stub 逻辑 + fix NPU API + tempfile | ★★★★ |
| `src/ascendc_devkit/orchestration/stages/verify.py` | PrecisionGate 接盘 stub + preflight_npu | ★★★ |
| `src/ascendc_devkit/orchestration/stages/perf.py` | PerfGate 接盘 stub | ★★ |
| `src/ascendc_devkit/application/dispatcher.py` | preflight 扩展 NPU | ★★ |
| `tests/ut/adapters/test_adapters.py` | 更新测试 | ★ |
| `tests/ut/orchestration/test_stages.py` | 更新测试 | ★ |

---

## 步骤 1：NPURunner 变纯执行器

**文件**：`src/ascendc_devkit/adapters/npu/runner.py`

### 1.1 移除 `enable_stubbed` 构造参数

```python
# 改前 (line 32-37)
def __init__(self, chip_version: str = "ascend910b", enable_stubbed: bool = False):
    self._chip_version = chip_version
    self._enable_stubbed = enable_stubbed
    self._torch_npu_available = False
    self._device_count = 0
    self._check_environment()

# 改后
def __init__(self, chip_version: str = "ascend910b"):
    self._chip_version = chip_version
    self._torch_npu_available = False
    self._device_count = 0
    self._check_environment()
```

### 1.2 `_check_environment()` 增加 smoke test

`import torch_npu` 成功后增加试调用验证 NPU 真正可用——参考 `test_npu_rotary_position_embedding_AB_mode_Gen.py` 的 pattern：

```python
# 改前 (line 52-62)
try:
    import torch_npu
    info["torch_npu_available"] = True
    self._torch_npu_available = True
    try:
        self._device_count = torch_npu.npu.device_count()
        info["device_count"] = self._device_count
    except Exception:
        pass
except ImportError:
    pass

# 改后
try:
    import torch_npu
    # Smoke test: import 成功不代表 NPU 真正可用（torch CPU 版 + torch_npu 兼容断裂）
    torch.zeros(1).npu()  # torch_npu monkey-patches .npu() onto Tensor
    info["torch_npu_available"] = True
    self._torch_npu_available = True
    try:
        self._device_count = torch_npu.npu.device_count()
        info["device_count"] = self._device_count
    except Exception:
        pass
except (ImportError, RuntimeError, AttributeError):
    pass
```

### 1.3 `execute()` 移除 stub fallback 分支

适配器层只执行或抛异常，stub 决策上移到调用方。

```python
# 改前 (line 86-97) — import 失败时的 fallback
if not self._torch_npu_available:
    if not self._enable_stubbed:
        raise EnvironmentNotAvailableError(...)
    Logger.warn(...)
    return self._stub_execute(operator)

# 改后
if not self._torch_npu_available:
    raise EnvironmentNotAvailableError(
        stage_name="npu_runner",
        missing="NPU runtime (torch_npu)",
        help_hint="Install torch_npu or verify your torch/torch_npu versions are compatible",
    )
```

```python
# 改前 (line 146-150) — catch-all 的 fallback
except Exception as e:
    if not self._enable_stubbed:
        raise  # fail-fast: real execution failed and stub mode is not allowed
    Logger.warn(f"NPU execution failed: {e}, falling back to stub")
    return self._stub_execute(operator)

# 改后
except Exception as e:
    raise  # 适配器不决策策略，异常直接向上传播给 gate/stage
```

### 1.4 `execute()` 改用 tempfile 执行 harness

```python
# 改前 (line 101-112)
harness = self._build_test_harness(operator, test_cases, npu_id, golden_path)
try:
    result = subprocess.run(
        [sys.executable, "-c", harness],      # ← -c 内联，大脚本脆弱
        capture_output=True, text=True, timeout=120,
        env={**os.environ, ...},
    )

# 改后
import tempfile
harness = self._build_test_harness(operator, test_cases, npu_id, golden_path)
try:
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.py', delete=False, prefix='npu_harness_'
    ) as f:
        f.write(harness)
        harness_path = f.name
    try:
        result = subprocess.run(
            [sys.executable, harness_path],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "ASCEND_NPU_ID": str(npu_id),
                 "CHIP_VERSION": self._chip_version},
        )
        ...
    finally:
        os.unlink(harness_path)
```

### 1.5 `_build_test_harness()` 修正 NPU API 用法

参考 `test_npu_rotary_position_embedding_AB_mode_Gen.py:428-430`：

```python
# 改前 (line 242-245) — 错误用法
"if torch_available:",
"    warmup = torch.randn(16, device='npu')",  # ❌ CPU torch 不认识 'npu'
"    del warmup",
"    torch.npu.synchronize()",                  # ❌ torch.npu 不存在

# 改后 — 正确用法
"if torch_available:",
"    warmup = torch.zeros(1).npu()",            # ✅ torch_npu monkey-patch
"    del warmup",
"    torch_npu.npu.synchronize()",             # ✅ torch_npu 命名空间
```

### 1.6 删除 `_stub_execute()` 方法

整个方法（line 294-307）删除。stub 结果由各 gate 自产自销。

---

## 步骤 2：PrecisionGate 接盘 stub 决策

**文件**：`src/ascendc_devkit/orchestration/stages/verify.py`

### 2.1 PrecisionGate.evaluate() 增加 try/except + stub

```python
# 改前 (line 110-124)
runner = NPURunner(chip_version=chip_version, enable_stubbed=enable_stubbed)
result = runner.execute(op_spec, test_cases, npu_id, golden_path=golden_path)
passed = result.get("passed", False)
return GateResult(...)

# 改后
runner = NPURunner(chip_version=chip_version)
try:
    result = runner.execute(op_spec, test_cases, npu_id, golden_path=golden_path)
except Exception as e:
    if not enable_stubbed:
        raise  # stub 不允许 → 向上传播
    result = self._stub_result(op_spec.name if op_spec else "unknown")

passed = result.get("passed", False)
return GateResult(...)
```

### 2.2 新增 `_stub_result()` 类方法

```python
@staticmethod
def _stub_result(op_name: str) -> dict:
    Logger.warn(
        f"NPU execution STUBBED for '{op_name}' — "
        f"install torch_npu to enable real execution"
    )
    return {
        "passed": False,        # ← 不假阳性
        "actual_ms": 1.5,
        "max_diff": 0.0,
        "per_shape": {"1024": 1.5},
        "baseline_ms": 0.0,
        "bottleneck": "stubbed",
        "stubbed": True,
    }
```

### 2.3 VerifyStage：preflight_npu_diagnostic()

`_check_npu_available()` 保持不变（用于 `actions()` 中的 stub 决策）。
新增 `preflight_npu_diagnostic()` 供 dispatcher 启动时调用：

```python
def preflight_npu_diagnostic(self) -> tuple[bool, str]:
    """Startup probe for NPU runtime (used by dispatcher preflight).
    
    Mirrors VerifyStage._check_npu_available() but returns
    (available, hint) tuple so the dispatcher never imports L6 adapters.
    """
    try:
        from ascendc_devkit.adapters.npu.runner import NPURunner
        npu = NPURunner()
        return npu._torch_npu_available, (
            "torch_npu is available and functional"
            if npu._torch_npu_available
            else "torch_npu is NOT available — install torch_npu or pass --enable-stubbed to allow stub fallback"
        )
    except Exception as e:
        return False, f"NPU probe failed: {e}"
```

### 2.4 VerifyStage.actions() 调整 NPU 检查逻辑

`_check_npu_available()` 本身不需要改（仍然只做 `import torch_npu`），因为它现在配合 `enable_stubbed` 做决策就够了。NPURunner.__init__ 调用时的 smoke test 是第二道防线。

---

## 步骤 3：PerfStage 的 PrecisionPassedGate 同步接盘

**文件**：`src/ascendc_devkit/orchestration/stages/perf.py`

### 3.1 PrecisionPassedGate.evaluate() 修改

```python
# 改前 (line 92-98)
enable_stubbed = evidence.get("enable_stubbed", False)
runner = NPURunner(chip_version=chip_version, enable_stubbed=enable_stubbed)
try:
    result = runner.execute(op_spec, test_cases, npu_id)
except Exception as e:
    Logger.warn(f"NPURunner failed: {e}, using stub")
    result = runner._stub_execute(op_spec)

# 改后
enable_stubbed = evidence.get("enable_stubbed", False)
runner = NPURunner(chip_version=chip_version)
try:
    result = runner.execute(op_spec, test_cases, npu_id)
except Exception as e:
    if not enable_stubbed:
        raise
    Logger.warn(f"NPURunner failed: {e}, using stub")
    result = _stub_result(op_spec.name if op_spec else "unknown")
```

### 3.2 新增模块级 `_stub_result()` 辅助函数

```python
def _stub_result(op_name: str) -> dict:
    return {
        "passed": False,
        "actual_ms": 1.5,
        "max_diff": 0.0,
        "per_shape": {"1024": 1.5},
        "baseline_ms": 0.0,
        "bottleneck": "stubbed",
        "stubbed": True,
    }
```

---

## 步骤 4：dispatcher preflight 扩展 NPU 检查

**文件**：`src/ascendc_devkit/application/dispatcher.py`

### 4.1 `_preflight_toolchain()` 扩展为 `_preflight_runtime()`

```python
# 改前 (line 251-277)
def _preflight_toolchain(state: State, workflow) -> int | None:
    has_verify = any(s.name == "verify" for s in workflow.stages)
    if not has_verify or state.enable_stubbed:
        return None
    verify_stage = next(s for s in workflow.stages if s.name == "verify")
    probe = getattr(verify_stage, "preflight_diagnostic", None)
    if probe is None:
        return None
    available, hint = probe()
    if available:
        return None
    Logger.error(...)
    return EX_CONFIG

# 改后 — 扩展为同时检查 CANN + NPU
def _preflight_runtime(state: State, workflow) -> int | None:
    """Fail fast when verify-bearing workflow lacks CANN or NPU runtime.

    Checks:
      1. CANN toolchain (ccec compiler) — existing check
      2. NPU runtime (torch_npu) — new check

    Both are required for real verify execution. When --enable-stubbed is set,
    only CANN is checked (stub compilation still needs the toolchain).
    """
    has_verify = any(s.name == "verify" for s in workflow.stages)
    if not has_verify:
        return None
    
    verify_stage = next(s for s in workflow.stages if s.name == "verify")
    
    # Check 1: CANN toolchain
    if not state.enable_stubbed:
        cann_probe = getattr(verify_stage, "preflight_diagnostic", None)
        if cann_probe:
            available, hint = cann_probe()
            if not available:
                Logger.error("工具链缺失，运行将中止（不会进入任何 Agent 阶段）：")
                Logger.error(f"  {hint}")
                return EX_CONFIG
    
    # Check 2: NPU runtime (skip when stubbed)
    if not state.enable_stubbed:
        npu_probe = getattr(verify_stage, "preflight_npu_diagnostic", None)
        if npu_probe:
            available, hint = npu_probe()
            if not available:
                Logger.error("NPU 运行时缺失，运行将中止（不会进入任何 Agent 阶段）：")
                Logger.error(f"  {hint}")
                return EX_CONFIG
    
    return None
```

### 4.2 调用点改名

```python
# 改前 (line 427)
toolchain_code = _preflight_toolchain(state, workflow)

# 改后
runtime_code = _preflight_runtime(state, workflow)
if runtime_code is not None:
    return runtime_code
```

---

## 验证方式

### 修改后手动验证

```bash
# 1. 环境正常时，verify 能真实执行
bash scripts/e2e_run.sh run

# 2. NPU 不可用时（卸载 torch_npu 或用 CPU torch），preflight 立即中止
pip uninstall -y torch_npu
ascendc-devkit run --op-dir /path/to/op --golden tests/fixtures/rope_golden.py
# 预期: preflight 阶段报 "NPU 运行时缺失", 退出码非 0, 不进入 agent stage

# 3. NPU 不可用 + --enable-stubbed，正常执行到 verify 但 precision gate 返回 passed=False, stubbed=True
ascendc-devkit run --op-dir /path/to/op --golden tests/fixtures/rope_golden.py --enable-stubbed

# 4. verify 阶段真实 NPU 执行失败（非 stub），异常直接上抛
```

### 单元测试预期失败点

| 测试 | 旧行为 | 新行为 |
|------|--------|--------|
| `test_npu_runner_no_torch_npu` | stub fallback + passed=True | `EnvironmentNotAvailableError` |
| `test_npu_runner_exec_exception` | catch-all → stub | re-raise 原始异常 |
| `test_verify_preflight_npu` | 无检查（通过 CANN 后直接进 agent） | preflight 检查 NPU → 缺失时中止 |

---

## 变更顺序（按依赖关系）

1. **步骤 1**（NPURunner 纯执行器）→ 底层变更，不依赖其他步骤
2. **步骤 2**（PrecisionGate 接盘）→ 依赖步骤 1（NPURunner 接口变化）
3. **步骤 3**（PerfGate 接盘）→ 依赖步骤 1
4. **步骤 4**（dispatcher preflight）→ 依赖步骤 2（preflight_npu_diagnostic）

**回滚策略**：每个步骤独立 commit，步骤 1-3 完成后功能等价（接口契约不变，仅职责归位），步骤 4 是纯新增功能。
