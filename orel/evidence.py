"""Persist an observation together with the exact image that produced it."""

import uuid
from datetime import datetime

import cv2
import numpy as np

from orel.domain import REASONS
from orel.storage import Store


def save_event(
    store: Store,
    source: dict,
    config: dict,
    code: str,
    position: float,
    result: dict,
    now: datetime,
    frame,
    playback_position: float | None = None,
    details: dict | None = None,
) -> dict:
    frame = frame.copy()
    height, width = frame.shape[:2]
    zone = config["zone"]
    if zone.get("points"):
        vertices = np.array(
            [[int(x * width), int(y * height)] for x, y in zone["points"]], dtype=np.int32
        )
        cv2.polylines(frame, [vertices], True, (65, 65, 235), 2)
    else:
        cv2.rectangle(
            frame,
            (int(zone["left"] * width), int(zone["top"] * height)),
            (int(zone["right"] * width), int(zone["bottom"] * height)),
            (65, 65, 235),
            2,
        )
    for person in result["people"]:
        x1, y1, x2, y2 = person["box"]
        cv2.rectangle(
            frame,
            (int(x1 * width), int(y1 * height)),
            (int(x2 * width), int(y2 * height)),
            (60, 60, 225),
            2,
        )
    event_id = uuid.uuid4().hex
    snapshot = store.root / "snapshots" / f"{event_id}.jpg"
    if not cv2.imwrite(str(snapshot), frame):
        raise OSError("Не удалось сохранить кадр события.")
    event = {
        "id": event_id,
        "video_id": source["id"],
        "video_name": source["name"],
        "source_type": source.get("source_type", "recording"),
        "created_at": now.isoformat(),
        "position": round(position, 3),
        "zone": zone["name"],
        "permit_number": (config.get("permit") or {}).get("number"),
        "code": code,
        "reason": REASONS[code],
        "people_count": result["people_in_zone"],
        "reviewed": False,
        "snapshot_url": f"/api/events/{event_id}/snapshot",
        "configuration": config,
        "model": source.get("model"),
        "analysis_settings": result["analysis_settings"],
    }
    if playback_position is not None:
        event["playback_position"] = round(playback_position, 3)
    if details:
        event.update(details)
    try:
        store.put("events", event_id, event)
    except Exception:
        snapshot.unlink(missing_ok=True)
        raise
    return event
