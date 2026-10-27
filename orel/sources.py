"""Source contract: adapters supply normalized detections, not safety decisions."""

from dataclasses import dataclass
from typing import TypedDict


class FrameObservation(TypedDict):
    objects: list[dict]
    inference_height: int
    inference_ms: float
    model: dict
    settings: dict


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    adapter: str
    available: bool
    inference_location: str
    detail: str

    def event_metadata(self, model: dict) -> dict:
        return {"id": self.id, "name": self.name, "source_type": "camera", "model": model}


LAPTOP = Source(
    "macbook-camera",
    "Камера ноутбука",
    "browser-jpeg",
    True,
    "local-computer",
    "Превью с локальной обработкой YOLO26n",
)
RUBETEK = Source(
    "rubetek",
    "Rubetek",
    "rubetek-sdk",
    False,
    "camera-planned",
    "Нужны модель камеры и SDK/API производителя. Установка собственной модели ещё не проверена.",
)
