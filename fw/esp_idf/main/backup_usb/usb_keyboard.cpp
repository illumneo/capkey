#include "usb_keyboard.h"

#include <cstring>

#include "sdkconfig.h"
#include "class/hid/hid.h"
#include "class/hid/hid_device.h"
#include "esp_err.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "tinyusb.h"
#include "tusb_console.h"
#include "tusb_cdc_acm.h"

namespace {
constexpr uint8_t kEndpointCdcNotif = 0x81;
constexpr uint8_t kEndpointCdcOut = 0x02;
constexpr uint8_t kEndpointCdcIn = 0x82;
#if CONFIG_TINYUSB_CDC_COUNT > 1
constexpr uint8_t kEndpointCdcNotif2 = 0x83;
constexpr uint8_t kEndpointCdcOut2 = 0x04;
constexpr uint8_t kEndpointCdcIn2 = 0x84;
#endif
constexpr uint16_t kCdcNotifPacketSize = 8;
constexpr uint16_t kCdcDataPacketSize = 64;
#if CONFIG_TINYUSB_HID_COUNT > 0
constexpr uint8_t kEndpointHidIn = 0x85;
constexpr uint8_t kHidEndpointSize = 8;
constexpr uint8_t kHidPollingIntervalMs = 10;
#endif
constexpr uint16_t kUsbVersion = 0x0200;
constexpr uint16_t kDeviceVersion = 0x0100;
constexpr uint16_t kProductId = 0x4004;
constexpr uint16_t kVendorId = USB_ESPRESSIF_VID;
constexpr uint8_t kMaxPower = 100;  // mA

#if CONFIG_TINYUSB_CDC_COUNT < 1
#error "At least one CDC interface is required"
#endif

enum InterfaceIndex : uint8_t {
  kInterfaceCdcComm = 0,
  kInterfaceCdcData,
#if CONFIG_TINYUSB_CDC_COUNT > 1
  kInterfaceCdcComm2,
  kInterfaceCdcData2,
#endif
#if CONFIG_TINYUSB_HID_COUNT > 0
  kInterfaceHid,
#endif
  kInterfaceCount,
};

enum StringIndex : uint8_t {
  kStringLangId = 0,
  kStringManufacturer,
  kStringProduct,
  kStringSerial,
  kStringCdc,
#if CONFIG_TINYUSB_CDC_COUNT > 1
  kStringCdc2,
#endif
#if CONFIG_TINYUSB_HID_COUNT > 0
  kStringHid,
#endif
};

constexpr uint16_t kTotalDescriptorLength =
    TUD_CONFIG_DESC_LEN +
    (CONFIG_TINYUSB_CDC_COUNT * TUD_CDC_DESC_LEN) +
    (CONFIG_TINYUSB_HID_COUNT * TUD_HID_DESC_LEN);

const tusb_desc_device_t kDeviceDescriptor = {
    .bLength = sizeof(tusb_desc_device_t),
    .bDescriptorType = TUSB_DESC_DEVICE,
    .bcdUSB = kUsbVersion,
    .bDeviceClass = TUSB_CLASS_MISC,
    .bDeviceSubClass = MISC_SUBCLASS_COMMON,
    .bDeviceProtocol = MISC_PROTOCOL_IAD,
    .bMaxPacketSize0 = CFG_TUD_ENDPOINT0_SIZE,
    .idVendor = kVendorId,
    .idProduct = kProductId,
    .bcdDevice = kDeviceVersion,
    .iManufacturer = 0x01,
    .iProduct = 0x02,
    .iSerialNumber = 0x03,
    .bNumConfigurations = 0x01,
};

#if CONFIG_TINYUSB_HID_COUNT > 0
const uint8_t hid_report_descriptor[] = {
    TUD_HID_REPORT_DESC_KEYBOARD()
};
#endif

const uint8_t kConfigurationDescriptor[] = {
    TUD_CONFIG_DESCRIPTOR(1, kInterfaceCount, 0, kTotalDescriptorLength,
                          TUSB_DESC_CONFIG_ATT_REMOTE_WAKEUP, kMaxPower),
    TUD_CDC_DESCRIPTOR(kInterfaceCdcComm, kStringCdc, kEndpointCdcNotif,
                       kCdcNotifPacketSize, kEndpointCdcOut, kEndpointCdcIn,
                       kCdcDataPacketSize),
#if CONFIG_TINYUSB_CDC_COUNT > 1
    TUD_CDC_DESCRIPTOR(kInterfaceCdcComm2, kStringCdc2, kEndpointCdcNotif2,
                       kCdcNotifPacketSize, kEndpointCdcOut2, kEndpointCdcIn2,
                       kCdcDataPacketSize),
#endif
#if CONFIG_TINYUSB_HID_COUNT > 0
    TUD_HID_DESCRIPTOR(kInterfaceHid, kStringHid, HID_ITF_PROTOCOL_KEYBOARD,
                       sizeof(hid_report_descriptor), kEndpointHidIn,
                       kHidEndpointSize, kHidPollingIntervalMs),
#endif
};

const uint16_t kLangIdDescriptor[] = {0x0409};

static const char *kStringDescriptors[] = {
    reinterpret_cast<const char *>(kLangIdDescriptor),
    "The Hooj",
    "Swipe Keyboard",
    "0001",
    "Swipe Console",
#if CONFIG_TINYUSB_CDC_COUNT > 1
    "Swipe Debug",
#endif
#if CONFIG_TINYUSB_HID_COUNT > 0
    "Swipe Keyboard",
#endif
};

constexpr size_t kStringDescriptorCount =
    sizeof(kStringDescriptors) / sizeof(kStringDescriptors[0]);

#if CONFIG_TINYUSB_HID_COUNT > 0
bool keyboard_ready() {
  return tud_mounted() && !tud_suspended();
}
#endif

#if CONFIG_TINYUSB_HID_COUNT > 0
struct KeySpec {
  uint8_t modifier;
  uint8_t keycode;
};

KeySpec map_char(char c) {
  switch (c) {
    case 'a': return {0, HID_KEY_A};
    case 'b': return {0, HID_KEY_B};
    case 'c': return {0, HID_KEY_C};
    case 'd': return {0, HID_KEY_D};
    case 'e': return {0, HID_KEY_E};
    case 'f': return {0, HID_KEY_F};
    case 'g': return {0, HID_KEY_G};
    case 'h': return {0, HID_KEY_H};
    case 'i': return {0, HID_KEY_I};
    case 'j': return {0, HID_KEY_J};
    case 'k': return {0, HID_KEY_K};
    case 'l': return {0, HID_KEY_L};
    case 'm': return {0, HID_KEY_M};
    case 'n': return {0, HID_KEY_N};
    case 'o': return {0, HID_KEY_O};
    case 'p': return {0, HID_KEY_P};
    case 'q': return {0, HID_KEY_Q};
    case 'r': return {0, HID_KEY_R};
    case 's': return {0, HID_KEY_S};
    case 't': return {0, HID_KEY_T};
    case 'u': return {0, HID_KEY_U};
    case 'v': return {0, HID_KEY_V};
    case 'w': return {0, HID_KEY_W};
    case 'x': return {0, HID_KEY_X};
    case 'y': return {0, HID_KEY_Y};
    case 'z': return {0, HID_KEY_Z};
        case 'A': return {KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_A};
        case 'B': return {KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_B};
        case 'C': return {KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_C};
        case 'D': return {KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_D};
        case 'E': return {KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_E};
        case 'F': return {KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_F};
        case 'G': return {KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_G};
        case 'H': return {KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_H};
        case 'I': return {KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_I};
        case 'J': return {KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_J};
        case 'K': return {KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_K};
        case 'L': return {KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_L};
        case 'M': return {KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_M};
        case 'N': return {KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_N};
        case 'O': return {KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_O};
        case 'P': return {KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_P};
        case 'Q': return {KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_Q};
        case 'R': return {KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_R};
        case 'S': return {KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_S};
        case 'T': return {KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_T};
        case 'U': return {KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_U};
        case 'V': return {KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_V};
        case 'W': return {KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_W};
        case 'X': return {KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_X};
        case 'Y': return {KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_Y};
        case 'Z': return {KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_Z};
    case '0': return {0, HID_KEY_0};
    case '1': return {0, HID_KEY_1};
    case '2': return {0, HID_KEY_2};
    case '3': return {0, HID_KEY_3};
    case '4': return {0, HID_KEY_4};
    case '5': return {0, HID_KEY_5};
    case '6': return {0, HID_KEY_6};
    case '7': return {0, HID_KEY_7};
    case '8': return {0, HID_KEY_8};
    case '9': return {0, HID_KEY_9};
    case '\n': return {0, HID_KEY_ENTER};
    case '\r': return {0, HID_KEY_ENTER};
    case ' ': return {0, HID_KEY_SPACE};
    default:
      return {0xFF, 0xFF};
  }
}

esp_err_t send_key(uint8_t modifier, uint8_t keycode) {
  if (keycode == 0xFF) {
    return ESP_ERR_INVALID_ARG;
  }
  // Wait briefly for the host to configure the device.
  for (int attempts = 0; attempts < 50; ++attempts) {
    if (keyboard_ready()) {
      break;
    }
    vTaskDelay(pdMS_TO_TICKS(10));
  }
  if (!keyboard_ready()) {
    return ESP_ERR_INVALID_STATE;
  }

uint8_t report[6] = {};
  report[0] = keycode;
#if CONFIG_TINYUSB_HID_COUNT > 0
  tud_hid_keyboard_report(0, modifier, report);
  vTaskDelay(pdMS_TO_TICKS(8));
  tud_hid_keyboard_report(0, 0, nullptr);
  vTaskDelay(pdMS_TO_TICKS(2));
  return ESP_OK;
#else
  (void)modifier;
  (void)report;
  return ESP_ERR_NOT_SUPPORTED;
#endif
}
#endif

constexpr char kLogTag[] = "usb_keyboard";
bool g_initialized = false;

}  // namespace

