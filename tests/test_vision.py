import hashlib
import json
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from orel import detector, vision


@pytest.fixture
def fake_inference(prepared_store, monkeypatch):
    """Only test fixtures replace model outputs; browser smoke tests run the real model."""
    import torch

    empty = SimpleNamespace(xyxyn=torch.empty((0, 4)), conf=torch.empty(0), cls=torch.empty(0))
    model = SimpleNamespace(
        names={0: "person"}, predict=lambda *a, **k: [SimpleNamespace(boxes=empty)]
    )
    monkeypatch.setattr(detector, "configure_ml", lambda: None)
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=lambda *a: model))
    weights = prepared_store.root / "weights.pt"
    weights.write_bytes(b"test-only weights")
    return {"path": str(weights), "ppe": False, "name": "test fixture"}


def test_worker_uses_presentation_timestamps_for_variable_rate_video(
    prepared_store, fake_inference, monkeypatch
):
    timestamps = [0, 100, 200, 300, 650, 750, 900, 1000]

    class Capture:
        index = -1

        def isOpened(self):
            return True

        def grab(self):
            self.index += 1
            return self.index < len(timestamps)

        def get(self, prop):
            return timestamps[self.index]

        def retrieve(self):
            return True, np.zeros((240, 320, 3), dtype=np.uint8)

        def release(self):
            pass

    video = prepared_store.get("videos", "testvideo")
    video.update(frame_count=len(timestamps), duration=1.1)
    prepared_store.put("videos", "testvideo", video)
    monkeypatch.setattr(vision.cv2, "VideoCapture", lambda *a: Capture())
    vision.analyze_video(str(prepared_store.root), "testvideo", fake_inference)
    assert prepared_store.get("videos", "testvideo")["status"] == "ready"
    results = json.loads((prepared_store.root / "results/testvideo.json").read_text())
    assert [f["time"] for f in results["frames"]] == [0, 0.2, 0.65, 0.9, 1.0]
    assert [f["frame_index"] for f in results["frames"]] == [0, 2, 4, 6, 7]


def test_truncated_decode_is_failed_even_when_95_percent_was_read(prepared_store, fake_inference):
    video = prepared_store.get("videos", "testvideo")
    video["frame_count"] = 42  # Fixture contains only 40 decodable frames.
    prepared_store.put("videos", "testvideo", video)
    vision.analyze_video(str(prepared_store.root), "testvideo", fake_inference)
    result = prepared_store.get("videos", "testvideo")
    assert result["status"] == "failed"
    assert "не полностью" in result["error"]


def test_worker_refuses_weights_that_do_not_match_the_evaluation(prepared_store, fake_inference):
    fake_inference["weights_sha256"] = hashlib.sha256(b"other weights").hexdigest()
    vision.analyze_video(str(prepared_store.root), "testvideo", fake_inference)
    result = prepared_store.get("videos", "testvideo")
    assert result["status"] == "failed"
    assert "модели повреждён" in result["error"]


def test_worker_stops_on_server_shutdown(prepared_store, fake_inference):
    (prepared_store.root / "results/testvideo.cancel").touch()
    vision.analyze_video(str(prepared_store.root), "testvideo", fake_inference)
    result = prepared_store.get("videos", "testvideo")
    assert result["status"] == "failed"
    assert "остановлен" in result["error"]
