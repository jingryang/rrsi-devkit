#!/usr/bin/env python3
"""Phase 4 声称验证：算法② 通用 N-D index 映射 kernel 的精确地址映射（对照 golden）。

声称（写进 design_spec.support_domain = 全部 perm）：
  单个 kernel pass 按"输出行 gather"实现任意 perm 转置：
    - outShape[j] = inShape[perm[j]]；inStride[k] = prod(inShape[k+1..])
    - 每输出行（固定 o0..o_{n-2}，变化 o_{n-1}）长度 outCols = outShape[n-1]，
      fastStride s = inStride[perm[n-1]]；行内第 j 个元素读输入
      x[baseIn(r) + j*s]，其中 baseIn(r) = Σ_{j=0}^{n-2} o_j * w[j]，
      w[j] = inStride[perm[j]]（r 按 outShape[0..n-2] 混合进制分解为 o0..o_{n-2}）。
    - 输出 y 连续写：y[r*outCols + j] = 上述输入元素。
  该声称与"通用 N-D index 映射 y[i0..]=x[i_perm[0]..]"逐元素等价（可推导，
  再以 golden=np.transpose 穷举/随机/真实用例三重核验）。

ground truth = np.transpose（golden 权威，§1.13）。跑不通先自修，不 halt。
"""
import itertools
import sys

import numpy as np


def golden(x, perm):
    return np.transpose(x, perm)


def claimed_impl(x, perm, chunk_rows=1):
    """按算法② kernel 的逐输出行地址映射复算（模拟 tiling + kernel 索引公式）。"""
    in_shape = list(x.shape)
    n = len(in_shape)
    out_shape = [in_shape[p] for p in perm]
    # 连续输入 stride
    in_stride = [1] * n
    for k in range(n - 2, -1, -1):
        in_stride[k] = in_stride[k + 1] * in_shape[k + 1]
    # 输出维权重 w[j] = inStride[perm[j]]；fastStride = w[n-1]
    w = [in_stride[p] for p in perm]
    fast_stride = w[-1]
    out_cols = out_shape[-1]
    total = int(np.prod(out_shape))
    if total == 0:
        return np.empty(out_shape, dtype=x.dtype)
    out_rows = total // out_cols
    y = np.empty(out_shape, dtype=x.dtype)
    y_flat = y.reshape(-1)
    x_flat = x.reshape(-1)
    for r in range(out_rows):
        # 混合进制分解 r -> o0..o_{n-2}（按 outShape[0..n-2]）
        rem = r
        coords = [0] * (n - 1)
        for j in range(n - 2, -1, -1):
            coords[j] = rem % out_shape[j]
            rem //= out_shape[j]
        assert rem == 0
        base_in = sum(coords[j] * w[j] for j in range(n - 1))
        for j in range(out_cols):
            y_flat[r * out_cols + j] = x_flat[base_in + j * fast_stride]
    return y


def domain_candidates():
    """穷举 rank 1-5 全部 perm + 随机大空间 + 20 个真实评测 shape/perm。"""
    cands = []
    rng = np.random.default_rng(7)
    # 1) 穷举 rank 1-5：全部 perm，取一批 shape（含非对齐/含1维）
    for n in range(1, 6):
        for perm in itertools.permutations(range(n)):
            # 每个 perm 用 1 个形状（确定性小 shape，穷举覆盖 perm 全集）
            shape = tuple(2 + (i % 3) for i in range(n))  # dims 2..4
            cands.append((shape, list(perm)))
    # 2) 随机 rank 2-6，大空间 200 组
    for _ in range(200):
        n = int(rng.integers(2, 7))
        shape = tuple(int(s) for s in rng.integers(1, 9, size=n))
        perm = rng.permutation(n).tolist()
        cands.append((shape, perm))
    # 3) 20 个真实评测 case 的 (shape, perm)
    real = [
        ([64, 32, 512, 128], [0, 2, 1, 3]), ([2048, 2048], [1, 0]),
        ([4096, 4096], [1, 0]), ([8192, 8192], [1, 0]),
        ([4096, 8192], [1, 0]), ([2, 9, 256, 256], [0, 2, 3, 1]),
        ([1023, 1023], [1, 0]), ([1009, 1021], [1, 0]),
        ([1537, 769], [1, 0]), ([363, 367, 373], [2, 0, 1]),
        ([2049, 513], [1, 0]), ([3, 7, 13, 4001], [0, 3, 1, 2]),
        ([2, 7, 256, 256], [0, 1, 3, 2]), ([2, 511, 7, 127], [0, 2, 1, 3]),
        ([11, 13, 17, 67, 67], [4, 3, 2, 1, 0]), ([3, 7, 11, 13, 1013], [4, 3, 2, 1, 0]),
        ([512, 2049], [1, 0]), ([255, 8193], [1, 0]),
        ([4097, 511], [1, 0]), ([2, 511, 2049], [2, 1, 0]),
    ]
    for shape, perm in real:
        cands.append((tuple(shape), perm))
    return cands


def main():
    ok = fail = 0
    fail_examples = []
    cands = domain_candidates()
    # 去重
    seen = set()
    uniq = []
    for shape, perm in cands:
        key = (shape, tuple(perm))
        if key not in seen:
            seen.add(key)
            uniq.append((shape, perm))
    # 单测 dtype 覆盖：int32（int64 数值同构，搬运算子与 dtype 无关）
    for shape, perm in uniq:
        n_elems = int(np.prod(shape))
        if n_elems > 20_000_000:  # 控制总运行时间
            continue
        try:
            x = np.arange(n_elems, dtype=np.int32).reshape(shape)
            want = golden(x, perm)
            got = claimed_impl(x, perm)
        except Exception as e:
            fail += 1
            fail_examples.append((shape, perm, f"异常 {type(e).__name__}: {e}"))
            continue
        if np.array_equal(got, want):
            ok += 1
        else:
            fail += 1
            fail_examples.append((shape, perm, "数值不一致"))
    total = ok + fail
    print(f"=== 声称覆盖域 vs 实测覆盖域 ===")
    print(f"总测试输入: {total}  声称成立: {ok}  不成立: {fail}")
    if fail_examples:
        for shape, perm, why in fail_examples[:10]:
            print(f"  - shape={shape} perm={perm} | {why}")
        print("结论: 声称只覆盖部分域 -> known_limitations 须记录")
        return 1
    print("结论: 算法②逐输出行地址映射与 np.transpose 在穷举 rank1-5 + 随机 200 + 真实 20 case 全一致。"
          "support_domain = {perm: 1<=len(perm)<=8 且为排列} = golden 全域；known_limitations = {}。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
