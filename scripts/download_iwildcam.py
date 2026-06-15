"""
iWildCam Image Downloader
==========================
Downloads a subset of iWildCam images using the filtered file lists.
Pulls hazard_present and ambient_noise images via the Kaggle CLI.

Usage:
    python download_iwildcam.py

Requirements:
    pip install kaggle
    kaggle auth login (must be authenticated)
"""

import subprocess
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

RAW_DIR         = Path("~/Documents/hazard_beacon/dataset/raw/iwildcam").expanduser()
HAZARD_LIST     = RAW_DIR / "hazard_present.txt"
AMBIENT_LIST    = RAW_DIR / "ambient_noise.txt"
HAZARD_OUT_DIR  = Path("~/Documents/hazard_beacon/dataset/processed/hazard_present").expanduser()
AMBIENT_OUT_DIR = Path("~/Documents/hazard_beacon/dataset/processed/ambient_noise").expanduser()

HAZARD_LIMIT  = 5000
AMBIENT_LIMIT = 2000

COMPETITION = "iwildcam-2020-fgvc7"

# ── Setup ─────────────────────────────────────────────────────────────────────

HAZARD_OUT_DIR.mkdir(parents=True, exist_ok=True)
AMBIENT_OUT_DIR.mkdir(parents=True, exist_ok=True)


def download_images(file_list_path, out_dir, limit, label):
    with open(file_list_path) as f:
        filenames = [line.strip() for line in f if line.strip()]

    filenames = filenames[:limit]
    print(f"\nDownloading {len(filenames)} {label} images to {out_dir} ...")

    success = 0
    failed  = 0

    for i, filename in enumerate(filenames, 1):
        dest = out_dir / filename
        if dest.exists():
            print(f"[{i}/{len(filenames)}] Skipping (already exists): {filename}")
            success += 1
            continue

        result = subprocess.run(
            ["kaggle", "competitions", "download",
             "-c", COMPETITION,
             "-f", f"train/{filename}",
             "-p", str(out_dir)],
            capture_output=True, text=True
        )

        if result.returncode == 0:
            success += 1
            print(f"[{i}/{len(filenames)}] Downloaded: {filename}")
        else:
            failed += 1
            print(f"[{i}/{len(filenames)}] FAILED: {filename} — {result.stderr.strip()}")

    print(f"\n{label}: {success} downloaded, {failed} failed")


# ── Run ───────────────────────────────────────────────────────────────────────

download_images(HAZARD_LIST,  HAZARD_OUT_DIR,  HAZARD_LIMIT,  "hazard_present")
download_images(AMBIENT_LIST, AMBIENT_OUT_DIR, AMBIENT_LIMIT, "ambient_noise")

print("\nAll downloads complete.")
