#!/usr/bin/env python3
"""
Validate an exported Edge Impulse .eim model against labelled images
from dataset/processed/ without needing the ESP32.

Usage:
    python scripts/test_eim_model.py
    python scripts/test_eim_model.py --eim /path/to/model.eim --samples 200
"""

import argparse
import os
import random
import sys

import cv2
from edge_impulse_linux.image import ImageImpulseRunner

DEFAULT_EIM = os.path.expanduser(
    "~/Downloads/hazard_beacon-mac-arm64-v4-impulse-#1.eim"
)
DATASET_DIR = os.path.join(os.path.dirname(__file__), "../dataset/processed")
CLASSES = ["hazard_present", "ambient_noise"]


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--eim", default=DEFAULT_EIM, help="Path to .eim model file")
    parser.add_argument("--samples", type=int, default=100,
                        help="Total images to test, split evenly per class (default: 100)")
    args = parser.parse_args()

    if not os.path.isfile(args.eim):
        print(f"ERROR: .eim file not found: {args.eim}")
        sys.exit(1)

    per_class = args.samples // 2
    samples = collect_samples(per_class)
    print(f"Testing {len(samples)} images ({per_class} per class)\n")

    results = []

    with ImageImpulseRunner(args.eim) as runner:
        info = runner.init()
        print(f"Model : {info['project']['name']}")
        print(f"Labels: {info['model_parameters']['labels']}\n")

        for i, (path, true_label) in enumerate(samples):
            img = cv2.imread(path)
            if img is None:
                print(f"  [skip: could not read {path}]")
                continue

            try:
                features, _ = runner.get_features_from_image(img)
                res = runner.classify(features)
                clf = res["result"]["classification"]
                predicted = max(clf, key=clf.get)
                score = clf[predicted]
            except Exception as e:
                predicted, score = "error", 0.0
                print(f"  [error on image {i + 1}: {e}]")

            correct = predicted == true_label
            results.append((true_label, predicted, score, correct))

            status = "OK   " if correct else "WRONG"
            print(
                f"[{i + 1:3}/{len(samples)}]  {status}  "
                f"true={true_label:15}  pred={predicted:15}  score={score:.2f}"
            )

    if not results:
        print("No results — check that images loaded correctly.")
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
    print("\nNote: this includes training images, not just the held-out test set,")
    print("so accuracy may be higher than Edge Impulse's Model Testing figure.")


if __name__ == "__main__":
    main()
