#include "usb_keyboard.h"

#include <algorithm>
#include <atomic>
#include <cstdio>
#include <cstring>

#include "hid_action.h"
#include "esp_mac.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_private/usb_phy.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "soc/rtc_cntl_reg.h"
#include "soc/soc.h"
#include "soc/usb_serial_jtag_reg.h"
#include "tinyusb.h"
#include "tusb_cdc_acm.h"
#include "device/dcd.h"
#include "device/usbd_pvt.h"

namespace {
constexpr size_t kQueueLength = 32;
constexpr uint32_t kReportTimeoutMs = 250;
constexpr uint8_t kCdcInterface = 0;
constexpr uint8_t kHidInterface = 2;
constexpr uint16_t kConfigurationLength =
    TUD_CONFIG_DESC_LEN + TUD_CDC_DESC_LEN + TUD_HID_DESC_LEN;

const uint8_t report_descriptor[] = {TUD_HID_REPORT_DESC_KEYBOARD()};
const tusb_desc_device_t device_descriptor = {
    .bLength = sizeof(tusb_desc_device_t),
    .bDescriptorType = TUSB_DESC_DEVICE,
    .bcdUSB = 0x0200,
    .bDeviceClass = TUSB_CLASS_MISC,
    .bDeviceSubClass = MISC_SUBCLASS_COMMON,
    .bDeviceProtocol = MISC_PROTOCOL_IAD,
    .bMaxPacketSize0 = CFG_TUD_ENDPOINT0_SIZE,
    .idVendor = 0x303a,
    .idProduct = 0x4004,
    .bcdDevice = 0x0100,
    .iManufacturer = 1,
    .iProduct = 2,
    .iSerialNumber = 3,
    .bNumConfigurations = 1,
};
const uint8_t configuration_descriptor[] = {
    TUD_CONFIG_DESCRIPTOR(1, 3, 0, kConfigurationLength, 0, 100),
    TUD_CDC_DESCRIPTOR(kCdcInterface, 4, 0x81, 8, 0x02, 0x82, 64),
    TUD_HID_DESCRIPTOR(kHidInterface, 5, HID_ITF_PROTOCOL_KEYBOARD,
                       sizeof(report_descriptor), 0x83, 8, 5),
};
const char language[] = {0x09, 0x04};
char serial_number[13] = {};
const char *strings[] = {
    language, "CapKey", "CapKey", serial_number,
    "CapKey diagnostics", "CapKey keyboard",
};

struct QueuedAction {
    KeyActionType type;
    char ch;
    char text[HidActionPlan::kMaxTextLength + 1];
    uint32_t generation;
    HidOrigin origin;
};

portMUX_TYPE state_mux = portMUX_INITIALIZER_UNLOCKED;
QueueHandle_t action_queue = nullptr;
TaskHandle_t hid_task = nullptr;
usb::Status counters = {};
std::atomic<bool> initialized{false};
std::atomic<bool> maintenance{false};
std::atomic<bool> worker_stopped{false};
bool caps_lock = false;
uint32_t generation = 0;
bool in_flight = false;
uint32_t submitted_token = 0;
uint32_t completed_token = 0;
uint32_t failed_token = 0;
uint32_t in_flight_generation = 0;
uint8_t current_report[8] = {};
struct Submission {
    HidKeyboardReport report;
    uint32_t generation;
    uint32_t token;
    bool allow_maintenance;
};
Submission submission = {};
HidCompletionLog completion_log;
bool submission_pending = false;

// Called with state_mux held. A generation change cancels accepted but stale
// actions; the HID worker accounts for each of them rather than resetting FIFO.
void invalidateConnection(bool cancel_transfer = true, bool clear_caps = true) {
    ++generation;
    counters.shift_pending = false;
    if (clear_caps) caps_lock = false;
    if (cancel_transfer) {
        in_flight = false;
        std::memset(current_report, 0, sizeof(current_report));
    }
}

bool connectionActive(uint32_t expected_generation, bool allow_maintenance = false) {
    portENTER_CRITICAL(&state_mux);
    const bool active = initialized && counters.mounted && !counters.suspended &&
        generation == expected_generation && (!maintenance || allow_maintenance);
    portEXIT_CRITICAL(&state_mux);
    return active;
}

// Transfer initiation runs on TinyUSB's own task, in order with USB connection
// callbacks. A disconnected action therefore cannot resume on another core and
// submit its old press to a newly enumerated host. No spinlock surrounds USB I/O.
void submitOnUsbTask(void *) {
    portENTER_CRITICAL(&state_mux);
    const Submission request = submission;
    const bool valid = initialized && counters.mounted && !counters.suspended &&
        generation == request.generation && (!maintenance || request.allow_maintenance) &&
        !in_flight;
    if (valid) {
        in_flight = true;
        in_flight_generation = request.generation;
        current_report[0] = request.report.modifier;
        current_report[1] = 0;
        std::memcpy(current_report + 2, request.report.keycodes, 6);
    }
    portEXIT_CRITICAL(&state_mux);
    const bool accepted = valid && tud_hid_ready() &&
        tud_hid_keyboard_report(0, request.report.modifier, request.report.keycodes);
    portENTER_CRITICAL(&state_mux);
    if (!accepted) {
        failed_token = request.token;
        if (valid) in_flight = false;
    }
    submission_pending = false;
    portEXIT_CRITICAL(&state_mux);
}

// Exactly one worker submits HID reports. Endpoint availability alone is not
// sufficient: the preceding transfer's callback must have retired in_flight.
// This also prevents a delayed press callback from acknowledging its release.
bool sendReport(const HidKeyboardReport &report, uint32_t expected_generation,
                bool allow_maintenance = false) {
    const int64_t deadline = esp_timer_get_time() + kReportTimeoutMs * 1000;
    uint32_t token = 0;
    while (esp_timer_get_time() < deadline) {
        if (!connectionActive(expected_generation, allow_maintenance)) return false;
        portENTER_CRITICAL(&state_mux);
        const bool pending = in_flight || submission_pending;
        portEXIT_CRITICAL(&state_mux);
        if (!pending && tud_hid_ready()) {
            portENTER_CRITICAL(&state_mux);
            const bool valid = generation == expected_generation && counters.mounted &&
                !counters.suspended && (!maintenance || allow_maintenance);
            if (valid) {
                token = ++submitted_token;
                submission = {report, expected_generation, token, allow_maintenance};
                submission_pending = true;
            }
            portEXIT_CRITICAL(&state_mux);
            if (!valid) return false;
            // This queue is serviced by the independent TinyUSB task. The
            // request storage is not reused until its deferred callback runs,
            // even when the caller times out or the device disconnects.
            usbd_defer_func(submitOnUsbTask, nullptr, false);
            break;
        }
        vTaskDelay(1);
    }
    if (!token) return false;
    while (esp_timer_get_time() < deadline) {
        portENTER_CRITICAL(&state_mux);
        const bool done = completed_token == token;
        const bool failed = failed_token == token;
        portEXIT_CRITICAL(&state_mux);
        if (!connectionActive(expected_generation, allow_maintenance)) return false;
        if (done) return true;
        if (failed) return false;
        vTaskDelay(1);
    }
    // Keep in_flight set until its callback or disconnect. A timed-out transfer
    // may still complete; it must never be overwritten with another report.
    return false;
}

void countFailed() {
    portENTER_CRITICAL(&state_mux);
    ++counters.failed;
    counters.shift_pending = false;
    portEXIT_CRITICAL(&state_mux);
}

void keyboardTask(void *) {
    HidActionEncoder encoder;
    uint32_t worker_generation = UINT32_MAX;
    bool release_required = true;
    const HidKeyboardReport release = {};
    for (;;) {
        portENTER_CRITICAL(&state_mux);
        const uint32_t current_generation = generation;
        const bool stopping = maintenance;
        const bool host_caps_lock = caps_lock;
        portEXIT_CRITICAL(&state_mux);
        if (current_generation != worker_generation) {
            encoder.reset();
            worker_generation = current_generation;
            release_required = true;
        }
        encoder.setCapsLock(host_caps_lock);

        if (stopping) {
            QueuedAction abandoned;
            while (xQueueReceive(action_queue, &abandoned, 0) == pdTRUE) countFailed();
            // No future press is allowed. Try one final release before detach.
            if (connectionActive(worker_generation, true)) {
                (void)sendReport(release, worker_generation, true);
            }
            portENTER_CRITICAL(&state_mux);
            counters.shift_pending = false;
            worker_stopped = true;
            portEXIT_CRITICAL(&state_mux);
            vTaskDelete(nullptr);
        }

        if (release_required && connectionActive(worker_generation)) {
            if (!sendReport(release, worker_generation)) {
                vTaskDelay(1);
                continue;
            }
            release_required = false;
        }

        QueuedAction queued;
        if (xQueueReceive(action_queue, &queued, pdMS_TO_TICKS(10)) != pdTRUE) continue;
        // Mount/resume may happen during the queue wait. Adopt a still-current
        // new generation before processing its first action, with a release
        // barrier; do not mistake that fresh action for disconnected backlog.
        if (queued.generation != worker_generation && connectionActive(queued.generation)) {
            worker_generation = queued.generation;
            encoder.reset();
            portENTER_CRITICAL(&state_mux);
            encoder.setCapsLock(caps_lock);
            portEXIT_CRITICAL(&state_mux);
            release_required = !sendReport(release, worker_generation);
        }
        if (queued.generation != worker_generation ||
            !connectionActive(queued.generation) || release_required) {
            countFailed();
            encoder.reset();
            continue;
        }
        const KeyAction action(queued.type, queued.ch, queued.text);
        HidActionPlan plan;
        // A host LED update may arrive while the queue receive is waiting.
        // Encode from the latest state rather than the pre-wait snapshot.
        portENTER_CRITICAL(&state_mux);
        const bool encoded_caps_lock = caps_lock;
        encoder.setCapsLock(encoded_caps_lock);
        portEXIT_CRITICAL(&state_mux);
        const bool shift_before = encoder.shiftPending();
        if (!encoder.encode(action, plan)) {
            countFailed();
            encoder.reset();
            continue;
        }
        bool succeeded = true;
        for (size_t i = 0; i < plan.report_count; ++i) {
            // Conservative even if submission itself fails: zero is harmless,
            // whereas allowing the next press before release could stick a key.
            release_required = true;
            if (!sendReport(plan.reports[i], queued.generation)) {
                succeeded = false;
                break;
            }
            if ((i & 1u) != 0) release_required = false;
        }
        const uint64_t completed_us = esp_timer_get_time();
        portENTER_CRITICAL(&state_mux);
        succeeded = succeeded && initialized && !maintenance &&
            counters.mounted && !counters.suspended && generation == queued.generation;
        if (succeeded) {
            encoder.commit(plan);
            if (plan.report_count) ++counters.completed;
            else ++counters.state_actions;
            counters.shift_pending = encoder.shiftPending();
            // Bounded memory copy only. No USB or callbacks while locked.
            completion_log.recordCompleted(true, queued.origin, plan, completed_us,
                                           queued.generation, encoded_caps_lock, shift_before, counters.failed, counters.dropped);
        }
        portEXIT_CRITICAL(&state_mux);
        if (!succeeded) {
            countFailed();
            encoder.reset();
        }
    }
}

void beforeRestart() {
    if (!maintenance) return;
    // ESP-IDF usb_console.c and Arduino's S3 USB recovery use this persistent
    // ROM download bit; the updater/esptool must clear it before application
    // reset. Restore native Serial/JTAG routing as well: software CPU restart
    // alone does not reset the OTG/Serial-JTAG PHY selection.
    CLEAR_PERI_REG_MASK(RTC_CNTL_USB_CONF_REG,
        RTC_CNTL_SW_HW_USB_PHY_SEL | RTC_CNTL_SW_USB_PHY_SEL | RTC_CNTL_USB_PAD_ENABLE);
    CLEAR_PERI_REG_MASK(USB_SERIAL_JTAG_CONF0_REG, USB_SERIAL_JTAG_PHY_SEL);
    SET_PERI_REG_MASK(USB_SERIAL_JTAG_CONF0_REG, USB_SERIAL_JTAG_USB_PAD_ENABLE);
    REG_WRITE(RTC_CNTL_OPTION1_REG, RTC_CNTL_FORCE_DOWNLOAD_BOOT);
}
}  // namespace

