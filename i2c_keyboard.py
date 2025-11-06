"""Read characters from I2C keyboard slave and add to keybuffer"""

from apps.base_app import BaseApp


class I2cKeyboard(BaseApp):
    def __init__(self, name: str, badge):
        super().__init__(name, badge)
        self.i2c_address = 0x49
        self.background_sleep_ms = 20

    def read_i2c_char(self):
        """Read a single ASCII character from the I2C keyboard slave.
        Returns the character as a string, or empty string if no data available or error.
        """
        try:
            # Read 1 byte from the I2C slave
            data = self.badge.sao_i2c.readfrom(self.i2c_address, 2)
            if data and len(data) > 0:
                if data[0] == 1:
                    # Convert byte to ASCII character
                    char = chr(data[1])
                    return char
                else:
                    return None
        except OSError:
            # I2C error (slave not responding, NACK, etc.)
            pass
        except Exception as e:
            # Any other error - print for debugging but don't crash
            print(f"I2C read error: {e}")
        return ""

    def run_background(self):
        char = self.read_i2c_char()
        if char is not None:
            # Add the ASCII character to the keyboard buffer
            self.badge.keyboard.keybuffer.append(char)
