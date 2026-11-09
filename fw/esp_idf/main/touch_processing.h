#pragma once

#include <cstddef>
#include <cstdint>

// Portable touch processing shared by firmware and host replay. Pad indices are
// ESP32-S3 physical GPIO/touch channel numbers, never capture array permutations.
namespace swipe {

constexpr std::size_t kTouchPadCount = 15;
constexpr uint16_t kRequiredTouchPadMask = 0x1ffe;  // GPIOs 1 through 12.
constexpr uint32_t kReferenceChargeTimes = 800;

enum class TouchProcessingMode {
    Legacy,
    // Experimental wiring-derived baseline, not a fitted calibration.
    Pcb,
};

struct TouchCoordinates {
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
    bool valid = false;
};

// physical_pad_deltas must point to kTouchPadCount signed smooth-minus-benchmark
// readings. Missing required channels invalidate the whole position. A complete
// low-energy sample remains valid and returns zero, preserving release samples.
// Deltas are scaled to 800-charge-equivalent counts before abs/clamping. This
// assumes a linear response to charge_times; it is not a sensor calibration.
// A zero charge_times value is invalid. The default preserves legacy arithmetic.
TouchCoordinates processTouch(
    const int32_t* physical_pad_deltas,
    uint16_t valid_mask,
    TouchProcessingMode mode = TouchProcessingMode::Legacy,
    uint32_t charge_times = kReferenceChargeTimes);

}  // namespace swipe
