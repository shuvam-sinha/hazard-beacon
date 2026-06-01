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
import numpy as np     # Used to reshape raw bytes into a 2D image array
import cv2             # OpenCV — used to save the image array as a PNG file
import os              # Used to create output directories and build file paths
import time            # Used to generate unique timestamps for filenames

# ── Configuration ─────────────────────────────────────────────────────────────

SERIAL_PORT   = "/dev/cu.usbmodem1101"   # The port your ESP32 is connected to on Mac
BAUD_RATE     = 115200                   # Must match Serial.begin() in your firmware
IMG_WIDTH     = 96                       # Frame width in pixels — must match FRAMESIZE_96X96
IMG_HEIGHT    = 96                       # Frame height in pixels — must match FRAMESIZE_96X96
FRAME_BYTES   = IMG_WIDTH * IMG_HEIGHT   # Total bytes per frame (9216 for 96x96 grayscale)
MAX_FRAMES    = 50                       # How many frames to capture before stopping
OUTPUT_DIR    = os.path.expanduser(      # Where to save the captured PNG files
    "~/Documents/hazard_beacon/dataset/raw/test_captures"
)

# ── Setup ─────────────────────────────────────────────────────────────────────

# Create the output directory if it doesn't already exist
os.makedirs(OUTPUT_DIR, exist_ok=True)
print(f"Saving frames to: {OUTPUT_DIR}")

# Open the serial connection to the ESP32
# timeout=5 means if no data arrives in 5 seconds, stop waiting and move on
ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=5)
print(f"Connected to {SERIAL_PORT} at {BAUD_RATE} baud")
print(f"Waiting for frames... (capturing {MAX_FRAMES} frames then stopping)\n")

# ── Frame Capture Loop ────────────────────────────────────────────────────────

frame_count = 0   # Track how many frames we've successfully saved

while frame_count < MAX_FRAMES:

    # Read one line of text from serial and decode it from bytes to a string
    # strip() removes the trailing newline character (\n) at the end
    line = ser.readline().decode("utf-8", errors="ignore").strip()

    # Check if this line is the start marker sent by the ESP32
    if line == "FRAME_START":

        # Read exactly FRAME_BYTES (9216) raw bytes — this is the pixel data
        raw = ser.read(FRAME_BYTES)

        # Read the next line — it should be FRAME_END confirming the frame is complete
        end_marker = ser.readline().decode("utf-8", errors="ignore").strip()

        # Verify we got the right number of bytes and the correct end marker
        if len(raw) == FRAME_BYTES and end_marker == "FRAME_END":

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
            print(f"[{frame_count}/{MAX_FRAMES}] Saved: {filename}")

        else:
            # Something went wrong — wrong byte count or missing end marker
            print(f"WARNING: Bad frame — got {len(raw)} bytes, end marker: '{end_marker}' — skipping")

# ── Done ──────────────────────────────────────────────────────────────────────

ser.close()   # Close the serial connection cleanly when done
print(f"\nDone! {frame_count} frames saved to {OUTPUT_DIR}")
print("Open Finder and navigate to that folder to view the captured images.")
