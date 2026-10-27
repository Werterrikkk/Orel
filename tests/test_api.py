from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool

import pytest
from fastapi.testclient import TestClient

from orel import app as app_module
from orel.app import create_app


def test_upload_rejects_invalid_media_and_removes_partial_files(tmp_path):
    with TestClient(create_app(tmp_path, enable_worker=False)) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        assert (
            client.post(
                "/api/videos", files={"file": ("broken.mp4", b"not a video", "video/mp4")}
            ).status_code
            == 422
        )
        assert list((tmp_path / "uploads").iterdir()) == []
        assert (
            client.post("/api/videos", files={"file": ("x.txt", b"a", "text/plain")}).status_code
            == 415
        )


def test_config_validation_timezone_and_video_binding(prepared_store):
    with TestClient(create_app(prepared_store.root, enable_worker=False)) as client:
        config = prepared_store.get("configurations", "testvideo")
        config["zone"]["right"] = 0
        assert client.put("/api/videos/testvideo/configuration", json=config).status_code == 422
        config["zone"]["right"] = 1
        config["permit"]["starts_at"] = "2026-10-21T12:00:00"
        assert client.put("/api/videos/testvideo/configuration", json=config).status_code == 422
        config["permit"] = None
        config["video_id"] = "other"
        assert client.put("/api/videos/testvideo/configuration", json=config).status_code == 422


def test_video_ranges_events_and_review_survive_restart(prepared_store):
    with TestClient(create_app(prepared_store.root, enable_worker=False)) as client:
        response = client.get("/api/videos/testvideo/media", headers={"Range": "bytes=0-99"})
        assert response.status_code == 206
        assert len(response.content) == 100
        for position in (0, 0.25, 0.5, 0.75, 1):
            response = client.post(
                "/api/playback",
                json={
                    "session_id": "session-test",
                    "video_id": "testvideo",
                    "position": position,
                    "playing": True,
                },
            )
            assert response.status_code == 200
        event = client.get("/api/events").json()[0]
        assert client.get(event["snapshot_url"]).status_code == 200
        assert client.patch(f"/api/events/{event['id']}", json={"reviewed": True}).json()[
            "reviewed"
        ]
        assert "Наряд закрыт" in client.get("/api/events.csv").text
        assert (
            client.post(
                "/api/playback",
                json={"session_id": "s", "video_id": "testvideo", "position": 99, "playing": True},
            ).status_code
            == 409
        )
    with TestClient(create_app(prepared_store.root, enable_worker=False)) as restarted:
        assert restarted.get("/api/events").json()[0]["reviewed"]


def test_interrupted_analysis_is_reported_as_failed(tmp_path):
    app = create_app(tmp_path, enable_worker=False)
    app.state.store.put("videos", "interrupted", {"id": "interrupted", "status": "processing"})
    with TestClient(app) as client:
        video = client.get("/api/videos/interrupted").json()
        assert video["status"] == "failed"
        assert "перезапущен" in video["error"]


@pytest.mark.parametrize("kind", ["media", "preview", "snapshot"])
def test_missing_media_returns_a_clear_not_found_response(prepared_store, kind):
    if kind == "snapshot":
        prepared_store.put("events", "missing", {"id": "missing"})
        url = "/api/events/missing/snapshot"
    else:
        folder, name = (
            ("uploads", "testvideo.mp4") if kind == "media" else ("previews", "testvideo.jpg")
        )
        (prepared_store.root / folder / name).unlink()
        url = f"/api/videos/testvideo/{kind}"
    with TestClient(create_app(prepared_store.root, enable_worker=False)) as client:
        assert client.get(url).status_code == 404


@pytest.mark.parametrize(
    "content", ['{"frames": []}', "not-json", "[]", '{"frames":[{"time":1},{"time":0}]}']
)
def test_corrupted_results_are_not_served_as_ready(prepared_store, content):
    (prepared_store.root / "results/testvideo.json").write_text(content)
    with TestClient(create_app(prepared_store.root, enable_worker=False)) as client:
        assert client.get("/api/videos/testvideo/detections").status_code == 409
        response = client.post(
            "/api/playback",
            json={
                "video_id": "testvideo",
                "session_id": "corrupt",
                "position": 0,
            },
        )
        assert response.status_code == 409


def test_permit_timestamps_are_stored_in_utc(prepared_store):
    config = prepared_store.get("configurations", "testvideo")
    config["permit"].update(
        starts_at="2026-10-21T12:00:00+03:00", ends_at="2026-10-21T13:00:00+03:00"
    )
    with TestClient(create_app(prepared_store.root, enable_worker=False)) as client:
        result = client.put("/api/videos/testvideo/configuration", json=config)
        assert result.status_code == 200
        assert result.json()["permit"]["starts_at"] == "2026-10-21T09:00:00Z"


@pytest.mark.parametrize("change", [{"box": [0, 0, -1, 1]}, {"confidence": "invalid"}])
def test_corrupted_detection_cannot_crash_the_frontend(prepared_store, change):
    import json

    path = prepared_store.root / "results/testvideo.json"
    data = json.loads(path.read_text())
    data["frames"][0]["objects"][0].update(change)
    path.write_text(json.dumps(data))
    with TestClient(create_app(prepared_store.root, enable_worker=False)) as client:
        assert client.get("/api/videos/testvideo/detections").status_code == 409


def test_csv_escapes_formulas_after_leading_whitespace(prepared_store):
    prepared_store.put(
        "events",
        "csv",
        {
            "created_at": "2026-10-21T10:00:00+00:00",
            "video_name": " \t=1+1",
            "position": 0,
            "zone": "@SUM(1)",
            "permit_number": "-2",
            "reason": "test",
            "reviewed": False,
        },
    )
    with TestClient(create_app(prepared_store.root, enable_worker=False)) as client:
        response = client.get("/api/events.csv")
        assert "' \t=1+1" in response.text
        assert "'@SUM(1)" in response.text


def test_worker_crash_can_be_retried_with_one_new_request(prepared_store, monkeypatch):
    pools = []

    class Pool:
        def __init__(self, **kwargs):
            pools.append(self)
            self.future = Future()

        def submit(self, *args):
            if len(pools) == 1:
                self.future.set_exception(BrokenProcessPool("Simulated worker crash"))
            return self.future

        def shutdown(self, **kwargs):
            self.future.cancel()

    monkeypatch.setattr(app_module, "ProcessPoolExecutor", Pool)
    with TestClient(create_app(prepared_store.root)) as client:
        assert (
            client.post("/api/videos/testvideo/analysis", json={"model": "person"}).status_code
            == 202
        )
        assert client.get("/api/videos/testvideo").json()["status"] == "failed"
        assert (
            client.post("/api/videos/testvideo/analysis", json={"model": "person"}).status_code
            == 202
        )
        assert len(pools) == 2
