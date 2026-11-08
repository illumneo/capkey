#include "touch_processing.h"

#include <algorithm>
#include <cmath>

namespace swipe {
namespace {

// Keep the legacy sum order and weights: even floating-point rounding is part
// of reproducing the previous TouchpadPosition::read implementation.
constexpr uint8_t kLegacyPadOrder[] = {1, 2, 12, 4, 5, 6, 7, 8, 9, 10, 11, 3};
constexpr uint8_t kLegacyX[] = {11, 2, 8, 3, 6, 4};
constexpr uint8_t kLegacyY[] = {1, 9, 12, 10, 5, 7};
constexpr float kLegacyPositions[] = {0.0f, 0.8f, 1.6f, 2.4f, 3.2f, 4.0f};

// 50 mm PCB, viewed from the touch side with the CapKey text upright.
// Evidence: capkey/kicad/capacitive_touch_6x6_50mm PCB footprint pad/net list.
constexpr uint8_t kPcbX[] = {11, 9, 10, 2, 3, 4};
constexpr uint8_t kPcbY[] = {1, 12, 8, 5, 6, 7};
// Detector cells have integer centres 0..3. This evenly spaced baseline is an
// explicit modelling choice; electrode centroids have not been fitted to keys.
constexpr float kPcbPositions[] = {0.0f, 0.6f, 1.2f, 1.8f, 2.4f, 3.0f};

float axisCoordinate(const float* magnitude, const uint8_t* pads,
                     const float* positions, float span) {
    float sum = 0.0f;
    float weighted = 0.0f;
    for (std::size_t i = 0; i < 6; ++i) {
        const float value = magnitude[pads[i]];
        sum += value;
        weighted += value * positions[i];
    }
    if (sum < 1e-3f) {
        return 0.0f;
    }
    return std::max(0.0f, std::min(span, weighted / sum));
}

}  // namespace

TouchCoordinates processTouch(const int32_t* physical_pad_deltas,
                              uint16_t valid_mask, TouchProcessingMode mode,
                              uint32_t charge_times) {
    TouchCoordinates out;
    if (physical_pad_deltas == nullptr || charge_times == 0 ||
        (valid_mask & kRequiredTouchPadMask) != kRequiredTouchPadMask) {
        return out;
    }
    out.valid = true;
    float magnitude[kTouchPadCount] = {};
    float total = 0.0f;
    const float delta_scale = static_cast<float>(kReferenceChargeTimes) /
                              static_cast<float>(charge_times);
    for (const uint8_t pad : kLegacyPadOrder) {
        const float value = static_cast<float>(physical_pad_deltas[pad]) * delta_scale;
        magnitude[pad] = mode == TouchProcessingMode::Legacy
                             ? std::fabs(value)
                             : std::max(0.0f, value);
        total += magnitude[pad];
    }
    if (total < 1500.0f) {
        return out;
    }
    const bool legacy = mode == TouchProcessingMode::Legacy;
    const float* positions = legacy ? kLegacyPositions : kPcbPositions;
    const float span = legacy ? 4.0f : 3.0f;
    out.x = axisCoordinate(magnitude, legacy ? kLegacyX : kPcbX, positions, span);
    out.y = axisCoordinate(magnitude, legacy ? kLegacyY : kPcbY, positions, span);
    out.z = total / 8000.0f;
    return out;
}

}  // namespace swipe
