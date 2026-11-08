# Calibration and replay

This firmware targets the **50 mm CapKey PCB**. Touch acquisition, recognition
and USB HID output run continuously. `HELLO` enables diagnostic streaming and
`STOP` disables it without resetting recognition. CDC diagnostics and HID share
the native USB connection. Use a US keyboard layout on the host.

## Build and acquisition settings

From `fw/esp_idf/`, activate ESP-IDF 5.5 and run:

```sh
idf.py build
```

See [README.md](README.md#build-and-install) for initial installation and
application-only updates. Keep the surface clear during boot: startup performs
three initial scans and resets each hardware benchmark once from settled
readings. Recording commands do not recalibrate a live touch.

The default is **200 charge cycles**, with hardware active threshold **500**.
The scan rate was approximately 60 Hz on the development board; measure it again
when changing hardware or acquisition settings. `idf.py menuconfig` exposes the
charge-cycle setting under **Swipe**. To build another setting without editing
the normal configuration:

```sh
python3 scripts/build_capture.py --charge-times 200
```

This writes `.calibration/sdkconfig.capture` and builds in
`.calibration/build-capture/`. It is the same runtime, not a separate recorder
firmware. The retained diagnostic-build flag has no runtime effect.

Metadata records acquisition settings and build/source identities. Keep captures
with different settings in separate sessions. Processing normalizes deltas by
`800 / charge_times`; this linear scale is an explicit model assumption, not
proof of identical sensor response at different settings.

## Board mapping and recognition

Physical GPIO numbers 1–14 equal their indices in the sample arrays. Slot 0
represents the internal denoise channel and is not a measured surface electrode.
GPIO13/14 are diagnostic probes. With the touch side facing you and the
**CapKey inscription upright**:

| Electrodes | GPIOs in physical order |
| --- | --- |
| Columns, left to right | 11, 9, 10, 2, 3, 4 |
| Rows, top to bottom | 1, 12, 8, 5, 6, 7 |

Processing uses positive `smooth - benchmark` signals and separate row/column
centroids on a 0–3 coordinate span. Logical cell centers are integers. Two active
scans confirm the start position; the first crossing still determines duration.
On release, the last in-contact position is retained because lift-off coordinates
can be unreliable.

The main recognition choices are:

- Ordinary swipes retain a 0.45-cell threshold. Shorter strokes can qualify with
  at least 0.32-cell net displacement, peak/path efficiency of at least 0.75,
  and endpoint/peak retention of at least 0.8, in a bound direction.
- The two I-cell `?` bindings use a 0.28-cell minimum. Edge assistance cannot
  bypass their path-quality checks. Metadata's `coherent_swipe_min_distance`
  reports the global default; the full source identity covers binding overrides.
- Edge assistance requires at least 0.20-cell motion and preserves the observed
  component's sign rather than reversing an inward stroke.
- Primary-letter holds require 500 ms and less than 0.25-cell excursion.
  Supported motion takes precedence; a slow tap-like command-pad contact still
  produces one action on release.
- Returns need sufficient outward motion and an endpoint below 0.55 of peak
  excursion. A bound initial direction wins; otherwise a bound peak direction
  can supply the return action.
- Circle tracking accumulates heading changes at 0.02-cell spatial anchors,
  rather than measuring rotation around a moving centroid. Eligibility requires
  eight anchors, at least 0.10-cell span, closure within 0.65 of peak, and the
  configured turn, area-density, signed-area-consistency and shape checks.
  Circles are considered before the simpler return rule. Recognized clockwise
  loops have explicit no-action bindings.

These are heuristic geometry rules. The constants in
[main/gestureConfig.h](main/gestureConfig.h) and bindings in
[main/keyMap.cpp](main/keyMap.cpp) are the source of truth. A malformed gesture
can match a different rule; the recognizer cannot infer intent from arbitrary
motion.

## Record a bounded session

The collectors require Python with `pyserial`. Use a new directory:

```sh
python3 scripts/capture_session.py --port /dev/ttyACM0 --duration 60 \
  --session-dir .calibration/sessions/example
```

The recorder preserves the complete wire stream, sends `HELLO` and a
device-clock start marker, and archives already-buffered records as startup
data. Normal recording begins at the acknowledged boundary. An idle checkpoint
later synchronizes replay with the continuously running recognizer, including
when recording begins during a touch.

For labeled input, save simple instructions and the intended order beside the
capture. Annotate extra, missed or mistaken inputs without changing the original
samples. Prompt times bound intended input; they are not exact contact times.
Long stationary holds provide position evidence, not automatic tap labels.

An optional guided collector is also included:

```sh
python3 scripts/collect_calibration.py --port /dev/ttyACM0 \
  --output .calibration/sessions/guided-example
```

It serves the supplied calibration UI on loopback port 8765; `--listen-port`
changes the port. `--dry-run` uses a synthetic wire fixture and must not be
reported as physical calibration data. The command-line recorder above does
not require a browser.

A raw session contains:

- `wire.bin`: original bytes, including startup text and incomplete packets.
- `frames.jsonl`: metadata, raw/smooth/benchmark arrays, validity masks,
  scan/time identifiers, marker acknowledgements and device events.
- `session.json`: acquisition provenance and separate acquisition/telemetry
  integrity summaries.
- `commands.jsonl`: host requests. Guided sessions also preserve trial labels.

Samples include idle and release periods; recording is not touch-gated.
Register reads occur sequentially at scan completion, with snapshot duration
recorded. Keep both the original stream and decoded frames.

For raw touches plus actual USB reports during ordinary typing on Linux:

```sh
python3 scripts/record_typing.py --port /dev/ttyACM0 --duration 600 \
  --session-dir .calibration/sessions/typing-example
```

This requires CDC and hidraw access. It does not grab the keyboard, inject keys,
or prescribe text: normal typing continues. It also writes `hidraw.jsonl`,
`input-context.json`, `installed-metadata.json` and `typing-recording.json`.
Stop after the duration, with Ctrl-C, or by creating `stop-request` in the session
directory. The recorder freezes a replay executable before collection and checks
its source identity against the device. Matching, clean sessions additionally
receive `verified-replay.jsonl` and `replay-result.json`; otherwise the report
records why verification was skipped or failed.

Captures can reconstruct typed text and include device identifiers and local
paths. Keep private sessions under the ignored `.calibration/` directory and
redact any material selected for publication.

## Replay and analyze

Replay requires a C++17 compiler and executes the shared touch processing,
detector and keymap:

```sh
python3 scripts/replay_capture.py \
  --input .calibration/sessions/example/frames.jsonl \
  --mode pcb --verify-device --output .calibration/example-replay.jsonl
python3 scripts/analyze_capture.py .calibration/sessions/example \
  --output .calibration/example-quality.json
```

`--verify-device` compares recorded decisions with host replay **after an idle
checkpoint**, matching sample identity, gesture, coordinates and action. Read
the synchronized sample coverage and compared gesture count: an idle-only match
does not establish touch accuracy. Missing or duplicate events, mismatched
decisions, invalid measurements and data loss cannot count as successful parity.

For older captures without device-event telemetry, omit `--verify-device`.
`--mode legacy` remains available for regression comparisons. Replay preserves
idle intervals and does not reset at trial labels. Missing samples fail by
default; `--gap-policy reset` explicitly segments damaged evidence and cannot
establish uninterrupted device parity.

After changing the recognizer, write candidate results separately from the
original device-parity results. A different source identity can intentionally
produce different decisions. Keep the original source/build identity and
intended labels with the input so improvements can be reviewed independently.

The included `tests/` generate synthetic inputs for reproducible behavior checks:

```sh
python3 -B -m unittest discover -s tests -v
python3 -B -m unittest discover -s scripts -p 'test_*.py' -v
```

The host tests compile production C++ with a logging shim. Coverage includes
release coordinates, successive contacts, taps/holds/returns, circle sampling
and negative geometry controls, edge directions, key bindings, HID encoding,
protocol integrity, recorder cleanup and correction inference. Synthetic timing,
noise, scale or geometry changes are sensitivity checks, not new physical trials.

For sparse legacy centroid logs, `scripts/analyze_taps.py` summarizes contacts
and `scripts/fit_affine.py` fits coordinates to the 4×4 integer-center grid.
The affine tool requires the exact intended contact order; `--expected` supplies
custom targets and `--taps-per-target` specifies consecutive repetitions. It
rejects partial, extra or malformed sequences rather than shifting labels.
Sparse logs cannot replace complete raw captures: do not invent missing idle
frames or use them to claim gesture replay. If fitting a new spatial model,
reserve whole independent contacts or passes for validation; neighboring frames
from a single touch are not independent observations.

## Passive completion history

The device retains 32 successfully completed HID actions in RAM. Each entry
links transmitted press reports to gesture geometry, duration, scan/event IDs,
Shift/Caps state and completion time. Diagnostic actions have separate
provenance. Failed or partly transmitted actions do not enter the success log;
failure counters and boot/generation boundaries remain significant.

Retrieve one snapshot:

```sh
python3 scripts/read_hid_log.py --port /dev/ttyACM0 \
  --output .calibration/history-query.jsonl
python3 scripts/analyze_corrections.py --hid-log .calibration/history-query.jsonl \
  --output .calibration/corrections.json
```

History requires no host process, overwrites its oldest records, and is lost
on power removal. The reader reports overwrites and incomplete queries and does
not start recording or inject keys. History queries are refused during raw
recording to preserve stream ordering.

Archive overlapping snapshots during a longer session:

```sh
python3 scripts/watch_hid_log.py --port /dev/ttyACM0 \
  --output-dir .calibration/history/example --duration 3600
python3 scripts/analyze_corrections.py --history-dir .calibration/history/example \
  --output .calibration/history-corrections.json
```

The collector polls once per second by default, pins the selected board's USB
serial identity across reconnects, and releases the port between queries. Use a
new output directory. Stop with Ctrl-C or a `stop-request` file in that directory.
The analyzer deduplicates overlapping records and retains recovered contiguous
input across failed polls; actual gaps, restarts and source/device-state changes
break editing context.

`analyze_corrections.py --session SESSION --output REPORT.json` instead analyzes
saved device events and ordered USB reports when available. It does not rerun
the current recognizer and present that as historical output. Possible
character/deletion/replacement sequences are inferred intent, not confirmed
labels. Multiple deletions, navigation, modified Backspace, diagnostics and
unknown editing context limit pairing. The device cannot observe focus changes,
editing from another keyboard or whether an application accepted text. No
automatic remapping or threshold adaptation is enabled.

## USB-output verification

To test actual USB reports and Linux key transitions independently of touch
recognition:

```sh
python3 scripts/verify_hid_device.py --port /dev/ttyACM0 \
  --output .calibration/hid-verification.json
```

The verifier needs read access to matching hidraw and input-event nodes and
read/write access to CDC. It discovers the matching devices, takes an exclusive
evdev keyboard grab, then sends diagnostic actions through the real mapping,
encoder and USB queue. It verifies key/modifier presses and releases and checks
for extra or held keys before releasing the grab. Preflight failures are saved
without sending diagnostic keys. `--hidraw` and `--evdev` can select explicit
matching nodes.

These checks exercise output delivery, one-shot Shift, Caps Lock handling and
release behavior. They bypass touch recognition and do not measure physical
typing accuracy. Likewise, replay parity demonstrates reproduction of device
decisions, including recognition errors. Synthetic and development regressions
do not establish held-out accuracy or typing speed. The latest small-circle and
question-mark tolerances still need physical evaluation on other boards/users.

## CDC protocol reference

Commands are newline-terminated ASCII. Replies use the CRC-protected SWP1
framing decoded by [scripts/capture_protocol.py](scripts/capture_protocol.py).
Packet types are metadata (1), sensor samples (2), marker/diagnostic
acknowledgements (3), gesture/reset/checkpoint events (4), and HID history (5).

| Command | Effect |
| --- | --- |
| `STATUS` | Report firmware/source identity, acquisition settings and HID/drop counters. |
| `HELLO` | Enable raw samples and device-event streaming without resetting recognition. |
| `STOP` | Stop streaming, drain its bounded queued prefix, and return final metadata. |
| `MARK token` | Acknowledge a marker with device time and scan identity; capture-start markers request a later idle checkpoint. |
| `HIDLOG token after_seq` | Retrieve the bounded completion suffix and summary; refused during raw streaming. |
| `HID token grid gesture direction` | Inject a mapped diagnostic action through the normal output path. |
| `HIDCHAR token code` | Inject a diagnostic character code through the output path. |
| `BOOTLOADER` | Enter the ROM bootloader for an explicit application update. |

Use the supplied verifier for `HID`/`HIDCHAR`: those commands produce real
keyboard input. A queued-action acknowledgement is not evidence of USB delivery;
completion records and host reports provide that evidence. Diagnostic loss is
reported separately from acquisition loss. A slow CDC reader must not be used
to infer that acquisition or HID output stopped.
