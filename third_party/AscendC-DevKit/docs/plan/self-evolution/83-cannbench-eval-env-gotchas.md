# cannbench_eval 环境陷阱 —— cann_bench_utils `_C` 编不出 / BISHENG link 缺 `/lib64/libc.so.6`

> **排错必读**：cannbench_eval（性能打分）阶段报 `cann_bench_utils unreachable` /
> `ImportError: cannot import name '_C' ... circular import` 时，**先读本节**，别去 debug
> "循环导入"——那是**次生假象**，真障碍在系统链接环境。本文件是 L4 补充的运维/排错参考
> （对齐 `docs/plan/opencode-sdk-backend/03-headless-env-gotchas.md` 惯例），随新发现追加。

---

## 一、症状与失败签名

self_evolve_op / cannbench_eval 阶段（**仅性能打分**，精度已通过）在 run.log 里出现：

```
[WARN] CannbenchScorer: cann_bench_utils unreachable; running eval_prepare (2 steps): ...
[WARN] CannbenchScorer: eval_prepare step 'cann_bench_utils_build' exited 1: ...
        subprocess.CalledProcessError: Command '['cmake','--build',...,'--parallel','192']'
        returned non-zero exit status 2.
[WARN] CannbenchScorer: eval_prepare step 'cann_bench_utils_install' exited 1:
        cann_bench_utils-*.whl is not a valid wheel filename.
[WARN] → infra: cann-bench eval 前置环境缺失 ... 预检 stderr:
        from . import _C
        ImportError: cannot import name '_C' from partially initialized module
        'cann_bench_utils' (most likely due to a circular import)
○ cannbench_eval skipped
```

**关键**：`circular import` 是 Python 对"`_C` 根本不存在"的误报——`from . import _C` 在
`__init__.py` 第一行就失败，Python 把"import 到一半失败"包装成 circular import。真因是
`_C.so` **从未编出来**（`cmake --build` exit 2），而 `--parallel 192` 把底层链接错误淹没了。

---

## 二、真根因（经手动串行 build 复现，钉到最底层）

串行 build（`cmake --build build --parallel 1`）后底层真错误浮出：

```
ld.lld: error: cannot open /lib64/libc.so.6: No such file or directory
cceld: Linker ReturnCode: 1
bisheng: error: linker command failed with exit code 1
```

根因链（自下而上）：

| 层 | 事实 |
|---|---|
| 表象 | `ImportError: cannot import name '_C' (circular import)` |
| 中层 | `_C.so` 从未编出（`cmake --build` exit 2，build/ 无 `.so`、dist/ 无 wheel） |
| **真根因** | BISHENG 链接器 `ld.lld`（`cceld`）找不到 **`/lib64/libc.so.6`** |
| 系统事实 | 本机 `/lib64` **目录整个不存在**；真实 libc 在 `/usr/lib64/libc.so.6`（`/lib → usr/lib` 软链正常，唯独缺 `/lib64`） |

即：**特定机器的系统库路径缺陷**（标准 Ubuntu 22.04 aarch64 该有 `/lib64` 或其软链，本机缺）
+ BISHENG lld 默认在 `/lib64` 搜 libc。**不是 CANN 环境问题、不是框架 bug、也不是 cann_bench_utils
的 build.sh bug。** 在该机稳定复现，影响所有在此机跑 "BISHENG 直接 link device object 成 `.so`" 的人。

### 排除的错误定性（都已复现证伪）
- ✗ "循环导入"——是次生假象，见上。
- ✗ "site-packages `cann_bench` 污染"——那是**另一算子/另一批次**的结论，本例 `_C` 是真没编出。
- ✗ "框架 `_ensure_eval_prepare` build 子进程没注入 CANN 环境"——实测：正确
  `source cann-9.1.0-beta.3/set_env.sh`（`ASCEND_HOME_PATH` 正确、`ccec` 在 PATH）后 build
  **仍失败**，同一个 `/lib64/libc.so.6` 错误。环境齐全照样挂 → 障碍不在环境注入。

---

