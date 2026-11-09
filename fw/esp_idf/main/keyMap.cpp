#include "keyMap.h"

#include <cstddef>

#include "esp_log.h"

namespace {
static const char *TAG = "keymap";

template <typename T, std::size_t N>
constexpr std::size_t ArraySize(const T (&)[N]) {
    return N;
}

constexpr GestureBinding kCell0Bindings[] = {
    {GESTURE_CIRCLE_CCW, DIR_CENTER, MakeCharAction('1')},
    {GESTURE_CIRCLE_CW, DIR_CENTER, KeyAction{}},
    {GESTURE_TAP, DIR_CENTER, MakeCharAction('a')},
    {GESTURE_HOLD, DIR_CENTER, MakeCharAction('A')},
    {GESTURE_SWIPE_SHORT, DIR_SOUTHWEST, MakeCharAction('$')},
    {GESTURE_SWIPE_SHORT, DIR_SOUTHEAST, MakeCharAction('v')},
    {GESTURE_SWIPE_RETURN, DIR_SOUTHEAST, MakeCharAction('V')},
    {GESTURE_SWIPE_SHORT, DIR_EAST, MakeCharAction('-')},
};

constexpr GestureBinding kCell1Bindings[] = {
    {GESTURE_CIRCLE_CCW, DIR_CENTER, MakeCharAction('2')},
    {GESTURE_CIRCLE_CW, DIR_CENTER, KeyAction{}},
    {GESTURE_TAP, DIR_CENTER, MakeCharAction('n')},
    {GESTURE_HOLD, DIR_CENTER, MakeCharAction('N')},
    {GESTURE_SWIPE_SHORT, DIR_SOUTH, MakeCharAction('l')},
    {GESTURE_SWIPE_RETURN, DIR_SOUTH, MakeCharAction('L')},
    {GESTURE_SWIPE_SHORT, DIR_NORTH, MakeCharAction('^')},
    {GESTURE_SWIPE_SHORT, DIR_NORTHWEST, MakeCharAction('`')},
    {GESTURE_SWIPE_SHORT, DIR_WEST, MakeCharAction('+')},
    {GESTURE_SWIPE_SHORT, DIR_EAST, MakeCharAction('!')},
    {GESTURE_SWIPE_SHORT, DIR_SOUTHWEST, MakeCharAction('/')},
    {GESTURE_SWIPE_SHORT, DIR_SOUTHEAST, MakeCharAction('\\')},
};

constexpr GestureBinding kCell2Bindings[] = {
    {GESTURE_CIRCLE_CCW, DIR_CENTER, MakeCharAction('3')},
    {GESTURE_CIRCLE_CW, DIR_CENTER, KeyAction{}},
    {GESTURE_TAP, DIR_CENTER, MakeCharAction('i')},
    {GESTURE_HOLD, DIR_CENTER, MakeCharAction('I')},
    {GESTURE_SWIPE_SHORT, DIR_SOUTHWEST, MakeCharAction('x')},
    {GESTURE_SWIPE_RETURN, DIR_SOUTHWEST, MakeCharAction('X')},
    {GESTURE_SWIPE_SHORT, DIR_WEST, MakeCharAction('?'), 0.28f},
    {GESTURE_SWIPE_SHORT, DIR_NORTHWEST, MakeCharAction('?'), 0.28f},
    {GESTURE_SWIPE_SHORT, DIR_SOUTH, MakeCharAction('=')},
};

constexpr GestureBinding kCell3Bindings[] = {
    {GESTURE_CIRCLE_CCW, DIR_CENTER, MakeCharAction('4')},
    {GESTURE_CIRCLE_CW, DIR_CENTER, KeyAction{}},
    {GESTURE_TAP, DIR_CENTER, MakeCharAction('h')},
    {GESTURE_HOLD, DIR_CENTER, MakeCharAction('H')},
    {GESTURE_SWIPE_SHORT, DIR_EAST, MakeCharAction('k')},
    {GESTURE_SWIPE_RETURN, DIR_EAST, MakeCharAction('K')},
    {GESTURE_SWIPE_SHORT, DIR_NORTHWEST, MakeCharAction('{')},
    {GESTURE_SWIPE_SHORT, DIR_NORTHEAST, MakeCharAction('%')},
    {GESTURE_SWIPE_SHORT, DIR_SOUTHEAST, MakeCharAction('_')},
    {GESTURE_SWIPE_SHORT, DIR_SOUTHWEST, MakeCharAction('[')},
    {GESTURE_SWIPE_SHORT, DIR_WEST, MakeCharAction('(')},
};

constexpr GestureBinding kCell4Bindings[] = {
    {GESTURE_TAP, DIR_CENTER, MakeCharAction('o')},
    {GESTURE_SWIPE_SHORT, DIR_NORTH, MakeCharAction('u')},
    {GESTURE_SWIPE_SHORT, DIR_NORTHWEST, MakeCharAction('q')},
    {GESTURE_SWIPE_SHORT, DIR_WEST, MakeCharAction('c')},
    {GESTURE_SWIPE_SHORT, DIR_SOUTHWEST, MakeCharAction('g')},
    {GESTURE_SWIPE_SHORT, DIR_SOUTH, MakeCharAction('d')},
    {GESTURE_SWIPE_SHORT, DIR_SOUTHEAST, MakeCharAction('j')},
    {GESTURE_SWIPE_SHORT, DIR_EAST, MakeCharAction('b')},
    {GESTURE_SWIPE_SHORT, DIR_NORTHEAST, MakeCharAction('p')},
    {GESTURE_SWIPE_RETURN, DIR_NORTH, MakeCharAction('U')},
    {GESTURE_SWIPE_RETURN, DIR_NORTHWEST, MakeCharAction('Q')},
    {GESTURE_SWIPE_RETURN, DIR_WEST, MakeCharAction('C')},
    {GESTURE_SWIPE_RETURN, DIR_SOUTHWEST, MakeCharAction('G')},
    {GESTURE_SWIPE_RETURN, DIR_SOUTH, MakeCharAction('D')},
    {GESTURE_SWIPE_RETURN, DIR_SOUTHEAST, MakeCharAction('J')},
    {GESTURE_SWIPE_RETURN, DIR_EAST, MakeCharAction('B')},
    {GESTURE_SWIPE_RETURN, DIR_NORTHEAST, MakeCharAction('P')},
    {GESTURE_HOLD, DIR_CENTER, MakeCharAction('O')},
    // Consume a recognized clockwise loop without typing. Removing the binding
    // would let the same loop fall through to swipe-return classification.
    {GESTURE_CIRCLE_CW, DIR_CENTER, KeyAction{}},
    {GESTURE_CIRCLE_CCW, DIR_CENTER, MakeCharAction('5')},
};

constexpr GestureBinding kCell5Bindings[] = {
    {GESTURE_CIRCLE_CCW, DIR_CENTER, MakeCharAction('6')},
    {GESTURE_CIRCLE_CW, DIR_CENTER, KeyAction{}},
    {GESTURE_TAP, DIR_CENTER, MakeCharAction('r')},
    {GESTURE_HOLD, DIR_CENTER, MakeCharAction('R')},
    {GESTURE_SWIPE_SHORT, DIR_WEST, MakeCharAction('m')},
    {GESTURE_SWIPE_RETURN, DIR_WEST, MakeCharAction('M')},
    {GESTURE_SWIPE_SHORT, DIR_NORTHWEST, MakeCharAction('|')},
    {GESTURE_SWIPE_SHORT, DIR_NORTH, MakeSpecialAction("<UP>")},
    {GESTURE_SWIPE_SHORT, DIR_NORTHEAST, MakeCharAction('}')},
    {GESTURE_SWIPE_SHORT, DIR_EAST, MakeCharAction(')')},
    {GESTURE_SWIPE_SHORT, DIR_SOUTHEAST, MakeCharAction(']')},
    {GESTURE_SWIPE_SHORT, DIR_SOUTH, MakeSpecialAction("<DOWN>")},
    {GESTURE_SWIPE_SHORT, DIR_SOUTHWEST, MakeCharAction('@')},
};

constexpr GestureBinding kCell6Bindings[] = {
    {GESTURE_CIRCLE_CCW, DIR_CENTER, MakeCharAction('7')},
    {GESTURE_CIRCLE_CW, DIR_CENTER, KeyAction{}},
    {GESTURE_TAP, DIR_CENTER, MakeCharAction('t')},
    {GESTURE_HOLD, DIR_CENTER, MakeCharAction('T')},
    {GESTURE_SWIPE_SHORT, DIR_EAST, MakeCharAction('*')},
    {GESTURE_SWIPE_SHORT, DIR_NORTHEAST, MakeCharAction('y')},
    {GESTURE_SWIPE_RETURN, DIR_NORTHEAST, MakeCharAction('Y')},
    {GESTURE_SWIPE_SHORT, DIR_NORTHWEST, MakeCharAction('~')},
    {GESTURE_SWIPE_SHORT, DIR_WEST, MakeCharAction('<')},
    {GESTURE_SWIPE_SHORT, DIR_SOUTHEAST, MakeCharAction('\t')},
};

constexpr GestureBinding kCell7Bindings[] = {
    {GESTURE_CIRCLE_CCW, DIR_CENTER, MakeCharAction('8')},
    {GESTURE_CIRCLE_CW, DIR_CENTER, KeyAction{}},
    {GESTURE_TAP, DIR_CENTER, MakeCharAction('e')},
    {GESTURE_HOLD, DIR_CENTER, MakeCharAction('E')},
    {GESTURE_SWIPE_SHORT, DIR_NORTH, MakeCharAction('w')},
    {GESTURE_SWIPE_RETURN, DIR_NORTH, MakeCharAction('W')},
    {GESTURE_SWIPE_SHORT, DIR_EAST, MakeCharAction('z')},
    {GESTURE_SWIPE_RETURN, DIR_EAST, MakeCharAction('Z')},
    {GESTURE_SWIPE_SHORT, DIR_NORTHWEST, MakeCharAction('"')},
    {GESTURE_SWIPE_SHORT, DIR_NORTHEAST, MakeCharAction('\'')},
    {GESTURE_SWIPE_SHORT, DIR_SOUTHWEST, MakeCharAction(',')},
    {GESTURE_SWIPE_SHORT, DIR_SOUTH, MakeCharAction('.')},
    {GESTURE_SWIPE_SHORT, DIR_SOUTHEAST, MakeCharAction(':')},
};

constexpr GestureBinding kCell8Bindings[] = {
    {GESTURE_CIRCLE_CCW, DIR_CENTER, MakeCharAction('9')},
    {GESTURE_CIRCLE_CW, DIR_CENTER, KeyAction{}},
    {GESTURE_TAP, DIR_CENTER, MakeCharAction('s')},
    {GESTURE_HOLD, DIR_CENTER, MakeCharAction('S')},
    {GESTURE_SWIPE_SHORT, DIR_NORTHWEST, MakeCharAction('f')},
    {GESTURE_SWIPE_RETURN, DIR_NORTHWEST, MakeCharAction('F')},
    {GESTURE_SWIPE_SHORT, DIR_WEST, MakeCharAction('#')},
    {GESTURE_SWIPE_SHORT, DIR_NORTH, MakeCharAction('&')},
    {GESTURE_SWIPE_SHORT, DIR_EAST, MakeCharAction('>')},
    {GESTURE_SWIPE_SHORT, DIR_SOUTHWEST, MakeCharAction(';')},
};

constexpr GestureBinding kDigitZeroBindings[] = {
    {GESTURE_TAP, DIR_CENTER, MakeCharAction('0')},
};

constexpr GestureBinding kCommandShiftBindings[] = {
    {GESTURE_TAP, DIR_CENTER, MakeSpecialAction("<SHIFT>")},
    {GESTURE_SWIPE_SHORT, DIR_CENTER, MakeSpecialAction("<SHIFT>")},
};

constexpr GestureBinding kCommandBackspaceBindings[] = {
    {GESTURE_TAP, DIR_CENTER, MakeBackspaceAction()},
    {GESTURE_SWIPE_SHORT, DIR_CENTER, MakeBackspaceAction()},
};

constexpr GestureBinding kCommandSpaceBindings[] = {
    {GESTURE_TAP, DIR_CENTER, MakeCharAction(' ')},
    {GESTURE_SWIPE_SHORT, DIR_CENTER, MakeCharAction(' ')},
};

constexpr GestureBinding kCommandEnterBindings[] = {
    {GESTURE_TAP, DIR_CENTER, MakeCharAction('\n')},
    {GESTURE_SWIPE_SHORT, DIR_CENTER, MakeCharAction('\n')},
};

struct BindingSpan {
    const GestureBinding *data;
    std::size_t size;
    bool direction_fallback;
};

constexpr BindingSpan kBindingTable[] = {
    {kCell0Bindings, ArraySize(kCell0Bindings), false},   // cell 0
    {kCell1Bindings, ArraySize(kCell1Bindings), false},   // cell 1
    {kCell2Bindings, ArraySize(kCell2Bindings), false},   // cell 2
    {kDigitZeroBindings, ArraySize(kDigitZeroBindings), false}, // cell 3
    {kCell3Bindings, ArraySize(kCell3Bindings), false},   // cell 4
    {kCell4Bindings, ArraySize(kCell4Bindings), false},   // cell 5
    {kCell5Bindings, ArraySize(kCell5Bindings), false},   // cell 6
    {kCommandShiftBindings, ArraySize(kCommandShiftBindings), true},   // cell 7
    {kCell6Bindings, ArraySize(kCell6Bindings), false},   // cell 8
    {kCell7Bindings, ArraySize(kCell7Bindings), false},   // cell 9
    {kCell8Bindings, ArraySize(kCell8Bindings), false},   // cell 10
    {kCommandBackspaceBindings, ArraySize(kCommandBackspaceBindings), true}, // cell 11
    {kCommandSpaceBindings, ArraySize(kCommandSpaceBindings), true},  // cell 12
    {kCommandSpaceBindings, ArraySize(kCommandSpaceBindings), true},  // cell 13
    {kCommandSpaceBindings, ArraySize(kCommandSpaceBindings), true},  // cell 14
    {kCommandEnterBindings, ArraySize(kCommandEnterBindings), true},  // cell 15
};

constexpr bool IsValidGrid(uint8_t grid_pos) {
    return grid_pos < ArraySize(kBindingTable);
}

constexpr GestureType NormalizeGestureForLookup(GestureType gesture) {
    switch (gesture) {
        case GESTURE_SWIPE_LONG:
            return GESTURE_SWIPE_SHORT;
        default:
            return gesture;
    }
}

}  // namespace

