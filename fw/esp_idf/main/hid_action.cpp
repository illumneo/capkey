#include "hid_action.h"

#include <cstring>

namespace {
// USB HID Usage Tables, Keyboard/Keypad page, as used by TinyUSB's hid.h.
constexpr uint8_t kShift = 0x02;  // Left Shift modifier bit.

bool asciiReport(uint8_t ch, bool one_shot_shift, bool caps_lock,
                 HidKeyboardReport &report) {
    report = {};
    if ((ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z')) {
        const bool upper = ch >= 'A' && ch <= 'Z';
        report.keycodes[0] = static_cast<uint8_t>(0x04 + ch - (upper ? 'A' : 'a'));
        // Actions denote literal characters. Host Caps Lock is compensated;
        // a one-shot Shift requests uppercase even for a lowercase action.
        if ((upper || one_shot_shift) != caps_lock) report.modifier = kShift;
        return true;
    }
    constexpr char plain[] = "1234567890-=[]\\;'`,./";
    constexpr char shifted[] = "!@#$%^&*()_+{}|:\"~<>?";
    constexpr uint8_t usages[] = {
        0x1e,0x1f,0x20,0x21,0x22,0x23,0x24,0x25,0x26,0x27,
        0x2d,0x2e,0x2f,0x30,0x31,0x33,0x34,0x35,0x36,0x37,0x38
    };
    static_assert(sizeof(plain) == sizeof(shifted), "US symbol pairs");
    static_assert(sizeof(plain) - 1 == sizeof(usages), "US symbol usages");
    for (size_t i = 0; i < sizeof(usages); ++i) {
        if (ch == static_cast<uint8_t>(plain[i]) || ch == static_cast<uint8_t>(shifted[i])) {
            report.keycodes[0] = usages[i];
            if (ch == static_cast<uint8_t>(shifted[i]) || one_shot_shift) report.modifier = kShift;
            return true;
        }
    }
    switch (ch) {
        case '\b': report.keycodes[0] = 0x2a; break;
        case '\t': report.keycodes[0] = 0x2b; break;
        case '\n': case '\r': report.keycodes[0] = 0x28; break;
        case 0x1b: report.keycodes[0] = 0x29; break;
        case ' ': report.keycodes[0] = 0x2c; break;
        case 0x7f: report.keycodes[0] = 0x4c; break;
        default: return false;  // No implicit Ctrl shortcuts or UTF-8 byte typing.
    }
    if (one_shot_shift) report.modifier = kShift;
    return true;
}

bool specialUsage(const char *label, uint8_t &usage) {
    if (!label) return false;
    struct Entry { const char *label; uint8_t usage; };
    constexpr Entry entries[] = {
        {"<UP>",0x52}, {"<DOWN>",0x51}, {"<LEFT>",0x50}, {"<RIGHT>",0x4f},
        {"<ENTER>",0x28}, {"<TAB>",0x2b}, {"<SPACE>",0x2c},
        {"<ESC>",0x29}, {"<ESCAPE>",0x29}, {"<BACKSPACE>",0x2a},
        {"<DELETE>",0x4c}, {"<HOME>",0x4a}, {"<END>",0x4d},
        {"<PAGEUP>",0x4b}, {"<PAGEDOWN>",0x4e}, {"<CAPSLOCK>",0x39}
    };
    for (const auto &entry : entries) {
        if (std::strcmp(label, entry.label) == 0) {
            usage = entry.usage;
            return true;
        }
    }
    return false;
}
}  // namespace

bool HidActionEncoder::encode(const KeyAction &action, HidActionPlan &plan) const {
    plan = {};  // Failed validation cannot leave a sendable prefix behind.
    HidActionPlan candidate;
    candidate.next_shift_pending = shift_pending_;
    auto append = [&](HidKeyboardReport report) {
        if (static_cast<size_t>(candidate.report_count) + 2 > HidActionPlan::kMaxReports) return false;
        candidate.reports[candidate.report_count++] = report;
        candidate.reports[candidate.report_count++] = {};  // Always release all keys/modifiers.
        candidate.next_shift_pending = false;
        return true;
    };
    auto character = [&](uint8_t ch) {
        HidKeyboardReport report;
        return asciiReport(ch, candidate.next_shift_pending, caps_lock_, report) && append(report);
    };
    switch (action.type) {
        case KeyActionType::Char:
            if (!character(static_cast<uint8_t>(action.ch))) return false;
            break;
        case KeyActionType::String:
            if (!action.str || !action.str[0]) return false;
            for (size_t i = 0; action.str[i]; ++i) {
                if (i >= HidActionPlan::kMaxTextLength ||
                    !character(static_cast<uint8_t>(action.str[i]))) return false;
            }
            break;
        case KeyActionType::Backspace:
            if (!character('\b')) return false;
            break;
        case KeyActionType::Special: {
            if (action.str && std::strcmp(action.str, "<SHIFT>") == 0) {
                candidate.next_shift_pending = !shift_pending_;
                break;
            }
            HidKeyboardReport report;
            if (!specialUsage(action.str, report.keycodes[0])) return false;
            report.modifier = candidate.next_shift_pending ? kShift : 0;
            if (!append(report)) return false;
            break;
        }
        case KeyActionType::None:
        default:
            return false;
    }
    plan = candidate;
    return true;
}
