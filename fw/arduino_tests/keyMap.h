#pragma once
#include "gestureTypes.h"
#include "USB.h"
#include "USBHIDKeyboard.h"

class SaoKeyboard;  // Forward declaration

class KeyMap {
public:
    KeyMap(bool enable_sao = true);

    // Initialize the keyboard
    void init();

    // Main dispatcher - routes to appropriate key handler and executes action
    void execute(uint8_t grid_pos, GestureType gesture, Direction direction);

    // Enable/disable keyboard output (useful for debugging via serial)
    void setKeyboardEnabled(bool enabled) { keyboard_enabled_ = enabled; }

private:
    USBHIDKeyboard keyboard_;
    bool keyboard_enabled_;
    bool caps_lock_state_;
    SaoKeyboard* sao_keyboard_;

    // One handler function per key/grid cell
    void handleKey0(GestureType gesture, Direction direction);  // Top-left
    void handleKey1(GestureType gesture, Direction direction);  // Top-center
    void handleKey2(GestureType gesture, Direction direction);  // Top-right
    void handleKey3(GestureType gesture, Direction direction);  // Middle-left
    void handleKey4(GestureType gesture, Direction direction);  // Center
    void handleKey5(GestureType gesture, Direction direction);  // Middle-right
    void handleKey6(GestureType gesture, Direction direction);  // Bottom-left
    void handleKey7(GestureType gesture, Direction direction);  // Bottom-center
    void handleKey8(GestureType gesture, Direction direction);  // Bottom-right

    // Helper functions for directly executing actions
    void charAction(char c);
    void stringAction(const char* str);
    void backspaceAction();
    void capsLockAction();
    void debug(GestureType gesture, Direction direction);
};

// Helper to encode gesture+direction into single value for switch
static inline constexpr uint16_t makeKey(GestureType gesture, Direction direction) {
    return (gesture << 8) | direction;
}

