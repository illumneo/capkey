#pragma once
#include <stdint.h>

// SAO Keyboard I2C Interface
// Acts as I2C slave device that buffers characters for a master to read

class SaoKeyboard {
public:
    SaoKeyboard();

    // Initialize I2C as slave with specified address and pins
    void begin(uint8_t address = 0x49, int sda_pin = 12, int scl_pin = 13);

    // Add a character to the transmit buffer
    void sendChar(char c);

    // Check if buffer has space
    bool hasSpace() const;

    // Get buffer usage stats
    uint8_t getBufferUsed() const;
    uint8_t getBufferSize() const;

private:
    static void onI2CRequest();
    static void onI2CReceive(int len);

    bool initialized_;
};

// Global instance for callback access
extern SaoKeyboard* g_sao_keyboard;

