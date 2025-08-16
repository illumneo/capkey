#pragma once
#include "Arduino.h"
#include "USB.h"
#include "USBHIDKeyboard.h"


#include "touchpad.h"


void gestureTask(void *pvParameters);

enum GestureState {
    WAITING_FOR_TOUCH,
    TRACKING_GESTURE,
    DETECTING_GESTURE
  };

class Gesture {
    public:
        Gesture(QueueHandle_t& position_queue);

        void init();
        void tick();
        void gestureFSM(float x, float y, float z);

    private:
        QueueHandle_t& position_queue_;
        TouchpadPosition position_;
        USBHIDKeyboard keyboard_;
        GestureState state_{WAITING_FOR_TOUCH};

        bool keyboard_on_{true}; // Used to disable USB output so Serial port remains enabled

};
