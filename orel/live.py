"""One local camera lease. Confirmation uses server time, never browser timestamps."""

import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime

import cv2
import numpy as np

from orel.domain import Detection, Zone, evaluate
from orel.evidence import save_event
from orel.schemas import CameraSettings
from orel.sources import LAPTOP, FrameObservation, Source
from orel.storage import Store
from orel.surveillance import SurveillanceRules

CAMERA_ID = "macbook-camera"
LEASE_SECONDS = 15
MAX_FRAME_AGE = 2.0


@dataclass
class CameraSession:
    model: dict
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_at: float = field(default_factory=time.monotonic)
    updated_at: float = field(default_factory=time.monotonic)
    sequence: int = -1
    last_observation: float | None = None
    rules: SurveillanceRules = field(default_factory=SurveillanceRules)
    source: Source = LAPTOP
    obscured_since: float | None = None
    obscured_event: bool = False


class LiveMonitor:
    """The app's inference lock protects session mutations, including config changes."""

    def __init__(self, store: Store, clock: Callable[[], float] = time.monotonic):
        self.store = store
        self.clock = clock
        self.session: CameraSession | None = None

    def settings(self) -> dict:
        stored = self.store.get("configurations", CAMERA_ID) or {}
        return CameraSettings.model_validate(stored).model_dump()

    def save_settings(self, settings: CameraSettings) -> dict:
        data = settings.model_dump()
        self.store.put("configurations", CAMERA_ID, data)
        if self.session:
            self.session.rules.reset()
            self.session.last_observation = None
        return data

    def active(self) -> bool:
        if self.session and self.clock() - self.session.updated_at >= LEASE_SECONDS:
            self.session = None
        return self.session is not None

    def start(self, model: dict, source: Source = LAPTOP) -> dict:
        if self.active():
            raise ValueError(
                "Камера уже запущена в другом окне. Остановите её там или подождите 15 секунд."
            )
        self.session = CameraSession(
            model=dict(model), source=source, started_at=self.clock(), updated_at=self.clock()
        )
        return {
            "id": self.session.id,
            "model": {key: value for key, value in model.items() if key != "path"},
            "settings": self.settings(),
        }

    def require(self, session_id: str) -> CameraSession:
        if not self.active() or self.session is None or self.session.id != session_id:
            raise ValueError("Сеанс камеры завершён. Включите камеру повторно.")
        return self.session

    def stop(self, session_id: str) -> None:
        if self.session and self.session.id == session_id:
            self.session = None

    def observe(
        self,
        session_id: str,
        sequence: int,
        jpeg: bytes,
        data: FrameObservation,
        received_at: float,
        now: datetime,
    ) -> dict:
        session = self.require(session_id)
        session.updated_at = self.clock()
        result = {
            "status": "stale",
            "people": [],
            "people_in_zone": 0,
            "people_total": 0,
            "reasons": [],
            "uncertain": False,
            "detections": [],
            "new_events": [],
            "alerts": [],
            "pending_signals": 0,
            "server_time": now.isoformat(),
            "sequence": sequence,
            "inference_ms": data["inference_ms"],
            "model": data["model"],
        }
        if self.clock() - received_at > MAX_FRAME_AGE:
            session.rules.reset()
            session.obscured_since = None
            session.obscured_event = False
            return result
        if session.last_observation is not None and received_at - session.last_observation > 1.25:
            session.rules.reset()
            session.obscured_since = None
            session.obscured_event = False
        session.last_observation = received_at
        settings = self.settings()
        health = data.get("camera_health", "ok")
        result["camera_health"] = health
        if health == "obscured":
            session.rules.assess(
                [],
                received_at,
                settings["require_helmet"],
                settings["require_vest"],
                settings["danger_zone"],
            )
            if session.obscured_since is None:
                session.obscured_since = received_at
            duration = received_at - session.obscured_since
            result.update(status="uncertain", uncertain=True, analysis_settings=data["settings"])
            if duration >= 5 and not session.obscured_event:
                frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
                if frame is not None:
                    event = save_event(
                        self.store,
                        session.source.event_metadata(data["model"]),
                        {"zone": {"name": "Камера", "left": 0, "top": 0, "right": 1, "bottom": 1}},
                        "camera_obscured",
                        received_at - session.started_at,
                        result,
                        now,
                        frame,
                        details={"severity": "critical", "duration_seconds": duration},
                    )
                    result["new_events"].append(event)
                    session.obscured_event = True
            result["camera_health_seconds"] = duration
            return result
        session.obscured_since = None
        session.obscured_event = False
        zone = Zone("Весь кадр", 0, 0, 1, 1, settings["require_helmet"], settings["require_vest"])
        assessment = evaluate(
            [
                Detection(item["kind"], tuple(item["box"]), item["confidence"])
                for item in data["objects"]
            ],
            zone,
            None,
            now,
            True,
            data["inference_height"],
            check_permit=False,
        )
        result.update(assessment, detections=data["objects"], analysis_settings=data["settings"])
        alerts = session.rules.assess(
            result["people"],
            received_at,
            settings["require_helmet"],
            settings["require_vest"],
            settings["danger_zone"],
        )
        result["alerts"] = alerts
        result["pending_signals"] = session.rules.pending_count
        people = iter(result["people"])
        result["detections"] = [
            {**item, "track_id": next(people)["track_id"]} if item["kind"] == "person" else item
            for item in data["objects"]
        ]
        if any(alert["code"] == "danger_zone" for alert in alerts):
            result["status"] = "restricted"
        source = session.source.event_metadata(data["model"])
        frame = None
        for alert in alerts:
            episode = session.rules.episodes[alert["track_id"], alert["code"]]
            if alert["duration_seconds"] < 1:
                continue
            if episode.event_id is None:
                if frame is None:
                    frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if frame is None:
                        raise ValueError("Не удалось получить кадр события камеры.")
                event_zone = (
                    {**settings["danger_zone"], "require_helmet": False, "require_vest": False}
                    if alert["code"] == "danger_zone"
                    else asdict(zone)
                )
                config = {"zone": event_zone, "permit": None, "check_permit": False}
                event = save_event(
                    self.store,
                    source,
                    config,
                    alert["code"],
                    received_at - session.started_at,
                    result,
                    now,
                    frame,
                    details={
                        "severity": alert["severity"],
                        "alert_id": alert["id"],
                        "track_id": alert["track_id"],
                        "duration_seconds": alert["duration_seconds"],
                        "missing": alert["missing"],
                    },
                )
                episode.event_id = event["id"]
                episode.saved_severity = alert["severity"]
                result["new_events"].append(event)
            elif episode.saved_severity == "warning" and alert["severity"] == "critical":
                event = self.store.get("events", episode.event_id)
                if event:
                    event.update(
                        severity=alert["severity"],
                        escalated_at=now.isoformat(),
                        duration_seconds=alert["duration_seconds"],
                        missing=alert["missing"],
                    )
                    self.store.put("events", episode.event_id, event)
                    episode.saved_severity = alert["severity"]
                    result["new_events"].append(event)
        return result
