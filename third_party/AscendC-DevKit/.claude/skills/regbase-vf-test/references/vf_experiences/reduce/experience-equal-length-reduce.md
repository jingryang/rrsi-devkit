# 等长段向量规约（对齐行距 + 折叠序位级锁定）

## 适用判据

多个等长段向量累加进持久 acc2：`acc2[ow] += Σ_s ws[s*outWAlign + ow]`（每批/每行调一次，跨批持久）。

## 关键实现要点

1. **VL 块外层、段内层**：`for j(出块){ segReg=0; for s(段){ LoadAlign(wReg, ws+s*outWAlign+j*VL); Add(segReg,...) } Load(acc2Reg)+Add+Store }`——segReg 在寄存器域完成段累加，最后一次性并入 acc2（与 pseudocode 折叠序一致）。
2. **行距选型 outWAlign（非 outW）**：outWAlign 为 8 倍数 → 段起点 `s*outWAlign*4B` 天然 32B 对齐，LoadAlign 全程安全；若误用紧密 outW 行距，段起点非对齐必 VEC_ERROR。紧密→对齐 relayout 归 buffer-kernel 层。
3. **浮点折叠序位级锁定**：`acc2_new = acc2 + (((0+w0)+w1)+…)`（左折叠、s 升序）；golden 必须同序（fp32 不结合，`acc2+seg` 与 `((acc2+w0)+w1)` 可差 1 ulp）。
4. **尾块 mask 只挂 Store**：`sregOut = outW - j*VL`（每 j 迭代重置，UpdateMask 自动递减）；Add 用 maskAllF（垃圾 lane 只在寄存器内，Store masked 掉无害）。
5. **LoadAlign 过读余量**：末块读 `[j·VL, j·VL+64)` 可越出 outWAlign（如 outW=103→读至 128 > 104），UB 分配按 `len+128` 元素留余量（PAD_ELEMS=128）。
6. **跨批持久验证**：tiling 加 batchCnt 字段，kernel 入口 `__aicore__` 层循环 batchCnt 次调 VF（同一 UB acc2）——模拟集成侧批循环契约；batchCnt=2 case 验证 rmw 持久性位级正确。

## 坑位与对策

| 现象 | 根因 | 对策 |
|------|------|------|
| `import SingleOperatorLaunch` 失败（目录存在、find_spec=None） | sys.path 误加**包目录本身** | 注入 skill 根（父目录） |
| sibling 脚本 `dev.devices` 属性不存在 | DeviceInfo 实际 API 是方法 | 直接 `dev.get_device_health(d)` 遍历 |
| （预防）段起点非对齐 VEC_ERROR | 按字面紧密行距实现 | 按 ub_layout 权威取 outWAlign 行距 |

## 可复用模式（最小骨架）

```cpp
AscendC::Reg::MaskReg maskAllF = AscendC::Reg::CreateMask<float, MaskPattern::ALL>();
for (uint16_t j = 0; j < outBlocks; ++j) {          // outBlocks = ceil(outW / VL)
    AscendC::Reg::Duplicate(segReg, 0.0f);          // 每块重置（非循环不变量）
    for (uint16_t s = 0; s < segBlkU16; ++s) {
        AscendC::Reg::LoadAlign(wReg, wsAddr + s * outWAlign + j * VL);  // 32B 对齐段起点
        AscendC::Reg::Add(segReg, segReg, wReg, maskAllF);
    }
    AscendC::Reg::LoadAlign(acc2Reg, acc2Addr + j * VL);
    AscendC::Reg::Add(acc2Reg, acc2Reg, segReg, maskAllF);
    uint32_t sregOut = outW - j * VL;               // 每次迭代重置
    auto outMask = UpdateMask<float, RegTensor<float>::trait>(sregOut);
    AscendC::Reg::StoreAlign(acc2Addr + j * VL, acc2Reg, outMask);
}
```

## 横切标签

`mask-tail`、`multi-dtype`。

## 实证来源

- `adaptive_avg_pool_3d` `merge_partial_sum`（10/10 max_diff=0.0，pad 哨兵 100% 存活）
