#include "gesture.h"

void printGesture(DetectedGesture detected);


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

const char* gestureTypeStr(int type) {
    switch (type) {
        case 0: return "NONE";
        case 1: return "TAP";
        case 2: return "HOLD";
        case 3: return "SWIPE_S";
        case 4: return "SWIPE_L";
        case 5: return "SWIPE_RET";
        case 6: return "CW_CIRCLE";
        case 7: return "CCW_CIRCLE";
        default: return "?";
    }
}

const char* directionStr(int dir) {
    switch (dir) {
        case 0: return "CENTER";
        case 1: return "N";
        case 2: return "NE";
        case 3: return "E";
        case 4: return "SE";
        case 5: return "S";
        case 6: return "SW";
        case 7: return "W";
        case 8: return "NW";
        default: return "?";
    }
}

void printGesture(DetectedGesture detected) {
    printf("Gesture detected: type=%s (%d), dir=%s (%d), pos=%d\n",
           gestureTypeStr(detected.type), detected.type,
           directionStr(detected.direction), detected.direction,
           detected.grid_position);
}
