#include "gesture.h"

void printGesture(DetectedGesture detected);

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
