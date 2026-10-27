"""Download and audit the public PPE dataset, then remap three target classes."""

import hashlib
import json
import shutil
import tempfile
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "https://github.com/ultralytics/assets/releases/download/v0.0.0/construction-ppe.zip"
TARGET_CLASSES = {6: 0, 0: 1, 2: 2}  # Person, helmet, vest in the documented source YAML.


def prepare():
    directory = ROOT / "data" / "datasets"
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / "construction-ppe.zip"
    if not archive.exists():
        print("Downloading public Construction-PPE dataset…", flush=True)
        temporary = archive.with_suffix(".download")
        urllib.request.urlretrieve(SOURCE, temporary)
        temporary.rename(archive)
    original = directory if (directory / "images").exists() else directory / "construction-ppe"
    if not (original / "images").exists():
        original.mkdir(exist_ok=True)
        with zipfile.ZipFile(archive) as package:
            for member in package.infolist():
                if not (original / member.filename).resolve().is_relative_to(original.resolve()):
                    raise ValueError("Unsafe archive path")
            package.extractall(original)
    source_names = yaml.safe_load((original / "data.yaml").read_text())["names"]
    if any(
        source_names[key].lower() != expected
        for key, expected in {6: "person", 0: "helmet", 2: "vest"}.items()
    ):
        raise ValueError("Source class mapping changed; review annotations before remapping.")
    target = directory / "ppe3"
    if target.exists():
        raise SystemExit("Prepared dataset already exists. Inspect its audit before reusing it.")
    audit = {
        "source": SOURCE,
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "classes": {0: "person", 1: "helmet", 2: "vest"},
        "splits": {},
    }
    with tempfile.TemporaryDirectory(prefix=".ppe3-", dir=directory) as staging:
        destination = target
        target = Path(staging) / "ppe3"
        hashes: set[str] = set()
        # Retain final-test examples first; identical train/validation images are then excluded.
        for split in ("test", "val", "train"):
            counts: Counter = Counter()
            duplicate_count = 0
            image_count = 0
            for image in sorted((original / "images" / split).glob("*")):
                if image.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                    continue
                fingerprint = hashlib.sha256(image.read_bytes()).hexdigest()
                if fingerprint in hashes:
                    duplicate_count += 1
                    continue
                hashes.add(fingerprint)
                label = original / "labels" / split / f"{image.stem}.txt"
                if not label.exists():
                    raise ValueError(f"Missing labels: {label.name}")
                output = []
                for line in label.read_text().splitlines():
                    parts = line.split()
                    if len(parts) != 5:
                        raise ValueError(f"Unexpected annotation: {label.name}")
                    class_id = int(parts[0])
                    x, y, width, height = map(float, parts[1:])
                    if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < width <= 1 and 0 < height <= 1):
                        raise ValueError(f"Invalid bounding box: {label.name}")
                    if class_id in TARGET_CLASSES:
                        mapped = TARGET_CLASSES[class_id]
                        counts[mapped] += 1
                        output.append(f"{mapped} {' '.join(parts[1:])}")
                image_dir, label_dir = target / "images" / split, target / "labels" / split
                image_dir.mkdir(parents=True, exist_ok=True)
                label_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(image, image_dir / image.name)
                (label_dir / f"{image.stem}.txt").write_text("\n".join(output) + "\n")
                image_count += 1
            if not image_count or any(counts[i] == 0 for i in range(3)):
                raise ValueError(f"Empty split or missing class: {split}")
            audit["splits"][split] = {
                "images": image_count,
                "objects": dict(counts),
                "exact_duplicates_removed": duplicate_count,
            }
        target.rename(destination)
        target = destination
    config = directory / "ppe3.yaml"
    config.write_text(
        f"path: {target}\ntrain: images/train\nval: images/val\ntest: images/test\n"
        "names:\n  0: person\n  1: helmet\n  2: vest\n"
    )
    (directory / "audit.json").write_text(json.dumps(audit, indent=2))
    print(json.dumps(audit, indent=2), flush=True)


if __name__ == "__main__":
    prepare()
