#include "keyMap.h"
#include "gestureTypes.h"
#include "Arduino.h"

KeyMap::KeyMap()
    : keyboard_enabled_(true), caps_lock_state_(false) {
}

void KeyMap::init() {
    if (keyboard_enabled_) {
        keyboard_.begin();
        USB.begin();
    }
}

// Main dispatcher
void KeyMap::execute(uint8_t grid_pos, GestureType gesture, Direction direction) {
    switch (grid_pos) {
        case 0: handleKey0(gesture, direction); break;
        case 1: handleKey1(gesture, direction); break;
        case 2: handleKey2(gesture, direction); break;
        case 3: handleKey3(gesture, direction); break;
        case 4: handleKey4(gesture, direction); break;
        case 5: handleKey5(gesture, direction); break;
        case 6: handleKey6(gesture, direction); break;
        case 7: handleKey7(gesture, direction); break;
        case 8: handleKey8(gesture, direction); break;
        default: break;
    }
}

// Key 0: Top-left
void KeyMap::handleKey0(GestureType gesture, Direction direction) {
    switch (makeKey(gesture, direction)) {
        case makeKey(GESTURE_TAP, DIR_CENTER):
            charAction('a');
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_SOUTHEAST):
            charAction('v');
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_EAST):
            charAction('\n');
            break;
        default:
            break;
    }
}

// Key 1: Top-center
void KeyMap::handleKey1(GestureType gesture, Direction direction) {
    switch (makeKey(gesture, direction)) {
        case makeKey(GESTURE_TAP, DIR_CENTER):
            charAction('n');
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_SOUTH):
            charAction('l');
            break;
        default:
            break;
    }
}

// Key 2: Top-right
void KeyMap::handleKey2(GestureType gesture, Direction direction) {
    switch (makeKey(gesture, direction)) {
        case makeKey(GESTURE_TAP, DIR_CENTER):
            charAction('i');
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_SOUTHWEST):
            charAction('x');
            break;
        default:
            break;
    }
}

// Key 3: Middle-left
void KeyMap::handleKey3(GestureType gesture, Direction direction) {
    switch (makeKey(gesture, direction)) {
        case makeKey(GESTURE_TAP, DIR_CENTER):
            charAction('h');
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_EAST):
            charAction('k');
            break;
        default:
            break;
    }
}

// Key 4: Center - most complex with many gestures
void KeyMap::handleKey4(GestureType gesture, Direction direction) {
    switch (makeKey(gesture, direction)) {
        case makeKey(GESTURE_TAP, DIR_CENTER):
            charAction('o');
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_NORTH):
            charAction('u');
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_NORTHWEST):
            charAction('q');
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_WEST):
            charAction('c');
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_SOUTHWEST):
            charAction('g');
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_SOUTH):
            charAction('d');
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_SOUTHEAST):
            charAction('j');
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_EAST):
            charAction('b');
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_NORTHEAST):
            charAction('p');
            break;

        // Swipe and return for upper case letters
        case makeKey(GESTURE_SWIPE_RETURN, DIR_NORTH):
            charAction('U');
            break;
        case makeKey(GESTURE_SWIPE_RETURN, DIR_NORTHWEST):
            charAction('Q');
            break;
        case makeKey(GESTURE_SWIPE_RETURN, DIR_WEST):
            charAction('C');
            break;
        case makeKey(GESTURE_SWIPE_RETURN, DIR_SOUTHWEST):
            charAction('G');
            break;
        case makeKey(GESTURE_SWIPE_RETURN, DIR_SOUTH):
            charAction('D');
            break;
        case makeKey(GESTURE_SWIPE_RETURN, DIR_SOUTHEAST):
            charAction('J');
            break;
        case makeKey(GESTURE_SWIPE_RETURN, DIR_EAST):
            charAction('B');
            break;
        case makeKey(GESTURE_SWIPE_RETURN, DIR_NORTHEAST):
            charAction('P');
            break;

        // Add more gestures here (hold, long swipe, circles, etc.)
        case makeKey(GESTURE_HOLD, DIR_CENTER):
            charAction('O');
            break;
        case makeKey(GESTURE_CIRCLE_CW, DIR_CENTER):
            charAction('O');
            break;
        case makeKey(GESTURE_CIRCLE_CCW, DIR_CENTER):
            charAction('5');
            break;
        default:
            break;
    }
}


// Key 5: Middle-right
void KeyMap::handleKey5(GestureType gesture, Direction direction) {
    switch (makeKey(gesture, direction)) {
        case makeKey(GESTURE_TAP, DIR_CENTER):
            charAction('r');
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_WEST):
            charAction('m');
            break;
        default:
            break;
    }
}

// Key 6: Bottom-left
void KeyMap::handleKey6(GestureType gesture, Direction direction) {
    switch (makeKey(gesture, direction)) {
        case makeKey(GESTURE_TAP, DIR_CENTER):
            charAction('t');
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_EAST):
            charAction(' ');
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_NORTHEAST):
            charAction('y');
            break;
        default:
            break;
    }
}

