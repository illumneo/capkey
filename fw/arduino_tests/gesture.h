#pragma once
#include "Arduino.h"
#include "touchpad.h"
#include "gestureDetector.h"
#include "keyMap.h"

void gestureTask(void *pvParameters);

class Gesture {
public:
    Gesture(QueueHandle_t& position_queue);

    void init();
    void tick();

private:
    QueueHandle_t& position_queue_;
    TouchpadPosition position_;

    GestureDetector detector_;
    KeyMap keymap_;
};
