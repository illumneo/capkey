#!/usr/bin/env python3
"""Read passive, bounded HID completion history. Does not start/stop recording."""
import argparse
import json
import math
from dataclasses import dataclass, field
import time
import uuid
from pathlib import Path
from capture_protocol import StreamDecoder


def validate_query(records, summary, after):
    completions = [r for r in records if r["event"] == "completion"]
    if len(completions) != summary["returned"]:
        raise ValueError("returned-record count mismatch")
    if summary["after_seq"] != after:
        raise ValueError("query cursor mismatch")
    if any(r["boot_id"] != summary["boot_id"] for r in completions):
        raise ValueError("query crossed a device boot")
    sequences = [r["completion_seq"] for r in completions]
    if any(a >= b for a, b in zip(sequences, sequences[1:])):
        raise ValueError("completion sequence regressed or duplicated")
    first = max(after + 1, summary["oldest_seq"])
    if any(not first <= seq <= summary["latest_seq"] for seq in sequences):
        raise ValueError("completion outside query snapshot bounds")
    expected = max(0, summary["latest_seq"] - first + 1)
    if len(completions) + summary["missing_during_query"] != expected:
        raise ValueError("unreported gap inside query snapshot")


@dataclass
class QueryResult:
    records: list = field(default_factory=list)
    summary: dict | None = None
    status: str = "incomplete"
    error: str | None = None
    decoder: dict = field(default_factory=dict)
    interrupted: bool = False


def query_hid_log(port_name, after=0, timeout=8, *, serial_factory=None,
                  clock=time.monotonic, stop_requested=lambda: False):
    """One passive query; errors retain partial records and always close the port."""
    if type(after) is not int or not 0 <= after <= 0xffffffffffffffff:
        raise ValueError("after must be an unsigned 64-bit integer")
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive and finite")
    result = QueryResult()
    decoder = StreamDecoder()
    port = None
    token = "hidlog-" + uuid.uuid4().hex
    deadline = clock() + timeout
    try:
        if stop_requested():
            result.error = "stop requested"
            result.interrupted = True
            return result
        if serial_factory is None:
            import serial
            serial_factory = serial.Serial
        port = serial_factory(port=None, baudrate=115200, timeout=min(.1, timeout),
                              write_timeout=min(1, timeout), exclusive=True)
        # Set line states before opening, matching the other CapKey tools.
        port.dtr = True
        port.rts = False
        port.port = port_name
        port.open()
        command = f"HIDLOG {token} {after}\n".encode()
        if port.write(command) != len(command):
            raise OSError("short HIDLOG command write")
        while clock() < deadline and result.summary is None:
            if stop_requested():
                result.error = "stop requested"
                result.interrupted = True
                break
            for record in decoder.feed(port.read(max(1, port.in_waiting))):
                if record.get("type") == "hid_log" and record.get("token") == token:
                    result.records.append(record)
                    if record["event"] == "summary": result.summary = record
        if result.summary is None:
            result.error = result.error or "query timed out before a final summary"
        elif result.summary["error"]:
            result.status = "refused"
            result.error = result.summary["error"]
        else:
            validate_query(result.records, result.summary, after)
            result.status = "complete"
    except KeyboardInterrupt:
        result.error = "keyboard interrupt"
        result.interrupted = True
    except Exception as exc:
        result.status = "incomplete" if result.records else "error"
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        if port is not None:
            try:
                port.close()
            except Exception as exc:
                result.error = result.error or f"port close failed: {exc}"
                if result.status == "complete": result.status = "error"
        decoder.finish()
        result.decoder = decoder.status()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--after", type=int, default=0, help="Cursor valid only for the same boot_id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 0 <= args.after <= 0xffffffffffffffff:
        parser.error("--after must be an unsigned 64-bit integer")
    if args.output.exists():
        parser.error("output already exists")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = query_hid_log(args.port, args.after)
    with args.output.open("x") as output:
        output.write("".join(json.dumps(record) + "\n" for record in result.records))
    if result.status != "complete":
        raise SystemExit(f"Query {result.status}: {result.error}; partial records saved")
    print(json.dumps(result.summary, indent=2))


if __name__ == "__main__":
    main()
