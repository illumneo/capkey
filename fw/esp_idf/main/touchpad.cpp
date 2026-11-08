#include "touchpad.h"
#include "touch_processing.h"
#include "touchpad_calibration.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <inttypes.h>
#include <limits>

#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

#include "gestureConfig.h"

namespace {
static const char *TAG = "touchpad";
constexpr std::array<uint8_t, TouchpadPosition::kProbeChannelCount> kAllTouchPads = {
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14,
};
}  // namespace

uint32_t scans = 0;

void TouchpadPosition::read(float &x, float &y, float &z) const {
    int32_t physical_deltas[swipe::kTouchPadCount]{};
    for (std::size_t i = 0; i < kChannelCount; ++i)
        physical_deltas[touchpad_calibration::kPadIds[i]] = readings[i];
    // The recorded four corners and center confirm the large PCB grouping.
    const auto coordinates = swipe::processTouch(
        physical_deltas, swipe::kRequiredTouchPadMask, swipe::TouchProcessingMode::Pcb,
        kTouchpadChargeTimes);
    x = coordinates.x;
    y = coordinates.y;
    z = coordinates.z;
    if (z == 0.0f) return;
    ESP_LOGD(TAG, "centroid (x,y,z)x1e3 = (%" PRId32 ", %" PRId32 ", %" PRId32 ")",
                   static_cast<int32_t>(std::lround(x * 1000.0f)),
                   static_cast<int32_t>(std::lround(y * 1000.0f)),
                   static_cast<int32_t>(std::lround(z * 1000.0f)));
}

Touchpad::Touchpad(touch_sensor_handle_t sensor_handle,
                   const uint8_t (&channel_ids)[kChannelCount],
                   QueueHandle_t position_queue)
    : sensor_handle_(sensor_handle), position_queue_(position_queue) {
    std::memcpy(channel_ids_, channel_ids, sizeof(channel_ids_));
}

esp_err_t Touchpad::init() {
    if (position_queue_ == nullptr || sensor_handle_ == nullptr) {
        return ESP_ERR_INVALID_ARG;
    }

    if (initialized_) {
        return ESP_OK;
    }

    touch_channel_config_t chan_cfg = TOUCHPAD_CHANNEL_CFG_DEFAULT();
    std::size_t channels_created = 0;
    esp_err_t err = ESP_OK;
    touch_event_callbacks_t callbacks = {};

    for (std::size_t i = 0; i < kChannelCount; ++i) {
        err = touch_sensor_new_channel(sensor_handle_, channel_ids_[i], &chan_cfg, &channel_handles_[i]);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "touch_sensor_new_channel failed for channel %u: %s",
                     static_cast<unsigned>(channel_ids_[i]), esp_err_to_name(err));
            goto cleanup;
        }
        const uint8_t pad = channel_ids_[i];
        if (pad < TouchpadPosition::kProbeChannelCount) {
            handles_by_pad_[pad] = channel_handles_[i];
        }
        ++channels_created;
    }

    for (uint8_t pad : kAllTouchPads) {
        if (pad >= TouchpadPosition::kProbeChannelCount) {
            continue;
        }
        if (handles_by_pad_[pad] != nullptr) {
            continue;
        }
        touch_channel_handle_t probe_handle = nullptr;
        esp_err_t probe_err = touch_sensor_new_channel(sensor_handle_, pad, &chan_cfg, &probe_handle);
        if (probe_err != ESP_OK) {
            ESP_LOGW(TAG, "probe channel %u registration failed: %s",
                     static_cast<unsigned>(pad), esp_err_to_name(probe_err));
            continue;
        }
        handles_by_pad_[pad] = probe_handle;
    }

    callbacks.on_scan_done = &Touchpad::onTouchScanDone;
    err = touch_sensor_register_callbacks(sensor_handle_, &callbacks, this);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "touch_sensor_register_callbacks failed: %s", esp_err_to_name(err));
        goto cleanup;
    }

    initialized_ = true;
    ESP_LOGI(TAG, "Touchpad channels initialised");
    return ESP_OK;

