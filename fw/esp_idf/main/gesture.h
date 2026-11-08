#pragma once

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

#include "gestureDetector.h"
#include "keyMap.h"
#include "touchpad.h"

void gestureTask(void *pvParameters);

class Gesture {
public:
    explicit Gesture(QueueHandle_t position_queue);

    void init();
    void tick();

private:
    QueueHandle_t position_queue_;
    GestureDetector detector_;
    KeyMap keymap_;
};
