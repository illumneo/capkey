#include "gestureDetector.h"
#include "gestureLayout.h"
#include "touch_processing.h"

#include <cmath>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <string>

namespace {
std::string jsonString(const std::string& text) {
    std::ostringstream out;
    out << '"';
    for (const unsigned char c : text) {
        if (c == '"' || c == '\\') {
            out << '\\' << c;
        } else if (c < 0x20) {
            out << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                << static_cast<unsigned>(c) << std::dec;
        } else {
            out << c;
        }
    }
    out << '"';
    return out.str();
}

void printAction(const GestureBinding* binding) {
    if (!binding) {
        std::cout << "null";
        return;
    }
    const auto& action = binding->action;
    const char* type = "none";
    std::string value;
    switch (action.type) {
        case KeyActionType::Char: type = "char"; value.assign(1, action.ch); break;
        case KeyActionType::String: type = "string"; value = action.str ? action.str : ""; break;
        case KeyActionType::Backspace: type = "backspace"; break;
        case KeyActionType::Special: type = "special"; value = action.str ? action.str : ""; break;
        case KeyActionType::None: break;
    }
    std::cout << "{\"type\":" << jsonString(type)
              << ",\"value\":" << jsonString(value) << '}';
}
}  // namespace

// Line protocol driven by replay_capture.py:
// S <source_line> <uint32 timestamp_us> <valid_mask> <15 signed deltas>
// R resets state at a recorded reboot or explicitly accepted discontinuity.
// C <charge_times> sets count normalization from this boot's capture metadata.
int main(int argc, char** argv) {
    if (argc != 2 || (std::string(argv[1]) != "legacy" && std::string(argv[1]) != "pcb")) {
        std::cerr << "usage: replay_main legacy|pcb\n";
        return 2;
    }
    const auto mode = std::string(argv[1]) == "legacy"
                          ? swipe::TouchProcessingMode::Legacy
                          : swipe::TouchProcessingMode::Pcb;
    GestureDetector detector;
    uint32_t charge_times = swipe::kReferenceChargeTimes;
    std::string line;
    std::cout << std::setprecision(std::numeric_limits<float>::max_digits10);
    while (std::getline(std::cin, line)) {
        if (line == "R") {
            detector.reset();
            std::cout << "{\"type\":\"reset_ack\"}" << std::endl;
            continue;
        }
        std::istringstream input(line);
        char command;
        if (!line.empty() && line[0] == 'C') {
            uint64_t value;
            std::string extra;
            if (!(input >> command >> value) || value == 0 || value > UINT32_MAX ||
                (input >> extra)) {
                std::cerr << "charge_times must be an integer in 1..UINT32_MAX\n";
                return 2;
            }
            charge_times = static_cast<uint32_t>(value);
            std::cout << "{\"type\":\"configuration_ack\",\"charge_times\":"
                      << charge_times << '}' << std::endl;
            continue;
        }
        uint64_t source_line, timestamp, mask;
        int32_t deltas[swipe::kTouchPadCount] = {};
        if (!(input >> command >> source_line >> timestamp >> mask) || command != 'S' ||
            timestamp > UINT32_MAX || mask > 0x7fff) {
            std::cerr << "invalid host replay command\n";
            return 2;
        }
        for (auto& value : deltas) {
            if (!(input >> value)) {
                std::cerr << "expected 15 signed physical-pad deltas\n";
                return 2;
            }
        }
        std::string extra;
        if (input >> extra) {
            std::cerr << "unexpected extra input\n";
            return 2;
        }
        const auto point = swipe::processTouch(deltas, static_cast<uint16_t>(mask), mode, charge_times);
        const bool detected = point.valid && detector.update(
            point.x, point.y, point.z, static_cast<uint32_t>(timestamp));
        std::cout << "{\"type\":\"sample_result\",\"source_line\":" << source_line
                  << ",\"timestamp_us\":" << timestamp
                  << ",\"charge_times\":" << charge_times
                  << ",\"reference_charge_times\":" << swipe::kReferenceChargeTimes
                  << ",\"delta_scale\":" << static_cast<float>(swipe::kReferenceChargeTimes) / charge_times
                  << ",\"valid\":" << (point.valid ? "true" : "false")
                  << ",\"below_release_threshold\":"
                  << (point.valid && point.z < TOUCH_RELEASE_THRESHOLD ? "true" : "false")
                  << ",\"x\":" << point.x << ",\"y\":" << point.y
                  << ",\"z\":" << point.z
                  << ",\"x_milli\":" << std::lround(point.x * 1000.0f)
                  << ",\"y_milli\":" << std::lround(point.y * 1000.0f)
                  << ",\"z_milli\":" << std::lround(point.z * 1000.0f)
                  << ",\"gesture\":";
        if (detected) {
            const auto event = detector.getDetectedGesture();
            std::cout << "{\"grid\":" << static_cast<unsigned>(event.grid_position)
                      << ",\"type\":" << static_cast<int>(event.type)
                      << ",\"direction\":" << static_cast<int>(event.direction)
                      << ",\"max_distance\":" << detector.maxDistance()
                      << ",\"start_x\":" << detector.startX()
                      << ",\"start_y\":" << detector.startY()
                      << ",\"action\":";
            printAction(FindGestureBinding(event.grid_position, event.type, event.direction));
            std::cout << '}';
        } else {
            std::cout << "null";
        }
        std::cout << '}' << std::endl;
    }
    return 0;
}