namespace usb {
esp_err_t init() {
    if (initialized) return ESP_ERR_INVALID_STATE;
    uint8_t mac[6];
    esp_err_t error = esp_efuse_mac_get_default(mac);
    if (error != ESP_OK) return error;
    std::snprintf(serial_number, sizeof(serial_number), "%02X%02X%02X%02X%02X%02X",
        mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    action_queue = xQueueCreate(kQueueLength, sizeof(QueuedAction));
    if (!action_queue) return ESP_ERR_NO_MEM;

    tinyusb_config_t config = {};
    config.device_descriptor = &device_descriptor;
    config.string_descriptor = strings;
    config.string_descriptor_count = sizeof(strings) / sizeof(strings[0]);
    config.external_phy = false;
    config.configuration_descriptor = configuration_descriptor;
    config.self_powered = false;
    error = tinyusb_driver_install(&config);
    if (error != ESP_OK) {
        vQueueDelete(action_queue);
        action_queue = nullptr;
        return error;
    }
    tinyusb_config_cdcacm_t cdc = {};
    cdc.usb_dev = TINYUSB_USBDEV_0;
    cdc.cdc_port = TINYUSB_CDC_ACM_0;
    error = tusb_cdc_acm_init(&cdc);
    if (error == ESP_OK) error = esp_register_shutdown_handler(beforeRestart);
    if (error != ESP_OK) {
        (void)tinyusb_driver_uninstall();
        vQueueDelete(action_queue);
        action_queue = nullptr;
        return error;
    }
    portENTER_CRITICAL(&state_mux);
    initialized = true;
    portEXIT_CRITICAL(&state_mux);
    if (xTaskCreate(keyboardTask, "capkey_hid", 4096, nullptr, 6, &hid_task) != pdPASS) {
        initialized = false;
        (void)esp_unregister_shutdown_handler(beforeRestart);
        (void)tusb_cdc_acm_deinit(TINYUSB_CDC_ACM_0);
        (void)tinyusb_driver_uninstall();
        vQueueDelete(action_queue);
        action_queue = nullptr;
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}

size_t read(uint8_t *destination, size_t capacity) {
    if (!initialized || maintenance || !destination || !capacity) return 0;
    size_t received = 0;
    if (tinyusb_cdcacm_read(TINYUSB_CDC_ACM_0, destination, capacity, &received) != ESP_OK) return 0;
    return received;
}

size_t write(const uint8_t *source, size_t length, uint32_t timeout_ms) {
    if (!initialized || maintenance || !source || !length) return 0;
    const int64_t deadline = esp_timer_get_time() + static_cast<int64_t>(timeout_ms) * 1000;
    size_t written = 0;
    do {
        if (!tud_cdc_n_connected(0)) break;
        written += tinyusb_cdcacm_write_queue(TINYUSB_CDC_ACM_0, source + written, length - written);
        // Nonblocking flush: console output is never redirected into this CDC.
        (void)tinyusb_cdcacm_write_flush(TINYUSB_CDC_ACM_0, 0);
        if (written == length || esp_timer_get_time() >= deadline) break;
        vTaskDelay(1);
    } while (true);
    return written;
}

bool enqueue(const KeyAction &action, const HidOrigin &origin) {
    QueuedAction queued = {};
    queued.origin = origin;
    queued.type = action.type;
    queued.ch = action.ch;
    bool supported = true;
    if (action.type == KeyActionType::String || action.type == KeyActionType::Special) {
        const size_t length = action.str ? strnlen(action.str, sizeof(queued.text)) : sizeof(queued.text);
        supported = length < sizeof(queued.text);
        if (supported) std::memcpy(queued.text, action.str, length + 1);
    }
    if (supported) {
        const KeyAction copied(queued.type, queued.ch, queued.text);
        HidActionEncoder validator;
        HidActionPlan plan;
        supported = validator.encode(copied, plan);
    }
    portENTER_CRITICAL(&state_mux);
    bool accepted = false;
    if (supported && initialized && !maintenance && counters.mounted && !counters.suspended) {
        queued.generation = generation;
        accepted = xQueueSend(action_queue, &queued, 0) == pdTRUE;
    }
    if (accepted) ++counters.enqueued;
    else ++counters.dropped;
    portEXIT_CRITICAL(&state_mux);
    return accepted;
}

HidLogStatus completion_log_status() {
    portENTER_CRITICAL(&state_mux);
    const auto result = completion_log.status();
    portEXIT_CRITICAL(&state_mux);
    return result;
}

bool completion_log_get(uint64_t sequence, HidCompletion &record) {
    portENTER_CRITICAL(&state_mux);
    const bool found = completion_log.get(sequence, record);
    portEXIT_CRITICAL(&state_mux);
    return found;
}

Status status() {
    portENTER_CRITICAL(&state_mux);
    Status snapshot = counters;
    const bool ready = initialized && !maintenance;
    portEXIT_CRITICAL(&state_mux);
    snapshot.cdc_connected = ready && tud_cdc_n_connected(0);
    snapshot.queue_depth = action_queue ? uxQueueMessagesWaiting(action_queue) : 0;
    return snapshot;
}

void enter_bootloader() {
    portENTER_CRITICAL(&state_mux);
    maintenance = true;
    portEXIT_CRITICAL(&state_mux);
    const int64_t deadline = esp_timer_get_time() + 1000000;
    bool stopped = false;
    do {
        portENTER_CRITICAL(&state_mux);
        stopped = worker_stopped || !hid_task;
        portEXIT_CRITICAL(&state_mux);
        if (stopped) break;
        vTaskDelay(1);
    } while (esp_timer_get_time() < deadline);
    (void)tud_disconnect();
    vTaskDelay(pdMS_TO_TICKS(100));
    if (stopped) {
        (void)tinyusb_driver_uninstall();
        usb_phy_config_t phy_config = {};
        phy_config.controller = USB_PHY_CTRL_SERIAL_JTAG;
        phy_config.target = USB_PHY_TARGET_INT;
        usb_phy_handle_t serial_phy = nullptr;
        (void)usb_new_phy(&phy_config, &serial_phy);
    }
    esp_restart();
}
}  // namespace usb

extern "C" {
uint8_t const *tud_hid_descriptor_report_cb(uint8_t) { return report_descriptor; }

uint16_t tud_hid_get_report_cb(uint8_t, uint8_t report_id, hid_report_type_t type,
                             uint8_t *buffer, uint16_t requested_length) {
    if (report_id != 0 || type != HID_REPORT_TYPE_INPUT) return 0;
    const uint16_t length = std::min<uint16_t>(requested_length, sizeof(current_report));
    portENTER_CRITICAL(&state_mux);
    std::memcpy(buffer, current_report, length);
    portEXIT_CRITICAL(&state_mux);
    return length;
}

void tud_hid_set_report_cb(uint8_t, uint8_t report_id, hid_report_type_t type,
                           const uint8_t *buffer, uint16_t length) {
    if (report_id != 0 || type != HID_REPORT_TYPE_OUTPUT || !length) return;
    portENTER_CRITICAL(&state_mux);
    caps_lock = (buffer[0] & KEYBOARD_LED_CAPSLOCK) != 0;
    portEXIT_CRITICAL(&state_mux);
}

void tud_hid_report_complete_cb(uint8_t instance, const uint8_t *report, uint16_t length) {
    if (instance != 0) return;
    portENTER_CRITICAL(&state_mux);
    if (in_flight) {
        if (in_flight_generation == generation && length == sizeof(current_report) &&
            std::memcmp(report, current_report, length) == 0)
            completed_token = submitted_token;
        else
            failed_token = submitted_token;
        in_flight = false;
    }
    portEXIT_CRITICAL(&state_mux);
}

void tud_hid_report_failed_cb(uint8_t instance, hid_report_type_t type,
                             const uint8_t *, uint16_t) {
    if (instance != 0 || type != HID_REPORT_TYPE_INPUT) return;
    portENTER_CRITICAL(&state_mux);
    if (in_flight) {
        failed_token = submitted_token;
        in_flight = false;
    }
    portEXIT_CRITICAL(&state_mux);
}

void tud_mount_cb() {
    portENTER_CRITICAL(&state_mux);
    invalidateConnection();
    counters.mounted = true;
    counters.suspended = false;
    portEXIT_CRITICAL(&state_mux);
}

void tud_umount_cb() {
    portENTER_CRITICAL(&state_mux);
    invalidateConnection();
    counters.mounted = false;
    counters.suspended = false;
    portEXIT_CRITICAL(&state_mux);
}

void tud_suspend_cb(bool) {
    portENTER_CRITICAL(&state_mux);
    // Suspend can leave an IN transfer pending. Keep it reserved until its
    // callback, then send zero after resume before accepting another press.
    invalidateConnection(false, false);
    counters.suspended = true;
    portEXIT_CRITICAL(&state_mux);
}

void tud_resume_cb() {
    portENTER_CRITICAL(&state_mux);
    invalidateConnection(false, false);
    counters.suspended = false;
    portEXIT_CRITICAL(&state_mux);
}

// A bus reset need not invoke tud_umount_cb. Invalidate queued input as soon as
// TinyUSB receives reset/unplug, including when that notification comes in ISR.
void tud_event_hook_cb(uint8_t, uint32_t event_id, bool in_isr) {
    if (event_id != DCD_EVENT_BUS_RESET && event_id != DCD_EVENT_UNPLUGGED) return;
    if (in_isr) portENTER_CRITICAL_ISR(&state_mux);
    else portENTER_CRITICAL(&state_mux);
    invalidateConnection();
    counters.mounted = false;
    counters.suspended = false;
    if (in_isr) portEXIT_CRITICAL_ISR(&state_mux);
    else portEXIT_CRITICAL(&state_mux);
}
}  // extern "C"
