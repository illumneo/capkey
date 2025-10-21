#pragma once
#include "gestureTypes.h"
#include "gestureConfig.h"
#include <math.h>

enum GestureState {
    STATE_IDLE,
    STATE_TRACKING,
    STATE_GESTURE_DETECTED
};

class GestureDetector {
public:
    GestureDetector();

    // Main update function - call this with each new sensor reading
    // Returns true if a gesture was detected
    bool update(float x, float y, float z, uint32_t timestamp);

    // Get the most recently detected gesture
    DetectedGesture getDetectedGesture() const { return detected_gesture_; }

    // Reset the detector state
    void reset();

private:
    // State machine
    GestureState state_ = STATE_IDLE;

    // Tracking data
    float start_x_ = 0.0f;
    float start_y_ = 0.0f;
    uint8_t start_grid_pos_ = 0;
    uint32_t start_time_ = 0;

    float current_x_ = 0.0f;
    float current_y_ = 0.0f;
    float current_z_ = 0.0f;
    uint32_t current_time_ = 0;

    float max_distance_ = 0.0f;
    float max_distance_x_ = 0.0f;
    float max_distance_y_ = 0.0f;  // Point of maximum distance
    float max_distance_angle_ = 0.0f;

    // Path history (circular buffer)
    PathPoint path_history_[PATH_HISTORY_SIZE];
    uint8_t path_head_ = 0;
    uint8_t path_count_ = 0;

    // Circle detection
    float circle_cumulative_angle_ = 0.0f;
    float circle_last_angle_ = 0.0f;
    float circle_center_x_ = 0.0f;
    float circle_center_y_ = 0.0f;
    uint8_t circle_point_count_ = 0;

    // Swipe return detection
    bool swipe_detected_ = false;
    float swipe_angle_ = 0.0f;

    // Detected gesture result
    DetectedGesture detected_gesture_;

    // Helper functions
    uint8_t getGridPosition(float x, float y) const;
    void addPathPoint(float x, float y);
    void updateCircleTracking(float x, float y);
    void updateSwipeReturnTracking(float x, float y);

    DetectedGesture analyzeGesture();
    DetectedGesture detectTap();
    DetectedGesture detectHold();
    DetectedGesture detectSwipe();
    DetectedGesture detectLongSwipe();
    DetectedGesture detectSwipeReturn();
    DetectedGesture detectCircle();

    Direction getDirectionFromAngle(float angle_deg) const;
    float calculateAngle(float dx, float dy) const;
    float calculateDistance(float dx, float dy) const;
    float normalizeAngle(float angle) const;
    float angleDifference(float angle1, float angle2) const;
};

