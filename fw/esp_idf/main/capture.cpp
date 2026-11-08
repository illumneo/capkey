#include <algorithm>
#include "capture.h"

#include <atomic>
#include <climits>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <inttypes.h>

#include "driver/touch_sens.h"
#include "esp_app_desc.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_random.h"
#include "esp_rom_crc.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "gestureDetector.h"
#include "keyMap.h"
#include "sdkconfig.h"
#include "touch_processing.h"
#include "touchpad.h"
#include "usb_keyboard.h"

#ifndef SWIPE_SDKCONFIG_SHA256
#define SWIPE_SDKCONFIG_SHA256 "unknown"
#endif
#ifndef SWIPE_RECOGNIZER_SHA256
#define SWIPE_RECOGNIZER_SHA256 "unknown"
#endif

namespace {
constexpr unsigned kPads = 15;
constexpr uint16_t kBoardMask = 0x1ffe;
constexpr unsigned kAcquisitionQueueDepth = 128;
constexpr unsigned kTelemetryQueueDepth = 128;
constexpr unsigned kStartupWarmupScans = 3;
constexpr size_t kPayloadSize = 212;
#ifdef CONFIG_SWIPE_CAPTURE_CHARGE_TIMES
constexpr unsigned kChargeTimes = CONFIG_SWIPE_CAPTURE_CHARGE_TIMES;
#else
constexpr unsigned kChargeTimes = 200;
#endif
constexpr unsigned kActiveThreshold = 2000 * kChargeTimes / 800;
static_assert(std::atomic<uint32_t>::is_always_lock_free);

// SWP1 sample layout is unchanged. dropped_scans counts acquisition loss only.
struct Sample {
    uint64_t timestamp_us;
    uint32_t scan_seq;
    uint32_t dropped_scans;
    uint32_t snapshot_duration_us;
    uint32_t boot_id;
    uint16_t registered_mask;
    uint16_t raw_valid_mask;
    uint16_t smooth_valid_mask;
    uint16_t benchmark_valid_mask;
    uint32_t raw[kPads];
    uint32_t smooth[kPads];
    uint32_t benchmark[kPads];
};
static_assert(offsetof(Sample, raw) == 32);
static_assert(offsetof(Sample, benchmark) + sizeof(Sample::benchmark) == kPayloadSize);

enum class EventKind : uint8_t { Gesture, Reset, IdleCheckpoint };
struct DeviceEvent {
    EventKind kind = EventKind::Gesture;
    uint64_t timestamp_us = 0;
    uint32_t scan_seq = 0;
    uint32_t event_seq = 0;
    uint32_t processing_epoch = 0;
    uint32_t acq_dropped_scans = 0;
    float x = 0, y = 0, z = 0;
    float start_x = 0, start_y = 0, max_distance = 0;
    uint8_t gesture_type = 0, direction = 0, grid_position = 0;
    KeyAction action;
    bool hid_queued = false;
    const char *reason = "";  // All strings refer to static storage.
};
struct TelemetryItem {
    Sample sample;
    DeviceEvent events[2];
    uint32_t stream_generation = 0;
    uint8_t event_count = 0;
    bool recording = false;
};

struct RuntimeState {
    touch_sensor_handle_t sensor = nullptr;
    touch_channel_handle_t channels[kPads] = {};
    QueueHandle_t acquisition_queue = nullptr;
    QueueHandle_t telemetry_queue = nullptr;
    uint16_t registered_mask = 0;
    uint32_t boot_id = 0;
    std::atomic<uint32_t> scan_seq{0};
    std::atomic<uint32_t> acquisition_drops{0};
    std::atomic<uint32_t> processed_scan_seq{0};
    std::atomic<uint32_t> processing_epoch{0};
    std::atomic<uint32_t> event_seq{0};
    std::atomic<uint32_t> telemetry_dropped_samples{0};
    std::atomic<uint32_t> telemetry_dropped_events{0};
    std::atomic<uint32_t> human_log_drops{0};
    std::atomic<uint32_t> stream_generation{0};
    std::atomic<bool> streaming{false};
    uint32_t packet_seq = 0;             // USB task only.
    uint32_t transport_failures = 0;     // USB task only.
    esp_err_t registration_errors[kPads] = {};
    portMUX_TYPE telemetry_mux = portMUX_INITIALIZER_UNLOCKED;
    portMUX_TYPE checkpoint_mux = portMUX_INITIALIZER_UNLOCKED;
    uint32_t checkpoint_request = 0;
    uint64_t checkpoint_after_us = 0;
};
RuntimeState runtime;

bool IRAM_ATTR scanDone(touch_sensor_handle_t,
                       const touch_scan_done_event_data_t *, void *) {
    Sample sample{};
    sample.timestamp_us = esp_timer_get_time();
    sample.scan_seq = runtime.scan_seq.fetch_add(1, std::memory_order_relaxed) + 1;
    sample.dropped_scans = runtime.acquisition_drops.load(std::memory_order_relaxed);
    sample.boot_id = runtime.boot_id;
    sample.registered_mask = runtime.registered_mask;
    for (unsigned pad = 1; pad < kPads; ++pad) {
        auto handle = runtime.channels[pad];
        if (handle == nullptr) continue;
        const uint16_t bit = static_cast<uint16_t>(1u << pad);
        if (touch_channel_read_data(handle, TOUCH_CHAN_DATA_TYPE_RAW, &sample.raw[pad]) == ESP_OK)
            sample.raw_valid_mask |= bit;
        if (touch_channel_read_data(handle, TOUCH_CHAN_DATA_TYPE_SMOOTH, &sample.smooth[pad]) == ESP_OK)
            sample.smooth_valid_mask |= bit;
        if (touch_channel_read_data(handle, TOUCH_CHAN_DATA_TYPE_BENCHMARK, &sample.benchmark[pad]) == ESP_OK)
            sample.benchmark_valid_mask |= bit;
    }
    sample.snapshot_duration_us = static_cast<uint32_t>(esp_timer_get_time() - sample.timestamp_us);
    BaseType_t woken = pdFALSE;
    if (xQueueSendFromISR(runtime.acquisition_queue, &sample, &woken) != pdTRUE)
        runtime.acquisition_drops.fetch_add(1, std::memory_order_relaxed);
    return woken == pdTRUE;
}

DeviceEvent eventFor(const Sample &sample, EventKind kind, uint32_t epoch) {
    DeviceEvent event;
    event.kind = kind;
    event.timestamp_us = sample.timestamp_us;
    event.scan_seq = sample.scan_seq;
    event.event_seq = runtime.event_seq.fetch_add(1) + 1;
    event.processing_epoch = epoch;
    event.acq_dropped_scans = sample.dropped_scans;
    return event;
}

void processingTask(void *) {
    GestureDetector detector;
    KeyMap keymap;
    keymap.init();
    uint32_t previous_scan = 0, previous_drops = 0, epoch = 0;
    uint32_t checkpoint_served = 0;
    uint64_t previous_timestamp = 0;
    bool have_previous = false, wait_for_idle = false;
    while (true) {
        TelemetryItem item{};
        if (xQueueReceive(runtime.acquisition_queue, &item.sample, portMAX_DELAY) != pdTRUE) continue;
        const Sample &sample = item.sample;
        const bool gap = have_previous &&
            (sample.scan_seq - previous_scan != 1 || sample.dropped_scans != previous_drops ||
             sample.timestamp_us <= previous_timestamp);
        previous_scan = sample.scan_seq;
        previous_drops = sample.dropped_scans;
        previous_timestamp = sample.timestamp_us;
        have_previous = true;
        int32_t deltas[kPads]{};
        uint16_t valid = sample.registered_mask & sample.smooth_valid_mask & sample.benchmark_valid_mask;
        for (unsigned pad = 1; pad < kPads; ++pad) {
            const int64_t delta = static_cast<int64_t>(sample.smooth[pad]) - sample.benchmark[pad];
            if (delta < INT32_MIN || delta > INT32_MAX) valid &= ~(1u << pad);
            else deltas[pad] = static_cast<int32_t>(delta);
        }
        const auto point = swipe::processTouch(deltas, valid, swipe::TouchProcessingMode::Pcb, kChargeTimes);
        if (gap || !point.valid) {
            detector.reset();
            ++epoch;
            runtime.processing_epoch.store(epoch);
            wait_for_idle = true;
            auto &event = item.events[item.event_count++];
            event = eventFor(sample, EventKind::Reset, epoch);
            event.reason = gap ? "acquisition_gap" : "invalid_required_channels";
        }
        // Never fabricate an action from the tail of a touch interrupted by loss.
        if (point.valid && wait_for_idle && point.z < TOUCH_RELEASE_THRESHOLD) wait_for_idle = false;
        if (point.valid && !wait_for_idle && detector.update(
                point.x, point.y, point.z, static_cast<uint32_t>(sample.timestamp_us))) {
            const auto detected = detector.getDetectedGesture();
            auto &event = item.events[item.event_count++];
            event = eventFor(sample, EventKind::Gesture, epoch);
            event.x = point.x; event.y = point.y; event.z = point.z;
            event.start_x = detector.startX(); event.start_y = detector.startY();
            event.max_distance = detector.maxDistance();
            event.gesture_type = static_cast<uint8_t>(detected.type);
            event.direction = static_cast<uint8_t>(detected.direction);
            event.grid_position = detected.grid_position;
            // HID has its own queue/task. Neither a busy keyboard endpoint nor
            // an unread calibration serial port can block touch recognition.
            event.action = keymap.execute(detected.grid_position, detected.type, detected.direction);
            if (event.action.type != KeyActionType::None) {
                HidOrigin origin;
                origin.source = HidOrigin::Source::Physical;
                origin.boot_id = runtime.boot_id; origin.processing_epoch = epoch;
                origin.event_seq = event.event_seq; origin.scan_seq = sample.scan_seq;
                origin.timestamp_us = sample.timestamp_us;
                origin.duration_us = detector.durationUs();
                origin.grid = detected.grid_position;
                origin.gesture_type = event.gesture_type; origin.direction = event.direction;
                origin.start_x = detector.startX(); origin.start_y = detector.startY();
                origin.end_x = detector.endX(); origin.end_y = detector.endY();
                origin.peak_dx = detector.maxDx(); origin.peak_dy = detector.maxDy();
                origin.max_distance = detector.maxDistance(); origin.path_length = detector.pathLength();
                event.hid_queued = usb::enqueue(event.action, origin);
            }
        }
        uint32_t checkpoint_request;
        uint64_t checkpoint_after;
        portENTER_CRITICAL(&runtime.checkpoint_mux);
        checkpoint_request = runtime.checkpoint_request;
        checkpoint_after = runtime.checkpoint_after_us;
        portEXIT_CRITICAL(&runtime.checkpoint_mux);
        const bool checkpoint_in_item = runtime.streaming.load() &&
            checkpoint_request != checkpoint_served && sample.timestamp_us >= checkpoint_after &&
            point.valid && !wait_for_idle && point.z < TOUCH_RELEASE_THRESHOLD && detector.isIdle();
        if (checkpoint_in_item) {
            auto &event = item.events[item.event_count++];
            event = eventFor(sample, EventKind::IdleCheckpoint, epoch);
            event.reason = "capture_start_idle";
        }
        runtime.processed_scan_seq.store(sample.scan_seq);
        // Recognition is complete before this nonblocking telemetry enqueue.
        // Host backpressure can lose recorded frames, never block the detector.
        // The short critical section also defines STOP's enqueue boundary. No
        // transport call occurs under this lock, and the queue send never waits.
        portENTER_CRITICAL(&runtime.telemetry_mux);
        item.recording = runtime.streaming.load();
        item.stream_generation = runtime.stream_generation.load();
        if (item.recording || item.event_count) {
            if (xQueueSend(runtime.telemetry_queue, &item, 0) == pdTRUE) {
                // A full telemetry queue must not consume the synchronization
                // request. Retry at the next observed idle sample after loss.
                if (checkpoint_in_item && item.recording) checkpoint_served = checkpoint_request;
            } else {
                if (item.recording) {
                    runtime.telemetry_dropped_samples.fetch_add(1);
                    runtime.telemetry_dropped_events.fetch_add(item.event_count);
                } else {
                    runtime.human_log_drops.fetch_add(item.event_count);
                }
            }
        }
        portEXIT_CRITICAL(&runtime.telemetry_mux);
    }
}

void put16(uint8_t *dst, uint16_t value) { std::memcpy(dst, &value, sizeof(value)); }
void put32(uint8_t *dst, uint32_t value) { std::memcpy(dst, &value, sizeof(value)); }

bool writeBytes(const void *bytes, size_t total) {
    size_t sent = 0;
    while (sent < total) {
        const size_t n = usb::write(static_cast<const uint8_t *>(bytes) + sent,
                                    total - sent, 20);
        if (n <= 0) { ++runtime.transport_failures; return false; }
        sent += static_cast<size_t>(n);
    }
    return true;
}

bool writePacket(uint8_t type, const void *payload, uint16_t length) {
    uint8_t frame[4096 + 16];
    if (length > 4096) return false;
    std::memcpy(frame, "SWP1", 4);
    frame[4] = 1; frame[5] = type;
    put16(frame + 6, length);
    put32(frame + 8, runtime.packet_seq++);
    std::memcpy(frame + 12, payload, length);
    put32(frame + 12 + length, esp_rom_crc32_le(0, frame, 12 + length));
    return writeBytes(frame, 16 + length);
}

const char *actionType(KeyActionType type) {
    switch (type) {
        case KeyActionType::Char: return "char";
        case KeyActionType::String: return "string";
        case KeyActionType::Backspace: return "backspace";
        case KeyActionType::Special: return "special";
        default: return "none";
    }
}

// Escape static action labels, including quote/backslash and control characters.
void escapedLabel(const KeyAction &action, char *out, size_t capacity) {
    const char character[2] = {action.ch, '\0'};
    const char *text = action.type == KeyActionType::Char ? character : action.str;
    if (text == nullptr) text = "";
    size_t used = 0;
    for (const unsigned char *p = reinterpret_cast<const unsigned char *>(text); *p; ++p) {
        char encoded[8];
        int count;
        if (*p == '"' || *p == '\\') count = std::snprintf(encoded, sizeof(encoded), "\\%c", *p);
        else if (*p < 32) count = std::snprintf(encoded, sizeof(encoded), "\\u%04x", *p);
        else { encoded[0] = static_cast<char>(*p); encoded[1] = '\0'; count = 1; }
        if (count < 0 || used + static_cast<size_t>(count) + 1 > capacity) break;
        std::memcpy(out + used, encoded, count); used += count;
    }
    out[used] = '\0';
}

void writeEvent(const DeviceEvent &event) {
    const char *kind = event.kind == EventKind::Gesture ? "gesture" :
                       event.kind == EventKind::Reset ? "processing_reset" : "idle_checkpoint";
    char label[192]; escapedLabel(event.action, label, sizeof(label));
    char json[1400];
    const int n = std::snprintf(json, sizeof(json),
        "{\"event\":\"%s\",\"boot_id\":%" PRIu32 ",\"event_seq\":%" PRIu32
        ",\"scan_seq\":%" PRIu32 ",\"timestamp_us\":%" PRIu64 ",\"processing_epoch\":%" PRIu32
        ",\"model\":\"pcb\",\"x\":%.9g,\"y\":%.9g,\"z\":%.9g,"
        "\"start_x\":%.9g,\"start_y\":%.9g,\"max_distance\":%.9g,"
        "\"gesture_type\":%u,\"direction\":%u,\"grid_position\":%u,"
        "\"action\":{\"type\":\"%s\",\"char_code\":%u,\"label\":\"%s\"},"
        "\"reason\":\"%s\",\"acq_dropped_scans\":%" PRIu32
        ",\"telemetry_dropped_samples\":%" PRIu32 ",\"telemetry_dropped_events\":%" PRIu32
        ",\"transport_failures\":%" PRIu32
        ",\"output_backend\":\"usb_hid\",\"hid_queued\":%s,\"hid_sent\":%s}",
        kind, runtime.boot_id, event.event_seq, event.scan_seq, event.timestamp_us, event.processing_epoch,
        event.x, event.y, event.z, event.start_x, event.start_y, event.max_distance,
        event.gesture_type, event.direction, event.grid_position,
        actionType(event.action.type), static_cast<unsigned>(static_cast<uint8_t>(event.action.ch)), label,
        event.reason, event.acq_dropped_scans,
        runtime.telemetry_dropped_samples.load(), runtime.telemetry_dropped_events.load(), runtime.transport_failures,
        event.hid_queued ? "true" : "false", event.hid_queued ? "null" : "false");
    if (n > 0 && static_cast<size_t>(n) < sizeof(json)) writePacket(4, json, n);
}

void humanEvent(const DeviceEvent &event) {
    if (!usb::status().cdc_connected) return;
    char label[192]; escapedLabel(event.action, label, sizeof(label));
    char text[400];
    const int n = event.kind == EventKind::Gesture
        ? std::snprintf(text, sizeof(text),
              "Gesture: scan=%" PRIu32 " grid=%u type=%u dir=%u Key output: %s%s HID queued=%s\r\n",
              event.scan_seq, event.grid_position, event.gesture_type, event.direction,
              event.action.type == KeyActionType::None ? "<NONE>" : "", label,
              event.hid_queued ? "yes" : "no")
        : std::snprintf(text, sizeof(text), "Recognizer %s: scan=%" PRIu32 " epoch=%" PRIu32 "\r\n",
                        event.reason, event.scan_seq, event.processing_epoch);
    if (n > 0 && static_cast<size_t>(n) < sizeof(text)) writeBytes(text, n);
}

void metadata() {
    const esp_app_desc_t *app = esp_app_get_description();
    const auto hid = usb::status();
    char sha[65];
    for (unsigned i = 0; i < 32; ++i) std::snprintf(sha + i * 2, 3, "%02x", app->app_elf_sha256[i]);
    char errors[192]; size_t used = 0;
    for (unsigned pad = 0; pad < kPads; ++pad) {
        const int n = std::snprintf(errors + used, sizeof(errors) - used, "%s%d", pad ? "," : "", runtime.registration_errors[pad]);
        if (n <= 0 || static_cast<size_t>(n) >= sizeof(errors) - used) return;
        used += n;
    }
    char json[3200];
    const int n = std::snprintf(json, sizeof(json),
        "{\"project\":\"swipe\",\"mode\":\"runtime\",\"protocol_version\":1,\"event_protocol_version\":1,\"streaming\":%s,"
        "\"board\":\"capkey_6x6_50mm\",\"boot_id\":%" PRIu32 ",\"app_version\":\"%s\",\"idf_version\":\"%s\","
        "\"elf_sha256\":\"%s\",\"sdkconfig_sha256\":\"%s\",\"recognizer_sha256\":\"%s\","
        "\"recognizer\":{\"model\":\"pcb\",\"reference_charge_times\":800,\"touch_threshold\":%.9g,"
        "\"release_threshold\":%.9g,\"hold_min_duration_us\":%u,\"swipe_min_distance\":%.9g,"
        "\"long_swipe_distance\":%.9g,\"coherent_swipe_min_distance\":%.9g,"
        "\"coherent_swipe_min_efficiency\":%.9g,\"coherent_swipe_min_end_ratio\":%.9g,"
        "\"coherent_efficiency_basis\":\"peak/path\",\"edge_swipe_min_distance\":%.9g,"
        "\"gap_policy\":\"reset_then_wait_for_idle\"},"
        "\"output_backend\":\"usb_hid\",\"hid_enabled\":true,\"hid_layout\":\"US\",\"hid_log_capacity\":32,"
        "\"hid_mounted\":%s,\"hid_suspended\":%s,\"hid_shift_pending\":%s,"
        "\"hid_enqueued\":%" PRIu32 ",\"hid_completed\":%" PRIu32 ",\"hid_failed\":%" PRIu32
        ",\"hid_queue_drops\":%" PRIu32 ",\"hid_state_actions\":%" PRIu32 ",\"hid_queue_depth\":%" PRIu32 ","
        "\"pad_ids\":[0,1,2,3,4,5,6,7,8,9,10,11,12,13,14],\"board_pad_mask\":%u,\"registered_mask\":%u,"
        "\"registration_errors\":[%s],\"column_gpio_left_to_right\":[11,9,10,2,3,4],\"row_gpio_top_to_bottom\":[1,12,8,5,6,7],"
        "\"orientation\":\"touch side; CapKey inscription upright\",\"transport\":\"tinyusb_cdc\","
        "\"capture_decimation\":1,\"queue_depth\":%u,\"telemetry_queue_depth\":%u,\"startup_warmup_scans\":%u,"
        "\"startup_benchmark_reset\":true,\"startup_calibration\":\"keep touch surface untouched during boot\","
        "\"snapshot\":\"scan_done; sequential register reads; snapshot_duration_us measured\","
        "\"scan_seq\":%" PRIu32 ",\"processed_scan_seq\":%" PRIu32 ",\"processing_epoch\":%" PRIu32
        ",\"event_seq\":%" PRIu32 ",\"dropped_scans\":%" PRIu32 ",\"transport_failures\":%" PRIu32
        ",\"telemetry_dropped_samples\":%" PRIu32 ",\"telemetry_dropped_events\":%" PRIu32 ",\"human_log_drops\":%" PRIu32 ","
        "\"acquisition\":{\"charge_times\":%u,\"voltage_low\":\"0.5V\",\"voltage_high\":\"2.2V\","
        "\"meas_interval_us\":100,\"charge_speed\":7,\"active_threshold\":%u,\"benchmark_filter\":\"IIR4\","
        "\"jitter_step\":1,\"denoise_level\":3,\"smooth_filter\":\"IIR2\",\"active_hysteresis\":0,"
        "\"debounce_count\":0,\"denoise_channel\":0,\"denoise_reference_pf\":6,\"denoise_resolution_bits\":8}}",
        runtime.streaming.load() ? "true" : "false",
        runtime.boot_id, app->version, app->idf_ver, sha, SWIPE_SDKCONFIG_SHA256, SWIPE_RECOGNIZER_SHA256,
        TOUCH_THRESHOLD, TOUCH_RELEASE_THRESHOLD, static_cast<unsigned>(HOLD_MIN_DURATION), SWIPE_MIN_DISTANCE, LONG_SWIPE_DISTANCE,
        COHERENT_SWIPE_MIN_DISTANCE, COHERENT_SWIPE_MIN_EFFICIENCY, COHERENT_SWIPE_MIN_END_RATIO, EDGE_SWIPE_MIN_DISTANCE,
        hid.mounted ? "true" : "false", hid.suspended ? "true" : "false", hid.shift_pending ? "true" : "false",
        hid.enqueued, hid.completed, hid.failed, hid.dropped, hid.state_actions, hid.queue_depth,
        kBoardMask, runtime.registered_mask, errors, kAcquisitionQueueDepth, kTelemetryQueueDepth, kStartupWarmupScans,
        runtime.scan_seq.load(), runtime.processed_scan_seq.load(), runtime.processing_epoch.load(), runtime.event_seq.load(),
        runtime.acquisition_drops.load(), runtime.transport_failures,
        runtime.telemetry_dropped_samples.load(), runtime.telemetry_dropped_events.load(), runtime.human_log_drops.load(),
        kChargeTimes, kActiveThreshold);
    if (n > 0 && static_cast<size_t>(n) < sizeof(json)) writePacket(1, json, n);
}

bool safeToken(const char *s) {
    const size_t length = std::strlen(s);
    if (length == 0 || length > 80) return false;
    for (size_t i = 0; i < length; ++i) {
        const char c = s[i];
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
              (c >= '0' && c <= '9') || c == '_' || c == '-' || c == '.')) return false;
    }
    return true;
}

