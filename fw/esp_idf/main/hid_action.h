#pragma once

#include <cstddef>
#include <cstdint>
#include "gestureLayout.h"

// Portable US-layout encoder. No USB I/O and no dynamic allocation.
struct HidKeyboardReport {
    uint8_t modifier = 0;
    uint8_t keycodes[6] = {};
};

struct HidActionPlan {
    static constexpr size_t kMaxTextLength = 31;
    static constexpr size_t kMaxReports = 2 * kMaxTextLength;
    HidKeyboardReport reports[kMaxReports] = {};
    uint8_t report_count = 0;
    bool next_shift_pending = false;
};

class HidActionEncoder {
public:
    // Returns false for unsupported/oversized input; leaves encoder state
    // unchanged. Every transmitted key has a following all-zero release.
    bool encode(const KeyAction &action, HidActionPlan &plan) const;
    // Call only after every report (including release) completes. A SHIFT
    // action has zero reports and toggles the one-shot modifier (tap again
    // to cancel without ever holding a physical host modifier).
    void commit(const HidActionPlan &plan) { shift_pending_ = plan.next_shift_pending; }
    // Disconnect/failure cancels pending modifiers. Transport owns recovery
    // releases for a report that may already have reached the host.
    void reset() { shift_pending_ = false; caps_lock_ = false; }
    bool shiftPending() const { return shift_pending_; }
    // Host output-report LED state, not an optimistic local toggle.
    void setCapsLock(bool enabled) { caps_lock_ = enabled; }
private:
    bool shift_pending_ = false;
    bool caps_lock_ = false;
};
