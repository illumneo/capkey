#include "saoKeyboard.h"
#include "Arduino.h"
#include "Wire.h"

// I2C Configuration
#define BUFFER_SIZE 32

// Circular buffer for characters to send
static char charBuffer[BUFFER_SIZE];
static volatile uint8_t bufferHead = 0;  // Where we write new data
static volatile uint8_t bufferTail = 0;  // Where we read data to send

// Global instance pointer for callbacks
SaoKeyboard* g_sao_keyboard = nullptr;

// Internal buffer management functions
static bool hasData() {
    return bufferHead != bufferTail;
}

static char peekChar() {
    if (hasData()) {
        return charBuffer[bufferTail];
    }
    return 0;
}

static void consumeChar() {
    if (hasData()) {
        bufferTail = (bufferTail + 1) % BUFFER_SIZE;
    }
}

static uint8_t getUsed() {
    if (bufferHead >= bufferTail) {
        return bufferHead - bufferTail;
    } else {
        return BUFFER_SIZE - bufferTail + bufferHead;
    }
}

SaoKeyboard::SaoKeyboard()
    : initialized_(false) {
    g_sao_keyboard = this;
}

void SaoKeyboard::begin(uint8_t address, int sda_pin, int scl_pin) {
    if (initialized_) {
        return;
    }

    Wire.onReceive(SaoKeyboard::onI2CReceive);
    Wire.onRequest(SaoKeyboard::onI2CRequest);
    Wire.setPins(sda_pin, scl_pin);
    Wire.begin((uint8_t)address);

    initialized_ = true;
}

void SaoKeyboard::sendChar(char c) {
    if (!initialized_) {
        return;
    }

    uint8_t nextHead = (bufferHead + 1) % BUFFER_SIZE;
    if (nextHead != bufferTail) {  // Not full
        charBuffer[bufferHead] = c;
        bufferHead = nextHead;
    }
}

bool SaoKeyboard::hasSpace() const {
    uint8_t nextHead = (bufferHead + 1) % BUFFER_SIZE;
    return nextHead != bufferTail;
}

uint8_t SaoKeyboard::getBufferUsed() const {
    return getUsed();
}

uint8_t SaoKeyboard::getBufferSize() const {
    return BUFFER_SIZE;
}

void SaoKeyboard::onI2CRequest() {
    uint8_t data[2];

    if (hasData()) {
        data[0] = 1;  // Data available flag
        data[1] = peekChar();
        Wire.write(data, 2);
        consumeChar();  // Remove from buffer after sending
    } else {
        data[0] = 0;  // No data available
        data[1] = 0;
        Wire.write(data, 2);
    }
}

void SaoKeyboard::onI2CReceive(int len) {
    // Drain any received data
    while (Wire.available()) {
        Wire.read();
    }
}

