#include "gestureDetector.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <inttypes.h>

#include "esp_log.h"
#include "gestureLayout.h"

namespace {
constexpr float kPi = 3.14159265358979323846f;
constexpr const char *kTag = "gesture_det";
}

GestureDetector::GestureDetector() = default;

bool GestureDetector::update(float x, float y, float z, uint32_t timestamp) {
    // A release reports when contact ended, not a reliable position. Keep the
    // last in-contact endpoint for direction and swipe-return classification.
    if (state_ != STATE_TRACKING || z >= TOUCH_RELEASE_THRESHOLD) {
        current_x_ = x;
        current_y_ = y;
    }
    current_z_ = z;
    current_time_ = timestamp;

    switch (state_) {
        case STATE_IDLE:
            if (z > TOUCH_THRESHOLD) {
                // The first active scan can precede a stable centroid as the
                // finger lands. Confirm on the next active scan, retaining
                // the first crossing's time for tap/hold duration.
                if (!onset_pending_) {
                    onset_pending_ = true;
                    start_time_ = timestamp;
                    break;
                }
                onset_pending_ = false;
                const uint8_t grid = getGridPosition(x, y);
                if (grid == kInvalidGrid) {
                    return false;
                }

                const int32_t z_milli = static_cast<int32_t>(z * 1000.0f);
                const int32_t x_milli = static_cast<int32_t>(x * 1000.0f);
                const int32_t y_milli = static_cast<int32_t>(y * 1000.0f);
                ESP_LOGI(kTag,
                               "Idle->Tracking (x1e3) z=%" PRId32 " start=(%" PRId32 ",%" PRId32 ") grid=%u",
                               z_milli, x_milli, y_milli,
                               static_cast<unsigned>(grid));
                state_ = STATE_TRACKING;
                start_x_ = x;
                start_y_ = y;
                start_grid_pos_ = grid;
                max_distance_ = 0.0f;
                max_distance_x_ = x;
                max_distance_y_ = y;
                max_distance_dx_ = 0.0f;
                max_distance_dy_ = 0.0f;
                max_distance_angle_ = 0.0f;
                path_head_ = 0;
                path_count_ = 0;
                circle_cumulative_angle_ = 0.0f;
                circle_heading_x_ = x;
                circle_heading_y_ = y;
                circle_point_count_ = 0;
                circle_twice_area_ = 0.0f;
                circle_absolute_twice_area_ = 0.0f;
                circle_path_length_ = 0.0f;
                swipe_detected_ = false;
                swipe_angle_ = 0.0f;
                swipe_dx_ = 0.0f;
                swipe_dy_ = 0.0f;

                addPathPoint(x, y);
            } else {
                onset_pending_ = false;
            }
            break;

        case STATE_TRACKING:
            if (z < TOUCH_RELEASE_THRESHOLD) {
                detected_gesture_ = analyzeGesture();
                const int32_t z_milli = static_cast<int32_t>(z * 1000.0f);
                const int32_t dist_milli = static_cast<int32_t>(max_distance_ * 1000.0f);
                ESP_LOGI(kTag,
                               "Tracking->Detected (x1e3) z=%" PRId32 " duration=%" PRIu32
                               " max_dist=%" PRId32,
                               z_milli, current_time_ - start_time_, dist_milli);
                // This sample already confirms release. The next active
                // sample may start a new onset, without an extra idle scan.
                state_ = STATE_IDLE;
                return true;
            } else {
                const int32_t z_milli = static_cast<int32_t>(z * 1000.0f);
                const int32_t x_milli = static_cast<int32_t>(x * 1000.0f);
                const int32_t y_milli = static_cast<int32_t>(y * 1000.0f);
                const int32_t dist_milli = static_cast<int32_t>(max_distance_ * 1000.0f);
                ESP_LOGD(kTag,
                               "Track (x1e3) z=%" PRId32 " x=%" PRId32 " y=%" PRId32
                               " max_dist=%" PRId32,
                               z_milli, x_milli, y_milli, dist_milli);
                addPathPoint(x, y);

                const float dx = x - start_x_;
                const float dy = y - start_y_;
                const float distance = calculateDistance(dx, dy);
                if (distance > max_distance_) {
                    max_distance_ = distance;
                    max_distance_x_ = x;
                    max_distance_y_ = y;
                    max_distance_dx_ = dx;
                    max_distance_dy_ = dy;
                    max_distance_angle_ = calculateAngle(dx, dy);
                }

                if (path_count_ >= 2) {
                    updateCircleTracking(x, y);
                }

                updateSwipeReturnTracking(x, y);
            }
            break;

    }

    return false;
}

