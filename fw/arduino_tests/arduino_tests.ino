// ESP32 Touch Test
// Just test touch pin - Touch0 is T0 which is on GPIO 4.
#include "driver/touch_sens.h"

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
  {'s', '.', 'f', '.', '.', '.', '.', '.', '.'}
};


#define EXAMPLE_TOUCH_SAMPLE_CFG_DEFAULT()      {TOUCH_SENSOR_V2_DEFAULT_SAMPLE_CONFIG(500, TOUCH_VOLT_LIM_L_0V5, TOUCH_VOLT_LIM_H_2V2)}
#define EXAMPLE_TOUCH_CHAN_CFG_DEFAULT()        {  \
    .active_thresh = {2000},  \
    .charge_speed = TOUCH_CHARGE_SPEED_7,  \
    .init_charge_volt = TOUCH_INIT_CHARGE_VOLT_DEFAULT,  \
}

// Touch version 3 supports multiple sample configurations (i.e. supports frequency hopping),
// others only have one set of sample configurations.
#define EXAMPLE_TOUCH_CHANNEL_NUM           8


// The touch channel IDs that used in this example
// For the corresponding GPIOs of these channel, please refer to 'touch_sensor_channel.h'
static int s_channel_id[EXAMPLE_TOUCH_CHANNEL_NUM] = {
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
touch_channel_handle_t chan_handle[EXAMPLE_TOUCH_CHANNEL_NUM];




void initTouch() {

     /* Step 1: Create a new touch sensor controller handle with default sample configuration */
     touch_sensor_sample_config_t sample_cfg[TOUCH_SAMPLE_CFG_NUM] = EXAMPLE_TOUCH_SAMPLE_CFG_DEFAULT();
     touch_sensor_config_t sens_cfg = TOUCH_SENSOR_DEFAULT_BASIC_CONFIG(1, sample_cfg);
     touch_sensor_new_controller(&sens_cfg, &sens_handle);

     /* Step 2: Create and enable the new touch channel handles with default configurations */
     touch_channel_config_t chan_cfg = EXAMPLE_TOUCH_CHAN_CFG_DEFAULT();
     /* Allocate new touch channel on the touch controller */
     for (int i = 0; i < EXAMPLE_TOUCH_CHANNEL_NUM; i++) {
         touch_sensor_new_channel(sens_handle, s_channel_id[i], &chan_cfg, &chan_handle[i]);
     }
     printf("=================================\n");

     /* Step 3: Confiture the default filter for the touch sensor (Note: Touch V1 uses software filter) */
     touch_sensor_filter_config_t filter_cfg = TOUCH_SENSOR_DEFAULT_FILTER_CONFIG();
     touch_sensor_config_filter(sens_handle, &filter_cfg);

     /* Step 6: Enable the touch sensor */
     touch_sensor_enable(sens_handle);

     /* Step 7: Start continuous scanning, you can also trigger oneshot scanning manually */
     touch_sensor_start_continuous_scanning(sens_handle);

}


void readPads(int32_t readings[8]) {
  uint32_t benchmark = 0;
  uint32_t data = 0;
  for(int i = 0; i < EXAMPLE_TOUCH_CHANNEL_NUM; i++) {
    touch_channel_read_data(chan_handle[i], TOUCH_CHAN_DATA_TYPE_BENCHMARK, &benchmark);
    touch_channel_read_data(chan_handle[i], TOUCH_CHAN_DATA_TYPE_SMOOTH, &data);
    readings[i] = data - benchmark;
  }
}


void setup() {
  Serial.begin(115200);
  initTouch();

  delay(1000);  // give me time to bring up serial monitor
  Serial.println("ESP32 Touch Test");
}

void loop() {
  readPads(readings);

  calculate(readings, x, y, z);
  gestureFSM(x, y, z);

  // printf("%f, %f, %f", x, y, z);
  // printf(",%d ", getPosition(x, y, z));

  // printf("\n");
  // delay(50);

  if (z > .5) {
    // printf("%ld, %f, %f, %f\n", micros(), x, y, z);
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
void calculate(int32_t readings[8], float &x, float &y, float &z) {
  int32_t sum_x = 0, sum_y = 0, centroid_x = 0, centroid_y = 0;
  float weight[4] {-1.5, -.5, .5, 1.5};
  for (int i = 0; i < 4; i++) {
    sum_x += readings[i];
    sum_y += readings[4 + i];

    centroid_x += readings[i] * weight[i];
    centroid_y += readings[4 + i] * weight[i];
  }

  x = 1.0 * centroid_x / sum_x;
  y = 1.0 * centroid_y / sum_y;
  z = (sum_x + sum_y) / 5000.0;


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
*/
