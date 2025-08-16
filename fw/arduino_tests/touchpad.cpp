#include "touchpad.h"

#define EXAMPLE_TOUCH_CHAN_CFG_DEFAULT()        {  \
    .active_thresh = {2000},  \
    .charge_speed = TOUCH_CHARGE_SPEED_7,  \
    .init_charge_volt = TOUCH_INIT_CHARGE_VOLT_DEFAULT,  \
}

uint32_t scans = 0;

bool touchpad_on_scan_done_callback(touch_sensor_handle_t sens_handle, const touch_active_event_data_t *event, void *user_ctx) {
    Touchpad *touchpad = (Touchpad *)user_ctx;
    touchpad->sendPosition();
    scans++;
    return false;
}


/******************************************
* TouchpadPosition
*******************************************/

void TouchpadPosition::read(float &x, float &y, float &z) {
    int32_t sum_x = 0, sum_y = 0, centroid_x = 0, centroid_y = 0;
    float weight[4] {-1.5, -.5, .5, 1.5};
    for (int i = 0; i < 4; i++) {
        sum_x += readings[i];
        sum_y += readings[4 + i];
        centroid_x += readings[i] * weight[i];
        centroid_y += readings[4 + i] * weight[i];
    }

    x = 1.0 * centroid_x / sum_x;
    y = 1.0 * centroid_y / sum_y;
    z = (sum_x + sum_y) / 2000.0;
}



/******************************************
* Touchpad
*******************************************/


Touchpad::Touchpad(touch_sensor_handle_t& sens_handle, uint8_t channel_id[8], QueueHandle_t& position_queue) : sens_handle_(sens_handle), position_queue_(position_queue) {
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

void Touchpad::sendPosition() {
    BaseType_t xHigherPriorityTaskWoken = pdFALSE;
    TouchpadPosition position;
    uint32_t data;

    for(int i = 0; i < 8; i++) {
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

