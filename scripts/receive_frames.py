"""
ESP32 Frame Receiver
====================
Receives raw 96x96 grayscale frames from the ESP32-S3-EYE over serial,
and saves each frame as a PNG image file.

Usage:
    python3 receive_frames.py

Requirements:
    pip3 install opencv-python pyserial numpy
"""

import serial          # Handles USB serial communication with the ESP32
import serial.tools.list_ports  # Used to find which port the ESP32 showed up on
import numpy as np     # Used to reshape raw bytes into a 2D image array
import cv2             # OpenCV — used to save the image array as a PNG file
import os              # Used to create output directories and build file paths
import time            # Used to generate unique timestamps for filenames

# ── Configuration ─────────────────────────────────────────────────────────────

BAUD_RATE   = 115200                   # Must match Serial.begin() in your firmware
IMG_WIDTH   = 96                       # Frame width in pixels — must match FRAMESIZE_96X96
IMG_HEIGHT  = 96                       # Frame height in pixels — must match FRAMESIZE_96X96

CLASS_DIRS = {
    "1": os.path.expanduser("~/Documents/hazard_beacon/dataset/processed/hazard_present2"),
    "2": os.path.expanduser("~/Documents/hazard_beacon/dataset/processed/ambient_noise2"),
}

# ── Find the ESP32's serial port ──────────────────────────────────────────────
# macOS names the port something like /dev/cu.usbmodem101, but the number can
# change between reconnects, so we look it up instead of hardcoding it.


def find_serial_port():
    for port in serial.tools.list_ports.comports():
        if "usbmodem" in port.device or "usbserial" in port.device:
            return port.device
    return None


SERIAL_PORT = find_serial_port()

if SERIAL_PORT is None:
    print("ERROR: No ESP32 serial port found.")
    print("Check that the USB cable is connected and the board is powered on.")
    raise SystemExit(1)

# ── Session prompt ────────────────────────────────────────────────────────────

print("What are you capturing?")
print("  1 — Hazard present (person/animal walking through IR zone)")
print("  2 — Ambient noise  (empty scene, nothing in IR zone)")
choice = input("Enter 1 or 2: ").strip()

while choice not in CLASS_DIRS:
    choice = input("Invalid choice. Enter 1 or 2: ").strip()

OUTPUT_DIR = CLASS_DIRS[choice]
label      = "hazard_present" if choice == "1" else "ambient_noise"

# ── Setup ─────────────────────────────────────────────────────────────────────

os.makedirs(OUTPUT_DIR, exist_ok=True)
print(f"\nCapturing: {label}")
print(f"Saving frames to: {OUTPUT_DIR}")

# Open the serial connection to the ESP32
# timeout=5 means if no data arrives in 5 seconds, stop waiting and move on
ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=5)
print(f"Connected to {SERIAL_PORT} at {BAUD_RATE} baud")
print(f"Waiting for frames... (press Ctrl+C to stop)\n")

# ── Frame Capture Loop ────────────────────────────────────────────────────────

frame_count = 0   # Track how many frames we've successfully saved

end_time = time.time()+(30*60)

while (time.time() <= end_time):

    # Read one line of text from serial and decode it from bytes to a string
    # strip() removes the trailing newline character (\n) at the end
    line = ser.readline().decode("utf-8", errors="ignore").strip()

    # Check if this line is the start marker sent by the ESP32
    if line.startswith("FRAME_START:"):
        parts = line.split(":")
        frame_bytes = int(parts[1])

        # Read exactly FRAME_BYTES (9216) raw bytes — this is the pixel data
        raw = ser.read(frame_bytes)

        # Read the next line — it should be FRAME_END confirming the frame is complete
        #end_marker = ser.readline().decode("utf-8", errors="ignore").strip()

        # Verify we got the right number of bytes and the correct end marker
        if len(raw) == frame_bytes:

            # Convert the raw bytes into a numpy array of unsigned 8-bit integers
            # Each value is one pixel brightness: 0 = black, 255 = white
            arr = np.frombuffer(raw, dtype=np.uint8)

            # Reshape the flat 1D array of 9216 values into a 2D 96x96 grid
            img = arr.reshape((IMG_HEIGHT, IMG_WIDTH))

            # Build a unique filename using the current timestamp
            timestamp = int(time.time() * 1000)   # Milliseconds since epoch
            filename  = f"frame_{timestamp}.png"
            filepath  = os.path.join(OUTPUT_DIR, filename)

            # Save the image as a PNG file using OpenCV
            cv2.imwrite(filepath, img)

            frame_count += 1   # Increment our counter
            print(f"[{frame_count}] Saved: {filename}")

        else:
            # Something went wrong — wrong byte count or missing end marker
            print(f"WARNING: Bad frame — got {len(raw)} bytes")

# ── Done ──────────────────────────────────────────────────────────────────────

ser.close()   # Close the serial connection cleanly when done
print(f"\nDone! {frame_count} frames saved to {OUTPUT_DIR}")
print("Open Finder and navigate to that folder to view the captured images.")
