"""Detector adapter and offline video analysis, executed outside the API process."""

import json
import math
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import cv2

from orel.detector import Detector, cached_detector
from orel.storage import Store

ROOT = Path(__file__).resolve().parents[1]


def model_catalog() -> dict:
    manifest = ROOT / "models" / "active.json"
    try:
        ppe = json.loads(manifest.read_text()) if manifest.exists() else None
    except (OSError, json.JSONDecodeError):
        ppe = None
    if not isinstance(ppe, dict) or not isinstance(ppe.get("path"), str):
        ppe = None
    ppe_metadata = {
        key: value
        for key, value in (ppe or {}).items()
        if key in {"path", "weights_sha256", "qualification", "metrics", "report"}
    }
    return {
        "person": {
            "available": True,
            "name": "YOLO26n · люди",
            "path": str(ROOT / "models/yolo26n.pt"),
            "ppe": False,
        },
        "ppe": {
            "available": bool(ppe and Path(ppe["path"]).is_file()),
            "name": "YOLO26n · люди и СИЗ",
            "ppe": True,
            **ppe_metadata,
        },
    }


def inspect_video(path: Path, preview: Path) -> dict:
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValueError("Не удалось открыть видео. Попробуйте MP4 с кодеком H.264.")
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        ok, frame = capture.read()
        if not ok or not math.isfinite(fps) or fps <= 0 or frames <= 0:
            raise ValueError("Не удалось прочитать кадры и длительность видео.")
        duration = frames / fps
        if duration > 600:
            raise ValueError("Для прототипа выберите ролик длительностью до 10 минут.")
        height, width = frame.shape[:2]
        if not cv2.imwrite(str(preview), frame):
            raise OSError("Не удалось сохранить превью.")
        return {
            "width": width,
            "height": height,
            "fps": fps,
            "duration": duration,
            "frame_count": frames,
        }
    finally:
        capture.release()


def analyze_video(root: str, video_id: str, model_spec: dict, sample_fps: float = 5.0):
    """Worker entry point. Database progress is visible even across HTTP polling requests."""
    store = Store(Path(root))
    video = store.get("videos", video_id)
    if video is None:
        return
    capture = None
    cancelled = store.root / "results" / f"{video_id}.cancel"
    started = time.monotonic()
    try:
        if cancelled.exists():
            raise ValueError("Анализ остановлен при завершении приложения.")
        detector = Detector(model_spec)
        capture = cv2.VideoCapture(str(store.root / "uploads" / video["file"]))
        if not capture.isOpened():
            raise ValueError("Источник видео недоступен.")
        output = []
        index = 0
        last_progress = 0.0
        next_sample = 0.0
        previous_time = -1.0
        while True:
            if cancelled.exists():
                raise ValueError("Анализ остановлен при завершении приложения.")
            ok = capture.grab()
            if not ok:
                break
            timestamp = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
            # Presentation timestamps handle variable-rate recordings. Some decoders return 0.
            if not math.isfinite(timestamp) or timestamp <= previous_time:
                timestamp = max(previous_time + 1 / video["fps"], index / video["fps"])
            previous_time = timestamp
            if timestamp + 1e-6 >= next_sample:
                ok, frame = capture.retrieve()
                if not ok:
                    raise ValueError("Не удалось декодировать кадр.")
                objects, inference_ms = detector.predict(frame)
                output.append(
                    {
                        "time": round(timestamp, 4),
                        "frame_index": index,
                        "objects": objects,
                        "inference_ms": inference_ms,
                    }
                )
                next_sample = (math.floor((timestamp + 1e-6) * sample_fps) + 1) / sample_fps
                if time.monotonic() - last_progress > 1:
                    video["progress"] = min(0.99, index / (video["duration"] * video["fps"]))
                    store.put("videos", video_id, video)
                    last_progress = time.monotonic()
            index += 1
        expected_frames = video.get("frame_count", round(video["duration"] * video["fps"]))
        if not output or index < expected_frames - 1:
            raise ValueError("Видео прочитано не полностью; анализ не будет считаться готовым.")
        effective_fps = (
            (len(output) - 1) / (output[-1]["time"] - output[0]["time"])
            if len(output) > 1
            else min(video["fps"], sample_fps)
        )
        results = {
            "analyzed_at": datetime.now(UTC).isoformat(),
            "frames": output,
            "sample_fps": effective_fps,
            "model": detector.metadata,
            "inference_height": round(
                video["height"] * min(1, 640 / max(video["width"], video["height"]))
            ),
            "seconds": round(time.monotonic() - started, 2),
            "device": "cpu",
            "settings": {"confidence": 0.30, "input_size": 640, "target_fps": sample_fps},
        }
        path = store.root / "results" / f"{video_id}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(results))
        os.replace(temporary, path)
        video.update(
            status="ready",
            progress=1,
            error=None,
            model=results["model"],
            analysis_seconds=results["seconds"],
        )
    except Exception as exc:
        video.update(status="failed", error=str(exc), progress=0)
    finally:
        if capture is not None:
            capture.release()
        cancelled.unlink(missing_ok=True)
        store.put("videos", video_id, video)


def analyze_frame(jpeg: bytes, model_spec: dict) -> dict:
    """Live worker entry point. The API admits only one pending frame."""
    import numpy as np

    frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None or max(frame.shape[:2]) > 1280:
        raise ValueError("Не удалось прочитать кадр камеры размером до 1280 px.")
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    # Detect darkness and nearly uniform covers; not a claim to detect every obstruction.
    obscured = float(gray.mean()) < 18 or float(gray.std()) < 4
    detector = cached_detector(json.dumps(model_spec, sort_keys=True))
    objects, inference_ms = detector.predict(frame)
    height, width = frame.shape[:2]
    return {
        "objects": [] if obscured else objects,
        "camera_health": "obscured" if obscured else "ok",
        "width": width,
        "height": height,
        "inference_height": round(height * min(1, 640 / max(width, height))),
        "model": detector.metadata,
        "inference_ms": inference_ms,
        "settings": {"confidence": 0.30, "input_size": 640, "device": "cpu"},
    }
