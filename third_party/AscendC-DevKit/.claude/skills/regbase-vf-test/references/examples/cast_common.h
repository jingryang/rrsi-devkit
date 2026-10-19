#ifndef _CAST_REGBASE_COMMON_H_
#define _CAST_REGBASE_COMMON_H_

// ============================================================================
// A5 Regbase Cast 公共工具集
//
// 结构（配套查询矩阵 + 场景详解 + Trait 全集见同目录 cast_index.md）：
//   §1  CastTrait 常量定义（§1.1-1.3b 窄化/扩宽/整型/同宽/直连/量化/编码）
//   §2  同宽互转（4B↔4B、2B↔2B，含 int16↔fp16、int32→int64）
//   §3  窄化（4B→2B/1B）：通用窄化输出 + 量化取整打包 + fp16→int8/uint8 直连
//   §4  扩宽（2B→4B / 1B→2B/4B）：通用扩宽输入 + 整寄存器 de-interleave + int8/uint8/int4x2→fp16 直连 + 量化解码
//   §5  拆位 / 组合（int64，A5 LoadDist/StoreDist 无 B64）
//   §6  标量专项（广播读 + 单元素写）
//
// 分类依据：按【位宽变换】组织，每个函数归属唯一——窄化函数一定在 §3，
//           扩宽函数一定在 §4，不再按方向/量化语义两套维度交叉分类。
//
// 【红线】4B→2B 窄化（fp32→fp16/bf16）用「单 ZERO Cast + StoreAlign<DIST_PACK_B32>」，
//         不要用「ZERO/ONE 双布局 Cast + Add」——后者产生每值重复两次 [v0,v0,v1,v1,...]。
// 【红线】fp32→bf16/half 的 CastTrait 必须显式 SatMode::NO_SAT 或 SAT，
//         用 UNKNOWN 会触发 static assertion failed。
// 【红线】RoundMode 在 AscendC:: 命名空间，不是 AscendC::Reg::。
// ============================================================================

#include "kernel_operator.h"

namespace CustomRegImpl {

// ============================================================================
// §1 CastTrait 常量定义
// ============================================================================

// ---- 1.1 浮点窄化（4B→2B / 4B→1B），SatMode 必须显式 ----
constexpr AscendC::Reg::CastTrait castTraitFp322Hifp8 = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::SAT,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::CAST_ROUND,
};

constexpr AscendC::Reg::CastTrait castTraitFp322Fp8 = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::SAT,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::CAST_RINT,
};

// fp32 → half/bfloat16_t（通用回转，CAST_RINT 舍入）
constexpr AscendC::Reg::CastTrait castTraitF322F16 = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::NO_SAT,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::CAST_RINT,
};

// fp32 → half（CAST_ODD 舍入，int8/fp4 打包链路中转用）
constexpr AscendC::Reg::CastTrait castTraitFp322Fp16 = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::NO_SAT,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::CAST_ODD,
};

// fp32 → bfloat16_t（量化路径：SAT 截断到 BF16 值域）
constexpr AscendC::Reg::CastTrait castTraitFp322Bf16Sat = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::SAT,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::CAST_RINT,
};

// ---- 1.2 浮点扩宽（2B→4B） ----
// half/bfloat16_t → fp32，ZERO layout（配 LoadAlign<DIST_UNPACK_B16> 逐 64 元素段）
constexpr AscendC::Reg::CastTrait castTraitF162F32 = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::UNKNOWN,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::UNKNOWN,
};

// half/bfloat16_t → fp32，ONE layout（整寄存器 128 元素 de-interleave 时配 ZERO 使用，§4.2）
constexpr AscendC::Reg::CastTrait castTraitF162F32One = {
    AscendC::Reg::RegLayout::ONE,
    AscendC::Reg::SatMode::UNKNOWN,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::UNKNOWN,
};

// ---- 1.3 整型 ↔ 浮点 ----
constexpr AscendC::Reg::CastTrait castTraitI82F16 = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::NO_SAT,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::CAST_RINT,
};

constexpr AscendC::Reg::CastTrait castTraitI322F16 = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::NO_SAT,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::CAST_RINT,
};

// 同宽转换：layout 不参与，用 UNKNOWN
constexpr AscendC::Reg::CastTrait castTraitFp322Int32 = {
    AscendC::Reg::RegLayout::UNKNOWN,
    AscendC::Reg::SatMode::NO_SAT,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::CAST_RINT,
};

constexpr AscendC::Reg::CastTrait castTraitInt322Fp32 = {
    AscendC::Reg::RegLayout::UNKNOWN,
    AscendC::Reg::SatMode::NO_SAT,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::CAST_RINT,
};

constexpr AscendC::Reg::CastTrait castTraitFp162Int8 = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::NO_SAT,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::CAST_RINT,
};

// ---- 1.4 同宽 16-bit 互转（bf16 ↔ fp16，单 layout） ----
constexpr AscendC::Reg::CastTrait castTraitBf162Fp16 = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::NO_SAT,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::CAST_RINT,
};

// fp16 → bf16（OCP 标准 TRUNC 截断；RINT 变体用上方 castTraitBf162Fp16）
// 来源：ops-nn/norm/mx_quant_cast_traits.h:23、ops-nn/quant 多文件（CAST_TRUNC）
constexpr AscendC::Reg::CastTrait castTraitFp162Bf16Trunc = {
    AscendC::Reg::RegLayout::UNKNOWN,
    AscendC::Reg::SatMode::UNKNOWN,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::CAST_TRUNC,
};

// ---- 1.3b 窄 dtype 直连（int8/uint8/int16 ↔ fp16，不经 fp32 中转） ----
// int8/uint8 → fp16：ZERO layout，配 DIST_UNPACK4_B8（向量）/ DIST_BRC_B8（标量）
// 来源：ops-nn/quant ascend_anti_quant_v2_common.h:49、quantize.h:114/118
constexpr AscendC::Reg::CastTrait castTraitI82F16Direct = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::UNKNOWN,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::UNKNOWN,
};

// uint8 → fp16 同 castTraitI82F16Direct（quantize.h:118）
constexpr AscendC::Reg::CastTrait castTraitU8ToF16 = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::UNKNOWN,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::UNKNOWN,
};

