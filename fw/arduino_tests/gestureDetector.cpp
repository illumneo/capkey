#include "gestureDetector.h"

GestureDetector::GestureDetector() {}

bool GestureDetector::update(float x, float y, float z, uint32_t timestamp) {
    current_x_ = x;
    current_y_ = y;
    current_z_ = z;
    current_time_ = timestamp;

    switch (state_) {
        case STATE_IDLE:
            if (z > TOUCH_THRESHOLD) {
                // Touch started
                state_ = STATE_TRACKING;
                start_x_ = x;
                start_y_ = y;
                start_grid_pos_ = getGridPosition(x, y);
                start_time_ = timestamp;
                max_distance_ = 0;
                path_head_ = 0;
                path_count_ = 0;
                circle_cumulative_angle_ = 0;
                circle_point_count_ = 0;
                swipe_detected_ = false;

                addPathPoint(x, y);
            }
            break;

        case STATE_TRACKING:
            if (z < TOUCH_RELEASE_THRESHOLD) {
                // Touch released - analyze gesture
                detected_gesture_ = analyzeGesture();
                state_ = STATE_GESTURE_DETECTED;
                return true;
            } else {
                // Continue tracking
                state_ = STATE_TRACKING;

                addPathPoint(x, y);

                // Update max distance
                float dx = x - start_x_;
                float dy = y - start_y_;
                float distance = calculateDistance(dx, dy);
                if (distance > max_distance_) {
                    max_distance_ = distance;
                    max_distance_x_ = x;
                    max_distance_y_ = y;
                    max_distance_angle_ = calculateAngle(dx, dy);
                }

                // Update circle tracking if we have enough points
                if (path_count_ >= 3) {
                    updateCircleTracking(x, y);
                }

                // Update swipe-return tracking
                updateSwipeReturnTracking(x, y);
            }
            break;

        case STATE_GESTURE_DETECTED:
            // Wait for touch to be released before going back to idle
            if (z < TOUCH_RELEASE_THRESHOLD) {
                state_ = STATE_IDLE;
            }
            break;
    }

    return false;
}

void GestureDetector::reset() {
    state_ = STATE_IDLE;
    detected_gesture_ = DetectedGesture();
}

uint8_t GestureDetector::getGridPosition(float x, float y) const {
    // Convert x, y coordinates to grid position (0-8 for 3x3 grid)
    // Assumes origin at center of grid
    int col = 1;  // Default to middle column
    if (x < -GRID_CELL_WIDTH/2) col = 0;
    else if (x > GRID_CELL_WIDTH/2) col = 2;

    int row = 1;  // Default to middle row
    if (y < -GRID_CELL_HEIGHT/2) row = 0;
    else if (y > GRID_CELL_HEIGHT/2) row = 2;

    return row + (col  * GRID_COLS);
}

void GestureDetector::addPathPoint(float x, float y) {
    path_history_[path_head_] = PathPoint(x, y);
    path_head_ = (path_head_ + 1) % PATH_HISTORY_SIZE;
    if (path_count_ < PATH_HISTORY_SIZE) {
        path_count_++;
    }
}

void GestureDetector::updateCircleTracking(float x, float y) {
    // Calculate center as average of all path points
    float sum_x = 0, sum_y = 0;
    for (uint8_t i = 0; i < path_count_; i++) {
        sum_x += path_history_[i].x;
        sum_y += path_history_[i].y;
    }
    circle_center_x_ = sum_x / path_count_;
    circle_center_y_ = sum_y / path_count_;

    // Calculate angle from center to current point
    float dx = x - circle_center_x_;
    float dy = y - circle_center_y_;
    float current_angle = calculateAngle(dx, dy);

    // Update cumulative angle if we have a previous angle
    if (circle_point_count_ > 0) {
        float angle_delta = angleDifference(current_angle, circle_last_angle_);
        circle_cumulative_angle_ += angle_delta;
    }

    circle_last_angle_ = current_angle;
    circle_point_count_++;
}

