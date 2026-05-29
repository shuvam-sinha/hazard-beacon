"""
Wellington Camera Traps - Dataset Filter Script
================================================
Reads the wellington_camera_traps.csv and splits image filenames into:
  - hazard_present.txt  → animals (any label that isn't empty/nothinghere)
  - ambient_noise.txt   → empty frames (label == 'nothinghere')

Run this BEFORE downloading images so you only pull what you need.

Usage:
    python filter_wellington.py --csv wellington_camera_traps.csv

Requirements:
    pip install pandas
"""

import argparse
import pandas as pd
from pathlib import Path
from datetime import datetime


# ── Labels ────────────────────────────────────────────────────────────────────
# Any label NOT in this set is treated as a hazard (animal present)
EMPTY_LABELS = {"nothinghere", "empty", "unclassifiable"}

# Optional: restrict to nighttime only (hour range, 24h clock)
# Set NIGHT_ONLY = False to keep all times
NIGHT_ONLY = True
NIGHT_START = 19   # 7 PM
NIGHT_END   = 6    # 6 AM


def is_nighttime(date_str):
    """Return True if the timestamp falls in the nighttime window."""
    try:
        dt = datetime.strptime(str(date_str).strip(), "%m/%d/%Y %H:%M")
        h = dt.hour
        if NIGHT_START > NIGHT_END:          # wraps midnight
            return h >= NIGHT_START or h < NIGHT_END
        return NIGHT_START <= h < NIGHT_END
    except Exception:
        return False                          # keep row if date is unparseable


def main():
    parser = argparse.ArgumentParser(description="Filter Wellington Camera Traps CSV")
    parser.add_argument("--csv", required=True, help="Path to wellington_camera_traps.csv")
    parser.add_argument("--out", default=".", help="Output directory for text files")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    out_dir  = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Reading {csv_path} ...")
    df = pd.read_csv(csv_path)

    print(f"Total rows loaded: {len(df):,}")
    print(f"Columns found: {list(df.columns)}")
    print(f"Label values (sample): {df['label'].value_counts().head(10).to_dict()}\n")

    # ── Nighttime filter ──────────────────────────────────────────────────────
    if NIGHT_ONLY:
        before = len(df)
        df = df[df["date"].apply(is_nighttime)]
        print(f"After nighttime filter ({NIGHT_START}:00–{NIGHT_END}:00): "
              f"{len(df):,} rows (dropped {before - len(df):,})")
    else:
        print("Nighttime filter OFF — keeping all timestamps")

    # ── Split into classes ────────────────────────────────────────────────────
    df["label_lower"] = df["label"].str.strip().str.lower()

    hazard  = df[~df["label_lower"].isin(EMPTY_LABELS)]["file"].dropna().unique()
    ambient = df[ df["label_lower"].isin(EMPTY_LABELS)]["file"].dropna().unique()

    # ── Write file lists ──────────────────────────────────────────────────────
    hazard_path  = out_dir / "hazard_present.txt"
    ambient_path = out_dir / "ambient_noise.txt"

    with open(hazard_path, "w") as f:
        f.write("\n".join(hazard))

    with open(ambient_path, "w") as f:
        f.write("\n".join(ambient))

    print(f"\n✅ Done!")
    print(f"   hazard_present : {len(hazard):,} images  → {hazard_path}")
    print(f"   ambient_noise  : {len(ambient):,} images  → {ambient_path}")
    print(f"\nNext step: use these lists to download only the images you need")
    print(f"See: https://lila.science/image-access for batch download instructions")


if __name__ == "__main__":
    main()
