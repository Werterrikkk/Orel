"""Evaluate immutable weights on the held-out public test split, then optionally activate."""

import argparse
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("weights", type=Path)
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--device", default="mps")
    args = parser.parse_args()
    from orel.ml_runtime import configure_ml

    configure_ml()
    from ultralytics import YOLO

    model = YOLO(str(args.weights))
    if model.names != {0: "person", 1: "helmet", 2: "vest"}:
        raise SystemExit("Unexpected class mapping; activation refused.")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    result = model.val(
        data=str(ROOT / "data/datasets/ppe3.yaml"),
        split="test",
        imgsz=640,
        device=args.device,
        batch=4,
        workers=0,
        plots=True,
        project=str(ROOT / "models/evaluation"),
        name=stamp,
        exist_ok=False,
    )
    digest = hashlib.sha256(args.weights.read_bytes()).hexdigest()
    report = {
        "evaluated_at": datetime.now(UTC).isoformat(),
        "model": "YOLO26n fine-tuned for person/helmet/vest",
        "weights_sha256": digest,
        "classes": model.names,
        "metrics": result.results_dict,
        "per_class": {
            model.names[int(index)]: {
                "precision": float(result.box.p[offset]),
                "recall": float(result.box.r[offset]),
                "AP50": float(result.box.ap50[offset]),
                "AP50_95": float(result.box.ap[offset]),
            }
            for offset, index in enumerate(result.box.ap_class_index)
        },
        "dataset": json.loads((ROOT / "data/datasets/cleaning-report.json").read_text()),
        "scope": (
            "Public dataset test split after exact/perceptual duplicate checks. "
            "Scene independence is unverified. This does not measure site-camera performance, "
            "event accuracy, or correct PPE wearing."
        ),
    }
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "model-evaluation.json").write_text(json.dumps(report, indent=2))
    if args.activate:
        directory = ROOT / "models/active"
        directory.mkdir(exist_ok=True)
        destination = directory / f"ppe-{digest[:12]}.pt"
        if not destination.exists():
            shutil.copy2(args.weights, destination)
        manifest = {
            "path": str(destination),
            "weights_sha256": digest,
            "qualification": "experimental-public-data-only",
            "metrics": {
                "mAP50 (test)": float(result.box.map50),
                "mAP50–95 (test)": float(result.box.map),
            },
            "report": "reports/model-evaluation.json",
        }
        temporary = ROOT / "models/active.tmp"
        temporary.write_text(json.dumps(manifest, indent=2))
        temporary.replace(ROOT / "models/active.json")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