// int16 → fp16（同宽，RegLayout::UNKNOWN；RINT）
// 来源：ops-nn/quant ascend_quant.h:92、dynamic_quant:825、dequant_swiglu_quant:77
constexpr AscendC::Reg::CastTrait castTraitI162F16 = {
    AscendC::Reg::RegLayout::UNKNOWN,
    AscendC::Reg::SatMode::UNKNOWN,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::CAST_RINT,
};

// fp16 → int8（直接窄化，TRUNC 截断；RINT 变体用上方 castTraitFp162Int8）
// 来源：ops-nn/quant dequant_swiglu_quant_common.h:80（SAT+TRUNC）、dynamic_quant:828
constexpr AscendC::Reg::CastTrait castTraitFp162Int8Trunc = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::NO_SAT,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::CAST_TRUNC,
};

// fp16 → uint8（直接窄化，RINT）
// 来源：ops-nn/quant quantize.h:196
constexpr AscendC::Reg::CastTrait castTraitF162U8 = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::NO_SAT,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::CAST_RINT,
};

// int32 → int64（同宽扩到 8B；DIST_UNPACK_B32 展开后 Cast，无 RoundMode）
// 来源：ops-nn/norm sync_batch_norm_gather_stats_struct.h:46
constexpr AscendC::Reg::CastTrait castTraitI322I64 = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::UNKNOWN,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::UNKNOWN,
};

// ---- 1.5 量化格式解码（§4.3 使用） ----
// FP8_E8M0 → BF16：源类型必须写 fp8_e8m0_t（写 uint8_t 会做整数转浮点而非 E8M0 解码）
constexpr AscendC::Reg::CastTrait castTraitFp8E8m0ToBf16 = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::UNKNOWN,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::UNKNOWN,
};

// FP8 → FP32 四布局（1B→4B，256 个 fp8 散到 4 个寄存器；需 Interleave 恢复顺序）
constexpr AscendC::Reg::CastTrait castTraitFp8ToFp32Zero = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::UNKNOWN,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::UNKNOWN,
};
constexpr AscendC::Reg::CastTrait castTraitFp8ToFp32One = {
    AscendC::Reg::RegLayout::ONE,
    AscendC::Reg::SatMode::UNKNOWN,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::UNKNOWN,
};
constexpr AscendC::Reg::CastTrait castTraitFp8ToFp32Two = {
    AscendC::Reg::RegLayout::TWO,
    AscendC::Reg::SatMode::UNKNOWN,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::UNKNOWN,
};
constexpr AscendC::Reg::CastTrait castTraitFp8ToFp32Three = {
    AscendC::Reg::RegLayout::THREE,
    AscendC::Reg::SatMode::UNKNOWN,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::UNKNOWN,
};

// FP4 → BF16：配 LoadAlign<DIST_UNPACK4_B8>，源类型必须写 fp4x2_e2m1_t
constexpr AscendC::Reg::CastTrait castTraitFp4ToBf16 = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::UNKNOWN,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::UNKNOWN,
};

// ---- 1.6 量化输出编码（§3 使用：fp32→int16, int16→half, half→int4x2）----
constexpr AscendC::Reg::CastTrait castTraitFp322Int16 = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::NO_SAT,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::CAST_RINT,
};

constexpr AscendC::Reg::CastTrait castTraitInt162Half = {
    AscendC::Reg::RegLayout::UNKNOWN,
    AscendC::Reg::SatMode::NO_SAT,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::CAST_RINT,
};

constexpr AscendC::Reg::CastTrait castTraitF162I8 = {
    AscendC::Reg::RegLayout::ZERO,
    AscendC::Reg::SatMode::NO_SAT,
    AscendC::Reg::MaskMergeMode::ZEROING,
    AscendC::RoundMode::CAST_RINT,
};

// ============================================================================
// §2 同宽互转（4B↔4B、2B↔2B）
//   场景：位宽不变、仅数值语义重解释——fp32↔int32（4B 同宽）、bf16↔fp16（2B 同宽）。
//   特点：RegLayout 不参与（同宽无 layout 概念），同宽 16-bit 用单 layout 即可。
// ============================================================================

// fp32 → int32（同宽，RegLayout::UNKNOWN；CAST_RINT 舍入到最近偶数）
__simd_callee__ inline void CastFp32ToInt32(
    AscendC::Reg::RegTensor<int32_t>& dst, AscendC::Reg::RegTensor<float>& src, AscendC::Reg::MaskReg& preg)
{
    AscendC::Reg::Cast<int32_t, float, castTraitFp322Int32>(dst, src, preg);
}

// int32 → fp32（同宽）
__simd_callee__ inline void CastInt32ToFp32(
    AscendC::Reg::RegTensor<float>& dst, AscendC::Reg::RegTensor<int32_t>& src, AscendC::Reg::MaskReg& preg)
{
    AscendC::Reg::Cast<float, int32_t, castTraitInt322Fp32>(dst, src, preg);
}

// bfloat16_t → half（同宽 16-bit，单 layout，无需 Interleave）
__simd_callee__ inline void CastBf16ToFp16(
    AscendC::Reg::RegTensor<half>& dst, AscendC::Reg::RegTensor<bfloat16_t>& src, AscendC::Reg::MaskReg& preg)
{
    AscendC::Reg::Cast<half, bfloat16_t, castTraitBf162Fp16>(dst, src, preg);
}

// half → bfloat16_t（同宽 16-bit，RINT 舍入）
__simd_callee__ inline void CastFp16ToBf16(
    AscendC::Reg::RegTensor<bfloat16_t>& dst, AscendC::Reg::RegTensor<half>& src, AscendC::Reg::MaskReg& preg)
{
    AscendC::Reg::Cast<bfloat16_t, half, castTraitBf162Fp16>(dst, src, preg);
}

// half → bfloat16_t（同宽 16-bit，OCP 标准 TRUNC 截断；MX/FP8 指数提取路径用）
// 来源：ops-nn/norm mx_quant_cast_traits.h:23、ops-nn/quant swiglu_mx_quant:104
__simd_callee__ inline void CastFp16ToBf16Trunc(
    AscendC::Reg::RegTensor<bfloat16_t>& dst, AscendC::Reg::RegTensor<half>& src, AscendC::Reg::MaskReg& preg)
{
    AscendC::Reg::Cast<bfloat16_t, half, castTraitFp162Bf16Trunc>(dst, src, preg);
}

