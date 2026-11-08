#pragma once
#include <cstddef>
#include <cstdint>
#include "hid_action.h"

// Passive provenance only: this never changes recognition or output behavior.
struct HidOrigin {
    enum class Source : uint8_t { Diagnostic, Physical };
    Source source = Source::Diagnostic;
    uint32_t boot_id = 0, processing_epoch = 0, event_seq = 0, scan_seq = 0;
    uint32_t diagnostic_id = 0;
    uint64_t timestamp_us = 0;
    uint32_t duration_us = 0;
    uint8_t grid = 0, gesture_type = 0, direction = 0;
    float start_x = 0, start_y = 0, end_x = 0, end_y = 0;
    float peak_dx = 0, peak_dy = 0, max_distance = 0, path_length = 0;
};

struct HidCompletion {
    static constexpr size_t kMaxPresses = HidActionPlan::kMaxReports / 2;
    uint64_t completion_seq = 0, completed_us = 0;
    uint32_t usb_generation = 0, hid_failed = 0, hid_queue_drops = 0;
    HidOrigin origin;
    // The full press reports, in order. Successful releases are implicit;
    // an action enters this log only after every report is acknowledged.
    HidKeyboardReport presses[kMaxPresses] = {};
    uint8_t press_count = 0;
    bool caps_lock = false, shift_before = false, shift_after = false;
};

struct HidLogStatus {
    uint64_t oldest_seq = 0, latest_seq = 0, overwritten = 0;
    uint32_t retained = 0;
};

// No allocation or platform dependencies. The USB backend serializes access.
class HidCompletionLog {
public:
    static constexpr size_t kCapacity = 32;
    // Failed or partially transmitted actions and malformed report plans never
    // enter the log. State-only Shift commits have zero presses.
    bool recordCompleted(bool succeeded, const HidOrigin &origin,
                         const HidActionPlan &plan, uint64_t completed_us,
                         uint32_t usb_generation, bool caps_lock, bool shift_before,
                         uint32_t hid_failed = 0, uint32_t hid_queue_drops = 0);
    HidLogStatus status() const;
    bool get(uint64_t sequence, HidCompletion &record) const;
private:
    HidCompletion records_[kCapacity] = {};
    uint64_t latest_ = 0, overwritten_ = 0;
    uint32_t count_ = 0;
};
