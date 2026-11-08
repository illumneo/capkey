#pragma once

#include <cstdint>

#include "gestureTypes.h"

enum class KeyActionType {
    None = 0,
    Char,
    String,
    Backspace,
    Special,
};

struct KeyAction {
    constexpr KeyAction() : type(KeyActionType::None), ch(0), str(nullptr) {}
    constexpr KeyAction(KeyActionType t, char c, const char *s)
        : type(t), ch(c), str(s) {}

    KeyActionType type;
    char ch;
    const char *str;
};

constexpr KeyAction MakeCharAction(char c) {
    return KeyAction(KeyActionType::Char, c, nullptr);
}

constexpr KeyAction MakeStringAction(const char *s) {
    return KeyAction(KeyActionType::String, 0, s);
}

constexpr KeyAction MakeBackspaceAction() {
    return KeyAction(KeyActionType::Backspace, 0, nullptr);
}

constexpr KeyAction MakeSpecialAction(const char *label) {
    return KeyAction(KeyActionType::Special, 0, label);
}

struct GestureBinding {
    GestureType gesture;
    Direction direction;
    KeyAction action;
    // Optional net-distance override for a coherent short swipe. Zero uses
    // the global threshold; path straightness and endpoint retention remain.
    float coherent_min_distance = 0.0f;
};

const GestureBinding *FindGestureBinding(uint8_t grid_pos,
                                         GestureType gesture,
                                         Direction direction);

bool HasGestureBinding(uint8_t grid_pos,
                       GestureType gesture,
                       Direction direction);
