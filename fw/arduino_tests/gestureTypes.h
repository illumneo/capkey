#pragma once
#include <stdint.h>

// Gesture types that can be detected
enum GestureType {
    GESTURE_NONE = 0,
    GESTURE_TAP,
    GESTURE_HOLD,
    GESTURE_SWIPE_SHORT,
    GESTURE_SWIPE_LONG,
    GESTURE_SWIPE_RETURN,
    GESTURE_CIRCLE_CW,
    GESTURE_CIRCLE_CCW
};

// Directional components for gestures (where applicable)
enum Direction {
    DIR_CENTER = 0,
    DIR_NORTH,
    DIR_NORTHEAST,
    DIR_EAST,
    DIR_SOUTHEAST,
    DIR_SOUTH,
    DIR_SOUTHWEST,
    DIR_WEST,
    DIR_NORTHWEST
};

// Result of gesture detection
struct DetectedGesture {
    GestureType type;
    Direction direction;
    uint8_t grid_position;

    DetectedGesture() : type(GESTURE_NONE), direction(DIR_CENTER), grid_position(0) {}
    DetectedGesture(GestureType t, Direction d, uint8_t pos)
        : type(t), direction(d), grid_position(pos) {}
};

// Path point for tracking gesture trajectory
struct PathPoint {
    float x;
    float y;
    PathPoint() : x(0), y(0) {}
    PathPoint(float x_, float y_) : x(x_), y(y_) {}
};