void GestureDetector::reset() {
    state_ = STATE_IDLE;
    onset_pending_ = false;
    detected_gesture_ = DetectedGesture();
    start_x_ = 0.0f;
    start_y_ = 0.0f;
    start_grid_pos_ = 0;
    start_time_ = 0;
    current_x_ = 0.0f;
    current_y_ = 0.0f;
    current_z_ = 0.0f;
    current_time_ = 0;
    max_distance_ = 0.0f;
    max_distance_x_ = 0.0f;
    max_distance_y_ = 0.0f;
    max_distance_dx_ = 0.0f;
    max_distance_dy_ = 0.0f;
    max_distance_angle_ = 0.0f;
    path_head_ = 0;
    path_count_ = 0;
    circle_cumulative_angle_ = 0.0f;
    circle_last_angle_ = 0.0f;
    circle_heading_x_ = circle_heading_y_ = 0.0f;
    circle_center_x_ = 0.0f;
    circle_center_y_ = 0.0f;
    circle_point_count_ = 0;
    circle_twice_area_ = 0.0f;
    circle_absolute_twice_area_ = 0.0f;
    circle_path_length_ = 0.0f;
    swipe_detected_ = false;
    swipe_angle_ = 0.0f;
    swipe_dx_ = 0.0f;
    swipe_dy_ = 0.0f;
}

uint8_t GestureDetector::getGridPosition(float x, float y) const {
    int col = static_cast<int>(std::lround(x));
    int row = static_cast<int>(std::lround(y));

    if (col < 0 || row < 0) {
        return kInvalidGrid;
    }

    if (col > GRID_COLS - 1) {
        col = GRID_COLS - 1;
    }
    if (row > GRID_ROWS - 1) {
        row = GRID_ROWS - 1;
    }

    return static_cast<uint8_t>(row * GRID_COLS + col);
}

void GestureDetector::addPathPoint(float x, float y) {
    path_history_[path_head_] = PathPoint(x, y);
    path_head_ = static_cast<uint8_t>((path_head_ + 1) % PATH_HISTORY_SIZE);
    if (path_count_ < PATH_HISTORY_SIZE) {
        path_count_++;
    }
}

void GestureDetector::updateCircleTracking(float x, float y) {
    float sum_x = 0.0f;
    float sum_y = 0.0f;
    for (uint8_t i = 0; i < path_count_; ++i) {
        sum_x += path_history_[i].x;
        sum_y += path_history_[i].y;
    }

    circle_center_x_ = sum_x / static_cast<float>(path_count_);
    circle_center_y_ = sum_y / static_cast<float>(path_count_);

    // Sum changes in the motion's heading. Angles measured from a moving
    // running centroid distort even perfect circles as that centroid drifts.
    const auto& previous = path_history_[(path_head_ + PATH_HISTORY_SIZE - 2) % PATH_HISTORY_SIZE];
    const float dx = x - previous.x;
    const float dy = y - previous.y;
    const float distance = calculateDistance(dx, dy);
    if (distance == 0.0f) {
        return;
    }
    circle_path_length_ += distance;
    // Triangles about the fixed contact start make this translation-invariant.
    // The closing edge to that start contributes zero. Opposite loops cancel
    // signed area but still increase absolute area, exposing ambiguous scribbles.
    const float area = (previous.x - start_x_) * (y - start_y_) -
                       (previous.y - start_y_) * (x - start_x_);
    circle_twice_area_ += area;
    circle_absolute_twice_area_ += std::fabs(area);
    // Near-stationary consecutive samples have arbitrary tangent directions.
    // Use spatially separated anchors for heading and eligibility, while all
    // samples above still contribute to length and enclosed area. The result
    // is independent of pauses and does not add artificial turns from jitter.
    const float heading_dx = x - circle_heading_x_;
    const float heading_dy = y - circle_heading_y_;
    if (calculateDistance(heading_dx, heading_dy) < CIRCLE_HEADING_STEP) {
        return;
    }
    circle_heading_x_ = x;
    circle_heading_y_ = y;
    const float current_angle = calculateAngle(heading_dx, heading_dy);

    if (circle_point_count_ > 0) {
        const float angle_delta = angleDifference(current_angle, circle_last_angle_);
        circle_cumulative_angle_ += angle_delta;
    }

    circle_last_angle_ = current_angle;
    // Only eligibility matters; a long stroke must not wrap back to zero.
    if (circle_point_count_ < CIRCLE_MIN_POINTS) {
        circle_point_count_++;
    }
}