// Key 7: Bottom-center
void KeyMap::handleKey7(GestureType gesture, Direction direction) {
    switch (makeKey(gesture, direction)) {
        case makeKey(GESTURE_TAP, DIR_CENTER):
            charAction('e');
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_NORTH):
            charAction('w');
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_EAST):
            charAction('z');
            break;
        default:
            break;
    }
}

// Key 8: Bottom-right
void KeyMap::handleKey8(GestureType gesture, Direction direction) {
    switch (makeKey(gesture, direction)) {
        case makeKey(GESTURE_TAP, DIR_CENTER):
            charAction('s');
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_NORTHWEST):
            charAction('f');
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_WEST):
            backspaceAction();
            break;
        default:
            break;
    }
}

// Helper function implementations - directly execute keyboard actions
void KeyMap::charAction(char c) {
    if (keyboard_enabled_) {
        keyboard_.write(c);
    }
    Serial.print("Char: ");
    Serial.println(c);
}

void KeyMap::stringAction(const char* str) {
    if (keyboard_enabled_ && str != nullptr) {
        keyboard_.print(str);
    }
    Serial.print("String: ");
    Serial.println(str);
}

void KeyMap::backspaceAction() {
    if (keyboard_enabled_) {
        keyboard_.write(KEY_BACKSPACE);
    }
    Serial.println("Backspace");
}

void KeyMap::capsLockAction() {
    caps_lock_state_ = !caps_lock_state_;
    if (keyboard_enabled_) {
        // Toggle caps lock
        keyboard_.press(KEY_CAPS_LOCK);
        keyboard_.releaseAll();
    }
    Serial.print("Caps Lock: ");
    Serial.println(caps_lock_state_ ? "ON" : "OFF");
}



// Key 4: Center - most complex with many gestures
void KeyMap::debug(GestureType gesture, Direction direction) {
    switch (makeKey(gesture, direction)) {
        case makeKey(GESTURE_TAP, DIR_CENTER):
            Serial.println("Tap");
            break;
        case makeKey(GESTURE_HOLD, DIR_CENTER):
            Serial.println("Hold");
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_NORTH):
            Serial.println("N Swipe");
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_NORTHWEST):
            Serial.println("NW Swipe");
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_WEST):
            Serial.println("W Swipe");
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_SOUTHWEST):
            Serial.println("SW Swipe");
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_SOUTH):
            Serial.println("S Swipe");
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_SOUTHEAST):
            Serial.println("SE Swipe");
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_EAST):
            Serial.println("E Swipe");
            break;
        case makeKey(GESTURE_SWIPE_SHORT, DIR_NORTHEAST):
            Serial.println("NE Swipe");
            break;
        case makeKey(GESTURE_SWIPE_LONG, DIR_NORTH):
            Serial.println("N Long Swipe");
            break;
        case makeKey(GESTURE_SWIPE_LONG, DIR_NORTHWEST):
            Serial.println("NW Long Swipe");
            break;
        case makeKey(GESTURE_SWIPE_LONG, DIR_WEST):
            Serial.println("W Long Swipe");
            break;
        case makeKey(GESTURE_SWIPE_LONG, DIR_SOUTHWEST):
            Serial.println("SW Long Swipe");
            break;
        case makeKey(GESTURE_SWIPE_LONG, DIR_SOUTH):
            Serial.println("S Long Swipe");
            break;
        case makeKey(GESTURE_SWIPE_LONG, DIR_SOUTHEAST):
            Serial.println("SE Long Swipe");
            break;
        case makeKey(GESTURE_SWIPE_LONG, DIR_EAST):
            Serial.println("E Long Swipe");
            break;
        case makeKey(GESTURE_SWIPE_LONG, DIR_NORTHEAST):
            Serial.println("NE Long Swipe");
            break;
        case makeKey(GESTURE_SWIPE_RETURN, DIR_NORTH):
            Serial.println("N Return Swipe");
            break;
        case makeKey(GESTURE_SWIPE_RETURN, DIR_NORTHWEST):
            Serial.println("NW Return Swipe");
            break;
        case makeKey(GESTURE_SWIPE_RETURN, DIR_WEST):
            Serial.println("W Return Swipe");
            break;
        case makeKey(GESTURE_SWIPE_RETURN, DIR_SOUTHWEST):
            Serial.println("SW Return Swipe");
            break;
        case makeKey(GESTURE_SWIPE_RETURN, DIR_SOUTH):
            Serial.println("S Return Swipe");
            break;
        case makeKey(GESTURE_SWIPE_RETURN, DIR_SOUTHEAST):
            Serial.println("SE Return Swipe");
            break;
        case makeKey(GESTURE_SWIPE_RETURN, DIR_EAST):
            Serial.println("E Return Swipe");
            break;
        case makeKey(GESTURE_SWIPE_RETURN, DIR_NORTHEAST):
            Serial.println("NE Return Swipe");
            break;
        case makeKey(GESTURE_CIRCLE_CW, DIR_CENTER):
            Serial.println("CW Circle");
            break;
        case makeKey(GESTURE_CIRCLE_CCW, DIR_CENTER):
            Serial.println("CCW Circle");
            break;
        default:
            Serial.println("No Action");
            break;
    }
}