// int16 → half（同宽 16-bit；int4 量化取整中转）
// 来源：ops-nn/quant ascend_quant.h:92、dynamic_quant:825、dequant_swiglu_quant:77
__simd_callee__ inline void CastInt16ToFp16(
    AscendC::Reg::RegTensor<half>& dst, AscendC::Reg::RegTensor<int16_t>& src, AscendC::Reg::MaskReg& preg)
{
    AscendC::Reg::Cast<half, int16_t, castTraitI162F16>(dst, src, preg);
}

// half → int16（同宽 16-bit；int4 量化取整反向）
__simd_callee__ inline void CastFp16ToInt16(
    AscendC::Reg::RegTensor<int16_t>& dst, AscendC::Reg::RegTensor<half>& src, AscendC::Reg::MaskReg& preg)
{
    AscendC::Reg::Cast<int16_t, half, castTraitInt162Half>(dst, src, preg);
}

// int32 → int64（4B 同宽 → 8B；DIST_UNPACK_B32 展开到 2× 寄存器后单 Cast 扩宽）
// 来源：ops-nn/norm sync_batch_norm_gather_stats_n_not_full_load.h:202
__simd_callee__ inline void CastInt32ToInt64(
    AscendC::Reg::RegTensor<int64_t>& dst, AscendC::Reg::RegTensor<int32_t>& src, AscendC::Reg::MaskReg& preg)
{
    AscendC::Reg::Cast<int64_t, int32_t, castTraitI322I64>(dst, src, preg);
}

// ============================================================================
// §3 窄化（4B→2B / 4B→1B）
//   场景：fp32 计算域结果写回更窄 dtype——通用输出（§3.1）+ 量化取整打包（§3.2-3.4）。
//   【红线】窄化落 UB 必须用 StoreAlign<DIST_PACK_B32 / DIST_PACK4_B32> 紧凑打包，
//           禁止 ZERO/ONE 双布局 Cast + Add（产生 [v0,v0,v1,v1,...]）。
// ============================================================================

// ----------------------------------------------------------------------------
// 3.1 通用窄化输出主入口：64 个 fp32 → 64 个 T_OUT 落 UB
//
// 场景：fp32 计算域结果写回任意输出 dtype。每次处理 64 元素，与 §4.1 LoadTensorForDtypeTIn
//       对称使用；128 个目标元素调用 2 次。
//
// T_OUT 分派（红线见各分支注释）：
//   float      → StoreAlign<DIST_NORM> 直存（同宽，走本函数 float 分支）
//   half/bf16  → Cast<T_OUT,float,castTraitF322F16> + StoreAlign<DIST_PACK_B32>
//                【红线】4B→2B 窄化必须 DIST_PACK_B32 打包存储（64 fp32→64 fp16 占 128B，
//                目标寄存器 256B，PACK_B32 紧凑写前 64 个位置）；
//                【红线】禁止「Cast ZERO + Cast ONE + Add」——ZERO/ONE 各输出 32 个到
//                偶/奇槽位，Add 合并产生 [v0,v0,v1,v1,...] 每值重复两次。
//   int8_t     → Cast<half,float,Fp322Fp16> + Cast<int8,half,Fp162Int8> + StoreAlign<DIST_PACK4_B32>
//   uint8_t    → fp4/int4x2 打包：Cast(Fp322Fp16) + Pack + Cast<int4x2,half,Fp162Int8> + StoreAlign<DIST_PACK4_B32>
//   fp8_e4m3fn/fp8_e5m2 → Cast<T_OUT,float,castTraitFp322Fp8> + StoreAlign<DIST_PACK4_B32>
//   hifloat8_t → Cast<T_OUT,float,castTraitFp322Hifp8> + StoreAlign<DIST_PACK4_B32>
//
// 最易错（fp32→fp16/bf16）：
//   AscendC::Reg::RegTensor<T_OUT> xOut;
//   AscendC::Reg::Cast<T_OUT, float, castTraitF322F16>(xOut, xRegFp32, preg);
//   AscendC::Reg::StoreAlign<T_OUT, AscendC::Reg::StoreDist::DIST_PACK_B32>(dst + offset, xOut, preg);
// ----------------------------------------------------------------------------
template <typename T_OUT>
__simd_callee__ inline void StoreTensorForDtypeTOut(
    __ubuf__ T_OUT* dst, AscendC::Reg::RegTensor<float>& xRegFp32, AscendC::Reg::MaskReg& preg, uint32_t offset)
{
    if constexpr (AscendC::IsSameType<T_OUT, float>::value) {
        AscendC::Reg::StoreAlign<T_OUT, AscendC::Reg::StoreDist::DIST_NORM>(dst + offset, xRegFp32, preg);
    } else if constexpr (AscendC::IsSameType<T_OUT, bfloat16_t>::value || AscendC::IsSameType<T_OUT, half>::value) {
        AscendC::Reg::RegTensor<T_OUT> xOut;
        AscendC::Reg::Cast<T_OUT, float, castTraitF322F16>(xOut, xRegFp32, preg);
        AscendC::Reg::StoreAlign<T_OUT, AscendC::Reg::StoreDist::DIST_PACK_B32>(dst + offset, xOut, preg);
    } else if constexpr (AscendC::IsSameType<T_OUT, int8_t>::value) {
        AscendC::Reg::RegTensor<T_OUT> xOut;
        AscendC::Reg::RegTensor<half> xRegFp16;
        AscendC::Reg::Cast<half, float, castTraitFp322Fp16>(xRegFp16, xRegFp32, preg);
        AscendC::Reg::Cast<int8_t, half, castTraitFp162Int8>(xOut, xRegFp16, preg);
        AscendC::Reg::StoreAlign<T_OUT, AscendC::Reg::StoreDist::DIST_PACK4_B32>(dst + offset, xOut, preg);
    } else if constexpr (AscendC::IsSameType<T_OUT, uint8_t>::value) {
        AscendC::Reg::MaskReg mask4Int4 = AscendC::Reg::CreateMask<float, AscendC::Reg::MaskPattern::H>();
        AscendC::Reg::RegTensor<half> xRegFp16;
        AscendC::Reg::RegTensor<uint16_t> xUint16;
        AscendC::Reg::RegTensor<uint8_t> xUint8;
        AscendC::Reg::Cast<half, float, castTraitFp322Fp16>(xRegFp16, xRegFp32, preg);
        AscendC::Reg::Pack(xUint16, (AscendC::Reg::RegTensor<uint32_t>&)xRegFp16);
        AscendC::Reg::Cast<int4x2_t, half, castTraitFp162Int8>((AscendC::Reg::RegTensor<int4x2_t>&)xUint8, (AscendC::Reg::RegTensor<half>&)xUint16, preg);
        AscendC::Reg::StoreAlign<uint8_t, AscendC::Reg::StoreDist::DIST_PACK4_B32>(dst + offset / 2, xUint8, mask4Int4);
    } else if constexpr (AscendC::IsSameType<T_OUT, fp8_e4m3fn_t>::value || AscendC::IsSameType<T_OUT, fp8_e5m2_t>::value) {
        AscendC::Reg::RegTensor<T_OUT> xOut;
        AscendC::Reg::Cast<T_OUT, float, castTraitFp322Fp8>(xOut, xRegFp32, preg);
        AscendC::Reg::StoreAlign<T_OUT, AscendC::Reg::StoreDist::DIST_PACK4_B32>(dst + offset, xOut, preg);
    } else if constexpr (AscendC::IsSameType<T_OUT, hifloat8_t>::value) {
        AscendC::Reg::RegTensor<T_OUT> xOut;
        AscendC::Reg::Cast<T_OUT, float, castTraitFp322Hifp8>(xOut, xRegFp32, preg);
        AscendC::Reg::StoreAlign<T_OUT, AscendC::Reg::StoreDist::DIST_PACK4_B32>(dst + offset, xOut, preg);
    }
}

