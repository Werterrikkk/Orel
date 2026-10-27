import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from scripts import audit_images, clean_splits, prepare_dataset, train_ppe


def create_example(root: Path, split: str, name: str, image):
    for kind in ("images", "labels"):
        (root / kind / split).mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(root / "images" / split / name), image)
    (root / "labels" / split / f"{Path(name).stem}.txt").write_text("0 .5 .5 .5 .5\n")


def test_visual_audit_checks_png_as_well_as_jpeg_and_preserves_test(tmp_path, monkeypatch):
    root = tmp_path / "data/datasets/ppe3"
    image = np.random.default_rng(42).integers(0, 255, (64, 64, 3), dtype=np.uint8)
    create_example(root, "train", "a.png", image)
    create_example(root, "val", "b.png", image)
    create_example(root, "test", "c.jpg", image)
    monkeypatch.setattr(audit_images, "ROOT", tmp_path)
    monkeypatch.setattr(clean_splits, "ROOT", tmp_path)
    audit_images.main()
    report = json.loads((tmp_path / "data/datasets/near-duplicates.json").read_text())
    assert any(pair["left"] == "a.png" for pair in report["pairs"])
    clean_splits.main()
    assert (root / "images/test/c.jpg").is_file()
    assert not (root / "images/train/a.png").exists()
    assert not (root / "images/val/b.png").exists()
    assert (tmp_path / "data/datasets/excluded-near-duplicates/images/train/a.png").is_file()
    clean_splits.main()  # Reusing the same audit must not duplicate the exclusion history.
    repeated = json.loads((tmp_path / "data/datasets/cleaning-report.json").read_text())
    assert len(repeated["excluded"]) == 2
    audit_images.main()
    clean_splits.main()
    summary = json.loads((tmp_path / "data/datasets/cleaning-report.json").read_text())
    assert summary["remaining"] == {"train": 0, "val": 0, "test": 1}
    assert len(summary["excluded"]) == 2


def test_failed_preparation_leaves_no_partial_dataset_and_can_be_retried(tmp_path, monkeypatch):
    directory = tmp_path / "data/datasets"
    original = directory / "construction-ppe"
    directory.mkdir(parents=True)
    (directory / "construction-ppe.zip").write_bytes(b"already extracted test fixture")
    valid_labels = "6 .5 .5 .5 .5\n0 .5 .2 .2 .2\n2 .5 .5 .3 .3\n"
    for index, split in enumerate(("test", "val", "train")):
        create_example(original, split, "sample.png", np.full((64, 64, 3), index * 70, np.uint8))
        (original / "labels" / split / "sample.txt").write_text(valid_labels)
    (original / "data.yaml").write_text("names: {0: helmet, 2: vest, 6: person}\n")
    (original / "labels/val/sample.txt").write_text("invalid annotation")
    monkeypatch.setattr(prepare_dataset, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="annotation"):
        prepare_dataset.prepare()
    assert not (directory / "ppe3").exists()
    assert not list(directory.glob(".ppe3-*"))
    (original / "labels/val/sample.txt").write_text(valid_labels)
    prepare_dataset.prepare()
    assert (directory / "ppe3/images/train/sample.png").is_file()
    assert ".ppe3-" not in (directory / "ppe3.yaml").read_text()


def test_image_audit_explains_an_unreadable_file(tmp_path):
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    with pytest.raises(ValueError, match="broken.png"):
        audit_images.perceptual_hash(broken)


def test_training_refuses_missing_audit_before_loading_a_model(tmp_path, monkeypatch):
    monkeypatch.setattr(train_ppe, "ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["train_ppe"])
    with pytest.raises(SystemExit, match="Prepare and audit"):
        train_ppe.main()
