#pragma once

#include <cstddef>
#include <cstdint>

namespace touchpad_calibration {
constexpr std::size_t kChannelCount = 12;
// Physical pad order used by the legacy acquisition adapter.
constexpr uint8_t kPadIds[kChannelCount] = {1, 2, 12, 4, 5, 6, 7, 8, 9, 10, 11, 3};
}  // namespace touchpad_calibration