const GestureBinding *FindGestureBinding(uint8_t grid_pos,
                                         GestureType gesture,
                                         Direction direction) {
    if (!IsValidGrid(grid_pos)) {
        return nullptr;
    }
    const BindingSpan span = kBindingTable[grid_pos];
    auto find_match = [&](GestureType g, Direction d) -> const GestureBinding * {
        if (span.data == nullptr || span.size == 0) {
            return nullptr;
        }
        for (std::size_t i = 0; i < span.size; ++i) {
            if (span.data[i].gesture == g &&
                span.data[i].direction == d) {
                return &span.data[i];
            }
        }
        return nullptr;
    };

    const GestureType alias = NormalizeGestureForLookup(gesture);
    const bool has_alias = alias != gesture;

    const GestureBinding *binding = find_match(gesture, direction);
    if (!binding && has_alias) {
        binding = find_match(alias, direction);
    }

    if (!binding && span.direction_fallback && direction != DIR_CENTER) {
        binding = find_match(gesture, DIR_CENTER);
        if (!binding && has_alias) {
            binding = find_match(alias, DIR_CENTER);
        }
    }

    return binding;
}

bool HasGestureBinding(uint8_t grid_pos,
                       GestureType gesture,
                       Direction direction) {
    return FindGestureBinding(grid_pos, gesture, direction) != nullptr;
}