void GestureDetector::updateSwipeReturnTracking(float x, float y) {
    // Check if we've swiped far enough to start tracking return
    if (!swipe_detected_ && max_distance_ > SWIPE_RETURN_MIN_DISTANCE) {
        swipe_detected_ = true;
        swipe_angle_ = max_distance_angle_;
    }

    // If swipe detected, track current distance from max point
    if (swipe_detected_) {
        float dx = x - max_distance_x_;
        float dy = y - max_distance_y_;
        float distance = calculateDistance(dx, dy);

        // Check if we're moving back toward start
        if (distance > SWIPE_RETURN_MIN_RETURN_DISTANCE) {
            float current_angle = calculateAngle(dx, dy);
            // Check if angle is roughly opposite to swipe direction
            float angle_diff = fabs(angleDifference(current_angle, swipe_angle_));
            // Opposite direction is within tolerance of 180 degrees
            if (fabs(angle_diff - 180.0f) < SWIPE_RETURN_ANGLE_TOLERANCE) {
                // This looks like a swipe-return gesture
            }
        }
    }
}

DetectedGesture GestureDetector::analyzeGesture() {
    uint32_t duration = current_time_ - start_time_;

    // Priority order: Swipe-return > Circle > Long swipe > Hold > Swipe > Tap
    // Note: Swipe-return checked first to avoid confusion with circles

    // Check for swipe-return
    DetectedGesture swipe_return = detectSwipeReturn();
    if (swipe_return.type != GESTURE_NONE) return swipe_return;

    // Check for circle (requires consistent radius and rotation)
    DetectedGesture circle = detectCircle();
    if (circle.type != GESTURE_NONE) return circle;

    // Check for long swipe
    DetectedGesture long_swipe = detectLongSwipe();
    if (long_swipe.type != GESTURE_NONE) return long_swipe;

    // Check for hold
    DetectedGesture hold = detectHold();
    if (hold.type != GESTURE_NONE) return hold;

    // Check for short swipe
    DetectedGesture swipe = detectSwipe();
    if (swipe.type != GESTURE_NONE) return swipe;

    // Default to tap
    return detectTap();
}

DetectedGesture GestureDetector::detectTap() {
    if (max_distance_ < SWIPE_MIN_DISTANCE) {
        uint32_t duration = current_time_ - start_time_;
        if (duration < HOLD_MIN_DURATION) {
            return DetectedGesture(GESTURE_TAP, DIR_CENTER, start_grid_pos_);
        }
    }
    return DetectedGesture();
}

DetectedGesture GestureDetector::detectHold() {
    uint32_t duration = current_time_ - start_time_;
    if (duration >= HOLD_MIN_DURATION && max_distance_ < SWIPE_MIN_DISTANCE) {
        return DetectedGesture(GESTURE_HOLD, DIR_CENTER, start_grid_pos_);
    }
    return DetectedGesture();
}

DetectedGesture GestureDetector::detectSwipe() {
    if (max_distance_ >= SWIPE_MIN_DISTANCE && max_distance_ < LONG_SWIPE_DISTANCE) {
        Direction dir = getDirectionFromAngle(max_distance_angle_);
        return DetectedGesture(GESTURE_SWIPE_SHORT, dir, start_grid_pos_);
    }
    return DetectedGesture();
}

DetectedGesture GestureDetector::detectLongSwipe() {
    if (max_distance_ >= LONG_SWIPE_DISTANCE) {
        Direction dir = getDirectionFromAngle(max_distance_angle_);
        return DetectedGesture(GESTURE_SWIPE_LONG, dir, start_grid_pos_);
    }
    return DetectedGesture();
}