cleanup:
    for (std::size_t pad = 0; pad < TouchpadPosition::kProbeChannelCount; ++pad) {
        touch_channel_handle_t handle = handles_by_pad_[pad];
        if (handle == nullptr) {
            continue;
        }
        bool owned_by_primary = false;
        for (std::size_t i = 0; i < channels_created; ++i) {
            if (channel_handles_[i] == handle) {
                owned_by_primary = true;
                break;
            }
        }
        if (owned_by_primary) {
            continue;
        }
        const esp_err_t del_err = touch_sensor_del_channel(handle);
        if (del_err != ESP_OK) {
            ESP_LOGW(TAG, "touch_sensor_del_channel failed for probe channel %u: %s",
                     static_cast<unsigned>(pad), esp_err_to_name(del_err));
        }
        handles_by_pad_[pad] = nullptr;
    }
    for (std::size_t i = 0; i < channels_created; ++i) {
        if (channel_handles_[i] == nullptr) {
            continue;
        }
        const esp_err_t del_err = touch_sensor_del_channel(channel_handles_[i]);
        if (del_err != ESP_OK) {
            ESP_LOGW(TAG, "touch_sensor_del_channel failed for channel %u: %s",
                     static_cast<unsigned>(channel_ids_[i]), esp_err_to_name(del_err));
        }
        channel_handles_[i] = nullptr;
    }
    return err;
}

bool IRAM_ATTR Touchpad::onTouchScanDone(touch_sensor_handle_t,
                                         const touch_scan_done_event_data_t *,
                                         void *user_ctx) {
    auto *touchpad = static_cast<Touchpad *>(user_ctx);
    if (touchpad == nullptr) {
        return false;
    }

    const bool task_woken = touchpad->sendPositionFromISR();
    ++scans;
    return task_woken;
}

bool Touchpad::sendPositionFromISR() {
    if (position_queue_ == nullptr) {
        return false;
    }

    TouchpadPosition position{};

    for (std::size_t i = 0; i < kChannelCount; ++i) {
        if (channel_handles_[i] == nullptr) {
            position.readings[i] = 0;
            continue;
        }

        uint32_t benchmark_value = 0;
        if (touch_channel_read_data(channel_handles_[i], TOUCH_CHAN_DATA_TYPE_BENCHMARK, &benchmark_value) != ESP_OK) {
            benchmark_value = benchmark_[i];
        }
        benchmark_[i] = benchmark_value;

        uint32_t smooth_value = benchmark_value;
        if (touch_channel_read_data(channel_handles_[i], TOUCH_CHAN_DATA_TYPE_SMOOTH, &smooth_value) != ESP_OK) {
            smooth_value = benchmark_value;
        }

        position.readings[i] =
            static_cast<int32_t>(smooth_value) - static_cast<int32_t>(benchmark_value);
    }

    for (std::size_t pad = 0; pad < TouchpadPosition::kProbeChannelCount; ++pad) {
        int32_t reading = 0;
        touch_channel_handle_t handle = handles_by_pad_[pad];
        if (handle != nullptr) {
            uint32_t benchmark_value = 0;
            if (touch_channel_read_data(handle, TOUCH_CHAN_DATA_TYPE_BENCHMARK, &benchmark_value) != ESP_OK) {
                benchmark_value = probe_benchmark_[pad];
            }
            probe_benchmark_[pad] = benchmark_value;

            uint32_t smooth_value = benchmark_value;
            if (touch_channel_read_data(handle, TOUCH_CHAN_DATA_TYPE_SMOOTH, &smooth_value) != ESP_OK) {
                smooth_value = benchmark_value;
            }
            reading = static_cast<int32_t>(smooth_value) - static_cast<int32_t>(benchmark_value);
        }
        position.probe_readings[pad] = reading;
    }

    position.timestamp = static_cast<uint32_t>(esp_timer_get_time());

    BaseType_t task_woken = pdFALSE;
    xQueueOverwriteFromISR(position_queue_, &position, &task_woken);
    return task_woken == pdTRUE;
}