void GestureDetector::updateSwipeReturnTracking(float x, float y) {
    if (!swipe_detected_ && max_distance_ > SWIPE_RETURN_MIN_DISTANCE) {
        swipe_detected_ = true;
        swipe_angle_ = max_distance_angle_;
        swipe_dx_ = max_distance_dx_;
        swipe_dy_ = max_distance_dy_;
    }

    if (swipe_detected_) {
        const float dx = x - max_distance_x_;
        const float dy = y - max_distance_y_;
        const float distance = calculateDistance(dx, dy);

        if (distance > SWIPE_RETURN_MIN_RETURN_DISTANCE) {
            const float current_angle = calculateAngle(dx, dy);
            const float angle_diff =
                std::fabs(angleDifference(current_angle, swipe_angle_));
            if (std::fabs(angle_diff - 180.0f) < SWIPE_RETURN_ANGLE_TOLERANCE) {
                // Pattern looks like a swipe-return; actual detection handled in analyzeGesture.
            }
        }
    }
}

DetectedGesture GestureDetector::analyzeGesture() {
    const uint32_t duration = current_time_ - start_time_;
    (void)duration;

    // A closed loop also ends near its start. Validate its geometry before
    // the simpler out-and-back rule gets a chance to claim it.
    const DetectedGesture circle = detectCircle();
    if (circle.type != GESTURE_NONE) {
        return circle;
    }

    const DetectedGesture swipe_return = detectSwipeReturn();
    if (swipe_return.type != GESTURE_NONE) {
        return swipe_return;
    }

    const DetectedGesture long_swipe = detectLongSwipe();
    if (long_swipe.type != GESTURE_NONE) {
        return long_swipe;
    }

    const DetectedGesture swipe = detectSwipe();
    if (swipe.type != GESTURE_NONE) {
        return swipe;
    }

    const DetectedGesture edge_swipe = detectEdgeSwipe();
    if (edge_swipe.type != GESTURE_NONE && edge_swipe.type != GESTURE_TAP) {
        return edge_swipe;
    }

    // Holds tolerate centroid drift, but a supported motion gesture still
    // wins. An edge helper's tap fallback must not suppress capitalization.
    const DetectedGesture hold = detectHold();
    if (hold.type != GESTURE_NONE) {
        return hold;
    }

    return detectTap();
}

DetectedGesture GestureDetector::detectTap() {
    if (max_distance_ < SWIPE_MIN_DISTANCE) {
        // Duration selects an explicitly bound hold; it does not cancel a
        // tap-like press when no higher-priority gesture matched.
        if (HasGestureBinding(start_grid_pos_, GESTURE_TAP, DIR_CENTER)) {
            return DetectedGesture(GESTURE_TAP, DIR_CENTER, start_grid_pos_);
        }
    }
    return DetectedGesture();
}

DetectedGesture GestureDetector::detectHold() {
    const uint32_t duration = current_time_ - start_time_;
    if (duration < HOLD_MIN_DURATION) {
        return DetectedGesture();
    }

    if (max_distance_ >= HOLD_MAX_DISTANCE) {
        return DetectedGesture();
    }

    if (!HasGestureBinding(start_grid_pos_, GESTURE_HOLD, DIR_CENTER)) {
        return DetectedGesture();
    }

    return DetectedGesture(GESTURE_HOLD, DIR_CENTER, start_grid_pos_);
}

