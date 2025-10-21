#include "gesture.h"

// Lone function to pass into xTaskCreate to run Gesture::tick()
void gestureTask(void *pvParameters) {
    Gesture *gesture = (Gesture *)pvParameters;
    while (1) {
        gesture->tick();
    }
}

Gesture::Gesture(QueueHandle_t& position_queue)
    : position_queue_(position_queue) {
}

void Gesture::init() {
    keymap_.init();
}

void Gesture::tick() {
    TouchpadPosition position;
    float x, y, z;

    xQueueReceive(position_queue_, &position, portMAX_DELAY);
    position.read(x, y, z);

    // Update gesture detector
    bool gesture_detected = detector_.update(x, y, z, position.timestamp);

    if (gesture_detected) {
        DetectedGesture detected = detector_.getDetectedGesture();

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