// ----------------------------------------------------------------------------
// 3.2 量化 scale 因子（DIV_FACTOR，compute scale 段使用）
// 计算 scale = absmax(y) / MAX_ABS，其中 MAX_ABS 由 T_Y 值域上限决定：
//   int8_t: 127；fp8_e4m3fn_t: 448；fp8_e5m2_t: 57344；hifloat8_t: 32768；int4b_t: 7
// 用法：scaleReg 已含 absmax(y)（Reduce<MAX>），用 VL1 mask 乘 DIV_FACTOR 得最终 scale。
// ----------------------------------------------------------------------------
template <typename T_Y>
__simd_callee__ inline void MulQuantScaleFactor(
    AscendC::Reg::RegTensor<float>& scaleReg, AscendC::Reg::MaskReg& maskRegOne)
{
    if constexpr (AscendC::IsSameType<T_Y, int8_t>::value) {
        AscendC::Reg::Muls(scaleReg, scaleReg, 1.0f / 127.0f, maskRegOne);
    } else if constexpr (AscendC::IsSameType<T_Y, fp8_e4m3fn_t>::value) {
        AscendC::Reg::Muls(scaleReg, scaleReg, 1.0f / 448.0f, maskRegOne);
    } else if constexpr (AscendC::IsSameType<T_Y, fp8_e5m2_t>::value) {
        AscendC::Reg::Muls(scaleReg, scaleReg, 1.0f / 57344.0f, maskRegOne);
    } else if constexpr (AscendC::IsSameType<T_Y, hifloat8_t>::value) {
        AscendC::Reg::Muls(scaleReg, scaleReg, 1.0f / 32768.0f, maskRegOne);
    } else if constexpr (AscendC::IsSameType<T_Y, int4b_t>::value) {
        AscendC::Reg::Muls(scaleReg, scaleReg, 1.0f / 7.0f, maskRegOne);
    }
}

// ----------------------------------------------------------------------------
// 3.3 fp32 → int8 量化输出（ComputeMutlY int8 分支）
// 链路：Truncate(CAST_RINT) 就近取整 → Cast<half,float,Fp322Fp16> → Cast<int8,half,Fp162Int8>
//       → StoreAlign<DIST_PACK4_B32>
// 注意：必须先 Truncate 成整数值再 Cast 到 fp16，避免 fp32→fp16 时丢整数精度。
//       输出的 dst offset 按「64 元素段起始 idx」传（与 §3.1 一致，非字节偏移）。
// 与 §3.1 int8 分支的区别：本函数先 Truncate 在 fp32 域取整（动态量化精确取整），
//                           §3.1 直接 fp16 中转（一般 int8 输出）。
// ----------------------------------------------------------------------------
__simd_callee__ inline void CastFp32ToInt8Quant(
    __ubuf__ int8_t* dst, AscendC::Reg::RegTensor<float>& xRegFp32, AscendC::Reg::MaskReg& preg, uint32_t offset)
{
    AscendC::Reg::RegTensor<float> xRegTmp;
    AscendC::Reg::RegTensor<half> xRegFp16;
    AscendC::Reg::RegTensor<int8_t> xOut;
    AscendC::Reg::Truncate<float, AscendC::RoundMode::CAST_RINT>(xRegTmp, xRegFp32, preg);
    AscendC::Reg::Cast<half, float, castTraitFp322Fp16>(xRegFp16, xRegTmp, preg);
    AscendC::Reg::Cast<int8_t, half, castTraitFp162Int8>(xOut, xRegFp16, preg);
    AscendC::Reg::StoreAlign<int8_t, AscendC::Reg::StoreDist::DIST_PACK4_B32>(dst + offset, xOut, preg);
}

