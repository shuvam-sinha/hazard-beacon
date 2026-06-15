"""
iWildCam 2020 - Dataset Filter Script
======================================
Reads iwildcam2020_train_annotations.json and splits image filenames into:
  - hazard_present.txt  → images with animals (category_id != 0)
  - ambient_noise.txt   → empty frames (category_id == 0)

Only nighttime images are kept (19:00–06:00).

Usage:
    python filter_iwildcam.py

Requirements:
    pip install pandas
"""

import json
from pathlib import Path
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────

ANNOTATIONS_FILE = Path("~/Documents/hazard_beacon/dataset/raw/iwildcam/iwildcam2020_train_annotations.json").expanduser()
OUT_DIR          = Path("~/Documents/hazard_beacon/dataset/raw/iwildcam").expanduser()

NIGHT_START = 19  # 7 PM
NIGHT_END   = 6   # 6 AM
EMPTY_CAT   = 0   # category_id 0 = empty frame


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_nighttime(datetime_str):
    try:
        dt = datetime.strptime(datetime_str.strip(), "%Y-%m-%d %H:%M:%S.%f")
        h = dt.hour
        return h >= NIGHT_START or h < NIGHT_END  # wraps midnight
    except Exception:
        return False


# ── Load JSON ─────────────────────────────────────────────────────────────────

print(f"Loading {ANNOTATIONS_FILE} ...")
with open(ANNOTATIONS_FILE) as f:
    data = json.load(f)

images      = data["images"]
annotations = data["annotations"]
print(f"Total images: {len(images):,}")
print(f"Total annotations: {len(annotations):,}")

# ── Nighttime filter ──────────────────────────────────────────────────────────

night_images = {img["id"]: img["file_name"] for img in images if is_nighttime(img["datetime"])}
print(f"After nighttime filter ({NIGHT_START}:00–{NIGHT_END}:00): {len(night_images):,} images")

# ── Build image_id → category_id map ─────────────────────────────────────────

image_to_category = {ann["image_id"]: ann["category_id"] for ann in annotations}

# ── Split into classes ────────────────────────────────────────────────────────

hazard  = []
ambient = []

for image_id, file_name in night_images.items():
    cat = image_to_category.get(image_id)
    if cat is None:
        continue
    if cat == EMPTY_CAT:
        ambient.append(file_name)
    else:
        hazard.append(file_name)

# ── Write file lists ──────────────────────────────────────────────────────────

hazard_path  = OUT_DIR / "hazard_present.txt"
ambient_path = OUT_DIR / "ambient_noise.txt"

with open(hazard_path, "w") as f:
    f.write("\n".join(hazard))

with open(ambient_path, "w") as f:
    f.write("\n".join(ambient))

print(f"\nDone!")
print(f"  hazard_present : {len(hazard):,} images  → {hazard_path}")
print(f"  ambient_noise  : {len(ambient):,} images  → {ambient_path}")
