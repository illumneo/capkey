// ESP32 Touch Test
// Just test touch pin - Touch0 is T0 which is on GPIO 4.
#include "driver/touch_sens.h"
#include "USB.h"
#include "USBHIDKeyboard.h"

#include "touchpad.h"

#define EXAMPLE_TOUCH_SAMPLE_CFG_DEFAULT()      {TOUCH_SENSOR_V2_DEFAULT_SAMPLE_CONFIG(500, TOUCH_VOLT_LIM_L_0V5, TOUCH_VOLT_LIM_H_2V2)}

USBHIDKeyboard Keyboard;

int32_t offset[8];
int32_t readings[8];
float x, y, z;

const char board[10][9] = {
  //c    N    NW   W    SW   S    SE   E    NE
  {'.', '.', '.', '.', '.', '.', '.', '.', '.'},
  {'a', '.', '.', '.', '.', '.', 'v', '\n', '.'},
  {'n', '.', '.', '.', '.', 'l', '.', '.', '.'},
  {'i', '.', '.', '.', 'x', '.', '.', '.', '.'},
  {'h', '.', '.', '.', '.', '.', '.', 'k', '.'},
  {'o', 'u', 'q', 'c', 'g', 'd', 'j', 'b', 'p'},
  {'r', '.', '.', 'm', '.', '.', '.', '.', '.'},
  {'t', '.', '.', '.', '.', '.', '.', ' ', 'y'},
  {'e', 'w', '.', '.', '.', '.', '.', 'z', '.'},
  {'s', '.', 'f', KEY_BACKSPACE, '.', '.', '.', '.', '.'}
};



// The touch channel IDs that used in this example
// For the corresponding GPIOs of these channel, please refer to 'touch_sensor_channel.h'
static uint8_t s_channel_id[8] = {
    1,
    2,
    10,
    9,
    11,
    12,
    3,
    4,
};

/* Handles of touch sensor */
touch_sensor_handle_t sens_handle = NULL;

Touchpad touchpad(sens_handle, s_channel_id);


void initTouch() {

     /* Step 1: Create a new touch sensor controller handle with default sample configuration */
     touch_sensor_sample_config_t sample_cfg[TOUCH_SAMPLE_CFG_NUM] = EXAMPLE_TOUCH_SAMPLE_CFG_DEFAULT();
     touch_sensor_config_t sens_cfg = TOUCH_SENSOR_DEFAULT_BASIC_CONFIG(1, sample_cfg);
     touch_sensor_new_controller(&sens_cfg, &sens_handle);

     touchpad.initTouch();

    //  /* Step 2: Create and enable the new touch channel handles with default configurations */
    //  touch_channel_config_t chan_cfg = EXAMPLE_TOUCH_CHAN_CFG_DEFAULT();
    //  /* Allocate new touch channel on the touch controller */
    //  for (int i = 0; i < EXAMPLE_TOUCH_CHANNEL_NUM; i++) {
    //      touch_sensor_new_channel(sens_handle, s_channel_id[i], &chan_cfg, &chan_handle[i]);
    //  }
    //  printf("=================================\n");

     /* Step 3: Confiture the default filter for the touch sensor (Note: Touch V1 uses software filter) */
     touch_sensor_filter_config_t filter_cfg = TOUCH_SENSOR_DEFAULT_FILTER_CONFIG();
     touch_sensor_config_filter(sens_handle, &filter_cfg);

     /* Step 6: Enable the touch sensor */
     touch_sensor_enable(sens_handle);

     /* Step 7: Start continuous scanning, you can also trigger oneshot scanning manually */
     touch_sensor_start_continuous_scanning(sens_handle);

}


void setup() {
  Serial.begin(115200);
  initTouch();

  delay(1000);  // give me time to bring up serial monitor
  Serial.println("ESP32 Touch Test");

  Keyboard.begin();
  USB.begin();
}

