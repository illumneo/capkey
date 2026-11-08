#pragma once

#include "esp_err.h"

namespace usb_keyboard {

esp_err_t init();
esp_err_t send_char(char c);
esp_err_t send_string(const char *str);
esp_err_t send_backspace();
esp_err_t send_caps_lock();

}  // namespace usb_keyboard
