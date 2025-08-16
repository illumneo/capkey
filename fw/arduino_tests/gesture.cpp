#include "gesture.h"


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
const float TOUCH_THRESHOLD = 2;


// Helper functions
int getPosition(float x, float y, float z);
char calculateGesture(float start_x, float start_y, float end_x, float end_y);

// Lone function to pass into xTaskCreate to run Gesture::tick()
void gestureTask(void *pvParameters) {
    Gesture *gesture = (Gesture *)pvParameters;
    while (1) {
        gesture->tick();
    }
}

Gesture::Gesture(QueueHandle_t& position_queue) : position_queue_(position_queue) {
}

void Gesture::init() {
    if (keyboard_on_) {
        keyboard_.begin();
        USB.begin();
    }
}

void Gesture::tick() {
    TouchpadPosition position;
    float x, y, z;
    xQueueReceive(position_queue_, &position, portMAX_DELAY);

    position.read(x, y, z);
    gestureFSM(x, y, z);

    if (z > .5) {
        printf("%ld, %f, %f, %f\n", position.timestamp, x, y, z);
    }
}

void Gesture::gestureFSM(float x, float y, float z) {
    static float start_x, start_y;
    switch (state_) {
      case WAITING_FOR_TOUCH:
        if (z > TOUCH_THRESHOLD) {
          state_ = TRACKING_GESTURE;
          start_x = x;
          start_y = y;
        }
        break;
      case TRACKING_GESTURE:
       if (z < TOUCH_THRESHOLD * .8) { // TODO: add hysteresis?
        char c = calculateGesture(start_x, start_y, x, y);
        keyboard_.write(c);
        printf("%c\n", c);

        state_ = WAITING_FOR_TOUCH;
        }
    }
  }

/*****************************************************
* Helper functions
******************************************************/

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

  char calculateGesture(float start_x, float start_y, float end_x, float end_y) {
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
    return board[getPosition(start_x, start_y, 2)][gesture];
  }
