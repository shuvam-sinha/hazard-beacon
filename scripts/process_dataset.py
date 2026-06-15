"""
Dataset Processor
==================
Converts all images in the processed dataset folders to 96x96 grayscale PNGs.
Processes both hazard_present and ambient_noise class folders in place.

Run this after all downloads are complete and after augment_dataset.py.

Usage:
    python process_dataset.py

Requirements:
    pip install opencv-python
"""

import cv2
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

PROCESSED_DIR = Path("~/Documents/hazard_beacon/dataset/processed").expanduser()
TARGET_SIZE   = (96, 96)

CLASS_FOLDERS     = ["hazard_present", "ambient_noise"]
VALID_EXTENSIONS  = {".jpg", ".jpeg", ".png", ".bmp"}

# ── Process each class folder ─────────────────────────────────────────────────

for class_name in CLASS_FOLDERS:
    folder = PROCESSED_DIR / class_name

    if not folder.exists():
        print(f"Skipping {class_name} — folder not found")
        continue

    image_files = [f for f in folder.iterdir() if f.suffix.lower() in VALID_EXTENSIONS]
    print(f"\nProcessing {class_name}: {len(image_files)} images ...")

    success = 0
    skipped = 0
    failed  = 0

    for i, img_path in enumerate(image_files, 1):
        img = cv2.imread(str(img_path))

        if img is None:
            print(f"  FAILED to read: {img_path.name}")
            failed += 1
            continue

        # Skip if already correct format
        h, w = img.shape[:2]
        already_grayscale = len(img.shape) == 2 or img.shape[2] == 1
        already_sized     = (w == TARGET_SIZE[0] and h == TARGET_SIZE[1])
        if already_grayscale and already_sized and img_path.suffix == ".png":
            skipped += 1
            continue

        # Convert to grayscale if needed
        if len(img.shape) == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Resize to 96x96 if needed
        if (w, h) != TARGET_SIZE:
            img = cv2.resize(img, TARGET_SIZE, interpolation=cv2.INTER_AREA)

        # Save as PNG
        out_path = img_path.with_suffix(".png")
        cv2.imwrite(str(out_path), img)

        # Remove original if it was a different format
        if img_path.suffix.lower() != ".png":
            img_path.unlink()

        success += 1
        if i % 100 == 0:
            print(f"  [{i}/{len(image_files)}] processed ...")

    print(f"  Done — {success} converted, {skipped} skipped (already correct), {failed} failed")

print("\nAll folders processed.")