// ----------------------------------------------------------------------------
// 3.4 fp32 → int4b 量化输出（ComputeMutlY int4b 分支）
// 链路：Cast<int16,float,Fp322Int16> → Cast<half,int16,Int162Half> → Pack(uint32)
//       → Cast<int4x2,half,F162I8> → StoreAlign<uint8,DIST_PACK4_B32>(H mask)
// 注意：dst offset 传「64 元素段起始 idx」，函数内部 /2 得到字节偏移（每字节 2 个 int4）。
//       写入用 H mask（只写前 32 槽位 = 64 个 int4 值），offset/2 定位字节。
// ----------------------------------------------------------------------------
__simd_callee__ inline void CastFp32ToInt4Quant(
    __ubuf__ uint8_t* dst, AscendC::Reg::RegTensor<float>& xRegFp32, AscendC::Reg::MaskReg& preg, uint32_t offset)
{
    AscendC::Reg::MaskReg mask4Int4 = AscendC::Reg::CreateMask<float, AscendC::Reg::MaskPattern::H>();
    AscendC::Reg::RegTensor<int16_t> vregInt16;
    AscendC::Reg::RegTensor<half> vregFp16;
    AscendC::Reg::RegTensor<uint16_t> vregTmp1;
    AscendC::Reg::RegTensor<uint8_t> vregTmp2;
    AscendC::Reg::Cast<int16_t, float, castTraitFp322Int16>(vregInt16, xRegFp32, preg);
    AscendC::Reg::Cast<half, int16_t, castTraitInt162Half>(vregFp16, vregInt16, preg);
    AscendC::Reg::Pack(vregTmp1, (AscendC::Reg::RegTensor<uint32_t>&)vregFp16);
    AscendC::Reg::Cast<int4x2_t, half, castTraitF162I8>(
        (AscendC::Reg::RegTensor<int4x2_t>&)vregTmp2, (AscendC::Reg::RegTensor<half>&)vregTmp1, preg);
    AscendC::Reg::StoreAlign<uint8_t, AscendC::Reg::StoreDist::DIST_PACK4_B32>(dst + offset / 2, vregTmp2, mask4Int4);
}

// ----------------------------------------------------------------------------
// 3.5 fp32 → BF16 量化输出（SAT 截断值域）
// 与 §3.1 的 castTraitF322F16(NO_SAT) 区别：量化路径需把超出 BF16 值域的结果 clip 而非溢出。
// 落 UB 同样配 StoreAlign<DIST_PACK_B32>（4B→2B 窄化红线）。
// ----------------------------------------------------------------------------
__simd_callee__ inline void CastFp32ToBf16Sat(
    AscendC::Reg::RegTensor<bfloat16_t>& dst, AscendC::Reg::RegTensor<float>& src, AscendC::Reg::MaskReg& preg)
{
    AscendC::Reg::Cast<bfloat16_t, float, castTraitFp322Bf16Sat>(dst, src, preg);
}

// ----------------------------------------------------------------------------
// 3.6 fp16 → int8 / uint8 直连窄化（不经 fp32 中转）
// 场景：fp16 输入直接量化到 int8/uint8（quant 算子的 int8 输出路径）。
// int8 用 TRUNC（OCP 截断），uint8 用 RINT。
// 来源：ops-nn/quant dequant_swiglu_quant_common.h:80（SAT+TRUNC）、
//       dynamic_quant_regbase_full_load_pertensor.h:828、quantize.h:196
// ----------------------------------------------------------------------------
__simd_callee__ inline void CastFp16ToInt8Direct(
    AscendC::Reg::RegTensor<int8_t>& dst, AscendC::Reg::RegTensor<half>& src, AscendC::Reg::MaskReg& preg)
{
    AscendC::Reg::Cast<int8_t, half, castTraitFp162Int8Trunc>(dst, src, preg);
}

__simd_callee__ inline void CastFp16ToUint8Direct(
    AscendC::Reg::RegTensor<uint8_t>& dst, AscendC::Reg::RegTensor<half>& src, AscendC::Reg::MaskReg& preg)
{
    AscendC::Reg::Cast<uint8_t, half, castTraitF162U8>(dst, src, preg);
}

// ============================================================================
// §4 扩宽（2B→4B / 1B→2B / 1B→4B）
//   场景：窄 dtype 输入统一进 fp32 计算域（§4.1），或整寄存器一次展开（§4.2），
//         或量化解码到 bf16/fp32（§4.3）。
//   特点：扩宽 Cast 的 RegLayout 用 ZERO（配 DIST_UNPACK_B16/B8），
//         多布局（ONE/TWO/THREE）用于整寄存器 de-interleave / 1B→4B 四槽位展开。
// ============================================================================

// ----------------------------------------------------------------------------
// 4.1 通用扩宽输入主入口：64 元素段（任意窄 dtype）→ 64 个 fp32
//
// 场景：任意 dtype 输入统一进 fp32 计算域做数值稳定运算（BF16 精度不足时先升精度，
//       内部全链 FP32）。每次处理 64 元素（VL_FP32=256B/sizeof(float)），
//       128 个源元素需调用 2 次（offset=0/64）或由调用方按 64 元素段循环。
//
// 典型循环骨架：
//   uint16_t repeatTime = (calCount + 63) / 64;
//   uint32_t sreg = calCount;
//   for (uint16_t i = 0; i < repeatTime; ++i) {
//       preg = AscendC::Reg::UpdateMask<float>(sreg);
//       LoadTensorForDtypeTIn<T_IN>(src, xFp32, preg, i * 64);
//       // ... fp32 计算 ...
//   }
//
// T_IN 分派（红线见各分支注释）：
//   float      → LoadAlign<DIST_NORM> 直载（无 Cast，同宽）
//   half/bf16  → LoadAlign<DIST_UNPACK_B16> + Cast<float, T_IN, castTraitF162F32>
//                （DIST_UNPACK_B16 把 16-bit 展开到 32-bit 槽，ZERO layout 单 Cast 完成扩宽）
//   int8_t     → LoadAlign<DIST_UNPACK4_B8> + Cast<half,int8,I82F16> + Cast<float,half,F162F32>
//                （两步中转：int8→half→float；DIST_UNPACK4_B8 是 4× 解包，仅 fp4 打包数据适用，
//                  普通顺序 int8 需按需求调整 LoadDist）
//   int32_t    → LoadAlign<DIST_NORM> + Cast<float,int32,Int322Fp32>（同宽，UNKNOWN layout）
// ----------------------------------------------------------------------------
template <typename T_IN>
__simd_callee__ inline void LoadTensorForDtypeTIn(
    __ubuf__ T_IN* src, AscendC::Reg::RegTensor<float>& dst, AscendC::Reg::MaskReg& preg, uint32_t offset)
{
    if constexpr (AscendC::IsSameType<T_IN, float>::value) {
        AscendC::Reg::LoadAlign<float, AscendC::Reg::LoadDist::DIST_NORM>(dst, src + offset);
    } else if constexpr (AscendC::IsSameType<T_IN, int8_t>::value) {
        AscendC::Reg::RegTensor<T_IN> xIn;
        AscendC::Reg::RegTensor<half> xInTmp;
        AscendC::Reg::LoadAlign<T_IN, AscendC::Reg::LoadDist::DIST_UNPACK4_B8>(xIn, src + offset);
        AscendC::Reg::Cast<half, T_IN, castTraitI82F16>(xInTmp, xIn, preg);
        AscendC::Reg::Cast<float, half, castTraitF162F32>(dst, xInTmp, preg);
    } else if constexpr (AscendC::IsSameType<T_IN, int32_t>::value) {
        AscendC::Reg::RegTensor<T_IN> xIn;
        AscendC::Reg::LoadAlign<int32_t, AscendC::Reg::LoadDist::DIST_NORM>(xIn, src + offset);
        AscendC::Reg::Cast<float, T_IN, castTraitInt322Fp32>(dst, xIn, preg);
    } else {
        AscendC::Reg::RegTensor<T_IN> xIn;
        AscendC::Reg::LoadAlign<T_IN, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(xIn, src + offset);
        AscendC::Reg::Cast<float, T_IN, castTraitF162F32>(dst, xIn, preg);
    }
}