DetectedGesture GestureDetector::detectSwipe() {
    const float coherent_dx = current_x_ - start_x_;
    const float coherent_dy = current_y_ - start_y_;
    const float coherent_distance = calculateDistance(coherent_dx, coherent_dy);
    const Direction coherent_direction = coherent_distance >= max_distance_ * 0.9f
        ? getDirectionFromVector(coherent_dx, coherent_dy)
        : getDirectionFromVector(max_distance_dx_, max_distance_dy_);
    const GestureBinding *coherent_binding = FindGestureBinding(
        start_grid_pos_, GESTURE_SWIPE_SHORT, coherent_direction);
    const float coherent_min_distance = coherent_binding && coherent_binding->coherent_min_distance > 0.0f
        ? coherent_binding->coherent_min_distance : COHERENT_SWIPE_MIN_DISTANCE;
    if (max_distance_ < SWIPE_MIN_DISTANCE && path_count_ >= 4 &&
        coherent_distance >= coherent_min_distance &&
        coherent_distance >= max_distance_ * COHERENT_SWIPE_MIN_END_RATIO &&
        max_distance_ >= circle_path_length_ * COHERENT_SWIPE_MIN_EFFICIENCY) {
        // The sensor's filtered release tail can recoil after raw contact has
        // vanished. Count its path length, but assess the outward excursion;
        // the retained-distance gate above still rejects substantial returns.
        // Use the same peak/endpoint direction policy as ordinary swipes.
        if (coherent_direction != DIR_CENTER && coherent_binding) {
            return DetectedGesture(GESTURE_SWIPE_SHORT, coherent_direction, start_grid_pos_);
        }
    }

    if (max_distance_ >= SWIPE_MIN_DISTANCE &&
        max_distance_ < LONG_SWIPE_DISTANCE) {
        float dir_dx = max_distance_dx_;
        float dir_dy = max_distance_dy_;
        const float dir_dist = calculateDistance(dir_dx, dir_dy);

        const float end_dx = current_x_ - start_x_;
        const float end_dy = current_y_ - start_y_;
        const float end_dist = calculateDistance(end_dx, end_dy);

        if (end_dist >= dir_dist * 0.9f) {
            dir_dx = end_dx;
            dir_dy = end_dy;
        } else if (dir_dist < 1e-4f) {
            dir_dx = end_dx;
            dir_dy = end_dy;
        }

        const Direction dir = getDirectionFromVector(dir_dx, dir_dy);
        if (dir == DIR_CENTER) {
            return DetectedGesture();
        }

        if (!HasGestureBinding(start_grid_pos_, GESTURE_SWIPE_SHORT, dir)) {
            if (dir_dist < EDGE_SWIPE_TAP_DISTANCE) {
                return detectTap();
            }
            return DetectedGesture();
        }

        return DetectedGesture(GESTURE_SWIPE_SHORT, dir, start_grid_pos_);
    }
    return DetectedGesture();
}

DetectedGesture GestureDetector::detectLongSwipe() {
    if (max_distance_ >= LONG_SWIPE_DISTANCE) {
        float dir_dx = max_distance_dx_;
        float dir_dy = max_distance_dy_;
        const float dir_dist = calculateDistance(dir_dx, dir_dy);

        const float end_dx = current_x_ - start_x_;
        const float end_dy = current_y_ - start_y_;
        const float end_dist = calculateDistance(end_dx, end_dy);

        if (end_dist >= dir_dist * 0.9f) {
            dir_dx = end_dx;
            dir_dy = end_dy;
        } else if (dir_dist < 1e-4f) {
            dir_dx = end_dx;
            dir_dy = end_dy;
        }

        const Direction dir = getDirectionFromVector(dir_dx, dir_dy);
        if (dir == DIR_CENTER) {
            return DetectedGesture();
        }
        if (!HasGestureBinding(start_grid_pos_, GESTURE_SWIPE_LONG, dir)) {
            return DetectedGesture();
        }
        return DetectedGesture(GESTURE_SWIPE_LONG, dir, start_grid_pos_);
    }
    return DetectedGesture();
}

