#!/usr/bin/env python3
"""Update the application through CapKey CDC, preserving its partition table."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

import serial
from serial.tools import list_ports


def ports(pid):
    return [p for p in list_ports.comports() if p.vid == 0x303A and p.pid in pid]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, default=Path(__file__).resolve().parents[1] / "build/swipe.bin")
    parser.add_argument("--port", help="CapKey CDC or ROM serial port; auto-detected when unique")
    python_env = os.environ.get("IDF_PYTHON_ENV_PATH")
    parser.add_argument("--esptool-python", default=str(Path(python_env) / "bin/python") if python_env else sys.executable)
    args = parser.parse_args()
    image = args.image.resolve()
    data = image.read_bytes()
    if not data or data[0] != 0xE9 or len(data) > 0x100000:
        parser.error("Expected an ESP application image fitting the existing 1 MiB factory partition")
    candidates = ports({0x4004, 0x1001, 0x0002})
    selected = [p for p in candidates if not args.port or p.device == args.port]
    if len(selected) != 1:
        parser.error("Select one CapKey/ESP ROM device with --port; found " + repr([p.device for p in selected]))
    device = selected[0]
    bootloader_requested = device.pid == 0x4004
    if bootloader_requested:
        connection = serial.Serial(port=None, baudrate=115200, timeout=.2, write_timeout=2)
        connection.dtr = True
        connection.rts = False
        connection.port = device.device
        connection.open()
        try:
            connection.write(b"BOOTLOADER\n")
            connection.flush()
        finally:
            connection.close()
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            boot = ports({0x1001, 0x0002})
            # Match physical USB path across firmware's change of serial ID.
            same = [p for p in boot if p.location == device.location]
            if len(same) == 1:
                device = same[0]
                break
            time.sleep(.1)
        else:
            raise RuntimeError("CapKey did not re-enumerate in its ROM bootloader")
    command = [args.esptool_python, "-B", "-m", "esptool", "--chip", "esp32s3",
               # USB Serial/JTAG reset also releases DTR/BOOT. Opening the ROM
               # port with no_reset can leave BOOT asserted after the write.
               "--port", device.device, "--before", "usb_reset" if device.pid == 0x1001 else "no_reset",
               "--after", "hard_reset", "--connect-attempts", "2", "--baud", "460800",
               "write_flash", "--flash_mode", "keep", "--flash_freq", "keep",
               "--flash_size", "keep", "0x10000", str(image)]
    subprocess.run(command, check=True, timeout=60)
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        keyboard = [p for p in ports({0x4004}) if p.location == device.location]
        if len(keyboard) == 1:
            print("CapKey keyboard running on " + keyboard[0].device)
            return
        time.sleep(.1)
    raise RuntimeError("Flash verified, but CapKey did not return as a USB keyboard")


if __name__ == "__main__":
    main()
