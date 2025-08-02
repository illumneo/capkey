// ESP32 Touch Test
// Just test touch pin - Touch0 is T0 which is on GPIO 4.

int32_t offset[8];
int32_t readings[8];
float x, y, z;

void readPads(int32_t readings[8]) {
  readings[0] = touchRead(1);
  readings[1] = touchRead(2);
  readings[2] = touchRead(10);
  readings[3] = touchRead(9);
  readings[4] = touchRead(11);
  readings[5] = touchRead(12);
  readings[6] = touchRead(3);
  readings[7] = touchRead(4);
}


void setup() {
  Serial.begin(115200);
  readPads(offset);

  delay(1000);  // give me time to bring up serial monitor
  Serial.println("ESP32 Touch Test");
}

void loop() {
  readPads(readings);

  uint32_t zero = touchRead(0);
  for(int i =0; i < 8; i++) {
    readings[i] -= offset[i];
  }
  calculate(readings, x, y, z);
  gestureFSM(x, y, z);

  // printf("%f, %f, %f", x, y, z);
  // printf(",%d ", getPosition(x, y, z));

  // printf("\n");
  // delay(50);
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
  y = 1.0 * centroid_y / sum_y * 0.8; // small correction factor since x and y pads are different capacitance
  z = (sum_x + sum_y) / 10000.0;


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
     if (z < TOUCH_THRESHOLD) { // TODO: add hysteresis?
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
  printf("%d, ", getPosition(start_x, start_y, 2));
  if (distance < .5) { // just a tap, no movement
    printf("@@tap %f, %f\n", angle, distance);
    gesture = 0;
  } else {
    gesture = (int) (angle + 22.5+45)/45;
    if (gesture == 9) {
      gesture = 1;
    }
    printf("@@swipe %f, %f, d: %d\n", angle, distance, (int) (angle + 22.5)/45);

  }

  char gesture_str[9] = {'o', 'u', 'q', 'c', 'g', 'd', 'j', 'b', 'p'};

  printf("______%c______\n", gesture_str[gesture]);
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
