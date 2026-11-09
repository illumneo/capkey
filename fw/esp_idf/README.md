# CapKey ESP-IDF firmware

Standalone USB HID firmware for the **50 mm CapKey touch board**, with a CDC
serial interface for recording and diagnostics on the same cable. Normal typing
does not require a host process. Use a **US keyboard layout** on the computer.

## Build and install

Run these commands from `fw/esp_idf/` after activating an ESP-IDF 5.5 environment:

```sh
idf.py build
```

For an initial installation, put the board in its ROM bootloader and use
`idf.py -p PORT flash`, replacing `PORT` with its serial device. This installs
the project's bootloader, partition table and application.

For subsequent updates to this firmware, the application-only updater preserves
the existing bootloader and partition table:

```sh
python3 scripts/flash_keyboard.py --port /dev/ttyACM0
```

The updater requires `pyserial` and an ESP-IDF Python environment with `esptool`.
It expects a 1 MiB application partition at `0x10000`, asks the running keyboard
to enter its ROM bootloader, writes `build/swipe.bin`, and waits for CapKey to
reconnect. Opening CDC alone does not reset the keyboard.

Keep the touch surface clear while connecting or restarting the board so its
initial touch baselines can settle.

## Typing

With the touch side facing you, the CapKey inscription upright and USB at the
top, the tap layout is:

| | | | |
| --- | --- | --- | --- |
| a | n | i | 0 |
| h | o | r | Shift |
| t | e | s | Backspace |
| Space | Space | Space | Enter |

- **Lowercase:** tap a primary letter or swipe in a printed letter direction.
- **Uppercase primary letters:** hold nearly still for at least half a second,
  then lift. This applies to A, N, I, H, O, R, T, E and S.
- **Uppercase directional letters:** swipe out and back toward the starting
  point before lifting. All 17 directional letters support this; for example,
  A southeast/back gives V and E north/back gives W.
- **Shift:** tap Shift, then enter a character. Tap Shift again to cancel it.
  The modifier is not held at the host while waiting for the next character.
- **Digits:** counterclockwise circles on the nine letter cells produce 1–9
  in row order: A=1, N=2, I=3, H=4, O=5, R=6, T=7, E=8, S=9. Tap the
  upper-right cell for 0. Finish a circle near its starting point.

From O: north U, northeast P, east B, southeast J, south D, southwest G,
west C and northwest Q. Swipe left or up-left from I for `?`; down-left gives X
(lowercase unless returning). R north/south moves the cursor up/down, and
T southeast produces Tab. [main/keyMap.cpp](main/keyMap.cpp) defines the complete
letter, punctuation and command mapping.

Actions occur on release; keeping a finger down does not repeat a key. Hold
timing includes the sensor filter's release tail, and small landing/release
drift is allowed. Recognized motion takes precedence over a hold. Holding a
command pad or the zero pad produces its ordinary single tap action.

Recognized clockwise circles are consumed without typing. A malformed loop can
still classify as another gesture. Ctrl, Alt/Meta and function-key gestures
are not assigned. The firmware does not automatically change its mappings or
recognition thresholds.

## Record once and replay changes

[CALIBRATION.md](CALIBRATION.md) describes the capture protocol, board mapping,
calibration tools and validation workflow. A bounded raw recording can be made
with:

```sh
python3 scripts/capture_session.py --port /dev/ttyACM0 --duration 60 \
  --session-dir .calibration/sessions/example
python3 scripts/replay_capture.py \
  --input .calibration/sessions/example/frames.jsonl \
  --mode pcb --verify-device --output .calibration/example-replay.jsonl
```

Capture requires `pyserial`; replay requires a C++17 compiler. Use a new session
directory and output filename for each run. The host replay executes the same
C++ touch processing, recognizer and keymap as the device. Device parity checks
compare recorded decisions after synchronization; they do not establish that
those decisions matched the intended characters.

For ordinary typing, `record_typing.py` records raw touches and actual USB
reports while typing continues normally:

```sh
python3 scripts/record_typing.py --port /dev/ttyACM0 --duration 600 \
  --session-dir .calibration/sessions/typing-example
```

This Linux recorder requires access to the board's CDC and hidraw nodes. It
freezes a host replay executable before collection and verifies device parity
only when its source identity matches the running firmware. Stop with Ctrl-C
or by creating `stop-request` inside the session directory.

## Completion history and correction analysis

The firmware keeps the last **32 completed actions in RAM**, including touch
geometry, duration, transmitted keys, Shift/Caps state and completion time.
Older records are overwritten; removing power clears the history. Retrieve and
analyze a snapshot without starting raw recording:

```sh
python3 scripts/read_hid_log.py --port /dev/ttyACM0 \
  --output .calibration/history-query.jsonl
python3 scripts/analyze_corrections.py --hid-log .calibration/history-query.jsonl \
  --output .calibration/corrections.json
```

For longer sessions, archive overlapping snapshots:

```sh
python3 scripts/watch_hid_log.py --port /dev/ttyACM0 \
  --output-dir .calibration/history/example --duration 3600
python3 scripts/analyze_corrections.py --history-dir .calibration/history/example \
  --output .calibration/history-corrections.json
```

The collector polls once per second and follows the selected board across
reconnects. Stop with Ctrl-C or by creating `stop-request` in its output
directory. History queries are refused while raw recording is active.

Possible character/Backspace/replacement sequences are evidence to inspect,
not confirmed intent or automatic training labels. Navigation, ambiguous
multiple deletions, diagnostic actions and gaps limit the inference.

Recordings can contain typed text, device identifiers and local paths. They are
stored under the ignored `.calibration/` directory; review and redact captures
before sharing them.

## Checks and limits

Run the host regressions without a connected device:

```sh
python3 -B -m unittest discover -s tests -v
python3 -B -m unittest discover -s scripts -p 'test_*.py' -v
```

The tests cover recognition geometry, mapping, HID encoding, protocol handling,
record/replay consistency and correction analysis. Generated synthetic inputs
test specific behavior; they do not establish general typing accuracy
or speed on another board or for another user.

For a separate Linux USB-output check, `scripts/verify_hid_device.py` uses the
board's CDC, hidraw and input-event nodes. It takes an exclusive keyboard grab
before sending diagnostic key commands and verifies releases before relinquishing
it. These commands bypass touch recognition; see [CALIBRATION.md](CALIBRATION.md)
for invocation and interpretation.
