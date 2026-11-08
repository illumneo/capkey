#!/usr/bin/env python3
"""Bounded passive CapKey history collection. Sends only HIDLOG queries."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
from read_hid_log import QueryResult, query_hid_log

CAPKEY_VID, CAPKEY_PID = 0x303a, 0x4004
DEFAULT_SERIAL = None


def find_capkey(requested_port=None, expected_serial=DEFAULT_SERIAL, *, ports=None):
    """Resolve one CapKey CDC interface; never follow ttyACM reuse to another board."""
    if ports is None:
        from serial.tools import list_ports
        ports = list_ports.comports()
    matches = []
    for port in ports:
        if (port.vid, port.pid) != (CAPKEY_VID, CAPKEY_PID) or not port.serial_number:
            continue
        if expected_serial is not None:
            if port.serial_number.upper() != expected_serial.upper(): continue
        elif requested_port is not None:
            if Path(port.device).resolve() != Path(requested_port).resolve(): continue
        matches.append(port)
    if len(matches) != 1:
        raise RuntimeError(f"Expected one matching CapKey CDC interface; found {len(matches)}")
    port = matches[0]
    return dict(vid=port.vid, pid=port.pid, serial_number=port.serial_number.upper(),
                device=port.device, location=port.location)


def bounds(duration, interval):
    if (isinstance(duration, bool) or not isinstance(duration, (int, float)) or
            not math.isfinite(duration) or not 0 < duration <= 86400):
        raise ValueError("duration must be finite and in (0, 86400] seconds")
    if (isinstance(interval, bool) or not isinstance(interval, (int, float)) or
            not math.isfinite(interval) or not .1 <= interval <= 60):
        raise ValueError("interval must be finite and in [0.1, 60] seconds")


def collect(output_dir, *, port=None, serial_number=DEFAULT_SERIAL, duration=3600,
            interval=1, query=query_hid_log, discover=find_capkey,
            clock=time.monotonic, sleep=time.sleep):
    bounds(duration, interval)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "queries").mkdir()
    stop_file = output_dir / "stop-request"
    started = clock()
    deadline = started + duration
    pinned_serial = None if port else serial_number
    device = None
    previous_boot = None
    seen_latest = {}
    status = dict(state="running", requested_duration_seconds=duration, interval_seconds=interval,
                  queries=0, complete_queries=0, refused_queries=0, incomplete_queries=0,
                  error_queries=0, unique_completions=0, boot_changes=0,
                  unavailable_before_first_poll=0, missing_since_previous_poll=0,
                  polling_after_seq=0, stop_reason=None)

    def write_status():
        status["elapsed_seconds"] = round(max(0, clock() - started), 6)
        temporary = output_dir / "status.json.tmp"
        temporary.write_text(json.dumps(status, indent=2) + "\n")
        temporary.replace(output_dir / "status.json")

    write_status()
    try:
        with (output_dir / "manifest.jsonl").open("x") as manifest:
            while clock() < deadline and not stop_file.exists():
                index = status["queries"] + 1
                attempt_start = clock()
                entry = dict(query_index=index, path=f"queries/{index:06d}.jsonl",
                             started_utc=datetime.now(timezone.utc).isoformat(), after_seq=0)
                try:
                    device = discover(port, pinned_serial)
                    pinned_serial = device["serial_number"]
                    status["device_identity"] = device
                    entry["device_identity"] = device
                    if clock() >= deadline or stop_file.exists():
                        result = QueryResult(error="stop requested", interrupted=True)
                    else:
                        result = query(device["device"], after=0, timeout=min(8, deadline - clock()),
                                       stop_requested=lambda: stop_file.exists() or clock() >= deadline)
                except KeyboardInterrupt:
                    result = QueryResult(error="keyboard interrupt", interrupted=True)
                except Exception as exc:
                    result = QueryResult(status="error", error=f"{type(exc).__name__}: {exc}")
                    if device is not None: entry["last_device_identity"] = device
                entry.update(status=result.status, elapsed_seconds=round(max(0, clock() - attempt_start), 6),
                             error=result.error, decoder=result.decoder)
                with (output_dir / entry["path"]).open("x") as output:
                    output.write("".join(json.dumps(record) + "\n" for record in result.records))
                summary = result.summary
                if summary is not None:
                    for key in ("boot_id", "recognizer_sha256", "oldest_seq", "latest_seq", "overwritten",
                                "overwritten_at_end", "retained", "returned", "lost_before_query",
                                "missing_during_query", "hid_failed", "hid_queue_drops"):
                        entry[key] = summary[key]
                status["queries"] += 1
                status[result.status + "_queries"] += 1
                if result.status == "complete":
                    boot = summary["boot_id"]
                    key = (boot, summary["recognizer_sha256"])
                    previous = seen_latest.get(key)
                    completions = [r for r in result.records if r["event"] == "completion"]
                    new = sum(r["completion_seq"] > (previous or 0) for r in completions)
                    unavailable = max(0, summary["latest_seq"] - (previous or 0) - new)
                    entry.update(new_records=new, duplicate_records=len(completions) - new,
                                 prior_latest_seq=previous, boot_changed=previous_boot is not None and boot != previous_boot)
                    if previous is None:
                        entry["unavailable_before_first_poll"] = unavailable
                        status["unavailable_before_first_poll"] += unavailable
                    else:
                        entry["missing_since_previous_poll"] = unavailable
                        status["missing_since_previous_poll"] += unavailable
                    seen_latest[key] = max(previous or 0, summary["latest_seq"])
                    status["unique_completions"] += new
                    status["boot_changes"] += int(entry["boot_changed"])
                    previous_boot = boot
                manifest.write(json.dumps(entry) + "\n")
                manifest.flush()
                write_status()
                if result.interrupted:
                    status["stop_reason"] = ("keyboard_interrupt" if result.error == "keyboard interrupt"
                                             else "stop_request" if stop_file.exists() else "duration")
                    break
                next_poll = min(deadline, max(attempt_start + interval, clock()))
                while clock() < next_poll and not stop_file.exists():
                    sleep(min(.1, next_poll - clock()))
            if status["stop_reason"] is None:
                status["stop_reason"] = "stop_request" if stop_file.exists() else "duration"
    except KeyboardInterrupt:
        status["stop_reason"] = "keyboard_interrupt"
    finally:
        status["state"] = "stopped"
        write_status()
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory; refuses an existing one")
    parser.add_argument("--port", help="Initial CDC path; its physical serial is pinned before any query")
    parser.add_argument("--serial", default=DEFAULT_SERIAL,
                        help="CapKey serial to follow; otherwise select the only connected CapKey")
    parser.add_argument("--duration", type=float, default=3600)
    parser.add_argument("--interval", type=float, default=1)
    args = parser.parse_args()
    try:
        bounds(args.duration, args.interval)
        if args.output_dir.exists(): parser.error("output directory already exists")
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(collect(args.output_dir, port=args.port, serial_number=args.serial,
                             duration=args.duration, interval=args.interval), indent=2))


if __name__ == "__main__": main()
