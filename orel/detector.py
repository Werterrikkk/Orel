"""YOLO adapter owned by one inference worker; never shared between API threads."""

import hashlib
import json
import time
from functools import lru_cache
from pathlib import Path

from orel.ml_runtime import configure_ml

ALIASES = {
    "person": "person",
    "human": "person",
    "helmet": "helmet",
    "hardhat": "helmet",
    "vest": "vest",
    "safety-vest": "vest",
}


class Detector:
    def __init__(self, spec: dict):
        configure_ml()
        import torch
        from ultralytics import YOLO

        torch.set_num_threads(4)
        path = Path(spec["path"])
        if path.is_file() and spec.get("weights_sha256"):
            with path.open("rb") as weights:
                digest = hashlib.file_digest(weights, "sha256").hexdigest()
            if digest != spec["weights_sha256"]:
                raise ValueError("Файл модели повреждён. Повторно активируйте проверенные веса.")
        self.model = YOLO(str(path))
        person_path = Path(__file__).resolve().parents[1] / "models/yolo26n.pt"
        self.person_model = (
            YOLO(str(person_path)) if spec["ppe"] and person_path.is_file() else None
        )
        with path.open("rb") as weights:
            digest = hashlib.file_digest(weights, "sha256").hexdigest()
        self.metadata = {key: value for key, value in spec.items() if key != "path"}
        self.metadata["weights_sha256"] = digest
        if self.person_model is not None:
            with person_path.open("rb") as weights:
                self.metadata["person_weights_sha256"] = hashlib.file_digest(
                    weights, "sha256"
                ).hexdigest()
            self.metadata["person_detector"] = "YOLO26n COCO"
        self.names = {
            int(key): ALIASES.get(str(value).lower()) for key, value in self.model.names.items()
        }
        if "person" not in self.names.values() or (
            spec["ppe"] and not {"helmet", "vest"}.issubset(self.names.values())
        ):
            raise ValueError("Классы модели не соответствуют выбранному режиму.")
        self.class_ids = [key for key, value in self.names.items() if value]

    def predict(self, frame) -> tuple[list[dict], float]:
        started = time.monotonic()
        result = self.model.predict(
            frame, classes=self.class_ids, conf=0.30, imgsz=640, device="cpu", verbose=False
        )[0]
        objects = []
        for box, score, class_id in zip(
            result.boxes.xyxyn.cpu().tolist(),
            result.boxes.conf.cpu().tolist(),
            result.boxes.cls.cpu().tolist(),
            strict=True,
        ):
            box = [round(min(1.0, max(0.0, x)), 6) for x in box]
            if box[0] >= box[2] or box[1] >= box[3]:
                continue
            objects.append(
                {"kind": self.names[int(class_id)], "box": box, "confidence": round(score, 4)}
            )
        if self.person_model is not None:
            people = self.person_model.predict(
                frame, classes=[0], conf=0.30, imgsz=640, device="cpu", verbose=False
            )[0]
            objects = [item for item in objects if item["kind"] != "person"]
            for box, score in zip(
                people.boxes.xyxyn.cpu().tolist(), people.boxes.conf.cpu().tolist(), strict=True
            ):
                box = [round(min(1.0, max(0.0, x)), 6) for x in box]
                if box[0] < box[2] and box[1] < box[3]:
                    objects.append({"kind": "person", "box": box, "confidence": round(score, 4)})
        return objects, round((time.monotonic() - started) * 1000, 1)


@lru_cache(maxsize=1)
def cached_detector(spec_json: str) -> Detector:
    """Only used in the single-process worker, which executes frames sequentially."""
    return Detector(json.loads(spec_json))
