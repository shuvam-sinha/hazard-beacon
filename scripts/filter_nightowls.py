"""
NightOwls - Dataset Filter Script
===================================
Reads nightowls_training.json and nightowls_validation.json and outputs
image filenames for hazard_present (pedestrians, cyclists, motorbike drivers).

All NightOwls images are nighttime so no timestamp filtering is needed.
There are no empty frames in NightOwls — only hazard_present is generated.

Usage:
    python filter_nightowls.py

Requirements:
    None (standard library only)
"""

import json
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

DATA_DIR = Path("~/Documents/hazard_beacon/dataset/raw/nightowls").expanduser()
OUT_DIR  = DATA_DIR

ANNOTATION_FILES = [
    DATA_DIR / "nightowls_training.json",
    DATA_DIR / "nightowls_validation.json",
]

HAZARD_CATEGORIES = {1, 2, 3}  # pedestrian, bicycledriver, motorbikedriver
IGNORE_CATEGORY   = 4          # ignore — skip these


# ── Process each annotation file ─────────────────────────────────────────────

hazard_files = set()

for ann_file in ANNOTATION_FILES:
    print(f"Loading {ann_file.name} ...")
    with open(ann_file) as f:
        data = json.load(f)

    images      = {img["id"]: img["file_name"] for img in data["images"]}
    annotations = data["annotations"]

    # Collect image IDs that have at least one hazard annotation
    hazard_image_ids = set()
    for ann in annotations:
        if ann["category_id"] in HAZARD_CATEGORIES:
            hazard_image_ids.add(ann["image_id"])

    for image_id in hazard_image_ids:
        if image_id in images:
            hazard_files.add(images[image_id])

    print(f"  {len(hazard_image_ids):,} hazard images found in {ann_file.name}")

# ── Write file list ───────────────────────────────────────────────────────────

hazard_path = OUT_DIR / "hazard_present.txt"
with open(hazard_path, "w") as f:
    f.write("\n".join(sorted(hazard_files)))

print(f"\nDone!")
print(f"  hazard_present : {len(hazard_files):,} images  → {hazard_path}")
print(f"  (NightOwls has no empty frames — no ambient_noise.txt generated)")
