#include "Arduino.h"
#include "driver/touch_sens.h"

extern uint32_t scans;

class Touchpad {
    public:
        Touchpad(touch_sensor_handle_t& sens_handle, uint8_t channel_id[8]);

        void initTouch();
        void processInputs();
        void calculatePosition();

        void read(float &x, float &y, float &z);

    private:
        touch_sensor_handle_t& sens_handle_;
        uint8_t channel_id_[8];
        touch_channel_handle_t chan_handle_[8];
        int32_t readings_[8];
        uint32_t benchmark_[8];

        float x_, y_, z_;
};

