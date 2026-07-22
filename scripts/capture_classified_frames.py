#!/usr/bin/env python3
"""
Debug tool: save the exact 96x96 grayscale frames the on-device classifier
receives, tagged with its decision and both class scores.

The firmware (main.cpp, with DUMP_FRAMES=1) streams each classified frame as:
    FRAME_START:<num_bytes>:<decision>:<hazard_score>:<ambient_score>\n
    <num_bytes raw grayscale pixel bytes>

Each frame is written to a PNG so you can see what the model actually saw when
it reported e.g. 100% hazard on a scene you never changed. Filenames sort by
time and carry the decision + scores, e.g.:
    20260711_143022_501_hazard_h1.00_a0.00.png

Usage:
    python scripts/capture_classified_frames.py
    python scripts/capture_classified_frames.py --port /dev/cu.usbmodem1101
    python scripts/capture_classified_frames.py --out debug_captures --scale 4

Requirements:
    pip3 install pyserial pillow
"""

import argparse
import os
import sys
from datetime import datetime

import serial
import serial.tools.list_ports
from PIL import Image

IMG_WIDTH = 96
IMG_HEIGHT = 96
DEFAULT_OUT = os.path.join(os.path.dirname(__file__), "..", "debug_captures")


def find_port():
    ports = list(serial.tools.list_ports.comports())
    for p in ports:
        if "usbmodem" in p.device or "usbserial" in p.device or "SLAB" in p.device:
            return p.device
    return ports[0].device if ports else None


def read_exact(ser, n):
    """Read exactly n bytes, or fewer if the serial read times out."""
    buf = bytearray()
    while len(buf) < n:
        chunk = ser.read(n - len(buf))
        if not chunk:
            break  # timeout
        buf += chunk
    return bytes(buf)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=None, help="serial port (auto-detected if omitted)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--out", default=DEFAULT_OUT, help="directory to save frames into")
    ap.add_argument("--scale", type=int, default=1,
                    help="upscale factor for saved PNGs (nearest-neighbour, for easier viewing)")
    args = ap.parse_args()

    port = args.port or find_port()
    if not port:
        print("ERROR: no serial port found. Pass --port /dev/cu.usbmodemXXXX")
        sys.exit(1)

    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)

    print(f"Connecting to {port} at {args.baud} baud...")
    print(f"Saving classified frames to {out_dir}/")
    print("Press Ctrl+C to stop.\n")

    expected = IMG_WIDTH * IMG_HEIGHT
    count = 0

    with serial.Serial(port, args.baud, timeout=10) as ser:
        while True:
            line = ser.readline().decode("utf-8", errors="replace").strip()
            if not line:
                continue

            if not line.startswith("FRAME_START:"):
                print(line)  # pass through [Inference] lines, boot logs, etc.
                continue

            # Header: FRAME_START:<num_bytes>:<decision>:<hazard>:<ambient>
            parts = line.split(":")
            if len(parts) != 5:
                print(f"  [bad header] {line}")
                continue
            try:
                num_bytes = int(parts[1])
                decision = parts[2]
                hazard = float(parts[3])
                ambient = float(parts[4])
            except ValueError:
                print(f"  [bad header] {line}")
                continue

            raw = read_exact(ser, num_bytes)
            if len(raw) != num_bytes:
                print(f"  [timeout] got {len(raw)}/{num_bytes} bytes, skipping")
                continue
            if num_bytes != expected:
                print(f"  [size mismatch] header says {num_bytes}, expected {expected}")

            img = Image.frombytes("L", (IMG_WIDTH, IMG_HEIGHT), raw[:expected])
            if args.scale > 1:
                img = img.resize((IMG_WIDTH * args.scale, IMG_HEIGHT * args.scale), Image.NEAREST)

            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            fname = f"{ts}_{decision}_h{hazard:.2f}_a{ambient:.2f}.png"
            img.save(os.path.join(out_dir, fname))
            count += 1
            print(f"  -> [{count}] {decision:6s} hazard={hazard:.2f} ambient={ambient:.2f}  saved {fname}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
