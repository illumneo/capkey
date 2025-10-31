#pragma once
#include "Arduino.h"
#include "touchpad.h"
#include "gestureDetector.h"
#include "keyMap.h"

template<uint8_t ROWS = 4, uint8_t COLS = 4>
class Gesture {
public:
    using Position = TouchpadPosition<ROWS, COLS>;

    Gesture(QueueHandle_t& position_queue)
        : position_queue_(position_queue) {
    }

    void init() {
        keymap_.init();
    }

    void tick();

private:
    QueueHandle_t& position_queue_;
    Position position_;

    GestureDetector detector_;
    KeyMap keymap_;
};

// Template method implementation
template<uint8_t ROWS, uint8_t COLS>
void Gesture<ROWS, COLS>::tick() {
    Position position;
    float x, y, z;

    xQueueReceive(position_queue_, &position, portMAX_DELAY);
    position.read(x, y, z);

    // Update gesture detector
    bool gesture_detected = detector_.update(x, y, z, position.timestamp);

    if (gesture_detected) {
        DetectedGesture detected = detector_.getDetectedGesture();
        // printGesture(detected);

        // Execute action for this gesture
        keymap_.execute(detected.grid_position, detected.type, detected.direction);

        // // Debug output
        // printf("Gesture detected: type=%d, dir=%d, pos=%d\n",
        //        detected.type, detected.direction, detected.grid_position);
    }

    // Optional: Log high Z values for debugging
    // if (z > 0.5f) {
    //     printf("%ld, %f, %f, %f\n", position.timestamp, x, y, z);
    // }
}
