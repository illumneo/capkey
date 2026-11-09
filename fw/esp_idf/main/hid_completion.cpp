#include "hid_completion.h"
#include <limits>

bool HidCompletionLog::recordCompleted(bool succeeded, const HidOrigin &origin,
                                      const HidActionPlan &plan, uint64_t completed_us,
                                      uint32_t usb_generation, bool caps_lock,
                                      bool shift_before, uint32_t hid_failed, uint32_t hid_queue_drops) {
    if (!succeeded || plan.report_count > HidActionPlan::kMaxReports ||
        (plan.report_count & 1u) || latest_ == std::numeric_limits<uint64_t>::max()) return false;
    for (size_t i = 1; i < plan.report_count; i += 2) {
        if (plan.reports[i].modifier) return false;
        for (const auto key : plan.reports[i].keycodes) if (key) return false;
    }
    const uint64_t sequence = latest_ + 1;
    auto &record = records_[(sequence - 1) % kCapacity];
    record = {};
    record.completion_seq = sequence;
    record.completed_us = completed_us;
    record.usb_generation = usb_generation;
    record.hid_failed = hid_failed; record.hid_queue_drops = hid_queue_drops;
    record.origin = origin;
    record.press_count = plan.report_count / 2;
    for (size_t i = 0; i < record.press_count; ++i) record.presses[i] = plan.reports[i * 2];
    record.caps_lock = caps_lock;
    record.shift_before = shift_before;
    record.shift_after = plan.next_shift_pending;
    latest_ = sequence;
    if (count_ == kCapacity) ++overwritten_;
    else ++count_;
    return true;
}

HidLogStatus HidCompletionLog::status() const {
    return {count_ ? latest_ - count_ + 1 : 0, latest_, overwritten_, count_};
}

bool HidCompletionLog::get(uint64_t sequence, HidCompletion &record) const {
    const auto bounds = status();
    if (!sequence || !bounds.retained || sequence < bounds.oldest_seq || sequence > bounds.latest_seq)
        return false;
    record = records_[(sequence - 1) % kCapacity];
    return record.completion_seq == sequence;
}