KeyMap::KeyMap()
    : caps_lock_state_(false) {}

void KeyMap::init() {
    ESP_LOGI(TAG, "Keymap initialised; runtime dispatches actions to USB HID");
}

KeyAction KeyMap::execute(uint8_t grid_pos, GestureType gesture,
                     Direction direction) {
    if (!IsValidGrid(grid_pos)) {
        ESP_LOGW(TAG, "Unhandled grid position: %u", grid_pos);
        return KeyAction{};
    }
    const GestureBinding *binding =
        FindGestureBinding(grid_pos, gesture, direction);
    if (binding == nullptr) {
        debug(gesture, direction);
        return KeyAction{};
    }
    performAction(binding->action);
    return binding->action;
}

void KeyMap::charAction(char c) {
    const char *label = nullptr;
    switch (c) {
        case '\n': label = "<ENTER>"; break;
        case ' ': label = "<SPACE>"; break;
        case '\t': label = "<TAB>"; break;
        default: break;
    }

    if (label != nullptr) {
        ESP_LOGI(TAG, "Key output: %s", label);
    } else if (c >= 32 && c <= 126) {
        ESP_LOGI(TAG, "Key output: %c", c);
    } else {
        ESP_LOGI(TAG, "Key output: 0x%02X",
                       static_cast<unsigned>(static_cast<uint8_t>(c)));
    }
}

void KeyMap::stringAction(const char *str) {
    if (str != nullptr) {
        ESP_LOGI(TAG, "String: %s", str);
    }
}

void KeyMap::backspaceAction() {
    ESP_LOGI(TAG, "Backspace");
}

void KeyMap::capsLockAction() {
    caps_lock_state_ = !caps_lock_state_;
    ESP_LOGI(TAG, "Caps Lock: %s", caps_lock_state_ ? "ON" : "OFF");
}

void KeyMap::specialAction(const char *label) {
    if (label != nullptr) {
        ESP_LOGI(TAG, "Key output: %s", label);
    }
}

void KeyMap::debug(GestureType gesture, Direction direction) {
    ESP_LOGD(TAG, "Unhandled gesture %d direction %d",
                   gesture, direction);
}

void KeyMap::performAction(const KeyAction &action) {
    switch (action.type) {
        case KeyActionType::Char:
            charAction(action.ch);
            break;
        case KeyActionType::String:
            stringAction(action.str);
            break;
        case KeyActionType::Backspace:
            backspaceAction();
            break;
        case KeyActionType::Special:
            specialAction(action.str);
            break;
        case KeyActionType::None:
        default:
            ESP_LOGD(TAG, "No action mapped");
            break;
    }
}
