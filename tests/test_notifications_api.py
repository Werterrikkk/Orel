import json
import threading
import time
from concurrent.futures import Future
from copy import deepcopy

import cv2
import numpy as np
from fastapi.testclient import TestClient

from orel import app as app_module
from orel.app import create_app
from tests.test_notifications import TOKEN, Client


def test_connection_configuration_and_test_message_do_not_expose_token(prepared_store):
    transport = Client()
    app = create_app(
        prepared_store.root, enable_worker=False, telegram_client_factory=lambda _: transport
    )
    with TestClient(app) as client:
        assert client.get("/api/telegram").json()["configured"] is False
        assert client.post("/api/telegram/test").status_code == 400
        invalid = client.post("/api/telegram/bot", json={"token": TOKEN, "unexpected": TOKEN})
        assert invalid.status_code == 422 and TOKEN not in invalid.text
        connected = client.post("/api/telegram/bot", json={"token": TOKEN})
        assert connected.status_code == 200 and TOKEN not in connected.text
        assert client.post("/api/telegram/chats").json()[0]["id"] == "42"
        assert (
            client.put("/api/telegram", json={"enabled": True, "chat_id": "42"}).status_code == 200
        )
        assert client.post("/api/telegram/test").json()["last_test_at"]
        assert (
            client.put("/api/telegram", json={"enabled": False, "chat_id": "42"}).json()["enabled"]
            is False
        )
        assert len([call for call in transport.calls if call[0] == "sendMessage"]) == 1
        assert TOKEN not in json.dumps(app.state.store.list("configurations"))


def test_confirmed_camera_event_enqueues_while_network_delivery_never_blocks_capture(
    prepared_store, monkeypatch
):
    entered, release = threading.Event(), threading.Event()

    class SlowClient(Client):
        def call(self, method, values, photo=None):
            if method == "sendPhoto":
                entered.set()
                release.wait(5)
            return super().call(method, values, photo)

    transport = SlowClient()
    spec = {"available": True, "ppe": True, "path": "fixture.pt", "weights_sha256": "fixture"}
    monkeypatch.setattr(app_module, "model_catalog", lambda: {"ppe": spec, "person": spec})
    prediction = {
        "objects": [{"kind": "person", "box": [0.2, 0.1, 0.6, 0.9], "confidence": 0.9}],
        "inference_height": 480,
        "inference_ms": 10,
        "model": {"ppe": True, "weights_sha256": "fixture"},
        "settings": {},
    }

    class Pool:
        def __init__(self, **kwargs):
            pass

        def submit(self, *args):
            future = Future()
            future.set_result(deepcopy(prediction))
            return future

        def shutdown(self, **kwargs):
            pass

    monkeypatch.setattr(app_module, "ProcessPoolExecutor", Pool)
    app = create_app(prepared_store.root, telegram_client_factory=lambda _: transport)
    jpeg = cv2.imencode(".jpg", np.full((240, 320, 3), 100, np.uint8))[1].tobytes()
    with TestClient(app) as client:
        client.post("/api/telegram/bot", json={"token": TOKEN})
        client.put("/api/telegram", json={"enabled": True, "chat_id": "42"})
        session = client.post("/api/camera/sessions").json()["id"]

        def frame(sequence):
            return client.post(
                f"/api/camera/sessions/{session}/frames?sequence={sequence}",
                files={"file": ("frame.jpg", jpeg, "image/jpeg")},
            )

        try:
            assert frame(0).json()["new_events"] == []
            assert client.get("/api/telegram").json()["pending"] == 0
            for sequence in range(1, 8):
                time.sleep(0.35)
                assert frame(sequence).status_code == 200
            assert entered.wait(2)
            before = time.monotonic()
            assert frame(8).status_code == 200
            assert time.monotonic() - before < 0.5
            assert client.get("/api/telegram").json()["pending"] == 1
        finally:
            release.set()
            client.delete(f"/api/camera/sessions/{session}")
    jobs = app.state.store.list("notifications")
    assert len(jobs) == 1 and jobs[0]["status"] == "sent"
    assert [call[2] for call in transport.calls if call[0] == "sendPhoto"] == [jpeg]
