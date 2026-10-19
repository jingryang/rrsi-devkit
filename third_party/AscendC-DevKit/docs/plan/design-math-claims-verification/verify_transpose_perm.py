"""验证 transpose 降维数学（2026-08-09，对照 L1 design-math-claims-verification/01-problems.md）。

结论（本脚本可复现）：
1. 单个 2D 转置(contiguous reshape+transpose) 只能表达『循环旋转』perm=[b..n-1,0..b-1]；
   rank=n 时循环旋转恰 n 个，其余 n!-n 个 perm 需通用算法。
2. 评测 8 个 CPU-fallback case 的 perm 全部非循环旋转（与 no_npu_kernel_detected 一一对应）。
3. 两种通用正确算法均已核验（对照 np.transpose）：
   算法① 任意 perm 分解为 ≤(n-1) 次两两换维（每 pass = strided 2D 转置）；
   算法② 通用 N-D index 映射（单 pass，输出 tile 直读 strided 输入）。

作为 design-math-claims/verify_simplification_claim.py 通用模板的原型。
"""
import numpy as np
from itertools import permutations

def is_cyclic_rotation(perm):
    n = len(perm)
    if list(perm)==list(range(n)): return True, 0
    for b in range(1,n):
        exp=[(b+k) if k<n-b else (k-(n-b)) for k in range(n)]
        if list(perm)==exp: return True, b
    return False, None

def permute_via_pairwise_swaps(x, perm):
    """通用算法①：任意 perm 分解为 ≤n-1 个两两换维，每个换维=一次 strided 2D 转置 pass。
    数学：perm 排序回 identity 的相邻/任意对换序列，对数组按逆序 swapaxes（协变/逆变）。"""
    n=len(perm); p=list(perm); swaps=[]
    for i in range(n):
        j=p.index(i)
        if j!=i:
            swaps.append((i,j)); p[i],p[j]=p[j],p[i]
    y=x
    for i,j in reversed(swaps):
        y=np.swapaxes(y,i,j)   # 模拟一次『换维(i,j)』的 kernel pass
    return y

def general_nd_transpose_sim(x, perm):
    """通用算法②：直接 index 映射——真正 N-D 转置 kernel 的本质（输出坐标→输入坐标）"""
    out=np.empty([x.shape[i] for i in perm],dtype=x.dtype)
    idx=np.indices(out.shape)
    src=[idx[perm.index(k)] for k in range(len(perm))]
    out[...] = x[tuple(src)]
    return out

# 确认 8 个评测 perm 的循环性 + 两种通用算法逐一核验（含真实 eval shape）
print("=== 8 个 eval CPU-fallback case：单个2D转置 vs 两种通用算法（真实 shape）===")
cases=[("1",[64,32,512,128],[0,2,1,3]),("6",[2,9,256,256],[0,2,3,1]),("12",[3,7,13,4001],[0,3,1,2]),
       ("13",[2,7,256,256],[0,1,3,2]),("14",[2,511,7,127],[0,2,1,3]),("15",[11,13,17,67,67],[4,3,2,1,0]),
       ("16",[3,7,11,13,1013],[4,3,2,1,0]),("20",[2,511,2049],[2,1,0])]
rng=np.random.default_rng(1)
allok=True
for cid,shape,perm in cases:
    x=rng.random(tuple(shape)); g=np.transpose(x,perm)
    a=permute_via_pairwise_swaps(x,perm); b=general_nd_transpose_sim(x,perm)
    cyc,_=is_cyclic_rotation(perm)
    ok1=np.array_equal(g,a); ok2=np.array_equal(g,b)
    allok &= ok1 and ok2
    print(f"  transpose_{cid} perm={perm} 循环旋转={cyc} | 算法①两两换维一致={ok1} | 算法②index映射一致={ok2}")

print()
print("=== 随机 100 组 (rank 2-6) 全量核验两种通用算法 ===")
f1=f2=0
for _ in range(100):
    n=int(rng.integers(2,7)); shape=tuple(int(s) for s in rng.integers(2,6,size=n)); perm=rng.permutation(n).tolist()
    x=rng.random(shape); g=np.transpose(x,perm)
    if not np.array_equal(g, permute_via_pairwise_swaps(x,perm)): f1+=1
    if not np.array_equal(g, general_nd_transpose_sim(x,perm)): f2+=1
print(f"  算法① 失败={f1}/100   算法② 失败={f2}/100")

print()
print("=== 设计阶段必须写清的数学契约（结论）===")
print(" 1) 单个 2D 转置(contiguous reshape+transpose) 只能表达『循环旋转』perm=[b..n-1,0..b-1]")
for n in (2,3,4,5):
    allp=list(permutations(range(n))); cyc=sum(1 for p in allp if is_cyclic_rotation(p)[0])
    print(f"    rank={n}: 循环旋转 {cyc}/{len(allp)}，其余 {(len(allp)-cyc)}/{len(allp)} 需通用算法")
print(" 2) 任意 perm 正确实现路径（均已核验）:")
print("    ① 分解为 ≤(n-1) 个两两换维，每个换维 = 一次 strided 2D 转置 pass（复用现有 kernel 思路，多 pass）")
print("    ② 通用 N-D index 映射 kernel（输出 tile 直读 strided 输入，单 pass，需更复杂 tiling）")
print()
print(f"  全部核验通过: {allok}")