// Explicit query only, and only outside a raw recording. This leaves existing
// sample/event ordering, gap detection and replay synchronization unchanged.
void writeHidLog(const char *token, uint64_t after) {
    const auto initial = usb::completion_log_status();
    const char *error = runtime.streaming.load() ? "recording_active" :
                        after > initial.latest_seq ? "cursor_ahead" : "";
    const uint64_t lost = initial.retained && after < initial.oldest_seq - 1 ?
                          initial.oldest_seq - 1 - after : 0;
    uint32_t returned = 0, missing = 0;
    if (!*error) {
        const uint64_t first = initial.retained ? std::max(after + 1, initial.oldest_seq) : 1;
        for (uint64_t seq = first; seq <= initial.latest_seq && seq != 0; ++seq) {
            HidCompletion record;
            if (!usb::completion_log_get(seq, record)) { ++missing; continue; }
            const auto &o = record.origin;
            char json[2600]; size_t used = 0; bool fits = true;
            auto append = [&](const char *format, auto... values) {
                if (!fits) return;
                const int count = std::snprintf(json + used, sizeof(json) - used, format, values...);
                if (count < 0 || static_cast<size_t>(count) >= sizeof(json) - used) fits = false;
                else used += static_cast<size_t>(count);
            };
            append("{\"event\":\"completion\",\"token\":\"%s\",\"boot_id\":%" PRIu32
                   ",\"completion_seq\":%" PRIu64 ",\"completed_us\":%" PRIu64
                   ",\"usb_generation\":%" PRIu32 ",\"hid_failed\":%" PRIu32 ",\"hid_queue_drops\":%" PRIu32
                   ",\"source\":\"%s\",\"processing_epoch\":%" PRIu32
                   ",\"event_seq\":%" PRIu32 ",\"scan_seq\":%" PRIu32 ",\"diagnostic_id\":%" PRIu32
                   ",\"timestamp_us\":%" PRIu64 ",\"duration_us\":%" PRIu32
                   ",\"grid\":%u,\"gesture_type\":%u,\"direction\":%u",
                   token, o.boot_id, record.completion_seq, record.completed_us, record.usb_generation,
                   record.hid_failed, record.hid_queue_drops,
                   o.source == HidOrigin::Source::Physical ? "physical" : "diagnostic",
                   o.processing_epoch, o.event_seq, o.scan_seq, o.diagnostic_id, o.timestamp_us,
                   o.duration_us, unsigned(o.grid), unsigned(o.gesture_type), unsigned(o.direction));
            append(",\"start_x\":%.9g,\"start_y\":%.9g,\"end_x\":%.9g,\"end_y\":%.9g"
                   ",\"peak_dx\":%.9g,\"peak_dy\":%.9g,\"max_distance\":%.9g,\"path_length\":%.9g"
                   ",\"caps_lock\":%s,\"shift_before\":%s,\"shift_after\":%s,\"state_only\":%s,\"presses\":[",
                   o.start_x, o.start_y, o.end_x, o.end_y, o.peak_dx, o.peak_dy, o.max_distance, o.path_length,
                   record.caps_lock ? "true" : "false", record.shift_before ? "true" : "false",
                   record.shift_after ? "true" : "false", record.press_count ? "false" : "true");
            for (size_t i = 0; i < record.press_count; ++i) {
                const auto &press = record.presses[i];
                append("%s[%u,%u,%u,%u,%u,%u,%u]", i ? "," : "", unsigned(press.modifier),
                       unsigned(press.keycodes[0]), unsigned(press.keycodes[1]), unsigned(press.keycodes[2]),
                       unsigned(press.keycodes[3]), unsigned(press.keycodes[4]), unsigned(press.keycodes[5]));
            }
            append("%s", "]}");
            if (!fits || !writePacket(5, json, used)) return; // No misleading successful summary.
            ++returned;
        }
    }
    const auto final = usb::completion_log_status();
    const auto hid = usb::status();
    char json[1536];
    const int n = std::snprintf(json, sizeof(json),
        "{\"event\":\"summary\",\"token\":\"%s\",\"boot_id\":%" PRIu32
        ",\"after_seq\":%" PRIu64 ",\"oldest_seq\":%" PRIu64 ",\"latest_seq\":%" PRIu64
        ",\"overwritten\":%" PRIu64 ",\"overwritten_at_end\":%" PRIu64
        ",\"retained\":%" PRIu32 ",\"returned\":%" PRIu32 ",\"lost_before_query\":%" PRIu64
        ",\"missing_during_query\":%" PRIu32 ",\"hid_failed\":%" PRIu32 ",\"hid_queue_drops\":%" PRIu32
        ",\"error\":\"%s\",\"hid_layout\":\"US\",\"recognizer_sha256\":\"%s\""
        ",\"coherent_swipe_min_distance\":%.9g,\"coherent_swipe_min_efficiency\":%.9g"
        ",\"coherent_swipe_min_end_ratio\":%.9g,\"coherent_efficiency_basis\":\"peak/path\""
        ",\"edge_swipe_min_distance\":%.9g}",
        token, runtime.boot_id, after, initial.oldest_seq, initial.latest_seq,
        initial.overwritten, final.overwritten, initial.retained, returned, lost, missing,
        hid.failed, hid.dropped, error, SWIPE_RECOGNIZER_SHA256,
        COHERENT_SWIPE_MIN_DISTANCE, COHERENT_SWIPE_MIN_EFFICIENCY,
        COHERENT_SWIPE_MIN_END_RATIO, EDGE_SWIPE_MIN_DISTANCE);
    if (n > 0 && static_cast<size_t>(n) < sizeof(json)) writePacket(5, json, n);
}

