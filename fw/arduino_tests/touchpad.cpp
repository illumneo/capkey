#include "touchpad.h"

#define EXAMPLE_TOUCH_CHAN_CFG_DEFAULT()        {  \
    .active_thresh = {2000},  \
    .charge_speed = TOUCH_CHARGE_SPEED_7,  \
    .init_charge_volt = TOUCH_INIT_CHARGE_VOLT_DEFAULT,  \
}

uint32_t scans = 0;

bool touchpad_on_scan_done_callback(touch_sensor_handle_t sens_handle, const touch_active_event_data_t *event, void *user_ctx) {
    Touchpad *touchpad = (Touchpad *)user_ctx;
    touchpad->processInputs();
    scans++;
    return false;
}



Touchpad::Touchpad(touch_sensor_handle_t& sens_handle, uint8_t channel_id[8]) : sens_handle_(sens_handle) {
    for (int i = 0; i < 8; i++) {
        channel_id_[i] = channel_id[i];
    }
}

void Touchpad::initTouch() {
    touch_channel_config_t chan_cfg = EXAMPLE_TOUCH_CHAN_CFG_DEFAULT();
    for (int i = 0; i < 8; i++) {
        touch_sensor_new_channel(sens_handle_, channel_id_[i], &chan_cfg, &chan_handle_[i]);
    }

    touch_event_callbacks_t callbacks = {
        .on_scan_done = touchpad_on_scan_done_callback,
    };
    touch_sensor_register_callbacks(sens_handle_, &callbacks, this);
}

void Touchpad::processInputs() {
    uint32_t data;
    for(int i = 0; i < 8; i++) {
        touch_channel_read_data(chan_handle_[i], TOUCH_CHAN_DATA_TYPE_BENCHMARK, &benchmark_[i]);
        touch_channel_read_data(chan_handle_[i], TOUCH_CHAN_DATA_TYPE_SMOOTH, &data);
        readings_[i] = data - benchmark_[i];
    }
}

void Touchpad::calculatePosition() {
    int32_t sum_x = 0, sum_y = 0, centroid_x = 0, centroid_y = 0;
    float weight[4] {-1.5, -.5, .5, 1.5};
    for (int i = 0; i < 4; i++) {
      sum_x += readings_[i];
      sum_y += readings_[4 + i];

      centroid_x += readings_[i] * weight[i];
      centroid_y += readings_[4 + i] * weight[i];
    }

    x_ = 1.0 * centroid_x / sum_x;
    y_ = 1.0 * centroid_y / sum_y;
    z_ = (sum_x + sum_y) / 2000.0;
}

void Touchpad::read(float &x, float &y, float &z) {
    calculatePosition();
    x = this->x_;
    y = this->y_;
    z = this->z_;
}
