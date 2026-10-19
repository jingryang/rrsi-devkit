#pragma once

#include "kernel_operator.h"

// ============================================================================
// AscendC 核内同步追踪器 v4
//
// 改进：
// 1. 支持多错误收集（最多 8 个不同错误）
// 2. 错误去重：相同错误只计数，不重复记录
// 3. 遇到错误时不修改状态，避免连锁错误
// 4. 记录上一次 SET 的行号，帮助定位 SET on SET 和 WAIT on UNSET
// 5. 增加 FILE_ID 支持多文件精确定位（配合 sync_file_map.json）
//
// 用法：
//   TrackerSet(HE_XXX, eid, FILE_ID, __LINE__)
//   TrackerWait(HE_XXX, eid, FILE_ID, __LINE__)
//   在 Kernel 结尾调用 TrackerPrint()
//
// FILE_ID 由注入脚本自动分配，映射关系保存在 sync_file_map.json
// ============================================================================

// ----------------------------------------------------------------------------
// HardEvent 索引常量（与 AscendC 内部顺序一致）
// ----------------------------------------------------------------------------
static constexpr uint8_t HE_MTE2_MTE1 = 0;
static constexpr uint8_t HE_MTE1_MTE2 = 1;
static constexpr uint8_t HE_MTE1_M = 2;
static constexpr uint8_t HE_M_MTE1 = 3;
static constexpr uint8_t HE_MTE2_V = 4;
static constexpr uint8_t HE_V_MTE2 = 5;
static constexpr uint8_t HE_MTE3_V = 6;
static constexpr uint8_t HE_V_MTE3 = 7;
static constexpr uint8_t HE_M_V = 8;
static constexpr uint8_t HE_V_M = 9;
static constexpr uint8_t HE_MTE3_MTE1 = 10;
static constexpr uint8_t HE_MTE1_MTE3 = 11;
static constexpr uint8_t HE_MTE1_V = 12;
static constexpr uint8_t HE_MTE2_M = 13;
static constexpr uint8_t HE_M_MTE2 = 14;
static constexpr uint8_t HE_V_MTE1 = 15;
static constexpr uint8_t HE_M_FIX = 16;
static constexpr uint8_t HE_FIX_M = 17;
static constexpr uint8_t HE_MTE3_MTE2 = 18;
static constexpr uint8_t HE_MTE2_MTE3 = 19;
static constexpr uint8_t HE_S_V = 20;
static constexpr uint8_t HE_V_S = 21;
static constexpr uint8_t HE_S_MTE2 = 22;
static constexpr uint8_t HE_MTE2_S = 23;
static constexpr uint8_t HE_S_MTE3 = 24;
static constexpr uint8_t HE_MTE3_S = 25;
static constexpr uint8_t HE_MTE2_FIX = 26;
static constexpr uint8_t HE_FIX_MTE2 = 27;
static constexpr uint8_t HE_FIX_S = 28;
static constexpr uint8_t HE_M_S = 29;
static constexpr uint8_t HE_FIX_MTE3 = 30;

// 最大错误记录数
static constexpr uint8_t MAX_ERRORS = 8;

// ----------------------------------------------------------------------------
// 全局追踪状态
// ----------------------------------------------------------------------------
struct SyncTracker {
    // flag 状态: 0=UNSET, 1=SET
    uint8_t flag_state[31][16];

    // 每个 flag 上一次 SET 的位置
    struct SetLocation {
        uint16_t line;    // SET 的行号
        uint16_t file_id; // SET 的文件编号
        uint8_t valid;    // 是否有效（曾经 SET 过）
    } set_location[31][16];

    // 错误记录
    struct ErrorRecord {
        uint8_t type;         // 1=WAIT on UNSET, 2=SET on SET
        uint8_t hard_event;   // 出错的 HardEvent 类型
        uint8_t event_id;     // 出错的 event_id
        uint16_t line;        // 出错的行号
        uint16_t file_id;     // 出错的文件编号
        uint16_t prev_line;   // 上一次 SET 的行号
        uint16_t prev_file_id;// 上一次 SET 的文件编号
        uint16_t count;       // 此错误出现的次数
    } errors[MAX_ERRORS];

    uint8_t error_count;      // 当前错误数量
};

// 全局变量（每个核独立）
inline __gm__ SyncTracker g_tracker = {0};

// ----------------------------------------------------------------------------
// 核心追踪函数
// ----------------------------------------------------------------------------

__aicore__ inline void TrackerSet(uint8_t hard_event, uint8_t event_id, uint16_t file_id, uint16_t line) {
    if (AscendC::GetBlockIdx() != 0) return;

    if (g_tracker.flag_state[hard_event][event_id] == 1) {
        // 重复 SET 错误：连续两次 SET 同一个 flag
        // 检查是否已记录过相同的错误（去重）
        for (int i = 0; i < g_tracker.error_count; i++) {
            auto& err = g_tracker.errors[i];
            if (err.type == 2 && err.hard_event == hard_event &&
                err.event_id == event_id && err.line == line) {
                // 相同错误，增加计数
                err.count++;
                return;  // 不修改状态，避免连锁错误
            }
        }

        // 新错误，记录它
        if (g_tracker.error_count < MAX_ERRORS) {
            auto& err = g_tracker.errors[g_tracker.error_count++];
            err.type = 2;  // SET on SET
            err.hard_event = hard_event;
            err.event_id = event_id;
            err.line = line;
            err.file_id = file_id;
            err.prev_line = g_tracker.set_location[hard_event][event_id].line;
            err.prev_file_id = g_tracker.set_location[hard_event][event_id].file_id;
            err.count = 1;
        }
        // 不修改状态，保持 SET 状态
        return;
    }

    // 正常情况，更新状态
    g_tracker.flag_state[hard_event][event_id] = 1;
    g_tracker.set_location[hard_event][event_id].line = line;
    g_tracker.set_location[hard_event][event_id].file_id = file_id;
    g_tracker.set_location[hard_event][event_id].valid = 1;
}

