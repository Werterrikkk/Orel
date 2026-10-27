import json
from datetime import UTC, datetime, timedelta

import cv2
import numpy as np
import pytest

from orel.storage import Store


@pytest.fixture
def prepared_store(tmp_path):
    """Synthetic media/detections are test fixtures, never exposed as real demo results."""
    store = Store(tmp_path)
    video_id = "testvideo"
    path = tmp_path / "uploads/testvideo.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 240))
    for _ in range(40):
        writer.write(np.full((240, 320, 3), 100, np.uint8))
    writer.release()
    frame = np.full((240, 320, 3), 100, np.uint8)
    cv2.imwrite(str(tmp_path / "previews/testvideo.jpg"), frame)
    store.put(
        "videos",
        video_id,
        {
            "id": video_id,
            "file": path.name,
            "name": "Test fixture.mp4",
            "status": "ready",
            "duration": 4,
            "fps": 10,
            "width": 320,
            "height": 240,
            "model": {"name": "test", "ppe": True},
        },
    )
    now = datetime.now(UTC)
    store.put(
        "configurations",
        video_id,
        {
            "video_id": video_id,
            "zone": {
                "name": "Цех",
                "left": 0,
                "top": 0,
                "right": 1,
                "bottom": 1,
                "require_helmet": False,
                "require_vest": False,
            },
            "permit": {
                "number": "ND-test",
                "starts_at": (now - timedelta(hours=1)).isoformat(),
                "ends_at": (now + timedelta(hours=1)).isoformat(),
                "closed": True,
            },
        },
    )
    frames = [
        {
            "time": round(i / 5, 2),
            "objects": [{"kind": "person", "box": [0.2, 0.1, 0.6, 0.9], "confidence": 0.9}],
        }
        for i in range(20)
    ]
    (tmp_path / "results/testvideo.json").write_text(
        json.dumps(
            {"frames": frames, "sample_fps": 5, "model": {"ppe": True}, "inference_height": 640}
        )
    )
    return store
