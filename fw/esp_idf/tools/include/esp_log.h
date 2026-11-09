#pragma once

// Host-only shim: keep firmware logging arguments type checked while keeping
// stdout reserved for the replay JSONL protocol. No device APIs are emulated.
#include <cstdio>
#define ESP_LOGI(tag, ...) do { if (false) { (void)(tag); std::fprintf(stderr, __VA_ARGS__); } } while (0)
#define ESP_LOGW(tag, ...) ESP_LOGI(tag, __VA_ARGS__)
#define ESP_LOGE(tag, ...) ESP_LOGI(tag, __VA_ARGS__)
#define ESP_LOGD(tag, ...) ESP_LOGI(tag, __VA_ARGS__)
#define ESP_EARLY_LOGI(tag, ...) ESP_LOGI(tag, __VA_ARGS__)
#define ESP_EARLY_LOGW(tag, ...) ESP_LOGI(tag, __VA_ARGS__)
#define ESP_EARLY_LOGE(tag, ...) ESP_LOGI(tag, __VA_ARGS__)
#define ESP_EARLY_LOGD(tag, ...) ESP_LOGI(tag, __VA_ARGS__)