// ----------------------------------------------------------------------------
// 4.1b int8/uint8 → fp16 直连扩宽（不经 fp32 中转）
// 场景：int8/uint8 输入直接展宽到 fp16（quant 算子的 offset 加载路径、反量化路径）。
//       与 §4.1 LoadTensorForDtypeTIn 的区别：只到 fp16 而非 fp32，省一步 Cast。
// 来源：ops-nn/quant ascend_anti_quant_v2:49、quantize.h:114/118
// ----------------------------------------------------------------------------
__simd_callee__ inline void CastInt8ToFp16(
    AscendC::Reg::RegTensor<half>& dst, AscendC::Reg::RegTensor<int8_t>& src, AscendC::Reg::MaskReg& preg)
{
    AscendC::Reg::Cast<half, int8_t, castTraitI82F16Direct>(dst, src, preg);
}

__simd_callee__ inline void CastUint8ToFp16(
    AscendC::Reg::RegTensor<half>& dst, AscendC::Reg::RegTensor<uint8_t>& src, AscendC::Reg::MaskReg& preg)
{
    AscendC::Reg::Cast<half, uint8_t, castTraitU8ToF16>(dst, src, preg);
}

// int4x2 → fp16（Cast + UnPack 两步：int4x2→half 直链 Cast，再 UnPack 展开偶/奇槽位到 fp16）
// 来源：ops-nn/quant ascend_anti_quant_v2_common.h:106-114
__simd_callee__ inline void CastInt4x2ToFp16(
    AscendC::Reg::RegTensor<half>& dst, AscendC::Reg::RegTensor<uint8_t>& srcUnpacked,
    AscendC::Reg::RegTensor<uint16_t>& tmpU16, AscendC::Reg::MaskReg& preg)
{
    AscendC::Reg::Cast<uint16_t, int4x2_t, castTraitI82F16Direct>(
        tmpU16, (AscendC::Reg::RegTensor<int4x2_t>&)srcUnpacked, preg);
    AscendC::Reg::UnPack((AscendC::Reg::RegTensor<uint32_t>&)dst, tmpU16);
}

// ----------------------------------------------------------------------------
// 4.2 多布局 de-interleave：整寄存器 2B→4B（一次处理满寄存器 128 元素）
//   场景：一个 256B 寄存器装 128 个 bf16/fp16，一次性展开成 2 个 fp32 寄存器（各 64 lane）。
//   与 4.1 的区别：4.1 按 64 元素段循环（配 DIST_UNPACK_B16），此处一次处理满寄存器。
//   注意：ZERO 取偶下标、ONE 取奇下标，两个目标寄存器内部各自顺序；
//         若需完全顺序排列需再做 Interleave（见 vf-instructions/interleave.md）。
// ----------------------------------------------------------------------------
template <typename T_IN>
__simd_callee__ inline void CastF16ToF32Pair(
    AscendC::Reg::RegTensor<float>& dstZero, AscendC::Reg::RegTensor<float>& dstOne,
    AscendC::Reg::RegTensor<T_IN>& src, AscendC::Reg::MaskReg& preg)
{
    AscendC::Reg::Cast<float, T_IN, castTraitF162F32>(dstZero, src, preg);
    AscendC::Reg::Cast<float, T_IN, castTraitF162F32One>(dstOne, src, preg);
}

// ----------------------------------------------------------------------------
// 4.3 量化解码（1B→2B / 1B→4B）
//   来源：vf_experiences/quant/{compute_scale_fp8,compute_data_fp8,
//                               compute_scale_fp4,compute_data_fp4}_lesson.md
//   说明：以下 helper 接收**已加载好的寄存器**，不含 LoadAlign（加载方式随
//         PostLiteral/AddrReg 用法而异，由调用方按场景选择）。
// ----------------------------------------------------------------------------

// 4.3.1 FP8_E8M0 → BF16（scale 解码）
// 前置：先把 uint8 源与全 0 寄存器做 Interleave-with-zero（data 必须是 Src0），
//       把每个字节铺到 16-bit slot；之后每个半寄存器用单 ZERO layout 即得顺序 BF16。
//   AscendC::Reg::Duplicate(vdZero, static_cast<uint8_t>(0));
//   AscendC::Reg::Interleave(vdScale0, vdScale1, vdScaleRaw, vdZero);
// 关键：源类型必须转成 fp8_e8m0_t 引用，写 uint8_t 会变成整数转浮点。
__simd_callee__ inline void CastFp8E8m0ToBf16(
    AscendC::Reg::RegTensor<bfloat16_t>& dst, AscendC::Reg::RegTensor<uint8_t>& srcInterleaved,
    AscendC::Reg::MaskReg& maskU8)
{
    AscendC::Reg::Cast<bfloat16_t, fp8_e8m0_t, castTraitFp8E8m0ToBf16>(
        dst, (AscendC::Reg::RegTensor<fp8_e8m0_t>&)srcInterleaved, maskU8);
}

