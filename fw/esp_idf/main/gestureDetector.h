#pragma once

#include <cstdint>

#include "gestureConfig.h"
#include "gestureTypes.h"

enum GestureState {
    STATE_IDLE,
    STATE_TRACKING
};

class GestureDetector {
public:
    static constexpr uint8_t kInvalidGrid = 0xFF;

    GestureDetector();

    bool update(float x, float y, float z, uint32_t timestamp);
    bool isIdle() const { return state_ == STATE_IDLE && !onset_pending_; }
    DetectedGesture getDetectedGesture() const { return detected_gesture_; }
    float maxDistance() const { return max_distance_; }
    uint8_t startGrid() const { return start_grid_pos_; }
    float startX() const { return start_x_; }
    float startY() const { return start_y_; }
    float maxDx() const { return max_distance_dx_; }
    float maxDy() const { return max_distance_dy_; }
    float maxX() const { return max_distance_x_; }
    float maxY() const { return max_distance_y_; }
    float maxAngle() const { return max_distance_angle_; }
    // Contact endpoint is retained at release; the release sample may collapse.
    float endX() const { return current_x_; }
    float endY() const { return current_y_; }
    float pathLength() const { return circle_path_length_; }
    uint32_t durationUs() const { return current_time_ - start_time_; }
    void reset();

private:
    GestureState state_ = STATE_IDLE;
    bool onset_pending_ = false;

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
    float max_distance_y_ = 0.0f;
    float max_distance_dx_ = 0.0f;
    float max_distance_dy_ = 0.0f;
    float max_distance_angle_ = 0.0f;

    PathPoint path_history_[PATH_HISTORY_SIZE];
    uint8_t path_head_ = 0;
    uint8_t path_count_ = 0;

    float circle_cumulative_angle_ = 0.0f;
    float circle_last_angle_ = 0.0f;
    float circle_heading_x_ = 0.0f;
    float circle_heading_y_ = 0.0f;
    float circle_center_x_ = 0.0f;
    float circle_center_y_ = 0.0f;
    uint8_t circle_point_count_ = 0;
    float circle_twice_area_ = 0.0f;
    float circle_absolute_twice_area_ = 0.0f;
    float circle_path_length_ = 0.0f;

    bool swipe_detected_ = false;
    float swipe_angle_ = 0.0f;
    float swipe_dx_ = 0.0f;
    float swipe_dy_ = 0.0f;

    DetectedGesture detected_gesture_;

    uint8_t getGridPosition(float x, float y) const;
    void addPathPoint(float x, float y);
    void updateCircleTracking(float x, float y);
    void updateSwipeReturnTracking(float x, float y);

    DetectedGesture analyzeGesture();
    DetectedGesture detectTap();
    DetectedGesture detectHold();
    DetectedGesture detectSwipe();
    DetectedGesture detectLongSwipe();
    DetectedGesture detectEdgeSwipe();
    DetectedGesture detectSwipeReturn();
    DetectedGesture detectCircle();

    bool supportsEdgeDirection(Direction direction) const;
    bool nearLeftEdge() const;
    bool nearRightEdge() const;
    bool nearTopEdge() const;
    bool nearBottomEdge() const;

    Direction getDirectionFromAngle(float angle_deg) const;
    Direction getDirectionFromVector(float dx, float dy) const;
    float calculateAngle(float dx, float dy) const;
    float calculateDistance(float dx, float dy) const;
    float normalizeAngle(float angle) const;
    float angleDifference(float angle1, float angle2) const;
};
