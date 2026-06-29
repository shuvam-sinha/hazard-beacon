#!/usr/bin/env python3
"""
Listens on serial, prints inference results, and saves each frame as a PNG.
Filenames include timestamp, label, and confidence score.

Usage:
    python scripts/save_captures.py
    python scripts/save_captures.py --port /dev/cu.usbmodem1101 --baud 115200
"""

import argparse
import os
import struct
import sys
from datetime import datetime

import serial
import serial.tools.list_ports
from PIL import Image

SAVE_DIR = os.path.join(os.path.dirname(__file__), "../dataset/raw/live_captures")
IMG_WIDTH  = 96
IMG_HEIGHT = 96


def find_port():
    ports = list(serial.tools.list_ports.comports())
    for p in ports:
        if "usbmodem" in p.device or "usbserial" in p.device or "SLAB" in p.device:
            return p.device
    if ports:
        return ports[0].device
    return None


def save_frame(raw_bytes, label, score):
    os.makedirs(SAVE_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    filename = f"{ts}_{label}_{score:.2f}.png"
    path = os.path.join(SAVE_DIR, filename)
    img = Image.frombytes("L", (IMG_WIDTH, IMG_HEIGHT), raw_bytes)
    img.save(path)
    print(f"  → saved {filename}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default=None)
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args()

    port = args.port or find_port()
    if not port:
        print("ERROR: No serial port found. Specify with --port /dev/cu.usbmodemXXXX")
        sys.exit(1)

    print(f"Connecting to {port} at {args.baud} baud...")
    print(f"Saving frames to {os.path.abspath(SAVE_DIR)}/")
    print("Press Ctrl+C to stop.\n")

    with serial.Serial(port, args.baud, timeout=10) as ser:
        while True:
            line = ser.readline().decode("utf-8", errors="replace").strip()
            if not line:
                continue

            if line.startswith("FRAME_START:"):
                # Header format: FRAME_START:<bytes>:<label>:<score>
                try:
                    _, num_bytes, label, score_str = line.split(":")
                    num_bytes = int(num_bytes)
                    score = float(score_str)
                except ValueError:
                    print(f"  [bad header] {line}")
                    continue

                raw = b""
                while len(raw) < num_bytes:
                    chunk = ser.read(num_bytes - len(raw))
                    if not chunk:
                        print("  [timeout reading frame]")
                        break
                    raw += chunk

                if len(raw) == num_bytes:
                    save_frame(raw, label, score)
            else:
                print(line)


if __name__ == "__main__":
    main()