// 4.3.2 FP8 → FP32 四布局展开（1B→4B）
// 256 个 fp8 散到 4 个 fp32 寄存器：vd0=[0,4,8..] vd1=[1,5,9..] vd2=[2,6,10..] vd3=[3,7,11..]
// 恢复顺序需两级 Interleave（cross-pair 0+2/1+3，再 0+1/2+3），见 vf-instructions/INDEX.md 模式 1.1。
template <typename T_FP8>
__simd_callee__ inline void CastFp8ToFp32Quad(
    AscendC::Reg::RegTensor<float>& vd0, AscendC::Reg::RegTensor<float>& vd1,
    AscendC::Reg::RegTensor<float>& vd2, AscendC::Reg::RegTensor<float>& vd3,
    AscendC::Reg::RegTensor<T_FP8>& src, AscendC::Reg::MaskReg& maskU8)
{
    AscendC::Reg::Cast<float, T_FP8, castTraitFp8ToFp32Zero>(vd0, src, maskU8);
    AscendC::Reg::Cast<float, T_FP8, castTraitFp8ToFp32One>(vd1, src, maskU8);
    AscendC::Reg::Cast<float, T_FP8, castTraitFp8ToFp32Two>(vd2, src, maskU8);
    AscendC::Reg::Cast<float, T_FP8, castTraitFp8ToFp32Three>(vd3, src, maskU8);
}

// 4.3.3 FP4 → BF16（硬件解包路径）
// 前置：LoadAlign<uint8_t, ..., LoadDist::DIST_UNPACK4_B8> 把 64 个打包字节铺成 256B 布局，
//       之后单 ZERO layout Cast 直接得到 128 个顺序 BF16（无需 Interleave / ShiftRights）。
// 关键：源类型必须转成 fp4x2_e2m1_t 引用。
__simd_callee__ inline void CastFp4ToBf16(
    AscendC::Reg::RegTensor<bfloat16_t>& dst, AscendC::Reg::RegTensor<uint8_t>& srcUnpacked,
    AscendC::Reg::MaskReg& maskU8)
{
    AscendC::Reg::Cast<bfloat16_t, fp4x2_e2m1_t, castTraitFp4ToBf16>(
        dst, (AscendC::Reg::RegTensor<fp4x2_e2m1_t>&)srcUnpacked, maskU8);
}

// ============================================================================
// §5 拆位 / 组合（int64）
//   来源：vf_experiences/_generic/reg_scalar_carry_and_int64_lesson.md §3
//   背景：A5 的 LoadDist DIST_BRC 与 StoreDist DIST_FIRST_ELEMENT 都只有 B8/B16/B32，
//         没有 B64 —— int64 既不能单指令广播，也不能单指令写回，必须拆低/高 32 位。
// ============================================================================

// int64 单元素写出：拆成 2×int32 连续写（i64Addr 视作 int32* 后按 2*idx / 2*idx+1 落位）。
// 高 32 位由低 32 位算术右移 31 得到，从而支持负值（如 -1 索引）符号扩展。
// 注意：ShiftRights 的移位量必须 static_cast<int16_t>，否则会在 fp16 上下文被推导为 half。
__simd_callee__ inline void StoreScalarInt64AsLoHi(
    __ubuf__ int32_t* i32Addr, uint32_t elemIdx,
    AscendC::Reg::RegTensor<int32_t>& idxLo, AscendC::Reg::MaskReg& maskAllI32)
{
    AscendC::Reg::RegTensor<int32_t> idxHi;
    AscendC::Reg::MaskReg maskOneI32 = AscendC::Reg::CreateMask<int32_t, AscendC::Reg::MaskPattern::VL1>();
    AscendC::Reg::StoreAlign<int32_t, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(
        i32Addr + 2 * elemIdx, idxLo, maskOneI32);
    AscendC::Reg::ShiftRights<int32_t>(idxHi, idxLo, static_cast<int16_t>(31), maskAllI32);
    AscendC::Reg::StoreAlign<int32_t, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(
        i32Addr + 2 * elemIdx + 1, idxHi, maskOneI32);
}

// int64 比较：x <= ref  ⟺  (xHi < refHi) || (xHi == refHi && xLo <= refLo)
// 低位按 uint32 无符号比较，高位按 int32 有符号比较。结果写入 leMask。
__simd_callee__ inline void CompareInt64LessEqual(
    AscendC::Reg::MaskReg& leMask,
    AscendC::Reg::RegTensor<int32_t>& xHi, AscendC::Reg::RegTensor<uint32_t>& xLo,
    AscendC::Reg::RegTensor<int32_t>& refHi, AscendC::Reg::RegTensor<uint32_t>& refLo,
    AscendC::Reg::MaskReg& maskAllI32, AscendC::Reg::MaskReg& maskAllU32)
{
    AscendC::Reg::MaskReg hiEq;
    AscendC::Reg::MaskReg loLe;
    AscendC::Reg::Compare<int32_t, AscendC::CMPMODE::LT>(leMask, xHi, refHi, maskAllI32);
    AscendC::Reg::Compare<int32_t, AscendC::CMPMODE::EQ>(hiEq, xHi, refHi, maskAllI32);
    AscendC::Reg::Compare<uint32_t, AscendC::CMPMODE::LE>(loLe, xLo, refLo, maskAllU32);
    AscendC::Reg::MaskAnd(hiEq, hiEq, loLe, maskAllU32);
    AscendC::Reg::MaskOr(leMask, leMask, hiEq, maskAllU32);
}

// ============================================================================
// §6 标量专项（广播读 + 单元素写）
//   场景：VF 内「每行 / 每 tile 不变量」标量的读入与写出——softmax rowMax、量化 scale、
//         偏置等；norm/loss 收尾把 fp32 累加器写回 0 维 / 单元素输出。
//   特点：LoadDist 用 DIST_BRC_*（广播），StoreDist 用 DIST_FIRST_ELEMENT_*（单元素）。
//         与 §2-§5 的按 64 元素段处理不同，标量只取 1 个元素。
// ============================================================================

