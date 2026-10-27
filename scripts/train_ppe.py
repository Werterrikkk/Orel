"""Reproducible local fine-tuning. Runs are never overwritten."""

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--device", default="mps")
    parser.add_argument("--resume", type=Path)
    args = parser.parse_args()
    audit_path = ROOT / "data/datasets/cleaning-report.json"
    if not audit_path.is_file():
        raise SystemExit("Prepare and audit the dataset before training; see docs/model.md.")
    dataset_audit = json.loads(audit_path.read_text())
    if any(
        dataset_audit.get("remaining", {}).get(split, 0) <= 0 for split in ("train", "val", "test")
    ):
        raise SystemExit("Training requires nonempty audited train, validation, and test splits.")
    from orel.ml_runtime import configure_ml

    configure_ml()
    import torch
    from ultralytics import YOLO

    if args.device == "mps" and not torch.backends.mps.is_available():
        raise SystemExit(
            "MPS is unavailable; inspect the environment before choosing another device."
        )
    models = ROOT / "models"
    models.mkdir(exist_ok=True)
    initial_weights = args.resume if args.resume else models / "yolo26n.pt"
    model = YOLO(str(initial_weights))
    initial_digest = hashlib.sha256(initial_weights.read_bytes()).hexdigest()
    started = time.monotonic()
    result = model.train(
        data=str(ROOT / "data/datasets/ppe3.yaml"),
        epochs=args.epochs,
        batch=args.batch,
        imgsz=640,
        device=args.device,
        workers=0,
        cache=False,
        optimizer="AdamW",
        lr0=0.001,
        seed=42,
        deterministic=True,
        project=str(models / "runs"),
        name=datetime.now(UTC).strftime("ppe-%Y%m%dT%H%M%SZ"),
        exist_ok=False,
        patience=15,
        plots=True,
        resume=bool(args.resume),
    )
    report = {
        "model": "YOLO26n",
        "classes": model.names,
        "epochs_requested": args.epochs,
        "seconds": round(time.monotonic() - started, 2),
        "device": args.device,
        "dataset_audit": dataset_audit,
        "initial_weights_sha256": initial_digest,
        "metrics": result.results_dict,
        "best_weights": str(Path(model.trainer.save_dir) / "weights/best.pt"),
        "scope": "Validation on the public dataset; not qualification on a real facility camera.",
    }
    destination = Path(model.trainer.save_dir) / "training-report.json"
    destination.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
