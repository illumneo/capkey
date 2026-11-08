#pragma once

// Grid Configuration
#define GRID_ROWS 4
#define GRID_COLS 4
#define GRID_SIZE (GRID_ROWS * GRID_COLS)

// Touch Detection Thresholds
#define TOUCH_THRESHOLD 1.3f
#define TOUCH_RELEASE_THRESHOLD 0.9f

// Distance Thresholds
#define SWIPE_MIN_DISTANCE 0.45f
// Shorter strokes need a supported direction and a mostly straight path that
// finishes near its maximum excursion. Keep the ordinary tap boundary intact.
#define COHERENT_SWIPE_MIN_DISTANCE 0.32f
#define COHERENT_SWIPE_MIN_EFFICIENCY 0.75f
// Permit modest release-filter recoil while still requiring a retained stroke.
#define COHERENT_SWIPE_MIN_END_RATIO 0.8f
#define LONG_SWIPE_DISTANCE 1.30f
#define SWIPE_RETURN_MIN_DISTANCE 0.25f
#define EDGE_SWIPE_TRIGGER_DISTANCE 0.18f
#define EDGE_SWIPE_EDGE_CELL_TRIGGER 0.12f
#define EDGE_SWIPE_MIN_DISTANCE 0.20f
#define EDGE_SWIPE_TAP_DISTANCE 0.16f

// Time Thresholds (microseconds)
// Letter-pad holds produce capitals on release. Duration includes the sensor
// filter's release tail; command pads retain their ordinary tap behavior.
#define HOLD_MIN_DURATION 500000

// Hold Detection
// Allow landing/release drift below the return-stroke threshold. Supported
// motion gestures take precedence, so slow edge punctuation stays a swipe.
#define HOLD_MAX_DISTANCE 0.25f

// Circle Detection Parameters
#define CIRCLE_MIN_ARC_ANGLE 270.0f
#define CIRCLE_MAX_RADIUS_VARIANCE 0.2f
#define CIRCLE_MIN_POINTS 8
// Ignore sub-step jitter when estimating tangent direction, not enclosed area.
#define CIRCLE_HEADING_STEP 0.02f
// Heuristic geometry bounds, checked against recorded contacts and synthetic
// controls; not a universal calibration. Span is measured from contact start.
// Small loops must not require more spatial anchors than their perimeter can
// contain. Area and net turning still distinguish them from hold jitter.
#define CIRCLE_MIN_SPAN 0.10f
// Leave room for the PCB's distorted landing/lift centroid. A 3/4-circle still
// fails this bound; net turning, enclosed area and consistency also must pass.
#define CIRCLE_MAX_CLOSURE_FRACTION 0.65f
#define CIRCLE_MIN_AREA_DENSITY 0.12f
#define CIRCLE_MIN_AREA_CONSISTENCY 0.8f

// Swipe Return Parameters
#define SWIPE_RETURN_MAX_END_RATIO 0.55f
#define SWIPE_RETURN_ANGLE_TOLERANCE 45.0f
#define SWIPE_RETURN_MIN_RETURN_DISTANCE 0.10f

// Path History Configuration
#define PATH_HISTORY_SIZE 64

// Edge Swipe Handling
#define EDGE_ZONE_THRESHOLD 0.35f

// Grid Cell Boundaries
#define GRID_CELL_WIDTH 1.0f
#define GRID_CELL_HEIGHT 1.0f
