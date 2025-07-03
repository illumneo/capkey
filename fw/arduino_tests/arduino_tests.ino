// ESP32 Touch Test
// Just test touch pin - Touch0 is T0 which is on GPIO 4.

int32_t offset[8];
int32_t readings[8];
float x, y, z;

void setup() {
  Serial.begin(115200);
  offset[0] = touchRead(1);
  offset[1] = touchRead(2);
  offset[2] = touchRead(10);
  offset[3] = touchRead(9);
  offset[4] = touchRead(11);
  offset[5] = touchRead(12);
  offset[6] = touchRead(3);
  offset[7] = touchRead(4);

  delay(1000);  // give me time to bring up serial monitor
  Serial.println("ESP32 Touch Test");
}

void loop() {
  readings[0] = touchRead(1);
  readings[1] = touchRead(2);
  readings[2] = touchRead(10);
  readings[3] = touchRead(9);
  readings[4] = touchRead(11);
  readings[5] = touchRead(12);
  readings[6] = touchRead(3);
  readings[7] = touchRead(4);

  uint32_t zero = touchRead(0);
  for(int i =0; i < 8; i++) {
    readings[i] -= offset[i];
   // printf( "%d, ", readings[i]);
  }
  calculate(readings, x, y, z);
  printf("%f, %f, %f", x, y, z);
  printf(",%d ", getPosition(x, y, z));
  printf("\n");
  delay(50);
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
  z = (sum_x + sum_y) / 10000.0;


}
