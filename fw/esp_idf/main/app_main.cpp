#include "capture.h"

#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

extern "C" void app_main(void) {
    // One acquisition/recognition path in every image. The lower-priority task
    // owns USB, and starts the independent high-priority recognizer task.
    const BaseType_t started = xTaskCreate(
        [](void *) { runSwipeRuntime(); }, "swipe_usb", 16384, nullptr, 8, nullptr);
    ESP_ERROR_CHECK(started == pdPASS ? ESP_OK : ESP_ERR_NO_MEM);
}