DetectedGesture GestureDetector::detectEdgeSwipe() {
    const bool left_cell = (start_grid_pos_ % GRID_COLS) == 0;
    const bool right_cell = (start_grid_pos_ % GRID_COLS) == (GRID_COLS - 1);
    const bool top_cell = (start_grid_pos_ / GRID_COLS) == 0;
    const bool bottom_cell = (start_grid_pos_ / GRID_COLS) == (GRID_ROWS - 1);

    const bool edge_cell = left_cell || right_cell || top_cell || bottom_cell;
    const float trigger = edge_cell ? EDGE_SWIPE_EDGE_CELL_TRIGGER : EDGE_SWIPE_TRIGGER_DISTANCE;

    if (path_count_ < 4) {
        return DetectedGesture();
    }

    if (max_distance_ < EDGE_SWIPE_MIN_DISTANCE) {
        return DetectedGesture();
    }

    if (max_distance_ >= SWIPE_MIN_DISTANCE) {
        return DetectedGesture();
    }

    float dir_dx = max_distance_dx_;
    float dir_dy = max_distance_dy_;
    float dir_dist = calculateDistance(dir_dx, dir_dy);

    const float end_dx = current_x_ - start_x_;
    const float end_dy = current_y_ - start_y_;
    const float end_dist = calculateDistance(end_dx, end_dy);

    if (edge_cell) {
        dir_dx = end_dx;
        dir_dy = end_dy;
        dir_dist = end_dist;
    } else if (end_dist > dir_dist) {
        dir_dx = end_dx;
        dir_dy = end_dy;
        dir_dist = end_dist;
    }

    const float max_cols = static_cast<float>(GRID_COLS);
    const float max_rows = static_cast<float>(GRID_ROWS);

    const bool left_edge = nearLeftEdge();
    const bool right_edge = nearRightEdge();
    const bool top_edge = nearTopEdge();
    const bool bottom_edge = nearBottomEdge();

    const float axis_threshold = std::max(trigger * 0.45f, 0.06f);
    const float horiz_mag = std::max(std::fabs(end_dx), std::fabs(max_distance_dx_));
    const float vert_mag = std::max(std::fabs(end_dy), std::fabs(max_distance_dy_));

    // An edge can amplify an observed outward component, but must never
    // reverse an inward stroke merely because it started in an edge cell.
    if (left_edge && dir_dx < 0.0f && dir_dx > -trigger && horiz_mag > axis_threshold &&
        (max_distance_x_ <= EDGE_ZONE_THRESHOLD || current_x_ <= EDGE_ZONE_THRESHOLD * 0.5f || left_cell)) {
        dir_dx = -trigger;
    }
    if (right_edge && dir_dx > 0.0f && dir_dx < trigger && horiz_mag > axis_threshold &&
        (max_distance_x_ >= max_cols - EDGE_ZONE_THRESHOLD ||
         current_x_ >= max_cols - EDGE_ZONE_THRESHOLD * 0.5f || right_cell)) {
        dir_dx = trigger;
    }
    if (top_edge && dir_dy < 0.0f && dir_dy > -trigger && vert_mag > axis_threshold &&
        (max_distance_y_ <= EDGE_ZONE_THRESHOLD || current_y_ <= EDGE_ZONE_THRESHOLD * 0.5f || top_cell)) {
        dir_dy = -trigger;
    }
    if (bottom_edge && dir_dy > 0.0f && dir_dy < trigger && vert_mag > axis_threshold &&
        (max_distance_y_ >= max_rows - EDGE_ZONE_THRESHOLD ||
         current_y_ >= max_rows - EDGE_ZONE_THRESHOLD * 0.5f || bottom_cell)) {
        dir_dy = trigger;
    }

    const float diag_end_threshold = std::max(axis_threshold, trigger * 0.45f);
    if (std::fabs(end_dx) > diag_end_threshold && std::fabs(end_dy) > diag_end_threshold) {
        const float dist = calculateDistance(end_dx, end_dy);
        if (dist > axis_threshold) {
            const float scale = trigger / std::max(dist, trigger);
            dir_dx = end_dx * scale;
            dir_dy = end_dy * scale;
        }
    }

    dir_dist = calculateDistance(dir_dx, dir_dy);
    if (dir_dist < axis_threshold) {
        return DetectedGesture();
    }

    const float dominant_axis = std::max(std::fabs(dir_dx), std::fabs(dir_dy));
    if (dominant_axis < axis_threshold) {
        return DetectedGesture();
    }

    Direction dir = getDirectionFromVector(dir_dx, dir_dy);
    if (dir == DIR_CENTER) {
        return DetectedGesture();
    }

    if (!supportsEdgeDirection(dir)) {
        return DetectedGesture();
    }

    const GestureBinding *binding = FindGestureBinding(start_grid_pos_, GESTURE_SWIPE_SHORT, dir);
    if (binding && binding->coherent_min_distance > 0.0f) {
        // A binding-specific short stroke must pass the coherent-path checks
        // above; edge assistance must not bypass its distance or quality gates.
        return DetectedGesture();
    }

    if (!HasGestureBinding(start_grid_pos_, GESTURE_SWIPE_SHORT, dir)) {
        if (dir_dist < EDGE_SWIPE_TAP_DISTANCE) {
            return detectTap();
        }
        return DetectedGesture();
    }

    return DetectedGesture(GESTURE_SWIPE_SHORT, dir, start_grid_pos_);
}

