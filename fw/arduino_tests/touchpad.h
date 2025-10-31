#pragma once
#include "Arduino.h"
#include "driver/touch_sens.h"

// Template method implementations
#define EXAMPLE_TOUCH_CHAN_CFG_DEFAULT()        {  \
    .active_thresh = {2000},  \
    .charge_speed = TOUCH_CHARGE_SPEED_7,  \
    .init_charge_volt = TOUCH_INIT_CHARGE_VOLT_DEFAULT,  \
}


template<uint8_t ROWS, uint8_t COLS>
struct TouchpadPosition {
    static_assert(ROWS + COLS <= 14, "Total channels (ROWS + COLS) cannot exceed 14");
    static constexpr uint8_t CHANNELS = ROWS + COLS;

    int32_t readings[CHANNELS];
    uint32_t timestamp;

    void read(float &x, float &y, float &z) {
        float sum_x = 0, sum_y = 0, centroid_x = 0, centroid_y = 0;

        // Calculate weights for centroid calculation
        // Weights are distributed evenly from -(N-1)/2 to +(N-1)/2
        for (uint8_t i = 0; i < ROWS; i++) {
            float weight = (float)i - (float)(ROWS - 1) / 2.0f;
            sum_x += readings[i];
            centroid_x += readings[i] * weight;
        }

        for (uint8_t i = 0; i < COLS; i++) {
            float weight = (float)i - (float)(COLS - 1) / 2.0f;
            sum_y += readings[ROWS + i];
            centroid_y += readings[ROWS + i] * weight;
        }

        x = (sum_x > 0) ? (centroid_x / sum_x) : 0.0f;
        y = (sum_y > 0) ? (centroid_y / sum_y) : 0.0f;
        z = (sum_x + sum_y) / 2000.0f;
    }
};

template<uint8_t ROWS = 4, uint8_t COLS = 4>
class Touchpad {
    static_assert(ROWS + COLS <= 14, "Total channels (ROWS + COLS) cannot exceed 14");
    static_assert(ROWS > 0 && COLS > 0, "ROWS and COLS must be greater than 0");

    public:
        static constexpr uint8_t CHANNELS = ROWS + COLS;
        using Position = TouchpadPosition<ROWS, COLS>;

        Touchpad(touch_sensor_handle_t& sens_handle, uint8_t channel_id[CHANNELS], QueueHandle_t& position_queue)
            : sens_handle_(sens_handle), position_queue_(position_queue) {
            for (uint8_t i = 0; i < CHANNELS; i++) {
                channel_id_[i] = channel_id[i];
            }
        }

        void initTouch();
        void sendPosition();

        uint8_t getRows() const { return ROWS; }
        uint8_t getCols() const { return COLS; }
        uint8_t getChannels() const { return CHANNELS; }

    private:
        touch_sensor_handle_t& sens_handle_;
        uint8_t channel_id_[CHANNELS];
        QueueHandle_t& position_queue_;

        touch_channel_handle_t chan_handle_[CHANNELS];
        int32_t readings_[CHANNELS];
        uint32_t benchmark_[CHANNELS];
};

// Template callback wrapper function
template<uint8_t ROWS, uint8_t COLS>
bool touchpad_on_scan_done_callback(touch_sensor_handle_t sens_handle, const touch_active_event_data_t *event, void *user_ctx) {
    Touchpad<ROWS, COLS> *touchpad = (Touchpad<ROWS, COLS> *)user_ctx;
    touchpad->sendPosition();
    return false;
}


template<uint8_t ROWS, uint8_t COLS>
void Touchpad<ROWS, COLS>::initTouch() {
    touch_channel_config_t chan_cfg = EXAMPLE_TOUCH_CHAN_CFG_DEFAULT();
    for (uint8_t i = 0; i < CHANNELS; i++) {
        touch_sensor_new_channel(sens_handle_, channel_id_[i], &chan_cfg, &chan_handle_[i]);
    }

    touch_event_callbacks_t callbacks = {
        .on_scan_done = touchpad_on_scan_done_callback<ROWS, COLS>,
    };
    touch_sensor_register_callbacks(sens_handle_, &callbacks, this);
}

template<uint8_t ROWS, uint8_t COLS>
void Touchpad<ROWS, COLS>::sendPosition() {
    BaseType_t xHigherPriorityTaskWoken = pdFALSE;
    Position position;
    uint32_t data;

    for(uint8_t i = 0; i < CHANNELS; i++) {
        touch_channel_read_data(chan_handle_[i], TOUCH_CHAN_DATA_TYPE_BENCHMARK, &benchmark_[i]);
        touch_channel_read_data(chan_handle_[i], TOUCH_CHAN_DATA_TYPE_SMOOTH, &data);
        position.readings[i] = data - benchmark_[i];
    }
    position.timestamp = micros();
    xQueueOverwriteFromISR(position_queue_, &position, &xHigherPriorityTaskWoken);

    if (xHigherPriorityTaskWoken) {
        portYIELD_FROM_ISR();
    }
}

