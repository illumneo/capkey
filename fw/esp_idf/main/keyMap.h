#pragma once

#include <cstdint>

#include "gestureLayout.h"
#include "gestureTypes.h"

class KeyMap {
public:
    KeyMap();

    void init();
    // Return the action actually selected by the on-device mapping. The current
    // runtime dispatches the returned action to its independent HID queue.
    KeyAction execute(uint8_t grid_pos, GestureType gesture, Direction direction);

private:
    bool caps_lock_state_;

    void charAction(char c);
    void stringAction(const char *str);
    void backspaceAction();
    void specialAction(const char *label);
    void capsLockAction();
    void performAction(const KeyAction &action);
    void debug(GestureType gesture, Direction direction);
};