## 三、为什么 precision_debug / 标准算子 deploy 不受影响（很久没人察觉的原因）

同一批跑里 precision_debug 上板测精度（20/20 通过）、deploy 编译算子（smoke passed）都成功，
**唯独 cannbench_eval 挂**。差异有两层，任一层都足以让它们绕过 `/lib64/libc.so.6`：

1. **precision_debug 根本不用 cann_bench_utils**。后者是 cannbench_eval 的**性能反作弊预热工具**
   （`cann_bench_warmup` 拉频 / `cann_bench_cache_clean` 刷 L2），只服务性能测量的公平性；精度调试
   与它正交（框架 `debug_service.py`/`runner.py` 零引用）。

2. **即便都编 `_C SHARED`，两条 link 路本质不同**（更深一层）：

   | | 标准算子仓 `_C`（deploy / precision，成功） | cann_bench_utils `_C`（失败） |
   |---|---|---|
   | `_C SHARED` 里的 objects | `extension.cpp` + host plugin（纯 host C++） | `extension.cpp` + **BISHENG `-xasc` 编的 kernel object** + plugin |
   | device kernel 归属 | 由 `npu_op_kernel_library` 单独编，走 CANN 内部工具链打进 opp/run 包 | **直接塞进同一个 `_C`** |
   | link 用的链接器 | 系统 `g++`/`ld`（`_C` 纯 host） | **BISHENG `cceld`/`ld.lld`**（因含 device object） |
   | 撞 `/lib64/libc.so.6`？ | 否 | **是** |

   标准算子仓做了 **device kernel 与 host `_C` 分离**；cann_bench_utils 把 kernel object 塞进 `_C`，
   导致 link 必须用 BISHENG lld，才撞上系统 libc 路径缺失。

**一句话**：`/lib64/libc.so.6` 缺失只影响"**BISHENG lld 直接 link device object 成 `.so`**"这一种场景，
全流程里只有 cann_bench_utils 走这条路，所以只有性能打分挂，精度/编译全不受影响。

---

## 四、规避方案

### 方案 ①（推荐，系统级，一劳永逸）—— 补 `/lib64` 兼容路径
```bash
sudo mkdir -p /lib64
sudo ln -sfn /usr/lib64/libc.so.6 /lib64/libc.so.6
# 若后续仍报缺其它 /lib64/*，可整体软链：sudo ln -sfn /usr/lib64 /lib64
```
让**所有** BISHENG `-xasc` 直编 kernel 的场景都受益，不止 cann_bench_utils。需 root。

### 方案 ②（不碰系统，指定 lld 搜索路径）
```bash
export LDFLAGS="-L/usr/lib64"   # 或给 cceld 传 --sysroot=/
cd <op>/src/cann_bench_utils && bash build.sh && \
  pip install dist/cann_bench_utils-*.whl --force-reinstall --no-deps
```
比 ① 脆——`LDFLAGS` 是否透传到 BISHENG object link 取决于其 CMakeLists，需实测。

### 方案 ③（框架诊断增强，已落地）
`verify-env` 增加 BISHENG link 前置自检（`/lib64/libc.so.6` 可达性），在**加载期**（§1.3）明确
报出真障碍，而非等到 cannbench_eval 运行期以"circular import"假象暴露（§1.11 忠实信号）。
搭环境时 `ascendc-devkit verify-env` 即可提前发现。

---

## 五、影响与归属定性

- **不阻塞精度**：cannbench_eval 挂只丢**性能分**，精度全流程（design→codegen→precision_debug→finalize）
  不受影响。b3d2c7 即在此障碍下仍成功走通到 finalize（20/20 精度通过、已 commit），只是没拿到性能分。
- **框架行为正确**：框架已 fail-loud（给出确切预装命令、落 WARN、skip 干净），未静默、未空烧、未误报
  （符合 §external-infra「外部/系统障碍时框架自身不误报、留可诊断信号」）。方案 ③ 进一步让信号更忠实。
- **归属**：系统环境缺陷（`/lib64` 缺），非 DevKit / 非外部算子仓的代码 bug。用方案 ① 一次性解掉即可。