// ----------------------------------------------------------------------------
// 6.1 LoadScalarForDtypeTIn<T_IN> —— 标量 → fp32 ×64 lane 广播
//
// 场景：VF 内需要「每行 / 每 tile 不变量标量」时（softmax rowMax、量化 scale、
//       偏置等），把 UB 中 1 个元素广播成 64 个 fp32 参与后续 element-wise 计算。
//
// 用法（读取 0 维标量）：
//   AscendC::Reg::RegTensor<float> accReg;
//   AscendC::Reg::MaskReg pregFull = AscendC::Reg::CreateMask<float, AscendC::Reg::MaskPattern::ALL>();
//   CustomRegImpl::LoadScalarForDtypeTIn<float>(accUb, accReg, pregFull, 0);
//
// T_IN 分派：float→DIST_BRC_B32；half/bf16→DIST_BRC_B16+Cast(F162F32)；
//           int8→DIST_BRC_B8+Cast(I82F16)+Cast(F162F32)；int32→DIST_BRC_B32+Cast(Int322Fp32)。
// 注意：DIST_BRC 广播族只有 B8/B16/B32，int64 无法单指令广播（见 §5 拆位）。
// ----------------------------------------------------------------------------
template <typename T_IN>
__simd_callee__ inline void LoadScalarForDtypeTIn(
    __ubuf__ T_IN* src, AscendC::Reg::RegTensor<float>& dst, AscendC::Reg::MaskReg& preg, uint32_t offset)
{
    if constexpr (AscendC::IsSameType<T_IN, float>::value) {
        AscendC::Reg::LoadAlign<float, AscendC::Reg::LoadDist::DIST_BRC_B32>(dst, src + offset);
    } else if constexpr (AscendC::IsSameType<T_IN, int8_t>::value) {
        AscendC::Reg::RegTensor<T_IN> xIn;
        AscendC::Reg::RegTensor<half> xInTmp;
        AscendC::Reg::LoadAlign<T_IN, AscendC::Reg::LoadDist::DIST_BRC_B8>(xIn, src + offset);
        AscendC::Reg::Cast<half, T_IN, castTraitI82F16>(xInTmp, xIn, preg);
        AscendC::Reg::Cast<float, half, castTraitF162F32>(dst, xInTmp, preg);
    } else if constexpr (AscendC::IsSameType<T_IN, int32_t>::value) {
        AscendC::Reg::RegTensor<T_IN> xIn;
        AscendC::Reg::LoadAlign<int32_t, AscendC::Reg::LoadDist::DIST_BRC_B32>(xIn, src + offset);
        AscendC::Reg::Cast<float, T_IN, castTraitInt322Fp32>(dst, xIn, preg);
    } else {
        AscendC::Reg::RegTensor<T_IN> xIn;
        AscendC::Reg::LoadAlign<T_IN, AscendC::Reg::LoadDist::DIST_BRC_B16>(xIn, src + offset);
        AscendC::Reg::Cast<float, T_IN, castTraitF162F32>(dst, xIn, preg);
    }
}

// ----------------------------------------------------------------------------
// 6.2 StoreScalarForDtypeTOut<T_OUT> —— fp32 累加器 → 单元素写出（norm/loss 收尾）
//
// 场景：整张量/整行规约后把 fp32 结果写回 0 维输出（如 foreach_norm 的 y ← f(acc)、
//       softmax 的 rowMax 标量槽位）。与 LoadScalarForDtypeTIn（广播读）配对使用。
//
// 用法：
//   // 读 0 维标量（广播到 fp32 寄存器）
//   CustomRegImpl::LoadScalarForDtypeTIn<float>(accUb, accReg, pregFull, 0);
//   // ... 计算 ...
//   // 写回 1 个元素（fp16/bf16 输出）
//   CustomRegImpl::StoreScalarForDtypeTOut<DY>(yAddr, yF32Reg, pregFull);
//
// T_OUT 分派：fp32 → StoreAlign<DIST_FIRST_ELEMENT_B32>（VL1 mask）；
//            half/bf16 → Cast(F322F16) + StoreAlign<DIST_FIRST_ELEMENT_B16>；
//            int32 → Cast(Fp322Int32) + StoreAlign<DIST_FIRST_ELEMENT_B32>。
// 注意：DIST_FIRST_ELEMENT 只有 B8/B16/B32，int64 无法单指令写回（见 §5 拆位）。
// 注意：CastTrait 的 RoundMode 在 AscendC:: 命名空间（AscendC::RoundMode），不是 Reg::。
// ----------------------------------------------------------------------------
template <typename T_OUT>
__simd_callee__ inline void StoreScalarForDtypeTOut(
    __ubuf__ T_OUT* dst, AscendC::Reg::RegTensor<float>& xRegFp32, AscendC::Reg::MaskReg& pregFull)
{
    if constexpr (AscendC::IsSameType<T_OUT, float>::value) {
        AscendC::Reg::MaskReg pregOne = AscendC::Reg::CreateMask<float, AscendC::Reg::MaskPattern::VL1>();
        AscendC::Reg::StoreAlign<float, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(dst, xRegFp32, pregOne);
    } else if constexpr (AscendC::IsSameType<T_OUT, bfloat16_t>::value || AscendC::IsSameType<T_OUT, half>::value) {
        AscendC::Reg::RegTensor<T_OUT> xOut;
        AscendC::Reg::Cast<T_OUT, float, castTraitF322F16>(xOut, xRegFp32, pregFull);
        AscendC::Reg::MaskReg pregOneDY = AscendC::Reg::CreateMask<T_OUT, AscendC::Reg::MaskPattern::VL1>();
        AscendC::Reg::StoreAlign<T_OUT, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B16>(dst, xOut, pregOneDY);
    } else if constexpr (AscendC::IsSameType<T_OUT, int32_t>::value) {
        AscendC::Reg::RegTensor<int32_t> xOut;
        AscendC::Reg::Cast<int32_t, float, castTraitFp322Int32>(xOut, xRegFp32, pregFull);
        AscendC::Reg::MaskReg pregOneI32 = AscendC::Reg::CreateMask<int32_t, AscendC::Reg::MaskPattern::VL1>();
        AscendC::Reg::StoreAlign<int32_t, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(dst, xOut, pregOneI32);
    }
}

} // namespace CustomRegImpl
#endif // _CAST_REGBASE_COMMON_H_