#if CONFIG_TINYUSB_HID_COUNT > 0
extern "C" {

uint8_t const *tud_hid_descriptor_report_cb(uint8_t) {
  return hid_report_descriptor;
}

uint16_t tud_hid_get_report_cb(uint8_t, uint8_t, hid_report_type_t, uint8_t *,
                               uint16_t) {
  return 0;
}

void tud_hid_set_report_cb(uint8_t, uint8_t, hid_report_type_t,
                           uint8_t const *, uint16_t) {}

}  // extern "C"
#endif

namespace usb_keyboard {

esp_err_t init() {
  if (g_initialized) {
    return ESP_OK;
  }

  const tinyusb_config_t config = {
      .device_descriptor = &kDeviceDescriptor,
      .string_descriptor = kStringDescriptors,
      .string_descriptor_count = static_cast<int>(kStringDescriptorCount),
      .external_phy = false,
      .configuration_descriptor = kConfigurationDescriptor,
      .self_powered = false,
      .vbus_monitor_io = -1,
  };

  esp_err_t err = tinyusb_driver_install(&config);
  if (err != ESP_OK) {
    ESP_LOGE(kLogTag, "Failed to install TinyUSB driver: %s",
             esp_err_to_name(err));
    return err;
  }

  tinyusb_config_cdcacm_t acm_cfg = {
      .usb_dev = TINYUSB_USBDEV_0,
      .cdc_port = TINYUSB_CDC_ACM_0,
      .rx_unread_buf_sz = CONFIG_TINYUSB_CDC_RX_BUFSIZE,
      .callback_rx = nullptr,
      .callback_rx_wanted_char = nullptr,
      .callback_line_state_changed = nullptr,
      .callback_line_coding_changed = nullptr,
  };

  err = tusb_cdc_acm_init(&acm_cfg);
  if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
    ESP_LOGW(kLogTag, "TinyUSB CDC init failed: %s", esp_err_to_name(err));
  }

