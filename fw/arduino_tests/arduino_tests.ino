#include "driver/touch_sens.h"
#include "touchpad.h"
#include "gesture.h"

#define EXAMPLE_TOUCH_SAMPLE_CFG_DEFAULT()      {TOUCH_SENSOR_V2_DEFAULT_SAMPLE_CONFIG(500, TOUCH_VOLT_LIM_L_0V5, TOUCH_VOLT_LIM_H_2V2)}

QueueHandle_t touchpad_position_queue;

// The touch channel IDs that used in this example
// For the corresponding GPIOs of these channel, please refer to 'touch_sensor_channel.h'
static uint8_t s_channel_id[8] = {
    // Columns
    11,
    12,
    3,
    4,
    // Rows
    9,
    10,
    2,
    1,

};

/* Handles of touch sensor */
touch_sensor_handle_t sens_handle = NULL;

Touchpad touchpad(sens_handle, s_channel_id, touchpad_position_queue);

Gesture gesture(touchpad_position_queue);

void initTouch() {
    /* Step 1: Create a new touch sensor controller handle with default sample configuration */
    touch_sensor_sample_config_t sample_cfg[TOUCH_SAMPLE_CFG_NUM] = EXAMPLE_TOUCH_SAMPLE_CFG_DEFAULT();
    touch_sensor_config_t sens_cfg = TOUCH_SENSOR_DEFAULT_BASIC_CONFIG(1, sample_cfg);
    touch_sensor_new_controller(&sens_cfg, &sens_handle);

    /* Step 2: Initialize touchpad channels */
    touchpad.initTouch();

    /* Step 3: Configure the default filter for the touch sensor */
    touch_sensor_filter_config_t filter_cfg = TOUCH_SENSOR_DEFAULT_FILTER_CONFIG();
    touch_sensor_config_filter(sens_handle, &filter_cfg);

    /* Step 4: Enable the touch sensor */
    touch_sensor_enable(sens_handle);

    /* Step 5: Start continuous scanning */
    touch_sensor_start_continuous_scanning(sens_handle);
}

void setup() {
    Serial.begin(115200);

    // Create queue for passing touch data from ISR to gesture task
    touchpad_position_queue = xQueueCreate(1, sizeof(TouchpadPosition));

    // Initialize touch sensor hardware
    initTouch();

    // Initialize gesture detection system (includes USB keyboard)
    gesture.init();

    // Create FreeRTOS task for gesture processing
    xTaskCreate(gestureTask, "Gesture Task", 4096, &gesture, 10, NULL);

    Serial.println("Setup complete. Gesture detection active.");
    Serial.println("See GESTURE_SYSTEM.md for documentation.");
}

void loop() {
    delay(1000);
}
