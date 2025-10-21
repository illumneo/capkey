#pragma once

// Grid Configuration
#define GRID_ROWS 3
#define GRID_COLS 3
#define GRID_SIZE (GRID_ROWS * GRID_COLS)

// Touch Detection Thresholds
#define TOUCH_THRESHOLD 2.5f          // Z-value to consider as "touch started"
#define TOUCH_RELEASE_THRESHOLD 2.1f  // Z-value to consider as "touch released" (with hysteresis)

// Distance Thresholds (in normalized coordinates, typically -1.5 to 1.5)
#define SWIPE_MIN_DISTANCE 0.4f       // Minimum distance for swipe
#define LONG_SWIPE_DISTANCE 1.7f      // Minimum distance for long swipe
#define SWIPE_RETURN_MIN_DISTANCE 0.8f // How far to swipe before detecting return

// Time Thresholds (in microseconds)
#define HOLD_MIN_DURATION 200000         // Minimum duration for hold

// Circle Detection Parameters
#define CIRCLE_MIN_ARC_ANGLE 270.0f   // Minimum cumulative angle for circle (degrees)
#define CIRCLE_MAX_RADIUS_VARIANCE 0.2f // Maximum variance in radius for circle detection
#define CIRCLE_MIN_POINTS 14          // Minimum path points needed for circle - more points = longer gesture

// Swipe Return Parameters
#define SWIPE_RETURN_ANGLE_TOLERANCE 45.0f  // Angle tolerance for detecting reversal (degrees)
#define SWIPE_RETURN_MIN_RETURN_DISTANCE 0.4f // Minimum return distance

// Path History Configuration
#define PATH_HISTORY_SIZE 64          // Number of path points to track

// Grid Cell Boundaries (for 3x3 grid with center at 0,0)
// Assumes x and y range approximately from -1.5 to 1.5
#define GRID_CELL_WIDTH 1.0f
#define GRID_CELL_HEIGHT 1.0f