DetectedGesture GestureDetector::detectSwipeReturn() {
    if (!swipe_detected_) return DetectedGesture();

    // Check if we swiped out and came back
    if (max_distance_ >= SWIPE_RETURN_MIN_DISTANCE) {
        // Check current distance from start
        float dx = current_x_ - start_x_;
        float dy = current_y_ - start_y_;
        float current_distance = calculateDistance(dx, dy);

        // If we're now much closer to start than max distance, it's a return
        if (current_distance < max_distance_ * 0.5f) {
            Direction dir = getDirectionFromAngle(swipe_angle_);
            return DetectedGesture(GESTURE_SWIPE_RETURN, dir, start_grid_pos_);
        }
    }
    return DetectedGesture();
}

DetectedGesture GestureDetector::detectCircle() {
    // Need enough points for a circle
    if (circle_point_count_ < CIRCLE_MIN_POINTS) return DetectedGesture();

    // Check if cumulative angle is enough for a circle
    float abs_angle = fabs(circle_cumulative_angle_);
    if (abs_angle >= CIRCLE_MIN_ARC_ANGLE) {
        // Calculate average radius to check variance
        float sum_radius = 0;
        for (uint8_t i = 0; i < path_count_; i++) {
            float dx = path_history_[i].x - circle_center_x_;
            float dy = path_history_[i].y - circle_center_y_;
            sum_radius += calculateDistance(dx, dy);
        }
        float avg_radius = sum_radius / path_count_;

        // Check radius variance
        float variance = 0;
        for (uint8_t i = 0; i < path_count_; i++) {
            float dx = path_history_[i].x - circle_center_x_;
            float dy = path_history_[i].y - circle_center_y_;
            float radius = calculateDistance(dx, dy);
            variance += fabs(radius - avg_radius);
        }
        variance /= path_count_;

        if (variance < CIRCLE_MAX_RADIUS_VARIANCE) {
            // It's a circle! Determine direction
            GestureType type = (circle_cumulative_angle_ < 0) ? GESTURE_CIRCLE_CW : GESTURE_CIRCLE_CCW;
            return DetectedGesture(type, DIR_CENTER, start_grid_pos_);
        }
    }
    return DetectedGesture();
}

Direction GestureDetector::getDirectionFromAngle(float angle_deg) const {
    // Normalize angle to 0-360
    angle_deg = normalizeAngle(angle_deg);

    // Map angle to 8 directions
    // South = 0°, East = 90°, North = 180°, West = 270°
    if (angle_deg >= 337.5f || angle_deg < 22.5f) return DIR_SOUTH;
    if (angle_deg >= 22.5f && angle_deg < 67.5f) return DIR_SOUTHEAST;
    if (angle_deg >= 67.5f && angle_deg < 112.5f) return DIR_EAST;
    if (angle_deg >= 112.5f && angle_deg < 157.5f) return DIR_NORTHEAST;
    if (angle_deg >= 157.5f && angle_deg < 202.5f) return DIR_NORTH;
    if (angle_deg >= 202.5f && angle_deg < 247.5f) return DIR_NORTHWEST;
    if (angle_deg >= 247.5f && angle_deg < 292.5f) return DIR_WEST;
    return DIR_SOUTHWEST;
}

float GestureDetector::calculateAngle(float dx, float dy) const {
    // Calculate angle in degrees (0 = South, 90 = East)
    float angle_rad = atan2(dy, dx);
    return angle_rad * 180.0f / M_PI;
}

float GestureDetector::calculateDistance(float dx, float dy) const {
    return sqrt(dx * dx + dy * dy);
}

float GestureDetector::normalizeAngle(float angle) const {
    while (angle < 0) angle += 360.0f;
    while (angle >= 360.0f) angle -= 360.0f;
    return angle;
}

float GestureDetector::angleDifference(float angle1, float angle2) const {
    float diff = angle1 - angle2;
    while (diff > 180.0f) diff -= 360.0f;
    while (diff < -180.0f) diff += 360.0f;
    return diff;
}