void loop() {
  touchpad.processInputs();

  touchpad.read(x, y, z);
  gestureFSM(x, y, z);

  if (z > .5) {
    printf("%ld, %f, %f, %f\n", micros(), x, y, z);
  }
}

int getPosition(float x, float y, float z) {
  static int pos = 0;
  if (z > 1) { // touch detected
    if(y < -.5) {
      pos = 1;
    } else if ( y < .5) {
      pos = 2;
    } else {
      pos = 3;
    }
    if(x < -.5) {
      pos += 0;
    } else if ( x < .5) {
      pos += 3;
    } else {
      pos += 6;
    }
  }
  return pos;
}

enum GestureState {
  WAITING_FOR_TOUCH,
  TRACKING_GESTURE,
  DETECTING_GESTURE
};

const float TOUCH_THRESHOLD = 2;



void gestureFSM(float x, float y, float z) {
  static GestureState state = WAITING_FOR_TOUCH;
  static float start_x, start_y;
  switch (state) {
    case WAITING_FOR_TOUCH:
      if (z > TOUCH_THRESHOLD) {
        state = TRACKING_GESTURE;
        start_x = x;
        start_y = y;
      }
      break;
    case TRACKING_GESTURE:
     if (z < TOUCH_THRESHOLD * .8) { // TODO: add hysteresis?
        calculateGesture(start_x, start_y, x, y);
        state = WAITING_FOR_TOUCH;
      }
  }
}

void calculateGesture(float start_x, float start_y, float end_x, float end_y) {
  float x = end_x - start_x;
  float y = end_y - start_y;
  float angle = atan2(y, x) * 180.0 / M_PI + 180;
  float distance = sqrt(x*x + y*y);
  uint8_t gesture;
  // printf("%d, ", getPosition(start_x, start_y, 2));
  if (distance < .5) { // just a tap, no movement
    // printf("@@tap %f, %f\n", angle, distance);
    gesture = 0;
  } else {
    gesture = (int) (angle + 22.5+45)/45;
    if (gesture == 9) {
      gesture = 1;
    }
    // printf("@@swipe %f, %f, d: %d\n", angle, distance, (int) (angle + 22.5)/45);

  }

  printf(", , , , %c\n", board[getPosition(start_x, start_y, 2)][gesture]);
  Serial.flush();
  Keyboard.write(board[getPosition(start_x, start_y, 2)][gesture]);
}

/*
Get start,
if at any point distance is greater than X, calculate the direction
If distance is greater, update zone again (to handle in accuracies when close to start)
If end distance is less than 1/2 max distance (including direction?) then it is a swipe back

Is a circle one where the min/max angle delta is greater than X?


So:
- Get start location
- calculate distance and angle
- if distance is great than X, type == swipe
- if distance is > then max distance, update angle
- while distance is > than X, update min/max angles
- (Some check to see if swipe back occured)

variables:
- max distance
- min angle
- max angle
- swipe angle

output:
- gesture type (tap, swipe, swipe back, cw, ccw?)
- angle? (or maybe gesture type is just an enum with all options)
- which square it started in?

(Let's just start with taps and swipes)
on press:
- save start/stop
on release: (Is on release reasonable? will the data be okay?)
- if magnitude < X --> it's a tap
- else, get angle



Json:
keys: [
  {
  // Types: tap, swipe, longpress, swipeback, longswipe, circle CW, circle CCW
    //"Location": [primary(tap/swipe), secondary(longpress/swipeback), tertiary(circle)]
    "center": ["A"],
    "topLeft": ["A",],
    "top": ["A"],
    "topRight": ["A"],
    "left": ["A"],
    "right": "A",
    "bottomLeft": "A",
    "bottom": "A",
    "bottomRight": "A",

    // How do I handle hold gestures (multi delete, move cursor, etc)? Or stateful ones (shift, ctrl, etc)?
    // Also, I want to be able to print a string (such as url for the project page, version #, etc)

Could generate 'current guess' on each tick, and then based on time, movement, or release, it could change?


  }
]


*/