DetectedGesture GestureDetector::detectSwipeReturn() {
    if (!swipe_detected_) {
        return DetectedGesture();
    }

    if (max_distance_ >= SWIPE_RETURN_MIN_DISTANCE) {
        const float dx = current_x_ - start_x_;
        const float dy = current_y_ - start_y_;
        const float current_distance = calculateDistance(dx, dy);

        if (current_distance < max_distance_ * SWIPE_RETURN_MAX_END_RATIO) {
            const Direction dir = getDirectionFromVector(swipe_dx_, swipe_dy_);
            if (dir != DIR_CENTER &&
                HasGestureBinding(start_grid_pos_, GESTURE_SWIPE_RETURN, dir)) {
                return DetectedGesture(GESTURE_SWIPE_RETURN, dir, start_grid_pos_);
            }
            // Landing drift can arm the return in an unbound direction before
            // the intended outward stroke develops. Use its peak in that case,
            // as ordinary swipes do. Preserve a valid early direction: curved
            // diagonal strokes can have a cardinal peak later in the contact.
            const Direction peak_dir = getDirectionFromVector(max_distance_dx_, max_distance_dy_);
            if (peak_dir != DIR_CENTER &&
                HasGestureBinding(start_grid_pos_, GESTURE_SWIPE_RETURN, peak_dir)) {
                return DetectedGesture(GESTURE_SWIPE_RETURN, peak_dir, start_grid_pos_);
            }
        }
    }
    return DetectedGesture();
}

DetectedGesture GestureDetector::detectCircle() {
    if (circle_point_count_ < CIRCLE_MIN_POINTS) {
        return DetectedGesture();
    }

    if (max_distance_ < CIRCLE_MIN_SPAN) {
        return DetectedGesture();
    }
    const float closure = calculateDistance(current_x_ - start_x_, current_y_ - start_y_);
    if (closure > max_distance_ * CIRCLE_MAX_CLOSURE_FRACTION) {
        return DetectedGesture();
    }
    // Perimeter-squared circularity falls as 1/N for N identical turns, so
    // valid repeated circles used to fail. Area / (length * span) instead
    // stays constant for repeated turns and is rotation invariant. Thin
    // retraced loops enclose too little area, regardless of their orientation.
    // Accumulators use bounded memory and include the entire contact, so a
    // small incidental loop cannot hide a long tail or an opposing lobe.
    const float area = std::fabs(circle_twice_area_);
    if (area < 2.0f * circle_path_length_ * max_distance_ * CIRCLE_MIN_AREA_DENSITY ||
        area < circle_absolute_twice_area_ * CIRCLE_MIN_AREA_CONSISTENCY ||
        circle_cumulative_angle_ * circle_twice_area_ >= 0.0f) {
        return DetectedGesture();
    }

    const float abs_angle = std::fabs(circle_cumulative_angle_);
    if (abs_angle >= CIRCLE_MIN_ARC_ANGLE) {
        float sum_radius = 0.0f;
        for (uint8_t i = 0; i < path_count_; ++i) {
            const float dx = path_history_[i].x - circle_center_x_;
            const float dy = path_history_[i].y - circle_center_y_;
            sum_radius += calculateDistance(dx, dy);
        }
        const float avg_radius = sum_radius / static_cast<float>(path_count_);

        float variance = 0.0f;
        for (uint8_t i = 0; i < path_count_; ++i) {
            const float dx = path_history_[i].x - circle_center_x_;
            const float dy = path_history_[i].y - circle_center_y_;
            const float radius = calculateDistance(dx, dy);
            variance += std::fabs(radius - avg_radius);
        }
        variance /= static_cast<float>(path_count_);

        if (variance < CIRCLE_MAX_RADIUS_VARIANCE) {
            const GestureType type = (circle_cumulative_angle_ < 0.0f)
                                         ? GESTURE_CIRCLE_CW
                                         : GESTURE_CIRCLE_CCW;
            if (HasGestureBinding(start_grid_pos_, type, DIR_CENTER)) {
                return DetectedGesture(type, DIR_CENTER, start_grid_pos_);
            }
        }
    }
    return DetectedGesture();
}

