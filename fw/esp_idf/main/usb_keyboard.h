#pragma once

#include <cstddef>
#include <cstdint>
#include "esp_err.h"
#include "gestureLayout.h"
#include "hid_completion.h"

namespace usb {

struct Status {
    bool mounted;
    bool cdc_connected;
    bool shift_pending;
    bool suspended;
    uint32_t enqueued;
    uint32_t completed;  // Actions whose complete press/release reports were acknowledged.
    uint32_t failed;     // Accepted actions aborted before completion.
    uint32_t dropped;    // Actions rejected at enqueue (full/disconnected/unsupported).
    uint32_t state_actions;  // One-shot modifier updates; not transmitted keystrokes.
    uint32_t queue_depth;
};

// One composite native-PHY device: CDC diagnostics plus a boot keyboard.
esp_err_t init();
size_t read(uint8_t *destination, size_t capacity);
size_t write(const uint8_t *source, size_t length, uint32_t timeout_ms = 20);
// Never waits for USB or queue space. The caller's action strings must remain
// valid until enqueue returns; the queue stores its own copy.
bool enqueue(const KeyAction &action, const HidOrigin &origin);
// Non-destructive bounded RAM history, safe to query from the CDC task.
HidLogStatus completion_log_status();
bool completion_log_get(uint64_t sequence, HidCompletion &record);
Status status();
// Explicit maintenance operation; no automatic bootloader entry on CDC open.
void enter_bootloader();

}  // namespace usb
