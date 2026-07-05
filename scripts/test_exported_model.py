#!/usr/bin/env python3
"""
Validates the exported Edge Impulse model by sending labelled images from
dataset/processed/ to the ESP32 over serial and checking the predictions.

The ESP32 must be flashed with the TEST MODE firmware (main.cpp with the
test mode loop active). It will print TEST_MODE_READY on boot, then wait
for images one at a time.

Usage:
    python scripts/test_exported_model.py
    python scripts/test_exported_model.py --port /dev/cu.usbmodem1101 --samples 100
"""

import argparse
import os
import random
import sys
import time

import serial
import serial.tools.list_ports
from PIL import Image

# Folder containing the two class subdirectories
PROCESSED_DIR = os.path.join(os.path.dirname(__file__), "../dataset/processed")

# Must match EI_CLASSIFIER_INPUT_WIDTH / HEIGHT in the firmware
IMG_WIDTH  = 96
IMG_HEIGHT = 96
IMG_BYTES  = IMG_WIDTH * IMG_HEIGHT  # 9216 bytes per image

# Maps class label → subfolder name
CLASSES = {
    "hazard_present": "hazard_present",
    "ambient_noise":  "ambient_noise",
}


def find_port():
    """Auto-detect the ESP32's serial port."""
    ports = list(serial.tools.list_ports.comports())
    for p in ports:
        if "usbmodem" in p.device or "usbserial" in p.device or "SLAB" in p.device:
            return p.device
    if ports:
        return ports[0].device
    return None


def load_image_bytes(path):
    """
    Open an image, convert it to 96×96 grayscale, and return raw pixel bytes.
    Grayscale ('L') means one byte per pixel, matching what the camera produces.
    """
    img = Image.open(path).convert("L").resize((IMG_WIDTH, IMG_HEIGHT))
    return img.tobytes()


def collect_samples(per_class):
    """
    Randomly sample up to per_class images from each class folder.
    Returns a shuffled list of (path, true_label) tuples.
    """
    samples = []
    for label, folder_name in CLASSES.items():
        folder = os.path.join(PROCESSED_DIR, folder_name)
        if not os.path.isdir(folder):
            print(f"ERROR: folder not found: {folder}")
            sys.exit(1)

        # Get all PNG paths in this folder
        paths = [
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.lower().endswith(".png")
        ]

        # Randomly pick up to per_class images
        random.shuffle(paths)
        samples += [(p, label) for p in paths[:per_class]]

    random.shuffle(samples)
    return samples


def send_and_classify(ser, path, true_label):
    """
    Send one image to the ESP32 and read back the prediction.
    Returns (predicted_label, confidence_score, is_correct).
    """
    raw = load_image_bytes(path)

    # Send the header so the firmware knows what's coming
    # Format: TEST_IMAGE:<true_label>:<num_bytes>
    header = f"TEST_IMAGE:{true_label}:{len(raw)}\n"
    ser.write(header.encode())

    # Wait for the firmware to acknowledge the header before sending image bytes.
    # This confirms the firmware parsed the header correctly and is ready.
    deadline = time.time() + 5
    header_acked = False
    while time.time() < deadline:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if line == "HEADER_OK":
            header_acked = True
            break
    if not header_acked:
        return "timeout", 0.0, False

    # Send image bytes in 64-byte chunks, waiting for an ACK after each one.
    # The firmware only sends ACK once it has safely read the chunk into its
    # buffer, so this guarantees no bytes are dropped regardless of UART speed.
    chunk_size = 64
    for i in range(0, len(raw), chunk_size):
        ser.write(raw[i:i + chunk_size])
        ser.flush()

        # Wait for ACK before sending next chunk
        ack_deadline = time.time() + 5
        while time.time() < ack_deadline:
            ack = ser.readline().decode("utf-8", errors="replace").strip()
            if ack == "ACK":
                break
        else:
            return "timeout", 0.0, False

    # All chunks sent — wait for the classifier result
    # Format: RESULT:<predicted_label>:<score>
    deadline = time.time() + 15
    while time.time() < deadline:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if line.startswith("RESULT:"):
            parts = line.split(":")
            if len(parts) >= 3:
                predicted = parts[1]
                score     = float(parts[2])
                correct   = (predicted == true_label)
                return predicted, score, correct

    # Timed out waiting for result
    return "timeout", 0.0, False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port",    default=None,
                        help="Serial port (auto-detected if not specified)")
    parser.add_argument("--baud",    type=int, default=115200)
    parser.add_argument("--samples", type=int, default=1,
                        help="Total images to test, split evenly between classes (default: 1)")
    args = parser.parse_args()

    port = args.port or find_port()
    if not port:
        print("ERROR: No serial port found. Specify with --port /dev/cu.usbmodemXXXX")
        sys.exit(1)

    # Collect samples — split evenly across classes
    per_class = args.samples // 2
    samples   = collect_samples(per_class)

    print(f"Connecting to {port} at {args.baud} baud...")
    print(f"Testing {len(samples)} images ({per_class} per class)\n")

    with serial.Serial(port, args.baud, timeout=5) as ser:
        # Read from the moment we connect — TEST_MODE_READY is printed during boot
        # so we must not sleep or drain the buffer before listening.
        deadline = time.time() + 30
        ready = False
        while time.time() < deadline:
            line = ser.readline().decode("utf-8", errors="replace").strip()
            if line == "TEST_MODE_READY":
                ready = True
                break
            # Print other startup lines (WiFi status, PSRAM info, etc.)
            if line:
                print(f"  [{line}]")

        if not ready:
            print("ERROR: ESP32 did not print TEST_MODE_READY.")
            print("Make sure the TEST MODE firmware is flashed and the device just booted.")
            sys.exit(1)

        print("ESP32 ready. Sending images...\n")

        # ── Run inference on each image ───────────────────────────────────────
        total_correct = 0
        results = []

        for i, (path, true_label) in enumerate(samples):
            predicted, score, correct = send_and_classify(ser, path, true_label)
            total_correct += correct
            results.append((true_label, predicted, score, correct))

            status = "OK   " if correct else "WRONG"
            print(f"[{i+1:3}/{len(samples)}]  {status}  "
                  f"true={true_label:15}  pred={predicted:15}  score={score:.2f}")

        # ── Summary ───────────────────────────────────────────────────────────
        accuracy = total_correct / len(samples) * 100
        print(f"\n{'='*60}")
        print(f"Overall accuracy: {total_correct}/{len(samples)} = {accuracy:.1f}%")

        # Per-class breakdown
        for label in CLASSES:
            class_results = [(p, s, c) for (t, p, s, c) in results if t == label]
            class_correct = sum(c for (_, _, c) in class_results)
            print(f"  {label}: {class_correct}/{len(class_results)}")

        print(f"{'='*60}")
        print("\nNote: this may include training images (not just the held-out test set),")
        print("so accuracy may be slightly higher than Edge Impulse's Model Testing figure.")


if __name__ == "__main__":
    main()
