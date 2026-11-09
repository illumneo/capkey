#pragma once

#include <cstddef>
#include <cstdint>
#include <array>

#include "esp_err.h"
#include "esp_attr.h"
#include "driver/touch_sens.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "soc/soc_caps.h"

// Qualified on the large PCB: about 60 scans/s with strong touch response.
constexpr uint32_t kTouchpadChargeTimes = 200;
#define TOUCHPAD_SAMPLE_CFG_DEFAULT() \
    { TOUCH_SENSOR_V2_DEFAULT_SAMPLE_CONFIG(kTouchpadChargeTimes, TOUCH_VOLT_LIM_L_0V5, TOUCH_VOLT_LIM_H_2V2) }

#define TOUCHPAD_CHANNEL_CFG_DEFAULT() \
    {                                                                        \
        .active_thresh = {2000 * kTouchpadChargeTimes / 800},                  \
        .charge_speed = TOUCH_CHARGE_SPEED_7,                                \
        .init_charge_volt = TOUCH_INIT_CHARGE_VOLT_DEFAULT,                  \
    }

extern uint32_t scans;

struct TouchpadPosition {
    static constexpr std::size_t kChannelCount = 12;
    static constexpr std::size_t kProbeChannelCount = SOC_TOUCH_SENSOR_NUM;

    int32_t readings[kChannelCount];
    int32_t probe_readings[kProbeChannelCount];
    uint32_t timestamp;

    void read(float &x, float &y, float &z) const;
};

class Touchpad {
public:
    static constexpr std::size_t kChannelCount = 12;

    Touchpad(touch_sensor_handle_t sensor_handle,
             const uint8_t (&channel_ids)[kChannelCount],
             QueueHandle_t position_queue);
    Touchpad(const Touchpad &) = delete;
    Touchpad &operator=(const Touchpad &) = delete;

    esp_err_t init();

private:
    static bool IRAM_ATTR onTouchScanDone(touch_sensor_handle_t sens_handle,
                                          const touch_scan_done_event_data_t *event,
                                          void *user_ctx);

    bool sendPositionFromISR();

    touch_sensor_handle_t sensor_handle_ = nullptr;
    uint8_t channel_ids_[kChannelCount] = {};
    touch_channel_handle_t channel_handles_[kChannelCount] = {};
    uint32_t benchmark_[kChannelCount] = {};
    touch_channel_handle_t handles_by_pad_[TouchpadPosition::kProbeChannelCount] = {};
    uint32_t probe_benchmark_[TouchpadPosition::kProbeChannelCount] = {};
    QueueHandle_t position_queue_;
    bool initialized_ = false;
};
