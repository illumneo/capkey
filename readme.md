# Capacitive Touch Keyboard

<img src="./docs/capkey.gif">

A gesture-based capacitive touch keyboard using MessagEase-inspired input. Features both a compact 18mm board the size of a single key cap and a larger 50mm board for practical daily use.

## What Is This?

This project implements a full keyboard interface on a single capacitive touch surface by using gestures (taps, swipes, circles) to input different characters. Instead of pressing physical keys, you perform gestures on a 3×3 grid of touch-sensitive regions. For example:
- **Tap** on a cell to type the primary character (e.g., 'a', 'n', 'i')
- **Swipe** from a cell to type secondary characters (e.g., swipe up from center for 'u')
- **Long swipe** across the entire pad for common actions (space, backspace)
- **Circle** gestures for special functions (number entry, capitalization)

The device appears as a standard USB HID keyboard and can be bodged to also supports I2C communication as a Shitty Add-On (SAO) peripheral.

## Hardware
<img src="./docs/large_pad.jpg" width="200"> <img src="./docs/large_back.jpg" width="200">

- **MCU**: ESP32-S3-Zero (using capacitive touch-sensing pins) (example from [waveshare](https://www.waveshare.com/esp32-s3-zero.htm?sku=25081))
- **Versions**:
  - **4×4 18mm**: Ultra-compact single key version
  - **6×6 50mm**: Business card-sized for practical use
- **PCB**: Custom-designed capacitive touch pads (flower pattern) generated programmatically

## How to Use the Keyboard

### Basic Layout (3×3 Grid)

The touch surface is divided into 9 regions arranged in a grid:

```
 0 | 1 | 2
---|---|---
 3 | 4 | 5
---|---|---
 6 | 7 | 8
```

### Gestures

1. **Tap**: Quick touch and release
   - Primary characters (a, n, i, h, o, r, t, e, s)

2. **Swipe**: Touch and drag in a direction (8 directions: N, NE, E, SE, S, SW, W, NW)
   - Secondary characters and punctuation
   - Example: Tap center (4) for 'o', or swipe-up from center for 'u'

3. **Long Swipe**: Extended swipe across entire surface
   - Special functions (space, backspace)

4. **Swipe-Return**: Swipe out and back in opposite direction
   - Additional character variations

5. **Circle**: Circular motion (clockwise or counter-clockwise)
   - Additional character variations

6. **Hold**: Long press in one location
   - Mode toggles

### Example Character Entry

- **'a'**: Tap position 0 (top-left)
- **'u'**: Swipe up from position 4 (center)
- **Space**: Long swipe from left to right
- **Backspace**: Long swipe from right to left

## PCB Generation

The capacitive touch pad geometry is generated programmatically using Python scripts. This allows for easy experimentation with different pad shapes, sizes, and layouts.

### Script: `generate_svg_capacitive_touch.py`

Located in `kicad/generate_svg_capacitive_touch.py`, this script generates SVG files containing the copper pad patterns.

**Features:**
- **Multiple pad shapes**: Diamond and flower patterns
- **Configurable parameters**: Pitch, corner radius, separation distance, trace width
- **Grid layouts**: Supports various dimensions (2×2, 3×3, 4×4, etc.)
- **Back traces**: Generates via connection patterns for PCB layout

**Usage:**

```bash
cd kicad
python3 generate_svg_capacitive_touch.py
# Output: touch_pads.svg
```

The generated SVG files can be imported directly into KiCad as graphical elements on the copper layers. It is still necessary to manually add all of the vias, but the back traces file helps with alignment. Kicad DRC is also very unhappy with the generated image (since so much stuff overlaps) but it's produced fine results so far.

**Design Guidelines:**

Based on Microchip [AN2934](https://ww1.microchip.com/downloads/aemDocuments/documents/TXFG/ApplicationNotes/ApplicationNotes/Capacitive-Touch-Sensor-Design-Guide-DS00002934-B.pdf), the script implements:
- Proper trace routing to minimize parasitic capacitance
- Optimized pad shapes for uniform touch sensitivity
- Adequate spacing between pads to prevent crosstalk

### Additional Script: `generate_touch_silkscreen.py`

Generates silkscreen overlays showing the key layout. Note: KiCad doesn't process SVG text elements, so the SVG must be converted using Inkscape (text to path) before importing.

## How It Works

The firmware is structured in three main layers:

### 1. Touchpad Layer (`touchpad.h/cpp`)

**Purpose**: Interfaces with ESP32 capacitive touch hardware to determine finger position.

**How it works:**
- Configures 8 touch pins on the ESP32 (arranged in rows and columns)
- Continuously reads capacitance values from each sensor
- Uses ESP-IDF's touch sensor API with benchmark subtraction for stable readings
- Calculates normalized **X, Y, Z** coordinates:
  - **X, Y**: Finger position on the surface (weighted average of active sensors)
  - **Z**: Touch intensity/proximity (sum of all sensor values divided by 2000)
- Coordinate system: Center at (0, 0), ranging approximately ±1.5

**Key features:**
- Automatic baseline calibration
- Per-sensor sensitivity adjustment
- Real-time position tracking

### 2. Gesture Detection Layer (`GestureDetector.h/cpp`, `gestureConfig.h`)

**Purpose**: Analyzes touchpad position data to recognize gesture patterns.

**How it works:**

1. **State Machine**: Tracks touch lifecycle
   - `IDLE`: Waiting for touch
   - `TRACKING`: Recording touch path
   - `GESTURE_DETECTED`: Gesture completed

2. **Path Recording**: Maintains circular buffer of recent position samples
   - Stores X, Y coordinates at each time step
   - Used for detecting complex patterns

3. **Gesture Recognition Algorithms**:

   - **Tap**: Short duration, minimal movement
   - **Hold**: Long duration in same location
   - **Swipe**: Linear movement above threshold distance
     - Direction calculated from angle (8-way: N, NE, E, SE, S, SW, W, NW)
   - **Long Swipe**: Extended swipe across entire surface
   - **Swipe-Return**: Detects reversal in movement direction
     - Tracks maximum distance point and return path
   - **Circle**: Cumulative angle tracking
     - Measures total angular displacement around estimated center
     - Distinguishes clockwise vs counter-clockwise

4. **Grid Position**: Determines which of the cells the gesture started in

**Configuration**: All thresholds are tunable in `gestureConfig.h`:
- Distance thresholds for swipe detection
- Time thresholds for holds
- Angular parameters for circles
- Grid cell boundaries

### 3. Action/Output Layer (`KeyMap.h/cpp`, `saoKeyboard.h/cpp`)

**Purpose**: Converts detected gestures into keyboard actions.

**How it works:**

1. **KeyMap Class**: Routes gestures to appropriate handler
   - Uses starting grid position (0-8) to select handler function
   - Each grid cell has its own gesture mapping
   - Switch statements map gesture+direction combinations to characters

2. **Output Methods**:

   - **USB HID**: Uses Arduino `USBHIDKeyboard` library
     - Appears as standard keyboard device
     - Sends keypresses and special keys (backspace, etc.)

   - **I2C SAO Mode**: Acts as I2C slave device
     - Buffered character transmission
     - Master device reads characters on demand
     - Default address: 0x49, configurable pins

3. **State Management**:
   - Caps lock toggle
   - Mode switching (future expansion)

**Example Mapping** (simplified):
```cpp
// Center cell (position 4)
handleKey4(gesture, direction):
  case TAP: sendChar('o');
  case SWIPE_N: sendChar('u');
  case SWIPE_E: sendChar('b');
  case SWIPE_S: sendChar('d');
  case GESTURE_CIRCLE_CW: sendChar('O');
  // ... etc
```

### Data Flow

```
Touch Sensors → Touchpad → GestureDetector → KeyMap → USB/I2C Output
                 (X,Y,Z)     (Gesture+Dir)   (Char)
```

1. Finger touches pad
2. Touchpad calculates position every ~10ms (depending on # of touch channels and their config)
3. GestureDetector accumulates path and identifies pattern on release
4. KeyMap looks up character based on starting position + gesture
5. Output sent via USB keyboard or I2C buffer

## Project Structure

```
.
├── fw/
│   └── arduino_tests/         # Main firmware (Arduino framework)
│       ├── arduino_tests.ino  # Main sketch
│       ├── touchpad.*         # Touch sensor interface
│       ├── GestureDetector.*  # Gesture recognition engine
│       ├── gestureConfig.h    # Tunable parameters
│       ├── gestureTypes.h     # Data structures
│       ├── KeyMap.*           # Gesture to character mapping
│       └── saoKeyboard.*      # I2C SAO interface
├── kicad/
│   ├── generate_svg_capacitive_touch.py  # PCB pad generator
│   ├── generate_touch_silkscreen.py      # Silkscreen generator
│   ├── capacitive_touch_4x4_18mm/        # Small board files
│   └── capacitive_touch_6x6_50mm/        # Large board files
└── docs/
    └── demo.svg                           # Demo animation
```

## Building and Flashing

### Requirements

- Arduino IDE
- ESP32-S3 board support
- USB connection to ESP32-S3

### Dependencies

The firmware uses:
- `ESP-IDF` touch sensor API (included with ESP32 core)
- `USB.h` and `USBHIDKeyboard.h` (ESP32 Arduino core)
- `Wire.h` for I2C (Arduino standard library)

### Compilation

1. Open `fw/arduino_tests/arduino_tests.ino` in Arduino IDE
2. Select ESP32-S3 board
3. Compile and upload

### Configuration

Edit `gestureConfig.h` to adjust:
- Touch sensitivity thresholds
- Gesture distance requirements
- Timing parameters
- Grid boundaries

## Development Notes

See `devlog.md` for detailed development history and design decisions.

## Future Improvements

- Dynamic touch threshold calibration
- Mouse mode for cursor control
- Bluetooth connectivity
- Custom key mapping via configuration file
- Better support for the larger touchpad

## Acknowledgments

- Capacitive touch design based on Microchip AN2934
- Input method inspired by MessagEase keyboard
- Developed for Hackaday Supercon 2025