  err = esp_tusb_init_console(TINYUSB_CDC_ACM_0);
  if (err != ESP_OK) {
    ESP_LOGW(kLogTag, "TinyUSB CDC console init failed: %s",
             esp_err_to_name(err));
  }

  g_initialized = true;
  ESP_LOGI(kLogTag, "TinyUSB keyboard initialised");
  return ESP_OK;
}

esp_err_t send_char(char c) {
#if CONFIG_TINYUSB_HID_COUNT > 0
  const auto spec = map_char(c);
  return send_key(spec.modifier, spec.keycode);
#else
  (void)c;
  return ESP_ERR_NOT_SUPPORTED;
#endif
}

esp_err_t send_string(const char *str) {
  if (str == nullptr) {
    return ESP_ERR_INVALID_ARG;
  }
#if CONFIG_TINYUSB_HID_COUNT > 0
  esp_err_t result = ESP_OK;
  for (const char *p = str; *p != '\0'; ++p) {
    const esp_err_t status = send_char(*p);
    if (status != ESP_OK) {
      result = status;
    }
  }
  return result;
#else
  (void)str;
  return ESP_ERR_NOT_SUPPORTED;
#endif
}

esp_err_t send_backspace() {
#if CONFIG_TINYUSB_HID_COUNT > 0
  return send_key(0, HID_KEY_BACKSPACE);
#else
  return ESP_ERR_NOT_SUPPORTED;
#endif
}

esp_err_t send_caps_lock() {
#if CONFIG_TINYUSB_HID_COUNT > 0
  return send_key(0, HID_KEY_CAPS_LOCK);
#else
  return ESP_ERR_NOT_SUPPORTED;
#endif
}

}  // namespace usb_keyboard
