"""Replay sessions: server-side evaluation, episode filtering, and evidence capture."""

import bisect
import hashlib
import json
import math
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import pairwise

import cv2

from orel.domain import REASONS, Detection, IncidentGate, Permit, Zone, evaluate
from orel.evidence import save_event
from orel.schemas import PlaybackInput
from orel.storage import Store


@dataclass
class ReplaySession:
    updated_at: float = field(default_factory=time.monotonic)
    position: float | None = None
    signature: str = ""
    video_id: str = ""
    gates: dict[str, IncidentGate] = field(default_factory=dict)


class Monitor:
    def __init__(self, store: Store):
        self.store = store
        self.sessions: dict[str, ReplaySession] = {}
        self.lock = threading.Lock()
        self.cache: dict[str, tuple[int, dict, list[float]]] = {}

    def results(self, video_id: str) -> tuple[dict, list[float]]:
        path = self.store.root / "results" / f"{video_id}.json"
        modified = path.stat().st_mtime_ns
        cached = self.cache.get(video_id)
        if not cached or cached[0] != modified:
            try:
                data = json.loads(path.read_text())
                times = [frame["time"] for frame in data["frames"]]
                if (
                    not times
                    or not all(math.isfinite(t) and t >= 0 for t in times)
                    or any(right <= left for left, right in pairwise(times))
                    or not math.isfinite(data["sample_fps"])
                    or data["sample_fps"] <= 0
                    or not isinstance(data["model"]["ppe"], bool)
                    or data["inference_height"] <= 0
                ):
                    raise ValueError("Invalid analysis metadata")
                for frame in data["frames"]:
                    if not isinstance(frame["objects"], list):
                        raise ValueError("Invalid detection list")
                    for detection in frame["objects"]:
                        left, top, right, bottom = detection["box"]
                        if (
                            detection["kind"] not in {"person", "helmet", "vest"}
                            or not 0 <= left < right <= 1
                            or not 0 <= top < bottom <= 1
                            or not 0 <= detection["confidence"] <= 1
                        ):
                            raise ValueError("Invalid detection")
            except (ValueError, KeyError, TypeError, IndexError) as exc:
                raise ValueError(
                    "Результаты анализа повреждены. Запустите анализ повторно."
                ) from exc
            cached = modified, data, times
            # A prototype only keeps the current video's potentially large analysis in memory.
            self.cache = {video_id: cached}
        return cached[1], cached[2]

    def observe(self, request: PlaybackInput, now: datetime | None = None) -> dict:
        now = now or datetime.now(UTC)
        video = self.store.get("videos", request.video_id)
        if not video or video["status"] != "ready":
            raise ValueError("Анализ видео не готов.")
        if request.position > video["duration"] + 0.1:
            raise ValueError("Позиция выходит за границы видео.")
        with self.lock:
            config = self.store.get("configurations", request.video_id)
            if not config or not config.get("zone"):
                self.sessions.pop(request.session_id, None)
                return {
                    "status": "no_zone",
                    "people": [],
                    "people_in_zone": 0,
                    "people_total": 0,
                    "reasons": [],
                    "uncertain": False,
                    "new_events": [],
                    "server_time": now.isoformat(),
                }
            data, times = self.results(request.video_id)
            index = max(0, bisect.bisect_right(times, request.position) - 1)
            sample = data["frames"][index]
            if abs(sample["time"] - request.position) > max(0.75, 2 / data["sample_fps"]):
                raise ValueError("Нет актуального результата для этой позиции видео.")
            detections = [
                Detection(d["kind"], tuple(d["box"]), d["confidence"]) for d in sample["objects"]
            ]
            zone = Zone(**config["zone"])
            raw_permit = config.get("permit")
            permit = (
                Permit(
                    **{
                        **raw_permit,
                        "starts_at": datetime.fromisoformat(raw_permit["starts_at"]),
                        "ends_at": datetime.fromisoformat(raw_permit["ends_at"]),
                    }
                )
                if raw_permit
                else None
            )
            result = evaluate(
                detections, zone, permit, now, data["model"]["ppe"], data["inference_height"]
            )
            result.update(
                server_time=now.isoformat(),
                sample_time=sample["time"],
                sample_frame_index=sample.get("frame_index"),
                detections=sample["objects"],
                new_events=[],
                analysis_settings=data.get("settings", {}),
            )
            self.sessions = {
                key: value
                for key, value in self.sessions.items()
                if time.monotonic() - value.updated_at < 1800
            }
            if request.session_id not in self.sessions and len(self.sessions) >= 100:
                raise ValueError("Слишком много активных сеансов.")
            session = self.sessions.setdefault(request.session_id, ReplaySession())
            signature = hashlib.sha256(
                json.dumps(
                    [config, data.get("analyzed_at"), data["model"]], sort_keys=True
                ).encode()
            ).hexdigest()
            jump = (
                session.position is not None and not 0 <= request.position - session.position <= 1.0
            )
            interrupted = time.monotonic() - session.updated_at > 2
            if (
                session.signature != signature
                or session.video_id != request.video_id
                or request.seeking
                or jump
                or interrupted
            ):
                session.gates.clear()
            session.signature = signature
            session.video_id = request.video_id
            session.updated_at = time.monotonic()
            advancing = (
                request.playing
                and not request.seeking
                and (session.position is None or request.position > session.position)
            )
            if advancing:
                for code in REASONS:
                    gate = session.gates.setdefault(code, IncidentGate())
                    if gate.observe(request.position, code in result["reasons"]):
                        try:
                            event = self._save_event(
                                video, config, code, request.position, result, now
                            )
                        except Exception:
                            gate.emitted = False
                            raise
                        result["new_events"].append(event)
            session.position = request.position
            return result

    def _save_event(
        self, video: dict, config: dict, code: str, position: float, result: dict, now: datetime
    ) -> dict:
        capture = cv2.VideoCapture(str(self.store.root / "uploads" / video["file"]))
        try:
            if result["sample_frame_index"] is not None:
                capture.set(cv2.CAP_PROP_POS_FRAMES, result["sample_frame_index"])
            else:
                capture.set(cv2.CAP_PROP_POS_MSEC, result["sample_time"] * 1000)
            ok, frame = capture.read()
            if not ok:
                raise OSError("Не удалось получить кадр события.")
        finally:
            capture.release()
        return save_event(
            self.store,
            video,
            config,
            code,
            result["sample_time"],
            result,
            now,
            frame,
            playback_position=position,
        )
