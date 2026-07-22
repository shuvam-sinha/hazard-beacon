#!/usr/bin/env python3
"""
Validate the model on the ESP32 by sending labelled images over serial and
checking the predictions. The ESP32 must be running the TEST MODE firmware
(main.cpp with the test-mode loop active).

Protocol (defined in main.cpp):
  1. ESP32 prints TEST_MODE_READY every 2s while idle
  2. Python sends: TEST_IMAGE:<true_label>:<num_bytes>\n
  3. ESP32 replies: HEADER_OK
  4. Python sends image bytes in 64-byte chunks; ESP32 replies ACK after each
  5. ESP32 replies: RESULT:<predicted_label>:<score>

Usage:
    python scripts/test_exported_model.py
    python scripts/test_exported_model.py --port /dev/cu.usbmodem1101 --samples 20
"""

import argparse
import os
import random
import sys
import time

import serial
import serial.tools.list_ports
from PIL import Image

DATASET_DIR  = os.path.join(os.path.dirname(__file__), "../dataset/processed")
CLASSES      = ["hazard_present", "ambient_noise"]
IMG_W, IMG_H = 96, 96
CHUNK_SIZE   = 64


def find_port():
    for p in serial.tools.list_ports.comports():
        if any(x in p.device for x in ("usbmodem", "usbserial", "SLAB")):
            return p.device
    ports = list(serial.tools.list_ports.comports())
    return ports[0].device if ports else None


def load_image_bytes(path):
    img = Image.open(path).convert("L").resize((IMG_W, IMG_H))
    return bytes(img.tobytes())


def collect_samples(per_class):
    samples = []
    for label in CLASSES:
        folder = os.path.join(DATASET_DIR, label)
        if not os.path.isdir(folder):
            print(f"ERROR: folder not found: {folder}")
            sys.exit(1)
        paths = [
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.lower().endswith(".png")
        ]
        random.shuffle(paths)
        samples.extend((p, label) for p in paths[:per_class])
    random.shuffle(samples)
    return samples


def wait_for_ready(ser, timeout=30):
    """Block until the ESP32 prints TEST_MODE_READY.
    30s covers a full reboot cycle (camera init can take ~8s after a crash).
    No buffer flush here — reset_input_buffer() disrupts the USB-CDC write
    endpoint on macOS and silently breaks all subsequent ser.write() calls."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if line == "TEST_MODE_READY":
            return True
    return False


def run_one(ser, path, true_label):
    """Send one image, return (predicted, score, correct).

    No pre-image sync — send the header directly.  Calling wait_for_ready()
    before each write disrupts the USB-CDC write path on macOS.  Sync only
    happens at startup and after a crash recovery (caller's responsibility)."""
    raw = load_image_bytes(path)

    ser.write(f"TEST_IMAGE:{true_label}:{len(raw)}\n".encode())
    ser.flush()

    # Wait for HEADER_OK (skip unrecognised lines like TEST_MODE_READY)
    deadline = time.time() + 10
    while time.time() < deadline:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if line == "HEADER_OK":
            break
    else:
        return "timeout_header", 0.0, False

    # Send image in 64-byte chunks, ACK-gated
    for offset in range(0, len(raw), CHUNK_SIZE):
        ser.write(raw[offset : offset + CHUNK_SIZE])
        ser.flush()
        deadline = time.time() + 10
        while time.time() < deadline:
            ack = ser.readline().decode("utf-8", errors="replace").strip()
            if ack == "ACK":
                break
            if ack.startswith("RESULT:"):
                print(f"    [dbg] got {ack!r} while waiting for ACK at offset {offset}")
                return "fw_error", 0.0, False
        else:
            return "timeout_ack", 0.0, False

    # Wait for RESULT:<label>:<score>
    deadline = time.time() + 20
    while time.time() < deadline:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if line.startswith("RESULT:"):
            parts = line.split(":")
            if len(parts) >= 3:
                predicted = parts[1]
                score     = float(parts[2])
                return predicted, score, predicted == true_label

    return "timeout_result", 0.0, False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port",    default=None)
    parser.add_argument("--baud",    type=int, default=115200)
    parser.add_argument("--samples", type=int, default=20,
                        help="Total images to test, split evenly per class (default: 20)")
    args = parser.parse_args()

    port = args.port or find_port()
    if not port:
        print("ERROR: no serial port found. Specify with --port /dev/cu.usbmodemXXXX")
        sys.exit(1)

    per_class = args.samples // 2
    samples   = collect_samples(per_class)
    print(f"Connecting to {port} at {args.baud} baud...")
    print(f"Testing {len(samples)} images ({per_class} per class)\n")

    with serial.Serial(port, args.baud, timeout=5) as ser:
        print("Waiting for ESP32 (up to 30s)...")
        deadline = time.time() + 30
        while time.time() < deadline:
            line = ser.readline().decode("utf-8", errors="replace").strip()
            if line == "TEST_MODE_READY":
                break
            if line:
                print(f"  [{line}]")
        else:
            print("ERROR: ESP32 did not print TEST_MODE_READY within 30s.")
            sys.exit(1)

        print("ESP32 ready.\n")

        results = []
        for i, (path, true_label) in enumerate(samples):
            predicted, score, correct = run_one(ser, path, true_label)
            results.append((true_label, predicted, score, correct))
            if "timeout" in predicted or predicted == "no_sync":
                # ESP32 likely crashed — wait for it to reboot and re-sync
                print("    [recovering — waiting up to 30s for ESP32 reboot]")
                time.sleep(2)
                if not wait_for_ready(ser, timeout=30):
                    print("    [ESP32 did not recover — stopping]")
                    break

            status = "OK   " if correct else "WRONG"
            print(
                f"[{i + 1:3}/{len(samples)}]  {status}  "
                f"true={true_label:15}  pred={predicted:15}  score={score:.2f}"
            )

    if not results:
        print("No results collected.")
        sys.exit(1)

    total_correct = sum(c for *_, c in results)
    accuracy = total_correct / len(results) * 100
    print(f"\n{'=' * 60}")
    print(f"Overall accuracy: {total_correct}/{len(results)} = {accuracy:.1f}%")
    for label in CLASSES:
        class_results = [(p, s, c) for t, p, s, c in results if t == label]
        class_correct = sum(c for _, _, c in class_results)
        print(f"  {label}: {class_correct}/{len(class_results)}")
    print(f"{'=' * 60}")
    print("\nNote: includes training images, not just the held-out test set.")


if __name__ == "__main__":
    main()
