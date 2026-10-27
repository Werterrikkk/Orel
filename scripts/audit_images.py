"""Flag visually similar images across provided splits; does not claim scene separation."""

import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def perceptual_hash(path: Path) -> int:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"Cannot read dataset image: {path.name}")
    dct = cv2.dct(cv2.resize(image, (32, 32)).astype(np.float32))[:8, :8].flatten()
    threshold = np.median(dct[1:])
    return int("".join("1" if value > threshold else "0" for value in dct), 2)


def main():
    root = ROOT / "data/datasets/ppe3/images"
    images = {
        split: [
            (path.name, perceptual_hash(path))
            for path in sorted((root / split).iterdir())
            if path.suffix.lower() in {".jpg", ".jpeg", ".png"}
        ]
        for split in ("train", "val", "test")
    }
    pairs = []
    for left, right in (("train", "val"), ("train", "test"), ("val", "test")):
        for name_a, hash_a in images[left]:
            for name_b, hash_b in images[right]:
                distance = (hash_a ^ hash_b).bit_count()
                if distance <= 8:
                    pairs.append(
                        {
                            "left_split": left,
                            "left": name_a,
                            "right_split": right,
                            "right": name_b,
                            "distance": distance,
                        }
                    )
    report = {
        "method": "64-bit DCT perceptual hash; Hamming distance <= 8",
        "limitation": (
            "Flags candidates only. Camera/scene identifiers are unavailable in the source dataset."
        ),
        "pairs": pairs,
    }
    (ROOT / "data/datasets/near-duplicates.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