Direction GestureDetector::getDirectionFromAngle(float angle_deg) const {
    const float normalized = normalizeAngle(angle_deg);
    const float angle_rad = normalized * kPi / 180.0f;
    const float dx = std::cos(angle_rad);
    const float dy = -std::sin(angle_rad);
    return getDirectionFromVector(dx, dy);
}

float GestureDetector::calculateAngle(float dx, float dy) const {
    const float angle_rad = std::atan2(-dy, dx);
    return angle_rad * 180.0f / kPi;
}

Direction GestureDetector::getDirectionFromVector(float dx, float dy) const {
    const float abs_dx = std::fabs(dx);
    const float abs_dy = std::fabs(dy);
    if (abs_dx < 1e-4f && abs_dy < 1e-4f) {
        return DIR_CENTER;
    }

    const float angle_deg = normalizeAngle(calculateAngle(dx, dy));

    if (angle_deg >= 337.5f || angle_deg < 22.5f) return DIR_EAST;
    if (angle_deg < 67.5f) return DIR_NORTHEAST;
    if (angle_deg < 112.5f) return DIR_NORTH;
    if (angle_deg < 157.5f) return DIR_NORTHWEST;
    if (angle_deg < 202.5f) return DIR_WEST;
    if (angle_deg < 247.5f) return DIR_SOUTHWEST;
    if (angle_deg < 292.5f) return DIR_SOUTH;
    return DIR_SOUTHEAST;
}

bool GestureDetector::supportsEdgeDirection(Direction direction) const {
    bool allowed = false;

    if ((direction == DIR_NORTH || direction == DIR_NORTHEAST || direction == DIR_NORTHWEST) &&
        nearTopEdge()) {
        allowed = true;
    }
    if ((direction == DIR_SOUTH || direction == DIR_SOUTHWEST || direction == DIR_SOUTHEAST) &&
        nearBottomEdge()) {
        allowed = true;
    }
    if ((direction == DIR_EAST || direction == DIR_NORTHEAST || direction == DIR_SOUTHEAST) &&
        nearRightEdge()) {
        allowed = true;
    }
    if ((direction == DIR_WEST || direction == DIR_NORTHWEST || direction == DIR_SOUTHWEST) &&
        nearLeftEdge()) {
        allowed = true;
    }

    return allowed;
}

bool GestureDetector::nearLeftEdge() const {
    const bool left_cell = (start_grid_pos_ % GRID_COLS) == 0;
    return left_cell || start_x_ <= EDGE_ZONE_THRESHOLD;
}

bool GestureDetector::nearRightEdge() const {
    const float max_col = static_cast<float>(GRID_COLS);
    const bool right_cell = (start_grid_pos_ % GRID_COLS) == (GRID_COLS - 1);
    return right_cell || start_x_ >= max_col - EDGE_ZONE_THRESHOLD;
}

bool GestureDetector::nearTopEdge() const {
    const bool top_cell = (start_grid_pos_ / GRID_COLS) == 0;
    return top_cell || start_y_ <= EDGE_ZONE_THRESHOLD;
}

bool GestureDetector::nearBottomEdge() const {
    const float max_row = static_cast<float>(GRID_ROWS);
    const bool bottom_cell = (start_grid_pos_ / GRID_COLS) == (GRID_ROWS - 1);
    return bottom_cell || start_y_ >= max_row - EDGE_ZONE_THRESHOLD;
}



float GestureDetector::calculateDistance(float dx, float dy) const {
    return std::sqrt(dx * dx + dy * dy);
}

float GestureDetector::normalizeAngle(float angle) const {
    float result = angle;
    while (result < 0.0f) {
        result += 360.0f;
    }
    while (result >= 360.0f) {
        result -= 360.0f;
    }
    return result;
}

float GestureDetector::angleDifference(float angle1, float angle2) const {
    float diff = angle1 - angle2;
    while (diff > 180.0f) {
        diff -= 360.0f;
    }
    while (diff < -180.0f) {
        diff += 360.0f;
    }
    return diff;
}