__aicore__ inline void TrackerWait(uint8_t hard_event, uint8_t event_id, uint16_t file_id, uint16_t line) {
    if (AscendC::GetBlockIdx() != 0) return;

    if (g_tracker.flag_state[hard_event][event_id] == 0) {
        // WAIT 无 SET 错误
        // 检查是否已记录过相同的错误（去重）
        for (int i = 0; i < g_tracker.error_count; i++) {
            auto& err = g_tracker.errors[i];
            if (err.type == 1 && err.hard_event == hard_event &&
                err.event_id == event_id && err.line == line) {
                // 相同错误，增加计数
                err.count++;
                return;  // 不修改状态，避免连锁错误
            }
        }

        // 新错误，记录它
        if (g_tracker.error_count < MAX_ERRORS) {
            auto& err = g_tracker.errors[g_tracker.error_count++];
            err.type = 1;  // WAIT on UNSET
            err.hard_event = hard_event;
            err.event_id = event_id;
            err.line = line;
            err.file_id = file_id;
            err.prev_line = g_tracker.set_location[hard_event][event_id].line;
            err.prev_file_id = g_tracker.set_location[hard_event][event_id].file_id;
            err.count = 1;
        }
        // 不修改状态，保持 UNSET 状态
        return;
    }

    // 正常情况，更新状态
    g_tracker.flag_state[hard_event][event_id] = 0;
}

// ----------------------------------------------------------------------------
// 输出函数
// ----------------------------------------------------------------------------

__aicore__ inline void TrackerPrint() {
    if (AscendC::GetBlockIdx() != 0) return;

    if (g_tracker.error_count == 0) {
        AscendC::printf("[SYNC DEBUG] OK: all sync calls are correct\n");
        return;
    }

    // 输出错误统计
    AscendC::printf("[SYNC DEBUG] Found %d error(s):\n", g_tracker.error_count);
    AscendC::printf("\n");

    for (int i = 0; i < g_tracker.error_count; i++) {
        auto& err = g_tracker.errors[i];

        if (err.type == 1) {
            // WAIT on UNSET
            if (g_tracker.set_location[err.hard_event][err.event_id].valid) {
                // 这个 flag 曾经 SET 过，后来被 WAIT 清零了
                AscendC::printf("[SYNC DEBUG] ERROR %d: WAIT on UNSET (HE=%d eid=%d) x %d times\n",
                    i + 1, err.hard_event, err.event_id, err.count);
                AscendC::printf("  WAIT at F%d:L%d, prev SET at F%d:L%d\n",
                    err.file_id, err.line,
                    err.prev_file_id, err.prev_line);
                AscendC::printf("  => flag was SET then WAITed, need another SET?\n");
            } else {
                // 这个 flag 从未被 SET 过
                AscendC::printf("[SYNC DEBUG] ERROR %d: WAIT on NEVER-SET (HE=%d eid=%d) x %d times\n",
                    i + 1, err.hard_event, err.event_id, err.count);
                AscendC::printf("  WAIT at F%d:L%d (flag never SET before)\n",
                    err.file_id, err.line);
                AscendC::printf("  => need SET before this WAIT\n");
            }
        } else if (err.type == 2) {
            // SET on SET
            AscendC::printf("[SYNC DEBUG] ERROR %d: SET on SET (HE=%d eid=%d) x %d times\n",
                i + 1, err.hard_event, err.event_id, err.count);
            AscendC::printf("  SET at F%d:L%d, prev SET at F%d:L%d\n",
                err.file_id, err.line,
                err.prev_file_id, err.prev_line);
            AscendC::printf("  => flag already SET, need WAIT before this SET?\n");
        }
        AscendC::printf("\n");
    }
}

__aicore__ inline bool TrackerHasError() {
    return g_tracker.error_count > 0;
}

// 返回错误数量
__aicore__ inline uint8_t TrackerGetErrorCount() {
    return g_tracker.error_count;
}

// ----------------------------------------------------------------------------
// 调试辅助：打印当前 flag 状态
// ----------------------------------------------------------------------------

__aicore__ inline void TrackerDumpState(uint8_t hard_event) {
    if (AscendC::GetBlockIdx() != 0) return;

    AscendC::printf("[SYNC DEBUG] HE=%d flags: ", hard_event);
    for (int i = 0; i < 16; i++) {
        if (g_tracker.flag_state[hard_event][i] == 1) {
            AscendC::printf("[%d]=SET@F%d:L%d ", i,
                g_tracker.set_location[hard_event][i].file_id,
                g_tracker.set_location[hard_event][i].line);
        }
    }
    AscendC::printf("\n");
}