void command(const char *line) {
    if (std::strcmp(line, "BOOTLOADER") == 0) {
        // Explicit maintenance command; opening CDC never resets the keyboard.
        usb::enter_bootloader();
    } else if (std::strncmp(line, "HIDLOG ", 7) == 0) {
        char token[81]{}; uint64_t after = 0; int consumed = 0;
        if (std::sscanf(line, "HIDLOG %80s %" SCNu64 "%n", token, &after, &consumed) == 2 &&
            line[consumed] == '\0' && safeToken(token)) writeHidLog(token, after);
    } else if (std::strcmp(line, "STATUS") == 0) {
        metadata();
    } else if (std::strncmp(line, "HID ", 4) == 0 || std::strncmp(line, "HIDCHAR ", 8) == 0) {
        // Deliberate host diagnostics only: send saved gesture decisions through
        // the exact normal keymap/output path. The host verifier grabs this
        // device's evdev node before invoking these commands.
        char token[81]{}; unsigned grid = 0, gesture = 0, direction = 0, code = 0;
        int consumed = 0; KeyAction action;
        bool valid = false;
        if (std::sscanf(line, "HID %80s %u %u %u%n", token, &grid, &gesture, &direction, &consumed) == 4 &&
            line[consumed] == '\0' && grid < 16 && gesture <= GESTURE_CIRCLE_CCW && direction <= DIR_NORTHWEST) {
            const auto *binding = FindGestureBinding(grid, static_cast<GestureType>(gesture), static_cast<Direction>(direction));
            if (binding != nullptr) { action = binding->action; valid = true; }
        } else if (std::sscanf(line, "HIDCHAR %80s %u%n", token, &code, &consumed) == 2 &&
                   line[consumed] == '\0' && code > 0 && code < 128) {
            action = MakeCharAction(static_cast<char>(code)); valid = true;
        }
        if (!safeToken(token)) return;
        static uint32_t diagnostic_id = 0;
        HidOrigin origin;
        origin.boot_id = runtime.boot_id; origin.scan_seq = runtime.scan_seq.load();
        origin.processing_epoch = runtime.processing_epoch.load();
        origin.timestamp_us = esp_timer_get_time(); origin.diagnostic_id = ++diagnostic_id;
        const bool accepted = valid && usb::enqueue(action, origin);
        char json[320];
        const int n = std::snprintf(json, sizeof(json),
            "{\"token\":\"%s\",\"device_us\":%" PRIu64 ",\"scan_seq\":%" PRIu32
            ",\"boot_id\":%" PRIu32 ",\"diagnostic_id\":%" PRIu32 ",\"hid_accepted\":%s}",
            token, static_cast<uint64_t>(esp_timer_get_time()), runtime.scan_seq.load(), runtime.boot_id,
            origin.diagnostic_id, accepted ? "true" : "false");
        if (n > 0 && static_cast<size_t>(n) < sizeof(json)) writePacket(3, json, n);
    } else if (std::strcmp(line, "HELLO") == 0) {
        portENTER_CRITICAL(&runtime.telemetry_mux);
        runtime.streaming.store(false);
        runtime.stream_generation.fetch_add(1);
        // Recognition is untouched. Discard only telemetry queued for an older attachment.
        xQueueReset(runtime.telemetry_queue);
        runtime.streaming.store(true);
        portEXIT_CRITICAL(&runtime.telemetry_mux);
        metadata();
    } else if (std::strcmp(line, "STOP") == 0) {
        portENTER_CRITICAL(&runtime.telemetry_mux);
        const uint32_t recording_generation = runtime.stream_generation.load();
        runtime.streaming.store(false);
        runtime.stream_generation.fetch_add(1);
        const UBaseType_t queued_recording_items = uxQueueMessagesWaiting(runtime.telemetry_queue);
        portEXIT_CRITICAL(&runtime.telemetry_mux);
        // No producer can append another recording item past the boundary.
        // Drain the finite existing prefix before final metadata; any new human
        // events stay queued and are rendered only after that binary record.
        for (UBaseType_t i = 0; i < queued_recording_items; ++i) {
            TelemetryItem item;
            if (xQueueReceive(runtime.telemetry_queue, &item, 0) != pdTRUE) break;
            if (item.recording && item.stream_generation == recording_generation) {
                writePacket(2, &item.sample, kPayloadSize);
                for (unsigned j = 0; j < item.event_count; ++j) writeEvent(item.events[j]);
            }
        }
        // Final counters follow all queued recording data. Acquisition and
        // recognition remain active while this lower-priority task drains USB.
        metadata();
    } else if (std::strncmp(line, "MARK ", 5) == 0 && safeToken(line + 5)) {
        const uint64_t now = esp_timer_get_time();
        const uint32_t scan = runtime.scan_seq.load();
        char json[240];
        const int n = std::snprintf(json, sizeof(json),
            "{\"token\":\"%s\",\"device_us\":%" PRIu64 ",\"scan_seq\":%" PRIu32 ",\"boot_id\":%" PRIu32 "}",
            line + 5, now, scan, runtime.boot_id);
        // Request the checkpoint only after writing ACK, and require an acquired
        // sample at/after the ACK timestamp. Never reset a touch merely to record.
        const bool acknowledged = n > 0 && static_cast<size_t>(n) < sizeof(json) && writePacket(3, json, n);
        if (acknowledged && std::strncmp(line + 5, "capture-start-", 14) == 0) {
            portENTER_CRITICAL(&runtime.checkpoint_mux);
            runtime.checkpoint_after_us = now;
            ++runtime.checkpoint_request;
            portEXIT_CRITICAL(&runtime.checkpoint_mux);
        }
    }
}

