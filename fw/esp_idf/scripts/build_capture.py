#!/usr/bin/env python3
"""Build the unified runtime in an isolated directory with an explicit scan setting.

Every image recognizes continuously; HELLO/STOP toggle telemetry at runtime.
The retained legacy diagnostic flag has no behavioral effect.
"""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--charge-times', type=int, default=200,
                        help='Charge/discharge cycles per measurement (50..2000; default: 200; original: 800)')
    args = parser.parse_args()
    if not 50 <= args.charge_times <= 2000:
        parser.error('--charge-times must be in 50..2000')
    root = Path(__file__).resolve().parents[1]
    idf = shutil.which("idf.py")
    if not idf or not os.environ.get("IDF_PATH"):
        raise SystemExit("Activate ESP-IDF first: . ~/esp-idf/export.sh")
    state = root / ".calibration"
    state.mkdir(exist_ok=True)
    config = (root / "sdkconfig").read_text()
    config = re.sub(r"^(?:# )?CONFIG_SWIPE_DIAGNOSTIC_CAPTURE(?:=.*| is not set)$",
                    "", config, flags=re.MULTILINE)
    config += "\nCONFIG_SWIPE_DIAGNOSTIC_CAPTURE=y\n"
    config = re.sub(r"^CONFIG_SWIPE_CAPTURE_CHARGE_TIMES=.*$", "", config, flags=re.MULTILINE)
    config += f"CONFIG_SWIPE_CAPTURE_CHARGE_TIMES={args.charge_times}\n"
    path = state / "sdkconfig.capture"
    # The base file is authoritative. Never edit the original firmware config.
    if not path.exists() or path.read_text() != config:
        path.write_text(config)
    subprocess.run([idf, "-B", str(state / "build-capture"), "-D", f"SDKCONFIG={path}",
                    "build"], cwd=root, check=True)


if __name__ == "__main__":
    main()
