"""
Dataset Augmentation Script
=============================
Expands real ESP32 captures by applying random transformations to each image.
Augmented images are saved alongside originals in the same class folder.

Transformations applied per image:
  - Horizontal flip
  - Brightness jitter ±30%
  - Gaussian noise
  - Random crop + resize back to 96x96

Usage:
    python augment_dataset.py

Requirements:
    pip install opencv-python numpy
"""

import cv2
import numpy as np
import os
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

PROCESSED_DIR   = Path("~/Documents/hazard_beacon/dataset/processed").expanduser()
CLASS_FOLDERS   = ["hazard_present", "ambient_noise"]
AUGMENTS_PER_IMAGE = 5       # how many augmented copies to generate per original
TARGET_SIZE        = (96, 96)

# Only augment images captured by the ESP32 (PNGs with frame_ prefix)
ESP32_PREFIX = "frame_"


# ── Augmentation functions ────────────────────────────────────────────────────

def horizontal_flip(img):
    return cv2.flip(img, 1)


def brightness_jitter(img):
    factor = np.random.uniform(0.8, 1.2)  # ±20%
    out = np.clip(img.astype(np.float32) * factor, 0, 255).astype(np.uint8)
    return out


def gaussian_noise(img):
    noise = np.random.normal(0, 8, img.shape).astype(np.float32)
    out = np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    return out


def random_crop(img):
    h, w = img.shape
    max_offset = 8  # pixels to crop from each side
    top    = np.random.randint(0, max_offset)
    left   = np.random.randint(0, max_offset)
    bottom = np.random.randint(0, max_offset)
    right  = np.random.randint(0, max_offset)
    cropped = img[top:h-bottom-1, left:w-right-1]
    return cv2.resize(cropped, TARGET_SIZE, interpolation=cv2.INTER_AREA)


def augment(img):
    """Apply a random combination of transformations to one image."""
    if np.random.rand() > 0.5:
        img = horizontal_flip(img)
    img = brightness_jitter(img)
    img = gaussian_noise(img)
    img = random_crop(img)
    return img


# ── Process each class folder ─────────────────────────────────────────────────

for class_name in CLASS_FOLDERS:
    folder = PROCESSED_DIR / class_name

    if not folder.exists():
        print(f"Skipping {class_name} — folder not found")
        continue

    # Only augment ESP32 frames, not downloaded dataset images
    source_images = [f for f in folder.iterdir()
                     if f.name.startswith(ESP32_PREFIX) and f.suffix == ".png"]

    if not source_images:
        print(f"No ESP32 frames found in {class_name} — skipping")
        continue

    print(f"\nAugmenting {class_name}: {len(source_images)} source images x {AUGMENTS_PER_IMAGE} = {len(source_images) * AUGMENTS_PER_IMAGE} new images ...")

    generated = 0

    for img_path in source_images:
        img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue

        for i in range(AUGMENTS_PER_IMAGE):
            aug = augment(img)
            out_name = f"{img_path.stem}_aug{i}.png"
            out_path = folder / out_name
            cv2.imwrite(str(out_path), aug)
            generated += 1

    print(f"  Done — {generated} augmented images saved to {folder}")

print("\nAugmentation complete.")