void pollCommands() {
    static char line[96]; static size_t length = 0; static bool discard = false;
    uint8_t bytes[96];
    const int n = static_cast<int>(usb::read(bytes, sizeof(bytes)));
    for (int i = 0; i < n; ++i) {
        const char c = static_cast<char>(bytes[i]);
        if (c == '\n') {
            if (!discard) { line[length] = '\0'; command(line); }
            length = 0; discard = false;
        } else if (c != '\r') {
            if (length + 1 < sizeof(line) && !discard) line[length++] = c;
            else discard = true;
        }
    }
}
}  // namespace

void runSwipeRuntime() {
    runtime.boot_id = esp_random();
    runtime.acquisition_queue = xQueueCreate(kAcquisitionQueueDepth, sizeof(Sample));
    runtime.telemetry_queue = xQueueCreate(kTelemetryQueueDepth, sizeof(TelemetryItem));
    ESP_ERROR_CHECK(runtime.acquisition_queue && runtime.telemetry_queue ? ESP_OK : ESP_ERR_NO_MEM);
    ESP_ERROR_CHECK(usb::init());
    touch_sensor_sample_config_t sample_cfg[TOUCH_SAMPLE_CFG_NUM] = {
        TOUCH_SENSOR_V2_DEFAULT_SAMPLE_CONFIG(kChargeTimes, TOUCH_VOLT_LIM_L_0V5, TOUCH_VOLT_LIM_H_2V2)
    };
    touch_sensor_config_t sensor_cfg = TOUCH_SENSOR_DEFAULT_BASIC_CONFIG(1, sample_cfg);
    sensor_cfg.meas_interval_us = 100.0f;
    ESP_ERROR_CHECK(touch_sensor_new_controller(&sensor_cfg, &runtime.sensor));
    touch_channel_config_t chan_cfg = TOUCHPAD_CHANNEL_CFG_DEFAULT();
    chan_cfg.active_thresh[0] = kActiveThreshold;
    runtime.registration_errors[0] = ESP_ERR_NOT_SUPPORTED;
    for (unsigned pad = 1; pad < kPads; ++pad) {
        const esp_err_t err = touch_sensor_new_channel(runtime.sensor, pad, &chan_cfg, &runtime.channels[pad]);
        runtime.registration_errors[pad] = err;
        if (err == ESP_OK) runtime.registered_mask |= static_cast<uint16_t>(1u << pad);
        else if (kBoardMask & (1u << pad)) ESP_ERROR_CHECK(err);
    }
    touch_sensor_filter_config_t filter = TOUCH_SENSOR_DEFAULT_FILTER_CONFIG();
    filter.benchmark.filter_mode = TOUCH_BM_IIR_FILTER_4;
    filter.benchmark.jitter_step = 1;
    filter.benchmark.denoise_lvl = 3;
    filter.data.smooth_filter = TOUCH_SMOOTH_IIR_FILTER_2;
    filter.data.active_hysteresis = 0; filter.data.debounce_cnt = 0;
    ESP_ERROR_CHECK(touch_sensor_config_filter(runtime.sensor, &filter));
#if SOC_TOUCH_SUPPORT_DENOISE_CHAN
    const touch_denoise_chan_config_t denoise = {
        .charge_speed = TOUCH_CHARGE_SPEED_7, .init_charge_volt = TOUCH_INIT_CHARGE_VOLT_DEFAULT,
        .ref_cap = TOUCH_DENOISE_CHAN_CAP_6PF, .resolution = TOUCH_DENOISE_CHAN_RESOLUTION_BIT8,
    };
    ESP_ERROR_CHECK(touch_sensor_config_denoise_channel(runtime.sensor, &denoise));
#endif
    // Follow ESP-IDF touch_sens_basic's initial-scanning sequence: hardware
    // channel/filter data is invalid on the first read. Do this before callbacks
    // and recognition exist, rather than treating startup transients as touches.
    // Keep the touch surface untouched during this startup calibration.
    ESP_ERROR_CHECK(touch_sensor_enable(runtime.sensor));
    for (unsigned i = 0; i < kStartupWarmupScans; ++i)
        ESP_ERROR_CHECK(touch_sensor_trigger_oneshot_scanning(runtime.sensor, 2000));
    ESP_ERROR_CHECK(touch_sensor_disable(runtime.sensor));
    // The official example subsequently reconfigures each channel; the S3
    // driver's reconfiguration unconditionally resets that channel's benchmark.
    // Use its documented benchmark API to do the same once from warmed data,
    // preserving our thresholds. Never reset benchmarks in the live runtime.
    const touch_chan_benchmark_config_t initial_benchmark = {.do_reset = true};
    for (unsigned pad = 1; pad < kPads; ++pad) {
        if (runtime.channels[pad] != nullptr)
            ESP_ERROR_CHECK(touch_channel_config_benchmark(runtime.channels[pad], &initial_benchmark));
    }
    // Every runtime log in the processing path is suppressed; only this lower
    // priority task writes text or binary to the independent CDC interface.
    esp_log_level_set("*", ESP_LOG_NONE);
    const BaseType_t started = xTaskCreate(processingTask, "recognizer", 8192, nullptr, 10, nullptr);
    ESP_ERROR_CHECK(started == pdPASS ? ESP_OK : ESP_ERR_NO_MEM);
    touch_event_callbacks_t callbacks = {}; callbacks.on_scan_done = scanDone;
    ESP_ERROR_CHECK(touch_sensor_register_callbacks(runtime.sensor, &callbacks, nullptr));
    ESP_ERROR_CHECK(touch_sensor_enable(runtime.sensor));
    ESP_ERROR_CHECK(touch_sensor_start_continuous_scanning(runtime.sensor));
    const char ready[] = "CapKey ready: USB keyboard active. HELLO/STOP control recording; STATUS reports HID delivery.\r\n";
    if (usb::status().cdc_connected) writeBytes(ready, sizeof(ready) - 1);
    int64_t last_metadata = esp_timer_get_time();
    while (true) {
        pollCommands();
        TelemetryItem item;
        if (xQueueReceive(runtime.telemetry_queue, &item, pdMS_TO_TICKS(10)) == pdTRUE) {
            const bool streaming = runtime.streaming.load();
            const bool same_generation = item.stream_generation == runtime.stream_generation.load();
            if (streaming && item.recording && same_generation) {
                writePacket(2, &item.sample, kPayloadSize);
                for (unsigned i = 0; i < item.event_count; ++i) writeEvent(item.events[i]);
            } else if (!streaming && !item.recording && same_generation) {
                for (unsigned i = 0; i < item.event_count; ++i) humanEvent(item.events[i]);
            }
        }
        const int64_t now = esp_timer_get_time();
        if (runtime.streaming.load() && now - last_metadata >= 1000000) {
            metadata(); last_metadata = now;
        }
    }
}
