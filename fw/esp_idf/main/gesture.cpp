#include "gesture.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <inttypes.h>
#include <string>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

namespace {
static const char *TAG = "gesture";

constexpr uint32_t kRawLogIntervalUs = 50'000;  // log raw channels every 50 ms while touching
}

void gestureTask(void *pvParameters) {
    auto *gesture = static_cast<Gesture *>(pvParameters);
    configASSERT(gesture != nullptr);

    while (true) {
        gesture->tick();
    }
}

Gesture::Gesture(QueueHandle_t position_queue)
    : position_queue_(position_queue) {}

void Gesture::init() {
    keymap_.init();
    ESP_EARLY_LOGI(TAG, "Gesture system initialised");
}

void Gesture::tick() {
    if (position_queue_ == nullptr) {
        vTaskDelay(pdMS_TO_TICKS(10));
        return;
    }

    TouchpadPosition position;
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;

    if (xQueueReceive(position_queue_, &position, portMAX_DELAY) != pdTRUE) {
        return;
    }

    position.read(x, y, z);

    static uint32_t last_raw_log_ts = 0;
    if (z >= TOUCH_THRESHOLD && esp_log_level_get(TAG) >= ESP_LOG_DEBUG) {
        const bool should_log =
            (last_raw_log_ts == 0) ||
            (position.timestamp - last_raw_log_ts >= kRawLogIntervalUs);
        if (should_log) {
            std::string raw_log = "raw channels: [";
            for (std::size_t i = 0; i < TouchpadPosition::kChannelCount; ++i) {
                raw_log += std::to_string(static_cast<long>(position.readings[i]));
                if (i + 1 != TouchpadPosition::kChannelCount) {
                    raw_log.push_back(',');
                }
            }
        raw_log.push_back(']');
        ESP_EARLY_LOGI(TAG, "%s", raw_log.c_str());

        std::string probe_log = "touch pads: [";
        for (std::size_t pad = 0; pad < TouchpadPosition::kProbeChannelCount; ++pad) {
            probe_log += std::to_string(pad);
            probe_log.push_back('=');
            probe_log += std::to_string(static_cast<long>(position.probe_readings[pad]));
            if (pad + 1 != TouchpadPosition::kProbeChannelCount) {
                probe_log.append(", ");
            }
        }
        probe_log.push_back(']');
        ESP_EARLY_LOGI(TAG, "%s", probe_log.c_str());

            float magnitudes[TouchpadPosition::kChannelCount];
            float magnitude_total = 0.0f;
            for (std::size_t i = 0; i < TouchpadPosition::kChannelCount; ++i) {
                magnitudes[i] = std::fabs(static_cast<float>(position.readings[i]));
                magnitude_total += magnitudes[i];
            }

            struct ChannelShare {
                int index;
                float share;
            } top_channels[4] = {
                {-1, 0.0f},
                {-1, 0.0f},
                {-1, 0.0f},
                {-1, 0.0f},
            };

            for (std::size_t i = 0; i < TouchpadPosition::kChannelCount; ++i) {
                const float share = (magnitude_total > 1e-6f) ? (magnitudes[i] / magnitude_total) : 0.0f;
                for (int j = 0; j < 4; ++j) {
                    if (share > top_channels[j].share) {
                        for (int k = 3; k > j; --k) {
                            top_channels[k] = top_channels[k - 1];
                        }
                        top_channels[j].index = static_cast<int>(i);
                        top_channels[j].share = share;
                        break;
                    }
                }
            }

            auto to_permil = [](float value) -> int32_t {
                return static_cast<int32_t>(std::lround(value * 1000.0f));
            };

            ESP_EARLY_LOGI(TAG,
                           "channel share permil: [%d=%" PRId32 ", %d=%" PRId32 ", %d=%" PRId32 ", %d=%" PRId32 "]",
                           top_channels[0].index, to_permil(top_channels[0].share),
                           top_channels[1].index, to_permil(top_channels[1].share),
                           top_channels[2].index, to_permil(top_channels[2].share),
                           top_channels[3].index, to_permil(top_channels[3].share));

            last_raw_log_ts = position.timestamp;
        }
    } else if (last_raw_log_ts != 0 && z < TOUCH_RELEASE_THRESHOLD) {
        last_raw_log_ts = 0;
    }

    const bool gesture_detected =
        detector_.update(x, y, z, position.timestamp);

    if (gesture_detected) {
        const DetectedGesture detected = detector_.getDetectedGesture();
        const int32_t dist_milli = static_cast<int32_t>(detector_.maxDistance() * 1000.0f);
        const int32_t x_milli = static_cast<int32_t>(x * 1000.0f);
        const int32_t y_milli = static_cast<int32_t>(y * 1000.0f);
        const uint8_t start_grid = detector_.startGrid();
        const float start_x = detector_.startX();
        const float start_y = detector_.startY();
        const float max_dx = detector_.maxDx();
        const float max_dy = detector_.maxDy();
        const float max_x = detector_.maxX();
        const float max_y = detector_.maxY();
        const float max_angle = detector_.maxAngle();
        const int32_t start_x_milli = static_cast<int32_t>(start_x * 1000.0f);
        const int32_t start_y_milli = static_cast<int32_t>(start_y * 1000.0f);
        const int32_t max_dx_milli = static_cast<int32_t>(max_dx * 1000.0f);
        const int32_t max_dy_milli = static_cast<int32_t>(max_dy * 1000.0f);
        const int32_t max_x_milli = static_cast<int32_t>(max_x * 1000.0f);
        const int32_t max_y_milli = static_cast<int32_t>(max_y * 1000.0f);

        ESP_EARLY_LOGW(TAG, "Gesture: grid=%u type=%d dir=%d max_dist=%" PRId32,
                       static_cast<unsigned>(start_grid),
                       static_cast<int>(detected.type),
                       static_cast<int>(detected.direction),
                       dist_milli);
        ESP_EARLY_LOGI(TAG, "start coords (norm x1e3): x=%" PRId32 " y=%" PRId32,
                       start_x_milli, start_y_milli);
        ESP_EARLY_LOGI(TAG, "coords (norm x1e3): x=%" PRId32 " y=%" PRId32, x_milli, y_milli);
        ESP_EARLY_LOGI(TAG, "max delta (norm x1e3): dx=%" PRId32 " dy=%" PRId32,
                       max_dx_milli, max_dy_milli);
        ESP_EARLY_LOGI(TAG, "max coords (norm x1e3): x=%" PRId32 " y=%" PRId32,
                       max_x_milli, max_y_milli);

        // Translate current coordinates into a 4x4 logical grid (1..4)
        auto mapToAlt = [](float value, int max_index) -> int {
            const int rounded = static_cast<int>(std::lround(value));
            const int max_clamp = std::max(0, max_index - 1);
            const int clamped = std::clamp(rounded, 0, max_clamp);
            return clamped + 1;
        };

        const int start_alt_x = mapToAlt(start_x, GRID_COLS);
        const int start_alt_y = mapToAlt(start_y, GRID_ROWS);
        const int max_alt_x = mapToAlt(max_x, GRID_COLS);
        const int max_alt_y = mapToAlt(max_y, GRID_ROWS);
        const int end_alt_x = mapToAlt(x, GRID_COLS);
        const int end_alt_y = mapToAlt(y, GRID_ROWS);
        ESP_EARLY_LOGI(TAG, "alt coords (start/max/end): %d,%d -> %d,%d -> %d,%d",
                       start_alt_x, start_alt_y, max_alt_x, max_alt_y,
                       end_alt_x, end_alt_y);

        const float end_dx = x - start_x;
        const float end_dy = y - start_y;
        const int32_t end_dx_milli = static_cast<int32_t>(end_dx * 1000.0f);
        const int32_t end_dy_milli = static_cast<int32_t>(end_dy * 1000.0f);
        const float end_dist = std::sqrt(end_dx * end_dx + end_dy * end_dy);
        const int32_t end_dist_milli = static_cast<int32_t>(end_dist * 1000.0f);

        const float kDegPerRad = 57.2957795f;
        auto normalize_angle = [](float angle) {
            float result = angle;
            while (result < 0.0f) result += 360.0f;
            while (result >= 360.0f) result -= 360.0f;
            return result;
        };
        const float angle_max_vec = normalize_angle(std::atan2(-max_dy, max_dx) * kDegPerRad);
        const float angle_end_vec = normalize_angle(std::atan2(-end_dy, end_dx) * kDegPerRad);
        const float angle_max_path = normalize_angle(max_angle);

        const int32_t angle_max_vec_milli = static_cast<int32_t>(std::lround(angle_max_vec * 1000.0f));
        const int32_t angle_end_vec_milli = static_cast<int32_t>(std::lround(angle_end_vec * 1000.0f));
        const int32_t angle_max_path_milli = static_cast<int32_t>(std::lround(angle_max_path * 1000.0f));

        ESP_EARLY_LOGI(TAG,
                       "swipe detail: vec_max=(dx=%" PRId32 ",dy=%" PRId32 ",ang_mdeg=%" PRId32 ") "
                       "vec_end=(dx=%" PRId32 ",dy=%" PRId32 ",ang_mdeg=%" PRId32 ") "
                       "dist_end=%" PRId32 " ang_path_mdeg=%" PRId32,
                       max_dx_milli, max_dy_milli, angle_max_vec_milli,
                       end_dx_milli, end_dy_milli, angle_end_vec_milli,
                       end_dist_milli, angle_max_path_milli);

        if (start_grid == GestureDetector::kInvalidGrid) {
            ESP_EARLY_LOGI(TAG, "Gesture ignored (outside keypad)");
            return;
        }

        const char *gesture_name = "unknown";
        switch (detected.type) {
            case GESTURE_TAP: gesture_name = "tap"; break;
            case GESTURE_HOLD: gesture_name = "hold"; break;
            case GESTURE_SWIPE_SHORT: gesture_name = "swipe"; break;
            case GESTURE_SWIPE_LONG: gesture_name = "swipe_long"; break;
            case GESTURE_SWIPE_RETURN: gesture_name = "swipe_return"; break;
            case GESTURE_CIRCLE_CW: gesture_name = "circle_cw"; break;
            case GESTURE_CIRCLE_CCW: gesture_name = "circle_ccw"; break;
            default: break;
        }
        const char *dir_name = "center";
        switch (detected.direction) {
            case DIR_NORTH: dir_name = "north"; break;
            case DIR_SOUTH: dir_name = "south"; break;
            case DIR_EAST: dir_name = "east"; break;
            case DIR_WEST: dir_name = "west"; break;
            case DIR_NORTHEAST: dir_name = "northeast"; break;
            case DIR_NORTHWEST: dir_name = "northwest"; break;
            case DIR_SOUTHEAST: dir_name = "southeast"; break;
            case DIR_SOUTHWEST: dir_name = "southwest"; break;
            case DIR_CENTER: dir_name = "center"; break;
        }
        ESP_EARLY_LOGI(TAG, "Gesture decoded: %s direction=%s", gesture_name, dir_name);
        keymap_.execute(start_grid, detected.type,
                        detected.direction);
    }
}
