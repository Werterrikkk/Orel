import threading
from concurrent.futures import Future, ThreadPoolExecutor

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from orel import app as app_module
from orel.app import create_app


@pytest.fixture
def camera_app(prepared_store, monkeypatch):
    spec = {"available": True, "ppe": True, "path": "fixture.pt", "weights_sha256": "fixture"}
    monkeypatch.setattr(app_module, "model_catalog", lambda: {"ppe": spec, "person": spec})
    app = create_app(prepared_store.root)
    return app, spec


def jpeg():
    return cv2.imencode(".jpg", np.full((240, 320, 3), 100, np.uint8))[1].tobytes()


def test_camera_session_requires_trained_weights_and_idle_recording_worker(camera_app):
    app, spec = camera_app
    with TestClient(app) as client:
        spec["available"] = False
        assert client.post("/api/camera/sessions").status_code == 409
        spec["available"] = True
        video = app.state.store.get("videos", "testvideo")
        video["status"] = "processing"
        app.state.store.put("videos", "testvideo", video)
        assert client.post("/api/camera/sessions").status_code == 409


def test_camera_settings_persist_and_reject_unrelated_fields(camera_app):
    app, _ = camera_app
    with TestClient(app) as client:
        assert client.get("/api/camera/configuration").json() == {
            "require_helmet": True,
            "require_vest": False,
            "danger_zone": None,
        }
        assert (
            client.put(
                "/api/camera/configuration", json={"require_helmet": True, "require_vest": True}
            ).status_code
            == 200
        )
        assert (
            client.put("/api/camera/configuration", json={"fake_detections": []}).status_code == 422
        )
    with TestClient(create_app(app.state.store.root)) as client:
        assert client.get("/api/camera/configuration").json()["require_vest"]


def test_camera_rejects_invalid_and_oversized_frames_without_submitting_work(
    camera_app, monkeypatch
):
    app, _ = camera_app
    with TestClient(app) as client:
        session = client.post("/api/camera/sessions").json()["id"]
        path = f"/api/camera/sessions/{session}/frames?sequence=0"
        assert (
            client.post(path, files={"file": ("frame.jpg", b"not-jpeg", "image/jpeg")}).status_code
            == 415
        )
        monkeypatch.setattr(app_module, "MAX_CAMERA_FRAME", 10)
        assert (
            client.post(path, files={"file": ("frame.jpg", jpeg(), "image/jpeg")}).status_code
            == 413
        )
        assert client.delete(f"/api/camera/sessions/{session}").status_code == 204


def test_only_one_frame_is_admitted_and_stopped_sessions_cannot_create_results(
    camera_app, monkeypatch
):
    app, _ = camera_app
    pending = Future()
    submitted = threading.Event()

    class Pool:
        def __init__(self, **kwargs):
            pass

        def submit(self, *args):
            submitted.set()
            return pending

        def shutdown(self, **kwargs):
            pending.cancel()

    monkeypatch.setattr(app_module, "ProcessPoolExecutor", Pool)
    data = {
        "objects": [],
        "inference_height": 240,
        "inference_ms": 10,
        "model": {"ppe": True, "weights_sha256": "fixture"},
        "settings": {},
    }
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as requests:
        session = client.post("/api/camera/sessions").json()["id"]
        base = f"/api/camera/sessions/{session}"
        first = requests.submit(
            client.post,
            base + "/frames?sequence=0",
            files={"file": ("frame.jpg", jpeg(), "image/jpeg")},
        )
        try:
            assert submitted.wait(timeout=5)
            second = client.post(
                base + "/frames?sequence=1", files={"file": ("frame.jpg", jpeg(), "image/jpeg")}
            )
            assert second.status_code == 429
            assert (
                client.post("/api/videos/testvideo/analysis", json={"model": "person"}).status_code
                == 409
            )
            assert client.delete(base).status_code == 204
        finally:
            pending.set_result(data)
        assert first.result(timeout=5).status_code == 409
        assert client.get("/api/events").json() == []


def test_zone_is_validated_persisted_and_source_status_does_not_claim_rubetek_support(camera_app):
    app, _ = camera_app
    zone = {"name": "Проход", "left": 0.2, "top": 0.3, "right": 0.8, "bottom": 0.9}
    with TestClient(app) as client:
        assert (
            client.put("/api/camera/configuration", json={"danger_zone": zone}).status_code == 200
        )
        assert client.get("/api/camera/configuration").json()["danger_zone"] == {
            **zone,
            "points": None,
        }
        assert (
            client.put(
                "/api/camera/configuration", json={"danger_zone": {**zone, "right": 0.1}}
            ).status_code
            == 422
        )
        sources = client.get("/api/sources").json()
        assert sources[0]["available"] is True
        assert sources[1]["id"] == "rubetek"
        assert sources[1]["available"] is False
